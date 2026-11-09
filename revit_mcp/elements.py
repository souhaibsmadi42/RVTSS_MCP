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
    POST /create_elements/        levels, grids, walls, floors, family instances, rooms, roofs, ceilings,
                                  columns, beams, foundations, wall foundations; (2.3) ducts, pipes,
                                  cable trays, conduit, openings, shafts, railings, spaces, areas,
                                  boundary lines, automatic rooms, rebar, toposolids, DirectShape meshes
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
            if p is None:  # keys must have one type per mode (IronPython 3 cannot compare tuple/float)
                return (0.0, 0.0) if mode in ("xy", "yx") else 0.0
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
    if op in ("pin", "unpin", "join", "unjoin", "switch_join"):
        return _modify_elements(ctx, doc, op, elements)
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
                    if p is None:
                        raise RvtssError("Element {} has no location or bounding box to rotate about".format(
                            id_int(e)), hint="Pass 'center' and each_about_own_center=false.")
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
        elif op == "array":
            # non-associative array: count-1 copies, linear (vector) or radial (angle_deg in total, center)
            count = ctx.int("count", minimum=2, maximum=200)
            if count is None:
                raise RvtssError("array needs 'count' (2-200, including the originals)")
            if ctx.get("vector") is not None:
                step = _vector(ctx, "vector")
                for i in range(1, count):
                    new_ids.extend(DB.ElementTransformUtils.CopyElements(doc, ids, step * float(i)))
            elif ctx.get("angle_deg") is not None:
                c = center()
                axis = DB.Line.CreateBound(c, c + DB.XYZ.BasisZ)
                total = math.radians(ctx.float("angle_deg"))
                full = abs(abs(ctx.float("angle_deg")) - 360.0) < 1e-6
                step = total / (count if full else count - 1)
                for i in range(1, count):
                    copies = DB.ElementTransformUtils.CopyElements(doc, ids, DB.XYZ.Zero)
                    DB.ElementTransformUtils.RotateElements(doc, copies, axis, step * i)
                    new_ids.extend(copies)
            else:
                raise RvtssError("array needs 'vector' (linear) or 'angle_deg' (radial, about 'center')")
        else:
            raise RvtssError("operation must be move, copy, rotate, mirror, array, pin, unpin, join, unjoin "
                             "or switch_join")
        doc.Regenerate()
        moved = [{"id": id_int(e), "location": core.element_location(e, ctx.unit)} for e in elements[:50]]
        return {"operation": op, "count": len(elements), "new_element_ids": [id_int(i) for i in new_ids],
                "elements": moved}

    dry = preview or ctx.dry_run
    result, failures = core.run_transaction(doc, "Transform " + op, run, dry_run=dry)
    return core.preview_status(core.commit_result(result, failures, dry, {"unit": ctx.unit}), preview)


def _modify_elements(ctx, doc, op, elements):
    """pin / unpin every element; join / unjoin / switch_join the first element with each of the others."""
    if op in ("join", "unjoin", "switch_join") and len(elements) < 2:
        raise RvtssError("{} needs at least 2 element_ids (the first is joined with each of the others)".format(op))
    J = DB.JoinGeometryUtils

    def run():
        out = []
        if op in ("pin", "unpin"):
            for e in elements:
                try:
                    e.Pinned = op == "pin"
                    out.append({"id": id_int(e), "ok": True, "pinned": e.Pinned})
                except Exception as ex:
                    out.append({"id": id_int(e), "ok": False, "error": normalize_string(text_type(ex))})
            return {"operation": op, "results": out}
        a = elements[0]
        for b in elements[1:]:
            r = {"pair": [id_int(a), id_int(b)]}
            try:
                joined = J.AreElementsJoined(doc, a, b)
                if op == "join":
                    if not joined:
                        J.JoinGeometry(doc, a, b)
                    r["joined"] = True
                elif op == "unjoin":
                    if joined:
                        J.UnjoinGeometry(doc, a, b)
                    r["joined"] = False
                else:
                    if not joined:
                        raise RvtssError("elements are not joined")
                    J.SwitchJoinOrder(doc, a, b)
                    r["cutting_first"] = J.IsCuttingElementInJoin(doc, a, b)
                r["ok"] = True
            except Exception as ex:
                r.update({"ok": False, "error": normalize_string(text_type(getattr(ex, "message", ex)))})
            out.append(r)
        if ctx.bool("atomic", False) and any(not r["ok"] for r in out):
            raise RvtssError("{} failed for {} pair(s)".format(op, len([r for r in out if not r["ok"]])),
                             results=out, hint="Nothing was changed (atomic=true).")
        return {"operation": op, "results": out}

    result, failures = core.run_transaction(doc, op.replace("_", " ").title(), run, dry_run=ctx.dry_run)
    return core.commit_result(result, failures, ctx.dry_run)


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
    if kind in _STRUCTURE_KINDS:
        return _STRUCTURE_KINDS[kind](ctx, item)
    if kind in _MODELLING_KINDS:
        return _MODELLING_KINDS[kind](ctx, item)
    raise RvtssError("Unknown kind '{}'. Use level, grid, wall, floor, family_instance, room, roof, ceiling, "
                     "column, beam, foundation, wall_foundation, duct, pipe, cable_tray, conduit, wall_opening, "
                     "opening, shaft, railing, space, area, area_boundary, room_separation, space_separation, auto_rooms, "
                     "rebar, toposolid, direct_shape, curtain_grid_line, mullions, curtain_panel_type, wall_sweep, "
                     "reveal, model_line, reference_plane, foundation_isolated, foundation_wall, brace, truss or "
                     "beam_system".format(kind), failed_item=item)


# ---------------------------------------------------- roofs, ceilings, structure (2.2)
def _outline(ctx, item, level):
    """Closed boundary [[x, y], ...] at the level elevation -> list of lines."""
    pts = [U.point_from(p, ctx.unit) for p in item.get("boundary") or []]
    if len(pts) < 3:
        raise RvtssError("'boundary' needs at least 3 points", failed_item=item)
    z = level.Elevation
    lines = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        pa, pb = DB.XYZ(a[0], a[1], z), DB.XYZ(b[0], b[1], z)
        if pa.DistanceTo(pb) < 1e-4:
            raise RvtssError("boundary has two equal consecutive points", failed_item=item)
        lines.append(DB.Line.CreateBound(pa, pb))
    return lines


