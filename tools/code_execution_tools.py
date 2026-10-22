# -*- coding: utf-8 -*-
"""Code execution tools for the MCP server."""

from ._compat import Context, DESTRUCTIVE
from .utils import format_response


def register_code_execution_tools(mcp, revit_get, revit_post, revit_image=None):
    """Register code execution tools with the MCP server."""
    # Note: revit_get and revit_image are unused but kept for interface consistency
    _ = revit_get, revit_image  # Acknowledge unused parameters

    @mcp.tool(annotations=DESTRUCTIVE)
    async def execute_revit_code(
        code: str,
        description: str = "Code execution",
        transaction_mode: str = None,
        ctx: Context = None,
    ) -> str:
        """
        Execute IronPython code directly in Revit context.

        The code has access to:
        - doc: The active Revit document
        - uidoc: The active UIDocument (use for UI operations like switching the active view)
        - DB: Revit API Database namespace
        - revit: pyRevit module
        - print: Function to output text (returned in response)

        Prefer the dedicated RVTSS tools (find_elements, set_parameters, family_*,
        ...) - they validate input and support dry runs. Use this for anything
        they do not cover.

        transaction_mode:
        - None/"none" (default): no transaction is opened automatically.
        - "auto": the code runs in one transaction, committed on success and
          rolled back if it raises. Do not start your own Transaction then.
        - "dry_run": like auto but always rolled back - test modifying code safely.

        With the default mode, wrap model-modifying code yourself:
            t = DB.Transaction(doc, "My change")
            t.Start()
            # ... modify model ...
            t.Commit()

        For UI operations that cannot run inside a transaction (e.g. switching the active view):
            all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
            target = next((v for v in all_views if v.Name == "Level 1"), None)
            if target:
                uidoc.ActiveView = target

        Tips:
        - Use getattr(element, 'Name', 'N/A') to safely access the Name property
        - Check elements exist before use: if element:
        - Use hasattr() for optional properties
        """
        try:
            payload = {"code": code, "description": description}
            if transaction_mode:
                payload["transaction_mode"] = transaction_mode

            if ctx:
                await ctx.info("Executing code: {}".format(description))

            response = await revit_post("/execute_code/", payload, ctx, timeout=60.0)
            return format_response(response)

        except (ConnectionError, ValueError, RuntimeError) as e:
            error_msg = "Error during code execution: {}".format(str(e))
            if ctx:
                await ctx.error(error_msg)
            return error_msg
