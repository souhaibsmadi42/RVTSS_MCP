# RVTSS MCP tool reference

Generated from the live tool registry by `scripts/generate_tool_docs.py` - do not edit by hand.

74 tools. **Origin**: *retained* = from the original MCP (some improved), *new* = added by RVTSS. **Mode**: read-only / modifies / destructive (MCP tool annotations).

## Session & status

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `get_revit_status` | retained | read-only | Check if the Revit MCP API is active and responding |
| `get_session_info` | new | read-only | Revit version/build, RVTSS version, active document and view, selection count, ALL open |
| `get_revit_model_info` | retained | read-only | Get comprehensive information about the current Revit model |
| `list_revit_installations` | retained | read-only | Discover all Revit versions installed on this system. |
| `launch_revit` | retained | modifies | Launch Revit on this machine, optionally opening a file. |
| `open_document` | retained | modifies | Open a Revit document file in the running Revit instance. |
| `close_document` | retained | destructive | Close the active Revit document. |
| `save_document` | retained | modifies | Save the active Revit document. |
| `sync_with_central` | retained | modifies | Synchronize the active workshared document with central. |

## Model intelligence

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `get_project_overview` | new | read-only | Project information parameters, display units, levels (elevations), grids, phases, |
| `find_elements` | new | read-only | Find elements with combinable filters; returns ids, names, category/family/type and |
| `get_element_details` | new | read-only | Full details for up to 50 elements: category, family/type, level, location, bounding box, |
| `get_family_inventory` | new | read-only | Loaded families grouped by category with their types, instance counts, in-place and |
| `list_families` | retained | read-only | Get a flat list of available family types in the current Revit model. |
| `list_family_categories` | retained | read-only | Get a list of all family categories in the current Revit model |
| `list_levels` | retained | read-only | Get a list of all levels in the current Revit model |
| `list_links` | new | read-only | Revit links (path, load status, pinned, position/rotation) and CAD imports/links. |
| `get_model_warnings` | new | read-only | Revit warnings grouped by description (most frequent first) with the failing element ids. |
| `find_views` | new | read-only | Views with ids, type, level, scale, detail level, view template and the sheet they are on. |
| `list_revit_views` | retained | read-only | Get a list of all exportable views in the current Revit model |
| `get_current_view_info` | retained | read-only | Get detailed information about the currently active view in Revit. |
| `get_current_view_elements` | retained | read-only | Get elements visible in the currently active view in Revit. |
| `get_revit_view` | retained | read-only | Export a specific Revit view as a PNG image. |
| `list_sheets` | new | read-only | Sheets with number, name, placed views, title blocks and revisions, plus counts of sheets |
| `get_schedule_data` | new | read-only | Read a schedule's table (column headers and rows as displayed), paginated. |
| `list_category_parameters` | retained | read-only | Get available parameters for elements in a category |
| `revit_selection` | new | modifies | Read the current Revit selection, or select/highlight elements for the user (active document only). |

## Element editing

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `set_parameters` | new | modifies | Set parameter values on elements (instance or type) and return before/after values. |
| `bulk_update_parameter` | new | modifies | Write one parameter on many elements (by ids, selection or filters) using a fixed value or a |
| `transform_elements` | new | modifies | Move, copy, rotate or mirror elements. Copies return the new element ids. |
| `delete_elements` | new | destructive | Delete elements. Without confirm=true this only previews: Revit performs the deletion inside a |
| `create_elements` | new | modifies | Create levels, grids, walls, floors, family instances (hosted or not) and rooms in one |
| `place_family` | retained | modifies | Place a family instance at a specified location in the Revit model. |
| `manage_element_types` | new | modifies | Project types: duplicate a type (optionally setting its parameters), rename it, list the |
| `color_splash` | retained | modifies | Color elements in a category based on parameter values |
| `clear_colors` | retained | modifies | Clear color overrides for elements in a category |

