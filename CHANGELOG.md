# Changelog

All notable changes to RVTSS. Details, verification status and design notes: [docs/UPGRADE_REPORT.md](docs/UPGRADE_REPORT.md).

## Unreleased

### Added
* **Install & use tutorial** (`media/rvtss-tutorial.mp4`, 3:54, 1080p): a narrated motion-graphics walkthrough of
  installation, connecting Claude, toolsets, usage, features and the safety model. Voiceover and music were made
  with ElevenLabs. English captions are in `media/tutorial-src/captions.vtt`, and the render source is in
  `media/tutorial-src/`.
* **40 s social reel** (`media/rvtss-reel-40s.mp4`, 1080×1920, captions burned in) with a cover image, for
  Reels, TikTok, Shorts, LinkedIn and WhatsApp Status. Its source is in `media/reel-src/`.
* **User manual** (`docs/USER_MANUAL.md`): installation step by step, usage examples, every tool by area,
  prompts and resources, safety, security, configuration, troubleshooting, and updating.
* **Website** (`website/`): a landing page with the tutorial (chapters, captions), install steps with copy
  buttons, and the manual as HTML. It is deployed to GitHub Pages by `.github/workflows/pages.yml`.

### Fixed
* `extension.json` now sets `default_enabled` to `True` and `builtin` to `False`. Recent pyRevit versions read
  this file and disabled a freshly cloned RVTSS, so no `revit_mcp` routes were registered and
  `/revit_mcp/status/` answered `Route does not exits`.

## 2.1.0 – 2026-10-22

### Added
* **Live verification:**
  * The **Diagnostics → Run Self-Test** button in Revit.
  * `tests/live/run_live.py` (HTTP).
  * Both run the same plan on a copy of `tests/test.rvt` in `%TEMP%\RVTSS_live` and write
    `rvtss_live_report.json` and `.md`.
* **Security:**
  * An optional `RVTSS_TOKEN` shared secret.
  * `RVTSS_ALLOW_CODE_EXECUTION` and a `read_only` transaction mode for `execute_revit_code`.
  * The MCP server refuses non-loopback Revit hosts unless `RVTSS_ALLOW_REMOTE=1`.
  * Secret redaction, capped lines and 30-day rotation in the audit logs.
* **Toolsets:**
  * `RVTSS_TOOLSETS`, with profiles `bim_coordinator`, `family_author`, `modeler` and `minimal`.
  * Full tool documentation is served as the `rvtss://docs/tools/{name}` resource.
* **MCP protocol:**
  * Structured output for six read tools.
  * Resources: `rvtss://session`, `project/overview`, `qc_rules`, `config`, `logs/today`, `docs/toolsets`.
  * Seven prompts.
  * Progress heartbeats and log messages for long operations.
  * Elicitation-based confirmation of destructive previews.
* **Bridge:**
  * One pooled HTTP client.
  * A `/ping/` route that answers without API context; timeouts now say "Revit busy" or "Routes down".
  * A GET is retried once after a dropped connection; a POST never is.
  * View images: jpg and size options and a structured error envelope.
  * A correlation id goes MCP → Routes → audit log and comes back as `request_id`.
* **Coordination** (see [docs/COORDINATION.md](docs/COORDINATION.md)):
  * Clearance clashes with level, grid zone and nearest grid intersection, plus grouping and
    `export_clash_report` (CSV and HTML).
  * `audit_family_library`.
  * The `iso19650` naming check, with an [example rule set](docs/examples/qc_rules.iso19650.json).
  * The `view_audit` check.
  * `export_to_excel`.
  * IFC/COBie presets for `map_parameters`.
  * `global_parameters` label/unlabel dimensions.
* **Tooling:**
  * GitHub Actions CI: Python 3.11–3.13 × mcp 1.9.x / 2.x, pyflakes, vermin and a `TOOLS.md` freshness
    check.
  * `docs/UPSTREAM.md` and this changelog.
* Revit 2027 is listed in the supported range: its API reference was checked and pyRevit ships a 2027
  runtime. It has not been run live yet.

### Changed
* **Smaller tool list.** The default tool-list payload is 71.2k characters, down from 119.4k (−40 %), even
  with three new tools. Only the first docstring paragraph is advertised, and schemas are compacted.
* **Deprecated aliases.** Seven overlapping original tools move to the `legacy` toolset, unchanged but
  marked deprecated, to be removed in the next release:
  * `list_families` and `list_family_categories` → `get_family_inventory`
  * `list_revit_views` → `find_views`
  * `get_current_view_elements` → `find_elements(view='active')`
  * `get_current_view_info` → `get_session_info` / `find_views`
  * `list_levels` → `get_project_overview(include=['levels'])`
  * `place_family` → `create_elements(kind='family_instance')`
* **Request ids on every route.** All routes are now wrapped so they carry request ids. Handler argument
  names are kept, so pyRevit's API-context detection is unchanged.
* **Package and display name.** The Python package is renamed `rvtss-mcp` (it was `mcp-server-for-revit`)
  and the extension display name is now `RVTSS`. The API name `revit_mcp`, port 48884 and the install
  folder are unchanged.
* **Dependency.** `openpyxl` is a new MCP-side dependency.

### Fixed
* `SharedParametersFilename` was not restored when Revit previously had no shared parameter file.
* Clash grid zones were reversed for grids drawn along +Y.
* The `ifc_overrides` preset without a selection silently mapped Rooms only.
* The `validate` argument shadowed a pydantic attribute on mcp 1.9.
* 20 pyflakes warnings were cleaned up.

### Notes
* mcp 1.9.x needs `pydantic<2.14`: 2.14 removed an internal that mcp 1.9 imports. The default install
  resolves to mcp 2.x and is not affected.
* **Breaking for VM setups:** set `RVTSS_ALLOW_REMOTE=1` when `REVIT_HOST` is not loopback.

## 2.0.0

The first RVTSS release, built on mcp-server-for-revit-python:
* 54 new tools for model intelligence, element editing, family creation and editing, parameter management,
  documentation automation and BIM QC;
* a Revit version compatibility layer;
* true dry runs and confirmation gates;
* MCP SDK 1.x and 2.x support;
* 158 offline unit tests.
