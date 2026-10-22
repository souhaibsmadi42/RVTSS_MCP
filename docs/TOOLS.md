# RVTSS MCP tool reference

Generated from the live tool registry by `scripts/generate_tool_docs.py` - do not edit by hand.

77 tools. **Origin**: *retained* = from the original MCP (some improved), *new* = added by RVTSS. **Mode**: read-only / modifies / destructive (MCP tool annotations).

Select toolsets with `RVTSS_TOOLSETS` (comma list of toolsets or profiles). Profiles: `all` = code, core, documentation, edit, families, launch, legacy, model, parameters, qc; `bim_coordinator` = core, model, parameters, documentation, qc; `family_author` = core, families, parameters; `minimal` = core, model; `modeler` = core, model, edit, documentation.

## Session & status

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `get_revit_status` | core | retained | read-only | Check if the Revit MCP API is active and responding |
| `get_session_info` | core | new | read-only | Call first: Revit/pyRevit/RVTSS versions, active document and view, all open documents (use titles as `document`), security status, paths. |
| `get_revit_model_info` | model | retained | read-only | Get comprehensive information about the current Revit model |
| `list_revit_installations` | launch | retained | read-only | Discover all Revit versions installed on this system. |
| `launch_revit` | launch | retained | modifies | Launch a Revit version (optionally with a file) and wait until pyRevit Routes answers. |
| `open_document` | launch | retained | modifies | Open a Revit document file in the running Revit instance. |
| `close_document` | launch | retained | destructive | Close the active Revit document. |
| `save_document` | launch | retained | modifies | Save the active Revit document. |
| `sync_with_central` | launch | retained | modifies | Synchronize the active workshared document with central. |

## Model intelligence

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `get_project_overview` | model | new | read-only | Project info, display units, levels, grids, phases, worksets and design options in one call. |
| `find_elements` | core | new | read-only | Find elements by combinable filters -> ids, names, category/family/type, counts (paginated). E.g. doors on Level 2 wider than 900 mm: categories=['Doors'], level='Level 2', param_filters=[{name:'Width', op:'gt', value:900, unit:'mm'}]. |
| `get_element_details` | core | new | read-only | Full details for up to 50 elements: level, location, bbox, workset, phases, host, group/assembly, parameters with units, geometry. |
| `get_family_inventory` | model | new | read-only | Loaded families by category with types, instance counts, in-place/editable flags. |
| `list_families` | legacy | retained | read-only | [Deprecated: use get_family_inventory] Flat list of family types, filterable with `contains`. |
| `list_family_categories` | legacy | retained | read-only | [Deprecated: use get_family_inventory] Get a list of all family categories in the current Revit model |
| `list_levels` | legacy | retained | read-only | [Deprecated: use get_project_overview(include=['levels'])] Get a list of all levels in the current Revit model |
| `list_links` | model | new | read-only | Revit links (path, load status, pinned, position/rotation) and CAD imports/links. |
| `get_model_warnings` | model | new | read-only | Revit warnings grouped by description (most frequent first) with the failing element ids. |
| `find_views` | model | new | read-only | Views with id, type, level, scale, template and sheet placement. |
| `list_revit_views` | legacy | retained | read-only | [Deprecated: use find_views] Get a list of all exportable views in the current Revit model |
| `get_current_view_info` | legacy | retained | read-only | [Deprecated: use get_session_info / find_views] Name, type, id, scale, crop, detail level and discipline of the active view. |
| `get_current_view_elements` | legacy | retained | read-only | [Deprecated: use find_elements(view='active')] Elements visible in the active view with category counts (truncated at `limit`). |
| `get_revit_view` | model | retained | read-only | Export a view as an image (png, or jpg for smaller payloads; pixel_size 128-4096). |
| `list_sheets` | model | new | read-only | Sheets with number, name, placed views, title blocks, revisions; counts sheets without views/title blocks. |
| `get_schedule_data` | model | new | read-only | Read a schedule's table (column headers and rows as displayed), paginated. |
| `list_category_parameters` | documentation | retained | read-only | Parameters available on a category's elements (for color_splash). |
| `revit_selection` | core | new | modifies | Read the current Revit selection, or select/highlight elements for the user (active document only). |

## Element editing

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `set_parameters` | edit | new | modifies | Set instance/type parameter values with before/after values. Dimensional numbers need `unit` (or '900 mm'); bare numbers are rejected. |
| `bulk_update_parameter` | edit | new | modifies | Write one parameter on many elements (ids, selection or filters) with a value or a numbering template, e.g. selected doors left-to-right: parameter='Mark', selection=true, template='D{n:02}', sort_by='x'. Use dry_run first. |
| `transform_elements` | edit | new | modifies | Move, copy, rotate or mirror elements. Copies return the new element ids. |
| `delete_elements` | edit | new | destructive | Delete elements. Without confirm=true it only previews everything Revit would delete (incl. hosted/dependent elements); show the preview first. |
| `create_elements` | edit | new | modifies | Create levels, grids, walls, floors, family instances (hosted or not) and rooms in one transaction; returns new ids. |
| `place_family` | legacy | retained | modifies | [Deprecated: use create_elements(kind='family_instance')] Place a family instance at a specified location in the Revit model. |
| `manage_element_types` | edit | new | modifies | Project types: duplicate a type (optionally setting its parameters), rename it, list the types an element may switch to, or change elements to another type. |
| `color_splash` | documentation | retained | modifies | Color a category's elements in the active view by parameter value. |
| `clear_colors` | documentation | retained | modifies | Clear color overrides for elements in a category |

## Family creation & editing

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `family_list_templates` | families | new | read-only | Find family templates (.rft) for a kind (best first) or show which kinds are available/missing. |
| `family_create` | families | new | modifies | Create a new .rfa family from a template (by kind or template_path); opens in the background - pass its title as `document`. |
| `family_open` | families | new | modifies | Open an existing family for editing - from an .rfa file or a family loaded in the project. |
| `family_get_info` | families | new | read-only | Inspect a family: properties, parameters (formula, shared GUID, associations, labels), types with values, reference planes, dimensions, forms, nested families. |
| `family_set_properties` | families | new | modifies | Change the family category and family-level settings (shared, work plane based, always vertical...). |
| `family_add_parameters` | families | new | modifies | Add family parameters (type/instance, any data type, value, formula, reporting, or shared with its GUID). Formulas are checked before Revit applies them. |
| `family_edit_parameters` | families | new | modifies | Edit existing family parameters. Shared parameters keep their GUID and cannot be renamed (Revit API limitation) - use replace_with_shared to swap definitions. |
| `family_manage_types` | families | new | modifies | Family types: list, create/upsert, duplicate, rename, delete, set values per type; export/import type catalogs. |
| `family_create_reference_planes` | families | new | modifies | Create named reference planes (x: left/right, y: front/back, z: horizontal) at offsets, or list them. |
| `family_create_form` | families | new | modifies | Create solid/void extrusion, blend, revolution or sweep on a work plane, with material/visibility/end parameter links, subcategory and face locking. |
| `family_add_dimension` | families | new | modifies | Dimension between parallel reference planes (or Ref. Level) and label it with a parameter (e.g. Left-Right labelled Width), add EQ constraints (Left-Center-Right) or lock it. |
| `family_align_geometry` | families | new | modifies | Lock form faces to the reference planes they lie on, so geometry follows labelled dimensions. |
| `family_build_parametric_box` | families | new | modifies | One call: fully constrained parametric box (planes, Width/Depth labels with EQ, locked extrusion, Height, Material) + flex check. Base for furniture/casework/equipment. |
| `family_nested` | families | new | modifies | Load a family into the family being edited and place it, linking nested parameters to host family parameters (parameter associations). |
| `family_flex_test` | families | new | read-only | Flex a family through types/values, measure geometry, report constraint errors and parameters with no effect; all rolled back. |
| `family_validate` | families | new | read-only | QC a family: category, formulas, parameters that drive nothing, type values, geometry, labelled dimensions, warnings - with severity and fixes. |
| `family_save` | families | new | modifies | Save the family document. Existing files are backed up to %APPDATA%/RVTSS/backups before being overwritten. |
| `family_load_into_project` | families | new | modifies | Load (or reload) the family into a project and verify that all its types arrived. |
| `family_close` | families | new | destructive | Close a background family document (refuses to drop unsaved changes unless discard_changes=true). |

