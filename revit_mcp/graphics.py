# -*- coding: UTF-8 -*-
"""Rule-based view filters and revisions (RVTSS v2.2).

Routes:
    POST /views/filters/      list filters (rules, where used), create rule-based filters, apply to views /
                              templates with visibility and overrides, remove, delete
    POST /sheets/revisions/   list revisions (with sheets), create, assign / unassign to sheets, mark issued
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, text_type, make_id
from .pure import filter_rules as FR
from .pure import units as U
from .utils import normalize_string

logger = logging.getLogger(__name__)


def _id_list(ids):
    from System.Collections.Generic import List

    lst = List[DB.ElementId]()
    for i in ids:
        lst.Add(i)
    return lst


# ---------------------------------------------------------------- view filters
def _param_label(doc, pid):
    v = id_int(pid)
    if v < 0:
        try:
            import System

            bip = System.Enum.ToObject(DB.BuiltInParameter, v)
            return normalize_string(DB.LabelUtils.GetLabelFor(bip))
        except Exception:
            return text_type(v)
    e = doc.GetElement(pid)
    return normalize_string(e.Name) if e is not None else text_type(v)


def _filterable(doc, cat_ids):
    """{lower-case label / BuiltInParameter name: ElementId} common to the categories."""
    out = {}
    for pid in DB.ParameterFilterUtilities.GetFilterableParametersInCommon(doc, _id_list(cat_ids)):
        out[_param_label(doc, pid).lower()] = pid
        if id_int(pid) < 0:
            try:
                import System

                out[text_type(System.Enum.ToObject(DB.BuiltInParameter, id_int(pid))).lower()] = pid
            except Exception:
                pass
    return out


def _rule_parameter(doc, name, filterable):
    key = text_type(name).strip().lower()
    if key in filterable:
        return filterable[key]
    raise core.not_found("Filterable parameter (common to all the filter's categories)", name,
                         sorted(set(_param_label(doc, p) for p in filterable.values())),
                         hint="A filter rule can only use a parameter every chosen category has.")


def _param_storage(doc, cat_ids, pid):
    """(StorageType name, unit kind) of a filter parameter, read from one element of the categories."""
    from .compat import definition_spec

    for cid in cat_ids:
        for col in (DB.FilteredElementCollector(doc).OfCategoryId(cid).WhereElementIsNotElementType(),
                    DB.FilteredElementCollector(doc).OfCategoryId(cid).WhereElementIsElementType()):
            for e in col:
                p = None
                try:
                    if id_int(pid) < 0:
                        import System

                        p = e.get_Parameter(System.Enum.ToObject(DB.BuiltInParameter, id_int(pid)))
                    else:
                        for q in e.Parameters:
                            if q.Id == pid:
                                p = q
                                break
                except Exception:
                    p = None
                if p is not None:
                    _name, kind = definition_spec(p.Definition)
                    return str(p.StorageType), kind
                break  # the first element of a category is representative
    return None, None


def _adapt_rule(doc, cat_ids, pid, r, default_unit, warn):
    """Fit the rule's value type and unit to the parameter: doubles in project units, mm by default."""
    r = dict(r)
    storage, kind = _param_storage(doc, cat_ids, pid)
    if r["kind"] in ("integer", "double") and storage == "Double":
        r["kind"] = "double"
        r["value"] = float(r["value"])
        if kind in ("length", "area", "volume", "angle", "measurable"):
            base = kind if kind != "measurable" else "length"
            r["unit"] = U.length_unit_for(base, r.get("unit") or default_unit)
        else:
            r["unit"] = r.get("unit")  # plain number: no conversion unless a unit was given
    elif r["kind"] == "double" and storage == "Integer" and not r.get("unit"):
        r["kind"], r["value"] = "integer", int(r["value"])
    elif r["kind"] == "integer" and storage == "ElementId":
        r["kind"] = "element_id"
    elif storage is None and r["kind"] == "double":
        r["unit"] = r.get("unit") or default_unit
        warn("Could not sample parameter '{}' on the categories; the value was read as a length in {}.".format(
            r["parameter"], r["unit"]))
    return r


