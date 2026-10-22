# -*- coding: utf-8 -*-
"""Output models for structured tools (structuredContent / outputSchema on mcp 2.x).

Deliberately loose (extra fields allowed): they document the stable top-level
keys without rejecting additional data Revit returns.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str


class FindElementsOut(_Out):
    count: Optional[int] = None
    pagination: Optional[Dict[str, Any]] = None
    category_counts: Optional[Dict[str, int]] = None
    elements: Optional[List[Dict[str, Any]]] = None


class ElementDetailsOut(_Out):
    unit: Optional[str] = None
    elements: Optional[List[Dict[str, Any]]] = None


class ProjectOverviewOut(_Out):
    document: Optional[Dict[str, Any]] = None
    levels: Optional[List[Dict[str, Any]]] = None
    grids: Optional[List[Dict[str, Any]]] = None


class FindingsOut(_Out):
    summary: Optional[Dict[str, Any]] = None
    findings: Optional[List[Dict[str, Any]]] = None


class ScheduleOut(_Out):
    columns: Optional[List[str]] = None
    row_count: Optional[int] = None
    rows: Optional[List[List[Any]]] = None
