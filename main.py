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
from typing import Optional, Dict, Any, Union

from tools._compat import create_server, run_server, http_apps, log_level, Image, Context
from revit_mcp.pure import security as _security

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

# Create a generic MCP server for interacting with Revit
# (stateless HTTP + JSON responses for HTTP transports; works on mcp 1.x and 2.x)
mcp = create_server(
    "Revit MCP Server",
    host="127.0.0.1",
    port=int(os.environ.get("MCP_PORT", "8000")),
    instructions=SERVER_INSTRUCTIONS,
)

CONNECT_HINT = (
    "Cannot reach the pyRevit Routes server at {url}. Check that: (1) Revit is running, "
    "(2) pyRevit is loaded, (3) pyRevit Settings > Routes > 'Routes Server' is enabled, "
    "(4) this extension is installed and pyRevit was reloaded, (5) REVIT_HOST/REVIT_PORT "
    "match your setup. Only one copy of the extension may be installed."
)
TIMEOUT_HINT = (
    "Request timed out after {t} seconds. The operation may still be running in Revit. "
    "Revit only executes API requests when idle: close any open dialog, finish any edit "
    "mode (sketch/in-place family), then check the model state before retrying."
)


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return await _revit_call("GET", endpoint, ctx=ctx, **kwargs)


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs)


async def revit_image(endpoint: str, ctx: Context = None) -> Union[Image, str]:
    """GET request that returns an Image object"""
    refused = _remote_refusal()
    if refused:
        return refused
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            _d, params, headers = _auth("GET")
            response = await client.get(f"{BASE_URL}{endpoint}", params=params, headers=headers)

            if response.status_code == 200:
                data = response.json()
                image_bytes = base64.b64decode(data["image_data"])
                return Image(data=image_bytes, format="png")
            else:
                return f"Error: {response.status_code} - {response.text}"
    except httpx.TimeoutException:
        return "Error: Image export timed out after 60 seconds."
    except httpx.ConnectError:
        return "Error: " + CONNECT_HINT.format(url=BASE_URL)
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"


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
    """Internal function handling all HTTP calls"""
    timeout = timeout or DEFAULT_TIMEOUT
    url = f"{BASE_URL}{endpoint}"
    refused = _remote_refusal()
    if refused:
        return refused
    data, params, headers = _auth(method, data, params)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url, params=params, headers=headers)
            else:  # POST
                response = await client.post(url, json=data, headers=headers)

            if response.status_code == 200:
                return response.json()
            logger.info("Revit returned %s for %s", response.status_code, endpoint)
            return _decode_error_response(response)
    except httpx.TimeoutException:
        return "Error: " + TIMEOUT_HINT.format(t=timeout)
    except httpx.ConnectError:
        return "Error: " + CONNECT_HINT.format(url=BASE_URL)
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"


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
    await server.serve()


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

    run_server(mcp, transport)
