# -*- coding: UTF-8 -*-
"""Materials: inventory, quantity take-off and editing (RVTSS v2.2).

Routes:
    POST /materials/list/      materials with class, colour, transparency, appearance asset, patterns, usage
    POST /materials/takeoff/   area / volume per material from element geometry, grouped
    POST /materials/manage/    create, duplicate, rename, set properties, assign to elements / types / layers
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, text_type
from .query import collect, query_spec
from .pure import units as U
from .pure import filters as F
from .utils import normalize_string

logger = logging.getLogger(__name__)


def _hex(color):
    try:
        if color is None or not color.IsValid:
            return None
        return "#{:02X}{:02X}{:02X}".format(color.Red, color.Green, color.Blue)
    except Exception:
        return None


def _name(doc, eid):
    if not is_valid_id(eid):
        return None
    e = doc.GetElement(eid)
    return normalize_string(e.Name) if e is not None else None


def _pattern_ids(m):
    out = {}
    for key, attrs in (("surface_pattern", ("SurfaceForegroundPatternId", "SurfacePatternId")),
                       ("cut_pattern", ("CutForegroundPatternId", "CutPatternId"))):
        for a in attrs:
            try:
                out[key] = getattr(m, a)
                break
            except Exception:
                continue
    return out


def _describe(doc, m):
    d = {"id": id_int(m), "name": normalize_string(m.Name), "class": normalize_string(m.MaterialClass or ""),
         "category": normalize_string(getattr(m, "MaterialCategory", "") or ""), "color": _hex(m.Color),
         "transparency": m.Transparency, "shininess": m.Shininess}
    try:
        d["appearance_asset"] = _name(doc, m.AppearanceAssetId)
    except Exception:
        pass
    for key, pid in _pattern_ids(m).items():
        d[key] = _name(doc, pid)
    return d


def _usage_counts(doc):
    counts = {}
    col = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
    for e in col:
        cat = e.Category
        if cat is None or cat.CategoryType != DB.CategoryType.Model:
            continue
        try:
            for mid in list(e.GetMaterialIds(False)) + list(e.GetMaterialIds(True)):
                counts[id_int(mid)] = counts.get(id_int(mid), 0) + 1
        except Exception:
            continue
    return counts


def list_materials(ctx):
    doc = ctx.doc
    contains = (ctx.get("contains") or "").lower()
    mclass = (ctx.get("material_class") or "").lower()
    usage = _usage_counts(doc) if ctx.bool("include_usage", False) else None
    items = []
    for m in DB.FilteredElementCollector(doc).OfClass(DB.Material):
        d = _describe(doc, m)
        if contains and contains not in d["name"].lower():
            continue
        if mclass and d["class"].lower() != mclass:
            continue
        if usage is not None:
            d["used_by_elements"] = usage.get(d["id"], 0)
        items.append(d)
    if usage is not None and ctx.bool("unused_only", False):
        items = [d for d in items if not d["used_by_elements"]]
    items.sort(key=lambda d: d["name"].lower())
    page, meta = F.paginate(items, ctx.int("offset", 0), ctx.int("limit", 200, 1, core.MAX_LIMIT))
    classes = {}
    for d in items:
        classes[d["class"] or "(none)"] = classes.get(d["class"] or "(none)", 0) + 1
    return {"count": len(items), "by_class": classes, "pagination": meta, "materials": page}


def takeoff(ctx):
    doc = ctx.doc
    core.require_project(doc)
    spec = query_spec(ctx.data)
    if not any(spec.get(k) for k in ("element_ids", "selection", "categories", "view", "level", "class_name")):
        raise RvtssError("Give a scope: categories, element_ids, view, level or selection",
                         hint="e.g. categories=['Walls','Floors'] for a structure take-off.")
    try:
        area_unit = U.length_unit_for("area", ctx.get("area_unit") or "m2")
        volume_unit = U.length_unit_for("volume", ctx.get("volume_unit") or "m3")
    except U.UnitError as e:
        raise RvtssError(str(e))
    group_by = ctx.list("group_by") or ["material"]
    for g in group_by:
        if g not in ("material", "category", "level", "type"):
            raise RvtssError("group_by entries must be material, category, level or type")
    include_paint = ctx.bool("include_paint", True)
    elements = collect(ctx, spec, max_scan=ctx.int("max_scan", 200000))
    groups = {}
    scanned = 0
    for e in elements:
        try:
            mids = list(e.GetMaterialIds(False))
            pids = list(e.GetMaterialIds(True)) if include_paint else []
        except Exception:
            continue
        if not mids and not pids:
            continue
        scanned += 1
        brief = None
        for mid, painted in [(m, False) for m in mids] + [(p, True) for p in pids]:
            try:
                area = e.GetMaterialArea(mid, painted)
                volume = 0.0 if painted else e.GetMaterialVolume(mid)
            except Exception:
                continue
            if brief is None:
                brief = core.element_brief(doc, e)
                brief["level"] = core.element_level(doc, e)
            key_parts = []
            for g in group_by:
                if g == "material":
                    key_parts.append(_name(doc, mid) or "(none)")
                elif g == "category":
                    key_parts.append(brief.get("category") or "(none)")
                elif g == "level":
                    key_parts.append(brief.get("level") or "(none)")
                else:
                    key_parts.append(u"{} : {}".format(brief.get("family") or "", brief.get("type") or ""))
            key = tuple(key_parts)
            grp = groups.setdefault(key, {"area": 0.0, "volume": 0.0, "painted_area": 0.0, "elements": set()})
            if painted:
                grp["painted_area"] += area
            else:
                grp["area"] += area
                grp["volume"] += volume
            grp["elements"].add(id_int(e))
    rows = []
    for key, grp in groups.items():
        row = dict(zip(group_by, key))
        row.update({"area": U.from_internal(grp["area"], area_unit, 3),
                    "volume": U.from_internal(grp["volume"], volume_unit, 4),
                    "painted_area": U.from_internal(grp["painted_area"], area_unit, 3),
                    "element_count": len(grp["elements"]), "element_ids": sorted(grp["elements"])[:50]})
        rows.append(row)
    rows.sort(key=lambda r: -(r["volume"] or 0) - (r["area"] or 0) * 1e-6)
    page, meta = F.paginate(rows, ctx.int("offset", 0), ctx.int("limit", 200, 1, 2000))
    return {"area_unit": area_unit, "volume_unit": volume_unit, "group_by": group_by,
            "elements_in_scope": len(elements), "elements_with_materials": scanned,
            "total_area": round(sum(r["area"] for r in rows), 3),
            "total_volume": round(sum(r["volume"] for r in rows), 4),
            "note": "Area is the material's exposed face area Revit reports (GetMaterialArea); volume comes from "
                    "element geometry. Paint is reported separately (painted_area).",
            "pagination": meta, "rows": page}


def _color(hexstr):
    h = text_type(hexstr).lstrip("#")
    if len(h) != 6:
        raise RvtssError("Colours must be hex like '#C0C0C0'")
    return DB.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def find_material(doc, name_or_id):
    if name_or_id is None:
        raise RvtssError("'material' (name or id) is required")
    mats = list(DB.FilteredElementCollector(doc).OfClass(DB.Material))
    s = text_type(name_or_id).strip()
    if s.isdigit():
        e = doc.GetElement(core.make_id(int(s)))
        if isinstance(e, DB.Material):
            return e
    for m in mats:
        if normalize_string(m.Name).lower() == s.lower():
            return m
    raise core.not_found("Material", name_or_id, [m.Name for m in mats], hint="Use list_materials.")


def _fill_pattern(doc, name, drafting=True):
    """Cut patterns must be drafting patterns; surface patterns may be model or drafting (2019+)."""
    for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        try:
            pat = fp.GetFillPattern()
            if normalize_string(fp.Name).lower() == text_type(name).lower() and \
                    (not drafting or pat.Target == DB.FillPatternTarget.Drafting or pat.IsSolidFill):
                return fp
        except Exception:
            continue
    raise core.not_found("Fill pattern", name, [fp.Name for fp in DB.FilteredElementCollector(doc)
                                                .OfClass(DB.FillPatternElement)])


def _set_props(doc, m, props, warn):
    if props.get("color"):
        m.Color = _color(props["color"])
    if props.get("transparency") is not None:
        m.Transparency = max(0, min(100, int(props["transparency"])))
    if props.get("shininess") is not None:
        m.Shininess = max(0, min(128, int(props["shininess"])))
    if props.get("material_class"):
        m.MaterialClass = props["material_class"]
    if props.get("use_render_appearance") is not None:
        m.UseRenderAppearanceForShading = bool(props["use_render_appearance"])
    for key, attrs, drafting in (("surface_pattern", ("SurfaceForegroundPatternId", "SurfacePatternId"), False),
                                 ("cut_pattern", ("CutForegroundPatternId", "CutPatternId"), True)):
        if props.get(key):
            fp = _fill_pattern(doc, props[key], drafting)
            for a in attrs:
                try:
                    setattr(m, a, fp.Id)
                    break
                except Exception:
                    continue
            else:
                warn("{} not applied on this Revit version".format(key))
    for key, attrs in (("surface_pattern_color", ("SurfaceForegroundPatternColor", "SurfacePatternColor")),
                       ("cut_pattern_color", ("CutForegroundPatternColor", "CutPatternColor"))):
        if props.get(key):
            c = _color(props[key])
            for a in attrs:
                try:
                    setattr(m, a, c)
                    break
                except Exception:
                    continue


def _assign(doc, ctx, mat):
    """Material -> instance/type material parameters, or compound-structure layers of host types."""
    param_name = ctx.get("parameter") or "Material"
    from .params_util import find as find_param

    done, skipped = [], []
    layer = ctx.get("layer_index")
    for e in core.get_elements(doc, ctx.list("element_ids")):
        if layer is not None:
            target = e if isinstance(e, DB.HostObjAttributes) else doc.GetElement(e.GetTypeId())
            if not isinstance(target, DB.HostObjAttributes):
                skipped.append({"id": id_int(e), "reason": "no compound structure (walls, floors, roofs, ceilings)"})
                continue
            cs = target.GetCompoundStructure()
            if cs is None or int(layer) < 0 or int(layer) >= cs.LayerCount:
                skipped.append({"id": id_int(e), "reason": "layer_index out of range"})
                continue
            cs.SetMaterialId(int(layer), mat.Id)
            target.SetCompoundStructure(cs)
            done.append({"id": id_int(target), "layer_index": int(layer), "type_edit": True})
            continue
        p, owner = find_param(doc, e, param_name)
        if p is None or p.IsReadOnly or p.StorageType != DB.StorageType.ElementId:
            skipped.append({"id": id_int(e), "reason": "no writable material parameter '{}'".format(param_name)})
            continue
        p.Set(mat.Id)
        done.append({"id": id_int(e), "parameter": param_name, "on": owner,
                     "note": "type parameter: every instance of the type changes" if owner == "type" else None})
    if not done and skipped:
        raise RvtssError("Nothing assigned: {}".format(skipped[0]["reason"]), skipped=skipped[:20])
    return done, skipped


def manage(ctx):
    doc = ctx.doc
    action = ctx.require("action")
    dry = ctx.dry_run
    props = ctx.get("properties") or {}
    forced = False
    if action == "assign":
        ids = ctx.list("element_ids")
        if not ids:
            raise RvtssError("assign needs element_ids")
        if core.confirm_gate(ctx, len(ids), "Material assignment"):
            forced = not ctx.dry_run
            dry = True

    def run():
        if action == "create":
            name = ctx.require("name")
            if any(normalize_string(m.Name).lower() == name.lower()
                   for m in DB.FilteredElementCollector(doc).OfClass(DB.Material)):
                raise RvtssError("A material named '{}' already exists".format(name), status=409,
                                 hint="Use action='set_properties' or pick another name.")
            m = doc.GetElement(DB.Material.Create(doc, name))
            _set_props(doc, m, props, ctx.warn)
            return {"material": _describe(doc, m)}
        mat = find_material(doc, ctx.get("material"))
        if action == "duplicate":
            m = mat.Duplicate(ctx.require("name"))
            _set_props(doc, m, props, ctx.warn)
            return {"material": _describe(doc, m), "source": normalize_string(mat.Name)}
        if action == "rename":
            old = normalize_string(mat.Name)
            mat.Name = ctx.require("name")
            return {"material": _describe(doc, mat), "old_name": old}
        if action == "set_properties":
            if not props:
                raise RvtssError("set_properties needs 'properties'")
            _set_props(doc, mat, props, ctx.warn)
            return {"material": _describe(doc, mat)}
        if action == "assign":
            done, skipped = _assign(doc, ctx, mat)
            return {"material": normalize_string(mat.Name), "assigned": done, "skipped": skipped}
        raise RvtssError("action must be create, duplicate, rename, set_properties or assign")

    res, fails = core.run_transaction(doc, "Materials: " + action, run, dry_run=dry)
    return core.preview_status(core.commit_result(res, fails, dry), forced)


def register_materials_routes(api):
    @api.route("/materials/list/", methods=["POST"])
    def materials_list_route(doc, request):
        return handle(doc, request, list_materials)

    @api.route("/materials/takeoff/", methods=["POST"])
    def materials_takeoff_route(doc, uidoc, request):
        return handle(doc, request, takeoff, uidoc=uidoc)

    @api.route("/materials/manage/", methods=["POST"])
    def materials_manage_route(doc, request):
        return handle(doc, request, manage)

    logger.info("RVTSS materials routes registered")
