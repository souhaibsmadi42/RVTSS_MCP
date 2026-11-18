# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/spaces.py -> spaces.json."""
from _lane_b import Recorder
from revit_mcp.pure import spaces as SP

r = Recorder(SP)
r.extra["not_enclosed_markers"] = list(SP.NOT_ENCLOSED_MARKERS)
r.extra["redundant_markers"] = list(SP.REDUNDANT_MARKERS)

for text in ["Room is not in a properly enclosed region", "Multiple Rooms are in the same enclosed region.",
             "Highlighted walls overlap", None, "", "ROOM IS NOT ENCLOSED", "Area is Redundant",
             "not enclosed and redundant", "Space is not in a properly enclosed region", "notenclosed", "Not  enclosed",
             "A redundant Room in the same enclosed region", "enclosed"]:
    r.call("classify_warning", text)

for placed in [True, False, None, 0, 1, "", "yes"]:
    for area in [0, 12.5, 1e-9, 1.1e-9, 1e-12, -5, None, 0.0, 1, True, False]:
        r.call("spatial_status", placed, area)
        for kind in ["redundant", "not_enclosed", None, ""]:
            r.call("spatial_status", placed, area, kind)
r.call("spatial_status", True, 0, warning_kind="redundant")

WALLS = [
    ([5.0, 3.0, [[1.0, 2.0]]], {}), ([1.0, 1.0, [[5.0, 5.0]]], {}), ([None, 3.0], {}), ([5.0, 3.0], {}), ([5, 3, []], {}),
    ([5, 3, None], {}), ([5.5, 2.75, [[0.9, 2.1], [1.2, 1.5], [0.6, 0.6]]], {}), ([-5, 3, [[1, 1]]], {}), ([5, -3], {}),
    ([5, 3, [[-1, 2], [1, -2], [None, 2], [1, None], [0, 0]]], {}), (["5", "3", [["1", "2"]]], {}), ([0, 0, [[1, 1]]], {}),
    ([5, 3, [[1, 2, 3]]], {}), ([5, 3, [[1]]], {}), ([5, 3, [5]], {}), (["abc", 3], {}), ([5, 3, [["x", 1]]], {}),
    ([4.2, 2.4], {"openings": [[1.0, 2.1]]}), ([True, 3], {}), ([10, 2.5, [[10, 2.5]]], {}), ([10, 2.5, [[10, 2.6]]], {}),
    ([1e6, 1e-6, [[0.5, 0.5]]], {}), ([3.3, 2.7, [[0.1, 0.2]] * 7], {}),
]
for args, kw in WALLS:
    r.call("wall_finish", *args, **kw)

ITEMS = [{"level": "L1", "area": 10.0}, {"level": "L1", "area": 5.5}, {"level": None, "area": 1.0}]
BIG = [{"level": "L%d" % (i % 4), "dept": ["A", "B", None, ""][i % 4], "area": 10.123 + i * 0.37, "volume": i * 2.5 + 0.111,
        "perimeter": i, "name": "R%d" % i} for i in range(25)]
MIXED = [{"k": "a", "area": 1}, {"k": "a", "area": "2"}, {"k": "a", "area": None}, {"k": "a"}, {"k": "", "area": 2.25},
         {"k": 1, "area": 3}, {"k": 1.5, "area": True}, {"k": True, "area": False}, {"area": 4.0004}, {"k": "b", "area": -1.2341},
         {"k": "b", "area": 0.0001}, {"k": 0, "area": 1}]
for items, key in [(ITEMS, "level"), (ITEMS, "missing"), ([], "level"), (BIG, "level"), (BIG, "dept"), (BIG, "name"),
                   (MIXED, "k"), (["notadict"], "k")]:
    r.call("summarize_by", items, key)
    r.call("summarize_by", items, key, ["area", "volume"])
    r.call("summarize_by", items, key, [])
    r.call("summarize_by", items, key, value_keys=["perimeter", "nope"])
r.write("spaces")
