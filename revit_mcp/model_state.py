# -*- coding: UTF-8 -*-
"""Phases, design options, Revit links and saved selection sets (RVTSS v2.3).

Routes:
    POST /phases/manage/          list phases / phase filters / design options; set element phases;
                                  set a view's phase and phase filter; elements of a design option
    POST /links/manage/           list Revit links; reload, unload, reload_from a path; load a new link
    POST /selection_sets/         list, save (ids or current selection), load (select), delete

The Revit API cannot create phases or design options; those stay manual.
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, make_id, text_type
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------- phases
def _phase(doc, ref):
    if ref in (None, "", "none"):
        return None
    for p in doc.Phases:
        if text_type(id_int(p)) == text_type(ref) or normalize_string(p.Name).lower() == text_type(ref).strip().lower():
            return p
    raise RvtssError("Phase '{}' not found".format(ref), status=404,
                     available=[normalize_string(p.Name) for p in doc.Phases])


def _design_options(doc):
    out = []
    for o in DB.FilteredElementCollector(doc).OfClass(DB.DesignOption):
        set_name = None
        try:
            p = o.get_Parameter(DB.BuiltInParameter.OPTION_SET_ID)
            os_el = doc.GetElement(p.AsElementId()) if p else None
            set_name = normalize_string(os_el.Name) if os_el else None
        except Exception:
            pass
        out.append({"id": id_int(o), "name": normalize_string(o.Name), "option_set": set_name,
                    "is_primary": o.IsPrimary})
    return out


def phases(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    if action == "list":
        filters = [{"id": id_int(f), "name": normalize_string(f.Name)}
                   for f in DB.FilteredElementCollector(doc).OfClass(DB.PhaseFilter)]
        out = {"phases": [{"id": id_int(p), "name": normalize_string(p.Name), "sequence": i + 1}
                          for i, p in enumerate(doc.Phases)],
               "phase_filters": filters, "design_options": _design_options(doc)}
        if ctx.bool("counts", False):
            for ph in out["phases"]:
                f = DB.ElementPhaseStatusFilter(make_id(ph["id"]), DB.ElementOnPhaseStatus.New)
                ph["new_elements"] = DB.FilteredElementCollector(doc).WhereElementIsNotElementType().WherePasses(
                    f).GetElementCount()
        return out
    if action == "option_elements":
        opt = [o for o in DB.FilteredElementCollector(doc).OfClass(DB.DesignOption)
               if normalize_string(o.Name).lower() == text_type(ctx.require("option")).strip().lower()
               or text_type(id_int(o)) == text_type(ctx.get("option"))]
        if not opt:
            raise RvtssError("Design option '{}' not found".format(ctx.get("option")), status=404,
                             available=[o["name"] for o in _design_options(doc)])
        col = DB.FilteredElementCollector(doc).WherePasses(DB.ElementDesignOptionFilter(opt[0].Id))
        ids = [id_int(i) for i in col.ToElementIds()]
        limit = ctx.int("limit", 500, 1, core.MAX_LIMIT)
        return {"option": normalize_string(opt[0].Name), "count": len(ids), "element_ids": ids[:limit],
                "truncated": len(ids) > limit}
    if action == "set_element_phase":
        elements = core.get_elements(doc, ctx.list("element_ids"))
        if not elements:
            raise RvtssError("element_ids is required")
        created = _phase(doc, ctx.get("created")) if ctx.get("created") else None
        demolished_ref = ctx.get("demolished")
        demolished = _phase(doc, demolished_ref) if demolished_ref not in (None, "") else None
        preview = core.confirm_gate(ctx, len(elements), "set_element_phase")

        def run():
            res = []
            for e in elements:
                r = {"id": id_int(e), "ok": True}
                try:
                    if created is not None:
                        e.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(created.Id)
                    if demolished_ref is not None:
                        e.get_Parameter(DB.BuiltInParameter.PHASE_DEMOLISHED).Set(
                            demolished.Id if demolished is not None else DB.ElementId.InvalidElementId)
                except Exception as ex:
                    r.update({"ok": False, "error": normalize_string(text_type(ex))})
                res.append(r)
            if ctx.bool("atomic", True) and any(not r["ok"] for r in res):
                raise RvtssError("Phase could not be set on every element", results=res)
            return {"results": res}

        dry = preview or ctx.dry_run
        result, fails = core.run_transaction(doc, "Set element phase", run, dry_run=dry)
        return core.preview_status(core.commit_result(result, fails, dry), preview)
    if action == "set_view_phase":
        v = core.find_view(doc, ctx.get("view"), uidoc=ctx.uidoc)
        ph = _phase(doc, ctx.get("phase")) if ctx.get("phase") else None
        pf = None
        if ctx.get("phase_filter"):
            pf = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.PhaseFilter)
                  if normalize_string(f.Name).lower() == text_type(ctx.get("phase_filter")).strip().lower()]
            if not pf:
                raise RvtssError("Phase filter '{}' not found".format(ctx.get("phase_filter")), status=404)
            pf = pf[0]

        def run():
            if ph is not None:
                v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).Set(ph.Id)
            if pf is not None:
                v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE_FILTER).Set(pf.Id)
            return {"view_id": id_int(v), "phase": normalize_string(ph.Name) if ph else None,
                    "phase_filter": normalize_string(pf.Name) if pf else None}

        result, fails = core.run_transaction(doc, "Set view phase", run, dry_run=ctx.dry_run)
        return core.commit_result(result, fails, ctx.dry_run)
    raise RvtssError("action must be list, option_elements, set_element_phase or set_view_phase")


# -------------------------------------------------------------------------- links
def _link_types(doc):
    return list(DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType))


def _link_info(doc, lt):
    path = None
    try:
        ext = lt.GetExternalFileReference()
        path = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(ext.GetAbsolutePath())
    except Exception:
        pass
    status = None
    try:
        status = text_type(DB.RevitLinkType.GetLinkedFileStatus(lt.Id)) if hasattr(DB.RevitLinkType, "GetLinkedFileStatus") \
            else text_type(lt.GetLinkedFileStatus())
    except Exception:
        try:
            status = "Loaded" if DB.RevitLinkType.IsLoaded(doc, lt.Id) else "Unloaded"
        except Exception:
            pass
    inst = [id_int(i.Id) for i in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance)
            if i.GetTypeId() == lt.Id]
    return {"id": id_int(lt), "name": normalize_string(get_element_name(lt)), "path": path, "status": status,
            "is_nested": lt.IsNestedLink, "instance_ids": inst}


def _find_link(doc, ref):
    for lt in _link_types(doc):
        if text_type(id_int(lt)) == text_type(ref) or \
                normalize_string(get_element_name(lt)).lower() in (text_type(ref).strip().lower(),
                                                                    text_type(ref).strip().lower() + ".rvt"):
            return lt
    raise RvtssError("Revit link '{}' not found".format(ref), status=404,
                     available=[normalize_string(get_element_name(l)) for l in _link_types(doc)])


def links(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    if action == "list":
        items = [_link_info(doc, lt) for lt in _link_types(doc)]
        return {"count": len(items), "links": items}
    if action in ("reload", "unload", "reload_from"):
        lt = _find_link(doc, ctx.require("link"))
        if lt.IsNestedLink:
            raise RvtssError("Nested links are reloaded through their parent link")
        if ctx.dry_run:
            return {"status": "dry_run", "would": action, "link": _link_info(doc, lt)}
        core.require_writable(action + " link")
        if doc.IsModifiable:
            raise RvtssError("Links cannot be reloaded while a transaction is open", status=409)
        if action == "reload":
            res = lt.Reload()
        elif action == "unload":
            lt.Unload(None)
            res = None
        else:
            mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(ctx.require("path"))
            res = lt.LoadFrom(mp, DB.WorksetConfiguration())
        out = {"action": action, "link": _link_info(doc, lt)}
        if res is not None:
            try:
                out["load_result"] = text_type(res.LoadResult)
            except Exception:
                pass
        return out
    if action == "load":
        path = ctx.require("path")
        placement = {"origin": DB.ImportPlacement.Origin, "center": DB.ImportPlacement.Centered,
                     "shared": DB.ImportPlacement.Shared}.get(ctx.get("placement", "origin"), DB.ImportPlacement.Origin)

        def run():
            mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
            opts = DB.RevitLinkOptions(ctx.bool("relative", True))
            res = DB.RevitLinkType.Create(doc, mp, opts)
            inst = DB.RevitLinkInstance.Create(doc, res.ElementId, placement)
            return {"link_type_id": id_int(res.ElementId), "instance_id": id_int(inst),
                    "load_result": text_type(res.LoadResult)}

        result, fails = core.run_transaction(doc, "Load Revit link", run, dry_run=ctx.dry_run)
        return core.commit_result(result, fails, ctx.dry_run)
    raise RvtssError("action must be list, reload, unload, reload_from or load")


# ----------------------------------------------------------------- selection sets
def _sets(doc):
    return list(DB.FilteredElementCollector(doc).OfClass(DB.SelectionFilterElement))


def _find_set(doc, name):
    low = text_type(name).strip().lower()
    for s in _sets(doc):
        if normalize_string(s.Name).lower() == low:
            return s
    return None


def selection_sets(ctx):
    doc = ctx.doc
    action = ctx.get("action", "list")
    if action == "list":
        return {"sets": [{"id": id_int(s), "name": normalize_string(s.Name), "count": s.GetElementIds().Count}
                         for s in _sets(doc)]}
    name = ctx.require("name")
    existing = _find_set(doc, name)
    if action == "load":
        if existing is None:
            raise RvtssError("Selection set '{}' not found".format(name), status=404)
        ids = list(existing.GetElementIds())
        if ctx.uidoc is not None and ctx.uidoc.Document.Equals(doc):
            ctx.uidoc.Selection.SetElementIds(core.to_id_list(ids))
            selected = True
        else:
            selected = False
        return {"name": normalize_string(existing.Name), "element_ids": [id_int(i) for i in ids[:1000]],
                "count": len(ids), "selected_in_revit": selected}
    if action == "save":
        ids = ctx.list("element_ids")
        if not ids:
            if ctx.uidoc is None or not ctx.uidoc.Document.Equals(doc):
                raise RvtssError("Pass element_ids (no active selection in this document)")
            ids = [id_int(i) for i in ctx.uidoc.Selection.GetElementIds()]
        if not ids:
            raise RvtssError("Nothing to save: pass element_ids or select elements in Revit")
        if existing is not None and not ctx.bool("overwrite", False):
            raise RvtssError("Selection set '{}' exists".format(name), status=409, hint="Pass overwrite=true.")
        elements = core.get_elements(doc, ids)

        def run():
            s = existing
            if s is None:
                s = DB.SelectionFilterElement.Create(doc, text_type(name))
            s.SetElementIds(core.to_id_list([e.Id for e in elements]))
            return {"id": id_int(s), "name": normalize_string(s.Name), "count": len(elements)}

        result, fails = core.run_transaction(doc, "Save selection set", run, dry_run=ctx.dry_run)
        return core.commit_result(result, fails, ctx.dry_run)
    if action == "delete":
        if existing is None:
            raise RvtssError("Selection set '{}' not found".format(name), status=404)

        def run():
            doc.Delete(existing.Id)
            return {"deleted": normalize_string(name)}

        result, fails = core.run_transaction(doc, "Delete selection set", run, dry_run=ctx.dry_run)
        return core.commit_result(result, fails, ctx.dry_run)
    raise RvtssError("action must be list, save, load or delete")


def register_model_state_routes(api):
    @api.route("/phases/manage/", methods=["POST"])
    def phases_route(doc, uidoc, request):
        return handle(doc, request, phases, uidoc=uidoc)

    @api.route("/links/manage/", methods=["POST"])
    def links_route(doc, request):
        return handle(doc, request, links)

    @api.route("/selection_sets/", methods=["POST"])
    def selection_sets_route(doc, uidoc, request):
        return handle(doc, request, selection_sets, uidoc=uidoc)

    logger.info("RVTSS phases / links / selection set routes registered")
