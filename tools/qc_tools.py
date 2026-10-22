# -*- coding: utf-8 -*-
"""RVTSS BIM coordination and quality-control tools."""
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from ._compat import Context, READ_ONLY, MODIFIES, structured_return
from ._outputs import FindingsOut
from .utils import format_response
from ._common import LengthUnit, compact, DOC_HELP, call_with_progress, post_structured

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]
CheckName = Literal["warnings", "duplicates", "naming", "similar_family_names", "duplicate_types",
                    "unused_families", "in_place_families", "cad_imports", "links", "rooms",
                    "views_not_on_sheets", "sheets", "required_parameters", "groups", "iso19650", "view_audit"]


def register_qc_tools(mcp, revit_get, revit_post):
    """Register QC tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def run_model_checks(
        checks: Annotated[Optional[List[CheckName]], Field(description="Default: all checks")] = None,
        rules: Annotated[Optional[Dict[str, Any]], Field(description=(
            "Project rules (merged over %APPDATA%/RVTSS/qc_rules.json): {naming: {views|sheets|levels|families|types: "
            "{pattern, severity, description}}, required_parameters: [{categories, parameters, severity}], "
            "sheet_parameters: [...]}"))] = None,
        sheet_parameters: Optional[List[str]] = None,
        duplicate_tolerance: Annotated[float, Field(description="Distance in `unit` for duplicate detection")] = 1.0,
        min_severity: Literal["info", "warning", "error", "critical"] = "info",
        max_findings: int = 200,
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> structured_return(FindingsOut):
        """BIM QC report (warnings, duplicates, naming, families/types, CAD, links, rooms, views, sheets,
        required parameters, groups) with severity, ids and fixes.

        BIM quality report: warnings, duplicate elements, naming standards, near-duplicate families,
        duplicate types, unused / in-place families, CAD imports, link status, rooms, views not on
        sheets, sheet completeness, required parameters and unused groups. Each finding has severity,
        element ids and a recommended correction.
        """
        data = compact(checks=checks, rules=rules, sheet_parameters=sheet_parameters,
                       duplicate_tolerance=duplicate_tolerance, min_severity=min_severity, max_findings=max_findings,
                       unit=unit, document=document)
        return await post_structured(revit_post, "/qc/model_checks/", data, ctx, timeout=300.0)

    @mcp.tool(annotations=READ_ONLY)
    async def check_clashes(
        set_a: Annotated[Dict[str, Any], Field(description="Element query, e.g. {categories: ['Ducts'], level: 'Level 2'}")],
        set_b: Annotated[Dict[str, Any], Field(description="Element query; add link_instance_id to test against a Revit link")],
        max_pairs: int = 200,
        max_elements: int = 2000,
        compute_volume: bool = False,
        clearance: Annotated[float, Field(ge=0, description="Soft clash distance in `unit` (0 = hard only)")] = 0.0,
        group_by: Optional[List[Literal["pair", "type_pair", "level", "grid_zone"]]] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Hard and clearance clashes between two element sets (also against a link), with level, grid zone
        and nearest grid intersection; export_clash_report writes CSV/HTML.

        Hard clash detection (solid intersection) between two element sets in the model or against a
        loaded Revit link; with clearance > 0 also pairs closer than the clearance (sampled distance).
        Returns clashing pairs with ids, categories, types, type (hard/clearance), distance, level,
        grid_zone and nearest_grid, grouped when group_by is given.
        """
        data = compact(set_a=set_a, set_b=set_b, max_pairs=max_pairs, max_elements=max_elements,
                       compute_volume=compute_volume or None, clearance=clearance or None, group_by=group_by,
                       unit=unit, dry_run=dry_run or None, document=document)
        response = await call_with_progress(revit_post, "/qc/clashes/", data, ctx, 600.0, "Clash check")
        return format_response(response)

    @mcp.tool(annotations=MODIFIES)
    async def model_snapshot(
        action: Literal["create", "list"] = "create",
        name: Optional[str] = None,
        path: Optional[str] = None,
        categories: Optional[List[str]] = None,
        level: Optional[str] = None,
        track_parameters: Annotated[Optional[List[str]], Field(description="Parameters whose values are recorded (default Mark, Comments)")] = None,
        hash_all_parameters: Annotated[bool, Field(description="Detect any parameter change (slower)")] = False,
        link_instance_id: Annotated[Optional[int], Field(description="Snapshot a Revit link (coordinates transformed to the host)")] = None,
        overwrite: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Save a JSON snapshot (ids, types, levels, locations, tracked parameters) for later compare_models.

        Save a JSON snapshot of the model (ids, UniqueIds, types, levels, locations, tracked parameter
        values) to %APPDATA%/RVTSS/snapshots for later change detection with compare_models.
        """
        data = compact(action=action, name=name, path=path, categories=categories, level=level,
                       track_parameters=track_parameters, hash_all_parameters=hash_all_parameters or None,
                       link_instance_id=link_instance_id, overwrite=overwrite or None, document=document)
        response = await call_with_progress(revit_post, "/qc/snapshot/", data, ctx, 600.0, "Snapshot")
        return format_response(response)

    @mcp.tool(annotations=READ_ONLY)
    async def compare_models(
        mode: Literal["snapshots", "match"] = "snapshots",
        baseline: Annotated[Optional[str], Field(description="snapshots: baseline snapshot name")] = None,
        current: Annotated[Optional[str], Field(description="snapshots: second snapshot (default: the live model)")] = None,
        categories: Optional[List[str]] = None,
        move_tolerance: float = 1.0,
        source: Annotated[Optional[Dict[str, Any]], Field(description="match: element query (+link_instance_id), e.g. the design model")] = None,
        target: Annotated[Optional[Dict[str, Any]], Field(description="match: element query (+link_instance_id), e.g. the shop model link")] = None,
        match_on: Annotated[Optional[List[Literal["category", "family", "type", "level"]]], Field(description="match: keys that must be equal")] = None,
        tolerance: Annotated[float, Field(description="match: max distance in mm")] = 50.0,
        max_items: int = 300,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Change detection: snapshot vs live model or another snapshot (added/removed/modified), or match two
        element sets by location (design vs shop model).

        Change detection and model comparison. snapshots: added / removed / modified elements (type,
        level, moved, parameter changes) between a baseline snapshot and the live model or another
        snapshot. match: pair elements of two sets by location (design model vs shop drawing /
        fabrication link) and report unmatched elements and type substitutions.
        """
        data = compact(mode=mode, baseline=baseline, current=current, categories=categories,
                       move_tolerance=move_tolerance, source=source, target=target, match_on=match_on,
                       tolerance=tolerance, max_items=max_items, document=document)
        response = await call_with_progress(revit_post, "/qc/compare/", data, ctx, 600.0, "Model comparison")
        return format_response(response)
