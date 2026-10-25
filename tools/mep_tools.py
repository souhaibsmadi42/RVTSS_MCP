# -*- coding: utf-8 -*-
"""RVTSS v2.2 MEP tools (read-only)."""
from typing import Annotated, List, Literal, Optional

from pydantic import Field

from ._compat import Context, READ_ONLY
from ._common import ElementScope, LengthUnit, compact, post, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_mep_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def list_mep_systems(
        domain: Optional[Literal["mechanical", "piping", "electrical"]] = None,
        contains: Optional[str] = None,
        include_elements: Annotated[bool, Field(description="Element ids per system (max 500)")] = False,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """MEP systems: type, classification, element count, base equipment, well-connected flag."""
        return await post(revit_post, "/mep/systems/", compact(
            domain=domain, contains=contains, include_elements=include_elements or None, offset=offset,
            limit=limit, document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def get_mep_connectors(
        element_ids: Annotated[List[int], Field(min_length=1, max_length=50)],
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Connectors of MEP elements: domain, shape and size, flow direction, system, connected elements."""
        return await post(revit_post, "/mep/connectors/", compact(element_ids=element_ids, unit=unit,
                                                                   document=document), ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def find_mep_disconnects(
        scope: Annotated[Optional[ElementScope], Field(description="Default: all duct / pipe / tray / conduit "
                                                                   "curves, fittings, accessories, equipment")] = None,
        unit: LengthUnit = "mm",
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=2000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Open MEP connectors (nothing attached): missing fittings, caps, terminals or gaps, with location."""
        return await post(revit_post, "/mep/disconnects/", compact(
            filter=scope, unit=unit, offset=offset, limit=limit, document=document), ctx, timeout=300.0)
