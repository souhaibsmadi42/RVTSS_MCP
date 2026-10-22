# -*- coding: utf-8 -*-
"""Phase 6: clash zones/grouping/reports, ISO 19650 naming, view audit, mapping presets,
family library audit, Excel export and the new coordination tools."""
import csv
import importlib
import io
import json
import os

import pytest

from revit_mcp.pure import clash as CL
from revit_mcp.pure import naming as N
from revit_mcp.pure import view_audit as VA
from revit_mcp.pure import mapping_presets as MP
from revit_mcp.pure import family_library as FL
from tools import excel_export as XL

from .revit_stubs import revit_environment, FakeRequest

# 3 x 3 orthogonal grids, 8 m spacing: letters run along X (vertical lines), numbers along Y
GRIDS = [{"name": n, "start": [x, -1000], "end": [x, 17000]} for n, x in (("A", 0), ("B", 8000), ("C", 16000))] + \
        [{"name": n, "start": [-1000, y], "end": [17000, y]} for n, y in (("1", 0), ("2", 8000), ("3", 16000))]


def _clash(a_cat, b_cat, point, level="Level 1", kind="hard", aid=1, bid=2):
    return {"a": {"id": aid, "category": a_cat, "family": a_cat + " fam", "type": "T1"},
            "b": {"id": bid, "category": b_cat, "family": b_cat + " fam", "type": "T2"},
            "type": kind, "distance": 0 if kind == "hard" else 30.0, "point": point, "level": level}


# ----------------------------------------------------------------- clashes
class TestClashGeometry:
    def test_intersections_and_names(self):
        inters = CL.grid_intersections(GRIDS)
        assert len(inters) == 9
        names = set(i["name"] for i in inters)
        assert "A/1" in names and "C/3" in names and "1/A" not in names

    def test_parallel_lines_do_not_intersect(self):
        assert CL.line_intersection(GRIDS[0], GRIDS[1]) is None

    def test_zone_and_nearest(self):
        assert CL.grid_zone([4000, 3000], GRIDS) == "A-B/1-2"
        assert CL.grid_zone([20000, 3000], GRIDS) == ">C/1-2"
        assert CL.grid_zone([-500, -500], GRIDS) == "<A/<1"
        near = CL.nearest_intersection([7000, 7500], CL.grid_intersections(GRIDS))
        assert near["name"] == "B/2" and near["distance"] == pytest.approx(1118.0, abs=1)

    def test_reversed_grid_direction_and_rotation(self):
        flipped = [dict(g, start=g["end"], end=g["start"]) if g["name"] == "B" else g for g in GRIDS]
        assert CL.grid_zone([4000, 3000], flipped) == "A-B/1-2"
        import math

        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))

        def rot(p):
            return [p[0] * c - p[1] * s, p[0] * s + p[1] * c]
        rotated = [dict(g, start=rot(g["start"]), end=rot(g["end"])) for g in GRIDS]
        assert CL.grid_zone(rot([4000, 3000]), rotated) == "A-B/1-2"

    def test_locate_group_rows(self):
        clashes = [_clash("Ducts", "Structural Framing", [4000, 3000, 3000]),
                   _clash("Ducts", "Structural Framing", [12000, 3000, 3000], kind="clearance", aid=3, bid=4),
                   _clash("Pipes", "Walls", [4000, 12000, 3000], level="Level 2", aid=5, bid=6)]
        CL.locate(clashes, GRIDS)
        assert clashes[1]["grid_zone"] == "B-C/1-2" and clashes[1]["nearest_grid"]["name"] in ("B/1", "C/1")
        pairs = CL.group_clashes(clashes, "pair")
        assert pairs[0]["key"] == "Ducts x Structural Framing" and pairs[0]["count"] == 2
        assert pairs[0]["hard"] == 1 and pairs[0]["clearance"] == 1 and pairs[0]["element_ids"] == [1, 2, 3, 4]
        assert [g["key"] for g in CL.group_clashes(clashes, "level")] == ["Level 1", "Level 2"]
        assert CL.group_clashes(clashes, "type_pair")[0]["key"].startswith("Ducts fam : T1 x")
        with pytest.raises(ValueError):
            CL.group_key(clashes[0], "bogus")
        rows = CL.clash_rows(clashes)
        assert rows[0][:5] == [1, "hard", 0, "Level 1", "A-B/1-2"] and rows[0][7] == 1

    def test_html_report_escapes_and_summarises(self):
        c = _clash("Ducts <x>", "Walls & Co", [1, 2, 3])
        report = {"clashes": [c], "unit": "mm", "clearance": 50, "document": "P1.rvt",
                  "groups": {"pair": CL.group_clashes([c], "pair")}}
        html = CL.to_html(report)
        assert "Ducts &lt;x&gt;" in html and "Walls &amp; Co" in html and "<x>" not in html
        assert "Grouped by pair" in html and "Distance [mm]" in html and "50 mm" in html


