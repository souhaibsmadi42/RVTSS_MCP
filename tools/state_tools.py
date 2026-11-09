# -*- coding: utf-8 -*-
"""RVTSS v2.3 tools: look at elements in 3D, stairs, phases / design options, links, selection sets, undo."""
import base64
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from ._compat import Context, Image, READ_ONLY, MODIFIES, DESTRUCTIVE
from ._common import LengthUnit, compact, post, DOC_HELP
from .utils import format_response

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_state_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def capture_elements(
        element_ids: List[int],
        orientation: Literal["iso_se", "iso_sw", "iso_ne", "iso_nw", "top", "front", "back", "left",
                             "right"] = "iso_se",
        margin: Annotated[float, Field(description="Section box margin around the elements in `unit`")] = 1000,
        isolate: bool = False,
        highlight: Annotated[bool, Field(description="Colour the elements orange (when not isolated)")] = True,
        display_style: Literal["shaded", "realistic", "hidden", "wireframe"] = "shaded",
        perspective: bool = False,
        eye: Annotated[Optional[List[float]], Field(description="Custom camera [x,y,z] (with target)")] = None,
        target: Optional[List[float]] = None,
        image_format: Literal["png", "jpg"] = "png",
        pixel_size: Annotated[int, Field(ge=128, le=4096)] = 1024,
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ):
        """See elements: a temporary 3D view with a section box around them, returned as an image.

        Nothing is kept: the view is created and rolled back, so the model and undo history do not change.
        """
        r = await revit_post("/views/capture/", compact(
            element_ids=element_ids, orientation=orientation, margin=margin, isolate=isolate or None,
            highlight=highlight, display_style=display_style, perspective=perspective or None, eye=eye,
            target=target, image_format=image_format, pixel_size=pixel_size, unit=unit, document=document),
            ctx, timeout=180.0)
        if isinstance(r, dict) and r.get("image_data"):
            return Image(data=base64.b64decode(r["image_data"]),
                         format="jpeg" if "jpeg" in (r.get("content_type") or "") else "png")
        return format_response(r)

    @mcp.tool(annotations=MODIFIES)
    async def create_stairs(
        base_level: str,
        top_level: str,
        runs: Annotated[List[Dict[str, Any]], Field(description=(
            "Straight runs in walking order: [{start:[x,y], end:[x,y], width?}, ...]; landings are added "
            "between consecutive runs"))],
        width: Annotated[Optional[float], Field(description="Default run width in `unit`")] = None,
        justification: Literal["center", "left", "right"] = "center",
        type: Annotated[Optional[str], Field(description="Stairs type name (default: the project default)")] = None,
        landings: bool = True,
        railings: bool = False,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create component stairs between two levels from straight runs, with landings and optional railings.

        One undo step. Revit spreads the risers between the levels; the result reports riser count and height.
        """
        return await post(revit_post, "/stairs/create/", compact(
            base_level=base_level, top_level=top_level, runs=runs, width=width, justification=justification,
            type=type, landings=landings, railings=railings or None, unit=unit, dry_run=dry_run or None,
            document=document), ctx, timeout=180.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_phases(
        action: Literal["list", "option_elements", "set_element_phase", "set_view_phase"] = "list",
        element_ids: Optional[List[int]] = None,
        created: Annotated[Optional[str], Field(description="Phase created (name or id)")] = None,
        demolished: Annotated[Optional[str], Field(description="Phase demolished; 'none' clears it")] = None,
        view: Optional[str] = None,
        phase: Optional[str] = None,
        phase_filter: Optional[str] = None,
        option: Annotated[Optional[str], Field(description="Design option name or id")] = None,
        counts: bool = False,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Phases, phase filters and design options: list, set element / view phases, elements of an option.

        The Revit API cannot create phases or design options.
        """
        return await post(revit_post, "/phases/manage/", compact(
            action=action, element_ids=element_ids, created=created, demolished=demolished, view=view,
            phase=phase, phase_filter=phase_filter, option=option, counts=counts or None,
            dry_run=dry_run or None, confirm=confirm or None, document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_links(
        action: Literal["list", "reload", "unload", "reload_from", "load"] = "list",
        link: Annotated[Optional[str], Field(description="Link name or type id")] = None,
        path: Annotated[Optional[str], Field(description="reload_from / load: .rvt path")] = None,
        placement: Literal["origin", "center", "shared"] = "origin",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Revit links: list status and paths, reload, unload, reload from another path, load a new link."""
        return await post(revit_post, "/links/manage/", compact(
            action=action, link=link, path=path, placement=placement, dry_run=dry_run or None,
            document=document), ctx, timeout=600.0)

    @mcp.tool(annotations=MODIFIES)
    async def selection_sets(
        action: Literal["list", "save", "load", "delete"] = "list",
        name: Optional[str] = None,
        element_ids: Annotated[Optional[List[int]], Field(description="save: ids (default: current selection)")] = None,
        overwrite: bool = False,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Saved selection sets (Revit selection filters): list, save ids or the selection, load (select), delete."""
        return await post(revit_post, "/selection_sets/", compact(
            action=action, name=name, element_ids=element_ids, overwrite=overwrite or None,
            dry_run=dry_run or None, document=document), ctx)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def undo_last_change(
        action: Literal["status", "undo"] = "status",
        expect_tool: Annotated[Optional[str], Field(description="Only undo if the last step came from this tool")] = None,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Undo the latest change in the model, only if RVTSS made it (status lists the latest steps).

        Uses Revit's own Undo, so the whole step (one RVTSS request) is reverted; refuses when the user
        changed the model since. Re-read the elements afterwards.
        """
        return await post(revit_post, "/undo/", compact(action=action, expect_tool=expect_tool,
                                                        dry_run=dry_run or None, document=document), ctx)
