# -*- coding: UTF-8 -*-
"""Annotation: untagged-element checks, tagging and text notes (RVTSS v2.2).

Routes:
    POST /annotation/untagged/   elements of categories visible in a view without a tag in that view
    POST /annotation/tag/        tag elements (by ids or category) - rooms/spaces/areas get their own tags
    POST /annotation/text/       place text notes
    POST /annotation/detail/     dimensions, detail lines and filled regions in one view (v2.3)
    POST /annotation/types/      text, tag, dimension, filled region types and line styles (v2.3)
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, text_type, bic_from_category
from .pure import units as U
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

NO_ANNOTATION_VIEWS = ("Schedule", "ColumnSchedule", "ProjectBrowser", "SystemBrowser", "Internal", "Undefined",
                       "Report", "CostReport", "LoadsReport", "PresureLossReport", "PanelSchedule")
SPATIAL_TAG = {"OST_Rooms": "room", "OST_MEPSpaces": "space", "OST_Areas": "area"}


def _annotation_view(ctx):
    view = core.find_view(ctx.doc, ctx.get("view", "active"), uidoc=ctx.uidoc)
    if view.IsTemplate or str(view.ViewType) in NO_ANNOTATION_VIEWS:
        raise RvtssError("View '{}' ({}) cannot hold tags or text".format(normalize_string(view.Name), view.ViewType),
                         status=409, hint="Use a plan, section, elevation, 3D (locked) or drafting view.")
    return view


def _tagged_local_ids(tag):
    try:
        return [id_int(i) for i in tag.GetTaggedLocalElementIds()]  # 2022+
    except Exception:
        pass
    try:
        eid = tag.TaggedLocalElementId
        return [id_int(eid)] if is_valid_id(eid) else []
    except Exception:
        return []


def tagged_ids_in_view(doc, view):
    """Ids of elements tagged in this view (independent tags, room / space / area tags)."""
    ids = set()
    for tag in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.IndependentTag):
        ids.update(_tagged_local_ids(tag))
    for bic, attr in (("OST_RoomTags", "Room"), ("OST_MEPSpaceTags", "Space"), ("OST_AreaTags", "Area")):
        try:
            col = DB.FilteredElementCollector(doc, view.Id).OfCategory(getattr(DB.BuiltInCategory, bic)) \
                .WhereElementIsNotElementType()
        except Exception:
            continue
        for t in col:
            try:
                target = getattr(t, attr)
                if target is not None:
                    ids.add(id_int(target))
            except Exception:
                continue
    return ids


def _visible(doc, view, cat):
    return list(DB.FilteredElementCollector(doc, view.Id).OfCategoryId(cat.Id).WhereElementIsNotElementType())


def untagged(ctx):
    doc = ctx.doc
    core.require_project(doc)
    cats = ctx.list("categories")
    if not cats:
        raise RvtssError("'categories' is required, e.g. ['Doors','Windows','Rooms']")
    view = _annotation_view(ctx)
    limit = ctx.int("limit", 200, 1, 2000)
    tagged = tagged_ids_in_view(doc, view)
    out, total_untagged = [], 0
    for name in cats:
        cat = core.resolve_category(doc, name)
        elems = _visible(doc, view, cat)
        if SPATIAL_TAG.get(bic_from_category(cat)):
            elems = [e for e in elems if e.Location is not None and (getattr(e, "Area", 0) or 0) > 0]
        missing = [e for e in elems if id_int(e) not in tagged]
        total_untagged += len(missing)
        out.append({"category": normalize_string(cat.Name), "visible": len(elems), "tagged": len(elems) - len(missing),
                    "untagged": len(missing), "truncated": len(missing) > limit,
                    "untagged_elements": [core.element_brief(doc, e) for e in missing[:limit]]})
    return {"view": normalize_string(view.Name), "view_id": id_int(view), "untagged_total": total_untagged,
            "categories": out,
            "next_step": "tag_elements(view=..., categories=[...]) tags only what is untagged (skip_tagged=true)."
            if total_untagged else None}


def _tag_type(doc, spec):
    if spec is None:
        return None
    if text_type(spec).isdigit():
        return core.find_type(doc, type_id=int(spec))
    fam, _sep, typ = text_type(spec).partition(":")
    if typ:
        return core.find_type(doc, family=fam.strip(), type_name=typ.strip())
    return core.find_type(doc, type_name=fam.strip())


def tag(ctx):
    doc = ctx.doc
    core.require_project(doc)
    view = _annotation_view(ctx)
    unit = ctx.unit
    ids = ctx.list("element_ids")
    cats = ctx.list("categories")
    if not ids and not cats:
        raise RvtssError("Give element_ids or categories (tagged in the view)")
    elements, seen = [], set()
    for e in (core.get_elements(doc, ids) if ids else []):
        if id_int(e) not in seen:
            seen.add(id_int(e))
            elements.append(e)
    for name in cats:
        for e in _visible(doc, view, core.resolve_category(doc, name)):
            if id_int(e) not in seen:
                seen.add(id_int(e))
                elements.append(e)
    skipped = []
    if ctx.bool("skip_tagged", True):
        tagged = tagged_ids_in_view(doc, view)
        kept = []
        for e in elements:
            if id_int(e) in tagged:
                skipped.append({"id": id_int(e), "reason": "already tagged in this view"})
            else:
                kept.append(e)
        elements = kept
    ttype = _tag_type(doc, ctx.get("tag_type"))
    offset = ctx.list("offset") or [0, 0]
    dx, dy, _dz = U.point_from(offset, unit)
    leader = ctx.bool("leader", False)
    orient = DB.TagOrientation.Vertical if ctx.get("orientation") == "vertical" else DB.TagOrientation.Horizontal
    preview = core.confirm_gate(ctx, len(elements), "tag_elements")
    dry = preview or ctx.dry_run

    def tag_one(e):
        kind = SPATIAL_TAG.get(bic_from_category(e.Category) if e.Category else None)
        if kind:
            if e.Location is None:
                raise RvtssError("unplaced {} cannot be tagged".format(kind))
            p = e.Location.Point
            uv = DB.UV(p.X + dx, p.Y + dy)
            if kind == "room":
                t = doc.Create.NewRoomTag(DB.LinkElementId(e.Id), uv, view.Id)
            elif kind == "space":
                t = doc.Create.NewSpaceTag(e, uv, view)
            else:
                if not isinstance(view, DB.ViewPlan):
                    raise RvtssError("area tags need an area plan view")
                t = doc.Create.NewAreaTag(view, e, uv)
            if t is None:
                raise RvtssError("Revit returned no tag (is a {} tag family loaded?)".format(kind))
            if ttype is not None:
                t.ChangeTypeId(ttype.Id)
            return {"element_id": id_int(e), "tag_id": id_int(t)}
        p = core.element_point(e)
        if p is None:
            raise RvtssError("element has no location to place a tag")
        pt = DB.XYZ(p.X + dx, p.Y + dy, p.Z)
        ref = DB.Reference(e)
        if ttype is not None:
            t = DB.IndependentTag.Create(doc, ttype.Id, view.Id, ref, leader, orient, pt)
        else:
            t = DB.IndependentTag.Create(doc, view.Id, ref, leader, DB.TagMode.TM_ADDBY_CATEGORY, orient, pt)
        if t is None:
            raise RvtssError("no tag created - load a tag family for '{}'".format(
                normalize_string(e.Category.Name) if e.Category else "?"))
        return {"element_id": id_int(e), "tag_id": id_int(t),
                "tag_type": normalize_string(get_element_name(doc.GetElement(t.GetTypeId())))}

    def run():
        return {"results": core.batch(doc, elements, tag_one, atomic=ctx.bool("atomic", False))}

    if elements:
        res, fails = core.run_transaction(doc, "Tag elements", run, dry_run=dry)
    else:
        res, fails = {"results": []}, []
    results = res.get("results", [])
    out = core.commit_result({"tagged": len([r for r in results if r.get("ok")]),
                              "failed": [r for r in results if not r.get("ok")][:50],
                              "created": [r for r in results if r.get("ok")][:200],
                              "skipped": skipped[:100], "skipped_count": len(skipped)},
                             fails, dry, {"view": normalize_string(view.Name), "view_id": id_int(view)})
    failed = [r for r in results if not r.get("ok")]
    if failed and any("tag family" in (r.get("error") or "").lower() or "no tag" in (r.get("error") or "").lower()
                      for r in failed):
        out["hint"] = "Load a tag family for the category (Insert > Load Family > Annotations) or pass tag_type."
    return core.preview_status(out, preview and not ctx.dry_run)


def text_notes(ctx):
    doc = ctx.doc
    view = _annotation_view(ctx)
    unit = ctx.unit
    notes = ctx.list("notes")
    if not notes:
        raise RvtssError("'notes' is required: [{text, point:[x,y], type?}]")
    default_type = ctx.get("text_type")
    dry = ctx.dry_run

    def type_id(name):
        if not name:
            return doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType)
        return core.find_type(doc, type_name=name, of_class=DB.TextNoteType).Id

    def one(n):
        if not n.get("text"):
            raise RvtssError("note without text")
        x, y, z = U.point_from(n.get("point") or [0, 0], unit)
        t = DB.TextNote.Create(doc, view.Id, DB.XYZ(x, y, z), text_type(n["text"]), type_id(n.get("type") or default_type))
        return {"text_note_id": id_int(t)}

    def run():
        return {"results": core.batch(doc, notes, one, atomic=True)}

    res, fails = core.run_transaction(doc, "Text notes", run, dry_run=dry)
    return core.commit_result(res, fails, dry, {"view": normalize_string(view.Name), "view_id": id_int(view)})


# ------------------------------------------------- detailing (v2.3): dimensions, lines, regions
_FI_REFS = {
    "center_left_right": "CenterLeftRight", "center_front_back": "CenterFrontBack",
    "center_elevation": "CenterElevation", "left": "Left", "right": "Right", "front": "Front",
    "back": "Back", "top": "Top", "bottom": "Bottom",
}


def _on_plane(view, xyz):
    """Project a model point onto the view plane ([x, y] is enough in plans)."""
    n = view.ViewDirection
    return xyz - n.Multiply((xyz - view.Origin).DotProduct(n))


def _view_point(ctx, view, value, what="point"):
    if value is None:
        raise RvtssError("'{}' is required".format(what))
    x, y, z = U.point_from(value, ctx.unit)
    return _on_plane(view, DB.XYZ(x, y, z))


def _segment(a, b):
    if a.DistanceTo(b) < 1e-4:
        raise RvtssError("Two consecutive points are the same (after projection onto the view)")
    return DB.Line.CreateBound(a, b)


def _named(doc, cls, name, default_group=None, what="type"):
    types = list(DB.FilteredElementCollector(doc).OfClass(cls))
    if name:
        key = text_type(name).strip().lower()
        for t in types:
            if normalize_string(get_element_name(t)).lower() == key or text_type(id_int(t)) == key:
                return t
        raise core.not_found(what, name, [get_element_name(t) for t in types],
                             hint="list_annotation_types lists the available names.")
    if default_group is not None:
        try:
            t = doc.GetElement(doc.GetDefaultElementTypeId(default_group))
            if t is not None:
                return t
        except Exception:
            pass
    if not types:
        raise RvtssError("No {} exists in '{}'".format(what, doc.Title))
    return types[0]


def _line_styles(doc):
    out = {}
    try:
        lines = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        for sub in lines.SubCategories:
            gs = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
            if gs is not None:
                out[normalize_string(sub.Name)] = gs
    except Exception as e:
        logger.debug("line styles: %s", e)
    return out


def _dim_reference(e, item):
    if isinstance(e, DB.Grid):
        return DB.Reference(e)
    if isinstance(e, DB.Level):
        return e.GetPlaneReference()
    if isinstance(e, DB.ReferencePlane):
        return e.GetReference()
    if isinstance(e, DB.Wall):
        side = (item.get("wall_face") or "exterior").lower()
        shell = DB.ShellLayerType.Interior if side == "interior" else DB.ShellLayerType.Exterior
        faces = list(DB.HostObjectUtils.GetSideFaces(e, shell))
        if not faces:
            raise RvtssError("Wall {} has no {} face to dimension".format(id_int(e), side))
        return faces[0]
    if isinstance(e, DB.FamilyInstance):
        name = _FI_REFS.get((item.get("instance_reference") or "center_left_right").lower())
        if name is None:
            raise RvtssError("instance_reference must be one of: {}".format(", ".join(sorted(_FI_REFS))))
        refs = list(e.GetReferences(getattr(DB.FamilyInstanceReferenceType, name)))
        if not refs:
            raise RvtssError("Family instance {} has no '{}' reference".format(id_int(e), name),
                             hint="Try another instance_reference, e.g. left / right / center_front_back.")
        return refs[0]
    raise RvtssError("Cannot dimension {} (id {}): use grids, levels, reference planes, walls or family "
                     "instances".format(type(e).__name__, id_int(e)))


def _dimension(ctx, view, item):
    doc = ctx.doc
    ids = item.get("element_ids") or []
    if len(ids) < 2:
        raise RvtssError("dimension: 'element_ids' needs at least 2 elements")
    arr = DB.ReferenceArray()
    for i in ids:
        arr.Append(_dim_reference(core.get_element(doc, i), item))
    line = _segment(_view_point(ctx, view, item.get("start"), "start"), _view_point(ctx, view, item.get("end"), "end"))
    if item.get("type"):
        dim = doc.Create.NewDimension(view, line, arr, _named(doc, DB.DimensionType, item["type"],
                                                              what="Dimension type"))
    else:
        dim = doc.Create.NewDimension(view, line, arr)
    if dim is None:
        raise RvtssError("Revit could not create the dimension (are the references parallel and visible?)")
    out = {"kind": "dimension", "id": id_int(dim)}
    try:
        if dim.Value is not None:
            out["value"] = U.from_internal(dim.Value, ctx.unit, 2)
    except Exception:
        pass
    return out


def _detail_line(ctx, view, item):
    doc = ctx.doc
    raw = item.get("points") or [item.get("start"), item.get("end")]
    pts = [_view_point(ctx, view, p) for p in raw]
    if len(pts) < 2:
        raise RvtssError("detail_line needs start/end or at least 2 points")
    if item.get("closed") and len(pts) > 2:
        pts.append(pts[0])
    style = None
    if item.get("line_style"):
        styles = _line_styles(doc)
        key = text_type(item["line_style"]).strip().lower()
        style = next((gs for n, gs in styles.items() if n.lower() == key), None)
        if style is None:
            raise core.not_found("Line style", item["line_style"], list(styles))
    ids = []
    for a, b in zip(pts[:-1], pts[1:]):
        dc = doc.Create.NewDetailCurve(view, _segment(a, b))
        if style is not None:
            dc.LineStyle = style
        ids.append(id_int(dc))
    return {"kind": "detail_line", "ids": ids}


def _filled_region(ctx, view, item):
    from System.Collections.Generic import List

    doc = ctx.doc
    pts = [_view_point(ctx, view, p) for p in item.get("boundary") or []]
    if len(pts) < 3:
        raise RvtssError("filled_region: 'boundary' needs at least 3 points")
    loop = DB.CurveLoop()
    for i in range(len(pts)):
        loop.Append(_segment(pts[i], pts[(i + 1) % len(pts)]))
    frt = _named(doc, DB.FilledRegionType, item.get("type"), DB.ElementTypeGroup.FilledRegionType,
                 "Filled region type")
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    fr = DB.FilledRegion.Create(doc, frt.Id, view.Id, loops)
    return {"kind": "filled_region", "id": id_int(fr), "type": normalize_string(get_element_name(frt))}


# ---- v2.4: masking regions, revision clouds, spot dimensions, detail components and symbols
def _closed_loop(ctx, view, item, what):
    pts = [_view_point(ctx, view, p) for p in item.get("boundary") or []]
    if len(pts) < 3:
        raise RvtssError("{}: 'boundary' needs at least 3 points".format(what))
    return [_segment(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _masking_region(ctx, view, item):
    from System.Collections.Generic import List

    doc = ctx.doc
    types = list(DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType))
    masking = None
    for t in types:
        try:
            if t.IsMasking:
                masking = t
                break
        except Exception:
            continue
    if masking is None:
        raise RvtssError("No masking filled region type exists in '{}'".format(doc.Title), status=409,
                         hint="Duplicate a filled region type in Revit and tick 'Masking', or draw one masking "
                              "region by hand once.")
    loop = DB.CurveLoop()
    for seg in _closed_loop(ctx, view, item, "masking_region"):
        loop.Append(seg)
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    fr = DB.FilledRegion.Create(doc, masking.Id, view.Id, loops)
    return {"kind": "masking_region", "id": id_int(fr)}


def _revision(doc, ref):
    ids = list(DB.Revision.GetAllRevisionIds(doc))
    if not ids:
        raise RvtssError("The project has no revision", status=409, hint="Create one with manage_revisions.")
    revs = [doc.GetElement(i) for i in ids]
    if ref in (None, "", "latest"):
        return revs[-1]
    key = text_type(ref).strip().lower()
    for r in revs:
        if text_type(id_int(r)) == key or text_type(r.SequenceNumber) == key or \
                normalize_string(r.Description or "").lower() == key:
            return r
    raise core.not_found("Revision", ref, [normalize_string(r.Description or "") for r in revs],
                         hint="Pass the revision id, its sequence number or its description.")


def _revision_cloud(ctx, view, item):
    from System.Collections.Generic import List

    doc = ctx.doc
    rev = _revision(doc, item.get("revision"))
    if rev.Issued:
        raise RvtssError("Revision '{}' is issued; clouds cannot be added to it".format(
            normalize_string(rev.Description or "")), status=409)
    curves = List[DB.Curve]()
    for seg in _closed_loop(ctx, view, item, "revision_cloud"):
        curves.Add(seg)
    cloud = DB.RevisionCloud.Create(doc, view, rev.Id, curves)
    return {"kind": "revision_cloud", "id": id_int(cloud), "revision": normalize_string(rev.Description or "")}


def _top_face_reference(e):
    try:
        if isinstance(e, DB.RoofBase) or isinstance(e, DB.CeilingAndFloor):
            refs = list(DB.HostObjectUtils.GetTopFaces(e))
            if refs:
                return refs[0]
    except Exception:
        pass
    raise RvtssError("Spot dimensions are supported on floors, roofs, ceilings and toposolids (id {} is a {})".format(
        id_int(e), type(e).__name__), hint="For other elements use run_revit_command('SpotElevation').")


def _spot(ctx, view, item, coordinate):
    doc = ctx.doc
    e = core.get_element(doc, item.get("element_id"))
    ref = _top_face_reference(e)
    x, y, z = U.point_from(item.get("point") or [0, 0], ctx.unit)
    origin = DB.XYZ(x, y, z)
    try:
        face = e.GetGeometryObjectFromReference(ref)
        hit = face.Project(origin)
        if hit is None:
            raise RvtssError("point is not over the top face of element {}".format(id_int(e)))
        origin = hit.XYZPoint
    except RvtssError:
        raise
    except Exception as ex:
        logger.debug("spot projection: %s", ex)
    leader = bool(item.get("leader", False))
    ox, oy, _oz = U.point_from(item.get("offset") or [600, 600], ctx.unit)
    bend = DB.XYZ(origin.X + ox, origin.Y + oy, origin.Z)
    end = DB.XYZ(bend.X + abs(ox), bend.Y, bend.Z)
    make = doc.Create.NewSpotCoordinate if coordinate else doc.Create.NewSpotElevation
    sd = make(view, ref, origin, bend, end, origin, leader)
    if sd is None:
        raise RvtssError("Revit created no spot dimension (is the face visible in this view?)")
    return {"kind": "spot_coordinate" if coordinate else "spot_elevation", "id": id_int(sd)}


def _spot_elevation(ctx, view, item):
    return _spot(ctx, view, item, False)


def _spot_coordinate(ctx, view, item):
    return _spot(ctx, view, item, True)


def _detail_component(ctx, view, item):
    """Detail items and generic annotation symbols: a point, or start/end for line-based detail families."""
    doc = ctx.doc
    spec = item.get("type")
    if not spec:
        raise RvtssError("detail_component: 'type' is required ('Family : Type', type name or id)")
    sym = _tag_type(doc, spec)
    if not isinstance(sym, DB.FamilySymbol):
        raise RvtssError("'{}' is not a loadable family type".format(spec))
    if not sym.IsActive:
        sym.Activate()
        doc.Regenerate()
    if item.get("start") is not None and item.get("end") is not None:
        line = _segment(_view_point(ctx, view, item.get("start"), "start"),
                        _view_point(ctx, view, item.get("end"), "end"))
        inst = doc.Create.NewFamilyInstance(line, sym, view)
    else:
        inst = doc.Create.NewFamilyInstance(_view_point(ctx, view, item.get("point")), sym, view)
    return {"kind": "detail_component", "id": id_int(inst),
            "type": normalize_string(get_element_name(sym))}


_DETAIL = {"dimension": _dimension, "detail_line": _detail_line, "filled_region": _filled_region,
           "masking_region": _masking_region, "revision_cloud": _revision_cloud,
           "spot_elevation": _spot_elevation, "spot_coordinate": _spot_coordinate,
           "detail_component": _detail_component}
DETAIL_KINDS = tuple(sorted(_DETAIL))


# ---- v2.4: find and replace in text notes
def replace_in_text(text, find, replace, regex=False, match_case=False, whole_word=False):
    """(new text, number of replacements). Pure: unit-tested without Revit."""
    import re

    if not find:
        raise ValueError("'find' must not be empty")
    pattern = find if regex else re.escape(find)
    if whole_word:
        pattern = r"\b(?:" + pattern + r")\b"
    flags = 0 if match_case else re.IGNORECASE
    if regex:
        return re.subn(pattern, replace, text, flags=flags)
    return re.subn(pattern, lambda _m: replace, text, flags=flags)


def replace_text(ctx):
    import re

    doc = ctx.doc
    find = ctx.require("find")
    replace = text_type(ctx.get("replace", ""))
    regex, case, whole = ctx.bool("regex", False), ctx.bool("match_case", False), ctx.bool("whole_word", False)
    try:
        replace_in_text("", find, replace, regex, case, whole)
    except (ValueError, re.error) as e:
        raise RvtssError("Invalid find pattern: {}".format(e))
    views = ctx.list("views")
    if views:
        notes, seen = [], set()
        for v in views:
            view = core.find_view(doc, v, uidoc=ctx.uidoc)
            for n in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.TextNote):
                if id_int(n) not in seen:
                    seen.add(id_int(n))
                    notes.append(n)
    else:
        notes = list(DB.FilteredElementCollector(doc).OfClass(DB.TextNote))
    plan = []
    for n in notes:
        old = n.Text or ""
        new, count = replace_in_text(old, find, replace, regex, case, whole)
        if count and new != old:
            plan.append((n, old, new, count))
    preview = core.confirm_gate(ctx, len(plan), "replace_text")
    dry = preview or ctx.dry_run

    def run():
        done = []
        for n, old, new, count in plan:
            n.Text = new
            owner = doc.GetElement(n.OwnerViewId)
            done.append({"id": id_int(n), "view": normalize_string(owner.Name) if owner is not None else None,
                         "old": normalize_string(old)[:200], "new": normalize_string(new)[:200],
                         "replacements": count})
        return {"changed": done[:300]}

    res, fails = core.run_transaction(doc, "Replace text", run, dry_run=dry) if plan else ({"changed": []}, [])
    out = core.commit_result(res, fails, dry, {
        "text_notes_searched": len(notes), "text_notes_changed": len(plan),
        "replacements": sum(p[3] for p in plan), "truncated": len(plan) > 300})
    if plan:
        ctx.warn("Setting a text note's text drops mixed formatting (bold / italic runs) inside that note.")
    return core.preview_status(out, preview)


def detailing(ctx):
    doc = ctx.doc
    items = ctx.list("items")
    if not items:
        raise RvtssError("'items' is required: [{kind: 'detail_line', start: [x, y], end: [x, y]}, ...]")
    if len(items) > 500:
        raise RvtssError("At most 500 items per call")
    view = _annotation_view(ctx)
    dry = ctx.dry_run

    def one(item):
        kind = item.get("kind")
        if kind not in _DETAIL:
            raise RvtssError("Unknown kind '{}'. Use {}".format(kind, ", ".join(DETAIL_KINDS)))
        return _DETAIL[kind](ctx, view, item)

    def run():
        return {"results": core.batch(doc, items, one, atomic=ctx.bool("atomic", True))}

    res, fails = core.run_transaction(doc, "Detailing", run, dry_run=dry)
    res["created"] = len([r for r in res["results"] if r.get("ok")])
    return core.commit_result(res, fails, dry, {"view": normalize_string(view.Name), "view_id": id_int(view),
                                               "unit": ctx.unit})


def annotation_types(ctx):
    doc = ctx.doc
    wanted = set(ctx.list("kinds")) or {"text", "dimension", "filled_region", "line_style", "tag"}
    out = {}

    def brief(t):
        return {"id": id_int(t), "name": normalize_string(get_element_name(t))}

    if "text" in wanted:
        out["text"] = [brief(t) for t in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType)]
    if "dimension" in wanted:
        dims = []
        for t in DB.FilteredElementCollector(doc).OfClass(DB.DimensionType):
            if not normalize_string(get_element_name(t)):
                continue
            d = brief(t)
            try:
                d["style"] = str(t.StyleType)
            except Exception:
                pass
            dims.append(d)
        out["dimension"] = dims
    if "filled_region" in wanted:
        out["filled_region"] = [brief(t) for t in DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType)]
    if "line_style" in wanted:
        out["line_style"] = sorted(_line_styles(doc))
    if "tag" in wanted:
        tags = {}
        for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
            cat = s.Category
            if cat is None:
                continue
            is_tag = getattr(cat, "IsTagCategory", None)
            if is_tag is None:
                is_tag = normalize_string(cat.Name).endswith("Tags")
            if is_tag:
                tags.setdefault(normalize_string(cat.Name), []).append(
                    dict(brief(s), family=normalize_string(s.FamilyName)))
        out["tag"] = tags
    return out


def register_annotation_routes(api):
    @api.route("/annotation/detail/", methods=["POST"])
    def annotation_detail_route(doc, uidoc, request):
        return handle(doc, request, detailing, uidoc=uidoc)

    @api.route("/annotation/text/replace/", methods=["POST"])
    def annotation_text_replace_route(doc, uidoc, request):
        return handle(doc, request, replace_text, uidoc=uidoc)

    @api.route("/annotation/types/", methods=["POST"])
    def annotation_types_route(doc, request):
        return handle(doc, request, annotation_types)

    @api.route("/annotation/untagged/", methods=["POST"])
    def annotation_untagged_route(doc, uidoc, request):
        return handle(doc, request, untagged, uidoc=uidoc)

    @api.route("/annotation/tag/", methods=["POST"])
    def annotation_tag_route(doc, uidoc, request):
        return handle(doc, request, tag, uidoc=uidoc)

    @api.route("/annotation/text/", methods=["POST"])
    def annotation_text_route(doc, uidoc, request):
        return handle(doc, request, text_notes, uidoc=uidoc)

    logger.info("RVTSS annotation routes registered")
