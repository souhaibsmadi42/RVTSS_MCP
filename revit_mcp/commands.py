# -*- coding: UTF-8 -*-
"""Ribbon command launcher (RVTSS v2.4).

Routes:
    POST /commands/list/   Revit's postable ribbon commands (UI.PostableCommand), filtered by text
    POST /commands/run/    post one command: Revit runs it right after the request returns, exactly as
                           if the user had pressed the button (its dialog or tool opens for the user)

This covers every button RVTSS has no dedicated tool for. The command is not run by RVTSS: it is
queued with UIApplication.PostCommand, so nothing can be verified from the answer. Commands that save,
synchronize, undo or redo are refused here: they have their own guarded tools.
"""
import logging
import re

from . import core
from .core import RvtssError, handle
from .compat import text_type

logger = logging.getLogger(__name__)

# command name pattern -> (reason, tool to use instead)
_BLOCKED = (
    (re.compile(r"^(Undo|Redo)$", re.I), "undo and redo go through the RVTSS ledger", "undo_last_change"),
    (re.compile(r"^(Save|SaveAs.*|SaveSelection)$", re.I), "saving is controlled by the RVTSS save policy",
     "save_document"),
    (re.compile(r"(Synchroni[sz]e|ReloadLatest|RelinquishAllMine)", re.I),
     "worksharing is controlled by the RVTSS sync policy", "sync_with_central"),
    (re.compile(r"^(ExitRevit|Close.*)$", re.I), "closing documents or Revit is not posted from RVTSS",
     "close_document"),
)


def split_words(name):
    """'StructuralFoundationWall' -> 'Structural Foundation Wall' (pure, unit-tested)."""
    out = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", text_type(name))
    return out.replace("_", " ").strip()


def blocked_reason(name):
    """(reason, replacement tool) when a command must not be posted, else None (pure, unit-tested)."""
    for rx, reason, tool in _BLOCKED:
        if rx.search(text_type(name)):
            return reason, tool
    return None


def match_commands(names, contains=None, limit=200):
    """Filter command names: every word of `contains` must appear in the name or its spaced label."""
    words = [w for w in text_type(contains or "").lower().split() if w]
    out = []
    for n in sorted(names):
        hay = (n + " " + split_words(n)).lower()
        if all(w in hay for w in words):
            out.append(n)
    return out[:limit], len(out)


def _ui():
    from Autodesk.Revit import UI

    return UI


def _uiapp():
    from pyrevit import HOST_APP

    return HOST_APP.uiapp


def _all_names():
    import System

    return [text_type(n) for n in System.Enum.GetNames(_ui().PostableCommand)]


def _command_id(name=None, command_id=None):
    UI = _ui()
    if command_id:
        cid = UI.RevitCommandId.LookupCommandId(text_type(command_id))
        if cid is None:
            raise RvtssError("Command id '{}' is not known to Revit".format(command_id), status=404,
                             hint="Use a PostableCommand name from list_revit_commands, or an add-in command id.")
        return cid, text_type(command_id)
    names = _all_names()
    low = dict((n.lower(), n) for n in names)
    key = text_type(name or "").replace(" ", "").lower()
    real = low.get(key)
    if real is None:
        close, _total = match_commands(names, name, 15)
        raise core.not_found("Revit command", name, close or names[:15],
                             hint="list_revit_commands(contains=...) searches the command names.")
    return UI.RevitCommandId.LookupPostableCommandId(getattr(UI.PostableCommand, real)), real


def list_commands(ctx):
    names = _all_names()
    limit = ctx.int("limit", 200, 1, 2000)
    found, total = match_commands(names, ctx.get("contains"), limit)
    check = ctx.bool("check_available", False)
    uiapp = _uiapp() if check else None
    UI = _ui()
    items = []
    for n in found:
        item = {"name": n, "label": split_words(n)}
        blocked = blocked_reason(n)
        if blocked:
            item["blocked"] = "use " + blocked[1]
        if check:
            try:
                item["available_now"] = bool(uiapp.CanPostCommand(
                    UI.RevitCommandId.LookupPostableCommandId(getattr(UI.PostableCommand, n))))
            except Exception:
                item["available_now"] = None
        items.append(item)
    return {"count": total, "returned": len(items), "truncated": total > len(items), "commands": items,
            "note": "These are Revit's own ribbon commands. run_revit_command starts one for the user; "
                    "prefer a dedicated RVTSS tool when one exists."}


def run_command(ctx):
    name, command_id = ctx.get("name"), ctx.get("command_id")
    if not name and not command_id:
        raise RvtssError("Give 'name' (a PostableCommand name) or 'command_id'")
    cid, label = _command_id(name, command_id)
    blocked = blocked_reason(label)
    if blocked:
        raise RvtssError("'{}' is not posted by RVTSS: {}".format(label, blocked[0]), status=403,
                         hint="Use {} instead.".format(blocked[1]), code="POLICY_DENIED")
    uiapp = _uiapp()
    if uiapp.ActiveUIDocument is None:
        raise RvtssError("No document is open in Revit", status=409)
    can = bool(uiapp.CanPostCommand(cid))
    if ctx.dry_run:
        return {"status": "dry_run", "command": label, "label": split_words(label), "available_now": can}
    if not can:
        raise RvtssError("Revit cannot start '{}' right now".format(label), status=409,
                         hint="The command is disabled in the active view or document state (for example a plan "
                              "command in a 3D view, or an open edit mode). Activate a suitable view and retry.")
    core.require_writable("Running the Revit command '{}'".format(label))
    try:
        uiapp.PostCommand(cid)
    except Exception as e:
        raise RvtssError("Revit refused to queue '{}': {}".format(label, text_type(e)), status=409,
                         hint="Only one command can be queued per request, and none while another is running.")
    return {"status": "posted", "command": label, "label": split_words(label),
            "message": "Revit starts this command for the user right after this answer; its dialog or tool is "
                       "now theirs to complete. RVTSS cannot see the outcome: re-read the model to verify."}


def register_command_routes(api):
    @api.route("/commands/list/", methods=["POST"])
    def commands_list_route(doc, request):
        return handle(doc, request, list_commands, needs_doc=False)

    @api.route("/commands/run/", methods=["POST"])
    def commands_run_route(doc, request):
        return handle(doc, request, run_command, needs_doc=False)

    logger.info("RVTSS command launcher routes registered")
