# -*- coding: utf-8 -*-
"""RVTSS v2.4 tools: insert files and families, project settings, styles, project standards, worksharing."""
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from ._compat import Context, MODIFIES, DESTRUCTIVE
from ._common import LengthUnit, compact, post, post_confirmable, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
Colour = Annotated[Optional[Union[str, List[int]]], Field(description="[r, g, b] or '#rrggbb'")]


def register_project_admin_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=DESTRUCTIVE)
    async def insert_files(
        action: Literal["list", "link_cad", "import_cad", "place_image", "reload_cad", "delete"] = "list",
        path: Annotated[Optional[str], Field(description=(
            "CAD or image file"))] = None,
        view: Annotated[Optional[str], Field(description="Host view")] = None,
        placement: Literal["origin", "center", "shared", "site"] = "origin",
        import_unit: Literal["auto", "mm", "cm", "dm", "m", "ft", "in"] = "auto",
        color_mode: Literal["preserve", "invert", "black_white"] = "preserve",
        current_view_only: bool = False,
        visible_layers_only: bool = False,
        orient_to_view: bool = False,
        pin: bool = True,
        point: Annotated[Optional[List[float]], Field(description="Image centre [x, y]")] = None,
        width: Annotated[Optional[float], Field(description="Image width")] = None,
        link: Annotated[Optional[str], Field(description="CAD name or id")] = None,
        all_instances: Annotated[bool, Field(description="delete: all")] = True,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Link or import CAD (DWG, DXF, DGN, SAT, SKP), place an image, list, reload or delete CAD files.

        dry_run checks the file and options without loading it. delete previews until confirm=true.
        Revit links (.rvt) are handled by manage_links.
        """
        data = compact(
            action=action, path=path, view=view, placement=placement, import_unit=import_unit,
            color_mode=color_mode, current_view_only=current_view_only or None,
            visible_layers_only=visible_layers_only or None, orient_to_view=orient_to_view or None, pin=pin,
            point=point, width=width, link=link, all_instances=all_instances, unit=unit,
            dry_run=dry_run or None, confirm=confirm or None, document=document)
        if action == "delete":
            return await post_confirmable(revit_post, "/insert/files/", data, ctx, 120.0, "insert_files")
        return await post(revit_post, "/insert/files/", data, ctx, timeout=600.0)

    @mcp.tool(annotations=MODIFIES)
    async def load_family(
        paths: Annotated[List[str], Field(description="One or more .rfa files (max 100)")],
        type: Annotated[Optional[str], Field(description="Load only this type (single path)")] = None,
        overwrite: Annotated[bool, Field(description="Reload a family that is already in the document")] = False,
        overwrite_parameter_values: bool = False,
        atomic: Annotated[bool, Field(description="true: one failing file rolls everything back")] = False,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Load family files (.rfa) from disk into the project, or a single type; reports the loaded types.

        To load a family that is open in the family editor use family_load_into_project.
        """
        return await post(revit_post, "/insert/family/", compact(
            paths=paths, type=type, overwrite=overwrite or None,
            overwrite_parameter_values=overwrite_parameter_values or None, atomic=atomic or None,
            dry_run=dry_run or None, document=document), ctx, timeout=600.0)

    @mcp.tool(annotations=MODIFIES)
    async def project_settings(
        action: Literal["get", "set_info", "set_units", "set_starting_view", "set_location"] = "get",
        include: Annotated[Optional[List[Literal["info", "units", "starting_view", "location"]]],
                           Field(description="get: sections (default: all)")] = None,
        values: Annotated[Optional[Dict[str, Any]], Field(description=(
            "set_info: {name: text}, e.g. {'Number': 'P-001', 'Client Name': 'ACME'}"))] = None,
        units: Annotated[Optional[Dict[str, Any]], Field(description=(
            "set_units: {length|area|volume|angle: {unit, rounding}}; units: mm cm m ft in ft_in m_cm / m2 ft2 "
            "/ m3 ft3 l / deg rad"))] = None,
        view: Annotated[Optional[str], Field(description="set_starting_view: view name or id; 'none' = last opened")] = None,
        latitude: Annotated[Optional[float], Field(description="set_location: degrees")] = None,
        longitude: Annotated[Optional[float], Field(description="set_location: degrees")] = None,
        true_north_angle: Annotated[Optional[float], Field(description="Angle from project north to true north, degrees")] = None,
        east_west: Annotated[Optional[float], Field(description="Shared coordinates of the internal origin, in `unit`")] = None,
        north_south: Optional[float] = None,
        elevation: Optional[float] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Project information, project units, the starting view and the project location: read or set.

        Every set action returns the values before the change; ask for a dry run first on units and location.
        """
        return await post(revit_post, "/project/settings/", compact(
            action=action, include=include, values=values, units=units, view=view, latitude=latitude,
            longitude=longitude, true_north_angle=true_north_angle, east_west=east_west,
            north_south=north_south, elevation=elevation, unit=unit, dry_run=dry_run or None,
            document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_styles(
        action: Literal["list_object_styles", "set_object_style", "create_subcategory", "create_line_style",
                        "list_patterns", "create_line_pattern", "create_fill_pattern"] = "list_object_styles",
        category: Annotated[Optional[str], Field(description="Category name, e.g. 'Walls'")] = None,
        subcategory: Optional[str] = None,
        category_type: Literal["model", "annotation", "all"] = "model",
        include_subcategories: Optional[bool] = None,
        name: Annotated[Optional[str], Field(description="create_*: new name")] = None,
        line_weight: Annotated[Optional[int], Field(ge=1, le=16, description="Projection line weight")] = None,
        line_weight_cut: Annotated[Optional[int], Field(ge=1, le=16)] = None,
        line_color: Colour = None,
        line_pattern: Annotated[Optional[str], Field(description="Line pattern name or 'Solid'")] = None,
        material: Annotated[Optional[str], Field(description="Material name; 'none' clears it")] = None,
        segments: Annotated[Optional[List[Dict[str, Any]]], Field(description=(
            "[{type: dash|dot|space, length}]"))] = None,
        target: Literal["drafting", "model"] = "drafting",
        angle: Annotated[Optional[float], Field(description="Fill pattern angle, degrees")] = None,
        spacing: Annotated[Optional[float], Field(description="Line spacing")] = None,
        spacing2: Annotated[Optional[float], Field(description="Second spacing = crosshatch")] = None,
        kinds: Optional[List[Literal["line", "fill"]]] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 80,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Object styles, subcategories, line styles, line patterns and fill patterns: list, set, create.

        set_object_style changes how a whole category prints in every view; show the dry run first.
        """
        return await post(revit_post, "/styles/manage/", compact(
            action=action, category=category, subcategory=subcategory, category_type=category_type,
            include_subcategories=include_subcategories, name=name, line_weight=line_weight,
            line_weight_cut=line_weight_cut, line_color=line_color, line_pattern=line_pattern,
            material=material, segments=segments, target=target, angle=angle, spacing=spacing,
            spacing2=spacing2, kinds=kinds, limit=limit, unit=unit, dry_run=dry_run or None,
            document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def transfer_project_standards(
        source: Annotated[str, Field(description="Title or path of another OPEN document to copy from")],
        action: Literal["list", "copy"] = "list",
        kinds: Optional[List[Literal[
            "view_templates", "filters", "materials", "line_patterns", "fill_patterns", "text_types",
            "dimension_types", "filled_region_types", "wall_types", "floor_types", "ceiling_types",
            "roof_types"]]] = None,
        names: Annotated[Optional[List[str]], Field(description="Only these names (default: all of the kinds)")] = None,
        skip_existing: Annotated[bool, Field(description="Skip names the target already has")] = True,
        on_duplicate_types: Literal["use_target", "abort"] = "use_target",
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        dry_run: bool = False,
        confirm: bool = False,
        document: Annotated[Optional[str], Field(description="Target document (default: active)")] = None,
        ctx: Context = None,
    ) -> str:
        """Copy view templates, filters, materials, patterns and system types from another open document.

        list shows what the source has that the target lacks. Existing names are skipped, never overwritten.
        """
        data = compact(source=source, action=action, kinds=kinds, names=names, skip_existing=skip_existing,
                       on_duplicate_types=on_duplicate_types, limit=limit, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        if action == "copy":
            return await post_confirmable(revit_post, "/standards/transfer/", data, ctx, 600.0,
                                          "transfer_project_standards")
        return await post(revit_post, "/standards/transfer/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def worksharing(
        action: Literal["status", "relinquish", "reload_latest", "acquire_coordinates",
                        "publish_coordinates"] = "status",
        element_ids: Annotated[Optional[List[int]], Field(description="status: who owns these (max 500)")] = None,
        link: Annotated[Optional[str], Field(description="*_coordinates: Revit link name or instance id")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Worksharing: element and workset ownership, relinquish, reload latest, shared coordinates with a link.

        relinquish and reload_latest talk to central and cannot be undone: they need RVTSS_ALLOW_SYNC, like
        sync_with_central. publish_coordinates changes the linked file and previews until confirm=true.
        """
        data = compact(action=action, element_ids=element_ids, link=link, unit=unit, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        if action == "publish_coordinates":
            return await post_confirmable(revit_post, "/worksharing/", data, ctx, 600.0, "worksharing")
        return await post(revit_post, "/worksharing/", data, ctx, timeout=600.0)
