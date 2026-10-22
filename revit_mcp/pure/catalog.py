# -*- coding: utf-8 -*-
"""Revit type catalog (.txt next to the .rfa) reader/writer.

Format:
    ,Width##LENGTH##MILLIMETERS,Height##LENGTH##MILLIMETERS,Fire Rating##OTHER##
    D1 900x2100,900,2100,60 min
"""
import csv
import io

# catalog unit token -> rvtss unit
CATALOG_UNITS = {
    "MILLIMETERS": "mm", "CENTIMETERS": "cm", "METERS": "m", "FEET": "ft", "INCHES": "in",
    "SQUARE_METERS": "m2", "SQUARE_FEET": "ft2", "CUBIC_METERS": "m3", "CUBIC_FEET": "ft3",
    "DEGREES": "deg", "DECIMAL_DEGREES": "deg", "RADIANS": "rad",
}
RVTSS_TO_CATALOG = dict((v, k) for k, v in CATALOG_UNITS.items() if k != "DECIMAL_DEGREES")

# rvtss spec name -> catalog type token
SPEC_TO_CATALOG = {
    "length": "LENGTH", "area": "AREA", "volume": "VOLUME", "angle": "ANGLE",
    "number": "OTHER", "integer": "OTHER", "text": "OTHER", "yesno": "OTHER",
    "material": "OTHER", "url": "OTHER",
}


class CatalogError(ValueError):
    pass


def parse_header_cell(cell):
    parts = cell.split("##")
    name = parts[0].strip()
    kind = parts[1].strip().upper() if len(parts) > 1 else "OTHER"
    unit_tok = parts[2].strip().upper() if len(parts) > 2 else ""
    unit = CATALOG_UNITS.get(unit_tok) if unit_tok else None
    return {"name": name, "kind": kind, "unit": unit, "unit_token": unit_tok}


def parse(text):
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise CatalogError("Type catalog is empty")
    header = rows[0]
    if header and header[0].strip():
        raise CatalogError("Type catalog header must start with an empty cell (',Param##TYPE##UNIT,...')")
    columns = [parse_header_cell(c) for c in header[1:]]
    types = []
    for i, r in enumerate(rows[1:], 2):
        if len(r) - 1 > len(columns):
            raise CatalogError("Line %d has more values than header columns" % i)
        name = r[0].strip()
        if not name:
            raise CatalogError("Line %d has no type name" % i)
        values = {}
        for col, val in zip(columns, r[1:]):
            if val.strip() == "":
                continue
            values[col["name"]] = {"value": val.strip(), "unit": col["unit"], "kind": col["kind"]}
        types.append({"name": name, "values": values})
    return {"columns": columns, "types": types}


def write(columns, types):
    """columns: [{"name", "spec", "unit"}]; types: [{"name", "values": {param: value}}]"""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    hdr = [""]
    for c in columns:
        kind = SPEC_TO_CATALOG.get(c.get("spec") or "", "OTHER")
        unit = RVTSS_TO_CATALOG.get(c.get("unit") or "", "") if kind != "OTHER" else ""
        hdr.append("%s##%s##%s" % (c["name"], kind, unit))
    w.writerow(hdr)
    for t in types:
        row = [t["name"]]
        for c in columns:
            v = t["values"].get(c["name"])
            row.append("" if v is None else (u"%s" % v))
        w.writerow(row)
    return out.getvalue()