# ------------------------------------------------------------------ naming
SCHEME = {
    "delimiter": "-",
    "fields": [{"name": "project", "values": ["P123"]}, {"name": "originator", "values": ["ABC", "XYZ"]},
               {"name": "volume", "pattern": "^(ZZ|XX|[A-Z0-9]{2})$"},
               {"name": "level", "values": ["00", "01", "B1", "ZZ"]}, {"name": "type", "values": ["DR", "M3"]},
               {"name": "role", "values": ["A", "S"]}, {"name": "number", "pattern": "^\\d{4}$"}],
    "targets": {"sheets": {"source": "number", "severity": "error"},
                "worksets": {"delimiter": "_", "fields": [{"name": "discipline", "values": ["ARC", "STR"]},
                                                         {"name": "description", "min_length": 3},
                                                         {"name": "suffix", "optional": True}]}},
}


class TestIsoNaming:
    def test_valid_and_invalid_names(self):
        ts = N.target_scheme(SCHEME, "sheets")
        assert N.check_name("P123-ABC-ZZ-01-DR-A-0001", ts) == []
        errs = dict(N.check_name("P123-QQQ-ZZ-01-DR-A-12", ts))
        assert "not in allowed values" in errs["originator"] and "does not match" in errs["number"]
        assert N.check_name("P123-ABC", ts)[0][0] == "structure"

    def test_optional_case_and_lengths(self):
        ts = N.target_scheme(SCHEME, "worksets")
        assert N.check_name("ARC_Walls", ts) == []
        assert N.check_name("ARC_Walls_Ext", ts) == []
        assert dict(N.check_name("ARC_W", ts))["description"].startswith("'W' is shorter")
        field = {"name": "role", "values": ["A"], "case_sensitive": False}
        assert N.check_field(field, "a") is None and N.check_field({"name": "x", "length": 2}, "abc")

    def test_findings_and_untargeted(self):
        items = [(1, "P123-ABC-ZZ-01-DR-A-0001"), (2, "P123-ABC-ZZ-07-DR-A-0002"), (3, "bad")]
        f = N.check_items(items, SCHEME, "sheets")[0]
        assert f["severity"] == "error" and f["element_ids"] == [2, 3] and f["count"] == 2
        assert f["fields_violated"] == {"level": 1, "structure": 1} and "2 of 3 sheets" in f["message"]
        assert N.check_items(items, SCHEME, "views") == []

    def test_scheme_errors(self):
        with pytest.raises(N.SchemeError):
            N.target_scheme({"targets": {"views": {}}}, "views")
        with pytest.raises(N.SchemeError):
            N.target_scheme({"fields": [{"name": "x", "pattern": "("}], "targets": {"views": {}}}, "views")

    def test_example_rule_file_is_valid(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "docs", "examples", "qc_rules.iso19650.json"), encoding="utf-8") as fh:
            rules = json.load(fh)
        scheme = rules["iso19650"]
        for target in scheme["targets"]:
            assert target in N.TARGETS
            N.target_scheme(scheme, target)
        ts = N.target_scheme(scheme, "sheets")
        example = scheme["examples"]["sheets"]
        assert N.check_name(example, ts) == [], example


