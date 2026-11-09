# -*- coding: UTF-8 -*-
"""
Revit MCP Extension Startup (RVTSS)
Registers all MCP routes and initializes the API
"""

from pyrevit import routes
import logging

logger = logging.getLogger(__name__)

# Initialize the main API
api = routes.API("revit_mcp")


def register_routes():
    """Register all MCP route modules (see revit_mcp/registry.py)"""
    import revit_mcp
    from revit_mcp.registry import register_all

    revit_mcp.REGISTRATION_ERRORS.clear()
    revit_mcp.REGISTRATION_ERRORS.update(register_all(api))
    if revit_mcp.REGISTRATION_ERRORS:
        logger.error("MCP routes registered with errors: %s", revit_mcp.REGISTRATION_ERRORS)
    else:
        logger.info("All MCP routes registered successfully")


def install_undo_listener():
    """RVTSS v2.3: DocumentChanged ledger behind undo_last_change (never blocks route registration)."""
    try:
        from pyrevit import HOST_APP
        from revit_mcp import undo

        undo.install(HOST_APP.app)
    except Exception as e:
        logger.error("RVTSS undo listener not installed: %s", e)


# Register all routes when the extension loads
register_routes()
install_undo_listener()
