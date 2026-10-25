# -*- coding: UTF-8 -*-
"""Exports written by Revit: PDF, DWG, DXF, IFC, NWC, schedule CSV (RVTSS v2.2).

Routes:
    POST /export/settings/   DWG export setups, PDF export settings (2022+), view/sheet sets, IFC versions,
                             Navisworks exporter availability, default folder
    POST /export/run/        export sheets / views / schedules / the model to a folder on the Revit machine

Files are written by Revit, on the Revit machine. One file per sheet / view
(named from a template such as "{number} - {name}") unless combine=true (PDF).
Existing files are never overwritten unless overwrite=true.
"""
import logging
import os
import time

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, REVIT_YEAR
from .pure import exportnames as N
from .utils import normalize_string

logger = logging.getLogger(__name__)


def default_folder(doc):
    base = os.path.join(os.path.expanduser("~"), "Documents", "RVTSS", "exports")
    stem = N.sanitize(os.path.splitext(normalize_string(doc.Title))[0])
    return os.path.join(base, stem)


def _id_list(ids):
    from System.Collections.Generic import List

    lst = List[DB.ElementId]()
    for i in ids:
        lst.Add(i)
    return lst


def _sheet_fields(doc, v):
    f = {"name": normalize_string(v.Name), "title": normalize_string(doc.Title), "view_type": str(v.ViewType),
         "date": time.strftime("%Y-%m-%d"), "document": os.path.splitext(normalize_string(doc.Title))[0]}
    if isinstance(v, DB.ViewSheet):
        f["number"] = normalize_string(v.SheetNumber)
        try:
            p = v.get_Parameter(DB.BuiltInParameter.SHEET_CURRENT_REVISION)
            f["revision"] = normalize_string(p.AsString() or "") if p else ""
        except Exception:
            f["revision"] = ""
    else:
        f["number"] = text_type(id_int(v))
    return f


def _resolve_targets(ctx, fmt):
    """Views / sheets / schedules to export, in a stable order."""
    doc = ctx.doc
    out = []
    seen = set()

    def add(v):
        if v is not None and id_int(v) not in seen:
            seen.add(id_int(v))
            out.append(v)

    all_sheets = sorted([s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
                         if not s.IsTemplate and not s.IsPlaceholder], key=lambda s: normalize_string(s.SheetNumber))
    if ctx.bool("all_sheets", False):
        for s in all_sheets:
            add(s)
    by_number = dict((normalize_string(s.SheetNumber).lower(), s) for s in all_sheets)
    for s in ctx.list("sheets"):
        key = text_type(s).strip()
        sheet = by_number.get(key.lower())
        if sheet is None and key.isdigit():
            e = doc.GetElement(core.make_id(int(key)))
            sheet = e if isinstance(e, DB.ViewSheet) else None
        if sheet is None:
            raise core.not_found("Sheet", s, [x.SheetNumber for x in all_sheets])
        add(sheet)
    for v in ctx.list("views"):
        add(core.find_view(doc, v))
    if ctx.get("view_set"):
        name = text_type(ctx.get("view_set")).lower()
        sets = list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet))
        match = [s for s in sets if normalize_string(s.Name).lower() == name]
        if not match:
            raise core.not_found("View/sheet set", ctx.get("view_set"), [s.Name for s in sets])
        members = [v for v in match[0].Views]
        for v in sorted(members, key=lambda v: (not isinstance(v, DB.ViewSheet),
                                                normalize_string(getattr(v, "SheetNumber", "") or v.Name))):
            add(v)
    if fmt == "csv":
        bad = [normalize_string(v.Name) for v in out if not isinstance(v, DB.ViewSchedule)]
        if bad:
            raise RvtssError("CSV export takes schedules only; not schedules: {}".format(bad[:10]))
    elif fmt not in N.MODEL_FORMATS:
        bad = [normalize_string(v.Name) for v in out if isinstance(v, DB.ViewSchedule) or v.IsTemplate]
        if bad:
            raise RvtssError("These views cannot be exported as {}: {}".format(fmt.upper(), bad[:10]),
                             hint="Place schedules on sheets and export the sheets, or use format='csv'.")
    return out


def _check_files(folder, stems, fmt, overwrite):
    paths = [os.path.join(folder, s + N.FORMATS[fmt]) for s in stems]
    existing = [p for p in paths if os.path.exists(p)]
    if existing and not overwrite:
        raise RvtssError("{} file(s) already exist, e.g. {}".format(len(existing), existing[0]), status=409,
                         hint="Pass overwrite=true, another folder or another naming template.",
                         existing=existing[:20])
    return paths


