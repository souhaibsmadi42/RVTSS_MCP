# -*- coding: UTF-8 -*-
"""Element inspection and editing routes (RVTSS).

Routes:
    POST /find_elements/          query + paginate elements
    POST /element_details/        full details for up to 50 ids
    POST /selection/              get or set the Revit selection
    POST /set_parameters/         batch parameter writes (unit-safe)
    POST /bulk_update_parameter/  one parameter on many elements, value or template
    POST /transform_elements/     move / copy / rotate / mirror
    POST /delete_elements/        preview by default, confirm=true to delete
    POST /create_elements/        levels, grids, walls, floors, family instances, rooms
    POST /element_types/          duplicate / rename types, change element types
"""
import math
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, new_floor, text_type
from .query import collect, query_spec, category_counts, selection_ids
from .params_util import find as find_param, read as read_param, read_all, set_value
from .pure import units as U
from .pure import filters as F
from .pure import textfmt
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- inspect
def _describe(ctx, e, fields, param_names):
    doc = ctx.doc
    info = core.element_brief(doc, e)
    if "level" in fields:
        info["level"] = core.element_level(doc, e)
    if "location" in fields:
        info["location"] = core.element_location(e, ctx.unit)
    if "bbox" in fields:
        info["bbox"] = core.element_bbox(e, ctx.unit)
    if param_names:
        vals = {}
        for n in param_names:
            p, owner = find_param(doc, e, n)
            if p is None:
                vals[n] = None
            else:
                r = read_param(doc, p, ctx.unit)
                vals[n] = r.get("display", r.get("value"))
        info["parameters"] = vals
    return info


def find_elements(ctx):
    spec = query_spec(ctx.data)
    if not any(spec.get(k) for k in ("element_ids", "selection", "categories", "class_name", "view",
                                     "level", "family", "type", "text", "param_filters", "name_contains")):
        raise RvtssError("Give at least one filter (categories, class_name, view, level, text, ...)",
                         hint="Broad unfiltered queries on large models are slow; start with get_revit_model_info.")
    elements = collect(ctx, spec, max_scan=ctx.int("max_scan", 200000))
    counts = category_counts(elements)
    if ctx.get("count_only"):
        return {"count": len(elements), "category_counts": counts}
    page, meta = F.paginate(elements, ctx.int("offset", 0, 0), ctx.int("limit", 100, 1, core.MAX_LIMIT))
    fields = [f.lower() for f in ctx.list("fields")]
    params = ctx.list("parameters")
    return {
        "count": meta["total"],
        "pagination": meta,
        "unit": ctx.unit,
        "category_counts": counts,
        "elements": [_describe(ctx, e, fields, params) for e in page],
    }


def _geometry_summary(e, unit):
    opt = DB.Options()
    opt.DetailLevel = DB.ViewDetailLevel.Fine
    geom = e.get_Geometry(opt)
    if geom is None:
        return None
    vol, area, solids, faces = 0.0, 0.0, 0, 0

    def walk(g):
        for obj in g:
            if isinstance(obj, DB.Solid) and obj.Volume > 0:
                yield obj
            elif isinstance(obj, DB.GeometryInstance):
                for s in walk(obj.GetInstanceGeometry()):
                    yield s

    for s in walk(geom):
        solids += 1
        vol += s.Volume
        area += s.SurfaceArea
        faces += s.Faces.Size
    return {"solids": solids, "faces": faces,
            "volume": U.from_internal(vol, U.length_unit_for("volume", unit), 4),
            "surface_area": U.from_internal(area, U.length_unit_for("area", unit), 4),
            "volume_unit": U.length_unit_for("volume", unit), "area_unit": U.length_unit_for("area", unit)}