def _system_type(doc, item, cls, group, what):
    if item.get("type") or item.get("type_id") is not None:
        return core.find_type(doc, family=item.get("family"), type_name=item.get("type"),
                              type_id=item.get("type_id"), of_class=cls)
    t = None
    if group is not None:
        try:
            t = doc.GetElement(doc.GetDefaultElementTypeId(group))
        except Exception:
            t = None
    if t is None:
        t = DB.FilteredElementCollector(doc).OfClass(cls).FirstElement()
    if t is None:
        raise RvtssError("No {} type exists in '{}'".format(what, doc.Title))
    return t


def _symbol(doc, item, categories, what):
    """FamilySymbol from family/type/type_id, else the first loaded symbol of the categories."""
    if item.get("type") or item.get("type_id") is not None or item.get("family"):
        sym = core.find_type(doc, family=item.get("family"), type_name=item.get("type"),
                             type_id=item.get("type_id"), of_class=DB.FamilySymbol)
    else:
        sym = None
        for bic in categories:
            sym = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(bic).FirstElement()
            if sym is not None:
                break
        if sym is None:
            raise RvtssError("No {} family is loaded in '{}'".format(what, doc.Title),
                             hint="Load one (family_load_into_project) or pass family/type.")
    if not sym.IsActive:
        sym.Activate()
        doc.Regenerate()
    return sym


def _set_param(e, bips, value):
    for bip in bips:
        p = e.get_Parameter(getattr(DB.BuiltInParameter, bip))
        if p is not None and not p.IsReadOnly:
            p.Set(value)
            return True
    return False


def _level_point(ctx, item, level, key="point"):
    v = item.get(key)
    if v is None:
        raise RvtssError("'{}' is required".format(key), failed_item=item)
    x, y, z = U.point_from(v, ctx.unit)
    return DB.XYZ(x, y, z if len(list(v)) == 3 else level.Elevation)


def _roof(ctx, item):
    import clr

    doc = ctx.doc
    level = core.find_level(doc, item.get("level"))
    rt = _system_type(doc, item, DB.RoofType, DB.ElementTypeGroup.RoofType, "roof")
    footprint = DB.CurveArray()
    for ln in _outline(ctx, item, level):
        footprint.Append(ln)
    # the out parameter must hold an instance: an empty Reference fails with "Value cannot be null"
    model_curves = clr.Reference[DB.ModelCurveArray](DB.ModelCurveArray())
    roof = doc.Create.NewFootPrintRoof(footprint, level, rt, model_curves)
    slope = item.get("slope_deg")
    sloped = []
    if slope:
        edges = item.get("slope_edges")
        for i, mc in enumerate(model_curves.Value):
            if edges is None or i in edges:
                roof.set_DefinesSlope(mc, True)
                roof.set_SlopeAngle(mc, math.tan(math.radians(float(slope))))
                sloped.append(i)
    if item.get("base_offset"):
        _set_param(roof, ["ROOF_LEVEL_OFFSET_PARAM"], U.to_internal(item["base_offset"], ctx.unit))
    return {"kind": "roof", "id": id_int(roof), "type": normalize_string(get_element_name(rt)),
            "sloped_edges": sloped}


def _ceiling(ctx, item):
    from System.Collections.Generic import List

    doc = ctx.doc
    if not (hasattr(DB, "Ceiling") and hasattr(DB.Ceiling, "Create")):
        raise RvtssError("Creating ceilings needs Revit 2022 or later")
    level = core.find_level(doc, item.get("level"))
    ct = _system_type(doc, item, DB.CeilingType, getattr(DB.ElementTypeGroup, "CeilingType", None), "ceiling")
    loop = DB.CurveLoop()
    for ln in _outline(ctx, item, level):
        loop.Append(ln)
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    c = DB.Ceiling.Create(doc, loops, ct.Id, level.Id)
    if item.get("height") is not None:
        _set_param(c, ["CEILING_HEIGHTABOVELEVEL_PARAM"], U.to_internal(item["height"], ctx.unit))
    return {"kind": "ceiling", "id": id_int(c), "type": normalize_string(get_element_name(ct))}


def _column(ctx, item):
    doc = ctx.doc
    base = core.find_level(doc, item.get("level") or item.get("base_level"))
    sym = _symbol(doc, item, [DB.BuiltInCategory.OST_StructuralColumns, DB.BuiltInCategory.OST_Columns], "column")
    structural = sym.Category is not None and id_int(sym.Category.Id) == int(DB.BuiltInCategory.OST_StructuralColumns)
    st = DB.Structure.StructuralType.Column if structural else DB.Structure.StructuralType.NonStructural
    pt = _level_point(ctx, item, base)
    fi = doc.Create.NewFamilyInstance(pt, sym, base, st)
    _set_param(fi, ["FAMILY_BASE_LEVEL_OFFSET_PARAM"], U.to_internal(item.get("base_offset", 0), ctx.unit))
    if item.get("top_level") is not None:
        top = core.find_level(doc, item.get("top_level"))
        _set_param(fi, ["FAMILY_TOP_LEVEL_PARAM"], top.Id)
    if item.get("top_offset") is not None:
        _set_param(fi, ["FAMILY_TOP_LEVEL_OFFSET_PARAM"], U.to_internal(item["top_offset"], ctx.unit))
    rot = float(item.get("rotation_deg", 0) or 0)
    if rot:
        doc.Regenerate()
        DB.ElementTransformUtils.RotateElement(doc, fi.Id, DB.Line.CreateBound(pt, pt + DB.XYZ.BasisZ),
                                               math.radians(rot))
    return {"kind": "column", "id": id_int(fi), "structural": structural,
            "family": normalize_string(sym.Family.Name), "type": normalize_string(get_element_name(sym))}


def _beam(ctx, item):
    doc = ctx.doc
    level = core.find_level(doc, item.get("level"))
    sym = _symbol(doc, item, [DB.BuiltInCategory.OST_StructuralFraming], "structural framing (beam)")
    a, b = _level_point(ctx, item, level, "start"), _level_point(ctx, item, level, "end")
    if a.DistanceTo(b) < 1e-4:
        raise RvtssError("start and end are the same point", failed_item=item)
    fi = doc.Create.NewFamilyInstance(DB.Line.CreateBound(a, b), sym, level, DB.Structure.StructuralType.Beam)
    return {"kind": "beam", "id": id_int(fi), "family": normalize_string(sym.Family.Name),
            "type": normalize_string(get_element_name(sym))}


