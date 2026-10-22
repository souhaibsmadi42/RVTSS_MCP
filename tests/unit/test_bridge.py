# -*- coding: utf-8 -*-
"""Phase 5: pooled client, GET retry, timeout diagnosis via /ping/, image envelope, correlation ids."""
import base64
import importlib
import inspect
import json

import httpx
import pytest

from revit_mcp.pure import tracing as T

from .revit_stubs import revit_environment, FakeRequest


@pytest.fixture
def bridge(monkeypatch):
    """main with httpx.AsyncClient bound to a MockTransport; returns (main, setter for the handler, factory calls)."""
    import main

    real = httpx.AsyncClient
    state = {"handler": lambda req: httpx.Response(200, json={"status": "success"}), "created": 0}

    def factory(*args, **kwargs):
        state["created"] += 1
        kwargs["transport"] = httpx.MockTransport(lambda req: state["handler"](req))
        return real(*args, **kwargs)
    monkeypatch.setattr(main.httpx, "AsyncClient", factory)

    def set_handler(h):
        state["handler"] = h
    yield main, set_handler, state


# ------------------------------------------------------------------ pooling
async def test_one_pooled_client_is_reused(bridge):
    main, _set, state = bridge
    await main.revit_get("/status/")
    await main.revit_post("/find_elements/", {})
    await main.revit_get("/list_levels/")
    assert state["created"] == 1
    await main.close_client()
    assert main._POOL.client is None
    await main.revit_get("/status/")
    assert state["created"] == 2


# ------------------------------------------------------------------- retries
async def test_get_is_retried_once_after_connection_reset(bridge):
    main, set_handler, _ = bridge
    calls = []

    def flaky(req):
        calls.append(req)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=req)
        return httpx.Response(200, json={"status": "success"})
    set_handler(flaky)
    assert (await main.revit_get("/list_levels/"))["status"] == "success"
    assert len(calls) == 2
    # the same correlation id is reused for the retry
    assert calls[0].url.params["rvtss_request_id"] == calls[1].url.params["rvtss_request_id"]


async def test_get_is_not_retried_twice(bridge):
    main, set_handler, _ = bridge
    calls = []

    def dead(req):
        calls.append(req)
        raise httpx.ReadError("Connection reset by peer", request=req)
    set_handler(dead)
    res = await main.revit_get("/list_levels/")
    assert isinstance(res, str) and "Connection reset" in res and "request_id" in res
    assert len(calls) == 2


async def test_post_is_never_retried(bridge):
    main, set_handler, _ = bridge
    calls = []

    def reset(req):
        calls.append(req)
        raise httpx.RemoteProtocolError("Server disconnected", request=req)
    set_handler(reset)
    res = await main.revit_post("/delete_elements/", {"element_ids": [1], "confirm": True})
    assert isinstance(res, str) and res.startswith("Error:")
    assert len(calls) == 1


# ------------------------------------------------------------ timeout cases
async def test_timeout_with_live_routes_reports_revit_busy(bridge):
    main, set_handler, _ = bridge

    def handler(req):
        if req.url.path.endswith("/ping/"):
            return httpx.Response(200, json={"status": "success", "pong": True})
        raise httpx.ReadTimeout("timed out", request=req)
    set_handler(handler)
    res = await main.revit_post("/qc/clashes/", {}, timeout=1)
    assert "Revit is busy" in res and "modal dialog" in res and "/ping/ answered" in res


async def test_timeout_with_dead_routes_reports_routes_down(bridge):
    main, set_handler, _ = bridge

    def handler(req):
        if req.url.path.endswith("/ping/"):
            raise httpx.ConnectError("refused", request=req)
        raise httpx.ReadTimeout("timed out", request=req)
    set_handler(handler)
    res = await main.revit_get("/status/", timeout=1)
    assert "does not answer /ping/" in res and "Revit is busy" not in res


async def test_pyrevit_host_timeout_gets_busy_hint(bridge):
    main, set_handler, _ = bridge
    set_handler(lambda req: httpx.Response(504, json={"exception": {
        "source": "Autodesk Revit 2026", "message": 'Route handler was timed out by host: "/find_elements/"'}}))
    res = await main.revit_post("/find_elements/", {})
    assert res["status"] == "error" and res["response_code"] == 504
    assert "modal dialog" in res["hint"] and res["request_id"]


async def test_connect_error_message_unchanged_plus_request_id(bridge):
    main, set_handler, _ = bridge

    def refused(req):
        raise httpx.ConnectError("refused", request=req)
    set_handler(refused)
    res = await main.revit_get("/status/")
    assert res.startswith("Error: Cannot reach the pyRevit Routes server") and "(request_id: " in res


# ----------------------------------------------------------- correlation id
async def test_request_id_sent_and_returned(bridge):
    main, set_handler, _ = bridge
    seen = []

    def echo(req):
        seen.append(req)
        if req.method == "POST":
            rid = json.loads(req.content)["_rvtss_request_id"]
        else:
            rid = req.url.params["rvtss_request_id"]
        return httpx.Response(200, json={"status": "success", "request_id": rid})
    set_handler(echo)
    post = await main.revit_post("/find_elements/", {"a": 1})
    get = await main.revit_get("/list_levels/")
    assert post["request_id"] != get["request_id"]
    assert post["request_id"] == json.loads(seen[0].content)["_rvtss_request_id"]


async def test_request_id_added_when_revit_side_is_older(bridge):
    main, set_handler, _ = bridge
    set_handler(lambda req: httpx.Response(200, json={"status": "success"}))
    res = await main.revit_get("/status/")
    assert len(res["request_id"]) == 12