def element_details(ctx):
    ids = ctx.list("element_ids")
    if not ids:
        raise RvtssError("element_ids is required")
    if len(ids) > 50:
        raise RvtssError("At most 50 elements per call", hint="Page through ids or use find_elements with parameters=[...].")
    doc = ctx.doc
    names = ctx.list("parameters")
    meta = ctx.bool("include_parameter_meta", False)
    out = []
    for e in core.get_elements(doc, ids):
        d = core.element_brief(doc, e)
        d["unique_id"] = e.UniqueId
        d["class"] = e.GetType().Name
        d["level"] = core.element_level(doc, e)
        d["location"] = core.element_location(e, ctx.unit)
        d["bbox"] = core.element_bbox(e, ctx.unit)
        d["pinned"] = getattr(e, "Pinned", None)
        try:
            if doc.IsWorkshared:
                d["workset"] = normalize_string(doc.GetWorksetTable().GetWorkset(e.WorksetId).Name)
        except Exception:
            pass
        for attr, key in (("CreatedPhaseId", "phase_created"), ("DemolishedPhaseId", "phase_demolished")):
            try:
                pid = getattr(e, attr)
                if is_valid_id(pid):
                    d[key] = normalize_string(doc.GetElement(pid).Name)
            except Exception:
                pass
        try:
            if e.DesignOption is not None:
                d["design_option"] = normalize_string(e.DesignOption.Name)
        except Exception:
            pass
        for attr, key in (("GroupId", "group_id"), ("AssemblyInstanceId", "assembly_id")):
            try:
                v = getattr(e, attr)
                if is_valid_id(v):
                    d[key] = id_int(v)
            except Exception:
                pass
        if isinstance(e, DB.FamilyInstance):
            try:
                d["host_id"] = id_int(e.Host) if e.Host else None
                d["super_component_id"] = id_int(e.SuperComponent) if e.SuperComponent else None
                d["sub_component_ids"] = [id_int(i) for i in e.GetSubComponentIds()]
                d["mirrored"] = e.Mirrored
                d["hand_flipped"] = e.HandFlipped
                d["facing_flipped"] = e.FacingFlipped
            except Exception:
                pass
        if ctx.bool("include_parameters", True):
            d["parameters"] = read_all(doc, e, ctx.unit, names or None, meta)
        if ctx.bool("include_type_parameters", False):
            tid = e.GetTypeId()
            if is_valid_id(tid):
                d["type_parameters"] = read_all(doc, doc.GetElement(tid), ctx.unit, names or None, meta)
        if ctx.bool("include_geometry", False):
            try:
                d["geometry"] = _geometry_summary(e, ctx.unit)
            except Exception as ex:
                d["geometry"] = {"error": text_type(ex)}
        out.append(d)
    return {"unit": ctx.unit, "elements": out}


def selection(ctx):
    action = ctx.get("action", "get")
    if action == "get":
        ids = selection_ids(ctx)
        doc = ctx.doc
        limit = ctx.int("limit", 200, 1, core.MAX_LIMIT)
        els = [doc.GetElement(i) for i in ids[:limit]]
        return {"count": len(ids), "category_counts": category_counts([doc.GetElement(i) for i in ids]),
                "elements": [core.element_brief(doc, e) for e in els if e is not None],
                "truncated": len(ids) > limit}
    if action in ("set", "add", "clear"):
        if ctx.uidoc is None or not ctx.uidoc.Document.Equals(ctx.doc):
            raise RvtssError("Selection can only be changed in the active document", status=409)
        current = list(ctx.uidoc.Selection.GetElementIds()) if action == "add" else []
        new_ids = [] if action == "clear" else [e.Id for e in core.get_elements(ctx.doc, ctx.list("element_ids"))]
        ctx.uidoc.Selection.SetElementIds(core.to_id_list(current + new_ids))
        if ctx.bool("zoom", False) and new_ids:
            ctx.uidoc.ShowElements(core.to_id_list(new_ids))
        return {"selected_count": len(current) + len(new_ids)}
    raise RvtssError("action must be get, set, add or clear")


# ----------------------------------------------------------------------- params
def _normalise_updates(ctx):
    updates = ctx.list("updates")
    if not updates and ctx.get("element_ids") and ctx.get("parameter"):
        for i in ctx.list("element_ids"):
            updates.append({"element_id": i, "parameter": ctx.get("parameter"),
                            "value": ctx.data.get("value"), "unit": ctx.get("value_unit")})
    if not updates:
        raise RvtssError("Provide 'updates': [{element_id, parameter, value, unit?}] "
                         "or element_ids + parameter + value")
    for u in updates:
        if "element_id" not in u or not u.get("parameter") or "value" not in u:
            raise RvtssError("Each update needs element_id, parameter and value", failed_item=u)
    return updates


