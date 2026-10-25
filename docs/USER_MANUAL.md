# RVTSS User Manual

**RVTSS — Revit MCP for Claude** · version 2.1 · by Suhaib Al Smadi

RVTSS connects Claude to the Autodesk Revit model you have open. You ask in plain language. Claude then
runs RVTSS tools inside Revit to inspect, edit, document and check the model, and reports back.

> 🎬 **Prefer video?** The 4-minute install and use tutorial covers this manual's quick path:
> [media/rvtss-tutorial.mp4](../media/rvtss-tutorial.mp4) (also on the
> [RVTSS website](https://souhaibsmadi42.github.io/RVTSS_MCP/)).

---

## Contents

1. [What RVTSS does](#1-what-rvtss-does)
2. [What you need](#2-what-you-need)
3. [How it works](#3-how-it-works)
4. [Installation (step by step)](#4-installation-step-by-step)
5. [Using RVTSS](#5-using-rvtss)
6. [Toolsets and profiles](#6-toolsets-and-profiles)
7. [Features: every tool](#7-features-every-tool)
8. [Built-in prompts and resources](#8-built-in-prompts-and-resources)
9. [Safety model](#9-safety-model)
10. [Security](#10-security)
11. [Configuration reference](#11-configuration-reference)
12. [Troubleshooting](#12-troubleshooting)
13. [Updating and uninstalling](#13-updating-and-uninstalling)
14. [Getting help](#14-getting-help)

---

## 1. What RVTSS does

| Area | What you can ask Claude to do |
|---|---|
| **Model intelligence** | Summarise a project; find elements with combined filters; read element details, schedules, sheets, views, links and warnings. |
| **Element editing** | Set parameters, renumber in bulk, move/copy/rotate/mirror, create levels, grids, walls, floors, rooms and family instances, delete with preview. |
| **Families (.rfa)** | Create or open families, add parameters and formulas, build constrained geometry, manage types, flex-test, validate, save and load into the project. |
| **Parameters** | Shared, project and global parameters; audits; CSV import/export; Excel export; mapping to your standard or to IFC/COBie. |
| **Documentation** | Create views, sheets and schedules; graphic overrides; batch renaming; groups and assemblies; colour by parameter. |
| **Coordination & QC** | 16 model checks (including ISO 19650 naming and view audit), hard and clearance clashes with CSV/HTML reports, model snapshots and change detection, family library audits. |

**77 tools in 10 toolsets**, plus MCP resources and ready-made prompts. RVTSS is an upgrade of
[mcp-server-for-revit-python](https://github.com/mcp-servers-for-revit/mcp-server-for-revit-python) and keeps
its API name, port and all 20 original tools.

---

## 2. What you need

| Requirement | Version | Notes |
|---|---|---|
| **Autodesk Revit** | 2021 – 2027 | Windows. 2027 is supported by the API but not yet verified live. |
| **pyRevit** | 4.8+ or 5.x | Provides the *Routes* web server that RVTSS runs on. [pyrevitlabs.io](https://pyrevitlabs.io) |
| **Python** | 3.11 or newer | For the MCP server (runs outside Revit). |
| **uv** | latest | Python package manager. Installs and runs the MCP server. |
| **git** | any | To clone the extension (or download the ZIP instead). |
| **Claude** | Claude Desktop or Claude Code | Any MCP-capable client works. |

Install **uv** on Windows (PowerShell):

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen the terminal, then check: `uv --version`.

---

## 3. How it works

```
Claude (Desktop / Code)
   │  MCP: tools, resources, prompts
   ▼
RVTSS MCP server  (main.py, Python 3.11+, on your PC)
   │  HTTP JSON  →  http://127.0.0.1:48884/revit_mcp/...
   ▼
pyRevit Routes  (inside Revit)
   │  Revit API, inside transactions
   ▼
Your Revit model
```

* The **MCP server** is what Claude starts. It turns each tool call into an HTTP request.
* **pyRevit Routes** is a small web server inside Revit, on port **48884**. The RVTSS extension adds the
  `revit_mcp` routes to it.
* Every change runs in a named Revit **transaction**, so it can be undone, and errors roll back.

---

## 4. Installation (step by step)

### Step 1 — Install the extension

Open **PowerShell** and clone the repository into the pyRevit extensions folder, as a folder whose name ends
in `.extension`:

```powershell
cd "$env:APPDATA\pyRevit\Extensions"
git clone https://github.com/souhaibsmadi42/RVTSS_MCP RVTSS.extension
```

No git? Download the ZIP from GitHub, extract it there, and rename the folder to `RVTSS.extension`.

> ⚠️ **Keep only ONE copy.** Two Revit MCP extensions both register the `revit_mcp` API and conflict. If
> `revit-mcp-python.extension` or `mcp-server-for-revit-python.extension` is in
> `%APPDATA%\pyRevit\Extensions`, remove or disable it first.

*Alternative:* keep the clone anywhere and add its **parent** folder under pyRevit → Settings →
**Custom Extension Directories**.

### Step 2 — Turn on pyRevit Routes

1. In Revit, open the **pyRevit** tab → **Settings**.
2. Go to **Routes** and enable **Routes Server**.
3. Set the host to **`127.0.0.1`** (recommended: only this PC can reach it). Leave the port at **48884**.
4. Click **Save Settings and Reload**.

A new **RVTSS** tab appears in the Revit ribbon. If it doesn't, see
[Troubleshooting](#route-does-not-exits--no-rvtss-tab).

### Step 3 — Check the server

Open this address in any browser while Revit is running:

```
http://127.0.0.1:48884/revit_mcp/status/
```

You should see JSON containing:

```json
{ "status": "active", "health": "healthy", "rvtss_version": "2.1.0", "api_name": "revit_mcp" }
```

### Step 4 — Run the self-test (recommended)

On the **RVTSS** tab, click **Diagnostics → Run Self-Test**.

* It copies the bundled test model (`tests/test.rvt`) to `%TEMP%\RVTSS_live` and works only on that copy.
  **Your own files and your shared parameter file are never touched.**
* It runs every group: status, original tools, read-only tools, editing (dry run, then real), the family
  workflow, parameters (on a scratch shared parameter file), and QC & coordination.
* It writes `rvtss_live_report.json` and `.md` and opens a pass/fail report.

### Step 5 — Install the MCP server dependencies

In the extension folder:

```powershell
cd "$env:APPDATA\pyRevit\Extensions\RVTSS.extension"
uv sync
```

### Step 6 — Connect Claude

#### Claude Desktop

Open **Settings → Developer → Edit Config**. This opens `claude_desktop_config.json`. Add the RVTSS server,
replacing `<you>` with your Windows user name:

```json
{
  "mcpServers": {
    "RVTSS Revit": {
      "command": "uv",
      "args": [
        "run",
        "--project", "C:\\Users\\<you>\\AppData\\Roaming\\pyRevit\\Extensions\\RVTSS.extension",
        "python", "C:\\Users\\<you>\\AppData\\Roaming\\pyRevit\\Extensions\\RVTSS.extension\\main.py"
      ],
      "env": {
        "RVTSS_TOOLSETS": "bim_coordinator"
      }
    }
  }
}
```

If the file already has an `mcpServers` section, add only the `"RVTSS Revit": {...}` entry inside it.
**Fully quit and restart Claude Desktop.** The RVTSS tools then appear in the tools (🔨) menu.

#### Claude Code

One command (PowerShell):

```powershell
claude mcp add -s user RVTSS -- uv run --project "$env:APPDATA\pyRevit\Extensions\RVTSS.extension" python "$env:APPDATA\pyRevit\Extensions\RVTSS.extension\main.py"
```

Check it with `claude mcp list`. To pick a profile, add `-e RVTSS_TOOLSETS=bim_coordinator` before `--`.

### Step 7 — First test

With a model open in Revit, ask Claude:

> *"Call get_session_info and tell me which Revit model is open."*

Claude should report your Revit version, the active document and view. You're ready.

---

## 5. Using RVTSS

Just describe what you want. Claude picks the tools. Some example requests:

**Understand a model**
* "Give me an overview of this project: levels, grids, phases and worksets."
* "Find all doors on Level 2 wider than 900 mm and list their marks."
* "Which families are loaded but never placed?"
* "Show me the 10 most frequent Revit warnings and the elements causing them."
* "Read the Door Schedule and tell me which doors have no fire rating."

**Edit**
* "Renumber the selected doors left to right as D01, D02… — do a dry run first."
* "Set the Comments parameter of all Level 3 walls to 'Phase 2'."
* "Duplicate the 'Basic Wall 200' type as 'Basic Wall 250' and set its thickness to 250 mm."

**Families**
* "Create a parametric door family with Frame Thickness 50 mm and three sizes, flex-test it, and load it into
  the project."
* "Build a parametric box family for a reception desk, 1800 × 800 × 1100 mm."

**Parameters and documentation**
* "Roll out the shared parameters 'Asset Code' and 'Install Date' to Mechanical Equipment as instance
  parameters."
* "Export door and window parameters to Excel."
* "Create a sheet A-101 and place the Level 1 floor plan on it."
* "Rename all views that start with 'Copy of' — show me the preview first."

**Coordination and QC**
* "Run the model checks before we issue and list anything critical."
* "Check clashes between ducts and pipes and structural framing with 50 mm clearance, and export an HTML report
  grouped by level and grid zone."
* "Audit our sheet and view names against ISO 19650."
* "Take a model snapshot now, so we can compare after the next design update."

### Good habits

* **Start with `get_session_info`.** It confirms which model is active and lists all open documents. Use a
  document's title to target it when several are open.
* **Ask for a dry run** on anything that changes many elements. Revit validates the whole change, then rolls
  it back, and you see exactly what would happen.
* **Always give units** for dimensions: "900 mm", "3 ft". Bare numbers are rejected on purpose.
* **Close modal dialogs in Revit** before asking. A dialog or an edit mode blocks the Revit API, and RVTSS
  will tell you "Revit is busy".

---

## 6. Toolsets and profiles

Every tool definition costs context on every turn, so load only what you need. Set **`RVTSS_TOOLSETS`** in
the MCP server's environment (the `env` block in the Claude config) to a profile or a comma-separated list of
toolsets.

| Profile | Toolsets | Tools | Best for |
|---|---|---|---|
| `all` *(default)* | everything | 77 | trying everything |
| `bim_coordinator` | core, model, parameters, documentation, qc | 37 | coordinators, QC, documentation |
| `family_author` | core, families, parameters | 33 | building and fixing families |
| `modeler` | core, model, edit, documentation | 30 | everyday modelling edits |
| `minimal` | core, model | 14 | read-only exploration |

| Toolset | Contents |
|---|---|
| `core` *(always loaded)* | status, session, `find_elements`, element details, selection |
| `model` | overview, families, views, sheets, schedules, links, warnings, view image |
| `edit` | set and bulk parameters, transform, delete, create, types |
| `families` | the full `.rfa` workflow and the library audit |
| `parameters` | shared, project and global parameters, audit, CSV/Excel export, mapping presets |
| `documentation` | views, sheets, schedules, renames, groups, colours |
| `qc` | model checks, clashes, clash report, snapshots |
| `launch` | start Revit, open, save, close and sync documents |
| `code` | `execute_revit_code` (run IronPython in Revit) |
| `legacy` | seven original tools superseded by newer ones (deprecated) |

Example: `"RVTSS_TOOLSETS": "bim_coordinator,launch"`.

---

## 7. Features: every tool

*Mode:* 🔍 read-only · ✏️ modifies · ⚠️ destructive. The full, auto-generated reference with every parameter
is [docs/TOOLS.md](TOOLS.md).

### Session & status
| Tool | | What it does |
|---|---|---|
| `get_session_info` | 🔍 | **Call first.** Revit/pyRevit/RVTSS versions, active document and view, open documents, security status. |
| `get_revit_status` | 🔍 | Is the Revit MCP API active and responding? |
| `get_revit_model_info` | 🔍 | Comprehensive information about the current model. |
| `list_revit_installations` | 🔍 | Revit versions installed on this PC. |
| `launch_revit` | ✏️ | Start a Revit version (optionally with a file) and wait until Routes answers. |
| `open_document` / `save_document` | ✏️ | Open or save a document. |
| `close_document` | ⚠️ | Close the active document. |
| `sync_with_central` | ✏️ | Synchronise a workshared model with central. |

### Model intelligence
| Tool | | What it does |
|---|---|---|
| `get_project_overview` | 🔍 | Project info, units, levels, grids, phases, worksets, design options in one call. |
| `find_elements` | 🔍 | Combinable filters (category, level, family, type, parameter values with units…), paginated. |
| `get_element_details` | 🔍 | Level, location, bounding box, workset, phases, host, parameters with units, geometry (up to 50 elements). |
| `get_family_inventory` | 🔍 | Loaded families by category with types, instance counts and flags. |
| `find_views` | 🔍 | Views with type, level, scale, template and sheet placement. |
| `list_sheets` | 🔍 | Sheets with placed views, title blocks, revisions. |
| `get_schedule_data` | 🔍 | A schedule's table as displayed, paginated. |
| `list_links` | 🔍 | Revit links and CAD imports with status and position. |
| `get_model_warnings` | 🔍 | Warnings grouped by description, with element ids. |
| `get_revit_view` | 🔍 | Export a view as a PNG/JPG image. |
| `revit_selection` | ✏️ | Read the selection, or select/highlight elements for you. |
| `list_category_parameters` | 🔍 | Parameters available on a category (for colouring). |

### Element editing
| Tool | | What it does |
|---|---|---|
| `set_parameters` | ✏️ | Set instance/type parameters, with before/after values. |
| `bulk_update_parameter` | ✏️ | Write one parameter on many elements, or number them with a template (e.g. `D{n:02}`, sorted by x). |
| `transform_elements` | ✏️ | Move, copy, rotate or mirror. |
| `create_elements` | ✏️ | Levels, grids, walls, floors, family instances and rooms in one transaction. |
| `manage_element_types` | ✏️ | Duplicate, rename or switch types. |
| `delete_elements` | ⚠️ | Previews everything that would be deleted (including dependents); deletes only after confirmation. |
| `color_splash` / `clear_colors` | ✏️ | Colour a category by parameter value in the active view, or clear it. |

### Families (.rfa)
Typical order: `family_list_templates` → `family_create` / `family_open` → `family_add_parameters` →
`family_build_parametric_box` (or `family_create_form` + `family_add_dimension`) → `family_manage_types` →
`family_flex_test` → `family_validate` → `family_save` → `family_load_into_project`.

| Tool | | What it does |
|---|---|---|
| `family_list_templates` | 🔍 | Find family templates (.rft) for a kind. |
| `family_create` / `family_open` | ✏️ | New family from a template, or open one for editing. |
| `family_get_info` | 🔍 | Parameters, formulas, types, reference planes, dimensions, forms, nested families. |
| `family_set_properties` | ✏️ | Category and family settings (shared, work-plane based…). |
| `family_add_parameters` / `family_edit_parameters` | ✏️ | Add or edit parameters, formulas checked before Revit applies them. |
| `family_manage_types` | ✏️ | Create, duplicate, rename, delete types; type catalogs. |
| `family_create_reference_planes` | ✏️ | Named reference planes at offsets. |
| `family_create_form` | ✏️ | Extrusions, blends, revolutions and sweeps (solid or void). |
| `family_add_dimension` / `family_align_geometry` | ✏️ | Labelled dimensions, EQ constraints, face locking. |
| `family_build_parametric_box` | ✏️ | One call: a fully constrained parametric box plus a flex check. |
| `family_nested` | ✏️ | Load and place a nested family with parameter associations. |
| `family_flex_test` | 🔍 | Flex through types and values, report constraint errors (all rolled back). |
| `family_validate` | 🔍 | QC: category, formulas, unused parameters, geometry, warnings — with fixes. |
| `family_save` | ✏️ | Save, backing up any existing file first. |
| `family_load_into_project` | ✏️ | Load or reload into the project and verify every type arrived. |
| `family_close` | ⚠️ | Close a background family (refuses to drop unsaved changes by default). |
| `audit_family_library` | 🔍 | Audit a folder of .rfa files read-only — never saves. |

### Parameters
| Tool | | What it does |
|---|---|---|
| `list_project_parameters` | 🔍 | Bindings, categories, data types, GUIDs, duplicates. |
| `shared_parameters` | ✏️ | Read/create shared parameter files and definitions (GUIDs preserved), bind to categories. |
| `global_parameters` | ✏️ | List, create, set values/formulas, associate, label project dimensions. |
| `audit_parameters` | 🔍 | Missing, empty, invalid or misnamed parameters. |
| `export_parameters` / `import_parameters` | 🔍 / ✏️ | CSV round-trip (import is a dry run by default). |
| `export_to_excel` | 🔍 | Parameter values and schedules to `.xlsx`. |
| `map_parameters` | ✏️ | Copy values into your standard parameters, or apply IFC/COBie presets. Source values are never deleted. |

### Documentation
| Tool | | What it does |
|---|---|---|
| `create_view` | ✏️ | Plans, 3D (optionally boxed to elements), sections, elevations, drafting views, duplicates. |
| `view_graphics` | ✏️ | Overrides, hide/isolate, category visibility, templates, scale, detail level. |
| `manage_sheets` | ✏️ | Create sheets with title blocks and place views or schedules. |
| `create_schedule` | ✏️ | Schedules with fields, sorting and filters. |
| `batch_rename` | ✏️ | Find/replace/regex/prefix/suffix renames with collision detection (dry run by default). |
| `manage_groups` / `manage_assemblies` | ✏️ | Groups and assemblies, including assembly views and sheets. |

### Coordination & QC
| Tool | | What it does |
|---|---|---|
| `run_model_checks` | 🔍 | 16 checks: warnings, duplicates, naming, **ISO 19650**, **view audit**, families, CAD, links, rooms, sheets, required parameters, groups… with severity and fixes. |
| `check_clashes` | 🔍 | Hard and clearance clashes between two sets (or against a link), with level, grid zone and nearest grid intersection. |
| `export_clash_report` | 🔍 | The same, written to CSV and HTML, grouped by pair, level or grid zone. |
| `model_snapshot` / `compare_models` | ✏️ / 🔍 | Save a snapshot; detect added, removed and modified elements later. |

### Advanced
| Tool | | What it does |
|---|---|---|
| `execute_revit_code` | ⚠️ | Run IronPython in Revit. Every call is logged. Can be disabled; `read_only` mode refuses transactions. |

More worked examples for coordination: [docs/COORDINATION.md](COORDINATION.md).

---

## 8. Built-in prompts and resources

**Prompts** are ready-made workflows. In Claude Desktop, find them under the ➕ / attach menu → RVTSS:

| Prompt | What it runs |
|---|---|
| `model_health_check` | A full health review of the model. |
| `create_parametric_family` | A family from description to loaded, flexed and validated. |
| `shared_parameter_rollout` | Shared parameters to categories, reusing GUIDs. |
| `naming_audit` | Sheet, view and family naming against your rules. |
| `pre_issue_qc` | Pre-submission checks before an issue. |
| `clash_coordination` | A clash round with report. |
| `bim_standards_audit` | Standards audit, optionally including a family library. |

**Resources** Claude can read: `rvtss://session`, `rvtss://project/overview`, `rvtss://qc_rules`,
`rvtss://config`, `rvtss://logs/today`, `rvtss://docs/toolsets` and `rvtss://docs/tools/{name}`.

---

## 9. Safety model

* **Transactions.** Every change runs in a named transaction: undo it in Revit with Ctrl+Z. Errors roll back.
  Nothing is reported as done unless Revit committed it. Revit warnings are returned to Claude.
* **Dry runs.** `dry_run=true` lets Revit validate the whole change, then rolls it back.
* **Confirmation.** Deletions, CSV imports, batch renames and operations over `RVTSS_CONFIRM_THRESHOLD`
  elements (default 100) return a **preview** first. They run only after you confirm.
* **Units.** Dimensional values need a unit (`900 mm`). Bare numbers are rejected.
* **Files.** `.rfa` files are backed up before overwriting. Shared parameter GUIDs are never rewritten.
  Bindings are extended, never replaced. The family library audit never saves.
* **Retries.** Requests that change the model are never retried automatically.

---

## 10. Security

pyRevit Routes has no authentication of its own: anything that can reach port 48884 can drive Revit.

| Setting | Where | Effect |
|---|---|---|
| Routes host = `127.0.0.1` | pyRevit Settings → Routes | **Recommended.** Only this PC can connect. |
| `RVTSS_TOKEN` | Revit environment **and** MCP server `env` (or `"token"` in `%APPDATA%\RVTSS\config.json`) | Every route except `/status/` and `/ping/` requires the same token. |
| `RVTSS_ALLOW_CODE_EXECUTION=0` | Revit environment / config | Disables `execute_revit_code`. |
| `RVTSS_ALLOW_REMOTE=1` | MCP server `env` | Needed only when Revit runs on another machine or a VM. |

Audit logs live in `%APPDATA%\RVTSS\logs`. Secret-looking values are redacted, and files older than 30 days
are deleted.

---

## 11. Configuration reference

| Setting | Where | Default |
|---|---|---|
| `REVIT_HOST`, `REVIT_PORT`, `REVIT_API_NAME` | MCP server env | `127.0.0.1`, `48884`, `revit_mcp` |
| `RVTSS_TOOLSETS` | MCP server env | `all` |
| `RVTSS_TIMEOUT` / `RVTSS_IMAGE_TIMEOUT` | MCP server env (seconds) | `30` / `60` |
| `RVTSS_IMAGE_MAX_KB` | MCP server env | `4096` |
| `RVTSS_REPORT_DIR` | MCP server env — clash reports, Excel files | `~/Documents/RVTSS/reports` |
| `RVTSS_LOG_LEVEL` | MCP server env | `WARNING` |
| `RVTSS_CONFIRM_THRESHOLD` | Revit env | `100` |
| `%APPDATA%\RVTSS\config.json` | token, code execution, `family_template_dirs`, naming pattern | optional |
| `%APPDATA%\RVTSS\qc_rules.json` | naming, ISO 19650 scheme, required parameters, view audit ([example](examples/qc_rules.iso19650.json)) | optional |
| `%APPDATA%\RVTSS\presets\*.json` | office parameter-mapping presets for `map_parameters` | optional |

Example `config.json`:

```json
{
  "family_template_dirs": ["C:\\ProgramData\\Autodesk\\RVT 2025\\Family Templates\\English"],
  "naming": { "parameters": { "pattern": "^[A-Z][A-Za-z0-9 ]+$" } }
}
```

---

## 12. Troubleshooting

#### "Route does not exits" / no RVTSS tab
The extension is disabled or not found. In Revit: **pyRevit → Extensions → RVTSS → Enable**. Or set
`disabled = false` under `[RVTSS.extension]` in `%APPDATA%\pyRevit\pyRevit_config.ini`. Then restart Revit.
Check that the folder name ends in `.extension`.

#### The status page doesn't load at all
* Routes is off: pyRevit → Settings → Routes → enable **Routes Server**, then reload.
* Revit isn't running, or another program uses port 48884.
* Two MCP extensions are installed: keep only one (see Step 1).

#### Claude doesn't show the RVTSS tools
* Fully quit Claude Desktop (system tray → Quit) and start it again.
* `uv` not found: use its full path in `"command"`, e.g. `C:\\Users\\<you>\\.local\\bin\\uv.exe`.
* Wrong paths in `args`: both the `--project` folder and `main.py` must exist. Use double backslashes in JSON.
* Check the logs under Claude Desktop → Settings → Developer → *Open Logs Folder*.

#### "Revit is busy"
Revit answered `/ping/` but not the request. Close any open dialog, finish edit modes (sketch, group or family
edits), wait for long operations, and ask again. For slow models, raise `RVTSS_TIMEOUT`.

#### "pyRevit Routes is not reachable" / "Routes down"
Revit or Routes isn't running. Open Revit, check the status page, and see above.

#### "Dimensional value needs a unit"
Say "900 mm" instead of "900". This protects you from feet/millimetre mix-ups.

#### Token errors
`RVTSS_TOKEN` must be identical in Revit's environment and in the MCP server's `env`. Restart Revit after
changing it.

#### Revit runs in a VM or on another PC
Set the Routes host to that machine's address, then in the MCP server `env` set `REVIT_HOST` to it and
`RVTSS_ALLOW_REMOTE=1`. Strongly consider `RVTSS_TOKEN`.

#### View image refused
The image is larger than `RVTSS_IMAGE_MAX_KB`. Ask for `jpg` or a smaller `pixel_size`.

#### Still stuck?
Run **Diagnostics → Run Self-Test** and open an issue with `rvtss_live_report.md` attached.

---

## 13. Updating and uninstalling

**Update:**
```powershell
cd "$env:APPDATA\pyRevit\Extensions\RVTSS.extension"
git pull
uv sync
```
Then reload pyRevit (or restart Revit) and restart Claude. See [CHANGELOG.md](../CHANGELOG.md) for what changed.

**Uninstall:** remove the `"RVTSS Revit"` entry from the Claude config (or `claude mcp remove RVTSS`), delete
the `RVTSS.extension` folder, and reload pyRevit. Optionally delete `%APPDATA%\RVTSS` (logs, backups,
snapshots).

---

## 14. Getting help

* **Website (video + manual):** https://souhaibsmadi42.github.io/RVTSS_MCP/
* **Source and issues:** https://github.com/souhaibsmadi42/RVTSS_MCP
* **Tool reference:** [docs/TOOLS.md](TOOLS.md) · **Coordination guide:** [docs/COORDINATION.md](COORDINATION.md)
* **License:** MIT — see [LICENSE](../LICENSE).
