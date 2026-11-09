# Changelog

All notable changes to RVTSS. Details, verification status and design notes: [docs/UPGRADE_REPORT.md](docs/UPGRADE_REPORT.md).

## 2.3.0 – 2026-11-07

Closes gaps found in a feature comparison with other Revit MCP servers (a survey of
13 Revit MCP repositories on GitHub; ideas re-implemented, no code copied). **First release verified live:
the full self-test passes on Revit 2026 and Revit 2027 (52 passed, 0 failed each).** 107 tools.

### Added (second batch)
* **`capture_elements`:** the AI can look at elements. A temporary 3D view with a section box around them
  (orientation preset or eye/target, isolate, orange highlight, perspective, display style) is exported as
  PNG/JPG and rolled back, so the model and its undo history do not change.
* **`create_stairs`:** component stairs between two levels from straight runs, automatic landings, optional
  railings; one undo step, dry run supported.
* **`undo_last_change`:** undo the latest step, only if RVTSS made it. A DocumentChanged ledger records who
  made each step (user, Ctrl+Z / Ctrl+Y and dry runs are tracked), then Revit's own Undo is posted.
* **`manage_phases`** (phases, phase filters, design options; set element / view phase; elements of an option),
  **`manage_links`** (list, reload, unload, reload from a path, load a link), **`selection_sets`** (save, load,
  list, delete saved selections).
* **`create_elements` kinds:** ducts, pipes, cable trays and conduit (multi-point runs joined by elbows),
  wall openings, floor / roof / ceiling openings, shafts, railings, spaces, areas, area boundary and room /
  space separation lines, automatic rooms (a room in every closed region), rebar from a polyline with a
  fixed-number layout, toposolids (2024+) and DirectShape meshes (inline or .obj).
* **`transform_elements` operations:** `array` (linear or radial copies), `pin` / `unpin`, `join` / `unjoin` /
  `switch_join`.
* **`scripts/install.ps1`:** one read-only check of pyRevit, extension copies, Routes, uv, the MCP
  environment and the Claude Code / Desktop entries; `-Apply` fixes them after a yes per change, with
  backups.
* Self-test group `v23`; the test creates its own walls and floor in the copy of `tests/test.rvt` (an empty
  template), so the editing steps that were skipped before now run.

### Fixed (found by the first live run)
* `place_family` never found a family type: `FamilySymbol.Name` raises in IronPython and the error ended the
  search. Names are now read safely per symbol (case-insensitive).
* `global_parameters(action='create')` called a method that does not exist (`GlobalParameter.IsValidName`);
  it now uses `GlobalParametersManager.IsUniqueName`.
* `family_create_form` sweeps always failed: Revit wants the profile in the XY plane at the origin and moves it
  to the path itself.
* An explicit `dry_run=true` came back as `status: preview` asking for `confirm=true` (set_parameters,
  bulk_update_parameter, transform_elements, tag_elements, batch_rename, change_type).
* `spatial_query` crashed on elements with an unbound location curve.
* Footprint roofs (`create_elements` kind `roof`, added earlier in 2.3) failed with "Value cannot be null":
  the out parameter of `NewFootPrintRoof` needs an instance in IronPython. Roofs are now in the self-test.
* Title block family templates were never found on Windows (`Titleblocks\A1 metric.rft`): the folder name now
  counts. CI on Linux hid it because a Windows path is one file name there.
* Self-test: the first status check no longer fails before a document is open; views are addressed by id
  (floor and ceiling plans share names); Model Text is not offered to the placement test.

### Changed (second batch)
* The default tool list is 102k characters for 107 tools (v2.0: 119k for 74); per tool still within 5 % of
  v2.1. The payload test now allows 88 % of v2.0 (was 82 % for 99 tools).

### Added
* **Detailing:** `create_detailing` makes dimensions (grids, levels, reference planes, wall faces, family
  instance references), detail lines (with line styles, open or closed) and filled regions in one view, in
  one transaction. `list_annotation_types` lists text, tag, dimension and filled region types and line styles.
* **Modelling:** `create_elements` also creates footprint roofs (with slope), ceilings (Revit 2022+),
  structural and architectural columns, beams, isolated foundations and wall foundations.

### Changed
* **Saving and synchronizing are off by default.** `save_document`, `close_document(save=true)` and
  `sync_with_central` return 403 `POLICY_DENIED` until `"allow_save"` / `"allow_sync": true` is set in
  `%APPDATA%\RVTSS\config.json` (or `RVTSS_ALLOW_SAVE` / `RVTSS_ALLOW_SYNC` for Revit). `family_save` and
  exports are unchanged. `/status/` and `get_session_info` report both settings.

