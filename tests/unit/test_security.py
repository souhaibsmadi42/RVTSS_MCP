# -*- coding: utf-8 -*-
"""Phase 2 security: token protection, code execution gate, remote refusal, log redaction."""
import importlib
import inspect
import json
import sys

import httpx
import pytest

from revit_mcp.pure import security as S
from .revit_stubs import revit_environment, FakeRequest


# ------------------------------------------------------------------- pure
class TestPure:
    def test_redact_known_secret_shapes(self):
        text = ('password="hunter2" api_key: abc123 token=xyz sk-ABCDEFGHIJKLMNOPQRSTUV '
                'ghp_ABCDEFGHIJKLMNOPQRSTUVWX12 eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghij')
        out = S.redact(text)
        for secret in ("hunter2", "abc123", "xyz", "sk-ABCD", "ghp_ABCD", "eyJhbGci"):
            assert secret not in out
        assert out.count(S.REDACTED) >= 6

    def test_redact_keeps_normal_text_and_guids(self):
        s = "Set Comments on 12 walls in C:\\Projects\\Tower A.rvt guid 5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01"
        assert S.redact(s) == s

    def test_redact_caps_length(self):
        out = S.redact("wall " * 200, max_len=100)
        assert len(out) < 140 and out.endswith("chars]")
        # long opaque blobs are treated as secrets before capping
        assert S.redact("z" * 600) == S.REDACTED

    def test_redact_mapping(self):
        d = S.redact_mapping({"name": "Mark", "password": "p", "nested": [{"apiKey": "k", "v": "ok"}]})
        assert d == {"name": "Mark", "password": S.REDACTED, "nested": [{"apiKey": S.REDACTED, "v": "ok"}]}

    def test_token_extraction_and_compare(self):
        assert S.extract_token({"_rvtss_token": "a"}) == "a"
        assert S.extract_token(None, {"rvtss_token": ["b"]}) == "b"
        assert S.extract_token(None, None, {"x-rvtss-token": "c"}) == "c"
        assert S.constant_time_equal("abc", "abc") and not S.constant_time_equal("abc", "abd")
        assert not S.constant_time_equal(None, "abc")

    def test_flags_and_hosts(self):
        assert S.parse_flag("0") is False and S.parse_flag("yes") is True and S.parse_flag(None, True) is True
        assert S.is_loopback("127.0.0.1") and S.is_loopback("localhost") and not S.is_loopback("10.0.0.5")
        assert S.binds_all_interfaces("") and S.binds_all_interfaces("0.0.0.0") and not S.binds_all_interfaces("127.0.0.1")


# --------------------------------------------------------------- revit side
@pytest.fixture
def secured_routes(monkeypatch):
    monkeypatch.setenv("RVTSS_TOKEN", "s3cret")
    with revit_environment():
        startup = importlib.import_module("startup")
        import revit_mcp

        yield startup.api, dict(revit_mcp.REGISTRATION_ERRORS)


def _route(api, path):
    return [r for r in api.routes if r["path"] == path][0]["func"]


def test_token_wraps_every_route_but_status(secured_routes):
    api, errors = secured_routes
    assert errors == {}
    for r in api.routes:
        args = list(inspect.signature(r["func"]).parameters)
        if r["path"] in S.UNPROTECTED_PATHS:
            assert "request" not in args or r["path"] != "/status/"
        else:
            assert "request" in args, r["path"]
        assert set(args) <= {"doc", "uidoc", "request", "view_name"}, (r["path"], args)


def test_token_rejects_and_accepts(secured_routes):
    api, _ = secured_routes
    find = _route(api, "/find_elements/")
    denied = find(doc=None, uidoc=None, request=FakeRequest({"categories": ["Walls"]}))
    assert denied["status"] == 401 and "token" in denied["data"]["error"]
    bad = find(doc=None, uidoc=None, request=FakeRequest({"_rvtss_token": "nope"}))
    assert bad["status"] == 401
    req = FakeRequest({"_rvtss_token": "s3cret", "categories": ["Walls"]})
    ok = find(doc=None, uidoc=None, request=req)
    assert ok["status"] == 503  # reached the handler (no document in the stub)
    assert "_rvtss_token" not in req.data  # token stripped before the handler sees the body


