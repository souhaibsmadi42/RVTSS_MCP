# BIM coordination features (RVTSS v2.1)

Worked examples for the seven Phase 6 features. Each one can be tried with `dry_run=true` first. The
MCP prompts `clash_coordination` and `bim_standards_audit` chain them into complete workflows.

Files written by the MCP server (clash reports, Excel) go to `RVTSS_REPORT_DIR`, or to
`~/Documents/RVTSS/reports` when it is not set, on the machine running `main.py`. Files that Revit reads
(the family library, `qc_rules.json`, office presets) live on the Revit machine.

## 1. Clearance clashes, grouping and the clash report

```text
check_clashes(set_a={categories: ["Ducts", "Pipes"]},
              set_b={categories: ["Structural Framing"]},
              clearance=50, group_by=["pair", "level", "grid_zone"])
```

* **Clash types.** `type: "hard"` means the solids intersect. `type: "clearance"` means the solids are
  closer than `clearance` (in `unit`, default mm), with the measured `distance`.
* **Location.** Each pair carries:
  * `level` (the level of element A);
  * `point` (host coordinates);
  * `grid_zone`, e.g. `"A-B/1-2"`, or `">C/1-2"` outside the last grid;
  * `nearest_grid` (`{"name": "B/2", "distance": 1118.0}`).
* **Grids.** Only straight grids are used. Zones are measured in +X/+Y order, so a grid drawn top to bottom
  still gives `A-B` and not `B-A`.
* **How distance is measured.** Clearance distance is sampled: an n×n grid of points on every face, plus
  edge points, projected onto the other solid's faces and edges (`samples`, default 5). The result is
  never below the true distance, so a pair just inside the limit can be missed; raise `samples` for
  critical checks.
* **Links.** Against a link, add `link_instance_id` to `set_b`. Grid zones use the host grids.

```text
export_clash_report(set_a=..., set_b=..., clearance=50)
-> files: {csv: ".../clash_report_20261022-101500.csv", html: ".../clash_report_20261022-101500.html"}
```

The CSV has one row per clash: number, type, distance, level, grid zone, nearest grid and its offset, the
A and B id/category/family/type, and X/Y/Z. The HTML report has a summary, one table per grouping, and all
clashes.

## 2. Family library audit

```text
audit_family_library(folder="D:/Library/Doors", dry_run=true)   # which files would be opened
audit_family_library(folder="D:/Library/Doors", max_files=100)
```

* **Read-only.** Every `.rfa` is opened with `Application.OpenDocumentFile` and closed with `Close(False)`,
  so nothing is saved. Families that are already open are inspected and left open. Backups (`*.0001.rfa`)
  are skipped.
* **Per family:** category, size, parameters (shared/instance/formula), types, nested families, Revit
  warnings and the `family_validate` findings.
* **Library findings:**
  * open failures;
  * files larger than `max_size_kb`;
  * Generic Models or no category;
  * no types, more than 10 nested families, or Revit warnings;
  * validation errors;
  * parameter names that differ only in case;
  * naming, using `naming.families` and the iso19650 `families` target.

## 3. ISO 19650 naming checks

Copy [`examples/qc_rules.iso19650.json`](examples/qc_rules.iso19650.json) to
`%APPDATA%/RVTSS/qc_rules.json` and replace the codes with the ones in your BEP. Then:

```text
run_model_checks(checks=["iso19650"])
```

* **Scheme.** Fields are checked one by one. A field can have `values` (an allowed list), `pattern` (regex),
  `length` / `min_length` / `max_length`, `optional` and `case_sensitive`.
* **Targets:** `sheets` (number or name), `views`, `view_templates`, `families`, `types` and `worksets`
  (workshared models only). Each target can override `delimiter`, `fields` and `severity`.
* **Findings:** one finding per target, with the count of violations per field and up to 15 examples that
  show the failing fields. For example, `'P123-QQQ-ZZ-01-DR-A-12'` gives `originator: 'QQQ' not in allowed
  values` and `number: '12' does not match ^\d{4}$`.

