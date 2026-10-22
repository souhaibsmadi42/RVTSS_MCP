# -*- coding: UTF-8 -*-
"""Project / shared / global parameter management (RVTSS).

Routes:
    POST /parameters/project/   list project parameter bindings (categories, instance/type, shared GUID)
    POST /parameters/shared/    read_file | create_definitions | bind | create_file
    POST /parameters/global/    list | create | set_value | set_formula | associate | dissociate
    POST /parameters/audit/     missing / empty / invalid values, wrong data types, duplicate definitions
    POST /parameters/export/    element parameter values to CSV
    POST /parameters/import/    CSV (ElementId column) back into the model
    POST /parameters/map/       copy values between parameters (naming-standard migrations)

API limits respected: existing shared parameter GUIDs are never rewritten; a
definition name already present in the file is reused, not duplicated;
project parameters are created from shared definitions (the reliable cross-
version path); bound parameters are extended with ReInsert, never replaced.
"""
import os
import logging

from pyrevit import DB
import System

from . import core
from .core import RvtssError, handle
from .compat import (id_int, text_type, definition_spec, definition_group, external_definition_options,
                     insert_binding, reinsert_binding, spec_id, is_valid_id, make_id)
from .params_util import find as find_param, read as read_param, set_value, raw_value
from .query import collect, query_spec
from .pure import sharedparams as SP
from .pure import csvutil
from .pure import filters as F
from .pure import rules as R
from .pure import units as U
from .utils import normalize_string

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- project
def _bindings(doc):
    out = []
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        d = it.Key
        b = it.Current
        cats = sorted(normalize_string(c.Name) for c in b.Categories)
        spec, _kind = definition_spec(d)
        entry = {"name": normalize_string(d.Name), "binding": "instance" if isinstance(b, DB.InstanceBinding) else "type",
                 "categories": cats, "spec": spec, "group": definition_group(d)}
        try:
            pe = doc.GetElement(d.Id)
            if isinstance(pe, DB.SharedParameterElement):
                entry["shared"] = True
                entry["guid"] = str(pe.GuidValue)
            else:
                entry["shared"] = False
            entry["id"] = id_int(d.Id)
        except Exception:
            pass
        try:
            entry["vary_between_groups"] = d.VariesAcrossGroups
        except Exception:
            pass
        out.append((d, b, entry))
    return out


def project_parameters(ctx):
    doc = ctx.doc
    core.require_project(doc)
    contains = (ctx.get("contains") or "").lower()
    items = [e for _d, _b, e in _bindings(doc) if not contains or contains in e["name"].lower()]
    items.sort(key=lambda e: e["name"].lower())
    names = {}
    for e in items:
        names.setdefault(e["name"].lower(), []).append(e)
    dups = [v[0]["name"] for v in names.values() if len(v) > 1]
    return {"count": len(items), "parameters": items, "duplicate_names": dups}


# -------------------------------------------------------------------- shared
class _SharedFile(object):
    """Temporarily point Revit at a shared parameter file and restore afterwards."""

    def __init__(self, app, path=None, create=False):
        self.app = app
        self.path = path
        self.create = create
        self.previous = None

    def __enter__(self):
        self.previous = self.app.SharedParametersFilename
        if self.path:
            if not os.path.isfile(self.path):
                if not self.create:
                    raise RvtssError("Shared parameter file not found: {}".format(self.path), status=404,
                                     hint="Pass create_file=true to create it.")
                folder = os.path.dirname(self.path)
                if folder and not os.path.isdir(folder):
                    os.makedirs(folder)
                open(self.path, "w").close()
            self.app.SharedParametersFilename = self.path
        dfile = self.app.OpenSharedParameterFile()
        if dfile is None:
            raise RvtssError("No shared parameter file is configured in Revit", status=409,
                             hint="Pass shared_parameter_file (and create_file=true for a new one).")
        return dfile

    def __exit__(self, *exc):
        if self.path and self.previous and self.previous != self.path:
            try:
                self.app.SharedParametersFilename = self.previous
            except Exception:
                pass
        return False


def _all_definitions(dfile):
    for g in dfile.Groups:
        for d in g.Definitions:
            yield g, d


