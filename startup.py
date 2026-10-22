# -*- coding: UTF-8 -*-
"""
Revit MCP Extension Startup (RVTSS)
Registers all MCP routes and initializes the API
"""

from pyrevit import routes
import importlib
import logging
import traceback

logger = logging.getLogger(__name__)

# Initialize the main API
api = routes.API("revit_mcp")

# (module, register function). The original modules come first. Each module is
# registered independently: previously one failing import aborted the
# registration of every module after it.
ROUTE_MODULES = [
    ("revit_mcp.status", "register_status_routes"),
    ("revit_mcp.model_info", "register_model_info_routes"),
    ("revit_mcp.views", "register_views_routes"),
    ("revit_mcp.placement", "register_placement_routes"),
    ("revit_mcp.colors", "register_color_routes"),
    ("revit_mcp.code_execution", "register_code_execution_routes"),
    ("revit_mcp.document", "register_document_routes"),
    # RVTSS modules
    ("revit_mcp.elements", "register_elements_routes"),
    ("revit_mcp.project_data", "register_project_data_routes"),
    ("revit_mcp.families", "register_family_routes"),
    ("revit_mcp.family_geometry", "register_family_geometry_routes"),
    ("revit_mcp.parameters", "register_parameter_routes"),
    ("revit_mcp.documentation", "register_documentation_routes"),
    ("revit_mcp.qc", "register_qc_routes"),
]


def register_routes():
    """Register all MCP route modules"""
    import revit_mcp

    revit_mcp.REGISTRATION_ERRORS.clear()
    for module_name, func_name in ROUTE_MODULES:
        try:
            module = importlib.import_module(module_name)
            getattr(module, func_name)(api)
        except Exception as e:
            revit_mcp.REGISTRATION_ERRORS[module_name] = "{}: {}".format(type(e).__name__, e)
            logger.error("Failed to register %s: %s\n%s", module_name, str(e), traceback.format_exc())
    if revit_mcp.REGISTRATION_ERRORS:
        logger.error("MCP routes registered with errors: %s", revit_mcp.REGISTRATION_ERRORS)
    else:
        logger.info("All MCP routes registered successfully")


# Register all routes when the extension loads
register_routes()
