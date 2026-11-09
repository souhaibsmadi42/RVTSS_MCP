# -*- coding: utf-8 -*-
"""RVTSS documentation tools: views, graphics, sheets, schedules, renaming, groups, assemblies."""
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ._compat import Context, MODIFIES, IDEMPOTENT
from .utils import format_response
from ._common import LengthUnit, compact, post, DOC_HELP, call_with_progress

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
ViewRef = Annotated[Optional[Union[int, str]], Field(description="View id, exact name, or 'active'")]


class FilterRule(BaseModel):
    parameter: str = Field(description="Label or BuiltInParameter name")
    op: Literal["equals", "not_equals", "contains", "not_contains", "begins_with", "not_begins_with", "ends_with",
                "not_ends_with", "greater", "greater_or_equal", "less", "less_or_equal", "has_value",
                "has_no_value"] = "equals"
    value: Optional[Union[str, float, int, bool]] = None
    unit: Optional[str] = None
    type: Optional[Literal["string", "double", "integer", "element_id"]] = None


class FilterOverrides(BaseModel):
    color: Optional[str] = None
    fill: bool = True
    line_weight: Optional[int] = Field(None, ge=1, le=16)
    halftone: Optional[bool] = None
    transparency: Optional[int] = Field(None, ge=0, le=100)


def register_documentation_tools(mcp, revit_get, revit_post):
    """Register documentation tools"""

    @mcp.tool(annotations=MODIFIES)
    async def create_view(
        kind: Literal["floor_plan", "ceiling_plan", "structural_plan", "area_plan", "three_d", "section",
                      "elevation", "drafting", "callout", "legend", "duplicate"],
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
        min: Annotated[Optional[List[float]], Field(description="callout: one corner in the parent view "
                                                                "(source_view)")] = None,
        max: Annotated[Optional[List[float]], Field(description="callout: the opposite corner")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create plans, 3D (optionally boxed to elements), sections, elevations, drafting views, callouts,
        legends or duplicates, with name/template/scale.

        Create plans, 3D views (optionally section-boxed to elements), sections framing elements,
        elevations, drafting views, or duplicate a view - with name, template, scale and detail level.
        callout: a rectangle (min, max) in source_view; a detail view unless view_family_type names another.
        legend: the Revit API cannot create the first legend, so an existing one (source_view, or the first
        legend) is duplicated.
        """
        data = compact(kind=kind, name=name, level=level, element_ids=element_ids, margin=margin, looking=looking,
                       plan_view=plan_view, point=point, facing=facing, source_view=source_view,
                       duplicate_option=duplicate_option, template=template, scale=scale, detail_level=detail_level,
                       view_family_type=view_family_type, area_scheme=area_scheme, min=min, max=max, unit=unit,
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
        category: Annotated[Optional[str], Field(description="Needed for kind category, key and "
                                                             "material_takeoff")] = None,
        fields: Annotated[Optional[List[str]], Field(description="Schedulable field names, e.g. ['Mark','Type','Width','Fire Rating']")] = None,
        kind: Literal["category", "key", "material_takeoff", "sheet_list", "view_list", "note_block"] = "category",
        family: Annotated[Optional[str], Field(description="note_block: generic annotation family name")] = None,
        name: Optional[str] = None,
        sort_by: Optional[List[str]] = None,
        filters: Annotated[Optional[List[Dict[str, Any]]], Field(description="[{field, type: 'Equal'|'Contains'|'GreaterThan'|..., value, unit?}] - numbers for numeric fields (with unit for lengths), text for text fields")] = None,
        itemized: bool = True,
        strict: bool = True,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create a schedule with fields, sorting and filters: by category, key schedule, material take-off,
        sheet list, view list or note block."""
        data = compact(category=category, fields=fields, kind=None if kind == "category" else kind, family=family,
                       name=name, sort_by=sort_by, filters=filters,
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

    @mcp.tool(annotations=MODIFIES)
    async def manage_view_filters(
        action: Literal["list", "create", "apply", "remove", "delete"] = "list",
        filter: Annotated[Optional[str], Field(description="Existing filter name or id")] = None,
        name: Annotated[Optional[str], Field(description="create: new filter name")] = None,
        categories: Optional[List[str]] = None,
        rules: Optional[List[FilterRule]] = None,
        logic: Literal["and", "or"] = "and",
        apply_to: Annotated[Optional[List[str]], Field(description="Views or view templates (names / ids); "
                                                                   "default: active view")] = None,
        visible: Optional[bool] = None,
        overrides: Optional[FilterOverrides] = None,
        contains: Annotated[Optional[str], Field(description="list: name filter")] = None,
        dry_run: bool = False,
        confirm: Annotated[bool, Field(description="delete: required")] = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Rule-based view filters: list (rules, where used), create, apply to views/templates with visibility and
        graphic overrides, remove, delete.

        Example: create name='Fire doors' categories=['Doors'] rules=[{parameter: 'Fire Rating', op:
        'has_value'}] apply_to=['Level 1'] overrides={color: '#FF0000'}. Dimensional values are read in
        the rule's `unit` (default mm, m2 / m3 for areas / volumes).
        """
        data = compact(action=action, filter=filter, name=name, categories=categories, rules=rules, logic=logic,
                       apply_to=apply_to, visible=visible, overrides=overrides, contains=contains,
                       dry_run=dry_run or None, confirm=confirm or None, document=document)
        return await post(revit_post, "/views/filters/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_revisions(
        action: Literal["list", "create", "update", "assign", "unassign", "issue"] = "list",
        revision: Annotated[Optional[str], Field(description="Revision id, sequence number or description")] = None,
        sheets: Annotated[Optional[List[str]], Field(description="Sheet numbers or ids")] = None,
        description: Optional[str] = None,
        date: Optional[str] = None,
        issued_to: Optional[str] = None,
        issued_by: Optional[str] = None,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Revisions: list (with the sheets showing them), create, update, assign/unassign to sheets, issue.

        assign/unassign edit a sheet's additional revisions; revisions shown by clouds stay on the sheet.
        issue locks the revision.
        """
        data = compact(action=action, revision=revision, sheets=sheets, description=description, date=date,
                       issued_to=issued_to, issued_by=issued_by, dry_run=dry_run or None, document=document)
        return await post(revit_post, "/sheets/revisions/", data, ctx, timeout=120.0)
