# -*- coding: UTF-8 -*-
"""Project-level model intelligence routes (RVTSS).

Routes:
    POST /project_overview/   project info, units, levels, grids, phases, worksets, design options
    POST /list_links/         Revit links and CAD imports with status and transforms
    POST /model_warnings/     warnings grouped by description, with element ids
    POST /family_inventory/   loaded families grouped by category with type / instance counts
    POST /find_views/         views with type, level, scale, template, sheet placement
    POST /list_sheets/        sheets with title block, viewports and key parameters
    POST /schedule_data/      read a schedule's table (paginated)
"""
import math
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, text_type, REVIT_YEAR
from .params_util import read_all
from .pure import units as U
from .pure import filters as F
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


def _display_length_unit(doc):
    try:
        fo = doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Length)
        return text_type(DB.LabelUtils.GetLabelForUnit(fo.GetUnitTypeId()))
    except Exception:
        try:
            return str(doc.GetUnits().GetFormatOptions(DB.UnitType.UT_Length).DisplayUnits)
        except Exception:
            return None


def project_overview(ctx):
    doc = ctx.doc
    unit = ctx.unit
    include = set(ctx.list("include") or ["info", "levels", "grids", "phases", "worksets", "design_options"])
    out = {"document": core.describe_document(doc), "revit_version": REVIT_YEAR or None,
           "display_length_unit": _display_length_unit(doc), "unit": unit}
    if "info" in include and not doc.IsFamilyDocument:
        pi = doc.ProjectInformation
        out["project_information"] = dict(
            (p["name"], p.get("display", p.get("value"))) for p in read_all(doc, pi, unit))
        try:
            site = doc.SiteLocation
            out["site"] = {"place": normalize_string(site.PlaceName),
                           "latitude_deg": round(math.degrees(site.Latitude), 6),
                           "longitude_deg": round(math.degrees(site.Longitude), 6)}
        except Exception:
            pass
    if "levels" in include:
        levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda lv: lv.Elevation)
        out["levels"] = [{"id": id_int(lv), "name": normalize_string(lv.Name),
                          "elevation": U.from_internal(lv.Elevation, unit, 2)} for lv in levels]
    if "grids" in include and not doc.IsFamilyDocument:
        grids = []
        for g in DB.FilteredElementCollector(doc).OfClass(DB.Grid):
            c = g.Curve
            grids.append({"id": id_int(g), "name": normalize_string(g.Name),
                          "start": core.xyz_list(c.GetEndPoint(0), unit),
                          "end": core.xyz_list(c.GetEndPoint(1), unit),
                          "curved": not isinstance(c, DB.Line)})
        out["grids"] = sorted(grids, key=lambda g: g["name"])
    if "phases" in include and not doc.IsFamilyDocument:
        out["phases"] = [{"id": id_int(p), "name": normalize_string(p.Name)} for p in doc.Phases]
    if "worksets" in include and doc.IsWorkshared:
        ws = DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
        out["worksets"] = [{"id": w.Id.IntegerValue, "name": normalize_string(w.Name), "is_open": w.IsOpen,
                            "is_editable": w.IsEditable, "owner": normalize_string(w.Owner or "")} for w in ws]
        try:
            out["active_workset"] = normalize_string(doc.GetWorksetTable().GetWorkset(
                doc.GetWorksetTable().GetActiveWorksetId()).Name)
        except Exception:
            pass
    if "design_options" in include and not doc.IsFamilyDocument:
        opts = []
        for o in DB.FilteredElementCollector(doc).OfClass(DB.DesignOption):
            try:
                set_name = normalize_string(doc.GetElement(o.get_Parameter(
                    DB.BuiltInParameter.OPTION_SET_ID).AsElementId()).Name)
            except Exception:
                set_name = None
            opts.append({"id": id_int(o), "name": normalize_string(o.Name), "is_primary": o.IsPrimary,
                         "option_set": set_name})
        out["design_options"] = opts
    return out


