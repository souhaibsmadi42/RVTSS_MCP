# -*- coding: utf-8 -*-
"""RVTSS documentation tools: views, graphics, sheets, schedules, renaming, groups, assemblies."""
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from ._compat import Context, MODIFIES, IDEMPOTENT
from .utils import format_response
from ._common import LengthUnit, compact, post, DOC_HELP, call_with_progress

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
ViewRef = Annotated[Optional[Union[int, str]], Field(description="View id, exact name, or 'active'")]


def register_documentation_tools(mcp, revit_get, revit_post):
    """Register documentation tools"""

    @mcp.tool(annotations=MODIFIES)
    async def create_view(
        kind: Literal["floor_plan", "ceiling_plan", "structural_plan", "area_plan", "three_d", "section",
                      "elevation", "drafting", "duplicate"],
        name: Optional[str] = None,
        level: Annotated[Optional[str], Field(description="plans: level name or id")] = None,
        element_ids: Annotated[Optional[List[int]], Field(description="three_d: section box around them; section: framed elements")] = None,
        margin: Annotated[float, Field(description="Box margin around element_ids in `unit`")] = 500,
        looking: Annotated[Literal["north", "south", "east", "west"], Field(description="section direction")] = "north",
        plan_view: Annotated[ViewRef, Field(description="elevation: plan view hosting the marker")] = None,
        point: Annotated[Optional[List[float]], Field(description="elevation: marker location")] = None,
        facing: Literal["north", "south", "east", "west"] = "north",
        source_view: ViewRef = None,
        duplicate_option: Literal["duplicate", "with_detailing", "as_dependent"] = "duplicate",
        template: Optional[str] = None,
        scale: Optional[int] = None,
        detail_level: Optional[Literal["coarse", "medium", "fine"]] = None,
        view_family_type: Optional[str] = None,
        area_scheme: Annotated[Optional[str], Field(description="area_plan: area scheme name (default: first)")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create plans, 3D (optionally boxed to elements), sections, elevations, drafting views or duplicates,
        with name/template/scale.

        Create plans, 3D views (optionally section-boxed to elements), sections framing elements,
        elevations, drafting views, or duplicate a view - with name, template, scale and detail level.
        """
        data = compact(kind=kind, name=name, level=level, element_ids=element_ids, margin=margin, looking=looking,
                       plan_view=plan_view, point=point, facing=facing, source_view=source_view,
                       duplicate_option=duplicate_option, template=template, scale=scale, detail_level=detail_level,
                       view_family_type=view_family_type, area_scheme=area_scheme, unit=unit,
                       dry_run=dry_run or None, document=document)
        return await post(revit_post, "/views/create/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=IDEMPOTENT)
    async def view_graphics(
        action: Literal["override", "reset", "hide", "unhide", "temporary_isolate", "temporary_hide",
                        "reset_temporary", "category_hidden", "apply_template", "remove_template", "set_scale",
                        "set_detail_level"],
        view: ViewRef = "active",
        element_ids: Optional[List[int]] = None,
        categories: Optional[List[str]] = None,
        color: Annotated[Optional[str], Field(description="override: hex color '#FF0000'")] = None,
        fill: Annotated[bool, Field(description="override: also apply a solid surface fill")] = True,
        line_weight: Optional[int] = None,
        halftone: Optional[bool] = None,
        transparency: Annotated[Optional[int], Field(ge=0, le=100)] = None,
        hidden: Annotated[bool, Field(description="category_hidden: hide (true) or show (false)")] = True,
        template: Optional[str] = None,
        scale: Optional[int] = None,
        detail_level: Optional[Literal["coarse", "medium", "fine"]] = None,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Per-view graphics: element/category overrides, hide/unhide, temporary isolate, category visibility,
        view templates, scale, detail level.

        Per-view graphics: element/category overrides (color, fill, line weight, halftone,
        transparency), hide/unhide, temporary isolate/hide, category visibility, view templates, scale
        and detail level. Warns when a view template controls the setting.
        """
        data = compact(action=action, view=view, element_ids=element_ids, categories=categories, color=color,
                       fill=fill, line_weight=line_weight, halftone=halftone, transparency=transparency,
                       hidden=hidden, template=template, scale=scale, detail_level=detail_level,
                       dry_run=dry_run or None, document=document)
        return await post(revit_post, "/views/graphics/", data, ctx, timeout=60.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_sheets(
        action: Literal["create", "place_view", "list_titleblocks"],
        sheets: Annotated[Optional[List[Dict[str, Any]]], Field(description="create: [{number, name, title_block?}]")] = None,
        title_block: Annotated[Optional[str], Field(description="Default title block type name or id")] = None,
        sheet_id: Optional[int] = None,
        view: Annotated[ViewRef, Field(description="place_view: view or schedule")] = None,
        location: Annotated[Optional[List[float]], Field(description="place_view: [x, y] on the sheet in `unit`")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create sheets (with title blocks) and place views or schedules on them."""
        data = compact(action=action, sheets=sheets, title_block=title_block, sheet_id=sheet_id, view=view,
                       location=location, unit=unit, dry_run=dry_run or None, document=document)
        return await post(revit_post, "/sheets/manage/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def create_schedule(
        category: str,
        fields: Annotated[List[str], Field(description="Schedulable field names, e.g. ['Mark','Type','Width','Fire Rating']")],
        name: Optional[str] = None,
        sort_by: Optional[List[str]] = None,
        filters: Annotated[Optional[List[Dict[str, Any]]], Field(description="[{field, type: 'Equal'|'Contains'|'GreaterThan'|..., value, unit?}] - numbers for numeric fields (with unit for lengths), text for text fields")] = None,
        itemized: bool = True,
        strict: bool = True,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create a schedule for a category with fields, sorting and filters."""
        data = compact(category=category, fields=fields, name=name, sort_by=sort_by, filters=filters,
                       itemized=itemized, strict=strict, dry_run=dry_run or None, document=document)
        return await post(revit_post, "/schedules/create/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def batch_rename(
        target: Literal["views", "view_templates", "sheets", "levels", "grids", "families", "family_types",
                        "system_types", "materials", "rooms"],
        find: Optional[str] = None,
        replace: str = "",
        regex: bool = False,
        prefix: str = "",
        suffix: str = "",
        case: Optional[Literal["upper", "lower", "title"]] = None,
        include_regex: Annotated[Optional[str], Field(description="Only rename names matching this regex")] = None,
        element_ids: Optional[List[int]] = None,
        field: Annotated[Literal["name", "number"], Field(description="sheets: rename the number instead of the name")] = "name",
        dry_run: bool = True,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Rename views/sheets/levels/families/types/rooms... with find/replace/regex/prefix/suffix/case;
        detects collisions. dry_run by default.

        Rename many items to a naming standard with find/replace (or regex), prefix, suffix and case.
        Detects collisions and invalid characters before changing anything. Defaults to dry_run=true.
        """
        data = compact(target=target, find=find, replace=replace, regex=regex, prefix=prefix, suffix=suffix, case=case,
                       include_regex=include_regex, element_ids=element_ids, field=field, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        response = await call_with_progress(revit_post, "/batch_rename/", data, ctx, 120.0, "Batch rename")
        return format_response(response)

    @mcp.tool(annotations=MODIFIES)
    async def manage_groups(
        action: Literal["list", "create", "ungroup"] = "list",
        element_ids: Optional[List[int]] = None,
        name: Optional[str] = None,
        group_id: Optional[int] = None,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """List group types (instances, unused types), create a model group from elements, or ungroup."""
        data = compact(action=action, element_ids=element_ids, name=name, group_id=group_id,
                       dry_run=dry_run or None, document=document)
        return await post(revit_post, "/groups/manage/", data, ctx)

    @mcp.tool(annotations=MODIFIES)
    async def manage_assemblies(
        action: Literal["list", "create", "add_members", "remove_members", "rename", "create_views"] = "list",
        element_ids: Optional[List[int]] = None,
        assembly_id: Optional[int] = None,
        name: Optional[str] = None,
        naming_category: Optional[str] = None,
        views: Annotated[Optional[List[Literal["3d", "front", "back", "left", "right", "top", "bottom", "detail_front",
                                               "detail_side", "horizontal", "parts_list", "material_takeoff"]]],
                         Field(description="create_views: which assembly views to create")] = None,
        create_sheet: bool = False,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Assemblies: create, add/remove members, rename, create assembly views and sheet.

        Assemblies: create from elements (with a name), add/remove members, rename, and generate
        assembly views (3D, elevations/sections, parts list, material takeoff) plus an assembly sheet.
        """
        data = compact(action=action, element_ids=element_ids, assembly_id=assembly_id, name=name,
                       naming_category=naming_category, views=views, create_sheet=create_sheet or None,
                       dry_run=dry_run or None, document=document)
        return await post(revit_post, "/assemblies/manage/", data, ctx, timeout=120.0)
