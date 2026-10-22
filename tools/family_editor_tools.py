# -*- coding: utf-8 -*-
"""RVTSS family editor tools: create and edit real .rfa family documents."""
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ._compat import Context, READ_ONLY, MODIFIES, DESTRUCTIVE, IDEMPOTENT
from .utils import format_response
from ._common import LengthUnit, ValueUnit, Scalar, compact, post, call_with_progress

FamDoc = Annotated[Optional[str], Field(description="Family document title/path (default: active)")]

ParamType = Literal["length", "area", "volume", "angle", "slope", "number", "integer", "text", "multiline_text",
                    "url", "yesno", "material", "image", "currency", "mass", "force"]
ParamGroup = Literal["dimensions", "constraints", "construction", "data", "identity_data", "materials", "graphics",
                     "text", "general", "phasing", "visibility", "fire_protection", "structural", "mechanical",
                     "electrical", "plumbing", "energy_analysis", "ifc", "other"]
# ~50 template kinds (door, window, furniture, casework, generic_model, ... see revit_mcp/pure/templates.py).
# Kept as a plain string to keep the tool listing small; Revit validates it and lists the valid kinds.
TemplateKind = Annotated[str, Field(description="e.g. door, window, furniture, casework, generic_model, "
                                                "generic_model_wall_based, lighting_fixture (family_list_templates lists all)")]


class FamilyParameterSpec(BaseModel):
    name: str
    type: ParamType = "length"
    group: Optional[ParamGroup] = Field(None, description="Default: dimensions for measurable types, materials for material, else data")
    instance: bool = Field(False, description="Instance parameter (true) or type parameter (false)")
    value: Scalar = Field(None, description="Initial value for the current type")
    unit: Optional[ValueUnit] = Field(None, description="Unit of value (required for dimensional numbers)")
    formula: Optional[str] = Field(None, description="Revit formula, e.g. 'Width - 2 * Frame Thickness'")
    shared: bool = Field(False, description="Add the shared definition with this name from the shared parameter file (keeps its GUID)")
    guid: Optional[str] = Field(None, description="Pick the shared definition by GUID instead of name")
    reporting: bool = False
    if_exists: Literal["skip", "error"] = "skip"


class FormSpec(BaseModel):
    kind: Literal["extrusion", "blend", "revolution", "sweep"] = "extrusion"
    void: bool = False
    work_plane: str = Field("level", description="'level' (Ref. Level) or a reference plane name, e.g. 'Center (Front/Back)'")
    coordinates: Literal["local", "world"] = Field("local", description="local: [u, v] in the work plane; world: [x, y, z] projected")
    profile: Optional[Dict[str, Any]] = Field(None, description=(
        "{rectangle: {min: [u,v], max: [u,v]}} | {circle: {center: [u,v], radius}} | {loops: [[[u,v], ...], ...]}"))
    base_profile: Optional[Dict[str, Any]] = Field(None, description="blend: bottom profile")
    top_profile: Optional[Dict[str, Any]] = Field(None, description="blend: top profile")
    start: Optional[float] = Field(None, description="extrusion start offset")
    end: Optional[float] = Field(None, description="extrusion end offset (depth), default 1000")
    height: Optional[float] = Field(None, description="blend height")
    axis: Optional[List[List[float]]] = Field(None, description="revolution axis [[u,v],[u,v]] in the work plane")
    start_angle: Optional[float] = None
    end_angle: Optional[float] = None
    path: Optional[List[List[float]]] = Field(None, description="sweep path points [[u,v], ...] in the work plane")
    material_parameter: Optional[str] = Field(None, description="Associate the form material to this family parameter (created if missing)")
    visible_parameter: Optional[str] = Field(None, description="Associate visibility to a Yes/No parameter (created if missing)")
    end_parameter: Optional[str] = Field(None, description="extrusion: drive the end offset with a length parameter")
    start_parameter: Optional[str] = None
    instance_parameters: bool = False
    visibility: Optional[Dict[str, bool]] = Field(None, description="{coarse, medium, fine, plan, front_back, left_right}")
    subcategory: Optional[str] = Field(None, description="Object subcategory (created if missing)")
    cut_solids: bool = Field(True, description="void: cut intersecting solids")
    align: bool = Field(False, description="Lock faces that coincide with reference planes")


