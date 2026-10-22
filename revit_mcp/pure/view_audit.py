# -*- coding: utf-8 -*-
"""View, view-template, sheet and scope-box audit on plain data (filled by revit_mcp/qc.py).

views:       [{"id", "name", "view_type", "is_template", "template_id", "on_sheet", "scope_box_id",
               "is_dependent", "printable"}]
sheets:      [{"id", "number", "name", "view_count", "is_placeholder"}]
scope_boxes: [{"id", "name"}]
datum_scope_box_ids: scope boxes used by grids / levels / reference planes
"""
from . import rules as R


def audit(views, sheets, scope_boxes, datum_scope_box_ids=None, require_template_types=None):
    out = []
    templates = [v for v in views if v.get("is_template")]
    real = [v for v in views if not v.get("is_template")]
    printable = [v for v in real if v.get("printable", True)]

    kinds = set(require_template_types) if require_template_types else None
    no_template = [v for v in printable if not v.get("template_id")
                   and (kinds is None or v.get("view_type") in kinds)]
    if no_template:
        by_type = {}
        for v in no_template:
            by_type[v.get("view_type")] = by_type.get(v.get("view_type"), 0) + 1
        out.append(R.finding("view_audit", "warning", "%d views have no view template" % len(no_template),
                             [v["id"] for v in no_template], by_view_type=by_type,
                             examples=[v["name"] for v in no_template[:15]],
                             recommendation="Assign the project's view templates (view_graphics / view template)."))

    used = set(v.get("template_id") for v in real if v.get("template_id"))
    unused = [t for t in templates if t["id"] not in used]
    if unused:
        out.append(R.finding("view_audit", "info", "%d view templates are not used by any view" % len(unused),
                             [t["id"] for t in unused], examples=[t["name"] for t in unused[:15]],
                             recommendation="Delete unused templates after checking the office standard."))

    empty = [s for s in sheets if not s.get("is_placeholder") and not s.get("view_count")]
    if empty:
        out.append(R.finding("view_audit", "warning", "%d sheets have no views" % len(empty),
                             [s["id"] for s in empty],
                             examples=["%s - %s" % (s.get("number"), s.get("name")) for s in empty[:15]],
                             recommendation="Place views or delete the empty sheets."))

    off_sheet = [v for v in printable if not v.get("on_sheet") and not v.get("is_dependent")]
    if off_sheet:
        out.append(R.finding("view_audit", "info", "%d views are not placed on any sheet" % len(off_sheet),
                             [v["id"] for v in off_sheet], examples=[v["name"] for v in off_sheet[:15]],
                             recommendation="Place them on sheets or delete working views before issue."))

    names = {}
    for v in real:
        names.setdefault((v.get("name") or "").strip().lower(), []).append(v)
    dups = dict((k, vs) for k, vs in names.items() if k and len(vs) > 1)
    if dups:
        ids = [v["id"] for vs in dups.values() for v in vs]
        out.append(R.finding("view_audit", "warning", "%d view names are used by more than one view" % len(dups),
                             ids, examples=["%s (%s)" % (vs[0]["name"], ", ".join(sorted(set(
                                 str(v.get("view_type")) for v in vs)))) for vs in list(dups.values())[:15]],
                             recommendation="Rename so view names are unique across view types (e.g. add 'RCP')."))

    if scope_boxes:
        used_boxes = set(v.get("scope_box_id") for v in views if v.get("scope_box_id"))
        used_boxes.update(datum_scope_box_ids or [])
        idle = [b for b in scope_boxes if b["id"] not in used_boxes]
        if idle:
            out.append(R.finding("view_audit", "info", "%d scope boxes are not used by views or datums" % len(idle),
                                 [b["id"] for b in idle], examples=[b["name"] for b in idle[:15]],
                                 recommendation="Delete unused scope boxes."))
    return out
