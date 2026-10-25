# -*- coding: UTF-8 -*-
"""Change-impact survey: what else a change to these elements touches (RVTSS v2.2). Read-only.

Routes:
    POST /impact/survey/   relationships of up to 20 elements, grouped, each "found", "none" or "not_checked"

Groups: type (shared by N instances), host / hosted, joins, group / assembly,
rooms, tags / dimensions, dependents (deleted with it), views / sheets, levels,
MEP connections. Every group says how it was checked; anything not checked is
reported as such - absence of evidence is never reported as "none".
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

MAX_ELEMENTS = 20
ID_CAP = 50


def _group(found=None, ids=None, note=None, reason=None, count=None):
    if reason is not None:
        return {"status": "not_checked", "reason": reason}
    ids = sorted(set(ids or []))
    n = count if count is not None else len(ids)
    out = {"status": "found" if n else "none", "count": n, "ids": ids[:ID_CAP]}
    if len(ids) > ID_CAP:
        out["ids_truncated"] = True
    if found:
        out.update(found)
    if note:
        out["note"] = note
    return out


class _Index(object):
    """Model-wide reverse lookups, built lazily once per request."""

    def __init__(self, doc):
        self.doc = doc
        self._tags = None
        self._dims = None
        self._hosted = None
        self._sheet_of_view = None

    def tags(self):
        if self._tags is None:
            self._tags = {}
            for t in DB.FilteredElementCollector(self.doc).OfClass(DB.IndependentTag):
                try:
                    ids = [id_int(i) for i in t.GetTaggedLocalElementIds()]
                except Exception:
                    try:
                        ids = [id_int(t.TaggedLocalElementId)]
                    except Exception:
                        ids = []
                for i in ids:
                    self._tags.setdefault(i, []).append(id_int(t))
            for bic, attr in (("OST_RoomTags", "Room"), ("OST_MEPSpaceTags", "Space"), ("OST_AreaTags", "Area")):
                try:
                    col = DB.FilteredElementCollector(self.doc).OfCategory(getattr(DB.BuiltInCategory, bic)) \
                        .WhereElementIsNotElementType()
                except Exception:
                    continue
                for t in col:
                    try:
                        target = getattr(t, attr)
                        if target is not None:
                            self._tags.setdefault(id_int(target), []).append(id_int(t))
                    except Exception:
                        continue
        return self._tags

    def dimensions(self):
        if self._dims is None:
            self._dims = {}
            for d in DB.FilteredElementCollector(self.doc).OfClass(DB.Dimension):
                try:
                    for ref in d.References:
                        self._dims.setdefault(id_int(ref.ElementId), set()).add(id_int(d))
                except Exception:
                    continue
        return self._dims

    def hosted(self):
        if self._hosted is None:
            self._hosted = {}
            for fi in DB.FilteredElementCollector(self.doc).OfClass(DB.FamilyInstance):
                try:
                    if fi.Host is not None:
                        self._hosted.setdefault(id_int(fi.Host), []).append(id_int(fi))
                except Exception:
                    continue
        return self._hosted

    def sheet_of_view(self):
        if self._sheet_of_view is None:
            self._sheet_of_view = {}
            for vp in DB.FilteredElementCollector(self.doc).OfClass(DB.Viewport):
                sh = self.doc.GetElement(vp.SheetId)
                if sh is not None:
                    self._sheet_of_view[id_int(vp.ViewId)] = normalize_string(sh.SheetNumber)
        return self._sheet_of_view


def _type_group(doc, e):
    if isinstance(e, DB.ElementType):
        tid = e.Id
    else:
        tid = e.GetTypeId()
    if not is_valid_id(tid):
        return _group(reason="element has no type")
    t = doc.GetElement(tid)
    if isinstance(t, DB.FamilySymbol):
        ids = [id_int(i) for i in DB.FilteredElementCollector(doc).WherePasses(DB.FamilyInstanceFilter(doc, tid))
               .ToElementIds()]
        method = "FamilyInstanceFilter (exact)"
    else:
        cat = t.Category if t is not None else None
        col = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
        if cat is not None:
            col = col.OfCategoryId(cat.Id)
        ids = [id_int(x) for x in col if x.GetTypeId() == tid]
        method = "category scan (exact)"
    return _group({"type_id": id_int(tid), "type": normalize_string(get_element_name(t)) if t else None,
                   "family": normalize_string(getattr(t, "FamilyName", "") or "") or None, "method": method},
                  ids, note="Editing a type parameter changes every one of these instances.")


def _host_group(doc, e, idx):
    out = {}
    host = getattr(e, "Host", None) if isinstance(e, DB.FamilyInstance) else None
    out["host_id"] = id_int(host) if host is not None else None
    hosted = list(idx.hosted().get(id_int(e), []))
    if isinstance(e, DB.HostObject):
        try:
            hosted += [id_int(i) for i in e.FindInserts(True, True, True, True)]
        except Exception:
            pass
    if isinstance(e, DB.FamilyInstance):
        try:
            if e.SuperComponent is not None:
                out["super_component_id"] = id_int(e.SuperComponent)
            hosted += [id_int(i) for i in e.GetSubComponentIds()]
        except Exception:
            pass
    return _group(out, hosted, note="Hosted / nested elements move or are deleted with their host.")


def _join_group(doc, e):
    ids = []
    try:
        ids += [id_int(i) for i in DB.JoinGeometryUtils.GetJoinedElements(doc, e)]
    except Exception:
        pass
    loc = e.Location
    if isinstance(loc, DB.LocationCurve):
        for end in (0, 1):
            try:
                ids += [id_int(x) for x in loc.get_ElementsAtJoin(end) if id_int(x) != id_int(e)]
            except Exception:
                continue
    return _group(None, ids, note="Geometry joins and wall end joins; cuts/attachments are not traced.")


def _group_assembly(doc, e):
    out, ids = {}, []
    try:
        if is_valid_id(e.GroupId):
            g = doc.GetElement(e.GroupId)
            gt = g.GroupType
            instances = [id_int(x) for x in gt.Groups]
            out.update({"group_id": id_int(g), "group_type": normalize_string(gt.Name),
                        "group_instances": len(instances)})
            ids += instances
    except Exception:
        pass
    try:
        if is_valid_id(e.AssemblyInstanceId):
            a = doc.GetElement(e.AssemblyInstanceId)
            out["assembly_id"] = id_int(a)
            out["assembly"] = normalize_string(a.AssemblyTypeName)
            ids.append(id_int(a))
    except Exception:
        pass
    note = ("Group member: editing it in place changes every instance of the group type."
            if out.get("group_instances") else None)
    return _group(out, ids, note=note)


def _rooms_group(doc, e):
    if not isinstance(e, DB.FamilyInstance):
        return _group(reason="only family instances report From/To rooms")
    found = {}
    for attr in ("Room", "FromRoom", "ToRoom", "Space"):
        try:
            r = getattr(e, attr)
            if r is not None:
                found[attr.lower()] = id_int(r)
        except Exception:
            continue
    return _group({"rooms": found}, list(found.values()), note="Final project phase only.")


def _annotation_group(doc, e, idx):
    tags = idx.tags().get(id_int(e), [])
    dims = sorted(idx.dimensions().get(id_int(e), set()))
    return _group({"tag_ids": tags[:ID_CAP], "dimension_ids": dims[:ID_CAP], "tags": len(tags),
                   "dimensions": len(dims)}, tags + dims,
                  note="Local tags and dimensions; keynotes, spot dimensions in links and text are not traced.")


def _dependents(doc, e):
    try:
        deps = [i for i in e.GetDependentElements(None) if id_int(i) != id_int(e)]
    except Exception as ex:
        return _group(reason="GetDependentElements unavailable: {}".format(ex))
    by_cat = {}
    for i in deps:
        x = doc.GetElement(i)
        cat = normalize_string(x.Category.Name) if x is not None and x.Category else "(no category)"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return _group({"by_category": by_cat}, [id_int(i) for i in deps],
                  note="Elements Revit would delete together with this one (sketches, tags, hosted...).")


def _views_group(doc, e, idx):
    out = {}
    ids = []
    try:
        if e.ViewSpecific and is_valid_id(e.OwnerViewId):
            v = doc.GetElement(e.OwnerViewId)
            out["owner_view"] = {"id": id_int(v), "name": normalize_string(v.Name),
                                 "sheet": idx.sheet_of_view().get(id_int(v))}
            ids.append(id_int(v))
    except Exception:
        pass
    if isinstance(e, DB.View):
        out["on_sheet"] = idx.sheet_of_view().get(id_int(e))
    return _group(out, ids, note="View-specific ownership and sheet placement; visibility in other views is not "
                                 "computed (use find_elements(view=...) for a view).")


def _datum_group(doc, e):
    found = {}
    for key, bip in (("level", None), ("base_constraint", "WALL_BASE_CONSTRAINT"),
                     ("top_constraint", "WALL_HEIGHT_TYPE"), ("schedule_level", "SCHEDULE_LEVEL_PARAM"),
                     ("reference_level", "INSTANCE_REFERENCE_LEVEL_PARAM")):
        try:
            if bip is None:
                lid = e.LevelId
            else:
                p = e.get_Parameter(getattr(DB.BuiltInParameter, bip))
                lid = p.AsElementId() if p is not None else None
            if lid is not None and is_valid_id(lid):
                lv = doc.GetElement(lid)
                if isinstance(lv, DB.Level):
                    found[key] = {"id": id_int(lv), "name": normalize_string(lv.Name)}
        except Exception:
            continue
    return _group({"levels": found}, [v["id"] for v in found.values()],
                  note="Moving or deleting these levels moves or breaks this element. Grids and reference planes "
                       "are not traced.")


def _mep_group(doc, e):
    from .mep import connectors

    cons = connectors(e)
    if not cons:
        return _group(reason="no MEP connectors")
    ids, open_count = [], 0
    for c in cons:
        try:
            if not c.IsConnected:
                open_count += 1
            for ref in c.AllRefs:
                if ref.Owner is not None and ref.Owner.Id != e.Id:
                    ids.append(id_int(ref.Owner))
        except Exception:
            continue
    return _group({"connectors": len(cons), "open_connectors": open_count}, ids,
                  note="Directly connected elements (includes logical system owners).")


def survey(ctx):
    doc = ctx.doc
    ids = ctx.list("element_ids")
    if not ids:
        raise RvtssError("'element_ids' is required (max {})".format(MAX_ELEMENTS))
    if len(ids) > MAX_ELEMENTS:
        raise RvtssError("At most {} elements per survey".format(MAX_ELEMENTS),
                         hint="Survey a representative subset, or the shared type instead of its instances.")
    change = ctx.get("change_kind", "instance")
    if change not in ("instance", "type", "move", "delete", "unknown"):
        raise RvtssError("change_kind must be instance, type, move, delete or unknown")
    idx = _Index(doc)
    results, all_ids, flags = [], set(), []
    for e in core.get_elements(doc, ids):
        groups = {
            "type": _type_group(doc, e),
            "host_hosted": _host_group(doc, e, idx),
            "joins": _join_group(doc, e),
            "group_assembly": _group_assembly(doc, e),
            "rooms": _rooms_group(doc, e),
            "tags_dimensions": _annotation_group(doc, e, idx),
            "dependents": _dependents(doc, e),
            "views_sheets": _views_group(doc, e, idx),
            "levels": _datum_group(doc, e),
            "mep_connections": _mep_group(doc, e),
        }
        relevant = {"instance": ("group_assembly", "tags_dimensions", "rooms", "host_hosted"),
                    "type": ("type", "group_assembly"),
                    "move": ("host_hosted", "joins", "tags_dimensions", "mep_connections", "rooms"),
                    "delete": ("dependents", "host_hosted", "tags_dimensions", "mep_connections", "views_sheets"),
                    "unknown": tuple(groups)}[change]
        brief = core.element_brief(doc, e)
        for g in relevant:
            if groups[g].get("status") == "found":
                all_ids.update(groups[g].get("ids", []))
        if change == "type" and groups["type"].get("count", 0) > 1:
            flags.append("Element {}: type '{}' is shared by {} instances".format(
                brief["id"], groups["type"].get("type"), groups["type"]["count"]))
        if groups["group_assembly"].get("group_instances", 0) > 1:
            flags.append("Element {} is in group type '{}' with {} instances".format(
                brief["id"], groups["group_assembly"].get("group_type"), groups["group_assembly"]["group_instances"]))
        if change in ("move", "delete") and groups["host_hosted"].get("count"):
            flags.append("Element {} hosts {} element(s) that move/delete with it".format(
                brief["id"], groups["host_hosted"]["count"]))
        if change == "delete" and groups["dependents"].get("count"):
            flags.append("Deleting {} also deletes {} dependent element(s)".format(
                brief["id"], groups["dependents"]["count"]))
        results.append({"element": brief, "relevant_groups": list(relevant), "groups": groups})
    return {"change_kind": change, "elements": results, "propagation_candidates": len(all_ids - set(ids)),
            "requires_discussion": flags,
            "blind_spots": ["linked models", "schedules / filters / formulas reading these values",
                            "visibility in views", "engineering intent and calculations", "keynotes and text"],
            "next_step": "Agree the scope with the user before changing anything when requires_discussion is not "
                         "empty. Use dry_run=true on the edit, then batch_execute for multi-step changes."}


def register_impact_routes(api):
    @api.route("/impact/survey/", methods=["POST"])
    def impact_survey_route(doc, request):
        return handle(doc, request, survey)

    logger.info("RVTSS impact routes registered")
