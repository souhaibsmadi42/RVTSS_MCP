# -*- coding: utf-8 -*-
"""MCP resources (read-only context) and prompts (reusable RVTSS workflows)."""
import json

from .toolsets import TOOL_DOCS, TOOLSETS, PROFILES, DEPRECATED

RESOURCES = {
    "rvtss://session": "Revit session: versions, active document/view, open documents, security status",
    "rvtss://project/overview": "Project information, units, levels, grids, phases, worksets, design options",
    "rvtss://qc_rules": "QC rules (%APPDATA%/RVTSS/qc_rules.json on the Revit machine)",
    "rvtss://config": "RVTSS config (%APPDATA%/RVTSS/config.json, secrets masked)",
    "rvtss://logs/today": "Today's RVTSS audit log (last 200 lines, secrets masked)",
    "rvtss://docs/toolsets": "Toolsets, profiles and deprecated tools",
}


def _dump(data):
    return json.dumps(data, indent=1, ensure_ascii=False, default=str)


def register_resources(mcp, revit_post):
    async def _call(endpoint, data=None, timeout=30.0):
        res = await revit_post(endpoint, data or {}, None, timeout=timeout)
        return _dump(res if isinstance(res, dict) else {"status": "error", "error": str(res)})

    @mcp.resource("rvtss://session", name="session", description=RESOURCES["rvtss://session"],
                  mime_type="application/json")
    async def session_resource() -> str:
        return await _call("/session_info/")

    @mcp.resource("rvtss://project/overview", name="project_overview",
                  description=RESOURCES["rvtss://project/overview"], mime_type="application/json")
    async def project_overview_resource() -> str:
        return await _call("/project_overview/")

    @mcp.resource("rvtss://qc_rules", name="qc_rules", description=RESOURCES["rvtss://qc_rules"],
                  mime_type="application/json")
    async def qc_rules_resource() -> str:
        return await _call("/rvtss_files/", {"kind": "qc_rules"})

    @mcp.resource("rvtss://config", name="config", description=RESOURCES["rvtss://config"],
                  mime_type="application/json")
    async def config_resource() -> str:
        return await _call("/rvtss_files/", {"kind": "config"})

    @mcp.resource("rvtss://logs/today", name="log_today", description=RESOURCES["rvtss://logs/today"],
                  mime_type="application/json")
    async def log_resource() -> str:
        return await _call("/rvtss_files/", {"kind": "log_today", "max_lines": 200})

    @mcp.resource("rvtss://docs/toolsets", name="toolsets", description=RESOURCES["rvtss://docs/toolsets"],
                  mime_type="application/json")
    async def toolsets_resource() -> str:
        return _dump({"toolsets": TOOLSETS, "profiles": PROFILES, "deprecated": DEPRECATED,
                      "how": "Set RVTSS_TOOLSETS=<toolsets or profiles, comma separated> for the MCP server."})

    @mcp.resource("rvtss://docs/tools/{name}", name="tool_docs",
                  description="Full documentation of one RVTSS tool (examples, rules, limits)",
                  mime_type="text/markdown")
    async def tool_docs_resource(name: str) -> str:
        doc = TOOL_DOCS.get(name)
        if doc is None:
            return "Unknown or disabled tool '%s'. Registered: %s" % (name, ", ".join(sorted(TOOL_DOCS)))
        return "# %s\n\n%s\n" % (name, doc)


PROMPTS = {}


def _prompt(name, description):
    def deco(fn):
        PROMPTS[name] = {"description": description, "fn": fn}
        return fn
    return deco


@_prompt("model_health_check", "Model health check: status, warnings, QC checks, links, a prioritised fix list")
def model_health_check(scope: str = "whole model") -> str:
    return f"""Run an RVTSS model health check for: {scope}.

1. get_session_info - confirm the right project is active (stop and ask if not).
2. get_revit_model_info and get_project_overview - summarise size, levels, phases, worksets.
3. get_model_warnings(limit=20) - group the most frequent warnings.
4. run_model_checks() - all checks; then list_links - unloaded / unpinned links.
5. Check between steps: never modify anything in this workflow (read-only tools only).
6. Report: a table of findings by severity (critical/error/warning/info) with counts, element ids
   (first 10) and the recommended fix, then the top 5 actions in priority order."""


