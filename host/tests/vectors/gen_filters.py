# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/filters.py -> filters.json."""
from _lane_b import Recorder
from revit_mcp.pure import filters as F

r = Recorder(F)
r.extra["ops"] = list(F.OPS)
r.extra["numeric_ops"] = list(F.NUMERIC_OPS)

for v in [None, True, False, 0, 1, -3, 2.5, "2.5", " 7 ", "1e3", "abc", "", "  ", "inf", "-Infinity", "nan", "NaN", "+5",
          "1.", ".5", "0x10", "1,5", [1], {"a": 1}, "12abc", "--1", "1e", "e5", "+", ".", "Infinity", "infinit"]:
    r.call("_num", v)
    r.call("_is_empty", v)

for f in [None, "x", [], {}, {"name": ""}, {"name": None, "op": "eq"}, {"name": "Mark"}, {"name": "Mark", "op": "eq"},
          {"name": "Mark", "op": "bogus", "value": 1}, {"name": "Mark", "op": 5, "value": 1},
          {"name": "Mark", "op": None, "value": 1},
          {"name": "Mark", "op": "empty"}, {"name": "Mark", "op": "not_empty"}, {"name": "Mark", "op": "exists"},
          {"name": "Mark", "op": "missing"}, {"name": "Width", "op": "gt", "value": "wide"},
          {"name": "Width", "op": "gt", "value": "900"}, {"name": "Width", "op": "ge", "value": 900},
          {"name": "Width", "op": "lt", "value": None}, {"name": "Width", "op": "le", "value": True},
          {"name": "Width", "op": "le", "value": [1]}, {"name": "Width", "op": "gt"},
          {"name": 5, "op": "contains"}, {"name": "Mark", "value": "x"}, {"name": "Mark", "value": None},
          {"name": "Mark", "op": "regex", "value": "^\\d{3}$"}, {"name": "Mark", "op": "regex", "value": "("},
          {"name": "Mark", "op": "regex", "value": "[a-"}, {"name": "Mark", "op": "regex", "value": 5},
          {"name": "Mark", "op": "regex", "value": "(?P<n>a)(?P=n)"},
          {"name": "Mark", "op": "in", "value": ["a"]}, {"name": "Mark", "op": "in", "value": "a"},
          {"name": "Mark", "op": "in", "value": 5}, {"name": "Mark", "op": "in", "value": []},
          {"name": "Mark", "op": "contains", "value": 5}, {"name": "Mark", "op": "startswith", "value": None},
          {"name": "Mark", "op": "ne", "value": "x", "extra": 1}]:
    r.call("validate_filter", f)

OPS = list(F.OPS) + ["bogus", None, 5]
TRIPLES = [
    (900, 910.0, "910 mm"), (900, 900.0000001, None), (900, 900.01, None), ("900", 900.0, "900 mm"),
    ("fire", "FIRE DOOR", None), ("Fire", "fire door", "Fire Door"), ("d-", "D-101", None), ("101", "D-101", None),
    ("^\\d{3}$", "101", None), ("^\\d{3}$", "1010", "101"), ("(", "x", None), ("[A-Z]+", "abc", None),
    (["a", "b"], "B", None), (["a", "b"], "c", "A"), ("ab", "a", None), ([1, 2.5], 1, None), ([], "x", None),
    (None, "", None), (None, "x", None), (None, None, None), (None, None, ""), (None, "  ", " "), (None, 0, None),
    ("x", None, None), ("x", "x", None), ("X", "x", None), ("", "", None), ("", "abc", None),
    (5, 5, "5"), (5, "5", None), (5.0, 5, None), ("5.0", 5, None), ("abc", 5, "abc"), ("5", 5.0, "5 mm"),
    (True, 1, None), (True, True, "Yes"), ("yes", True, "Yes"), ("true", True, None), (1, True, None),
    (0, 0.0000001, None), (1000000, 1000000.5, None), (1000000, 1000002, None), (-3, -3.0000001, None),
    ("wide", 910.0, None), (900, "wide", None), (900, None, "900"), (None, 900, None), ("1e3", 1000, None),
    (2.5, 2.5, None), (2.5, "2.5", None), (0.1, 0.1, "0.1"), (12, 12.0, "12.0"), ("12.0", 12, None), ("12", 12.5, None),
    ("mm", 910.5, "910.5 mm"), (" x ", " X ", None), ("a.c", "abc", None), ("None", None, None),
    (u"Été", u"étÉ", None), ("door", "Door", "DOOR"), ("^a", "A\nb", "b\na"),
]
for op in OPS:
    for expected, raw, display in TRIPLES:
        r.call("match", op, expected, raw, display)
        r.call("match", op, expected, raw, display, True, True)
        r.call("match", op, expected, raw, display, exists=False)
        r.call("match", op, expected, raw, display, case_sensitive=True)
for op in ["in", "regex", "contains", "eq"]:
    for expected in [5, None, 2.5, True]:
        r.call("match", op, expected, "a5", "None")

for q, parts in [("fire door", ["Doors", "Single-Flush", "Fire 60", None]), ("fire window", ["Doors", "Fire 60"]),
                 ("", ["a"]), (None, ["a"]), ("   ", ["a"]), ("   ", []), ("a", []), ("A  b\tc", ["C b", "", "a"]),
                 ("60", ["Fire", 60]), ("true", [True, False]), ("0", [0, "x"]), ("x y", ["xy"]), ("x y", ["x", "y"]),
                 ("1.5", [1.5]), ("door", [None, None]), (u"ÉTÉ", [u"été"]), ("a b", ["A\nB"]),
                 (5, ["5"]), (0, ["5"]), ([], ["a"]), (["a"], ["a"]), ("re fi", ["Fire"]), ("a", ["b", "ca"])]:
    r.call("text_match", q, parts)

ITEMS = list(range(10))
for args in [(ITEMS,), (ITEMS, 8, 5), (ITEMS, 0, 5), (ITEMS, 5, 5), (ITEMS, 10, 5), (ITEMS, 20, 5), (ITEMS, -3, 4),
             (ITEMS, 0, 0), (ITEMS, 0, -2), (ITEMS, None, None), (ITEMS, 3, None), (ITEMS, None, 3), (ITEMS, 9, 1),
             (ITEMS, 0, 10), (ITEMS, 0, 11), (ITEMS, 0, 9), ([], 0, 5), ([], 3, 5), (["a", {"b": 1}, None], 1, 1),
             (ITEMS, 2), (list(range(250)),), (list(range(250)), 100), (list(range(250)), 200, 100)]:
    r.call("paginate", *args)
r.call("paginate", ITEMS, offset=4, limit=3)
r.call("paginate", ITEMS, limit=3)
r.write("filters")
