# -*- coding: utf-8 -*-
"""RVTSS MCP server - bridges Claude (MCP) and Revit (pyRevit Routes).

Created by Suhaib Al Smadi. Based on mcp-server-for-revit-python.
"""
import os
import sys
import json
import logging
import httpx
import anyio
import base64
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, Union

from tools._compat import create_server, run_server, http_apps, log_level, Image, Context
from revit_mcp.pure import security as _security
from revit_mcp.pure import tracing as _tracing

# MCP stdio uses stdout for the protocol: all logging must go to stderr.
logging.basicConfig(
    level=os.environ.get("RVTSS_LOG_LEVEL", "WARNING").upper(),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rvtss")

SERVER_INSTRUCTIONS = """RVTSS controls a live Autodesk Revit session through pyRevit.
Working rules:
1. Inspect before changing: use get_revit_status / get_revit_model_info / find_elements /
   family_get_info to learn the current state first. Use element ids returned by tools.
2. Lengths in RVTSS tools default to millimetres ("unit" argument). Legacy tools
   place_family / list_levels / get_current_view_elements report decimal feet.
3. Prefer dry_run=true for multi-element or structural changes, read the preview,
   then run again with dry_run=false (and confirm=true when asked).
4. Destructive or large operations return status "preview" until confirm=true is passed.
5. Verify after changing: re-read the elements or run family_flex_test / family_validate.
6. Never report a change as done unless the tool returned status "success".
Families: family_list_templates -> family_create (or family_open) -> family_add_parameters ->
family_build_parametric_box / family_create_reference_planes + family_create_form +
family_add_dimension -> family_manage_types -> family_flex_test -> family_validate ->
family_save -> family_load_into_project."""

# Configuration
# Revit runs on Windows; when it lives in a VM the routes server is not on the
# host loopback, so allow overriding the target via the environment.
REVIT_HOST = os.environ.get("REVIT_HOST", "127.0.0.1")
REVIT_PORT = int(os.environ.get("REVIT_PORT", "48884"))
REVIT_API_NAME = os.environ.get("REVIT_API_NAME", "revit_mcp")
DEFAULT_TIMEOUT = float(os.environ.get("RVTSS_TIMEOUT", "30"))
BASE_URL = f"http://{REVIT_HOST}:{REVIT_PORT}/{REVIT_API_NAME}"
# Optional shared secret (must match RVTSS_TOKEN of the Revit process). pyRevit
# Routes does not hand HTTP headers to route handlers, so the token is sent in
# the JSON body (POST) and the query string (GET); the header is sent as well.
RVTSS_TOKEN = os.environ.get("RVTSS_TOKEN") or None
# Talking to a Routes server that is not on this machine must be explicit.
ALLOW_REMOTE = bool(_security.parse_flag(os.environ.get("RVTSS_ALLOW_REMOTE"), False))
REMOTE_REFUSED = (
    "Refusing to send Revit commands to non-loopback host '{host}'. pyRevit Routes has no authentication of "
    "its own: set RVTSS_ALLOW_REMOTE=1 (and preferably RVTSS_TOKEN on both sides) for VM / remote setups."
)


def _remote_refusal():
    if _security.is_loopback(REVIT_HOST) or ALLOW_REMOTE:
        return None
    return "Error: " + REMOTE_REFUSED.format(host=REVIT_HOST)


def _auth(method, data=None, params=None):
    """Add the RVTSS token to a request (body for POST, query for GET, plus header)."""
    headers = {"Content-Type": "application/json"} if method == "POST" else {}
    if not RVTSS_TOKEN:
        return data, params, headers
    headers[_security.TOKEN_HEADER] = RVTSS_TOKEN
    if method == "POST":
        data = dict(data or {})
        data[_security.TOKEN_BODY_KEY] = RVTSS_TOKEN
    else:
        params = dict(params or {})
        params[_security.TOKEN_QUERY_KEY] = RVTSS_TOKEN
    return data, params, headers

# stdio serves one session for the life of the process: close the pooled HTTP
# client when it ends. HTTP transports are stateless (the lifespan runs per
# request), so there the pool stays open and is closed when uvicorn stops.
_CLOSE_POOL_ON_SESSION_END = {"enabled": False}


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        if _CLOSE_POOL_ON_SESSION_END["enabled"]:
            await close_client()


# Create a generic MCP server for interacting with Revit
# (stateless HTTP + JSON responses for HTTP transports; works on mcp 1.x and 2.x)
mcp = create_server(
    "Revit MCP Server",
    host="127.0.0.1",
    port=int(os.environ.get("MCP_PORT", "8000")),
    instructions=SERVER_INSTRUCTIONS,
    lifespan=_lifespan,
)

CONNECT_HINT = (
    "Cannot reach the pyRevit Routes server at {url}. Check that: (1) Revit is running, "
    "(2) pyRevit is loaded, (3) pyRevit Settings > Routes > 'Routes Server' is enabled, "
    "(4) this extension is installed and pyRevit was reloaded, (5) REVIT_HOST/REVIT_PORT "
    "match your setup. Only one copy of the extension may be installed."
)
TIMEOUT_BUSY_HINT = (
    "Revit is busy: no answer after {t} seconds, but the pyRevit Routes server is running (/ping/ answered). "
    "Revit's main thread is blocked by a modal dialog, an edit mode (sketch / in-place family / group edit) "
    "or a long operation, which may still finish. Close dialogs, finish the edit mode, then check the model "
    "state before retrying."
)
HOST_TIMEOUT_HINT = (
    "pyRevit could not get Revit's main thread: Revit is busy with a modal dialog, an edit mode or a long "
    "operation. Close dialogs / finish the edit mode, then retry."
)
TIMEOUT_DOWN_HINT = (
    "No answer after {t} seconds and the pyRevit Routes server at {url} does not answer /ping/ either: "
    "Revit may be frozen, closed, or Routes stopped. Check Revit, then reload pyRevit."
)


IMAGE_TIMEOUT = float(os.environ.get("RVTSS_IMAGE_TIMEOUT", "60"))
# Images larger than this are refused (they would flood the model context).
IMAGE_MAX_BYTES = int(float(os.environ.get("RVTSS_IMAGE_MAX_KB", "4096")) * 1024)
PING_TIMEOUT = 3.0
# Connection errors after which a GET is retried once (a pooled keep-alive
# connection closed by the server). Never applied to POST: it may change the model.
RETRYABLE_GET_ERRORS = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


class _ClientPool(object):
    """One pooled httpx.AsyncClient per event loop.

    Created on first use, recreated when the event loop changes (tests, combined
    mode restarts) or when httpx.AsyncClient was replaced (unit tests), and
    closed by close_client() / the server lifespan. Timeouts are passed per call.
    """

    def __init__(self):
        self.client = None
        self._loop = None
        self._factory = None

    def get(self):
        import asyncio

        loop = asyncio.get_running_loop()
        stale = (self.client is None or self.client.is_closed or self._loop is not loop
                 or self._factory is not httpx.AsyncClient)
        if stale:
            self._factory = httpx.AsyncClient
            self._loop = loop
            self.client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=10.0))
        return self.client

    async def aclose(self):
        client, self.client = self.client, None
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                pass


