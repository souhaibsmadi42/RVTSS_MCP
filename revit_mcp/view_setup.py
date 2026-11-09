# -*- coding: UTF-8 -*-
"""View extents, view templates and viewports on sheets (RVTSS v2.4).

Routes:
    POST /views/extents/     get; crop region (on/off, visible, fit to elements or a box); 3D section box;
                             plan view range; far clip of sections and elevations
    POST /views/templates/   list, create from a view, duplicate, apply to views, remove, delete,
                             include / exclude the parameters a template controls
    POST /sheets/viewports/  list a sheet's viewports and schedules; move, change type, set detail number,
                             rotate, remove
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, text_type
from .pure import units as U
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

PLANES = (("top", "TopClipPlane"), ("cut", "CutPlane"), ("bottom", "BottomClipPlane"),
          ("view_depth", "ViewDepthPlane"))
FAR_CLIP = {"no_clip": 0, "clip_with_line": 1, "clip_without_line": 2}


# ------------------------------------------------------------------------ extents
def _model_box(ctx):
    """Model-space box from element_ids (+ margin) or min / max points. None when neither is given."""
    doc, unit = ctx.doc, ctx.unit
    ids = ctx.list("element_ids")
    lo, hi = ctx.get("min"), ctx.get("max")
    if ids:
        mins = maxs = None
        for e in core.get_elements(doc, ids):
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            if mins is None:
                mins, maxs = bb.Min, bb.Max
            else:
                mins = DB.XYZ(min(mins.X, bb.Min.X), min(mins.Y, bb.Min.Y), min(mins.Z, bb.Min.Z))
                maxs = DB.XYZ(max(maxs.X, bb.Max.X), max(maxs.Y, bb.Max.Y), max(maxs.Z, bb.Max.Z))
        if mins is None:
            raise RvtssError("None of the elements has a bounding box")
        m = U.to_internal(ctx.float("margin", 500), unit)
        return DB.XYZ(mins.X - m, mins.Y - m, mins.Z - m), DB.XYZ(maxs.X + m, maxs.Y + m, maxs.Z + m)
    if lo is not None and hi is not None:
        a, b = U.point_from(lo, unit), U.point_from(hi, unit)
        return (DB.XYZ(min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2])),
                DB.XYZ(max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])))
    if lo is not None or hi is not None:
        raise RvtssError("Give both 'min' and 'max'")
    return None


def _corners(lo, hi):
    return [DB.XYZ(x, y, z) for x in (lo.X, hi.X) for y in (lo.Y, hi.Y) for z in (lo.Z, hi.Z)]


def _pt(p, unit):
    return [U.from_internal(p.X, unit, 1), U.from_internal(p.Y, unit, 1), U.from_internal(p.Z, unit, 1)]


def _crop_info(view, unit):
    out = {}
    try:
        out["crop_active"] = bool(view.CropBoxActive)
        out["crop_visible"] = bool(view.CropBoxVisible)
        bb = view.CropBox
        if bb is not None:
            t = bb.Transform
            pts = [t.OfPoint(p) for p in _corners(bb.Min, bb.Max)]
            out["crop_min"] = _pt(DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts), min(p.Z for p in pts)), unit)
            out["crop_max"] = _pt(DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts), max(p.Z for p in pts)), unit)
    except Exception as e:
        out["crop_error"] = normalize_string(text_type(e))
    return out


def _range_info(doc, view, unit):
    vr = view.GetViewRange()
    out = {}
    for key, plane in PLANES:
        p = getattr(DB.PlanViewPlane, plane)
        lvl = doc.GetElement(vr.GetLevelId(p))
        out[key] = {"offset": U.from_internal(vr.GetOffset(p), unit, 1),
                    "level": normalize_string(lvl.Name) if lvl is not None else None}
    return out


def _extents_info(ctx, view):
    doc, unit = ctx.doc, ctx.unit
    out = {"view": normalize_string(view.Name), "view_id": id_int(view), "view_type": str(view.ViewType),
           "scale": getattr(view, "Scale", None), "unit": unit}
    out.update(_crop_info(view, unit))
    try:
        _p, sb = _scope_box_of(doc, view)
        out["scope_box"] = normalize_string(sb.Name) if sb is not None else None
    except Exception:
        pass
    if isinstance(view, DB.View3D):
        out["section_box_active"] = bool(view.IsSectionBoxActive)
        if view.IsSectionBoxActive:
            sb = view.GetSectionBox()
            pts = [sb.Transform.OfPoint(p) for p in _corners(sb.Min, sb.Max)]
            out["section_box_min"] = _pt(DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts),
                                                min(p.Z for p in pts)), unit)
            out["section_box_max"] = _pt(DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts),
                                                max(p.Z for p in pts)), unit)
    if isinstance(view, DB.ViewPlan):
        try:
            out["view_range"] = _range_info(doc, view, unit)
        except Exception as e:
            out["view_range_error"] = normalize_string(text_type(e))
    far = view.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR)
    if far is not None and far.HasValue:
        out["far_clip_offset"] = U.from_internal(far.AsDouble(), unit, 1)
    return out


def _scope_boxes(doc):
    return list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)
                .WhereElementIsNotElementType())


def _scope_box_of(doc, view):
    p = view.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
    if p is None or not is_valid_id(p.AsElementId()):
        return p, None
    return p, doc.GetElement(p.AsElementId())


def _set_crop(ctx, view):
    doc = ctx.doc
    box = _model_box(ctx)
    sb_param, sb = _scope_box_of(doc, view)
    wanted = ctx.get("scope_box")
    if wanted is not None:
        # assign an existing scope box (the Revit API cannot create one), or 'none' to detach
        if sb_param is None or sb_param.IsReadOnly:
            raise RvtssError("View '{}' cannot use a scope box".format(normalize_string(view.Name)), status=409)
        if text_type(wanted).strip().lower() in ("none", ""):
            sb_param.Set(DB.ElementId.InvalidElementId)
        else:
            key = text_type(wanted).strip().lower()
            boxes = _scope_boxes(doc)
            match = [b for b in boxes if normalize_string(b.Name).lower() == key or text_type(id_int(b)) == key]
            if not match:
                raise core.not_found("Scope box", wanted, [b.Name for b in boxes],
                                     hint="Scope boxes are drawn in Revit: run_revit_command('ScopeBox').")
            if box is not None:
                raise RvtssError("Give either scope_box or a crop box (element_ids / min, max), not both")
            sb_param.Set(match[0].Id)
        sb = None
    if box is not None and sb is not None:
        # Revit silently ignores CropBox while a scope box controls the crop
        raise RvtssError("The crop of '{}' is controlled by scope box '{}'".format(
            normalize_string(view.Name), normalize_string(sb.Name)), status=409,
            hint="Pass scope_box='none' to detach it in the same call, or edit the scope box in Revit.")
    if box is not None:
        bb = view.CropBox
        if bb is None:
            raise RvtssError("View '{}' has no crop region".format(normalize_string(view.Name)), status=409)
        inv = bb.Transform.Inverse
        pts = [inv.OfPoint(p) for p in _corners(box[0], box[1])]
        # keep the depth (local Z) of the existing crop box: only the region in the view plane changes
        new = DB.BoundingBoxXYZ()
        new.Transform = bb.Transform
        new.Min = DB.XYZ(min(p.X for p in pts), min(p.Y for p in pts), bb.Min.Z)
        new.Max = DB.XYZ(max(p.X for p in pts), max(p.Y for p in pts), bb.Max.Z)
        view.CropBox = new
        view.CropBoxActive = True
    if ctx.get("crop_active") is not None:
        view.CropBoxActive = ctx.bool("crop_active")
    if ctx.get("crop_visible") is not None:
        view.CropBoxVisible = ctx.bool("crop_visible")
    if ctx.get("annotation_crop") is not None:
        p = view.get_Parameter(DB.BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
        if p is None or p.IsReadOnly:
            raise RvtssError("This view has no annotation crop", status=409)
        p.Set(1 if ctx.bool("annotation_crop") else 0)


def _set_section_box(ctx, view):
    if not isinstance(view, DB.View3D):
        raise RvtssError("A section box needs a 3D view ('{}' is {})".format(normalize_string(view.Name),
                                                                           view.ViewType), status=409)
    box = _model_box(ctx)
    if box is not None:
        bb = DB.BoundingBoxXYZ()
        bb.Min, bb.Max = box[0], box[1]
        view.SetSectionBox(bb)
        view.IsSectionBoxActive = True
    if ctx.get("enabled") is not None:
        view.IsSectionBoxActive = ctx.bool("enabled")
    elif box is None:
        raise RvtssError("Give element_ids, min/max or enabled")


def _set_view_range(ctx, view):
    if not isinstance(view, DB.ViewPlan):
        raise RvtssError("A view range needs a plan view ('{}' is {})".format(normalize_string(view.Name),
                                                                            view.ViewType), status=409)
    vr = view.GetViewRange()
    changed = []
    for key, plane in PLANES:
        if ctx.get(key) is None:
            continue
        p = getattr(DB.PlanViewPlane, plane)
        if ctx.get(key + "_level"):
            vr.SetLevelId(p, core.find_level(ctx.doc, ctx.get(key + "_level")).Id)
        vr.SetOffset(p, U.to_internal(ctx.float(key), ctx.unit))
        changed.append(key)
    if not changed:
        raise RvtssError("Give at least one of top, cut, bottom, view_depth (offsets from the plane's level)")
    view.SetViewRange(vr)


def _set_far_clip(ctx, view):
    if ctx.get("far_clip_offset") is not None:
        p = view.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR)
        if p is None or p.IsReadOnly:
            raise RvtssError("View '{}' has no editable far clip offset".format(normalize_string(view.Name)),
                             status=409, hint="Sections, elevations and callouts have one; turn far clipping on.")
        p.Set(U.to_internal(ctx.float("far_clip_offset"), ctx.unit))
    if ctx.get("far_clipping"):
        mode = FAR_CLIP.get(ctx.get("far_clipping"))
        if mode is None:
            raise RvtssError("far_clipping must be one of: " + ", ".join(sorted(FAR_CLIP)))
        p = view.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING)
        if p is None or p.IsReadOnly:
            raise RvtssError("View '{}' has no far clipping setting".format(normalize_string(view.Name)), status=409)
        p.Set(mode)
    if ctx.get("far_clip_offset") is None and not ctx.get("far_clipping"):
        raise RvtssError("Give far_clip_offset and/or far_clipping")


_EXTENT_ACTIONS = {"set_crop": _set_crop, "set_section_box": _set_section_box, "set_view_range": _set_view_range,
                   "set_far_clip": _set_far_clip}


def view_extents(ctx):
    doc = ctx.doc
    action = ctx.get("action", "get")
    view = core.find_view(doc, ctx.get("view", "active"), uidoc=ctx.uidoc)
    if action == "get":
        return _extents_info(ctx, view)
    if action not in _EXTENT_ACTIONS:
        raise RvtssError("action must be get, " + ", ".join(sorted(_EXTENT_ACTIONS)))
    if view.IsTemplate:
        raise RvtssError("View templates have no extents", status=409)
    dry = ctx.dry_run

    def run():
        _EXTENT_ACTIONS[action](ctx, view)
        doc.Regenerate()
        return _extents_info(ctx, view)

    res, fails = core.run_transaction(doc, "View extents: " + action, run, dry_run=dry)
    out = core.commit_result(res, fails, dry)
    if is_valid_id(view.ViewTemplateId):
        out.setdefault("warnings", []).append("View uses template '{}'; it may control these settings.".format(
            normalize_string(doc.GetElement(view.ViewTemplateId).Name)))
    return out


# ---------------------------------------------------------------------- templates
def _templates(doc):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if v.IsTemplate]


def _find_template(doc, ref):
    key = text_type(ref).strip().lower()
    for t in _templates(doc):
        if normalize_string(t.Name).lower() == key or text_type(id_int(t)) == key:
            return t
    raise core.not_found("View template", ref, [t.Name for t in _templates(doc)])


def _views_using(doc, template):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
            if not v.IsTemplate and v.ViewTemplateId == template.Id]


def _param_name(doc, template, pid):
    """Name of a template-controlled parameter id (built-in ids are negative, so look on the view)."""
    for p in template.Parameters:
        if p.Id == pid:
            return normalize_string(p.Definition.Name)
    return text_type(id_int(pid))


def _template_params(doc, template):
    off = set(id_int(i) for i in template.GetNonControlledTemplateParameterIds())
    out = []
    for pid in template.GetTemplateParameterIds():
        out.append({"name": _param_name(doc, template, pid), "included": id_int(pid) not in off})
    return sorted(out, key=lambda d: d["name"])


def view_templates(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    dry = ctx.dry_run
    if action == "list":
        items = []
        for t in _templates(doc):
            item = {"id": id_int(t), "name": normalize_string(t.Name), "view_type": str(t.ViewType),
                    "used_by": len(_views_using(doc, t))}
            if ctx.bool("parameters", False):
                item["parameters"] = _template_params(doc, t)
            items.append(item)
        return {"count": len(items), "templates": sorted(items, key=lambda d: d["name"]),
                "unused": sorted(i["name"] for i in items if not i["used_by"])}

    if action == "create_from_view":
        src = core.find_view(doc, ctx.get("view", "active"), uidoc=ctx.uidoc)
        if not src.IsViewValidForTemplateCreation():
            raise RvtssError("A template cannot be created from '{}' ({})".format(normalize_string(src.Name),
                                                                               src.ViewType), status=409)

        def run():
            t = src.CreateViewTemplate()
            if ctx.get("name"):
                t.Name = ctx.get("name")
            return {"template_id": id_int(t), "name": normalize_string(t.Name), "view_type": str(t.ViewType)}

        res, fails = core.run_transaction(doc, "Create view template", run, dry_run=dry)
        return core.commit_result(res, fails, dry)

    if action in ("apply", "remove"):
        views = [core.find_view(doc, v, uidoc=ctx.uidoc) for v in (ctx.list("views") or ["active"])]
        template = _find_template(doc, ctx.require("template")) if action == "apply" else None
        once = ctx.bool("once", False)
        preview = core.confirm_gate(ctx, len(views), "manage_view_templates")
        dryp = preview or dry

        def one(v):
            if template is None:
                v.ViewTemplateId = DB.ElementId.InvalidElementId
            elif once:
                v.ApplyViewTemplateParameters(template)  # copy the settings, keep the view unassigned
            else:
                if not v.IsValidViewTemplate(template.Id):
                    raise RvtssError("template '{}' ({}) does not fit view '{}' ({})".format(
                        normalize_string(template.Name), template.ViewType, normalize_string(v.Name), v.ViewType))
                v.ViewTemplateId = template.Id
            return {"view_id": id_int(v), "view": normalize_string(v.Name)}

        def run():
            return {"results": core.batch(doc, views, one, atomic=ctx.bool("atomic", True))}

        res, fails = core.run_transaction(doc, "View template: " + action, run, dry_run=dryp)
        out = core.commit_result(res, fails, dryp, {
            "template": normalize_string(template.Name) if template is not None else None, "applied_once": once})
        return core.preview_status(out, preview)

    template = _find_template(doc, ctx.require("template"))
    if action == "duplicate":
        def run():
            # View.Duplicate refuses templates ("View cannot be duplicated"): copy the element instead
            new_ids = list(DB.ElementTransformUtils.CopyElement(doc, template.Id, DB.XYZ.Zero))
            if not new_ids:
                raise RvtssError("Revit did not copy the template", status=409)
            t = doc.GetElement(new_ids[0])
            if ctx.get("name"):
                t.Name = ctx.get("name")
            return {"template_id": id_int(t), "name": normalize_string(t.Name)}

        res, fails = core.run_transaction(doc, "Duplicate view template", run, dry_run=dry)
        return core.commit_result(res, fails, dry)

    if action == "delete":
        users = _views_using(doc, template)
        forced = bool(users) and not ctx.confirmed and not dry
        dryd = forced or dry

        name = normalize_string(template.Name)
        user_ids = [id_int(v) for v in users[:100]]

        def run():
            doc.Delete(template.Id)
            return {"deleted": name, "views_that_used_it": len(users), "view_ids": user_ids}

        res, fails = core.run_transaction(doc, "Delete view template", run, dry_run=dryd)
        out = core.commit_result(res, fails, dryd, {"template": name})
        return core.preview_status(out, forced)

    if action == "set_included":
        include = set(text_type(n).strip().lower() for n in ctx.list("include"))
        exclude = set(text_type(n).strip().lower() for n in ctx.list("exclude"))
        if not include and not exclude:
            raise RvtssError("Give 'include' and/or 'exclude' (parameter names from action='list', parameters=true)")
        from System.Collections.Generic import List

        ids = list(template.GetTemplateParameterIds())
        names = dict((_param_name(doc, template, i).lower(), i) for i in ids)
        unknown = sorted(n for n in (include | exclude) if n not in names)
        if unknown:
            raise RvtssError("Not template parameters: {}".format(", ".join(unknown)), status=404,
                             available=sorted(names))
        off = dict((id_int(i), i) for i in template.GetNonControlledTemplateParameterIds())
        for n in include:
            off.pop(id_int(names[n]), None)
        for n in exclude:
            off[id_int(names[n])] = names[n]

        def run():
            lst = List[DB.ElementId]()
            for i in off.values():
                lst.Add(i)
            template.SetNonControlledTemplateParameterIds(lst)
            return {"template": normalize_string(template.Name), "parameters": _template_params(doc, template)}

        res, fails = core.run_transaction(doc, "View template parameters", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    raise RvtssError("action must be list, create_from_view, duplicate, apply, remove, delete or set_included")


# ---------------------------------------------------------------------- viewports
ROTATION = {"none": "None", "clockwise": "Clockwise", "counterclockwise": "Counterclockwise"}


def _sheet(doc, ref):
    key = text_type(ref).strip().lower()
    sheets = list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet))
    for s in sheets:
        if text_type(id_int(s)) == key or normalize_string(s.SheetNumber).lower() == key:
            return s
    for s in sheets:
        if normalize_string(s.Name).lower() == key:
            return s
    raise core.not_found("Sheet", ref, [s.SheetNumber for s in sheets], hint="Pass the sheet number or id.")


def _viewport_info(doc, vp, unit):
    view = doc.GetElement(vp.ViewId)
    c = vp.GetBoxCenter()
    num = vp.get_Parameter(DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
    out = {"viewport_id": id_int(vp), "view_id": id_int(vp.ViewId),
           "view": normalize_string(view.Name) if view is not None else None,
           "center": [U.from_internal(c.X, unit, 1), U.from_internal(c.Y, unit, 1)],
           "type": normalize_string(get_element_name(doc.GetElement(vp.GetTypeId()))),
           "detail_number": num.AsString() if num is not None else None}
    try:
        out["rotation"] = str(vp.Rotation).lower()
    except Exception:
        pass
    return out


def _viewport(doc, ref):
    vp = core.get_element(doc, ref, "Viewport")
    if not isinstance(vp, DB.Viewport):
        raise RvtssError("Element {} is not a viewport".format(ref),
                         hint="manage_viewports(action='list', sheet=...) lists viewport ids.")
    return vp


def viewports(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    unit = ctx.unit
    dry = ctx.dry_run
    if action == "list":
        sheet = _sheet(doc, ctx.require("sheet"))
        vps = [_viewport_info(doc, doc.GetElement(i), unit) for i in sheet.GetAllViewports()]
        scheds = []
        for si in DB.FilteredElementCollector(doc, sheet.Id).OfClass(DB.ScheduleSheetInstance):
            if si.IsTitleblockRevisionSchedule:
                continue
            sv = doc.GetElement(si.ScheduleId)
            scheds.append({"instance_id": id_int(si), "schedule": normalize_string(sv.Name) if sv else None,
                           "point": [U.from_internal(si.Point.X, unit, 1), U.from_internal(si.Point.Y, unit, 1)]})
        types = {}
        for i in sheet.GetAllViewports():
            for tid in doc.GetElement(i).GetValidTypes():
                types[id_int(tid)] = normalize_string(get_element_name(doc.GetElement(tid)))
            break
        return {"sheet": sheet.SheetNumber, "sheet_id": id_int(sheet), "sheet_name": normalize_string(sheet.Name),
                "viewports": vps, "schedules": scheds, "viewport_types": sorted(set(types.values())), "unit": unit}

    vp = _viewport(doc, ctx.require("viewport_id"))

    def run():
        if action == "move":
            x, y, _z = U.point_from(ctx.require("location"), unit)
            vp.SetBoxCenter(DB.XYZ(x, y, 0))
        elif action == "set_type":
            want = text_type(ctx.require("type")).strip().lower()
            match = None
            names = []
            for tid in vp.GetValidTypes():
                nm = normalize_string(get_element_name(doc.GetElement(tid)))
                names.append(nm)
                if nm.lower() == want or text_type(id_int(tid)) == want:
                    match = tid
            if match is None:
                raise core.not_found("Viewport type", ctx.get("type"), names)
            vp.ChangeTypeId(match)
        elif action == "set_detail_number":
            p = vp.get_Parameter(DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
            if p is None or p.IsReadOnly:
                raise RvtssError("This viewport's detail number cannot be changed", status=409)
            p.Set(text_type(ctx.require("detail_number")))
        elif action == "rotate":
            rot = ROTATION.get(ctx.get("rotation", "none"))
            if rot is None:
                raise RvtssError("rotation must be none, clockwise or counterclockwise")
            vp.Rotation = getattr(DB.ViewportRotation, rot)
        elif action == "remove":
            info = _viewport_info(doc, vp, unit)
            sheet = doc.GetElement(vp.SheetId)
            sheet.DeleteViewport(vp)
            return {"removed": info}
        else:
            raise RvtssError("action must be list, move, set_type, set_detail_number, rotate or remove")
        return {"viewport": _viewport_info(doc, vp, unit)}

    res, fails = core.run_transaction(doc, "Viewport: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry, {"unit": unit})


def register_view_setup_routes(api):
    @api.route("/views/extents/", methods=["POST"])
    def views_extents_route(doc, uidoc, request):
        return handle(doc, request, view_extents, uidoc=uidoc)

    @api.route("/views/templates/", methods=["POST"])
    def views_templates_route(doc, uidoc, request):
        return handle(doc, request, view_templates, uidoc=uidoc)

    @api.route("/sheets/viewports/", methods=["POST"])
    def sheets_viewports_route(doc, request):
        return handle(doc, request, viewports)

    logger.info("RVTSS view setup routes registered")