def set_parameters(ctx):
    doc = ctx.doc
    updates = _normalise_updates(ctx)
    distinct = len(set(u["element_id"] for u in updates))
    preview = core.confirm_gate(ctx, distinct, "set_parameters")
    target_default = ctx.get("target", "auto")
    type_hits = {}

    def apply_one(u):
        e = core.get_element(doc, u["element_id"])
        target = u.get("target", target_default)
        p, owner = find_param(doc, e, u["parameter"], allow_type=(target != "instance"))
        if p is None:
            raise RvtssError("Parameter '{}' not found on element {}".format(u["parameter"], u["element_id"]),
                             status=404)
        if target == "type" and owner != "type":
            t = doc.GetElement(e.GetTypeId())
            p = find_param(doc, t, u["parameter"], allow_type=False)[0] if t else None
            owner = "type"
            if p is None:
                raise RvtssError("Type parameter '{}' not found".format(u["parameter"]), status=404)
        if owner == "type" and not isinstance(e, DB.ElementType):
            type_hits[id_int(e.GetTypeId())] = True
        before = read_param(doc, p, "mm")
        after = set_value(doc, p, u["value"], u.get("unit"))
        return {"element_id": u["element_id"], "parameter": after["name"], "owner": owner,
                "before": before.get("display", before.get("value")),
                "after": after.get("display", after.get("value"))}

    atomic = ctx.bool("atomic", True)
    dry = preview or ctx.dry_run
    results, failures = core.run_transaction(
        doc, "Set parameters", lambda: core.batch(doc, updates, apply_one, atomic), dry_run=dry)
    out = core.commit_result({"results": results, "succeeded": len([r for r in results if r["ok"]]),
                              "failed": len([r for r in results if not r["ok"]])}, failures, dry)
    if type_hits:
        out["note"] = "Type parameters were changed on {} type(s); every instance of those types is affected.".format(
            len(type_hits))
    return core.preview_status(out, preview)


def _sort_key(doc, mode):
    if mode in (None, "", "id"):
        return lambda e: id_int(e)
    if mode == "name":
        return lambda e: normalize_string(get_element_name(e) or "").lower()
    if mode in ("x", "y", "z", "xy", "yx"):
        def key(e):
            p = core.element_point(e)
            if p is None:
                return (0, 0, 0)
            if mode == "xy":
                return (round(p.X, 3), round(p.Y, 3))
            if mode == "yx":
                return (round(-p.Y, 3), round(p.X, 3))
            return getattr(p, mode.upper())
        return key
    if mode.startswith("param:"):
        name = mode[6:]

        def pkey(e):
            p, _ = find_param(doc, e, name)
            if p is None:
                return ""
            v = p.AsValueString() or p.AsString() or ""
            return normalize_string(v).lower()
        return pkey
    raise RvtssError("sort_by must be id, name, x, y, z, xy, yx or param:<name>")


def _template_resolver(doc, e, unit):
    def resolve(name):
        low = name.lower()
        if low == "level":
            return core.element_level(doc, e)
        b = core.element_brief(doc, e)
        if low in ("category", "family", "type", "name"):
            return b.get(low)
        p, _ = find_param(doc, e, name)
        if p is None:
            return None
        r = read_param(doc, p, unit)
        v = r.get("display", r.get("value"))
        return None if v in (None, "") else v
    return resolve


