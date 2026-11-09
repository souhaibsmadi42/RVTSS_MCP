# -*- coding: utf-8 -*-
"""RVTSS v2.4 tools: the Modify panel (align, offset, trim / extend, split, scale, flip, cut, paint, parts)."""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import Field

from ._compat import Context, MODIFIES
from ._common import LengthUnit, compact, post_confirmable, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_modify_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=MODIFIES)
    async def modify_elements(
        operation: Literal["align", "offset", "trim_extend", "split", "scale", "flip", "cut", "uncut", "paint",
                           "remove_paint", "create_parts", "divide_parts"],
        element_ids: List[int],
        axis: Annotated[Literal["x", "y", "z"], Field(description="align axis")] = "x",
        reference_id: Annotated[Optional[int], Field(description="align to this element")] = None,
        coordinate: Annotated[Optional[float], Field(description="or to this value")] = None,
        distance: Annotated[Optional[float], Field(description=(
            "offset; positive = left of start -> end"))] = None,
        keep_original: Annotated[bool, Field(description="offset: offset a copy")] = False,
        mode: Annotated[Literal["corner", "single"], Field(description=(
            "single: only the first id changes"))] = "corner",
        point: Annotated[Optional[List[float]], Field(description="split point")] = None,
        parameter: Annotated[Optional[float], Field(description="or 0-1 along it")] = None,
        factor: Annotated[Optional[float], Field(description="scale factor")] = None,
        center: Annotated[Optional[List[float]], Field(description="scale centre")] = None,
        flip: Literal["auto", "hand", "facing", "both", "work_plane"] = "auto",
        material: Annotated[Optional[Union[str, int]], Field(description="paint material")] = None,
        faces: Annotated[Literal["all", "top", "bottom", "interior", "exterior"], Field(description=(
            "faces to paint"))] = "all",
        divider_ids: Annotated[Optional[List[int]], Field(description=(
            "divide_parts: levels, grids, ref planes"))] = None,
        lines: Annotated[Optional[List[List[List[float]]]], Field(description=(
            "divide_parts: [[[x,y],[x,y]], ...] on level"))] = None,
        level: Optional[str] = None,
        unpin: bool = False,
        atomic: Optional[bool] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Modify elements: align, offset, trim/extend to a corner, split, scale, flip, cut/uncut, paint, parts.

        One undo step per call; use dry_run first.
        align: move elements so their x / y / z matches reference_id or coordinate.
        offset: walls and other line-based elements sideways (keep_original=true offsets a copy).
        trim_extend: exactly two straight walls or lines, to their intersection.
        split: one duct, pipe or straight wall at a point (walls with inserts beyond the point are refused).
        scale: lengths of line-based elements and positions of point-based ones, in plan; type sizes
        (wall thickness, family sizes) and sketch-based elements (floors, roofs) do not scale.
        flip: walls, and the hand / facing / work plane of family instances.
        cut / uncut: the first id is cut by each of the others (void families or solids Revit lets cut).
        paint / remove_paint: a material on the faces of walls, floors, roofs... (not family instances).
        create_parts: parts from walls, floors, roofs; divide_parts: by divider_ids and / or lines.
        Move / copy / rotate / mirror / array / pin / join are in transform_elements. The Revit API cannot
        attach wall tops / bases, edit wall profiles, split faces or do linework; do those in Revit.
        """
        data = compact(operation=operation, element_ids=element_ids,
                       axis=axis if operation == "align" else None,
                       reference_id=reference_id, coordinate=coordinate, distance=distance, copy=keep_original or None,
                       mode=mode if operation == "trim_extend" else None, point=point, parameter=parameter,
                       factor=factor, center=center, flip=flip if operation == "flip" else None,
                       material=material,
                       faces=faces if operation in ("paint", "remove_paint") else None,
                       divider_ids=divider_ids, lines=lines, level=level, unpin=unpin or None, atomic=atomic,
                       unit=unit, dry_run=dry_run or None, confirm=confirm or None, document=document)
        return await post_confirmable(revit_post, "/modify/elements/", data, ctx, 180.0, "modify_elements")
