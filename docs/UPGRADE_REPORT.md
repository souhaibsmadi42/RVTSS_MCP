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

---

# v2.1

## Phase 0 – baseline and audit (v2.0.0, commit `405a980`)

| Check | Result |
|---|---|
| Unit tests | 158 passed (mcp 1.9.0 via `uv.lock`, and mcp 2.3.0) |
| pyflakes | 13 messages, all unused imports/variables in upstream files and the compat shim (no errors) |
| vermin `-t=2.7- -t=3.4-` on `revit_mcp/`, `startup.py` | pass |
| `tools/list` payload | **119,369 chars ≈ 29.8k tokens** for 74 tools on mcp 2.3 (107,005 on mcp 1.9). Per-tool sizes: `docs/metrics/tool_payload_v2.0.json` |

**Where the payload goes (mcp 2.3):** 10.4k auto-generated `outputSchema` boilerplate (`{"result": string}`) on text tools, 8.8k property `title`s, ~7k `anyOf [..., null]` wrappers, 4.7k `"default": null`, the rest descriptions. Largest tools: `family_create_form` 4.6k, `find_elements` 4.4k, `bulk_update_parameter` 4.0k, `shared_parameters` 4.0k.

**Overlapping tools**

| Older tool | Covered by | Decision |
|---|---|---|
| `list_families` | `get_family_inventory` (families, types, instance counts) | legacy toolset, deprecated alias |
| `list_family_categories` | `get_family_inventory.families_by_category` | legacy |
| `list_revit_views` | `find_views` (ids, types, templates, sheets) | legacy |
| `get_current_view_elements` | `find_elements(view="active")` | legacy |
| `get_current_view_info` | `get_session_info.active_view` + `find_views` | legacy |
| `list_levels` (feet) | `get_project_overview(include=["levels"])` (mm, ids) | legacy |
| `place_family` | `create_elements(kind="family_instance")` (units, hosts, batch, dry run) | legacy |
| `create_point_based_element` | – (only in the upstream README "Pending" table; never implemented) | README table removed |
| `get_revit_status` / `get_session_info` | complementary: status works without API context (health), session info is detailed | keep both |
| `color_splash` / `view_graphics(override)` | complementary: colouring by parameter value vs explicit overrides | keep both |

Legacy tools keep their exact arguments and behaviour; they only move to the `legacy` toolset and get a deprecation note.

## Phase 1 – live verification harness

* `revit_mcp/pure/selftest.py` – one self-test **plan** (≈35 steps covering the §7 order: status → original
  tools → read-only → editing with dry run then real → family workflow → shared parameters on a scratch
  file → QC) and a runner that produces `rvtss_live_report.json` and a Markdown summary (per step and per
  MCP tool: pass / fail / skip, duration, environment, error + hint + traceback).
  * Model-changing steps run **only** after a copy of `tests/test.rvt` (in `%TEMP%\RVTSS_live`) is open and
    verified as the active document; otherwise they are skipped (unit-tested).
  * The shared-parameter steps use a scratch file and assert it did not become Revit's current file.
  * The family steps measure the generated geometry, so the known risk areas are checked automatically:
    blend top profile (expects 200 × 200 × 300 mm), sweep profile orientation (expects 500 × 50 × 50 mm),
    revolution (400 × 400 × 200 mm), formula evaluation per type, flex of all types, catalog, save, load.
* `tests/live/run_live.py` (+ `tests/live/test_live.py`, marker `live`, skipped when Routes is not
  reachable) – HTTP runner against the real Routes server.
* `RVTSS.tab/Diagnostics.panel/Run Self-Test.pushbutton` – runs the same plan inside Revit. It cannot use
  HTTP (the button runs on Revit's UI thread, where pyRevit Routes executes API requests through an
  ExternalEvent, so a request to itself would wait forever). `revit_mcp/selftest_runtime.py` therefore
  registers the routes on a recorder and calls the handlers directly with the same `doc` / `uidoc` /
  `request` arguments (pyRevit source checked: `routes/server/server.py`, `handler.py`).
* `revit_mcp/registry.py` – the route-module list shared by `startup.py` and the self-test.
* Bug fixed while writing the shared-parameter steps: when Revit had **no** shared parameter file
  configured, `shared_parameters` / `family_add_parameters(shared=true)` with an explicit file left Revit
  pointing at that file (the restore only ran when a previous file existed).