# --------------------------------------------------------------- view audit
def test_view_audit_findings():
    views = [
        {"id": 1, "name": "L1 Plan", "view_type": "FloorPlan", "template_id": 10, "on_sheet": True},
        {"id": 2, "name": "L1 Plan", "view_type": "CeilingPlan", "template_id": None, "on_sheet": False},
        {"id": 3, "name": "Working", "view_type": "FloorPlan", "template_id": None, "on_sheet": False,
         "scope_box_id": 50},
        {"id": 4, "name": "Dep", "view_type": "FloorPlan", "template_id": 10, "on_sheet": False, "is_dependent": True},
        {"id": 10, "name": "T-Plan", "is_template": True}, {"id": 11, "name": "T-Unused", "is_template": True},
    ]
    sheets = [{"id": 20, "number": "A-100", "name": "Plans", "view_count": 1},
              {"id": 21, "number": "A-101", "name": "Empty", "view_count": 0},
              {"id": 22, "number": "X", "name": "Placeholder", "view_count": 0, "is_placeholder": True}]
    boxes = [{"id": 50, "name": "SB-View"}, {"id": 51, "name": "SB-Grid"}, {"id": 52, "name": "SB-Idle"}]
    out = dict((f["message"], f) for f in VA.audit(views, sheets, boxes, {51}, ["FloorPlan", "CeilingPlan"]))
    assert out["2 views have no view template"]["element_ids"] == [2, 3]
    assert out["1 view templates are not used by any view"]["element_ids"] == [11]
    assert out["1 sheets have no views"]["element_ids"] == [21]
    assert out["2 views are not placed on any sheet"]["element_ids"] == [2, 3]  # dependent view excluded
    assert out["1 view names are used by more than one view"]["element_ids"] == [1, 2]
    assert out["1 scope boxes are not used by views or datums"]["element_ids"] == [52]
    only_plans = VA.audit(views, [], [], None, ["FloorPlan"])
    assert [f for f in only_plans if "no view template" in f["message"]][0]["element_ids"] == [3]


# ------------------------------------------------------------ presets
class TestPresets:
    def test_builtin_presets_are_well_formed(self):
        for name in MP.PRESETS:
            ms = MP.get_preset(name)
            assert ms and all(m["from"] and m["to"] and "verified" in m for m in ms)
        assert MP.get_preset("cobie_type")[0] == {"from": "Manufacturer", "to": "COBie.Type.Manufacturer",
                                                  "allow_type": True, "verified": True}
        assert "COBie.Type.ModelNumber" in MP.describe()["cobie_type"]["unverified_targets"]

    def test_user_preset_and_errors(self):
        office = {"office_ifc": {"description": "x", "mappings": [{"from": "A", "to": "B", "categories": ["Doors"]}]}}
        assert MP.get_preset("office_ifc", office)[0]["to"] == "B"
        with pytest.raises(MP.PresetError):
            MP.get_preset("nope", office)
        with pytest.raises(MP.PresetError):
            MP.get_preset("bad", {"bad": {"mappings": [{"from": "A"}]}})
        ms = MP.get_preset("ifc_overrides")
        ms[0]["to"] = "changed"
        assert MP.get_preset("ifc_overrides")[0]["to"] == "IfcTag"  # copies, not shared

    def test_applies_and_categories(self):
        m = {"from": "Number", "to": "IfcName", "categories": ["Rooms"]}
        assert MP.applies(m, "Rooms") and MP.applies(m, "rooms") and not MP.applies(m, "Doors")
        assert MP.applies({"from": "a", "to": "b"}, None)
        assert MP.preset_categories(MP.get_preset("cobie_space")) == ["Rooms"]
        assert MP.preset_categories(MP.get_preset("cobie_type")) == []


