# -*- coding: utf-8 -*-
"""v2.4: ribbon command launcher, view extents / templates / viewports, new view, schedule and detailing kinds,
text find-and-replace."""
import importlib

import pytest

from .revit_stubs import revit_environment
from tools.view_setup_tools import register_view_setup_tools
from tools.annotation_tools import register_annotation_tools
from tools.documentation_tools import register_documentation_tools


@pytest.fixture
def rv(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_READ_ONLY", raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        import revit_mcp
        from revit_mcp import core

        yield startup.api, revit_mcp, core


def test_v24_view_routes_registered(rv):
    api, revit_mcp, _core = rv
    paths = set(r["path"] for r in api.routes)
    assert revit_mcp.REGISTRATION_ERRORS == {}
    assert {"/commands/list/", "/commands/run/", "/views/extents/", "/views/templates/", "/sheets/viewports/",
            "/annotation/text/replace/"} <= paths


# ------------------------------------------------------------------ launcher (pure parts)
def test_command_labels_and_search(rv):
    from revit_mcp import commands as C

    assert C.split_words("StructuralFoundationWall") == "Structural Foundation Wall"
    assert C.split_words("MEPSettings") == "MEP Settings"
    names = ["ScopeBox", "CurtainGrid", "Wall", "StructuralFoundationWall", "Undo"]
    found, total = C.match_commands(names, "wall")
    assert found == ["StructuralFoundationWall", "Wall"] and total == 2
    assert C.match_commands(names, "foundation structural")[0] == ["StructuralFoundationWall"]
    assert C.match_commands(names, "scope box")[0] == ["ScopeBox"]
    assert C.match_commands(names, None, limit=2)[1] == 5


@pytest.mark.parametrize("name", ["Undo", "Redo", "Save", "SaveAsProject", "SynchronizeNow",
                                  "SynchronizeAndModifySettings", "ReloadLatest", "RelinquishAllMine",
                                  "ExitRevit", "CloseInactiveViews"])
def test_guarded_commands_are_blocked(rv, name):
    from revit_mcp import commands as C

    assert C.blocked_reason(name) is not None


@pytest.mark.parametrize("name", ["ScopeBox", "DesignOptions", "Phases", "Render", "Wall", "SaveAsLibraryFamily_x"])
def test_ordinary_commands_are_not_blocked(rv, name):
    from revit_mcp import commands as C

    # "SaveAsLibraryFamily_x" starts with SaveAs and must be blocked; everything else passes
    assert (C.blocked_reason(name) is None) == (not name.startswith("Save"))


def test_run_command_needs_a_name(rv):
    _api, _rm, core = rv
    from revit_mcp import commands as C

    with pytest.raises(core.RvtssError) as e:
        C.run_command(core.Ctx(None, None, {}, needs_doc=False))
    assert "name" in e.value.message


# ------------------------------------------------------------------ text replace (pure part)
def test_replace_in_text(rv):
    from revit_mcp.annotation import replace_in_text as R

    assert R("See detail A and DETAIL b", "detail", "DTL") == ("See DTL A and DTL b", 2)
    assert R("See detail A and DETAIL b", "detail", "DTL", match_case=True) == ("See DTL A and DETAIL b", 1)
    assert R("cat concat", "cat", "dog", whole_word=True) == ("dog concat", 1)
    assert R("L01 L02", r"L(\d+)", r"Level \1", regex=True) == ("Level 01 Level 02", 2)
    # a plain replacement is literal: backslashes and group references are not interpreted
    assert R("a.b", ".", r"\1") == (r"a\1b", 1)
    with pytest.raises(ValueError):
        R("x", "", "y")


def test_detail_kinds_cover_v24(rv):
    from revit_mcp import annotation as A

    assert {"dimension", "detail_line", "filled_region", "masking_region", "revision_cloud", "spot_elevation",
            "spot_coordinate", "detail_component"} == set(A.DETAIL_KINDS)


def test_schedule_kinds(rv):
    from revit_mcp import documentation as D

    assert D.SCHEDULE_KINDS == ("category", "key", "material_takeoff", "sheet_list", "view_list", "note_block")


# ------------------------------------------------------------------ MCP wrappers
@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_view_setup_tools(mock_mcp, mock_revit_get, mock_revit_post)
    register_annotation_tools(mock_mcp, mock_revit_get, mock_revit_post)
    register_documentation_tools(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


async def test_launcher_payloads(tools, mock_revit_post):
    await tools["list_revit_commands"](contains="scope box", ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/commands/list/" and data == {"contains": "scope box", "limit": 200}
    await tools["run_revit_command"](name="ScopeBox", dry_run=True, ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/commands/run/" and data == {"name": "ScopeBox", "dry_run": True}


async def test_view_extents_payloads(tools, mock_revit_post):
    await tools["view_extents"](ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/views/extents/" and data == {"action": "get", "view": "active", "unit": "mm"}
    await tools["view_extents"](action="set_section_box", view="{3D}", element_ids=[5, 6], margin=250, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["element_ids"] == [5, 6] and data["margin"] == 250 and "enabled" not in data
    await tools["view_extents"](action="set_view_range", view="Level 1", cut=1200, bottom=0, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["cut"] == 1200 and data["bottom"] == 0 and "top" not in data and "margin" not in data
    await tools["view_extents"](action="set_crop", crop_active=False, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["crop_active"] is False


async def test_template_and_viewport_payloads(tools, mock_revit_post):
    await tools["manage_view_templates"](action="apply", template="Plans", views=["Level 1", "Level 2"], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/views/templates/" and data == {"action": "apply", "template": "Plans",
                                                 "views": ["Level 1", "Level 2"]}
    await tools["manage_view_templates"](action="delete", template="Old", confirm=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["confirm"] is True
    await tools["manage_viewports"](action="move", viewport_id=9, location=[200, 150], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/sheets/viewports/" and data["viewport_id"] == 9 and data["location"] == [200, 150]


async def test_replace_text_is_a_dry_run_by_default(tools, mock_revit_post):
    await tools["replace_text"](find="TBC", replace="Confirmed", ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/annotation/text/replace/" and data["dry_run"] is True and data["find"] == "TBC"
    await tools["replace_text"](find="TBC", replace="", dry_run=False, views=["active"], ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert "dry_run" not in data and data["replace"] == "" and data["views"] == ["active"]


async def test_callout_and_schedule_kinds(tools, mock_revit_post):
    await tools["create_view"](kind="callout", source_view="Level 1", min=[0, 0], max=[3000, 2000], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/views/create/" and data["kind"] == "callout" and data["max"] == [3000, 2000]
    await tools["create_schedule"](kind="sheet_list", fields=["Sheet Number", "Sheet Name"], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/schedules/create/" and data["kind"] == "sheet_list" and "category" not in data
    await tools["create_schedule"](category="Doors", fields=["Mark"], ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert "kind" not in data and data["category"] == "Doors"