* `get_session_info` now reports pyRevit version, Python engine/version and the Revit-side temp folder.

**Live run: not run – no Revit on this machine** (cloud container without Windows/Revit). Run
`uv run python tests/live/run_live.py` or the *Run Self-Test* button and keep the generated report.

## Phase 2 – security

Verified first in the pyRevit source (`pyrevitlib/pyrevit/routes/server/server.py`, `develop` 2026-10-21):
`_prepare_request` builds the handler's `Request` from path, method, body, route and query parameters only.
**HTTP headers and the client address never reach a route handler**, and the server binds to
`user_config.routes_host`, which is empty – all interfaces – by default.

* **Token** (`RVTSS_TOKEN`, Revit environment or `"token"` in `%APPDATA%\RVTSS\config.json`; off by default):
  every route except `/status/` (and `/ping/`, Phase 5) requires it. Because headers are not forwarded it is
  read from the JSON body (`_rvtss_token`, stripped before the handler runs) or the query string
  (`rvtss_token`); `X-RVTSS-Token` is accepted too for a future pyRevit. `main.py` sends all three from its
  own `RVTSS_TOKEN`. The wrapper (`revit_mcp/secure_api.py`) is generated with the handler's exact argument
  names plus `request`, because pyRevit picks API context and injects arguments by name. Registration
  **fails closed**: if the wrapper cannot load, no route is registered. Constant-time comparison.
* **Code execution**: `RVTSS_ALLOW_CODE_EXECUTION=0` refuses `execute_revit_code` (HTTP 403); allowed by
  default. Every call logs a warning and writes the code to `logs/code-YYYYMMDD.log` (redacted, capped at
  20k chars). New `transaction_mode="read_only"`: `DB.Transaction/SubTransaction/TransactionGroup` are
  blocked in the code's namespace, the code runs inside a TransactionGroup that is always rolled back, and
  `DocumentChanged` is watched – any change is undone and reported (409).
* **Remote access**: a handler cannot see who is calling, so the Revit side cannot refuse remote clients.
  Done instead:
  * `main.py` refuses non-loopback `REVIT_HOST` unless `RVTSS_ALLOW_REMOTE=1`. **Breaking change** for VM
    setups: set `RVTSS_ALLOW_REMOTE=1`.
  * `/status/` and `get_session_info` report `security`: `token_required`, `code_execution_allowed`,
    `routes_host`, `reachable_beyond_loopback`, and warnings when Routes listens beyond loopback without a
    token.
  * The README recommends setting pyRevit Settings → Routes → Host to `127.0.0.1`.
* **Logs**:
  * audit lines and code are passed through `pure/security.redact` (API keys, bearer/JWT tokens,
    `key=value` secrets, long opaque strings; GUIDs kept);
  * lines are capped at 500 chars;
  * `.log` files older than 30 days are deleted;
  * the token is never logged or returned.
* **Bug found:** `code_execution.py` imported `StringIO` from the Python 2 module, so `execute_revit_code`
  failed to import on pyRevit's IronPython 3 engine. It now falls back to `io.StringIO`.

## Phase 3 – smaller tool context

| Measurement (`scripts/measure_tool_payload.py`) | chars | ≈ tokens | vs v2.0 |
|---|---|---|---|
| v2.0 baseline, 74 tools (mcp 2.3) | 119,369 | 29.8k | – |
| v2.1 default (all toolsets, 74 tools; mcp 2.3 **and** 1.9) | **66,600** | 16.7k | **−44.2 %** |
| `RVTSS_TOOLSETS=bim_coordinator` (35 tools) | 33,142 | 8.3k | −72.2 % |
| `RVTSS_TOOLSETS=family_author` (31 tools) | 34,547 | 8.6k | −71.1 % |

Per-tool numbers: `docs/metrics/tool_payload_v2.1_phase3.json`. A unit test keeps the default at or below 60% of
the v2.0 payload.

* **Toolsets** (`tools/toolsets.py`, `RVTSS_TOOLSETS`): `core, model, edit, families, parameters,
  documentation, qc, launch, code, legacy`, plus the profiles `bim_coordinator`, `family_author`, `modeler`,
  `minimal` and `all` (the default). `core` is always on. Tools register through a proxy, so the tool
  modules are unchanged.
