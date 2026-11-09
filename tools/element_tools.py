# -*- coding: utf-8 -*-
"""RVTSS element inspection and editing tools."""
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from ._compat import Context, READ_ONLY, MODIFIES, DESTRUCTIVE, IDEMPOTENT, structured_return
from ._outputs import FindElementsOut, ElementDetailsOut
from ._common import (LengthUnit, ValueUnit, ParamFilter, ParameterUpdate, Scalar, compact, post, DOC_HELP,
                      post_confirmable, post_structured)

Ids = Optional[List[int]]
Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_element_tools(mcp, revit_get, revit_post):
    """Register element tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def find_elements(
        categories: Annotated[Optional[List[str]], Field(description="e.g. ['Doors','Walls'] or ['OST_Doors']")] = None,
        class_name: Annotated[Optional[str], Field(description="Revit API class: Wall, Floor, FamilyInstance, Level, Grid, View, ViewSheet...")] = None,
        level: Annotated[Optional[str], Field(description="Level name or id")] = None,
        view: Annotated[Optional[str], Field(description="Only elements visible in this view (name, id or 'active')")] = None,
        family: Optional[str] = None,
        type: Optional[str] = None,
        name_contains: Optional[str] = None,
        text: Annotated[Optional[str], Field(description="Free text; every word must appear in category/family/type/name/mark")] = None,
        param_filters: Optional[List[ParamFilter]] = None,
        element_ids: Ids = None,
        selection: Annotated[bool, Field(description="Restrict to the current Revit selection")] = False,
        include_types: Annotated[bool, Field(description="Return element types (FamilySymbol, WallType...) instead of instances")] = False,
        fields: Annotated[Optional[List[Literal["level", "location", "bbox"]]], Field(description="Extra fields per element")] = None,
        parameters: Annotated[Optional[List[str]], Field(description="Parameter values to include per element")] = None,
        count_only: bool = False,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> structured_return(FindElementsOut):
        """Find elements by combinable filters -> ids, names, category/family/type, counts (paginated).
        E.g. doors on Level 2 wider than 900 mm: categories=['Doors'], level='Level 2',
        param_filters=[{name:'Width', op:'gt', value:900, unit:'mm'}].
        """
        data = compact(categories=categories, class_name=class_name, level=level, view=view, family=family,
                       type=type, name_contains=name_contains, text=text, param_filters=param_filters,
                       element_ids=element_ids, selection=selection or None,
                       include_types=include_types or None, fields=fields, parameters=parameters,
                       count_only=count_only or None, offset=offset, limit=limit, unit=unit, document=document)
        return await post_structured(revit_post, "/find_elements/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def get_element_details(
        element_ids: Annotated[List[int], Field(min_length=1, max_length=50)],
        parameters: Annotated[Optional[List[str]], Field(description="Only these parameters (default: all with values)")] = None,
        include_parameters: bool = True,
        include_type_parameters: bool = False,
        include_parameter_meta: Annotated[bool, Field(description="Storage type, spec, group, read-only, shared GUID")] = False,
        include_geometry: Annotated[bool, Field(description="Solid count, volume and surface area")] = False,
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> structured_return(ElementDetailsOut):
        """Full details for up to 50 elements: level, location, bbox, workset, phases, host, group/assembly,
        parameters with units, geometry.

        Full details for up to 50 elements: category, family/type, level, location, bounding box,
        workset, phases, design option, group/assembly, host, parameters (with units), geometry.
        """
        data = compact(element_ids=element_ids, parameters=parameters, include_parameters=include_parameters,
                       include_type_parameters=include_type_parameters,
                       include_parameter_meta=include_parameter_meta, include_geometry=include_geometry,
                       unit=unit, document=document)
        return await post_structured(revit_post, "/element_details/", data, ctx, timeout=60.0)

    @mcp.tool(annotations=MODIFIES)
    async def revit_selection(
        action: Literal["get", "set", "add", "clear"] = "get",
        element_ids: Ids = None,
        zoom: Annotated[bool, Field(description="Zoom the view to the newly selected elements")] = False,
        ctx: Context = None,
    ) -> str:
        """Read the current Revit selection, or select/highlight elements for the user (active document only)."""
        return await post(revit_post, "/selection/", compact(action=action, element_ids=element_ids,
                                                              zoom=zoom or None), ctx)

    @mcp.tool(annotations=IDEMPOTENT)
    async def set_parameters(
        updates: Annotated[Optional[List[ParameterUpdate]], Field(description="Per-element updates")] = None,
        element_ids: Annotated[Ids, Field(description="Shorthand: same parameter/value for these ids")] = None,
        parameter: Optional[str] = None,
        value: Scalar = None,
        value_unit: Optional[ValueUnit] = None,
        target: Literal["auto", "instance", "type"] = "auto",
        atomic: Annotated[bool, Field(description="All-or-nothing (default). false = apply what succeeds")] = True,
        dry_run: bool = False,
        confirm: Annotated[bool, Field(description="Required when more than 100 elements are affected")] = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Set instance/type parameter values with before/after values. Dimensional numbers need `unit` (or
        '900 mm'); bare numbers are rejected.

        Set parameter values on elements (instance or type) and return before/after values.

        Units are strict: a dimensional parameter needs `unit` (e.g. value=900, unit='mm') or a
        string with units ('900 mm'); bare numbers are rejected to prevent feet/mm mistakes.
        Yes/No accepts true/false. Element-id parameters accept an id or a material/level name.
        Changing a type parameter affects every instance of that type (reported in the result).
        """
        data = compact(updates=updates, element_ids=element_ids, parameter=parameter, value=value,
                       value_unit=value_unit, target=target, atomic=atomic, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        if value is None and parameter and "updates" not in data:
            data["value"] = None
        return await post_confirmable(revit_post, "/set_parameters/", data, ctx, 120.0, "set_parameters")

    @mcp.tool(annotations=MODIFIES)
    async def bulk_update_parameter(
        parameter: str,
        value: Scalar = None,
        template: Annotated[Optional[str], Field(description=(
            "Per-element value template: {n} / {n:03} sequence, {Level}, {Type}, {Family}, {id}, "
            "{value} (current), {Any Parameter}. e.g. 'D-{Level}-{n:03}'"))] = None,
        element_ids: Ids = None,
        selection: bool = False,
        categories: Optional[List[str]] = None,
        level: Optional[str] = None,
        view: Optional[str] = None,
        family: Optional[str] = None,
        type: Optional[str] = None,
        param_filters: Optional[List[ParamFilter]] = None,
        sort_by: Annotated[str, Field(description="id | name | x | y | z | xy | yx | param:<name> - numbering order")] = "id",
        start: int = 1,
        step: int = 1,
        only_empty: Annotated[bool, Field(description="Skip elements that already have a value")] = False,
        value_unit: Optional[ValueUnit] = None,
        allow_type: bool = False,
        atomic: bool = True,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Write one parameter on many elements (ids, selection or filters) with a value or a numbering
        template, e.g. selected doors left-to-right: parameter='Mark', selection=true, template='D{n:02}',
        sort_by='x'. Use dry_run first."""
        data = compact(parameter=parameter, value=value, template=template, element_ids=element_ids,
                       selection=selection or None, categories=categories, level=level, view=view,
                       family=family, type=type, param_filters=param_filters, sort_by=sort_by, start=start,
                       step=step, only_empty=only_empty or None, value_unit=value_unit,
                       allow_type=allow_type or None, atomic=atomic, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        if template is None and "value" not in data:
            data["value"] = None
        return await post_confirmable(revit_post, "/bulk_update_parameter/", data, ctx, 180.0, "bulk_update_parameter")

    @mcp.tool(annotations=MODIFIES)
    async def transform_elements(
        operation: Literal["move", "copy", "rotate", "mirror", "array", "pin", "unpin", "join", "unjoin",
                           "switch_join"],
        element_ids: List[int],
        vector: Annotated[Optional[List[float]], Field(description="[dx, dy, dz] for move/copy/linear array step")] = None,
        angle_deg: Annotated[Optional[float], Field(description="Rotation, or radial array total angle")] = None,
        count: Annotated[Optional[int], Field(description="array: number of items incl. the original")] = None,
        center: Annotated[Optional[List[float]], Field(description="Rotation centre / mirror plane origin (default: centroid)")] = None,
        each_about_own_center: bool = False,
        plane_normal: Annotated[Literal["x", "y"], Field(description="Mirror plane normal (vertical plane)")] = "x",
        mirror_copy: Annotated[bool, Field(description="Mirror: keep originals and create mirrored copies")] = False,
        unpin: bool = False,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Move, copy, rotate, mirror, array (linear/radial copies), pin/unpin, join/unjoin/switch_join elements.

        Copies and arrays return the new element ids. join/unjoin/switch_join pair the first id with each
        of the others (wall-floor, column-beam ...).
        """
        data = compact(operation=operation, element_ids=element_ids, vector=vector, angle_deg=angle_deg, count=count,
                       center=center, each_about_own_center=each_about_own_center or None,
                       plane_normal=plane_normal, mirror_copy=mirror_copy or None, unpin=unpin or None, unit=unit,
                       dry_run=dry_run or None, confirm=confirm or None, document=document)
        return await post_confirmable(revit_post, "/transform_elements/", data, ctx, 120.0, "transform_elements")

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_elements(
        element_ids: List[int],
        confirm: Annotated[bool, Field(description="false (default) = preview of everything Revit would delete")] = False,
        include_pinned: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Delete elements. Without confirm=true it only previews everything Revit would delete (incl.
        hosted/dependent elements); show the preview first.

        Delete elements. Without confirm=true this only previews: Revit performs the deletion inside a
        rolled-back transaction and reports every dependent element that would also be removed (hosted
        doors, tags, dimensions...). Show the preview to the user before confirming.
        """
        data = compact(element_ids=element_ids, confirm=confirm or None, include_pinned=include_pinned or None,
                       document=document)
        return await post_confirmable(revit_post, "/delete_elements/", data, ctx, 120.0, "delete_elements")

    @mcp.tool(annotations=MODIFIES)
    async def create_elements(
        items: Annotated[List[Dict[str, Any]], Field(description=(
            "Items by kind (coordinates in `unit`):\n"
            "level: {kind:'level', elevation, name?, create_plan_view?}\n"
            "grid: {kind:'grid', start:[x,y], end:[x,y], name?}\n"
            "wall: {kind:'wall', start, end, level, type?|type_id?, height?(3000), base_offset?, structural?, flip?}\n"
            "floor: {kind:'floor', boundary:[[x,y],...], level, type?|type_id?, structural?}\n"
            "family_instance: {kind:'family_instance', family, type|type_id, point:[x,y,z], level?, host_id?, rotation_deg?}\n"
            "room: {kind:'room', level, point:[x,y], name?, number?}\n"
            "roof: {boundary, level, type?, slope_deg?, slope_edges?, base_offset?}\n"
            "ceiling: {boundary, level, type?, height?}\n"
            "column: {point, level, top_level?, base_offset?, top_offset?, family?, type?, rotation_deg?}\n"
            "beam: {start, end, level, family?, type?}\n"
            "foundation: {point, level, family?, type?, base_offset?}\n"
            "wall_foundation: {wall_id, type?}\n"
            "duct|pipe|cable_tray|conduit: {points:[[x,y(,z)],...], level, offset?, type?, system_type? (duct/pipe), "
            "width?/height?/diameter?, fittings?(true: elbows at bends)}\n"
            "wall_opening: {wall_id, offset_along, width, height, sill?}\n"
            "opening: {host_id (floor/roof/ceiling), boundary}\n"
            "shaft: {boundary, level, top_level, base_offset?, top_offset?}\n"
            "railing: {points, level, type?} or {host_id (stairs/ramp), position?}\n"
            "space: {level, point, name?, number?}; area: {area_view, point, name?, number?}\n"
            "area_boundary: {area_view, points, closed?}; room_separation|space_separation: {view, points, closed?}\n"
            "auto_rooms: {level} (a room in every closed region)\n"
            "rebar: {host_id, points:[[x,y,z],...], normal?, type?, style?, count?, spacing?}\n"
            "toposolid: {points:[[x,y,z],...], level, type?} (2024+)\n"
            "direct_shape: {vertices, faces:[[i,j,k],...]} or {obj_file, obj_unit?}; category?, name?, material?\n"
            "curtain_grid_line: {wall_id, direction:'vertical'|'horizontal', offset_along | height | point}\n"
            "mullions: {wall_id, lines?:'all'|'horizontal'|'vertical' | grid_line_ids, type?}\n"
            "curtain_panel_type: {wall_id | panel_ids, type|type_id, unpin?}\n"
            "wall_sweep|reveal: {wall_id, distance, vertical?, side?:'exterior'|'interior', from_top?, type?}\n"
            "model_line: {points | start,end, level?, offset?, closed?, line_style?}\n"
            "reference_plane: {start, end, name?, level?, view?}\n"
            "foundation_isolated: as foundation; foundation_wall: as wall_foundation\n"
            "brace: {start:[x,y,z], end:[x,y,z], level, family?, type?}; truss: {start, end, level, offset?, type?}\n"
            "beam_system: {boundary, level, direction_edge?(0), is_3d?, family?, type?}"))],
        unit: LengthUnit = "mm",
        atomic: bool = True,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create levels, grids, walls, floors, family instances, rooms, roofs, ceilings, structure, ducts, pipes,
        cable trays, conduit, openings, shafts and railings in one transaction; returns new ids.

        Create levels, grids, walls, floors, family instances (hosted or not), rooms, footprint roofs,
        ceilings (Revit 2022+), structural / architectural columns (from the family category), beams,
        isolated and wall foundations, MEP runs (segments joined by elbows), wall / floor / roof openings,
        shafts and railings in one transaction (one undo step). Returns new element ids.
        Doors/windows need host_id of a wall. Without family/type the default type, or the first
        loaded family of the category, is used.
        v2.4: curtain grid lines, mullions and panel types, wall sweeps and reveals, model lines,
        reference planes, braces, trusses and beam systems. The Revit API cannot create ramps or model
        text in a project, or attach wall tops / bases; do those in Revit.
        """
        data = compact(items=items, unit=unit, atomic=atomic, dry_run=dry_run or None, document=document)
        return await post(revit_post, "/create_elements/", data, ctx, timeout=180.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_element_types(
        action: Literal["list_valid_types", "duplicate", "rename", "change_type"],
        type_id: Optional[int] = None,
        family: Optional[str] = None,
        type: Optional[str] = None,
        category: Optional[str] = None,
        new_name: Optional[str] = None,
        parameters: Annotated[Optional[Dict[str, Any]], Field(description=(
            "duplicate: type parameter values for the new type, {name: value} or {name: {value, unit}}"))] = None,
        element_id: Annotated[Optional[int], Field(description="list_valid_types: the element to inspect")] = None,
        element_ids: Annotated[Ids, Field(description="change_type: elements to switch to the type")] = None,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Project types: duplicate a type (optionally setting its parameters), rename it, list the
        types an element may switch to, or change elements to another type."""
        data = compact(action=action, type_id=type_id, family=family, type=type, category=category,
                       new_name=new_name, parameters=parameters, element_id=element_id,
                       element_ids=element_ids, dry_run=dry_run or None, confirm=confirm or None,
                       document=document)
        return await post_confirmable(revit_post, "/element_types/", data, ctx, 120.0, "manage_element_types")
