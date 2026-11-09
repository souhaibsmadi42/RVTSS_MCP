# -*- coding: utf-8 -*-
"""Revit-side modules import, register their routes, and match the MCP tools.

Runs against stub pyRevit/Revit modules (see revit_stubs.py).
"""
import inspect
import os
import re
import importlib

import pytest

from .revit_stubs import revit_environment, FakeRequest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALLOWED_ARGS = {"doc", "uidoc", "request"}


@pytest.fixture(scope="module")
def registered():
    with revit_environment():
        startup = importlib.import_module("startup")
        import revit_mcp

        yield startup.api, dict(revit_mcp.REGISTRATION_ERRORS), revit_mcp


def test_all_route_modules_register_without_errors(registered):
    api, errors, _ = registered
    assert errors == {}
    assert len(api.routes) >= 60


def test_route_paths_are_unique(registered):
    api, _, _ = registered
    keys = [(r["path"], tuple(r["methods"])) for r in api.routes]
    assert len(keys) == len(set(keys))


def test_route_handlers_use_only_pyrevit_injected_arguments(registered):
    """pyRevit Routes decides API context from argument names; anything else must be a URL param."""
    api, _, _ = registered
    for r in api.routes:
        url_params = set(re.findall(r"<(?:\w+:)?(\w+)>", r["path"]))
        args = set(inspect.signature(r["func"]).parameters)
        assert args <= ALLOWED_ARGS | url_params, (r["path"], args)


def test_modifying_rvtss_routes_run_in_api_context(registered):
    """Every RVTSS route must receive `doc` (forces Revit API context)."""
    api, _, _ = registered
    legacy = {"/status/", "/ping/", "/rvtss_files/"}  # deliberately outside API context (no Revit API use)
    for r in api.routes:
        if r["path"] in legacy:
            continue
        assert "doc" in inspect.signature(r["func"]).parameters or "uidoc" in inspect.signature(r["func"]).parameters, r["path"]


def _tool_endpoints():
    endpoints = set()
    rx = re.compile(r"""(?:revit_post|revit_get|revit_image|post|post_structured|post_confirmable|call_with_progress)"""
                    r"""\(\s*(?:revit_post,\s*)?f?["'](/[^"'{]+)""")
    tools_dir = os.path.join(ROOT, "tools")
    for fname in os.listdir(tools_dir):
        if fname.endswith(".py"):
            with open(os.path.join(tools_dir, fname), encoding="utf-8") as fh:
                endpoints.update(rx.findall(fh.read()))
    return endpoints


def test_every_tool_endpoint_has_a_route(registered):
    api, _, _ = registered
    paths = [r["path"] for r in api.routes]
    endpoints = _tool_endpoints()
    assert len(endpoints) >= 55
    for ep in endpoints:
        assert any(p == ep or p.startswith(ep) and "<" in p for p in paths), "No route for " + ep


def test_handle_maps_rvtss_error_to_structured_response(registered):
    _, _, revit_mcp = registered
    from revit_mcp import core

    def impl(ctx):
        raise core.RvtssError("Bad input", status=422, hint="Fix it", extra_field=1)

    res = core.handle(object(), FakeRequest({}), impl, needs_doc=False)
    assert res["status"] == 422
    assert res["data"]["status"] == "error"
    assert res["data"]["error"] == "Bad input"
    assert res["data"]["hint"] == "Fix it"
    assert res["data"]["extra_field"] == 1


def test_handle_unexpected_exception_returns_500_with_traceback(registered):
    from revit_mcp import core

    def impl(ctx):
        raise ValueError("boom")

    res = core.handle(object(), FakeRequest({}), impl, needs_doc=False)
    assert res["status"] == 500
    assert "ValueError: boom" in res["data"]["error"]
    assert "traceback" in res["data"]


def test_handle_requires_document(registered):
    from revit_mcp import core

    res = core.handle(None, FakeRequest({}), lambda ctx: {"x": 1})
    assert res["status"] == 503
    assert "No active Revit document" in res["data"]["error"]


def test_handle_success_adds_status_and_warnings(registered):
    from revit_mcp import core

    def impl(ctx):
        ctx.warn("careful")
        return {"value": ctx.int("n", 0, 0, 10)}

    res = core.handle(None, FakeRequest('{"n": 50}'), impl, needs_doc=False)
    assert res["status"] == 200
    assert res["data"] == {"status": "success", "value": 10, "warnings": ["careful"]}


def test_handle_rejects_invalid_json(registered):
    from revit_mcp import core

    res = core.handle(None, FakeRequest("{not json"), lambda ctx: {}, needs_doc=False)
    assert res["status"] == 400
    assert "Invalid JSON" in res["data"]["error"]


def test_confirm_gate_forces_preview_over_threshold(registered):
    from revit_mcp import core

    ctx = core.Ctx(None, None, {}, needs_doc=False)
    assert core.confirm_gate(ctx, core.CONFIRM_THRESHOLD + 1, "op") is True
    assert ctx.warnings
    ctx = core.Ctx(None, None, {"confirm": True}, needs_doc=False)
    assert core.confirm_gate(ctx, core.CONFIRM_THRESHOLD + 1, "op") is False
    # an explicit dry run is not a forced preview: it must report status "dry_run" (live self-test)
    ctx = core.Ctx(None, None, {"dry_run": True, "confirm": True}, needs_doc=False)
    assert core.confirm_gate(ctx, 1, "op") is False
    ctx = core.Ctx(None, None, {"dry_run": True}, needs_doc=False)
    assert core.confirm_gate(ctx, core.CONFIRM_THRESHOLD + 1, "op") is False
    out = core.preview_status({"status": "dry_run"}, True)
    assert out["status"] == "preview" and out["requires_confirmation"]


def test_clean_makes_payload_json_safe(registered):
    import json
    from revit_mcp import core

    payload = core._clean({"a": float("nan"), "b": [1, 2.5, "x"], "c": {"d": None}, 5: True})
    json.dumps(payload)
    assert payload["a"] is None and payload["5"] is True
