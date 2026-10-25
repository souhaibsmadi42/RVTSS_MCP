# -*- coding: UTF-8 -*-
"""Coordinates and spatial queries (RVTSS v2.2). Read-only.

Routes:
    POST /coordinates/       internal origin, project base point, survey point, true north, project locations,
                             link transforms; optional internal -> shared conversion of points
    POST /spatial/query/     distance between elements, elements in a box / near a point, ray cast in a 3D view
"""
import math
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int
from .pure import units as U
from .utils import normalize_string

logger = logging.getLogger(__name__)


class _SharedConverter(object):
    """Internal -> shared coordinates through the active ProjectLocation transform.

    ProjectLocation.GetProjectPosition is only documented for the origin, so points use
    GetTotalTransform(). Its direction is checked against a base point whose shared position Revit
    reports itself (survey point, then project base point); `verified` says whether that check ran.
    """

    def __init__(self, doc, location):
        self.method = None
        self.verified = False
        tr = location.GetTotalTransform()
        candidates = [("transform_inverse", tr.Inverse), ("transform", tr)]
        self.transform = candidates[0][1]
        self.method = candidates[0][0]
        for getter in (DB.BasePoint.GetSurveyPoint, DB.BasePoint.GetProjectBasePoint):
            try:
                bp = getter(doc)
                internal, shared = bp.Position, bp.SharedPosition
            except Exception:
                continue
            for name, t in candidates:
                if t.OfPoint(internal).DistanceTo(shared) < 1e-4:
                    self.transform, self.method, self.verified = t, name, True
                    return
            return

    def convert(self, p, unit):
        q = self.transform.OfPoint(p)
        return {"east_west": U.from_internal(q.X, unit, 1), "north_south": U.from_internal(q.Y, unit, 1),
                "elevation": U.from_internal(q.Z, unit, 1)}


def _base_point(getter, conv, unit):
    try:
        bp = getter()
    except Exception:
        return None
    if bp is None:
        return None
    out = {"id": id_int(bp)}
    try:
        out["internal"] = core.xyz_list(bp.Position, unit)
        out["shared"] = core.xyz_list(bp.SharedPosition, unit)
    except Exception:
        try:
            out["shared"] = conv.convert(bp.Position, unit)
        except Exception:
            pass
    try:
        out["pinned"] = bp.Pinned
        out["clipped"] = bp.Clipped if hasattr(bp, "Clipped") else None
    except Exception:
        pass
    return out


def coordinates(ctx):
    doc = ctx.doc
    core.require_project(doc)
    unit = ctx.unit
    loc = doc.ActiveProjectLocation
    conv = _SharedConverter(doc, loc)
    out = {"unit": unit, "active_location": normalize_string(loc.Name),
           "shared_conversion": {"method": conv.method, "verified_against_base_point": conv.verified}}
    try:
        origin_pos = loc.GetProjectPosition(DB.XYZ.Zero)
        out["angle_to_true_north_deg"] = round(math.degrees(origin_pos.Angle), 6)
        out["internal_origin_in_shared"] = conv.convert(DB.XYZ.Zero, unit)
    except Exception as e:
        out["warnings"] = ["Project position unavailable: {}".format(e)]
    out["project_base_point"] = _base_point(lambda: DB.BasePoint.GetProjectBasePoint(doc), conv, unit)
    out["survey_point"] = _base_point(lambda: DB.BasePoint.GetSurveyPoint(doc), conv, unit)
    try:
        out["project_locations"] = [normalize_string(l.Name) for l in doc.ProjectLocations]
    except Exception:
        pass
    try:
        site = doc.SiteLocation
        out["site"] = {"place": normalize_string(site.PlaceName), "latitude_deg": round(math.degrees(site.Latitude), 6),
                       "longitude_deg": round(math.degrees(site.Longitude), 6)}
    except Exception:
        pass
    links = []
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        d = {"instance_id": id_int(inst), "name": normalize_string(inst.Name)}
        try:
            tr = inst.GetTotalTransform()
            d["origin_internal"] = core.xyz_list(tr.Origin, unit)
            d["rotation_deg"] = round(math.degrees(math.atan2(tr.BasisX.Y, tr.BasisX.X)), 6)
            d["origin_shared"] = conv.convert(tr.Origin, unit)
            d["is_identity"] = tr.IsIdentity
        except Exception:
            pass
        try:
            p = inst.get_Parameter(DB.BuiltInParameter.RVT_LINK_INSTANCE_POSITIONING) if hasattr(
                DB.BuiltInParameter, "RVT_LINK_INSTANCE_POSITIONING") else None
            if p is not None:
                d["positioning"] = normalize_string(p.AsValueString() or "")
        except Exception:
            pass
        links.append(d)
    out["links"] = links
    pts = ctx.list("points")
    if pts:
        converted = []
        for p in pts[:200]:
            x, y, z = U.point_from(p, unit)
            converted.append({"internal": list(p), "shared": conv.convert(DB.XYZ(x, y, z), unit)})
        out["converted_points"] = converted
    return out


# ------------------------------------------------------------------ spatial query
def _bbox_gap(a, b):
    """Gap between two bounding boxes (0 when they overlap)."""
    if a is None or b is None:
        return None
    dx = max(0.0, max(a.Min.X, b.Min.X) - min(a.Max.X, b.Max.X))
    dy = max(0.0, max(a.Min.Y, b.Min.Y) - min(a.Max.Y, b.Max.Y))
    dz = max(0.0, max(a.Min.Z, b.Min.Z) - min(a.Max.Z, b.Max.Z))
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _cat_filter(doc, cats):
    if not cats:
        return None
    from System.Collections.Generic import List

    lst = List[DB.ElementId]()
    for c in cats:
        lst.Add(core.resolve_category(doc, c).Id)
    return DB.ElementMulticategoryFilter(lst)


