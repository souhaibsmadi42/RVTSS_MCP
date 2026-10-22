# -*- coding: utf-8 -*-
"""End to end: MCP client -> main.py (stdio, like Claude Desktop) -> fake pyRevit Routes HTTP server.

Verifies the real transport chain without Revit: server start-up, initialize,
tools/list and tools/call, request routing to the configured host/port and
rendering of success / structured error responses.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeRevit(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]  # pyRevit Routes parses the query string separately
        self.calls.append(("GET", path, None))
        if path.endswith("/status/"):
            self._send(200, {"status": "active", "health": "healthy", "revit_available": True,
                             "document_title": "Test.rvt", "api_name": "revit_mcp"})
        else:
            self._send(404, {"error": "unknown"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append(("POST", self.path, body))
        if self.path.endswith("/find_elements/"):
            self._send(200, {"status": "success", "count": 1, "elements": [{"id": 42, "category": "Doors"}]})
        elif self.path.endswith("/family/validate/"):
            self._send(404, {"status": "error", "error": "Open document not found: X",
                             "hint": "Use get_session_info", "did_you_mean": ["X Door"]})
        else:
            self._send(200, {"status": "success"})


@pytest.fixture
def fake_revit():
    _FakeRevit.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _FakeRevit)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1], _FakeRevit.calls
    srv.shutdown()


def _text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


async def test_stdio_roundtrip(fake_revit):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

    port, calls = fake_revit
    env = dict(os.environ, REVIT_PORT=str(port), REVIT_HOST="127.0.0.1", PYTHONPATH=ROOT)
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "main.py")], env=env, cwd=ROOT)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            assert len(names) >= 74 and "family_build_parametric_box" in names

            status = await session.call_tool("get_revit_status", {})
            assert "Test.rvt" in _text(status)

            found = await session.call_tool("find_elements", {"categories": ["Doors"], "limit": 5})
            assert '"id": 42' in _text(found)
            method, path, body = calls[-1]
            assert path == "/revit_mcp/find_elements/" and body["categories"] == ["Doors"] and body["limit"] == 5

            err = await session.call_tool("family_validate", {"document": "X"})
            text = _text(err)
            assert "=== ERROR DETAILS ===" in text and "Use get_session_info" in text and "X Door" in text

            bad = await session.call_tool("find_elements", {"limit": 5000})
            assert bad.isError if hasattr(bad, "isError") else bad.is_error