## Parameter management

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `list_project_parameters` | parameters | new | read-only | Project parameters with binding (instance/type), categories, data type, group, shared GUID, plus names defined more than once. |
| `shared_parameters` | parameters | new | modifies | Shared parameters: read_file, create_definitions (GUIDs preserved), create_file, bind to categories (instance/type). |
| `global_parameters` | parameters | new | modifies | Global parameters: list (value, formula, affected elements, labelled dimensions), create, set value/formula, associate element parameters, and label / unlabel project dimensions. |
| `audit_parameters` | parameters | new | read-only | Audit parameters on elements: missing, empty, invalid values, wrong types, duplicate or misnamed definitions. |
| `export_parameters` | parameters | new | read-only | Export element parameter values to CSV (ElementId, UniqueId, Category, Family, Type + columns). |
| `import_parameters` | parameters | new | modifies | Import parameter values from CSV (ElementId or UniqueId column + parameter columns). dry_run by default. |
| `map_parameters` | parameters | new | modifies | Copy values from existing parameters into your BIM-standard parameters (converting between storage types through display values), or apply an IFC/COBie preset. Source values are never deleted. |

## Documentation

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `create_view` | documentation | new | modifies | Create plans, 3D (optionally boxed to elements), sections, elevations, drafting views or duplicates, with name/template/scale. |
| `view_graphics` | documentation | new | modifies | Per-view graphics: element/category overrides, hide/unhide, temporary isolate, category visibility, view templates, scale, detail level. |
| `manage_sheets` | documentation | new | modifies | Create sheets (with title blocks) and place views or schedules on them. |
| `create_schedule` | documentation | new | modifies | Create a schedule for a category with fields, sorting and filters. |
| `batch_rename` | documentation | new | modifies | Rename views/sheets/levels/families/types/rooms... with find/replace/regex/prefix/suffix/case; detects collisions. dry_run by default. |
| `manage_groups` | documentation | new | modifies | List group types (instances, unused types), create a model group from elements, or ungroup. |
| `manage_assemblies` | documentation | new | modifies | Assemblies: create, add/remove members, rename, create assembly views and sheet. |

## Coordination & QC

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `run_model_checks` | qc | new | read-only | BIM QC report (warnings, duplicates, naming, families/types, CAD, links, rooms, views, sheets, required parameters, groups) with severity, ids and fixes. |
| `check_clashes` | qc | new | read-only | Hard and clearance clashes between two element sets (also against a link), with level, grid zone and nearest grid intersection; export_clash_report writes CSV/HTML. |
| `export_clash_report` | qc | new | read-only | Clash check (hard + clearance) written to CSV/HTML: ids, levels, grid zone, nearest grid. |
| `model_snapshot` | qc | new | modifies | Save a JSON snapshot (ids, types, levels, locations, tracked parameters) for later compare_models. |
| `compare_models` | qc | new | read-only | Change detection: snapshot vs live model or another snapshot (added/removed/modified), or match two element sets by location (design vs shop model). |
| `audit_family_library` | families | new | read-only | Audit a folder of .rfa files (opened read-only, never saved): category, size, parameters, nested families, warnings, family_validate errors, naming. |
| `export_to_excel` | parameters | new | read-only | Write parameter values (one sheet per category, units in headers) and schedules to .xlsx. |

## Advanced

| Tool | Toolset | Origin | Mode | Purpose |
|---|---|---|---|---|
| `execute_revit_code` | code | retained | destructive | Run IronPython in Revit (doc, uidoc, DB, revit; print output returned). Prefer dedicated tools; transaction_mode none/auto/dry_run/read_only. |

## Parameters

### `get_revit_status`

Toolset: `core`

Check if the Revit MCP API is active and responding

### `get_session_info`

Toolset: `core`

Call first: Revit/pyRevit/RVTSS versions, active document and view, all open documents (use titles
as `document`), security status, paths.

Revit version/build, RVTSS version, active document and view, selection count, ALL open
documents (projects and background family documents - use their title as `document`), linked
documents, shared parameter file and family template path. Call this first in a session.

### `get_revit_model_info`

Toolset: `model`

Get comprehensive information about the current Revit model

### `list_revit_installations`

Toolset: `launch`

Discover all Revit versions installed on this system.

Returns a list of installed Revit versions with their executable paths.
Use this to check what's available before calling launch_revit.

### `launch_revit`

Toolset: `launch`

Launch a Revit version (optionally with a file) and wait until pyRevit Routes answers.

Launch Revit on this machine, optionally opening a file.

Finds installed Revit versions automatically. After launching, polls
the pyRevit Routes health endpoint until Revit is ready for MCP tools.

For workshared (central model) files, Revit will show its native
worksharing dialog on open. Use the open_document tool after launch
for more control over worksharing options like detach from central.

Args:
    file_path: Path to a .rvt, .rfa, or .rte file to open. Optional.
    version: Revit version year (e.g. "2025"). Uses latest if omitted.
    language: Language code (e.g. "ENU", "FRA"). Optional.
    timeout: Seconds to wait for Revit readiness (default 120).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string |  |  |  |
| `version` | string |  |  |  |
| `language` | string |  |  |  |
| `timeout` | integer |  | `120` |  |

### `open_document`

Toolset: `launch`

Open a Revit document file in the running Revit instance.

Supports workshared (central) files with options to detach from
central or audit the file on open.

Args:
    file_path: Absolute path to a .rvt, .rfa, or .rte file.
    detach: If True, open detached from central (workshared files only).
            Preserves worksets but severs the link to the central model.
    audit: If True, audit the file on open to check for corruption.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string | yes |  |  |
| `detach` | boolean |  | `False` |  |
| `audit` | boolean |  | `False` |  |

### `close_document`

Toolset: `launch`

Close the active Revit document.

Args:
    save: If True, save the document before closing.
          If False (default), close without saving.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `save` | boolean |  | `False` |  |

### `save_document`

Toolset: `launch`

Save the active Revit document.

If file_path is omitted, saves the document in place.
If file_path is provided, performs a Save As to the new location.

Args:
    file_path: Optional path for Save As. If omitted, saves in place.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string |  |  |  |

### `sync_with_central`

Toolset: `launch`

Synchronize the active workshared document with central.

Only works with workshared (central model) documents. For non-workshared
documents, use save_document instead.

Args:
    comment: Sync comment visible in the worksharing log.
    compact: If True, compact the central model during sync.
    relinquish_all: If True (default), relinquish all borrowed elements
                   and worksets after sync.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `comment` | string |  | `` |  |
| `compact` | boolean |  | `False` |  |
| `relinquish_all` | boolean |  | `True` |  |

### `get_project_overview`

Toolset: `model`

Project info, display units, levels, grids, phases, worksets and design options in one call.

Project information parameters, display units, levels (elevations), grids, phases, worksets
(workshared models) and design options - in one call.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `include` | list of `info` \| `levels` \| `grids` \| `phases` \| `worksets` \| `design_options` |  |  |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `find_elements`