def _find_definition(dfile, name=None, guid=None):
    for g, d in _all_definitions(dfile):
        if guid and str(d.GUID).lower() == guid.lower():
            return g, d
    if name:
        for g, d in _all_definitions(dfile):
            if normalize_string(d.Name) == name:
                return g, d
    return None, None


def _project_shared_guids(doc):
    out = {}
    for spe in DB.FilteredElementCollector(doc).OfClass(DB.SharedParameterElement):
        try:
            out[str(spe.GuidValue).lower()] = normalize_string(spe.GetDefinition().Name)
        except Exception:
            continue
    return out


def _read_file(ctx):
    path = ctx.get("shared_parameter_file") or ctx.app.SharedParametersFilename
    if not path:
        raise RvtssError("No shared parameter file configured", status=404,
                         hint="Pass shared_parameter_file or set one in Manage > Shared Parameters.")
    if not os.path.isfile(path):
        raise RvtssError("Shared parameter file not found: {}".format(path), status=404)
    parsed = SP.parse_file(path)
    in_project = {}
    if ctx.doc is not None and not ctx.doc.IsFamilyDocument:
        in_project = _project_shared_guids(ctx.doc)
    contains = (ctx.get("contains") or "").lower()
    params = []
    for p in parsed["params"]:
        if contains and contains not in p["name"].lower():
            continue
        q = dict((k, p[k]) for k in ("name", "guid", "datatype", "group", "description", "visible"))
        if in_project:
            q["in_project"] = p["guid"].lower() in in_project
        params.append(q)
    for guid, pname in in_project.items():
        for p in parsed["params"]:
            if p["guid"].lower() == guid and p["name"] != pname:
                parsed["issues"].append({"issue": "GUID {} is '{}' in the file but '{}' in the project".format(
                    guid, p["name"], pname), "severity": "warning"})
    return {"path": path, "is_current_file": path == ctx.app.SharedParametersFilename,
            "groups": sorted(set(parsed["groups"].values())), "count": len(params), "parameters": params,
            "issues": parsed["issues"]}


def _create_definitions(ctx):
    defs = ctx.list("definitions")
    if not defs:
        raise RvtssError("'definitions' is required: [{name, type, group?, guid?, description?}]")
    dry = ctx.dry_run
    results = []
    with _SharedFile(ctx.app, ctx.get("shared_parameter_file"), ctx.bool("create_file", False)) as dfile:
        existing_guids = dict((str(d.GUID).lower(), normalize_string(d.Name)) for _g, d in _all_definitions(dfile))
        for item in defs:
            name = item.get("name")
            if not name:
                raise RvtssError("Each definition needs a name")
            _g, found = _find_definition(dfile, name=name)
            guid = (item.get("guid") or "").strip()
            if found is not None:
                results.append({"name": name, "action": "exists", "guid": str(found.GUID),
                                "note": "Existing definition reused; its GUID was not changed."})
                if guid and guid.lower() != str(found.GUID).lower():
                    results[-1]["warning"] = "Requested GUID {} differs from the existing one".format(guid)
                continue
            if guid:
                if not SP.is_guid(guid):
                    raise RvtssError("Invalid GUID '{}'".format(guid))
                if guid.lower() in existing_guids:
                    raise RvtssError("GUID {} is already used by '{}'".format(guid, existing_guids[guid.lower()]),
                                     status=409, hint="A GUID identifies one parameter; never reuse it for another name.")
            if dry:
                results.append({"name": name, "action": "would_create", "guid": guid or "(new)"})
                continue
            group_name = item.get("group") or "RVTSS"
            group = dfile.Groups.get_Item(group_name) or dfile.Groups.Create(group_name)
            opts = external_definition_options(name, item.get("type", "text"))
            if guid:
                opts.GUID = System.Guid(guid)
            if item.get("description"):
                opts.Description = item["description"]
            opts.Visible = bool(item.get("visible", True))
            opts.UserModifiable = bool(item.get("user_modifiable", True))
            if "hide_when_no_value" in item:
                try:
                    opts.HideWhenNoValue = bool(item["hide_when_no_value"])
                except Exception:
                    pass
            d = group.Definitions.Create(opts)
            existing_guids[str(d.GUID).lower()] = name
            results.append({"name": name, "action": "created", "guid": str(d.GUID), "group": group_name})
        path = ctx.app.SharedParametersFilename
    return {"status": "dry_run" if dry else "success", "file": path, "results": results}


