# -*- coding: utf-8 -*-
"""Unit tests for revit_mcp.pure (Revit-independent helpers)."""
import math
import os

import pytest

from revit_mcp.pure import units as U
from revit_mcp.pure import textfmt as T
from revit_mcp.pure import filters as F
from revit_mcp.pure import sharedparams as SP
from revit_mcp.pure import catalog as C
from revit_mcp.pure import templates as TPL
from revit_mcp.pure import formula as FO
from revit_mcp.pure import diff as D
from revit_mcp.pure import rules as R
from revit_mcp.pure import csvutil as CSV


# ------------------------------------------------------------------ units
class TestUnits:
    def test_mm_to_feet_is_exact(self):
        assert U.to_internal(304.8, "mm") == pytest.approx(1.0, abs=1e-12)
        assert U.from_internal(1.0, "mm") == pytest.approx(304.8)

    def test_area_and_volume(self):
        assert U.to_internal(1, "m2") == pytest.approx(10.763910416709722)
        assert U.from_internal(35.314666721488585, "m3") == pytest.approx(1.0)

    def test_angle(self):
        assert U.to_internal(180, "deg") == pytest.approx(math.pi)

    def test_aliases(self):
        assert U.normalize_unit("Millimeters") == "mm"
        assert U.normalize_unit("sqm") == "m2"

    def test_unknown_unit_raises(self):
        with pytest.raises(U.UnitError):
            U.to_internal(1, "furlong")

    def test_point_from_2d(self):
        assert U.point_from([304.8, 0], "mm") == pytest.approx((1.0, 0.0, 0.0))

    def test_length_unit_for(self):
        assert U.length_unit_for("area", "mm") == "mm2"
        assert U.length_unit_for("angle", "m") == "deg"
        # units that already fit the kind are kept, others adapted (review finding)
        assert U.length_unit_for("area", "m2") == "m2"
        assert U.length_unit_for("volume", "m2") == "m3"
        assert U.length_unit_for("length", "ft2") == "ft"
        assert U.length_unit_for("length", "deg") == "mm"
        assert U.length_unit_for("angle", "rad") == "rad"
        assert U.length_unit_for("length", "internal") == "internal"
        assert U.length_unit_for("number", "mm") is None


# --------------------------------------------------------------- templates
class TestValueTemplates:
    def test_sequence_and_params(self):
        vals = {"Level": "L2", "Type": "D90"}
        out = T.render("D-{Level}-{n:03}", vals.get, n=7, element_id=99)
        assert out == "D-L2-007"

    def test_literal_braces_and_value(self):
        assert T.render("{{x}} {value}", lambda n: None, current="A") == "{x} A"

    def test_missing_param_raises(self):
        with pytest.raises(T.TemplateError):
            T.render("{Fire Rating}", lambda n: None)

    def test_tokens(self):
        assert T.tokens("{Level}-{n:02}-{Type Mark}") == ["Level", "Type Mark"]

    def test_rename_regex_prefix_case(self):
        assert T.apply_rename("Level 1 - Plan", r"Level (\d)", r"L0\1", regex=True, prefix="A_", case="upper") == "A_L01 - PLAN"

    def test_invalid_characters(self):
        assert T.invalid_name_chars("A:B{C}") == [":", "{", "}"]


# ----------------------------------------------------------------- filters
class TestFilters:
    def test_numeric_compare(self):
        assert F.match("gt", 900, 910.0, "910 mm")
        assert not F.match("lt", 900, 910.0, "910 mm")

    def test_eq_numeric_tolerance(self):
        assert F.match("eq", 900, 900.0000001, None)

    def test_text_ops_case_insensitive(self):
        assert F.match("contains", "fire", "FIRE DOOR", None)
        assert F.match("startswith", "d-", "D-101", None)
        assert F.match("regex", r"^\d{3}$", "101", None)
        assert F.match("in", ["a", "b"], "B", None)

    def test_empty_and_existence(self):
        assert F.match("empty", None, "", None)
        assert F.match("not_empty", None, "x", None)
        assert F.match("missing", None, None, None, exists=False)
        assert F.match("ne", "x", None, None, exists=False)
        assert not F.match("eq", "x", None, None, exists=False)

    def test_validate_filter(self):
        with pytest.raises(F.FilterError):
            F.validate_filter({"name": "Width", "op": "gt", "value": "wide"})
        with pytest.raises(F.FilterError):
            F.validate_filter({"name": "Width", "op": "bogus", "value": 1})
        F.validate_filter({"name": "Mark", "op": "empty"})

    def test_text_match_all_words(self):
        assert F.text_match("fire door", ["Doors", "Single-Flush", "Fire 60", None])
        assert not F.text_match("fire window", ["Doors", "Fire 60"])

    def test_paginate(self):
        page, meta = F.paginate(list(range(10)), 8, 5)
        assert page == [8, 9] and meta["next_offset"] is None and meta["total"] == 10
        page, meta = F.paginate(list(range(10)), 0, 5)
        assert meta["next_offset"] == 5


