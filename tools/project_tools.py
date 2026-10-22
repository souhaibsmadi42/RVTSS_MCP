# -*- coding: utf-8 -*-
"""RVTSS project-level model intelligence tools."""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import Field

from ._compat import Context, READ_ONLY
from ._common import LengthUnit, compact, post, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_project_tools(mcp, revit_get, revit_post):
    """Register project information tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def get_session_info(ctx: Context = None) -> str:
        """Revit version/build, RVTSS version, active document and view, selection count, ALL open
        documents (projects and background family documents - use their title as `document`), linked
        documents, shared parameter file and family template path. Call this first in a session."""
        return await post(revit_post, "/session_info/", {}, ctx, timeout=20.0)

    @mcp.tool(annotations=READ_ONLY)
    async def get_project_overview(
        include: Optional[List[Literal["info", "levels", "grids", "phases", "worksets", "design_options"]]] = None,
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Project information parameters, display units, levels (elevations), grids, phases,
        worksets (workshared models) and design options - in one call."""
        return await post(revit_post, "/project_overview/", compact(include=include, unit=unit, document=document), ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def list_links(
        include_counts: Annotated[bool, Field(description="Model element counts per category inside each loaded link")] = False,
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Revit links (path, load status, pinned, position/rotation) and CAD imports/links."""
        return await post(revit_post, "/list_links/", compact(include_counts=include_counts or None, unit=unit,
                                                               document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def get_model_warnings(
        contains: Optional[str] = None,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
        ids_per_warning: int = 30,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Revit warnings grouped by description (most frequent first) with the failing element ids."""
        return await post(revit_post, "/model_warnings/", compact(contains=contains, offset=offset, limit=limit,
                                                                   ids_per_warning=ids_per_warning,
                                                                   document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def get_family_inventory(
        category: Optional[str] = None,
        contains: Optional[str] = None,
        unused_only: Annotated[bool, Field(description="Only families with zero placed instances")] = False,
        include_types: bool = True,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Loaded families grouped by category with their types, instance counts, in-place and
        editable flags. Use the family name with family_open to edit it."""
        return await post(revit_post, "/family_inventory/", compact(
            category=category, contains=contains, unused_only=unused_only or None, include_types=include_types,
            offset=offset, limit=limit, document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def find_views(
        view_types: Annotated[Optional[List[str]], Field(description="e.g. ['FloorPlan','Section','ThreeD','Schedule','DraftingView']")] = None,
        name_contains: Optional[str] = None,
        templates: Literal["exclude", "include", "only"] = "exclude",
        on_sheet: Annotated[Optional[bool], Field(description="true: only placed views, false: only unplaced")] = None,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Views with ids, type, level, scale, detail level, view template and the sheet they are on."""
        return await post(revit_post, "/find_views/", compact(
            view_types=view_types, name_contains=name_contains, templates=templates, on_sheet=on_sheet,
            offset=offset, limit=limit, document=document), ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def list_sheets(
        contains: Optional[str] = None,
        parameters: Annotated[Optional[List[str]], Field(description="Sheet parameters to include, e.g. ['Drawn By']")] = None,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Sheets with number, name, placed views, title blocks and revisions, plus counts of sheets
        without views or title blocks."""
        return await post(revit_post, "/list_sheets/", compact(contains=contains, parameters=parameters,
                                                                offset=offset, limit=limit, document=document), ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def get_schedule_data(
        schedule: Annotated[Union[int, str], Field(description="Schedule view id or exact name")],
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=2000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Read a schedule's table (column headers and rows as displayed), paginated."""
        return await post(revit_post, "/schedule_data/", compact(schedule=schedule, offset=offset, limit=limit,
                                                                  document=document), ctx, timeout=120.0)
