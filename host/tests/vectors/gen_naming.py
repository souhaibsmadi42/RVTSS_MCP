# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/naming.py -> naming.json."""
import io
import json
import os

from _lane_b import Recorder, ROOT
from revit_mcp.pure import naming as N

r = Recorder(N)
r.extra["targets"] = list(N.TARGETS)

SCHEME = {
    "delimiter": "-",
    "severity": "error",
    "description": "Follow the BEP",
    "fields": [
        {"name": "project", "values": ["P123"]},
        {"name": "originator", "values": ["ABC", "XYZ"]},
        {"name": "volume", "pattern": "^(ZZ|XX|[A-Z0-9]{2})$"},
        {"name": "level", "values": ["00", "01", "02", "B1", "RF", "ZZ", "XX"]},
        {"name": "type", "values": ["DR", "M3", "SH", "SC"]},
        {"name": "role", "values": ["A", "S", "M", "E", "P"]},
        {"name": "number", "pattern": "^\\d{4}$"},
    ],
    "targets": {
        "sheets": {"source": "number"},
        "views": {"fields": [{"name": "discipline", "values": ["ARC", "STR"], "case_sensitive": False},
                             {"name": "kind", "min_length": 2, "max_length": 6},
                             {"name": "suffix", "optional": True, "length": 3}],
                  "delimiter": "_", "severity": "warning", "description": "Views: DIS_Kind[_Sfx]"},
        "view_templates": None,
        "families": {"delimiter": "", "fields": [{"name": "whole", "pattern": "^[A-Z]{3}_"}], "severity": "bogus"},
        "worksets": {"fields": [{"name": "discipline", "values": ["ARC", "STR", "MEP"]},
                                {"name": "description", "min_length": 3},
                                {"name": "zone", "optional": True}],
                     "delimiter": "_"},
    },
}
SCHEMES = {
    "main": SCHEME,
    "empty": {},
    "no_targets": {"fields": [{"name": "x"}]},
    "no_fields": {"targets": {"views": {}}},
    "bad_pattern": {"fields": [{"name": "x", "pattern": "("}], "targets": {"views": {}}},
    "bad_pattern_noname": {"fields": [{"pattern": "[a-"}], "targets": {"views": {"delimiter": "/"}}},
    "defaults": {"fields": [{"name": "a"}, {"name": "b", "optional": True}], "targets": {"types": {}, "views": None}},
    "targets_none": {"targets": None, "fields": [{"name": "a"}]},
    "field_not_dict": {"fields": ["x"], "targets": {"views": {}}},
    "empty_fields_target": {"fields": [{"name": "top"}], "targets": {"views": {"fields": []}}},
    "dup_field_names": {"delimiter": ".", "fields": [{"name": "p", "length": 1}, {"name": "p", "length": 1}, {"length": 2}],
                        "targets": {"types": {"description": ""}}},
}
example = os.path.join(ROOT, "docs", "examples", "qc_rules.iso19650.json")
if os.path.exists(example):
    with io.open(example, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc.get("iso19650"), dict):
        SCHEMES["docs_example"] = doc["iso19650"]
r.extra["schemes"] = SCHEMES

for key in sorted(SCHEMES):
    for target in list(N.TARGETS) + ["levels", ""]:
        r.call_as("target_scheme", N.target_scheme, (SCHEMES[key], target), {}, shown_args=[key, target])

