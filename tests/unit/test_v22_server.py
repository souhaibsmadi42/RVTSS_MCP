# -*- coding: utf-8 -*-
"""v2.2 server-side features: read-only mode, argument guard, response guard, health, batch_execute."""
import asyncio
import json

import pytest

from tools import guards as G
from tools import toolsets as TS
from tools._compat import create_server


# ------------------------------------------------------------------ helpers
def _server(post=None, get=None, read_only=False, toolsets=None, health_probe=None):
    from tools import register_tools

    calls = []

    async def fake_post(endpoint, data, ctx=None, **kw):
        calls.append((endpoint, data))
        if post is not None:
            return post(endpoint, data)
        return {"status": "success", "echo": endpoint}

    async def fake_get(endpoint, ctx=None, **kw):
        calls.append((endpoint, None))
        if get is not None:
            return get(endpoint)
        return {"status": "active", "health": "healthy", "rvtss_version": "2.2.0"}

    srv = create_server("test")
    proxy = register_tools(srv, fake_get, fake_post, fake_get, toolsets=toolsets or set(TS.TOOLSETS),
                           health_probe=health_probe, read_only=read_only)
    return srv, proxy, calls


def _text(result):
    """Text of a call_tool result on either SDK major."""
    content = getattr(result, "content", None)
    if content is None and isinstance(result, (list, tuple)):
        content = result[0] if result and isinstance(result[0], (list, tuple)) else result
    return "\n".join(getattr(c, "text", "") for c in content or [])


def _call(srv, name, args):
    return asyncio.run(srv.call_tool(name, args))


# --------------------------------------------------------------- read-only mode
def test_read_only_flag_parsing(monkeypatch):
    monkeypatch.delenv("RVTSS_READ_ONLY", raising=False)
    assert G.read_only_enabled() is False
    assert G.read_only_enabled("1") is True
    assert G.read_only_enabled("no") is False


def test_read_only_mode_registers_only_read_only_tools():
    _srv, proxy, _ = _server(read_only=True)
    assert "find_elements" in proxy.registered and "get_coordinates" in proxy.registered
    for name in ("set_parameters", "delete_elements", "execute_revit_code", "batch_execute", "export_documents",
                 "purge_unused", "family_save"):
        assert name in proxy.skipped_read_only and name not in proxy.registered
    assert all(TS.TOOL_READ_ONLY[n] for n in proxy.registered)


def test_normal_mode_keeps_everything():
    _srv, proxy, _ = _server()
    assert proxy.skipped_read_only == [] and len(proxy.registered) >= 99


# ------------------------------------------------------------------ arguments
def test_unknown_arguments_suggest_names():
    schema = {"properties": {"element_ids": {}, "dry_run": {}, "confirm": {}}}
    unknown = G.unknown_arguments({"elementIds": [1], "dryrun": True, "confirm": True, "zzz": 1}, schema)
    assert ("elementIds", ["element_ids"]) in unknown and ("dryrun", ["dry_run"]) in unknown
    assert ("zzz", []) in unknown and len(unknown) == 3
    msg = G.argument_error("delete_elements", unknown, schema)
    assert msg.startswith("INVALID_ARGUMENT") and "did you mean 'dry_run'" in msg and "Nothing was sent" in msg


def test_argument_guard_refuses_misspelled_dry_run_before_revit():
    srv, _proxy, calls = _server()
    with pytest.raises(Exception, match="INVALID_ARGUMENT.*did you mean 'dry_run'"):
        _call(srv, "set_parameters", {"element_ids": [1], "parameter": "Mark", "value": "A", "dryrun": True})
    assert calls == []
    _call(srv, "set_parameters", {"element_ids": [1], "parameter": "Mark", "value": "A", "dry_run": True})
    assert calls and calls[-1][0] == "/set_parameters/" and calls[-1][1]["dry_run"] is True


# ------------------------------------------------------------------ responses
def test_response_guard_passes_small_and_flags_large(monkeypatch):
    monkeypatch.setenv("RVTSS_RESPONSE_WARN_KB", "1")
    monkeypatch.setenv("RVTSS_RESPONSE_BUDGET_KB", "8")
    assert G.guard_text("small") == "small"
    medium = "x" * 3000
    assert "large response" in G.guard_text(medium)
    big = {"status": "success", "committed": True, "count": 5000, "elements": [{"id": i} for i in range(5000)]}
    out = json.loads(G.guard_text(json.dumps(big), big))
    assert out["status"] == "success" and out["committed"] is True and out["count"] == 5000
    assert out["elements"]["omitted_list_items"] == 5000
    assert out["response_guard"]["code"] == "RESPONSE_TOO_LARGE"