_POOL = _ClientPool()


async def close_client():
    await _POOL.aclose()


def new_request_id():
    return uuid.uuid4().hex[:12]


def _with_request_id(data, params, method, request_id):
    if method == "POST":
        data = dict(data or {})
        data[_tracing.REQUEST_ID_BODY_KEY] = request_id
    else:
        params = dict(params or {})
        params[_tracing.REQUEST_ID_QUERY_KEY] = request_id
    return data, params


async def ping_revit() -> Dict[str, Any]:
    """GET /ping/ (no Revit API context): is the Routes server itself alive?"""
    try:
        client = _POOL.get()
        _d, params, headers = _auth("GET")
        response = await client.get(f"{BASE_URL}/ping/", params=params, headers=headers, timeout=PING_TIMEOUT)
        if response.status_code == 200:
            return {"alive": True}
        if response.status_code == 404:
            return {"alive": True, "note": "Routes answered but /ping/ is missing (RVTSS extension older than v2.1)"}
        return {"alive": True, "note": "Routes answered {}".format(response.status_code)}
    except Exception as e:
        return {"alive": False, "error": str(e) or type(e).__name__}


async def _timeout_message(timeout, request_id):
    probe = await ping_revit()
    if probe.get("alive"):
        text = TIMEOUT_BUSY_HINT.format(t=timeout)
    else:
        text = TIMEOUT_DOWN_HINT.format(t=timeout, url=BASE_URL)
    return "Error: {} (request_id: {})".format(text, request_id)


