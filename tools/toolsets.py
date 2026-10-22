# -*- coding: utf-8 -*-
"""Toolsets: register only the tool groups a user needs (RVTSS_TOOLSETS).

    RVTSS_TOOLSETS=core,model,parameters,documentation,qc     # "BIM coordinator"
    RVTSS_TOOLSETS=core,families,parameters                  # "family author"
    (unset / "all")                                           # everything, like v2.0

The proxy also keeps tool listings small: it advertises the first paragraph of
each docstring as the description (the full docstring is served by the
rvtss://docs/tools/{name} resource), marks deprecated tools, and turns off the
SDK's automatic {"result": string} output schema for text tools.
"""
import inspect
import os
import sys

TOOLSETS = {
    "core": ["get_revit_status", "get_session_info", "find_elements", "get_element_details", "revit_selection"],
    "model": ["get_revit_model_info", "get_project_overview", "get_family_inventory", "find_views", "list_sheets",
              "get_schedule_data", "list_links", "get_model_warnings", "get_revit_view"],
    "edit": ["set_parameters", "bulk_update_parameter", "transform_elements", "delete_elements", "create_elements",
             "manage_element_types"],
    "families": ["family_list_templates", "family_create", "family_open", "family_get_info", "family_set_properties",
                 "family_add_parameters", "family_edit_parameters", "family_manage_types",
                 "family_create_reference_planes", "family_create_form", "family_add_dimension",
                 "family_align_geometry", "family_build_parametric_box", "family_nested", "family_flex_test",
                 "family_validate", "family_save", "family_load_into_project", "family_close",
                 "audit_family_library"],
    "parameters": ["list_project_parameters", "shared_parameters", "global_parameters", "audit_parameters",
                   "export_parameters", "import_parameters", "map_parameters", "export_to_excel"],
    "documentation": ["create_view", "view_graphics", "manage_sheets", "create_schedule", "batch_rename",
                      "manage_groups", "manage_assemblies", "color_splash", "clear_colors",
                      "list_category_parameters"],
    "qc": ["run_model_checks", "check_clashes", "model_snapshot", "compare_models", "export_clash_report"],
    "launch": ["list_revit_installations", "launch_revit", "open_document", "close_document", "save_document",
               "sync_with_central"],
    "code": ["execute_revit_code"],
    "legacy": ["list_families", "list_family_categories", "list_revit_views", "get_current_view_elements",
               "get_current_view_info", "list_levels", "place_family"],
}

# deprecated tool -> replacement (shown in the description; kept for one release)
DEPRECATED = {
    "list_families": "get_family_inventory",
    "list_family_categories": "get_family_inventory",
    "list_revit_views": "find_views",
    "get_current_view_elements": "find_elements(view='active')",
    "get_current_view_info": "get_session_info / find_views",
    "list_levels": "get_project_overview(include=['levels'])",
    "place_family": "create_elements(kind='family_instance')",
}

# tools returning structuredContent + outputSchema (mcp 2.x); text everywhere else
STRUCTURED_TOOLS = ("find_elements", "get_element_details", "get_project_overview", "run_model_checks",
                    "audit_parameters", "get_schedule_data")

PROFILES = {
    "all": sorted(TOOLSETS),
    "bim_coordinator": ["core", "model", "parameters", "documentation", "qc"],
    "family_author": ["core", "families", "parameters"],
    "modeler": ["core", "model", "edit", "documentation"],
    "minimal": ["core", "model"],
}

TOOL_TO_SET = dict((tool, name) for name, tools in TOOLSETS.items() for tool in tools)
# full docstrings of registered tools, served as rvtss://docs/tools/{name}
TOOL_DOCS = {}


def enabled_toolsets(value=None):
    """Parse RVTSS_TOOLSETS: comma list of toolsets and/or profile names. Default: all."""
    raw = os.environ.get("RVTSS_TOOLSETS", "") if value is None else value
    names = [n.strip().lower() for n in raw.replace(";", ",").split(",") if n.strip()]
    if not names or "all" in names:
        return set(TOOLSETS)
    out = set()
    for n in names:
        if n in TOOLSETS:
            out.add(n)
        elif n in PROFILES:
            out.update(PROFILES[n])
        else:
            print("RVTSS_TOOLSETS: unknown toolset '%s' ignored (known: %s; profiles: %s)" % (
                n, ", ".join(sorted(TOOLSETS)), ", ".join(sorted(PROFILES))), file=sys.stderr)
    out.add("core")  # status / session tools are always available
    return out


def first_paragraph(doc):
    doc = (doc or "").strip()
    return doc.split("\n\n", 1)[0].replace("\n", " ").strip()


def _supports(fn, name):
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


class ToolsetServer(object):
    """Wraps the MCP server; tool modules register through it unchanged."""

    def __init__(self, server, toolsets=None, structured=None):
        self._server = server
        self.toolsets = enabled_toolsets() if toolsets is None else set(toolsets)
        self.structured = set(structured or ())
        self.registered = []
        self.skipped = []
        self._can_unstructure = _supports(server.tool, "structured_output")

    def tool(self, *args, **kwargs):
        def deco(func):
            name = kwargs.get("name") or func.__name__
            toolset = TOOL_TO_SET.get(name, "core")
            if toolset not in self.toolsets:
                self.skipped.append(name)
                return func
            doc = inspect.getdoc(func) or ""
            TOOL_DOCS[name] = doc
            kw = dict(kwargs)
            desc = kw.get("description") or first_paragraph(doc)
            if name in DEPRECATED:
                desc = "[Deprecated: use %s] %s" % (DEPRECATED[name], desc)
            kw["description"] = desc
            if self._can_unstructure and "structured_output" not in kw and name not in self.structured:
                kw["structured_output"] = False
            self.registered.append(name)
            return self._server.tool(*args, **kw)(func)
        return deco

    def __getattr__(self, name):
        return getattr(self._server, name)
