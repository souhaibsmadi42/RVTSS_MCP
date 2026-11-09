# -*- coding: utf-8 -*-
"""v2.4 MEP editing: route registration, argument checks on the Revit side, MCP wrapper payloads."""
import importlib

import pytest

from .revit_stubs import revit_environment, FakeAPI
from tools.mep_edit_tools import register_mep_edit_tools

ROUTES = {"/mep/connect/", "/mep/create/", "/mep/insulation/", "/mep/systems/manage/"}


@pytest.fixture
def rv(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_READ_ONLY", raising=False)
    with revit_environment():
        mep_edit = importlib.import_module("revit_mcp.mep_edit")
        from revit_mcp import core

        yield mep_edit, core


def test_routes_register_on_an_api(rv):
    mep_edit, _core = rv
    api = FakeAPI("revit_mcp")
    mep_edit.register_mep_edit_routes(api)
    assert set(r["path"] for r in api.routes) == ROUTES
    assert all(r["methods"] == ["POST"] for r in api.routes)


class _Doc(object):
    IsFamilyDocument = False
    Title = "a"


def _ctx(core, data):
    return core.Ctx(_Doc(), None, data, needs_doc=False)


@pytest.mark.parametrize("impl, data, text", [
    ("connect", {"action": "weld", "element_ids": [1, 2]}, "action must be"),
    ("connect", {"action": "tee", "element_ids": [1, 2]}, "exactly 3"),
    ("connect", {"action": "cap"}, "element_ids"),
    ("connect", {"action": "disconnect", "element_ids": [1, 2, 3]}, "disconnect needs"),
    ("create_parts", {"action": "bend"}, "action must be"),
    ("insulation", {"action": "list"}, "element_ids"),
    ("manage_systems", {"action": "resize"}, "action must be"),
    ("manage_systems", {"action": "create", "domain": "electrical"}, "mechanical or piping"),
])
def test_bad_requests_are_refused_before_revit_is_touched(rv, impl, data, text):
    mep_edit, core = rv
    with pytest.raises(core.RvtssError) as e:
        getattr(mep_edit, impl)(_ctx(core, data))
    assert text in e.value.message


def test_fitting_table_matches_the_tool_actions(rv):
    mep_edit, _core = rv
    assert mep_edit.FITTINGS == {"elbow": 2, "transition": 2, "union": 2, "tee": 3, "cross": 4}


# ------------------------------------------------------------------ MCP wrappers
@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_mep_edit_tools(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


def test_four_tools_are_registered(tools):
    assert set(tools) == {"mep_connect", "create_mep_parts", "mep_insulation", "manage_mep_systems"}


async def test_connect_payloads(tools, mock_revit_post):
    await tools["mep_connect"](action="elbow", element_ids=[1, 2], dry_run=True, ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/mep/connect/" and kw["timeout"] == 120.0
    assert data == {"action": "elbow", "element_ids": [1, 2], "unit": "mm", "dry_run": True}
    await tools["mep_connect"](action="connect", element_ids=[1, 2], tolerance=5, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["tolerance"] == 5 and "dry_run" not in data


async def test_create_parts_payloads(tools, mock_revit_post):
    await tools["create_mep_parts"](action="flex_pipe", points=[[0, 0], [1000, 0], [1000, 1000]], level="L1",
                                    offset=2700, diameter=25, ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/mep/create/" and data["points"][2] == [1000, 1000] and data["offset"] == 2700
    assert "host_id" not in data and "dry_run" not in data
    await tools["create_mep_parts"](action="insert_on_curve", host_id=7, point=[500, 0, 2700], family="Valve",
                                    type="Standard", dry_run=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["host_id"] == 7 and data["family"] == "Valve" and data["dry_run"] is True


async def test_insulation_payloads(tools, mock_revit_post):
    await tools["mep_insulation"](element_ids=[4], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/mep/insulation/"
    assert data == {"element_ids": [4], "action": "list", "kind": "insulation", "unit": "mm"}
    await tools["mep_insulation"](element_ids=[4, 5], action="add", kind="lining", thickness=25, replace=True,
                                  confirm=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["kind"] == "lining" and data["thickness"] == 25 and data["replace"] is True and data["confirm"] is True


async def test_systems_payloads(tools, mock_revit_post):
    await tools["manage_mep_systems"](action="list_circuits", ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/mep/systems/manage/" and data == {"action": "list_circuits", "limit": 200}
    assert kw["timeout"] == 180.0
    await tools["manage_mep_systems"](action="create", domain="mechanical", element_ids=[1, 2], name="SA 1",
                                      system_type="Supply Air", dry_run=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["domain"] == "mechanical" and data["name"] == "SA 1" and "limit" not in data
    await tools["manage_mep_systems"](action="create_circuit", element_ids=[9], circuit_type="power", panel_id=3,
                                      ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["circuit_type"] == "power" and data["panel_id"] == 3
