# -*- coding: utf-8 -*-
"""v2.4 batch B: modify_elements (align, offset, trim/extend, split, scale, flip, cut, paint, parts) and
the new create_elements kinds (curtain walls, sweeps, model lines, reference planes, structure)."""
import importlib
import inspect

import pytest

from .revit_stubs import revit_environment, FakeAPI, FakeRequest
from tools.modify_tools import register_modify_tools
from tools.element_tools import register_element_tools

NEW_KINDS = {"curtain_grid_line", "mullions", "curtain_panel_type", "wall_sweep", "reveal", "model_line",
             "reference_plane", "foundation_isolated", "foundation_wall", "brace", "truss", "beam_system"}


@pytest.fixture
def rv(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_READ_ONLY", raising=False)
    with revit_environment():
        core = importlib.import_module("revit_mcp.core")
        modify = importlib.import_module("revit_mcp.modify")
        elements = importlib.import_module("revit_mcp.elements")
        yield core, modify, elements


class FakeDoc(object):
    Title = "Test"
    PathName = ""
    IsFamilyDocument = False
    IsReadOnly = False
    IsLinked = False
    IsModifiable = False

    def GetElement(self, _id):
        return None


# ------------------------------------------------------------------ Revit side
def test_modify_route_registers(rv):
    _core, modify, _el = rv
    api = FakeAPI("revit_mcp")
    modify.register_modify_routes(api)
    assert [(r["path"], r["methods"]) for r in api.routes] == [("/modify/elements/", ["POST"])]
    # pyRevit decides the execution context from the handler's argument names
    assert inspect.getfullargspec(api.routes[0]["func"]).args == ["doc", "request"]


def test_modify_operations_are_all_dispatched(rv):
    _core, modify, _el = rv
    src = inspect.getsource(modify.modify_elements)
    for op in modify.OPERATIONS:
        assert '"%s"' % op in src or op == "divide_parts", op
    assert len(modify.OPERATIONS) == 12


@pytest.mark.parametrize("data,needle", [
    ({}, "Missing required field 'operation'"),
    ({"operation": "explode", "element_ids": [1]}, "operation must be one of"),
    ({"operation": "align"}, "element_ids is required"),
    ({"operation": "align", "element_ids": [7]}, "ids not found"),
])
def test_modify_validation(rv, data, needle):
    core, modify, _el = rv
    res = core.handle(FakeDoc(), FakeRequest(data), modify.modify_elements)
    assert res["data"]["status"] == "error" and needle in res["data"]["error"], res["data"]


def test_intersection_of_two_plan_lines(rv):
    _core, modify, _el = rv

    class P(object):
        def __init__(self, x, y):
            self.X, self.Y, self.Z = x, y, 0.0

    class L(object):
        def __init__(self, x, y, dx, dy):
            self._p, self.Direction = P(x, y), P(dx, dy)

        def GetEndPoint(self, _i):
            return self._p

    assert modify._intersect_2d(L(0, 0, 1, 0), L(5, -3, 0, 1)) == (5.0, 0.0)
    assert modify._intersect_2d(L(0, 0, 1, 0), L(0, 2, 1, 0)) is None   # parallel


def test_new_kinds_are_registered_without_touching_the_v23_set(rv):
    _core, _modify, elements = rv
    assert set(elements._MODELLING_KINDS) == NEW_KINDS
    assert not NEW_KINDS & set(elements._STRUCTURE_KINDS)
    src = inspect.getsource(elements._create_one)
    for kind in NEW_KINDS:
        assert kind in src, kind   # named in the "Unknown kind" message


def test_unknown_kind_message_lists_the_new_kinds(rv):
    core, _modify, elements = rv
    ctx = core.Ctx(FakeDoc(), None, {})
    with pytest.raises(core.RvtssError) as e:
        elements._create_one(ctx, {"kind": "ramp"})
    assert "beam_system" in e.value.message and "curtain_grid_line" in e.value.message


# ------------------------------------------------------------------ MCP wrappers
@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_modify_tools(mock_mcp, mock_revit_get, mock_revit_post)
    register_element_tools(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


async def test_align_payload_is_minimal(tools, mock_revit_post):
    await tools["modify_elements"](operation="align", element_ids=[1, 2], axis="y", reference_id=9, dry_run=True,
                                   ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/modify/elements/" and kw["timeout"] == 180.0
    assert data == {"operation": "align", "element_ids": [1, 2], "axis": "y", "reference_id": 9, "unit": "mm",
                    "dry_run": True}


async def test_operation_specific_defaults_are_not_sent_to_other_operations(tools, mock_revit_post):
    await tools["modify_elements"](operation="offset", element_ids=[3], distance=500, keep_original=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data == {"operation": "offset", "element_ids": [3], "distance": 500, "copy": True, "unit": "mm"}
    await tools["modify_elements"](operation="trim_extend", element_ids=[1, 2], ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["mode"] == "corner" and "axis" not in data and "faces" not in data and "flip" not in data
    await tools["modify_elements"](operation="flip", element_ids=[4], flip="facing", ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["flip"] == "facing" and "mode" not in data


async def test_split_scale_paint_parts_payloads(tools, mock_revit_post):
    await tools["modify_elements"](operation="split", element_ids=[5], point=[2000, 0], ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["point"] == [2000, 0] and "parameter" not in data
    await tools["modify_elements"](operation="scale", element_ids=[5, 6], factor=2, center=[0, 0], unit="m",
                                   ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["factor"] == 2 and data["center"] == [0, 0] and data["unit"] == "m"
    await tools["modify_elements"](operation="paint", element_ids=[7], material="Concrete", faces="exterior",
                                   ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["material"] == "Concrete" and data["faces"] == "exterior"
    await tools["modify_elements"](operation="divide_parts", element_ids=[8], divider_ids=[11],
                                   lines=[[[0, 0], [5000, 0]]], level="Level 1", confirm=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["divider_ids"] == [11] and data["lines"] == [[[0, 0], [5000, 0]]] and data["level"] == "Level 1"
    assert data["confirm"] is True and "dry_run" not in data


async def test_modify_preview_is_returned_when_the_client_cannot_confirm(tools, mock_revit_post):
    mock_revit_post.return_value = {"status": "preview", "requires_confirmation": True, "count": 150}
    out = await tools["modify_elements"](operation="flip", element_ids=list(range(150)), ctx=None)
    assert "PREVIEW" in out and '"count": 150' in out and mock_revit_post.call_count == 1


def test_modify_tool_description_is_short_and_names_the_limits(tools):
    doc = inspect.getdoc(tools["modify_elements"])
    assert len(doc.split("\n\n", 1)[0]) < 140
    for word in ("transform_elements", "attach wall tops", "dry_run"):
        assert word in doc


async def test_create_elements_passes_v24_kinds_and_documents_them(tools, mock_revit_post):
    items = [{"kind": "curtain_grid_line", "wall_id": 5, "direction": "vertical", "offset_along": 1500},
             {"kind": "beam_system", "boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "level": "Level 2"}]
    await tools["create_elements"](items=items, dry_run=True, ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/create_elements/" and data["items"] == items and data["dry_run"] is True
    doc = inspect.getdoc(tools["create_elements"])
    for word in ("mullions", "reference planes", "trusses", "ramps"):
        assert word in doc
    desc = inspect.signature(tools["create_elements"]).parameters["items"].annotation.__metadata__[0].description
    for kind in NEW_KINDS:
        assert kind in desc, kind
