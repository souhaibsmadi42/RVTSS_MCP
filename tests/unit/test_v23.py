# -*- coding: utf-8 -*-
"""v2.3: save / sync off by default, detailing routes, new create_elements kinds, tool wrappers."""
import importlib
import inspect

import pytest

from .revit_stubs import revit_environment, FakeRequest
from .test_v22_revit import FakeDoc
from tools.annotation_tools import register_annotation_tools
from tools.element_tools import register_element_tools


@pytest.fixture
def rv(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # no user config.json
    for k in ("RVTSS_READ_ONLY", "RVTSS_ALLOW_SAVE", "RVTSS_ALLOW_SYNC"):
        monkeypatch.delenv(k, raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        import revit_mcp
        from revit_mcp import core

        yield startup.api, revit_mcp, core


# ---------------------------------------------------------------- save / sync policy
def test_save_and_sync_refused_by_default(rv):
    _api, _rm, core = rv
    for kind, action in (("save", "save_document"), ("sync", "sync_with_central")):
        res = core.file_policy_response(kind, action)
        assert res["status"] == 403 and res["data"]["code"] == "POLICY_DENIED", res
        assert ("allow_" + kind) in res["data"]["hint"]


def test_save_and_sync_allowed_by_env_or_config(rv, monkeypatch, tmp_path):
    _api, _rm, core = rv
    monkeypatch.setenv("RVTSS_ALLOW_SAVE", "1")
    assert core.file_policy_response("save", "save_document") is None
    assert core.file_policy_response("sync", "sync_with_central")["status"] == 403
    (tmp_path / "RVTSS").mkdir(exist_ok=True)
    (tmp_path / "RVTSS" / "config.json").write_text('{"allow_sync": true}')
    assert core.file_policy_response("sync", "sync_with_central") is None


def test_security_status_reports_policy(rv):
    from revit_mcp.secure_api import security_status

    st = security_status()
    assert st["allow_save"] is False and st["allow_sync"] is False


def test_save_route_checks_the_policy(rv):
    src = inspect.getsource(importlib.import_module("revit_mcp.document"))
    assert src.count("file_policy_response(\"save\"") == 3 and src.count("file_policy_response(\"sync\"") == 1


# ---------------------------------------------------------------- detailing routes
def test_detailing_routes_registered(rv):
    api, revit_mcp, _core = rv
    paths = set(r["path"] for r in api.routes)
    assert revit_mcp.REGISTRATION_ERRORS == {}
    assert {"/annotation/detail/", "/annotation/types/"} <= paths


@pytest.mark.parametrize("data,needle", [
    ({}, "'items' is required"),
    ({"items": [{"kind": "x"}] * 501}, "At most 500"),
])
def test_detailing_validation(rv, data, needle):
    _api, _rm, core = rv
    from revit_mcp import annotation

    class Doc(FakeDoc):
        IsFamilyDocument = False

    res = core.handle(Doc(), FakeRequest(dict(data, view="1")), annotation.detailing)
    assert res["data"]["status"] == "error" and needle in res["data"]["error"], res["data"]


def test_create_elements_knows_new_kinds(rv):
    from revit_mcp import elements

    assert set(elements._STRUCTURE_KINDS) == {"roof", "ceiling", "column", "beam", "foundation", "wall_foundation"}


# ---------------------------------------------------------------- MCP wrappers
@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_annotation_tools(mock_mcp, mock_revit_get, mock_revit_post)
    register_element_tools(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


async def test_create_detailing_payload(tools, mock_revit_post):
    items = [{"kind": "detail_line", "start": [0, 0], "end": [1000, 0]},
             {"kind": "dimension", "element_ids": [1, 2], "start": [0, 500], "end": [6000, 500]}]
    await tools["create_detailing"](items=items, view="Level 1", ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/annotation/detail/" and data["items"] == items and data["view"] == "Level 1"
    assert data["atomic"] is True and data["unit"] == "mm" and "dry_run" not in data
    assert kw["timeout"] == 180.0


async def test_list_annotation_types_payload(tools, mock_revit_post):
    await tools["list_annotation_types"](kinds=["line_style"], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/annotation/types/" and data == {"kinds": ["line_style"]}


async def test_create_elements_passes_new_kinds(tools, mock_revit_post):
    items = [{"kind": "roof", "boundary": [[0, 0], [5000, 0], [5000, 4000]], "level": "Level 2", "slope_deg": 30}]
    await tools["create_elements"](items=items, ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/create_elements/" and data["items"] == items


def test_create_elements_docs_mention_new_kinds(tools):
    doc = inspect.getdoc(tools["create_elements"])
    for word in ("roofs", "ceilings", "columns", "beams", "foundations"):
        assert word in doc
