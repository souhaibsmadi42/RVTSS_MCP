# -*- coding: UTF-8 -*-
"""Undo the last RVTSS change, safely (RVTSS v2.3).

Routes:
    POST /undo/   action=status: the latest undo steps in the document and who made them
                  action=undo:   undo the latest step, only if RVTSS made it

The Revit API has no undo call. RVTSS listens to Application.DocumentChanged and keeps a
small ledger per document of committed / undone / redone steps, marking the ones committed while
an RVTSS request was running. Undo posts Revit's own Undo command, and only when the latest
step in the document is an RVTSS step, so it never undoes the user's own work. The command runs
right after this request returns; callers re-read the model to verify.
"""
import logging
import time


from . import core
from .core import RvtssError, handle
from .compat import text_type
from .utils import normalize_string

logger = logging.getLogger(__name__)

_LEDGER = {}   # document key -> [entry, ...] (oldest first)
_REDO = {}
_STATE = {"installed": False, "error": None}
_MAX = 50
_SLOT = "RVTSS_DOCUMENT_CHANGED_HANDLER"


def _key(doc):
    return (doc.PathName or doc.Title or "").lower()


def _on_changed(sender, args):
    try:
        doc = args.GetDocument()
        op = text_type(args.Operation)
        names = [normalize_string(n) for n in args.GetTransactionNames()]
        k = _key(doc)
        stack = _LEDGER.setdefault(k, [])
        req = core.ACTIVE_REQUEST
        if op.endswith("TransactionCommitted"):
            rv = bool(req.get("method")) and all(n.startswith("RVTSS") for n in names)
            top = stack[-1] if stack else None
            if rv and top is not None and top.get("rvtss") and top.get("seq") == req.get("seq"):
                top["names"].extend(names)  # same request, e.g. an assimilated transaction group
            else:
                stack.append({"names": names, "rvtss": rv, "tool": req.get("method") if rv else None,
                              "seq": req.get("seq") if rv else None, "time": time.strftime("%H:%M:%S"),
                              "added": args.GetAddedElementIds().Count,
                              "modified": args.GetModifiedElementIds().Count,
                              "deleted": args.GetDeletedElementIds().Count})
            del stack[:-_MAX]
            _REDO.pop(k, None)
        elif op.endswith("TransactionUndone"):
            if stack:
                _REDO.setdefault(k, []).append(stack.pop())
        elif op.endswith("TransactionRedone"):
            if _REDO.get(k):
                stack.append(_REDO[k].pop())
        elif op.endswith("TransactionGroupRolledBack"):
            # an RVTSS dry run: its inner commits were recorded above, then thrown away with the group
            if req.get("method"):
                while stack and stack[-1].get("rvtss") and stack[-1].get("seq") == req.get("seq"):
                    stack.pop()
    except Exception as e:  # never break Revit's event chain
        _STATE["error"] = text_type(e)


def install(app):
    """Subscribe once per Revit session (pyRevit reloads replace the previous handler)."""
    try:
        import System
        from System import EventHandler
        from Autodesk.Revit.DB.Events import DocumentChangedEventArgs

        domain = System.AppDomain.CurrentDomain
        old = domain.GetData(_SLOT)
        if old is not None:
            try:
                app.DocumentChanged -= old
            except Exception:
                pass
        handler = EventHandler[DocumentChangedEventArgs](_on_changed)
        app.DocumentChanged += handler
        domain.SetData(_SLOT, handler)
        _STATE["installed"] = True
        _STATE["error"] = None
    except Exception as e:
        _STATE["installed"] = False
        _STATE["error"] = text_type(e)
        logger.error("RVTSS undo listener not installed: %s", e)
    return _STATE["installed"]


def _undo_command_id():
    from Autodesk.Revit import UI

    pc = getattr(UI.PostableCommand, "Undo", None)
    if pc is not None:
        try:
            return UI.RevitCommandId.LookupPostableCommandId(pc)
        except Exception:
            pass
    return UI.RevitCommandId.LookupCommandId("ID_EDIT_UNDO")


def undo(ctx):
    doc = ctx.doc
    stack = _LEDGER.get(_key(doc), [])
    top = stack[-1] if stack else None
    action = ctx.get("action", "status")
    if action == "status":
        return {"listening": _STATE["installed"], "listener_error": _STATE["error"],
                "can_undo": bool(top and top.get("rvtss")),
                "latest_steps": [dict(e) for e in reversed(stack[-ctx.int("limit", 10, 1, _MAX):])],
                "note": "Steps made before RVTSS started listening (Revit start / pyRevit reload) are unknown."}
    if action != "undo":
        raise RvtssError("action must be status or undo")
    if not _STATE["installed"]:
        raise RvtssError("The undo listener is not running", status=503, hint=_STATE["error"])
    if top is None:
        raise RvtssError("No change recorded in '{}' since RVTSS started listening".format(doc.Title), status=409)
    if not top.get("rvtss"):
        raise RvtssError("The latest change in the model was not made by RVTSS ({}); nothing was undone".format(
            ", ".join(top["names"]) or "unnamed"), status=409,
            hint="Undo it in Revit (Ctrl+Z) if that is what you want.")
    expect = ctx.get("expect_tool")
    if expect and top.get("tool") != expect:
        raise RvtssError("The latest RVTSS step came from '{}', not '{}'".format(top.get("tool"), expect), status=409)
    if ctx.uidoc is None or not ctx.uidoc.Document.Equals(doc):
        raise RvtssError("Undo works on the active document only", status=409,
                         hint="Activate the document's view in Revit first.")
    if ctx.dry_run:
        return {"status": "dry_run", "would_undo": top}
    core.require_writable("undo")
    from pyrevit import HOST_APP

    HOST_APP.uiapp.PostCommand(_undo_command_id())
    return {"status": "posted", "undoing": top,
            "message": "Revit runs the undo right after this answer. Re-read the elements to verify; call "
                       "undo_last_change(action='status') to see the next step."}


def register_undo_routes(api):
    @api.route("/undo/", methods=["POST"])
    def undo_route(doc, uidoc, request):
        return handle(doc, request, undo, uidoc=uidoc)

    logger.info("RVTSS undo routes registered")