def list_links(ctx):
    doc = ctx.doc
    unit = ctx.unit
    links = []
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ltype = doc.GetElement(inst.GetTypeId())
        info = {"instance_id": id_int(inst), "type_id": id_int(ltype) if ltype else None,
                "name": normalize_string(inst.Name), "pinned": inst.Pinned}
        try:
            ref = DB.ExternalFileUtils.GetExternalFileReference(doc, ltype.Id)
            info["path"] = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(ref.GetAbsolutePath())
            info["status"] = str(ref.GetLinkedFileStatus())
        except Exception:
            pass
        ldoc = inst.GetLinkDocument()
        info["loaded"] = ldoc is not None
        try:
            tr = inst.GetTotalTransform()
            info["transform"] = {"origin": core.xyz_list(tr.Origin, unit),
                                 "rotation_deg": round(math.degrees(math.atan2(tr.BasisX.Y, tr.BasisX.X)), 4)}
        except Exception:
            pass
        if ldoc is not None:
            info["link_title"] = normalize_string(ldoc.Title)
            if ctx.bool("include_counts", False):
                counts = {}
                for e in DB.FilteredElementCollector(ldoc).WhereElementIsNotElementType():
                    if e.Category is not None and e.Category.CategoryType == DB.CategoryType.Model:
                        n = normalize_string(e.Category.Name)
                        counts[n] = counts.get(n, 0) + 1
                info["model_category_counts"] = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:40])
        links.append(info)
    imports = []
    for imp in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance):
        try:
            imports.append({"id": id_int(imp), "name": normalize_string(imp.Category.Name if imp.Category else ""),
                            "is_linked": imp.IsLinked, "view_specific": imp.ViewSpecific,
                            "owner_view_id": id_int(imp.OwnerViewId) if is_valid_id(imp.OwnerViewId) else None,
                            "pinned": imp.Pinned})
        except Exception:
            continue
    return {"revit_links": links, "revit_link_count": len(links),
            "not_loaded": [l["name"] for l in links if not l["loaded"]],
            "cad_imports": imports, "cad_import_count": len(imports),
            "cad_imported_not_linked": len([i for i in imports if not i["is_linked"]])}


def model_warnings(ctx):
    doc = ctx.doc
    groups = {}
    for w in doc.GetWarnings():
        text = normalize_string(w.GetDescriptionText())
        g = groups.setdefault(text, {"description": text, "count": 0, "severity": str(w.GetSeverity()),
                                     "element_ids": []})
        g["count"] += 1
        if len(g["element_ids"]) < ctx.int("ids_per_warning", 30):
            ids = [id_int(i) for i in w.GetFailingElements()]
            try:
                ids += [id_int(i) for i in w.GetAdditionalElements()]
            except Exception:
                pass
            g["element_ids"].append(ids)
    items = sorted(groups.values(), key=lambda g: -g["count"])
    contains = (ctx.get("contains") or "").lower()
    if contains:
        items = [g for g in items if contains in g["description"].lower()]
    page, meta = F.paginate(items, ctx.int("offset", 0), ctx.int("limit", 50, 1, 500))
    return {"total_warnings": sum(g["count"] for g in groups.values()), "distinct_warnings": len(groups),
            "pagination": meta, "warnings": page}