def _error_suffix(request_id):
    return " (request_id: {})".format(request_id)


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return await _revit_call("GET", endpoint, ctx=ctx, **kwargs)


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs)


def _image_error(error, kind, request_id, hint=None, **extra):
    """Same envelope as the JSON tools: status/error/hint (+ request_id)."""
    out = {"status": "error", "error": error, "error_kind": kind, "request_id": request_id}
    if hint:
        out["hint"] = hint
    out.update(extra)
    return out


async def revit_image(endpoint: str, ctx: Context = None, timeout: float = None, image_format: str = None,
                      pixel_size: int = None, max_bytes: int = None) -> Union[Image, Dict]:
    """GET a view export and return an Image, or a structured error envelope."""
    request_id = new_request_id()
    refused = _remote_refusal()
    if refused:
        return _image_error(refused[len("Error: "):], "remote_refused", request_id)
    timeout = timeout or IMAGE_TIMEOUT
    max_bytes = max_bytes or IMAGE_MAX_BYTES
    query = {}
    if image_format:
        query["image_format"] = image_format
    if pixel_size:
        query["pixel_size"] = int(pixel_size)
    _d, params, headers = _auth("GET", params=query)
    _d, params = _with_request_id(None, params, "GET", request_id)
    url = f"{BASE_URL}{endpoint}"
    try:
        client = _POOL.get()
        try:
            response = await client.get(url, params=params, headers=headers, timeout=timeout)
        except RETRYABLE_GET_ERRORS:
            response = await client.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code != 200:
            body = _decode_error_response(response)
            if isinstance(body, dict):
                body.setdefault("request_id", request_id)
                body.setdefault("error_kind", "revit_error")
                return body
            return _image_error(body[len("Error: "):], "revit_error", request_id,
                                response_code=response.status_code)
        data = response.json()
        image_bytes = base64.b64decode(data["image_data"])
        if len(image_bytes) > max_bytes:
            return _image_error(
                "View image is {:.0f} KB, above the {:.0f} KB limit".format(len(image_bytes) / 1024.0,
                                                                            max_bytes / 1024.0),
                "image_too_large", request_id,
                hint="Retry with image_format='jpg' and/or a smaller pixel_size (e.g. 800), "
                     "or raise RVTSS_IMAGE_MAX_KB.")
        content_type = data.get("content_type") or "image/png"
        return Image(data=image_bytes, format="jpeg" if "jpeg" in content_type else "png")
    except httpx.TimeoutException:
        return _image_error((await _timeout_message(timeout, request_id))[len("Error: "):], "timeout", request_id)
    except httpx.ConnectError:
        return _image_error(CONNECT_HINT.format(url=BASE_URL), "routes_unreachable", request_id)
    except Exception as e:
        return _image_error(str(e) or type(e).__name__, "client_error", request_id)


