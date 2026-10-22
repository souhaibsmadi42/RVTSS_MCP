# -*- coding: utf-8 -*-
"""Tests for the live self-test plan/runner (revit_mcp/pure/selftest.py) and its in-Revit transport."""
import importlib
import json
import os
import re
import sys


from revit_mcp.pure import selftest
from .revit_stubs import revit_environment

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_CHANGING = ("/set_parameters/", "/bulk_update_parameter/", "/transform_elements/", "/create_elements/",
                  "/delete_elements/", "/place_family/", "/color_splash/", "/clear_colors/",
                  "/family/load_into_project/", "/element_types/", "/views/create/", "/views/graphics/",
                  "/batch_rename/", "/parameters/global/")


def _plan_endpoints():
    src = open(os.path.join(ROOT, "revit_mcp", "pure", "selftest.py"), encoding="utf-8").read()
    return set(re.findall(r't\.(?:get|post)\("(/[^"]+)"', src))


def test_route_matching():
    routes = [{"path": "/get_view/<view_name>", "methods": ["GET"], "func": "a"},
              {"path": "/sisters/<int:version>", "methods": ["GET"], "func": "b"},
              {"path": "/find_elements/", "methods": ["POST"], "func": "c"}]
    r, p = selftest.match_route(routes, "GET", "/get_view/Level%201?x=1")
    assert r["func"] == "a" and p == {"view_name": "Level%201"}
    r, p = selftest.match_route(routes, "GET", "/sisters/2027")
    assert r["func"] == "b" and p == {"version": 2027}
    assert selftest.match_route(routes, "GET", "/find_elements/") == (None, None)
    assert selftest.match_route(routes, "POST", "/find_elements/")[0]["func"] == "c"


def test_every_plan_endpoint_is_a_registered_route():
    with revit_environment():
        startup = importlib.import_module("startup")
        routes = startup.api.routes
    for ep in _plan_endpoints():
        if ep == "/get_view/":  # built as "/get_view/" + quote(view name)
            ep = "/get_view/Level%201"
        method_ok = any(selftest.match_route(routes, m, ep)[0] for m in ("GET", "POST"))
        assert method_ok, "self-test calls unknown route " + ep


def test_model_changes_never_run_without_test_model(tmp_path):
    calls = []

    def transport(method, path, payload):
        calls.append(path)
        if path == "/status/":
            return 200, {"status": "active", "health": "healthy"}
        if path == "/session_info/":
            return 200, {"status": "success", "active_document": "Client Project.rvt"}
        if path == "/open_document/":
            return 500, {"status": "error", "error": "cannot open"}
        return 200, {"status": "success"}

    report = selftest.run(transport, str(tmp_path), prepare_model=lambda t: "C:/tmp/copy.rvt")
    touched = [c for c in calls if c in MODEL_CHANGING]
    assert touched == [], touched
    open_step = [s for s in report["steps"] if s["name"] == "open test model copy"][0]
    assert open_step["status"] == "fail"
    skipped = [s for s in report["steps"] if s["status"] == "skip"]
    assert any("test model not open" in s.get("reason", "") for s in skipped)


def test_wrong_active_document_blocks_model_changes(tmp_path):
    calls = []

    def transport(method, path, payload):
        calls.append(path)
        if path == "/status/":
            return 200, {"status": "active", "health": "healthy"}
        if path == "/session_info/":
            return 200, {"status": "success", "active_document": "Client Project.rvt"}
        return 200, {"status": "success"}

    selftest.run(transport, str(tmp_path), prepare_model=lambda t: "C:/tmp/RVTSS_selftest_1.rvt")
    assert not [c for c in calls if c in MODEL_CHANGING]


def test_report_when_revit_is_down(tmp_path):
    report = selftest.run(lambda m, p, d: (598, {"status": "error", "error": "cannot connect", "hint": "start Revit"}),
                          str(tmp_path), prepare_model=None)
    assert report["summary"]["fail"] >= 1 and report["summary"]["pass"] == 0
    md = selftest.to_markdown(report)
    assert "## Failures" in md and "start Revit" in md
    data = json.loads(selftest.to_json(report))
    assert data["tools"]["get_revit_status"] == "fail"
    assert set(data["summary"]) == {"pass", "fail", "skip"}


def test_groups_filter_keeps_status(tmp_path):
    seen = []
    selftest.run(lambda m, p, d: (seen.append(p), (598, {"status": "error", "error": "x"}))[1], str(tmp_path),
                 groups=["qc"])
    assert "/status/" in seen and "/qc/model_checks/" in seen and "/find_elements/" not in seen


def test_tool_summary_precedence():
    res = [{"tools": ["a", "b"], "status": "pass"}, {"tools": ["b"], "status": "fail"}, {"tools": ["c"], "status": "skip"}]
    assert selftest.tool_summary(res) == {"a": "pass", "b": "fail", "c": "skip"}


def test_in_process_transport_calls_handlers(monkeypatch):
    """selftest_runtime registers the routes on a recorder and calls them with injected arguments."""
    with revit_environment():
        routes_mod = sys.modules["pyrevit.routes"]

        class Resp(object):
            def __init__(self, data=None, status=200, headers=None):
                self.data, self.status = data, status

        monkeypatch.setattr(routes_mod, "make_response", lambda data=None, status=200, headers=None: Resp(data, status))
        runtime = importlib.import_module("revit_mcp.selftest_runtime")

        class UIApp(object):
            ActiveUIDocument = None

        transport, errors = runtime.make_transport(UIApp())
        assert errors == {}
        status, data = transport("POST", "/find_elements/", {"categories": ["Walls"]})
        assert status == 503 and "No active Revit document" in data["error"]
        status, data = transport("GET", "/nope/", None)
        assert status == 404