def bulk_update_parameter(ctx):
    doc = ctx.doc
    pname = ctx.require("parameter")
    template = ctx.get("template")
    has_value = "value" in ctx.data
    if not template and not has_value:
        raise RvtssError("Provide either 'value' or 'template' (e.g. 'D-{Level}-{n:03}')")
    spec = query_spec(ctx.data)
    elements = collect(ctx, spec) if spec else []
    if not elements:
        raise RvtssError("No elements matched", status=404,
                         hint="Pass element_ids, selection=true or filter keys (categories, level, ...).")
    elements.sort(key=_sort_key(doc, ctx.get("sort_by")))
    start, step = ctx.int("start", 1), ctx.int("step", 1)
    only_empty = ctx.bool("only_empty", False)
    preview = core.confirm_gate(ctx, len(elements), "bulk_update_parameter")
    counter = {"n": start}

    def apply_one(e):
        p, owner = find_param(doc, e, pname, allow_type=ctx.bool("allow_type", False))
        if p is None:
            raise RvtssError("Parameter '{}' not found on element {}".format(pname, id_int(e)), status=404)
        current = read_param(doc, p, ctx.unit)
        cur_val = current.get("display", current.get("value"))
        if only_empty and cur_val not in (None, ""):
            return {"element_id": id_int(e), "skipped": "already has a value", "value": cur_val}
        if template:
            try:
                new_val = textfmt.render(template, _template_resolver(doc, e, ctx.unit), n=counter["n"],
                                         element_id=id_int(e), current=cur_val)
            except textfmt.TemplateError as te:
                raise RvtssError(str(te))
            counter["n"] += step
        else:
            new_val = ctx.data.get("value")
        after = set_value(doc, p, new_val, ctx.get("value_unit"))
        return {"element_id": id_int(e), "before": cur_val, "after": after.get("display", after.get("value"))}

    dry = preview or ctx.dry_run
    results, failures = core.run_transaction(
        doc, "Bulk update " + pname, lambda: core.batch(doc, elements, apply_one, ctx.bool("atomic", True)),
        dry_run=dry)
    out = core.commit_result({"parameter": pname, "matched": len(elements), "results": results[:ctx.int("max_results", 200)],
                              "results_truncated": len(results) > ctx.int("max_results", 200)}, failures, dry)
    return core.preview_status(out, preview)


# -------------------------------------------------------------------- transform
def _vector(ctx, key):
    v = ctx.get(key)
    if v is None:
        raise RvtssError("'{}' is required ([x, y, z] in {})".format(key, ctx.unit))
    x, y, z = U.point_from(v, ctx.unit)
    return DB.XYZ(x, y, z)


def transform_elements(ctx):
    doc = ctx.doc
    op = ctx.require("operation")
    elements = core.get_elements(doc, ctx.list("element_ids"))
    if not elements:
        raise RvtssError("element_ids is required")
    pinned = [id_int(e) for e in elements if getattr(e, "Pinned", False)]
    if pinned and not ctx.bool("unpin", False):
        raise RvtssError("Pinned elements cannot be transformed: {}".format(pinned[:20]), status=409,
                         hint="Pass unpin=true to unpin them first (they stay unpinned).")
    ids = core.to_id_list([e.Id for e in elements])
    preview = core.confirm_gate(ctx, len(elements), "transform_elements")

    def center():
        c = ctx.get("center")
        if c is not None:
            x, y, z = U.point_from(c, ctx.unit)
            return DB.XYZ(x, y, z)
        pts = [core.element_point(e) for e in elements]
        pts = [p for p in pts if p is not None]
        if not pts:
            raise RvtssError("Cannot determine a rotation centre; pass 'center'")
        return DB.XYZ(sum(p.X for p in pts) / len(pts), sum(p.Y for p in pts) / len(pts),
                      sum(p.Z for p in pts) / len(pts))

    def run():
        for e in elements:
            if getattr(e, "Pinned", False):
                e.Pinned = False
        new_ids = []
        if op == "move":
            DB.ElementTransformUtils.MoveElements(doc, ids, _vector(ctx, "vector"))
        elif op == "copy":
            new_ids = list(DB.ElementTransformUtils.CopyElements(doc, ids, _vector(ctx, "vector")))
        elif op == "rotate":
            angle = math.radians(ctx.float("angle_deg", 0.0))
            if ctx.bool("each_about_own_center", False):
                for e in elements:
                    p = core.element_point(e)
                    axis = DB.Line.CreateBound(p, p + DB.XYZ.BasisZ)
                    DB.ElementTransformUtils.RotateElement(doc, e.Id, axis, angle)
            else:
                c = center()
                DB.ElementTransformUtils.RotateElements(doc, ids, DB.Line.CreateBound(c, c + DB.XYZ.BasisZ), angle)
        elif op == "mirror":
            normal = {"x": DB.XYZ.BasisX, "y": DB.XYZ.BasisY}.get(ctx.get("plane_normal", "x"))
            if normal is None:
                raise RvtssError("plane_normal must be 'x' or 'y' (vertical mirror plane)")
            plane = DB.Plane.CreateByNormalAndOrigin(normal, center())
            res = DB.ElementTransformUtils.MirrorElements(doc, ids, plane, ctx.bool("mirror_copy", False))
            if res is not None:
                new_ids = list(res)
        else:
            raise RvtssError("operation must be move, copy, rotate or mirror")
        doc.Regenerate()
        moved = [{"id": id_int(e), "location": core.element_location(e, ctx.unit)} for e in elements[:50]]
        return {"operation": op, "count": len(elements), "new_element_ids": [id_int(i) for i in new_ids],
                "elements": moved}

    dry = preview or ctx.dry_run
    result, failures = core.run_transaction(doc, "Transform " + op, run, dry_run=dry)
    return core.preview_status(core.commit_result(result, failures, dry, {"unit": ctx.unit}), preview)