def _make_rule(doc, pid, r):
    fac = DB.ParameterFilterRuleFactory
    method = getattr(fac, FR.FACTORY[r["op"]], None)
    if method is None:
        raise RvtssError("Rule op '{}' is not available in this Revit version".format(r["op"]), status=501,
                         hint="has_value / has_no_value rules need Revit 2023+.")
    kind, value = r["kind"], r["value"]
    if kind is None:
        return method(pid)
    if kind == "string":
        try:
            return method(pid, value)  # Revit 2023+
        except Exception:
            return method(pid, value, False)  # older: caseSensitive argument
    if kind == "double":
        v = U.to_internal(value, r["unit"]) if r.get("unit") else value
        return method(pid, v, 1e-6)
    if kind == "element_id":
        return method(pid, make_id(value))
    return method(pid, int(value))


def _ogs(doc, spec):
    from .documentation import _color, _solid_fill

    ogs = DB.OverrideGraphicSettings()
    if spec.get("color"):
        c = _color(spec["color"])
        ogs.SetProjectionLineColor(c)
        ogs.SetCutLineColor(c)
        fill = _solid_fill(doc)
        if fill is not None and spec.get("fill", True):
            try:
                ogs.SetSurfaceForegroundPatternId(fill)
                ogs.SetSurfaceForegroundPatternColor(c)
                ogs.SetCutForegroundPatternId(fill)
                ogs.SetCutForegroundPatternColor(c)
            except AttributeError:
                pass
    if spec.get("line_weight"):
        ogs.SetProjectionLineWeight(max(1, min(16, int(spec["line_weight"]))))
    if spec.get("halftone") is not None:
        ogs.SetHalftone(bool(spec["halftone"]))
    if spec.get("transparency") is not None:
        ogs.SetSurfaceTransparency(max(0, min(100, int(spec["transparency"]))))
    return ogs


def _find_filter(doc, name_or_id):
    filters = list(DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement))
    s = text_type(name_or_id).strip()
    for f in filters:
        if normalize_string(f.Name).lower() == s.lower() or text_type(id_int(f)) == s:
            return f
    raise core.not_found("View filter", name_or_id, [f.Name for f in filters])


def _describe_filter(doc, f, usage):
    d = {"id": id_int(f), "name": normalize_string(f.Name),
         "categories": [normalize_string(DB.Category.GetCategory(doc, c).Name) for c in f.GetCategories()
                        if DB.Category.GetCategory(doc, c) is not None]}
    try:
        ef = f.GetElementFilter()
        d["logic"] = type(ef).__name__ if ef is not None else None
        rules = []
        subs = [ef]
        try:
            subs = list(ef.GetFilters())
        except Exception:
            pass
        for sub in subs:
            try:
                for rule in sub.GetRules():
                    rd = {"parameter": _param_label(doc, rule.GetRuleParameter()), "rule": type(rule).__name__}
                    try:
                        ev = rule.GetEvaluator()
                        rd["evaluator"] = type(ev).__name__
                    except Exception:
                        pass
                    for attr in ("RuleString", "RuleValue"):
                        try:
                            rd["value"] = text_type(getattr(rule, attr))
                            break
                        except Exception:
                            continue
                    rules.append(rd)
            except Exception:
                continue
        d["rules"] = rules
    except Exception:
        d["rules"] = None
    d["used_in"] = usage.get(id_int(f), [])
    return d


def _usage(doc):
    out = {}
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            fids = v.GetFilters()
        except Exception:
            continue
        for fid in fids:
            try:
                vis = v.GetFilterVisibility(fid)
            except Exception:
                vis = None
            out.setdefault(id_int(fid), []).append({"view_id": id_int(v), "view": normalize_string(v.Name),
                                                    "is_template": v.IsTemplate, "visible": vis})
    return out


