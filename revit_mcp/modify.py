# -*- coding: UTF-8 -*-
"""Modify panel operations (RVTSS v2.4).

Routes:
    POST /modify/elements/   operation = align | offset | trim_extend | split | scale | flip |
                             cut | uncut | paint | remove_paint | create_parts | divide_parts

Each call is one transaction (one undo step) with dry_run support. Move / copy / rotate / mirror /
array / pin / join stay in /transform_elements/.

Not possible through the Revit API (left to the user): attaching wall tops / bases to roofs and
floors, editing a wall profile sketch, Split Face, wall join display, linework.
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, make_id, text_type
from .pure import units as U
from .utils import normalize_string

logger = logging.getLogger(__name__)

OPERATIONS = ("align", "offset", "trim_extend", "split", "scale", "flip", "cut", "uncut", "paint",
              "remove_paint", "create_parts", "divide_parts")
_AXES = {"x": 0, "y": 1, "z": 2}
_EPS = 1e-6


# ------------------------------------------------------------------------ helpers
def _xyz(ctx, value, what):
    if value is None:
        raise RvtssError("'{}' is required ([x, y] or [x, y, z] in {})".format(what, ctx.unit))
    x, y, z = U.point_from(value, ctx.unit)
    return DB.XYZ(x, y, z)


def _coord(p, axis):
    return (p.X, p.Y, p.Z)[_AXES[axis]]


def _axis_vector(axis, value):
    return DB.XYZ(value if axis == "x" else 0.0, value if axis == "y" else 0.0, value if axis == "z" else 0.0)


def _location_curve(e, what="operation"):
    loc = e.Location
    if not isinstance(loc, DB.LocationCurve):
        raise RvtssError("Element {} has no location line; {} works on walls, beams, ducts, pipes and "
                         "lines".format(id_int(e), what))
    return loc


def _straight(e, what):
    loc = _location_curve(e, what)
    c = loc.Curve
    if not isinstance(c, DB.Line) or not c.IsBound:
        raise RvtssError("Element {} is not straight; {} needs straight elements".format(id_int(e), what))
    return loc, c


def _unpin_check(ctx, elements):
    pinned = [id_int(e) for e in elements if getattr(e, "Pinned", False)]
    if pinned and not ctx.bool("unpin", False):
        raise RvtssError("Pinned elements cannot be modified: {}".format(pinned[:20]), status=409,
                         hint="Pass unpin=true to unpin them first (they stay unpinned).")


def _unpin(elements):
    for e in elements:
        if getattr(e, "Pinned", False):
            e.Pinned = False


def _run(ctx, name, elements, one, extra=None, atomic_default=True):
    """Apply one(element) to every element in one transaction, behind the confirm gate."""
    doc = ctx.doc
    preview = core.confirm_gate(ctx, len(elements), "modify_elements " + name)
    dry = preview or ctx.dry_run

    def run():
        res = core.batch(doc, elements, one, ctx.bool("atomic", atomic_default))
        doc.Regenerate()
        return res

    results, failures = core.run_transaction(doc, "Modify " + name, run, dry_run=dry)
    out = {"operation": name, "count": len(elements), "succeeded": len([r for r in results if r.get("ok")]),
           "results": results[:200], "results_truncated": len(results) > 200, "unit": ctx.unit}
    if extra:
        out.update(extra)
    return core.preview_status(core.commit_result(out, failures, dry), preview)


# -------------------------------------------------------------------------- align
def _align(ctx, elements):
    axis = text_type(ctx.get("axis", "x")).lower()
    if axis not in _AXES:
        raise RvtssError("axis must be x, y or z")
    if ctx.get("reference_id") is not None:
        ref = core.get_element(ctx.doc, ctx.get("reference_id"), "Reference element")
        p = core.element_point(ref)
        if p is None:
            raise RvtssError("Reference element {} has no location".format(id_int(ref)))
        target = _coord(p, axis)
    elif ctx.get("coordinate") is not None:
        target = U.to_internal(ctx.float("coordinate"), ctx.unit)
    else:
        raise RvtssError("align needs 'reference_id' (align to that element) or 'coordinate' (a value on the axis)")
    _unpin_check(ctx, elements)

    def one(e):
        p = core.element_point(e)
        if p is None:
            raise RvtssError("Element {} has no location to align".format(id_int(e)))
        delta = target - _coord(p, axis)
        if getattr(e, "Pinned", False):
            e.Pinned = False
        if abs(delta) > _EPS:
            DB.ElementTransformUtils.MoveElement(ctx.doc, e.Id, _axis_vector(axis, delta))
        return {"id": id_int(e), "moved": U.from_internal(delta, ctx.unit, 2)}

    return _run(ctx, "align", elements, one,
                {"axis": axis, "aligned_to": U.from_internal(target, ctx.unit, 2)})


# ------------------------------------------------------------------------- offset
def _offset(ctx, elements):
    doc = ctx.doc
    if ctx.get("distance") is None:
        raise RvtssError("offset needs 'distance' (in {}; positive = left of start -> end)".format(ctx.unit))
    dist = U.to_internal(ctx.float("distance"), ctx.unit)
    copy = ctx.bool("copy", False)
    _unpin_check(ctx, elements)

    def one(e):
        loc = _location_curve(e, "offset")
        c = loc.Curve
        if getattr(e, "Pinned", False) and not copy:
            e.Pinned = False
        if isinstance(c, DB.Line):
            d = c.Direction
            vec = DB.XYZ.BasisZ.CrossProduct(d)
            if vec.GetLength() < _EPS:
                raise RvtssError("Element {} is vertical; offset works in plan".format(id_int(e)))
            vec = vec.Normalize().Multiply(dist)
            if copy:
                new_ids = list(DB.ElementTransformUtils.CopyElement(doc, e.Id, vec))
                return {"id": id_int(e), "new_element_ids": [id_int(i) for i in new_ids]}
            DB.ElementTransformUtils.MoveElement(doc, e.Id, vec)
            return {"id": id_int(e)}
        # arcs and other planar curves: a true offset curve (the radius changes)
        new_curve = c.CreateOffset(dist, DB.XYZ.BasisZ)
        if copy:
            new_ids = list(DB.ElementTransformUtils.CopyElement(doc, e.Id, DB.XYZ.Zero))
            if not new_ids:
                raise RvtssError("Element {} could not be copied".format(id_int(e)))
            _location_curve(doc.GetElement(new_ids[0]), "offset").Curve = new_curve
            return {"id": id_int(e), "new_element_ids": [id_int(i) for i in new_ids]}
        loc.Curve = new_curve
        return {"id": id_int(e)}

    return _run(ctx, "offset", elements, one, {"distance": ctx.float("distance"), "copy": copy})


# -------------------------------------------------------------------- trim_extend
def _intersect_2d(a, b):
    """Intersection of two unbounded lines in plan -> (x, y) or None when parallel."""
    p, r = a.GetEndPoint(0), a.Direction
    q, s = b.GetEndPoint(0), b.Direction
    den = r.X * s.Y - r.Y * s.X
    if abs(den) < 1e-9:
        return None
    t = ((q.X - p.X) * s.Y - (q.Y - p.Y) * s.X) / den
    return p.X + r.X * t, p.Y + r.Y * t


def _to_corner(loc, line, x, y):
    """Move the end of the line nearest to (x, y) onto it; the far end stays."""
    a, b = line.GetEndPoint(0), line.GetEndPoint(1)
    pa = DB.XYZ(x, y, a.Z)
    pb = DB.XYZ(x, y, b.Z)
    if a.DistanceTo(pa) <= b.DistanceTo(pb):
        if pa.DistanceTo(b) < 1e-4:
            raise RvtssError("Trimming would leave a zero-length element")
        loc.Curve = DB.Line.CreateBound(pa, b)
        return 0
    if a.DistanceTo(pb) < 1e-4:
        raise RvtssError("Trimming would leave a zero-length element")
    loc.Curve = DB.Line.CreateBound(a, pb)
    return 1


def _trim_extend(ctx, elements):
    doc = ctx.doc
    if len(elements) != 2:
        raise RvtssError("trim_extend needs exactly 2 element_ids (two walls or two lines)")
    mode = text_type(ctx.get("mode", "corner")).lower()
    if mode not in ("corner", "single"):
        raise RvtssError("mode must be 'corner' (both elements meet) or 'single' (only the first is "
                         "trimmed / extended to the second)")
    (loc_a, line_a), (loc_b, line_b) = _straight(elements[0], "trim_extend"), _straight(elements[1], "trim_extend")
    hit = _intersect_2d(line_a, line_b)
    if hit is None:
        raise RvtssError("The two elements are parallel; there is no corner to trim or extend to")
    _unpin_check(ctx, elements)

    def run():
        _unpin(elements)
        ends = {"first_end_moved": _to_corner(loc_a, line_a, hit[0], hit[1])}
        if mode == "corner":
            ends["second_end_moved"] = _to_corner(loc_b, line_b, hit[0], hit[1])
        doc.Regenerate()
        ends.update({"operation": "trim_extend", "mode": mode,
                     "intersection": [U.from_internal(hit[0], ctx.unit, 1), U.from_internal(hit[1], ctx.unit, 1)],
                     "elements": [{"id": id_int(e), "location": core.element_location(e, ctx.unit)}
                                  for e in elements],
                     "unit": ctx.unit})
        return ends

    result, failures = core.run_transaction(doc, "Modify trim_extend", run, dry_run=ctx.dry_run)
    return core.commit_result(result, failures, ctx.dry_run)


# -------------------------------------------------------------------------- split
def _split_point(ctx, line):
    """Point on the line from 'point' (projected onto it in plan) or 'parameter' (0-1 from the start)."""
    a, b = line.GetEndPoint(0), line.GetEndPoint(1)
    if ctx.get("point") is not None:
        p = _xyz(ctx, ctx.get("point"), "point")
        plan = (b.X - a.X) ** 2 + (b.Y - a.Y) ** 2
        if plan > 1e-9:
            ratio = ((p.X - a.X) * (b.X - a.X) + (p.Y - a.Y) * (b.Y - a.Y)) / plan
        elif abs(b.Z - a.Z) > 1e-9:   # a vertical run: use the height of the point
            ratio = (p.Z - a.Z) / (b.Z - a.Z)
        else:
            raise RvtssError("The element has no length")
    elif ctx.get("parameter") is not None:
        ratio = ctx.float("parameter")
    else:
        raise RvtssError("split needs 'point' (on or near the element) or 'parameter' (0-1 from its start)")
    if ratio <= 0.001 or ratio >= 0.999:
        raise RvtssError("The split point is not inside the element (position {:.3f} of its length)".format(ratio),
                         hint="Give a point between the two ends, or parameter between 0 and 1.")
    return a + (b - a).Multiply(ratio), ratio


def _copy_param(src, dst, bip_name, as_id=False):
    try:
        bip = getattr(DB.BuiltInParameter, bip_name)
        ps, pd = src.get_Parameter(bip), dst.get_Parameter(bip)
        if ps is None or pd is None or pd.IsReadOnly:
            return
        pd.Set(ps.AsElementId() if as_id else ps.AsDouble())
    except Exception as ex:
        logger.debug("split: %s not copied: %s", bip_name, ex)


def _split_wall(ctx, wall, point, ratio):
    doc = ctx.doc
    loc, line = _straight(wall, "split")
    try:
        inserts = list(wall.FindInserts(True, False, False, False))
    except Exception:
        inserts = []
    beyond = []
    for iid in inserts:
        ins = doc.GetElement(iid)
        ip = core.element_point(ins) if ins is not None else None
        if ip is None:
            continue
        a = line.GetEndPoint(0)
        d = line.Direction
        if ((ip.X - a.X) * d.X + (ip.Y - a.Y) * d.Y) > line.Length * ratio:
            beyond.append(id_int(iid))
    if beyond:
        raise RvtssError("Wall {} hosts {} insert(s) beyond the split point: {}".format(
            id_int(wall), len(beyond), beyond[:20]), status=409,
            hint="Revit would delete them. Split the wall in Revit (Modify > Split Element), or move / "
                 "re-host the inserts first.")
    a, b = line.GetEndPoint(0), line.GetEndPoint(1)
    height = wall.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
    offset = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    structural = False
    try:
        structural = wall.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT).AsInteger() == 1
    except Exception:
        pass
    loc.Curve = DB.Line.CreateBound(a, point)
    new = DB.Wall.Create(doc, DB.Line.CreateBound(point, b), wall.GetTypeId(), wall.LevelId, height, offset,
                         bool(wall.Flipped), structural)
    _copy_param(wall, new, "WALL_HEIGHT_TYPE", as_id=True)   # top constraint
    _copy_param(wall, new, "WALL_TOP_OFFSET")
    try:
        ps = wall.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM)
        pd = new.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM)
        if ps is not None and pd is not None and not pd.IsReadOnly:
            pd.Set(ps.AsInteger())   # location line
    except Exception:
        pass
    return new


def _split(ctx, elements):
    doc = ctx.doc
    if len(elements) != 1:
        raise RvtssError("split takes exactly one element id (a duct, a pipe or a straight wall)")
    e = elements[0]
    _unpin_check(ctx, elements)
    _loc, line = _straight(e, "split")
    point, ratio = _split_point(ctx, line)
    kind = type(e).__name__

    def run():
        _unpin(elements)
        if isinstance(e, DB.Wall):
            new_id = _split_wall(ctx, e, point, ratio).Id
        elif kind == "Duct":
            from Autodesk.Revit.DB import Mechanical as M

            new_id = M.MechanicalUtils.BreakCurve(doc, e.Id, point)
        elif kind == "Pipe":
            from Autodesk.Revit.DB import Plumbing as P

            new_id = P.PlumbingUtils.BreakCurve(doc, e.Id, point)
        else:
            raise RvtssError("split supports ducts, pipes and straight walls (got {})".format(kind),
                             hint="Other elements: use Modify > Split Element in Revit.")
        doc.Regenerate()
        new = doc.GetElement(new_id)
        return {"operation": "split", "id": id_int(e), "new_element_id": id_int(new_id),
                "position": round(ratio, 4), "unit": ctx.unit,
                "elements": [{"id": id_int(x), "location": core.element_location(x, ctx.unit)}
                             for x in (e, new) if x is not None]}

    result, failures = core.run_transaction(doc, "Modify split", run, dry_run=ctx.dry_run)
    return core.commit_result(result, failures, ctx.dry_run)


# -------------------------------------------------------------------------- scale
def _scale(ctx, elements):
    """Scale positions and lengths in plan about a centre. Sizes that come from types do not change."""
    factor = ctx.float("factor")
    if factor is None or factor <= 0:
        raise RvtssError("scale needs 'factor' > 0 (2 doubles lengths, 0.5 halves them)")
    if ctx.get("center") is not None:
        c = _xyz(ctx, ctx.get("center"), "center")
    else:
        pts = [p for p in (core.element_point(e) for e in elements) if p is not None]
        if not pts:
            raise RvtssError("Cannot determine a centre; pass 'center'")
        c = DB.XYZ(sum(p.X for p in pts) / len(pts), sum(p.Y for p in pts) / len(pts), 0.0)
    _unpin_check(ctx, elements)

    def sc(p):
        return DB.XYZ(c.X + (p.X - c.X) * factor, c.Y + (p.Y - c.Y) * factor, p.Z)

    def one(e):
        if getattr(e, "Pinned", False):
            e.Pinned = False
        loc = e.Location
        if isinstance(loc, DB.LocationCurve):
            cv = loc.Curve
            if isinstance(cv, DB.Line) and cv.IsBound:
                loc.Curve = DB.Line.CreateBound(sc(cv.GetEndPoint(0)), sc(cv.GetEndPoint(1)))
            elif isinstance(cv, DB.Arc) and cv.IsBound:
                loc.Curve = DB.Arc.Create(sc(cv.GetEndPoint(0)), sc(cv.GetEndPoint(1)), sc(cv.Evaluate(0.5, True)))
            else:
                raise RvtssError("Element {} is not a bound line or arc".format(id_int(e)))
            return {"id": id_int(e), "scaled": "curve"}
        if isinstance(loc, DB.LocationPoint):
            p = loc.Point
            DB.ElementTransformUtils.MoveElement(ctx.doc, e.Id, sc(p) - p)
            return {"id": id_int(e), "scaled": "position_only"}
        raise RvtssError("Element {} has no location line or point (sketch-based elements such as floors "
                         "cannot be scaled)".format(id_int(e)))

    return _run(ctx, "scale", elements, one, {
        "factor": factor, "center": core.xyz_list(c, ctx.unit),
        "note": "Lengths of line-based elements and the positions of point-based ones are scaled in plan. "
                "Sizes that come from types (wall thickness, family sizes) and sketch-based elements do not "
                "scale."})


# --------------------------------------------------------------------------- flip
def _flip(ctx, elements):
    what = text_type(ctx.get("flip", "auto")).lower()
    if what not in ("auto", "hand", "facing", "both", "work_plane"):
        raise RvtssError("flip must be auto, hand, facing, both or work_plane")

    def one(e):
        if isinstance(e, DB.Wall):
            e.Flip()
            return {"id": id_int(e), "flipped": ["wall"], "is_flipped": bool(e.Flipped)}
        if isinstance(e, DB.FamilyInstance):
            done = []
            if what in ("auto", "hand", "both") and e.CanFlipHand:
                e.flipHand()
                done.append("hand")
            if what in ("facing", "both") or (what == "auto" and not done):
                if e.CanFlipFacing:
                    e.flipFacing()
                    done.append("facing")
            if what == "work_plane":
                if e.CanFlipWorkPlane:
                    e.IsWorkPlaneFlipped = not e.IsWorkPlaneFlipped
                    done.append("work_plane")
            if not done:
                raise RvtssError("Family instance {} cannot be flipped that way (the family has no '{}' "
                                 "flip control)".format(id_int(e), what))
            return {"id": id_int(e), "flipped": done}
        raise RvtssError("Element {} ({}) cannot be flipped; flip works on walls and family "
                         "instances".format(id_int(e), type(e).__name__))

    return _run(ctx, "flip", elements, one)


# ------------------------------------------------------------------- cut / uncut
def _cut(ctx, elements, op):
    """The first element is cut by each of the others (void family instances or solids)."""
    doc = ctx.doc
    if len(elements) < 2:
        raise RvtssError("{} needs at least 2 element_ids: the element to cut, then the cutting "
                         "elements".format(op))
    target, cutters = elements[0], elements[1:]
    add = op == "cut"

    def one(cutter):
        r = {"target_id": id_int(target), "cutter_id": id_int(cutter)}
        void = False
        if isinstance(cutter, DB.FamilyInstance):
            try:
                void = bool(DB.InstanceVoidCutUtils.CanBeCutWithVoid(target))
            except Exception:
                void = False
        if void:
            exists = DB.InstanceVoidCutUtils.InstanceVoidCutExists(target, cutter)
            if add and not exists:
                try:
                    DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, target, cutter)
                    r["method"] = "instance_void"
                    return r
                except Exception as ex:   # no unattached void in the family: try a solid cut below
                    r["instance_void_error"] = normalize_string(text_type(ex))
            elif not add and exists:
                DB.InstanceVoidCutUtils.RemoveInstanceVoidCut(doc, target, cutter)
                r["method"] = "instance_void"
                return r
            elif add:
                r.update({"method": "instance_void", "already": True})
                return r
        S = DB.SolidSolidCutUtils
        try:
            exists = S.CutExistsBetweenElements(target, cutter)
            if isinstance(exists, tuple):   # IronPython returns (result, out firstCutsSecond)
                exists = exists[0]
        except Exception:
            exists = None
        if add:
            if exists:
                r.update({"method": "solid", "already": True})
                return r
            S.AddCutBetweenSolids(doc, target, cutter)
        else:
            if exists is False:
                raise RvtssError("No cut exists between {} and {}".format(id_int(target), id_int(cutter)))
            S.RemoveCutBetweenSolids(doc, target, cutter)
        r["method"] = "solid"
        return r

    return _run(ctx, op, cutters, one, {
        "target_id": id_int(target),
        "note": "Solid cuts work for the category pairs Revit allows (e.g. a void-like generic model or "
                "structural framing cutting a wall, floor or column); instance voids need a family with an "
                "unattached void and 'Cut with Voids When Loaded'."}, atomic_default=False)


# ------------------------------------------------------------------------- paint
def _material(doc, ref):
    if ref is None or ref == "":
        raise RvtssError("paint needs 'material' (name or id); list_materials lists them")
    if text_type(ref).lstrip("-").isdigit():
        m = doc.GetElement(make_id(int(ref)))
        if isinstance(m, DB.Material):
            return m
    mats = list(DB.FilteredElementCollector(doc).OfClass(DB.Material))
    low = text_type(ref).strip().lower()
    for m in mats:
        if normalize_string(m.Name).lower() == low:
            return m
    raise core.not_found("Material", ref, [m.Name for m in mats], hint="list_materials lists the materials.")


def _own_faces(e):
    """Faces of the element's own solids (faces inside family instance geometry cannot be painted)."""
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.DetailLevel = DB.ViewDetailLevel.Fine
    geom = e.get_Geometry(opt)
    faces = []
    if geom is None:
        return faces
    for obj in geom:
        if isinstance(obj, DB.Solid) and obj.Faces.Size > 0:
            for f in obj.Faces:
                faces.append(f)
    return faces


