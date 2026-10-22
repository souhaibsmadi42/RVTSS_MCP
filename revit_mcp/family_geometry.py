# -*- coding: UTF-8 -*-
"""Parametric family geometry (RVTSS).

Routes:
    POST /family/reference_planes/  create (batch) or list reference planes
    POST /family/forms/             extrusion / blend / revolution / sweep, solid or void
    POST /family/dimension/         dimension between reference planes / Ref. Level, label, EQ, lock
    POST /family/align/             lock form faces to coplanar reference planes
    POST /family/build_box/         complete parametric box (planes, labelled dims, EQ, locked
                                    extrusion, height + material parameters) + flex check
    POST /family/flex/              flex types / parameter values and verify geometry responds

Coordinates are in `unit` (default mm). Axis convention in family templates:
X = left/right, Y = front/back, Z = up; the Ref. Level is at Z = 0.
"""
import math
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, definition_spec, add_family_parameter
from .params_util import family_parameter, set_family_value, family_type_value
from .family_utils import (plan_view, elevation_view, find_ref_plane, reference_planes, plane_orientation,
                           plane_offset, describe_ref_plane, datum_reference, datum_orientation, datum_offset,
                           set_is_reference, solid_faces, forms, describe_form, combined_bbox, ref_level,
                           ensure_current_type, labeled_dimensions, is_relevant)
from .pure import units as U
from .utils import normalize_string

logger = logging.getLogger(__name__)

EXTENT = 3.0  # ft, half-length of new reference planes


# ------------------------------------------------------------ reference planes
def _new_ref_plane(doc, orientation, offset, name, extent=EXTENT):
    if orientation == "x":
        bubble, free, cut = DB.XYZ(offset, extent, 0), DB.XYZ(offset, -extent, 0), DB.XYZ.BasisZ
        view = plan_view(doc)
    elif orientation == "y":
        bubble, free, cut = DB.XYZ(extent, offset, 0), DB.XYZ(-extent, offset, 0), DB.XYZ.BasisZ
        view = plan_view(doc)
    elif orientation == "z":
        bubble, free, cut = DB.XYZ(extent, 0, offset), DB.XYZ(-extent, 0, offset), DB.XYZ.BasisY
        view = elevation_view(doc, "front")
    else:
        raise RvtssError("orientation must be x (left/right planes), y (front/back) or z (horizontal)")
    rp = doc.FamilyCreate.NewReferencePlane(bubble, free, cut, view)
    if name:
        rp.Name = name
    return rp


def reference_planes_route(ctx):
    doc = ctx.doc
    core.require_family(doc)
    unit = ctx.unit
    if ctx.get("action", "create") == "list":
        return {"unit": unit, "reference_planes": [describe_ref_plane(rp, unit) for rp in reference_planes(doc)]}
    items = ctx.list("planes")
    if not items:
        raise RvtssError("'planes' is required: [{name: 'Left', orientation: 'x', offset: -450}]")
    existing = dict((normalize_string(rp.Name).lower(), rp) for rp in reference_planes(doc))
    dry = ctx.dry_run

    def one(item):
        name = item.get("name")
        o = item.get("orientation")
        off = U.to_internal(item.get("offset", 0), unit)
        if name and name.lower() in existing:
            rp = existing[name.lower()]
            if item.get("if_exists", "reuse") == "error":
                raise RvtssError("Reference plane '{}' exists".format(name), status=409)
            return {"name": name, "id": id_int(rp), "action": "exists",
                    "offset": U.from_internal(plane_offset(rp), unit, 3)}
        rp = _new_ref_plane(doc, o, off, name)
        if item.get("is_reference"):
            try:
                set_is_reference(rp, item["is_reference"])
            except RvtssError as e:
                ctx.warn("{}: {}".format(name, e.message))
        return {"name": name, "id": id_int(rp), "action": "created", "orientation": o,
                "offset": item.get("offset", 0)}

    res, fails = core.run_transaction(doc, "Reference planes", lambda: core.batch(doc, items, one, True), dry_run=dry)
    return core.commit_result({"unit": unit, "results": res}, fails, dry)


