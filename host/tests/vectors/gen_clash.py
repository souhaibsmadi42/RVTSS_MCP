# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/clash.py -> clash.json. Run: uv run --project . python host/tests/vectors/gen_clash.py"""
import math
import random

from _lane_c import Recorder
from revit_mcp.pure import clash as CL

rec = Recorder("clash")
rec.extra["constants"] = {"ANGLE_TOL_DEG": CL.ANGLE_TOL_DEG, "GROUP_KEYS": list(CL.GROUP_KEYS),
                          "ROW_HEADER": list(CL.ROW_HEADER)}

# 3 x 3 orthogonal grids, 8 m spacing: letters run along X (vertical lines), numbers along Y
GRIDS = [{"name": n, "start": [x, -1000], "end": [x, 17000]} for n, x in (("A", 0), ("B", 8000), ("C", 16000))] + \
        [{"name": n, "start": [-1000, y], "end": [17000, y]} for n, y in (("1", 0), ("2", 8000), ("3", 16000))]


def clash(a_cat, b_cat, point, level="Level 1", kind="hard", aid=1, bid=2):
    return {"a": {"id": aid, "category": a_cat, "family": a_cat + " fam", "type": "T1"},
            "b": {"id": bid, "category": b_cat, "family": b_cat + " fam", "type": "T2"},
            "type": kind, "distance": 0 if kind == "hard" else 30.0, "point": point, "level": level}


def rotate(grids, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))

    def rot(p):
        return [p[0] * c - p[1] * s, p[0] * s + p[1] * c]
    return [dict(g, start=rot(g["start"]), end=rot(g["end"])) for g in grids], rot


FLIPPED = [dict(g, start=g["end"], end=g["start"]) if g["name"] in ("B", "2") else g for g in GRIDS]
ROT30, rot30 = rotate(GRIDS, 30)
ROT117, rot117 = rotate(GRIDS, 117.3)
SKEW = GRIDS + [{"name": "S1", "start": [0, 0], "end": [9000, 9000]}, {"name": "S2", "start": [4000, 0], "end": [13000, 9000.5]},
                {"name": "S3", "start": [16000, 0], "end": [0, 16000]}]
DEGENERATE = [{"name": "Z", "start": [5, 5], "end": [5, 5]}]
ONE = [{"name": "A", "start": [0, 0], "end": [0, 1000]}]
SAME_NAME = [{"name": "A", "start": [0, 0], "end": [0, 1000]}, {"name": "A", "start": [500, 0], "end": [500, 1000]}]
NUMERIC_NAMES = [{"name": 1, "start": [0, 0], "end": [0, 1000]}, {"name": 2, "start": [500, 0], "end": [500, 1000]},
                 {"name": "10", "start": [0, 0], "end": [1000, 0]}, {"name": "2a", "start": [0, 700], "end": [1000, 700]}]
ONLY_X = [g for g in GRIDS if g["name"] in "ABC"]
THREE_D = [{"name": "A", "start": [0, 0, 100], "end": [0, 1000, 100]}, {"name": "1", "start": [0.0, 0.0, 5], "end": [1000.0, 0.0, 5]}]
NEAR_PARALLEL = [{"name": "A", "start": [0, 0], "end": [0, 10000]}, {"name": "A'", "start": [100, 0], "end": [200, 10000]},
                 {"name": "A''", "start": [300, 0], "end": [600, 10000]}, {"name": "1", "start": [0, 0], "end": [10000, 0]}]
ALL_SETS = [GRIDS, FLIPPED, ROT30, ROT117, SKEW, DEGENERATE, ONE, SAME_NAME, NUMERIC_NAMES, ONLY_X, THREE_D,
            NEAR_PARALLEL, GRIDS + DEGENERATE, []]

# ---------------------------------------------------------------- names
for a, b in (("A", "1"), ("1", "A"), ("B", "A"), ("A", "A"), ("10", "2"), ("2", "10"), ("", "A"), (None, "A"),
             ("A", None), (1, "A"), (2, 1), ("a", "B"), ("É", "E"), ("1a", "A1"), (None, None), (0, "0"), ("x", 1.5)):
    rec.call("intersection_name", CL.intersection_name, a, b)