## Family creation & editing

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `family_list_templates` | new | read-only | Inspect family template folders (Revit's FamilyTemplatePath + extra dirs). With `kind`, returns |
| `family_create` | new | modifies | Create a NEW family document (.rfa) from a Revit family template, chosen by kind (door, window, |
| `family_open` | new | modifies | Open an existing family for editing - from an .rfa file or a family loaded in the project. |
| `family_get_info` | new | read-only | Inspect a family document: category and family properties, parameters (instance/type, spec, group, |
| `family_set_properties` | new | modifies | Change the family category and family-level settings (shared, work plane based, always vertical...). |
| `family_add_parameters` | new | modifies | Add family parameters (type or instance; any data type; optional initial value, formula, |
| `family_edit_parameters` | new | modifies | Edit existing family parameters. Shared parameters keep their GUID and cannot be renamed |
| `family_manage_types` | new | modifies | List, create, duplicate, rename, delete family types and set per-type values; export or import a |
| `family_create_reference_planes` | new | modifies | Create named reference planes (x: left/right, y: front/back, z: horizontal) at offsets, or list them. |
| `family_create_form` | new | modifies | Create solid or void extrusions, blends, revolutions and sweeps on a work plane, optionally |
| `family_add_dimension` | new | modifies | Dimension between parallel reference planes (or Ref. Level) and label it with a parameter |
| `family_align_geometry` | new | modifies | Lock form faces to the reference planes they lie on, so geometry follows labelled dimensions. |
| `family_build_parametric_box` | new | modifies | Build a genuinely parametric box in one step: Left/Right/Front/Back reference planes centred |
| `family_nested` | new | modifies | Load a family into the family being edited and place it, linking nested parameters to host |
| `family_flex_test` | new | read-only | Flex a family: apply types / parameter values, regenerate and measure geometry, report Revit |
| `family_validate` | new | read-only | Quality-control a family: category, formulas (syntax, unknown names, circular references), |
| `family_save` | new | modifies | Save the family document. Existing files are backed up to %APPDATA%/RVTSS/backups before being |
| `family_load_into_project` | new | modifies | Load (or reload) the family into a project and verify that all its types arrived. |
| `family_close` | new | destructive | Close a background family document (refuses to drop unsaved changes unless discard_changes=true). |

## Parameter management

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `list_project_parameters` | new | read-only | Project parameters with binding (instance/type), categories, data type, group, shared GUID, |
| `shared_parameters` | new | modifies | Shared parameter workflow: read the file (GUIDs, groups, duplicates, which are already in the |
| `global_parameters` | new | modifies | Global parameters: list (value, formula, affected elements), create, set value/formula and |
| `audit_parameters` | new | read-only | Audit parameters on a set of elements: missing, empty, invalid values, wrong data types, and |
| `export_parameters` | new | read-only | Export element parameter values to CSV (ElementId, UniqueId, Category, Family, Type + columns). |
| `import_parameters` | new | modifies | Import parameter values from CSV (needs an ElementId or UniqueId column; other columns are |
| `map_parameters` | new | modifies | Copy values from existing parameters into your BIM-standard parameters (converting between |

## Documentation

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `create_view` | new | modifies | Create plans, 3D views (optionally section-boxed to elements), sections framing elements, |
| `view_graphics` | new | modifies | Per-view graphics: element/category overrides (color, fill, line weight, halftone, |
| `manage_sheets` | new | modifies | Create sheets (with title blocks) and place views or schedules on them. |
| `create_schedule` | new | modifies | Create a schedule for a category with fields, sorting and filters. |
| `batch_rename` | new | modifies | Rename many items to a naming standard with find/replace (or regex), prefix, suffix and case. |
| `manage_groups` | new | modifies | List group types (instances, unused types), create a model group from elements, or ungroup. |
| `manage_assemblies` | new | modifies | Assemblies: create from elements (with a name), add/remove members, rename, and generate |

## Coordination & QC

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `run_model_checks` | new | read-only | BIM quality report: warnings, duplicate elements, naming standards, near-duplicate families, |
| `check_clashes` | new | read-only | Hard clash detection (solid intersection) between two element sets in the model or against a |
| `model_snapshot` | new | modifies | Save a JSON snapshot of the model (ids, UniqueIds, types, levels, locations, tracked parameter |
| `compare_models` | new | read-only | Change detection and model comparison. snapshots: added / removed / modified elements (type, |

## Advanced

| Tool | Origin | Mode | Purpose |
|---|---|---|---|
| `execute_revit_code` | retained | destructive | Execute IronPython code directly in Revit context. |

## Parameters

### `get_revit_status`

Check if the Revit MCP API is active and responding

### `get_session_info`

Revit version/build, RVTSS version, active document and view, selection count, ALL open
        documents (projects and background family documents - use their title as `document`), linked
        documents, shared parameter file and family template path. Call this first in a session.

### `get_revit_model_info`

Get comprehensive information about the current Revit model

### `list_revit_installations`

Discover all Revit versions installed on this system.

        Returns a list of installed Revit versions with their executable paths.
        Use this to check what's available before calling launch_revit.

### `launch_revit`

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

Close the active Revit document.

        Args:
            save: If True, save the document before closing.
                  If False (default), close without saving.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `save` | boolean |  | `False` |  |

### `save_document`

Save the active Revit document.

        If file_path is omitted, saves the document in place.
        If file_path is provided, performs a Save As to the new location.

        Args:
            file_path: Optional path for Save As. If omitted, saves in place.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string |  |  |  |

### `sync_with_central`

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

Project information parameters, display units, levels (elevations), grids, phases,
        worksets (workshared models) and design options - in one call.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `include` | list of `info` \| `levels` \| `grids` \| `phases` \| `worksets` \| `design_options` |  |  |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `find_elements`

Find elements with combinable filters; returns ids, names, category/family/type and
        category counts, paginated. Use this to turn a natural-language description
        ("all fire doors on Level 2 wider than 900 mm") into concrete element ids:
        categories=['Doors'], level='Level 2', param_filters=[{name:'Width', op:'gt', value:900, unit:'mm'}].
        Numeric comparisons on dimensional parameters use `unit` of the filter (default mm).

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `get_element_details`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `get_family_inventory`

Loaded families grouped by category with their types, instance counts, in-place and
        editable flags. Use the family name with family_open to edit it.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category` | string |  |  |  |
| `contains` | string |  |  |  |
| `unused_only` | boolean |  | `False` | Only families with zero placed instances |
| `include_types` | boolean |  | `True` |  |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `100` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `list_families`

Get a flat list of available family types in the current Revit model.
        Use `contains` to filter by a substring of the family or type name (case-insensitive).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `limit` | integer |  | `50` |  |

### `list_family_categories`

Get a list of all family categories in the current Revit model

### `list_levels`

Get a list of all levels in the current Revit model

### `list_links`

Revit links (path, load status, pinned, position/rotation) and CAD imports/links.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `include_counts` | boolean |  | `False` | Model element counts per category inside each loaded link |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `get_model_warnings`

Revit warnings grouped by description (most frequent first) with the failing element ids.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `50` |  |
| `ids_per_warning` | integer |  | `30` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `find_views`

Views with ids, type, level, scale, detail level, view template and the sheet they are on.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `view_types` | list of string |  |  | e.g. ['FloorPlan','Section','ThreeD','Schedule','DraftingView'] |
| `name_contains` | string |  |  |  |
| `templates` | `exclude` \| `include` \| `only` |  | `exclude` |  |
| `on_sheet` | boolean |  |  | true: only placed views, false: only unplaced |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `200` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `list_revit_views`

Get a list of all exportable views in the current Revit model

### `get_current_view_info`

Get detailed information about the currently active view in Revit.

        Returns comprehensive information including:
        - View name, type, and ID
        - Scale and detail level
        - Crop box status
        - View family type
        - View discipline
        - Template status

### `get_current_view_elements`

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

Export a specific Revit view as a PNG image.

        view_name: the exact view name, or the view element id as a string when
        several views share a name (e.g. floor and ceiling plan "Level 1").

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `view_name` | string | yes |  |  |

### `list_sheets`

Sheets with number, name, placed views, title blocks and revisions, plus counts of sheets
        without views or title blocks.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `parameters` | list of string |  |  | Sheet parameters to include, e.g. ['Drawn By'] |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `100` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `get_schedule_data`

Read a schedule's table (column headers and rows as displayed), paginated.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `schedule` | integer or string | yes |  | Schedule view id or exact name |
| `offset` | integer |  | `0` |  |
| `limit` | integer |  | `200` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `list_category_parameters`

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

Read the current Revit selection, or select/highlight elements for the user (active document only).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `get` \| `set` \| `add` \| `clear` |  | `get` |  |
| `element_ids` | list of integer |  |  |  |
| `zoom` | boolean |  | `False` | Zoom the view to the newly selected elements |

### `set_parameters`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `bulk_update_parameter`

Write one parameter on many elements (by ids, selection or filters) using a fixed value or a
        numbering/naming template. Example: renumber the Mark of the selected doors left-to-right:
        parameter='Mark', selection=true, template='D{n:02}', sort_by='x'. Use dry_run first.

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `transform_elements`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `delete_elements`

Delete elements. Without confirm=true this only previews: Revit performs the deletion inside a
        rolled-back transaction and reports every dependent element that would also be removed
        (hosted doors, tags, dimensions...). Show the preview to the user before confirming.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `element_ids` | list of integer | yes |  |  |
| `confirm` | boolean |  | `False` | false (default) = preview of everything Revit would delete |
| `include_pinned` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `create_elements`

Create levels, grids, walls, floors, family instances (hosted or not) and rooms in one
        transaction. Returns new element ids. Doors/windows need host_id of a wall.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | list of object | yes |  | Items by kind (coordinates in `unit`): level: {kind:'level', elevation, name?, create_plan_view?} grid: {kind:'grid', start:[x,y], end:[x,y], name?} wall: {kind:'wall', start, end, level, type?\|type_id?, height?(3000), base_offset?, structural?, flip?} floor: {kind:'floor', boundary:[[x,y],...], level, type?\|type_id?, structural?} family_instance: {kind:'family_instance', family, type\|type_id, point:[x,y,z], level?, host_id?, rotation_deg?} room: {kind:'room', level, point:[x,y], name?, number?} |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `place_family`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `color_splash`

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

Inspect family template folders (Revit's FamilyTemplatePath + extra dirs). With `kind`, returns
        matching .rft files best first and reports when none exists; without, shows the best template per
        kind and which kinds are missing.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | `generic_model` \| `generic_model_face_based` \| `generic_model_wall_based` \| `generic_model_floor_based` \| `generic_model_ceiling_based` \| `generic_model_line_based` \| `generic_model_adaptive` \| `door` \| `door_curtain_wall` \| `window` \| `window_curtain_wall` \| `furniture` \| `furniture_system` \| `casework` \| `casework_wall_based` \| `plumbing_fixture` \| `lighting_fixture` \| `lighting_fixture_ceiling_based` \| `mechanical_equipment` \| `electrical_equipment` \| `electrical_fixture` \| `specialty_equipment` \| `column` \| `structural_column` \| `structural_framing` \| `structural_foundation` \| `structural_stiffener` \| `structural_truss` \| `entourage` \| `planting` \| `site` \| `parking` \| `profile` \| `profile_mullion` \| `profile_rail` \| `profile_reveal` \| `profile_hosted` \| `detail_item` \| `detail_item_line_based` \| `generic_annotation` \| `door_tag` \| `window_tag` \| `room_tag` \| `multi_category_tag` \| `title_block` \| `rebar_shape` \| `mass` \| `railing_baluster` \| `ceiling_based_generic` |  |  |  |
| `unit_system` | `metric` \| `imperial` |  |  |  |
| `contains` | string |  |  |  |
| `search_dirs` | list of string |  |  |  |

### `family_create`

Create a NEW family document (.rfa) from a Revit family template, chosen by kind (door, window,
        furniture, casework, generic_model, ...) or explicit template_path. The family opens in the
        background; pass its title as `document` to the other family_* tools.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | `generic_model` \| `generic_model_face_based` \| `generic_model_wall_based` \| `generic_model_floor_based` \| `generic_model_ceiling_based` \| `generic_model_line_based` \| `generic_model_adaptive` \| `door` \| `door_curtain_wall` \| `window` \| `window_curtain_wall` \| `furniture` \| `furniture_system` \| `casework` \| `casework_wall_based` \| `plumbing_fixture` \| `lighting_fixture` \| `lighting_fixture_ceiling_based` \| `mechanical_equipment` \| `electrical_equipment` \| `electrical_fixture` \| `specialty_equipment` \| `column` \| `structural_column` \| `structural_framing` \| `structural_foundation` \| `structural_stiffener` \| `structural_truss` \| `entourage` \| `planting` \| `site` \| `parking` \| `profile` \| `profile_mullion` \| `profile_rail` \| `profile_reveal` \| `profile_hosted` \| `detail_item` \| `detail_item_line_based` \| `generic_annotation` \| `door_tag` \| `window_tag` \| `room_tag` \| `multi_category_tag` \| `title_block` \| `rebar_shape` \| `mass` \| `railing_baluster` \| `ceiling_based_generic` |  |  |  |
| `template_path` | string |  |  |  |
| `save_path` | string |  |  | Full .rfa path to save immediately (recommended) |
| `category` | string |  |  | Override the template category, e.g. 'Furniture' |
| `type_name` | string |  |  |  |
| `unit_system` | `metric` \| `imperial` |  | `metric` |  |
| `overwrite` | boolean |  | `False` |  |
| `search_dirs` | list of string |  |  |  |

### `family_open`

Open an existing family for editing - from an .rfa file or a family loaded in the project.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string |  |  | Path of an .rfa file |
| `family_name` | string |  |  | Name of a family loaded in the active project (Edit Family) |

### `family_get_info`

Inspect a family document: category and family properties, parameters (instance/type, spec, group,
        formula, shared GUID, reporting, associations, labelled dimensions), types with values, reference
        planes, dimensions, solid/void forms with associated parameters, and nested families.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `include` | list of `parameters` \| `types` \| `reference_planes` \| `dimensions` \| `forms` \| `nested` \| `properties` |  |  |  |
| `include_builtin` | boolean |  | `False` |  |
| `max_types` | integer |  | `50` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |

### `family_set_properties`

Change the family category and family-level settings (shared, work plane based, always vertical...).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `category` | string |  |  |  |
| `set` | object |  |  | {work_plane_based, always_vertical, shared, room_calculation_point, cut_with_voids} |
| `dry_run` | boolean |  | `False` |  |

### `family_add_parameters`

Add family parameters (type or instance; any data type; optional initial value, formula,
        reporting; or shared definitions with their existing GUID). Existing names are skipped.
        Formulas are pre-checked for unknown names and circular references, then validated by Revit.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `parameters` | list of FamilyParameterSpec | yes |  |  |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `naming_pattern` | string |  |  | Regex every new name must match |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_edit_parameters`

Edit existing family parameters. Shared parameters keep their GUID and cannot be renamed
        (Revit API limitation) - use replace_with_shared to swap definitions.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `remove` \| `rename` \| `set_formula` \| `set_instance` \| `set_reporting` \| `replace_with_shared` \| `associate` \| `set_values` | yes |  |  |
| `parameters` | list of object |  |  | remove: {name} \| rename: {name, new_name} \| set_formula: {name, formula} (empty formula clears) \| set_instance: {name, instance} \| set_reporting: {name, reporting} \| replace_with_shared: {name, shared_name?\|guid?, group?, instance?} \| associate: {element_id, element_parameter, name} (name omitted = dissociate) \| set_values: {name, value, unit?} on the current type |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `shared_parameter_file` | string |  |  |  |
| `atomic` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |

### `family_manage_types`

List, create, duplicate, rename, delete family types and set per-type values; export or import a
        Revit type catalog (.txt). Example: three door sizes ->
        action='create', types=[{name:'900x2100', values:{Width:900, Height:2100}}, ...].

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `upsert` \| `duplicate` \| `rename` \| `delete` \| `set_values` \| `export_catalog` \| `import_catalog` |  | `list` |  |
| `types` | list of object |  |  | create/upsert: {name, values: {param: value\|{value, unit}}, based_on?} \| duplicate: {source, new_name, values?} \| rename: {name, new_name} \| delete: {name} \| set_values: {name, values} |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `parameters` | list of string |  |  | list: only these parameters |
| `path` | string |  |  | Type catalog .txt path (default: next to the .rfa) |
| `catalog_text` | string |  |  |  |
| `overwrite` | boolean |  | `False` |  |
| `strict` | boolean |  | `True` | Roll back everything if any value fails |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` | Unit for plain numeric values of length parameters |
| `dry_run` | boolean |  | `False` |  |

### `family_create_reference_planes`

Create named reference planes (x: left/right, y: front/back, z: horizontal) at offsets, or list them.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `planes` | list of ReferencePlaneSpec |  |  |  |
| `action` | `create` \| `list` |  | `create` |  |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_create_form`

Create solid or void extrusions, blends, revolutions and sweeps on a work plane, optionally
        associating material / visibility / extrusion end to family parameters, setting detail-level
        visibility and subcategory, cutting solids with voids and locking faces to reference planes.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `forms` | list of FormSpec | yes |  |  |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_add_dimension`

Dimension between parallel reference planes (or Ref. Level) and label it with a parameter
        (e.g. Left-Right labelled Width), add EQ constraints (Left-Center-Right) or lock it.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `dimensions` | list of DimensionSpec | yes |  |  |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_align_geometry`

Lock form faces to the reference planes they lie on, so geometry follows labelled dimensions.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `form_ids` | list of integer |  |  | Default: all solid forms |
| `planes` | list of string |  |  | Default: every reference plane + Ref. Level |
| `lock` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_build_parametric_box`

Build a genuinely parametric box in one step: Left/Right/Front/Back reference planes centred
        on the template's centre planes, Width/Depth labelled dimensions with EQ, a solid extrusion with
        all four sides locked, Height driving the extrusion end and a Material parameter - then flex it
        to prove the geometry follows the parameters. Ideal base for furniture, casework and equipment.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
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

Load a family into the family being edited and place it, linking nested parameters to host
        family parameters (parameter associations).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `load` \| `place` | yes |  |  |
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `path` | string |  |  | load: .rfa to nest |
| `family` | string |  |  |  |
| `type` | string |  |  |  |
| `point` | list of number |  |  |  |
| `associate` | object |  |  | place: {nested parameter: host family parameter} |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |

### `family_flex_test`

Flex a family: apply types / parameter values, regenerate and measure geometry, report Revit
        constraint errors and parameters with no geometric effect. Everything is rolled back.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `cases` | list of FlexCase |  |  | Default: every type, then +20% on each length parameter |
| `expect` | object |  |  | Bounding box axis -> parameter, e.g. {x:'Width'} |
| `tolerance` | number |  | `0.5` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |

### `family_validate`

Quality-control a family: category, formulas (syntax, unknown names, circular references),
        parameters that drive nothing, types missing values or with zero dimensions, invalid geometry,
        missing labelled dimensions (not parametric) and Revit warnings - with severities and fixes.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `expected_category` | string |  |  |  |
| `parameter_naming_pattern` | string |  |  |  |

### `family_save`

Save the family document. Existing files are backed up to %APPDATA%/RVTSS/backups before being
        overwritten.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `save_path` | string |  |  | Save As path (.rfa). Omit to save in place |
| `overwrite` | boolean |  | `False` |  |
| `compact_file` | boolean |  | `False` |  |
| `backup` | boolean |  | `True` | Copy the existing file to %APPDATA%/RVTSS/backups first |

### `family_load_into_project`

Load (or reload) the family into a project and verify that all its types arrived.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `project` | string |  |  | Target project title (default: active/only project) |
| `overwrite` | boolean |  | `True` | Reload if the family already exists in the project |
| `overwrite_parameter_values` | boolean |  | `False` | Also overwrite type parameter values in the project |

### `family_close`

Close a background family document (refuses to drop unsaved changes unless discard_changes=true).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `document` | string |  |  | Family document title or path (from family_create / family_open). Default: the active document. |
| `save` | boolean |  | `False` |  |
| `discard_changes` | boolean |  | `False` | Required to close with unsaved changes and save=false |

### `list_project_parameters`

Project parameters with binding (instance/type), categories, data type, group, shared GUID,
        plus names defined more than once.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `contains` | string |  |  |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `shared_parameters`

Shared parameter workflow: read the file (GUIDs, groups, duplicates, which are already in the
        project), create definitions (existing names are reused and their GUIDs never changed; supplied
        GUIDs are honoured), create a new file, and bind a shared parameter to categories as instance or
        type (existing bindings are extended, never replaced). Example: 'Fire Rating' on Doors and Walls ->
        create_definitions [{name:'Fire Rating', type:'text'}] then bind name='Fire Rating',
        categories=['Doors','Walls'].

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `global_parameters`

Global parameters: list (value, formula, affected elements), create, set value/formula and
        associate element parameters with them.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `set_value` \| `set_formula` \| `associate` \| `dissociate` |  | `list` |  |
| `name` | string |  |  |  |
| `type` | `length` \| `area` \| `volume` \| `angle` \| `slope` \| `number` \| `integer` \| `text` \| `multiline_text` \| `url` \| `yesno` \| `material` \| `image` \| `currency` \| `mass` \| `force` |  | `length` |  |
| `value` | string or number or integer or boolean |  |  |  |
| `value_unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` \| `mm2` \| `m2` \| `ft2` \| `mm3` \| `m3` \| `ft3` \| `deg` \| `rad` \| `internal` |  |  |  |
| `formula` | string |  |  |  |
| `element_ids` | list of integer |  |  | associate/dissociate targets |
| `parameter` | string |  |  | associate: element parameter to drive |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `audit_parameters`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `export_parameters`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `import_parameters`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `map_parameters`

Copy values from existing parameters into your BIM-standard parameters (converting between
        storage types through display values). Source values are never deleted.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `mappings` | list of object | yes |  | [{from: 'Old Param', to: 'Standard Param'}] |
| `categories` | list of string |  |  |  |
| `element_ids` | list of integer |  |  |  |
| `view` | string |  |  |  |
| `level` | string |  |  |  |
| `only_empty_target` | boolean |  | `False` |  |
| `allow_type` | boolean |  | `False` |  |
| `atomic` | boolean |  | `False` |  |
| `dry_run` | boolean |  | `True` |  |
| `confirm` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `create_view`

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
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `view_graphics`

Per-view graphics: element/category overrides (color, fill, line weight, halftone,
        transparency), hide/unhide, temporary isolate/hide, category visibility, view templates,
        scale and detail level. Warns when a view template controls the setting.

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `manage_sheets`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `create_schedule`

Create a schedule for a category with fields, sorting and filters.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `category` | string | yes |  |  |
| `fields` | list of string | yes |  | Schedulable field names, e.g. ['Mark','Type','Width','Fire Rating'] |
| `name` | string |  |  |  |
| `sort_by` | list of string |  |  |  |
| `filters` | list of object |  |  | [{field, type: 'Equal'\|'Contains'\|..., value}] |
| `itemized` | boolean |  | `True` |  |
| `strict` | boolean |  | `True` |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `batch_rename`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `manage_groups`

List group types (instances, unused types), create a model group from elements, or ungroup.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `list` \| `create` \| `ungroup` |  | `list` |  |
| `element_ids` | list of integer |  |  |  |
| `name` | string |  |  |  |
| `group_id` | integer |  |  |  |
| `dry_run` | boolean |  | `False` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `manage_assemblies`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `run_model_checks`

BIM quality report: warnings, duplicate elements, naming standards, near-duplicate families,
        duplicate types, unused / in-place families, CAD imports, link status, rooms, views not on sheets,
        sheet completeness, required parameters and unused groups. Each finding has severity, element ids
        and a recommended correction.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `checks` | list of `warnings` \| `duplicates` \| `naming` \| `similar_family_names` \| `duplicate_types` \| `unused_families` \| `in_place_families` \| `cad_imports` \| `links` \| `rooms` \| `views_not_on_sheets` \| `sheets` \| `required_parameters` \| `groups` |  |  | Default: all checks |
| `rules` | object |  |  | Project rules (merged over %APPDATA%/RVTSS/qc_rules.json): {naming: {views\|sheets\|levels\|families\|types: {pattern, severity, description}}, required_parameters: [{categories, parameters, severity}], sheet_parameters: [...]} |
| `sheet_parameters` | list of string |  |  |  |
| `duplicate_tolerance` | number |  | `1.0` | Distance in `unit` for duplicate detection |
| `min_severity` | `info` \| `warning` \| `error` \| `critical` |  | `info` |  |
| `max_findings` | integer |  | `200` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `check_clashes`

Hard clash detection (solid intersection) between two element sets in the model or against a
        loaded Revit link. Returns clashing pairs with ids, categories and types.

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `set_a` | object | yes |  | Element query, e.g. {categories: ['Ducts'], level: 'Level 2'} |
| `set_b` | object | yes |  | Element query; add link_instance_id to test against a Revit link |
| `max_pairs` | integer |  | `200` |  |
| `max_elements` | integer |  | `2000` |  |
| `compute_volume` | boolean |  | `False` |  |
| `unit` | `mm` \| `cm` \| `m` \| `ft` \| `in` |  | `mm` |  |
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `model_snapshot`

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `compare_models`

Change detection and model comparison. snapshots: added / removed / modified elements (type,
        level, moved, parameter changes) between a baseline snapshot and the live model or another
        snapshot. match: pair elements of two sets by location (design model vs shop drawing / fabrication
        link) and report unmatched elements and type substitutions.

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
| `document` | string |  |  | Target document title or path; default is the active document. Family documents opened with family_open/family_create are addressed this way. |

### `execute_revit_code`

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