def view_filters(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    if action == "list":
        usage = _usage(doc)
        out = [_describe_filter(doc, f, usage) for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)]
        contains = (ctx.get("contains") or "").lower()
        if contains:
            out = [d for d in out if contains in d["name"].lower()]
        out.sort(key=lambda d: d["name"].lower())
        return {"count": len(out), "filters": out, "unused": [d["name"] for d in out if not d["used_in"]]}
    dry = ctx.dry_run

    def run():
        if action == "create":
            name = ctx.require("name")
            if not DB.ParameterFilterElement.IsNameUnique(doc, name):
                raise RvtssError("A filter named '{}' already exists".format(name), status=409)
            cats = [core.resolve_category(doc, c) for c in ctx.list("categories")]
            if not cats:
                raise RvtssError("create needs categories")
            cat_ids = [c.Id for c in cats]
            rules_in = ctx.list("rules")
            if not rules_in:
                raise RvtssError("create needs rules: [{parameter, op, value, unit?}]",
                                 hint="ops: " + ", ".join(FR.ALL_OPS))
            filterable = _filterable(doc, cat_ids)
            rules = []
            for r in rules_in:
                try:
                    nr = FR.validate_rule(r)
                except FR.RuleError as e:
                    raise RvtssError(text_type(e))
                pid = _rule_parameter(doc, nr["parameter"], filterable)
                nr = _adapt_rule(doc, cat_ids, pid, nr, ctx.unit, ctx.warn)
                rules.append(_make_rule(doc, pid, nr))
            if ctx.get("logic", "and") == "or":
                from System.Collections.Generic import List

                subs = List[DB.ElementFilter]()
                for rule in rules:
                    subs.Add(DB.ElementParameterFilter(rule))
                ef = DB.LogicalOrFilter(subs)
            else:
                from System.Collections.Generic import List

                lst = List[DB.FilterRule]()
                for rule in rules:
                    lst.Add(rule)
                ef = DB.ElementParameterFilter(lst)
            f = DB.ParameterFilterElement.Create(doc, name, _id_list(cat_ids), ef)
            out = {"filter_id": id_int(f), "name": normalize_string(f.Name), "rules": len(rules)}
            if ctx.list("apply_to"):
                out["applied"] = [_apply(doc, ctx, f, v) for v in ctx.list("apply_to")]
            return out
        f = _find_filter(doc, ctx.require("filter"))
        if action == "apply":
            views = ctx.list("apply_to") or [ctx.get("view", "active")]
            return {"filter": normalize_string(f.Name), "applied": [_apply(doc, ctx, f, v) for v in views]}
        if action == "remove":
            done = []
            for vname in ctx.list("apply_to") or [ctx.get("view", "active")]:
                v = _view_or_template(doc, ctx, vname)
                if f.Id in list(v.GetFilters()):
                    v.RemoveFilter(f.Id)
                    done.append(normalize_string(v.Name))
            return {"filter": normalize_string(f.Name), "removed_from": done}
        if action == "delete":
            if not ctx.confirmed:
                raise RvtssError("Deleting a filter removes it from every view and template; pass confirm=true",
                                 status=409, used_in=_usage(doc).get(id_int(f), []))
            name = normalize_string(f.Name)
            doc.Delete(f.Id)
            return {"deleted": name}
        raise RvtssError("action must be list, create, apply, remove or delete")

    res, fails = core.run_transaction(doc, "View filters: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry)


def _view_or_template(doc, ctx, name):
    if name in (None, "", "active"):
        return core.find_view(doc, "active", uidoc=ctx.uidoc)
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if v.IsTemplate and (normalize_string(v.Name).lower() == text_type(name).lower()
                             or text_type(id_int(v)) == text_type(name)):
            return v
    return core.find_view(doc, name)


def _apply(doc, ctx, f, vname):
    v = _view_or_template(doc, ctx, vname)
    if not v.IsTemplate and is_valid_id(v.ViewTemplateId):
        tpl = doc.GetElement(v.ViewTemplateId)
        ctx.warn("View '{}' uses template '{}': filters may be controlled by the template - apply to the template "
                 "instead.".format(normalize_string(v.Name), normalize_string(tpl.Name)))
    if not v.IsFilterApplied(f.Id):
        v.AddFilter(f.Id)
    vis = ctx.get("visible")
    if vis is not None:
        v.SetFilterVisibility(f.Id, bool(vis))
    ov = ctx.get("overrides")
    if ov:
        v.SetFilterOverrides(f.Id, _ogs(doc, ov))
    return {"view_id": id_int(v), "view": normalize_string(v.Name), "is_template": v.IsTemplate,
            "visible": v.GetFilterVisibility(f.Id)}


# -------------------------------------------------------------------- revisions
def _sheets_by_key(doc):
    sheets = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet) if not s.IsTemplate]
    return sheets, dict((normalize_string(s.SheetNumber).lower(), s) for s in sheets)


def _resolve_sheets(doc, keys):
    sheets, by_num = _sheets_by_key(doc)
    out = []
    for k in keys:
        s = by_num.get(text_type(k).strip().lower())
        if s is None and text_type(k).isdigit():
            e = doc.GetElement(make_id(int(k)))
            s = e if isinstance(e, DB.ViewSheet) else None
        if s is None:
            raise core.not_found("Sheet", k, [x.SheetNumber for x in sheets])
        out.append(s)
    return out