def test_token_on_get_routes_via_query(secured_routes):
    api, _ = secured_routes
    levels = _route(api, "/list_levels/")
    assert list(inspect.signature(levels).parameters) == ["doc", "request"]

    class Req(object):
        data = None
        query_params = {"rvtss_token": "s3cret"}
    res = levels(doc=None, request=Req())
    assert res["status"] == 503  # legacy handler ran: "No active Revit document"
    Req.query_params = {}
    assert levels(doc=None, request=Req())["status"] == 401


def test_registration_fails_closed(monkeypatch):
    monkeypatch.setenv("RVTSS_TOKEN", "s3cret")
    with revit_environment():
        import revit_mcp.secure_api as sa

        def boom(api):
            raise RuntimeError("broken")
        monkeypatch.setattr(sa, "secured", boom)
        from revit_mcp.registry import register_all
        from .revit_stubs import FakeAPI

        api = FakeAPI("revit_mcp")
        errors = register_all(api)
        assert api.routes == [] and "revit_mcp.secure_api" in errors


def test_no_token_means_unchanged_handlers(monkeypatch):
    monkeypatch.delenv("RVTSS_TOKEN", raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        levels = _route(startup.api, "/list_levels/")
        assert list(inspect.signature(levels).parameters) == ["doc"]


class _FakeApp(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        return self


class _Doc(object):
    IsModifiable = True  # skip the TransactionGroup in the stub
    IsReadOnly = False
    Title = "Stub.rvt"

    class Application(object):
        DocumentChanged = None


def _exec_route(monkeypatch):
    with revit_environment():
        startup = importlib.import_module("startup")
        return _route(startup.api, "/execute_code/")


def test_code_execution_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("RVTSS_ALLOW_CODE_EXECUTION", "0")
    monkeypatch.delenv("RVTSS_TOKEN", raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        run = _route(startup.api, "/execute_code/")
        res = run(doc=_Doc(), uidoc=None, request=FakeRequest({"code": "x = 1"}))
        assert res["status"] == 403 and "disabled" in res["data"]["error"]


def test_code_is_audited_with_redaction_and_read_only_blocks_transactions(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_ALLOW_CODE_EXECUTION", raising=False)
    monkeypatch.delenv("RVTSS_TOKEN", raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        run = _route(startup.api, "/execute_code/")
        ok = run(doc=_Doc(), uidoc=None, request=FakeRequest({
            "code": "api_key = 'abc123'\nresult = 1", "transaction_mode": "read_only"}))
        assert ok["status"] == 200 and ok["data"]["status"] == "success"
        blocked = run(doc=_Doc(), uidoc=None, request=FakeRequest({
            "code": "t = DB.Transaction(doc, 'x')", "transaction_mode": "read_only"}))
        assert blocked["status"] == 500 and "read_only mode" in blocked["data"]["error"]
    logs = list((tmp_path / "RVTSS" / "logs").glob("code-*.log"))
    text = logs[0].read_text(encoding="utf-8")
    assert "result = 1" in text and "abc123" not in text and S.REDACTED in text


# ---------------------------------------------------------------- mcp side
class TestClient:
    def _patch(self, monkeypatch, handler):
        import main

        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)
        monkeypatch.setattr(main.httpx, "AsyncClient", factory)
        return main

    async def test_token_sent_in_body_query_and_header(self, monkeypatch):
        seen = []

        def handler(req):
            seen.append(req)
            return httpx.Response(200, json={"status": "success"})
        main = self._patch(monkeypatch, handler)
        monkeypatch.setattr(main, "RVTSS_TOKEN", "s3cret")
        await main.revit_post("/find_elements/", {"a": 1})
        await main.revit_get("/list_levels/")
        body = json.loads(seen[0].content)
        assert body == {"a": 1, "_rvtss_token": "s3cret"} and seen[0].headers["X-RVTSS-Token"] == "s3cret"
        assert seen[1].url.params["rvtss_token"] == "s3cret"

    async def test_remote_host_refused_unless_allowed(self, monkeypatch):
        main = self._patch(monkeypatch, lambda req: httpx.Response(200, json={"status": "success"}))
        monkeypatch.setattr(main, "REVIT_HOST", "192.168.1.20")
        monkeypatch.setattr(main, "ALLOW_REMOTE", False)
        res = await main.revit_get("/status/")
        assert isinstance(res, str) and "RVTSS_ALLOW_REMOTE=1" in res
        monkeypatch.setattr(main, "ALLOW_REMOTE", True)
        assert (await main.revit_get("/status/"))["status"] == "success"
