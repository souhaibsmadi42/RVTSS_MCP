# RVTSS upgrade report

RVTSS – created by Suhaib Al Smadi. Upgrade of the existing Revit MCP (pyRevit extension) to version 2.0.0.

## 1. Starting point (audit)

**Source used.** Two uploaded folders from `%APPDATA%\pyRevit\Extensions`:
`revit-mcp-python.extension` and `mcp-server-for-revit-python.extension`. Both were git clones of
[mcp-servers-for-revit/mcp-server-for-revit-python](https://github.com/mcp-servers-for-revit/mcp-server-for-revit-python)
at commit `4e8ec5f`, and their working trees were **byte-identical**. The only local differences from
upstream were CRLF line endings. `pyproject.toml` and `tools/document_tools.py` were truncated in both
archives and were restored from the folder's own git history. That code was committed unchanged as
the baseline (`01dbc06`), and every change since then is a separate commit on top of it.

> Both copies were installed side by side in the pyRevit Extensions folder. Both register the same
> Routes API (`revit_mcp`) on port 48884, so they conflict. Keep only one.

**Architecture (kept).**

* `main.py` – MCP server (FastMCP, stdio / SSE / streamable HTTP), HTTP helpers `revit_get/post/image`.
* `tools/*.py` – MCP tool modules registered through `tools/__init__.py`.
* `startup.py` – pyRevit startup script; creates `routes.API("revit_mcp")` and registers route modules.
* `revit_mcp/*.py` – IronPython route modules executed inside Revit (API context when the handler takes
  `doc`/`uidoc`).
* Revit versions: whatever pyRevit supports (code already handled `ElementId.Value` vs `IntegerValue`).

**Original tools (20, all retained):** `get_revit_status`, `get_revit_model_info`, `list_levels`,
`get_revit_view`, `list_revit_views`, `get_current_view_info`, `get_current_view_elements`,
`place_family`, `list_families`, `list_family_categories`, `color_splash`, `clear_colors`,
`list_category_parameters`, `execute_revit_code`, `list_revit_installations`, `launch_revit`,
`open_document`, `close_document`, `save_document`, `sync_with_central`.

**Gaps.** No element search or editing beyond placing families and running raw code. No family-document
(.rfa) tools, no parameter management, no documentation or QC tools, no dry runs, and no structured
error contract.

**Baseline tests:** 74 unit tests passed with the locked `mcp 1.9.0`. With `mcp 2.x`, which is what
`requirements.txt` and `uv run --with mcp[cli]` install, every test module failed at import.

## 2. Bugs found and fixed

| # | Problem | Effect | Fix |
|---|---|---|---|
| 1 | Code imported `mcp.server.fastmcp`, but `requirements.txt` pinned `mcp==2.2.0`, which removed it | The server crashed on start-up with current SDKs, including the documented `uv run --with mcp[cli]` config | `tools/_compat.py` supports `FastMCP` (1.x) and `MCPServer` (2.x); tested on 1.9.0, 2.2.0 and 2.3.0 |
| 2 | `requirements.txt` pinned `mcp 2.2.0` with `typing-inspection 0.4.0`, which mcp 2.2.0 does not accept | `pip/uv install -r requirements.txt` failed | Regenerated with the resolver; `pyproject.toml` allows `mcp>=1.9,<3` |
| 3 | Non-200 Revit responses were flattened into `"Error: <code> - <raw text>"` | Hints, tracebacks and candidate lists never reached Claude | JSON error bodies are kept as structured responses |
| 4 | `format_response` returned only `message` when a success response had one | Data was dropped, e.g. all elements of a truncated `get_current_view_elements` result | The message is returned with the remaining payload |
| 5 | `model_info`: `DB.WarningType` does not exist; the bare `except` hid the error | Every model with warnings reported **0 warnings** | Uses `FailureSeverity`; errors are logged |
| 6 | `/model_info/` read `revit.doc` without a `doc` argument | Ran outside Revit API context (thread-unsafe) | The handler takes `doc` |
| 7 | `get_view` exported with a fixed prefix and returned the newest PNG in the folder | Could return a stale image from an earlier export | Unique prefix per export; views can also be addressed by id (duplicate names) |
| 8 | `place_family` read coordinates in feet only and could not take a host | `x=3000` meant 3000 ft; doors and windows could not be placed | Optional `unit` and `host_id` (defaults unchanged) |
| 9 | `execute_code` documented a `use_transaction` option that did not exist | Misleading | Real `transaction_mode`: `none` (default), `auto`, `dry_run` |
| 10 | `utils.normalize_string` used the `unicode` builtin | `NameError` on pyRevit's IronPython 3 engine | Fallback added |
| 11 | `startup.py` registered all modules inside one `try` | One failing import silently dropped every later module | Each module registers independently; `/status/` reports `degraded` with the failing modules |
| 12 | Connection and timeout errors gave no guidance | Hard to recover | Messages explain Routes Server, port, modal dialogs and duplicate installs |
| 13 | Tools had no MCP annotations | Claude could not tell read-only tools from destructive ones | All 74 tools are annotated read-only / modifies / destructive |

## 3. Architecture changes

All changes are incremental: same folders, API name, port, transports and Claude configuration.

* **Revit-side core** (`revit_mcp/core.py`). `handle()` gives every new route the same response shape:
  `{"status": "success" | "dry_run" | "preview" | "error", ...}` with `error`, `hint`, `did_you_mean`,
  `traceback`. It also provides:
  * `document` targeting, by title or path, of any open document, including background family
    documents;
  * `run_transaction()`, which collects Revit failures (warnings are dismissed and reported, errors roll
    back) and supports `dry_run` (commit inside a TransactionGroup that is rolled back, so Revit's own
    validation runs);
  * `batch()`: atomic, or per-item SubTransactions;
  * `confirm_gate()` for operations above `RVTSS_CONFIRM_THRESHOLD`;
  * a per-request audit log in `%APPDATA%\RVTSS\logs`.
* **Version shims** (`revit_mcp/compat.py`) for Revit 2021–2026: ElementId construction and value,
  `ParameterType` vs `SpecTypeId`, `BuiltInParameterGroup` vs `GroupTypeId`, the overloads of
  `FamilyManager.AddParameter` / `ExternalDefinitionCreationOptions` / bindings, and `Floor.Create`.
* **Unit safety** (`revit_mcp/params_util.py`). Dimensional parameters need an explicit unit or a
  string with units. Bare numbers are rejected rather than read as feet.
* **Pure logic** (`revit_mcp/pure/`): units, value templates, filters, shared parameter parser, type
  catalogs, template matching, formula analysis, snapshot diff and location matching, QC rules, CSV.
* **MCP side**: shared typed models in `tools/_common.py` (pydantic). Strict enums and limits are
  validated before anything reaches Revit, and long operations get longer timeouts.

## 4. Tools

74 tools: 20 retained (several improved) and 54 new. Full reference with every argument:
[TOOLS.md](TOOLS.md).

**Improved original tools:** `place_family` (unit, host), `get_revit_view` (view id), `get_revit_model_info`
(warnings, API context, units label), `execute_revit_code` (transaction modes), `get_revit_status`
(version, degraded modules), and all error rendering.

**New tools by area**

* Session / model intelligence: `get_session_info`, `get_project_overview`, `find_elements`,
  `get_element_details`, `get_family_inventory`, `find_views`, `list_sheets`, `get_schedule_data`,
  `list_links`, `get_model_warnings`, `revit_selection`.
* Editing: `set_parameters`, `bulk_update_parameter`, `transform_elements`, `delete_elements`,
  `create_elements`, `manage_element_types`.
* Families: `family_list_templates`, `family_create`, `family_open`, `family_get_info`,
  `family_set_properties`, `family_add_parameters`, `family_edit_parameters`, `family_manage_types`,
  `family_create_reference_planes`, `family_create_form`, `family_add_dimension`,
  `family_align_geometry`, `family_build_parametric_box`, `family_nested`, `family_flex_test`,
  `family_validate`, `family_save`, `family_load_into_project`, `family_close`.
* Parameters: `list_project_parameters`, `shared_parameters`, `global_parameters`, `audit_parameters`,
  `export_parameters`, `import_parameters`, `map_parameters`.
* Documentation: `create_view`, `view_graphics`, `manage_sheets`, `create_schedule`, `batch_rename`,
  `manage_groups`, `manage_assemblies`.
* QC: `run_model_checks`, `check_clashes`, `model_snapshot`, `compare_models`.

## 5. Family creation and parameter management

* **Templates.** RVTSS scans Revit's `FamilyTemplatePath` plus configured folders and matches about 50
  kinds (door, window, furniture, casework, generic model and its hosted variants, fixtures,
  equipment, structural, profiles, detail items, tags, title blocks...) by keyword. Missing kinds are
  reported.
* **Documents.** `family_create` uses `Application.NewFamilyDocument` and can save immediately.
  `family_open` opens an .rfa or runs `EditFamily` on a loaded family. Family documents stay open in the
  background and are addressed by title.
* **Geometry.**
  * Reference planes are named, placed at offsets and can have *Is Reference* set.
  * Extrusions, blends, revolutions and sweeps can be solid or void, on the level or any reference
    plane, from rectangles, circles or polygon loops.
  * Voids cut intersecting solids.
  * Detail-level visibility, subcategories, and material / visibility / extrusion-end parameter
    associations are supported.
  * Labelled dimensions, EQ constraints and locks can be added, and faces aligned (and locked) to
    coplanar planes.
* **Parametric box.** One call builds the planes, Width/Depth labels, EQ, a locked extrusion, a Height
  parameter driving the extrusion end and a Material parameter. A ×1.5 / ×0.5 flex check confirms
  that the geometry follows the parameters.
* **Parameters.**
  * Add type or instance parameters of any data type and group, with initial values and formulas.
    Formulas are pre-checked for unknown names, unbalanced brackets and circular references, then
    validated by Revit in the same transaction.
  * Remove parameters; rename them (not shared ones, an API limitation); switch instance/type; make
    them reporting.
  * Replace a family parameter with a shared one (the GUID is preserved); associate element parameters
    and nested-family parameters.
* **Types.** Create, upsert, duplicate, rename and delete; set values per type with units; export and
  import Revit type catalogs (UTF-16, `##LENGTH##MILLIMETERS` headers).
* **Quality.** `family_flex_test` applies each type and each length parameter at +20% inside a
  rolled-back TransactionGroup, reports Revit constraint errors and lists parameters that have no
  geometric effect. `family_validate` checks the category, formulas, unused parameters, missing or
  zero type values, invalid geometry, missing labelled dimensions and warnings.
* **Save and load.** Files are backed up before overwrite. `LoadFamily` uses an `IFamilyLoadOptions`
  that honours the overwrite option, and the result is verified against the family's types.
* **Shared parameters.** Read the file (UTF-16 aware): GUIDs, groups, duplicate GUIDs or names, and
  which are already in the project. Create definitions: existing names are reused, supplied GUIDs are
  honoured and never duplicated, existing GUIDs are never rewritten. Create a file. Bind as instance
  or type to categories (an existing binding is extended with `ReInsert`; a conflicting same-name
  parameter is refused).
* **Other parameter tools.** Global parameters (create, values, formulas, associations); audits
  (missing, empty, rule violations, wrong data type, duplicate definitions, naming pattern); CSV
  export and import (dry run by default); mapping between parameters for BIM-standard migrations.

## 6. Test results (executed in this environment)

| Suite | Result |
|---|---|
| Original unit tests (`tests/unit`, 74) | pass on mcp 1.9.0, 2.2.0, 2.3.0 |
| New pure-logic tests (47) | pass |
| Route registration against pyRevit stubs (12): all 14 modules import, 71 routes register, signatures valid for pyRevit Routes, every tool endpoint has a route, error/confirmation/serialisation envelopes | pass |
| Tool payload / schema / annotation / HTTP-client tests (24) | pass |
| End-to-end stdio (MCP client → `main.py` → fake Routes server), also via `mcp run main.py` | pass |
| **Total offline** | **158 passed, 0 failed**, in three clean environments (`uv.lock` / mcp 1.9.0, `requirements.txt` / mcp 2.2.0, latest mcp 2.3.0) |
| Static checks: pyflakes (new code clean); vermin – Revit-side code compatible with Python 2.7 and 3.4 (IronPython 2.7 / 3.4) | pass |
| `tests/integration` (needs Revit) | **not run** – Revit is not available here |

### Independent code review

The Revit-side code was reviewed separately for Revit API misuse, wrong transaction state,
geometry and IronPython problems. The review confirmed the transaction states for `LoadFamily`,
`SaveAs`, `Close`, `EditFamily` and `NewFamilyDocument`, the `IFamilyLoadOptions` out-parameters,
the reference-plane vectors, the section transform and the version switches.

It found 8 defects and 3 minor ones. All were fixed in commit `641fc95`:

* unit adaptation for angle, area and volume family values;
* flex-test case isolation;
* rename uniqueness scopes;
* `CreateAreaPlan`;
* global-parameter value parsing;
* rotated clash outlines;
* filters applied to explicit ids;
* schedule filter value types;
* elements without a location.

The same day, built-in driving parameters (door and window Width and Height) were restored to the
family tools (`3717528`).

## 7. Verification status

Revit API behaviour cannot be executed outside Revit, so the stubs prove imports, registration and
contracts, not API results. **No Revit operation was executed in a live session in this environment.**

Run these in a test project or test family first, in this order:

1. `get_revit_status` / `get_session_info` – the extension loads, `health: healthy`, nothing in
   `route_modules_failed`.
2. Original tools (regression): `get_revit_model_info` (warning count now non-zero where warnings
   exist), `list_revit_views`, `get_revit_view`, `place_family`, `color_splash`, `execute_revit_code`.
3. Read-only tools: `find_elements`, `get_element_details`, `get_project_overview`, `list_links`,
   `get_model_warnings`, `get_family_inventory`, `find_views`, `list_sheets`, `get_schedule_data`.
4. Editing with `dry_run=true`, then for real: `set_parameters`, `bulk_update_parameter`,
   `transform_elements`, `create_elements`, `delete_elements` (preview, then confirm).
5. Family workflow on a scratch folder: `family_create(kind='generic_model')` →
   `family_build_parametric_box` (check `flex_check.passed`) → `family_manage_types` →
   `family_flex_test` → `family_validate` → `family_save` → `family_load_into_project`.
   Then `family_create_form` with blend, revolution and sweep. **The sweep profile orientation and blend
   top-profile placement are the parts most in need of visual confirmation.**
6. Shared parameters against a **copy** of your shared parameter file: `read_file`,
   `create_definitions`, `bind` (dry run, then real), `audit_parameters`.
7. QC: `run_model_checks`, `check_clashes` (host and link), `model_snapshot` + `compare_models`.

Areas with the most version-specific API surface, worth checking on each Revit version you use:
parameter creation/binding (2021 legacy path vs 2022+ ForgeTypeId), `ElementId` construction (2024+),
`Floor.Create` (2022+), assembly view creation, and type catalog encoding.

## 8. Compatibility and requirements

* Revit 2021–2026 with pyRevit 4.8+ / 5.x (IronPython 2.7 or 3.4 engine); the pyRevit Routes Server
  enabled.
* MCP server: Python 3.11+, `mcp[cli] >=1.9,<3`, `httpx`, `pydantic 2`.
* Claude Desktop / Claude Code configuration unchanged (stdio via `mcp run main.py` or `python main.py`;
  `--sse`, `--streamable-http`, `--combined` still work).

## 9. Configuration changes required

* None for existing installs. Optionally set the environment variables and `%APPDATA%\RVTSS\*.json`
  files listed in the README.
* **Remove the duplicate extension copy** (see section 1).
* After updating the files, reload pyRevit (or restart Revit) so the new route modules load.

## 10. Known limitations

* Hard clashes only (solid intersection); no clearance/soft clashes and no clash grouping.
* Non-shared project parameters are created through shared definitions (the reliable cross-version
  API path). Renaming or removing project parameter bindings and renaming shared parameters are not
  offered: these are Revit API limitations or would destroy data.
* Global-parameter association covers element parameters; labelling project dimensions with globals
  is not implemented.
* Dimension and alignment creation in families assumes axis-aligned reference planes and the template's
  plan and front elevation views.
* `delete_elements` previews by doing a real delete inside a rolled-back transaction group; very large
  sets can take time.
* Snapshots of very large models (100k+ elements) are slow; filter by category.
* Assembly naming needs a second transaction (Revit requirement). If it fails, the assembly exists
  without the requested name.
* pyRevit Routes has no authentication; keep port 48884 bound to localhost.

## 11. Recommended next steps

1. Run the live verification list in section 7 on your Revit version(s) and report any failing tool.
   The structured error, hint and traceback make fixes quick.
2. Fill `%APPDATA%\RVTSS\qc_rules.json` with your company naming standards and required parameters.
3. Point `family_template_dirs` at your office template library.
4. Add integration tests for the new tools to `tests/integration` once a test model is fixed.
5. Possible extensions: clearance clashes with tolerance, family libraries (batch audit of a folder of
   .rfa files), IFC/COBie parameter mapping presets.
