# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/units.py -> units.json."""
from _lane_b import Recorder
from revit_mcp.pure import units as U

r = Recorder(U)
r.extra["units"] = dict((k, [v[0], v[1]]) for k, v in U.UNITS.items())
r.extra["aliases"] = dict(U.ALIASES)

ALL = sorted(U.UNITS)
for u in [None, " MM ", "Meters", "Millimeters", u"°", "'", '"', "m^2", "sqm", "CUM", "xyz", "", "  ", "furlong",
          "mm 2", "INTERNAL"] + ALL + sorted(U.ALIASES):
    r.call("normalize_unit", u)
    r.call("unit_kind", u)

VALUES = [0, 1, -2.5, 304.8, 1000000.0, 0.001, 123456.789, "12", "1.5", " 3 ", "-4e2", True, False]
for v in VALUES:
    for u in [None, "mm", "cm", "m", "ft", "in", "m2", "ft2", "mm3", "m3", "deg", "rad", "internal", "Metres", "sqft"]:
        r.call("to_internal", v, u)
for v, u in [("abc", "mm"), (None, "mm"), (1, "zz"), ("", None), (None, None), ("abc", None), ([1], "mm"), (1, "")]:
    r.call("to_internal", v, u)

for v in [0, 1, -2.6, 3.28083989501, 10.763910416709722, 35.314666721488585, 3.141592653589793, 0.123456789, 1234.5678,
          1e-7, "2.26", None, True]:
    for u in [None, "mm", "m", "ft", "in", "m2", "mm2", "m3", "ft3", "deg", "rad", "internal"]:
        r.call("from_internal", v, u)
        for nd in (0, 1, 3, 6, -1, -2):
            r.call("from_internal", v, u, nd)
        r.call("from_internal", v, u, ndigits=4)
for v, u in [("abc", "mm"), (1, "zz"), ([1], None), (1, "")]:
    r.call("from_internal", v, u)
    r.call("from_internal", v, u, 2)
r.call("from_internal", None, "zz")

for kind in ["length", "area", "volume", "angle", "number", "other", None, ""]:
    for u in [None, "", "mm", "cm", "m", "ft", "in", "m2", "mm2", "ft2", "in2", "m3", "ft3", "cm3", "deg", "rad",
              "internal", "sqm", "Meters", "degrees", "cum", "bad"]:
        r.call("length_unit_for", kind, u)

for vals in [[1, 2], [1, 2, 3], [304.8, 0], [1], [1, 2, 3, 4], [], ["1", "2"], ["1", "2.5", " 3 "], [1, "x"], "ab", "abc",
             None, [None, 1], [1.5, -2.5, 1000], [True, 2], 5, "12", [[1], 2]]:
    for u in [None, "mm", "m", "ft", "bad"]:
        r.call("point_from", vals, u)

for xyz in [[1, 2, 3], [0.123456, -3.28084, 10], [None, 1, 2], [], [1], ["1.5", 2], [1.0, 2.0, 3.0, 4.0]]:
    for u in [None, "mm", "m", "in", "bad"]:
        r.call("point_to", xyz, u)
        r.call("point_to", xyz, u, 1)
        r.call("point_to", xyz, u, ndigits=6)
        r.call("point_to", xyz, u, None)
r.write("units")