# --------------------------------------------------------------- shared params
SHARED_FILE = (
    "# This is a Revit shared parameter file.\n"
    "# Do not edit manually.\n"
    "*META\tVERSION\tMINVERSION\n"
    "META\t2\t1\n"
    "*GROUP\tID\tNAME\n"
    "GROUP\t1\tIdentity\n"
    "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEINPROPERTIES\n"
    "PARAM\t5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01\tFire Rating\tTEXT\t\t1\t1\tFire resistance\t1\t0\n"
    "PARAM\t5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01\tFire Rating 2\tTEXT\t\t1\t1\t\t1\t0\n"
    "PARAM\tnot-a-guid\tFrame Depth\tLENGTH\t\t9\t1\t\t1\t0\n"
)


class TestSharedParams:
    def test_parse(self):
        res = SP.parse(SHARED_FILE)
        assert res["groups"] == {"1": "Identity"}
        names = [p["name"] for p in res["params"]]
        assert names == ["Fire Rating", "Fire Rating 2", "Frame Depth"]
        assert res["params"][0]["description"] == "Fire resistance"

    def test_issues_detect_duplicate_guid_bad_guid_and_group(self):
        issues = " | ".join(i["issue"] for i in SP.parse(SHARED_FILE)["issues"])
        assert "Duplicate GUID" in issues
        assert "invalid GUID" in issues
        assert "unknown group" in issues

    def test_read_utf16_file(self, tmp_path):
        p = tmp_path / "sp.txt"
        p.write_bytes(b"\xff\xfe" + SHARED_FILE.encode("utf-16-le"))
        assert len(SP.parse_file(str(p))["params"]) == 3

    def test_is_guid(self):
        assert SP.is_guid("5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01")
        assert not SP.is_guid("5b3e5f1c")


# ---------------------------------------------------------------- catalogs
class TestTypeCatalog:
    def test_roundtrip(self):
        cols = [{"name": "Width", "spec": "length", "unit": "mm"}, {"name": "Fire Rating", "spec": "text"}]
        text = C.write(cols, [{"name": "D 900, std", "values": {"Width": 900, "Fire Rating": "60"}}])
        assert text.splitlines()[0] == ",Width##LENGTH##MILLIMETERS,Fire Rating##OTHER##"
        parsed = C.parse(text)
        assert parsed["types"][0]["name"] == "D 900, std"
        assert parsed["types"][0]["values"]["Width"] == {"value": "900", "unit": "mm", "kind": "LENGTH"}

    def test_header_must_start_empty(self):
        with pytest.raises(C.CatalogError):
            C.parse("Name,Width##LENGTH##MILLIMETERS\nA,1\n")


# --------------------------------------------------------------- templates
class TestFamilyTemplates:
    FILES = [
        r"C:\T\English\Metric Door.rft", r"C:\T\English\Metric Door - Curtain Wall.rft",
        r"C:\T\English\Metric Generic Model.rft", r"C:\T\English\Metric Generic Model face based.rft",
        r"C:\T\English_I\Door.rft", r"C:\T\English\Metric Furniture.rft",
        r"C:\T\English\Annotations\Metric Door Tag.rft", r"C:\T\English\Titleblocks\A1 metric.rft",
    ]

    def test_door_prefers_metric_plain(self):
        m = TPL.match(self.FILES, "door", "metric")
        assert os.path.basename(m[0].replace("\\", "/")) == "Metric Door.rft"
        assert all("Tag" not in x and "Curtain" not in x for x in m)

    def test_generic_model_excludes_face_based(self):
        m = TPL.match(self.FILES, "generic_model")
        assert len(m) == 1 and m[0].endswith("Metric Generic Model.rft")

    def test_tags_and_titleblocks(self):
        assert TPL.match(self.FILES, "door_tag")[0].endswith("Metric Door Tag.rft")
        assert TPL.match(self.FILES, "title_block")[0].endswith("A1 metric.rft")

    def test_unknown_kind(self):
        assert TPL.match(self.FILES, "spaceship") == []

    def test_find_files(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "Metric Window.rft").write_text("x")
        (tmp_path / "readme.txt").write_text("x")
        assert TPL.find_template_files([str(tmp_path), "/does/not/exist"]) == [str(tmp_path / "sub" / "Metric Window.rft")]


# ----------------------------------------------------------------- formulas
class TestFormulas:
    NAMES = ["Width", "Frame Thickness", "Rough Width", "Height", "Has Glass"]

    def test_references_with_spaces(self):
        assert sorted(FO.references("Rough Width - 2 * Frame Thickness", self.NAMES)) == ["Frame Thickness", "Rough Width"]

    def test_strings_are_ignored(self):
        assert FO.references('if(Has Glass, "Width", "x")', self.NAMES) == ["Has Glass"]

    def test_unknown_identifiers(self):
        assert FO.unknown_identifiers("Widht + 50 mm", self.NAMES) == ["Widht"]
        assert FO.unknown_identifiers("if(Width > 900 mm, sqrt(Height), 0)", self.NAMES) == []

    def test_balance(self):
        assert FO.check_balance("if(a, (b, c)") == "Missing ')'"
        assert FO.check_balance("a)") == "Unbalanced ')'"
        assert FO.check_balance('"abc') == "Unterminated string literal"

    def test_cycles(self):
        cycles = FO.find_cycles({"Width": "Rough Width - 10", "Rough Width": "Width + 10"}, self.NAMES)
        assert cycles and set(cycles[0]) == {"Width", "Rough Width"}

    def test_analyse(self):
        issues = FO.analyse({"Width": "Height * 2", "Height": "Width / 2", "Rough Width": "Widht"}, self.NAMES)
        kinds = [i["issue"] for i in issues]
        assert any("Circular" in k for k in kinds)
        assert any("unknown names: Widht" in k for k in kinds)


