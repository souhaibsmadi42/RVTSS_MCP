# -*- coding: utf-8 -*-
"""RVTSS live self-test: one plan, two runners.

The plan follows docs/UPGRADE_REPORT.md section 7 (status -> original tools ->
read-only tools -> editing with dry run then real -> family workflow -> shared
parameters on a scratch file -> QC). It is pure Python (IronPython 2.7/3.4 and
CPython 3) and talks to RVTSS only through a *transport*:

    transport(method, path, payload) -> (http_status, data_dict)

* tests/live/run_live.py      - HTTP transport against the running Routes server
* revit_mcp/selftest_runtime  - in-process transport used by the pyRevit button

Safety rules built into the plan:
* every model change happens only after the bundled test model (a copy in the
  scratch folder) has been opened and verified as the active document;
* family files, catalogs and the shared parameter file live in the scratch
  folder; the user's own shared parameter file is never written (RVTSS switches
  to the scratch file per request and restores the original afterwards).
"""
import json
import re
import time
import traceback

PASS, FAIL, SKIP = "pass", "fail", "skip"
OK_STATUSES = ("success", "dry_run", "preview", "active", "ok")


class StepFailed(Exception):
    def __init__(self, message, data=None):
        Exception.__init__(self, message)
        self.message = message
        self.data = data or {}


class StepSkipped(Exception):
    pass


def _join(base, *parts):
    sep = "\\" if ("\\" in base or re.match(r"^[A-Za-z]:", base)) else "/"
    out = base.rstrip("\\/")
    for p in parts:
        out = out + sep + p.strip("\\/")
    return out


# ------------------------------------------------------------------ routing
def compile_route(pattern):
    """'/get_view/<view_name>' -> regex with named groups (pyRevit style)."""
    rx = "^"
    pos = 0
    for m in re.finditer(r"<(?:(int|float|str|path):)?(\w+)>", pattern):
        rx += re.escape(pattern[pos:m.start()])
        kind = m.group(1)
        rx += {"int": r"(?P<%s>-?\d+)", "float": r"(?P<%s>-?\d+(?:\.\d+)?)",
               "path": r"(?P<%s>.+)"}.get(kind, r"(?P<%s>[^/]+)") % m.group(2)
        pos = m.end()
    rx += re.escape(pattern[pos:]) + "$"
    return re.compile(rx)


def match_route(routes, method, path):
    """routes: [{"path", "methods", "func"}] -> (route, url_params) or (None, None)."""
    clean = path.split("?", 1)[0]
    for r in routes:
        if method.upper() not in [m.upper() for m in r["methods"]]:
            continue
        m = compile_route(r["path"]).match(clean)
        if m:
            params = dict((k, (int(v) if v.lstrip("-").isdigit() and "int:" in r["path"] else v))
                          for k, v in m.groupdict().items())
            return r, params
    return None, None


# ------------------------------------------------------------------ context
class TestContext(object):
    def __init__(self, transport, scratch_dir, prepare_model=None, log=None):
        self.transport = transport
        self.scratch = scratch_dir
        self.prepare_model = prepare_model
        self.state = {}
        self.log = log or (lambda m: None)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")

    def path(self, *parts):
        return _join(self.scratch, *parts)

    def call(self, method, path, payload=None, expect_error=False):
        status, data = self.transport(method, path, payload)
        if not isinstance(data, dict):
            data = {"status": "error", "error": "Non-JSON response: %r" % (data,)}
        failed = status >= 400 or data.get("status") == "error" or (
            "error" in data and data.get("status") not in OK_STATUSES)
        if expect_error:
            if not failed:
                raise StepFailed("Expected an error but the call succeeded", data)
            return data
        if failed:
            raise StepFailed(data.get("error") or "HTTP %s" % status, data)
        return data

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, payload=None, **kw):
        return self.call("POST", path, payload or {}, **kw)

    def require(self, key, why):
        if not self.state.get(key):
            raise StepSkipped(why)
        return self.state[key]

    def require_test_model(self):
        if not self.state.get("test_model_open"):
            raise StepSkipped("test model not open - model-changing steps are skipped for safety")


def check(cond, message, data=None):
    if not cond:
        raise StepFailed(message, data)


# --------------------------------------------------------------------- steps
STEPS = []


def step(group, name, tools):
    def deco(fn):
        STEPS.append({"group": group, "name": name, "tools": tools, "fn": fn})
        return fn
    return deco


# 1. status --------------------------------------------------------------------
@step("status", "routes status", ["get_revit_status"])
def _status(t):
    status, d = t.transport("GET", "/status/", None)
    if isinstance(d, dict) and "no active revit document" in (d.get("error") or "").lower():
        # checked again by "setup / routes status with the test model" once a document is open
        raise StepSkipped("no document open yet")
    if status >= 400:
        raise StepFailed((d or {}).get("error") or "HTTP %s" % status, d if isinstance(d, dict) else {})
    return _check_status(d)


def _check_status(d):
    check(d.get("health") in ("healthy", "degraded"), "unexpected health", d)
    check(d.get("health") != "degraded", "route modules failed: %s" % d.get("route_modules_failed"), d)
    return {"document": d.get("document_title"), "rvtss_version": d.get("rvtss_version")}


@step("status", "ping (no API context) and request id echo", ["get_revit_status"])
def _ping(t):
    d = t.get("/ping/")
    check(d.get("pong") is True, "/ping/ did not answer pong", d)
    return {"rvtss_version": d.get("rvtss_version")}


@step("status", "session info", ["get_session_info"])
def _session(t):
    d = t.post("/session_info/")
    t.state["env"] = dict((k, d.get(k)) for k in ("revit_version", "revit_build", "rvtss_version", "pyrevit_version",
                                                   "python_engine", "python_version", "active_document"))
    t.state["revit_temp"] = d.get("temp_dir")
    return t.state["env"]


# 2. test model ----------------------------------------------------------------
@step("setup", "open test model copy", ["open_document"])
def _open_model(t):
    if t.prepare_model is None:
        raise StepSkipped("no test model available to this runner")
    path = t.prepare_model(t)
    if not path:
        raise StepSkipped("test model could not be prepared")
    t.post("/open_document/", {"file_path": path})
    d = t.post("/session_info/")
    active = (d.get("active_document") or "").lower()
    stem = re.split(r"[\\/]", path)[-1].lower()
    check(active and (active == stem or active == stem.rsplit(".", 1)[0]),
          "active document is %r, expected the test copy %r" % (active, stem), d)
    t.state["test_model_open"] = True
    t.state["test_model"] = path
    return {"path": path}


@step("setup", "routes status with the test model", ["get_revit_status"])
def _status_model(t):
    t.require_test_model()
    return _check_status(t.get("/status/"))


@step("setup", "seed walls + floor in the test copy", ["create_elements", "find_views"])
def _seed(t):
    """The bundled test model is an empty template: give the later steps something to work on."""
    t.require_test_model()
    levels = sorted(t.post("/project_overview/", {"include": ["levels"]}).get("levels") or [],
                    key=lambda lv: lv.get("elevation", 0))
    check(levels, "no levels in the test model")
    level = levels[0]["name"]
    pts = [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]
    items = [{"kind": "wall", "start": pts[i], "end": pts[(i + 1) % 4], "level": level, "height": 3000}
             for i in range(4)]
    items.append({"kind": "floor", "boundary": pts, "level": level})
    d = t.post("/create_elements/", {"items": items, "unit": "mm"})
    check(d.get("created") == len(items), "seed elements not created", d)
    res = d.get("results") or []
    t.state["seed_wall_ids"] = [r["id"] for r in res if r.get("kind") == "wall"]
    t.state["seed_floor_id"] = ([r["id"] for r in res if r.get("kind") == "floor"] or [None])[0]
    t.state["seed_level"] = level
    t.state["seed_top_level"] = levels[1]["name"] if len(levels) > 1 else None
    # view names are not unique (floor plan and ceiling plan share them): later steps use the id
    v = t.post("/find_views/", {"view_types": ["FloorPlan"], "limit": 50})
    plans = [x for x in v.get("views") or [] if x.get("level") in (level, None)] or v.get("views") or []
    t.state["plan_id"] = str(plans[0]["id"]) if plans else None
    return {"level": level, "created": d.get("created"), "plan_id": t.state["plan_id"]}


