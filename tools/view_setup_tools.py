# -*- coding: utf-8 -*-
"""RVTSS v2.4 tools: the ribbon command launcher, view extents, view templates and viewports."""
from typing import Annotated, List, Literal, Optional

from pydantic import Field

from ._compat import Context, READ_ONLY, MODIFIES, DESTRUCTIVE
from ._common import LengthUnit, compact, post, post_confirmable, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
ViewRef = Annotated[Optional[str], Field(description="View name, id or 'active'")]


def register_view_setup_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def list_revit_commands(
        contains: Annotated[Optional[str], Field(description="Words, e.g. 'curtain grid'")] = None,
        check_available: bool = False,
        limit: Annotated[int, Field(ge=1, le=2000)] = 200,
        ctx: Context = None,
    ) -> str:
        """Revit's own ribbon commands (the buttons), searchable by words. Use with run_revit_command."""
        return await post(revit_post, "/commands/list/", compact(
            contains=contains, check_available=check_available or None, limit=limit), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def run_revit_command(
        name: Annotated[Optional[str], Field(description="From list_revit_commands, e.g. 'ScopeBox'")] = None,
        command_id: Annotated[Optional[str], Field(description="Or a raw command id")] = None,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Press a Revit ribbon button for the user: the command starts in Revit and the user completes it.

        For anything RVTSS has no dedicated tool for (scope boxes, design options, phases, rendering...).
        The command is queued and runs after this call returns; RVTSS cannot see its outcome, so re-read
        the model afterwards. Save, synchronize, close, undo and redo are refused: use their own tools.
        """
        return await post(revit_post, "/commands/run/", compact(
            name=name, command_id=command_id, dry_run=dry_run or None), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def view_extents(
        action: Literal["get", "set_crop", "set_section_box", "set_view_range", "set_far_clip"] = "get",
        view: ViewRef = "active",
        element_ids: Annotated[Optional[List[int]], Field(description="Fit the crop / section box to them")] = None,
        margin: float = 500,
        min: Annotated[Optional[List[float]], Field(description="Or box corners [x,y,z]")] = None,
        max: Optional[List[float]] = None,
        scope_box: Annotated[Optional[str], Field(description="Scope box name, or 'none' to detach")] = None,
        crop_active: Optional[bool] = None,
        crop_visible: Optional[bool] = None,
        annotation_crop: Optional[bool] = None,
        enabled: Optional[bool] = None,
        top: Annotated[Optional[float], Field(description="View range offsets from the level")] = None,
        cut: Optional[float] = None,
        bottom: Optional[float] = None,
        view_depth: Optional[float] = None,
        far_clip_offset: Optional[float] = None,
        far_clipping: Optional[Literal["no_clip", "clip_with_line", "clip_without_line"]] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Crop region, 3D section box, plan view range and far clip of a view: read them or set them.

        set_crop fits the crop to element_ids (+ margin) or min / max; a view whose crop is controlled by a
        scope box needs scope_box='none' in the same call. set_section_box: enabled turns the box on or off.
        """
        return await post(revit_post, "/views/extents/", compact(
            action=action, view=view, element_ids=element_ids, margin=margin if element_ids else None, min=min,
            max=max, scope_box=scope_box, crop_active=crop_active, crop_visible=crop_visible, annotation_crop=annotation_crop,
            enabled=enabled, top=top, cut=cut, bottom=bottom, view_depth=view_depth,
            far_clip_offset=far_clip_offset, far_clipping=far_clipping, unit=unit, dry_run=dry_run or None,
            document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def manage_view_templates(
        action: Literal["list", "create_from_view", "duplicate", "apply", "remove", "delete",
                        "set_included"] = "list",
        template: Annotated[Optional[str], Field(description="Template name or id")] = None,
        view: ViewRef = None,
        views: Optional[List[str]] = None,
        name: Optional[str] = None,
        once: Annotated[bool, Field(description="apply: copy settings, do not assign")] = False,
        include: Annotated[Optional[List[str]], Field(description="Parameter names to control")] = None,
        exclude: Optional[List[str]] = None,
        parameters: bool = False,
        atomic: bool = True,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """View templates: list, create from a view, duplicate, apply to views, remove, delete, and choose the
        parameters a template controls.

        create_from_view uses view and name; apply / remove take views (default: active). list with
        parameters=true shows what each template controls. Deleting a template that views still use
        returns a preview until confirm=true.
        """
        data = compact(action=action, template=template, view=view, views=views, name=name, once=once or None,
                       include=include, exclude=exclude, parameters=parameters or None,
                       atomic=None if atomic else False, dry_run=dry_run or None, confirm=confirm or None,
                       document=document)
        return await post_confirmable(revit_post, "/views/templates/", data, ctx, 180.0, "manage_view_templates")

    @mcp.tool(annotations=DESTRUCTIVE)
    async def manage_viewports(
        action: Literal["list", "move", "set_type", "set_detail_number", "rotate", "remove"] = "list",
        sheet: Annotated[Optional[str], Field(description="Sheet number, name or id")] = None,
        viewport_id: Optional[int] = None,
        location: Annotated[Optional[List[float]], Field(description="New centre [x, y]")] = None,
        type: Optional[str] = None,
        detail_number: Optional[str] = None,
        rotation: Optional[Literal["none", "clockwise", "counterclockwise"]] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Viewports on a sheet: list them (with schedules), move, change type, set the detail number, rotate
        or remove. Place views with manage_sheets."""
        return await post(revit_post, "/sheets/viewports/", compact(
            action=action, sheet=sheet, viewport_id=viewport_id, location=location, type=type,
            detail_number=detail_number, rotation=rotation, unit=unit, dry_run=dry_run or None,
            document=document), ctx, timeout=120.0)
