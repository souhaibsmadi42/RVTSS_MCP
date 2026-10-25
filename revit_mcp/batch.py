# -*- coding: UTF-8 -*-
"""Atomic batches (RVTSS v2.2).

Routes:
    POST /batch/   run up to 20 RVTSS route payloads inside one TransactionGroup

The MCP side (tools/batch_tools.py) builds each payload with the real tool and
sends {commands: [{index, tool, endpoint, payload}], continue_on_error, dry_run}.
Each command runs through its normal route handler (its own named transaction,
failure collection and error envelope). The group is assimilated into one undo
step when every command succeeded, and rolled back on the first failure (unless
continue_on_error), for dry_run, or when anything unexpected happens.
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .utils import normalize_string

logger = logging.getLogger(__name__)

MAX_COMMANDS = 20
# path -> raw (unprotected) route handler, filled by registry.RecordingAPI
ROUTE_TABLE = {}
# Revit-side allowlist (the MCP side has its own): single-document edits that open their own transaction
BATCHABLE_ENDPOINTS = (
    "/set_parameters/", "/bulk_update_parameter/", "/transform_elements/", "/delete_elements/",
    "/create_elements/", "/element_types/", "/views/create/", "/views/graphics/", "/sheets/manage/",
    "/schedules/create/", "/batch_rename/", "/groups/manage/", "/parameters/global/", "/parameters/map/",
    "/annotation/tag/", "/annotation/text/", "/materials/manage/", "/views/filters/", "/sheets/revisions/",
    "/worksets/manage/",
)


class _SubRequest(object):
    """Stands in for a pyRevit Request when a handler is called in-process."""

    def __init__(self, data):
        self.data = data
        self.query_params = {}
        self.headers = {}


def _arg_names(func):
    import inspect

    try:
        return list(inspect.getargspec(func).args)
    except (AttributeError, ValueError, TypeError):
        return list(inspect.signature(func).parameters)  # novermin (IronPython 3 path)


def unpack_response(resp):
    """pyRevit Response (or the test stub dict) -> (http_status, data dict)."""
    if isinstance(resp, dict) and "data" in resp and "status" in resp and len(resp) <= 3:
        return resp.get("status") or 200, resp.get("data") or {}
    status = getattr(resp, "status", 200) or 200
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp
    return status, data if isinstance(data, dict) else {"status": "error", "error": "non-JSON response"}


def classify(http_status, data):
    """'ok' | 'needs_confirmation' | 'failed' for one sub-result."""
    st = (data or {}).get("status")
    if http_status >= 400 or st == "error":
        return "failed"
    if st == "preview" or data.get("requires_confirmation"):
        return "needs_confirmation"
    return "ok"


def _brief(data):
    """Sub-results without bulky lists (the batch answer must stay readable)."""
    out = {}
    for k, v in (data or {}).items():
        if isinstance(v, list) and len(v) > 25:
            out[k] = v[:25]
            out[k + "_truncated"] = len(v)
        else:
            out[k] = v
    return out


def run_batch(ctx):
    doc = ctx.doc
    core.check_modifiable(doc)
    commands = ctx.list("commands")
    if not commands:
        raise RvtssError("'commands' is required (1-{} commands)".format(MAX_COMMANDS))
    if len(commands) > MAX_COMMANDS:
        raise RvtssError("A batch takes at most {} commands, got {}".format(MAX_COMMANDS, len(commands)),
                         hint="Split the work into several batches (each is its own undo step).")
    dry = ctx.dry_run
    if not dry:
        core.require_writable("batch_execute")
    keep_going = ctx.bool("continue_on_error", False)
    target_title = normalize_string(doc.Title)
    plan = []
    for i, cmd in enumerate(commands):
        endpoint = (cmd or {}).get("endpoint")
        if endpoint not in BATCHABLE_ENDPOINTS:
            raise RvtssError("Command {} ({}) is not batchable".format(i, endpoint), status=400,
                             batchable=list(BATCHABLE_ENDPOINTS))
        func = ROUTE_TABLE.get(endpoint)
        if func is None:
            raise RvtssError("Command {}: route {} is not registered".format(i, endpoint), status=500)
        payload = dict((cmd or {}).get("payload") or {})
        payload.pop("dry_run", None)
        sub_doc = payload.get("document")
        if sub_doc and not core.resolve_document(ctx.active_doc, sub_doc).Equals(doc):
            raise RvtssError("Command {} targets document '{}' but the batch runs on '{}'".format(
                i, sub_doc, target_title), hint="A batch is one transaction group on one document.")
        if ctx.data.get("document"):
            payload["document"] = ctx.data.get("document")
        plan.append((cmd.get("index", i), cmd.get("tool") or endpoint, func, payload))

    results = []
    failed = False
    group = DB.TransactionGroup(doc, "RVTSS: " + (ctx.get("name") or "batch of {} commands".format(len(plan))))
    group.Start()
    core.set_batch_state(True, dry)
    try:
        for index, tool, func, payload in plan:
            kwargs = {}
            for a in _arg_names(func):
                if a == "doc":
                    kwargs[a] = ctx.active_doc
                elif a == "uidoc":
                    kwargs[a] = ctx.uidoc
                elif a == "request":
                    kwargs[a] = _SubRequest(payload)
            http_status, data = unpack_response(func(**kwargs))
            outcome = classify(http_status, data)
            entry = {"index": index, "tool": tool, "outcome": outcome, "result": _brief(data)}
            if outcome == "needs_confirmation":
                entry["hint"] = "This command only produced a preview; add confirm=true to its arguments."
            results.append(entry)
            if outcome != "ok":
                failed = True
                if not keep_going:
                    break
        if dry or (failed and not keep_going):
            group.RollBack()
            rolled_back = True
        else:
            group.Assimilate()
            rolled_back = False
    except Exception:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        raise
    finally:
        core.set_batch_state(False)
    ran = len(results)
    out = {"commands": len(plan), "ran": ran, "succeeded": len([r for r in results if r["outcome"] == "ok"]),
           "failed": len([r for r in results if r["outcome"] != "ok"]), "rolled_back": rolled_back,
           "committed": not rolled_back, "results": results, "document": target_title}
    if ran < len(plan):
        out["not_run"] = [p[0] for p in plan[ran:]]
    if dry:
        out["status"] = "dry_run"
        out["message"] = "Dry run: every command ran and the whole group was rolled back. Nothing was modified."
    elif rolled_back:
        out["status"] = "error"
        out["error"] = "Command {} failed; the whole batch was rolled back - nothing was changed.".format(
            next(r["index"] for r in results if r["outcome"] != "ok"))
        out["hint"] = "Fix the failing command (see results) and run the batch again."
    elif failed:
        out["status"] = "partial"
        out["message"] = "continue_on_error: failed commands changed nothing; the others are kept as one undo step."
    else:
        out["message"] = "All commands committed as one undo step."
    return out


def register_batch_routes(api):
    @api.route("/batch/", methods=["POST"])
    def batch_route(doc, uidoc, request):
        return handle(doc, request, run_batch, uidoc=uidoc)

    logger.info("RVTSS batch route registered")