def _pdf_options(doc, ctx):
    if not hasattr(DB, "PDFExportOptions"):
        raise RvtssError("PDF export needs Revit 2022 or newer (this is Revit {})".format(REVIT_YEAR or "?"),
                         status=501, hint="Print to a PDF printer from Revit, or export DWG.")
    opts = None
    if ctx.get("setup"):
        try:
            found = DB.ExportPDFSettings.FindByName(doc, ctx.get("setup"))
            opts = found.GetOptions() if found is not None else None
        except Exception:
            opts = None
        if opts is None:
            raise core.not_found("PDF export setting", ctx.get("setup"), _pdf_setting_names(doc))
    if opts is None:
        opts = DB.PDFExportOptions()
        for attr, value in (("HideCropBoundaries", True), ("HideScopeBoxes", True),
                            ("HideReferencePlane", True), ("HideUnreferencedViewTags", True)):
            try:
                setattr(opts, attr, value)
            except Exception:
                pass
    color = ctx.get("pdf_color")
    if color:
        try:
            opts.ColorDepth = getattr(DB.ColorDepthType, {"color": "Color", "grayscale": "GrayScale",
                                                          "black_line": "BlackLine"}[color])
        except Exception:
            ctx.warn("pdf_color not applied on this Revit version")
    return opts


def _pdf_setting_names(doc):
    try:
        return [normalize_string(s.Name) for s in DB.FilteredElementCollector(doc).OfClass(DB.ExportPDFSettings)]
    except Exception:
        return []


def _dwg_options(doc, ctx, dxf=False):
    if dxf:
        return DB.DXFExportOptions()
    if ctx.get("setup"):
        opts = DB.DWGExportOptions.GetPredefinedOptions(doc, ctx.get("setup"))
        if opts is None:
            raise core.not_found("DWG export setup", ctx.get("setup"), _dwg_setup_names(doc))
        return opts
    opts = DB.DWGExportOptions()
    try:
        opts.MergedViews = True  # one DWG per view, xrefs off
    except Exception:
        pass
    return opts


def _dwg_setup_names(doc):
    try:
        return [normalize_string(s.Name) for s in DB.FilteredElementCollector(doc).OfClass(DB.ExportDWGSettings)]
    except Exception:
        return []


def _ifc_options(doc, ctx):
    opts = DB.IFCExportOptions()
    version = ctx.get("ifc_version")
    if version:
        member = getattr(DB.IFCVersion, version, None)
        if member is None:
            raise RvtssError("Unknown ifc_version '{}'. Available: {}".format(
                version, ", ".join(_ifc_versions())))
        opts.FileVersion = member
    if ctx.get("ifc_view"):
        v = core.find_view(doc, ctx.get("ifc_view"))
        opts.FilterViewId = v.Id
    for k, v in (ctx.get("ifc_options") or {}).items():
        # exporter options by name, e.g. {"ExportBaseQuantities": "true", "SpaceBoundaries": "1"}
        opts.AddOption(text_type(k), text_type(v))
    return opts


def _ifc_versions():
    try:
        import System

        return [text_type(n) for n in System.Enum.GetNames(DB.IFCVersion)]
    except Exception:
        return ["IFC2x3", "IFC4", "IFC2x3CV2", "IFC4RV", "IFC4DTV"]


def _nwc_available():
    try:
        return bool(DB.OptionalFunctionalityUtils.IsNavisworksExporterAvailable())
    except Exception:
        return False


def settings(ctx):
    doc = ctx.doc
    sets = []
    try:
        for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheetSet):
            sets.append({"id": id_int(s), "name": normalize_string(s.Name), "views": s.Views.Size})
    except Exception:
        pass
    return {"default_folder": default_folder(doc), "dwg_setups": _dwg_setup_names(doc),
            "pdf_settings": _pdf_setting_names(doc), "pdf_supported": hasattr(DB, "PDFExportOptions"),
            "view_sheet_sets": sets, "ifc_versions": _ifc_versions(),
            "navisworks_exporter_available": _nwc_available(),
            "formats": sorted(N.FORMATS), "naming_fields": ["{%s}" % f for f in N.FIELDS]}