def family_inventory(ctx):
    doc = ctx.doc
    core.require_project(doc)
    cat_filter = None
    if ctx.get("category"):
        cat_filter = core.resolve_category(doc, ctx.get("category")).Id
    contains = (ctx.get("contains") or "").lower()
    instance_counts = {}
    for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        try:
            k = id_int(fi.Symbol.Id)
            instance_counts[k] = instance_counts.get(k, 0) + 1
        except Exception:
            continue
    fams = []
    for fam in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        cat = fam.FamilyCategory
        if cat_filter is not None and (cat is None or cat.Id != cat_filter):
            continue
        name = normalize_string(fam.Name)
        if contains and contains not in name.lower():
            continue
        types = []
        total = 0
        for sid in fam.GetFamilySymbolIds():
            s = doc.GetElement(sid)
            n = instance_counts.get(id_int(sid), 0)
            total += n
            types.append({"id": id_int(sid), "name": normalize_string(get_element_name(s)), "instances": n})
        entry = {"id": id_int(fam), "name": name, "category": normalize_string(cat.Name) if cat else None,
                 "in_place": fam.IsInPlace, "editable": fam.IsEditable, "type_count": len(types),
                 "instance_count": total}
        if ctx.bool("include_types", True):
            entry["types"] = sorted(types, key=lambda t: t["name"])
        fams.append(entry)
    fams.sort(key=lambda f: ((f["category"] or ""), f["name"]))
    if ctx.bool("unused_only", False):
        fams = [f for f in fams if f["instance_count"] == 0]
    page, meta = F.paginate(fams, ctx.int("offset", 0), ctx.int("limit", 100, 1, core.MAX_LIMIT))
    by_cat = {}
    for f in fams:
        by_cat[f["category"] or "(none)"] = by_cat.get(f["category"] or "(none)", 0) + 1
    return {"family_count": len(fams), "families_by_category": by_cat, "pagination": meta, "families": page}


def _sheet_of_views(doc):
    placed = {}
    for vp in DB.FilteredElementCollector(doc).OfClass(DB.Viewport):
        sh = doc.GetElement(vp.SheetId)
        placed[id_int(vp.ViewId)] = normalize_string(sh.SheetNumber) if sh else None
    for ssi in DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance):
        sh = doc.GetElement(ssi.OwnerViewId)
        placed.setdefault(id_int(ssi.ScheduleId), normalize_string(sh.SheetNumber) if sh else None)
    return placed


def find_views(ctx):
    doc = ctx.doc
    vtypes = set(t.lower() for t in ctx.list("view_types"))
    contains = (ctx.get("name_contains") or "").lower()
    templates = ctx.get("templates", "exclude")  # exclude | include | only
    placed = _sheet_of_views(doc) if not doc.IsFamilyDocument else {}
    on_sheet = ctx.get("on_sheet")  # None | True | False
    out = []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if v.ViewType in (DB.ViewType.Internal, DB.ViewType.ProjectBrowser, DB.ViewType.SystemBrowser):
            continue
        if templates == "exclude" and v.IsTemplate or templates == "only" and not v.IsTemplate:
            continue
        vt = str(v.ViewType)
        if vtypes and vt.lower() not in vtypes:
            continue
        name = normalize_string(v.Name)
        if contains and contains not in name.lower():
            continue
        sheet = placed.get(id_int(v))
        if on_sheet is True and not sheet or on_sheet is False and sheet:
            continue
        d = {"id": id_int(v), "name": name, "view_type": vt, "is_template": v.IsTemplate, "sheet": sheet}
        try:
            d["scale"] = v.Scale
        except Exception:
            pass
        try:
            if is_valid_id(v.ViewTemplateId):
                d["template"] = normalize_string(doc.GetElement(v.ViewTemplateId).Name)
        except Exception:
            pass
        try:
            if isinstance(v, DB.ViewPlan) and v.GenLevel is not None:
                d["level"] = normalize_string(v.GenLevel.Name)
        except Exception:
            pass
        try:
            d["detail_level"] = str(v.DetailLevel)
        except Exception:
            pass
        out.append(d)
    out.sort(key=lambda d: (d["view_type"], d["name"]))
    page, meta = F.paginate(out, ctx.int("offset", 0), ctx.int("limit", 200, 1, core.MAX_LIMIT))
    by_type = {}
    for d in out:
        by_type[d["view_type"]] = by_type.get(d["view_type"], 0) + 1
    return {"count": len(out), "by_type": by_type, "pagination": meta, "views": page}