# 3. original tools --------------------------------------------------------------
@step("original", "model info", ["get_revit_model_info"])
def _model_info(t):
    d = t.get("/model_info/")
    return {"warnings": d.get("model_health", {}).get("total_warnings"),
            "elements": d.get("element_summary", {}).get("total_elements")}


@step("original", "list levels / views / families", ["list_levels", "list_revit_views", "list_families",
                                                      "list_family_categories"])
def _original_lists(t):
    lv = t.get("/list_levels/")
    views = t.get("/list_views/")
    fams = t.post("/list_families/", {"limit": 5})
    cats = t.get("/list_family_categories/")
    plans = (views.get("views_by_type") or {}).get("floor_plans") or []
    t.state["plan_name"] = plans[0] if plans else None
    return {"levels": lv.get("total_levels"), "views": views.get("total_exportable_views"),
            "families": fams.get("count"), "categories": cats.get("total_categories")}


@step("original", "current view info / elements", ["get_current_view_info", "get_current_view_elements"])
def _current_view(t):
    info = t.get("/current_view_info/")
    el = t.post("/current_view_elements/", {"limit": 5})
    return {"view": (info.get("view_info") or {}).get("view_name"), "elements": el.get("total_elements")}


@step("original", "export view image", ["get_revit_view"])
def _view_image(t):
    name = t.require("plan_name", "no floor plan in the model")
    try:
        from urllib import quote  # IronPython 2
    except ImportError:
        from urllib.parse import quote  # novermin (py2 fallback above)
    d = t.get("/get_view/" + quote(name))
    check(d.get("image_data") and d.get("file_size_bytes", 0) > 1000, "no image data", {"keys": list(d)})
    return {"view": name, "bytes": d.get("file_size_bytes")}


@step("original", "category parameters + color splash", ["list_category_parameters", "color_splash", "clear_colors"])
def _colors(t):
    t.post("/list_category_parameters/", {"category_name": "Walls"})
    t.require_test_model()
    d = t.post("/color_splash/", {"category_name": "Walls", "parameter_name": "Comments"})
    t.post("/clear_colors/", {"category_name": "Walls"})
    return {"colored": d.get("total_elements") or d.get("elements_colored")}


@step("original", "execute code (dry run)", ["execute_revit_code"])
def _exec(t):
    d = t.post("/execute_code/", {"code": "print(doc.Title)", "transaction_mode": "dry_run",
                                  "description": "RVTSS self-test"})
    check("dry_run" == d.get("status") and d.get("output"), "unexpected result", d)
    return {"output": (d.get("output") or "").strip()[:60]}


@step("original", "place family + delete", ["place_family", "delete_elements"])
def _place(t):
    t.require_test_model()
    d = t.post("/find_elements/", {"categories": ["Furniture", "Generic Models", "Specialty Equipment"],
                                   "include_types": True, "limit": 50})
    # Model Text is a Generic Models "type" that cannot be placed as a family instance
    types = [e for e in d.get("elements") or []
             if e.get("family") and "model text" not in (e.get("family") or "").lower()]
    if not types:
        raise StepSkipped("no furniture / generic model type loaded")
    typ = types[0]
    p = t.post("/place_family/", {"family_name": typ.get("family"), "type_name": typ.get("name"),
                                  "location": {"x": 1000, "y": 1000, "z": 0}, "unit": "mm"})
    eid = p.get("element_id")
    check(eid, "no element id", p)
    prev = t.post("/delete_elements/", {"element_ids": [eid]})
    check(prev.get("status") == "preview", "delete without confirm must preview", prev)
    t.post("/delete_elements/", {"element_ids": [eid], "confirm": True})
    return {"placed": "%s : %s" % (typ.get("family"), typ.get("name")), "id": eid}


# 4. read-only RVTSS tools --------------------------------------------------------
@step("read", "find + details", ["find_elements", "get_element_details"])
def _find(t):
    d = t.post("/find_elements/", {"categories": ["Walls"], "limit": 5, "fields": ["level", "location", "bbox"]})
    check(d.get("count", 0) > 0, "no walls in the model", d)
    ids = [e["id"] for e in d["elements"]]
    t.state["wall_ids"] = ids
    det = t.post("/element_details/", {"element_ids": ids[:1], "include_geometry": True,
                                       "include_type_parameters": True})
    e = det["elements"][0]
    check(e.get("parameters"), "no parameters", e)
    return {"walls": d["count"], "first": ids[0], "volume": (e.get("geometry") or {}).get("volume")}


@step("read", "project overview + session lists", ["get_project_overview", "list_links", "get_model_warnings",
                                                   "get_family_inventory", "find_views", "list_sheets"])
def _overview(t):
    ov = t.post("/project_overview/")
    t.post("/list_links/")
    w = t.post("/model_warnings/", {"limit": 5})
    inv = t.post("/family_inventory/", {"limit": 5})
    v = t.post("/find_views/", {"view_types": ["Schedule"], "limit": 5})
    sh = t.post("/list_sheets/", {"limit": 5})
    t.state["schedule"] = v["views"][0]["id"] if v.get("views") else None
    return {"levels": len(ov.get("levels") or []), "warnings": w.get("total_warnings"),
            "families": inv.get("family_count"), "sheets": sh.get("count")}


@step("read", "schedule data", ["get_schedule_data"])
def _schedule(t):
    sid = t.require("schedule", "model has no schedule")
    d = t.post("/schedule_data/", {"schedule": sid, "limit": 5})
    return {"rows": d.get("row_count"), "columns": len(d.get("columns") or [])}


@step("read", "selection", ["revit_selection"])
def _selection(t):
    d = t.post("/selection/", {"action": "get"})
    return {"selected": d.get("count")}


# 5. editing ------------------------------------------------------------------------
def _comments(t, eid):
    d = t.post("/element_details/", {"element_ids": [eid], "parameters": ["Comments"]})
    return d["elements"][0]["parameters"][0].get("value")


@step("edit", "set parameter: dry run then real", ["set_parameters"])
def _set_param(t):
    t.require_test_model()
    eid = t.require("wall_ids", "no walls")[0]
    before = _comments(t, eid)
    value = "RVTSS self-test " + t.stamp
    d = t.post("/set_parameters/", {"updates": [{"element_id": eid, "parameter": "Comments", "value": value}],
                                    "dry_run": True})
    check(d.get("status") == "dry_run", "expected dry_run", d)
    check(_comments(t, eid) == before, "dry run changed the model")
    t.post("/set_parameters/", {"updates": [{"element_id": eid, "parameter": "Comments", "value": value}]})
    check(_comments(t, eid) == value, "value not written")
    return {"element": eid, "value": value}


@step("edit", "unit strictness", ["set_parameters"])
def _unit_strict(t):
    t.require_test_model()
    eid = t.require("wall_ids", "no walls")[0]
    d = t.post("/set_parameters/", {"updates": [{"element_id": eid, "parameter": "WALL_BASE_OFFSET", "value": 0}]},
               expect_error=True)
    check("unit" in (d.get("error", "") + d.get("hint", "")).lower(), "error does not mention units", d)
    return {"rejected": d.get("error")}


@step("edit", "bulk update + transform (dry run)", ["bulk_update_parameter", "transform_elements"])
def _bulk(t):
    t.require_test_model()
    ids = t.require("wall_ids", "no walls")
    b = t.post("/bulk_update_parameter/", {"parameter": "Comments", "template": "W-{n:02}", "element_ids": ids,
                                           "sort_by": "x", "dry_run": True})
    check(b.get("status") == "dry_run" and b.get("results"), "bulk dry run failed", b)
    m = t.post("/transform_elements/", {"operation": "move", "element_ids": ids[:1], "vector": [100, 0, 0],
                                        "dry_run": True})
    check(m.get("status") == "dry_run", "transform dry run failed", m)
    return {"first_value": b["results"][0].get("after")}