def _resolve_categories(doc, names):
    cats = []
    for n in names:
        c = core.resolve_category(doc, n)
        if not c.AllowsBoundParameters:
            raise RvtssError("Category '{}' does not allow bound parameters".format(c.Name), status=409)
        cats.append(c)
    return cats


def _bind(ctx):
    doc = ctx.doc
    core.require_project(doc)
    name = ctx.get("name")
    guid = ctx.get("guid")
    if not name and not guid:
        raise RvtssError("Pass the shared parameter 'name' or 'guid'")
    cats = _resolve_categories(doc, ctx.list("categories"))
    if not cats:
        raise RvtssError("'categories' is required, e.g. ['Doors', 'Walls']")
    binding_kind = ctx.get("binding", "instance")
    group = ctx.get("group", "data")
    dry = ctx.dry_run
    with _SharedFile(ctx.app, ctx.get("shared_parameter_file")) as dfile:
        _g, definition = _find_definition(dfile, name=name, guid=guid)
        if definition is None:
            raise RvtssError("Shared parameter '{}' not found in {}".format(guid or name, ctx.app.SharedParametersFilename),
                             status=404, hint="Create it with action='create_definitions' first.")
        existing = None
        for d, b, entry in _bindings(doc):
            if entry["name"] == normalize_string(definition.Name):
                if not entry.get("shared") or entry.get("guid", "").lower() != str(definition.GUID).lower():
                    raise RvtssError("A different parameter named '{}' is already bound (guid {})".format(
                        entry["name"], entry.get("guid", "not shared")), status=409,
                        hint="Two parameters with the same name cause schedule/tag ambiguity. Rename or remove the "
                             "existing project parameter first (Revit UI).")
                existing = (d, b, entry)

        def run():
            app = doc.Application
            catset = app.Create.NewCategorySet()
            merged = []
            if existing is not None:
                for c in existing[1].Categories:
                    catset.Insert(c)
                    merged.append(normalize_string(c.Name))
                kind = "instance" if isinstance(existing[1], DB.InstanceBinding) else "type"
                if kind != binding_kind:
                    raise RvtssError("'{}' is already bound as a {} parameter".format(definition.Name, kind), status=409,
                                     hint="Changing instance/type binding would delete existing values; do it in Revit.")
            for c in cats:
                catset.Insert(c)
            binding = app.Create.NewInstanceBinding(catset) if binding_kind == "instance" \
                else app.Create.NewTypeBinding(catset)
            if existing is not None:
                ok = reinsert_binding(doc, definition, binding, group)
                action = "categories_extended"
            else:
                ok = insert_binding(doc, definition, binding, group)
                action = "bound"
            if not ok:
                raise RvtssError("Revit refused the binding", status=409)
            if ctx.get("vary_between_groups") is not None and binding_kind == "instance":
                for d, _b, entry in _bindings(doc):
                    if entry["name"] == normalize_string(definition.Name) and isinstance(d, DB.InternalDefinition):
                        d.SetAllowVaryBetweenGroups(doc, bool(ctx.get("vary_between_groups")))
            return {"name": normalize_string(definition.Name), "guid": str(definition.GUID), "action": action,
                    "binding": binding_kind, "categories": sorted(set(merged + [normalize_string(c.Name) for c in cats]))}

        res, fails = core.run_transaction(doc, "Bind shared parameter", run, dry_run=dry)
    return core.commit_result(res, fails, dry)


def shared_parameters(ctx):
    action = ctx.require("action")
    if action == "read_file":
        return _read_file(ctx)
    if action == "create_definitions":
        return _create_definitions(ctx)
    if action == "create_file":
        path = ctx.require("shared_parameter_file")
        if os.path.exists(path):
            raise RvtssError("File exists: {}".format(path), status=409)
        with _SharedFile(ctx.app, path, create=True):
            pass
        if ctx.bool("set_as_current", False):
            ctx.app.SharedParametersFilename = path
        return {"created": path, "is_current_file": ctx.app.SharedParametersFilename == path}
    if action == "bind":
        return _bind(ctx)
    raise RvtssError("action must be read_file, create_definitions, create_file or bind")


