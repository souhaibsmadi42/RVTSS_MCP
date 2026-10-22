# -*- coding: utf-8 -*-
"""Shared schema pieces and helpers for RVTSS tool modules."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .utils import format_response
from ._compat import structured_result, report_progress, log_info, client_supports

LengthUnit = Literal["mm", "cm", "m", "ft", "in"]
ValueUnit = Literal["mm", "cm", "m", "ft", "in", "mm2", "m2", "ft2", "mm3", "m3", "ft3", "deg", "rad", "internal"]
FilterOp = Literal["eq", "ne", "contains", "not_contains", "startswith", "endswith", "regex",
                   "gt", "ge", "lt", "le", "empty", "not_empty", "in", "exists", "missing"]
Scalar = Union[str, float, int, bool, None]


class ParamFilter(BaseModel):
    """Filter on a parameter value (instance first, then type)."""
    name: str = Field(description="Parameter name, BuiltInParameter name (ALL_MODEL_MARK) or shared GUID")
    op: FilterOp = "eq"
    value: Optional[Union[str, float, int, bool, List[Union[str, float, int]]]] = None
    unit: Optional[ValueUnit] = Field(None, description="Unit for numeric comparisons on dimensional params (default mm)")
    case_sensitive: bool = False


class ParameterUpdate(BaseModel):
    element_id: int
    parameter: str = Field(description="Parameter name, BuiltInParameter name or shared GUID")
    value: Scalar = Field(description="New value. Dimensional numbers need 'unit' (or pass a string like '900 mm')")
    unit: Optional[ValueUnit] = None
    target: Literal["auto", "instance", "type"] = Field(
        "auto", description="auto: instance parameter, falling back to the type parameter")


def dump(value):
    """pydantic model / list of models / dict -> plain JSON data."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [dump(v) for v in value]
    if isinstance(value, dict):
        return {k: dump(v) for k, v in value.items() if v is not None}
    return value


def compact(**kwargs) -> Dict[str, Any]:
    """Build a request payload, dropping None values."""
    return {k: dump(v) for k, v in kwargs.items() if v is not None}


async def post(revit_post, endpoint, data, ctx=None, timeout=None):
    if timeout is not None:
        response = await revit_post(endpoint, data, ctx, timeout=timeout)
    else:
        response = await revit_post(endpoint, data, ctx)
    return format_response(response)


DOC_HELP = "Document title or path (default: active)"


HEARTBEAT_SECONDS = 3.0


def _as_data(response):
    if isinstance(response, dict):
        return response, response.get("status") == "error"
    return {"status": "error", "error": str(response)}, True


async def post_structured(revit_post, endpoint, data, ctx=None, timeout=None):
    """Like post(), plus structuredContent (mcp 2.x) with the raw Revit response."""
    response = await call_with_progress(revit_post, endpoint, data, ctx, timeout, endpoint.strip("/"))
    payload, is_error = _as_data(response)
    return structured_result(format_response(response), payload, is_error)


async def call_with_progress(revit_post, endpoint, data, ctx=None, timeout=None, label="Revit"):
    """Run a long Revit call, sending progress heartbeats (elapsed seconds) and log messages.

    Revit executes one request at a time and reports nothing while it runs, so the
    heartbeat tells the client the call is alive rather than a percentage.
    """
    import asyncio
    import time

    if ctx is None:
        if timeout is not None:
            return await revit_post(endpoint, data, ctx, timeout=timeout)
        return await revit_post(endpoint, data, ctx)
    start = time.monotonic()
    await log_info(ctx, "%s: started" % label)
    await report_progress(ctx, 0, None, "%s: started" % label)
    coro = revit_post(endpoint, data, ctx, timeout=timeout) if timeout is not None else revit_post(endpoint, data, ctx)
    task = asyncio.ensure_future(coro)
    while True:
        done, _pending = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
        if done:
            break
        elapsed = time.monotonic() - start
        await report_progress(ctx, round(elapsed, 1), None, "%s: running for %ds" % (label, elapsed))
    response = task.result()
    elapsed = round(time.monotonic() - start, 1)
    await report_progress(ctx, elapsed, elapsed, "%s: finished in %.1fs" % (label, elapsed))
    await log_info(ctx, "%s: finished in %.1fs" % (label, elapsed))
    return response


class _Confirm(BaseModel):
    confirm: bool = Field(description="Apply this change in Revit")


async def elicit_confirmation(ctx, message):
    """Ask the user to confirm. True/False = answer, None = elicitation not available."""
    if ctx is None or not hasattr(ctx, "elicit") or not client_supports(ctx, "elicitation"):
        return None
    try:
        result = await ctx.elicit(message, _Confirm)
    except Exception:
        return None
    return getattr(result, "action", None) == "accept" and bool(getattr(getattr(result, "data", None), "confirm", False))


def _preview_message(response):
    parts = [response.get("message") or "Revit prepared a preview of this change."]
    for key in ("deleted_total", "dependent_elements_deleted", "matched", "count", "succeeded"):
        if key in response:
            parts.append("%s: %s" % (key.replace("_", " "), response[key]))
    return " ".join(str(p) for p in parts) + " Apply it?"


async def post_confirmable(revit_post, endpoint, data, ctx=None, timeout=None, label="Revit"):
    """POST; if Revit answers with a confirmation preview, ask the user via elicitation (when
    the client supports it) and re-run with confirm=true on acceptance. Without elicitation
    the preview is returned unchanged (Claude must pass confirm=true after showing it)."""
    response = await call_with_progress(revit_post, endpoint, data, ctx, timeout, label)
    if not (isinstance(response, dict) and response.get("status") == "preview" and not data.get("confirm")):
        return format_response(response)
    answer = await elicit_confirmation(ctx, _preview_message(response))
    if answer is None:
        return format_response(response)
    if not answer:
        response = dict(response, user_decision="declined", message="The user declined; nothing was changed.")
        return format_response(response)
    confirmed = dict(data, confirm=True)
    confirmed.pop("dry_run", None)
    final = await call_with_progress(revit_post, endpoint, confirmed, ctx, timeout, label)
    if isinstance(final, dict):
        final = dict(final, user_decision="confirmed")
    return format_response(final)