@step("edit", "create level, delete with preview", ["create_elements", "delete_elements"])
def _create(t):
    t.require_test_model()
    d = t.post("/create_elements/", {"items": [{"kind": "level", "elevation": 99000,
                                                "name": "RVTSS SelfTest " + t.stamp}]})
    lid = d["results"][0]["id"]
    prev = t.post("/delete_elements/", {"element_ids": [lid]})
    check(prev.get("status") == "preview" and prev.get("deleted_total", 0) >= 1, "bad delete preview", prev)
    t.post("/delete_elements/", {"element_ids": [lid], "confirm": True})
    return {"level_id": lid}


@step("edit", "types + views + graphics + rename (dry run)", ["manage_element_types", "create_view", "view_graphics",
                                                               "batch_rename"])
def _doc_dry(t):
    t.require_test_model()
    eid = t.require("wall_ids", "no walls")[0]
    vt = t.post("/element_types/", {"action": "list_valid_types", "element_id": eid})
    t.post("/views/create/", {"kind": "drafting", "name": "RVTSS SelfTest " + t.stamp, "dry_run": True})
    t.post("/views/graphics/", {"action": "override", "element_ids": [eid], "color": "#FF0000", "dry_run": True})
    r = t.post("/batch_rename/", {"target": "levels", "suffix": " (x)", "dry_run": True})
    return {"valid_wall_types": len(vt.get("valid_types") or []), "rename_planned": len(r.get("renamed") or [])}


# 6. family workflow -------------------------------------------------------------------
@step("family", "templates", ["family_list_templates"])
def _templates(t):
    d = t.post("/family/templates/", {"kind": "generic_model", "unit_system": "metric"})
    if not d.get("matches"):
        raise StepSkipped("no Generic Model template installed: %s" % d.get("hint"))
    t.state["template_ok"] = True
    return {"template": d["matches"][0]}


@step("family", "create family + parametric box (flex check)", ["family_create", "family_build_parametric_box"])
def _family_box(t):
    t.require("template_ok", "no template")
    path = t.path("RVTSS_SelfTest_Box_%s.rfa" % t.stamp)
    c = t.post("/family/create/", {"kind": "generic_model", "unit_system": "metric", "save_path": path,
                                   "category": "Furniture", "type_name": "Default"})
    t.state["family"] = c["document"]
    t.state["family_path"] = path
    b = t.post("/family/build_box/", {"document": c["document"], "width": 900, "depth": 600, "height": 750})
    flex = b.get("flex_check") or {}
    check(flex.get("passed"), "flex check failed: %s" % json.dumps(flex.get("cases"))[:600], b)
    return {"document": c["document"], "dimensions": len(b.get("dimension_ids") or [])}


@step("family", "parameters + formula + types", ["family_add_parameters", "family_manage_types", "family_get_info"])
def _family_params(t):
    doc = t.require("family", "no family")
    t.post("/family/parameters/", {"document": doc, "action": "add", "parameters": [
        {"name": "Frame Thickness", "type": "length", "value": 50, "unit": "mm"},
        {"name": "Inner Width", "type": "length", "formula": "Width - 2 * Frame Thickness"}]})
    t.post("/family/types/", {"document": doc, "action": "create", "types": [
        {"name": "W600", "values": {"Width": 600, "Depth": 400}},
        {"name": "W900", "values": {"Width": 900, "Depth": 600}},
        {"name": "W1200", "values": {"Width": 1200, "Depth": 600}}]})
    info = t.post("/family/info/", {"document": doc, "include": ["types", "parameters"]})
    types = dict((ty["name"], ty["values"]) for ty in info.get("types") or [])
    check(abs((types.get("W1200") or {}).get("Inner Width", 0) - 1100) < 0.01, "formula not evaluated per type",
          {"types": types})
    return {"types": sorted(types)}


@step("family", "flex test all types", ["family_flex_test"])
def _family_flex(t):
    doc = t.require("family", "no family")
    d = t.post("/family/flex/", {"document": doc, "expect": {"x": "Width", "y": "Depth", "z": "Height"}})
    type_cases = [c for c in d.get("cases") or [] if c["case"] in ("W600", "W900", "W1200")]
    check(type_cases and all(c["ok"] for c in type_cases), "type flex failed", d)
    return {"inert": d.get("parameters_without_geometric_effect")}


@step("family", "blend geometry (top profile)", ["family_create_form"])
def _family_blend(t):
    doc = t.require("family", "no family")
    d = t.post("/family/forms/", {"document": doc, "forms": [{
        "kind": "blend", "base_profile": {"rectangle": {"min": [1000, -100], "max": [1200, 100]}},
        "top_profile": {"rectangle": {"min": [1050, -50], "max": [1150, 50]}}, "height": 300}]})
    fid = d["results"][0]["id"]
    forms = t.post("/family/forms/", {"document": doc, "action": "list"})["forms"]
    size = [f for f in forms if f["id"] == fid][0].get("size")
    check(size and abs(size[2] - 300) < 1 and abs(size[0] - 200) < 1, "blend size %s, expected [200, 200, 300]" % size)
    return {"size": size}


@step("family", "sweep geometry (profile orientation)", ["family_create_form"])
def _family_sweep(t):
    doc = t.require("family", "no family")
    d = t.post("/family/forms/", {"document": doc, "forms": [{
        "kind": "sweep", "path": [[-1500, 1000], [-1000, 1000]],
        "profile": {"rectangle": {"min": [-25, 0], "max": [25, 50]}}}]})
    fid = d["results"][0]["id"]
    forms = t.post("/family/forms/", {"document": doc, "action": "list"})["forms"]
    size = [f for f in forms if f["id"] == fid][0].get("size")
    check(size and abs(size[0] - 500) < 1 and abs(size[1] - 50) < 1 and abs(size[2] - 50) < 1,
          "sweep size %s, expected [500, 50, 50] (profile perpendicular to the path)" % size)
    return {"size": size}


@step("family", "revolution geometry", ["family_create_form"])
def _family_revolve(t):
    doc = t.require("family", "no family")
    d = t.post("/family/forms/", {"document": doc, "forms": [{
        "kind": "revolution", "work_plane": "Center (Front/Back)",
        "profile": {"loops": [[[2000, 0], [2100, 0], [2100, 200], [2000, 200]]]},
        "axis": [[1900, 0], [1900, 1]]}]})
    fid = d["results"][0]["id"]
    forms = t.post("/family/forms/", {"document": doc, "action": "list"})["forms"]
    size = [f for f in forms if f["id"] == fid][0].get("size")
    check(size and abs(size[2] - 200) < 1 and abs(size[0] - 400) < 1,
          "revolution size %s, expected [400, 400, 200]" % size)
    return {"size": size}


@step("family", "validate + catalog + save", ["family_validate", "family_manage_types", "family_save"])
def _family_save(t):
    doc = t.require("family", "no family")
    v = t.post("/family/validate/", {"document": doc, "expected_category": "Furniture"})
    cat = t.post("/family/types/", {"document": doc, "action": "export_catalog",
                                    "path": t.path("RVTSS_SelfTest_Box_%s.txt" % t.stamp), "overwrite": True})
    s = t.post("/family/save/", {"document": doc})
    check(cat.get("type_count") == 4, "catalog should list 4 types", cat)
    return {"validation": v.get("summary", {}).get("passed"), "findings": v.get("summary", {}).get("total_findings"),
            "saved": s.get("saved_path"), "backup": bool(s.get("backup"))}


@step("family", "load into test project + close", ["family_load_into_project", "family_close"])
def _family_load(t):
    doc = t.require("family", "no family")
    t.require_test_model()
    d = t.post("/family/load_into_project/", {"document": doc, "overwrite": True})
    check(d.get("verified"), "not all types arrived: %s" % d.get("types_missing_in_project"), d)
    t.post("/family/close/", {"document": doc, "discard_changes": True})
    return {"types_in_project": d.get("types_in_project")}