Toolset: `core`

Find elements by combinable filters -> ids, names, category/family/type, counts (paginated).
E.g. doors on Level 2 wider than 900 mm: categories=['Doors'], level='Level 2',
param_filters=[{name:'Width', op:'gt', value:900, unit:'mm'}].

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `categories` | list of string |  |  | e.g. ['Doors','Walls'] or ['OST_Doors'] |
| `class_name` | string |  |  | Revit API class: Wall, Floor, FamilyInstance, Level, Grid, View, ViewSheet... |
| `level` | string |  |  | Level name or id |
| `view` | string |  |  | Only elements visible in this view (name, id or 'active') |
| `family` | string |  |  |  |
| `type` | string |  |  |  |
| `name_contains` | string |  |  |  |
| `text` | string |  |  | Free text; every word must appear in category/family/type/name/mark |
| `param_filters` | list of ParamFilter |  |  |  |
| `element_ids` | list of integer |  |  |  |
| `selection` | boolean |  | `False` | Restrict to the current Revit selection |
| `include_types` | boolean |  | `False` | Return element types (FamilySymbol, WallType...) instead of instances |
| `fields` | list of `level` \| `location` \| `bbox` |  |  | Extra fields per element |
| `parameters` | list of string |  |  | Parameter values to include per element |
| `count_only` | boolean |  | `False` |  |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `100` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `get_element_details`

Toolset: `core`

Full details for up to 50 elements: level, location, bbox, workset, phases, host, group/assembly,
parameters with units, geometry.

Full details for up to 50 elements: category, family/type, level, location, bounding box,
workset, phases, design option, group/assembly, host, parameters (with units), geometry.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `element_ids` | list of integer | yes |  |  |
| `parameters` | list of string |  |  | Only these parameters (default: all with values) |
| `include_parameters` | boolean |  | `True` |  |
| `include_type_parameters` | boolean |  | `False` |  |
| `include_parameter_meta` | boolean |  | `False` | Storage type, spec, group, read-only, shared GUID |
| `include_geometry` | boolean |  | `False` | Solid count, volume and surface area |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `get_family_inventory`

Toolset: `model`

Loaded families by category with types, instance counts, in-place/editable flags.

Loaded families grouped by category with their types, instance counts, in-place and editable
flags. Use the family name with family_open to edit it.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category` | string |  |  |  |
| `contains` | string |  |  |  |
| `unused_only` | boolean |  | `False` | Only families with zero placed instances |
| `include_types` | boolean |  | `True` |  |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `100` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `list_families`

Toolset: `legacy`

Flat list of family types, filterable with `contains`.

Get a flat list of available family types in the current Revit model. Use `contains` to filter
by a substring of the family or type name (case-insensitive).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `limit` | integer |  | `50` |  |

### `list_family_categories`

Toolset: `legacy`

Get a list of all family categories in the current Revit model

### `list_levels`

Toolset: `legacy`

Get a list of all levels in the current Revit model

### `list_links`

Toolset: `model`

Revit links (path, load status, pinned, position/rotation) and CAD imports/links.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `include_counts` | boolean |  | `False` | Model element counts per category inside each loaded link |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `get_model_warnings`

Toolset: `model`

Revit warnings grouped by description (most frequent first) with the failing element ids.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `50` |  |
| `ids_per_warning` | integer |  | `30` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `find_views`

Toolset: `model`

Views with id, type, level, scale, template and sheet placement.

Views with ids, type, level, scale, detail level, view template and the sheet they are on.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `view_types` | list of string |  |  | e.g. ['FloorPlan','Section','ThreeD','Schedule','DraftingView'] |
| `name_contains` | string |  |  |  |
| `templates` | `exclude` \| `include` \| `only` |  | `exclude` |  |
| `on_sheet` | boolean |  |  | true: only placed views, false: only unplaced |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `200` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `list_revit_views`

Toolset: `legacy`

Get a list of all exportable views in the current Revit model

### `get_current_view_info`

Toolset: `legacy`

Name, type, id, scale, crop, detail level and discipline of the active view.

Get detailed information about the currently active view in Revit.

Returns comprehensive information including:
- View name, type, and ID
- Scale and detail level
- Crop box status
- View family type
- View discipline
- Template status

### `get_current_view_elements`

Toolset: `legacy`

Elements visible in the active view with category counts (truncated at `limit`).

Get elements visible in the currently active view in Revit.

Returns per element: element_id, name, category, category_id.
Also returns category_counts (always for ALL elements, even if truncated).

If the response contains truncated=true, not all elements were returned.
Check total_elements vs returned_elements and increase limit if needed.

Args:
    limit: Maximum number of elements to return (default 5000).
    include_levels: Include level name and level_id per element. Default false.
    include_location: Include location geometry (point or curve). Default false.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer |  | `5000` |  |
| `include_levels` | boolean |  | `False` |  |
| `include_location` | boolean |  | `False` |  |

### `get_revit_view`

Toolset: `model`

Export a view as an image (png, or jpg for smaller payloads; pixel_size 128-4096).

view_name: the exact view name, or the view element id as a string when
several views share a name (e.g. floor and ceiling plan "Level 1").
Images above RVTSS_IMAGE_MAX_KB (default 4096 KB) are refused with a hint;
errors come back as {status, error, error_kind, hint, request_id}.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `view_name` | string | yes |  |  |
| `image_format` | `png` \| `jpg` |  | `png` |  |
| `pixel_size` | integer |  | `1024` |  |

### `list_sheets`

Toolset: `model`

Sheets with number, name, placed views, title blocks, revisions; counts sheets without views/title
blocks.

Sheets with number, name, placed views, title blocks and revisions, plus counts of sheets
without views or title blocks.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `parameters` | list of string |  |  | Sheet parameters to include, e.g. ['Drawn By'] |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `100` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `get_schedule_data`

Toolset: `model`

Read a schedule's table (column headers and rows as displayed), paginated.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `schedule` | integer or string | yes |  | Schedule view id or exact name |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `200` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `list_category_parameters`

Toolset: `documentation`

Parameters available on a category's elements (for color_splash).

Get available parameters for elements in a category

This tool helps you discover what parameters are available for coloring
by listing all parameters found on elements in the specified category.

Args:
    category_name: Name of the category to check parameters for (e.g., "Walls", "Doors")
    ctx: MCP context for logging

Returns:
    List of available parameters with their types and sample values

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category_name` | string | yes |  |  |

### `revit_selection`

Toolset: `core`

Read the current Revit selection, or select/highlight elements for the user (active document only).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `get` \| `set` \| `add` \| `clear` |  | `get` |  |
| `element_ids` | list of integer |  |  |  |
| `zoom` | boolean |  | `False` | Zoom the view to the newly selected elements |

### `set_parameters`

Toolset: `edit`

Set instance/type parameter values with before/after values. Dimensional numbers need `unit` (or
'900 mm'); bare numbers are rejected.

Set parameter values on elements (instance or type) and return before/after values.

Units are strict: a dimensional parameter needs `unit` (e.g. value=900, unit='mm') or a
string with units ('900 mm'); bare numbers are rejected to prevent feet/mm mistakes.
Yes/No accepts true/false. Element-id parameters accept an id or a material/level name.
Changing a type parameter affects every instance of that type (reported in the result).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `updates` | list of ParameterUpdate |  |  | Per-element updates |
| `element_ids` | list of integer |  |  | Shorthand: same parameter/value for these ids |
| `parameter` | string |  |  |  |
| `value` | string or number or integer or boolean |  |  |  |
| `value_unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` \| `mm2` \| `m2` \| `ft2` \| `mm3` \| `m3` \| `ft3` \| `deg` \| `rad` \| `internal` |  |  |  |
| `target` | `auto` \| `instance` \| `type` |  | `auto` |  |
| `atomic` | boolean |  | `True` | All-or-nothing (default). false = apply what succeeds |
| `dry_run` | boolean |  | `False` |  |
| `confirm` | boolean |  | `False` | Required when more than 100 elements are affected |
| `document` | string |  |  | Document title or path (default: active) |

