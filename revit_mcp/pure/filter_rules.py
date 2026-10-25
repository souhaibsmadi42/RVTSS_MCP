# -*- coding: utf-8 -*-
"""View filter rules (RVTSS v2.2): validate user rules and pick the Revit rule kind - Revit independent."""

STRING_OPS = ("equals", "not_equals", "contains", "not_contains", "begins_with", "not_begins_with",
              "ends_with", "not_ends_with", "greater", "greater_or_equal", "less", "less_or_equal")
NUMBER_OPS = ("equals", "not_equals", "greater", "greater_or_equal", "less", "less_or_equal")
VALUELESS_OPS = ("has_value", "has_no_value")
ALL_OPS = tuple(sorted(set(STRING_OPS + NUMBER_OPS + VALUELESS_OPS)))
KINDS = ("string", "double", "integer", "element_id")

# op -> ParameterFilterRuleFactory method
FACTORY = {
    "equals": "CreateEqualsRule", "not_equals": "CreateNotEqualsRule",
    "contains": "CreateContainsRule", "not_contains": "CreateNotContainsRule",
    "begins_with": "CreateBeginsWithRule", "not_begins_with": "CreateNotBeginsWithRule",
    "ends_with": "CreateEndsWithRule", "not_ends_with": "CreateNotEndsWithRule",
    "greater": "CreateGreaterRule", "greater_or_equal": "CreateGreaterOrEqualRule",
    "less": "CreateLessRule", "less_or_equal": "CreateLessOrEqualRule",
    "has_value": "CreateHasValueParameterRule", "has_no_value": "CreateHasNoValueParameterRule",
}


class RuleError(ValueError):
    pass


def infer_kind(value, unit=None, kind=None):
    """string | double | integer | element_id for a rule value (explicit kind wins)."""
    if kind:
        if kind not in KINDS:
            raise RuleError("rule type must be one of %s" % ", ".join(KINDS))
        return kind
    if isinstance(value, bool):
        return "integer"
    if isinstance(value, float) or (unit and isinstance(value, (int, float))):
        return "double"
    if isinstance(value, int):
        return "integer"
    return "string"


def validate_rule(rule):
    """Normalised copy of {parameter, op, value, unit, type} or RuleError."""
    if not isinstance(rule, dict):
        raise RuleError("each rule must be an object {parameter, op, value}")
    param = rule.get("parameter")
    if not param:
        raise RuleError("rule needs 'parameter'")
    op = (rule.get("op") or "equals").lower()
    if op not in ALL_OPS:
        raise RuleError("unknown op '%s'. Use: %s" % (op, ", ".join(ALL_OPS)))
    out = {"parameter": param, "op": op, "unit": rule.get("unit")}
    if op in VALUELESS_OPS:
        out["kind"] = None
        out["value"] = None
        return out
    if "value" not in rule or rule.get("value") is None:
        raise RuleError("op '%s' needs a value" % op)
    kind = infer_kind(rule["value"], rule.get("unit"), rule.get("type"))
    if kind == "string" and op not in STRING_OPS:
        raise RuleError("op '%s' does not apply to text" % op)
    if kind != "string" and op not in NUMBER_OPS:
        raise RuleError("op '%s' needs a text value" % op)
    value = rule["value"]
    if kind == "integer":
        value = int(value) if not isinstance(value, bool) else (1 if value else 0)
    elif kind == "double":
        value = float(value)
    elif kind == "element_id":
        value = int(value)
    else:
        value = u"%s" % value
    out.update({"kind": kind, "value": value})
    return out