def _faces(doc, e, side):
    if side in ("interior", "exterior"):
        if not isinstance(e, DB.Wall):
            raise RvtssError("faces='{}' works on walls only (element {})".format(side, id_int(e)))
        shell = DB.ShellLayerType.Interior if side == "interior" else DB.ShellLayerType.Exterior
        refs = list(DB.HostObjectUtils.GetSideFaces(e, shell))
        return [f for f in (e.GetGeometryObjectFromReference(r) for r in refs) if f is not None]
    if side in ("top", "bottom"):
        if isinstance(e, DB.HostObject) and not isinstance(e, DB.Wall):
            try:
                refs = list(DB.HostObjectUtils.GetTopFaces(e) if side == "top"
                            else DB.HostObjectUtils.GetBottomFaces(e))
                faces = [f for f in (e.GetGeometryObjectFromReference(r) for r in refs) if f is not None]
                if faces:
                    return faces
            except Exception as ex:
                logger.debug("paint: host faces of %s: %s", id_int(e), ex)
        want = 1.0 if side == "top" else -1.0
        out = []
        for f in _own_faces(e):
            if isinstance(f, DB.PlanarFace) and abs(f.FaceNormal.Z - want) < 1e-3:
                out.append(f)
        return out
    return _own_faces(e)


def _paint(ctx, elements, op):
    doc = ctx.doc
    side = text_type(ctx.get("faces", "all")).lower()
    if side not in ("all", "top", "bottom", "interior", "exterior"):
        raise RvtssError("faces must be all, top, bottom, interior or exterior")
    mat = _material(doc, ctx.get("material")) if op == "paint" else None

    def one(e):
        faces = _faces(doc, e, side)
        if not faces:
            raise RvtssError("Element {} has no '{}' face that can be painted (family instances are painted "
                             "in the family)".format(id_int(e), side))
        n = 0
        for f in faces:
            if op == "paint":
                doc.Paint(e.Id, f, mat.Id)
                n += 1
            elif doc.IsPainted(e.Id, f):
                doc.RemovePaint(e.Id, f)
                n += 1
        return {"id": id_int(e), "faces": n}

    extra = {"faces": side}
    if mat is not None:
        extra["material"] = normalize_string(mat.Name)
    return _run(ctx, op, elements, one, extra)