### `bulk_update_parameter`

Toolset: `edit`

Write one parameter on many elements (ids, selection or filters) with a value or a numbering
template, e.g. selected doors left-to-right: parameter='Mark', selection=true, template='D{n:02}',
sort_by='x'. Use dry_run first.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `parameter` | string | yes |  |  |
| `value` | string or number or integer or boolean |  |  |  |
| `template` | string |  |  | Per-element value template: {n} / {n:03} sequence, {Level}, {Type}, {Family}, {id}, {value} (current), {Any Parameter}. e.g. 'D-{Level}-{n:03}' |
| `element_ids` | list of integer |  |  |  |
| `selection` | boolean |  | `False` |  |
| `categories` | list of string |  |  |  |
| `level` | string |  |  |  |
| `view` | string |  |  |  |
| `family` | string |  |  |  |
| `type` | string |  |  |  |
| `param_filters` | list of ParamFilter |  |  |  |
| `sort_by` | string |  | `id` | id \| name \| x \| y \| z \| xy \| yx \| param:<name> - numbering order |
| `start` | integer |  | `1` |  |
| `step` | integer |  | `1` |  |
| `only_empty` | boolean |  | `False` | Skip elements that already have a value |
| `value_unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` \| `mm2` \| `m2` \| `ft2` \| `mm3` \| `m3` \| `ft3` \| `deg` \| `rad` \| `internal` |  |  |  |
| `allow_type` | boolean |  | `False` |  |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `transform_elements`

Toolset: `edit`

Move, copy, rotate or mirror elements. Copies return the new element ids.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `operation` | `move` \| `copy` \| `rotate` \| `mirror` | yes |  |  |
| `element_ids` | list of integer | yes |  |  |
| `vector` | list of number |  |  | [dx, dy, dz] for move/copy |
| `angle_deg` | number |  |  | Rotation about the vertical axis |
| `center` | list of number |  |  | Rotation centre / mirror plane origin (default: centroid) |
| `each_about_own_center` | boolean |  | `False` |  |
| `plane_normal` | `x` \| `y` |  | `x` | Mirror plane normal (vertical plane) |
| `mirror_copy` | boolean |  | `False` | Mirror: keep originals and create mirrored copies |
| `unpin` | boolean |  | `False` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `delete_elements`

Toolset: `edit`

Delete elements. Without confirm=true it only previews everything Revit would delete (incl.
hosted/dependent elements); show the preview first.

Delete elements. Without confirm=true this only previews: Revit performs the deletion inside a
rolled-back transaction and reports every dependent element that would also be removed (hosted
doors, tags, dimensions...). Show the preview to the user before confirming.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `element_ids` | list of integer | yes |  |  |
| `confirm` | boolean |  | `False` | false (default) = preview of everything Revit would delete |
| `include_pinned` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `create_elements`

Toolset: `edit`

Create levels, grids, walls, floors, family instances (hosted or not) and rooms in one transaction;
returns new ids.

Create levels, grids, walls, floors, family instances (hosted or not) and rooms in one
transaction. Returns new element ids. Doors/windows need host_id of a wall.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | list of object | yes |  | Items by kind (coordinates in `unit`): level: {kind:'level', elevation, name?, create_plan_view?} grid: {kind:'grid', start:[x,y], end:[x,y], name?} wall: {kind:'wall', start, end, level, type?\|type_id?, height?(3000), base_offset?, structural?, flip?} floor: {kind:'floor', boundary:[[x,y],...], level, type?\|type_id?, structural?} family_instance: {kind:'family_instance', family, type\|type_id, point:[x,y,z], level?, host_id?, rotation_deg?} room: {kind:'room', level, point:[x,y], name?, number?} |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `place_family`

Toolset: `legacy`

Place a family instance at a specified location in the Revit model.

Coordinates are decimal feet unless `unit` is given ("mm", "m", "cm", "in", "ft").
rotation is in degrees about the vertical axis. For hosted families (doors,
windows, wall/face based) pass host_id = the wall/host element id.
Numeric `properties` are written in Revit internal units; prefer
set_parameters (which validates units) for dimensional values.
For full control (curves, floors, levels, grids) use create_elements.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `family_name` | string | yes |  |  |
| `type_name` | string |  |  |  |
| `x` | number |  | `0.0` |  |
| `y` | number |  | `0.0` |  |
| `z` | number |  | `0.0` |  |
| `rotation` | number |  | `0.0` |  |
| `level_name` | string |  |  |  |
| `properties` | object |  |  |  |
| `unit` | string |  |  |  |
| `host_id` | integer |  |  |  |

### `manage_element_types`

Toolset: `edit`

Project types: duplicate a type (optionally setting its parameters), rename it, list the
types an element may switch to, or change elements to another type.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list_valid_types` \| `duplicate` \| `rename` \| `change_type` | yes |  |  |
| `type_id` | integer |  |  |  |
| `family` | string |  |  |  |
| `type` | string |  |  |  |
| `category` | string |  |  |  |
| `new_name` | string |  |  |  |
| `parameters` | object |  |  | duplicate: type parameter values for the new type, {name: value} or {name: {value, unit}} |
| `element_id` | integer |  |  | list_valid_types: the element to inspect |
| `element_ids` | list of integer |  |  | change_type: elements to switch to the type |
| `dry_run` | boolean |  | `False` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `color_splash`

Toolset: `documentation`

Color a category's elements in the active view by parameter value.

Color elements in a category based on parameter values

This tool applies color coding to Revit elements within a specified category
based on their parameter values. Elements with the same parameter value
will receive the same color.

Args:
    category_name: Name of the category to color (e.g., "Walls", "Doors", "Windows")
    parameter_name: Name of the parameter to use for coloring (e.g., "Mark", "Type Name")
    use_gradient: Whether to use gradient coloring instead of distinct colors (default: False)
    custom_colors: Optional list of custom colors in hex format (e.g., ["#FF0000", "#00FF00"])
    ctx: MCP context for logging

Returns:
    Results of the coloring operation including statistics and color assignments

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category_name` | string | yes |  |  |
| `parameter_name` | string | yes |  |  |
| `use_gradient` | boolean |  | `False` |  |
| `custom_colors` | list of string |  |  |  |

### `clear_colors`

Toolset: `documentation`

Clear color overrides for elements in a category

This tool removes all color overrides that have been applied to elements
in the specified category, returning them to their default appearance.

Args:
    category_name: Name of the category to clear colors from (e.g., "Walls", "Doors")
    ctx: MCP context for logging

