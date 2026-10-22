# -*- coding: utf-8 -*-
"""View-related tools for capturing and listing Revit views"""

from typing import Literal

from ._compat import Context, READ_ONLY
from .utils import format_response


def register_view_tools(mcp, revit_get, revit_post, revit_image):
    """Register view-related tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def get_revit_view(view_name: str, image_format: Literal["png", "jpg"] = "png",
                             pixel_size: int = 1024, ctx: Context = None):
        """Export a view as an image (png, or jpg for smaller payloads; pixel_size 128-4096).

        view_name: the exact view name, or the view element id as a string when
        several views share a name (e.g. floor and ceiling plan "Level 1").
        Images above RVTSS_IMAGE_MAX_KB (default 4096 KB) are refused with a hint;
        errors come back as {status, error, error_kind, hint, request_id}.
        """
        return await revit_image(f"/get_view/{view_name}", ctx, image_format=image_format,
                                 pixel_size=pixel_size)

    @mcp.tool(annotations=READ_ONLY)
    async def list_revit_views(ctx: Context = None) -> str:
        """Get a list of all exportable views in the current Revit model"""
        response = await revit_get("/list_views/", ctx)
        return format_response(response)

    @mcp.tool(annotations=READ_ONLY)
    async def get_current_view_info(ctx: Context = None) -> str:
        """Name, type, id, scale, crop, detail level and discipline of the active view.

        Get detailed information about the currently active view in Revit.

        Returns comprehensive information including:
        - View name, type, and ID
        - Scale and detail level
        - Crop box status
        - View family type
        - View discipline
        - Template status
        """
        if ctx:
            await ctx.info("Getting current view information...")
        response = await revit_get("/current_view_info/", ctx)
        return format_response(response)

    @mcp.tool(annotations=READ_ONLY)
    async def get_current_view_elements(
        limit: int = 5000,
        include_levels: bool = False,
        include_location: bool = False,
        ctx: Context = None,
    ) -> str:
        """Elements visible in the active view with category counts (truncated at `limit`).

        Get elements visible in the currently active view in Revit.

        Returns per element: element_id, name, category, category_id.
        Also returns category_counts (always for ALL elements, even if truncated).

        If the response contains truncated=true, not all elements were returned.
        Check total_elements vs returned_elements and increase limit if needed.

        Args:
            limit: Maximum number of elements to return (default 5000).
            include_levels: Include level name and level_id per element. Default false.
            include_location: Include location geometry (point or curve). Default false.
        """
        if ctx:
            await ctx.info("Getting elements in current view...")
        data = {
            "limit": limit,
            "include_levels": include_levels,
            "include_location": include_location,
        }
        response = await revit_post("/current_view_elements/", data, ctx)
        return format_response(response)