# ---------------------------------------------------------- family library
class TestFamilyLibrary:
    def test_file_listing(self, tmp_path):
        (tmp_path / "sub").mkdir()
        for name in ("Door.rfa", "Door.0001.rfa", "Chair.RFA", "notes.txt", "sub/Table.rfa"):
            (tmp_path / name).write_text("x")
        files = FL.list_files(os.walk(str(tmp_path)), True, str(tmp_path))
        assert [os.path.basename(f) for f in files] == ["Chair.RFA", "Door.rfa", "Table.rfa"]
        top = FL.list_files(os.walk(str(tmp_path)), False, str(tmp_path))
        assert [os.path.basename(f) for f in top] == ["Chair.RFA", "Door.rfa"]

    def test_findings(self):
        ok = {"file": "ABC_Door_Single.rfa", "path": "C:/lib/ABC_Door_Single.rfa", "size_kb": 300,
              "category": "Doors", "types": ["900"], "nested": [], "warnings": [],
              "parameters": [{"name": "Width"}, {"name": "Frame"}],
              "validation": {"summary": {"by_severity": {"error": 0}}, "findings": []}}
        bad = {"file": "chair.rfa", "path": "C:/lib/chair.rfa", "size_kb": 5000, "category": "Generic Models",
               "types": [], "nested": ["n%d" % i for i in range(12)], "warnings": ["Line is too short"],
               "parameters": [{"name": "Width"}, {"name": "width", "shared": True}],
               "validation": {"summary": {"by_severity": {"error": 2}},
                              "findings": [{"severity": "error", "message": "Family has no types"}]}}
        broken = {"file": "broken.rfa", "path": "C:/lib/broken.rfa", "error": "newer version"}
        findings = FL.library_findings([ok, bad, broken], {"pattern": "^[A-Z]{3}_"}, None, 2048, 10)
        checks = dict((f["check"], f) for f in findings)
        assert checks["library_open"]["element_ids"] == ["broken"]
        assert checks["library_size"]["element_ids"] == ["chair"]
        for c in ("library_category", "library_types", "library_nested", "library_warnings", "library_parameters"):
            assert checks[c]["element_ids"] == ["chair"], c
        assert checks["library_validation"]["details"] == {"chair": ["Family has no types"]}
        assert set(checks["library_naming"]["element_ids"]) == {"chair", "broken"}
        row = FL.summary_row(bad)
        assert row["family"] == "chair" and row["validation_errors"] == 2 and row["shared_parameters"] == 1

    def test_iso_naming_of_families(self):
        scheme = {"targets": {"families": {"delimiter": "_", "fields": [
            {"name": "originator", "values": ["ABC"]}, {"name": "category", "min_length": 3},
            {"name": "description", "min_length": 2}]}}}
        recs = [{"file": "ABC_Door_Single.rfa", "path": "ABC_Door_Single.rfa"},
                {"file": "XYZ_Door_S.rfa", "path": "XYZ_Door_S.rfa"}]
        f = [x for x in FL.library_findings(recs, None, scheme) if x["check"] == "iso19650"][0]
        assert f["element_ids"] == ["XYZ_Door_S"]


def test_library_audit_route_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    (tmp_path / "lib").mkdir()
    for name in ("A.rfa", "B.rfa", "B.0003.rfa"):
        (tmp_path / "lib" / name).write_bytes(b"0" * 2048)
    with revit_environment():
        startup = importlib.import_module("startup")
        route = [r for r in startup.api.routes if r["path"] == "/family/library_audit/"][0]["func"]
        res = route(doc=None, request=FakeRequest({"folder": str(tmp_path / "lib"), "dry_run": True,
                                                   "max_files": 1}))
        assert res["status"] == 200, res
        data = res["data"]
        assert data["status"] == "dry_run" and data["families_found"] == 2 and data["would_open"] == ["A.rfa"]
        assert data["skipped"] == [{"file": "B.rfa", "reason": "max_files=1 reached"}]
        missing = route(doc=None, request=FakeRequest({"folder": str(tmp_path / "nope")}))
        assert missing["status"] == 404


# ------------------------------------------------------------------ excel
class TestExcel:
    def test_sheet_titles(self):
        used = set()
        assert XL.sheet_title("Doors", used) == "Doors"
        assert XL.sheet_title("doors", used) == "doors (2)"
        assert XL.sheet_title("A/B:C*?[x]", used) == "A_B_C___x_"
        long = XL.sheet_title("x" * 40, used)
        assert len(long) == 31 and len(XL.sheet_title("x" * 40, used)) == 31

    def test_category_sheet_headers(self):
        sheet = XL.category_sheet("Doors", {"columns": ["ElementId", "Width", "Mark"],
                                            "column_units": {"Width": "mm"}, "rows": [[1, 900.0, "D1"]]})
        assert sheet["headers"] == ["ElementId", "Width [mm]", "Mark"]

    def test_workbook_roundtrip_and_formula_guard(self, tmp_path):
        from openpyxl import load_workbook

        path = str(tmp_path / "out" / "x.xlsx")
        titles = XL.write_workbook(path, [
            {"title": "Doors", "headers": ["Id", "Width [mm]", "Comment"],
             "rows": [[1, 900.0, "=HYPERLINK(\"x\")"], [2, -5, "-12"]]}], [["RVTSS export", "now"]])
        assert titles == ["Summary", "Doors"]
        ws = load_workbook(path)["Doors"]
        assert [c.value for c in ws[1]] == ["Id", "Width [mm]", "Comment"]
        assert ws["B2"].value == 900.0 and ws["C2"].value == "'=HYPERLINK(\"x\")"
        assert ws["B3"].value == -5 and ws["C3"].value == "-12" and ws.freeze_panes == "A2"