Returns:
    Results of the clear operation including count of elements processed

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category_name` | string | yes |  |  |

### `family_list_templates`

Toolset: `families`

Find family templates (.rft) for a kind (best first) or show which kinds are available/missing.

Inspect family template folders (Revit's FamilyTemplatePath + extra dirs). With `kind`, returns
matching .rft files best first and reports when none exists; without, shows the best template
per kind and which kinds are missing.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | string |  |  | e.g. door, window, furniture, casework, generic_model, generic_model_wall_based, lighting_fixture (family_list_templates lists all) |
| `unit_system` | `metric` \| `imperial` |  |  |  |
| `contains` | string |  |  |  |
| `search_dirs` | list of string |  |  |  |

### `family_create`

Toolset: `families`

Create a new .rfa family from a template (by kind or template_path); opens in the background - pass
its title as `document`.

Create a NEW family document (.rfa) from a Revit family template, chosen by kind (door, window,
furniture, casework, generic_model, ...) or explicit template_path. The family opens in the
background; pass its title as `document` to the other family_* tools.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | string |  |  | e.g. door, window, furniture, casework, generic_model, generic_model_wall_based, lighting_fixture (family_list_templates lists all) |
| `template_path` | string |  |  |  |
| `save_path` | string |  |  | Full .rfa path to save immediately (recommended) |
| `category` | string |  |  | Override the template category, e.g. 'Furniture' |
| `type_name` | string |  |  |  |
| `unit_system` | `metric` \| `imperial` |  | `metric` |  |
| `overwrite` | boolean |  | `False` |  |
| `search_dirs` | list of string |  |  |  |

### `family_open`

Toolset: `families`

Open an existing family for editing - from an .rfa file or a family loaded in the project.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string |  |  | Path of an .rfa file |
| `family_name` | string |  |  | Name of a family loaded in the active project (Edit Family) |

### `family_get_info`

Toolset: `families`

Inspect a family: properties, parameters (formula, shared GUID, associations, labels), types with
values, reference planes, dimensions, forms, nested families.

Inspect a family document: category and family properties, parameters (instance/type, spec,
group, formula, shared GUID, reporting, associations, labelled dimensions), types with values,
reference planes, dimensions, solid/void forms with associated parameters, and nested families.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `include` | list of `parameters` \| `types` \| `reference_planes` \| `dimensions` \| `forms` \| `nested` \| `properties` |  |  |  |
| `include_builtin` | boolean |  | `False` |  |
| `max_types` | integer |  | `50` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |

### `family_set_properties`

Toolset: `families`

Change the family category and family-level settings (shared, work plane based, always vertical...).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `category` | string |  |  |  |
| `set` | object |  |  | {work_plane_based, always_vertical, shared, room_calculation_point, cut_with_voids} |
| `dry_run` | boolean |  | `False` |  |

### `family_add_parameters`

Toolset: `families`

Add family parameters (type/instance, any data type, value, formula, reporting, or shared with its
GUID). Formulas are checked before Revit applies them.

Add family parameters (type or instance; any data type; optional initial value, formula,
reporting; or shared definitions with their existing GUID). Existing names are skipped. Formulas
are pre-checked for unknown names and circular references, then validated by Revit.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `parameters` | list of FamilyParameterSpec | yes |  |  |
| `document` | string |  |  | Family document title/path (default: active) |
| `naming_pattern` | string |  |  | Regex every new name must match |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_edit_parameters`

Toolset: `families`

Edit existing family parameters. Shared parameters keep their GUID and cannot be renamed
(Revit API limitation) - use replace_with_shared to swap definitions.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `remove` \| `rename` \| `set_formula` \| `set_instance` \| `set_reporting` \| `replace_with_shared` \| `associate` \| `set_values` | yes |  |  |
| `parameters` | list of object |  |  | remove: {name} \| rename: {name, new_name} \| set_formula: {name, formula} (empty formula clears) \| set_instance: {name, instance} \| set_reporting: {name, reporting} \| replace_with_shared: {name, shared_name?\|guid?, group?, instance?} \| associate: {element_id, element_parameter, name} (name omitted = dissociate) \| set_values: {name, value, unit?} on the current type |
| `document` | string |  |  | Family document title/path (default: active) |
| `shared_parameter_file` | string |  |  |  |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |

### `family_manage_types`

Toolset: `families`

Family types: list, create/upsert, duplicate, rename, delete, set values per type; export/import
type catalogs.

List, create, duplicate, rename, delete family types and set per-type values; export or import a
Revit type catalog (.txt). Example: three door sizes -> action='create',
types=[{name:'900x2100', values:{Width:900, Height:2100}}, ...].

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `upsert` \| `duplicate` \| `rename` \| `delete` \| `set_values` \| `export_catalog` \| `import_catalog` |  | `list` |  |
| `types` | list of object |  |  | create/upsert: {name, values: {param: value\|{value, unit}}, based_on?} \| duplicate: {source, new_name, values?} \| rename: {name, new_name} \| delete: {name} \| set_values: {name, values} |
| `document` | string |  |  | Family document title/path (default: active) |
| `parameters` | list of string |  |  | list: only these parameters |
| `path` | string |  |  | Type catalog .txt path (default: next to the .rfa) |
| `catalog_text` | string |  |  |  |
| `overwrite` | boolean |  | `False` |  |
| `strict` | boolean |  | `True` | Roll back everything if any value fails |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` | Unit for plain numeric values of length parameters |
| `dry_run` | boolean |  | `False` |  |

### `family_create_reference_planes`

Toolset: `families`

Create named reference planes (x: left/right, y: front/back, z: horizontal) at offsets, or list them.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `planes` | list of ReferencePlaneSpec |  |  |  |
| `action` | `create` \| `list` |  | `create` |  |
| `document` | string |  |  | Family document title/path (default: active) |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_create_form`

Toolset: `families`

Create solid/void extrusion, blend, revolution or sweep on a work plane, with
material/visibility/end parameter links, subcategory and face locking.

Create solid or void extrusions, blends, revolutions and sweeps on a work plane, optionally
associating material / visibility / extrusion end to family parameters, setting detail-level
visibility and subcategory, cutting solids with voids and locking faces to reference planes.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `forms` | list of FormSpec | yes |  |  |
| `document` | string |  |  | Family document title/path (default: active) |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_add_dimension`

Toolset: `families`

Dimension between parallel reference planes (or Ref. Level) and label it with a parameter
(e.g. Left-Right labelled Width), add EQ constraints (Left-Center-Right) or lock it.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `dimensions` | list of DimensionSpec | yes |  |  |
| `document` | string |  |  | Family document title/path (default: active) |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_align_geometry`

Toolset: `families`

Lock form faces to the reference planes they lie on, so geometry follows labelled dimensions.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `form_ids` | list of integer |  |  | Default: all solid forms |
| `planes` | list of string |  |  | Default: every reference plane + Ref. Level |
| `lock` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_build_parametric_box`

Toolset: `families`

One call: fully constrained parametric box (planes, Width/Depth labels with EQ, locked extrusion,
Height, Material) + flex check. Base for furniture/casework/equipment.

Build a genuinely parametric box in one step: Left/Right/Front/Back reference planes centred on
the template's centre planes, Width/Depth labelled dimensions with EQ, a solid extrusion with
all four sides locked, Height driving the extrusion end and a Material parameter - then flex it
to prove the geometry follows the parameters. Ideal base for furniture, casework and equipment.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `width` | number |  | `900` |  |
| `depth` | number |  | `600` |  |
| `height` | number |  | `750` |  |
| `width_parameter` | string |  | `Width` |  |
| `depth_parameter` | string |  | `Depth` |  |
| `height_parameter` | string |  | `Height` |  |
| `material_parameter` | string |  | `Material` | Material parameter name ('' to skip) |
| `instance_parameters` | boolean |  | `False` |  |
| `center_equality` | boolean |  | `True` |  |
| `subcategory` | string |  |  |  |
| `flex_check` | boolean |  | `True` | Flex x1.5 / x0.5 afterwards and verify the bounding box |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_nested`

Toolset: `families`

