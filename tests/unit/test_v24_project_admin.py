# -*- coding: utf-8 -*-
"""v2.4 batch D: insert files / families, project settings, styles, project standards, worksharing."""
import importlib

import pytest

from .revit_stubs import revit_environment, FakeAPI
from tools.project_admin_tools import register_project_admin_tools

ROUTES = {"/insert/files/", "/insert/family/", "/project/settings/", "/styles/manage/", "/standards/transfer/",
          "/worksharing/"}


@pytest.fixture
def pa(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_READ_ONLY", raising=False)
    monkeypatch.delenv("RVTSS_ALLOW_SYNC", raising=False)
    with revit_environment():
        mod = importlib.import_module("revit_mcp.project_admin")
        from revit_mcp import core

        yield mod, core


class _Ctx(object):
    """Just enough of core.Ctx for the validation paths that run before any Revit call."""

    def __init__(self, data, doc=None):
        self.data, self.doc, self.active_doc, self.uidoc, self.warnings = data, doc, doc, None, []

    def get(self, k, default=None):
        v = self.data.get(k, default)
        return default if v is None else v

    def require(self, k, what=None):
        if self.data.get(k) in (None, "", []):
            raise AssertionError("missing " + k)
        return self.data[k]

    def bool(self, k, default=False):
        return bool(self.data.get(k, default))

    def list(self, k, default=None):
        v = self.data.get(k)
        return [] if v is None else (list(v) if isinstance(v, (list, tuple)) else [v])

    @property
    def dry_run(self):
        return bool(self.data.get("dry_run"))

    @property
    def confirmed(self):
        return bool(self.data.get("confirm"))

    unit = "mm"


# ------------------------------------------------------------------ Revit side
def test_routes_register_on_an_api(pa):
    mod, _core = pa
    api = FakeAPI("revit_mcp")
    mod.register_project_admin_routes(api)
    assert set(r["path"] for r in api.routes) == ROUTES
    assert all(r["methods"] == ["POST"] for r in api.routes)


def test_missing_file_and_wrong_extension_are_clear_errors(pa, tmp_path):
    mod, core = pa
    with pytest.raises(core.RvtssError) as e:
        mod._existing_file(str(tmp_path / "nope.dwg"), set(mod.CAD_EXT), "CAD file")
    assert e.value.status == 404 and "not found" in e.value.message
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(core.RvtssError) as e:
        mod._existing_file(str(txt), set([".rfa"]), "Family file")
    assert ".rfa" in e.value.message
    rfa = tmp_path / "Door.rfa"
    rfa.write_text("x")
    assert mod._existing_file(str(rfa), set([".rfa"])).endswith("Door.rfa")


def test_colour_parsing(pa):
    mod, core = pa
    for bad in ("red", "#12345", [1, 2], [0, 0, 300]):
        with pytest.raises(core.RvtssError):
            mod._color(bad)
    mod._color("#FF8000")
    mod._color([255, 128, 0])


def test_sync_policy_is_off_by_default_and_can_be_allowed(pa, monkeypatch):
    mod, core = pa
    with pytest.raises(core.RvtssError) as e:
        mod._require_sync_policy("Relinquish")
    assert e.value.status == 403 and e.value.extra.get("code") == "POLICY_DENIED"
    from revit_mcp import secure_api

    monkeypatch.setattr(secure_api, "settings", lambda: {"allow_sync": True})
    mod._require_sync_policy("Relinquish")


def test_load_family_validates_before_touching_revit(pa, tmp_path):
    mod, core = pa
    with pytest.raises(core.RvtssError) as e:
        mod.load_family(_Ctx({}))
    assert "paths" in e.value.message
    a, b = tmp_path / "A.rfa", tmp_path / "B.rfa"
    a.write_text("x")
    b.write_text("x")
    with pytest.raises(core.RvtssError) as e:
        mod.load_family(_Ctx({"paths": [str(a), str(b)], "type": "T1"}))
    assert "single path" in e.value.message


def test_cad_link_dry_run_needs_an_existing_cad_file(pa, tmp_path):
    mod, core = pa
    with pytest.raises(core.RvtssError) as e:
        mod.insert_files(_Ctx({"action": "link_cad", "path": str(tmp_path / "x.dwg"), "dry_run": True}))
    assert e.value.status == 404
    with pytest.raises(core.RvtssError) as e:
        mod.insert_files(_Ctx({"action": "explode"}))
    assert "action must be" in e.value.message


def test_standard_kinds_and_unit_tables_are_consistent(pa):
    mod, _core = pa
    assert set(mod._UNIT_IDS) == set(mod._UNIT_SPECS)
    assert {"view_templates", "filters", "materials", "wall_types"} <= set(mod.STANDARD_KINDS)
    assert mod._INFO_KEYS["client_name"] == "ClientName" and mod._INFO_KEYS["number"] == "Number"


# ------------------------------------------------------------------ MCP wrappers
@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_project_admin_tools(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


def test_six_tools_registered(tools):
    assert set(tools) == {"insert_files", "load_family", "project_settings", "manage_styles",
                          "transfer_project_standards", "worksharing"}


async def test_insert_files_payloads(tools, mock_revit_post):
    await tools["insert_files"](action="link_cad", path=r"C:\cad\site.dwg", placement="shared",
                                import_unit="m", current_view_only=True, dry_run=True, ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/insert/files/" and kw["timeout"] == 600.0
    assert data["path"].endswith("site.dwg") and data["placement"] == "shared" and data["import_unit"] == "m"
    assert data["current_view_only"] is True and data["dry_run"] is True and "confirm" not in data
    mock_revit_post.return_value = {"status": "preview", "requires_confirmation": True}
    out = await tools["insert_files"](action="delete", link="site.dwg", ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert data["action"] == "delete" and data["link"] == "site.dwg" and "PREVIEW" in out


async def test_load_family_payload(tools, mock_revit_post):
    await tools["load_family"](paths=[r"C:\lib\Door.rfa"], type="900 x 2100", overwrite=True, ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/insert/family/" and kw["timeout"] == 600.0
    assert data == {"paths": [r"C:\lib\Door.rfa"], "type": "900 x 2100", "overwrite": True}


async def test_project_settings_payloads(tools, mock_revit_post):
    await tools["project_settings"](ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/project/settings/" and data == {"action": "get", "unit": "mm"}
    await tools["project_settings"](action="set_units", units={"length": {"unit": "mm", "rounding": 1}},
                                    dry_run=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["units"]["length"] == {"unit": "mm", "rounding": 1} and data["dry_run"] is True
    await tools["project_settings"](action="set_location", latitude=31.95, longitude=35.93,
                                    true_north_angle=12.5, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["latitude"] == 31.95 and data["true_north_angle"] == 12.5 and "east_west" not in data


async def test_manage_styles_payloads(tools, mock_revit_post):
    await tools["manage_styles"](action="set_object_style", category="Walls", subcategory="Common Edges",
                                 line_weight=3, line_color="#FF0000", line_pattern="Dash", dry_run=True, ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/styles/manage/" and data["line_weight"] == 3 and data["line_color"] == "#FF0000"
    assert data["subcategory"] == "Common Edges" and data["dry_run"] is True
    await tools["manage_styles"](action="create_line_pattern", name="RVTSS dash",
                                 segments=[{"type": "dash", "length": 6}, {"type": "space", "length": 3}], ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["name"] == "RVTSS dash" and len(data["segments"]) == 2


async def test_transfer_standards_payloads(tools, mock_revit_post):
    await tools["transfer_project_standards"](source="Office Template", ctx=None)
    ep, data, kw = _call(mock_revit_post)
    assert ep == "/standards/transfer/" and data["action"] == "list" and kw["timeout"] == 120.0
    await tools["transfer_project_standards"](source="Office Template", action="copy",
                                              kinds=["view_templates", "filters"], names=["A-Plan"],
                                              confirm=True, ctx=None)
    _ep, data, _ = _call(mock_revit_post)
    assert data["kinds"] == ["view_templates", "filters"] and data["names"] == ["A-Plan"]
    assert data["confirm"] is True and data["skip_existing"] is True


async def test_worksharing_payloads(tools, mock_revit_post):
    await tools["worksharing"](element_ids=[11, 12], ctx=None)
    ep, data, _ = _call(mock_revit_post)
    assert ep == "/worksharing/" and data == {"action": "status", "element_ids": [11, 12], "unit": "mm"}
    await tools["worksharing"](action="acquire_coordinates", link="Site.rvt", dry_run=True, ctx=None)
    _ep, data, kw = _call(mock_revit_post)
    assert data["link"] == "Site.rvt" and data["dry_run"] is True and kw["timeout"] == 600.0