def list_sheets(ctx):
    doc = ctx.doc
    core.require_project(doc)
    params = ctx.list("parameters")
    contains = (ctx.get("contains") or "").lower()
    tbs = {}
    for tb in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
            .WhereElementIsNotElementType():
        tbs.setdefault(id_int(tb.OwnerViewId), []).append(core.element_brief(doc, tb))
    sheets = []
    for sh in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
        if sh.IsTemplate:
            continue
        num, name = normalize_string(sh.SheetNumber), normalize_string(sh.Name)
        if contains and contains not in (num + " " + name).lower():
            continue
        vps = []
        for vid in sh.GetAllPlacedViews():
            v = doc.GetElement(vid)
            if v is not None:
                vps.append({"id": id_int(v), "name": normalize_string(v.Name), "view_type": str(v.ViewType)})
        d = {"id": id_int(sh), "number": num, "name": name, "placeholder": sh.IsPlaceholder,
             "views": vps, "title_blocks": tbs.get(id_int(sh), [])}
        try:
            d["revisions"] = [normalize_string(doc.GetElement(r).Name) for r in sh.GetAllRevisionIds()]
        except Exception:
            pass
        if params:
            d["parameters"] = dict((p["name"], p.get("display", p.get("value")))
                                   for p in read_all(doc, sh, ctx.unit, params))
        sheets.append(d)
    sheets.sort(key=lambda s: s["number"])
    page, meta = F.paginate(sheets, ctx.int("offset", 0), ctx.int("limit", 100, 1, core.MAX_LIMIT))
    return {"count": len(sheets), "pagination": meta, "sheets": page,
            "sheets_without_views": len([s for s in sheets if not s["views"] and not s["placeholder"]]),
            "sheets_without_title_block": len([s for s in sheets if not s["title_blocks"] and not s["placeholder"]])}


def schedule_data(ctx):
    doc = ctx.doc
    sid = ctx.get("schedule")
    if sid is None:
        raise RvtssError("'schedule' (id or name) is required")
    sched = None
    if isinstance(sid, int) or text_type(sid).isdigit():
        sched = doc.GetElement(core.make_id(int(sid)))
    else:
        for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
            if normalize_string(v.Name).lower() == text_type(sid).lower():
                sched = v
                break
    if not isinstance(sched, DB.ViewSchedule):
        raise core.not_found("Schedule", sid, [v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule)
                                               if not v.IsTemplate])
    table = sched.GetTableData()
    body = table.GetSectionData(DB.SectionType.Body)
    rows, cols = body.NumberOfRows, body.NumberOfColumns
    data_rows = []
    for r in range(rows):
        data_rows.append([text_type(sched.GetCellText(DB.SectionType.Body, r, c)) for c in range(cols)])
    header_rows = 1
    try:
        if sched.Definition.ShowHeaders is False:
            header_rows = 0
    except Exception:
        pass
    headers = data_rows[0] if header_rows and data_rows else []
    records = data_rows[header_rows:]
    page, meta = F.paginate(records, ctx.int("offset", 0), ctx.int("limit", 200, 1, 2000))
    return {"schedule_id": id_int(sched), "name": normalize_string(sched.Name), "columns": headers,
            "row_count": len(records), "pagination": meta, "rows": page}