### Verification
* Unit tests: 325 passed. Live self-test (tests/live/run_live.py): 52 passed, 0 failed, 1 skipped (the
  status check before a document is open) on Revit 2026 (build 20260731_1210) and Revit 2027 (build
  20260527_1515), pyRevit 6.5.5, IronPython 2.7.12. Revit 2024 was not run.

## 2.2.0 – 2026-10-25

Ideas ported from [bimwright/rvt-mcp](https://github.com/bimwright/rvt-mcp) (Apache-2.0, C#) and
re-implemented for pyRevit; see [NOTICE](NOTICE). Revit-side behaviour of the new tools is covered by the
in-Revit self-test (group `v22`) and has not yet been run in a live Revit session.

### Added
* **22 tools (99 in all) and six toolsets:**
  * `rooms`: `list_rooms` (rooms, spaces, areas; placed / unplaced / not enclosed / redundant; totals by level
    and department), `get_room_details` (boundary segments, doors and windows by From/To room, estimated
    wall/floor/ceiling finish areas, contents).
  * `materials`: `list_materials` (optional usage counts), `material_takeoff` (area and volume per material,
    grouped by material / category / level / type), `manage_materials` (create, duplicate, rename, set
    colour/patterns, assign to elements, types or compound-structure layers).
  * `annotation`: `find_untagged_elements`, `tag_elements` (independent tags plus room, space and area
    tags; skips tagged elements), `create_text_notes`.
  * `export`: `list_export_settings`, `export_documents` (PDF on Revit 2022+, DWG, DXF, IFC, NWC, schedule
    CSV; one file per sheet from a naming template, combined PDF, saved setups, dry-run file plan, never
    overwrites without `overwrite=true`).
  * `mep`: `list_mep_systems`, `get_mep_connectors`, `find_mep_disconnects`.
  * `admin`: `manage_worksets` (counts, create, rename, move elements, set active), `purge_unused`
    (Revit 2024+ purge query, unused family types before; preview until `confirm=true`).
  * `model`: `survey_change_impact` (type siblings, host/hosted, joins, groups, rooms, tags, dimensions,
    dependents, views/sheets, levels, MEP connections; every group *found*, *none* or *not checked*),
    `get_coordinates` (base points, true north, links, internal → shared conversion).
  * `documentation`: `manage_view_filters` (rule-based filters, overrides, where used), `manage_revisions`.
  * `qc`: `spatial_query` (distance, in box, near point, ray cast).
  * `core`: `rvtss_health` (MCP server → Routes → Revit, works with Revit closed, names the next step).
  * `edit`: `batch_execute`.
* **`batch_execute`:** up to 20 edits in one Revit TransactionGroup: one undo step, everything rolled back
  on the first failure (unless `continue_on_error`) or for `dry_run`. Sub-commands are built and validated
  by the real tools (payload capture), checked against an allow list on both sides, and must target the
  same document.
* **Read-only mode** `RVTSS_READ_ONLY`: on the MCP server only read-only tools are registered; in Revit
  every change, save, sync, family save and export is refused with 403 (dry runs still work, code execution
  only in `read_only` / `dry_run` mode).
* **Argument guard:** unknown argument names are refused with `did_you_mean` before anything is sent
  (pydantic used to drop them silently, so `dryrun=true` ran a real change).
* **Response guard:** results above `RVTSS_RESPONSE_BUDGET_KB` (default 256) are summarised, keeping the
  status and every scalar field, with narrowing hints; a note is added above `RVTSS_RESPONSE_WARN_KB`.
* **Prompts:** `getting_started`, `safe_change`, `room_documentation`, `issue_sheets`,
  `mep_connectivity_review` (12 in all).
* **Profiles:** `architect`, `mep_coordinator`, `publisher`, `auditor`.
* **Docs:** generated Claude Code read-only allow list in the README, `AGENTS.md` (agent-assisted install),
  `SECURITY.md`, `CONTRIBUTING.md`, `NOTICE`.
* Self-test group `v22`: read-only calls of the new tools, dry runs, an export plan, a purge preview and a
  batch that must roll back.

### Changed
* The default tool list is 95k characters for 99 tools (v2.0: 119k for 74; v2.1: 71k for 77). The payload
  test now checks the per-tool size against v2.1.
* Server instructions mention `survey_change_impact`, `batch_execute` and `rvtss_health`.
* `/status/` and `get_session_info` report `read_only` in the security block.

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
