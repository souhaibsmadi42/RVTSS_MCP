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
    d = t.get("/status/")
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
                                   "include_types": True, "limit": 1})
    if not d.get("elements"):
        raise StepSkipped("no furniture / generic model type loaded")
    typ = d["elements"][0]
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
    if t.state.get("plan_name"):
        u = t.post("/annotation/untagged/", {"categories": ["Walls", "Doors"], "view": t.state["plan_name"]})
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
    plan = t.require("plan_name", "no floor plan")
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
