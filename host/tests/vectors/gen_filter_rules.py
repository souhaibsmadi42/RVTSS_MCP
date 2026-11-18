# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/filter_rules.py -> filter_rules.json.
Run: uv run --project . python host/tests/vectors/gen_filter_rules.py"""
from _lane_c import Recorder
from revit_mcp.pure import filter_rules as FR

rec = Recorder("filter_rules")
rec.extra["constants"] = {"STRING_OPS": list(FR.STRING_OPS), "NUMBER_OPS": list(FR.NUMBER_OPS),
                          "VALUELESS_OPS": list(FR.VALUELESS_OPS), "ALL_OPS": list(FR.ALL_OPS), "KINDS": list(FR.KINDS),
                          "FACTORY": FR.FACTORY}


def infer_kind(value, unit="<default>", kind="<default>"):
    if unit == "<default>":
        return FR.infer_kind(value)
    if kind == "<default>":
        return FR.infer_kind(value, unit)
    return FR.infer_kind(value, unit, kind)


def validate_rule(rule):
    out = FR.validate_rule(rule)
    # 900 and 900.0 are the same number in JSON: record the Python type of the value as well
    return {"rule": out, "value_type": type(out["value"]).__name__}


VALUES = [None, True, False, 0, 1, -5, 900, 2 ** 40, 0.0, 1.5, -2.0, "", "D", "12", "1.5", [1], {"a": 1}]
for v in VALUES:
    rec.call("infer_kind", infer_kind, v)
    for unit in (None, "", "mm", 0, 1):
        rec.call("infer_kind", infer_kind, v, unit)
        for kind in (None, "", "string", "double", "integer", "element_id", "text", "Integer", 1, ["string"]):
            rec.call("infer_kind", infer_kind, v, unit, kind)

for rule in (None, "text", [], 5, {},
             {"parameter": "Fire Rating", "op": "has_value"},
             {"parameter": "Fire Rating", "op": "HAS_NO_VALUE", "value": 5, "unit": "mm", "type": "bogus"},
             {"parameter": "Width", "op": "greater", "value": 900, "unit": "mm"},
             {"parameter": "Mark", "op": "contains", "value": "D"},
             {"parameter": "Is Fire", "value": True},
             {"parameter": "Is Fire", "value": False, "op": None},
             {"parameter": "Is Fire", "value": True, "unit": "mm"},
             {"op": "equals", "value": 1}, {"parameter": "", "value": 1}, {"parameter": None, "value": 1},
             {"parameter": 0, "value": 1}, {"parameter": 12345, "value": 1}, {"parameter": ["a"], "value": "x"},
             {"parameter": "x", "op": "near", "value": 1}, {"parameter": "x", "op": "contains", "value": 5},
             {"parameter": "x", "op": "equals"}, {"parameter": "x", "op": "equals", "value": None},
             {"parameter": "x", "op": "", "value": 1}, {"parameter": "x", "op": "Equals", "value": "A"},
             {"parameter": "x", "op": "has_value", "unit": "m"}, {"parameter": "x", "op": "has value"},
             {"parameter": "x", "op": "contains", "value": True}, {"parameter": "x", "op": "contains", "value": 1.5},
             {"parameter": "x", "op": "begins_with", "value": "A", "unit": "mm"},
             {"parameter": "x", "op": "less", "value": "A"}, {"parameter": "x", "op": "less", "value": "5", "unit": "mm"},
             {"parameter": "x", "value": 1.5}, {"parameter": "x", "value": 2.0}, {"parameter": "x", "value": -3},
             {"parameter": "x", "value": 3, "unit": "mm"}, {"parameter": "x", "value": 2 ** 40},
             {"parameter": "x", "value": 0}, {"parameter": "x", "value": 0.0}, {"parameter": "x", "value": ""},
             {"parameter": "x", "value": [1, 2]}, {"parameter": "x", "value": {"a": 1}},
             {"parameter": "x", "value": [1, 2], "op": "greater"},
             {"parameter": "x", "value": "12", "type": "integer"}, {"parameter": "x", "value": " 12 ", "type": "integer"},
             {"parameter": "x", "value": "1.5", "type": "integer"}, {"parameter": "x", "value": "abc", "type": "integer"},
             {"parameter": "x", "value": 2.7, "type": "integer"}, {"parameter": "x", "value": -2.7, "type": "integer"},
             {"parameter": "x", "value": True, "type": "integer"}, {"parameter": "x", "value": False, "type": "double"},
             {"parameter": "x", "value": "1.5", "type": "double"}, {"parameter": "x", "value": "abc", "type": "double"},
             {"parameter": "x", "value": 7, "type": "double"}, {"parameter": "x", "value": "1e3", "type": "double"},
             {"parameter": "x", "value": 123456, "type": "element_id"}, {"parameter": "x", "value": "123456", "type": "element_id"},
             {"parameter": "x", "value": 12.9, "type": "element_id"}, {"parameter": "x", "value": "x", "type": "element_id"},
             {"parameter": "x", "value": True, "type": "element_id"},
             {"parameter": "x", "value": 5, "type": "string"}, {"parameter": "x", "value": 1.0, "type": "string"},
             {"parameter": "x", "value": True, "type": "string"}, {"parameter": "x", "value": 0.1, "type": "string", "op": "ends_with"},
             {"parameter": "x", "value": 5, "type": "string", "op": "greater"},
             {"parameter": "x", "value": 5, "type": "text"}, {"parameter": "x", "value": 5, "type": ""},
             {"parameter": "x", "value": 5, "type": None, "unit": ""},
             {"parameter": "x", "value": [1], "type": "integer"}, {"parameter": "x", "value": [1], "type": "double"},
             {"parameter": "x", "value": 5, "op": 5},
             {"parameter": "Comments", "op": "not_contains", "value": "é ü", "extra": "ignored"}):
    rec.call("validate_rule", validate_rule, rule)
for op in FR.ALL_OPS:
    for value in ("A", 5, 5.5, True):
        rec.call("validate_rule", validate_rule, {"parameter": "P", "op": op, "value": value})

rec.save()