* **Consolidation:** the seven overlapping tools from Phase 0 keep their names, arguments and behaviour,
  but move to the `legacy` toolset with a `[Deprecated: use …]` note. They are planned for removal in the
  next release.
* **What was trimmed:**
  * The SDK's automatic `{"result": string}` output schema is turned off for text tools (2.x).
  * Advertised input schemas are compacted after registration: no titles, no `null` branches, no
    `"default": null`. Validation still uses the full pydantic model.
  * `destructiveHint` is dropped on read-only tools, where the spec ignores it.
  * Only the first docstring paragraph is advertised; 36 first paragraphs were rewritten as "what it
    does, when to use it". The full docstrings remain in `TOOL_DOCS`, served as
    `rvtss://docs/tools/{name}` (Phase 4) and in `docs/TOOLS.md`.
  * The repeated `document` hint was shortened, and the 50-value template-kind enum became a validated
    string (Revit lists the valid kinds).
* **Annotations re-checked:**
  * all tools are closed-world (`openWorldHint: false`);
  * read-only tools are idempotent;
  * `set_parameters`, `family_save`, `save_document`, `family_set_properties` and `view_graphics` are now
    marked idempotent;
  * `delete_elements`, `family_close`, `close_document` and `execute_revit_code` remain destructive.

## Phase 4 – more of the MCP protocol

* **Structured output.** On mcp 2.x, these tools return `structuredContent` and advertise an `outputSchema`
  (loose models in `tools/_outputs.py`):
  * `find_elements`, `get_element_details`, `get_project_overview`, `get_schedule_data`,
    `run_model_checks` and `audit_parameters`;
  * the text content is unchanged.

  On mcp 1.9 they return text only, through `structured_return`/`structured_result` in `_compat.py`. The
  default payload is 68,339 chars (−42.7 %).
* **Resources:**
  * `rvtss://session`
  * `rvtss://project/overview`
  * `rvtss://qc_rules`
  * `rvtss://config` (secrets masked)
  * `rvtss://logs/today` (redacted, last 200 lines)
  * `rvtss://docs/toolsets`
  * the template `rvtss://docs/tools/{name}` (full tool docs)

  The files are read by the new Revit route `/rvtss_files/`, which runs without API context and reads only
  `%APPDATA%/RVTSS`.
* **Prompts:**
  * `model_health_check`
  * `create_parametric_family`
  * `shared_parameter_rollout`
  * `naming_audit`
  * `pre_issue_qc`

  Each is a step list with checks between steps.
* **Progress and logging.** Long calls (flex test, clashes, snapshot/compare, parameter import, batch
  rename, the parametric box, every structured tool) run through `call_with_progress`. It sends:
  * `ctx.info` at start and finish;
  * a progress heartbeat every 3 s while Revit works, because Routes cannot stream intermediate progress;
  * a final progress = total.
* **Confirmations.** `delete_elements`, `set_parameters`, `bulk_update_parameter`, `transform_elements`
  and `manage_element_types` use `post_confirmable`. When Revit answers with a `preview` and the client
  declared the `elicitation` capability (mcp 2.x), the user is asked through elicitation:
  * **Accept:** the same call is re-run with `confirm=true`. The Revit-side `confirm_gate`, dry-run and
    unit checks still apply.
  * **Decline/cancel:** nothing changes.
  * **No elicitation support:** the preview is returned exactly as before.
* **Tests:**
  * `tests/unit/test_mcp_features.py` runs a stdio end-to-end check of structured content, resources,
    prompts, and accept/decline/no-elicitation;
  * it also checks the heartbeat timing and the text fallback;
  * the elicitation cases are skipped on 1.9.

## Phase 5 – bridge reliability

* **One pooled `httpx.AsyncClient`** (`main._ClientPool`): at most 8 connections, 4 keep-alive, 10 s
  expiry.
  * It is created on first use, and recreated if the event loop changes or the client was closed.
  * It is closed when the stdio session ends (server lifespan) and when the combined HTTP server stops. In
    stateless HTTP mode the lifespan runs per request, so the pool is deliberately kept open there.
  * Timeouts are still set per call: tool timeouts, `RVTSS_TIMEOUT`, and `RVTSS_IMAGE_TIMEOUT` (default
    60 s).