def session_info(ctx):
    from . import __version__ as base_version, RVTSS_VERSION
    from .compat import REVIT_YEAR as year

    docs = [core.describe_document(d) for d in core.all_documents(ctx.active_doc)]
    active = ctx.active_doc
    out = {"revit_version": year or None, "extension_version": base_version, "rvtss_version": RVTSS_VERSION,
           "active_document": normalize_string(active.Title) if active is not None else None,
           "open_documents": [d for d in docs if not d["is_linked"]],
           "linked_documents": [d["title"] for d in docs if d["is_linked"]]}
    try:
        from pyrevit import HOST_APP

        out["revit_build"] = HOST_APP.build
        out["pyrevit_language"] = HOST_APP.language
    except Exception:
        pass
    if ctx.uidoc is not None and active is not None:
        try:
            v = ctx.uidoc.ActiveView
            out["active_view"] = {"id": id_int(v), "name": normalize_string(v.Name), "type": str(v.ViewType)}
            out["selection_count"] = ctx.uidoc.Selection.GetElementIds().Count
        except Exception:
            pass
    try:
        out["shared_parameter_file"] = ctx.app.SharedParametersFilename or None
        out["family_template_path"] = ctx.app.FamilyTemplatePath or None
    except Exception:
        pass
    out["rvtss_data_folder"] = core.rvtss_home()
    try:
        from .secure_api import security_status

        out["security"] = security_status()
    except Exception:
        pass
    import sys
    import platform
    import tempfile

    out["python_version"] = sys.version.split("\n")[0]
    out["python_engine"] = platform.python_implementation()
    out["temp_dir"] = tempfile.gettempdir()
    try:
        from pyrevit import versionmgr

        out["pyrevit_version"] = versionmgr.get_pyrevit_version().get_formatted()
    except Exception:
        out["pyrevit_version"] = None
    return out


def rvtss_files(ctx):
    """config.json / qc_rules.json / today's audit log from %APPDATA%/RVTSS (secrets masked)."""
    import io
    import os
    import time
    from .pure.security import redact_mapping, redact

    kind = ctx.require("kind")
    home = core.rvtss_home()
    if kind in ("config", "qc_rules"):
        path = os.path.join(home, "config.json" if kind == "config" else "qc_rules.json")
        if not os.path.isfile(path):
            return {"kind": kind, "path": path, "exists": False, "content": {}}
        import json

        with io.open(path, encoding="utf-8") as fh:
            try:
                content = json.load(fh)
            except ValueError as e:
                return {"kind": kind, "path": path, "exists": True, "error": "invalid JSON: {}".format(e)}
        return {"kind": kind, "path": path, "exists": True, "content": redact_mapping(content)}
    if kind == "log_today":
        path = os.path.join(home, "logs", "rvtss-{}.log".format(time.strftime("%Y%m%d")))
        lines = []
        if os.path.isfile(path):
            with io.open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        n = ctx.int("max_lines", 200, 1, 2000)
        return {"kind": kind, "path": path, "lines": [redact(l) for l in lines[-n:]], "total_lines": len(lines)}
    raise RvtssError("kind must be config, qc_rules or log_today")


def register_project_data_routes(api):
    # file access only: no `doc` argument, so pyRevit answers without waiting for Revit to be idle
    @api.route("/rvtss_files/", methods=["POST"])
    def rvtss_files_route(request):
        return handle(None, request, rvtss_files, needs_doc=False)

    @api.route("/session_info/", methods=["POST"])
    def session_info_route(doc, uidoc, request):
        return handle(doc, request, session_info, uidoc=uidoc, needs_doc=False)

    @api.route("/project_overview/", methods=["POST"])
    def project_overview_route(doc, request):
        return handle(doc, request, project_overview)

    @api.route("/list_links/", methods=["POST"])
    def list_links_route(doc, request):
        return handle(doc, request, list_links)

    @api.route("/model_warnings/", methods=["POST"])
    def model_warnings_route(doc, request):
        return handle(doc, request, model_warnings)

    @api.route("/family_inventory/", methods=["POST"])
    def family_inventory_route(doc, request):
        return handle(doc, request, family_inventory)

    @api.route("/find_views/", methods=["POST"])
    def find_views_route(doc, request):
        return handle(doc, request, find_views)

    @api.route("/list_sheets/", methods=["POST"])
    def list_sheets_route(doc, request):
        return handle(doc, request, list_sheets)

    @api.route("/schedule_data/", methods=["POST"])
    def schedule_data_route(doc, request):
        return handle(doc, request, schedule_data)

    logger.info("RVTSS project data routes registered")
