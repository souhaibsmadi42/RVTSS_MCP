# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/family_library.py -> family_library.json.
Run (on Windows: the module joins paths with os.path): uv run --project . python host/tests/vectors/gen_family_library.py"""
import os

from _lane_c import Recorder
from revit_mcp.pure import family_library as FL

assert os.sep == "\\", "family_library joins and normalises paths with ntpath: generate the vectors on Windows"

rec = Recorder("family_library")
rec.extra["constants"] = {"BACKUP_RX": FL.BACKUP_RX.pattern}


def list_files(walk_items, recursive="<default>", root="<default>"):
    walk = [tuple(w) for w in walk_items]
    if recursive == "<default>":
        return FL.list_files(walk)
    if root == "<default>":
        return FL.list_files(walk, recursive)
    return FL.list_files(walk, recursive, root)


def library_findings(records, naming_rule="<default>", iso_scheme="<default>", max_size_kb="<default>", max_nested="<default>"):
    args = [a for a in (naming_rule, iso_scheme, max_size_kb, max_nested) if a != "<default>"]
    return FL.library_findings(records, *args)


for name in ("Door.rfa", "Door.0001.rfa", "Chair.RFA", "notes.txt", "Table.Rfa", "Door.0001.RFA", "Door.001.rfa",
             "Door.00001.rfa", "Door.1234.rfa.bak", "Door.rfa.0001.rfa", ".rfa", "rfa", "", "Door.rfa ", "Door.rfa\n",
             "Door.0001.rfa\n", "Door.٠٠٠١.rfa", "Door 0001.rfa", "Door.2026.rfa", "a.b.c.rfa", "Door.abcd.rfa", "x.0000.rfax"):
    rec.call("is_family_file", FL.is_family_file, name)
rec.call("is_family_file", FL.is_family_file, None)  # AttributeError

WALK = [
    ["C:\\lib", ["sub", "Other"], ["Door.rfa", "Door.0001.rfa", "Chair.RFA", "notes.txt", "apple.rfa", "Zebra.rfa"]],
    ["C:\\lib\\sub", ["deep"], ["Table.rfa", "banana.rfa"]],
    ["C:\\lib\\sub\\deep", [], ["Table.rfa", "x.0002.rfa"]],
    ["C:\\lib\\Other", [], []],
    ["C:/lib/mixed/", [], ["Slash.rfa"]],
    ["C:\\LIB", [], ["Upper.rfa"]],
    ["C:\\lib\\.", [], ["Dot.rfa"]],
    ["C:\\lib\\sub\\..", [], ["DotDot.rfa"]],
    ["C:\\\\lib\\\\", [], ["Double.rfa"]],
    ["", [], ["Bare.rfa"]],
    ["rel\\dir", [], ["Rel.rfa"]],
    ["C:", [], ["DriveOnly.rfa"]],
    ["C:\\", [], ["Root.rfa"]],
    ["\\\\server\\share", [], ["Unc.rfa"]],
    ["\\\\server\\share\\lib\\", [], ["Unc2.rfa"]],
]
rec.call("list_files", list_files, WALK)
rec.call("list_files", list_files, WALK, True)
rec.call("list_files", list_files, WALK, False)
rec.call("list_files", list_files, [])
for root in ("C:\\lib", "C:\\lib\\", "C:/lib", "C:/lib/", "c:\\lib", "C:\\lib\\sub", "C:\\lib\\sub\\..\\sub", "C:\\lib\\.\\sub\\",
             "C:\\lib\\mixed", "", ".", "rel/dir", "rel\\dir\\", ".\\rel\\dir", "rel\\x\\..\\dir", "C:", "C:\\", "C:/",
             "\\\\server\\share", "\\\\server\\share\\", "//server/share/lib", "C:\\missing", "C:\\lib\\sub\\deep\\..\\..",
             "..\\x", "..", "C:\\..\\lib", "\\lib", None):
    rec.call("list_files", list_files, WALK, False, root)
    rec.call("list_files", list_files, WALK, True, root)
rec.call("list_files", list_files, [["C:\\a", [], ["b.rfa", "B.rfa", "a.rfa", "A.RFA"]], ["C:\\A", [], ["a.rfa"]]])
rec.call("list_files", list_files, [["C:\\a", [], ["C:\\abs\\x.rfa", "\\rooted.rfa", "sub\\y.rfa", "D:z.rfa", "c:same.rfa"]]])

for path in ("C:/lib/ABC_Door_Single.rfa", "C:\\lib\\chair.rfa", "chair.rfa", "chair", "", "C:\\lib\\", "a.b.c.rfa",
             ".rfa", "C:\\lib\\.hidden", "C:\\lib.v2\\chair", "C:chair.rfa", "//server/share/x.RFA", "a/b\\c.rfa", "name.", "..",
             "x.0001.rfa", "dir.with.dots/file"):
    rec.call("family_name", FL.family_name, path)

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
critical = {"file": "XYZ_Crit.rfa", "path": "C:\\lib\\sub\\XYZ_Crit.rfa", "size_kb": 2048.5, "category": "",
            "types": ["a", "b"], "nested": ["n"] * 10, "warnings": ["w1", "w2", "w3", "w4"],
            "parameters": [{"name": None}, {"name": ""}, {"name": "A", "shared": 1}, {"name": "B", "shared": 0}],
            "validation": {"summary": {"by_severity": {"error": 1, "critical": 2, "warning": 3.5, "info": 9}},
                           "findings": [{"severity": "critical", "message": "m%d" % i} for i in range(4)]
                           + [{"severity": "warning", "message": "not listed"}, {"severity": "error", "message": "m4"},
                              {"severity": "error", "message": "m5"}, {"message": "no severity"}]}}
minimal = {"file": "ABC_Min.rfa"}
nopath = {"file": "nopath.rfa", "size_kb": 9999, "types": ["t"], "category": "Walls"}
exact = {"file": "ABC_Exact.rfa", "path": "ABC_Exact.rfa", "size_kb": 2048, "category": None, "types": ["t"],
         "nested": ["n"] * 11, "warnings": None, "parameters": None, "validation": None}
floats = {"file": "f.rfa", "path": "f.rfa", "validation": {"summary": {"by_severity": {"error": 0.0, "critical": 0}}},
          "types": ["t"], "category": "Doors", "size_kb": None}

for r in (ok, bad, broken, critical, minimal, nopath, exact, floats, {}, {"path": "", "file": "only_file.rfa"},
          {"path": "C:\\x\\p.rfa", "file": "other.rfa", "error": ""}, {"validation": {"summary": None}},
          {"validation": {"summary": {"by_severity": None}}}, {"parameters": [{"shared": True}, {"shared": "yes"}, {}]}):
    rec.call("summary_row", FL.summary_row, r)
rec.call("summary_row", FL.summary_row, {"parameters": ["text"]})  # AttributeError

ISO = {"targets": {"families": {"delimiter": "_", "fields": [
    {"name": "originator", "values": ["ABC"]}, {"name": "category", "min_length": 3},
    {"name": "description", "min_length": 2}]}}}
ALL = [ok, bad, broken, critical, exact, floats]
rec.call("library_findings", library_findings, [ok, bad, broken], {"pattern": "^[A-Z]{3}_"}, None, 2048, 10)
rec.call("library_findings", library_findings, [ok, bad, broken])
rec.call("library_findings", library_findings, [])
rec.call("library_findings", library_findings, [], {"pattern": "^x"}, ISO)
rec.call("library_findings", library_findings, ALL)
rec.call("library_findings", library_findings, ALL, None, None)
rec.call("library_findings", library_findings, ALL, {}, {})
rec.call("library_findings", library_findings, ALL, {"pattern": ""})
rec.call("library_findings", library_findings, ALL, {"pattern": "^[A-Z]{3}_", "severity": "error", "description": "Use ABC_ names"})
rec.call("library_findings", library_findings, ALL, {"pattern": "^[A-Z]{3}_", "severity": "info"}, ISO)
rec.call("library_findings", library_findings, ALL, {"pattern": "("})
rec.call("library_findings", library_findings, ALL, {"severity": "error"}, ISO, 100, 0)
rec.call("library_findings", library_findings, ALL, None, ISO, 2048.5, 11)
rec.call("library_findings", library_findings, ALL, None, None, 10 ** 6, 100)
rec.call("library_findings", library_findings, ALL, None, None, 299, 9)
rec.call("library_findings", library_findings, [minimal, {}, {"file": "x.rfa", "types": ["t"], "category": "Doors"}])
rec.call("library_findings", library_findings, [{"file": "ABC_Door_Single.rfa", "path": "ABC_Door_Single.rfa"},
                                                {"file": "XYZ_Door_S.rfa", "path": "XYZ_Door_S.rfa"}], None, ISO)
rec.call("library_findings", library_findings, [nopath])  # KeyError: big families need "path"
rec.call("library_findings", library_findings, [dict(nopath, size_kb=1, warnings=["w"])])  # KeyError
many = [dict(bad, file="chair%02d.rfa" % i, path="C:/lib/chair%02d.rfa" % i, size_kb=3000 + i,
             error="broken" if i % 9 == 0 else None) for i in range(70)]
rec.call("library_findings", library_findings, many, {"pattern": "^[A-Z]"}, ISO)
rec.call("library_findings", library_findings, many[:35] + [ok] + many[35:], None, None, 3040, 11)

rec.save()
