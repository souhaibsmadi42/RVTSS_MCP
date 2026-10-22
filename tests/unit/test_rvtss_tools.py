# -*- coding: utf-8 -*-
"""RVTSS tool wrappers: payloads, endpoints, schemas and the HTTP client."""
import asyncio
import json

import httpx
import pytest

from tools.element_tools import register_element_tools
from tools.family_editor_tools import register_family_editor_tools, FamilyParameterSpec, FormSpec
from tools.parameter_tools import register_parameter_tools
from tools.documentation_tools import register_documentation_tools
from tools.qc_tools import register_qc_tools
from tools.project_tools import register_project_tools
from tools._common import ParamFilter, ParameterUpdate, compact


@pytest.fixture
def tools(mock_mcp, mock_revit_get, mock_revit_post):
    mock_revit_post.return_value = {"status": "success", "count": 1}
    for reg in (register_element_tools, register_family_editor_tools, register_parameter_tools,
                register_documentation_tools, register_qc_tools, register_project_tools):
        reg(mock_mcp, mock_revit_get, mock_revit_post)
    return mock_mcp.tools


def _call(mock_post):
    args, kwargs = mock_post.call_args
    return args[0], args[1], kwargs


class TestPayloads:
    async def test_find_elements_drops_none_and_dumps_filters(self, tools, mock_revit_post):
        await tools["find_elements"](categories=["Doors"], param_filters=[ParamFilter(name="Width", op="gt", value=900)],
                                     ctx=None)
        ep, data, kw = _call(mock_revit_post)
        assert ep == "/find_elements/"
        assert data["categories"] == ["Doors"]
        assert data["param_filters"] == [{"name": "Width", "op": "gt", "value": 900, "case_sensitive": False}]
        assert "level" not in data and "selection" not in data
        assert data["unit"] == "mm" and data["limit"] == 100
        assert kw["timeout"] == 120.0

    async def test_set_parameters_updates(self, tools, mock_revit_post):
        await tools["set_parameters"](updates=[ParameterUpdate(element_id=5, parameter="Width", value=900, unit="mm")],
                                      dry_run=True, ctx=None)
        ep, data, _ = _call(mock_revit_post)
        assert ep == "/set_parameters/"
        assert data["updates"] == [{"element_id": 5, "parameter": "Width", "value": 900, "unit": "mm", "target": "auto"}]
        assert data["dry_run"] is True and "confirm" not in data

    async def test_set_parameters_shorthand_keeps_explicit_null(self, tools, mock_revit_post):
        await tools["set_parameters"](element_ids=[1, 2], parameter="Comments", value=None, ctx=None)
        _, data, _ = _call(mock_revit_post)
        assert data["element_ids"] == [1, 2] and data["value"] is None

    async def test_bulk_update_template(self, tools, mock_revit_post):
        await tools["bulk_update_parameter"](parameter="Mark", template="D{n:02}", selection=True, sort_by="x", ctx=None)
        ep, data, _ = _call(mock_revit_post)
        assert ep == "/bulk_update_parameter/"
        assert data["template"] == "D{n:02}" and data["selection"] is True and "value" not in data

    async def test_delete_defaults_to_preview(self, tools, mock_revit_post):
        await tools["delete_elements"](element_ids=[1], ctx=None)
        _, data, _ = _call(mock_revit_post)
        assert "confirm" not in data

    async def test_family_add_parameters(self, tools, mock_revit_post):
        await tools["family_add_parameters"](
            parameters=[FamilyParameterSpec(name="Width", value=900, unit="mm"),
                        FamilyParameterSpec(name="Fire Rating", type="text", shared=True)],
            document="My Door", ctx=None)
        ep, data, _ = _call(mock_revit_post)
        assert ep == "/family/parameters/" and data["action"] == "add" and data["document"] == "My Door"
        assert data["parameters"][0] == {"name": "Width", "type": "length", "instance": False, "value": 900,
                                         "unit": "mm", "shared": False, "reporting": False, "if_exists": "skip"}
        assert data["parameters"][1]["shared"] is True

    async def test_family_create_form(self, tools, mock_revit_post):
        await tools["family_create_form"](forms=[FormSpec(profile={"rectangle": {"min": [0, 0], "max": [1, 1]}}, end=750,
                                                          material_parameter="Material")], ctx=None)
        ep, data, _ = _call(mock_revit_post)
        assert ep == "/family/forms/"
        f = data["forms"][0]
        assert f["kind"] == "extrusion" and f["end"] == 750 and f["material_parameter"] == "Material"
        assert f["work_plane"] == "level" and f["void"] is False

    async def test_family_save_maps_compact_flag(self, tools, mock_revit_post):
        await tools["family_save"](save_path="C:/f.rfa", compact_file=True, ctx=None)
        _, data, _ = _call(mock_revit_post)
        assert data == {"save_path": "C:/f.rfa", "compact": True, "backup": True}

    async def test_shared_parameters_bind(self, tools, mock_revit_post):
        await tools["shared_parameters"](action="bind", name="Fire Rating", categories=["Doors", "Walls"], ctx=None)
        ep, data, _ = _call(mock_revit_post)
        assert ep == "/parameters/shared/"
        assert data["categories"] == ["Doors", "Walls"] and data["binding"] == "instance" and data["group"] == "data"

    async def test_import_parameters_dry_run_default(self, tools, mock_revit_post):
        await tools["import_parameters"](csv_text="ElementId,Mark\n1,A\n", ctx=None)
        _, data, _ = _call(mock_revit_post)
        assert data["dry_run"] is True

    async def test_batch_rename_dry_run_default(self, tools, mock_revit_post):
        await tools["batch_rename"](target="views", find="Level", replace="L", ctx=None)
        ep, data, _ = _call(mock_revit_post)
        assert ep == "/batch_rename/" and data["dry_run"] is True

    async def test_qc_and_session(self, tools, mock_revit_post):
        await tools["run_model_checks"](checks=["warnings", "links"], ctx=None)
        assert _call(mock_revit_post)[0] == "/qc/model_checks/"
        await tools["get_session_info"](ctx=None)
        assert _call(mock_revit_post)[0] == "/session_info/"

    async def test_result_is_formatted_text(self, tools, mock_revit_post):
        mock_revit_post.return_value = {"status": "preview", "message": "Preview only", "deleted_total": 3}
        out = await tools["delete_elements"](element_ids=[1], ctx=None)
        assert out.startswith("=== PREVIEW ===") and '"deleted_total": 3' in out


