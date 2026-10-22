# -*- coding: utf-8 -*-
"""Family library audit on plain records (filled by revit_mcp/family_library.py).

Record: {"file", "path", "size_kb", "category", "parameters": [{"name", "shared", "instance", "formula"}],
         "types": [names], "nested": [names], "warnings": [texts], "validation": {"summary", "findings"},
         "error": str (open failed)}
"""
import os
import re

from . import rules as R
from . import naming as N

BACKUP_RX = re.compile(r"\.\d{4}\.rfa$", re.IGNORECASE)


def is_family_file(name):
    return name.lower().endswith(".rfa") and not BACKUP_RX.search(name)


def list_files(walk_items, recursive=True, root=None):
    """walk_items: os.walk-like [(dirpath, dirnames, filenames)] -> sorted .rfa paths (backups skipped)."""
    out = []
    for dirpath, _dirs, files in walk_items:
        if not recursive and root is not None and os.path.normpath(dirpath) != os.path.normpath(root):
            continue
        for f in files:
            if is_family_file(f):
                out.append(os.path.join(dirpath, f))
    return sorted(out, key=lambda p: p.lower())


def family_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def summary_row(rec):
    params = rec.get("parameters") or []
    v = (rec.get("validation") or {}).get("summary") or {}
    sev = v.get("by_severity") or {}
    return {"family": family_name(rec.get("path") or rec.get("file") or ""), "file": rec.get("file"),
            "category": rec.get("category"), "size_kb": rec.get("size_kb"), "types": len(rec.get("types") or []),
            "parameters": len(params), "shared_parameters": len([p for p in params if p.get("shared")]),
            "nested": len(rec.get("nested") or []), "warnings": len(rec.get("warnings") or []),
            "validation_errors": sev.get("error", 0) + sev.get("critical", 0),
            "validation_warnings": sev.get("warning", 0), "error": rec.get("error")}


def library_findings(records, naming_rule=None, iso_scheme=None, max_size_kb=2048, max_nested=10):
    out = []

    def ids(recs):
        return [family_name(r.get("path") or r.get("file") or "") for r in recs]

    failed = [r for r in records if r.get("error")]
    if failed:
        out.append(R.finding("library_open", "error", "%d families could not be opened" % len(failed),
                             ids(failed), errors=[{"file": r.get("file"), "error": r.get("error")} for r in failed[:20]],
                             recommendation="Open them manually in Revit to see the error (corrupt or newer version)."))
    ok = [r for r in records if not r.get("error")]
    big = [r for r in ok if (r.get("size_kb") or 0) > max_size_kb]
    if big:
        out.append(R.finding("library_size", "warning", "%d families are larger than %d KB" % (len(big), max_size_kb),
                             ids(big), sizes=dict((family_name(r["path"]), r.get("size_kb")) for r in big[:30]),
                             recommendation="Purge unused nested families/materials, remove imported CAD, simplify geometry."))
    generic = [r for r in ok if r.get("category") in (None, "", "Generic Models")]
    if generic:
        out.append(R.finding("library_category", "info", "%d families use Generic Models or no category" % len(generic),
                             ids(generic), recommendation="Use a specific category so the family schedules and filters."))
    no_types = [r for r in ok if not r.get("types")]
    if no_types:
        out.append(R.finding("library_types", "warning", "%d families have no types" % len(no_types), ids(no_types)))
    nested = [r for r in ok if len(r.get("nested") or []) > max_nested]
    if nested:
        out.append(R.finding("library_nested", "info", "%d families nest more than %d families" % (
            len(nested), max_nested), ids(nested)))
    warned = [r for r in ok if r.get("warnings")]
    if warned:
        out.append(R.finding("library_warnings", "warning", "%d families contain Revit warnings" % len(warned),
                             ids(warned), examples=dict((family_name(r["path"]), r["warnings"][:3]) for r in warned[:15])))
    invalid = [r for r in ok if summary_row(r)["validation_errors"]]
    if invalid:
        out.append(R.finding("library_validation", "error", "%d families fail family_validate" % len(invalid),
                             ids(invalid), details=dict((family_name(r["path"]), [
                                 f.get("message") for f in (r.get("validation") or {}).get("findings", [])
                                 if f.get("severity") in ("error", "critical")][:5]) for r in invalid[:20]),
                             recommendation="Open the family and fix the errors listed (family_validate)."))
    dup_params = []
    for r in ok:
        seen = {}
        for p in r.get("parameters") or []:
            seen.setdefault((p.get("name") or "").lower(), 0)
            seen[(p.get("name") or "").lower()] += 1
        if [k for k, n in seen.items() if n > 1]:
            dup_params.append(r)
    if dup_params:
        out.append(R.finding("library_parameters", "warning", "%d families have parameters with the same name "
                             "(differing only in case or shared vs family)" % len(dup_params), ids(dup_params)))
    items = [(family_name(r.get("path") or r.get("file") or ""), family_name(r.get("path") or r.get("file") or ""))
             for r in records]
    if naming_rule and naming_rule.get("pattern"):
        out.extend(R.check_names(items, naming_rule, "library_naming", "family files"))
    if iso_scheme:
        out.extend(N.check_items(items, iso_scheme, "families", "family files"))
    return R.sort_findings(out)