def _foundation(ctx, item):
    doc = ctx.doc
    level = core.find_level(doc, item.get("level"))
    sym = _symbol(doc, item, [DB.BuiltInCategory.OST_StructuralFoundation], "structural foundation")
    pt = _level_point(ctx, item, level)
    fi = doc.Create.NewFamilyInstance(pt, sym, level, DB.Structure.StructuralType.Footing)
    if item.get("base_offset") is not None:
        _set_param(fi, ["INSTANCE_FREE_HOST_OFFSET_PARAM", "INSTANCE_ELEVATION_PARAM"],
                   U.to_internal(item["base_offset"], ctx.unit))
    return {"kind": "foundation", "id": id_int(fi), "family": normalize_string(sym.Family.Name),
            "type": normalize_string(get_element_name(sym))}


def _wall_foundation(ctx, item):
    doc = ctx.doc
    if item.get("wall_id") is None:
        raise RvtssError("'wall_id' is required", failed_item=item)
    wall = core.get_element(doc, item["wall_id"], "Wall")
    if not isinstance(wall, DB.Wall):
        raise RvtssError("Element {} is not a wall".format(item["wall_id"]))
    ft = _system_type(doc, item, DB.WallFoundationType, None, "wall foundation")
    wf = DB.WallFoundation.Create(doc, ft.Id, wall.Id)
    return {"kind": "wall_foundation", "id": id_int(wf), "wall_id": id_int(wall),
            "type": normalize_string(get_element_name(ft))}


# ------------------------------------------- MEP, openings, shafts, railings (2.3)
def _route_points(ctx, item, level):
    """'points' [[x,y(,z)],...] (or start/end) -> XYZ list. z defaults to level elevation + 'offset'."""
    raw = item.get("points") or ([item["start"], item["end"]] if item.get("start") and item.get("end") else None)
    if not raw or len(raw) < 2:
        raise RvtssError("'points' needs at least 2 points (or start and end)", failed_item=item)
    off = U.to_internal(item.get("offset", 0), ctx.unit)
    pts = []
    for p in raw:
        x, y, z = U.point_from(p, ctx.unit)
        pts.append(DB.XYZ(x, y, z if len(list(p)) == 3 else level.Elevation + off))
    for a, b in zip(pts, pts[1:]):
        if a.DistanceTo(b) < 1e-4:
            raise RvtssError("route has two equal consecutive points", failed_item=item)
    return pts


def _end_connector(curve_el, point):
    best, dist = None, None
    for c in curve_el.ConnectorManager.Connectors:
        d = c.Origin.DistanceTo(point)
        if dist is None or d < dist:
            best, dist = c, d
    return best


def _mep_system_type(doc, item, cls, what):
    name = item.get("system_type")
    types = list(DB.FilteredElementCollector(doc).OfClass(cls))
    if not types:
        raise RvtssError("No {} system type exists in '{}'".format(what, doc.Title),
                         hint="Use a project started from an MEP template, or load the system types.")
    if name:
        for t in types:
            if normalize_string(get_element_name(t)).lower() == text_type(name).strip().lower():
                return t
        raise not_found_type(what + " system type", name, [get_element_name(t) for t in types])
    return types[0]


def not_found_type(what, name, names):
    return RvtssError("{} '{}' not found".format(what, name), status=404,
                      available=sorted(set(normalize_string(n) for n in names))[:50])


def _set_size(ctx, el, item, mapping):
    """mapping: {'width': [BIP, ...], ...}; values in ctx.unit."""
    done = {}
    for key, bips in mapping.items():
        if item.get(key) is not None:
            if _set_param(el, bips, U.to_internal(item[key], ctx.unit)):
                done[key] = item[key]
    return done


def _mep_run(ctx, item, kind):
    doc = ctx.doc
    core.require_project(doc)
    level = core.find_level(doc, item.get("level"))
    pts = _route_points(ctx, item, level)
    if kind == "duct":
        from Autodesk.Revit.DB import Mechanical as M
        st = _mep_system_type(doc, item, M.MechanicalSystemType, "duct")
        tt = _system_type(doc, item, M.DuctType, None, "duct")
        make = lambda a, b: M.Duct.Create(doc, st.Id, tt.Id, level.Id, a, b)  # noqa: E731
        sizes = {"width": ["RBS_CURVE_WIDTH_PARAM"], "height": ["RBS_CURVE_HEIGHT_PARAM"],
                 "diameter": ["RBS_CURVE_DIAMETER_PARAM"]}
    elif kind == "pipe":
        from Autodesk.Revit.DB import Plumbing as P
        st = _mep_system_type(doc, item, P.PipingSystemType, "piping")
        tt = _system_type(doc, item, P.PipeType, None, "pipe")
        make = lambda a, b: P.Pipe.Create(doc, st.Id, tt.Id, level.Id, a, b)  # noqa: E731
        sizes = {"diameter": ["RBS_PIPE_DIAMETER_PARAM"]}
    elif kind == "cable_tray":
        from Autodesk.Revit.DB import Electrical as E
        tt = _system_type(doc, item, E.CableTrayType, None, "cable tray")
        make = lambda a, b: E.CableTray.Create(doc, tt.Id, a, b, level.Id)  # noqa: E731
        sizes = {"width": ["RBS_CABLETRAY_WIDTH_PARAM"], "height": ["RBS_CABLETRAY_HEIGHT_PARAM"]}
    else:  # conduit
        from Autodesk.Revit.DB import Electrical as E
        tt = _system_type(doc, item, E.ConduitType, None, "conduit")
        make = lambda a, b: E.Conduit.Create(doc, tt.Id, a, b, level.Id)  # noqa: E731
        sizes = {"diameter": ["RBS_CONDUIT_DIAMETER_PARAM"]}
    segs = []
    for a, b in zip(pts, pts[1:]):
        s = make(a, b)
        _set_size(ctx, s, item, sizes)
        segs.append(s)
    fittings, fitting_errors = [], []
    if item.get("fittings", True) and len(segs) > 1:
        doc.Regenerate()
        for i in range(len(segs) - 1):
            joint = pts[i + 1]
            try:
                f = doc.Create.NewElbowFitting(_end_connector(segs[i], joint), _end_connector(segs[i + 1], joint))
                fittings.append(id_int(f))
            except Exception as ex:  # routing preferences without an elbow, too-short segment, ...
                fitting_errors.append({"joint": i + 1, "error": normalize_string(text_type(ex))})
    out = {"kind": kind, "id": id_int(segs[0]), "segment_ids": [id_int(s) for s in segs],
           "type": normalize_string(get_element_name(tt)), "fitting_ids": fittings}
    if kind in ("duct", "pipe"):
        out["system_type"] = normalize_string(get_element_name(st))
    if fitting_errors:
        out["fitting_errors"] = fitting_errors
    return out


