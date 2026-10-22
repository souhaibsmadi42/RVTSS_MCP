# -*- coding: utf-8 -*-
"""Excel (.xlsx) writing on the MCP side with openpyxl (data comes from Revit as JSON).

Kept free of MCP imports so the sheet/heading logic is unit-testable.
"""
import os
import re

INVALID_SHEET_CHARS = re.compile(r"[\[\]\:\*\?\/\\]")
MAX_SHEET_TITLE = 31


def sheet_title(name, used):
    """Excel-safe, unique sheet title (max 31 chars, no []:*?/\\)."""
    base = INVALID_SHEET_CHARS.sub("_", str(name or "Sheet")).strip("'") or "Sheet"
    base = base[:MAX_SHEET_TITLE]
    title, n = base, 2
    while title.lower() in used:
        suffix = " (%d)" % n
        title = base[:MAX_SHEET_TITLE - len(suffix)] + suffix
        n += 1
    used.add(title.lower())
    return title


def header_with_unit(column, unit):
    return "%s [%s]" % (column, unit) if unit else column


def category_sheet(category, export):
    """Sheet spec from a /parameters/export/ JSON answer (format='json')."""
    units = export.get("column_units") or {}
    headers = [header_with_unit(c, units.get(c)) for c in export.get("columns") or []]
    return {"title": category, "headers": headers, "rows": export.get("rows") or [],
            "note": "truncated" if export.get("truncated") else None}


def schedule_sheet(name, columns, rows):
    return {"title": name, "headers": list(columns or []), "rows": rows or []}


def _cell(v):
    if isinstance(v, (int, float)) or v is None:
        return v
    if isinstance(v, (list, dict)):
        return str(v)
    s = str(v)
    # never let a value become a formula (CSV/Excel injection)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _is_number(s) else s


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def write_workbook(path, sheets, summary_rows=None):
    """Write sheets [{title, headers, rows}] (+ optional summary sheet) to `path`. Returns sheet titles."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    used = set()
    titles = []
    first = wb.active
    if summary_rows:
        first.title = sheet_title("Summary", used)
        for r in summary_rows:
            first.append([_cell(v) for v in r])
        first.column_dimensions["A"].width = 28
        first.column_dimensions["B"].width = 60
        titles.append(first.title)
        first = None
    for i, spec in enumerate(sheets):
        ws = first if (first is not None and i == 0) else wb.create_sheet()
        ws.title = sheet_title(spec["title"], used)
        titles.append(ws.title)
        ws.append(list(spec["headers"]))
        for c in ws[1]:
            c.font = Font(bold=True)
        for row in spec["rows"]:
            ws.append([_cell(v) for v in row])
        ws.freeze_panes = "A2"
        for idx, h in enumerate(spec["headers"], 1):
            width = max([len(str(h))] + [len(str(r[idx - 1])) for r in spec["rows"][:200]
                                         if idx - 1 < len(r) and r[idx - 1] is not None])
            ws.column_dimensions[get_column_letter(idx)].width = min(60, max(8, width + 2))
    if first is not None and not sheets:
        first.title = sheet_title("Empty", used)
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    wb.save(path)
    return titles
