# -*- coding: UTF-8 -*-
"""
Code Execution Module for Revit MCP
Handles direct execution of IronPython code in Revit context.
"""
from pyrevit import routes, revit, DB
import json
import logging
import sys
import traceback

try:
    from StringIO import StringIO  # IronPython 2.7
except ImportError:  # IronPython 3: the StringIO module does not exist (import failed before)
    from io import StringIO

# Standard logger setup
logger = logging.getLogger(__name__)


class _ReadOnlyDB(object):
    """DB namespace for read_only code: transaction classes are blocked."""

    _BLOCKED = ("Transaction", "SubTransaction", "TransactionGroup")

    def __getattr__(self, name):
        if name in self._BLOCKED:
            raise RuntimeError("read_only mode: DB.{} is not allowed. Use transaction_mode='auto' or "
                               "'dry_run' for code that modifies the model.".format(name))
        return getattr(DB, name)


def _run_read_only(doc, code, namespace):
    """Execute code inside a TransactionGroup that is always rolled back.

    Returns the number of elements Revit reported as changed (0 = read only).
    The rollback is the safety net for code that reaches the API another way.
    """
    changed = {"count": 0}

    def on_changed(sender, args):
        try:
            changed["count"] += (args.GetAddedElementIds().Count + args.GetModifiedElementIds().Count +
                                 args.GetDeletedElementIds().Count)
        except Exception:
            changed["count"] += 1

    app = doc.Application
    group = None
    subscribed = False
    try:
        app.DocumentChanged += on_changed
        subscribed = True
    except Exception:
        pass
    try:
        if not doc.IsModifiable and not doc.IsReadOnly:
            group = DB.TransactionGroup(doc, "RVTSS read_only code")
            group.Start()
        exec(code, namespace)
    finally:
        if group is not None and group.HasStarted() and not group.HasEnded():
            group.RollBack()
        if subscribed:
            try:
                app.DocumentChanged -= on_changed
            except Exception:
                pass
    return changed["count"]