def _wall_opening(ctx, item):
    """Rectangular opening in a straight wall: offset along the wall from its start, width, sill, height."""
    doc = ctx.doc
    wall = core.get_element(doc, item.get("wall_id"), "Wall")
    if not isinstance(wall, DB.Wall) or not isinstance(wall.Location, DB.LocationCurve):
        raise RvtssError("Element {} is not a wall with a location line".format(item.get("wall_id")))
    line = wall.Location.Curve
    if not isinstance(line, DB.Line):
        raise RvtssError("wall_opening needs a straight wall")
    for key in ("offset_along", "width", "height"):
        if item.get(key) is None:
            raise RvtssError("'{}' is required".format(key), failed_item=item)
    p0 = line.GetEndPoint(0)
    d = line.Direction
    base = doc.GetElement(wall.LevelId)
    z0 = base.Elevation if base else p0.Z
    try:
        z0 += wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    except Exception:
        pass
    a = U.to_internal(item["offset_along"], ctx.unit)
    w = U.to_internal(item["width"], ctx.unit)
    sill = U.to_internal(item.get("sill", 0), ctx.unit)
    h = U.to_internal(item["height"], ctx.unit)
    if a < 0 or a + w > line.Length + 1e-6:
        raise RvtssError("Opening runs past the wall end (wall length {:.0f} {})".format(
            U.from_internal(line.Length, ctx.unit), ctx.unit), failed_item=item)
    pa = DB.XYZ(p0.X + d.X * a, p0.Y + d.Y * a, z0 + sill)
    pb = DB.XYZ(p0.X + d.X * (a + w), p0.Y + d.Y * (a + w), z0 + sill + h)
    op = doc.Create.NewOpening(wall, pa, pb)
    return {"kind": "wall_opening", "id": id_int(op), "wall_id": id_int(wall)}


def _host_opening(ctx, item):
    """Opening cut perpendicular through a floor, roof or ceiling from a plan boundary."""
    doc = ctx.doc
    host = core.get_element(doc, item.get("host_id"), "Host")
    lv = doc.GetElement(host.LevelId) if is_valid_id(host.LevelId) else None
    z = lv.Elevation if lv is not None else 0.0
    prof = DB.CurveArray()
    pts = [U.point_from(p, ctx.unit) for p in item.get("boundary") or []]
    if len(pts) < 3:
        raise RvtssError("'boundary' needs at least 3 points", failed_item=item)
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        prof.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z), DB.XYZ(b[0], b[1], z)))
    op = doc.Create.NewOpening(host, prof, True)
    return {"kind": "opening", "id": id_int(op), "host_id": id_int(host)}


def _shaft(ctx, item):
    doc = ctx.doc
    core.require_project(doc)
    bottom = core.find_level(doc, item.get("level") or item.get("base_level"))
    top = core.find_level(doc, item.get("top_level"))
    prof = DB.CurveArray()
    for ln in _outline(ctx, item, bottom):
        prof.Append(ln)
    op = doc.Create.NewOpening(bottom, top, prof)
    if item.get("base_offset") is not None:
        _set_param(op, ["WALL_BASE_OFFSET"], U.to_internal(item["base_offset"], ctx.unit))
    if item.get("top_offset") is not None:
        _set_param(op, ["WALL_TOP_OFFSET"], U.to_internal(item["top_offset"], ctx.unit))
    return {"kind": "shaft", "id": id_int(op)}


def _railing(ctx, item):
    from Autodesk.Revit.DB import Architecture as A

    doc = ctx.doc
    core.require_project(doc)
    rt = _system_type(doc, item, A.RailingType, None, "railing")
    if item.get("host_id") is not None:  # stairs or ramp
        host = core.get_element(doc, item["host_id"], "Stairs/ramp")
        pos = getattr(A.RailingPlacementPosition, item.get("position", "treads").title(), A.RailingPlacementPosition.Treads)
        ids = A.Railing.Create(doc, host.Id, rt.Id, pos)
        return {"kind": "railing", "ids": [id_int(i) for i in ids], "type": normalize_string(get_element_name(rt))}
    level = core.find_level(doc, item.get("level"))
    pts = _route_points(ctx, item, level)
    loop = DB.CurveLoop()
    for a, b in zip(pts, pts[1:]):
        loop.Append(DB.Line.CreateBound(a, b))
    r = A.Railing.Create(doc, loop, rt.Id, level.Id)
    return {"kind": "railing", "id": id_int(r), "type": normalize_string(get_element_name(rt))}


# ------------------------------- spaces, areas, boundaries, rebar, toposolid, mesh (2.3)
def _named_spatial(el, item):
    if item.get("name"):
        _set_param(el, ["ROOM_NAME"], text_type(item["name"]))
    if item.get("number") is not None:
        _set_param(el, ["ROOM_NUMBER"], text_type(item["number"]))


def _space(ctx, item):
    doc = ctx.doc
    core.require_project(doc)
    level = core.find_level(doc, item.get("level"))
    x, y, _z = U.point_from(item.get("point"), ctx.unit)
    sp = doc.Create.NewSpace(level, DB.UV(x, y))
    _named_spatial(sp, item)
    return {"kind": "space", "id": id_int(sp)}


def _area_view(ctx, item):
    v = core.find_view(ctx.doc, item.get("area_view") or item.get("view"), default_active=True, uidoc=ctx.uidoc)
    if not isinstance(v, DB.ViewPlan) or v.ViewType != DB.ViewType.AreaPlan:
        raise RvtssError("'area_view' must be an area plan (got {})".format(v.ViewType),
                         hint="Create one with create_view(kind='area_plan').")
    return v


def _area(ctx, item):
    doc = ctx.doc
    v = _area_view(ctx, item)
    x, y, _z = U.point_from(item.get("point"), ctx.unit)
    a = doc.Create.NewArea(v, DB.UV(x, y))
    _named_spatial(a, item)
    return {"kind": "area", "id": id_int(a), "area_view_id": id_int(v)}