# ---------------------------------------------------------------- MCP tools
class _Rec(object):
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _tools(post):
    from tools.coordination_tools import register_coordination_tools

    rec = _Rec()

    async def get(*a, **k):
        return {}
    register_coordination_tools(rec, get, post)
    return rec.tools


async def test_export_clash_report_writes_csv_and_html(tmp_path, monkeypatch):
    monkeypatch.setenv("RVTSS_REPORT_DIR", str(tmp_path))
    sent = []
    clashes = [_clash("Ducts", "Structural Framing", [4000, 3000, 3000])]
    CL.locate(clashes, GRIDS)

    async def post(endpoint, data, ctx=None, timeout=None):
        sent.append((endpoint, data))
        return {"status": "success", "clash_count": 1, "hard_count": 1, "clearance_count": 0, "unit": "mm",
                "clearance": 50, "clashes": clashes, "groups": {"pair": CL.group_clashes(clashes, "pair")}}
    tools = _tools(post)
    out = await tools["export_clash_report"](set_a={"categories": ["Ducts"]}, set_b={"categories": ["Structural Framing"]},
                                             clearance=50, ctx=None)
    assert sent[0][0] == "/qc/clashes/" and sent[0][1]["clearance"] == 50
    assert sent[0][1]["group_by"] == ["pair", "level", "grid_zone"]
    files = sorted(os.listdir(str(tmp_path)))
    assert len(files) == 2 and files[0].endswith(".csv") and files[1].endswith(".html") and "clash_report_" in files[0]
    with open(str(tmp_path / files[0]), encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][2] == "Distance [mm]" and rows[1][4] == "A-B/1-2" and rows[1][5] in ("A/1", "B/1")
    assert "Ducts x Structural Framing" in out


async def test_export_clash_report_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("RVTSS_REPORT_DIR", str(tmp_path))

    async def post(endpoint, data, ctx=None, timeout=None):
        assert data["dry_run"] is True
        return {"status": "dry_run", "set_a_count": 12}
    out = await _tools(post)["export_clash_report"](set_a={"categories": ["Ducts"]}, set_b={"categories": ["Walls"]},
                                                     dry_run=True, ctx=None)
    assert "would_write" in out and os.listdir(str(tmp_path)) == []


async def test_export_clash_report_passes_errors_through(tmp_path, monkeypatch):
    monkeypatch.setenv("RVTSS_REPORT_DIR", str(tmp_path))

    async def post(endpoint, data, ctx=None, timeout=None):
        return "Error: Cannot reach the pyRevit Routes server"
    out = await _tools(post)["export_clash_report"](set_a={}, set_b={}, ctx=None)
    assert out.startswith("Error: Cannot reach") and os.listdir(str(tmp_path)) == []