# --------------------------------------------------------------------- diff
class TestDiff:
    A = {"elements": [
        {"uid": "u1", "id": 1, "category": "Doors", "family": "F", "type": "T1", "level": "L1", "loc": [0, 0, 0],
         "phash": "a", "params": {"Mark": "D1"}},
        {"uid": "u2", "id": 2, "category": "Walls", "family": "W", "type": "200", "level": "L1", "loc": [0, 0, 0],
         "phash": "b", "params": {}},
    ]}
    B = {"elements": [
        {"uid": "u1", "id": 1, "category": "Doors", "family": "F", "type": "T2", "level": "L1", "loc": [100, 0, 0],
         "phash": "c", "params": {"Mark": "D2"}},
        {"uid": "u3", "id": 3, "category": "Doors", "family": "F", "type": "T1", "level": "L1", "loc": [5, 5, 0],
         "phash": "d", "params": {}},
    ]}

    def test_diff_snapshots(self):
        r = D.diff_snapshots(self.A, self.B, move_tolerance=1.0)
        assert r["summary"] == {"added": 1, "removed": 1, "modified": 1, "unchanged": 0}
        fields = [c.get("field") or c.get("parameter") for c in r["modified"][0]["changes"]]
        assert fields == ["type", "location", "Mark"]
        assert r["by_category"]["Doors"] == {"added": 1, "removed": 0, "modified": 1}

    def test_match_by_location(self):
        r = D.match_by_location(self.A["elements"], self.B["elements"], tolerance=10, key_fields=("category",))
        assert r["summary"]["type_mismatch"] == 0
        assert r["summary"]["matched"] == 1  # door u1 (0,0) <-> door u3 (5,5)
        assert r["summary"]["only_in_source"] == 1  # wall
        assert r["summary"]["only_in_target"] == 1  # door at 100

    def test_type_substitution_detected(self):
        src = [{"id": 1, "category": "Doors", "family": "F", "type": "T1", "loc": [0, 0, 0]}]
        tgt = [{"id": 9, "category": "Doors", "family": "F", "type": "T9", "loc": [1, 0, 0]}]
        r = D.match_by_location(src, tgt, tolerance=5)
        assert r["summary"]["type_mismatch"] == 1 and r["type_mismatch"][0]["target_type"] == "F : T9"


# -------------------------------------------------------------------- rules
class TestRules:
    def test_finding_truncates_ids(self):
        f = R.finding("x", "error", "m", list(range(80)))
        assert f["count"] == 80 and len(f["element_ids"]) == 50 and f["element_ids_truncated"]

    def test_unknown_severity_defaults_to_warning(self):
        assert R.finding("x", "fatal", "m")["severity"] == "warning"

    def test_summarize_and_sort(self):
        fs = [R.finding("a", "info", "m", [1]), R.finding("b", "error", "m", [1, 2])]
        assert R.sort_findings(fs)[0]["check"] == "b"
        s = R.summarize(fs)
        assert s["worst_severity"] == "error" and s["by_severity"]["error"] == 1

    def test_check_names(self):
        out = R.check_names([(1, "A-101"), (2, "bad")], {"pattern": r"^[A-Z]-\d{3}$"}, "naming", "sheets")
        assert out[0]["element_ids"] == [2] and out[0]["examples"] == ["bad"]
        assert R.check_names([(1, "x")], {"pattern": "("}, "naming", "v")[0]["severity"] == "error"

    def test_duplicate_and_similar_names(self):
        assert R.check_duplicate_names([(1, "A"), (2, "a "), (3, "B")], "naming", "sheet")[0]["element_ids"] == [1, 2]
        assert ("Door 900", "Door_900") in R.similar_names(["Door 900", "Door_900", "Window"])


# ---------------------------------------------------------------------- csv
class TestCsv:
    def test_roundtrip_with_quotes_and_unicode(self, tmp_path):
        text = CSV.to_csv(["ElementId", "Comments"], [[1, 'He said "hi", ok'], [2, u"\u00e9t\u00e9\nline"], [3, None]])
        p = tmp_path / "x.csv"
        CSV.write_file(str(p), text)
        header, rows = CSV.parse_csv(CSV.read_file(str(p)))
        assert header == ["ElementId", "Comments"]
        assert rows[0]["Comments"] == 'He said "hi", ok'
        assert rows[1]["Comments"] == u"\u00e9t\u00e9\nline"
        assert rows[2]["Comments"] == ""

    def test_bool_cells(self):
        assert CSV.to_csv(["a"], [[True]]).splitlines()[1] == "Yes"
