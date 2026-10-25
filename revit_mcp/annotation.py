# -*- coding: UTF-8 -*-
"""Annotation: untagged-element checks, tagging and text notes (RVTSS v2.2).

Routes:
    POST /annotation/untagged/   elements of categories visible in a view without a tag in that view
    POST /annotation/tag/        tag elements (by ids or category) - rooms/spaces/areas get their own tags
    POST /annotation/text/       place text notes
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


def register_annotation_routes(api):
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