def _decode_error_response(response) -> Union[Dict, str]:
    """Keep structured error payloads (error, hint, traceback...) instead of raw text.

    Previously every non-200 answer was flattened into "Error: <code> - <body>",
    which hid hints and recovery data from the model.
    """
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        body = dict(body)
        body.setdefault("response_code", response.status_code)
        if not body.get("status"):
            body["status"] = "error"
        return body
    return f"Error: {response.status_code} - {response.text}"


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                     timeout: float = None, params: Dict = None) -> Union[Dict, str]:
    """Internal function handling all HTTP calls.

    Every call carries a correlation id (body `_rvtss_request_id` / query
    `rvtss_request_id`), which the Revit side writes to its audit log and returns
    as `request_id`. GETs are retried once after a dropped connection; POSTs are
    never retried. Timeouts ping /ping/ to report "Revit busy" vs "Routes down".
    """
    timeout = timeout or DEFAULT_TIMEOUT
    url = f"{BASE_URL}{endpoint}"
    request_id = new_request_id()
    refused = _remote_refusal()
    if refused:
        return refused
    data, params, headers = _auth(method, data, params)
    data, params = _with_request_id(data, params, method, request_id)
    try:
        client = _POOL.get()
        if method == "GET":
            try:
                response = await client.get(url, params=params, headers=headers, timeout=timeout)
            except RETRYABLE_GET_ERRORS as e:
                logger.info("GET %s retried after %s (request_id %s)", endpoint, type(e).__name__, request_id)
                response = await client.get(url, params=params, headers=headers, timeout=timeout)
        else:  # POST
            response = await client.post(url, json=data, headers=headers, timeout=timeout)

        if response.status_code == 200:
            body = response.json()
            if isinstance(body, dict):
                body.setdefault("request_id", request_id)
            return body
        logger.info("Revit returned %s for %s (request_id %s)", response.status_code, endpoint, request_id)
        body = _decode_error_response(response)
        if isinstance(body, dict):
            body.setdefault("request_id", request_id)
            if response.status_code == 504 and "timed out by host" in json.dumps(body):
                # pyRevit gave up waiting for Revit's main thread (RouteHandlerTimedOutException)
                body.setdefault("hint", HOST_TIMEOUT_HINT)
            return body
        return body + _error_suffix(request_id)
    except httpx.TimeoutException:
        return await _timeout_message(timeout, request_id)
    except httpx.ConnectError:
        return "Error: " + CONNECT_HINT.format(url=BASE_URL) + _error_suffix(request_id)
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}" + _error_suffix(request_id)


# Register all tools BEFORE the main block
from tools import register_tools
toolset_server = register_tools(mcp, revit_get, revit_post, revit_image)


async def run_combined_async():
    """Run server with both SSE and streamable-http endpoints.

    This allows clients to connect via either:
    - SSE: GET /sse, POST /messages/
    - Streamable-HTTP: POST/GET /mcp
    """
    import uvicorn

    # Get the streamable-http app first - it has the proper lifespan
    # that initializes the session manager's task group
    http_app, sse_app = http_apps(mcp)

    # Add SSE routes to the http app (preserving its lifespan)
    for route in sse_app.routes:
        http_app.routes.append(route)

    config = uvicorn.Config(
        http_app,
        host=mcp._rvtss_host,
        port=mcp._rvtss_port,
        log_level=log_level(mcp),
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await close_client()


if __name__ == "__main__":
    transport = "stdio"

    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv or "--streamable-http" in sys.argv:
        transport = "streamable-http"
    elif "--combined" in sys.argv:
        # Run both SSE and streamable-http transports simultaneously
        print("Starting combined server with SSE (/sse, /messages/) and streamable-http (/mcp) endpoints...",
              file=sys.stderr)
        anyio.run(run_combined_async)
        sys.exit(0)

    _CLOSE_POOL_ON_SESSION_END["enabled"] = transport == "stdio"
    run_server(mcp, transport)