* **`/ping/`** is a new route without Revit API context. Checked in the pyRevit source
  (`routes/server/server.py`): `ThreadedHttpServer` serves each request on its own thread, and only
  handlers that take `doc`/`uidoc`/`uiapp` wait for Revit's main thread. So `/ping/` answers while Revit
  is blocked. After a client timeout the MCP server pings:
  * if `/ping/` answers, the message is **"Revit is busy"** (modal dialog, edit mode or long operation);
  * if it doesn't, the message is **"Routes not responding"**.

  pyRevit's own host timeout (HTTP 504 `RouteHandlerTimedOutException`, after 30 s without dispatcher
  progress) gets the same "busy" hint. Against a v2.0 Revit extension, a 404 on `/ping/` still counts as
  "Routes alive". The self-test plan now includes `/ping/`.
* **Retries:**
  * A GET is retried exactly once after `RemoteProtocolError`, `ReadError` or `WriteError` (a dropped
    keep-alive connection), using the same request id.
  * Connect errors and timeouts are never retried.
  * A POST is never retried.
* **`revit_image` / `get_revit_view`:**
  * Errors come back in the same envelope as other calls: `{status: "error", error, error_kind, hint,
    request_id, …}`, plus the Revit payload such as `available_views`.
  * Timeout is configurable (`RVTSS_IMAGE_TIMEOUT`).
  * New optional arguments `image_format` (`png` | `jpg`) and `pixel_size` (128–4096, default 1024).
    `ImageFileType.JPEGMedium` was verified in the Revit 2025, 2026 and 2027 API docs.
  * Images above `RVTSS_IMAGE_MAX_KB` (default 4096) are refused with a hint to use jpg or a smaller size.
* **Correlation id.** Every call gets a 12-character id. It is sent as `_rvtss_request_id` (POST body) or
  `rvtss_request_id` (query), because pyRevit drops headers.
  * Revit side: the route wrapper in `secure_api.py` validates it (64 chars max, `[A-Za-z0-9._:-]`, so it
    is safe in log lines) and removes it from the body. It then stores it in a thread-local
    (`core.current_request_id`), writes it to the audit-log column and returns it as `request_id` in every
    response, including 401s and legacy routes.
  * MCP side: the id is added to every dict response and appended to text errors.
* **Behaviour change:** without `RVTSS_TOKEN` the routes are now also wrapped (for request ids). Handler
  argument names are preserved, so pyRevit's API-context detection is unchanged.
* **Tests:** `tests/unit/test_bridge.py` adds 19 tests covering pooling, retry and no-retry cases,
  busy/down diagnosis, the 504 hint, the image envelope and size limit, the pure tracing helpers, the
  `/ping/` route without API context or token, and the request id in the audit log. 214 passed on mcp 2.3
  and 2.2; 212 passed and 2 skipped on 1.9. The payload is 68,494 chars (−42.6 %).

## Phase 6 – BIM coordination features

There are worked examples for every feature in [`docs/COORDINATION.md`](COORDINATION.md), and the new MCP
prompts `clash_coordination` and `bim_standards_audit` chain them. Three tools are new
(`export_clash_report`, `audit_family_library`, `export_to_excel`), for 77 in total. Existing tools gained
only optional arguments.