# ------------------------------------------------------------------------- parts
def _associated_parts(doc, e):
    try:
        return [id_int(i) for i in DB.PartUtils.GetAssociatedParts(doc, e.Id, False, True)]
    except Exception:
        return []


def _create_parts(ctx, elements):
    doc = ctx.doc
    core.require_project(doc)
    ids = core.to_id_list([e.Id for e in elements])
    if not DB.PartUtils.AreElementsValidForCreateParts(doc, ids):
        bad = [id_int(e) for e in elements
               if not DB.PartUtils.AreElementsValidForCreateParts(doc, core.to_id_list([e.Id]))]
        raise RvtssError("Parts cannot be created from: {}".format(bad[:20]), status=409,
                         hint="Parts come from walls, floors, roofs, ceilings and structural elements that "
                              "have no parts yet.")
    preview = core.confirm_gate(ctx, len(elements), "modify_elements create_parts")
    dry = preview or ctx.dry_run

    def run():
        DB.PartUtils.CreateParts(doc, ids)
        doc.Regenerate()
        res = [{"id": id_int(e), "part_ids": _associated_parts(doc, e)} for e in elements]
        return {"operation": "create_parts", "count": len(elements), "results": res[:200],
                "parts_created": sum(len(r["part_ids"]) for r in res),
                "note": "Parts show in views whose Parts Visibility is 'Show Parts'."}

    result, failures = core.run_transaction(doc, "Modify create_parts", run, dry_run=dry)
    return core.preview_status(core.commit_result(result, failures, dry), preview)