def test_response_guard_truncates_plain_text(monkeypatch):
    monkeypatch.setenv("RVTSS_RESPONSE_BUDGET_KB", "4")
    text = "line\n" * 5000
    out = G.guard_text(text, {"status": "success", "output": text})
    assert "RESPONSE_TOO_LARGE" in out and len(out) < len(text)


def test_format_response_applies_guard(monkeypatch):
    from tools.utils import format_response

    monkeypatch.setenv("RVTSS_RESPONSE_BUDGET_KB", "4")
    resp = {"status": "success", "rows": [["a" * 50] for _ in range(500)]}
    assert "RESPONSE_TOO_LARGE" in format_response(resp)


def test_guard_payload_summarises_structured_content(monkeypatch):
    monkeypatch.setenv("RVTSS_RESPONSE_BUDGET_KB", "4")
    small = {"status": "success", "x": 1}
    assert G.guard_payload(small) is small
    big = {"status": "success", "rows": ["y" * 100] * 200}
    assert G.guard_payload(big)["response_guard"]["code"] == "RESPONSE_TOO_LARGE"


# --------------------------------------------------------------------- health
def test_health_reports_next_step_when_routes_down():
    async def probe():
        return {"config": {"read_only": False, "revit_port": 48884}, "ping": {"alive": False, "error": "refused"}}

    srv, _p, calls = _server(health_probe=probe)
    out = json.loads(_text(_call(srv, "rvtss_health", {})))
    assert out["status"] == "warning" and "pyRevit Routes does not answer" in out["next_step"]
    assert calls == []  # /status/ is not tried when /ping/ failed


def test_health_ok_and_version_mismatch():
    from revit_mcp import RVTSS_VERSION

    async def probe():
        return {"config": {}, "ping": {"alive": True}}

    srv, _p, _c = _server(health_probe=probe, get=lambda ep: {"status": "active", "health": "healthy",
                                                              "rvtss_version": RVTSS_VERSION})
    out = json.loads(_text(_call(srv, "rvtss_health", {})))
    assert out["status"] == "success" and out["next_step"] is None
    srv, _p, _c = _server(health_probe=probe, get=lambda ep: {"status": "active", "health": "healthy",
                                                              "rvtss_version": "1.0.0"})
    out = json.loads(_text(_call(srv, "rvtss_health", {})))
    assert "Version mismatch" in out["next_step"]


# ---------------------------------------------------------------------- batch
def test_batch_builds_payloads_with_the_real_tools_and_sends_one_request():
    srv, _p, calls = _server()
    _call(srv, "batch_execute", {"commands": [
        {"tool": "set_parameters", "arguments": {"element_ids": [1, 2], "parameter": "Mark", "value": "D1",
                                                 "dry_run": True}},
        {"tool": "transform_elements", "arguments": {"element_ids": [1], "operation": "move", "vector": [100, 0, 0]}},
    ], "name": "Doors"})
    assert [c[0] for c in calls] == ["/batch/"]
    sent = calls[0][1]
    assert sent["name"] == "Doors" and len(sent["commands"]) == 2
    first = sent["commands"][0]
    assert first["endpoint"] == "/set_parameters/" and first["tool"] == "set_parameters"
    assert first["payload"]["parameter"] == "Mark" and "dry_run" not in first["payload"]
    assert sent["commands"][1]["endpoint"] == "/transform_elements/"


def test_batch_rejects_unbatchable_and_invalid_commands_without_sending():
    srv, _p, calls = _server()
    out = json.loads(_text(_call(srv, "batch_execute", {"commands": [
        {"tool": "execute_revit_code", "arguments": {"code": "print(1)"}},
        {"tool": "set_parameters", "arguments": {"element_ids": [1], "parameter": "Mark", "value": "x",
                                                 "confrim": True}},
    ]})))
    assert out["status"] == "error" and calls == []
    errs = {e["index"]: e for e in out["invalid_commands"]}
    assert errs[0]["error"] == "not batchable"
    assert "did you mean 'confirm'" in errs[1]["error"]


def test_batch_document_is_propagated_to_commands():
    srv, _p, calls = _server()
    _call(srv, "batch_execute", {"document": "Tower", "commands": [
        {"tool": "create_view", "arguments": {"kind": "drafting", "name": "Notes"}}]})
    assert calls[0][1]["document"] == "Tower"
    assert calls[0][1]["commands"][0]["payload"]["document"] == "Tower"