# 7. shared parameters on a scratch file ---------------------------------------------------
@step("parameters", "shared parameter file + definitions", ["shared_parameters"])
def _shared(t):
    path = t.path("rvtss_selftest_shared_%s.txt" % t.stamp)
    t.post("/parameters/shared/", {"action": "create_file", "shared_parameter_file": path})
    name = "RVTSS SelfTest %s" % t.stamp
    d = t.post("/parameters/shared/", {"action": "create_definitions", "shared_parameter_file": path,
                                       "definitions": [{"name": name, "type": "text", "group": "RVTSS"}]})
    again = t.post("/parameters/shared/", {"action": "create_definitions", "shared_parameter_file": path,
                                           "definitions": [{"name": name, "type": "text"}]})
    check(again["results"][0]["action"] == "exists" and again["results"][0]["guid"] == d["results"][0]["guid"],
          "re-creating a definition must reuse the GUID", again)
    r = t.post("/parameters/shared/", {"action": "read_file", "shared_parameter_file": path})
    check(any(p["name"] == name for p in r["parameters"]), "definition not in file", r)
    check(not r.get("is_current_file"), "scratch file became Revit's current shared parameter file", r)
    t.state["shared"] = (path, name)
    return {"guid": d["results"][0]["guid"]}


@step("parameters", "bind (dry run, real) + audit", ["shared_parameters", "list_project_parameters",
                                                     "audit_parameters"])
def _bind(t):
    t.require_test_model()
    path, name = t.require("shared", "no shared definition")
    dr = t.post("/parameters/shared/", {"action": "bind", "shared_parameter_file": path, "name": name,
                                        "categories": ["Walls"], "dry_run": True})
    check(dr.get("status") == "dry_run", "dry run expected", dr)
    t.post("/parameters/shared/", {"action": "bind", "shared_parameter_file": path, "name": name,
                                   "categories": ["Walls"]})
    pp = t.post("/parameters/project/", {"contains": "RVTSS SelfTest"})
    check(any(p["name"] == name for p in pp["parameters"]), "binding not listed", pp)
    a = t.post("/parameters/audit/", {"categories": ["Walls"], "required": [name]})
    return {"missing": a["per_parameter"][name]["missing"], "empty": a["per_parameter"][name]["empty"]}


@step("parameters", "global parameter", ["global_parameters"])
def _global(t):
    t.require_test_model()
    name = "RVTSS_GP_%s" % t.stamp
    t.post("/parameters/global/", {"action": "create", "name": name, "type": "length", "value": 1000,
                                   "value_unit": "mm"})
    d = t.post("/parameters/global/", {"action": "list"})
    gp = [g for g in d["global_parameters"] if g["name"] == name]
    check(gp and abs(gp[0]["value"] - 1000) < 0.01, "global parameter value", d)
    return {"name": name}


@step("parameters", "export parameters (CSV inline)", ["export_parameters"])
def _export(t):
    d = t.post("/parameters/export/", {"categories": ["Walls"], "parameters": ["Comments", "Mark"]})
    check(d.get("rows", 0) > 0 and "ElementId" in d.get("csv", ""), "empty export", d)
    return {"rows": d["rows"]}


# 8. QC -----------------------------------------------------------------------------------
@step("qc", "model checks", ["run_model_checks"])
def _checks(t):
    d = t.post("/qc/model_checks/", {"checks": ["warnings", "links", "rooms", "views_not_on_sheets", "sheets",
                                                "naming", "groups"]})
    check(not d.get("checks_failed"), "checks crashed: %s" % d.get("checks_failed"), d)
    return d.get("summary")


@step("qc", "clashes walls vs floors", ["check_clashes"])
def _clash(t):
    d = t.post("/qc/clashes/", {"set_a": {"categories": ["Walls"]}, "set_b": {"categories": ["Floors"]},
                                "max_pairs": 5})
    return {"clashes": d.get("clash_count"), "checked": d.get("elements_checked")}


@step("qc", "snapshot + compare", ["model_snapshot", "compare_models"])
def _snapshot(t):
    name = "selftest_%s" % t.stamp
    t.post("/qc/snapshot/", {"name": name, "categories": ["Walls"], "overwrite": True})
    d = t.post("/qc/compare/", {"baseline": name, "categories": ["Walls"]})
    check(d["summary"]["added"] == 0 and d["summary"]["removed"] == 0, "live model differs from snapshot", d)
    m = t.post("/qc/compare/", {"mode": "match", "source": {"categories": ["Walls"]},
                                "target": {"categories": ["Walls"]}, "tolerance": 1})
    check(m["summary"]["only_in_source"] == 0, "self-match should pair every wall", m)
    return d["summary"]


@step("qc", "clearance clashes + grid zones + grouping", ["check_clashes", "export_clash_report"])
def _clearance(t):
    d = t.post("/qc/clashes/", {"set_a": {"categories": ["Walls"]}, "set_b": {"categories": ["Floors"]},
                                "clearance": 50, "group_by": ["pair", "level", "grid_zone"], "max_pairs": 20})
    check(d.get("clearance") == 50 and "groups" in d, "clearance / grouping missing from the answer", d)
    for c in d.get("clashes") or []:
        check(c.get("type") in ("hard", "clearance"), "clash without type", c)
        check(c.get("type") == "hard" or c.get("distance", 999) <= 50, "clearance pair beyond 50 mm", c)
    dr = t.post("/qc/clashes/", {"set_a": {"categories": ["Walls"]}, "set_b": {"categories": ["Floors"]},
                                 "dry_run": True})
    check(dr.get("status") == "dry_run", "clash dry run expected", dr)
    return {"hard": d.get("hard_count"), "clearance": d.get("clearance_count"),
            "zones": [g["key"] for g in (d.get("groups") or {}).get("grid_zone", [])][:5]}


@step("qc", "ISO 19650 naming + view audit checks", ["run_model_checks"])
def _iso_views(t):
    rules = {"iso19650": {"delimiter": "-", "fields": [{"name": "project", "values": ["P1"]},
                                                        {"name": "number", "pattern": "^\\d{3}$"}],
                          "targets": {"sheets": {"source": "number"}, "views": {}, "worksets": {}}}}
    d = t.post("/qc/model_checks/", {"checks": ["iso19650", "view_audit"], "rules": rules})
    check(not d.get("checks_failed"), "checks crashed: %s" % d.get("checks_failed"), d)
    return d.get("summary")


@step("qc", "family library audit (dry run + real, read-only)", ["audit_family_library"])
def _library(t):
    dr = t.post("/family/library_audit/", {"folder": t.scratch, "recursive": False, "dry_run": True})
    check(dr.get("status") == "dry_run", "dry run expected", dr)
    if not dr.get("would_open"):
        raise StepSkipped("no .rfa in the scratch folder (family group skipped)")
    d = t.post("/family/library_audit/", {"folder": t.scratch, "recursive": False, "max_files": 3})
    check(d.get("audited") == len(dr["would_open"][:3]), "audited count", d)
    check(not [f for f in d["families"] if f.get("error")], "a family failed to open", d)
    return {"audited": d["audited"], "summary": d.get("summary")}


@step("qc", "mapping preset (dry run) + JSON export for Excel", ["map_parameters", "export_to_excel"])
def _preset_export(t):
    t.require_test_model()
    d = t.post("/parameters/map/", {"preset": "ifc_overrides", "categories": ["Walls"], "dry_run": True})
    check(d.get("status") in ("dry_run", "preview"), "preset dry run expected", d)
    e = t.post("/parameters/export/", {"categories": ["Walls"], "parameters": ["Length", "Mark"],
                                       "value_mode": "raw", "format": "json"})
    check(e.get("rows") and e.get("column_units", {}).get("Length") == "mm", "JSON export with units", e)
    return {"preset_unverified": d.get("unverified_targets"), "rows": e.get("row_count")}


# 9. v2.2 tools ----------------------------------------------------------------------------
@step("v22", "rooms, materials, MEP, coordinates (read-only)", ["list_rooms", "get_room_details", "list_materials",
                                                              "material_takeoff", "list_mep_systems",
                                                              "find_mep_disconnects", "get_coordinates"])
