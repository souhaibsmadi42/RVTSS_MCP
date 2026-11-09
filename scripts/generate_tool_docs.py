# -*- coding: utf-8 -*-
"""Generate docs/TOOLS.md from the live MCP tool registry (python scripts/generate_tool_docs.py)."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main  # noqa: E402
from tools.toolsets import TOOL_DOCS, TOOL_TO_SET, PROFILES  # noqa: E402

GROUPS = [
    ("Session & status", ["rvtss_health", "get_revit_status", "get_session_info", "get_revit_model_info",
                          "list_revit_installations",
                          "launch_revit", "open_document", "close_document", "save_document", "sync_with_central"]),
    ("Model intelligence", ["get_project_overview", "find_elements", "get_element_details", "get_family_inventory",
                            "list_families", "list_family_categories", "list_levels", "list_links",
                            "get_model_warnings", "find_views", "list_revit_views", "get_current_view_info",
                            "get_current_view_elements", "get_revit_view", "list_sheets", "get_schedule_data",
                            "list_category_parameters", "revit_selection", "survey_change_impact",
                            "get_coordinates", "capture_elements"]),
    ("Element editing", ["set_parameters", "bulk_update_parameter", "transform_elements", "delete_elements",
                         "create_elements", "create_stairs", "place_family", "manage_element_types", "batch_execute",
                         "selection_sets", "undo_last_change", "color_splash", "clear_colors"]),
    ("Family creation & editing", ["family_list_templates", "family_create", "family_open", "family_get_info",
                                   "family_set_properties", "family_add_parameters", "family_edit_parameters",
                                   "family_manage_types", "family_create_reference_planes", "family_create_form",
                                   "family_add_dimension", "family_align_geometry", "family_build_parametric_box",
                                   "family_nested", "family_flex_test", "family_validate", "family_save",
                                   "family_load_into_project", "family_close"]),
    ("Parameter management", ["list_project_parameters", "shared_parameters", "global_parameters",
                              "audit_parameters", "export_parameters", "import_parameters", "map_parameters"]),
    ("Documentation", ["create_view", "view_graphics", "manage_view_filters", "manage_sheets", "manage_revisions",
                       "create_schedule", "batch_rename", "manage_groups", "manage_assemblies"]),
    ("Rooms, spaces & areas", ["list_rooms", "get_room_details"]),
    ("Materials", ["list_materials", "material_takeoff", "manage_materials"]),
    ("Annotation", ["find_untagged_elements", "tag_elements", "create_text_notes", "create_detailing",
                    "list_annotation_types"]),
    ("Export", ["list_export_settings", "export_documents"]),
    ("MEP", ["list_mep_systems", "get_mep_connectors", "find_mep_disconnects"]),
    ("Model administration", ["manage_worksets", "purge_unused", "manage_phases", "manage_links"]),
    ("Coordination & QC", ["run_model_checks", "check_clashes", "export_clash_report", "spatial_query",
                           "model_snapshot", "compare_models", "audit_family_library", "export_to_excel"]),
    ("Advanced", ["execute_revit_code"]),
]

ORIGINAL = {"get_revit_status", "get_revit_model_info", "list_levels", "get_revit_view", "list_revit_views",
            "place_family", "list_families", "list_family_categories", "get_current_view_info",
            "get_current_view_elements", "color_splash", "clear_colors", "list_category_parameters",
            "execute_revit_code", "list_revit_installations", "launch_revit", "open_document", "close_document",
            "save_document", "sync_with_central"}


def _schema(tool):
    return getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}


def _ann(tool, camel, snake):
    a = getattr(tool, "annotations", None)
    if a is None:
        return None
    v = getattr(a, camel, None)
    return v if v is not None else getattr(a, snake, None)


def _type(p):
    if "enum" in p:
        return " | ".join("`{}`".format(v) for v in p["enum"])
    if "anyOf" in p:
        return " or ".join(_type(x) for x in p["anyOf"] if x.get("type") != "null")
    if p.get("type") == "array":
        return "list of " + _type(p.get("items", {}))
    if "$ref" in p:
        return p["$ref"].split("/")[-1]
    return p.get("type", "any")


def main_():
    tools = {t.name: t for t in asyncio.run(main.mcp.list_tools())}
    listed = set(n for _g, names in GROUPS for n in names)
    missing = sorted(set(tools) - listed)
    if missing:
        GROUPS.append(("Other", missing))
    lines = ["# RVTSS MCP tool reference", "",
             "Generated from the live tool registry by `scripts/generate_tool_docs.py` - do not edit by hand.", "",
             "{} tools. **Origin**: *retained* = from the original MCP (some improved), *new* = added by RVTSS. "
             "**Mode**: read-only / modifies / destructive (MCP tool annotations).".format(len(tools)), "",
             "Select toolsets with `RVTSS_TOOLSETS` (comma list of toolsets or profiles). Profiles: " +
             "; ".join("`{}` = {}".format(k, ", ".join(v)) for k, v in sorted(PROFILES.items())) + ".", ""]
    for group, names in GROUPS:
        lines += ["## " + group, "", "| Tool | Toolset | Origin | Mode | Purpose |", "|---|---|---|---|---|"]
        for n in names:
            t = tools.get(n)
            if t is None:
                continue
            mode = "destructive" if _ann(t, "destructiveHint", "destructive_hint") else (
                "read-only" if _ann(t, "readOnlyHint", "read_only_hint") else "modifies")
            if _ann(t, "readOnlyHint", "read_only_hint") is None and n in ORIGINAL:
                mode = "-"
            first = (t.description or "").strip().split("\n")[0]
            lines.append("| `{}` | {} | {} | {} | {} |".format(n, TOOL_TO_SET.get(n, "core"),
                                                             "retained" if n in ORIGINAL else "new", mode,
                                                             first.replace("|", "\\|")))
        lines.append("")
    lines += ["## Parameters", ""]
    for group, names in GROUPS:
        for n in names:
            t = tools.get(n)
            if t is None:
                continue
            props = _schema(t).get("properties", {})
            req = set(_schema(t).get("required", []))
            lines += ["### `{}`".format(n), "", "Toolset: `{}`".format(TOOL_TO_SET.get(n, "core")), "",
                      (TOOL_DOCS.get(n) or t.description or "").strip(), ""]
            if props:
                lines += ["| Argument | Type | Required | Default | Description |", "|---|---|---|---|---|"]
                for pname, p in props.items():
                    lines.append("| `{}` | {} | {} | {} | {} |".format(
                        pname, _type(p).replace("|", "\\|"), "yes" if pname in req else "",
                        "`{}`".format(p["default"]) if "default" in p and p["default"] is not None else "",
                        (p.get("description") or "").replace("\n", " ").replace("|", "\\|")))
                lines.append("")
    out = os.path.join(ROOT, "docs", "TOOLS.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote", out, len(tools), "tools")
    write_allowlist(tools)


ALLOW_BEGIN = "<!-- BEGIN READ_ONLY_ALLOWLIST -->"
ALLOW_END = "<!-- END READ_ONLY_ALLOWLIST -->"


def write_allowlist(tools, server_name="RVTSS"):
    """Claude Code permission allow list of every read-only tool, written into README.md between the markers."""
    import json

    names = sorted(n for n, t in tools.items() if _ann(t, "readOnlyHint", "read_only_hint"))
    block = json.dumps({"permissions": {"allow": ["mcp__%s__%s" % (server_name, n) for n in names]}}, indent=2)
    readme = os.path.join(ROOT, "README.md")
    with open(readme, encoding="utf-8") as fh:
        text = fh.read()
    if ALLOW_BEGIN not in text or ALLOW_END not in text:
        print("README.md has no allow-list markers; skipped")
        return
    head, rest = text.split(ALLOW_BEGIN, 1)
    _old, tail = rest.split(ALLOW_END, 1)
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(head + ALLOW_BEGIN + "\n```json\n" + block + "\n```\n" + ALLOW_END + tail)
    print("README.md allow list:", len(names), "read-only tools")


if __name__ == "__main__":
    main_()