def delete_elements(ctx):
    doc = ctx.doc
    elements = core.get_elements(doc, ctx.list("element_ids"))
    if not elements:
        raise RvtssError("element_ids is required")
    if len(elements) > 5000:
        raise RvtssError("Refusing to delete more than 5000 elements in one call", status=409)
    pinned = [id_int(e) for e in elements if getattr(e, "Pinned", False)]
    if pinned and not ctx.bool("include_pinned", False):
        raise RvtssError("Pinned elements in the request: {}".format(pinned[:20]), status=409,
                         hint="Pinned elements are protected. Pass include_pinned=true to delete them anyway.")
    commit = ctx.confirmed and not ctx.dry_run
    requested = set(id_int(e) for e in elements)

    def run():
        deleted = list(doc.Delete(core.to_id_list([e.Id for e in elements])))
        return [id_int(i) for i in deleted]

    # Collect the full dependent set while the elements still exist
    summary = {}
    for e in elements:
        b = core.element_brief(doc, e)
        summary.setdefault(b.get("category") or "(none)", 0)
        summary[b.get("category") or "(none)"] += 1
    deleted, failures = core.run_transaction(doc, "Delete elements", run, dry_run=not commit)
    dependents = [i for i in deleted if i not in requested]
    out = {
        "requested": len(requested),
        "deleted_total": len(deleted),
        "dependent_elements_deleted": len(dependents),
        "dependent_ids_sample": dependents[:50],
        "requested_by_category": summary,
    }
    if not commit:
        out.update({"status": "preview", "committed": False, "requires_confirmation": True,
                    "message": "Preview: Revit would delete {} element(s) including {} dependent(s). "
                               "Nothing was deleted. Re-run with confirm=true to delete.".format(
                                   len(deleted), len(dependents))})
    else:
        out.update({"status": "success", "committed": True,
                    "message": "Deleted {} element(s). Revit's Undo (Ctrl+Z) can restore them while the "
                               "session lasts.".format(len(deleted))})
    if failures:
        out["revit_warnings"] = failures
    return out


# ----------------------------------------------------------------------- create
def _pt(ctx, item, key):
    v = item.get(key)
    if v is None:
        raise RvtssError("'{}' is required".format(key), failed_item=item)
    x, y, z = U.point_from(v, ctx.unit)
    return DB.XYZ(x, y, z)


def _line(ctx, item):
    a, b = _pt(ctx, item, "start"), _pt(ctx, item, "end")
    if a.DistanceTo(b) < 1e-4:
        raise RvtssError("start and end are the same point", failed_item=item)
    return DB.Line.CreateBound(a, b)