def _box_query(doc, lo, hi, cats, limit, exclude=()):
    col = DB.FilteredElementCollector(doc).WhereElementIsNotElementType() \
        .WherePasses(DB.BoundingBoxIntersectsFilter(DB.Outline(lo, hi)))
    f = _cat_filter(doc, cats)
    if f is not None:
        col = col.WherePasses(f)
    out = []
    for e in col:
        if id_int(e) in exclude or e.Category is None or e.Category.CategoryType != DB.CategoryType.Model:
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


def _view3d(doc, name):
    if name:
        v = core.find_view(doc, name)
        if not isinstance(v, DB.View3D) or v.IsTemplate:
            raise RvtssError("ray casting needs a 3D view (not a template)")
        return v
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate and not v.IsPerspective:
            return v
    raise RvtssError("No 3D view in the model", hint="Create one with create_view(kind='three_d').")


def spatial_query(ctx):
    doc = ctx.doc
    unit = ctx.unit
    mode = ctx.require("mode")
    limit = ctx.int("limit", 100, 1, 1000)
    cats = ctx.list("categories")
    if mode == "distance":
        a = core.get_element(doc, ctx.require("element_a"))
        b = core.get_element(doc, ctx.require("element_b"))
        pa, pb = core.element_point(a), core.element_point(b)
        out = {"element_a": core.element_brief(doc, a), "element_b": core.element_brief(doc, b), "unit": unit,
               "center_distance": U.from_internal(pa.DistanceTo(pb), unit, 1) if pa is not None and pb is not None
               else None,
               "bbox_gap": U.from_internal(_bbox_gap(a.get_BoundingBox(None), b.get_BoundingBox(None)), unit, 1)}
        if ctx.bool("exact", True):
            from .qc import _solids, _min_distance

            sa, sb = _solids(a), _solids(b)
            if sa and sb:
                d, p1, p2 = _min_distance(sa, sb, ctx.int("samples", 4, 2, 10))
                if d is not None:
                    out["surface_distance"] = U.from_internal(d, unit, 1)
                    out["closest_points"] = [core.xyz_list(p1, unit), core.xyz_list(p2, unit)]
                    out["surface_distance_note"] = "sampled over faces and edges: never below the true distance"
            else:
                out["surface_distance_note"] = "no solid geometry on one of the elements"
        return out
    if mode == "in_box":
        a = U.point_from(ctx.require("min"), unit)
        b = U.point_from(ctx.require("max"), unit)
        lo = DB.XYZ(min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]))
        hi = DB.XYZ(max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))
        found = _box_query(doc, lo, hi, cats, limit)
        return {"mode": mode, "count": len(found), "truncated": len(found) >= limit,
                "elements": [core.element_brief(doc, e) for e in found]}
    if mode == "near_point":
        c = DB.XYZ(*U.point_from(ctx.require("point"), unit))
        r = U.to_internal(ctx.float("radius", 1000.0), unit)
        found = _box_query(doc, c - DB.XYZ(r, r, r), c + DB.XYZ(r, r, r), cats, 5000)
        rows = []
        for e in found:
            p = core.element_point(e)
            d = p.DistanceTo(c) if p is not None else None
            if d is not None and d <= r:
                b = core.element_brief(doc, e)
                b["distance"] = U.from_internal(d, unit, 1)
                rows.append(b)
        rows.sort(key=lambda b: b["distance"])
        return {"mode": mode, "count": len(rows), "unit": unit, "elements": rows[:limit],
                "note": "distance from each element's location point / curve midpoint / box centre"}
    if mode == "raycast":
        origin = DB.XYZ(*U.point_from(ctx.require("point"), unit))
        dx, dy, dz = [float(v) for v in (ctx.list("direction") or [0, 0, -1])]
        direction = DB.XYZ(dx, dy, dz)
        if direction.GetLength() < 1e-9:
            raise RvtssError("direction must not be zero")
        view = _view3d(doc, ctx.get("view"))
        f = _cat_filter(doc, cats) or DB.ElementIsElementTypeFilter(True)
        ri = DB.ReferenceIntersector(f, DB.FindReferenceTarget.Element, view)
        ri.FindReferencesInRevitLinks = ctx.bool("include_links", False)
        hits = []
        seen = set()
        for ctxref in sorted(ri.Find(origin, direction.Normalize()), key=lambda r: r.Proximity):
            ref = ctxref.GetReference()
            key = (id_int(ref.ElementId), id_int(ref.LinkedElementId) if ref.LinkedElementId else None)
            if key in seen:
                continue
            seen.add(key)
            e = doc.GetElement(ref.ElementId)
            h = core.element_brief(doc, e) if e is not None else {"id": key[0]}
            h["distance"] = U.from_internal(ctxref.Proximity, unit, 1)
            try:
                h["hit_point"] = core.xyz_list(ref.GlobalPoint, unit)
            except Exception:
                pass
            if key[1] is not None and key[1] > 0:
                h["linked_element_id"] = key[1]
            hits.append(h)
            if len(hits) >= limit:
                break
        return {"mode": mode, "view": normalize_string(view.Name), "unit": unit, "hits": hits,
                "nearest": hits[0] if hits else None,
                "note": "Only elements visible in the 3D view are hit (section box and hidden categories apply)."}
    raise RvtssError("mode must be distance, in_box, near_point or raycast")


def register_spatial_routes(api):
    @api.route("/coordinates/", methods=["POST"])
    def coordinates_route(doc, request):
        return handle(doc, request, coordinates)

    @api.route("/spatial/query/", methods=["POST"])
    def spatial_query_route(doc, request):
        return handle(doc, request, spatial_query)

    logger.info("RVTSS spatial routes registered")