def test_compact_helper():
    assert compact(a=None, b=0, c=False, d=[ParamFilter(name="x")]) == {
        "b": 0, "c": False, "d": [{"name": "x", "op": "eq", "case_sensitive": False}]}


def test_param_filter_schema_is_strict():
    with pytest.raises(Exception):
        ParamFilter(name="Width", op="bigger")


# ----------------------------------------------------------------- server
def _schemas():
    import main

    async def go():
        return await main.mcp.list_tools()
    return {t.name: t for t in asyncio.run(go())}


def test_server_registers_all_tools_with_unique_names():
    tools = _schemas()
    assert len(tools) >= 74
    for name in ("get_revit_status", "place_family", "execute_revit_code", "find_elements", "family_create",
                 "family_build_parametric_box", "shared_parameters", "run_model_checks", "compare_models"):
        assert name in tools


def test_tool_schemas_have_descriptions_and_enums():
    tools = _schemas()
    for name, t in tools.items():
        assert t.description and len(t.description) > 20, name
    t = tools["family_manage_types"]
    schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema")  # mcp 1.x / 2.x
    assert "export_catalog" in json.dumps(schema)
    assert "ctx" not in schema.get("properties", {})


def test_read_only_annotations():
    tools = _schemas()
    ann = tools["find_elements"].annotations
    hint = getattr(ann, "readOnlyHint", None)
    if hint is None:
        hint = getattr(ann, "read_only_hint", None)
    assert hint is True
    dann = tools["delete_elements"].annotations
    dhint = getattr(dann, "destructiveHint", None)
    if dhint is None:
        dhint = getattr(dann, "destructive_hint", None)
    assert dhint is True


# ------------------------------------------------------------- http client
class TestRevitClient:
    def _patch(self, monkeypatch, handler):
        import main

        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)
        monkeypatch.setattr(main.httpx, "AsyncClient", factory)
        return main

    async def test_structured_error_is_preserved(self, monkeypatch):
        main = self._patch(monkeypatch, lambda req: httpx.Response(
            404, json={"status": "error", "error": "View not found: X", "did_you_mean": ["Level 1"]}))
        res = await main.revit_post("/find_views/", {})
        assert isinstance(res, dict)
        assert res["did_you_mean"] == ["Level 1"] and res["response_code"] == 404

    async def test_legacy_error_without_status_gets_error_status(self, monkeypatch):
        main = self._patch(monkeypatch, lambda req: httpx.Response(500, json={"error": "boom"}))
        res = await main.revit_get("/model_info/")
        assert res["status"] == "error" and res["error"] == "boom"

    async def test_non_json_error_stays_text(self, monkeypatch):
        main = self._patch(monkeypatch, lambda req: httpx.Response(502, text="Bad gateway"))
        res = await main.revit_get("/status/")
        assert res.startswith("Error: 502 - Bad gateway (request_id: ")

    async def test_connect_error_has_recovery_hint(self, monkeypatch):
        def boom(req):
            raise httpx.ConnectError("refused", request=req)
        main = self._patch(monkeypatch, boom)
        res = await main.revit_get("/status/")
        assert res.startswith("Error: Cannot reach the pyRevit Routes server") and "Routes Server" in res

    async def test_success_and_url(self, monkeypatch):
        seen = {}

        def ok(req):
            seen["url"] = str(req.url)
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"status": "success"})
        main = self._patch(monkeypatch, ok)
        assert (await main.revit_post("/find_elements/", {"a": 1}))["status"] == "success"
        assert seen["url"].endswith(":48884/revit_mcp/find_elements/")
        assert seen["body"].pop("_rvtss_request_id") and seen["body"] == {"a": 1}

    async def test_status_503_still_means_revit_is_up_for_launcher(self, monkeypatch):
        from tools.launch_tools import _wait_for_revit_ready

        main = self._patch(monkeypatch, lambda req: httpx.Response(
            503, json={"status": "unhealthy", "error": "No active Revit document"}))
        ready, _ = await _wait_for_revit_ready(main.revit_get, None, timeout=5, poll_interval=0)
        assert ready