Load a family into the family being edited and place it, linking nested parameters to host
family parameters (parameter associations).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `load` \| `place` | yes |  |  |
| `document` | string |  |  | Family document title/path (default: active) |
| `path` | string |  |  | load: .rfa to nest |
| `family` | string |  |  |  |
| `type` | string |  |  |  |
| `point` | list of number |  |  |  |
| `associate` | object |  |  | place: {nested parameter: host family parameter} |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_flex_test`

Toolset: `families`

Flex a family through types/values, measure geometry, report constraint errors and parameters with
no effect; all rolled back.

Flex a family: apply types / parameter values, regenerate and measure geometry, report Revit
constraint errors and parameters with no geometric effect. Everything is rolled back.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `cases` | list of FlexCase |  |  | Default: every type, then +20% on each length parameter |
| `expect` | object |  |  | Bounding box axis -> parameter, e.g. {x:'Width'} |
| `tolerance` | number |  | `0.5` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |

### `family_validate`

Toolset: `families`

QC a family: category, formulas, parameters that drive nothing, type values, geometry, labelled
dimensions, warnings - with severity and fixes.

Quality-control a family: category, formulas (syntax, unknown names, circular references),
parameters that drive nothing, types missing values or with zero dimensions, invalid geometry,
missing labelled dimensions (not parametric) and Revit warnings - with severities and fixes.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `expected_category` | string |  |  |  |
| `parameter_naming_pattern` | string |  |  |  |

### `family_save`

Toolset: `families`

Save the family document. Existing files are backed up to %APPDATA%/RVTSS/backups before being
overwritten.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `save_path` | string |  |  | Save As path (.rfa). Omit to save in place |
| `overwrite` | boolean |  | `False` |  |
| `compact_file` | boolean |  | `False` |  |
| `backup` | boolean |  | `True` | Copy the existing file to %APPDATA%/RVTSS/backups first |

### `family_load_into_project`

Toolset: `families`

Load (or reload) the family into a project and verify that all its types arrived.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `project` | string |  |  | Target project title (default: active/only project) |
| `overwrite` | boolean |  | `True` | Reload if the family already exists in the project |
| `overwrite_parameter_values` | boolean |  | `False` | Also overwrite type parameter values in the project |

### `family_close`

Toolset: `families`

Close a background family document (refuses to drop unsaved changes unless discard_changes=true).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title/path (default: active) |
| `save` | boolean |  | `False` |  |
| `discard_changes` | boolean |  | `False` | Required to close with unsaved changes and save=false |

### `list_project_parameters`

Toolset: `parameters`

Project parameters with binding (instance/type), categories, data type, group, shared GUID,
plus names defined more than once.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `document` | string |  |  | Document title or path (default: active) |

### `shared_parameters`

Toolset: `parameters`

Shared parameters: read_file, create_definitions (GUIDs preserved), create_file, bind to categories
(instance/type).

Shared parameters: read_file (GUIDs, duplicates, project use), create_definitions (existing
names/GUIDs reused, never rewritten), create_file, bind to categories as instance/type (extends
existing bindings). E.g. create_definitions [{name:'Fire Rating'}] then bind
categories=['Doors','Walls'].

Existing names are reused and their GUIDs never changed; supplied GUIDs are honoured. Existing
bindings are extended with ReInsert, never replaced; a different parameter with the same name is
refused.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `read_file` \| `create_definitions` \| `create_file` \| `bind` | yes |  |  |
| `shared_parameter_file` | string |  |  | Default: the file configured in Revit |
| `definitions` | list of SharedDefinitionSpec |  |  | create_definitions |
| `create_file` | boolean |  | `False` |  |
| `set_as_current` | boolean |  | `False` | create_file: make it Revit's shared parameter file |
| `name` | string |  |  | bind: shared parameter name |
| `guid` | string |  |  | bind: pick by GUID |
| `categories` | list of string |  |  | bind: e.g. ['Doors','Walls'] |
| `binding` | `instance` \| `type` |  | `instance` |  |
| `group` | `dimensions` \| `constraints` \| `construction` \| `data` \| `identity_data` \| `materials` \| `graphics` \| `text` \| `general` \| `phasing` \| `visibility` \| `fire_protection` \| `structural` \| `mechanical` \| `electrical` \| `plumbing` \| `energy_analysis` \| `ifc` \| `other` |  | `data` | bind: properties palette group |
| `vary_between_groups` | boolean |  |  |  |
| `contains` | string |  |  |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `global_parameters`

Toolset: `parameters`

Global parameters: list (value, formula, affected elements, labelled dimensions), create, set
value/formula, associate element parameters, and label / unlabel project dimensions.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `set_value` \| `set_formula` \| `associate` \| `dissociate` \| `label_dimensions` \| `unlabel_dimensions` |  | `list` |  |
| `name` | string |  |  |  |
| `type` | `length` \| `area` \| `volume` \| `angle` \| `slope` \| `number` \| `integer` \| `text` \| `multiline_text` \| `url` \| `yesno` \| `material` \| `image` \| `currency` \| `mass` \| `force` |  | `length` |  |
| `value` | string or number or integer or boolean |  |  |  |
| `value_unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` \| `mm2` \| `m2` \| `ft2` \| `mm3` \| `m3` \| `ft3` \| `deg` \| `rad` \| `internal` |  |  |  |
| `formula` | string |  |  |  |
| `element_ids` | list of integer |  |  | associate/dissociate targets; dimension ids for label_dimensions |
| `parameter` | string |  |  | associate: element parameter to drive |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `audit_parameters`

Toolset: `parameters`

Audit parameters on elements: missing, empty, invalid values, wrong types, duplicate or misnamed
definitions.

Audit parameters on a set of elements: missing, empty, invalid values, wrong data types, and
duplicate / badly named project parameter definitions. Returns findings with element ids.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `categories` | list of string |  |  |  |
| `element_ids` | list of integer |  |  |  |
| `view` | string |  |  |  |
| `level` | string |  |  |  |
| `required` | list of string |  |  | Parameters that must exist and be filled |
| `rules` | list of AuditRule |  |  | Value rules, e.g. {name:'Fire Rating', op:'regex', value:'^(30\|60\|90\|120)$'} |
| `expected_types` | object |  |  | {param: type} data type check |
| `naming_pattern` | string |  |  | Regex all project parameter names must match |
| `include_type_parameters` | boolean |  | `True` |  |
| `check_empty` | boolean |  | `True` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `export_parameters`

Toolset: `parameters`

Export element parameter values to CSV (ElementId, UniqueId, Category, Family, Type + columns).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `parameters` | list of string | yes |  |  |
| `categories` | list of string |  |  |  |
| `element_ids` | list of integer |  |  |  |
| `view` | string |  |  |  |
| `level` | string |  |  |  |
| `param_filters` | list of ParamFilter |  |  |  |
| `path` | string |  |  | Write a .csv file on the Revit machine (else returned inline) |
| `overwrite` | boolean |  | `False` |  |
| `value_mode` | `display` \| `raw` |  | `display` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `import_parameters`

Toolset: `parameters`

Import parameter values from CSV (ElementId or UniqueId column + parameter columns). dry_run by
default.

Import parameter values from CSV (needs an ElementId or UniqueId column; other columns are
parameter names). Defaults to dry_run=true - review the changes, then run with dry_run=false.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string |  |  |  |
| `csv_text` | string |  |  |  |
| `units` | object |  |  | {column: unit} for numeric dimensional columns |
| `ignore_columns` | list of string |  |  |  |
| `skip_empty` | boolean |  | `True` |  |
| `allow_type` | boolean |  | `False` |  |
| `atomic` | boolean |  | `False` |  |
| `dry_run` | boolean |  | `True` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `map_parameters`

Toolset: `parameters`

Copy values from existing parameters into your BIM-standard parameters (converting between
storage types through display values), or apply an IFC/COBie preset. Source values are never deleted.

Presets list the target parameter names; unverified names are reported in unverified_targets
and targets that do not exist on an element are skipped. Office presets:
%APPDATA%/RVTSS/presets/<name>.json = {"description", "mappings": [{from, to, categories?}]}.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `mappings` | list of object |  |  | [{from: 'Old Param', to: 'Standard Param'}] |
| `preset` | string |  |  | ifc_overrides \| ifc_common_psets \| cobie_type \| cobie_component \| cobie_space \| office preset |
| `categories` | list of string |  |  |  |
| `element_ids` | list of integer |  |  |  |
| `view` | string |  |  |  |
| `level` | string |  |  |  |
| `only_empty_target` | boolean |  | `False` |  |
| `allow_type` | boolean |  | `False` |  |
| `atomic` | boolean |  | `False` |  |
| `dry_run` | boolean |  | `True` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `create_view`

Toolset: `documentation`

Create plans, 3D (optionally boxed to elements), sections, elevations, drafting views or duplicates,
with name/template/scale.

Create plans, 3D views (optionally section-boxed to elements), sections framing elements,
elevations, drafting views, or duplicate a view - with name, template, scale and detail level.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | `floor_plan` \| `ceiling_plan` \| `structural_plan` \| `area_plan` \| `three_d` \| `section` \| `elevation` \| `drafting` \| `duplicate` | yes |  |  |
| `name` | string |  |  |  |
| `level` | string |  |  | plans: level name or id |
| `element_ids` | list of integer |  |  | three_d: section box around them; section: framed elements |
| `margin` | number |  | `500` | Box margin around element_ids in `unit` |
| `looking` | `north` \| `south` \| `east` \| `west` |  | `north` | section direction |
| `plan_view` | integer or string |  |  | elevation: plan view hosting the marker |
| `point` | list of number |  |  | elevation: marker location |
| `facing` | `north` \| `south` \| `east` \| `west` |  | `north` |  |
| `source_view` | integer or string |  |  | View id, exact name, or 'active' |
| `duplicate_option` | `duplicate` \| `with_detailing` \| `as_dependent` |  | `duplicate` |  |
| `template` | string |  |  |  |
| `scale` | integer |  |  |  |
| `detail_level` | `coarse` \| `medium` \| `fine` |  |  |  |
| `view_family_type` | string |  |  |  |
| `area_scheme` | string |  |  | area_plan: area scheme name (default: first) |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `view_graphics`

Toolset: `documentation`

Per-view graphics: element/category overrides, hide/unhide, temporary isolate, category visibility,
view templates, scale, detail level.

Per-view graphics: element/category overrides (color, fill, line weight, halftone,
transparency), hide/unhide, temporary isolate/hide, category visibility, view templates, scale
and detail level. Warns when a view template controls the setting.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `override` \| `reset` \| `hide` \| `unhide` \| `temporary_isolate` \| `temporary_hide` \| `reset_temporary` \| `category_hidden` \| `apply_template` \| `remove_template` \| `set_scale` \| `set_detail_level` | yes |  |  |
| `view` | integer or string |  | `active` | View id, exact name, or 'active' |
| `element_ids` | list of integer |  |  |  |
| `categories` | list of string |  |  |  |
| `color` | string |  |  | override: hex color '#FF0000' |
| `fill` | boolean |  | `True` | override: also apply a solid surface fill |
| `line_weight` | integer |  |  |  |
| `halftone` | boolean |  |  |  |
| `transparency` | integer |  |  |  |
| `hidden` | boolean |  | `True` | category_hidden: hide (true) or show (false) |
| `template` | string |  |  |  |
| `scale` | integer |  |  |  |
| `detail_level` | `coarse` \| `medium` \| `fine` |  |  |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `manage_sheets`

Toolset: `documentation`

Create sheets (with title blocks) and place views or schedules on them.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `create` \| `place_view` \| `list_titleblocks` | yes |  |  |
| `sheets` | list of object |  |  | create: [{number, name, title_block?}] |
| `title_block` | string |  |  | Default title block type name or id |
| `sheet_id` | integer |  |  |  |
| `view` | integer or string |  |  | place_view: view or schedule |
| `location` | list of number |  |  | place_view: [x, y] on the sheet in `unit` |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `create_schedule`

Toolset: `documentation`

Create a schedule for a category with fields, sorting and filters.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category` | string | yes |  |  |
| `fields` | list of string | yes |  | Schedulable field names, e.g. ['Mark','Type','Width','Fire Rating'] |
| `name` | string |  |  |  |
| `sort_by` | list of string |  |  |  |
| `filters` | list of object |  |  | [{field, type: 'Equal'\|'Contains'\|'GreaterThan'\|..., value, unit?}] - numbers for numeric fields (with unit for lengths), text for text fields |
| `itemized` | boolean |  | `True` |  |
| `strict` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `batch_rename`

