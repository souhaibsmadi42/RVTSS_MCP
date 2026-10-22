# -*- coding: utf-8 -*-
"""RVTSS project / shared / global parameter management tools."""
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ._compat import Context, READ_ONLY, MODIFIES
from ._common import LengthUnit, ValueUnit, ParamFilter, Scalar, compact, post, DOC_HELP
from .family_editor_tools import ParamType, ParamGroup

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


class SharedDefinitionSpec(BaseModel):
    name: str
    type: ParamType = "text"
    group: str = Field("RVTSS", description="Group inside the shared parameter file")
    guid: Optional[str] = Field(None, description="Use an established GUID (e.g. from your company standard)")
    description: Optional[str] = None
    visible: bool = True
    user_modifiable: bool = True
    hide_when_no_value: Optional[bool] = None


class AuditRule(ParamFilter):
    severity: Literal["info", "warning", "error", "critical"] = "warning"


def register_parameter_tools(mcp, revit_get, revit_post):
    """Register parameter management tools"""

    @mcp.tool(annotations=READ_ONLY)
    async def list_project_parameters(
        contains: Optional[str] = None,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Project parameters with binding (instance/type), categories, data type, group, shared GUID,
        plus names defined more than once."""
        return await post(revit_post, "/parameters/project/", compact(contains=contains, document=document), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def shared_parameters(
        action: Literal["read_file", "create_definitions", "create_file", "bind"],
        shared_parameter_file: Annotated[Optional[str], Field(description="Default: the file configured in Revit")] = None,
        definitions: Annotated[Optional[List[SharedDefinitionSpec]], Field(description="create_definitions")] = None,
        create_file: bool = False,
        set_as_current: Annotated[bool, Field(description="create_file: make it Revit's shared parameter file")] = False,
        name: Annotated[Optional[str], Field(description="bind: shared parameter name")] = None,
        guid: Annotated[Optional[str], Field(description="bind: pick by GUID")] = None,
        categories: Annotated[Optional[List[str]], Field(description="bind: e.g. ['Doors','Walls']")] = None,
        binding: Literal["instance", "type"] = "instance",
        group: Annotated[Optional[ParamGroup], Field(description="bind: properties palette group")] = "data",
        vary_between_groups: Optional[bool] = None,
        contains: Optional[str] = None,
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Shared parameters: read_file, create_definitions (GUIDs preserved), create_file, bind to categories
        (instance/type).

        Shared parameters: read_file (GUIDs, duplicates, project use), create_definitions (existing
        names/GUIDs reused, never rewritten), create_file, bind to categories as instance/type (extends
        existing bindings). E.g. create_definitions [{name:'Fire Rating'}] then bind
        categories=['Doors','Walls'].

        Existing names are reused and their GUIDs never changed; supplied GUIDs are honoured. Existing
        bindings are extended with ReInsert, never replaced; a different parameter with the same name is
        refused.
        """
        data = compact(action=action, shared_parameter_file=shared_parameter_file, definitions=definitions,
                       create_file=create_file or None, set_as_current=set_as_current or None, name=name, guid=guid,
                       categories=categories, binding=binding, group=group, vary_between_groups=vary_between_groups,
                       contains=contains, dry_run=dry_run or None, document=document)
        return await post(revit_post, "/parameters/shared/", data, ctx, timeout=120.0)

    @mcp.tool(annotations=MODIFIES)
    async def global_parameters(
        action: Literal["list", "create", "set_value", "set_formula", "associate", "dissociate"] = "list",
        name: Optional[str] = None,
        type: ParamType = "length",
        value: Scalar = None,
        value_unit: Optional[ValueUnit] = None,
        formula: Optional[str] = None,
        element_ids: Annotated[Optional[List[int]], Field(description="associate/dissociate targets")] = None,
        parameter: Annotated[Optional[str], Field(description="associate: element parameter to drive")] = None,
        unit: LengthUnit = "mm",
        dry_run: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Global parameters: list (value, formula, affected elements), create, set value/formula and
        associate element parameters with them."""
        data = compact(action=action, name=name, type=type, value=value, value_unit=value_unit, formula=formula,
                       element_ids=element_ids, parameter=parameter, unit=unit, dry_run=dry_run or None,
                       document=document)
        return await post(revit_post, "/parameters/global/", data, ctx)

    @mcp.tool(annotations=READ_ONLY)
    async def audit_parameters(
        categories: Optional[List[str]] = None,
        element_ids: Optional[List[int]] = None,
        view: Optional[str] = None,
        level: Optional[str] = None,
        required: Annotated[Optional[List[str]], Field(description="Parameters that must exist and be filled")] = None,
        rules: Annotated[Optional[List[AuditRule]], Field(description="Value rules, e.g. {name:'Fire Rating', op:'regex', value:'^(30|60|90|120)$'}")] = None,
        expected_types: Annotated[Optional[Dict[str, ParamType]], Field(description="{param: type} data type check")] = None,
        naming_pattern: Annotated[Optional[str], Field(description="Regex all project parameter names must match")] = None,
        include_type_parameters: bool = True,
        check_empty: bool = True,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Audit parameters on elements: missing, empty, invalid values, wrong types, duplicate or misnamed
        definitions.

        Audit parameters on a set of elements: missing, empty, invalid values, wrong data types, and
        duplicate / badly named project parameter definitions. Returns findings with element ids.
        """
        data = compact(categories=categories, element_ids=element_ids, view=view, level=level, required=required,
                       rules=rules, expected_types=expected_types, naming_pattern=naming_pattern,
                       include_type_parameters=include_type_parameters, check_empty=check_empty, document=document)
        return await post(revit_post, "/parameters/audit/", data, ctx, timeout=180.0)

    @mcp.tool(annotations=READ_ONLY)
    async def export_parameters(
        parameters: List[str],
        categories: Optional[List[str]] = None,
        element_ids: Optional[List[int]] = None,
        view: Optional[str] = None,
        level: Optional[str] = None,
        param_filters: Optional[List[ParamFilter]] = None,
        path: Annotated[Optional[str], Field(description="Write a .csv file on the Revit machine (else returned inline)")] = None,
        overwrite: bool = False,
        value_mode: Literal["display", "raw"] = "display",
        unit: LengthUnit = "mm",
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Export element parameter values to CSV (ElementId, UniqueId, Category, Family, Type + columns)."""
        data = compact(parameters=parameters, categories=categories, element_ids=element_ids, view=view, level=level,
                       param_filters=param_filters, path=path, overwrite=overwrite or None, value_mode=value_mode,
                       unit=unit, document=document)
        return await post(revit_post, "/parameters/export/", data, ctx, timeout=180.0)

    @mcp.tool(annotations=MODIFIES)
    async def import_parameters(
        path: Optional[str] = None,
        csv_text: Optional[str] = None,
        units: Annotated[Optional[Dict[str, ValueUnit]], Field(description="{column: unit} for numeric dimensional columns")] = None,
        ignore_columns: Optional[List[str]] = None,
        skip_empty: bool = True,
        allow_type: bool = False,
        atomic: bool = False,
        dry_run: bool = True,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Import parameter values from CSV (ElementId or UniqueId column + parameter columns). dry_run by
        default.

        Import parameter values from CSV (needs an ElementId or UniqueId column; other columns are
        parameter names). Defaults to dry_run=true - review the changes, then run with dry_run=false.
        """
        data = compact(path=path, csv_text=csv_text, units=units, ignore_columns=ignore_columns, skip_empty=skip_empty,
                       allow_type=allow_type or None, atomic=atomic, dry_run=dry_run or None,
                       confirm=confirm or None, document=document)
        return await post(revit_post, "/parameters/import/", data, ctx, timeout=300.0)

    @mcp.tool(annotations=MODIFIES)
    async def map_parameters(
        mappings: Annotated[List[Dict[str, str]], Field(description="[{from: 'Old Param', to: 'Standard Param'}]")],
        categories: Optional[List[str]] = None,
        element_ids: Optional[List[int]] = None,
        view: Optional[str] = None,
        level: Optional[str] = None,
        only_empty_target: bool = False,
        allow_type: bool = False,
        atomic: bool = False,
        dry_run: bool = True,
        confirm: bool = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Copy values from existing parameters into your BIM-standard parameters (converting between
        storage types through display values). Source values are never deleted."""
        data = compact(mappings=mappings, categories=categories, element_ids=element_ids, view=view, level=level,
                       only_empty_target=only_empty_target or None, allow_type=allow_type or None, atomic=atomic,
                       dry_run=dry_run or None, confirm=confirm or None, document=document)
        return await post(revit_post, "/parameters/map/", data, ctx, timeout=300.0)
