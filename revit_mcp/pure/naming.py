# -*- coding: utf-8 -*-
"""ISO 19650-style field-by-field name checks driven by qc_rules.json ("iso19650" section).

Scheme (see docs/examples/qc_rules.iso19650.json):
{
  "delimiter": "-",
  "fields": [
    {"name": "project",    "values": ["P123"]},
    {"name": "originator", "values": ["ABC", "XYZ"]},
    {"name": "volume",     "pattern": "^(ZZ|XX|[A-Z0-9]{2})$"},
    {"name": "level",      "values": ["00", "01", "02", "B1", "RF", "ZZ", "XX"]},
    {"name": "type",       "values": ["DR", "M3", "SH", "SC"]},
    {"name": "role",       "values": ["A", "S", "M", "E", "P"]},
    {"name": "number",     "pattern": "^\\d{4}$"}
  ],
  "targets": {
    "sheets":         {"source": "number", "severity": "error"},
    "views":          {"fields": [...], "delimiter": "_"},
    "view_templates": {...}, "families": {...}, "types": {...}, "worksets": {...}
  }
}
A target uses the top-level fields unless it defines its own. Each field may set
"values" (allowed list), "pattern" (regex), "length" / "min_length" / "max_length",
"optional": true (may be empty) and "case_sensitive" (default true).
"""
import re

from . import rules as R

TARGETS = ("sheets", "views", "view_templates", "families", "types", "worksets")


class SchemeError(ValueError):
    pass


def target_scheme(scheme, target):
    """Effective {delimiter, fields, severity, source} for one target, or None if not configured."""
    targets = scheme.get("targets") or {}
    if target not in targets:
        return None
    t = targets.get(target) or {}
    fields = t.get("fields") or scheme.get("fields")
    if not fields:
        raise SchemeError("iso19650: no fields defined for target '%s'" % target)
    out = {"delimiter": t.get("delimiter", scheme.get("delimiter", "-")), "fields": fields,
           "severity": t.get("severity", scheme.get("severity", "warning")), "source": t.get("source", "name"),
           "description": t.get("description") or scheme.get("description")}
    for f in fields:
        if f.get("pattern"):
            try:
                re.compile(f["pattern"])
            except re.error as e:
                raise SchemeError("iso19650: invalid pattern for field '%s': %s" % (f.get("name"), e))
    return out


def check_field(field, value):
    """Reason the value is invalid for the field, or None."""
    if value == "" or value is None:
        return None if field.get("optional") else "empty"
    cs = field.get("case_sensitive", True)
    allowed = field.get("values")
    if allowed:
        pool = allowed if cs else [str(a).lower() for a in allowed]
        if (value if cs else value.lower()) not in pool:
            shown = ", ".join(str(a) for a in allowed[:12]) + (" ..." if len(allowed) > 12 else "")
            return "'%s' not in allowed values (%s)" % (value, shown)
    pattern = field.get("pattern")
    if pattern and not re.search(pattern, value, 0 if cs else re.IGNORECASE):
        return "'%s' does not match %s" % (value, pattern)
    n = len(value)
    if field.get("length") is not None and n != int(field["length"]):
        return "'%s' must be %s characters" % (value, field["length"])
    if field.get("min_length") is not None and n < int(field["min_length"]):
        return "'%s' is shorter than %s" % (value, field["min_length"])
    if field.get("max_length") is not None and n > int(field["max_length"]):
        return "'%s' is longer than %s" % (value, field["max_length"])
    return None


def check_name(name, tscheme):
    """[(field_name, reason)] for one name ([] = compliant)."""
    delim = tscheme["delimiter"]
    fields = tscheme["fields"]
    parts = (name or "").split(delim) if delim else [name or ""]
    required = len([f for f in fields if not f.get("optional")])
    if len(parts) > len(fields) or len(parts) < required:
        return [("structure", "expected %d field(s) separated by '%s', found %d" % (len(fields), delim, len(parts)))]
    parts = parts + [""] * (len(fields) - len(parts))
    errors = []
    for f, v in zip(fields, parts):
        reason = check_field(f, v)
        if reason:
            errors.append((f.get("name", "?"), reason))
    return errors


def check_items(items, scheme, target, label=None, max_examples=15):
    """items: [(id, name)] -> findings (one summary finding per violated field)."""
    ts = target_scheme(scheme, target)
    if ts is None:
        return []
    label = label or target.replace("_", " ")
    per_field = {}
    bad_ids = []
    examples = []
    for eid, name in items:
        errs = check_name(name, ts)
        if not errs:
            continue
        bad_ids.append(eid)
        if len(examples) < max_examples:
            examples.append({"id": eid, "name": name, "errors": ["%s: %s" % e for e in errs]})
        for field, _reason in errs:
            per_field.setdefault(field, []).append(eid)
    if not bad_ids:
        return []
    return [R.finding("iso19650", ts["severity"], "%d of %d %s do not follow the naming scheme" % (
        len(bad_ids), len(items), label), bad_ids, target=target,
        recommendation=ts.get("description") or "Rename to the project naming standard (batch_rename with dry_run).",
        fields_violated=dict((k, len(v)) for k, v in sorted(per_field.items())),
        examples=examples, scheme=[f.get("name") for f in ts["fields"]], delimiter=ts["delimiter"])]