def _boundary_lines(ctx, item, kind):
    """area_boundary (area plan) or room_separation / space_separation (plan view) lines from 'points'."""
    doc = ctx.doc
    if kind == "area_boundary":
        v = _area_view(ctx, item)
        z = v.GenLevel.Elevation if v.GenLevel else 0.0
    else:
        v = core.find_view(doc, item.get("view"), default_active=True, uidoc=ctx.uidoc)
        if not isinstance(v, DB.ViewPlan) or v.GenLevel is None:
            raise RvtssError("'view' must be a floor plan for {} lines".format(kind))
        z = v.GenLevel.Elevation
    raw = item.get("points") or []
    if len(raw) < 2:
        raise RvtssError("'points' needs at least 2 points", failed_item=item)
    pts = [U.point_from(p, ctx.unit) for p in raw]
    if item.get("closed"):
        pts.append(pts[0])
    curves = DB.CurveArray()
    for a, b in zip(pts, pts[1:]):
        curves.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z), DB.XYZ(b[0], b[1], z)))
    sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ(0, 0, z)))
    ids = []
    if kind == "area_boundary":
        for c in curves:
            ids.append(id_int(doc.Create.NewAreaBoundaryLine(sp, c, v)))
    elif kind == "room_separation":
        ids = [id_int(m) for m in doc.Create.NewRoomBoundaryLines(sp, curves, v)]
    else:
        ids = [id_int(m) for m in doc.Create.NewSpaceBoundaryLines(sp, curves, v)]
    return {"kind": kind, "ids": ids, "view_id": id_int(v)}


def _auto_rooms(ctx, item):
    doc = ctx.doc
    core.require_project(doc)
    level = core.find_level(doc, item.get("level"))
    ids = list(doc.Create.NewRooms2(level))
    return {"kind": "auto_rooms", "ids": [id_int(i) for i in ids], "count": len(ids)}


def _rebar(ctx, item):
    """Rebar from a polyline in a host (beam, column, wall, floor, foundation), optional fixed-number layout."""
    from System.Collections.Generic import List
    from Autodesk.Revit.DB import Structure as S

    doc = ctx.doc
    host = core.get_element(doc, item.get("host_id"), "Host")
    if not S.RebarHostData.IsValidHost(host):
        raise RvtssError("Element {} cannot host rebar".format(id_int(host)))
    bt = _system_type(doc, item, S.RebarBarType, None, "rebar bar")
    raw = item.get("points") or []
    if len(raw) < 2:
        raise RvtssError("'points' needs at least 2 [x, y, z] points (bar centre line)", failed_item=item)
    pts = [DB.XYZ(*U.point_from(p, ctx.unit)) for p in raw]
    curves = List[DB.Curve]()
    for a, b in zip(pts, pts[1:]):
        curves.Add(DB.Line.CreateBound(a, b))
    nx, ny, nz = item.get("normal") or [0, 0, 1]
    normal = DB.XYZ(float(nx), float(ny), float(nz)).Normalize()
    style = S.RebarStyle.StirrupTie if item.get("style") == "stirrup_tie" else S.RebarStyle.Standard
    bar = S.Rebar.CreateFromCurves(doc, style, bt, None, None, host, normal, curves,
                                   S.RebarHookOrientation.Left, S.RebarHookOrientation.Left, True, True)
    if bar is None:
        raise RvtssError("Revit could not create the bar (curves outside the host or not planar?)")
    out = {"kind": "rebar", "id": id_int(bar), "bar_type": normalize_string(get_element_name(bt))}
    if item.get("count"):
        n = int(item["count"])
        spacing = U.to_internal(item.get("spacing", 200), ctx.unit)
        acc = bar.GetShapeDrivenAccessor() if hasattr(bar, "GetShapeDrivenAccessor") else bar
        acc.SetLayoutAsFixedNumber(n, spacing * (n - 1), True, True, True)
        out["layout"] = {"count": n, "spacing": item.get("spacing", 200)}
    return out


def _toposolid(ctx, item):
    from System.Collections.Generic import List

    doc = ctx.doc
    core.require_project(doc)
    if not hasattr(DB, "Toposolid"):
        raise RvtssError("Toposolids need Revit 2024 or later")
    level = core.find_level(doc, item.get("level"))
    tt = _system_type(doc, item, DB.ToposolidType, None, "toposolid")
    raw = item.get("points") or []
    if len(raw) < 3:
        raise RvtssError("'points' needs at least 3 [x, y, z] survey points", failed_item=item)
    pts = List[DB.XYZ]()
    for p in raw:
        pts.Add(DB.XYZ(*U.point_from(p, ctx.unit)))
    ts = DB.Toposolid.Create(doc, pts, tt.Id, level.Id)
    return {"kind": "toposolid", "id": id_int(ts), "type": normalize_string(get_element_name(tt))}


def _read_obj(path, limit=200000):
    verts, faces = [], []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif parts[0] == "f" and len(parts) >= 4:
                faces.append([int(x.split("/")[0]) - 1 for x in parts[1:]])
                if len(faces) > limit:
                    raise RvtssError("Mesh has more than {} faces".format(limit))
    return verts, faces


def _direct_shape(ctx, item):
    """DirectShape mesh: inline vertices/faces (in `unit`, faces = vertex index lists) or an .obj file."""
    from System.Collections.Generic import List

    doc = ctx.doc
    if item.get("obj_file"):
        verts, faces = _read_obj(item["obj_file"])
        scale = U.to_internal(1.0, item.get("obj_unit") or ctx.unit)
        verts = [[v[0] * scale, v[1] * scale, v[2] * scale] for v in verts]
    else:
        verts = [list(U.point_from(v, ctx.unit)) for v in item.get("vertices") or []]
        faces = item.get("faces") or []
    if len(verts) < 3 or not faces:
        raise RvtssError("direct_shape needs 'vertices' + 'faces' or 'obj_file'", failed_item=item)
    cat = core.resolve_category(doc, item.get("category") or "Generic Models")
    mat = DB.ElementId.InvalidElementId
    if item.get("material"):
        m = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.Material)
             if normalize_string(x.Name).lower() == text_type(item["material"]).strip().lower()]
        if m:
            mat = m[0].Id
    b = DB.TessellatedShapeBuilder()
    b.OpenConnectedFaceSet(False)
    for f in faces:
        loop = List[DB.XYZ]()
        for i in f:
            v = verts[int(i)]
            loop.Add(DB.XYZ(v[0], v[1], v[2]))
        b.AddFace(DB.TessellatedFace(loop, mat))
    b.CloseConnectedFaceSet()
    b.Target = DB.TessellatedShapeBuilderTarget.AnyGeometry
    b.Fallback = DB.TessellatedShapeBuilderFallback.Mesh
    b.Build()
    res = b.GetBuildResult()
    ds = DB.DirectShape.CreateElement(doc, cat.Id)
    ds.SetShape(res.GetGeometricalObjects())
    if item.get("name"):
        ds.Name = text_type(item["name"])
    return {"kind": "direct_shape", "id": id_int(ds), "faces": len(faces),
            "outcome": text_type(res.Outcome), "category": normalize_string(cat.Name)}


