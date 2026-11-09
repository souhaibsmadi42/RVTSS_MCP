# -*- coding: utf-8 -*-
"""RVTSS v2.4 MEP editing tools: connections and fittings, flex / placeholder / inline parts, insulation, systems."""
from typing import Annotated, List, Literal, Optional

from pydantic import Field

from ._compat import Context, MODIFIES, DESTRUCTIVE
from ._common import LengthUnit, compact, post, DOC_HELP

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_mep_edit_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=MODIFIES)
    async def mep_connect(
        action: Literal["connect", "elbow", "tee", "cross", "transition", "union", "cap", "disconnect"],
        element_ids: Annotated[List[int], Field(description=(
            "connect / elbow / transition / union: 2 elements; tee: [run 1, run 2, branch]; cross: [run 1, "
            "run 2, branch 1, branch 2]; cap: pipes (the API has none for ducts); disconnect: 1 element (all) or 2 (between them)"))],
        tolerance: Annotated[float, Field(description="connect: largest gap between the two ends, in `unit`")] = 1.0,
        atomic: Annotated[bool, Field(description="cap: stop at the first failure")] = False,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Connect MEP elements: join two ends, add an elbow / tee / cross / transition / union, cap open ends, disconnect.

        The nearest free connectors of the elements are used. Fittings come from the routing preferences of
        the duct / pipe type; Revit refuses when no matching fitting is loaded. One undo step.
        """
        return await post(revit_post, "/mep/connect/", compact(
            action=action, element_ids=element_ids, tolerance=tolerance if action == "connect" else None,
            atomic=atomic or None, unit=unit, dry_run=dry_run or None, confirm=confirm or None,
            document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def create_mep_parts(
        action: Literal["flex_duct", "flex_pipe", "duct_placeholder", "pipe_placeholder", "convert_placeholders",
                        "insert_on_curve", "air_terminal_on_duct"],
        points: Annotated[Optional[List[List[float]]], Field(description=(
            "flex / placeholder: route [[x, y(, z)], ...]; z defaults to the level elevation + offset"))] = None,
        level: Optional[str] = None,
        offset: Annotated[Optional[float], Field(description="Height above the level in `unit`")] = None,
        type: Annotated[Optional[str], Field(description=(
            "Flex duct / flex pipe / duct / pipe type; insert_on_curve: family type name"))] = None,
        family: Annotated[Optional[str], Field(description="insert_on_curve: family name")] = None,
        type_id: Annotated[Optional[int], Field(description="insert_on_curve: family type id")] = None,
        system_type: Annotated[Optional[str], Field(description="Duct / piping system type (default: first)")] = None,
        diameter: Annotated[Optional[float], Field(description="Round size in `unit`")] = None,
        host_id: Annotated[Optional[int], Field(description=(
            "insert_on_curve: the duct or pipe to break; air_terminal_on_duct: the duct"))] = None,
        point: Annotated[Optional[List[float]], Field(description="insert_on_curve: [x, y, z] on the duct / pipe")] = None,
        terminal_id: Annotated[Optional[int], Field(description="air_terminal_on_duct: the air terminal")] = None,
        element_ids: Annotated[Optional[List[int]], Field(description="convert_placeholders: placeholder ids")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Create MEP parts: flex ducts and pipes, placeholders, an accessory or fitting inserted on a duct / pipe.

        insert_on_curve breaks the duct / pipe at the point, places the family instance and connects both
        sides; connection problems are reported per connector. Rigid runs: create_elements. One undo step.
        """
        return await post(revit_post, "/mep/create/", compact(
            action=action, points=points, level=level, offset=offset, type=type, family=family, type_id=type_id,
            system_type=system_type, diameter=diameter, host_id=host_id, point=point, terminal_id=terminal_id,
            element_ids=element_ids, unit=unit, dry_run=dry_run or None, document=document), ctx, timeout=120.0)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def mep_insulation(
        element_ids: Annotated[List[int], Field(description="Ducts, pipes, their fittings and accessories")],
        action: Literal["list", "add", "remove"] = "list",
        kind: Annotated[Literal["insulation", "lining"], Field(description="lining: ducts and duct fittings only")] = "insulation",
        type: Annotated[Optional[str], Field(description="Insulation / lining type name (default: first)")] = None,
        thickness: Annotated[Optional[float], Field(description="add: thickness in `unit`")] = None,
        replace: Annotated[bool, Field(description="add: replace what is already there")] = False,
        atomic: bool = False,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Insulation on ducts and pipes and lining on ducts: list, add (type and thickness), remove."""
        return await post(revit_post, "/mep/insulation/", compact(
            element_ids=element_ids, action=action, kind=kind, type=type, thickness=thickness,
            replace=replace or None, atomic=atomic or None, unit=unit, dry_run=dry_run or None,
            confirm=confirm or None, document=document), ctx, timeout=180.0)

    @mcp.tool(annotations=MODIFIES)
    async def manage_mep_systems(
        action: Literal["create", "add_elements", "remove_elements", "rename", "set_system_type", "list_circuits",
                        "create_circuit", "select_panel", "create_panel_schedule"],
        element_ids: Optional[List[int]] = None,
        domain: Annotated[Optional[Literal["mechanical", "piping"]], Field(description="create")] = None,
        system: Annotated[Optional[str], Field(description="System name or id")] = None,
        name: Annotated[Optional[str], Field(description="create / rename: system name")] = None,
        system_type: Annotated[Optional[str], Field(description="Duct / piping system type name")] = None,
        circuit_type: Annotated[Optional[Literal["power", "data", "telephone", "fire_alarm", "security",
                                                 "nurse_call", "communication", "controls"]],
                                Field(description="create_circuit (default power)")] = None,
        circuit_id: Optional[int] = None,
        panel_id: Annotated[Optional[int], Field(description="Panel (electrical equipment) id")] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
        atomic: bool = False,
        dry_run: bool = False,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """MEP systems: create a duct or piping system, add / remove elements, rename, set system types; circuits and panel schedules.

        Reading systems: list_mep_systems. The Revit API has no automatic duct / pipe sizing; set sizes with
        set_parameters.
        """
        return await post(revit_post, "/mep/systems/manage/", compact(
            action=action, element_ids=element_ids, domain=domain, system=system, name=name,
            system_type=system_type, circuit_type=circuit_type, circuit_id=circuit_id, panel_id=panel_id,
            limit=limit if action == "list_circuits" else None, atomic=atomic or None,
            dry_run=dry_run or None, confirm=confirm or None, document=document), ctx, timeout=180.0)