# ----------------------------------------------------------------- sketch plane
def _sketch_plane(doc, work_plane):
    """Return (SketchPlane, origin XYZ, x axis, y axis, normal)."""
    wp = work_plane or "level"
    datum = find_ref_plane(doc, wp)
    try:
        sp = DB.SketchPlane.Create(doc, datum.Id)
    except Exception:
        sp = DB.SketchPlane.Create(doc, datum_reference(datum))
    plane = sp.GetPlane()
    return sp, plane.Origin, plane.XVec, plane.YVec, plane.Normal


def _local(origin, xv, yv, uv):
    return origin + xv * float(uv[0]) + yv * float(uv[1])


def _loops_from_profile(profile, unit, origin, xv, yv, normal, coordinates):
    """profile: {rectangle: {min, max}} | {circle: {center, radius}} | {loops: [[pt, ...], ...]}.

    Points are local (u, v) in the sketch plane (default) or world [x, y, z]
    (coordinates='world', projected onto the plane).
    """
    loops = []
    if "rectangle" in profile:
        r = profile["rectangle"]
        (x0, y0), (x1, y1) = r["min"], r["max"]
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        loops.append([_local(origin, xv, yv, (U.to_internal(a, unit), U.to_internal(b, unit))) for a, b in pts])
    elif "circle" in profile:
        c = profile["circle"]
        cu, cv = c.get("center", [0, 0])
        center = _local(origin, xv, yv, (U.to_internal(cu, unit), U.to_internal(cv, unit)))
        radius = U.to_internal(c["radius"], unit)
        return [[DB.Arc.Create(center, radius, 0.0, math.pi, xv, yv),
                 DB.Arc.Create(center, radius, math.pi, 2 * math.pi, xv, yv)]]
    elif "loops" in profile:
        for loop in profile["loops"]:
            pts = []
            for p in loop:
                if coordinates == "world":
                    x, y, z = U.point_from(p, unit)
                    w = DB.XYZ(x, y, z)
                    w = w - normal * (w - origin).DotProduct(normal)  # project onto plane
                    pts.append(w)
                else:
                    pts.append(_local(origin, xv, yv, (U.to_internal(p[0], unit), U.to_internal(p[1], unit))))
            if len(pts) < 3:
                raise RvtssError("Each profile loop needs at least 3 points")
            loops.append(pts)
    else:
        raise RvtssError("profile needs 'rectangle', 'circle' or 'loops'")
    out = []
    for pts in loops:
        curves = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            if a.DistanceTo(b) < 1e-5:
                continue
            curves.append(DB.Line.CreateBound(a, b))
        out.append(curves)
    return out


def _curve_arr_arr(loops):
    arrarr = DB.CurveArrArray()
    for loop in loops:
        arr = DB.CurveArray()
        for c in loop:
            arr.Append(c)
        arrarr.Append(arr)
    return arrarr


def _curve_arr(curves):
    arr = DB.CurveArray()
    for c in curves:
        arr.Append(c)
    return arr