def _divide_parts(ctx, elements):
    """Divide parts (or the parts of the given source elements) by levels / grids / reference planes
    and / or by plan lines sketched at a level."""
    from System.Collections.Generic import List

    doc = ctx.doc
    core.require_project(doc)
    part_ids = []
    for e in elements:
        if isinstance(e, DB.Part):
            part_ids.append(e.Id)
        else:
            found = list(DB.PartUtils.GetAssociatedParts(doc, e.Id, False, True))
            if not found:
                raise RvtssError("Element {} is not a part and has no parts".format(id_int(e)),
                                 hint="Run operation='create_parts' on it first.")
            part_ids.extend(found)
    dividers = core.get_elements(doc, ctx.list("divider_ids"), "Divider")
    raw_lines = ctx.list("lines")
    if not dividers and not raw_lines:
        raise RvtssError("divide_parts needs 'divider_ids' (levels, grids, reference planes) and / or "
                         "'lines' ([[[x, y], [x, y]], ...])")
    level = core.find_level(doc, ctx.get("level")) if ctx.get("level") is not None else None
    if raw_lines and level is None:
        raise RvtssError("'lines' need 'level' (the plane the dividing lines are sketched on)")
    ids = core.to_id_list(part_ids)
    if not DB.PartUtils.ArePartsValidForDivide(doc, ids):
        raise RvtssError("These parts cannot be divided (already divided, or not parts)", status=409)

    def run():
        curves = List[DB.Curve]()
        sketch_id = DB.ElementId.InvalidElementId
        if raw_lines:
            z = level.Elevation
            for ln in raw_lines:
                if len(ln) != 2:
                    raise RvtssError("Each line is [[x, y], [x, y]]")
                a, b = U.point_from(ln[0], ctx.unit), U.point_from(ln[1], ctx.unit)
                curves.Add(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z), DB.XYZ(b[0], b[1], z)))
            sketch_id = DB.SketchPlane.Create(
                doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ(0, 0, z))).Id
        maker = DB.PartUtils.DivideParts(doc, ids, core.to_id_list([d.Id for d in dividers]), curves, sketch_id)
        if maker is None:
            raise RvtssError("Revit did not divide the parts (do the dividers cross them?)")
        doc.Regenerate()
        new_parts = []
        for pid in part_ids:
            try:
                new_parts.extend(id_int(i) for i in DB.PartUtils.GetAssociatedParts(doc, pid, False, True))
            except Exception:
                pass
        return {"operation": "divide_parts", "divided_part_ids": [id_int(i) for i in part_ids][:200],
                "part_maker_id": id_int(maker), "new_part_ids": new_parts[:500], "unit": ctx.unit}

    result, failures = core.run_transaction(doc, "Modify divide_parts", run, dry_run=ctx.dry_run)
    return core.commit_result(result, failures, ctx.dry_run)