| # | Feature | Where | Dry run | Pure logic + tests |
|---|---|---|---|---|
| 1 | Clearance clashes (`clearance` in `unit`), `type` hard/clearance + `distance`, level, grid zone (`A-B/1-2`), nearest grid intersection, `group_by` pair / type_pair / level / grid_zone; CSV + HTML report | `qc.clashes`, `pure/clash.py`, `export_clash_report` | `check_clashes(dry_run)`, `export_clash_report(dry_run)` returns the planned files | grid intersections, zones (also reversed and 30°-rotated grids), grouping, rows, HTML escaping, CSV units |
| 2 | Family library audit (open read-only, `Close(False)`, never saved; category, size, parameters, nested, warnings, `family_validate`, naming) | `family_library.py`, `pure/family_library.py`, `audit_family_library` | lists files, sizes, skips | file listing (backups skipped), findings, ISO naming of file names, route dry run on a temp folder |
| 3 | ISO 19650 field-by-field naming for sheets / views / view templates / families / types / worksets | check `iso19650`, `pure/naming.py`, `docs/examples/qc_rules.iso19650.json` | read-only check | structure, allowed values, regex, optional, case, lengths, scheme errors; the example file is validated by a test |
| 4 | View audit: no template, unused templates, empty sheets, views off sheets (dependent excluded), duplicate names, unused scope boxes | check `view_audit`, `pure/view_audit.py` | read-only check | every finding |
| 5 | `.xlsx` export: one sheet per category, units in headers, schedules paged by 2000, summary sheet, formula-injection guard | `tools/excel_export.py`, `export_to_excel`; `/parameters/export/` gained `format="json"` and `column_units` | returns the sheets and row counts without writing | sheet titles (31 chars, invalid characters, unique), headers, round-trip through openpyxl, tool end-to-end with paging |
| 6 | IFC / COBie presets for `map_parameters` (`preset=`), office presets in `%APPDATA%/RVTSS/presets/*.json` | `pure/mapping_presets.py`, `parameters.map_values` | existing dry_run / confirm gate | preset shape, office override, copies, category filter, Revit-side errors |
| 7 | Global parameters on dimensions: `label_dimensions` / `unlabel_dimensions`, labelled dimensions in `list` | `parameters.global_parameters` | existing dry_run (transaction rolled back) | Revit-only API (no pure logic); covered by the self-test |

* **API checks:**
  * `GlobalParameter.CanLabelDimension`, `LabelDimension`, `UnlabelDimension`, `GetLabeledDimensions` and
    `ImageFileType.JPEGMedium` are confirmed in the Revit API reference.
  * `Face.Project`, `Curve.Project`, `Face.IsInside`, `Face.Evaluate`, `ElementFilter.PassesFilter`,
    `Application.OpenDocumentFile` and `Document.Close(bool)` are long-standing APIs.
  * `BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP` / `DATUM_VOLUME_OF_INTEREST` could **not** be found in
    the online docs reachable from this machine. They are looked up with `getattr` and the audit reports when
    they are missing.
  * COBie / IFC target names: confirmed names are marked `verified: true`; the rest are reported as
    `unverified_targets`.
* **Bugs found while testing:**
  * Grid zones were reversed (`B-A`) for grids drawn along +Y. The zone normal is now oriented towards +X/+Y.
  * A mixed preset (`ifc_overrides`) without a selection would have selected Rooms only. It now requires an
    explicit selection unless every mapping is category-limited.
  * The `validate` argument shadowed a pydantic attribute on mcp 1.9; it is renamed to `run_validation`.
* **Self-test:** four new `qc` steps (clearance clashes + grouping, iso19650 + view audit, library audit on
  the scratch folder, preset dry run + JSON export with units).
* **Dependencies:** `openpyxl>=3.1` (MCP side) was added to `pyproject.toml`, `uv.lock` and
  `requirements.txt`.
* **Payload:** 71,202 chars on mcp 2.3 (−40.4 %) and 69,911 on 1.9, with 3 more tools. The schema
  compaction now also drops `"additionalProperties": true`, the JSON Schema default. Numbers are in
  `docs/metrics/tool_payload_v2.1_phase6.json`.
* **Tests:** `tests/unit/test_coordination.py` (31 tests). The suites give 245 passed on mcp 2.3 and 2.2,
  and 243 passed + 2 skipped on 1.9. vermin is clean; pyflakes has no new warnings (20 pre-existing ones
  are cleaned up in Phase 7).

## Phase 7 – tooling and docs

* **CI.** `.github/workflows/ci.yml` runs on every push and pull request, on Python 3.11, 3.12 and 3.13 ×
  mcp 1.9.x and the latest 2.x. Each cell runs:
  * the unit tests;
  * `pyflakes tools main.py revit_mcp tests scripts startup.py` (clean: the 20 old warnings were removed);
  * `vermin -t=2.7- -t=3.4- --violations` on `revit_mcp/`, `startup.py` and the pushbuttons;
  * the `docs/TOOLS.md` freshness check (the generated file is identical on both SDK majors).

  The 3.11/1.9 and 3.13/2.x cells were reproduced locally in fresh virtual environments, which exposed the
  issue below.
* **Issue found: mcp 1.9.x + pydantic 2.14.** mcp 1.9 imports `pydantic._internal._typing_extra.
  eval_type_backport`, which pydantic 2.14 removed, so `import mcp` fails. pydantic 2.13.5 works. The CI cell
  for 1.9 pins `pydantic<2.14`, and the CHANGELOG says so. Default installs resolve to mcp 2.x and are not
  affected.