# ------------------------------------------------------------------------ forms
def _apply_form_options(ctx, doc, fm, form, item):
    out = {}
    vis = item.get("visibility")
    if vis:
        v = DB.FamilyElementVisibility(DB.FamilyElementVisibilityType.Model)
        v.IsShownInCoarse = bool(vis.get("coarse", True))
        v.IsShownInMedium = bool(vis.get("medium", True))
        v.IsShownInFine = bool(vis.get("fine", True))
        if "plan" in vis:
            v.IsShownInPlanRCPCut = bool(vis["plan"])
        if "front_back" in vis:
            v.IsShownInFrontBack = bool(vis["front_back"])
        if "left_right" in vis:
            v.IsShownInLeftRight = bool(vis["left_right"])
        form.SetVisibility(v)
        out["visibility"] = vis
    sub = item.get("subcategory")
    if sub:
        parent = doc.OwnerFamily.FamilyCategory
        subcat = None
        for c in parent.SubCategories:
            if normalize_string(c.Name).lower() == sub.lower():
                subcat = c
        if subcat is None:
            subcat = doc.Settings.Categories.NewSubcategory(parent, sub)
        form.Subcategory = subcat
        out["subcategory"] = sub
    for key, bip, ptype, group in (("material_parameter", "MATERIAL_ID_PARAM", "material", "materials"),
                                   ("visible_parameter", "IS_VISIBLE_PARAM", "yesno", "graphics"),
                                   ("end_parameter", "EXTRUSION_END_PARAM", "length", "dimensions"),
                                   ("start_parameter", "EXTRUSION_START_PARAM", "length", "dimensions")):
        pname = item.get(key)
        if not pname:
            continue
        ep = form.get_Parameter(getattr(DB.BuiltInParameter, bip))
        if ep is None:
            raise RvtssError("This form has no {} to associate".format(bip))
        fp = family_parameter(fm, pname)
        if fp is None:
            fp = add_family_parameter(fm, pname, ptype, group, bool(item.get("instance_parameters", False)))
            if ptype == "yesno":
                ensure_current_type(fm)
                fm.Set(fp, 1)
            elif ptype == "length":
                ensure_current_type(fm)
                fm.Set(fp, ep.AsDouble())
        fm.AssociateElementParameterToFamilyParameter(ep, fp)
        out[key] = pname
    return out


def _cut_solids(doc, void):
    cut = []
    vb = void.get_BoundingBox(None)
    for kind, f in forms(doc):
        if not f.IsSolid:
            continue
        bb = f.get_BoundingBox(None)
        if vb is None or bb is None:
            continue
        if bb.Max.X < vb.Min.X or bb.Min.X > vb.Max.X or bb.Max.Y < vb.Min.Y or bb.Min.Y > vb.Max.Y or \
                bb.Max.Z < vb.Min.Z or bb.Min.Z > vb.Max.Z:
            continue
        try:
            DB.SolidSolidCutUtils.AddCutBetweenSolids(doc, f, void)
            cut.append(id_int(f))
        except Exception as e:
            logger.warning("Void cut failed: {}".format(e))
    return cut