def run_export(ctx):
    doc = ctx.doc
    core.require_project(doc)
    fmt = (ctx.require("format") or "").lower()
    if fmt not in N.FORMATS:
        raise RvtssError("format must be one of: " + ", ".join(sorted(N.FORMATS)))
    folder = ctx.get("folder") or default_folder(doc)
    if not os.path.isabs(folder):
        raise RvtssError("folder must be an absolute path on the Revit machine: {}".format(folder))
    overwrite = ctx.bool("overwrite", False)
    targets = [] if fmt in N.MODEL_FORMATS else _resolve_targets(ctx, fmt)
    if fmt not in N.MODEL_FORMATS and not targets:
        raise RvtssError("Nothing to export: give sheets, views, view_set or all_sheets=true")
    template = ctx.get("naming")
    if fmt in N.MODEL_FORMATS:
        stem = N.strip_extension(ctx.get("file_name") or os.path.splitext(normalize_string(doc.Title))[0], fmt)
        stems = [N.sanitize(stem)]
    elif fmt == "pdf" and ctx.bool("combine", False):
        stems = [N.sanitize(N.strip_extension(ctx.get("file_name") or "{} - combined".format(
            os.path.splitext(normalize_string(doc.Title))[0]), fmt))]
    else:
        try:
            stems = N.unique([N.render(template or N.default_template(isinstance(v, DB.ViewSheet)),
                                       _sheet_fields(doc, v)) for v in targets])
        except N.NamingError as e:
            raise RvtssError(text_type(e))
    planned = [os.path.join(folder, s + N.FORMATS[fmt]) for s in stems]
    preview = {"format": fmt, "folder": folder, "files": planned, "file_count": len(planned),
               "targets": [{"id": id_int(v), "name": normalize_string(v.Name),
                            "number": normalize_string(getattr(v, "SheetNumber", "") or "") or None}
                           for v in targets][:200]}
    if ctx.dry_run:
        preview.update({"status": "dry_run", "message": "Dry run: nothing was exported."})
        return preview
    core.require_writable("Export")
    if fmt == "nwc" and not _nwc_available():
        raise RvtssError("The Navisworks NWC exporter is not installed for this Revit version", status=501,
                         hint="Install 'Navisworks NWC Export Utility' (Autodesk) for this Revit year.")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    _check_files(folder, stems, fmt, overwrite)
    started = time.time()
    results = []
    if fmt == "pdf":
        opts = _pdf_options(doc, ctx)
        if ctx.bool("combine", False):
            opts.Combine = True
            opts.FileName = stems[0]
            ok = doc.Export(folder, _id_list([v.Id for v in targets]), opts)
            results.append({"file": planned[0], "ok": bool(ok)})
        else:
            opts.Combine = True  # one view per call -> exact file name per sheet
            for v, stem, path in zip(targets, stems, planned):
                opts.FileName = stem
                try:
                    ok = doc.Export(folder, _id_list([v.Id]), opts)
                    results.append({"id": id_int(v), "file": path, "ok": bool(ok)})
                except Exception as e:
                    results.append({"id": id_int(v), "file": path, "ok": False, "error": normalize_string(text_type(e))})
    elif fmt in ("dwg", "dxf"):
        opts = _dwg_options(doc, ctx, dxf=fmt == "dxf")
        for v, stem, path in zip(targets, stems, planned):
            try:
                ok = doc.Export(folder, stem, _id_list([v.Id]), opts)
                results.append({"id": id_int(v), "file": path, "ok": bool(ok)})
            except Exception as e:
                results.append({"id": id_int(v), "file": path, "ok": False, "error": normalize_string(text_type(e))})
    elif fmt == "csv":
        opts = DB.ViewScheduleExportOptions()
        opts.FieldDelimiter = ctx.get("delimiter") or ","
        for v, stem, path in zip(targets, stems, planned):
            try:
                v.Export(folder, stem + ".csv", opts)
                results.append({"id": id_int(v), "file": path, "ok": True})
            except Exception as e:
                results.append({"id": id_int(v), "file": path, "ok": False, "error": normalize_string(text_type(e))})
    elif fmt == "ifc":
        core.check_modifiable(doc)
        opts = _ifc_options(doc, ctx)
        # the IFC exporter must run inside a transaction; nothing it does is kept
        t = DB.Transaction(doc, "RVTSS: IFC export")
        t.Start()
        try:
            ok = doc.Export(folder, stems[0], opts)
        finally:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        results.append({"file": planned[0], "ok": bool(ok)})
    elif fmt == "nwc":
        opts = DB.NavisworksExportOptions()
        if ctx.get("nwc_view"):
            v = core.find_view(doc, ctx.get("nwc_view"))
            opts.ExportScope = DB.NavisworksExportScope.View
            opts.ViewId = v.Id
        else:
            opts.ExportScope = DB.NavisworksExportScope.Model
        doc.Export(folder, stems[0], opts)
        results.append({"file": planned[0], "ok": True})
    for r in results:
        exists = os.path.exists(r["file"])
        if r.get("ok") and not exists:
            r["ok"] = False
            r["error"] = "Revit reported success but the file was not found"
        if exists:
            r["size_kb"] = int(os.path.getsize(r["file"]) / 1024)
    failed = [r for r in results if not r.get("ok")]
    out = {"format": fmt, "folder": folder, "exported": len(results) - len(failed), "failed": failed,
           "files": [r for r in results if r.get("ok")], "seconds": round(time.time() - started, 1)}
    if failed and len(failed) == len(results):
        out["status"] = "error"
        out["error"] = "No file was exported"
        out["hint"] = failed[0].get("error") or "Check the views (empty / not printable) and the export setup."
    return out


def register_export_routes(api):
    @api.route("/export/settings/", methods=["POST"])
    def export_settings_route(doc, request):
        return handle(doc, request, settings)

    @api.route("/export/run/", methods=["POST"])
    def export_run_route(doc, request):
        return handle(doc, request, run_export)

    logger.info("RVTSS export routes registered")