# -------------------------------------------------------------------- global
def _gp_value(gp, unit):
    v = gp.GetValue()
    spec, kind = definition_spec(gp.GetDefinition())
    if isinstance(v, DB.DoubleParameterValue):
        if kind in ("length", "area", "volume"):
            return U.from_internal(v.Value, U.length_unit_for(kind, unit), 6)
        if kind == "angle":
            return U.from_internal(v.Value, "deg", 6)
        return v.Value
    if isinstance(v, DB.IntegerParameterValue):
        return v.Value
    if isinstance(v, DB.StringParameterValue):
        return v.Value
    if isinstance(v, DB.ElementIdParameterValue):
        return id_int(v.Value)
    return None


def _find_gp(doc, name):
    gid = DB.GlobalParametersManager.FindByName(doc, name)
    if not is_valid_id(gid):
        names = [normalize_string(doc.GetElement(i).Name) for i in DB.GlobalParametersManager.GetAllGlobalParameters(doc)]
        raise core.not_found("Global parameter", name, names)
    return doc.GetElement(gid)


def global_parameters(ctx):
    doc = ctx.doc
    if not DB.GlobalParametersManager.AreGlobalParametersAllowed(doc):
        raise RvtssError("Global parameters are not available in this document", status=409)
    action = ctx.get("action", "list")
    unit = ctx.unit
    dry = ctx.dry_run
    if action == "list":
        out = []
        for gid in DB.GlobalParametersManager.GetAllGlobalParameters(doc):
            gp = doc.GetElement(gid)
            spec, _k = definition_spec(gp.GetDefinition())
            d = {"id": id_int(gp), "name": normalize_string(gp.Name), "spec": spec, "value": _gp_value(gp, unit),
                 "formula": gp.GetFormula() or None, "reporting": gp.IsReporting}
            try:
                d["affected_elements"] = gp.GetAffectedElements().Count
            except Exception:
                pass
            out.append(d)
        return {"unit": unit, "global_parameters": sorted(out, key=lambda d: d["name"].lower())}

    def set_val(gp, value, vunit):
        spec, kind = definition_spec(gp.GetDefinition())
        if kind in ("length", "area", "volume", "angle"):
            if vunit is None and not isinstance(value, (text_type, str)):
                raise RvtssError("Global parameter '{}' is {}: pass value_unit".format(gp.Name, spec))
            gp.SetValue(DB.DoubleParameterValue(U.to_internal(float(value), vunit)))
        elif spec in ("integer", "yesno"):
            gp.SetValue(DB.IntegerParameterValue(int(bool(value)) if spec == "yesno" else int(value)))
        elif spec in ("text", "multiline_text", "url"):
            gp.SetValue(DB.StringParameterValue(text_type(value)))
        elif spec == "material":
            gp.SetValue(DB.ElementIdParameterValue(make_id(int(value))))
        else:
            gp.SetValue(DB.DoubleParameterValue(float(value)))

    def run():
        if action == "create":
            name = ctx.require("name")
            if not DB.GlobalParameter.IsValidName(doc, name):
                raise RvtssError("'{}' is not a valid/unique global parameter name".format(name), status=409)
            gp = DB.GlobalParameter.Create(doc, name, spec_id(ctx.get("type", "length")))
            if ctx.data.get("value") is not None:
                set_val(gp, ctx.data["value"], ctx.get("value_unit"))
            if ctx.get("formula"):
                gp.SetFormula(ctx.get("formula"))
            return {"id": id_int(gp), "name": name, "action": "created"}
        gp = _find_gp(doc, ctx.require("name"))
        if action == "set_value":
            set_val(gp, ctx.data.get("value"), ctx.get("value_unit"))
            return {"name": gp.Name, "action": "value_set", "value": _gp_value(gp, unit)}
        if action == "set_formula":
            gp.SetFormula(ctx.get("formula") or "")
            return {"name": gp.Name, "action": "formula_set", "formula": ctx.get("formula")}
        if action in ("associate", "dissociate"):
            pname = ctx.require("parameter")
            done = []
            for e in core.get_elements(doc, ctx.list("element_ids")):
                p, _o = find_param(doc, e, pname, allow_type=False)
                if p is None:
                    raise RvtssError("Element {} has no parameter '{}'".format(id_int(e), pname), status=404)
                if action == "associate":
                    if not p.CanBeAssociatedWithGlobalParameter(gp.Id):
                        raise RvtssError("'{}' on element {} cannot be associated with '{}' (type mismatch or "
                                         "not supported)".format(pname, id_int(e), gp.Name), status=409)
                    p.AssociateWithGlobalParameter(gp.Id)
                else:
                    p.DissociateFromGlobalParameter()
                done.append(id_int(e))
            return {"name": gp.Name, "action": action, "element_ids": done}
        raise RvtssError("action must be list, create, set_value, set_formula, associate or dissociate")

    res, fails = core.run_transaction(doc, "Global parameters: " + action, run, dry_run=dry)
    return core.commit_result(res, fails, dry)


