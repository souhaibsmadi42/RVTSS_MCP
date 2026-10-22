# -*- coding: UTF-8 -*-
"""Family library audit (RVTSS v2.1).

Route:
    POST /family/library_audit/   open every .rfa in a folder read-only, inspect, close without saving

Each family is opened with Application.OpenDocumentFile, inspected (category, size,
parameters, types, nested families, warnings, family_validate findings) and closed
with Close(False) - nothing is ever saved. Families that are already open in Revit
are inspected but left open. dry_run lists the files without opening them.
"""
import os
import time
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int
from .family_utils import is_builtin
from .pure import family_library as L
from .utils import normalize_string

logger = logging.getLogger(__name__)


def _inspect(fdoc, path):
    fm = fdoc.FamilyManager
    cat = fdoc.OwnerFamily.FamilyCategory
    params = []
    for fp in fm.Parameters:
        if is_builtin(fp):
            continue
        params.append({"name": normalize_string(fp.Definition.Name), "shared": fp.IsShared,
                       "instance": fp.IsInstance, "formula": bool(fp.Formula)})
    owner = id_int(fdoc.OwnerFamily)
    nested = sorted(set(normalize_string(f.Name) for f in DB.FilteredElementCollector(fdoc).OfClass(DB.Family)
                        if id_int(f) != owner))
    warnings = sorted(set(normalize_string(w.GetDescriptionText()) for w in fdoc.GetWarnings()))
    return {"category": normalize_string(cat.Name) if cat else None, "parameters": params,
            "types": [normalize_string(t.Name) for t in fm.Types], "nested": nested, "warnings": warnings}


def _validate(fdoc):
    from .families import family_validate

    vctx = core.Ctx(fdoc, None, {"check_dimension_values": True}, needs_doc=False)
    res = family_validate(vctx)
    return {"summary": res.get("summary"), "findings": res.get("findings", [])[:20]}


def library_audit(ctx):
    folder = ctx.require("folder", "folder with .rfa files")
    if not os.path.isdir(folder):
        raise RvtssError("Folder not found: {}".format(folder), status=404)
    recursive = ctx.bool("recursive", True)
    walk = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    files = L.list_files(walk, recursive, folder)
    contains = (ctx.get("name_contains") or "").lower()
    if contains:
        files = [f for f in files if contains in os.path.basename(f).lower()]
    max_files = ctx.int("max_files", 50, 1, 500)
    max_mb = ctx.float("max_file_mb", 50.0)
    skipped = []
    selected = []
    for f in files:
        size_mb = os.path.getsize(f) / 1048576.0
        if size_mb > max_mb:
            skipped.append({"file": os.path.basename(f), "reason": "larger than {} MB".format(max_mb)})
        elif len(selected) < max_files:
            selected.append(f)
        else:
            skipped.append({"file": os.path.basename(f), "reason": "max_files={} reached".format(max_files)})
    if ctx.dry_run:
        return {"status": "dry_run", "folder": folder, "families_found": len(files),
                "would_open": [os.path.relpath(f, folder) for f in selected], "skipped": skipped[:100],
                "total_size_mb": round(sum(os.path.getsize(f) for f in selected) / 1048576.0, 1),
                "note": "Families are opened read-only and closed without saving."}

    app = ctx.app
    open_docs = dict(((d.PathName or "").lower(), d) for d in app.Documents if d.PathName)
    records = []
    t0 = time.time()
    validate = ctx.bool("validate", True)
    for path in selected:
        rec = {"file": os.path.relpath(path, folder), "path": path,
               "size_kb": int(os.path.getsize(path) / 1024)}
        fdoc = open_docs.get(path.lower())
        opened_here = fdoc is None
        try:
            if opened_here:
                fdoc = app.OpenDocumentFile(path)
            if not fdoc.IsFamilyDocument:
                raise RvtssError("not a family document")
            rec.update(_inspect(fdoc, path))
            if validate:
                rec["validation"] = _validate(fdoc)
            if not opened_here:
                rec["already_open"] = True
        except Exception as e:
            rec["error"] = normalize_string(core.text_type(e))[:300]
        finally:
            if opened_here and fdoc is not None:
                try:
                    fdoc.Close(False)
                except Exception as e:
                    logger.warning("Could not close %s: %s", path, e)
        records.append(rec)

    rules = core.load_qc_rules()[0]
    naming_rule = (rules.get("naming") or {}).get("families")
    iso = rules.get("iso19650") if (rules.get("iso19650") or {}).get("targets", {}).get("families") else None
    findings = L.library_findings(records, naming_rule, iso, ctx.int("max_size_kb", 2048), ctx.int("max_nested", 10))
    from .pure import rules as R

    return {"folder": folder, "families_found": len(files), "audited": len(records), "skipped": skipped[:100],
            "seconds": round(time.time() - t0, 1), "summary": R.summarize(findings), "findings": findings,
            "families": [L.summary_row(r) for r in records],
            "details": records if ctx.bool("include_details", False) else None}


def register_family_library_routes(api):
    @api.route("/family/library_audit/", methods=["POST"])
    def family_library_audit_route(doc, request):
        return handle(doc, request, library_audit, needs_doc=False)

    logger.info("RVTSS family library routes registered")