Toolset: `documentation`

Rename views/sheets/levels/families/types/rooms... with find/replace/regex/prefix/suffix/case;
detects collisions. dry_run by default.

Rename many items to a naming standard with find/replace (or regex), prefix, suffix and case.
Detects collisions and invalid characters before changing anything. Defaults to dry_run=true.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | `views` \| `view_templates` \| `sheets` \| `levels` \| `grids` \| `families` \| `family_types` \| `system_types` \| `materials` \| `rooms` | yes |  |  |
| `find` | string |  |  |  |
| `replace` | string |  | `` |  |
| `regex` | boolean |  | `False` |  |
| `prefix` | string |  | `` |  |
| `suffix` | string |  | `` |  |
| `case` | `upper` \| `lower` \| `title` |  |  |  |
| `include_regex` | string |  |  | Only rename names matching this regex |
| `element_ids` | list of integer |  |  |  |
| `field` | `name` \| `number` |  | `name` | sheets: rename the number instead of the name |
| `dry_run` | boolean |  | `True` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `manage_groups`

Toolset: `documentation`

List group types (instances, unused types), create a model group from elements, or ungroup.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `ungroup` |  | `list` |  |
| `element_ids` | list of integer |  |  |  |
| `name` | string |  |  |  |
| `group_id` | integer |  |  |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `manage_assemblies`

Toolset: `documentation`

Assemblies: create, add/remove members, rename, create assembly views and sheet.

Assemblies: create from elements (with a name), add/remove members, rename, and generate
assembly views (3D, elevations/sections, parts list, material takeoff) plus an assembly sheet.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `add_members` \| `remove_members` \| `rename` \| `create_views` |  | `list` |  |
| `element_ids` | list of integer |  |  |  |
| `assembly_id` | integer |  |  |  |
| `name` | string |  |  |  |
| `naming_category` | string |  |  |  |
| `views` | list of `3d` \| `front` \| `back` \| `left` \| `right` \| `top` \| `bottom` \| `detail_front` \| `detail_side` \| `horizontal` \| `parts_list` \| `material_takeoff` |  |  | create_views: which assembly views to create |
| `create_sheet` | boolean |  | `False` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `run_model_checks`

Toolset: `qc`

BIM QC report (warnings, duplicates, naming, families/types, CAD, links, rooms, views, sheets,
required parameters, groups) with severity, ids and fixes.