class ReferencePlaneSpec(BaseModel):
    name: str
    orientation: Literal["x", "y", "z"] = Field(description="x: left/right (normal X), y: front/back, z: horizontal")
    offset: float = Field(0, description="Position along the normal axis in `unit`")
    is_reference: Optional[Literal["NotAReference", "Left", "CenterLeftRight", "Right", "Front", "CenterFrontBack",
                                   "Back", "Bottom", "CenterElevation", "Top", "StrongReference", "WeakReference"]] = None
    if_exists: Literal["reuse", "error"] = "reuse"


class DimensionSpec(BaseModel):
    references: List[str] = Field(description="2+ parallel reference planes by name; 'Ref. Level' for the level")
    label: Optional[str] = Field(None, description="Length/angle family parameter that drives the dimension")
    equality: bool = Field(False, description="EQ constraint (needs 3+ references)")
    lock: bool = False
    line_offset: Optional[float] = Field(None, description="Where to draw the dimension line, in `unit`")


class FlexCase(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = Field(None, description="Switch to this family type")
    values: Optional[Dict[str, Any]] = Field(None, description="{param: value} or {param: {value, unit}}")


def register_family_editor_tools(mcp, revit_get, revit_post):
    """Register family document tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def family_list_templates(
        kind: Optional[TemplateKind] = None,
        unit_system: Optional[Literal["metric", "imperial"]] = None,
        contains: Optional[str] = None,
        search_dirs: Optional[List[str]] = None,
        ctx: Context = None,
    ) -> str:
        """Find family templates (.rft) for a kind (best first) or show which kinds are available/missing.

        Inspect family template folders (Revit's FamilyTemplatePath + extra dirs). With `kind`, returns
        matching .rft files best first and reports when none exists; without, shows the best template
        per kind and which kinds are missing.
        """
        return await post(revit_post, "/family/templates/", compact(kind=kind, unit_system=unit_system,
                                                                     contains=contains, search_dirs=search_dirs), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def family_create(
        kind: Optional[TemplateKind] = None,
        template_path: Optional[str] = None,
        save_path: Annotated[Optional[str], Field(description="Full .rfa path to save immediately (recommended)")] = None,
        category: Annotated[Optional[str], Field(description="Override the template category, e.g. 'Furniture'")] = None,
        type_name: Optional[str] = None,
        unit_system: Literal["metric", "imperial"] = "metric",
        overwrite: bool = False,
        search_dirs: Optional[List[str]] = None,
        ctx: Context = None,
    ) -> str:
        """Create a new .rfa family from a template (by kind or template_path); opens in the background - pass
        its title as `document`.

        Create a NEW family document (.rfa) from a Revit family template, chosen by kind (door, window,
        furniture, casework, generic_model, ...) or explicit template_path. The family opens in the
        background; pass its title as `document` to the other family_* tools.
        """
        data = compact(kind=kind, template_path=template_path, save_path=save_path, category=category,
                       type_name=type_name, unit_system=unit_system, overwrite=overwrite or None,
                       search_dirs=search_dirs)
        return await post(revit_post, "/family/create/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def family_open(
        path: Annotated[Optional[str], Field(description="Path of an .rfa file")] = None,
        family_name: Annotated[Optional[str], Field(description="Name of a family loaded in the active project (Edit Family)")] = None,
        ctx: Context = None,
    ) -> str:
        """Open an existing family for editing - from an .rfa file or a family loaded in the project."""
        return await post(revit_post, "/family/open/", compact(path=path, family_name=family_name), ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def family_get_info(
        document: FamDoc = None,
        include: Optional[List[Literal["parameters", "types", "reference_planes", "dimensions", "forms", "nested",
                                       "properties"]]] = None,
        include_builtin: bool = False,
        max_types: int = 50,
        unit: LengthUnit = "mm",
        ctx: Context = None,
    ) -> str:
        """Inspect a family: properties, parameters (formula, shared GUID, associations, labels), types with
        values, reference planes, dimensions, forms, nested families.

        Inspect a family document: category and family properties, parameters (instance/type, spec,
        group, formula, shared GUID, reporting, associations, labelled dimensions), types with values,
        reference planes, dimensions, solid/void forms with associated parameters, and nested families.
        """
        return await post(revit_post, "/family/info/", compact(document=document, include=include,
                                                                include_builtin=include_builtin or None,
                                                                max_types=max_types, unit=unit), ctx, timeout=60.0)

    @mcp.tool(annotations=IDEMPOTENT)
    async def family_set_properties(
        document: FamDoc = None,
        category: Optional[str] = None,
        set: Annotated[Optional[Dict[str, bool]], Field(description=(
            "{work_plane_based, always_vertical, shared, room_calculation_point, cut_with_voids}"))] = None,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Change the family category and family-level settings (shared, work plane based, always vertical...)."""
        return await post(revit_post, "/family/properties/", compact(document=document, category=category, set=set,
                                                                      dry_run=dry_run or None), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def family_add_parameters(
        parameters: List[FamilyParameterSpec],
        document: FamDoc = None,
        naming_pattern: Annotated[Optional[str], Field(description="Regex every new name must match")] = None,
        atomic: bool = True,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Add family parameters (type/instance, any data type, value, formula, reporting, or shared with its
        GUID). Formulas are checked before Revit applies them.

        Add family parameters (type or instance; any data type; optional initial value, formula,
        reporting; or shared definitions with their existing GUID). Existing names are skipped. Formulas
        are pre-checked for unknown names and circular references, then validated by Revit.
        """
        data = compact(action="add", parameters=parameters, document=document, naming_pattern=naming_pattern,
                       atomic=atomic, dry_run=dry_run or None)
        return await post(revit_post, "/family/parameters/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def family_edit_parameters(
        action: Literal["list", "remove", "rename", "set_formula", "set_instance", "set_reporting",
                        "replace_with_shared", "associate", "set_values"],
        parameters: Annotated[Optional[List[Dict[str, Any]]], Field(description=(
            "remove: {name} | rename: {name, new_name} | set_formula: {name, formula} (empty formula clears) | "
            "set_instance: {name, instance} | set_reporting: {name, reporting} | "
            "replace_with_shared: {name, shared_name?|guid?, group?, instance?} | "
            "associate: {element_id, element_parameter, name} (name omitted = dissociate) | "
            "set_values: {name, value, unit?} on the current type"))] = None,
        document: FamDoc = None,
        shared_parameter_file: Optional[str] = None,
        atomic: bool = True,
        dry_run: bool = False,
        unit: LengthUnit = "mm",
        ctx: Context = None,
    ) -> str:
        """Edit existing family parameters. Shared parameters keep their GUID and cannot be renamed
        (Revit API limitation) - use replace_with_shared to swap definitions."""
        data = compact(action=action, parameters=parameters, document=document,
                       shared_parameter_file=shared_parameter_file, atomic=atomic, dry_run=dry_run or None, unit=unit)
        return await post(revit_post, "/family/parameters/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def family_manage_types(
        action: Literal["list", "create", "upsert", "duplicate", "rename", "delete", "set_values",
                        "export_catalog", "import_catalog"] = "list",
        types: Annotated[Optional[List[Dict[str, Any]]], Field(description=(
            "create/upsert: {name, values: {param: value|{value, unit}}, based_on?} | duplicate: {source, new_name, "
            "values?} | rename: {name, new_name} | delete: {name} | set_values: {name, values}"))] = None,
        document: FamDoc = None,
        parameters: Annotated[Optional[List[str]], Field(description="list: only these parameters")] = None,
        path: Annotated[Optional[str], Field(description="Type catalog .txt path (default: next to the .rfa)")] = None,
        catalog_text: Optional[str] = None,
        overwrite: bool = False,
        strict: Annotated[bool, Field(description="Roll back everything if any value fails")] = True,
        unit: Annotated[LengthUnit, Field(description="Unit for plain numeric values of length parameters")] = "mm",
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Family types: list, create/upsert, duplicate, rename, delete, set values per type; export/import
        type catalogs.

        List, create, duplicate, rename, delete family types and set per-type values; export or import a
        Revit type catalog (.txt). Example: three door sizes -> action='create',
        types=[{name:'900x2100', values:{Width:900, Height:2100}}, ...].
        """
        data = compact(action=action, types=types, document=document, parameters=parameters, path=path,
                       catalog_text=catalog_text, overwrite=overwrite or None, strict=strict, unit=unit,
                       dry_run=dry_run or None)
        return await post(revit_post, "/family/types/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def family_create_reference_planes(
        planes: Optional[List[ReferencePlaneSpec]] = None,
        action: Literal["create", "list"] = "create",
        document: FamDoc = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Create named reference planes (x: left/right, y: front/back, z: horizontal) at offsets, or list them."""
        return await post(revit_post, "/family/reference_planes/", compact(planes=planes, action=action,
                                                                            document=document, unit=unit,
                                                                            dry_run=dry_run or None), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def family_create_form(
        forms: List[FormSpec],
        document: FamDoc = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Create solid/void extrusion, blend, revolution or sweep on a work plane, with
        material/visibility/end parameter links, subcategory and face locking.

        Create solid or void extrusions, blends, revolutions and sweeps on a work plane, optionally
        associating material / visibility / extrusion end to family parameters, setting detail-level
        visibility and subcategory, cutting solids with voids and locking faces to reference planes.
        """
        return await post(revit_post, "/family/forms/", compact(forms=forms, document=document, unit=unit,
                                                                 dry_run=dry_run or None), ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def family_add_dimension(
        dimensions: List[DimensionSpec],
        document: FamDoc = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Dimension between parallel reference planes (or Ref. Level) and label it with a parameter
        (e.g. Left-Right labelled Width), add EQ constraints (Left-Center-Right) or lock it."""
        return await post(revit_post, "/family/dimension/", compact(dimensions=dimensions, document=document,
                                                                     unit=unit, dry_run=dry_run or None), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def family_align_geometry(
        document: FamDoc = None,
        form_ids: Annotated[Optional[List[int]], Field(description="Default: all solid forms")] = None,
        planes: Annotated[Optional[List[str]], Field(description="Default: every reference plane + Ref. Level")] = None,
        lock: bool = True,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Lock form faces to the reference planes they lie on, so geometry follows labelled dimensions."""
        return await post(revit_post, "/family/align/", compact(document=document, form_ids=form_ids, planes=planes,
                                                                 lock=lock, dry_run=dry_run or None), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def family_build_parametric_box(
        document: FamDoc = None,
        width: float = 900,
        depth: float = 600,
        height: float = 750,
        width_parameter: str = "Width",
        depth_parameter: str = "Depth",
        height_parameter: str = "Height",
        material_parameter: Annotated[Optional[str], Field(description="Material parameter name ('' to skip)")] = "Material",
        instance_parameters: bool = False,
        center_equality: bool = True,
        subcategory: Optional[str] = None,
        flex_check: Annotated[bool, Field(description="Flex x1.5 / x0.5 afterwards and verify the bounding box")] = True,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """One call: fully constrained parametric box (planes, Width/Depth labels with EQ, locked extrusion,
        Height, Material) + flex check. Base for furniture/casework/equipment.

        Build a genuinely parametric box in one step: Left/Right/Front/Back reference planes centred on
        the template's centre planes, Width/Depth labelled dimensions with EQ, a solid extrusion with
        all four sides locked, Height driving the extrusion end and a Material parameter - then flex it
        to prove the geometry follows the parameters. Ideal base for furniture, casework and equipment.
        """
        data = compact(document=document, width=width, depth=depth, height=height, width_parameter=width_parameter,
                       depth_parameter=depth_parameter, height_parameter=height_parameter,
                       material_parameter=material_parameter, instance_parameters=instance_parameters or None,
                       center_equality=center_equality, subcategory=subcategory, flex_check=flex_check, unit=unit,
                       dry_run=dry_run or None)
        response = await call_with_progress(revit_post, "/family/build_box/", data, ctx, 180.0, "Parametric box")
        return format_response(response)

    @mcp.tool(annotations=MODIFIES)
    async def family_nested(
        action: Literal["load", "place"],
        document: FamDoc = None,
        path: Annotated[Optional[str], Field(description="load: .rfa to nest")] = None,
        family: Optional[str] = None,
        type: Optional[str] = None,
        point: Optional[List[float]] = None,
        associate: Annotated[Optional[Dict[str, str]], Field(description="place: {nested parameter: host family parameter}")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """Load a family into the family being edited and place it, linking nested parameters to host
        family parameters (parameter associations)."""
        data = compact(action=action, document=document, path=path, family=family, type=type, point=point,
                       associate=associate, unit=unit, dry_run=dry_run or None)
        return await post(revit_post, "/family/nested/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=READ_ONLY)
    async def family_flex_test(
        document: FamDoc = None,
        cases: Annotated[Optional[List[FlexCase]], Field(description="Default: every type, then +20% on each length parameter")] = None,
        expect: Annotated[Optional[Dict[Literal["x", "y", "z"], str]], Field(description="Bounding box axis -> parameter, e.g. {x:'Width'}")] = None,
        tolerance: float = 0.5,
        unit: LengthUnit = "mm",
        ctx: Context = None,
    ) -> str:
        """Flex a family through types/values, measure geometry, report constraint errors and parameters with
        no effect; all rolled back.

        Flex a family: apply types / parameter values, regenerate and measure geometry, report Revit
        constraint errors and parameters with no geometric effect. Everything is rolled back.
        """
        response = await call_with_progress(revit_post, "/family/flex/", compact(document=document, cases=cases, expect=expect,
                                                                tolerance=tolerance, unit=unit), ctx, 180.0, "Flex test")
        return format_response(response)

    @mcp.tool(annotations=READ_ONLY)
    async def family_validate(
        document: FamDoc = None,
        expected_category: Optional[str] = None,
        parameter_naming_pattern: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """QC a family: category, formulas, parameters that drive nothing, type values, geometry, labelled
        dimensions, warnings - with severity and fixes.

        Quality-control a family: category, formulas (syntax, unknown names, circular references),
        parameters that drive nothing, types missing values or with zero dimensions, invalid geometry,
        missing labelled dimensions (not parametric) and Revit warnings - with severities and fixes.
        """
        return await post(revit_post, "/family/validate/", compact(
            document=document, expected_category=expected_category,
            parameter_naming_pattern=parameter_naming_pattern), ctx, timeout=120.0)

    @mcp.tool(annotations=IDEMPOTENT)
    async def family_save(
        document: FamDoc = None,
        save_path: Annotated[Optional[str], Field(description="Save As path (.rfa). Omit to save in place")] = None,
        overwrite: bool = False,
        compact_file: bool = False,
        backup: Annotated[bool, Field(description="Copy the existing file to %APPDATA%/RVTSS/backups first")] = True,
        ctx: Context = None,
    ) -> str:
        """Save the family document. Existing files are backed up to %APPDATA%/RVTSS/backups before being
        overwritten."""
        return await post(revit_post, "/family/save/", compact(document=document, save_path=save_path,
                                                                overwrite=overwrite or None,
                                                                compact=compact_file or None, backup=backup),
                          ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def family_load_into_project(
        document: FamDoc = None,
        project: Annotated[Optional[str], Field(description="Target project title (default: active/only project)")] = None,
        overwrite: Annotated[bool, Field(description="Reload if the family already exists in the project")] = True,
        overwrite_parameter_values: Annotated[bool, Field(description="Also overwrite type parameter values in the project")] = False,
        ctx: Context = None,
    ) -> str:
        """Load (or reload) the family into a project and verify that all its types arrived."""
        return await post(revit_post, "/family/load_into_project/", compact(
            document=document, project=project, overwrite=overwrite,
            overwrite_parameter_values=overwrite_parameter_values), ctx, timeout=180.0)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def family_close(
        document: FamDoc = None,
        save: bool = False,
        discard_changes: Annotated[bool, Field(description="Required to close with unsaved changes and save=false")] = False,
        ctx: Context = None,
    ) -> str:
        """Close a background family document (refuses to drop unsaved changes unless discard_changes=true)."""
        return await post(revit_post, "/family/close/", compact(document=document, save=save,
                                                                 discard_changes=discard_changes or None), ctx)