## 4. View and view-template audit

```text
run_model_checks(checks=["view_audit"])
```

It reports:
* views without a template (by default only plans, RCPs, sections, elevations, 3D, area and structural
  plans; change this with `view_audit.template_view_types` in `qc_rules.json`);
* templates no view uses;
* sheets with no views (placeholders excluded);
* views not on any sheet (dependent views excluded);
* view names used more than once across view types;
* scope boxes used by neither a view nor a grid, level or reference plane.

The two scope-box parameters (`VIEWER_VOLUME_OF_INTEREST_CROP` and `DATUM_VOLUME_OF_INTEREST`) are looked up
defensively. If a Revit version lacks either one, the audit says so instead of failing.

## 5. Export to Excel

```text
export_to_excel(output_path="QTO_doors_windows.xlsx",
                categories=["Doors", "Windows"], parameters=["Width", "Height", "Fire Rating", "Mark"],
                schedules=["Door Schedule"])
```

* **Sheets:** one per category and one per schedule (fetched page by page, 2000 rows at a time), plus a
  `Summary` sheet.
* **Values.** In `value_mode="raw"` (the default), numbers are written in `unit` and the header shows the
  unit, e.g. `Width [mm]`. `display` writes Revit's formatted text instead.
* **Safety.** Values that start with `= + - @` (and are not numbers) are stored as text, so a parameter value
  can never become a formula.
* **Tooling.** `openpyxl` is needed on the MCP side; it is now a dependency.

## 6. IFC and COBie mapping presets

```text
map_parameters(preset="ifc_overrides", categories=["Doors", "Walls", "Rooms"], dry_run=true)
map_parameters(preset="cobie_space", dry_run=true)      # only Rooms: selected automatically
```

| Preset | Targets |
|---|---|
| `ifc_overrides` | `IfcTag`, `IfcDescription`, `IfcName` / `IfcLongName` (Rooms), `IfcObjectType` |
| `ifc_common_psets` | `FireRating`, `AcousticRating`, `IsExternal` (common pset property names) |
| `cobie_type` | `COBie.Type.Manufacturer`, `.ModelNumber`, `.Description`, `.Category` |
| `cobie_component` | `COBie.Component.SerialNumber`, `.InstallationDate`, `.TagNumber`, `.Description` |
| `cobie_space` | `COBie.Space.Name`, `COBie.Space.Description` |

* **Verification.** The results list `unverified_targets`: target names that could not be confirmed in
  Autodesk documentation while this release was built. Check them against your COBie Extension shared
  parameter file.
* **Safety.** A target that does not exist on an element is skipped, never created.
* **Office presets.** Put them in `%APPDATA%/RVTSS/presets/<name>.json` as
  `{"description": "...", "mappings": [{"from": "...", "to": "...", "categories": [...]}]}`.
* **Combining.** `mappings` given in the call are applied after the preset's mappings.

## 7. Global parameters on dimensions

```text
global_parameters(action="create", name="Corridor Width", type="length", value=1800, value_unit="mm")
global_parameters(action="label_dimensions", name="Corridor Width", element_ids=[123456], dry_run=true)
global_parameters(action="label_dimensions", name="Corridor Width", element_ids=[123456])
global_parameters(action="list")          # labeled_dimensions per parameter
global_parameters(action="unlabel_dimensions", name="Corridor Width", element_ids=[123456])
```

This uses `GlobalParameter.CanLabelDimension`, `LabelDimension`, `UnlabelDimension` and
`GetLabeledDimensions` (checked in the Revit 2025–2027 API reference). A dimension that cannot be labelled
returns 409 with the reason; typical causes are a multi-segment dimension, a spec mismatch, or a dimension
that doesn't reference model geometry. Everything runs in one transaction and `dry_run` rolls it back.
