# -*- coding: utf-8 -*-
"""Tool registration system for Revit MCP Server"""


def register_tools(mcp_server, revit_get_func, revit_post_func, revit_image_func, toolsets=None):
    """Register all tools with the MCP server.

    Tools are registered through a ToolsetServer proxy (tools/toolsets.py) that
    honours RVTSS_TOOLSETS and keeps the advertised descriptions short; the
    advertised input schemas are compacted afterwards. Returns the proxy.
    """
    from .toolsets import ToolsetServer, STRUCTURED_TOOLS
    from ._compat import finalize_tools

    server = mcp_server
    mcp_server = ToolsetServer(server, toolsets, structured=STRUCTURED_TOOLS)
    # Import all tool modules
    from .status_tools import register_status_tools
    from .view_tools import register_view_tools
    from .family_tools import register_family_tools
    from .model_tools import register_model_tools
    from .colors_tools import register_colors_tools
    from .code_execution_tools import register_code_execution_tools
    from .launch_tools import register_launch_tools
    from .document_tools import register_document_tools
    # RVTSS modules
    from .element_tools import register_element_tools
    from .project_tools import register_project_tools
    from .family_editor_tools import register_family_editor_tools
    from .parameter_tools import register_parameter_tools
    from .documentation_tools import register_documentation_tools
    from .qc_tools import register_qc_tools
    from .coordination_tools import register_coordination_tools

    # Register tools from each module
    register_status_tools(mcp_server, revit_get_func)
    register_view_tools(mcp_server, revit_get_func, revit_post_func, revit_image_func)
    register_family_tools(mcp_server, revit_get_func, revit_post_func)
    register_model_tools(mcp_server, revit_get_func)
    register_colors_tools(mcp_server, revit_get_func, revit_post_func)
    register_code_execution_tools(
        mcp_server, revit_get_func, revit_post_func, revit_image_func
    )
    register_launch_tools(mcp_server, revit_get_func)
    register_document_tools(mcp_server, revit_get_func, revit_post_func)
    register_element_tools(mcp_server, revit_get_func, revit_post_func)
    register_project_tools(mcp_server, revit_get_func, revit_post_func)
    register_family_editor_tools(mcp_server, revit_get_func, revit_post_func)
    register_parameter_tools(mcp_server, revit_get_func, revit_post_func)
    register_documentation_tools(mcp_server, revit_get_func, revit_post_func)
    register_qc_tools(mcp_server, revit_get_func, revit_post_func)
    register_coordination_tools(mcp_server, revit_get_func, revit_post_func)

    finalize_tools(server)

    from .resources_prompts import register_resources, register_prompts

    register_resources(server, revit_post_func)
    register_prompts(server)
    return mcp_server
