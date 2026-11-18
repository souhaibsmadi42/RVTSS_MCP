# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/exportnames.py -> exportnames.json.
Run: uv run --project . python host/tests/vectors/gen_exportnames.py"""
from _lane_c import Recorder
from revit_mcp.pure import exportnames as N

rec = Recorder("exportnames")
rec.extra["constants"] = {"FORMATS": N.FORMATS, "MODEL_FORMATS": list(N.MODEL_FORMATS), "FIELDS": list(N.FIELDS)}


def sanitize(name, replacement="<default>", max_len="<default>"):
    if replacement == "<default>":
        return N.sanitize(name)
    if max_len == "<default>":
        return N.sanitize(name, replacement)
    return N.sanitize(name, replacement, max_len)


rec.call("default_template", N.default_template, True)
rec.call("default_template", N.default_template, False)

NAMES = ["Plan: Level 1", "  ", "", None, "A/B\\C:D*E?F\"G<H>I|J", "tab\there\nnew\r\nline", "ctrl\x00\x01\x1f\x7f end",
         "  padded  ", "...dots...", " . mixed . ", ". .", "a   b \t c", "trailing dot.", ".hidden", "x" * 200,
         ("word " * 60), "a" * 179 + " b", "a" * 180 + "b", "a" * 178 + "  bcd", "Étage – niveau 1", "墙 / 楼板",
         "non breaking spaces", "CON", "name.pdf", "a_b-c", "  .  ", "*", "?.?", "\x1f", "emoji 😀 ok"]
for n in NAMES:
    rec.call("sanitize", sanitize, n)
for n in ("A:B", "a/b/c", "x" * 20, "  ..a b..  ", ""):
    for repl in ("-", "", " ", "__", ".", "$1", "$0"):
        rec.call("sanitize", sanitize, n, repl)
    for max_len in (5, 1, 0, 3, 180, 1000):
        rec.call("sanitize", sanitize, n, "_", max_len)
rec.call("sanitize", sanitize, "abc def ghi", "_", 4)
rec.call("sanitize", sanitize, "abcd  efgh", "_", 6)
rec.call("sanitize", sanitize, "A:B", "\\\\", 180)  # an escaped backslash in the replacement template
rec.call("sanitize", sanitize, "abcdef", "_", -2)

FIELDS = {"number": "A101", "name": "Plan: Level 1", "title": "Ground floor", "revision": "P02", "view_type": "FloorPlan",
          "date": "2026-11-18", "document": "Project.rvt"}
TEMPLATES = ["{number} - {name}", "{name}", "{number}", "{number}-{name}-{revision}", "{document}_{number}_{title}_{date}",
             "{view_type}/{name}", "plain text", "", "  ", " - {name}", "{name} - ", "{number} - {name} - {revision}",
             "- - {name} - -", "{name}{name}", "{ name }", "{}", "{{name}}", "{Name}", "{number} -{name}", "{name}\n",
             "{sheet_no}", "{number} {sheet_no} {bogus} {bogus} {a1}", "{number", "name}", "{nümber}", "{number}.{name}.",
             "{name} -\t- {number}", "-", " -- ", "{number}—{name}", "{0}", "{view_type}"]
SETS = [FIELDS, {}, {"number": "A101", "name": ""}, {"number": "", "name": "Plan"}, {"number": None, "name": None},
        {"number": 101, "name": 1.5, "revision": 0, "title": True, "date": False, "document": ["a"]},
        {"number": " A101 ", "name": "- dash -", "revision": "..", "view_type": "a\tb"},
        {"name": "x" * 300, "number": "A:1*?"}, {"name": "{number}", "number": "{name}"}, {"name": "$1 \\1 \\g<1>"}]
for tpl in TEMPLATES:
    for fields in SETS:
        rec.call("render", N.render, tpl, fields)
rec.call("render", N.render, None, FIELDS)  # TypeError

for names in (["A", "a", "B", "A"], [], ["x"], ["A", "A", "A", "A"], ["A", "A_2", "A"], ["A_2", "A", "A", "a_2"],
              ["a", "A", "A_2", "a_3", "A"], ["Plan", "plan", "PLAN", "Plan_2", "plan_2", "Plan"], ["", "", ""],
              ["É", "é", "E"], ["A", "B", "C"], ["x_1", "x", "X", "x_2", "X_2", "x_2_2", "x"],
              ["ß", "SS", "ss"], ["İ", "i", "I", "ı"]):
    rec.call("unique", N.unique, names)

for name in ("model.ifc", "model.IFC", "model.ifc.ifc", "model", "", None, ".ifc", "model.nwc", "a.pdf", "A.PDF", "ifc",
             "model.dwg ", "x.csv", "dxf.dxf"):
    for fmt in ("ifc", "nwc", "pdf", "dwg", "dxf", "csv", "bogus", "", "IFC", None):
        rec.call("strip_extension", N.strip_extension, name, fmt)

rec.save()
