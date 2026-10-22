# -*- coding: utf-8 -*-
"""Status and model information tools"""

from ._compat import Context, READ_ONLY
from .utils import format_response


def register_status_tools(mcp, revit_get):
    """Register status-related tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def get_revit_status(ctx: Context) -> str:
        """Check if the Revit MCP API is active and responding"""
        response = await revit_get("/status/", ctx, timeout=10.0)
        return format_response(response)

    @mcp.tool(annotations=READ_ONLY)
    async def get_revit_model_info(ctx: Context) -> str:
        """Get comprehensive information about the current Revit model"""
        response = await revit_get("/model_info/", ctx)
        return format_response(response)
