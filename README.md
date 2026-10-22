# RVTSS — Revit MCP for Claude

**RVTSS** (created by **Suhaib Al Smadi**) lets Claude inspect and edit live Autodesk Revit models through
pyRevit:
* it creates and edits real family documents (`.rfa`);
* it manages instance, type, family, shared, project and global parameters;
* it automates documentation;
* it runs BIM coordination and quality-control checks: clearance clashes, ISO 19650 naming, view audits,
  family library audits, and Excel and IFC/COBie exports.

It is an upgrade of [mcp-server-for-revit-python](https://github.com/mcp-servers-for-revit/mcp-server-for-revit-python)
and keeps its API name (`revit_mcp`), port (48884), installation method and all 20 original tools.
**v2.1.0** has 77 tools in 10 toolsets, plus MCP resources and prompts.

| | |
|---|---|
| Tool reference (generated) | [docs/TOOLS.md](docs/TOOLS.md) |
| Coordination features with examples | [docs/COORDINATION.md](docs/COORDINATION.md) |
| What changed, verification status | [CHANGELOG.md](CHANGELOG.md) · [docs/UPGRADE_REPORT.md](docs/UPGRADE_REPORT.md) |
| Original upstream documentation | [docs/UPSTREAM.md](docs/UPSTREAM.md) |

## Quick start

1. **Install the extension** (one copy only, see [Installation](#installation)):
   ```powershell
   cd "$env:APPDATA\pyRevit\Extensions"
   git clone https://github.com/souhaibsmadi42/RVTSS_MCP RVTSS.extension
   ```
2. **Turn on Routes.** In pyRevit Settings → Routes, enable **Routes Server**, set the host to
   `127.0.0.1`, then reload pyRevit.
3. **Check the server.** Open `http://127.0.0.1:48884/revit_mcp/status/`. It should show `"health":
   "healthy"` and `"rvtss_version": "2.1.0"`.
4. **Run the self-test.** On the RVTSS tab, click **Diagnostics → Run Self-Test**. It works on a copy of
   the bundled test model and opens a pass/fail report.
5. **Connect Claude.** Claude Desktop → Settings → Developer → Edit Config:
   ```json
   {
     "mcpServers": {
       "RVTSS Revit": {
         "command": "uv",
         "args": ["run", "--project", "C:\\path\\to\\RVTSS.extension", "python", "C:\\path\\to\\RVTSS.extension\\main.py"],
         "env": {"RVTSS_TOOLSETS": "bim_coordinator"}
       }
     }
   }
   ```
   For Claude Code: `claude mcp add -s user RVTSS -- uv run --project C:\path\to\RVTSS.extension python C:\path\to\RVTSS.extension\main.py`

## How it works

```
Claude (Desktop / Code)
   │  MCP (stdio or HTTP): tools, resources, prompts
   ▼
main.py + tools/          MCP server (Python 3.11+, mcp 1.9 – 2.x), one pooled HTTP client
   │  HTTP JSON  http://127.0.0.1:48884/revit_mcp/...   (+ optional RVTSS token, request id)
   ▼
startup.py + revit_mcp/   pyRevit Routes inside Revit (IronPython 2.7 / 3.4)
   │  Revit API, executed in API context, inside transactions
   ▼
Autodesk Revit 2021 – 2027
```

* `revit_mcp/core.py` handles:
  * request parsing and document targeting (`document` = title or path);
  * structured errors with hints;
  * transactions that collect Revit failures;
  * true dry runs (a commit inside a rolled-back TransactionGroup);
  * confirmation gates and the redacted audit log.
* `revit_mcp/compat.py` covers Revit version differences (ElementId Int32/Int64, ForgeTypeId specs, group
  ids...).
* `revit_mcp/pure/` holds the Revit-independent logic, all of it unit-tested: units, filters, formulas,
  shared parameter files, QC rules, clash zones, ISO 19650 naming, presets, security and the self-test plan.

## Installation

1. **Keep only one copy of the extension.** Two copies both register the `revit_mcp` API and conflict, for
   example `revit-mcp-python.extension` and `mcp-server-for-revit-python.extension` in
   `%APPDATA%\pyRevit\Extensions`. Remove or disable the old one.
2. Clone this repository into the pyRevit extensions folder as a folder ending in `.extension` (see the
   quick start). You can instead add its parent folder under pyRevit Settings → Custom Extension Directories.
   The extension shows up as **RVTSS** (tab `RVTSS`).
3. pyRevit Settings → Routes: enable the Routes Server on port 48884, set the host to `127.0.0.1` unless
   Revit runs in a VM, then reload pyRevit.
4. Install the MCP server dependencies (Python 3.11+). The package is `rvtss-mcp`:
   ```powershell
   uv sync                          # uses uv.lock
   uv pip install -r requirements.txt
   ```

## Toolsets and profiles

Every tool on every turn costs context. Load only what you need with `RVTSS_TOOLSETS`, a comma-separated
list of toolsets and/or profiles, in the MCP server's environment. The default is `all`. `core` is always
loaded.

| Profile | Toolsets | Tools |
|---|---|---|
| `all` (default) | everything | 77 |
| `bim_coordinator` | core, model, parameters, documentation, qc | 37 |
| `family_author` | core, families, parameters | 33 |
| `modeler` | core, model, edit, documentation | 30 |
| `minimal` | core, model | 14 |

**Toolsets:**
* `core`: status, session, `find_elements`, element details, selection
* `model`: overview, families, views, sheets, schedules, links, warnings, view image
* `edit`: set and bulk parameters, transform, delete, create, types
* `families`: the full `.rfa` workflow and the library audit
* `parameters`: shared, project and global parameters, audit, CSV/Excel export, mapping presets
* `documentation`: views, sheets, schedules, renames, groups, colours
* `qc`: model checks, clashes, clash report, snapshots
* `launch`: start Revit, open, save and sync documents
* `code`: `execute_revit_code`
* `legacy`: seven original tools superseded by newer ones, kept as deprecated aliases for one release

In the default profile the tool list is about 71k characters. That is **40 % less** than v2.0, even with
three more tools. With `bim_coordinator` it is roughly a third of v2.0.

Long tool documentation is not sent on every turn; it lives in the MCP resource
`rvtss://docs/tools/{name}`.

**Other resources:**
* `rvtss://session`
* `rvtss://project/overview`
* `rvtss://qc_rules`
* `rvtss://config`
* `rvtss://logs/today`
* `rvtss://docs/toolsets`

**Prompts:**
* `model_health_check`
* `create_parametric_family`
* `shared_parameter_rollout`
* `naming_audit`
* `pre_issue_qc`
* `clash_coordination`
* `bim_standards_audit`

## Security

pyRevit Routes has no authentication of its own: anything that can reach port 48884 can drive Revit.

| Setting | Where | Effect |
|---|---|---|
| pyRevit Routes host = `127.0.0.1` | pyRevit Settings → Routes | **Recommended.** If it is empty (all interfaces), `/status/` shows a warning. |
| `RVTSS_TOKEN` | Revit environment **and** MCP server environment (or `"token"` in `%APPDATA%\RVTSS\config.json`) | Every route except `/status/` and `/ping/` requires the same token. pyRevit does not pass HTTP headers to handlers, so the token travels in the JSON body or query string. Off by default. |
| `RVTSS_ALLOW_CODE_EXECUTION=0` | Revit environment / config | Disables `execute_revit_code`. It is allowed by default for backward compatibility. Every call is logged with its full code (redacted) in `%APPDATA%\RVTSS\logs\code-*.log`. `transaction_mode="read_only"` refuses code that opens a transaction. |
| `RVTSS_ALLOW_REMOTE=1` | MCP server environment | Needed when `REVIT_HOST` is not loopback (Revit in a VM). Without it the MCP server refuses to send commands to a remote host. |

The audit log (`%APPDATA%\RVTSS\logs`):
* redacts values that look like secrets;
* caps each line at 500 characters;
* deletes files older than 30 days;
* records the request id that each response returns as `request_id`.

## Self-test and live verification

* **In Revit, no terminal needed:** RVTSS tab → **Diagnostics → Run Self-Test**. It copies `tests/test.rvt`
  to `%TEMP%\RVTSS_live`, runs every group (status, original tools, read-only, editing with dry run then
  real, family workflow, parameters on a scratch shared parameter file, QC and coordination), and writes
  `rvtss_live_report.json` and `.md`. Your own shared parameter file is never touched.
* **From a terminal**, against the running Routes server:
  ```powershell
  uv run --extra test python tests/live/run_live.py --out rvtss_live_report    # add --token if RVTSS_TOKEN is set
  uv run --extra test pytest -m live tests/live                                # skipped when Routes is not reachable
  ```

## Configuration

| Setting | Where | Default |
|---|---|---|
| `REVIT_HOST`, `REVIT_PORT`, `REVIT_API_NAME` | MCP server env | `127.0.0.1`, `48884`, `revit_mcp` |
| `RVTSS_TOOLSETS` | MCP server env: toolsets and/or profiles | `all` |
| `RVTSS_TIMEOUT` / `RVTSS_IMAGE_TIMEOUT` | MCP server env, seconds (long tools set their own) | `30` / `60` |
| `RVTSS_IMAGE_MAX_KB` | MCP server env: larger view images are refused with a hint | `4096` |
| `RVTSS_REPORT_DIR` | MCP server env: clash reports and Excel files | `~/Documents/RVTSS/reports` |
| `RVTSS_LOG_LEVEL` | MCP server env (stderr) | `WARNING` |
| `RVTSS_CONFIRM_THRESHOLD` | **Revit** env: elements above which `confirm=true` is required | `100` |
| `%APPDATA%\RVTSS\config.json` | token, code-execution flag, `family_template_dirs`, `naming.parameters.pattern` | optional |
| `%APPDATA%\RVTSS\qc_rules.json` | naming, **iso19650** scheme, required parameters, view-audit options ([example](docs/examples/qc_rules.iso19650.json)) | optional |
| `%APPDATA%\RVTSS\presets\*.json` | office parameter-mapping presets for `map_parameters` | optional |
| `%APPDATA%\RVTSS\logs`, `backups`, `snapshots` | audit logs, `.rfa` backups, model snapshots | created |

## What Claude can do

* **Model intelligence:**
  * `get_session_info`, `get_project_overview`
  * `find_elements` (filters with units, pagination, structured output)
  * `get_element_details`, `get_family_inventory`
  * `find_views`, `list_sheets`, `get_schedule_data`
  * `list_links`, `get_model_warnings`
* **Editing:**
  * `set_parameters`, `bulk_update_parameter` (numbering templates)
  * `transform_elements`, `create_elements`, `manage_element_types`
  * `delete_elements` (previews dependent elements)

  Destructive previews are confirmed through MCP elicitation where the client supports it.
* **Families (`.rfa`)**, in this order:
  1. `family_list_templates`, then `family_create` or `family_open`
  2. `family_add_parameters`
  3. `family_build_parametric_box`, or `family_create_form` with `family_add_dimension`
  4. `family_manage_types`
  5. `family_flex_test`
  6. `family_validate`
  7. `family_save`
  8. `family_load_into_project`

  Library-wide: `audit_family_library`.
* **Parameters:**
  * `shared_parameters`, `list_project_parameters`
  * `global_parameters` (including labelling project dimensions)
  * `audit_parameters`
  * `export_parameters` / `import_parameters` (CSV), `export_to_excel` (`.xlsx`)
  * `map_parameters` (including IFC/COBie presets)
* **Documentation:**
  * `create_view`, `view_graphics`
  * `manage_sheets`, `create_schedule`
  * `batch_rename`, `manage_groups`, `manage_assemblies`
* **Coordination and QC:**
  * `run_model_checks`: 16 checks, including `iso19650` and `view_audit`
  * `check_clashes`: hard and clearance clashes, grid zones, grouping
  * `export_clash_report`: CSV and HTML
  * `model_snapshot` + `compare_models`

### Example: clash coordination round

```text
check_clashes(set_a={categories: ["Ducts", "Pipes"]}, set_b={categories: ["Structural Framing"]}, dry_run=true)
export_clash_report(set_a={categories: ["Ducts", "Pipes"]}, set_b={categories: ["Structural Framing"]},
                    clearance=50, group_by=["pair", "level", "grid_zone"])
```

### Example: parametric family with three types

```text
family_create(kind="door", save_path="C:/Families/RVTSS Door.rfa")
family_add_parameters(document="RVTSS Door", parameters=[
    {name: "Frame Thickness", type: "length", value: 50, unit: "mm"},
    {name: "Leaf Width", type: "length", formula: "Width - 2 * Frame Thickness"}])
family_manage_types(document="RVTSS Door", action="create", types=[
    {name: "900 x 2100", values: {Width: 900, Height: 2100}},
    {name: "1000 x 2100", values: {Width: 1000, Height: 2100}}])
family_flex_test(document="RVTSS Door")
family_validate(document="RVTSS Door", expected_category="Doors")
family_save(document="RVTSS Door")
family_load_into_project(document="RVTSS Door")
```

## Safety model

* **Transactions.**
  * Every change runs in a named transaction, so it can be undone in Revit.
  * Revit warnings are returned to Claude.
  * An error rolls the change back.
  * Nothing is reported as done unless Revit committed it.
* **Dry run and confirmation.**
  * `dry_run=true` lets Revit validate the whole change, then rolls it back.
  * Operations over `RVTSS_CONFIRM_THRESHOLD` elements, deletions, CSV imports and batch renames return a
    **preview**. They only run after confirmation: through elicitation, or by calling again with
    `confirm=true`.
* **Units.** Dimensional values need a unit (`900` with `unit="mm"`, or `"900 mm"`). Bare numbers are
  rejected.
* **Files.**
  * `.rfa` files are backed up before being overwritten.
  * Shared parameter GUIDs are never rewritten.
  * Bindings are extended, never replaced.
  * The family library audit never saves.
* **Retries.** Requests that change the model are never retried. A timeout tells you whether Revit is busy
  (a modal dialog or edit mode) or Routes is down.

## Tests

```powershell
uv run --extra test pytest tests/unit          # offline, both MCP SDK majors
uv run --extra test pytest -m live tests/live  # needs Revit + pyRevit Routes running
```

CI (`.github/workflows/ci.yml`) runs:
* the unit tests on Python 3.11–3.13, against mcp 1.9.x and the latest 2.x;
* pyflakes;
* vermin (IronPython 2.7 / 3.4 compatibility of the Revit side);
* a check that `docs/TOOLS.md` is up to date.

Revit API behaviour itself is verified by the self-test inside Revit; see the verification status in
[docs/UPGRADE_REPORT.md](docs/UPGRADE_REPORT.md).