_STRUCTURE_KINDS = {"roof": _roof, "ceiling": _ceiling, "column": _column, "beam": _beam,
                    "foundation": _foundation, "wall_foundation": _wall_foundation,
                    "duct": lambda c, i: _mep_run(c, i, "duct"), "pipe": lambda c, i: _mep_run(c, i, "pipe"),
                    "cable_tray": lambda c, i: _mep_run(c, i, "cable_tray"),
                    "conduit": lambda c, i: _mep_run(c, i, "conduit"),
                    "wall_opening": _wall_opening, "opening": _host_opening, "shaft": _shaft,
                    "railing": _railing, "space": _space, "area": _area,
                    "area_boundary": lambda c, i: _boundary_lines(c, i, "area_boundary"),
                    "room_separation": lambda c, i: _boundary_lines(c, i, "room_separation"),
                    "space_separation": lambda c, i: _boundary_lines(c, i, "space_separation"),
                    "auto_rooms": _auto_rooms, "rebar": _rebar, "toposolid": _toposolid,
                    "direct_shape": _direct_shape}


# ------------------- curtain walls, sweeps, model lines, reference planes, structure (2.4)
def _wall_of(ctx, item, what):
    if item.get("wall_id") is None:
        raise RvtssError("'wall_id' is required", failed_item=item)
    wall = core.get_element(ctx.doc, item["wall_id"], "Wall")
    if not isinstance(wall, DB.Wall):
        raise RvtssError("Element {} is not a wall ({} needs one)".format(item["wall_id"], what))
    return wall


def _curtain_grid(ctx, item, what):
    wall = _wall_of(ctx, item, what)
    grid = wall.CurtainGrid
    if grid is None:
        raise RvtssError("Wall {} is not a curtain wall".format(id_int(wall)),
                         hint="Create the wall with a curtain wall type first.")
    return wall, grid


def _wall_base(doc, wall):
    """(start point, direction, length, base z) of a straight wall."""
    if not isinstance(wall.Location, DB.LocationCurve) or not isinstance(wall.Location.Curve, DB.Line):
        raise RvtssError("Wall {} is not straight".format(id_int(wall)))
    line = wall.Location.Curve
    base = doc.GetElement(wall.LevelId)
    z = base.Elevation if base is not None else line.GetEndPoint(0).Z
    try:
        z += wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    except Exception:
        pass
    return line.GetEndPoint(0), line.Direction, line.Length, z


def _curtain_grid_line(ctx, item):
    """A grid line on a curtain wall: vertical at 'offset_along' from the wall start, or horizontal at
    'height' above the wall base ('point' [x, y, z] on the wall face works for both)."""
    doc = ctx.doc
    wall, grid = _curtain_grid(ctx, item, "curtain_grid_line")
    direction = text_type(item.get("direction") or "vertical").lower()
    if direction not in ("vertical", "horizontal"):
        raise RvtssError("direction must be 'vertical' or 'horizontal'", failed_item=item)
    if item.get("point") is not None:
        pt = _pt(ctx, item, "point")
    else:
        p0, d, length, z0 = _wall_base(doc, wall)
        if direction == "vertical":
            if item.get("offset_along") is None:
                raise RvtssError("a vertical grid line needs 'offset_along' (from the wall start) or 'point'",
                                 failed_item=item)
            a = U.to_internal(item["offset_along"], ctx.unit)
            if a <= 0 or a >= length:
                raise RvtssError("offset_along is outside the wall (length {:.0f} {})".format(
                    U.from_internal(length, ctx.unit), ctx.unit), failed_item=item)
            h = U.to_internal(item.get("height", 0), ctx.unit)
            pt = DB.XYZ(p0.X + d.X * a, p0.Y + d.Y * a, z0 + h)
        else:
            if item.get("height") is None:
                raise RvtssError("a horizontal grid line needs 'height' (above the wall base) or 'point'",
                                 failed_item=item)
            a = U.to_internal(item["offset_along"], ctx.unit) if item.get("offset_along") is not None \
                else length / 2.0
            pt = DB.XYZ(p0.X + d.X * a, p0.Y + d.Y * a, z0 + U.to_internal(item["height"], ctx.unit))
    # U grid lines are the horizontal ones on a curtain wall, V grid lines the vertical ones
    gl = grid.AddGridLine(direction == "horizontal", pt, bool(item.get("one_segment_only", False)))
    if gl is None:
        raise RvtssError("Revit did not add the grid line (is the point on the curtain wall?)", failed_item=item)
    return {"kind": "curtain_grid_line", "id": id_int(gl), "wall_id": id_int(wall), "direction": direction}


