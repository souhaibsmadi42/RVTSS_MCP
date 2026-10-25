# -*- coding: UTF-8 -*-
"""Model administration: worksets and purge (RVTSS v2.2).

Routes:
    POST /worksets/manage/   list (with element counts), create, rename, move elements, set active
    POST /purge/             purgeable elements (Revit 2024+ API, older: unused family types); preview first
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, REVIT_YEAR, bic_from_category
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------- worksets
def _user_worksets(doc):
    return list(DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))


def _workset_id_int(w):
    try:
        return w.Id.IntegerValue
    except AttributeError:
        return int(text_type(w.Id))


def _find_workset(doc, name_or_id):
    ws = _user_worksets(doc)
    s = text_type(name_or_id).strip()
    for w in ws:
        if normalize_string(w.Name).lower() == s.lower() or text_type(_workset_id_int(w)) == s:
            return w
    raise core.not_found("Workset", name_or_id, [w.Name for w in ws])


def _count(doc, w):
    try:
        return DB.FilteredElementCollector(doc).WherePasses(DB.ElementWorksetFilter(w.Id, False)) \
            .WhereElementIsNotElementType().GetElementCount()
    except Exception:
        return None


def worksets(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    if not doc.IsWorkshared:
        if action == "list":
            return {"workshared": False, "worksets": [], "message": "The model is not workshared."}
        raise RvtssError("The model is not workshared", status=409,
                         hint="Enable worksharing in Revit (Collaborate > Worksets) first.")
    table = doc.GetWorksetTable()
    if action == "list":
        active = table.GetActiveWorksetId()
        out = []
        for w in _user_worksets(doc):
            d = {"id": _workset_id_int(w), "name": normalize_string(w.Name), "is_open": w.IsOpen,
                 "is_editable": w.IsEditable, "owner": normalize_string(w.Owner or "") or None,
                 "visible_by_default": w.IsVisibleByDefault, "is_active": w.Id == active}
            if ctx.bool("include_counts", True):
                d["element_count"] = _count(doc, w)
            out.append(d)
        out.sort(key=lambda d: d["name"].lower())
        return {"workshared": True, "count": len(out), "worksets": out,
                "empty": [d["name"] for d in out if d.get("element_count") == 0]}
    if action == "set_active":
        w = _find_workset(doc, ctx.require("workset"))
        if core.in_batch():
            raise RvtssError("set_active cannot run in batch_execute (it is not a transaction and cannot be "
                             "rolled back)", hint="Call manage_worksets(action='set_active') on its own.")
        if ctx.dry_run:
            return {"status": "dry_run", "would_activate": normalize_string(w.Name),
                    "message": "Dry run: the active workset was not changed."}
        core.require_writable("set_active workset")
        table.SetActiveWorksetId(w.Id)
        return {"active_workset": normalize_string(w.Name)}
    dry = ctx.dry_run
    preview = False
    if action == "move_elements":
        ids = ctx.list("element_ids")
        if not ids:
            raise RvtssError("move_elements needs element_ids")
        preview = core.confirm_gate(ctx, len(ids), "Moving elements to a workset")
        dry = dry or preview

    def run():
        if action == "create":
            name = ctx.require("name")
            if not DB.WorksetTable.IsWorksetNameUnique(doc, name):
                raise RvtssError("Workset name '{}' is already used".format(name), status=409)
            w = DB.Workset.Create(doc, name)
            return {"workset": {"id": _workset_id_int(w), "name": normalize_string(w.Name)}}
        if action == "rename":
            w = _find_workset(doc, ctx.require("workset"))
            name = ctx.require("name")
            old = normalize_string(w.Name)
            DB.WorksetTable.RenameWorkset(doc, w.Id, name)
            return {"workset_id": _workset_id_int(w), "old_name": old, "new_name": name}
        if action == "move_elements":
            w = _find_workset(doc, ctx.require("workset"))
            moved, skipped = [], []
            for e in core.get_elements(doc, ctx.list("element_ids")):
                p = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                if p is None or p.IsReadOnly:
                    skipped.append({"id": id_int(e), "reason": "workset is read-only for this element "
                                                               "(view-specific, in a group, hosted or a type)"})
                    continue
                p.Set(_workset_id_int(w))
                moved.append(id_int(e))
            return {"workset": normalize_string(w.Name), "moved": moved, "skipped": skipped}
        raise RvtssError("action must be list, create, rename, move_elements or set_active")

    res, fails = core.run_transaction(doc, "Worksets: " + action, run, dry_run=dry)
    return core.preview_status(core.commit_result(res, fails, dry), preview and not ctx.dry_run)


# ----------------------------------------------------------------------- purge
def _unused_elements(doc):
    """(ids, method). Revit 2024+ exposes the Purge Unused query; older versions: unused family types."""
    from System.Collections.Generic import HashSet

    if hasattr(doc, "GetUnusedElements"):
        try:
            return list(doc.GetUnusedElements(HashSet[DB.ElementId]())), "Document.GetUnusedElements (Revit 2024+)"
        except Exception as e:
            logger.warning("GetUnusedElements failed, falling back: %s", e)
    used = set()
    for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        try:
            used.add(id_int(fi.Symbol.Id))
        except Exception:
            continue
    ids = []
    for fam in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        if not fam.IsEditable or fam.IsInPlace:
            continue
        cat = fam.FamilyCategory
        # only model families: annotation families (tags, heads, titles) and profiles are used without a
        # FamilyInstance, so "no instance" would wrongly mark them unused
        if cat is None or cat.CategoryType != DB.CategoryType.Model or \
                bic_from_category(cat) in ("OST_ProfileFamilies", "OST_DetailComponents"):
            continue
        sids = list(fam.GetFamilySymbolIds())
        unused = [s for s in sids if id_int(s) not in used]
        # Revit keeps at least one type per family: delete the whole family when no type is used
        ids.extend([fam.Id] if unused and len(unused) == len(sids) else unused)
    return ids, ("unused loadable model family types (Revit {} has no purge API; annotation and profile "
                 "families are not checked)".format(REVIT_YEAR or "<2024"))


def purge(ctx):
    doc = ctx.doc
    core.require_project(doc)
    core.check_modifiable(doc)
    cats = set(core.resolve_category(doc, c).Name for c in ctx.list("categories"))
    exclude = set(int(i) for i in ctx.list("exclude_ids"))
    ids, method = _unused_elements(doc)
    candidates = []
    for eid in ids:
        if id_int(eid) in exclude:
            continue
        e = doc.GetElement(eid)
        if e is None:
            continue
        cat = normalize_string(e.Category.Name) if e.Category else type(e).__name__
        if cats and cat not in cats:
            continue
        candidates.append((e, cat))
    by_cat = {}
    for _e, cat in candidates:
        by_cat[cat] = by_cat.get(cat, 0) + 1
    listing = [{"id": id_int(e), "category": cat, "name": normalize_string(get_element_name(e) or ""),
                "family": normalize_string(getattr(e, "FamilyName", "") or "") or None}
               for e, cat in candidates[:ctx.int("list_limit", 300, 1, 5000)]]
    out = {"method": method, "candidates": len(candidates), "by_category": by_cat, "elements": listing}
    if not candidates:
        out["message"] = "Nothing to purge."
        return out
    if not ctx.confirmed or ctx.dry_run:
        out.update({"status": "preview", "requires_confirmation": True,
                    "message": "Preview only - nothing was deleted. Review the list, then call again with "
                               "confirm=true (optionally categories / exclude_ids to narrow it)."})
        return out
    passes = ctx.int("passes", 1, 1, 5)
    core.require_writable("purge_unused")
    deleted_total, fails = [], []

    def run():
        deleted = [id_int(i) for i in doc.Delete(core.to_id_list([e.Id for e, _c in candidates]))]
        return {"deleted": deleted}

    # all passes form one undo step; any failure rolls every pass back
    group = DB.TransactionGroup(doc, "RVTSS: Purge unused")
    group.Start()
    try:
        res, f = core.run_transaction(doc, "Purge unused", run)
        deleted_total.extend(res.get("deleted", []))
        fails.extend(f)
        for _ in range(passes - 1):
            more, _m = _unused_elements(doc)
            more = [i for i in more if id_int(i) not in exclude and (not cats or (
                doc.GetElement(i) is not None and doc.GetElement(i).Category is not None
                and normalize_string(doc.GetElement(i).Category.Name) in cats))]
            if not more:
                break
            r, f = core.run_transaction(doc, "Purge unused (next pass)",
                                        lambda: {"deleted": [id_int(i) for i in doc.Delete(core.to_id_list(more))]})
            deleted_total.extend(r.get("deleted", []))
            fails.extend(f)
        group.Assimilate()
    except Exception:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    out = core.commit_result({"deleted_count": len(deleted_total), "deleted_ids": deleted_total[:500],
                              "method": method, "by_category": by_cat}, fails, False)
    out["note"] = "Deletion count includes dependent elements Revit removed with the purged ones. Undo is available."
    return out


def register_model_admin_routes(api):
    @api.route("/worksets/manage/", methods=["POST"])
    def worksets_manage_route(doc, request):
        return handle(doc, request, worksets)

    @api.route("/purge/", methods=["POST"])
    def purge_route(doc, request):
        return handle(doc, request, purge)

    logger.info("RVTSS model admin routes registered")