# ---------------------------------------------------------------- lines
for gs in ALL_SETS:
    for i in range(len(gs)):
        for j in range(len(gs)):
            if i != j and (i + j) % 2 == 1:
                rec.call("line_intersection", CL.line_intersection, gs[i], gs[j])
rec.call("line_intersection", CL.line_intersection, {"name": "A", "start": [0, 0], "end": [0, 1]},
         {"name": "B", "start": [0, 0], "end": [1, 0.0174]})  # just under the angle tolerance
rec.call("line_intersection", CL.line_intersection, {"name": "A", "start": [0, 0], "end": [1, 0]},
         {"name": "B", "start": [0, 5], "end": [1000, 5 + 1000 * math.tan(math.radians(1.01))]})
rec.call("line_intersection", CL.line_intersection, {"name": "A", "end": [0, 1]}, GRIDS[0])  # KeyError
rec.call("line_intersection", CL.line_intersection, {"name": "A", "start": ["0", "0"], "end": ["0", "9"]},
         {"name": "B", "start": [5, 5], "end": [5, 5]})  # float() takes strings; the second line is degenerate

for gs in ALL_SETS:
    rec.call("grid_intersections", CL.grid_intersections, gs)
    rec.call("direction_families", CL.direction_families, gs)
rec.call("grid_intersections", CL.grid_intersections, [{"start": [0, 0], "end": [0, 1]}, {"start": [0, 0], "end": [1, 0]}])
rec.call("direction_families", CL.direction_families, [{"name": "A", "start": [0, 0]}])

# ---------------------------------------------------------------- zones
POINTS = [[4000, 3000], [20000, 3000], [-500, -500], [7000, 7500], [0, 0], [8000, 8000], [16000, 16000],
          [8000, 3000], [3000, 8000], [16000.0, -0.0], [1e7, -1e7], [4000.5, 3000.25, 12], [-1, 17000]]
for gs in ALL_SETS:
    for p in POINTS:
        rec.call("grid_zone", CL.grid_zone, p, gs)
for p in POINTS:
    rec.call("grid_zone", CL.grid_zone, rot30(p), ROT30)
    rec.call("grid_zone", CL.grid_zone, rot117(p), ROT117)
rec.call("grid_zone", CL.grid_zone, None, GRIDS)
rec.call("grid_zone", CL.grid_zone, [], GRIDS)
rec.call("grid_zone", CL.grid_zone, [1, 2], None)
rec.call("grid_zone", CL.grid_zone, [1], GRIDS)  # IndexError

for gs in (GRIDS, ROT30, SKEW, NUMERIC_NAMES, ONE, []):
    inters = CL.grid_intersections(gs)
    for p in POINTS:
        rec.call("nearest_intersection", CL.nearest_intersection, p, inters)
rec.call("nearest_intersection", CL.nearest_intersection, [0, 0], [{"name": "A/1", "point": [0.05, 0]}, {"name": "B/1", "point": [0.25, 0]}])
rec.call("nearest_intersection", CL.nearest_intersection, [0, 0], [{"name": "A/1", "point": [3, 4]}, {"name": "B/1", "point": [-3, -4]}])
rec.call("nearest_intersection", CL.nearest_intersection, [0, 0], [{"name": "A/1"}])

rnd = random.Random(20261118)
for n in range(120):
    gs = []
    base = rnd.uniform(0, 180)
    for k in range(rnd.randint(1, 5)):
        ang = math.radians(base + rnd.uniform(-0.4, 0.4))
        ox, oy = rnd.uniform(-20000, 20000), rnd.uniform(-20000, 20000)
        ln = rnd.uniform(1000, 30000) * rnd.choice((1, -1))
        gs.append({"name": chr(65 + k), "start": [ox, oy], "end": [ox + ln * math.cos(ang), oy + ln * math.sin(ang)]})
    for k in range(rnd.randint(0, 5)):
        ang = math.radians(base + 90 + rnd.uniform(-0.4, 0.4))
        ox, oy = rnd.uniform(-20000, 20000), rnd.uniform(-20000, 20000)
        ln = rnd.uniform(1000, 30000) * rnd.choice((1, -1))
        gs.append({"name": str(k + 1), "start": [ox, oy], "end": [ox + ln * math.cos(ang), oy + ln * math.sin(ang)]})
    if n % 7 == 0:
        ang = math.radians(base + rnd.uniform(20, 70))
        gs.append({"name": "X", "start": [0, 0], "end": [9000 * math.cos(ang), 9000 * math.sin(ang)]})
    rnd.shuffle(gs)
    cl = [clash(rnd.choice(["Ducts", "Pipes"]), rnd.choice(["Walls", "Beams"]),
                [rnd.uniform(-25000, 25000), rnd.uniform(-25000, 25000), rnd.uniform(0, 9000)]) for _ in range(6)]
    cl.append({"a": {"id": 1}, "b": {"id": 2}})  # no point
    rec.call("locate", CL.locate, cl, gs)