def _mullions(ctx, item):
    """Mullions on the grid lines of a curtain wall (lines: all | horizontal | vertical, or grid_line_ids)."""
    doc = ctx.doc
    wall, grid = _curtain_grid(ctx, item, "mullions")
    types = list(DB.FilteredElementCollector(doc).OfClass(DB.MullionType))
    if not types:
        raise RvtssError("No mullion type exists in '{}'".format(doc.Title),
                         hint="Load or create a mullion type (rectangular / circular mullion) first.")
    if item.get("type") or item.get("type_id") is not None:
        mt = core.find_type(doc, family=item.get("family"), type_name=item.get("type"),
                            type_id=item.get("type_id"), of_class=DB.MullionType)
    else:
        mt = types[0]
    which = text_type(item.get("lines") or "all").lower()
    if item.get("grid_line_ids"):
        line_ids = [core.get_element(doc, i, "Curtain grid line").Id for i in item["grid_line_ids"]]
    else:
        line_ids = []
        if which in ("all", "horizontal"):
            line_ids.extend(grid.GetUGridLineIds())
        if which in ("all", "vertical"):
            line_ids.extend(grid.GetVGridLineIds())
        if which not in ("all", "horizontal", "vertical"):
            raise RvtssError("lines must be all, horizontal or vertical", failed_item=item)
    if not line_ids:
        raise RvtssError("Curtain wall {} has no grid lines".format(id_int(wall)),
                         hint="Add them with kind='curtain_grid_line' first.")
    created, errors = [], []
    for lid in line_ids:
        gl = doc.GetElement(lid)
        try:
            seg = None
            for c in gl.AllSegmentCurves:
                seg = c
                break
            if seg is None:
                raise RvtssError("grid line has no segment")
            for m in gl.AddMullions(seg, mt, False):
                created.append(id_int(m))
        except Exception as ex:   # e.g. mullions already exist on the line
            errors.append({"grid_line_id": id_int(lid),
                           "error": ex.message if isinstance(ex, RvtssError) else normalize_string(text_type(ex))})
    if not created and errors:
        raise RvtssError("No mullion was added: {}".format(errors[0]["error"]), failed_item=item, errors=errors[:20])
    out = {"kind": "mullions", "ids": created, "wall_id": id_int(wall),
           "type": normalize_string(get_element_name(mt)), "grid_lines": len(line_ids)}
    if errors:
        out["errors"] = errors[:20]
    return out


def _curtain_panel_type(ctx, item):
    """Change the type of curtain panels: all panels of a curtain wall, or panel_ids."""
    doc = ctx.doc
    if item.get("panel_ids"):
        panels = core.get_elements(doc, item["panel_ids"], "Panel")
        wall_id = None
    else:
        wall, grid = _curtain_grid(ctx, item, "curtain_panel_type")
        panels = [doc.GetElement(i) for i in grid.GetPanelIds()]
        wall_id = id_int(wall)
    if not (item.get("type") or item.get("type_id") is not None):
        raise RvtssError("'type' (or type_id) is required: a panel type, a wall type or a curtain panel family "
                         "type", failed_item=item)
    t = core.find_type(doc, family=item.get("family"), type_name=item.get("type"), type_id=item.get("type_id"))
    unpin = bool(item.get("unpin", False))
    changed, skipped = [], []
    for p in panels:
        if p is None:
            continue
        if getattr(p, "Pinned", False):
            if not unpin:
                skipped.append({"id": id_int(p), "reason": "pinned (set by the curtain wall type); pass unpin=true"})
                continue
            p.Pinned = False
        try:
            if t.Id not in list(p.GetValidTypes()):
                skipped.append({"id": id_int(p), "reason": "type is not valid for this panel"})
                continue
            p.ChangeTypeId(t.Id)
            changed.append(id_int(p))
        except Exception as ex:
            skipped.append({"id": id_int(p), "reason": normalize_string(text_type(ex))})
    if not changed:
        raise RvtssError("No panel was changed", failed_item=item, skipped=skipped[:20])
    return {"kind": "curtain_panel_type", "ids": changed, "wall_id": wall_id,
            "type": normalize_string(get_element_name(t)), "skipped": skipped[:50]}


def _wall_sweep(ctx, item, kind):
    """A wall sweep or reveal: horizontal at 'distance' above the base, or vertical at 'distance' along the wall."""
    doc = ctx.doc
    wall = _wall_of(ctx, item, kind)
    if not (hasattr(DB, "WallSweep") and hasattr(DB.WallSweep, "Create")):
        raise RvtssError("Wall sweeps cannot be created through the API in this Revit version")
    reveal = kind == "reveal"
    bic = DB.BuiltInCategory.OST_Reveals if reveal else DB.BuiltInCategory.OST_Cornices
    types = list(DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType())
    if not types:
        raise RvtssError("No {} type exists in '{}'".format("reveal" if reveal else "wall sweep", doc.Title),
                         hint="Create a type in Revit (Architecture > Wall > Wall: {}) and load a profile "
                              "family.".format("Reveal" if reveal else "Sweep"))
    st = types[0]
    if item.get("type_id") is not None:
        st = core.find_type(doc, type_id=item["type_id"])
    elif item.get("type"):
        key = text_type(item["type"]).strip().lower()
        match = [t for t in types if normalize_string(get_element_name(t)).lower() == key]
        if not match:
            raise not_found_type("{} type".format(kind), item["type"], [get_element_name(t) for t in types])
        st = match[0]
    vertical = bool(item.get("vertical", False))
    info = DB.WallSweepInfo(DB.WallSweepType.Reveal if reveal else DB.WallSweepType.Sweep, vertical)
    info.Distance = U.to_internal(item.get("distance", 0), ctx.unit)
    side = text_type(item.get("side") or "exterior").lower()
    info.WallSide = DB.WallSide.Interior if side == "interior" else DB.WallSide.Exterior
    if not vertical:
        info.DistanceMeasuredFrom = DB.DistanceMeasuredFrom.Top if item.get("from_top") \
            else DB.DistanceMeasuredFrom.Base
    if item.get("wall_offset") is not None:
        info.WallOffset = U.to_internal(item["wall_offset"], ctx.unit)
    ws = DB.WallSweep.Create(wall, st.Id, info)
    return {"kind": kind, "id": id_int(ws), "wall_id": id_int(wall), "vertical": vertical,
            "type": normalize_string(get_element_name(st))}


def _model_line(ctx, item):
    """Model lines on a horizontal plane: at 'level' (+ 'offset'), else at the z of the first point."""
    doc = ctx.doc
    raw = item.get("points") or ([item["start"], item["end"]] if item.get("start") and item.get("end") else None)
    if not raw or len(raw) < 2:
        raise RvtssError("'points' needs at least 2 points (or start and end)", failed_item=item)
    if item.get("level") is not None:
        z = core.find_level(doc, item["level"]).Elevation + U.to_internal(item.get("offset", 0), ctx.unit)
    else:
        z = U.point_from(raw[0], ctx.unit)[2]
    pts = []
    for p in raw:
        x, y, _z = U.point_from(p, ctx.unit)
        pts.append(DB.XYZ(x, y, z))
    if item.get("closed") and len(pts) > 2:
        pts.append(pts[0])
    sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ(0, 0, z)))
    style = None
    if item.get("line_style"):
        key = text_type(item["line_style"]).strip().lower()
        cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        names = []
        for sub in cat.SubCategories:
            names.append(sub.Name)
            if normalize_string(sub.Name).lower() == key:
                style = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
        if style is None:
            raise core.not_found("Line style", item["line_style"], names)
    creator = doc.FamilyCreate if doc.IsFamilyDocument else doc.Create
    ids = []
    for a, b in zip(pts, pts[1:]):
        if a.DistanceTo(b) < 1e-4:
            raise RvtssError("model_line has two equal consecutive points", failed_item=item)
        mc = creator.NewModelCurve(DB.Line.CreateBound(a, b), sp)
        if style is not None:
            mc.LineStyle = style
        ids.append(id_int(mc))
    return {"kind": "model_line", "ids": ids, "sketch_plane_id": id_int(sp)}