* **README** rewritten:
  * quick start;
  * toolsets and profiles, with measured tool counts;
  * security (token, code-execution gate, remote hosts, Routes host);
  * self-test and live runs;
  * the full configuration table and the coordination features.

  The upstream documentation moved to `docs/UPSTREAM.md`; its outdated "Current Implementation Status" /
  *Pending* table was removed and replaced by a pointer to `docs/TOOLS.md`.
* **`LLM.txt`** conventions updated:
  * `registry.py`;
  * the secure wrapper (token and request id);
  * self-test steps;
  * toolsets and the payload budget;
  * `post_structured`, `call_with_progress` and `post_confirmable`;
  * prompts;
  * pydantic-shadowing argument names.
* **Naming and versions:**
  * Python package `rvtss-mcp` (`pyproject.toml`, `uv.lock`, `requirements.txt`).
  * Extension display name `RVTSS` (`extension.json`). The install folder, API name `revit_mcp` and port
    are unchanged.
  * `RVTSS_VERSION = "2.1.0"`, package version 2.1.0.
  * Revit 2027 added to the supported range (`compat.py` docstring, README) based on the 2027 API reference
    and pyRevit's 2027 runtime. No new shim was needed.
* **Examples:** `examples/claude_desktop_config.json` now uses `uv run --project <extension> python main.py`,
  so the project's dependencies (`openpyxl`) are installed. It sets the `bim_coordinator` profile.
* `CHANGELOG.md` added.

## v2.1 summary

### Definition of done

| Item | Status |
|---|---|
| All phases committed | yes: one commit per phase on `claude/wizardly-goldberg-v7awiu` |
| Unit suite green | 245 passed (mcp 2.3, 2.2, latest 2.x on py3.13); 243 passed + 2 skipped (mcp 1.9, py3.11 and py3.13) |
| vermin / pyflakes | clean |
| Default tool payload ≥ 40 % smaller | 119,369 → **71,202** chars (−40.4 %) with 77 tools instead of 74. `bim_coordinator`: 37,173 (−68.9 %) |
| `tests/live` report | **not run – no Revit on this machine** (cloud container, Linux) |

### Bugs found and fixed in v2.1

1. `SharedParametersFilename` was not restored when Revit previously had no shared parameter file
   (`parameters._SharedFile`, `families._shared_definition`).
2. Clash grid zones were reversed for grids drawn along +Y.
3. A mixed mapping preset without a selection would have mapped Rooms only.
4. The tool argument `validate` shadowed a pydantic attribute on mcp 1.9 (now `run_validation`).
5. The proxy forced `structured_output=False` on every tool, so the structured tools had no
   `outputSchema` (found while building Phase 4).
6. Installation issue: mcp 1.9.x does not work with pydantic ≥ 2.14 (documented, and pinned in CI).

### Verified here vs. needs Revit