# --------------------------------------------------------------------- audit
def audit(ctx):
    doc = ctx.doc
    spec = query_spec(ctx.data)
    if not spec:
        raise RvtssError("Select elements to audit (categories, element_ids, view, level, ...)")
    elements = collect(ctx, spec)
    required = ctx.list("required")
    rules = ctx.list("rules")
    expected_types = ctx.get("expected_types") or {}
    allow_type = ctx.bool("include_type_parameters", True)
    findings = []
    stats = {}
    for name in required + [r["name"] for r in rules if r.get("name") not in required]:
        stats[name] = {"missing": [], "empty": [], "invalid": [], "wrong_type": []}
    for r in rules:
        try:
            F.validate_filter(r)
        except F.FilterError as e:
            raise RvtssError("Invalid rule: {}".format(e))
    for e in elements:
        eid = id_int(e)
        for name in stats:
            p, _o = find_param(doc, e, name, allow_type=allow_type)
            if p is None:
                stats[name]["missing"].append(eid)
                continue
            if name in expected_types:
                s, _k = definition_spec(p.Definition)
                if s != expected_types[name]:
                    stats[name]["wrong_type"].append(eid)
            if name in required and ctx.bool("check_empty", True):
                r = read_param(doc, p, "mm")
                if r.get("value") in (None, "") and not r.get("display"):
                    stats[name]["empty"].append(eid)
        for r in rules:
            p, _o = find_param(doc, e, r["name"], allow_type=allow_type)
            if p is None:
                continue
            raw = raw_value(p, r.get("unit") or "mm")
            disp = p.AsValueString()
            if not F.match(r.get("op", "eq"), r.get("value"), raw, disp, True, bool(r.get("case_sensitive"))):
                stats[r["name"]]["invalid"].append(eid)
    for name, s in stats.items():
        sev_rule = [r.get("severity") for r in rules if r["name"] == name]
        if s["missing"]:
            findings.append(R.finding("missing_parameter", "error", "'{}' does not exist on {} element(s)".format(
                name, len(s["missing"])), s["missing"], parameter=name,
                recommendation="Bind it with shared_parameters(action='bind') or add it to the families."))
        if s["empty"]:
            findings.append(R.finding("empty_value", "warning", "'{}' is empty on {} element(s)".format(
                name, len(s["empty"])), s["empty"], parameter=name,
                recommendation="Fill it with bulk_update_parameter or set_parameters."))
        if s["invalid"]:
            findings.append(R.finding("invalid_value", (sev_rule[0] if sev_rule and sev_rule[0] else "warning"),
                                      "'{}' fails the rule on {} element(s)".format(name, len(s["invalid"])),
                                      s["invalid"], parameter=name))
        if s["wrong_type"]:
            findings.append(R.finding("wrong_data_type", "error", "'{}' is not of type {} on {} element(s)".format(
                name, expected_types.get(name), len(s["wrong_type"])), s["wrong_type"], parameter=name,
                recommendation="A same-named parameter with another data type exists; map values to the correct one."))
    if not doc.IsFamilyDocument and ctx.bool("check_definitions", True):
        names = {}
        for _d, _b, entry in _bindings(doc):
            names.setdefault(entry["name"].lower(), []).append(entry)
        for k, v in names.items():
            if len(v) > 1:
                findings.append(R.finding("duplicate_definition", "error",
                                          "Project parameter name '{}' is defined {} times".format(v[0]["name"], len(v)),
                                          recommendation="Keep one definition; map values from the duplicate, then remove it.",
                                          definitions=v))
        pattern = ctx.get("naming_pattern")
        if pattern:
            findings.extend(R.check_names([(e.get("id"), e["name"]) for _d, _b, e in _bindings(doc)],
                                          {"pattern": pattern}, "parameter_naming", "project parameters"))
    findings = R.sort_findings(findings)
    return {"elements_checked": len(elements), "summary": R.summarize(findings), "findings": findings,
            "per_parameter": dict((n, dict((k, len(v)) for k, v in s.items())) for n, s in stats.items())}