@_prompt("create_parametric_family", "Create a parametric family from a description, flex it, validate, save and load")
def create_parametric_family(description: str, category: str = "Furniture",
                             save_folder: str = "C:/RVTSS/Families") -> str:
    return f"""Create a parametric Revit family: {description} (category {category}).

1. family_list_templates(kind=...) - pick the template; stop if it is missing.
2. family_create(kind, save_path="{save_folder}/<Name>.rfa", category="{category}").
3. Geometry: for box-like objects family_build_parametric_box(width, depth, height) - check flex_check.passed.
   Otherwise family_create_reference_planes -> family_create_form -> family_add_dimension(label=...)
   -> family_align_geometry.
4. family_add_parameters - extra parameters (instance vs type deliberately; units with every value;
   formulas like 'Width - 2 * Frame Thickness').
5. family_manage_types(action='create') - the requested sizes.
6. family_flex_test - every type must pass; investigate parameters_without_geometric_effect.
7. family_validate(expected_category="{category}") - fix every error before continuing.
8. family_save, then family_load_into_project (verified must be true).
Between steps: read each tool result; if status is not success, fix the cause before the next step."""


@_prompt("shared_parameter_rollout", "Roll out shared parameters to categories safely (dry run, bind, audit)")
def shared_parameter_rollout(parameters: str, categories: str, shared_parameter_file: str = "") -> str:
    spf = f', shared_parameter_file="{shared_parameter_file}"' if shared_parameter_file else ""
    return f"""Roll out shared parameters [{parameters}] to categories [{categories}].

1. shared_parameters(action="read_file"{spf}) - reuse existing definitions and GUIDs; report duplicates.
2. list_project_parameters - check for same-named parameters that would conflict.
3. shared_parameters(action="create_definitions"{spf}) only for names that do not exist yet.
4. For each parameter: shared_parameters(action="bind", ..., dry_run=true), show the result, then run it
   without dry_run.
5. audit_parameters(categories=[...], required=[...]) - report missing/empty counts.
Never replace an existing GUID; never bind a parameter whose name already exists with another GUID."""


@_prompt("naming_audit", "Sheet and view naming audit against qc_rules / ISO 19650 rules, with a rename plan")
def naming_audit(standard: str = "qc_rules.json") -> str:
    return f"""Audit sheet, view and family naming against {standard}.

1. Read rvtss://qc_rules (naming / iso19650 sections). If empty, ask for the pattern before continuing.
2. run_model_checks(checks=["naming", "iso19650", "view_audit"]) - list violations per target.
3. find_views / list_sheets - show examples of non-compliant names.
4. Propose renames with batch_rename(dry_run=true) per target; show collisions.
5. Only after the user approves: batch_rename(..., dry_run=false, confirm=true)."""


@_prompt("pre_issue_qc", "Prepare model for issue: pre-submission QC with a pass/fail checklist")
def pre_issue_qc(issue_name: str = "next issue") -> str:
    return f"""Pre-submission QC for {issue_name}.

1. get_session_info - correct model, worksharing state.
2. run_model_checks() - must have no critical/error findings (list them otherwise).
3. list_sheets - every sheet has views and a title block; required sheet parameters filled
   (run_model_checks(checks=["sheets"], sheet_parameters=[...])).
4. find_views(on_sheet=false) - working views to delete or place; view_audit for templates.
5. audit_parameters on Doors/Windows/Rooms for the project's required parameters.
6. model_snapshot(name="{issue_name}") - baseline for change detection after the issue.
Report a checklist (pass/fail per item) and the blocking items first."""


def register_prompts(mcp):
    for name, info in PROMPTS.items():
        mcp.prompt(name=name, description=info["description"])(info["fn"])