def _create_one(ctx, item):
    doc = ctx.doc
    kind = item.get("kind")
    unit = ctx.unit
    if kind == "level":
        lv = DB.Level.Create(doc, U.to_internal(item.get("elevation", 0), unit))
        if item.get("name"):
            lv.Name = item["name"]
        out = {"kind": kind, "id": id_int(lv), "name": lv.Name}
        if item.get("create_plan_view", False):
            vft = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                   if t.ViewFamily == DB.ViewFamily.FloorPlan][0]
            out["plan_view_id"] = id_int(DB.ViewPlan.Create(doc, vft.Id, lv.Id))
        return out
    if kind == "grid":
        g = DB.Grid.Create(doc, _line(ctx, item))
        if item.get("name"):
            g.Name = item["name"]
        return {"kind": kind, "id": id_int(g), "name": g.Name}
    if kind == "wall":
        level = core.find_level(doc, item.get("level"))
        wt = core.find_type(doc, family=item.get("family"), type_name=item.get("type"),
                            type_id=item.get("type_id"), of_class=DB.WallType) \
            if (item.get("type") or item.get("type_id")) else doc.GetElement(doc.GetDefaultElementTypeId(
                DB.ElementTypeGroup.WallType))
        height = U.to_internal(item.get("height", 3000), unit)
        offset = U.to_internal(item.get("base_offset", 0), unit)
        w = DB.Wall.Create(doc, _line(ctx, item), wt.Id, level.Id, height, offset,
                           bool(item.get("flip", False)), bool(item.get("structural", False)))
        return {"kind": kind, "id": id_int(w), "type": normalize_string(get_element_name(wt))}
    if kind == "floor":
        level = core.find_level(doc, item.get("level"))
        pts = [U.point_from(p, unit) for p in item.get("boundary") or []]
        if len(pts) < 3:
            raise RvtssError("floor needs a 'boundary' of at least 3 points", failed_item=item)
        loop = DB.CurveLoop()
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            loop.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], level.Elevation), DB.XYZ(b[0], b[1], level.Elevation)))
        ft = core.find_type(doc, family=item.get("family"), type_name=item.get("type"),
                            type_id=item.get("type_id"), of_class=DB.FloorType) \
            if (item.get("type") or item.get("type_id")) else doc.GetElement(doc.GetDefaultElementTypeId(
                DB.ElementTypeGroup.FloorType))
        f = new_floor(doc, [loop], ft, level, bool(item.get("structural", False)))
        return {"kind": kind, "id": id_int(f), "type": normalize_string(get_element_name(ft))}
    if kind == "family_instance":
        sym = core.find_type(doc, family=item.get("family"), type_name=item.get("type"),
                             type_id=item.get("type_id"), of_class=DB.FamilySymbol)
        if not sym.IsActive:
            sym.Activate()
            doc.Regenerate()
        pt = _pt(ctx, item, "point")
        st = DB.Structure.StructuralType.NonStructural
        level = core.find_level(doc, item.get("level")) if item.get("level") is not None else None
        host = core.get_element(doc, item["host_id"], "Host") if item.get("host_id") is not None else None
        if host is not None and level is not None:
            fi = doc.Create.NewFamilyInstance(pt, sym, host, level, st)
        elif host is not None:
            fi = doc.Create.NewFamilyInstance(pt, sym, host, st)
        elif level is not None:
            fi = doc.Create.NewFamilyInstance(pt, sym, level, st)
        else:
            fi = doc.Create.NewFamilyInstance(pt, sym, st)
        rot = float(item.get("rotation_deg", 0) or 0)
        if rot:
            doc.Regenerate()
            DB.ElementTransformUtils.RotateElement(doc, fi.Id, DB.Line.CreateBound(pt, pt + DB.XYZ.BasisZ),
                                                   math.radians(rot))
        return {"kind": kind, "id": id_int(fi), "family": normalize_string(sym.Family.Name),
                "type": normalize_string(get_element_name(sym))}
    if kind == "room":
        core.require_project(doc)
        level = core.find_level(doc, item.get("level"))
        x, y, _z = U.point_from(item.get("point"), unit)
        r = doc.Create.NewRoom(level, DB.UV(x, y))
        if item.get("name"):
            r.get_Parameter(DB.BuiltInParameter.ROOM_NAME).Set(item["name"])
        if item.get("number"):
            r.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER).Set(text_type(item["number"]))
        return {"kind": kind, "id": id_int(r)}
    raise RvtssError("Unknown kind '{}'. Use level, grid, wall, floor, family_instance or room".format(kind),
                     failed_item=item)


def create_elements(ctx):
    doc = ctx.doc
    items = ctx.list("items")
    if not items:
        raise RvtssError("'items' is required: [{kind: 'wall', start: [..], end: [..], level: 'Level 1'}, ...]")
    if len(items) > 500:
        raise RvtssError("At most 500 items per call")
    dry = ctx.dry_run

    def run():
        res = core.batch(doc, items, lambda it: _create_one(ctx, it), ctx.bool("atomic", True))
        doc.Regenerate()
        return res

    results, failures = core.run_transaction(doc, "Create elements", run, dry_run=dry)
    return core.commit_result({"results": results, "unit": ctx.unit,
                               "created": len([r for r in results if r["ok"]])}, failures, dry)


