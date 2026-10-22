# -*- coding: utf-8 -*-
"""Read-only parser for Revit shared parameter files (.txt).

Writing is always done through the Revit API (DefinitionFile) so Revit keeps
control of the file format and existing GUIDs are never rewritten.
"""
import io
import re

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def is_guid(text):
    return bool(text) and bool(_GUID.match(text.strip()))


def read_text(path):
    """Read a shared parameter file honouring the UTF-16 BOM Revit writes."""
    with open(path, "rb") as fh:
        data = fh.read()
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"), (b"\xef\xbb\xbf", "utf-8")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse(text):
    """Parse shared parameter file text.

    Returns {"meta": {...}, "groups": {id: name}, "params": [ {...} ], "issues": [...]}
    """
    meta, groups, params, issues = {}, {}, [], []
    headers = {}
    for lineno, line in enumerate(io.StringIO(text), 1):
        line = line.rstrip("\r\n")
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        kind = cols[0]
        if kind.startswith("*"):
            headers[kind[1:]] = cols[1:]
            continue
        hdr = headers.get(kind)
        if hdr is None:
            issues.append({"line": lineno, "issue": "Row '%s' before its header" % kind})
            continue
        row = dict(zip(hdr, cols[1:]))
        if kind == "META":
            meta = row
        elif kind == "GROUP":
            groups[row.get("ID")] = row.get("NAME")
        elif kind == "PARAM":
            p = {
                "guid": row.get("GUID", ""),
                "name": row.get("NAME", ""),
                "datatype": row.get("DATATYPE", ""),
                "datacategory": row.get("DATACATEGORY", ""),
                "group_id": row.get("GROUP", ""),
                "visible": row.get("VISIBLE", "1") == "1",
                "description": row.get("DESCRIPTION", ""),
                "user_modifiable": row.get("USERMODIFIABLE", "1") == "1",
                "hide_when_no_value": row.get("HIDEINPROPERTIES", "0") == "1",
                "line": lineno,
            }
            params.append(p)
    for p in params:
        p["group"] = groups.get(p["group_id"])
        if p["group"] is None:
            issues.append({"line": p["line"], "issue": "Parameter '%s' references unknown group %s" % (p["name"], p["group_id"])})
        if not is_guid(p["guid"]):
            issues.append({"line": p["line"], "issue": "Parameter '%s' has an invalid GUID" % p["name"]})
    issues.extend(find_duplicates(params))
    return {"meta": meta, "groups": groups, "params": params, "issues": issues}


def find_duplicates(params):
    issues = []
    by_guid, by_name = {}, {}
    for p in params:
        by_guid.setdefault(p["guid"].lower(), []).append(p)
        by_name.setdefault(p["name"].lower(), []).append(p)
    for guid, ps in by_guid.items():
        if len(ps) > 1:
            issues.append({"issue": "Duplicate GUID %s used by %s" % (guid, ", ".join(sorted(set(x["name"] for x in ps)))),
                           "severity": "error"})
    for name, ps in by_name.items():
        if len(ps) > 1:
            issues.append({"issue": "Parameter name '%s' defined %d times with different GUIDs" % (ps[0]["name"], len(ps)),
                           "severity": "warning"})
    return issues


def parse_file(path):
    return parse(read_text(path))