FIELDS = [
    {"name": "x"}, {"name": "x", "optional": True}, {"name": "x", "optional": 0},
    {"name": "x", "values": ["A", "B"]}, {"name": "x", "values": ["A", "b"], "case_sensitive": False},
    {"name": "x", "values": ["A", "b"], "case_sensitive": True}, {"name": "x", "values": []},
    {"name": "x", "values": [1, 2, "3"]}, {"name": "x", "values": [1, 2, "3"], "case_sensitive": False},
    {"name": "x", "values": ["v%02d" % i for i in range(12)]}, {"name": "x", "values": ["v%02d" % i for i in range(13)]},
    {"name": "x", "values": "ABC"}, {"name": "x", "values": "ABC", "case_sensitive": False},
    {"name": "x", "values": "ABCDEFGHIJKLMNOP"},
    {"name": "x", "pattern": "^\\d{4}$"}, {"name": "x", "pattern": "^[a-z]+$", "case_sensitive": False},
    {"name": "x", "pattern": "^[a-z]+$"}, {"name": "x", "pattern": "b"}, {"name": "x", "pattern": "("},
    {"name": "x", "pattern": "^(?P<a>[A-Z])(?P=a)$"}, {"name": "x", "pattern": "^ab\\Z"},
    {"name": "x", "length": 2}, {"name": "x", "length": "2"}, {"name": "x", "length": 2.0}, {"name": "x", "length": 0},
    {"name": "x", "min_length": 3}, {"name": "x", "max_length": 3}, {"name": "x", "min_length": 2, "max_length": 3},
    {"name": "x", "length": "two"}, {"name": "x", "values": ["AB"], "pattern": "^A", "length": 3},
    {"name": "x", "values": ["ab"], "pattern": "^A", "max_length": 1, "case_sensitive": False},
    {"name": "x", "min_length": "3"}, {"name": "x", "max_length": 2.9}, {},
]
for field in FIELDS:
    for value in ["", None, "A", "a", "B", "ab", "AB", "abc", "ABCD", "1234", "12", "3", "1", "v05", "V05", "zz", "AA",
                  "Ab", "ab\n", "BCD", "d"]:
        r.call("check_field", field, value)

for key in ["main", "defaults", "dup_field_names", "docs_example"]:
    if key not in SCHEMES:
        continue
    for target in N.TARGETS:
        ts = N.target_scheme(SCHEMES[key], target)
        if ts is None:
            continue
        for name in ["P123-ABC-ZZ-01-DR-A-0001", "P123-QQQ-ZZ-01-DR-A-12", "P123-ABC", "", None, "ARC_Walls",
                     "ARC_Walls_Ext", "arc_Plan", "STR_P_abc", "ARC_W", "XYZ_", "ABC_Door", "abc", "MEP_Ducts_Z1_extra",
                     "a", "a-b", "a-b-c", "-", "a.b.cc", "a.bb.c", "ab.c.dd", "P123-ABC-ZZ-01-DR-A-0001-extra",
                     "P123-XYZ-1-RF-SC-P-9999", "p123-abc-zz-01-dr-a-0001", "ARC_Plan_abc_", "ARC__abc"]:
            r.call_as("check_name", N.check_name, (name, ts), {}, shown_args=[name, {"scheme": key, "target": target}])
for ts in [{"delimiter": None, "fields": [{"name": "a"}]}, {"delimiter": "-", "fields": []}, {"fields": [{"name": "a"}]},
           {"delimiter": "-"}, {"delimiter": "--", "fields": [{"name": "a"}, {"name": "b"}]},
           {"delimiter": 5, "fields": [{"name": "a"}]}, {"delimiter": "-", "fields": [{"name": "n7", "length": 1}, {"length": 1}]}]:
    for name in ["x", "x--y", "", "ab-cd", None]:
        r.call("check_name", name, ts)


def check_items(items, scheme, target, *args, **kwargs):
    return N.check_items([tuple(i) for i in items], scheme, target, *args, **kwargs)


ITEMS = [[101, "P123-ABC-ZZ-01-DR-A-0001"], [102, "P123-QQQ-ZZ-01-DR-A-12"], [103, "P123-ABC"], [104, ""],
         [105, "P123-XYZ-1A-RF-SC-P-9999"], [106, "P123-XYZ-1A-RF-SC-Q-9999"], [107, None]]
VIEWS = [[1, "ARC_Plan"], [2, "arc_Plan_abc"], [3, "STR_P"], [4, "XXX_Section_ab"], [5, "ARC_Elevation"], [6, "ARC"]]
MANY = [[i, "bad name %d" % i] for i in range(40)]
for key in sorted(SCHEMES):
    for target in list(N.TARGETS) + ["levels"]:
        for items in (ITEMS, VIEWS, [], MANY):
            r.call_as("check_items", check_items, (items, SCHEMES[key], target), {}, shown_args=[items, key, target])
r.call_as("check_items", check_items, (MANY, SCHEME, "views"), {"label": "plan views", "max_examples": 3},
          shown_args=[MANY, "main", "views"])
r.call_as("check_items", check_items, (VIEWS, SCHEME, "views", "", 0), {}, shown_args=[VIEWS, "main", "views", "", 0])
r.call_as("check_items", check_items, (ITEMS, SCHEME, "sheets", "drawing sheets"), {},
          shown_args=[ITEMS, "main", "sheets", "drawing sheets"])
r.write("naming")