# ------------------------------------------------------------- export/import
def export_values(ctx):
    doc = ctx.doc
    spec = query_spec(ctx.data)
    if not spec:
        raise RvtssError("Select elements to export (categories, element_ids, view, ...)")
    elements = collect(ctx, spec)
    names = ctx.list("parameters")
    if not names:
        raise RvtssError("'parameters' (names to export) is required")
    mode = ctx.get("value_mode", "display")
    unit = ctx.unit
    header = ["ElementId", "UniqueId", "Category", "Family", "Type"] + names
    rows = []
    for e in elements:
        b = core.element_brief(doc, e)
        row = [id_int(e), e.UniqueId, b.get("category"), b.get("family"), b.get("type")]
        for n in names:
            p, _o = find_param(doc, e, n)
            if p is None:
                row.append(None)
                continue
            r = read_param(doc, p, unit)
            row.append(r.get("display", r.get("value")) if mode == "display" else r.get("value"))
        rows.append(row)
    text = csvutil.to_csv(header, rows)
    path = ctx.get("path")
    if path:
        if not path.lower().endswith(".csv"):
            raise RvtssError("path must end with .csv")
        if os.path.exists(path) and not ctx.bool("overwrite", False):
            raise RvtssError("File exists: {}".format(path), status=409, hint="Pass overwrite=true.")
        csvutil.write_file(path, text)
    out = {"rows": len(rows), "columns": header, "path": path, "value_mode": mode, "unit": unit}
    if not path:
        if len(text) > 200000:
            raise RvtssError("Export is too large to return inline ({} rows)".format(len(rows)),
                             hint="Pass path='C:/.../export.csv' to write a file.")
        out["csv"] = text
    return out


def import_values(ctx):
    doc = ctx.doc
    text = ctx.get("csv_text")
    path = ctx.get("path")
    if not text:
        if not path or not os.path.isfile(path):
            raise RvtssError("Pass csv_text or an existing path")
        text = csvutil.read_file(path)
    header, rows = csvutil.parse_csv(text)
    if "ElementId" not in header and "UniqueId" not in header:
        raise RvtssError("CSV needs an ElementId or UniqueId column")
    skip = set(["ElementId", "UniqueId", "Category", "Family", "Type"])
    columns = [h for h in header if h not in skip and h not in ctx.list("ignore_columns")]
    units = ctx.get("units") or {}
    preview = core.confirm_gate(ctx, len(rows), "import_parameter_values")
    skip_empty = ctx.bool("skip_empty", True)

    def one(row):
        e = None
        if row.get("UniqueId"):
            e = doc.GetElement(row["UniqueId"])
        if e is None and row.get("ElementId"):
            e = core.get_element(doc, int(row["ElementId"]))
        if e is None:
            raise RvtssError("Row element not found: {}".format(row.get("ElementId") or row.get("UniqueId")), status=404)
        changed = []
        for col in columns:
            val = row.get(col)
            if skip_empty and (val is None or val == ""):
                continue
            p, _o = find_param(doc, e, col, allow_type=ctx.bool("allow_type", False))
            if p is None:
                raise RvtssError("Element {} has no parameter '{}'".format(id_int(e), col), status=404)
            if p.IsReadOnly:
                continue
            before = read_param(doc, p, "mm")
            before_v = before.get("display", before.get("value"))
            if text_type(before_v) == val:
                continue
            u = units.get(col)
            after = set_value(doc, p, float(val) if u else val, u)
            changed.append({"parameter": col, "before": before_v, "after": after.get("display", after.get("value"))})
        return {"element_id": id_int(e), "changes": changed}

    dry = preview or ctx.dry_run
    res, fails = core.run_transaction(doc, "Import parameter values",
                                      lambda: core.batch(doc, rows, one, ctx.bool("atomic", False)), dry_run=dry)
    changed = [r for r in res if r.get("changes")]
    out = core.commit_result({"rows": len(rows), "rows_changed": len(changed),
                              "failed": [r for r in res if not r["ok"]][:100],
                              "changes": changed[:ctx.int("max_results", 100)]}, fails, dry)
    return core.preview_status(out, preview)