BIM quality report: warnings, duplicate elements, naming standards, near-duplicate families,
duplicate types, unused / in-place families, CAD imports, link status, rooms, views not on
sheets, sheet completeness, required parameters and unused groups. Each finding has severity,
element ids and a recommended correction.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `checks` | list of `warnings` \| `duplicates` \| `naming` \| `similar_family_names` \| `duplicate_types` \| `unused_families` \| `in_place_families` \| `cad_imports` \| `links` \| `rooms` \| `views_not_on_sheets` \| `sheets` \| `required_parameters` \| `groups` \| `iso19650` \| `view_audit` |  |  | Default: all checks |
| `rules` | object |  |  | Project rules (merged over %APPDATA%/RVTSS/qc_rules.json): {naming: {views\|sheets\|levels\|families\|types: {pattern, severity, description}}, required_parameters: [{categories, parameters, severity}], sheet_parameters: [...]} |
| `sheet_parameters` | list of string |  |  |  |
| `duplicate_tolerance` | number |  | `1.0` | Distance in `unit` for duplicate detection |
| `min_severity` | `info` \| `warning` \| `error` \| `critical` |  | `info` |  |
| `max_findings` | integer |  | `200` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `check_clashes`

Toolset: `qc`

Hard and clearance clashes between two element sets (also against a link), with level, grid zone
and nearest grid intersection; export_clash_report writes CSV/HTML.

Hard clash detection (solid intersection) between two element sets in the model or against a
loaded Revit link; with clearance > 0 also pairs closer than the clearance (sampled distance).
Returns clashing pairs with ids, categories, types, type (hard/clearance), distance, level,
grid_zone and nearest_grid, grouped when group_by is given.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `set_a` | object | yes |  | Element query, e.g. {categories: ['Ducts'], level: 'Level 2'} |
| `set_b` | object | yes |  | Element query; add link_instance_id to test against a Revit link |
| `max_pairs` | integer |  | `200` |  |
| `max_elements` | integer |  | `2000` |  |
| `compute_volume` | boolean |  | `False` |  |
| `clearance` | number |  | `0.0` | Soft clash distance in `unit` (0 = hard only) |
| `group_by` | list of `pair` \| `type_pair` \| `level` \| `grid_zone` |  |  |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `export_clash_report`

Toolset: `qc`

Clash check (hard + clearance) written to CSV/HTML: ids, levels, grid zone, nearest grid.

Groups clashes by element category pair, level and grid zone (default all three). Files are
written on the MCP machine. dry_run checks the sets and returns the planned file paths.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `set_a` | object | yes |  | Element query, e.g. {categories: ['Ducts']} |
| `set_b` | object | yes |  | Element query (+link_instance_id) |
| `clearance` | number |  | `0.0` | Soft-clash clearance in `unit` (0 = hard only) |
| `group_by` | list of `pair` \| `type_pair` \| `level` \| `grid_zone` |  |  |  |
| `name` | string |  | `clash_report` |  |
| `output_folder` | string |  |  | Default: RVTSS_REPORT_DIR |
| `formats` | list of `csv` \| `html` |  |  |  |
| `max_pairs` | integer |  | `500` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `model_snapshot`

Toolset: `qc`

Save a JSON snapshot (ids, types, levels, locations, tracked parameters) for later compare_models.

Save a JSON snapshot of the model (ids, UniqueIds, types, levels, locations, tracked parameter
values) to %APPDATA%/RVTSS/snapshots for later change detection with compare_models.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `create` \| `list` |  | `create` |  |
| `name` | string |  |  |  |
| `path` | string |  |  |  |
| `categories` | list of string |  |  |  |
| `level` | string |  |  |  |
| `track_parameters` | list of string |  |  | Parameters whose values are recorded (default Mark, Comments) |
| `hash_all_parameters` | boolean |  | `False` | Detect any parameter change (slower) |
| `link_instance_id` | integer |  |  | Snapshot a Revit link (coordinates transformed to the host) |
| `overwrite` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `compare_models`

Toolset: `qc`

Change detection: snapshot vs live model or another snapshot (added/removed/modified), or match two
element sets by location (design vs shop model).

Change detection and model comparison. snapshots: added / removed / modified elements (type,
level, moved, parameter changes) between a baseline snapshot and the live model or another
snapshot. match: pair elements of two sets by location (design model vs shop drawing /
fabrication link) and report unmatched elements and type substitutions.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `mode` | `snapshots` \| `match` |  | `snapshots` |  |
| `baseline` | string |  |  | snapshots: baseline snapshot name |
| `current` | string |  |  | snapshots: second snapshot (default: the live model) |
| `categories` | list of string |  |  |  |
| `move_tolerance` | number |  | `1.0` |  |
| `source` | object |  |  | match: element query (+link_instance_id), e.g. the design model |
| `target` | object |  |  | match: element query (+link_instance_id), e.g. the shop model link |
| `match_on` | list of `category` \| `family` \| `type` \| `level` |  |  | match: keys that must be equal |
| `tolerance` | number |  | `50.0` | match: max distance in mm |
| `max_items` | integer |  | `300` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `audit_family_library`

Toolset: `families`

Audit a folder of .rfa files (opened read-only, never saved): category, size, parameters, nested
families, warnings, family_validate errors, naming.

Naming uses qc_rules.json naming.families and the iso19650 'families' target. dry_run lists
the files that would be opened. Backup files (*.0001.rfa) are skipped.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder` | string | yes |  | Folder of .rfa files (Revit machine) |
| `recursive` | boolean |  | `True` |  |
| `name_contains` | string |  |  |  |
| `max_files` | integer |  | `50` |  |
| `run_validation` | boolean |  | `True` | Run family_validate on each family |
| `max_size_kb` | integer |  | `2048` |  |
| `include_details` | boolean |  | `False` |  |
| `dry_run` | boolean |  | `False` |  |

### `export_to_excel`

Toolset: `parameters`

Write parameter values (one sheet per category, units in headers) and schedules to .xlsx.

value_mode raw writes numbers in `unit` with the unit in the column header; display writes
Revit's formatted text. Values starting with = + - @ are written as text.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `output_path` | string | yes |  | .xlsx path (relative = report folder) |
| `categories` | list of string |  |  | One sheet per category |
| `parameters` | list of string |  |  | Parameter columns for category sheets |
| `schedules` | list of integer or string |  |  | Schedule names/ids, one sheet each |
| `level` | string |  |  |  |
| `value_mode` | `raw` \| `display` |  | `raw` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `overwrite` | boolean |  | `False` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Document title or path (default: active) |

### `execute_revit_code`

Toolset: `code`

Run IronPython in Revit (doc, uidoc, DB, revit; print output returned). Prefer dedicated tools;
transaction_mode none/auto/dry_run/read_only.

Execute IronPython code directly in Revit context.

The code has access to:
- doc: The active Revit document
- uidoc: The active UIDocument (use for UI operations like switching the active view)
- DB: Revit API Database namespace
- revit: pyRevit module
- print: Function to output text (returned in response)

Prefer the dedicated RVTSS tools (find_elements, set_parameters, family_*,
...) - they validate input and support dry runs. Use this for anything
they do not cover.

transaction_mode:
- None/"none" (default): no transaction is opened automatically.
- "auto": the code runs in one transaction, committed on success and
  rolled back if it raises. Do not start your own Transaction then.
- "dry_run": like auto but always rolled back - test modifying code safely.
- "read_only": no transaction; opening one is refused and any change is rolled back.

May be disabled on the Revit machine (RVTSS_ALLOW_CODE_EXECUTION=0); every call is
logged with the code (secrets redacted).

With the default mode, wrap model-modifying code yourself:
    t = DB.Transaction(doc, "My change")
    t.Start()
    # ... modify model ...
    t.Commit()

For UI operations that cannot run inside a transaction (e.g. switching the active view):
    all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
    target = next((v for v in all_views if v.Name == "Level 1"), None)
    if target:
        uidoc.ActiveView = target

Tips:
- Use getattr(element, 'Name', 'N/A') to safely access the Name property
- Check elements exist before use: if element:
- Use hasattr() for optional properties

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `description` | string |  | `Code execution` |  |
| `transaction_mode` | string |  |  |  |