async def test_export_to_excel_categories_and_paged_schedule(tmp_path, monkeypatch):
    from openpyxl import load_workbook

    monkeypatch.setenv("RVTSS_REPORT_DIR", str(tmp_path))
    calls = []

    async def post(endpoint, data, ctx=None, timeout=None):
        calls.append((endpoint, data))
        if endpoint == "/parameters/export/":
            return {"status": "success", "columns": ["ElementId", "Category", "Width"], "row_count": 1,
                    "column_units": {"Width": "mm"}, "rows": [[7, data["categories"][0], 900.0]]}
        offset = data["offset"]
        rows = [["r%d" % i] for i in range(offset, min(offset + 2000, 2500))]
        return {"status": "success", "name": "Door Schedule", "columns": ["Mark"], "row_count": 2500, "rows": rows}
    tools = _tools(post)
    out = await tools["export_to_excel"](output_path="qto.xlsx", categories=["Doors", "Windows"], parameters=["Width"],
                                         schedules=["Door Schedule"], ctx=None)
    assert '"status": "success"' in out or "success" in out
    assert [c[1]["offset"] for c in calls if c[0] == "/schedule_data/"] == [0, 2000]
    assert all(c[1]["format"] == "json" and c[1]["value_mode"] == "raw" for c in calls if c[0] == "/parameters/export/")
    wb = load_workbook(str(tmp_path / "qto.xlsx"))
    assert wb.sheetnames == ["Summary", "Doors", "Windows", "Door Schedule"]
    assert wb["Doors"]["C1"].value == "Width [mm]" and wb["Door Schedule"].max_row == 2501
    again = await tools["export_to_excel"](output_path="qto.xlsx", categories=["Doors"], parameters=["Width"], ctx=None)
    assert "exists" in again


async def test_export_to_excel_validation_and_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RVTSS_REPORT_DIR", str(tmp_path))

    async def post(endpoint, data, ctx=None, timeout=None):
        return {"status": "success", "columns": ["ElementId"], "rows": [[1]], "row_count": 1}
    tools = _tools(post)
    assert "parameters are required" in await tools["export_to_excel"](output_path="a.xlsx", categories=["Doors"], ctx=None)
    assert "must end with .xlsx" in await tools["export_to_excel"](output_path="a.csv", schedules=["S"], ctx=None)
    out = await tools["export_to_excel"](output_path="a.xlsx", categories=["Doors"], parameters=["Mark"], dry_run=True,
                                         ctx=None)
    assert "would_write" in out and os.listdir(str(tmp_path)) == []


async def test_audit_family_library_sends_options():
    sent = []

    async def post(endpoint, data, ctx=None, timeout=None):
        sent.append((endpoint, data, timeout))
        return {"status": "dry_run", "would_open": ["A.rfa"]}
    out = await _tools(post)["audit_family_library"](folder="C:/lib", dry_run=True, max_files=5, ctx=None)
    assert sent[0][0] == "/family/library_audit/" and sent[0][1]["dry_run"] is True and sent[0][1]["max_files"] == 5
    assert sent[0][2] == 1800.0 and "A.rfa" in out


def test_csv_report_header_units():
    from tools.coordination_tools import clash_csv

    rows = list(csv.reader(io.StringIO(clash_csv({"unit": "m", "clashes": [_clash("A", "B", [1, 2, 3])]}))))
    assert rows[0][2] == "Distance [m]" and rows[0][-1] == "Z [m]" and rows[1][7] == "1"


def test_coordination_prompts():
    from tools.resources_prompts import PROMPTS

    text = PROMPTS["clash_coordination"]["fn"](set_a="Ducts", set_b="Beams", clearance_mm="75", link="STR")
    assert "clearance=75" in text and "export_clash_report" in text and "link_instance_id" in text
    audit = PROMPTS["bim_standards_audit"]["fn"](family_folder="C:/lib", preset="cobie_type")
    assert 'audit_family_library(folder="C:/lib"' in audit and 'preset="cobie_type"' in audit
    assert "skip the library audit" in PROMPTS["bim_standards_audit"]["fn"]()


def test_map_preset_errors_on_revit_side(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with revit_environment():
        startup = importlib.import_module("startup")
        route = [r for r in startup.api.routes if r["path"] == "/parameters/map/"][0]["func"]
        res = route(doc=object(), uidoc=None, request=FakeRequest({"preset": "nope", "categories": ["Doors"]}))
        assert res["status"] == 404 and "ifc_overrides" in res["data"]["error"]
        res = route(doc=object(), uidoc=None, request=FakeRequest({"categories": ["Doors"]}))
        assert res["status"] == 400 and "Presets:" in res["data"]["hint"]
        res = route(doc=object(), uidoc=None, request=FakeRequest({"preset": "ifc_overrides"}))
        assert res["status"] == 400 and "applies to all categories" in res["data"]["error"]