def _v22_read(t):
    rooms = t.post("/rooms/list/", {"kind": "room", "limit": 5})
    placed = [r for r in rooms.get("items") or [] if r.get("status") == "placed"]
    if placed:
        det = t.post("/rooms/details/", {"element_ids": [placed[0]["id"]]})
        check(det.get("items") and "finishes" in det["items"][0], "room finishes missing", det)
    mats = t.post("/materials/list/", {"limit": 5})
    take = t.post("/materials/takeoff/", {"filter": {"categories": ["Walls"]}, "group_by": ["material"]})
    check("rows" in take, "take-off rows missing", take)
    t.post("/mep/systems/", {"limit": 5})
    dis = t.post("/mep/disconnects/", {"limit": 5})
    co = t.post("/coordinates/", {"points": [[0, 0, 0]]})
    check(co.get("converted_points"), "point conversion missing", co)
    return {"rooms": rooms.get("count"), "materials": mats.get("count"), "takeoff_rows": len(take["rows"]),
            "open_connectors": dis.get("open_connectors"), "true_north": co.get("angle_to_true_north_deg")}


@step("v22", "impact survey + spatial query", ["survey_change_impact", "spatial_query"])
def _v22_impact(t):
    ids = t.require("wall_ids", "no walls")
    s = t.post("/impact/survey/", {"element_ids": ids[:1], "change_kind": "type"})
    groups = s["elements"][0]["groups"]
    check(groups["type"]["status"] == "found", "a wall must find its type siblings", s)
    for g in groups.values():
        check(g["status"] in ("found", "none", "not_checked"), "bad group status", g)
    d = t.post("/spatial/query/", {"mode": "distance", "element_a": ids[0], "element_b": ids[-1]})
    n = t.post("/spatial/query/", {"mode": "near_point", "point": [0, 0, 0], "radius": 100000, "limit": 5})
    return {"type_instances": groups["type"]["count"], "center_distance": d.get("center_distance"),
            "near": n.get("count")}


@step("v22", "annotation, filters, revisions, worksets, export settings (read-only)",
      ["find_untagged_elements", "manage_view_filters", "manage_revisions", "manage_worksets",
       "list_export_settings"])
def _v22_doc_read(t):
    untagged = None
    plan = t.state.get("plan_id") or t.state.get("plan_name")
    if plan:
        u = t.post("/annotation/untagged/", {"categories": ["Walls", "Doors"], "view": plan})
        untagged = u.get("untagged_total")
    f = t.post("/views/filters/", {"action": "list"})
    r = t.post("/sheets/revisions/", {"action": "list"})
    w = t.post("/worksets/manage/", {"action": "list"})
    e = t.post("/export/settings/")
    return {"untagged": untagged, "filters": f.get("count"), "revisions": r.get("count"),
            "workshared": w.get("workshared"),
            "dwg_setups": len(e.get("dwg_setups") or []), "nwc": e.get("navisworks_exporter_available")}


@step("v22", "dry runs: filter, material, tags, export plan, purge preview",
      ["manage_view_filters", "manage_materials", "tag_elements", "export_documents", "purge_unused"])
def _v22_dry(t):
    t.require_test_model()
    t.post("/views/filters/", {"action": "create", "name": "RVTSS SelfTest " + t.stamp, "categories": ["Walls"],
                               "rules": [{"parameter": "Comments", "op": "contains", "value": "RVTSS"}],
                               "dry_run": True})
    t.post("/materials/manage/", {"action": "create", "name": "RVTSS SelfTest " + t.stamp,
                                  "properties": {"color": "#808080"}, "dry_run": True})
    plan = t.state.get("plan_id") or t.require("plan_name", "no floor plan")
    tg = t.post("/annotation/tag/", {"view": plan, "categories": ["Walls"], "dry_run": True})
    check(tg.get("status") in ("dry_run", "preview"), "tag dry run expected", tg)
    ex = t.post("/export/run/", {"format": "dwg", "views": [plan], "dry_run": True})
    check(ex.get("status") == "dry_run" and ex.get("files"), "export plan expected", ex)
    pg = t.post("/purge/", {})
    check(pg.get("status") in ("preview", "success"), "purge must only preview without confirm", pg)
    return {"tags_planned": tg.get("tagged"), "export_files": ex.get("file_count"), "purgeable": pg.get("candidates")}


@step("v22", "batch_execute: dry run, then failure rolls back", ["batch_execute"])
def _v22_batch(t):
    t.require_test_model()
    eid = t.require("wall_ids", "no walls")[0]
    before = _comments(t, eid)
    cmds = [{"index": 0, "tool": "set_parameters", "endpoint": "/set_parameters/",
             "payload": {"updates": [{"element_id": eid, "parameter": "Comments", "value": "RVTSS batch"}]}},
            {"index": 1, "tool": "create_view", "endpoint": "/views/create/",
             "payload": {"kind": "drafting", "name": "RVTSS Batch " + t.stamp}}]
    d = t.post("/batch/", {"commands": cmds, "dry_run": True})
    check(d.get("status") == "dry_run" and d.get("succeeded") == 2, "batch dry run", d)
    check(_comments(t, eid) == before, "batch dry run changed the model")
    bad = cmds[:1] + [{"index": 1, "tool": "set_parameters", "endpoint": "/set_parameters/",
                       "payload": {"updates": [{"element_id": 999999999, "parameter": "Comments", "value": "x"}]}}]
    f = t.post("/batch/", {"commands": bad}, expect_error=True)
    check(f.get("rolled_back") is True, "failed batch must roll back", f)
    check(_comments(t, eid) == before, "rolled-back batch left a change behind")
    return {"dry_run": d.get("succeeded"), "rolled_back": f.get("rolled_back")}


# 9. v2.3 ----------------------------------------------------------------------------
@step("v23", "capture elements as a 3D image", ["capture_elements"])
def _v23_capture(t):
    ids = t.require("seed_wall_ids", "no seeded walls")
    before = t.post("/find_views/", {"view_types": ["ThreeD"], "limit": 1000}).get("count")
    d = t.post("/views/capture/", {"element_ids": ids, "orientation": "iso_se", "pixel_size": 512})
    check(d.get("file_size_bytes", 0) > 1000 and d.get("image_data"), "no image", {"keys": list(d)})
    after = t.post("/find_views/", {"view_types": ["ThreeD"], "limit": 1000}).get("count")
    check(before == after, "the temporary 3D view was kept (%s -> %s views)" % (before, after))
    return {"bytes": d["file_size_bytes"], "section_box": d.get("section_box")}


@step("v23", "create_elements: openings, shaft, railing, space, rooms, mesh, MEP (dry run)", ["create_elements"])
def _v23_kinds(t):
    t.require_test_model()
    walls = t.require("seed_wall_ids", "no seeded walls")
    level, top = t.state["seed_level"], t.state.get("seed_top_level")
    items = [
        {"kind": "wall_opening", "wall_id": walls[0], "offset_along": 1000, "width": 900, "height": 2100},
        {"kind": "opening", "host_id": t.state["seed_floor_id"],
         "boundary": [[2000, 2000], [3000, 2000], [3000, 3000], [2000, 3000]]},
        {"kind": "railing", "points": [[500, 500], [500, 5500]], "level": level},
        {"kind": "roof", "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "level": top or level,
         "slope_deg": 20},
        {"kind": "space", "level": level, "point": [4000, 3000], "name": "RVTSS space"},
        {"kind": "auto_rooms", "level": level},
        {"kind": "direct_shape", "name": "RVTSS tetra",
         "vertices": [[0, 0, 0], [1000, 0, 0], [0, 1000, 0], [0, 0, 1000]],
         "faces": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]},
        {"kind": "duct", "points": [[1000, 1000], [6000, 1000], [6000, 5000]], "level": level, "offset": 2700},
        {"kind": "pipe", "points": [[1000, 1500], [6000, 1500]], "level": level, "offset": 2500},
        {"kind": "cable_tray", "points": [[1000, 2000], [6000, 2000]], "level": level, "offset": 2600},
        {"kind": "conduit", "points": [[1000, 2200], [6000, 2200]], "level": level, "offset": 2600},
        {"kind": "toposolid", "level": level, "points": [[-5000, -5000, -500], [15000, -5000, -500],
                                                         [15000, 15000, -400], [-5000, 15000, -600]]},
    ]
    if top:
        items.append({"kind": "shaft", "level": level, "top_level": top,
                      "boundary": [[6500, 4500], [7500, 4500], [7500, 5500], [6500, 5500]]})
    _status, d = t.transport("POST", "/create_elements/", {"items": items, "atomic": False, "dry_run": True})
    res = dict((it["kind"], r) for it, r in zip(items, d.get("results") or []))
    must = ["wall_opening", "opening", "railing", "roof", "space", "auto_rooms", "direct_shape"] + (["shaft"] if top else [])
    bad = dict((k, (res.get(k) or {}).get("error") or d.get("error")) for k in must if not (res.get(k) or {}).get("ok"))
    check(d.get("status") == "dry_run" and not bad, "kinds failed: %s" % bad, d)
    optional = dict((k, "ok" if (res.get(k) or {}).get("ok") else (res.get(k) or {}).get("error"))
                    for k in ("duct", "pipe", "cable_tray", "conduit", "toposolid"))
    return {"ok": sorted(k for k in res if res[k].get("ok")), "mep_and_topo": optional}