| Verified in this environment | Needs a live Revit session (self-test button) |
|---|---|
| Revit-side modules import and register against pyRevit stubs; every tool endpoint has a route; every self-test endpoint exists | Every Revit API call: transactions, geometry, family editing, view export, clash geometry |
| Token check, request ids, redaction, log rotation, `read_only` code mode (stubbed transaction classes) | `/ping/` answering while a modal dialog is open (pyRevit's threaded server was checked in its source) |
| MCP side end-to-end over stdio against a fake Routes server: structured content, resources, prompts, elicitation accept/decline, progress | Clearance distances on real solids, grid zones on a real model, the family library audit opening real `.rfa` files |
| Pure logic: clash zones and grouping, ISO 19650, view audit, presets, library findings, Excel workbook | `GlobalParameter.LabelDimension` on project dimensions; the scope-box BuiltInParameters |
| CI matrix cells reproduced locally | Revit 2027 |

### Manual steps for the user

1. **One extension copy.** Remove or disable the duplicate copy (`revit-mcp-python.extension` /
   `mcp-server-for-revit-python.extension`), so that only `RVTSS.extension` registers `revit_mcp`.
2. Pull this branch into the extension folder and **reload pyRevit**.
3. pyRevit Settings → Routes: set the host to **127.0.0.1** (unless Revit runs in a VM).
4. **Optional token:** set `RVTSS_TOKEN` in the Revit environment (or `"token"` in
   `%APPDATA%\RVTSS\config.json`) **and** in the MCP server `env` in the Claude config.
5. **VM setups:** add `RVTSS_ALLOW_REMOTE=1` to the MCP server `env`.
6. **Optional:** `RVTSS_ALLOW_CODE_EXECUTION=0` to disable `execute_revit_code`; `RVTSS_TOOLSETS=bim_coordinator`
   for a lighter tool list.
7. **Update dependencies** with `uv sync` (new: `openpyxl`) and update the Claude Desktop config (see
   `examples/claude_desktop_config.json`).
8. Copy `docs/examples/qc_rules.iso19650.json` to `%APPDATA%\RVTSS\qc_rules.json` and put in your BEP
   codes.
9. **Run Diagnostics → Run Self-Test** in Revit and keep `rvtss_live_report.md` / `.json` (they are written
   to `%TEMP%\RVTSS_live`).

# v2.2

## Source and approach

[bimwright/rvt-mcp](https://github.com/bimwright/rvt-mcp) (Apache-2.0, C#/.NET, ~100k lines, 237 tools)
was read in full and compared with RVTSS 2.1 tool by tool. RVTSS already covered families, parameters,
documentation basics, clashes and QC better than rvt-mcp (rvt-mcp has no family editor). The gaps worth
closing were picked by value for BIM work and re-implemented for pyRevit / IronPython; no code was copied
(see `NOTICE`).

| rvt-mcp idea | RVTSS 2.2 |
|---|---|
| `batch_execute` in one TransactionGroup | `batch_execute` (payload capture through the real tools, allow lists on both sides, same-document rule) |
| `--read-only` + generated allow list | `RVTSS_READ_ONLY` (MCP and Revit side) + README allow list from annotations |
| `INVALID_ARGUMENT` with `did_you_mean` | argument guard on the tool manager (unknown keys refused, not ignored) |
| response guard / spill | response budget with summaries that keep status and scalars |
| `revit_health` | `rvtss_health` |
| `revit_survey_change_impact` | `survey_change_impact` (found / none / not_checked per group) |
| getting_started / change / pre-issue prompts | `getting_started`, `safe_change`, `issue_sheets`, `room_documentation`, `mep_connectivity_review` |
| rooms, materials, annotation, export, MEP, graphics, sheets, links, geometry toolsets | 21 tools in `rooms`, `materials`, `annotation`, `export`, `mep`, `admin`, plus `model` / `documentation` / `qc` additions |

Not ported: ToolBaker (runtime C# compilation), toasts and ribbon UI, multi-instance targeting (pyRevit
Routes binds one Revit per port), MEP/structural element creation (`create_elements` and
`execute_revit_code` cover it), persistent change history (the audit log and `model_snapshot` /
`compare_models` cover most of it).

## Verified here

* 304 unit tests on Python 3.13 with MCP SDK 2.3 (302 + 2 skipped on 1.9): guards, batch payload capture, read-only
  registration, every new tool's payload, the Revit-side batch transaction group (assimilate / roll back /
  continue_on_error / dry run / preview / allow list) against stubs, Revit-side read-only refusals, input
  validation of every new route, pure helpers (spatial status, finish areas, export names, filter rules).
* All 21 new routes register under the pyRevit stubs; every tool endpoint has a route.
* pyflakes clean; vermin confirms IronPython 2.7 / 3.4 compatibility of the Revit side.
* `docs/TOOLS.md` and the README allow list are generated identically on both SDK majors.

## Needs a live Revit run

The Revit API calls of the new modules (`spaces`, `materials`, `annotation`, `exporting`, `mep`,
`model_admin`, `impact`, `spatial`, `graphics`, `batch`) were written against the Revit 2021–2027 API
reference with version fallbacks, but have not run inside Revit yet. Run **Diagnostics → Run Self-Test**:
group `v22` exercises them read-only or with dry runs, exports only a file plan, previews the purge and
checks that a failing batch rolls back. Areas most likely to need adjustment: PDF export options on 2022,
`IndependentTag.Create` overloads on 2021, filter-rule factories before 2023, IFC export inside a rolled-back
transaction, `GetUnusedElements` (2024+).
