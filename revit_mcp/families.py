# -*- coding: UTF-8 -*-
"""Family document (.rfa) management, parameters, types and QC (RVTSS).

Family documents are opened in the background (not shown in the Revit UI) and
addressed by their title or path through the "document" field, so Claude can
edit several families while the project stays active.

Routes:
    POST /family/templates/          template folders, matching templates, missing kinds
    POST /family/create/             new family from a template (optionally saved)
    POST /family/open/               open an .rfa or edit a family loaded in a project
    POST /family/info/               category, parameters, formulas, types, planes, dims, forms, nested
    POST /family/properties/         category and family-level settings
    POST /family/parameters/         add / remove / rename / formulas / instance-type / reporting /
                                     replace_with_shared / associate
    POST /family/types/              list / create / duplicate / rename / delete / set_values /
                                     export_catalog / import_catalog
    POST /family/nested/             load + place nested families, associate parameters
    POST /family/validate/           quality control report
    POST /family/save/               save / save as with automatic backup
    POST /family/load_into_project/  load or reload into a project and verify
    POST /family/close/              close a background family document
"""
import os
import time
import shutil
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, add_family_parameter, add_shared_family_parameter
from .params_util import (family_parameter, require_family_parameter, set_family_value, family_type_value,
                          lookup as lookup_param)
from .family_utils import (family_param_info, labeled_dimensions, describe_ref_plane, reference_planes,
                           forms, describe_form, describe_dimension, ensure_current_type, find_family_type,
                           family_name, ref_level, is_builtin, is_relevant)
from .pure import templates as T
from .pure import formula as FORMULA
from .pure import catalog as CATALOG
from .pure import units as U
from .pure import rules as R
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- templates
def _template_dirs(ctx):
    dirs = []
    try:
        if ctx.app.FamilyTemplatePath:
            dirs.append(ctx.app.FamilyTemplatePath)
    except Exception:
        pass
    cfg = core.load_config()
    dirs.extend(cfg.get("family_template_dirs", []))
    dirs.extend(ctx.list("search_dirs"))
    out = []
    for d in dirs:
        if d and d not in out:
            out.append(d)
    return out


def family_templates(ctx):
    dirs = _template_dirs(ctx)
    files = T.find_template_files(dirs)
    kind = ctx.get("kind")
    unit_system = ctx.get("unit_system")
    result = {"template_dirs": [{"path": d, "exists": os.path.isdir(d)} for d in dirs],
              "template_count": len(files), "kinds": sorted(T.TEMPLATE_KINDS)}
    if kind:
        if kind not in T.TEMPLATE_KINDS:
            raise RvtssError("Unknown template kind '{}'".format(kind), hint="Use one of: " + ", ".join(sorted(T.TEMPLATE_KINDS)))
        matches = T.match(files, kind, unit_system)
        result["kind"] = kind
        result["matches"] = matches[:15]
        if not matches:
            result["missing"] = True
            result["hint"] = ("No template for '{}' found. Install the Revit family templates for your language "
                              "or pass search_dirs / template_path.".format(kind))
    else:
        coverage = {}
        for k in sorted(T.TEMPLATE_KINDS):
            m = T.match(files, k, unit_system)
            coverage[k] = os.path.basename(m[0]) if m else None
        result["best_template_per_kind"] = coverage
        result["missing_kinds"] = [k for k, v in coverage.items() if v is None]
        contains = (ctx.get("contains") or "").lower()
        listing = [f for f in files if contains in os.path.basename(f).lower()] if contains else []
        if contains:
            result["files"] = listing[:200]
    if not files:
        result["hint"] = ("No .rft files found. Check Revit Options > File Locations > Family Template Files, "
                          "or pass search_dirs.")
    return result


# ------------------------------------------------------------- open / create
def _find_open_by_path(ctx, path):
    target = os.path.normcase(os.path.abspath(path))
    for d in ctx.app.Documents:
        if d.PathName and os.path.normcase(os.path.abspath(d.PathName)) == target:
            return d
    return None


def _family_summary(doc):
    fm = doc.FamilyManager
    cat = doc.OwnerFamily.FamilyCategory
    return {"document": normalize_string(doc.Title), "path": doc.PathName or None,
            "family_name": family_name(doc), "category": normalize_string(cat.Name) if cat else None,
            "parameter_count": fm.Parameters.Size, "type_count": fm.Types.Size,
            "types": [normalize_string(t.Name) for t in fm.Types]}