@step("v23", "transform: array, pin, join (dry run)", ["transform_elements"])
def _v23_transform(t):
    t.require_test_model()
    walls = t.require("seed_wall_ids", "no seeded walls")
    a = t.post("/transform_elements/", {"operation": "array", "element_ids": walls[:1], "vector": [0, 1000, 0],
                                        "count": 3, "dry_run": True})
    check(a.get("status") == "dry_run" and len(a.get("new_element_ids") or []) == 2, "array of 3 expected", a)
    p = t.post("/transform_elements/", {"operation": "pin", "element_ids": walls[:2], "dry_run": True})
    check(all(r["ok"] for r in p["results"]), "pin failed", p)
    j = t.post("/transform_elements/", {"operation": "join", "element_ids": [t.state["seed_floor_id"], walls[0]],
                                        "dry_run": True})
    check(j["results"][0]["ok"], "join failed", j)
    return {"array_new": len(a["new_element_ids"]), "joined": j["results"][0].get("joined")}


@step("v23", "stairs between two levels (dry run)", ["create_stairs"])
def _v23_stairs(t):
    t.require_test_model()
    top = t.require("seed_top_level", "only one level")
    d = t.post("/stairs/create/", {"base_level": t.state["seed_level"], "top_level": top, "width": 1100,
                                   "runs": [{"start": [1000, 4000], "end": [4000, 4000]},
                                            {"start": [4000, 5200], "end": [1000, 5200]}],
                                   "railings": True, "dry_run": True})
    check(d.get("status") == "dry_run" and d.get("stairs_id") and len(d.get("run_ids") or []) == 2, "stairs", d)
    return {"risers": d.get("risers"), "riser_height": d.get("riser_height"),
            "landings": len(d.get("landing_ids") or [])}


@step("v23", "phases, links, selection sets", ["manage_phases", "manage_links", "selection_sets"])
def _v23_state(t):
    t.require_test_model()
    walls = t.require("seed_wall_ids", "no seeded walls")
    ph = t.post("/phases/manage/", {"action": "list"})
    check(ph.get("phases"), "no phases", ph)
    sp = t.post("/phases/manage/", {"action": "set_element_phase", "element_ids": walls[:1],
                                    "created": ph["phases"][-1]["name"], "dry_run": True})
    check(sp.get("status") == "dry_run", "phase dry run", sp)
    ln = t.post("/links/manage/", {"action": "list"})
    name = "RVTSS set " + t.stamp
    t.post("/selection_sets/", {"action": "save", "name": name, "element_ids": walls})
    ld = t.post("/selection_sets/", {"action": "load", "name": name})
    check(ld.get("count") == len(walls), "selection set count", ld)
    t.post("/selection_sets/", {"action": "delete", "name": name})
    return {"phases": len(ph["phases"]), "links": ln.get("count"), "set_count": ld.get("count")}


@step("v23", "undo the last RVTSS change", ["undo_last_change", "set_parameters"])
def _v23_undo(t):
    t.require_test_model()
    wall = t.require("seed_wall_ids", "no seeded walls")[0]
    st = t.post("/undo/", {"action": "status"})
    check(st.get("listening"), "undo listener not running", st)
    before = _comments(t, wall)
    t.post("/set_parameters/", {"updates": [{"element_id": wall, "parameter": "Comments", "value": "undo me"}]})
    check(_comments(t, wall) == "undo me", "change not applied")
    u = t.post("/undo/", {"action": "undo", "expect_tool": "set_parameters"})
    check(u.get("status") == "posted", "undo not posted", u)
    after = None
    for _i in range(20):  # Revit runs the posted Undo once the request has returned
        time.sleep(0.5)
        after = _comments(t, wall)
        if after == before:
            break
    check(after == before, "undo did not revert Comments (%r -> %r)" % (before, after))
    return {"undone": (u.get("undoing") or {}).get("names")}


# 10. v2.4 ---------------------------------------------------------------------------
def _expected_refusal(data, *needles):
    """True when a call failed for a reason the empty test template explains (no MEP types, no revision...)."""
    msg = (data.get("error") or "").lower()
    return any(n.lower() in msg for n in needles)


@step("v24", "ribbon command launcher", ["list_revit_commands", "run_revit_command"])
def _v24_commands(t):
    d = t.post("/commands/list/", {"contains": "scope box"})
    names = [c["name"] for c in d.get("commands") or []]
    check("ScopeBox" in names, "ScopeBox not among Revit's postable commands", d)
    total = t.post("/commands/list/", {"limit": 1}).get("count")
    check(total and total > 100, "expected Revit's full command list", {"count": total})
    dr = t.post("/commands/run/", {"name": "ScopeBox", "dry_run": True})
    check(dr.get("status") == "dry_run" and "available_now" in dr, "command dry run", dr)
    refused = t.post("/commands/run/", {"name": "Undo"}, expect_error=True)
    check("undo_last_change" in (refused.get("hint") or ""), "Undo must be refused with a pointer", refused)
    t.post("/commands/run/", {"name": "SynchronizeNow"}, expect_error=True)
    return {"commands": total, "scope_box_available": dr.get("available_now")}


@step("v24", "view extents: crop, view range, section box (dry run)", ["view_extents"])
def _v24_extents(t):
    t.require_test_model()
    plan = t.require("plan_id", "no floor plan")
    walls = t.require("seed_wall_ids", "no seeded walls")
    g = t.post("/views/extents/", {"view": plan})
    check("view_range" in g and "crop_active" in g, "plan extents incomplete", g)
    vr = t.post("/views/extents/", {"action": "set_view_range", "view": plan, "cut": 1500, "dry_run": True})
    check(vr.get("status") == "dry_run" and abs(vr["view_range"]["cut"]["offset"] - 1500) < 1, "view range", vr)
    cr = t.post("/views/extents/", {"action": "set_crop", "view": plan, "element_ids": walls, "margin": 1000,
                                    "dry_run": True})
    check(cr.get("status") == "dry_run" and cr.get("crop_active") is True, "crop to elements", cr)
    check(abs((cr["crop_max"][0] - cr["crop_min"][0]) - 10000) < 400, "crop width should be about 10 m", cr)
    after = t.post("/views/extents/", {"view": plan})
    check(after["view_range"]["cut"]["offset"] == g["view_range"]["cut"]["offset"], "dry run changed the view range")
    out = {"cut_before": g["view_range"]["cut"]["offset"]}
    v3 = t.post("/find_views/", {"view_types": ["ThreeD"], "limit": 5}).get("views") or []
    if v3:
        sb = t.post("/views/extents/", {"action": "set_section_box", "view": str(v3[0]["id"]),
                                        "element_ids": walls, "dry_run": True})
        check(sb.get("section_box_active") is True, "section box", sb)
        out["section_box"] = True
    return out


