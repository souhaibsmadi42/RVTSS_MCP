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
from StringIO import StringIO

# Standard logger setup
logger = logging.getLogger(__name__)


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
            "transaction_mode": "none" | "auto" | "dry_run"
        }

        transaction_mode (RVTSS):
            none     - (default, original behaviour) no transaction is opened; the
                       code manages its own transactions. Required for UI operations.
            auto     - the code runs inside one transaction that is committed on
                       success and rolled back if the code raises.
            dry_run  - the code runs inside a transaction that is always rolled
                       back; use it to test modifying code safely.
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
            if transaction_mode not in ("none", "auto", "dry_run"):
                return routes.make_response(
                    data={"error": "transaction_mode must be none, auto or dry_run"},
                    status=400,
                )

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
                "DB": DB,
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
