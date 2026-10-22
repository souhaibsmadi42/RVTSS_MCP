# -*- coding: utf-8 -*-
"""Phase 4: structured output, resources, prompts, progress heartbeats and elicitation."""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tools._compat import MCP_MAJOR, STRUCTURED_OUTPUT
from tools import _common

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Revit(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        self.calls.append((self.path, body))
        p = self.path
        if p.endswith("/find_elements/"):
            self._send(200, {"status": "success", "count": 2, "elements": [{"id": 1}, {"id": 2}]})
        elif p.endswith("/session_info/"):
            self._send(200, {"status": "success", "active_document": "Tower.rvt"})
        elif p.endswith("/delete_elements/"):
            if body.get("confirm"):
                self._send(200, {"status": "success", "committed": True, "deleted_total": 3})
            else:
                self._send(200, {"status": "preview", "requires_confirmation": True, "deleted_total": 3,
                                 "dependent_elements_deleted": 2, "message": "Preview: 3 elements."})
        elif p.endswith("/rvtss_files/"):
            self._send(200, {"status": "success", "kind": body.get("kind"), "content": {"naming": {}}})
        else:
            self._send(200, {"status": "success"})


@pytest.fixture
def revit():
    _Revit.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _Revit)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], _Revit.calls
    srv.shutdown()


def _params(port):
    from mcp.client.stdio import StdioServerParameters

    env = dict(os.environ, REVIT_PORT=str(port), REVIT_HOST="127.0.0.1", PYTHONPATH=ROOT)
    env.pop("RVTSS_TOOLSETS", None)
    return StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "main.py")], env=env, cwd=ROOT)


def _text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


async def test_structured_resources_prompts(revit):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    port, calls = revit
    async with stdio_client(_params(port)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("find_elements", {"categories": ["Walls"]})
            assert '"count": 2' in _text(res)
            structured = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
            if STRUCTURED_OUTPUT:
                assert structured["count"] == 2 and structured["status"] == "success"
            tools = {t.name: t for t in (await s.list_tools()).tools}
            out_schema = getattr(tools["find_elements"], "output_schema", None) or getattr(tools["find_elements"], "outputSchema", None)
            assert (out_schema is not None) == STRUCTURED_OUTPUT

            resources = [str(x.uri) for x in (await s.list_resources()).resources]
            assert "rvtss://session" in resources and "rvtss://qc_rules" in resources
            sess = await s.read_resource("rvtss://session")
            assert "Tower.rvt" in sess.contents[0].text
            doc = await s.read_resource("rvtss://docs/tools/delete_elements")
            assert "preview" in doc.contents[0].text.lower()
            rules = await s.read_resource("rvtss://qc_rules")
            assert json.loads(rules.contents[0].text)["kind"] == "qc_rules"

            prompts = [p.name for p in (await s.list_prompts()).prompts]
            assert {"model_health_check", "create_parametric_family", "shared_parameter_rollout", "naming_audit",
                    "pre_issue_qc"} <= set(prompts)
            pr = await s.get_prompt("create_parametric_family", {"description": "a side table"})
            text = pr.messages[0].content.text
            assert "family_flex_test" in text and "a side table" in text


@pytest.mark.skipif(MCP_MAJOR < 2, reason="elicitation needs mcp 2.x")
async def test_delete_preview_confirmed_through_elicitation(revit):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    import mcp.types as types

    port, calls = revit
    asked = []

    async def on_elicit(context, params):
        asked.append(params.message)
        return types.ElicitResult(action="accept", content={"confirm": True})

    async with stdio_client(_params(port)) as (r, w):
        async with ClientSession(r, w, elicitation_callback=on_elicit) as s:
            await s.initialize()
            res = await s.call_tool("delete_elements", {"element_ids": [7]})
    deletes = [b for p, b in calls if p.endswith("/delete_elements/")]
    assert len(deletes) == 2 and "confirm" not in deletes[0] and deletes[1]["confirm"] is True
    assert asked and "deleted total: 3" in asked[0]
    assert "confirmed" in _text(res) and '"committed": true' in _text(res)


@pytest.mark.skipif(MCP_MAJOR < 2, reason="elicitation needs mcp 2.x")
async def test_declined_elicitation_changes_nothing(revit):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    import mcp.types as types

    port, calls = revit

    async def on_elicit(context, params):
        return types.ElicitResult(action="decline")

    async with stdio_client(_params(port)) as (r, w):
        async with ClientSession(r, w, elicitation_callback=on_elicit) as s:
            await s.initialize()
            res = await s.call_tool("delete_elements", {"element_ids": [7]})
    deletes = [b for p, b in calls if p.endswith("/delete_elements/")]
    assert len(deletes) == 1 and "declined" in _text(res)


async def test_without_elicitation_preview_is_returned(revit):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    port, calls = revit
    async with stdio_client(_params(port)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("delete_elements", {"element_ids": [7]})
    assert len([1 for p, _b in calls if p.endswith("/delete_elements/")]) == 1
    assert "PREVIEW" in _text(res)


async def test_progress_heartbeats(monkeypatch):
    events = []

    class Ctx(object):
        async def report_progress(self, progress, total=None, message=None):
            events.append(("progress", progress, total, message))

        async def info(self, msg):
            events.append(("info", msg))

    async def slow_post(endpoint, data, ctx, timeout=None):
        await asyncio.sleep(0.35)
        return {"status": "success"}

    monkeypatch.setattr(_common, "HEARTBEAT_SECONDS", 0.1)
    res = await _common.call_with_progress(slow_post, "/qc/clashes/", {}, Ctx(), 30, "Clash check")
    assert res == {"status": "success"}
    progress = [e for e in events if e[0] == "progress"]
    assert progress[0][1] == 0 and len(progress) >= 3
    assert progress[-1][2] == progress[-1][1] and "finished" in progress[-1][3]
    assert [e for e in events if e[0] == "info"][0][1] == "Clash check: started"


async def test_structured_result_falls_back_to_text(monkeypatch):
    from tools import _compat

    monkeypatch.setattr(_compat, "STRUCTURED_OUTPUT", False)
    assert _compat.structured_result("text", {"a": 1}) == "text"
