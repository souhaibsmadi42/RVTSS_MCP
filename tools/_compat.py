# -*- coding: utf-8 -*-
"""Compatibility layer for the MCP Python SDK 1.x (FastMCP) and 2.x (MCPServer).

mcp 2.x renamed ``mcp.server.fastmcp.FastMCP`` to ``mcp.server.mcpserver.MCPServer``
and moved transport settings (host/port/stateless_http/json_response) from the
constructor to ``run()`` / the app factories. requirements.txt pinned mcp 2.2.0
while every module imported ``mcp.server.fastmcp``, so a fresh
``pip install -r requirements.txt`` produced a server that crashed on import.
Everything in this package imports Context/Image/create_server from here instead.
"""

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerClass, Context, Image  # noqa: F401
    from mcp.server.fastmcp.exceptions import ToolError  # noqa: F401

    MCP_MAJOR = 1
except ImportError:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _ServerClass, Context, Image  # noqa: F401
    from mcp.server.mcpserver.exceptions import ToolError  # noqa: F401

    MCP_MAJOR = 2

try:
    from mcp.types import ToolAnnotations
except ImportError:  # very old SDKs
    ToolAnnotations = None


def create_server(name, host="127.0.0.1", port=8000, instructions=None):
    """Create the MCP server object for whichever SDK is installed."""
    if MCP_MAJOR == 1:
        kwargs = dict(host=host, port=port, stateless_http=True, json_response=True)
        if instructions:
            kwargs["instructions"] = instructions
        server = _ServerClass(name, **kwargs)
    else:
        server = _ServerClass(name, instructions=instructions)
    # remember transport settings for run_server()/combined mode
    server._rvtss_host = host
    server._rvtss_port = port
    return server


def run_server(server, transport="stdio"):
    if transport == "stdio" or MCP_MAJOR == 1:
        server.run(transport=transport)
        return
    kwargs = {"host": server._rvtss_host, "port": server._rvtss_port}
    if transport == "streamable-http":
        kwargs.update(stateless_http=True, json_response=True)
    server.run(transport=transport, **kwargs)


def http_apps(server):
    """Return (streamable_http_app, sse_app) for combined mode."""
    if MCP_MAJOR == 1:
        return server.streamable_http_app(), server.sse_app()
    host = server._rvtss_host
    return (server.streamable_http_app(stateless_http=True, json_response=True, host=host),
            server.sse_app(host=host))


def log_level(server):
    try:
        return server.settings.log_level.lower()
    except AttributeError:
        return "info"


def annotations(read_only=False, destructive=False, idempotent=None, title=None):
    """Build ToolAnnotations hints (camelCase aliases work on both SDK majors)."""
    if ToolAnnotations is None:
        return None
    kwargs = {"readOnlyHint": read_only, "destructiveHint": destructive, "openWorldHint": False}
    if idempotent is not None:
        kwargs["idempotentHint"] = idempotent
    if title:
        kwargs["title"] = title
    return ToolAnnotations(**kwargs)


READ_ONLY = annotations(read_only=True, idempotent=True)
MODIFIES = annotations(read_only=False, destructive=False)
DESTRUCTIVE = annotations(read_only=False, destructive=True)
