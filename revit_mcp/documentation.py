# -*- coding: UTF-8 -*-
"""Views, graphics, sheets, schedules, renaming, groups and assemblies (RVTSS).

Routes:
    POST /views/create/      floor/ceiling/structural plans, 3D (optionally boxed), sections, elevations,
                             drafting views, duplicates
    POST /views/graphics/    overrides, hide/unhide, isolate, category visibility, templates, scale/detail
    POST /sheets/manage/     create sheets, place views/schedules, list title blocks
    POST /schedules/create/  schedule with fields, sorting and filters
    POST /batch_rename/      views, sheets, levels, grids, families, types, rooms, materials (find/replace/regex)
    POST /groups/manage/     list / create / ungroup model groups
    POST /assemblies/manage/ list / create / add or remove members / rename / create views + sheet
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, is_valid_id, make_id
from .pure import units as U
from .pure import textfmt
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


def _vft(doc, family, name=None):
    types = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType) if t.ViewFamily == family]
    if name:
        for t in types:
            if normalize_string(t.Name).lower() == name.lower():
                return t
        raise core.not_found("View family type", name, [t.Name for t in types])
    if not types:
        raise RvtssError("No view family type for {}".format(family), status=409)
    return types[0]


def _template(doc, name):
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if v.IsTemplate and (normalize_string(v.Name).lower() == text_type(name).lower() or text_type(id_int(v)) == text_type(name)):
            return v
    raise core.not_found("View template", name, [v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
                                                if v.IsTemplate])


def _bbox_of(doc, ids, unit, margin):
    mins, maxs = None, None
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
        raise RvtssError("Elements have no bounding box")
    m = U.to_internal(margin, unit)
    box = DB.BoundingBoxXYZ()
    box.Min = DB.XYZ(mins.X - m, mins.Y - m, mins.Z - m)
    box.Max = DB.XYZ(maxs.X + m, maxs.Y + m, maxs.Z + m)
    return box


def create_view(ctx):
    doc = ctx.doc
    core.require_project(doc)
    kind = ctx.require("kind")
    unit = ctx.unit
    dry = ctx.dry_run

    def run():
        if kind == "area_plan":
            # area plans need an area scheme, not a view family type
            level = core.find_level(doc, ctx.require("level"))
            schemes = list(DB.FilteredElementCollector(doc).OfClass(DB.AreaScheme))
            wanted = (ctx.get("area_scheme") or "").lower()
            scheme = None
            for sc in schemes:
                if not wanted or normalize_string(sc.Name).lower() == wanted:
                    scheme = sc
                    break
            if scheme is None:
                raise core.not_found("Area scheme", ctx.get("area_scheme"), [sc.Name for sc in schemes])
            v = DB.ViewPlan.CreateAreaPlan(doc, scheme.Id, level.Id)
        elif kind in ("floor_plan", "ceiling_plan", "structural_plan"):
            fam = {"floor_plan": DB.ViewFamily.FloorPlan, "ceiling_plan": DB.ViewFamily.CeilingPlan,
                   "structural_plan": DB.ViewFamily.StructuralPlan}[kind]
            level = core.find_level(doc, ctx.require("level"))
            v = DB.ViewPlan.Create(doc, _vft(doc, fam, ctx.get("view_family_type")).Id, level.Id)
        elif kind == "three_d":
            v = DB.View3D.CreateIsometric(doc, _vft(doc, DB.ViewFamily.ThreeDimensional, ctx.get("view_family_type")).Id)
            if ctx.list("element_ids"):
                v.SetSectionBox(_bbox_of(doc, ctx.list("element_ids"), unit, ctx.float("margin", 500)))
        elif kind == "section":
            ids = ctx.list("element_ids")
            if not ids:
                raise RvtssError("section needs element_ids to frame (a section box is fitted around them)")
            bb = _bbox_of(doc, ids, unit, ctx.float("margin", 500))
            direction = ctx.get("looking", "north")
            dirs = {"north": DB.XYZ(0, 1, 0), "south": DB.XYZ(0, -1, 0), "east": DB.XYZ(1, 0, 0), "west": DB.XYZ(-1, 0, 0)}
            if direction not in dirs:
                raise RvtssError("looking must be north, south, east or west")
            vd = dirs[direction]
            up = DB.XYZ.BasisZ
            right = vd.CrossProduct(up)  # right-handed: right x up = -view direction
            center = (bb.Min + bb.Max) * 0.5
            half_w = abs((bb.Max - bb.Min).DotProduct(right)) / 2.0
            half_d = abs((bb.Max - bb.Min).DotProduct(vd)) / 2.0
            t = DB.Transform.Identity
            t.Origin = center
            t.BasisX = right
            t.BasisY = up
            t.BasisZ = vd.Negate()
            box = DB.BoundingBoxXYZ()
            box.Transform = t
            box.Min = DB.XYZ(-half_w, bb.Min.Z - center.Z, -half_d)
            box.Max = DB.XYZ(half_w, bb.Max.Z - center.Z, half_d)
            v = DB.ViewSection.CreateSection(doc, _vft(doc, DB.ViewFamily.Section, ctx.get("view_family_type")).Id, box)
        elif kind == "elevation":
            plan = core.find_view(doc, ctx.require("plan_view"))
            x, y, z = U.point_from(ctx.require("point"), unit)
            marker = DB.ElevationMarker.CreateElevationMarker(
                doc, _vft(doc, DB.ViewFamily.Elevation, ctx.get("view_family_type")).Id, DB.XYZ(x, y, z),
                ctx.int("scale", 100))
            idx = {"north": 1, "east": 2, "south": 3, "west": 0}.get(ctx.get("facing", "north"), 1)
            v = marker.CreateElevation(doc, plan.Id, idx)
        elif kind == "drafting":
            v = DB.ViewDrafting.Create(doc, _vft(doc, DB.ViewFamily.Drafting, ctx.get("view_family_type")).Id)
        elif kind == "callout":
            # v2.4: a callout (detail view by default) of a rectangle in a plan, section or elevation
            parent = core.find_view(doc, ctx.require("source_view"))
            a = U.point_from(ctx.require("min"), unit)
            b = U.point_from(ctx.require("max"), unit)
            wanted = ctx.get("view_family_type")
            vft = None
            if wanted:
                for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
                    if normalize_string(t.Name).lower() == wanted.lower():
                        vft = t
                        break
                if vft is None:
                    raise core.not_found("View family type", wanted, [
                        t.Name for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)])
            else:
                vft = _vft(doc, DB.ViewFamily.Detail)
            v = DB.ViewSection.CreateCallout(doc, parent.Id, vft.Id, DB.XYZ(a[0], a[1], a[2]),
                                             DB.XYZ(b[0], b[1], b[2]))
        elif kind == "legend":
            # the Revit API cannot create a legend from nothing; an existing legend is duplicated
            legends = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.View)
                       if x.ViewType == DB.ViewType.Legend and not x.IsTemplate]
            if ctx.get("source_view"):
                src = core.find_view(doc, ctx.get("source_view"))
                if src.ViewType != DB.ViewType.Legend:
                    raise RvtssError("source_view '{}' is not a legend".format(normalize_string(src.Name)))
            elif legends:
                src = legends[0]
            else:
                raise RvtssError("This model has no legend to copy; the Revit API cannot create the first one",
                                 status=409, hint="Create one legend in Revit (View > Legends > Legend, or "
                                                  "run_revit_command), then call this again.")
            opt = DB.ViewDuplicateOption.WithDetailing if ctx.get("duplicate_option") == "with_detailing" \
                else DB.ViewDuplicateOption.Duplicate
            v = doc.GetElement(src.Duplicate(opt))
        elif kind == "duplicate":
            src = core.find_view(doc, ctx.require("source_view"))
            opt = {"duplicate": DB.ViewDuplicateOption.Duplicate, "with_detailing": DB.ViewDuplicateOption.WithDetailing,
                   "as_dependent": DB.ViewDuplicateOption.AsDependent}[ctx.get("duplicate_option", "duplicate")]
            if not src.CanViewBeDuplicated(opt):
                raise RvtssError("View '{}' cannot be duplicated with option {}".format(src.Name, opt), status=409)
            v = doc.GetElement(src.Duplicate(opt))
        else:
            raise RvtssError("kind must be floor_plan, ceiling_plan, structural_plan, area_plan, three_d, section, "
                             "elevation, drafting, callout, legend or duplicate")
        if ctx.get("name"):
            v.Name = ctx.get("name")
        if ctx.get("template"):
            v.ViewTemplateId = _template(doc, ctx.get("template")).Id
        if ctx.get("scale") and kind != "elevation":
            try:
                v.Scale = ctx.int("scale")
            except Exception as e:
                ctx.warn("Scale not applied: {}".format(e))
        if ctx.get("detail_level"):
            v.DetailLevel = getattr(DB.ViewDetailLevel, ctx.get("detail_level").capitalize())
        return {"view_id": id_int(v), "name": normalize_string(v.Name), "view_type": str(v.ViewType)}

    res, fails = core.run_transaction(doc, "Create view", run, dry_run=dry)
    return core.commit_result(res, fails, dry)


def _color(hexstr):
    h = hexstr.lstrip("#")
    if len(h) != 6:
        raise RvtssError("Colors must be hex like '#FF0000'")
    return DB.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _solid_fill(doc):
    for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except Exception:
            continue
    return None


def view_graphics(ctx):
    doc = ctx.doc
    action = ctx.require("action")
    view = core.find_view(doc, ctx.get("view", "active"), uidoc=ctx.uidoc)
    dry = ctx.dry_run
    ids = ctx.list("element_ids")
    templ_warning = None
    if is_valid_id(view.ViewTemplateId) and action in ("override", "category_hidden", "hide"):
        templ_warning = ("View uses template '{}'; settings it controls may be overridden or locked.".format(
            doc.GetElement(view.ViewTemplateId).Name))

    def run():
        if action == "override":
            ogs = DB.OverrideGraphicSettings()
            if ctx.get("color"):
                c = _color(ctx.get("color"))
                ogs.SetProjectionLineColor(c)
                ogs.SetCutLineColor(c)
                fill = _solid_fill(doc)
                if fill is not None and ctx.bool("fill", True):
                    try:
                        ogs.SetSurfaceForegroundPatternId(fill)
                        ogs.SetSurfaceForegroundPatternColor(c)
                    except AttributeError:  # Revit < 2019
                        ogs.SetProjectionFillPatternId(fill)
                        ogs.SetProjectionFillColor(c)
            if ctx.get("line_weight"):
                ogs.SetProjectionLineWeight(ctx.int("line_weight", 1, 1, 16))
            if ctx.get("halftone") is not None:
                ogs.SetHalftone(ctx.bool("halftone"))
            if ctx.get("transparency") is not None:
                ogs.SetSurfaceTransparency(ctx.int("transparency", 0, 0, 100))
            targets = core.get_elements(doc, ids) if ids else []
            for e in targets:
                view.SetElementOverrides(e.Id, ogs)
            for cat in ctx.list("categories"):
                view.SetCategoryOverrides(core.resolve_category(doc, cat).Id, ogs)
            return {"overridden_elements": len(targets), "overridden_categories": ctx.list("categories")}
        if action == "reset":
            for e in core.get_elements(doc, ids):
                view.SetElementOverrides(e.Id, DB.OverrideGraphicSettings())
            return {"reset_elements": len(ids)}
        if action in ("hide", "unhide"):
            lst = core.to_id_list([e.Id for e in core.get_elements(doc, ids)])
            (view.HideElements if action == "hide" else view.UnhideElements)(lst)
            return {action: len(ids)}
        if action in ("temporary_isolate", "temporary_hide"):
            lst = core.to_id_list([e.Id for e in core.get_elements(doc, ids)])
            (view.IsolateElementsTemporary if action == "temporary_isolate" else view.HideElementsTemporary)(lst)
            return {action: len(ids)}
        if action == "reset_temporary":
            view.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
            return {"reset_temporary": True}
        if action == "category_hidden":
            done = []
            for cat in ctx.list("categories"):
                c = core.resolve_category(doc, cat)
                view.SetCategoryHidden(c.Id, ctx.bool("hidden", True))
                done.append(c.Name)
            return {"categories": done, "hidden": ctx.bool("hidden", True)}
        if action == "apply_template":
            view.ViewTemplateId = _template(doc, ctx.require("template")).Id
            return {"template": ctx.get("template")}
        if action == "remove_template":
            view.ViewTemplateId = DB.ElementId.InvalidElementId
            return {"template": None}
        if action == "set_scale":
            view.Scale = ctx.int("scale")
            return {"scale": view.Scale}
        if action == "set_detail_level":
            view.DetailLevel = getattr(DB.ViewDetailLevel, ctx.require("detail_level").capitalize())
            return {"detail_level": str(view.DetailLevel)}
        raise RvtssError("Unknown action '{}'".format(action))

    res, fails = core.run_transaction(doc, "View graphics: " + action, run, dry_run=dry)
    out = core.commit_result(res, fails, dry, {"view": normalize_string(view.Name), "view_id": id_int(view)})
    if templ_warning:
        out.setdefault("warnings", []).append(templ_warning)
    return out


def sheets_manage(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.require("action")
    unit = ctx.unit
    dry = ctx.dry_run
    if action == "list_titleblocks":
        tbs = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType()
        return {"title_blocks": [{"id": id_int(t), "family": normalize_string(t.FamilyName),
                                  "type": normalize_string(get_element_name(t))} for t in tbs]}

    def run():
        if action == "create":
            results = []
            for s in ctx.list("sheets") or [{"number": ctx.get("number"), "name": ctx.get("name")}]:
                tb = s.get("title_block") or ctx.get("title_block")
                if tb is not None:
                    tbt = core.find_type(doc, type_id=tb) if text_type(tb).isdigit() else \
                        core.find_type(doc, family=None, type_name=tb, category="OST_TitleBlocks")
                    tbid = tbt.Id
                else:
                    tbt = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
                        .WhereElementIsElementType().FirstElement()
                    tbid = tbt.Id if tbt else DB.ElementId.InvalidElementId
                sh = DB.ViewSheet.Create(doc, tbid)
                if s.get("number"):
                    sh.SheetNumber = text_type(s["number"])
                if s.get("name"):
                    sh.Name = s["name"]
                results.append({"sheet_id": id_int(sh), "number": sh.SheetNumber, "name": sh.Name})
            return {"sheets": results}
        if action == "place_view":
            sheet = core.get_element(doc, ctx.require("sheet_id"), "Sheet")
            if not isinstance(sheet, DB.ViewSheet):
                raise RvtssError("sheet_id is not a sheet")
            view = core.find_view(doc, ctx.require("view"))
            x, y, _z = U.point_from(ctx.get("location") or [400, 300], unit)
            pt = DB.XYZ(x, y, 0)
            if isinstance(view, DB.ViewSchedule):
                inst = DB.ScheduleSheetInstance.Create(doc, sheet.Id, view.Id, pt)
                return {"schedule_instance_id": id_int(inst)}
            if not DB.Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id):
                raise RvtssError("View '{}' cannot be placed (already on a sheet, a template, or empty)".format(view.Name),
                                 status=409, hint="Duplicate the view first with create_view(kind='duplicate').")
            vp = DB.Viewport.Create(doc, sheet.Id, view.Id, pt)
            return {"viewport_id": id_int(vp), "view": normalize_string(view.Name), "sheet": sheet.SheetNumber}
        raise RvtssError("action must be create, place_view or list_titleblocks")

    res, fails = core.run_transaction(doc, "Sheets: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry)


SCHEDULE_KINDS = ("category", "key", "material_takeoff", "sheet_list", "view_list", "note_block")


def create_schedule(ctx):
    doc = ctx.doc
    core.require_project(doc)
    kind = ctx.get("kind", "category")
    if kind not in SCHEDULE_KINDS:
        raise RvtssError("kind must be one of: " + ", ".join(SCHEDULE_KINDS))
    needs_cat = kind in ("category", "key", "material_takeoff")
    cat = core.resolve_category(doc, ctx.require("category")) if needs_cat else None
    fields = ctx.list("fields")
    if not fields and kind != "key":
        raise RvtssError("'fields' (parameter names) is required")
    family = None
    if kind == "note_block":
        want = text_type(ctx.require("family")).strip().lower()
        fams = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.Family)]
        family = next((f for f in fams if normalize_string(f.Name).lower() == want), None)
        if family is None:
            raise core.not_found("Annotation family", ctx.get("family"), [
                f.Name for f in fams if f.FamilyCategory is not None and
                id_int(f.FamilyCategory.Id) == int(DB.BuiltInCategory.OST_GenericAnnotation)])
    dry = ctx.dry_run

    def run():
        if kind == "key":
            sched = DB.ViewSchedule.CreateKeySchedule(doc, cat.Id)
        elif kind == "material_takeoff":
            sched = DB.ViewSchedule.CreateMaterialTakeoff(doc, cat.Id)
        elif kind == "sheet_list":
            sched = DB.ViewSchedule.CreateSheetList(doc)
        elif kind == "view_list":
            sched = DB.ViewSchedule.CreateViewList(doc)
        elif kind == "note_block":
            sched = DB.ViewSchedule.CreateNoteBlock(doc, family.Id)
        else:
            sched = DB.ViewSchedule.CreateSchedule(doc, cat.Id)
        if ctx.get("name"):
            sched.Name = ctx.get("name")
        definition = sched.Definition
        available = dict((normalize_string(sf.GetName(doc)).lower(), sf) for sf in definition.GetSchedulableFields())
        added, missing = {}, []
        for f in fields:
            sf = available.get(f.lower())
            if sf is None:
                missing.append(f)
                continue
            added[f] = definition.AddField(sf)
        if missing and ctx.bool("strict", True):
            raise RvtssError("Fields not schedulable for {}: {}".format(cat.Name if cat else kind, missing), status=404,
                             available_sample=sorted(available)[:60])
        for s in ctx.list("sort_by"):
            fld = added.get(s)
            if fld is not None:
                definition.AddSortGroupField(DB.ScheduleSortGroupField(fld.FieldId))
        for flt in ctx.list("filters"):
            fld = added.get(flt.get("field"))
            if fld is None:
                raise RvtssError("Filter field '{}' must also be in fields".format(flt.get("field")))
            ftype = getattr(DB.ScheduleFilterType, flt.get("type", "Equal"))
            val = flt.get("value", "")
            # ScheduleFilter takes a double (internal units) for numeric/dimensional fields,
            # an int for integer/yes-no fields and a string for text fields
            if isinstance(val, bool):
                val = 1 if val else 0
            elif isinstance(val, float) or (isinstance(val, int) and flt.get("unit")):
                val = U.to_internal(val, flt["unit"]) if flt.get("unit") else float(val)
            elif not isinstance(val, int):
                val = text_type(val)
            definition.AddFilter(DB.ScheduleFilter(fld.FieldId, ftype, val))
        definition.IsItemized = ctx.bool("itemized", True)
        return {"schedule_id": id_int(sched), "name": normalize_string(sched.Name), "kind": kind,
                "fields": list(added), "missing_fields": missing}

    res, fails = core.run_transaction(doc, "Create schedule", run, dry_run=dry)
    return core.commit_result(res, fails, dry)


RENAME_TARGETS = {
    "views": lambda doc: [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
                          if not v.IsTemplate and v.ViewType not in (DB.ViewType.Internal, DB.ViewType.ProjectBrowser,
                                                                      DB.ViewType.SystemBrowser, DB.ViewType.DrawingSheet)],
    "view_templates": lambda doc: [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if v.IsTemplate],
    "sheets": lambda doc: list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)),
    "levels": lambda doc: list(DB.FilteredElementCollector(doc).OfClass(DB.Level)),
    "grids": lambda doc: list(DB.FilteredElementCollector(doc).OfClass(DB.Grid)),
    "families": lambda doc: [f for f in DB.FilteredElementCollector(doc).OfClass(DB.Family) if f.IsEditable or f.IsInPlace],
    "family_types": lambda doc: list(DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)),
    "system_types": lambda doc: [t for t in DB.FilteredElementCollector(doc).WhereElementIsElementType()
                                 if not isinstance(t, DB.FamilySymbol) and isinstance(t, (DB.WallType, DB.FloorType,
                                                                                         DB.RoofType, DB.CeilingType))],
    "materials": lambda doc: list(DB.FilteredElementCollector(doc).OfClass(DB.Material)),
    "rooms": lambda doc: list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms)
                              .WhereElementIsNotElementType()),
}


def _name_of(e, target, field):
    if target == "sheets" and field == "number":
        return normalize_string(e.SheetNumber)
    if target == "rooms":
        return normalize_string(e.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() or "")
    return normalize_string(get_element_name(e) or "")


def _set_name(e, target, field, value):
    if target == "sheets" and field == "number":
        e.SheetNumber = value
    elif target == "rooms":
        e.get_Parameter(DB.BuiltInParameter.ROOM_NAME).Set(value)
    else:
        e.Name = value


def _uniqueness_scope(e, target, field):
    """Key within which Revit requires names to be unique; None = no uniqueness rule."""
    if target == "rooms" or (target == "sheets" and field == "name"):
        return None
    if target == "family_types":
        return ("family", id_int(e.Family.Id))
    if target == "system_types":
        return ("class", e.GetType().Name)
    if target in ("views", "view_templates"):
        return ("view_type", str(e.ViewType))
    return ("all",)


def batch_rename(ctx):
    import re

    doc = ctx.doc
    target = ctx.require("target")
    if target not in RENAME_TARGETS:
        raise RvtssError("target must be one of: " + ", ".join(sorted(RENAME_TARGETS)))
    field = ctx.get("field", "name")
    include = ctx.get("include_regex")
    rx = re.compile(include) if include else None
    ids = set(ctx.list("element_ids"))
    elements = [e for e in RENAME_TARGETS[target](doc) if (not ids or id_int(e) in ids)]
    elements = [e for e in elements if rx is None or rx.search(_name_of(e, target, field))]
    plan, conflicts = [], []
    existing = {}
    for e in RENAME_TARGETS[target](doc):
        scope = _uniqueness_scope(e, target, field)
        if scope is not None:
            existing.setdefault(scope, set()).add(_name_of(e, target, field))
    for e in elements:
        old = _name_of(e, target, field)
        try:
            new = textfmt.apply_rename(old, ctx.get("find"), ctx.get("replace", ""), ctx.bool("regex", False),
                                       ctx.get("prefix", ""), ctx.get("suffix", ""), ctx.get("case"))
        except textfmt.TemplateError as te:
            raise RvtssError(str(te))
        if new == old:
            continue
        bad = textfmt.invalid_name_chars(new)
        if bad:
            conflicts.append({"id": id_int(e), "old": old, "new": new, "reason": "invalid characters {}".format(bad)})
            continue
        plan.append((e, old, new))
    # names that stay after the rename, and planned new names, per uniqueness scope
    renamed_old = {}
    planned = {}
    for e, old, new in plan:
        scope = _uniqueness_scope(e, target, field)
        if scope is None:
            continue
        renamed_old.setdefault(scope, set()).add(old)
        planned.setdefault(scope, []).append(new)
    for e, old, new in plan:
        scope = _uniqueness_scope(e, target, field)
        if scope is None:
            continue
        staying = existing.get(scope, set()) - renamed_old.get(scope, set())
        if new in staying or planned[scope].count(new) > 1:
            conflicts.append({"id": id_int(e), "old": old, "new": new, "reason": "name already used"})
    conflict_ids = set(c["id"] for c in conflicts)
    plan = [p for p in plan if id_int(p[0]) not in conflict_ids]
    preview = core.confirm_gate(ctx, len(plan), "batch_rename")
    dry = preview or ctx.dry_run

    def run():
        done = []
        for e, old, new in plan:
            _set_name(e, target, field, new)
            done.append({"id": id_int(e), "old": old, "new": new})
        return {"renamed": done}

    res, fails = core.run_transaction(doc, "Batch rename " + target, run, dry_run=dry) if plan else ({"renamed": []}, [])
    out = core.commit_result(res, fails, dry, {"target": target, "matched": len(elements), "conflicts": conflicts})
    return core.preview_status(out, preview)


def groups_manage(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    dry = ctx.dry_run
    if action == "list":
        counts = {}
        for g in DB.FilteredElementCollector(doc).OfClass(DB.Group):
            counts.setdefault(id_int(g.GroupType), []).append(id_int(g))
        out = []
        for gt in DB.FilteredElementCollector(doc).OfClass(DB.GroupType):
            inst = counts.get(id_int(gt), [])
            out.append({"type_id": id_int(gt), "name": normalize_string(gt.Name),
                        "category": normalize_string(gt.Category.Name) if gt.Category else None,
                        "instances": len(inst), "instance_ids": inst[:50]})
        return {"group_types": sorted(out, key=lambda g: g["name"]),
                "unused_group_types": [g["name"] for g in out if not g["instances"]]}

    def run():
        if action == "create":
            members = core.get_elements(doc, ctx.list("element_ids"))
            g = doc.Create.NewGroup(core.to_id_list([e.Id for e in members]))
            if ctx.get("name"):
                g.GroupType.Name = ctx.get("name")
            return {"group_id": id_int(g), "group_type": normalize_string(g.GroupType.Name), "members": len(members)}
        if action == "ungroup":
            g = core.get_element(doc, ctx.require("group_id"), "Group")
            members = [id_int(i) for i in g.UngroupMembers()]
            return {"ungrouped_member_ids": members}
        raise RvtssError("action must be list, create or ungroup")

    res, fails = core.run_transaction(doc, "Groups: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry)


def _category_name(doc, assembly):
    try:
        return normalize_string(DB.Category.GetCategory(doc, assembly.NamingCategoryId).Name)
    except Exception:
        return None


def assemblies_manage(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    dry = ctx.dry_run
    if action == "list":
        out = []
        for a in DB.FilteredElementCollector(doc).OfClass(DB.AssemblyInstance):
            out.append({"id": id_int(a), "name": normalize_string(a.AssemblyTypeName),
                        "naming_category": _category_name(doc, a),
                        "members": len(list(a.GetMemberIds())),
                        "views": [id_int(v) for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
                                  if not v.IsTemplate and v.AssociatedAssemblyInstanceId == a.Id]})
        return {"assemblies": out}
    if action == "create":
        members = core.get_elements(doc, ctx.list("element_ids"))
        cat_id = core.resolve_category(doc, ctx.get("naming_category")).Id if ctx.get("naming_category") \
            else members[0].Category.Id
        ids = core.to_id_list([e.Id for e in members])
        if not DB.AssemblyInstance.IsValidNamingCategory(doc, cat_id, ids):
            raise RvtssError("Invalid naming category for these members", status=409)

        def run():
            a = DB.AssemblyInstance.Create(doc, ids, cat_id)
            return a

        a, fails = core.run_transaction(doc, "Create assembly", run, dry_run=dry)
        if dry:
            return core.commit_result({"members": len(members)}, fails, dry)
        name = ctx.get("name")
        if name:
            # Revit requires the assembly creation to be committed before renaming its type
            core.run_transaction(doc, "Name assembly", lambda: setattr(a, "AssemblyTypeName", name))
        return core.commit_result({"assembly_id": id_int(a), "name": normalize_string(a.AssemblyTypeName),
                                   "members": len(members)}, fails, False)
    a = core.get_element(doc, ctx.require("assembly_id"), "Assembly")

    def run():
        if action == "add_members":
            a.AddMemberIds(core.to_id_list(ctx.list("element_ids")))
            return {"members": len(list(a.GetMemberIds()))}
        if action == "remove_members":
            a.RemoveMemberIds(core.to_id_list(ctx.list("element_ids")))
            return {"members": len(list(a.GetMemberIds()))}
        if action == "rename":
            a.AssemblyTypeName = ctx.require("name")
            return {"name": a.AssemblyTypeName}
        if action == "create_views":
            made = {}
            for kind in ctx.list("views") or ["3d", "front", "top", "parts_list"]:
                if kind == "3d":
                    v = DB.AssemblyViewUtils.Create3DOrthographic(doc, a.Id)
                elif kind == "parts_list":
                    v = DB.AssemblyViewUtils.CreatePartList(doc, a.Id)
                elif kind == "material_takeoff":
                    v = DB.AssemblyViewUtils.CreateMaterialTakeoff(doc, a.Id)
                else:
                    orient = {"front": "ElevationFront", "back": "ElevationBack", "left": "ElevationLeft",
                              "right": "ElevationRight", "top": "ElevationTop", "bottom": "ElevationBottom",
                              "detail_front": "DetailSectionA", "detail_side": "DetailSectionB",
                              "horizontal": "HorizontalDetail"}.get(kind)
                    if orient is None:
                        raise RvtssError("Unknown assembly view '{}'".format(kind))
                    v = DB.AssemblyViewUtils.CreateDetailSection(doc, a.Id,
                                                                 getattr(DB.AssemblyDetailViewOrientation, orient))
                made[kind] = id_int(v)
            if ctx.bool("create_sheet", False):
                tb = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
                    .WhereElementIsElementType().FirstElement()
                sheet = DB.AssemblyViewUtils.CreateSheet(doc, a.Id, tb.Id if tb else DB.ElementId.InvalidElementId)
                made["sheet"] = id_int(sheet)
                x = 0.3
                for kind, vid in list(made.items()):
                    if kind == "sheet":
                        continue
                    v = doc.GetElement(make_id(vid))
                    if isinstance(v, DB.ViewSchedule):
                        DB.ScheduleSheetInstance.Create(doc, sheet.Id, v.Id, DB.XYZ(x, 0.8, 0))
                    elif DB.Viewport.CanAddViewToSheet(doc, sheet.Id, v.Id):
                        DB.Viewport.Create(doc, sheet.Id, v.Id, DB.XYZ(x, 0.5, 0))
                    x += 0.4
            return {"views": made}
        raise RvtssError("action must be list, create, add_members, remove_members, rename or create_views")

    res, fails = core.run_transaction(doc, "Assembly: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry, {"assembly_id": id_int(a)})


def register_documentation_routes(api):
    @api.route("/views/create/", methods=["POST"])
    def views_create_route(doc, request):
        return handle(doc, request, create_view)

    @api.route("/views/graphics/", methods=["POST"])
    def views_graphics_route(doc, uidoc, request):
        return handle(doc, request, view_graphics, uidoc=uidoc)

    @api.route("/sheets/manage/", methods=["POST"])
    def sheets_manage_route(doc, request):
        return handle(doc, request, sheets_manage)

    @api.route("/schedules/create/", methods=["POST"])
    def schedules_create_route(doc, request):
        return handle(doc, request, create_schedule)

    @api.route("/batch_rename/", methods=["POST"])
    def batch_rename_route(doc, request):
        return handle(doc, request, batch_rename)

    @api.route("/groups/manage/", methods=["POST"])
    def groups_manage_route(doc, request):
        return handle(doc, request, groups_manage)

    @api.route("/assemblies/manage/", methods=["POST"])
    def assemblies_manage_route(doc, request):
        return handle(doc, request, assemblies_manage)

    logger.info("RVTSS documentation routes registered")
