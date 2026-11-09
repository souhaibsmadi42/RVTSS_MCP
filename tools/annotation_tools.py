# -*- coding: utf-8 -*-
"""RVTSS annotation tools: untagged checks, tagging, text notes (v2.2); detailing, type lists (v2.3)."""
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ._compat import Context, READ_ONLY, MODIFIES
from ._common import LengthUnit, compact, post, post_confirmable, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
ViewRef = Annotated[Optional[str], Field(description="View name, id or 'active'")]


class TextNoteSpec(BaseModel):
    text: str
    point: List[float] = Field(description="[x, y] or [x, y, z] in `unit` (model coordinates of the view)")
    type: Optional[str] = Field(None, description="Text note type name (default: the project default)")


def register_annotation_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def find_untagged_elements(
        categories: Annotated[List[str], Field(min_length=1, description="e.g. ['Doors','Windows','Rooms']")],
        view: ViewRef = "active",
        limit: Annotated[int, Field(ge=1, le=2000)] = 200,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Elements of the categories visible in a view that have no tag in that view (incl. room/space/area tags)."""
        return await post(revit_post, "/annotation/untagged/", compact(
            categories=categories, view=view, limit=limit, document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def tag_elements(
        view: ViewRef = "active",
        element_ids: Optional[List[int]] = None,
        categories: Annotated[Optional[List[str]], Field(description="Tag every element of these categories "
                                                                     "visible in the view")] = None,
        tag_type: Annotated[Optional[str], Field(description="'Family : Type', type name or id (default: the "
                                                             "category's loaded tag)")] = None,
        skip_tagged: bool = True,
        leader: bool = False,
        orientation: Literal["horizontal", "vertical"] = "horizontal",
        offset: Annotated[Optional[List[float]], Field(description="[dx, dy] from the element point in `unit`")] = None,
        atomic: Annotated[bool, Field(description="false (default): skip elements that cannot be tagged")] = False,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Tag elements in a view - by ids or whole categories; rooms, spaces and areas get their own tags.

        Already-tagged elements are skipped. More than RVTSS_CONFIRM_THRESHOLD tags returns a preview
        until confirm=true. Needs a tag family loaded for each category (or tag_type).
        """
        data = compact(view=view, element_ids=element_ids, categories=categories, tag_type=tag_type,
                       skip_tagged=skip_tagged, leader=leader or None, orientation=orientation, offset=offset,
                       atomic=atomic or None, unit=unit, dry_run=dry_run or None, confirm=confirm or None,
                       document=document)
        return await post_confirmable(revit_post, "/annotation/tag/", data, ctx, 300.0, "tag_elements")

    @mcp.tool(annotations=MODIFIES)
    async def create_text_notes(
        notes: Annotated[List[TextNoteSpec], Field(min_length=1, max_length=200)],
        view: ViewRef = "active",
        text_type: Annotated[Optional[str], Field(description="Default text note type for all notes")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Place text notes in a view (one transaction; all or nothing)."""
        return await post(revit_post, "/annotation/text/", compact(
            notes=notes, view=view, text_type=text_type, unit=unit, dry_run=dry_run or None, document=document),
            ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def create_detailing(
        items: Annotated[List[Dict[str, Any]], Field(min_length=1, max_length=500, description=(
            "Model points in `unit`, projected onto the view ([x,y] plans, [x,y,z] sections).\n"
            "dimension: {element_ids (grids/levels/ref planes/walls/instances), start, end, type?, "
            "wall_face?, instance_reference?}\n"
            "detail_line: {start, end | points, closed?, line_style?}\n"
            "filled_region: {boundary, type?}\nmasking_region: {boundary}\n"
            "revision_cloud: {boundary, revision? (id, sequence, description or 'latest')}\n"
            "spot_elevation | spot_coordinate: {element_id (floor/roof/ceiling), point, leader?, offset?}\n"
            "detail_component: {type ('Family : Type'), point | start+end} - detail items and symbols\n"
            "Each item needs kind."))],
        view: ViewRef = "active",
        unit: LengthUnit = "mm",
        atomic: bool = True,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Dimensions, detail lines, filled and masking regions, revision clouds, spot dimensions and detail
        components in one view (one undo step).

        wall_face: exterior | interior. instance_reference: center_left_right | center_front_back |
        left | right | front | back | top | bottom. Names come from list_annotation_types.
        atomic=false keeps the items that succeed.
        """
        return await post(revit_post, "/annotation/detail/", compact(
            items=items, view=view, unit=unit, atomic=atomic, dry_run=dry_run or None, document=document),
            ctx, timeout=180.0)

    @mcp.tool(annotations=MODIFIES)
    async def replace_text(
        find: str,
        replace: str = "",
        views: Annotated[Optional[List[str]], Field(description="View names / ids / 'active' (default: the "
                                                                "whole model)")] = None,
        regex: bool = False,
        match_case: bool = False,
        whole_word: bool = False,
        dry_run: bool = True,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Find and replace text in text notes, in some views or the whole model. dry_run by default.

        The dry run lists every note with its old and new text. Mixed formatting inside a changed note
        (bold / italic runs) is lost, because Revit replaces the whole text.
        """
        data = compact(find=find, replace=replace, views=views, regex=regex or None, match_case=match_case or None,
                       whole_word=whole_word or None, dry_run=dry_run or None, confirm=confirm or None,
                       document=document)
        return await post_confirmable(revit_post, "/annotation/text/replace/", data, ctx, 300.0, "replace_text")

    @mcp.tool(annotations=READ_ONLY)
    async def list_annotation_types(
        kinds: Optional[List[Literal["text", "tag", "dimension", "filled_region", "line_style"]]] = None,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Text note types, tag types (by category), dimension types, filled region types and line styles."""
        return await post(revit_post, "/annotation/types/", compact(kinds=kinds, document=document), ctx)