def register_code_execution_routes(api):
    """Register code execution routes with the API."""

    @api.route("/execute_code/", methods=["POST"])
    def execute_code(doc, uidoc, request):
        """
        Execute IronPython code in Revit context.

        Expected payload:
        {
            "code": "python code as string",
            "description": "optional description of what the code does",
            "transaction_mode": "none" | "auto" | "dry_run" | "read_only"
        }

        transaction_mode (RVTSS):
            none     - (default, original behaviour) no transaction is opened; the
                       code manages its own transactions. Required for UI operations.
            auto     - the code runs inside one transaction that is committed on
                       success and rolled back if the code raises.
            dry_run  - the code runs inside a transaction that is always rolled
                       back; use it to test modifying code safely.
            read_only - (RVTSS 2.1) no transaction; the code may not open one
                       (DB.Transaction/SubTransaction/TransactionGroup are blocked) and
                       anything it changes anyway is rolled back and reported.

        Security (RVTSS 2.1): refused when RVTSS_ALLOW_CODE_EXECUTION=0 (or
        "allow_code_execution": false in %APPDATA%/RVTSS/config.json); every call is
        logged as a warning and the code is written to %APPDATA%/RVTSS/logs/code-*.log
        with secret-looking values redacted.
        """
        try:
            # Parse the request data
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            )
            code_to_execute = data.get("code", "")
            description = data.get("description", "Code execution")
            transaction_mode = (data.get("transaction_mode") or "none").lower()
            if transaction_mode not in ("none", "auto", "dry_run", "read_only"):
                return routes.make_response(
                    data={"error": "transaction_mode must be none, auto, dry_run or read_only"},
                    status=400,
                )
            from .secure_api import settings as _security_settings
            from .core import audit_code

            if not _security_settings()["allow_code_execution"]:
                return routes.make_response(
                    data={"status": "error", "error": "Code execution is disabled on this Revit machine",
                          "hint": "RVTSS_ALLOW_CODE_EXECUTION=0 (or allow_code_execution=false in "
                                  "%APPDATA%/RVTSS/config.json). Use the dedicated RVTSS tools instead."},
                    status=403,
                )
            if _security_settings().get("read_only") and transaction_mode not in ("read_only", "dry_run"):
                return routes.make_response(
                    data={"status": "error", "read_only": True,
                          "error": "RVTSS runs in read-only mode: only transaction_mode 'read_only' or "
                                   "'dry_run' is allowed",
                          "hint": "Both modes roll every change back. Unset RVTSS_READ_ONLY to allow changes."},
                    status=403,
                )
            logger.warning("execute_revit_code called (%s): %s", transaction_mode, description)
            audit_code(description, transaction_mode, code_to_execute)

            if not code_to_execute:
                return routes.make_response(
                    data={"error": "No code provided"}, status=400
                )

            logger.info("Executing code: {}".format(description))

            old_stdout = sys.stdout
            captured_output = StringIO()
            sys.stdout = captured_output

            namespace = {
                "doc": doc,
                "uidoc": uidoc,
                "DB": _ReadOnlyDB() if transaction_mode == "read_only" else DB,
                "revit": revit,
                "__builtins__": __builtins__,
                "print": lambda *args: captured_output.write(
                    " ".join(str(arg) for arg in args) + "\n"
                ),
            }

            try:
                failures = []
                if transaction_mode == "none":
                    exec(code_to_execute, namespace)
                elif transaction_mode == "read_only":
                    changed = _run_read_only(doc, code_to_execute, namespace)
                    if changed:
                        sys.stdout = old_stdout
                        captured_output.close()
                        return routes.make_response(
                            data={"status": "error",
                                  "error": "read_only code modified the model ({} element(s)); the change was "
                                           "rolled back".format(changed),
                                  "hint": "Use transaction_mode='dry_run' or 'auto' for modifying code."},
                            status=409,
                        )
                else:
                    from .core import run_transaction

                    def _run_user_code():
                        exec(code_to_execute, namespace)

                    _result, failures = run_transaction(
                        doc, description, _run_user_code,
                        dry_run=(transaction_mode == "dry_run"),
                    )

                sys.stdout = old_stdout
                output = captured_output.getvalue()
                captured_output.close()

                return routes.make_response(
                    data={
                        "status": "dry_run" if transaction_mode == "dry_run" else "success",
                        "transaction_mode": transaction_mode,
                        "committed": (None if transaction_mode == "none"
                                      else transaction_mode == "auto"),
                        "revit_warnings": failures,
                        "description": description,
                        "output": (
                            output
                            if output
                            else "Code executed successfully (no output)"
                        ),
                        "code_executed": code_to_execute,
                    }
                )

            except Exception as exec_error:
                sys.stdout = old_stdout
                partial_output = captured_output.getvalue()
                captured_output.close()

                error_traceback = traceback.format_exc()
                error_type = type(exec_error).__name__
                error_msg = str(exec_error)
                enhanced_message = "{}: {}".format(error_type, error_msg)

                hints = []
                if error_type == "AttributeError":
                    if "Name" in error_msg:
                        hints.append(
                            "The 'Name' property may not be directly accessible in IronPython. "
                            "Try getattr(element, 'Name', 'N/A') or "
                            "element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()"
                        )
                    else:
                        hints.append(
                            "Some Revit API properties are not directly accessible in IronPython. "
                            "Try getattr(obj, 'property_name', default_value) for safe access."
                        )
                elif error_type == "NullReferenceException" or "NoneType" in error_msg:
                    hints.append(
                        "An object is None/null. Check if elements exist before "
                        "accessing their properties: 'if element:'"
                    )
                elif error_type == "InvalidOperationException":
                    hints.append(
                        "This operation may require a transaction. Wrap model-modifying "
                        "code in: t = DB.Transaction(doc, 'desc'); t.Start(); ...; t.Commit()"
                    )

                logger.error("Code execution failed: {}".format(enhanced_message))

                response_data = {
                    "status": "error",
                    "error": enhanced_message,
                    "error_type": error_type,
                    "traceback": error_traceback,
                    "code_attempted": code_to_execute,
                }

                if partial_output:
                    response_data["partial_output"] = partial_output

                if hints:
                    response_data["hints"] = hints

                return routes.make_response(data=response_data, status=500)

        except Exception as e:
            logger.error("Execute code request failed: {}".format(str(e)))
            return routes.make_response(data={"error": str(e)}, status=500)

    logger.info("Code execution routes registered successfully.")
