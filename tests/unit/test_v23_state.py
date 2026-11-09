# -*- coding: utf-8 -*-
"""v2.3 (second batch): capture, stairs, phases, links, selection sets, undo ledger, fixes from the live run."""
import base64
import importlib

import pytest

from .revit_stubs import revit_environment
from tools.state_tools import register_state_tools


@pytest.fixture
def rv(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_READ_ONLY", raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        import revit_mcp
        from revit_mcp import core

        yield startup.api, revit_mcp, core


def test_v23_routes_registered(rv):
    api, revit_mcp, _core = rv
    paths = set(r["path"] for r in api.routes)
    assert revit_mcp.REGISTRATION_ERRORS == {}
    assert {"/views/capture/", "/stairs/create/", "/phases/manage/", "/links/manage/", "/selection_sets/",
            "/undo/"} <= paths


def test_confirm_gate_dry_run_is_not_a_forced_preview(rv):
    _api, _rm, core = rv
    ctx = core.Ctx(None, None, {"dry_run": True}, needs_doc=False)
    assert core.confirm_gate(ctx, 1, "op") is False


# ------------------------------------------------------------------ undo ledger
class _Ids(object):
    def __init__(self, n):
        self.Count = n


class _Args(object):
    def __init__(self, doc, op, names, added=0):
        self._doc, self.Operation, self._names, self._added = doc, op, names, added

    def GetDocument(self):
        return self._doc

    def GetTransactionNames(self):
        return self._names

    def GetAddedElementIds(self):
        return _Ids(self._added)

    def GetModifiedElementIds(self):
        return _Ids(0)

    def GetDeletedElementIds(self):
        return _Ids(0)


class _Doc(object):
    PathName = "C:/m/a.rvt"
    Title = "a"


def _ledger(rv):
    from revit_mcp import undo

    undo._LEDGER.clear()
    undo._REDO.clear()
    return undo, undo._LEDGER.setdefault(undo._key(_Doc()), [])


def test_undo_ledger_marks_rvtss_steps_and_merges_one_request(rv):
    _api, _rm, core = rv
    undo, stack = _ledger(rv)
    d = _Doc()
    undo._on_changed(None, _Args(d, "TransactionCommitted", ["Wall"], 1))  # the user's own change
    core.ACTIVE_REQUEST.update(method="create_stairs", seq=41)
    undo._on_changed(None, _Args(d, "TransactionCommitted", ["RVTSS: stairs runs"], 3))
    undo._on_changed(None, _Args(d, "TransactionCommitted", ["RVTSS: stairs railings"], 1))
    core.ACTIVE_REQUEST.update(method=None)
    stack = undo._LEDGER[undo._key(d)]
    assert len(stack) == 2 and stack[0]["rvtss"] is False
    assert stack[1]["rvtss"] and stack[1]["tool"] == "create_stairs" and len(stack[1]["names"]) == 2
    # the user's Ctrl+Z, then Ctrl+Y
    undo._on_changed(None, _Args(d, "TransactionUndone", ["RVTSS: stairs runs"]))
    assert len(undo._LEDGER[undo._key(d)]) == 1
    undo._on_changed(None, _Args(d, "TransactionRedone", ["RVTSS: stairs runs"]))
    assert undo._LEDGER[undo._key(d)][-1]["tool"] == "create_stairs"


def test_undo_ledger_drops_rolled_back_dry_runs(rv):
    _api, _rm, core = rv
    undo, _stack = _ledger(rv)
    d = _Doc()
    core.ACTIVE_REQUEST.update(method="create_elements", seq=7)
    undo._on_changed(None, _Args(d, "TransactionCommitted", ["RVTSS: Create elements"], 4))
    undo._on_changed(None, _Args(d, "TransactionGroupRolledBack", ["RVTSS: Create elements (dry run)"]))
    core.ACTIVE_REQUEST.update(method=None)
    assert undo._LEDGER[undo._key(d)] == []


def test_undo_refuses_when_the_user_changed_the_model_last(rv):
    _api, _rm, core = rv
    undo, _stack = _ledger(rv)
    d = _Doc()
    undo._STATE["installed"] = True
    undo._on_changed(None, _Args(d, "TransactionCommitted", ["Move"], 0))

    class Ctx(object):
        doc = d
        uidoc = None
        dry_run = False

        def get(self, k, default=None):
            return {"action": "undo"}.get(k, default)

    with pytest.raises(core.RvtssError) as e:
        undo.undo(Ctx())
    assert "not made by RVTSS" in e.value.message


# ------------------------------------------------------------------ MCP wrappers
@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_state_tools(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


async def test_capture_returns_an_image(tools, mock_revit_post):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    mock_revit_post.return_value = {"status": "success", "image_data": base64.b64encode(png).decode(),
                                    "content_type": "image/png"}
    img = await tools["capture_elements"](element_ids=[1, 2], orientation="top", ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/views/capture/" and data["element_ids"] == [1, 2] and data["orientation"] == "top"
    assert getattr(img, "data", None) == png and kw["timeout"] == 180.0


async def test_capture_error_is_text(tools, mock_revit_post):
    mock_revit_post.return_value = {"status": "error", "error": "None of the elements has a 3D bounding box"}
    out = await tools["capture_elements"](element_ids=[5], ctx=None)
    assert isinstance(out, str) and "bounding box" in out


async def test_stairs_phases_links_sets_undo_payloads(tools, mock_revit_post):
    await tools["create_stairs"](base_level="L1", top_level="L2", runs=[{"start": [0, 0], "end": [4000, 0]}],
                                 dry_run=True, ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/stairs/create/" and data["dry_run"] is True and data["runs"][0]["end"] == [4000, 0]
    await tools["manage_phases"](action="set_element_phase", element_ids=[3], created="New Construction", ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/phases/manage/" and data["created"] == "New Construction"
    await tools["manage_links"](action="reload", link="Structure", ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/links/manage/" and data["link"] == "Structure" and kw["timeout"] == 600.0
    await tools["selection_sets"](action="save", name="Fire doors", element_ids=[1, 2], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/selection_sets/" and data["name"] == "Fire doors"
    await tools["undo_last_change"](action="undo", expect_tool="create_stairs", ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/undo/" and data == {"action": "undo", "expect_tool": "create_stairs"}


# ------------------------------------------------------------------ fixes from the live run
def test_title_block_templates_match_on_windows_paths():
    from revit_mcp.pure import templates as T

    files = [r"C:\ProgramData\Autodesk\RVT 2026\Family Templates\English\Titleblocks\A1 metric.rft",
             r"C:\ProgramData\Autodesk\RVT 2026\Family Templates\English\Metric Generic Model.rft"]
    assert T.match(files, "title_block") == files[:1]
    assert T._parts(r"C:\a\b.rft") == ["C:", "a", "b.rft"] and T._parts("a/b.rft") == ["a", "b.rft"]