def map_values(ctx):
    doc = ctx.doc
    spec = query_spec(ctx.data)
    if not spec:
        raise RvtssError("Select elements (categories, element_ids, ...)")
    mappings = ctx.list("mappings")
    if not mappings:
        raise RvtssError("'mappings' is required: [{from: 'Old Name', to: 'New Name'}]")
    elements = collect(ctx, spec)
    preview = core.confirm_gate(ctx, len(elements), "map_parameters")
    only_empty = ctx.bool("only_empty_target", False)

    def one(e):
        changes, skipped = [], []
        for m in mappings:
            src, _o = find_param(doc, e, m["from"])
            dst, _o2 = find_param(doc, e, m["to"], allow_type=ctx.bool("allow_type", False))
            if src is None or dst is None:
                skipped.append({"mapping": m, "reason": "source missing" if src is None else "target missing"})
                continue
            if dst.IsReadOnly:
                skipped.append({"mapping": m, "reason": "target read-only"})
                continue
            cur = read_param(doc, dst, "mm")
            if only_empty and cur.get("value") not in (None, "", 0):
                skipped.append({"mapping": m, "reason": "target has a value"})
                continue
            if src.StorageType == dst.StorageType:
                if src.StorageType == DB.StorageType.Double:
                    dst.Set(src.AsDouble())
                elif src.StorageType == DB.StorageType.Integer:
                    dst.Set(src.AsInteger())
                elif src.StorageType == DB.StorageType.String:
                    dst.Set(src.AsString() or "")
                else:
                    dst.Set(src.AsElementId())
            else:
                v = src.AsValueString() or src.AsString()
                set_value(doc, dst, v if v is not None else "", None)
            changes.append({"from": m["from"], "to": m["to"], "value": read_param(doc, dst, ctx.unit).get("display")
                            or read_param(doc, dst, ctx.unit).get("value")})
        return {"element_id": id_int(e), "changes": changes, "skipped": skipped}

    dry = preview or ctx.dry_run
    res, fails = core.run_transaction(doc, "Map parameters", lambda: core.batch(doc, elements, one, ctx.bool("atomic", False)),
                                      dry_run=dry)
    out = core.commit_result({"elements": len(elements),
                              "changed": len([r for r in res if r.get("changes")]),
                              "results": res[:ctx.int("max_results", 100)]}, fails, dry)
    return core.preview_status(out, preview)


def register_parameter_routes(api):
    @api.route("/parameters/project/", methods=["POST"])
    def parameters_project_route(doc, request):
        return handle(doc, request, project_parameters)

    @api.route("/parameters/shared/", methods=["POST"])
    def parameters_shared_route(doc, request):
        return handle(doc, request, shared_parameters, needs_doc=False)

    @api.route("/parameters/global/", methods=["POST"])
    def parameters_global_route(doc, request):
        return handle(doc, request, global_parameters)

    @api.route("/parameters/audit/", methods=["POST"])
    def parameters_audit_route(doc, uidoc, request):
        return handle(doc, request, audit, uidoc=uidoc)

    @api.route("/parameters/export/", methods=["POST"])
    def parameters_export_route(doc, uidoc, request):
        return handle(doc, request, export_values, uidoc=uidoc)

    @api.route("/parameters/import/", methods=["POST"])
    def parameters_import_route(doc, request):
        return handle(doc, request, import_values)

    @api.route("/parameters/map/", methods=["POST"])
    def parameters_map_route(doc, uidoc, request):
        return handle(doc, request, map_values, uidoc=uidoc)

    logger.info("RVTSS parameter routes registered")
