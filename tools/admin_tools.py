# -*- coding: utf-8 -*-
"""RVTSS v2.2 model administration tools: worksets and purge."""
from typing import Annotated, List, Literal, Optional

from pydantic import Field

from ._compat import Context, MODIFIES, DESTRUCTIVE
from ._common import compact, post, post_confirmable, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_admin_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=MODIFIES)
    async def manage_worksets(
        action: Literal["list", "create", "rename", "move_elements", "set_active"] = "list",
        workset: Annotated[Optional[str], Field(description="Workset name or id")] = None,
        name: Annotated[Optional[str], Field(description="create / rename: new name")] = None,
        element_ids: Annotated[Optional[List[int]], Field(description="move_elements")] = None,
        include_counts: bool = True,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Worksets: list with element counts, create, rename, move elements to a workset, set the active one."""
        data = compact(action=action, workset=workset, name=name, element_ids=element_ids,
                       include_counts=include_counts, dry_run=dry_run or None, confirm=confirm or None,
                       document=document)
        if action == "move_elements":
            return await post_confirmable(revit_post, "/worksets/manage/", data, ctx, 120.0, "manage_worksets")
        return await post(revit_post, "/worksets/manage/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def purge_unused(
        categories: Annotated[Optional[List[str]], Field(description="Only purge these categories")] = None,
        exclude_ids: Optional[List[int]] = None,
        passes: Annotated[int, Field(ge=1, le=5, description="Repeat until nothing is left (nested families)")] = 1,
        list_limit: Annotated[int, Field(ge=1, le=5000)] = 300,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Purge unused families, types, materials, templates... Previews the list until confirm=true.

        Revit 2024+ uses Revit's own Purge Unused query; older versions purge unused loadable family
        types only. Always show the preview to the user before confirming.
        """
        data = compact(categories=categories, exclude_ids=exclude_ids, passes=passes, list_limit=list_limit,
                       confirm=confirm or None, document=document)
        return await post_confirmable(revit_post, "/purge/", data, ctx, 600.0, "purge_unused")