# ------------------------------------------------------------------------ types
def element_types(ctx):
    doc = ctx.doc
    action = ctx.require("action")
    dry = ctx.dry_run
    if action == "list_valid_types":
        e = core.get_element(doc, ctx.require("element_id"))
        valid = [doc.GetElement(i) for i in e.GetValidTypes()]
        return {"element_id": id_int(e), "current_type_id": id_int(e.GetTypeId()),
                "valid_types": [{"id": id_int(t), "family": normalize_string(getattr(t, "FamilyName", "")),
                                 "type": normalize_string(get_element_name(t))} for t in valid if t]}

    def get_type():
        return core.find_type(doc, family=ctx.get("family"), type_name=ctx.get("type"), type_id=ctx.get("type_id"),
                              category=ctx.get("category"))

    if action == "duplicate":
        src = get_type()
        new_name = ctx.require("new_name")

        def run():
            t = doc.GetElement(src.Duplicate(new_name).Id) if hasattr(src, "Duplicate") else None
            if t is None:
                raise RvtssError("This type cannot be duplicated")
            set_vals = []
            for pname, val in (ctx.get("parameters") or {}).items():
                p, _ = find_param(doc, t, pname, allow_type=False)
                if p is None:
                    raise RvtssError("Type parameter '{}' not found".format(pname), status=404)
                v, unit = (val.get("value"), val.get("unit")) if isinstance(val, dict) else (val, None)
                set_vals.append(set_value(doc, p, v, unit))
            return {"new_type_id": id_int(t), "name": t.Name, "parameters_set": set_vals}
        res, fails = core.run_transaction(doc, "Duplicate type", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    if action == "rename":
        t = get_type()
        new_name = ctx.require("new_name")

        def run():
            old = t.Name
            t.Name = new_name
            return {"type_id": id_int(t), "old_name": old, "new_name": t.Name}
        res, fails = core.run_transaction(doc, "Rename type", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    if action == "change_type":
        t = get_type()
        elements = core.get_elements(doc, ctx.list("element_ids"))
        preview = core.confirm_gate(ctx, len(elements), "change_type")

        def change(e):
            if t.Id not in list(e.GetValidTypes()):
                raise RvtssError("Type {} is not valid for element {}".format(id_int(t), id_int(e)),
                                 hint="Use action=list_valid_types to see allowed types.")
            old = id_int(e.GetTypeId())
            e.ChangeTypeId(t.Id)
            return {"element_id": id_int(e), "old_type_id": old, "new_type_id": id_int(t)}
        d = preview or dry
        res, fails = core.run_transaction(
            doc, "Change type", lambda: core.batch(doc, elements, change, ctx.bool("atomic", True)), dry_run=d)
        return core.preview_status(core.commit_result({"results": res}, fails, d), preview)
    raise RvtssError("action must be list_valid_types, duplicate, rename or change_type")


# ----------------------------------------------------------------------- routes
def register_elements_routes(api):
    @api.route("/find_elements/", methods=["POST"])
    def find_elements_route(doc, uidoc, request):
        return handle(doc, request, find_elements, uidoc=uidoc)

    @api.route("/element_details/", methods=["POST"])
    def element_details_route(doc, request):
        return handle(doc, request, element_details)

    @api.route("/selection/", methods=["POST"])
    def selection_route(doc, uidoc, request):
        return handle(doc, request, selection, uidoc=uidoc)

    @api.route("/set_parameters/", methods=["POST"])
    def set_parameters_route(doc, request):
        return handle(doc, request, set_parameters)

    @api.route("/bulk_update_parameter/", methods=["POST"])
    def bulk_update_parameter_route(doc, uidoc, request):
        return handle(doc, request, bulk_update_parameter, uidoc=uidoc)

    @api.route("/transform_elements/", methods=["POST"])
    def transform_elements_route(doc, request):
        return handle(doc, request, transform_elements)

    @api.route("/delete_elements/", methods=["POST"])
    def delete_elements_route(doc, request):
        return handle(doc, request, delete_elements)

    @api.route("/create_elements/", methods=["POST"])
    def create_elements_route(doc, request):
        return handle(doc, request, create_elements)

    @api.route("/element_types/", methods=["POST"])
    def element_types_route(doc, request):
        return handle(doc, request, element_types)

    logger.info("RVTSS element routes registered")
