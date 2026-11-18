# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/textfmt.py -> textfmt.json."""
from _lane_b import Recorder
from revit_mcp.pure import textfmt as T

r = Recorder(T)
r.extra["invalid_name_chars"] = T.INVALID_NAME_CHARS

SPECS = [None, "", "03", "5", "<5", ">5", "^5", "^6", "=5", "+", " ", "-", "+05", "04d", "x", "04x", "08b", "#06x", "#x",
         "#o", "#b", "5o", "0X", "5X", "010,", "08,", "07,", ",", "+,", "5,d", "5,x", "0.2f", "5.1f", "06.2f", "+.3e",
         "010.3e", ".3g", "0.0f", "#.0f", "3%", "0.1%", "5n", "0d", "00005", "3.2", "3z", "<", "=", "0=5", "0<5", "0>5",
         "0^7", " >6", " <6", "<>5", "=>5", "-5", " 5", "+5d", " 05", "d", "12", "1", "0", "00", "0,", "+08,.1f", "012,.2f",
         "-.2e", ".0e", "#.0e", "5.0e", ".1g", ".2g", ".6g", ".10g", "#.3g", ".0g", "5G", ".3E", "8.3F", "5%", "-x", "+b",
         " o", "3 ", "3d ", "++", "5.", "5.d", ".f", "0,d", "<05", "^05", "=+5"]
for n in [0, 1, 7, 42, -7, 12345, 1234567, -1234567, 999, 9995, 99950, 12500, 13500, 1000000, 255, 65]:
    for spec in SPECS:
        r.call("_format_number", n, spec)
r.call("_format_number", 65, "3c")
r.call("_format_number", 65, "c")
r.call("_format_number", 8364, "<3c")

TEMPLATES = ["D-{Level}-{n:03}", "{{x}} {value}", "{Fire Rating}", "{Level}-{n:02}-{Type Mark}", "", "plain", "{n}",
             "{n:}", "{n:5}|", "{ n :03}", "{id}", "{id:05}", "{value}", "{value:>5}", "{{{n}}}", "{{}}", "{", "}", "{}",
             "{:03}", "{a:b:c}", "{a}{b}{a}", "{ a }{a }", "{Level}{id}{value}{n}", "{n:x}", "{n:3.2}", "{n:+04}",
             "{Missing}", "{Empty}", "{Zero}-{Flag}-{Num}", "{{n}}", "}}{{", "{n:08,}", "{a{b}c}", "{a}}", "{{a}",
             u"{Höhe} é", "{n:0>5}", "{Level:x}", "{value}{value}", "{id}-{ID}", "{N}"]
RESOLVE = {"Level": "L1", "Type Mark": "TM", "a": "A", "b": "B", "Empty": "", "Zero": 0, "Flag": True, "Num": 2.5,
           u"Höhe": u"2 m", "ID": "upper"}
for t in TEMPLATES:
    r.call("tokens", t)
    for kw in [{}, {"n": 7}, {"n": 7, "element_id": 99, "current": "A"}, {"n": 0, "element_id": None, "current": None},
               {"n": -12, "element_id": "abc", "current": 4.5}, {"current": ""}, {"n": 1234567, "current": True}]:
        # the resolver is the dictionary lookup of "resolve" (a missing name gives None)
        r.call_as("render", lambda template, **k: T.render(template, RESOLVE.get, **k), (t,), kw, resolve=RESOLVE)
r.call_as("render", lambda template, *a: T.render(template, RESOLVE.get, *a), ("{n:03}/{id}/{value}/{a}", 5, 12, "cur"), {},
          resolve=RESOLVE)

RENAMES = [
    (["Level 1 - Plan", "Level (\\d)", "L0\\1"], {"regex": True, "prefix": "A_", "case": "upper"}),
    (["Level 1 - Plan"], {}), (["Level 1 - Plan", "Level", "L"], {}), (["Level 1 - Plan", "Level"], {}),
    (["Level 1 - Plan", "level", "L"], {}), (["Level 1 - Plan", "", "L"], {}), (["Level 1 - Plan", None, "L"], {}),
    (["Level 1 - Plan", "l", None], {}), (["a.b.c", ".", "-"], {}), (["a.b.c", ".", "-"], {"regex": True}),
    (["a.b.c", "\\.", "-", True], {}), (["a.b.c", "(", "-", True], {}), (["a.b.c", "[", "-", False], {}),
    (["Door 12 Type 7", "(\\d+)", "<\\1>", True], {}), (["Door 12 Type 7", "(?P<num>\\d+)", "#\\g<num>#", True], {}),
    (["Door 12 Type 7", "(\\d+)", "\\g<1>0", True], {}), (["Door 12 Type 7", "(\\d+)", "\\g<0>\\g<0>", True], {}),
    (["Door 12 Type 7", "(\\d)(\\d)?", "[\\2|\\1]", True], {}), (["Door 12", "(\\d+)", "\\5", True], {}),
    (["Door 12", "(\\d+)", "\\g<nope>", True], {}), (["Door 12", "(\\d+)", "$1 cost", True], {}),
    (["Door 12", " ", "\\n", True], {}), (["Door 12", " ", "\\t\\\\", True], {}), (["Door 12", " ", "\\n", False], {}),
    (["abxd", "x*", "-", True], {}), (["abc", "", "-", True], {}), (["abc", "^", ">", True], {}), (["abc", "$", "<", True], {}),
    (["Hello World", "o", "0"], {"case": "lower"}), (["Hello World"], {"case": "upper"}), (["hello wORLD"], {"case": "title"}),
    (["they're 2nd-floor plans_x a1b"], {"case": "title"}), (["Hello"], {"case": "Title"}), (["Hello"], {"case": "other"}),
    (["Hello"], {"case": None}), ([u"été ÉCOLE naïve"], {"case": "title"}),
    ([u"été École"], {"case": "upper"}), ([u"ÉTÉ École"], {"case": "lower"}),
    (["x"], {"prefix": "P-", "suffix": "-S"}), (["x"], {"prefix": None, "suffix": None}), (["x"], {"prefix": 5, "suffix": 2.5}),
    (["x"], {"prefix": 0, "suffix": False}), (["x", "x", "y", False, "<", ">", "upper"], {}),
    (["A-B-A", "A", "AA"], {}), (["aaa", "aa", "b"], {}), (["aaa", "a", ""], {}), (["Abc", "(?i)a", "z", True], {}),
    (["Abc", "(?P<x>b)(?P=x)?", "\\g<x>\\g<x>", True], {}), (["name", 5, "x"], {}), (["name", "n", 5], {}),
    (["", "a", "b"], {"prefix": "p"}), (["Plan", "plan", "x", True], {"case": "lower"}),
]
for args, kw in RENAMES:
    r.call("apply_rename", *args, **kw)

for name in ["A:B{C}", "", "plain name", "\\:{}[]|;<>?`~", "a?b?c<d>", "~x~", "[1] {2} <3>", u"é;è", "a/b*c\"d",
             "}{", "x\\y"]:
    r.call("invalid_name_chars", name)
r.write("textfmt")
