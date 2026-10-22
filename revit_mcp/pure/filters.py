# -*- coding: utf-8 -*-
"""Value matching for parameter filters and free-text search."""
import re

try:
    basestring  # noqa: F821  (IronPython 2.7)
except NameError:  # CPython 3
    basestring = str

OPS = ("eq", "ne", "contains", "not_contains", "startswith", "endswith", "regex",
       "gt", "ge", "lt", "le", "empty", "not_empty", "in", "exists", "missing")

NUMERIC_OPS = ("gt", "ge", "lt", "le")


class FilterError(ValueError):
    pass


def _num(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _is_empty(v):
    return v is None or (isinstance(v, basestring) and v.strip() == "")


def validate_filter(f):
    if not isinstance(f, dict):
        raise FilterError("Each parameter filter must be an object")
    if not f.get("name"):
        raise FilterError("Parameter filter is missing 'name'")
    op = f.get("op", "eq")
    if op not in OPS:
        raise FilterError("Unknown filter op '%s'. Use one of: %s" % (op, ", ".join(OPS)))
    if op in ("empty", "not_empty", "exists", "missing"):
        return
    if "value" not in f:
        raise FilterError("Filter on '%s' with op '%s' needs a 'value'" % (f["name"], op))
    if op in NUMERIC_OPS and _num(f["value"]) is None:
        raise FilterError("Filter op '%s' needs a numeric value" % op)
    if op == "regex":
        try:
            re.compile(f["value"])
        except re.error as ex:
            raise FilterError("Invalid regex '%s': %s" % (f["value"], ex))
    if op == "in" and not isinstance(f["value"], (list, tuple)):
        raise FilterError("Filter op 'in' needs a list value")


def match(op, expected, raw, display, exists=True, case_sensitive=False):
    """Evaluate one filter.

    raw: comparable value (number for numeric params, string otherwise),
         already converted to the filter's unit by the caller.
    display: the user-facing string (AsValueString) or None.
    exists: whether the parameter exists on the element.
    """
    if op == "exists":
        return exists
    if op == "missing":
        return not exists
    if not exists:
        return op in ("ne", "not_contains", "empty")
    if op == "empty":
        return _is_empty(raw) and _is_empty(display)
    if op == "not_empty":
        return not (_is_empty(raw) and _is_empty(display))

    if op in NUMERIC_OPS:
        a, b = _num(raw), _num(expected)
        if a is None or b is None:
            return False
        return {"gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]

    # numeric equality with tolerance when both sides are numbers
    if op in ("eq", "ne") and not isinstance(raw, basestring) and _num(expected) is not None \
            and _num(raw) is not None:
        same = abs(_num(raw) - _num(expected)) <= 1e-6 * max(1.0, abs(_num(expected)))
        return same if op == "eq" else not same

    candidates = [c for c in (raw, display) if c is not None]
    texts = [u"%s" % c for c in candidates]
    if not case_sensitive:
        texts = [t.lower() for t in texts]

    def norm(x):
        x = u"%s" % x
        return x if case_sensitive else x.lower()

    if op == "eq":
        return norm(expected) in texts
    if op == "ne":
        return norm(expected) not in texts
    if op == "contains":
        return any(norm(expected) in t for t in texts)
    if op == "not_contains":
        return not any(norm(expected) in t for t in texts)
    if op == "startswith":
        return any(t.startswith(norm(expected)) for t in texts)
    if op == "endswith":
        return any(t.endswith(norm(expected)) for t in texts)
    if op == "in":
        wanted = set(norm(v) for v in expected)
        return any(t in wanted for t in texts)
    if op == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        rx = re.compile(expected, flags)
        return any(rx.search(u"%s" % c) for c in candidates)
    raise FilterError("Unknown op %s" % op)


def text_match(query, haystack_parts):
    """All whitespace-separated query tokens must appear in the combined text."""
    if not query:
        return True
    hay = u" ".join(u"%s" % p for p in haystack_parts if p).lower()
    return all(tok in hay for tok in query.lower().split())


def paginate(items, offset=0, limit=100):
    total = len(items)
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 100))
    page = items[offset:offset + limit]
    nxt = offset + limit if offset + limit < total else None
    return page, {"total": total, "offset": offset, "limit": limit, "next_offset": nxt}