def _find_revision(doc, key):
    revs = list(DB.FilteredElementCollector(doc).OfClass(DB.Revision))
    s = text_type(key).strip()
    for r in revs:
        if text_type(id_int(r)) == s or normalize_string(r.Description or "").lower() == s.lower() or \
                text_type(r.SequenceNumber) == s:
            return r
    raise core.not_found("Revision (id, sequence number or description)", key,
                         [u"{} {}".format(r.SequenceNumber, r.Description) for r in revs])


def _describe_revision(r, sheets_by_rev):
    d = {"id": id_int(r), "sequence": r.SequenceNumber, "number": normalize_string(r.RevisionNumber or ""),
         "date": normalize_string(r.RevisionDate or ""), "description": normalize_string(r.Description or ""),
         "issued": r.Issued, "issued_to": normalize_string(r.IssuedTo or ""),
         "issued_by": normalize_string(r.IssuedBy or ""), "visibility": str(r.Visibility)}
    if sheets_by_rev is not None:
        d["sheets"] = sorted(sheets_by_rev.get(id_int(r), []))
    return d


def revisions(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    if action == "list":
        sheets, _ = _sheets_by_key(doc)
        by_rev = {}
        for s in sheets:
            try:
                for rid in s.GetAllRevisionIds():
                    by_rev.setdefault(id_int(rid), []).append(normalize_string(s.SheetNumber))
            except Exception:
                continue
        revs = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Revision), key=lambda r: r.SequenceNumber)
        return {"count": len(revs), "revisions": [_describe_revision(r, by_rev) for r in revs]}
    dry = ctx.dry_run

    def run():
        if action == "create":
            r = DB.Revision.Create(doc)
            for key, attr in (("description", "Description"), ("date", "RevisionDate"), ("issued_to", "IssuedTo"),
                              ("issued_by", "IssuedBy")):
                if ctx.get(key) is not None:
                    setattr(r, attr, text_type(ctx.get(key)))
            out = {"revision": _describe_revision(r, None)}
            if ctx.list("sheets"):
                out["assigned"] = _assign(doc, [r], _resolve_sheets(doc, ctx.list("sheets")), True)
            return out
        r = _find_revision(doc, ctx.require("revision"))
        if action in ("assign", "unassign"):
            sheets = _resolve_sheets(doc, ctx.list("sheets"))
            if not sheets:
                raise RvtssError("{} needs sheets (numbers or ids)".format(action))
            out = {"revision": _describe_revision(r, None),
                   action + "ed": _assign(doc, [r], sheets, action == "assign")}
            if action == "unassign":
                still = [normalize_string(s.SheetNumber) for s in sheets
                         if r.Id in list(s.GetAllRevisionIds())]
                if still:
                    out["still_shown_by_clouds"] = still
                    ctx.warn("The revision stays on {} because revision clouds in views on those sheets use it; "
                             "delete or change the clouds to remove it.".format(", ".join(still)))
            return out
        if action == "issue":
            r.Issued = True
            return {"revision": _describe_revision(r, None),
                    "note": "Issued revisions are locked: clouds and fields can no longer be edited."}
        if action == "update":
            if r.Issued:
                raise RvtssError("Revision is issued (locked); set issued=false in Revit first", status=409)
            for key, attr in (("description", "Description"), ("date", "RevisionDate"), ("issued_to", "IssuedTo"),
                              ("issued_by", "IssuedBy")):
                if ctx.get(key) is not None:
                    setattr(r, attr, text_type(ctx.get(key)))
            return {"revision": _describe_revision(r, None)}
        raise RvtssError("action must be list, create, update, assign, unassign or issue")

    res, fails = core.run_transaction(doc, "Revisions: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry)


def _assign(doc, revs, sheets, add):
    done = []
    for s in sheets:
        current = list(s.GetAdditionalRevisionIds())
        ids = set(id_int(i) for i in current)
        for r in revs:
            if add:
                ids.add(id_int(r))
            else:
                ids.discard(id_int(r))
        s.SetAdditionalRevisionIds(_id_list([make_id(i) for i in sorted(ids)]))
        done.append(normalize_string(s.SheetNumber))
    return done


def register_graphics_routes(api):
    @api.route("/views/filters/", methods=["POST"])
    def views_filters_route(doc, uidoc, request):
        return handle(doc, request, view_filters, uidoc=uidoc)

    @api.route("/sheets/revisions/", methods=["POST"])
    def sheets_revisions_route(doc, request):
        return handle(doc, request, revisions)

    logger.info("RVTSS graphics routes registered")