def _reference_plane(ctx, item):
    """A vertical reference plane drawn in plan from start to end (shown in 'view', default the active view)."""
    doc = ctx.doc
    a, b = _pt(ctx, item, "start"), _pt(ctx, item, "end")
    if item.get("level") is not None:
        z = core.find_level(doc, item["level"]).Elevation
        a, b = DB.XYZ(a.X, a.Y, z), DB.XYZ(b.X, b.Y, z)
    if a.DistanceTo(b) < 1e-4:
        raise RvtssError("start and end are the same point", failed_item=item)
    view = core.find_view(doc, item.get("view"))
    creator = doc.FamilyCreate if doc.IsFamilyDocument else doc.Create
    rp = creator.NewReferencePlane(a, b, DB.XYZ.BasisZ, view)
    if rp is None:
        raise RvtssError("Revit did not create the reference plane (use a plan view)", failed_item=item)
    if item.get("name"):
        rp.Name = text_type(item["name"])
    return {"kind": "reference_plane", "id": id_int(rp), "name": normalize_string(rp.Name),
            "view_id": id_int(view)}


def _brace(ctx, item):
    """A structural brace between two 3D points (z defaults to the level elevation)."""
    doc = ctx.doc
    level = core.find_level(doc, item.get("level"))
    sym = _symbol(doc, item, [DB.BuiltInCategory.OST_StructuralFraming], "structural framing (brace)")
    a, b = _level_point(ctx, item, level, "start"), _level_point(ctx, item, level, "end")
    if a.DistanceTo(b) < 1e-4:
        raise RvtssError("start and end are the same point", failed_item=item)
    fi = doc.Create.NewFamilyInstance(DB.Line.CreateBound(a, b), sym, level, DB.Structure.StructuralType.Brace)
    return {"kind": "brace", "id": id_int(fi), "family": normalize_string(sym.Family.Name),
            "type": normalize_string(get_element_name(sym))}


def _truss(ctx, item):
    from Autodesk.Revit.DB import Structure as S

    doc = ctx.doc
    core.require_project(doc)
    level = core.find_level(doc, item.get("level"))
    # TrussType cannot be collected with OfClass ("not in Revit's native object model"): go by category
    types = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Truss)
                 .WhereElementIsElementType())
    if not types:
        raise RvtssError("No truss family is loaded in '{}'".format(doc.Title),
                         hint="Load one (Insert > Load Family > Structural Trusses), then retry.")
    if item.get("type") or item.get("type_id") is not None:
        fam_l = text_type(item.get("family") or "").strip().lower()
        typ_l = text_type(item.get("type") or "").strip().lower()
        tt = None
        for t in types:
            if item.get("type_id") is not None:
                if id_int(t) == int(item["type_id"]):
                    tt = t
            elif (not fam_l or normalize_string(getattr(t, "FamilyName", "") or "").lower() == fam_l) and                     (not typ_l or normalize_string(get_element_name(t)).lower() == typ_l):
                tt = t
            if tt is not None:
                break
        if tt is None:
            raise core.not_found("Truss type", item.get("type") or item.get("type_id") or item.get("family"),
                                 [get_element_name(t) for t in types])
    else:
        tt = types[0]
    z = level.Elevation + U.to_internal(item.get("offset", 0), ctx.unit)
    a, b = _pt(ctx, item, "start"), _pt(ctx, item, "end")
    a, b = DB.XYZ(a.X, a.Y, z), DB.XYZ(b.X, b.Y, z)
    if a.DistanceTo(b) < 1e-4:
        raise RvtssError("start and end are the same point", failed_item=item)
    sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ(0, 0, z)))
    tr = S.Truss.Create(doc, tt.Id, sp.Id, DB.Line.CreateBound(a, b))
    return {"kind": "truss", "id": id_int(tr), "type": normalize_string(get_element_name(tt))}


def _beam_system(ctx, item):
    """A beam system inside a closed boundary; beams run parallel to boundary edge 'direction_edge' (0-based)."""
    from System.Collections.Generic import List

    doc = ctx.doc
    core.require_project(doc)
    level = core.find_level(doc, item.get("level"))
    profile = List[DB.Curve]()
    lines = _outline(ctx, item, level)
    for ln in lines:
        profile.Add(ln)
    edge = int(item.get("direction_edge", 0) or 0)
    if edge < 0 or edge >= len(lines):
        raise RvtssError("direction_edge must be between 0 and {}".format(len(lines) - 1), failed_item=item)
    bs = DB.BeamSystem.Create(doc, profile, level, edge, bool(item.get("is_3d", False)))  # not in DB.Structure
    out = {"kind": "beam_system", "id": id_int(bs)}
    if item.get("type") or item.get("type_id") is not None or item.get("family"):
        sym = _symbol(doc, item, [DB.BuiltInCategory.OST_StructuralFraming], "structural framing (beam)")
        bs.BeamType = sym
        out["beam_type"] = normalize_string(get_element_name(sym))
    try:
        doc.Regenerate()
        out["beam_ids"] = [id_int(i) for i in bs.GetBeamIds()]
    except Exception:
        pass
    return out


def _alias(func, kind):
    def call(ctx, item):
        out = func(ctx, item)
        out["kind"] = kind
        return out
    return call


_MODELLING_KINDS = {"curtain_grid_line": _curtain_grid_line, "mullions": _mullions,
                    "curtain_panel_type": _curtain_panel_type,
                    "wall_sweep": lambda c, i: _wall_sweep(c, i, "wall_sweep"),
                    "reveal": lambda c, i: _wall_sweep(c, i, "reveal"),
                    "model_line": _model_line, "reference_plane": _reference_plane,
                    "foundation_isolated": _alias(_foundation, "foundation_isolated"),
                    "foundation_wall": _alias(_wall_foundation, "foundation_wall"),
                    "brace": _brace, "truss": _truss, "beam_system": _beam_system}


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