# ------------------------------------------------------------------------- route
def modify_elements(ctx):
    doc = ctx.doc
    op = text_type(ctx.require("operation")).lower()
    if op not in OPERATIONS:
        raise RvtssError("operation must be one of: {}".format(", ".join(OPERATIONS)),
                         hint="move / copy / rotate / mirror / array / pin / join are in transform_elements.")
    elements = core.get_elements(doc, ctx.list("element_ids"))
    if not elements:
        raise RvtssError("element_ids is required")
    if op == "align":
        return _align(ctx, elements)
    if op == "offset":
        return _offset(ctx, elements)
    if op == "trim_extend":
        return _trim_extend(ctx, elements)
    if op == "split":
        return _split(ctx, elements)
    if op == "scale":
        return _scale(ctx, elements)
    if op == "flip":
        return _flip(ctx, elements)
    if op in ("cut", "uncut"):
        return _cut(ctx, elements, op)
    if op in ("paint", "remove_paint"):
        return _paint(ctx, elements, op)
    if op == "create_parts":
        return _create_parts(ctx, elements)
    return _divide_parts(ctx, elements)


def register_modify_routes(api):
    @api.route("/modify/elements/", methods=["POST"])
    def modify_elements_route(doc, request):
        return handle(doc, request, modify_elements)

    logger.info("RVTSS modify routes registered")