def _create_form(ctx, doc, fm, item):
    unit = ctx.unit
    kind = item.get("kind", "extrusion")
    solid = not item.get("void", False)
    sp, origin, xv, yv, normal = _sketch_plane(doc, item.get("work_plane"))
    coords = item.get("coordinates", "local")
    create = doc.FamilyCreate
    if kind == "extrusion":
        loops = _loops_from_profile(item["profile"], unit, origin, xv, yv, normal, coords)
        end = U.to_internal(item.get("end", item.get("depth", 1000)), unit)
        form = create.NewExtrusion(solid, _curve_arr_arr(loops), sp, end)
        start = U.to_internal(item.get("start", 0), unit)
        if start:
            form.StartOffset = start
        form.EndOffset = end
    elif kind == "blend":
        base = _loops_from_profile(item["base_profile"], unit, origin, xv, yv, normal, coords)[0]
        height = U.to_internal(item.get("height", 1000), unit)
        top_origin = origin + normal * height
        top = _loops_from_profile(item["top_profile"], unit, top_origin, xv, yv, normal, coords)[0]
        form = create.NewBlend(solid, _curve_arr(top), _curve_arr(base), sp)
        form.TopOffset = height
        form.BottomOffset = 0.0
    elif kind == "revolution":
        loops = _loops_from_profile(item["profile"], unit, origin, xv, yv, normal, coords)
        a0, a1 = item.get("axis", [[0, 0], [0, 1]])
        axis = DB.Line.CreateBound(_local(origin, xv, yv, (U.to_internal(a0[0], unit), U.to_internal(a0[1], unit))),
                                   _local(origin, xv, yv, (U.to_internal(a1[0], unit), U.to_internal(a1[1], unit))))
        form = create.NewRevolution(solid, _curve_arr_arr(loops), sp, axis,
                                    math.radians(item.get("start_angle", 0)), math.radians(item.get("end_angle", 360)))
    elif kind == "sweep":
        path_pts = [_local(origin, xv, yv, (U.to_internal(p[0], unit), U.to_internal(p[1], unit)))
                    for p in item["path"]]
        if len(path_pts) < 2:
            raise RvtssError("sweep needs a 'path' of at least 2 points")
        path = [DB.Line.CreateBound(path_pts[i], path_pts[i + 1]) for i in range(len(path_pts) - 1)]
        tangent = (path_pts[1] - path_pts[0]).Normalize()
        v_axis = normal
        u_axis = v_axis.CrossProduct(tangent).Normalize()
        loops = _loops_from_profile(item["profile"], unit, path_pts[0], u_axis, v_axis, tangent, "local")
        profile = doc.Application.Create.NewCurveLoopsProfile(_curve_arr_arr(loops))
        form = create.NewSweep(solid, _curve_arr(path), sp, profile, 0, DB.ProfilePlaneLocation.Start)
    else:
        raise RvtssError("kind must be extrusion, blend, revolution or sweep")
    doc.Regenerate()
    out = {"id": id_int(form), "kind": kind, "solid": solid,
           "work_plane": item.get("work_plane", "level"),
           "plane_axes": {"origin": core.xyz_list(origin, unit), "x": [round(xv.X, 4), round(xv.Y, 4), round(xv.Z, 4)],
                          "y": [round(yv.X, 4), round(yv.Y, 4), round(yv.Z, 4)]}}
    out.update(_apply_form_options(ctx, doc, fm, form, item))
    if not solid and item.get("cut_solids", True):
        out["cuts_solids"] = _cut_solids(doc, form)
    if item.get("align", False):
        out["alignments"] = _align_form(doc, form, None, True)
    return out


