# -*- coding: utf-8 -*-
"""RVTSS v2.1 coordination tools: clash report export, family library audit, Excel export.

Report files are written on the machine running the MCP server (RVTSS_REPORT_DIR,
default ~/Documents/RVTSS/reports); the data comes from Revit over the bridge.
"""
import csv
import io
import os
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from revit_mcp.pure import clash as CL

from ._compat import Context, READ_ONLY
from ._common import LengthUnit, compact, DOC_HELP, call_with_progress
from .utils import format_response
from . import excel_export as XL

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
GroupBy = Literal["pair", "type_pair", "level", "grid_zone"]


def report_dir():
    return os.environ.get("RVTSS_REPORT_DIR") or os.path.join(os.path.expanduser("~"), "Documents", "RVTSS", "reports")


def _safe_name(name):
    return "".join(c for c in (name or "report") if c.isalnum() or c in "-_. ").strip() or "report"


def _error(response):
    if isinstance(response, str):
        return response
    if isinstance(response, dict) and response.get("status") == "error":
        return format_response(response)
    return None


def clash_csv(report):
    unit = report.get("unit") or "mm"
    header = list(CL.ROW_HEADER)
    header[2] = "Distance [%s]" % unit
    header[6] = "Grid offset [%s]" % unit
    for i in (15, 16, 17):
        header[i] = "%s [%s]" % (header[i], unit)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in CL.clash_rows(report.get("clashes") or []):
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def write_clash_report(report, folder, name, formats):
    os.makedirs(folder, exist_ok=True)
    stem = os.path.join(folder, "%s_%s" % (_safe_name(name), time.strftime("%Y%m%d-%H%M%S")))
    paths = {}
    if "csv" in formats:
        paths["csv"] = stem + ".csv"
        with open(paths["csv"], "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(clash_csv(report))
    if "html" in formats:
        paths["html"] = stem + ".html"
        with open(paths["html"], "w", encoding="utf-8") as fh:
            fh.write(CL.to_html(report))
    return paths


def register_coordination_tools(mcp, revit_get, revit_post):
    """Register the v2.1 coordination tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def export_clash_report(
        set_a: Annotated[Dict[str, Any], Field(description="Element query, e.g. {categories: ['Ducts']}")],
        set_b: Annotated[Dict[str, Any], Field(description="Element query (+link_instance_id)")],
        clearance: Annotated[float, Field(ge=0, description="Soft-clash clearance in `unit` (0 = hard only)")] = 0.0,
        group_by: Optional[List[GroupBy]] = None,
        name: str = "clash_report",
        output_folder: Annotated[Optional[str], Field(description="Default: RVTSS_REPORT_DIR")] = None,
        formats: Optional[List[Literal["csv", "html"]]] = None,
        max_pairs: int = 500,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Clash check (hard + clearance) written to CSV/HTML: ids, levels, grid zone, nearest grid.

        Groups clashes by element category pair, level and grid zone (default all three). Files are
        written on the MCP machine. dry_run checks the sets and returns the planned file paths.
        """
        group_by = group_by or ["pair", "level", "grid_zone"]
        formats = formats or ["csv", "html"]
        folder = output_folder or report_dir()
        data = compact(set_a=set_a, set_b=set_b, clearance=clearance or None, group_by=group_by,
                       max_pairs=max_pairs, unit=unit, dry_run=dry_run or None, document=document)
        response = await call_with_progress(revit_post, "/qc/clashes/", data, ctx, 900.0, "Clash report")
        err = _error(response)
        if err:
            return err
        if dry_run:
            response["would_write"] = [os.path.join(folder, "%s_<timestamp>.%s" % (_safe_name(name), f))
                                       for f in formats]
            return format_response(response)
        response["set_a"], response["set_b"] = str(set_a), str(set_b)
        paths = write_clash_report(response, folder, name, formats)
        groups = response.get("groups") or {}
        return format_response({
            "status": "success", "files": paths, "clash_count": response.get("clash_count"),
            "hard_count": response.get("hard_count"), "clearance_count": response.get("clearance_count"),
            "groups": dict((k, [{"key": g["key"], "count": g["count"]} for g in v[:15]]) for k, v in groups.items()),
            "warnings": response.get("warnings"), "note": response.get("note"),
            "request_id": response.get("request_id")})

    @mcp.tool(annotations=READ_ONLY)
    async def audit_family_library(
        folder: Annotated[str, Field(description="Folder of .rfa files (Revit machine)")],
        recursive: bool = True,
        name_contains: Optional[str] = None,
        max_files: Annotated[int, Field(ge=1, le=500)] = 50,
        run_validation: Annotated[bool, Field(description="Run family_validate on each family")] = True,
        max_size_kb: int = 2048,
        include_details: bool = False,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Audit a folder of .rfa files (opened read-only, never saved): category, size, parameters, nested
        families, warnings, family_validate errors, naming.

        Naming uses qc_rules.json naming.families and the iso19650 'families' target. dry_run lists
        the files that would be opened. Backup files (*.0001.rfa) are skipped.
        """
        data = compact(folder=folder, recursive=recursive, name_contains=name_contains, max_files=max_files,
                       validate=run_validation, max_size_kb=max_size_kb, include_details=include_details or None,
                       dry_run=dry_run or None)
        response = await call_with_progress(revit_post, "/family/library_audit/", data, ctx, 1800.0,
                                            "Family library audit")
        return format_response(response)

    @mcp.tool(annotations=READ_ONLY)
    async def export_to_excel(
        output_path: Annotated[str, Field(description=".xlsx path (relative = report folder)")],
        categories: Annotated[Optional[List[str]], Field(description="One sheet per category")] = None,
        parameters: Annotated[Optional[List[str]], Field(description="Parameter columns for category sheets")] = None,
        schedules: Annotated[Optional[List[Union[int, str]]], Field(description="Schedule names/ids, one sheet each")] = None,
        level: Optional[str] = None,
        value_mode: Literal["raw", "display"] = "raw",
        unit: LengthUnit = "mm",
        overwrite: bool = False,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Write parameter values (one sheet per category, units in headers) and schedules to .xlsx.

        value_mode raw writes numbers in `unit` with the unit in the column header; display writes
        Revit's formatted text. Values starting with = + - @ are written as text.
        """
        if not categories and not schedules:
            return "Error: pass categories (with parameters) and/or schedules"
        if categories and not parameters:
            return "Error: parameters are required for category sheets"
        path = output_path if os.path.isabs(output_path) else os.path.join(report_dir(), output_path)
        if not path.lower().endswith(".xlsx"):
            return "Error: output_path must end with .xlsx"
        if os.path.exists(path) and not overwrite:
            return "Error: %s exists - pass overwrite=true" % path
        sheets, summary = [], [["RVTSS export", time.strftime("%Y-%m-%d %H:%M")], ["Unit", unit],
                               ["Value mode", value_mode], []]
        total = len(categories or []) + len(schedules or [])
        done = 0
        for cat in categories or []:
            res = await call_with_progress(revit_post, "/parameters/export/", compact(
                categories=[cat], parameters=parameters, level=level, value_mode=value_mode, unit=unit,
                format="json", document=document), ctx, 300.0, "Export %s" % cat)
            err = _error(res)
            if err:
                return err
            sheets.append(XL.category_sheet(cat, res))
            summary.append([cat, "%s rows%s" % (res.get("row_count"), " (truncated)" if res.get("truncated") else "")])
            done += 1
            if ctx:
                await ctx.report_progress(done, total, "Exported %s" % cat)
        for sch in schedules or []:
            rows, columns, offset, name = [], [], 0, str(sch)
            while True:
                res = await call_with_progress(revit_post, "/schedule_data/", compact(
                    schedule=sch, offset=offset, limit=2000, document=document), ctx, 300.0, "Schedule %s" % sch)
                err = _error(res)
                if err:
                    return err
                columns, name = res.get("columns") or columns, res.get("name") or name
                page = res.get("rows") or []
                rows.extend(page)
                offset += len(page)
                if not page or offset >= (res.get("row_count") or 0):
                    break
            sheets.append(XL.schedule_sheet(name, columns, rows))
            summary.append([name, "%d rows (schedule)" % len(rows)])
            done += 1
        if dry_run:
            return format_response({"status": "dry_run", "would_write": path,
                                    "sheets": [{"title": s["title"], "rows": len(s["rows"]),
                                                "headers": s["headers"]} for s in sheets]})
        titles = XL.write_workbook(path, sheets, summary)
        return format_response({"status": "success", "path": path, "sheets": titles,
                                "rows": sum(len(s["rows"]) for s in sheets)})
