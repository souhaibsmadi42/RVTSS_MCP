# -*- coding: utf-8 -*-
"""RVTSS v2.2 materials tools."""
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, Field

from ._compat import Context, READ_ONLY, MODIFIES
from ._common import ElementScope, compact, post, post_confirmable, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


class MaterialProperties(BaseModel):
    color: Optional[str] = Field(None, description="Shading colour '#RRGGBB'")
    transparency: Optional[int] = Field(None, ge=0, le=100)
    shininess: Optional[int] = Field(None, ge=0, le=128)
    material_class: Optional[str] = None
    use_render_appearance: Optional[bool] = None
    surface_pattern: Optional[str] = Field(None, description="Model fill pattern name")
    surface_pattern_color: Optional[str] = None
    cut_pattern: Optional[str] = Field(None, description="Drafting fill pattern name")
    cut_pattern_color: Optional[str] = None


def register_materials_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def list_materials(
        contains: Optional[str] = None,
        material_class: Optional[str] = None,
        include_usage: Annotated[bool, Field(description="Count model elements using each material (slower)")] = False,
        unused_only: Annotated[bool, Field(description="With include_usage: only materials no element uses")] = False,
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Materials with class, colour, transparency, appearance asset, fill patterns and (optionally) usage."""
        return await post(revit_post, "/materials/list/", compact(
            contains=contains, material_class=material_class, include_usage=include_usage or None,
            unused_only=unused_only or None, offset=offset, limit=limit, document=document), ctx, timeout=180.0)

    @mcp.tool(annotations=READ_ONLY)
    async def material_takeoff(
        scope: Annotated[ElementScope, Field(description="Which elements, e.g. {categories: ['Walls','Floors']}")],
        group_by: Optional[List[Literal["material", "category", "level", "type"]]] = None,
        include_paint: bool = True,
        area_unit: Literal["m2", "ft2", "mm2"] = "m2",
        volume_unit: Literal["m3", "ft3", "mm3"] = "m3",
        offset: int = 0,
        limit: Annotated[int, Field(ge=1, le=2000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Quantity take-off by material: area and volume per material (and category / level / type).

        Uses Revit's material quantities (GetMaterialArea / GetMaterialVolume) per element; painted
        faces are reported separately. Rows are sorted by volume.
        """
        return await post(revit_post, "/materials/takeoff/", compact(
            filter=scope, group_by=group_by, include_paint=include_paint, area_unit=area_unit,
            volume_unit=volume_unit, offset=offset, limit=limit, document=document), ctx, timeout=300.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_materials(
        action: Literal["create", "duplicate", "rename", "set_properties", "assign"],
        material: Annotated[Optional[str], Field(description="Existing material name or id")] = None,
        name: Annotated[Optional[str], Field(description="create / duplicate / rename: new name")] = None,
        properties: Optional[MaterialProperties] = None,
        element_ids: Annotated[Optional[List[int]], Field(description="assign: elements or types")] = None,
        parameter: Annotated[Optional[str], Field(description="assign: material parameter (default 'Material'; "
                                                              "e.g. 'Structural Material')")] = None,
        layer_index: Annotated[Optional[int], Field(description="assign: compound-structure layer of the wall / "
                                                                "floor / roof type (edits the type)")] = None,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create, duplicate, rename or restyle materials, or assign one to elements, types or type layers.

        assign sets an instance/type material parameter (type parameters change every instance) or a
        compound-structure layer (layer_index). Large assignments return a preview until confirm=true.
        """
        data = compact(action=action, material=material, name=name, properties=properties, element_ids=element_ids,
                       parameter=parameter, layer_index=layer_index, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        return await post_confirmable(revit_post, "/materials/manage/", data, ctx, 120.0, "manage_materials")