def family_create(ctx):
    template = ctx.get("template_path")
    if not template:
        kind = ctx.require("kind", "template kind, e.g. 'door', 'furniture', 'generic_model'")
        matches = T.match(T.find_template_files(_template_dirs(ctx)), kind, ctx.get("unit_system", "metric"))
        if not matches:
            raise RvtssError("No family template found for kind '{}'".format(kind), status=404,
                             hint="Run family_list_templates to see available templates, or pass template_path.")
        template = matches[0]
    if not os.path.isfile(template):
        raise RvtssError("Template not found: {}".format(template), status=404)
    save_path = ctx.get("save_path")
    if save_path:
        if not save_path.lower().endswith(".rfa"):
            raise RvtssError("save_path must end with .rfa")
        folder = os.path.dirname(save_path)
        if folder and not os.path.isdir(folder):
            if ctx.bool("create_folder", True):
                os.makedirs(folder)
            else:
                raise RvtssError("Folder does not exist: {}".format(folder), status=404)
        if os.path.exists(save_path) and not ctx.bool("overwrite", False):
            raise RvtssError("File already exists: {}".format(save_path), status=409,
                             hint="Use family_open to edit the existing family, or pass overwrite=true "
                                  "(a backup copy is made first).")
    famdoc = ctx.app.NewFamilyDocument(template)
    if famdoc is None:
        raise RvtssError("Revit could not create a family from {}".format(template), status=500)
    fm = famdoc.FamilyManager
    category = ctx.get("category")
    type_name = ctx.get("type_name")

    def setup():
        if category:
            famdoc.OwnerFamily.FamilyCategory = core.resolve_category(famdoc, category)
        if type_name or fm.CurrentType is None:
            fm.NewType(type_name or "Default")
        return None

    _r, fails = core.run_transaction(famdoc, "Set up new family", setup)
    backup = None
    if save_path:
        if os.path.exists(save_path):
            backup = _backup(save_path)
        opts = DB.SaveAsOptions()
        opts.OverwriteExistingFile = True
        famdoc.SaveAs(save_path, opts)
    out = _family_summary(famdoc)
    out.update({"template": template, "saved": bool(save_path), "backup": backup, "revit_warnings": fails,
                "next_steps": "Pass document='{}' to family_* tools. Add parameters, geometry, types, then "
                              "family_flex_test, family_validate, family_save.".format(normalize_string(famdoc.Title))})
    if not save_path:
        out["note"] = "Family is not saved yet. Use family_save with save_path before loading or closing."
    return out


def family_open(ctx):
    path = ctx.get("path")
    name = ctx.get("family_name")
    if path:
        if not os.path.isfile(path):
            raise RvtssError("File not found: {}".format(path), status=404)
        existing = _find_open_by_path(ctx, path)
        if existing is not None:
            out = _family_summary(existing)
            out["already_open"] = True
            return out
        famdoc = ctx.app.OpenDocumentFile(path)
        if not famdoc.IsFamilyDocument:
            raise RvtssError("{} is not a family file".format(path))
        out = _family_summary(famdoc)
        out["opened_from"] = "file"
        return out
    if name:
        doc = ctx.doc
        core.require_project(doc)
        fam = None
        for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
            if normalize_string(f.Name).lower() == name.lower():
                fam = f
                break
        if fam is None:
            raise core.not_found("Loaded family", name, [f.Name for f in DB.FilteredElementCollector(doc).OfClass(DB.Family)])
        if fam.IsInPlace or not fam.IsEditable:
            raise RvtssError("Family '{}' is {} and cannot be opened for editing".format(
                name, "in-place" if fam.IsInPlace else "not editable"), status=409)
        famdoc = doc.EditFamily(fam)
        out = _family_summary(famdoc)
        out.update({"opened_from": "project", "project": normalize_string(doc.Title),
                    "note": "This is an unsaved in-memory copy. Use family_load_into_project to push changes "
                            "back, and/or family_save with save_path to keep an .rfa file."})
        return out
    raise RvtssError("Pass 'path' to an .rfa file or 'family_name' of a family loaded in the project")


# ------------------------------------------------------------------------ info
def family_info(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    unit = ctx.unit
    include = set(ctx.list("include") or ["parameters", "types", "reference_planes", "dimensions", "forms",
                                           "nested", "properties"])
    labels = labeled_dimensions(doc)
    out = _family_summary(doc)
    out["unit"] = unit
    if "properties" in include:
        fam = doc.OwnerFamily
        props = {}
        for bip, key in (("FAMILY_WORK_PLANE_BASED", "work_plane_based"), ("FAMILY_ALWAYS_VERTICAL", "always_vertical"),
                         ("FAMILY_SHARED", "shared"), ("FAMILY_ROOM_CALCULATION_POINT", "room_calculation_point"),
                         ("FAMILY_ALLOW_CUT_WITH_VOIDS", "cut_with_voids"), ("FAMILY_IS_PARAMETRIC", "parametric"),
                         ("FAMILY_HOSTING_BEHAVIOR", "hosting")):
            b = getattr(DB.BuiltInParameter, bip, None)
            if b is None:
                continue
            try:
                p = fam.get_Parameter(b)
                if p is not None:
                    props[key] = p.AsValueString() or p.AsInteger()
            except Exception:
                continue
        out["properties"] = props
        try:
            out["warnings"] = len(doc.GetWarnings())
        except Exception:
            pass
    if "parameters" in include:
        include_builtin = ctx.bool("include_builtin", False)
        params = [family_param_info(doc, fm, fp, unit, labels) for fp in fm.Parameters
                  if is_relevant(fp, include_builtin)]
        params.sort(key=lambda p: ("builtin" in p, p["name"].lower()))
        out["parameters"] = params
    if "types" in include:
        max_types = ctx.int("max_types", 50)
        names = [fp for fp in fm.Parameters if is_relevant(fp, ctx.bool("include_builtin", False))]
        types = []
        for t in list(fm.Types)[:max_types]:
            vals = {}
            for fp in names:
                try:
                    vals[normalize_string(fp.Definition.Name)] = family_type_value(fm, t, fp, unit)
                except Exception:
                    continue
            types.append({"name": normalize_string(t.Name), "values": vals})
        out["types"] = types
        out["current_type"] = normalize_string(fm.CurrentType.Name) if fm.CurrentType else None
    if "reference_planes" in include:
        out["reference_planes"] = [describe_ref_plane(rp, unit) for rp in reference_planes(doc)]
        lv = ref_level(doc)
        out["reference_level"] = normalize_string(lv.Name) if lv else None
    if "dimensions" in include:
        dims = [describe_dimension(d, unit) for d in DB.FilteredElementCollector(doc).OfClass(DB.Dimension)]
        out["dimensions"] = dims
    if "forms" in include:
        out["forms"] = [describe_form(doc, k, f, unit, fm) for k, f in forms(doc)]
    if "nested" in include:
        nested = []
        for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
            if f.Id == doc.OwnerFamily.Id:
                continue
            count = 0
            for sid in f.GetFamilySymbolIds():
                count += len([1 for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance)
                              if fi.Symbol.Id == sid])
            shared = None
            try:
                shared = f.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED).AsInteger() == 1
            except Exception:
                pass
            nested.append({"id": id_int(f), "name": normalize_string(f.Name),
                           "category": normalize_string(f.FamilyCategory.Name) if f.FamilyCategory else None,
                           "types": [normalize_string(get_element_name(doc.GetElement(s))) for s in f.GetFamilySymbolIds()],
                           "instances": count, "shared": shared})
        out["nested_families"] = nested
    return out


