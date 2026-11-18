# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/rules.py -> rules.json."""
from _lane_b import Recorder
from revit_mcp.pure import rules as R

r = Recorder(R)
r.extra["severities"] = list(R.SEVERITIES)

for sev in ["info", "warning", "error", "critical", "fatal", "", None, 2, "ERROR", True]:
    r.call("severity_rank", sev)


def finding(args, extra):
    return R.finding(*args, **extra)


# args are positional; "extra" are the **extra keyword arguments
FINDING_CASES = [
    (["x", "error", "m"], {}),
    (["x", "fatal", "m"], {}),
    (["x", None, "m"], {}),
    (["x", "info", "m", [1, 2, 3]], {}),
    (["x", "critical", "m", list(range(80))], {}),
    (["x", "error", "m", list(range(50))], {}),
    (["x", "error", "m", list(range(51))], {}),
    (["x", "error", "m", [1, 2, 3], "Fix it"], {}),
    (["x", "error", "m", [1, 2, 3], ""], {}),
    (["x", "error", "m", [1, 2, 3], None, 7], {}),
    (["x", "error", "m", [1, 2, 3], None, 0], {}),
    (["x", "error", "m", None, None, None], {}),
    (["x", "error", "m", [], "r", None, 2], {}),
    (["x", "error", "m", [1, 2, 3, 4, 5], "r", None, 2], {}),
    (["x", "error", "m", [1, 2, 3, 4, 5], "r", None, 0], {}),
    (["x", "error", "m", [1, 2, 3, 4, 5], "r", None, -2], {}),
    (["x", "error", "m", [1, 2, 3, 4, 5], "r", None, 5], {}),
    (["x", "error", "m", ["a", None, 2.5]], {}),
    (["x", "warning", "m", [1]], {"examples": ["a", "b"], "target": "views"}),
    (["x", "warning", "m", [1, 2]], {"note": None, "severity_was": "kept as given", "extra_count": 99}),
    (["x", "warning", "m"], {"nested": {"a": [1, {"b": None}]}}),
]
for args, extra in FINDING_CASES:
    r.call_as("finding", finding, (args, extra), {})

F1 = R.finding("a", "info", "m", [1])
F2 = R.finding("b", "error", "m", [1, 2])
F3 = R.finding("c", "error", "m", [1, 2, 3])
F4 = R.finding("a", "critical", "m")
F5 = R.finding("d", "warning", "m", count=10)
F6 = R.finding("e", "warning", "m", [1, 2])
F7 = {"check": "odd", "severity": "fatal", "message": "custom severity"}
F8 = R.finding("f", "error", "m", [1, 2], count=2.5)
F9 = R.finding("g", "error", "m", [9, 8])
LISTS = [[], [F1], [F1, F2], [F2, F1], [F1, F2, F3, F4, F5, F6], [F6, F5, F4, F3, F2, F1], [F2, F9, F3, F8], [F9, F2],
         [F7], [F1, F7, F4], [F5, F6, F1, F1], [{"check": "x"}], [{"severity": "info"}], ["text"],
         [{"check": "x", "severity": "info", "count": "many"}]]
for fs in LISTS:
    r.call("summarize", fs)
    r.call("sort_findings", fs)


def check_names(items, rule, check_name, label):
    return R.check_names([tuple(i) for i in items], rule, check_name, label)


def check_duplicate_names(items, check_name, label):
    return R.check_duplicate_names([tuple(i) for i in items], check_name, label)


ITEM_SETS = [
    [[1, "A-101"], [2, "bad"]], [[1, "A-101"], [2, "B-202"]], [], [[1, None], [2, ""], [3, "A-101"]],
    [[i, "bad %d" % i] for i in range(14)], [[i, "bad %d" % i] for i in range(60)], [["x", "A-1"], [None, "zz"]],
    [[1, "a-101"], [2, "A-1010"], [3, "xA-101"]],
]
RULE_SETS = [
    {"pattern": "^[A-Z]-\\d{3}$"}, {"pattern": "^[A-Z]-\\d{3}$", "severity": "error", "description": "Sheet numbers: X-000"},
    {"pattern": "("}, {"pattern": ""}, {}, {"pattern": None}, {"pattern": "^[A-Z]-\\d{3}$", "severity": "bogus", "description": ""},
    {"pattern": "[A-Z]-\\d{3}"}, {"pattern": "^(?P<d>[A-Z])-"}, {"pattern": "^$"}, {"pattern": "[a-"}, {"pattern": 5},
    {"pattern": "^a", "severity": None},
]
for items in ITEM_SETS:
    for rule in RULE_SETS:
        r.call_as("check_names", check_names, (items, rule, "naming", "sheets"), {})

for items in [[[1, "A"], [2, "a "], [3, "B"]], [], [[1, "A"], [2, "B"]], [[1, None], [2, ""], [3, "  "], [4, None]],
              [[1, "x"], [2, "X"], [3, " x"], [4, "y"], [5, "Y"], [6, "z"]],
              [[i, "name %d" % (i % 13)] for i in range(40)], [[i, "same"] for i in range(70)],
              [[1, "b"], [2, "a"], [3, "B"], [4, "A"], [5, "c"]], [[1, u"Été"], [2, u"éTÉ"]]]:
    r.call_as("check_duplicate_names", check_duplicate_names, (items, "naming", "sheet"), {})

NAME_LISTS = [
    ["Door 900", "Door_900", "Window"], [], ["a"], ["Door", "door", "DOOR "], ["", None, "x", "_-. "],
    ["Single Flush 900x2100", "Single-Flush 900 x 2100", "Single Flush 900x2400", "Double Flush 900x2100"],
    ["M_Rectangular Column", "M_Rectangular Columns", "M_Round Column", "Rectangular Column"],
    ["abcdefghij", "abcdefghik", "abcdefghijk", "xbcdefghij", "abcdefghi"],
    ["Wall-Ext-200", "Wall.Ext.200", "Wall Ext 200", "WallExt200", "Wall_Ext_201"],
    ["aaaaaaaaaaaaaaaaaaaaaaaab", "aaaaaaaaaaaaaaaaaaaaaaaac", "baaaaaaaaaaaaaaaaaaaaaaaa"],
    ["Curtain Wall Dbl Glass", "Curtain Wall Sgl Glass", "Curtain Wall-Store Front-Dbl", "Curtain Wall Dbl Glass 2"],
    ["abab", "baba", "abba", "aabb"], ["kitten", "sitting", "mitten", "kitchen"],
    ["Basic Wall Generic - 200mm", "Basic Wall Generic - 300mm", "Basic Wall Generic - 200 mm"],
]
for names in NAME_LISTS:
    r.call("similar_names", names)
    for th in (0.5, 0.8, 0.95, 1.0, 0.0):
        r.call("similar_names", names, th)
r.call("similar_names", ["abcd", "abce"], threshold=0.75)
r.write("rules")