def forms_route(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    if ctx.get("action", "create") == "list":
        return {"unit": ctx.unit, "forms": [describe_form(doc, k, f, ctx.unit, fm) for k, f in forms(doc)]}
    items = ctx.list("forms")
    if not items:
        raise RvtssError("'forms' is required, e.g. [{kind: 'extrusion', profile: {rectangle: {min: [-450,-300], "
                         "max: [450,300]}}, end: 750, material_parameter: 'Material'}]")
    dry = ctx.dry_run
    res, fails = core.run_transaction(
        doc, "Create forms", lambda: core.batch(doc, items, lambda it: _create_form(ctx, doc, fm, it), True),
        dry_run=dry)
    return core.commit_result({"unit": ctx.unit, "results": res}, fails, dry)


# ------------------------------------------------------------------- dimensions
def _dimension(doc, fm, datums, label=None, equality=False, lock=False, line_offset=None):
    if len(datums) < 2:
        raise RvtssError("A dimension needs at least 2 reference planes")
    orients = set(datum_orientation(d) for d in datums)
    if len(orients) != 1 or "skew" in orients:
        raise RvtssError("All references of a dimension must be parallel axis planes (got {})".format(sorted(orients)))
    o = orients.pop()
    offs = [datum_offset(d) for d in datums]
    lo, hi = min(offs) - 0.5, max(offs) + 0.5
    k = line_offset if line_offset is not None else -2.0
    if o == "x":
        view = plan_view(doc)
        line = DB.Line.CreateBound(DB.XYZ(lo, k, 0), DB.XYZ(hi, k, 0))
    elif o == "y":
        view = plan_view(doc)
        line = DB.Line.CreateBound(DB.XYZ(k, lo, 0), DB.XYZ(k, hi, 0))
    else:
        view = elevation_view(doc, "front")
        line = DB.Line.CreateBound(DB.XYZ(k, 0, lo), DB.XYZ(k, 0, hi))
    refs = DB.ReferenceArray()
    for d in datums:
        refs.Append(datum_reference(d))
    dim = doc.FamilyCreate.NewDimension(view, line, refs)
    if dim is None:
        raise RvtssError("Revit could not create the dimension", status=409)
    if equality:
        if len(datums) < 3:
            raise RvtssError("EQ needs at least 3 references (e.g. Left, Center, Right)")
        dim.AreSegmentsEqual = True
    if label:
        fp = family_parameter(fm, label)
        if fp is None:
            raise RvtssError("Family parameter '{}' not found".format(label), status=404,
                             hint="Create it first (family_add_parameters, type length).")
        if definition_spec(fp.Definition)[1] not in ("length", "angle"):
            raise RvtssError("Only length/angle parameters can label a dimension ('{}' is {})".format(
                label, definition_spec(fp.Definition)[0]))
        dim.FamilyLabel = fp
    if lock:
        dim.IsLocked = True
    return dim


def dimension_route(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    items = ctx.list("dimensions") or [dict((k, ctx.data[k]) for k in ("references", "label", "equality", "lock")
                                            if k in ctx.data)]
    if not items or not items[0].get("references"):
        raise RvtssError("Pass references: ['Left', 'Right'] (reference plane names or 'Ref. Level'), "
                         "label (parameter), equality, lock")
    dry = ctx.dry_run

    def one(item):
        datums = [find_ref_plane(doc, n) for n in item["references"]]
        if item.get("label"):
            ensure_current_type(fm)
        dim = _dimension(doc, fm, datums, item.get("label"), item.get("equality", False), item.get("lock", False),
                         U.to_internal(item["line_offset"], ctx.unit) if item.get("line_offset") is not None else None)
        doc.Regenerate()
        return {"id": id_int(dim), "references": item["references"], "label": item.get("label"),
                "equality": bool(item.get("equality")), "value": U.from_internal(dim.Value, ctx.unit, 3)
                if dim.Value is not None else None}

    res, fails = core.run_transaction(doc, "Dimensions", lambda: core.batch(doc, items, one, True), dry_run=dry)
    return core.commit_result({"unit": ctx.unit, "results": res}, fails, dry)


# -------------------------------------------------------------------- alignment
def _align_form(doc, form, datum_names, lock=True):
    datums = [find_ref_plane(doc, n) for n in datum_names] if datum_names else \
        list(reference_planes(doc)) + ([ref_level(doc)] if ref_level(doc) else [])
    faces = solid_faces(form)
    made = []
    for d in datums:
        o = datum_orientation(d)
        if o == "skew":
            continue
        axis = {"x": DB.XYZ.BasisX, "y": DB.XYZ.BasisY, "z": DB.XYZ.BasisZ}[o]
        off = datum_offset(d)
        for f in faces:
            n = f.FaceNormal
            if abs(abs(n.DotProduct(axis)) - 1.0) > 1e-6:
                continue
            pos = f.Origin.DotProduct(axis)
            if abs(pos - off) > 1e-5 or f.Reference is None:
                continue
            view = elevation_view(doc, "front") if o == "z" else plan_view(doc)
            try:
                al = doc.FamilyCreate.NewAlignment(view, datum_reference(d), f.Reference)
                if lock:
                    try:
                        al.IsLocked = True
                    except Exception:
                        pass
                made.append({"plane": normalize_string(d.Name), "alignment_id": id_int(al)})
            except Exception as e:
                made.append({"plane": normalize_string(d.Name), "error": normalize_string(text_type(e))})
            break
    return made


def align_route(ctx):
    doc = ctx.doc
    core.require_family(doc)
    form_ids = ctx.list("form_ids") or [id_int(f) for k, f in forms(doc) if f.IsSolid]
    names = ctx.list("planes") or None
    dry = ctx.dry_run

    def run():
        out = []
        for fid in form_ids:
            out.append({"form_id": fid, "alignments": _align_form(doc, core.get_element(doc, fid), names,
                                                                  ctx.bool("lock", True))})
        doc.Regenerate()
        return {"results": out}

    res, fails = core.run_transaction(doc, "Align forms", run, dry_run=dry)
    return core.commit_result(res, fails, dry)


# ---------------------------------------------------------------------- box
def _ensure_length_param(fm, name, value, instance):
    fp = family_parameter(fm, name)
    if fp is None:
        fp = add_family_parameter(fm, name, "length", "dimensions", instance)
    elif definition_spec(fp.Definition)[1] != "length":
        raise RvtssError("Existing parameter '{}' is not a length".format(name), status=409)
    ensure_current_type(fm)
    if value is not None and not fp.Formula:
        fm.Set(fp, value)
    return fp


def _plane_pair(doc, names, orientation, half, existing):
    """Get or create the two planes at -half/+half."""
    out = []
    for name, sign in zip(names, (-1, 1)):
        rp = existing.get(name.lower())
        if rp is not None and plane_orientation(rp) != orientation:
            raise RvtssError("Plane '{}' exists with orientation {}".format(name, plane_orientation(rp)), status=409)
        if rp is None:
            rp = _new_ref_plane(doc, orientation, sign * half, name)
        out.append(rp)
    return out


def _center_plane(doc, orientation, existing):
    for key in (("center (left/right)",) if orientation == "x" else ("center (front/back)",)):
        if key in existing:
            return existing[key]
    for rp in existing.values():
        if plane_orientation(rp) == orientation and abs(plane_offset(rp)) < 1e-6:
            return rp
    return _new_ref_plane(doc, orientation, 0.0, "Center (Left/Right)" if orientation == "x" else "Center (Front/Back)")


def build_box(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    unit = ctx.unit
    w = U.to_internal(ctx.float("width", 900), unit)
    dpt = U.to_internal(ctx.float("depth", 600), unit)
    h = U.to_internal(ctx.float("height", 750), unit)
    if min(w, dpt, h) <= 0:
        raise RvtssError("width, depth and height must be positive")
    pw, pd, ph = ctx.get("width_parameter", "Width"), ctx.get("depth_parameter", "Depth"), \
        ctx.get("height_parameter", "Height")
    material = ctx.get("material_parameter", "Material")
    instance = ctx.bool("instance_parameters", False)
    dry = ctx.dry_run

    def run():
        existing = dict((normalize_string(rp.Name).lower(), rp) for rp in reference_planes(doc))
        _ensure_length_param(fm, pw, w, instance)
        _ensure_length_param(fm, pd, dpt, instance)
        fph = _ensure_length_param(fm, ph, h, instance)
        left, right = _plane_pair(doc, ("Left", "Right"), "x", w / 2.0, existing)
        front, back = _plane_pair(doc, ("Front", "Back"), "y", dpt / 2.0, existing)
        cx = _center_plane(doc, "x", existing)
        cy = _center_plane(doc, "y", existing)
        doc.Regenerate()
        x0, x1 = sorted([plane_offset(left), plane_offset(right)])
        y0, y1 = sorted([plane_offset(front), plane_offset(back)])
        level = ref_level(doc)
        sp = DB.SketchPlane.Create(doc, level.Id)
        z = level.Elevation
        pts = [DB.XYZ(x0, y0, z), DB.XYZ(x1, y0, z), DB.XYZ(x1, y1, z), DB.XYZ(x0, y1, z)]
        loop = [DB.Line.CreateBound(pts[i], pts[(i + 1) % 4]) for i in range(4)]
        ext = doc.FamilyCreate.NewExtrusion(True, _curve_arr_arr([loop]), sp, h)
        doc.Regenerate()
        aligned = _align_form(doc, ext, [left.Name, right.Name, front.Name, back.Name], True)
        dims = []
        dims.append(_dimension(doc, fm, [left, right], label=pw))
        dims.append(_dimension(doc, fm, [front, back], label=pd, line_offset=-2.0))
        if ctx.bool("center_equality", True):
            dims.append(_dimension(doc, fm, [left, cx, right], equality=True, line_offset=-2.5))
            dims.append(_dimension(doc, fm, [front, cy, back], equality=True, line_offset=-2.5))
        fm.AssociateElementParameterToFamilyParameter(ext.get_Parameter(DB.BuiltInParameter.EXTRUSION_END_PARAM), fph)
        mat = None
        if material:
            mat = family_parameter(fm, material)
            if mat is None:
                mat = add_family_parameter(fm, material, "material", "materials", instance)
            fm.AssociateElementParameterToFamilyParameter(ext.get_Parameter(DB.BuiltInParameter.MATERIAL_ID_PARAM), mat)
        sub = ctx.get("subcategory")
        if sub:
            _apply_form_options(ctx, doc, fm, ext, {"subcategory": sub})
        doc.Regenerate()
        errors = [a for a in aligned if "error" in a]
        if len([a for a in aligned if "alignment_id" in a]) < 4:
            raise RvtssError("Could not lock all four sides of the extrusion: {}".format(aligned), status=409,
                             hint="Nothing was kept. Check that Left/Right/Front/Back planes are not pinned or "
                                  "already constrained differently.")
        return {"extrusion_id": id_int(ext), "parameters": [pw, pd, ph] + ([material] if material else []),
                "reference_planes": [normalize_string(p.Name) for p in (left, right, front, back, cx, cy)],
                "dimension_ids": [id_int(d) for d in dims], "alignments": aligned, "alignment_errors": errors}

    res, fails = core.run_transaction(doc, "Build parametric box", run, dry_run=dry)
    out = core.commit_result(res, fails, dry, {"unit": unit})
    if not dry and ctx.bool("flex_check", True):
        factor_cases = [{"name": "x1.5", "values": {pw: {"value": ctx.float("width", 900) * 1.5, "unit": unit},
                                                     pd: {"value": ctx.float("depth", 600) * 1.5, "unit": unit},
                                                     ph: {"value": ctx.float("height", 750) * 1.5, "unit": unit}}},
                        {"name": "x0.5", "values": {pw: {"value": ctx.float("width", 900) * 0.5, "unit": unit},
                                                     pd: {"value": ctx.float("depth", 600) * 0.5, "unit": unit},
                                                     ph: {"value": ctx.float("height", 750) * 0.5, "unit": unit}}}]
        expect = {"x": pw, "y": pd, "z": ph}
        out["flex_check"] = _flex(doc, fm, factor_cases, unit, expect, ctx.float("tolerance", 0.5))
    return out


# -------------------------------------------------------------------------- flex
def _bbox_size(doc, unit):
    bb = combined_bbox(doc)
    if bb is None:
        return None
    mins, maxs = bb
    return [U.from_internal(maxs[i] - mins[i], unit, 3) for i in range(3)]


def _flex(doc, fm, cases, unit, expect=None, tol=0.5):
    """Apply each case in a committed transaction inside a TransactionGroup that is rolled back."""
    results = []
    group = DB.TransactionGroup(doc, "RVTSS: flex test")
    group.Start()
    try:
        base = _bbox_size(doc, unit)
        for case in cases:
            entry = {"case": case.get("name") or case.get("type") or "case", "ok": True}
            t, collector = core._start_tx(doc, "RVTSS: flex case")
            try:
                if case.get("type"):
                    from .family_utils import find_family_type

                    fm.CurrentType = find_family_type(fm, case["type"])
                for pname, val in (case.get("values") or {}).items():
                    fp = family_parameter(fm, pname)
                    if fp is None:
                        raise RvtssError("Parameter '{}' not found".format(pname))
                    v, u = (val.get("value"), val.get("unit", unit)) if isinstance(val, dict) else (val, unit)
                    set_family_value(doc, fm, fp, v, u)
                doc.Regenerate()
                status = t.Commit()
                if status != DB.TransactionStatus.Committed:
                    entry["ok"] = False
                    entry["errors"] = [m["message"] for m in collector.messages if m["severity"] != "Warning"]
            except Exception as e:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                entry["ok"] = False
                entry["errors"] = [e.message if isinstance(e, RvtssError) else normalize_string(text_type(e))]
            if collector.messages:
                entry["revit_messages"] = collector.messages[:10]
            size = _bbox_size(doc, unit)
            entry["bbox_size"] = size
            entry["changed_from_base"] = size != base
            if expect and entry["ok"] and size:
                checks = {}
                for axis, pname in expect.items():
                    fp = family_parameter(fm, pname)
                    if fp is None:
                        continue
                    want = family_type_value(fm, fm.CurrentType, fp, unit)
                    got = size["xyz".index(axis)]
                    checks[pname] = {"expected": want, "actual": got,
                                     "pass": want is not None and abs(got - want) <= tol}
                entry["checks"] = checks
                if any(not c["pass"] for c in checks.values()):
                    entry["ok"] = False
            results.append(entry)
    finally:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
    return {"base_bbox_size": base, "cases": results, "unit": unit,
            "passed": all(r["ok"] for r in results),
            "note": "All flex changes were rolled back; the family is unchanged."}


def flex_route(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    core.check_modifiable(doc)
    unit = ctx.unit
    cases = ctx.list("cases")
    expect = ctx.get("expect")
    auto = []
    if not cases:
        # every type, then +20% on each driving length parameter
        cases = [{"type": normalize_string(t.Name)} for t in fm.Types]
        labels = labeled_dimensions(doc)
        for fp in fm.Parameters:
            n = normalize_string(fp.Definition.Name)
            if fp.Formula or fp.IsReporting or definition_spec(fp.Definition)[1] != "length":
                continue
            if not is_relevant(fp):
                continue
            cur = family_type_value(fm, fm.CurrentType, fp, unit) if fm.CurrentType else None
            if not cur:
                continue
            auto.append(n)
            cases.append({"name": "{} +20%".format(n), "values": {n: {"value": cur * 1.2, "unit": unit}},
                          "parameter": n, "labelled": bool(labels.get(n))})
    result = _flex(doc, fm, cases, unit, expect, ctx.float("tolerance", 0.5))
    if auto:
        inert = [c["case"].replace(" +20%", "") for c, src in zip(result["cases"], cases)
                 if src.get("parameter") and c["ok"] and not c["changed_from_base"]]
        result["parameters_without_geometric_effect"] = inert
        if inert:
            result["hint"] = ("These length parameters do not change the overall bounding box. That is expected "
                              "for internal offsets, otherwise label a dimension or associate them.")
    return result


def register_family_geometry_routes(api):
    @api.route("/family/reference_planes/", methods=["POST"])
    def family_reference_planes_route(doc, request):
        return handle(doc, request, reference_planes_route)

    @api.route("/family/forms/", methods=["POST"])
    def family_forms_route(doc, request):
        return handle(doc, request, forms_route)

    @api.route("/family/dimension/", methods=["POST"])
    def family_dimension_route(doc, request):
        return handle(doc, request, dimension_route)

    @api.route("/family/align/", methods=["POST"])
    def family_align_route(doc, request):
        return handle(doc, request, align_route)

    @api.route("/family/build_box/", methods=["POST"])
    def family_build_box_route(doc, request):
        return handle(doc, request, build_box)

    @api.route("/family/flex/", methods=["POST"])
    def family_flex_route(doc, request):
        return handle(doc, request, flex_route)

    logger.info("RVTSS family geometry routes registered")
