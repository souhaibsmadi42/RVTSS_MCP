# -*- coding: UTF-8 -*-
"""The list of route modules, shared by startup.py and the in-Revit self-test."""
import importlib
import logging
import traceback

logger = logging.getLogger(__name__)

# (module, register function). The original modules come first. Each module is
# registered independently so one failing import cannot drop the others.
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
    ("revit_mcp.family_library", "register_family_library_routes"),
]


def register_all(api, secure=True):
    """Register every route module on `api`. Returns {module: error} for failures.

    secure=True wraps the API with the optional RVTSS token check (secure_api);
    the in-Revit self-test calls handlers in-process and passes secure=False.
    """
    errors = {}
    if secure:
        try:
            from .secure_api import secured

            api = secured(api)
        except Exception as e:
            # fail closed: never expose the routes unprotected when the check is broken
            errors["revit_mcp.secure_api"] = "{}: {} - no routes registered".format(type(e).__name__, e)
            logger.error("RVTSS token protection could not be enabled, routes NOT registered: %s", e)
            return errors
    for module_name, func_name in ROUTE_MODULES:
        try:
            module = importlib.import_module(module_name)
            getattr(module, func_name)(api)
        except Exception as e:
            errors[module_name] = "{}: {}".format(type(e).__name__, e)
            logger.error("Failed to register %s: %s\n%s", module_name, str(e), traceback.format_exc())
    return errors