@step("v24", "view templates: create from a view, apply, delete", ["manage_view_templates"])
def _v24_templates(t):
    t.require_test_model()
    plan = t.require("plan_id", "no floor plan")
    name = "RVTSS template " + t.stamp
    c = t.post("/views/templates/", {"action": "create_from_view", "view": plan, "name": name})
    check(c.get("template_id"), "template not created", c)
    lst = t.post("/views/templates/", {"action": "list", "parameters": True})
    mine = [x for x in lst.get("templates") or [] if x["name"] == name]
    check(mine and mine[0].get("parameters"), "new template not listed with its parameters", lst)
    ap = t.post("/views/templates/", {"action": "apply", "template": name, "views": [plan], "dry_run": True})
    check(ap.get("status") == "dry_run" and ap["results"][0]["ok"], "apply dry run", ap)
    t.post("/views/templates/", {"action": "delete", "template": name})
    names = [x["name"] for x in t.post("/views/templates/", {"action": "list"}).get("templates") or []]
    check(name not in names, "template was not deleted")
    return {"templates": lst.get("count"), "controlled_parameters": len(mine[0]["parameters"])}


@step("v24", "viewports: place a view, list, move, remove", ["manage_viewports", "manage_sheets", "create_view"])
def _v24_viewports(t):
    t.require_test_model()
    plan = t.require("plan_id", "no floor plan")
    v = t.post("/views/create/", {"kind": "duplicate", "source_view": plan, "name": "RVTSS vp " + t.stamp})
    s = t.post("/sheets/manage/", {"action": "create", "number": "RV-" + t.stamp[-6:], "name": "RVTSS viewports"})
    sheet_id = s["sheets"][0]["sheet_id"]
    p = t.post("/sheets/manage/", {"action": "place_view", "sheet_id": sheet_id, "view": str(v["view_id"]),
                                   "location": [300, 200]})
    lst = t.post("/sheets/viewports/", {"action": "list", "sheet": str(sheet_id)})
    check(len(lst.get("viewports") or []) == 1, "one viewport expected", lst)
    m = t.post("/sheets/viewports/", {"action": "move", "viewport_id": p["viewport_id"], "location": [250, 180]})
    c = m["viewport"]["center"]
    check(abs(c[0] - 250) < 1 and abs(c[1] - 180) < 1, "viewport did not move", m)
    t.post("/sheets/viewports/", {"action": "rotate", "viewport_id": p["viewport_id"], "rotation": "clockwise",
                                  "dry_run": True})
    t.post("/sheets/viewports/", {"action": "remove", "viewport_id": p["viewport_id"]})
    left = t.post("/sheets/viewports/", {"action": "list", "sheet": str(sheet_id)})
    check(not left.get("viewports"), "viewport was not removed", left)
    return {"viewport_types": lst.get("viewport_types"), "moved_to": c}


@step("v24", "callout, legend, schedule kinds (dry run)", ["create_view", "create_schedule"])
def _v24_view_kinds(t):
    t.require_test_model()
    plan = t.require("plan_id", "no floor plan")
    co = t.post("/views/create/", {"kind": "callout", "source_view": plan, "min": [1000, 1000],
                                   "max": [4000, 3000], "dry_run": True})
    check(co.get("status") == "dry_run" and co.get("view_id"), "callout", co)
    out = {"callout": co.get("view_type")}
    for kind, payload in (("sheet_list", {"fields": ["Sheet Number", "Sheet Name"]}),
                          ("view_list", {"fields": ["View Name"]}),
                          ("key", {"category": "Rooms"}),
                          ("material_takeoff", {"category": "Walls", "fields": ["Material: Name"]})):
        d = t.post("/schedules/create/", dict(payload, kind=kind, strict=False, dry_run=True))
        check(d.get("status") == "dry_run" and d.get("schedule_id"), kind + " schedule", d)
        out[kind] = d.get("fields")
    _st, lg = t.transport("POST", "/views/create/", {"kind": "legend", "dry_run": True})
    check(lg.get("status") == "dry_run" or _expected_refusal(lg, "no legend"), "legend", lg)
    out["legend"] = lg.get("status") if lg.get("status") == "dry_run" else "no legend in the template"
    return out


@step("v24", "detailing: masking region, revision cloud, spot elevation (dry run)", ["create_detailing"])
def _v24_detailing(t):
    t.require_test_model()
    plan = t.require("plan_id", "no floor plan")
    box = [[1000, 1000], [2500, 1000], [2500, 2000], [1000, 2000]]
    items = [{"kind": "masking_region", "boundary": box},
             {"kind": "revision_cloud", "boundary": box},
             {"kind": "spot_elevation", "element_id": t.state.get("seed_floor_id"), "point": [4000, 3000]}]
    _st, d = t.transport("POST", "/annotation/detail/", {"view": plan, "items": items, "atomic": False,
                                                        "dry_run": True})
    check(d.get("status") == "dry_run" and len(d.get("results") or []) == 3, "detailing dry run", d)
    out = {}
    for item, r in zip(items, d["results"]):
        if r.get("ok"):
            out[item["kind"]] = "ok"
            continue
        # the empty template may have no masking type and no revision: anything else is a real failure
        check(_expected_refusal(r, "no masking", "no revision", "is issued", "spot dimension", "not over the top"),
              "%s failed: %s" % (item["kind"], r.get("error")), d)
        out[item["kind"]] = r.get("error")
    return out


@step("v24", "find and replace in text notes", ["replace_text", "create_text_notes"])
def _v24_replace_text(t):
    t.require_test_model()
    plan = t.require("plan_id", "no floor plan")
    word = "RVTSSFIND" + t.stamp[-6:]
    t.post("/annotation/text/", {"view": plan, "notes": [{"text": "Check " + word + " here", "point": [2000, 2000]},
                                                         {"text": "nothing to see", "point": [2000, 2500]}]})
    dr = t.post("/annotation/text/replace/", {"find": word, "replace": "done", "views": [plan], "dry_run": True})
    check(dr.get("status") == "dry_run" and dr.get("text_notes_changed") == 1, "one note should match", dr)
    again = t.post("/annotation/text/replace/", {"find": word, "replace": "done", "views": [plan], "dry_run": True})
    check(again.get("text_notes_changed") == 1, "the dry run changed the text", again)
    real = t.post("/annotation/text/replace/", {"find": word, "replace": "done", "views": [plan]})
    check(real.get("status") == "success" and real["changed"][0]["new"] == "Check done here", "replace", real)
    gone = t.post("/annotation/text/replace/", {"find": word, "replace": "x", "views": [plan], "dry_run": True})
    check(gone.get("text_notes_changed") == 0, "the word is still there", gone)
    return {"searched": dr.get("text_notes_searched"), "replacements": real.get("replacements")}


@step("v24", "MEP editing: circuits, insulation, connect, placeholder", ["manage_mep_systems", "mep_insulation",
                                                                        "mep_connect", "create_mep_parts"])
def _v24_mep_edit(t):
    t.require_test_model()
    wall = t.require("seed_wall_ids", "no seeded walls")[0]
    ci = t.post("/mep/systems/manage/", {"action": "list_circuits"})
    ins = t.post("/mep/insulation/", {"action": "list", "element_ids": [wall]})
    dc = t.post("/mep/connect/", {"action": "disconnect", "element_ids": [wall], "dry_run": True})
    check(dc.get("status") == "dry_run", "disconnect dry run", dc)
    _st, ph = t.transport("POST", "/mep/create/", {"action": "pipe_placeholder", "points": [[0, 0], [3000, 0]],
                                                   "offset": 2700, "dry_run": True})
    # an architectural template has no pipe types or piping systems
    check(ph.get("status") == "dry_run" or _expected_refusal(ph, "no piping system", "no pipe type"),
          "pipe placeholder", ph)
    return {"circuits": ci.get("count"), "insulation": len(ins.get("insulation") or []),
            "placeholder": ph.get("status") if ph.get("status") == "dry_run" else ph.get("error")}


@step("v24", "modify: align, offset, trim, split, flip, scale, parts (dry run)", ["modify_elements",
                                                                                 "create_elements"])