def test_batchable_tools_exist_and_are_editing_tools():
    _srv, proxy, _ = _server()
    from tools.batch_tools import BATCHABLE

    for name in BATCHABLE:
        assert name in proxy.registered, name
        assert TS.TOOL_READ_ONLY[name] is False, name


# ------------------------------------------------------------- tool payloads
@pytest.mark.parametrize("tool,args,endpoint,expect", [
    ("list_rooms", {"kind": "space", "status": ["unplaced"]}, "/rooms/list/", {"kind": "space", "status": ["unplaced"]}),
    ("get_room_details", {"element_ids": [5], "include": ["finishes"]}, "/rooms/details/", {"include": ["finishes"]}),
    ("material_takeoff", {"scope": {"categories": ["Walls"]}, "group_by": ["material", "level"]},
     "/materials/takeoff/", {"filter": {"categories": ["Walls"]}, "group_by": ["material", "level"]}),
    ("manage_materials", {"action": "create", "name": "Brick", "properties": {"color": "#AA0000"}},
     "/materials/manage/", {"action": "create", "properties": {"color": "#AA0000"}}),
    ("find_untagged_elements", {"categories": ["Doors"]}, "/annotation/untagged/", {"view": "active"}),
    ("tag_elements", {"categories": ["Doors"], "offset": [0, 300]}, "/annotation/tag/",
     {"categories": ["Doors"], "skip_tagged": True, "offset": [0, 300]}),
    ("create_text_notes", {"notes": [{"text": "Hi", "point": [0, 0]}]}, "/annotation/text/",
     {"notes": [{"text": "Hi", "point": [0, 0]}]}),
    ("export_documents", {"format": "pdf", "sheets": ["A101"], "dry_run": True}, "/export/run/",
     {"format": "pdf", "sheets": ["A101"], "dry_run": True}),
    ("list_export_settings", {}, "/export/settings/", {}),
    ("list_mep_systems", {"domain": "piping"}, "/mep/systems/", {"domain": "piping"}),
    ("get_mep_connectors", {"element_ids": [1]}, "/mep/connectors/", {"element_ids": [1]}),
    ("find_mep_disconnects", {}, "/mep/disconnects/", {"unit": "mm"}),
    ("manage_worksets", {"action": "create", "name": "MEP"}, "/worksets/manage/", {"action": "create"}),
    ("purge_unused", {"categories": ["Materials"]}, "/purge/", {"categories": ["Materials"], "passes": 1}),
    ("survey_change_impact", {"element_ids": [1], "change_kind": "type"}, "/impact/survey/", {"change_kind": "type"}),
    ("get_coordinates", {"points": [[0, 0, 0]]}, "/coordinates/", {"points": [[0, 0, 0]]}),
    ("spatial_query", {"mode": "raycast", "point": [0, 0, 3000]}, "/spatial/query/", {"mode": "raycast"}),
    ("manage_view_filters", {"action": "create", "name": "F", "categories": ["Doors"],
                             "rules": [{"parameter": "Mark", "op": "contains", "value": "D"}]},
     "/views/filters/", {"rules": [{"parameter": "Mark", "op": "contains", "value": "D"}], "logic": "and"}),
    ("manage_revisions", {"action": "assign", "revision": "3", "sheets": ["A101"]}, "/sheets/revisions/",
     {"action": "assign", "sheets": ["A101"]}),
])
def test_new_tool_payloads(tool, args, endpoint, expect):
    srv, _p, calls = _server()
    _call(srv, tool, args)
    assert calls and calls[-1][0] == endpoint
    for k, v in expect.items():
        assert calls[-1][1].get(k) == v, (k, calls[-1][1])


def test_v22_prompts_render_and_point_at_safe_tools():
    import inspect

    from tools.resources_prompts import PROMPTS

    for name in ("getting_started", "safe_change", "room_documentation", "issue_sheets", "mep_connectivity_review"):
        fn = PROMPTS[name]["fn"]
        required = dict((k, "X") for k, p in inspect.signature(fn).parameters.items() if p.default is inspect._empty)
        assert len(fn(**required)) > 200, name
    text = PROMPTS["safe_change"]["fn"](change="retype doors")
    assert "survey_change_impact" in text and "batch_execute" in text and "dry_run=true" in text
    assert "unknown" in text  # never invent a reason
    assert 'set_b={categories: ["Structural Framing"' in PROMPTS["mep_connectivity_review"]["fn"]()
