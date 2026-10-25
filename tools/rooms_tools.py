# -*- coding: utf-8 -*-
"""RVTSS v2.2 rooms / spaces / areas tools."""
from typing import Annotated, List, Literal, Optional

from pydantic import Field

from ._compat import Context, READ_ONLY
from ._common import LengthUnit, compact, post, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
AreaUnit = Literal["m2", "mm2", "cm2", "ft2", "in2"]
SpatialStatus = Literal["placed", "unplaced", "not_enclosed", "redundant", "not_enclosed_or_redundant"]


def register_rooms_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def list_rooms(
        kind: Literal["room", "space", "area"] = "room",
        level: Optional[str] = None,
        phase: Optional[str] = None,
        status: Annotated[Optional[List[SpatialStatus]], Field(description="e.g. ['unplaced','not_enclosed']")] = None,
        contains: Annotated[Optional[str], Field(description="Text in number or name")] = None,
        area_unit: AreaUnit = "m2",
        unit: LengthUnit = "mm",
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Rooms, MEP spaces or areas with number, name, level, phase, area, perimeter, volume and status.

        Status: placed, unplaced, not_enclosed, redundant (from Revit warnings; localised Revit reports
        not_enclosed_or_redundant). Totals by level and department are computed from placed items.
        """
        return await post(revit_post, "/rooms/list/", compact(
            kind=kind, level=level, phase=phase, status=status, contains=contains, area_unit=area_unit, unit=unit,
            offset=offset, limit=limit, document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def get_room_details(
        element_ids: Annotated[List[int], Field(min_length=1, max_length=50)],
        include: Annotated[Optional[List[Literal["boundaries", "openings", "finishes", "contents"]]],
                           Field(description="Default: boundaries, openings, finishes")] = None,
        boundary_location: Literal["finish", "center", "core_center", "core_boundary"] = "finish",
        content_categories: Annotated[Optional[List[str]], Field(description="contents: only these categories")] = None,
        area_unit: AreaUnit = "m2",
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Room / space / area details: boundary segments, doors and windows, finish areas, contents.

        boundaries: segments with length and bounding element; openings: doors/windows whose From/To room
        is this room (room phase); finishes: estimated net wall area per bounding wall (length x unbounded
        height minus openings), floor and ceiling area; contents: family instances in the room.
        """
        return await post(revit_post, "/rooms/details/", compact(
            element_ids=element_ids, include=include, boundary_location=boundary_location,
            content_categories=content_categories, area_unit=area_unit, unit=unit, document=document),
            ctx, timeout=180.0)
