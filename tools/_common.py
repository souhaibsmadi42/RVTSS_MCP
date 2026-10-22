# -*- coding: utf-8 -*-
"""Shared schema pieces and helpers for RVTSS tool modules."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from .utils import format_response

LengthUnit = Literal["mm", "cm", "m", "ft", "in"]
ValueUnit = Literal["mm", "cm", "m", "ft", "in", "mm2", "m2", "ft2", "mm3", "m3", "ft3", "deg", "rad", "internal"]
FilterOp = Literal["eq", "ne", "contains", "not_contains", "startswith", "endswith", "regex",
                   "gt", "ge", "lt", "le", "empty", "not_empty", "in", "exists", "missing"]
Scalar = Union[str, float, int, bool, None]


class ParamFilter(BaseModel):
    """Filter on a parameter value (instance first, then type)."""
    name: str = Field(description="Parameter name, BuiltInParameter name (ALL_MODEL_MARK) or shared GUID")
    op: FilterOp = "eq"
    value: Optional[Union[str, float, int, bool, List[Union[str, float, int]]]] = None
    unit: Optional[ValueUnit] = Field(None, description="Unit for numeric comparisons on dimensional params (default mm)")
    case_sensitive: bool = False


class ParameterUpdate(BaseModel):
    element_id: int
    parameter: str = Field(description="Parameter name, BuiltInParameter name or shared GUID")
    value: Scalar = Field(description="New value. Dimensional numbers need 'unit' (or pass a string like '900 mm')")
    unit: Optional[ValueUnit] = None
    target: Literal["auto", "instance", "type"] = Field(
        "auto", description="auto: instance parameter, falling back to the type parameter")


def dump(value):
    """pydantic model / list of models / dict -> plain JSON data."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [dump(v) for v in value]
    if isinstance(value, dict):
        return {k: dump(v) for k, v in value.items() if v is not None}
    return value


def compact(**kwargs) -> Dict[str, Any]:
    """Build a request payload, dropping None values."""
    return {k: dump(v) for k, v in kwargs.items() if v is not None}


async def post(revit_post, endpoint, data, ctx=None, timeout=None):
    if timeout is not None:
        response = await revit_post(endpoint, data, ctx, timeout=timeout)
    else:
        response = await revit_post(endpoint, data, ctx)
    return format_response(response)


DOC_HELP = ("Target document title or path; default is the active document. Family documents opened "
            "with family_open/family_create are addressed this way.")
