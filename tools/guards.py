# -*- coding: utf-8 -*-
"""Server-side guards (RVTSS v2.2): read-only mode, argument names, response size.

* Read-only mode (``RVTSS_READ_ONLY=1``): only tools annotated readOnlyHint=true
  are registered, so a client cannot even see a tool that changes the model or
  writes files. Pair it with RVTSS_READ_ONLY on the Revit side for defence in depth.
* Argument guard: pydantic silently ignores unknown keys, so a misspelled
  ``dryrun=true`` or ``confirm_=true`` would be dropped and the call would run for
  real. Unknown argument names are refused with ``did_you_mean`` suggestions.
* Response guard: a tool result larger than the budget would flood the model's
  context (or be cut by the client). Oversized results are replaced by a compact
  summary that keeps the status and every scalar field (so a committed change is
  still reported as committed) plus narrowing guidance.
"""
import difflib
import json
import os

from revit_mcp.pure import security as _security


def read_only_enabled(value=None):
    raw = os.environ.get("RVTSS_READ_ONLY") if value is None else value
    return bool(_security.parse_flag(raw, False))


def is_read_only_annotation(ann):
    if ann is None:
        return False
    v = getattr(ann, "readOnlyHint", None)
    if v is None:
        v = getattr(ann, "read_only_hint", None)
    return bool(v)


# ------------------------------------------------------------------ arguments
def unknown_arguments(arguments, schema):
    """[(name, [suggestions])] for keys not declared in the tool's input schema."""
    props = (schema or {}).get("properties") or {}
    if not isinstance(arguments, dict) or not props:
        return []
    known = list(props)
    out = []
    for key in arguments:
        if key in props:
            continue
        lowered = dict((k.lower().replace("_", ""), k) for k in known)
        exact = lowered.get(str(key).lower().replace("_", "").replace("-", ""))
        hints = [exact] if exact else difflib.get_close_matches(str(key), known, n=3, cutoff=0.6)
        out.append((key, hints))
    return out


def argument_error(tool_name, unknown, schema):
    parts = []
    for key, hints in unknown:
        parts.append("'%s'%s" % (key, " (did you mean %s?)" % " or ".join("'%s'" % h for h in hints)
                                 if hints else ""))
    valid = sorted(((schema or {}).get("properties") or {}).keys())
    return ("INVALID_ARGUMENT: unknown argument%s for %s: %s. Nothing was sent to Revit. Valid arguments: %s. "
            "Names are case-sensitive snake_case." % ("s" if len(unknown) > 1 else "", tool_name, ", ".join(parts),
                                                     ", ".join(valid)))


def install_argument_guard(server):
    """Refuse calls with unknown argument names (both MCP SDK majors). Returns True if installed."""
    manager = getattr(server, "_tool_manager", None)
    if manager is None or getattr(manager, "_rvtss_guarded", False):
        return False
    original = manager.call_tool

    async def guarded_call_tool(name, arguments, *args, **kwargs):
        tool = manager.get_tool(name)
        if tool is not None:
            schema = getattr(tool, "parameters", None)
            unknown = unknown_arguments(arguments or {}, schema)
            if unknown:
                from ._compat import ToolError

                raise ToolError(argument_error(name, unknown, schema))
        return await original(name, arguments, *args, **kwargs)

    manager.call_tool = guarded_call_tool
    manager._rvtss_guarded = True
    return True


# ------------------------------------------------------------------- responses
def _kb_env(name, default):
    try:
        return int(float(os.environ.get(name, default)) * 1024)
    except (TypeError, ValueError):
        return int(default * 1024)


def response_limits():
    warn = _kb_env("RVTSS_RESPONSE_WARN_KB", 64)
    budget = _kb_env("RVTSS_RESPONSE_BUDGET_KB", 256)
    return min(warn, budget), max(budget, 4096)


NARROW_HINT = ("Narrow the request: add filters (categories, level, view, name_contains), lower `limit` and page "
               "with `offset`, request fewer `parameters`/`fields`, or use count_only=true. "
               "Raise RVTSS_RESPONSE_BUDGET_KB only if the client can take larger results.")


def summarize(response, max_items=3):
    """Keep scalars, describe lists/dicts by size (with the first few short items)."""
    out = {}
    for k, v in response.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) or len(v) <= 500 else v[:500] + "... [truncated]"
        elif isinstance(v, list):
            sample = [x for x in v[:max_items] if len(json.dumps(x, default=str)) <= 300]
            out[k] = {"omitted_list_items": len(v), "sample": sample}
        elif isinstance(v, dict):
            out[k] = {"omitted_keys": len(v), "keys_sample": sorted(str(x) for x in v)[:10]}
        else:
            out[k] = str(v)[:200]
    return out


def guard_text(text, response=None):
    """Apply the response budget to a formatted tool result."""
    if not isinstance(text, str):
        return text
    warn, budget = response_limits()
    size = len(text.encode("utf-8"))
    if size <= warn:
        return text
    if size <= budget:
        return text + "\n\n[RVTSS: large response (%d KB). %s]" % (size // 1024, NARROW_HINT)
    if isinstance(response, dict) and "output" not in response:
        summary = summarize(response)
        summary["response_guard"] = {
            "code": "RESPONSE_TOO_LARGE", "size_kb": size // 1024, "budget_kb": budget // 1024,
            "note": ("The full result was not returned. Scalar fields above are complete; lists/objects are "
                     "summarised. If this was a change, its status/committed fields still apply - do not "
                     "repeat it."), "hint": NARROW_HINT}
        return json.dumps(summary, indent=2, default=str, ensure_ascii=False)
    head = text[: budget // 2]
    tail = text[-(budget // 8):]
    return ("%s\n\n... [RVTSS RESPONSE_TOO_LARGE: %d KB total, middle omitted; budget %d KB. %s] ...\n\n%s"
            % (head, size // 1024, budget // 1024, NARROW_HINT, tail))


def guard_payload(payload):
    """structuredContent counterpart of guard_text (keeps clients from receiving the dump twice)."""
    if not isinstance(payload, dict):
        return payload
    _warn, budget = response_limits()
    try:
        size = len(json.dumps(payload, default=str).encode("utf-8"))
    except Exception:
        return payload
    if size <= budget:
        return payload
    summary = summarize(payload)
    summary["response_guard"] = {"code": "RESPONSE_TOO_LARGE", "size_kb": size // 1024,
                                 "budget_kb": budget // 1024, "hint": NARROW_HINT}
    return summary
