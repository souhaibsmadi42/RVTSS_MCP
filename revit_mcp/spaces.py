# -*- coding: UTF-8 -*-
"""Rooms, MEP spaces and areas (RVTSS v2.2).

Routes:
    POST /rooms/list/      rooms / spaces / areas with area, perimeter, volume, level, phase, status
    POST /rooms/details/   boundaries, doors/windows (From/To room), wall/floor/ceiling finishes, contents
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, bic_from_category
from .pure import spaces as SP
from .pure import units as U
from .pure import filters as F
from .utils import normalize_string

logger = logging.getLogger(__name__)

KIND_CATEGORY = {"room": "OST_Rooms", "space": "OST_MEPSpaces", "area": "OST_Areas"}


def _param_text(e, bip_name):
    try:
        p = e.get_Parameter(getattr(DB.BuiltInParameter, bip_name))
        if p is None:
            return None
        return normalize_string(p.AsString() or p.AsValueString() or "") or None
    except Exception:
        return None


def _phase_of(doc, e):
    for bip in ("ROOM_PHASE", "PHASE_CREATED"):
        try:
            p = e.get_Parameter(getattr(DB.BuiltInParameter, bip))
            if p is not None and is_valid_id(p.AsElementId()):
                return doc.GetElement(p.AsElementId())
        except Exception:
            continue
    return None


def _warning_kinds(doc):
    """{element id: 'not_enclosed' | 'redundant'} from the model warnings (English texts)."""
    kinds = {}
    try:
        for w in doc.GetWarnings():
            kind = SP.classify_warning(normalize_string(w.GetDescriptionText()))
            if kind:
                for i in w.GetFailingElements():
                    kinds[id_int(i)] = kind
    except Exception:
        pass
    return kinds


def _spatial_elements(doc, kind):
    bic = getattr(DB.BuiltInCategory, KIND_CATEGORY[kind])
    return list(DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType())


def _describe(doc, e, kind, unit, area_unit, warn_kinds):
    area = getattr(e, "Area", 0.0) or 0.0
    placed = e.Location is not None
    level = None
    try:
        level = normalize_string(e.Level.Name) if e.Level is not None else None
    except Exception:
        pass
    phase = _phase_of(doc, e)
    out = {"id": id_int(e), "number": _param_text(e, "ROOM_NUMBER"), "name": _param_text(e, "ROOM_NAME"),
           "level": level, "phase": normalize_string(phase.Name) if phase is not None else None,
           "area": U.from_internal(area, area_unit, 3),
           "status": SP.spatial_status(placed, area, warn_kinds.get(id_int(e)))}
    try:
        out["perimeter"] = U.from_internal(e.Perimeter, unit, 1)
    except Exception:
        pass
    if kind in ("room", "space"):
        try:
            out["volume"] = U.from_internal(e.Volume, U.length_unit_for("volume", area_unit), 3)
        except Exception:
            pass
        try:
            out["unbounded_height"] = U.from_internal(e.UnboundedHeight, unit, 1)
        except Exception:
            pass
        out["department"] = _param_text(e, "ROOM_DEPARTMENT")
    if kind == "area":
        try:
            out["area_scheme"] = normalize_string(e.AreaScheme.Name)
        except Exception:
            pass
    if kind == "space":
        try:
            if e.Room is not None:
                out["room_id"] = id_int(e.Room)
        except Exception:
            pass
    return out


def list_spaces(ctx):
    doc = ctx.doc
    core.require_project(doc)
    kind = ctx.get("kind", "room")
    if kind not in KIND_CATEGORY:
        raise RvtssError("kind must be room, space or area")
    unit, area_unit = ctx.unit, ctx.get("area_unit") or "m2"
    level = core.find_level(doc, ctx.get("level")) if ctx.get("level") else None
    phase_name = (ctx.get("phase") or "").lower()
    statuses = set(ctx.list("status"))
    contains = (ctx.get("contains") or "").lower()
    warn_kinds = _warning_kinds(doc)
    items = []
    for e in _spatial_elements(doc, kind):
        if level is not None:
            try:
                if e.LevelId != level.Id:
                    continue
            except Exception:
                continue
        d = _describe(doc, e, kind, unit, area_unit, warn_kinds)
        if phase_name and (d.get("phase") or "").lower() != phase_name:
            continue
        if statuses and d["status"] not in statuses:
            continue
        if contains and contains not in u"{} {}".format(d.get("number") or "", d.get("name") or "").lower():
            continue
        items.append(d)
    items.sort(key=lambda d: (d.get("level") or "", d.get("number") or "", d.get("name") or ""))
    page, meta = F.paginate(items, ctx.int("offset", 0), ctx.int("limit", 200, 1, core.MAX_LIMIT))
    placed = [d for d in items if d["status"] == "placed"]
    return {"kind": kind, "count": len(items), "unit": unit, "area_unit": area_unit,
            "total_area": round(sum(d["area"] or 0 for d in placed), 3),
            "by_status": dict((k, v["count"]) for k, v in SP.summarize_by(items, "status").items()),
            "by_level": SP.summarize_by(placed, "level"),
            "by_department": SP.summarize_by(placed, "department") if kind != "area" else None,
            "pagination": meta, "items": page}


# ------------------------------------------------------------------ details
def _segments(doc, e, unit, location="finish"):
    opts = DB.SpatialElementBoundaryOptions()
    try:
        opts.SpatialElementBoundaryLocation = getattr(
            DB.SpatialElementBoundaryLocation, {"finish": "Finish", "center": "Center", "core_center": "CoreCenter",
                                               "core_boundary": "CoreBoundary"}.get(location, "Finish"))
    except Exception:
        pass
    loops = []
    try:
        raw = e.GetBoundarySegments(opts)
    except Exception:
        raw = None
    for loop in raw or []:
        segs = []
        for s in loop:
            c = s.GetCurve()
            seg = {"start": core.xyz_list(c.GetEndPoint(0), unit), "end": core.xyz_list(c.GetEndPoint(1), unit),
                   "length": U.from_internal(c.Length, unit, 1), "_length_internal": c.Length}
            try:
                eid = s.ElementId
            except AttributeError:
                eid = s.Element.Id if s.Element is not None else DB.ElementId.InvalidElementId
            if is_valid_id(eid):
                seg["element_id"] = id_int(eid)
                be = doc.GetElement(eid)
                if be is not None:
                    seg["element_category"] = normalize_string(be.Category.Name) if be.Category else None
            try:
                if is_valid_id(s.LinkElementId):
                    seg["link_element_id"] = id_int(s.LinkElementId)
            except Exception:
                pass
            segs.append(seg)
        loops.append(segs)
    return loops


def _room_of(fi, getter, phase):
    try:
        return getattr(fi, "get_" + getter)(phase) if phase is not None else getattr(fi, getter)
    except Exception:
        try:
            return getattr(fi, getter)
        except Exception:
            return None


def _opening_size(doc, fi):
    """(width, height) in internal feet from the instance or its type, or (None, None)."""
    vals = []
    for names in (("DOOR_WIDTH", "WINDOW_WIDTH", "FAMILY_WIDTH_PARAM", "FURNITURE_WIDTH"),
                  ("DOOR_HEIGHT", "WINDOW_HEIGHT", "FAMILY_HEIGHT_PARAM", "GENERIC_HEIGHT")):
        v = None
        for owner in (fi, doc.GetElement(fi.GetTypeId())):
            if owner is None:
                continue
            for n in names:
                try:
                    p = owner.get_Parameter(getattr(DB.BuiltInParameter, n))
                    if p is not None and p.HasValue and p.AsDouble() > 0:
                        v = p.AsDouble()
                        break
                except Exception:
                    continue
            if v is not None:
                break
        vals.append(v)
    return vals[0], vals[1]


def _openings(doc, room, phase, unit):
    out = []
    for bic in (DB.BuiltInCategory.OST_Doors, DB.BuiltInCategory.OST_Windows):
        for fi in DB.FilteredElementCollector(doc).OfCategory(bic).OfClass(DB.FamilyInstance):
            fr, to = _room_of(fi, "FromRoom", phase), _room_of(fi, "ToRoom", phase)
            side = None
            if fr is not None and fr.Id == room.Id:
                side = "from"
            elif to is not None and to.Id == room.Id:
                side = "to"
            if side is None:
                continue
            w, h = _opening_size(doc, fi)
            d = core.element_brief(doc, fi)
            d.update({"side": side, "host_id": id_int(fi.Host) if fi.Host is not None else None,
                      "width": U.from_internal(w, unit, 1) if w else None,
                      "height": U.from_internal(h, unit, 1) if h else None,
                      "_w": w, "_h": h,
                      "other_room_id": id_int((to if side == "from" else fr)) if (to if side == "from" else fr) else None})
            out.append(d)
    return out


def _contents(doc, room, phase, categories):
    found = []
    col = DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance)
    cat_ids = set(id_int(core.resolve_category(doc, c).Id) for c in categories) if categories else None
    for fi in col:
        if fi.Category is None or (cat_ids is not None and id_int(fi.Category.Id) not in cat_ids):
            continue
        if bic_from_category(fi.Category) in ("OST_Doors", "OST_Windows"):
            continue
        r = _room_of(fi, "Room", phase)
        if r is None:
            try:
                pt = core.element_point(fi)
                if pt is not None and room.IsPointInRoom(DB.XYZ(pt.X, pt.Y, pt.Z + 0.3)):
                    r = room
            except Exception:
                r = None
        if r is not None and r.Id == room.Id:
            found.append(core.element_brief(doc, fi))
    return found


def space_details(ctx):
    doc = ctx.doc
    core.require_project(doc)
    ids = ctx.list("element_ids")
    if not ids:
        raise RvtssError("'element_ids' (room / space / area ids) is required",
                         hint="Get ids with list_rooms.")
    if len(ids) > 50:
        raise RvtssError("At most 50 rooms per call", hint="Page through list_rooms results.")
    unit, area_unit = ctx.unit, ctx.get("area_unit") or "m2"
    include = set(ctx.list("include") or ["boundaries", "openings", "finishes"])
    warn_kinds = _warning_kinds(doc)
    results = []
    for e in core.get_elements(doc, ids, "Room"):
        if not isinstance(e, DB.SpatialElement):
            raise RvtssError("Element {} is not a room, space or area".format(id_int(e)))
        bic = bic_from_category(e.Category)
        kind = {"OST_MEPSpaces": "space", "OST_Areas": "area"}.get(bic or "", "room")
        d = _describe(doc, e, kind, unit, area_unit, warn_kinds)
        phase = _phase_of(doc, e)
        loops = _segments(doc, e, unit, ctx.get("boundary_location", "finish")) \
            if include & set(["boundaries", "finishes"]) else []
        openings = _openings(doc, e, phase, unit) if kind != "area" and include & set(["openings", "finishes"]) else []
        if "finishes" in include and kind != "area":
            height = getattr(e, "UnboundedHeight", 0.0) or 0.0
            by_host = {}
            for o in openings:
                if o.get("host_id") and o.get("_w") and o.get("_h"):
                    by_host.setdefault(o["host_id"], []).append((o["_w"], o["_h"]))
            walls, total_net = [], 0.0
            for loop in loops:
                for s in loop:
                    if s.get("element_category") is None:
                        continue
                    holes = by_host.pop(s.get("element_id"), []) if s.get("element_id") else []
                    gross, hole, net = SP.wall_finish(s["_length_internal"], height, holes)
                    total_net += net
                    walls.append({"element_id": s.get("element_id"), "category": s.get("element_category"),
                                  "length": s["length"], "gross_area": U.from_internal(gross, area_unit, 3),
                                  "openings_area": U.from_internal(hole, area_unit, 3),
                                  "net_area": U.from_internal(net, area_unit, 3)})
            d["finishes"] = {"floor_area": d.get("area"), "ceiling_area": d.get("area"),
                             "wall_net_area": U.from_internal(total_net, area_unit, 3),
                             "height_used": U.from_internal(height, unit, 1), "walls": walls,
                             "method": "estimate: boundary length x unbounded height minus door/window "
                                       "width x height; sloped ceilings, columns and reveals are ignored"}
        if "boundaries" in include:
            d["boundaries"] = [[dict((k, v) for k, v in s.items() if not k.startswith("_")) for s in loop]
                               for loop in loops]
        if "openings" in include and kind != "area":
            d["openings"] = [dict((k, v) for k, v in o.items() if not k.startswith("_")) for o in openings]
        if "contents" in include and kind != "area":
            d["contents"] = _contents(doc, e, phase, ctx.list("content_categories"))[:500]
        results.append(d)
    return {"unit": unit, "area_unit": area_unit, "count": len(results), "items": results}


def register_spaces_routes(api):
    @api.route("/rooms/list/", methods=["POST"])
    def rooms_list_route(doc, request):
        return handle(doc, request, list_spaces)

    @api.route("/rooms/details/", methods=["POST"])
    def rooms_details_route(doc, request):
        return handle(doc, request, space_details)

    logger.info("RVTSS spaces routes registered")