# ------------------------------------------------------------------- images
def _png(n=100):
    return base64.b64encode(b"\x89PNG" + b"0" * n).decode()


async def test_image_success_and_query_options(bridge):
    main, set_handler, _ = bridge
    seen = []

    def ok(req):
        seen.append(req)
        return httpx.Response(200, json={"image_data": _png(), "content_type": "image/jpeg"})
    set_handler(ok)
    img = await main.revit_image("/get_view/Level 1", None, image_format="jpg", pixel_size=800)
    assert isinstance(img, main.Image)
    q = seen[0].url.params
    assert q["image_format"] == "jpg" and q["pixel_size"] == "800" and q["rvtss_request_id"]


async def test_image_errors_use_the_envelope(bridge):
    main, set_handler, _ = bridge
    set_handler(lambda req: httpx.Response(404, json={"error": "View 'X' not found", "available_views": ["A"]}))
    res = await main.revit_image("/get_view/X")
    assert res["status"] == "error" and res["available_views"] == ["A"] and res["request_id"]
    assert res["error_kind"] == "revit_error" and res["response_code"] == 404

    set_handler(lambda req: httpx.Response(500, text="boom"))
    res = await main.revit_image("/get_view/X")
    assert res["status"] == "error" and "boom" in res["error"] and res["response_code"] == 500

    def refused(req):
        raise httpx.ConnectError("refused", request=req)
    set_handler(refused)
    res = await main.revit_image("/get_view/X")
    assert res["error_kind"] == "routes_unreachable" and "Routes Server" in res["error"]


async def test_image_size_limit(bridge):
    main, set_handler, _ = bridge
    set_handler(lambda req: httpx.Response(200, json={"image_data": _png(5000), "content_type": "image/png"}))
    res = await main.revit_image("/get_view/Big", max_bytes=1024)
    assert res["error_kind"] == "image_too_large" and "pixel_size" in res["hint"]


async def test_image_timeout_is_diagnosed(bridge, monkeypatch):
    main, set_handler, _ = bridge

    def handler(req):
        if req.url.path.endswith("/ping/"):
            return httpx.Response(200, json={"pong": True})
        raise httpx.ReadTimeout("timed out", request=req)
    set_handler(handler)
    res = await main.revit_image("/get_view/X", timeout=1)
    assert res["error_kind"] == "timeout" and "Revit is busy" in res["error"]


async def test_ping_reports_old_extension(bridge):
    main, set_handler, _ = bridge
    set_handler(lambda req: httpx.Response(404, json={"error": "no route"}))
    probe = await main.ping_revit()
    assert probe["alive"] and "older than v2.1" in probe["note"]


# ---------------------------------------------------------------- pure logic
def test_tracing_helpers():
    assert T.clean_request_id("abc-123_x.y:z") == "abc-123_x.y:z"
    assert T.clean_request_id("a b") is None and T.clean_request_id("x" * 65) is None
    assert T.clean_request_id("x\nINJECTED") is None and T.clean_request_id(None) is None
    data = {"_rvtss_request_id": "r1", "a": 1}
    assert T.pop_request_id(data, None) == "r1" and data == {"a": 1}
    assert T.pop_request_id({}, {"rvtss_request_id": "q1"}) == "q1"
    assert T.attach_request_id({"status": "success"}, "r1") == {"status": "success", "request_id": "r1"}
    stub = {"data": {"x": 1}, "status": 200}
    assert T.attach_request_id(stub, "r2")["data"]["request_id"] == "r2"

    class Resp(object):
        data = {"a": 1}
    assert T.attach_request_id(Resp(), "r3").data["request_id"] == "r3"
    assert T.attach_request_id({"request_id": "keep"}, "new")["request_id"] == "keep"
    assert T.attach_request_id("text body", "r4") == "text body"


# ------------------------------------------------------------- Revit side
def _route(api, path):
    return [r for r in api.routes if r["path"] == path][0]["func"]


def test_ping_route_answers_without_api_context_and_without_token(monkeypatch):
    monkeypatch.setenv("RVTSS_TOKEN", "s3cret")
    with revit_environment():
        startup = importlib.import_module("startup")
        ping = _route(startup.api, "/ping/")
        assert list(inspect.signature(ping).parameters) == ["request"]  # no doc/uidoc -> no API context
        res = ping(request=FakeRequest({}))
        assert res["status"] == 200 and res["data"]["pong"] is True


def test_get_view_accepts_request_for_image_options():
    with revit_environment():
        startup = importlib.import_module("startup")
        get_view = _route(startup.api, "/get_view/<view_name>")
        assert {"doc", "view_name", "request"} <= set(inspect.signature(get_view).parameters)

        class Req(object):
            data = None
            query_params = {"image_format": "gif"}
        res = get_view(doc=object(), view_name="Level 1", request=Req())
        assert res["status"] == 400 and "png or jpg" in res["data"]["error"]


def test_request_id_reaches_audit_log(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("RVTSS_TOKEN", raising=False)
    with revit_environment():
        startup = importlib.import_module("startup")
        session_info = _route(startup.api, "/session_info/")
        res = session_info(doc=None, uidoc=None, request=FakeRequest({"_rvtss_request_id": "corr-42"}))
        assert res["data"]["request_id"] == "corr-42"
        from revit_mcp import core
        assert core.current_request_id() is None  # cleared after the request
    logs = list((tmp_path / "RVTSS" / "logs").glob("rvtss-*.log"))
    assert logs and "corr-42" in logs[0].read_text(encoding="utf-8")
