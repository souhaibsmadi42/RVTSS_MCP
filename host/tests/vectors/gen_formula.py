# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/formula.py -> formula.json."""
from _lane_b import Recorder
from revit_mcp.pure import formula as FO

r = Recorder(FO)
r.extra["functions"] = sorted(FO.FUNCTIONS)
r.extra["unit_words"] = sorted(FO.UNIT_WORDS)

NAMES = ["Width", "Height", "Rough Width", "Frame Thickness", "Has Glass", "Depth", "Width 2", "A", "a_b", "W+H",
         "Panel (L)", "Ratio %", u"Höhe", "", "x1", "X1"]
NAME_SETS = [NAMES, [], ["Width"], ["Width", "Width Offset", "Offset"], ["b", "ab", "abc"], ["abc", "ab", "b"],
             ["m", "mm", "if"], ["Rough Width", "Width", "Rough"], [None, "Width"], ["a.b", "a*b", "[x]", "c^2", "d$"]]
FORMULAS = [
    "Rough Width - 2 * Frame Thickness", 'if(Has Glass, "Width", "x")', "Widht + 50 mm",
    "if(Width > 900 mm, sqrt(Height), 0)", "if(a, (b, c)", "a)", '"abc', "", None, "Width", "Width2", "Width 2 + Width",
    "Width_2", "_Width", "Width+Height", "(Width)", "WIDTH", "width", "Height * 2", "Width / 2", "A + a_b + W+H",
    "Panel (L) * 2", "Ratio % / 100", u"Höhe + 1", "x1 + X1 + x2", "sin(Angle) * Radius", "PI() * r ^ 2",
    'if(Name = "Height", 1, 2)', '"a" + "b', '""', '")" + "("', "((a) + (b)))", "((a) + (b)", ")(", "abc ab b",
    "Width Offset + Offset", "Rough Width Rough", "m + mm + if", "a.b + a*b + [x] + c^2 + d$", "3 * 2 + 1.5e3",
    "roundup(Depth / 300 mm) * 1'", "Width  +  Height", "Yes", "not(Has Glass)", "size_lookup(T, \"C\", 0, D)",
    "e ^ 2 + E", "Width Width Width", "50mm + 2m", "Rough  Width", "Frame Thickness2 + 2Frame Thickness",
]
for names in NAME_SETS:
    for f in FORMULAS:
        r.call("references", f, names)
        r.call("unknown_identifiers", f, names)
for f in FORMULAS:
    r.call("check_balance", f)


def pairs(d):
    return [[k, v] for k, v in d.items()]


SETS = [
    {"Width": "Rough Width - 10", "Rough Width": "Width + 10"},
    {"Width": "Height * 2", "Height": "Width / 2", "Rough Width": "Widht"},
    {"Width": "Width + 1"},
    {"A": "Width", "Width": "Height", "Height": "Depth", "Depth": "Width"},
    {"A": "Width", "Width": "Height", "Height": "Depth", "Depth": "A + Width"},
    {"Width": "Height", "Height": "Width", "Depth": "Height + Width", "A": "Depth + A"},
    {"Width": "Height + Depth", "Height": "Depth", "Depth": "10"},
    {"Width": "", "Height": None, "Depth": "Width"},
    {},
    {"Width": "Height", "Height": "Depth", "Depth": "Height", "A": "Width"},
    {"x1": "X1", "X1": "x1 + (", "a_b": 'a_b + "'},
    {"Zeta": "Width", "Width": "Zeta", "Alpha": "Width +", "Beta": "Alpha) + Unknown1 + Unknown2 + Unknown1"},
    {"Rough Width": "Width + Frame Thickness", "Frame Thickness": "Rough Width / 10", "Width": "Rough Width"},
    {"Unknown Param": "Width", "Width": "Unknown Param"},
]
for s in SETS:
    for names in (NAMES, ["Width", "Height", "Depth"], []):
        # formulas travel as [name, formula] pairs so the vectors keep the dict order
        r.call_as("find_cycles", lambda p, n: FO.find_cycles(dict((k, v) for k, v in p), n), (pairs(s), names), {})
        r.call_as("analyse", lambda p, n: FO.analyse(dict((k, v) for k, v in p), n), (pairs(s), names), {})
r.write("formula")