def family_properties(ctx):
    doc = ctx.doc
    core.require_family(doc)
    fam = doc.OwnerFamily
    changes = ctx.get("set") or {}
    category = ctx.get("category")
    if not changes and not category:
        raise RvtssError("Pass category and/or set: {work_plane_based, always_vertical, shared, "
                         "room_calculation_point, cut_with_voids}")
    mapping = {"work_plane_based": "FAMILY_WORK_PLANE_BASED", "always_vertical": "FAMILY_ALWAYS_VERTICAL",
               "shared": "FAMILY_SHARED", "room_calculation_point": "FAMILY_ROOM_CALCULATION_POINT",
               "cut_with_voids": "FAMILY_ALLOW_CUT_WITH_VOIDS"}
    dry = ctx.dry_run

    def run():
        done = {}
        if category:
            old = fam.FamilyCategory.Name if fam.FamilyCategory else None
            fam.FamilyCategory = core.resolve_category(doc, category)
            done["category"] = {"old": old, "new": fam.FamilyCategory.Name}
        for key, val in changes.items():
            bip = getattr(DB.BuiltInParameter, mapping.get(key, ""), None)
            if bip is None:
                raise RvtssError("Unknown property '{}'. Use: {}".format(key, ", ".join(sorted(mapping))))
            p = fam.get_Parameter(bip)
            if p is None or p.IsReadOnly:
                raise RvtssError("Property '{}' is not available for this family template".format(key), status=409)
            p.Set(1 if val else 0)
            done[key] = bool(val)
        return {"changed": done}

    res, fails = core.run_transaction(doc, "Family properties", run, dry_run=dry)
    return core.commit_result(res, fails, dry)


# ------------------------------------------------------------------ parameters
def _shared_definition(ctx, name, guid=None):
    app = ctx.app
    path = ctx.get("shared_parameter_file")
    previous = app.SharedParametersFilename
    try:
        if path:
            app.SharedParametersFilename = path
        dfile = app.OpenSharedParameterFile()
        if dfile is None:
            raise RvtssError("No shared parameter file is set in Revit", status=409,
                             hint="Pass shared_parameter_file, or create definitions with shared_parameters.")
        for g in dfile.Groups:
            for d in g.Definitions:
                if guid and str(d.GUID).lower() == guid.lower():
                    return d
                if not guid and normalize_string(d.Name) == name:
                    return d
        raise RvtssError("Shared parameter '{}' not found in {}".format(guid or name, app.SharedParametersFilename),
                         status=404, hint="Create it first with shared_parameters(action='create_definitions').")
    finally:
        if path and (previous or "") != path:
            app.SharedParametersFilename = previous or ""


