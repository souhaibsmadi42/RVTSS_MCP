# -*- coding: utf-8 -*-
"""rvtss_health: one call that answers "is everything wired up?" - works even when Revit is down."""
from ._compat import Context, READ_ONLY, MCP_MAJOR


def register_health_tools(mcp, revit_get, health_probe=None):
    """health_probe: optional coroutine () -> dict with server configuration and a /ping/ result (main.py)."""

    @mcp.tool(annotations=READ_ONLY)
    async def rvtss_health(ctx: Context = None) -> str:
        """Health of the whole chain (MCP server -> pyRevit Routes -> Revit) with the next step to fix it.

        Answers even when Revit is closed or busy: MCP server version and settings (toolsets, read-only
        mode, token, remote host), whether pyRevit Routes answers /ping/ (no Revit API needed), and
        whether Revit has a document open (/status/). Call it first when a tool fails to connect.
        """
        import json

        from revit_mcp import RVTSS_VERSION
        from .toolsets import TOOL_DOCS

        out = {"server": {"rvtss_version": RVTSS_VERSION, "mcp_sdk_major": MCP_MAJOR,
                          "registered_tools": len(TOOL_DOCS)}}
        probe = {}
        if health_probe is not None:
            try:
                probe = await health_probe()
            except Exception as e:  # pragma: no cover - defensive
                probe = {"error": str(e)}
        out["server"].update(probe.get("config", {}))
        ping = probe.get("ping")
        out["routes"] = ping if ping is not None else {"alive": None, "note": "not probed"}
        status = None
        if ping is None or ping.get("alive"):
            status = await revit_get("/status/", ctx, timeout=10.0)
        if isinstance(status, dict):
            out["revit"] = dict((k, status.get(k)) for k in ("status", "health", "document_title", "rvtss_version",
                                                             "route_modules_failed", "security", "error",
                                                             "hint", "request_id") if status.get(k) is not None)
        elif status is not None:
            out["revit"] = {"status": "error", "error": str(status)}
        out["next_step"] = _next_step(out)
        out["status"] = "success" if out["next_step"] is None else "warning"
        return json.dumps(out, indent=2, default=str, ensure_ascii=False)


def _next_step(out):
    routes = out.get("routes") or {}
    revit = out.get("revit") or {}
    server = out.get("server") or {}
    if routes.get("alive") is False:
        return ("pyRevit Routes does not answer: start Revit, check pyRevit Settings > Routes (Routes Server on, "
                "host 127.0.0.1, port %s) and reload pyRevit." % server.get("revit_port", 48884))
    if revit.get("status") == "error" and "token" in str(revit.get("error", "")).lower():
        return "Token mismatch: set the same RVTSS_TOKEN for the MCP server and for Revit."
    if revit.get("status") == "unhealthy" or revit.get("revit_available") is False:
        return "Revit answers but no document is open: open a project (open_document) or ask the user to."
    if revit.get("health") == "degraded":
        return "Some RVTSS route modules failed to load (route_modules_failed): reload pyRevit and check its log."
    rv, sv = revit.get("rvtss_version"), server.get("rvtss_version")
    if rv and sv and rv != sv:
        return ("Version mismatch: Revit extension %s vs MCP server %s. Update both from the same checkout and "
                "reload pyRevit." % (rv, sv))
    if revit.get("status") not in ("active", None):
        return "Revit status: %s - %s" % (revit.get("status"), revit.get("error") or revit.get("hint") or "")
    return None