def _v24_modify(t):
    t.require_test_model()
    level = t.require("seed_level", "no level")
    made = t.post("/create_elements/", {"items": [
        {"kind": "wall", "start": [12000, 0], "end": [18000, 0], "level": level, "height": 3000},
        {"kind": "wall", "start": [15000, -2000], "end": [15000, 3000], "level": level, "height": 3000}]})
    w1, w2 = [r["id"] for r in made["results"]]
    out = {}
    for op, payload in (("align", {"element_ids": [w2], "axis": "x", "coordinate": 16000}),
                        ("offset", {"element_ids": [w1], "distance": 1000, "copy": True}),
                        ("trim_extend", {"element_ids": [w1, w2]}),
                        ("split", {"element_ids": [w1], "parameter": 0.5}),
                        ("flip", {"element_ids": [w1]}),
                        ("scale", {"element_ids": [w1], "factor": 2, "center": [12000, 0]}),
                        ("create_parts", {"element_ids": [w1]})):
        d = t.post("/modify/elements/", dict(payload, operation=op, dry_run=True))
        check(d.get("status") == "dry_run", op + " dry run", d)
        out[op] = "ok"
    still = t.post("/element_details/", {"element_ids": [w1, w2]})
    check(len(still.get("elements") or []) == 2, "a dry run removed or replaced the walls", still)
    k = t.post("/create_elements/", {"items": [
        {"kind": "model_line", "points": [[12000, 5000], [15000, 5000], [15000, 8000]], "level": level},
        {"kind": "reference_plane", "start": [12000, -1000], "end": [18000, -1000], "name": "RVTSS RP " + t.stamp,
         "view": t.state.get("plan_id")}], "atomic": False, "dry_run": True})
    out["kinds"] = dict((it, "ok" if r.get("ok") else r.get("error"))
                        for it, r in zip(("model_line", "reference_plane"), k.get("results") or []))
    check(k["results"][0].get("ok"), "model_line failed", k)
    return out


@step("v24", "project settings, styles, CAD list, worksharing status", ["project_settings", "manage_styles",
                                                                       "insert_files", "worksharing"])
def _v24_admin(t):
    t.require_test_model()
    g = t.post("/project/settings/", {"action": "get"})
    for payload in ({"action": "set_info", "values": {"Number": "RVTSS-TEST"}},
                    {"action": "set_units", "units": {"length": {"unit": "mm", "rounding": 1}}},
                    {"action": "set_location", "true_north_angle": 10}):
        d = t.post("/project/settings/", dict(payload, dry_run=True))
        check(d.get("status") == "dry_run", payload["action"] + " dry run", d)
    pats = t.post("/styles/manage/", {"action": "list_patterns"})
    for payload in ({"action": "create_line_pattern", "name": "RVTSS test " + t.stamp,
                     "segments": [{"type": "dash", "length": 6}, {"type": "space", "length": 3}]},
                    {"action": "create_fill_pattern", "name": "RVTSS hatch " + t.stamp, "spacing": 50, "angle": 45},
                    {"action": "set_object_style", "category": "Walls", "line_weight": 3}):
        d = t.post("/styles/manage/", dict(payload, dry_run=True))
        check(d.get("status") == "dry_run", payload["action"] + " dry run", d)
    cad = t.post("/insert/files/", {"action": "list"})
    ws = t.post("/worksharing/", {"action": "status"})
    check("workshared" in ws, "worksharing status", ws)
    return {"settings_keys": sorted(k for k in g if k != "status")[:12], "pattern_keys": sorted(pats)[:6],
            "cad_keys": sorted(cad)[:6], "workshared": ws.get("workshared")}


@step("v24", "transfer project standards: list from another open document", ["transfer_project_standards"])
def _v24_transfer(t):
    t.require_test_model()
    info = t.post("/session_info/")
    docs = [d for d in (info.get("open_documents") or [])
            if not d.get("is_family") and d.get("title") != info.get("active_document")]
    if not docs:
        raise StepSkipped("needs a second open project to copy from")
    d = t.post("/standards/transfer/", {"source": docs[0]["title"], "action": "list"})
    return {"source": docs[0]["title"], "keys": sorted(k for k in d if k != "status")[:10]}


@step("v24", "load a family from disk (dry run)", ["load_family"])
def _v24_load_family(t):
    t.require_test_model()
    path = t.state.get("family_path") or t.state.get("rfa_path")
    if not path:
        raise StepSkipped("no .rfa saved by the family workflow in this run")
    d = t.post("/insert/family/", {"paths": [path], "dry_run": True})
    check(d.get("status") == "dry_run", "load family dry run", d)
    return {"path": path}


# ------------------------------------------------------------------ runner
def run(transport, scratch_dir, prepare_model=None, groups=None, log=None, environment=None):
    t = TestContext(transport, scratch_dir, prepare_model, log)
    started = time.time()
    results = []
    for s in STEPS:
        if groups and s["group"] not in groups and s["group"] != "status":
            continue
        t0 = time.time()
        entry = {"group": s["group"], "name": s["name"], "tools": s["tools"]}
        try:
            details = s["fn"](t)
            entry["status"] = PASS
            if details is not None:
                entry["details"] = details
        except StepSkipped as e:
            entry["status"] = SKIP
            entry["reason"] = str(e)
        except StepFailed as e:
            entry["status"] = FAIL
            entry["error"] = e.message
            for k in ("hint", "traceback", "did_you_mean", "failed_item", "failures", "inner_exception"):
                if e.data.get(k):
                    entry[k] = e.data[k]
        except Exception as e:  # bug in the plan or transport
            entry["status"] = FAIL
            entry["error"] = "%s: %s" % (type(e).__name__, e)
            entry["traceback"] = traceback.format_exc()
        entry["duration_ms"] = int((time.time() - t0) * 1000)
        results.append(entry)
        t.log("[%s] %s / %s" % (entry["status"].upper(), s["group"], s["name"]))
    env = dict(environment or {})
    env.update(t.state.get("env") or {})
    summary = {PASS: 0, FAIL: 0, SKIP: 0}
    for r in results:
        summary[r["status"]] += 1
    return {"report_version": 1, "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
            "duration_s": round(time.time() - started, 1), "environment": env, "summary": summary,
            "test_model": t.state.get("test_model"), "scratch_dir": scratch_dir,
            "tools": tool_summary(results), "steps": results}


def tool_summary(results):
    """Per MCP tool: fail if any step covering it failed, pass if any passed, else skip."""
    out = {}
    for r in results:
        for tool in r["tools"]:
            cur = out.get(tool)
            if r["status"] == FAIL or cur == FAIL:
                out[tool] = FAIL
            elif r["status"] == PASS or cur == PASS:
                out[tool] = PASS
            else:
                out[tool] = SKIP
    return dict(sorted(out.items()))


def to_markdown(report):
    env = report.get("environment") or {}
    s = report["summary"]
    lines = ["# RVTSS live self-test", "",
             "Started %s, %s s. **%d passed, %d failed, %d skipped.**" % (
                 report["started"], report["duration_s"], s[PASS], s[FAIL], s[SKIP]), "",
             "| Environment | |", "|---|---|"]
    for k in ("revit_version", "revit_build", "pyrevit_version", "python_engine", "python_version", "rvtss_version",
              "transport", "active_document"):
        if env.get(k) is not None:
            lines.append("| %s | %s |" % (k, env.get(k)))
    lines += ["", "## Steps", "", "| Group | Step | Result | ms | Notes |", "|---|---|---|---|---|"]
    for r in report["steps"]:
        note = r.get("error") or r.get("reason") or (json.dumps(r.get("details"))[:140] if r.get("details") else "")
        lines.append("| %s | %s | %s | %s | %s |" % (r["group"], r["name"], r["status"].upper(), r["duration_ms"],
                                                   note.replace("|", "\\|").replace("\n", " ")))
    lines += ["", "## Tools", "", "| Tool | Result |", "|---|---|"]
    for tool, res in report["tools"].items():
        lines.append("| `%s` | %s |" % (tool, res.upper()))
    fails = [r for r in report["steps"] if r["status"] == FAIL]
    if fails:
        lines += ["", "## Failures", ""]
        for r in fails:
            lines += ["### %s / %s" % (r["group"], r["name"]), "", "Error: %s" % r.get("error")]
            if r.get("hint"):
                lines.append("Hint: %s" % r["hint"])
            if r.get("traceback"):
                lines += ["", "```", r["traceback"][-2500:], "```"]
            lines.append("")
    return "\n".join(lines) + "\n"


def to_json(report):
    return json.dumps(report, indent=1, sort_keys=False, default=str)