def family_parameters(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    action = ctx.require("action")
    dry = ctx.dry_run
    items = ctx.list("parameters")
    if action == "list":
        labels = labeled_dimensions(doc)
        return {"parameters": [family_param_info(doc, fm, fp, ctx.unit, labels) for fp in fm.Parameters]}
    if not items:
        raise RvtssError("'parameters' list is required for action '{}'".format(action))
    atomic = ctx.bool("atomic", True)
    naming = ctx.get("naming_pattern")

    def add(item):
        name = item.get("name")
        if not name:
            raise RvtssError("Parameter needs a name")
        if naming:
            issues = R.check_names([(0, name)], {"pattern": naming}, "naming", "parameter")
            if issues:
                raise RvtssError("'{}' violates naming pattern {}".format(name, naming))
        existing = family_parameter(fm, name)
        if existing is not None:
            if item.get("if_exists", "skip") == "error":
                raise RvtssError("Parameter '{}' already exists".format(name), status=409)
            return {"name": name, "action": "exists", "id": id_int(existing.Id)}
        instance = bool(item.get("instance", False))
        ptype = item.get("type", "length")
        group = item.get("group") or ("dimensions" if ptype in ("length", "angle", "area", "volume")
                                      else "materials" if ptype == "material" else "data")
        if item.get("shared"):
            fp = add_shared_family_parameter(fm, _shared_definition(ctx, name, item.get("guid")), group, instance)
        else:
            fp = add_family_parameter(fm, name, ptype, group, instance)
        out = {"name": name, "action": "added", "id": id_int(fp.Id), "instance": instance}
        if item.get("value") is not None and not item.get("formula"):
            ensure_current_type(fm)
            set_family_value(doc, fm, fp, item["value"], item.get("unit"))
            out["value_set"] = True
        # formulas are applied in a second pass so they may reference
        # parameters added later in the same batch
        if item.get("reporting"):
            fm.MakeReporting(fp)
            out["reporting"] = True
        return out

    def remove(item):
        fp = require_family_parameter(fm, item.get("name"))
        if is_builtin(fp):
            raise RvtssError("Built-in parameter '{}' cannot be removed".format(item.get("name")), status=409)
        fm.RemoveParameter(fp)
        return {"name": item.get("name"), "action": "removed"}

    def rename(item):
        fp = require_family_parameter(fm, item.get("name"))
        if fp.IsShared:
            raise RvtssError("Shared parameter '{}' cannot be renamed (its name belongs to the GUID)".format(
                item.get("name")), status=409, hint="Use replace_with_shared to swap it for another shared definition.")
        fm.RenameParameter(fp, item["new_name"])
        return {"name": item["new_name"], "old_name": item.get("name"), "action": "renamed"}

    def formula(item):
        fp = require_family_parameter(fm, item.get("name"))
        f = item.get("formula")
        if f:
            if not fp.CanAssignFormula:
                raise RvtssError("A formula cannot be assigned to '{}' (e.g. instance-driven by type, reporting)"
                                 .format(item.get("name")), status=409)
            fm.SetFormula(fp, f)
        else:
            fm.SetFormula(fp, None)
        return {"name": item.get("name"), "action": "formula_set" if f else "formula_cleared", "formula": f or None}

    def instance_type(item):
        fp = require_family_parameter(fm, item.get("name"))
        if item.get("instance"):
            fm.MakeInstance(fp)
        else:
            fm.MakeType(fp)
        return {"name": item.get("name"), "action": "made_instance" if item.get("instance") else "made_type"}

    def reporting(item):
        fp = require_family_parameter(fm, item.get("name"))
        if item.get("reporting", True):
            fm.MakeReporting(fp)
        else:
            fm.MakeNonReporting(fp)
        return {"name": item.get("name"), "action": "reporting" if item.get("reporting", True) else "non_reporting"}

    def replace_shared(item):
        fp = require_family_parameter(fm, item.get("name"))
        ext = _shared_definition(ctx, item.get("shared_name") or item.get("name"), item.get("guid"))
        from .compat import group_id

        new = fm.ReplaceParameter(fp, ext, group_id(item.get("group", "data")),
                                  bool(item.get("instance", fp.IsInstance)))
        return {"name": normalize_string(new.Definition.Name), "action": "replaced_with_shared",
                "guid": str(new.GUID)}

    def associate(item):
        e = core.get_element(doc, item.get("element_id"))
        ep = lookup_param(e, item.get("element_parameter"))
        if ep is None:
            raise RvtssError("Element {} has no parameter '{}'".format(item.get("element_id"),
                                                                          item.get("element_parameter")), status=404)
        fp = require_family_parameter(fm, item.get("name")) if item.get("name") else None
        if fp is not None and not fm.CanElementParameterBeAssociated(ep):
            raise RvtssError("Parameter '{}' of element {} cannot be associated".format(
                item.get("element_parameter"), item.get("element_id")), status=409)
        fm.AssociateElementParameterToFamilyParameter(ep, fp)
        return {"element_id": item.get("element_id"), "element_parameter": item.get("element_parameter"),
                "family_parameter": item.get("name"), "action": "associated" if fp else "dissociated"}

    def set_values(item):
        ensure_current_type(fm)
        fp = require_family_parameter(fm, item.get("name"))
        set_family_value(doc, fm, fp, item.get("value"), item.get("unit"))
        return {"name": item.get("name"), "action": "value_set",
                "value": family_type_value(fm, fm.CurrentType, fp, ctx.unit)}

    handlers = {"add": add, "remove": remove, "rename": rename, "set_formula": formula,
                "set_instance": instance_type, "set_reporting": reporting,
                "replace_with_shared": replace_shared, "associate": associate, "set_values": set_values}
    fn = handlers.get(action)
    if fn is None:
        raise RvtssError("action must be one of: list, " + ", ".join(sorted(handlers)))

    if action in ("add", "set_formula"):
        # formula static pre-check across the whole family
        known = [normalize_string(fp.Definition.Name) for fp in fm.Parameters] + [i.get("name") for i in items]
        formulas = dict((normalize_string(fp.Definition.Name), fp.Formula) for fp in fm.Parameters if fp.Formula)
        for i in items:
            if i.get("formula"):
                formulas[i["name"]] = i["formula"]
        pre = [x for x in FORMULA.analyse(formulas, known) if x["severity"] == "error"]
        if pre:
            raise RvtssError("Formula pre-check failed: " + "; ".join(x["issue"] for x in pre[:5]), issues=pre,
                             hint="Nothing was changed. Fix the formulas and retry.")

    def run():
        res = core.batch(doc, items, fn, atomic)
        if action == "add":
            for r, item in zip(res, items):
                if not r.get("ok") or not item.get("formula") or r.get("action") == "exists":
                    continue
                fp = require_family_parameter(fm, item["name"])
                try:
                    fm.SetFormula(fp, item["formula"])
                    r["formula"] = item["formula"]
                except Exception as e:
                    if atomic:
                        raise RvtssError("Formula for '{}' rejected by Revit: {}".format(
                            item["name"], normalize_string(text_type(e))),
                            hint="Nothing was changed. Check parameter names, units and result type.")
                    r.update({"ok": False, "error": "formula rejected: " + normalize_string(text_type(e))})
        doc.Regenerate()
        return res

    results, fails = core.run_transaction(doc, "Family parameters: " + action, run, dry_run=dry)
    return core.commit_result({"action": action, "results": results}, fails, dry)


# ----------------------------------------------------------------------- types
def _apply_type_values(doc, fm, values, unit):
    applied, errors = [], []
    for pname, val in (values or {}).items():
        fp = family_parameter(fm, pname)
        if fp is None:
            errors.append({"parameter": pname, "error": "not found"})
            continue
        v, u = (val.get("value"), val.get("unit", unit)) if isinstance(val, dict) else (val, unit)
        try:
            set_family_value(doc, fm, fp, v, u)
            applied.append(pname)
        except RvtssError as e:
            errors.append({"parameter": pname, "error": e.message})
        except Exception as e:
            errors.append({"parameter": pname, "error": normalize_string(text_type(e))})
    return applied, errors


def family_types(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    action = ctx.get("action", "list")
    unit = ctx.unit
    dry = ctx.dry_run
    if action == "list":
        names = [fp for fp in fm.Parameters if is_relevant(fp, ctx.bool("include_builtin", False))]
        only = set(ctx.list("parameters"))
        types = []
        for t in fm.Types:
            vals = {}
            for fp in names:
                n = normalize_string(fp.Definition.Name)
                if only and n not in only:
                    continue
                vals[n] = family_type_value(fm, t, fp, unit)
            types.append({"name": normalize_string(t.Name), "values": vals})
        return {"unit": unit, "current_type": normalize_string(fm.CurrentType.Name) if fm.CurrentType else None,
                "types": types}
    if action == "export_catalog":
        return _export_catalog(ctx, doc, fm)
    items = ctx.list("types")
    if action == "import_catalog":
        items = _catalog_items(ctx)
        action = "upsert"
    if not items:
        raise RvtssError("'types' list is required, e.g. [{name: 'W900', values: {Width: 900}}]")
    strict = ctx.bool("strict", True)

    def run():
        results = []
        for it in items:
            name = it.get("name")
            if action in ("create", "upsert"):
                exists = None
                for t in fm.Types:
                    if normalize_string(t.Name) == name:
                        exists = t
                if exists is not None and action == "create":
                    raise RvtssError("Type '{}' already exists".format(name), status=409,
                                     hint="Use action='set_values' or 'upsert'.")
                if exists is not None:
                    fm.CurrentType = exists
                else:
                    if it.get("based_on"):
                        fm.CurrentType = find_family_type(fm, it["based_on"])
                    fm.NewType(name)
                applied, errors = _apply_type_values(doc, fm, it.get("values"), it.get("unit", unit))
                results.append({"name": name, "action": "updated" if exists is not None else "created",
                                "values_set": applied, "errors": errors})
            elif action == "duplicate":
                fm.CurrentType = find_family_type(fm, it.get("source") or name)
                fm.NewType(it["new_name"])
                applied, errors = _apply_type_values(doc, fm, it.get("values"), it.get("unit", unit))
                results.append({"name": it["new_name"], "action": "duplicated", "source": it.get("source") or name,
                                "values_set": applied, "errors": errors})
            elif action == "rename":
                fm.CurrentType = find_family_type(fm, name)
                fm.RenameCurrentType(it["new_name"])
                results.append({"name": it["new_name"], "old_name": name, "action": "renamed"})
            elif action == "delete":
                if fm.Types.Size <= 1:
                    raise RvtssError("Cannot delete the last family type", status=409)
                fm.CurrentType = find_family_type(fm, name)
                fm.DeleteCurrentType()
                results.append({"name": name, "action": "deleted"})
            elif action == "set_values":
                fm.CurrentType = find_family_type(fm, name)
                applied, errors = _apply_type_values(doc, fm, it.get("values"), it.get("unit", unit))
                results.append({"name": name, "action": "values_set", "values_set": applied, "errors": errors})
            else:
                raise RvtssError("action must be list, create, upsert, duplicate, rename, delete, set_values, "
                                 "export_catalog or import_catalog")
            doc.Regenerate()
        errs = [e for r in results for e in r.get("errors", [])]
        if strict and errs:
            raise RvtssError("Some values could not be set: {}".format(errs[:5]), status=409, results=results,
                             hint="Nothing was changed (strict=true). Fix the values or pass strict=false.")
        return {"results": results}

    res, fails = core.run_transaction(doc, "Family types: " + action, run, dry_run=dry)
    out = core.commit_result(res, fails, dry)
    out["types_now"] = [normalize_string(t.Name) for t in fm.Types]
    return out


def _catalog_columns(fm):
    from .compat import definition_spec

    cols = []
    for fp in fm.Parameters:
        if fp.IsInstance or fp.IsReporting or fp.Formula or not is_relevant(fp):
            continue
        spec, kind = definition_spec(fp.Definition)
        cols.append((fp, {"name": normalize_string(fp.Definition.Name), "spec": spec,
                          "unit": {"length": "mm", "area": "m2", "volume": "m3", "angle": "deg"}.get(kind)}))
    return cols


def _export_catalog(ctx, doc, fm):
    cols = _catalog_columns(fm)
    types = []
    for t in fm.Types:
        vals = {}
        for fp, c in cols:
            if not t.HasValue(fp):
                continue
            if fp.StorageType == DB.StorageType.ElementId:
                e = doc.GetElement(t.AsElementId(fp))
                vals[c["name"]] = normalize_string(e.Name) if e else ""
            elif c["unit"]:
                vals[c["name"]] = U.from_internal(t.AsDouble(fp), c["unit"], 4)
            else:
                vals[c["name"]] = family_type_value(fm, t, fp, "mm")
                if isinstance(vals[c["name"]], bool):
                    vals[c["name"]] = 1 if vals[c["name"]] else 0
        types.append({"name": normalize_string(t.Name), "values": vals})
    text = CATALOG.write([c for _fp, c in cols], types)
    path = ctx.get("path")
    if not path and doc.PathName:
        path = os.path.splitext(doc.PathName)[0] + ".txt"
    written = None
    if path and ctx.bool("write", True):
        if os.path.exists(path) and not ctx.bool("overwrite", False):
            raise RvtssError("Catalog exists: {}".format(path), status=409, hint="Pass overwrite=true.")
        import io

        with io.open(path, "w", encoding="utf-16") as fh:
            fh.write(text)
        written = path
    return {"path": written, "columns": [c for _fp, c in cols], "type_count": len(types),
            "preview": text if len(text) < 6000 else text[:6000] + "..."}


def _catalog_items(ctx):
    text = ctx.get("catalog_text")
    path = ctx.get("path")
    if not text:
        if not path or not os.path.isfile(path):
            raise RvtssError("Pass catalog_text or an existing catalog path")
        from .pure.sharedparams import read_text

        text = read_text(path)
    try:
        parsed = CATALOG.parse(text)
    except CATALOG.CatalogError as e:
        raise RvtssError("Invalid type catalog: {}".format(e))
    items = []
    for t in parsed["types"]:
        vals = {}
        for pname, v in t["values"].items():
            if v["unit"]:
                vals[pname] = {"value": float(v["value"]), "unit": v["unit"]}
            else:
                vals[pname] = {"value": v["value"], "unit": None}
        items.append({"name": t["name"], "values": vals})
    return items


# ---------------------------------------------------------------------- nested
def family_nested(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    action = ctx.require("action")
    dry = ctx.dry_run
    if action == "load":
        path = ctx.require("path")
        if not os.path.isfile(path):
            raise RvtssError("File not found: {}".format(path), status=404)
        base = os.path.splitext(os.path.basename(path))[0]

        def run():
            loaded = doc.LoadFamily(path)
            fam = None
            for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
                if normalize_string(f.Name) == base:
                    fam = f
            if fam is None:
                raise RvtssError("Family {} did not load (it may already be loaded or be incompatible)".format(base),
                                 status=409)
            return {"family": base, "family_id": id_int(fam), "newly_loaded": bool(loaded),
                    "types": [normalize_string(get_element_name(doc.GetElement(s))) for s in fam.GetFamilySymbolIds()]}

        res, fails = core.run_transaction(doc, "Load nested family", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    if action == "place":
        sym = core.find_type(doc, family=ctx.require("family"), type_name=ctx.get("type"),
                             of_class=DB.FamilySymbol)
        x, y, z = U.point_from(ctx.get("point") or [0, 0, 0], ctx.unit)

        def run():
            if not sym.IsActive:
                sym.Activate()
                doc.Regenerate()
            inst = doc.FamilyCreate.NewFamilyInstance(DB.XYZ(x, y, z), sym,
                                                      DB.Structure.StructuralType.NonStructural)
            assoc = []
            for ep_name, fp_name in (ctx.get("associate") or {}).items():
                ep = lookup_param(inst, ep_name)
                if ep is None:
                    ep = lookup_param(sym, ep_name)
                if ep is None:
                    raise RvtssError("Nested family has no parameter '{}'".format(ep_name), status=404)
                fm.AssociateElementParameterToFamilyParameter(ep, require_family_parameter(fm, fp_name))
                assoc.append({"nested_parameter": ep_name, "family_parameter": fp_name})
            return {"instance_id": id_int(inst), "associations": assoc}

        res, fails = core.run_transaction(doc, "Place nested family", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    raise RvtssError("action must be load or place (use family_parameters action=associate for more links)")


# -------------------------------------------------------------------- validate
def family_validate(ctx):
    doc = ctx.doc
    fm = core.require_family(doc)
    findings = []
    labels = labeled_dimensions(doc)
    # user parameters for "drives nothing" checks (built-ins like door Width are driven by Revit itself)
    params = [fp for fp in fm.Parameters if not is_builtin(fp)]
    relevant = [fp for fp in fm.Parameters if is_relevant(fp)]
    names = [normalize_string(fp.Definition.Name) for fp in params]
    relevant_names = [normalize_string(fp.Definition.Name) for fp in relevant]
    formulas = dict((normalize_string(fp.Definition.Name), fp.Formula) for fp in relevant if fp.Formula)

    cat = doc.OwnerFamily.FamilyCategory
    expected = ctx.get("expected_category")
    if expected:
        exp = core.resolve_category(doc, expected)
        if cat is None or cat.Id != exp.Id:
            findings.append(R.finding("category", "error", "Family category is '{}' but '{}' was expected".format(
                cat.Name if cat else None, exp.Name), recommendation="family_properties(category=...)"))
    elif cat is not None and cat.Name in ("Generic Models",):
        findings.append(R.finding("category", "info", "Family uses the Generic Models category",
                                  recommendation="Use a specific category so it schedules and filters correctly."))

    for issue in FORMULA.analyse(formulas, names + [normalize_string(fp.Definition.Name) for fp in fm.Parameters]):
        findings.append(R.finding("formulas", issue["severity"], "{}: {}".format(issue["parameter"], issue["issue"]),
                                  recommendation="Correct the formula with family_parameters(action='set_formula')."))

    referenced = set()
    for f in formulas.values():
        referenced.update(FORMULA.references(f, relevant_names))
    unused = []
    for fp in params:
        n = normalize_string(fp.Definition.Name)
        if fp.AssociatedParameters.Size == 0 and not labels.get(n) and not fp.Formula and n not in referenced:
            unused.append(n)
    if unused:
        findings.append(R.finding("parameters", "warning",
                                  "{} parameter(s) drive nothing (no dimension label, association or formula use): {}"
                                  .format(len(unused), ", ".join(unused[:15])),
                                  recommendation="Label a dimension, associate it, or remove it if it is pure data.",
                                  parameters=unused))
    pattern = ctx.get("parameter_naming_pattern") or core.load_config().get("naming", {}).get("parameters", {}).get("pattern")
    if pattern:
        findings.extend(R.check_names([(0, n) for n in names], {"pattern": pattern}, "naming", "parameters"))

    types = list(fm.Types)
    if not types:
        findings.append(R.finding("types", "error", "Family has no types",
                                  recommendation="Create at least one type with family_manage_types."))
    for t in types:
        missing = [normalize_string(fp.Definition.Name) for fp in relevant
                   if not fp.IsInstance and not fp.Formula and not fp.IsReporting and not t.HasValue(fp)
                   and fp.StorageType != DB.StorageType.String]
        if missing:
            findings.append(R.finding("types", "warning", "Type '{}' has no value for: {}".format(
                normalize_string(t.Name), ", ".join(missing[:10]))))
        if ctx.bool("check_dimension_values", True):
            for fp in relevant:
                if fp.StorageType == DB.StorageType.Double and t.HasValue(fp):
                    from .compat import definition_spec

                    if definition_spec(fp.Definition)[1] == "length" and t.AsDouble(fp) <= 0:
                        findings.append(R.finding("types", "error", "Type '{}': {} is zero or negative".format(
                            normalize_string(t.Name), normalize_string(fp.Definition.Name))))

    form_list = forms(doc)
    solids = [f for k, f in form_list if f.IsSolid]
    if not form_list:
        findings.append(R.finding("geometry", "warning", "Family has no solid or void forms"))
    for k, f in form_list:
        try:
            bb = f.get_BoundingBox(None)
            if bb is None or bb.Min.DistanceTo(bb.Max) < 1e-6:
                findings.append(R.finding("geometry", "error", "{} {} has no valid geometry".format(k, id_int(f)),
                                          element_ids=[id_int(f)]))
        except Exception:
            pass
    if solids and not labels:
        findings.append(R.finding("constraints", "warning",
                                  "Geometry exists but no dimension is labelled with a parameter - the family is not parametric",
                                  recommendation="Use family_add_dimension with label=... or family_build_parametric_box."))
    try:
        warns = list(doc.GetWarnings())
        if warns:
            findings.append(R.finding("warnings", "warning", "{} Revit warning(s): {}".format(
                len(warns), "; ".join(sorted(set(normalize_string(w.GetDescriptionText()) for w in warns))[:5])),
                element_ids=[id_int(i) for w in warns for i in w.GetFailingElements()]))
    except Exception:
        pass

    findings = R.sort_findings(findings)
    summary = R.summarize(findings)
    summary["passed"] = summary["by_severity"].get("error", 0) == 0 and summary["by_severity"].get("critical", 0) == 0
    return {"family": family_name(doc), "summary": summary, "findings": findings,
            "next_step": "Run family_flex_test to verify that geometry follows the parameters."}


# ----------------------------------------------------------- save / load / close
def _backup(path):
    folder = core.rvtss_subdir("backups")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(folder, "{}_{}{}".format(base, stamp, os.path.splitext(path)[1]))
    shutil.copy2(path, dest)
    return dest


def family_save(ctx):
    doc = ctx.doc
    core.require_family(doc)
    save_path = ctx.get("save_path")
    backup = None
    compact = ctx.bool("compact", False)
    if save_path:
        if not save_path.lower().endswith(".rfa"):
            raise RvtssError("save_path must end with .rfa")
        if os.path.exists(save_path):
            if not ctx.bool("overwrite", False):
                raise RvtssError("File exists: {}".format(save_path), status=409,
                                 hint="Pass overwrite=true (the existing file is backed up first).")
            backup = _backup(save_path)
        folder = os.path.dirname(save_path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        opts = DB.SaveAsOptions()
        opts.OverwriteExistingFile = True
        opts.Compact = compact
        opts.MaximumBackups = ctx.int("maximum_backups", 3, 1, 99)
        doc.SaveAs(save_path, opts)
        saved = save_path
    else:
        if not doc.PathName:
            raise RvtssError("This family has never been saved", status=409, hint="Pass save_path (.rfa).")
        if os.path.exists(doc.PathName) and ctx.bool("backup", True):
            backup = _backup(doc.PathName)
        opts = DB.SaveOptions()
        opts.Compact = compact
        doc.Save(opts)
        saved = doc.PathName
    return {"saved_path": saved, "backup": backup, "document": normalize_string(doc.Title),
            "size_kb": int(os.path.getsize(saved) / 1024) if os.path.exists(saved) else None}


class _LoadOptions(DB.IFamilyLoadOptions):
    def __init__(self, overwrite_values):
        self.overwrite_values = overwrite_values

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = self.overwrite_values
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = self.overwrite_values
        return True


def _target_project(ctx, famdoc):
    target = ctx.get("project")
    if target:
        d = core.resolve_document(ctx.active_doc, target)
    else:
        projects = [d for d in ctx.app.Documents if not d.IsFamilyDocument and not d.IsLinked]
        if ctx.active_doc is not None and not ctx.active_doc.IsFamilyDocument:
            d = ctx.active_doc
        elif len(projects) == 1:
            d = projects[0]
        else:
            raise RvtssError("Several projects are open; pass project='<title>'", status=409,
                             candidates=[p.Title for p in projects])
    core.require_project(d)
    return d


def family_load_into_project(ctx):
    famdoc = ctx.doc
    core.require_family(famdoc)
    project = _target_project(ctx, famdoc)
    core.check_modifiable(project)
    if project.IsModifiable or famdoc.IsModifiable:
        raise RvtssError("A transaction is open in one of the documents", status=409)
    name = family_name(famdoc)
    before = None
    for f in DB.FilteredElementCollector(project).OfClass(DB.Family):
        if normalize_string(f.Name) == name:
            before = f
    if before is not None and not ctx.bool("overwrite", True):
        raise RvtssError("Family '{}' is already loaded in '{}'".format(name, project.Title), status=409,
                         hint="Pass overwrite=true to reload.")
    overwrite_values = ctx.bool("overwrite_parameter_values", False)
    loaded = famdoc.LoadFamily(project, _LoadOptions(overwrite_values))
    fam = loaded if isinstance(loaded, DB.Family) else None
    if fam is None:
        for f in DB.FilteredElementCollector(project).OfClass(DB.Family):
            if normalize_string(f.Name) == name:
                fam = f
    if fam is None:
        raise RvtssError("Revit did not load the family", status=500)
    types = [normalize_string(get_element_name(project.GetElement(s))) for s in fam.GetFamilySymbolIds()]
    inst = len([1 for fi in DB.FilteredElementCollector(project).OfClass(DB.FamilyInstance)
                if fi.Symbol.Family.Id == fam.Id])
    family_types_in_doc = [normalize_string(t.Name) for t in famdoc.FamilyManager.Types]
    missing = [t for t in family_types_in_doc if t not in types]
    return {"project": normalize_string(project.Title), "family": name, "family_id": id_int(fam),
            "action": "reloaded" if before is not None else "loaded", "types_in_project": types,
            "instances_in_project": inst, "overwrite_parameter_values": overwrite_values,
            "verified": not missing, "types_missing_in_project": missing}


def family_close(ctx):
    doc = ctx.doc
    core.require_family(doc)
    if ctx.active_doc is not None and doc.Equals(ctx.active_doc):
        raise RvtssError("The active document cannot be closed through the API", status=409,
                         hint="Switch Revit to another document, or use close_document for the active one.")
    save = ctx.bool("save", False)
    if doc.IsModified and not save and not ctx.bool("discard_changes", False):
        raise RvtssError("Family '{}' has unsaved changes".format(doc.Title), status=409,
                         hint="Pass save=true, or discard_changes=true to close without saving.")
    if save and not doc.PathName:
        raise RvtssError("Family was never saved; use family_save with save_path first", status=409)
    title = normalize_string(doc.Title)
    if save and doc.PathName and os.path.exists(doc.PathName):
        _backup(doc.PathName)
    doc.Close(save)
    return {"closed": title, "saved": save}


# ---------------------------------------------------------------------- routes
def register_family_routes(api):
    @api.route("/family/templates/", methods=["POST"])
    def family_templates_route(doc, request):
        return handle(doc, request, family_templates, needs_doc=False)

    @api.route("/family/create/", methods=["POST"])
    def family_create_route(doc, request):
        return handle(doc, request, family_create, needs_doc=False)

    @api.route("/family/open/", methods=["POST"])
    def family_open_route(doc, request):
        return handle(doc, request, family_open, needs_doc=False)

    @api.route("/family/info/", methods=["POST"])
    def family_info_route(doc, request):
        return handle(doc, request, family_info)

    @api.route("/family/properties/", methods=["POST"])
    def family_properties_route(doc, request):
        return handle(doc, request, family_properties)

    @api.route("/family/parameters/", methods=["POST"])
    def family_parameters_route(doc, request):
        return handle(doc, request, family_parameters)

    @api.route("/family/types/", methods=["POST"])
    def family_types_route(doc, request):
        return handle(doc, request, family_types)

    @api.route("/family/nested/", methods=["POST"])
    def family_nested_route(doc, request):
        return handle(doc, request, family_nested)

    @api.route("/family/validate/", methods=["POST"])
    def family_validate_route(doc, request):
        return handle(doc, request, family_validate)

    @api.route("/family/save/", methods=["POST"])
    def family_save_route(doc, request):
        return handle(doc, request, family_save)

    @api.route("/family/load_into_project/", methods=["POST"])
    def family_load_route(doc, request):
        return handle(doc, request, family_load_into_project)

    @api.route("/family/close/", methods=["POST"])
    def family_close_route(doc, request):
        return handle(doc, request, family_close)

    logger.info("RVTSS family routes registered")