# ---------------------------------------------------------------- locate / group / rows / html
clashes = [clash("Ducts", "Structural Framing", [4000, 3000, 3000]),
           clash("Ducts", "Structural Framing", [12000, 3000, 3000], kind="clearance", aid=3, bid=4),
           clash("Pipes", "Walls", [4000, 12000, 3000], level="Level 2", aid=5, bid=6),
           clash("Pipes", "Walls", [4000, 12500, 3000], level="Level 2", aid=5, bid=7),
           clash("Pipes", "Walls", None, level=None, aid=1.0, bid=6),
           {"a": None, "b": {"id": 9, "category": "Walls"}, "point": []},
           {"a": {"id": 10, "family": "", "category": "Cable Trays", "type": None}, "b": {}, "type": "other", "point": [1, 2]},
           {}]
rec.call("locate", CL.locate, clashes, GRIDS)
rec.call("locate", CL.locate, clashes, [])
rec.call("locate", CL.locate, clashes, None)
rec.call("locate", CL.locate, clashes, DEGENERATE)
rec.call("locate", CL.locate, clashes, ONE)
rec.call("locate", CL.locate, [], GRIDS)
rec.call("locate", CL.locate, clashes, SKEW)
rec.call("locate", CL.locate, [clash("A", "B", [1, 2, 3])], [{"name": "A", "start": [0, 0]}])  # KeyError
located = CL.locate([dict(c) for c in clashes], GRIDS)
for by in list(CL.GROUP_KEYS) + ["bogus", "", None]:
    rec.call("group_clashes", CL.group_clashes, located, by)
    for c in located:
        rec.call("group_key", CL.group_key, c, by)
rec.call("group_clashes", CL.group_clashes, [], "pair")
rec.call("group_clashes", CL.group_clashes, [], "bogus")
# ties are broken by the key; equal ids 1 and 1.0 count once
rec.call("group_clashes", CL.group_clashes, [clash("Z", "Y", None), clash("A", "B", None), clash("M", "N", None),
                                             clash("M", "N", None, aid=1.0, bid=1)], "pair")
rec.call("clash_rows", CL.clash_rows, located)
rec.call("clash_rows", CL.clash_rows, [])
rec.call("clash_rows", CL.clash_rows, [{"point": [1]}, {"point": [1, 2, 3, 4]}, {"nearest_grid": None, "a": {"id": "x"}}])

c1 = clash("Ducts <x>", "Walls & Co", [1, 2, 3])
report = {"clashes": [c1], "unit": "mm", "clearance": 50, "document": "P1.rvt",
          "groups": {"pair": CL.group_clashes([c1], "pair")}}
rec.call("to_html", CL.to_html, report)
rec.call("to_html", CL.to_html, report, 'Custom "title" <b> & more')
rec.call("to_html", CL.to_html, {})
rec.call("to_html", CL.to_html, {"clashes": located, "unit": "m", "created": "2026-11-18 10:00", "set_a": "Ducts",
                                 "set_b": {"categories": ["Walls", "Floors"], "link": 5}, "clearance": 0.05,
                                 "groups": dict((g, CL.group_clashes(located, g)) for g in CL.GROUP_KEYS)})
rec.call("to_html", CL.to_html, {"clashes": None, "groups": None, "unit": None, "clearance": 0, "set_a": ["Ducts", "Pipes"],
                                 "document": 'A "quoted" <doc>'})
many = [clash("A", "B", [i, i, i], aid=i, bid=1000 + i) for i in range(45)]
rec.call("to_html", CL.to_html, {"clashes": many, "groups": {"pair": CL.group_clashes(many, "pair")}})
rec.call("to_html", CL.to_html, {"clashes": [], "groups": {"pair": [{"key": "x"}]}})  # KeyError

rec.save()
