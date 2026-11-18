# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/diff.py -> diff.json. Run: uv run --project . python host/tests/vectors/gen_diff.py"""
import random

from _lane_c import Recorder
from revit_mcp.pure import diff as D

rec = Recorder("diff")
# round(): CPython rounds the exact binary value, IronPython 2.7 (the reference) rounds halves away from zero.
# The two only differ on decimal ties such as 1.2345 -> 3 digits, so the vectors avoid ties.


def diff(old, new, move_tolerance=1.0, max_items=500):
    return D.diff_snapshots(old, new, move_tolerance, max_items)


def match(source, target, tolerance, key_fields=None, max_items=500):
    if key_fields is None:
        return D.match_by_location(source, target, tolerance, max_items=max_items)
    return D.match_by_location(source, target, tolerance, tuple(key_fields), max_items)


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


def el(uid, **kw):
    e = {"uid": uid, "id": kw.pop("id", 1), "category": "Doors", "family": "F", "type": "T", "level": "L1",
         "loc": [0, 0, 0], "phash": "h", "params": {"Mark": "M"}}
    e.update(kw)
    return e


rec.call("diff_snapshots", diff, A, B)
rec.call("diff_snapshots", diff, A, B, 1.0)
rec.call("diff_snapshots", diff, A, B, 100.0)
rec.call("diff_snapshots", diff, A, B, 99.999)
rec.call("diff_snapshots", diff, B, A, 1.0, 1)
rec.call("diff_snapshots", diff, A, A)
rec.call("diff_snapshots", diff, {}, {})
rec.call("diff_snapshots", diff, {"elements": []}, B)
rec.call("diff_snapshots", diff, A, {"elements": []}, 1.0, 0)
rec.call("diff_snapshots", diff, A, {}, 1.0, -1)
rec.call("diff_snapshots", diff, {"elements": [{"id": 1}]}, B)  # KeyError: no uid

# every kind of change
old = {"elements": [
    el("same"),
    el("moved", loc=[0, 0, 0]), el("moved_less", loc=[0, 0, 0]), el("moved_exact", loc=[0, 0, 0]),
    el("loc_gone", loc=[1, 2, 3]), el("loc_new", loc=None), el("loc_short", loc=[3, 4]), el("loc_empty", loc=[]),
    el("cat", category="Doors"), el("cat_none", category=None), el("fam"), el("lvl", level=None),
    el("param", phash="1", params={"Mark": "A", "Comments": "x", "Gone": 1, "Same": [1, 2]}),
    el("param_hash_only", phash="1", params={"Mark": "A"}),
    el("param_hash_none", phash=None, params=None),
    el("param_hash_empty", phash="", params={}),
    el("param_types", phash="1", params={"n": 1, "f": 1.0, "b": True, "s": "1", "none": None, "l": [1, {"a": 2}]}),
    el("many", loc=[0, 0, 0], category="Doors", phash="1", params={"B": 1, "a": 1, "A": 1}),
    el("dup", type="first"), el("dup", type="second"),
    el("removed1", category="Walls"), el("removed2", category=""), el("removed3", category=None),
    el("no_fields"),
]}
new = {"elements": [
    el("same"),
    el("moved", loc=[3, 4, 12]), el("moved_less", loc=[0.6, 0.8, 0]), el("moved_exact", loc=[1.0004, 0, 0]),
    el("loc_gone", loc=None), el("loc_new", loc=[1, 2, 3]), el("loc_short", loc=[0, 0, 100]), el("loc_empty", loc=[5, 5, 5]),
    el("cat", category="Windows"), el("cat_none", category="Doors"), el("fam", family="G", type="T9"), el("lvl", level="L2"),
    el("param", phash="2", params={"Mark": "B", "Comments": "x", "New": 2, "Same": [1, 2]}),
    el("param_hash_only", phash="2", params={"Mark": "A"}),
    el("param_hash_none", phash="2", params={}),
    el("param_hash_empty", phash="2", params={}),
    el("param_types", phash="2", params={"n": 1.0, "f": 1, "b": 1, "s": 1, "none": 0, "l": [1, {"a": 2.0}]}),
    el("many", loc=[10, 0, 0], category="Walls", phash="2", params={"B": 2, "a": 2, "A": 2}),
    el("dup", type="third"),
    el("added1", category="Walls"), el("added2", category=None), el("added3", category=0), el("added1", category="Roofs"),
    {"uid": "no_fields"},
]}
rec.call("diff_snapshots", diff, old, new)
rec.call("diff_snapshots", diff, old, new, 0.0)
rec.call("diff_snapshots", diff, old, new, 5.0, 2)
rec.call("diff_snapshots", diff, new, old, 1.0, 3)
rec.call("diff_snapshots", diff, old, new, 1.0004)
rec.call("diff_snapshots", diff, {"elements": [el("a", loc=[0.0004, 0, 0])]}, {"elements": [el("a", loc=[2.0, 0, 0])]}, 1)
rec.call("diff_snapshots", diff, {"elements": [el("a", loc=[0, 0, 0])]}, {"elements": [el("a", loc=[1.2344, 0, 0])]}, 1)
rec.call("diff_snapshots", diff, {"elements": [el("a", loc=[0, 0, 0])]}, {"elements": [el("a", loc=[0.0126, 0.0, 0])]}, 0.001)
rec.call("diff_snapshots", diff, {"elements": [el("a", loc=["1", "2"])]}, {"elements": [el("a", loc=[4, 6.0])]}, 1)

rnd = random.Random(7)
for n in range(25):
    def snap():
        out = []
        for i in rnd.sample(range(30), rnd.randint(0, 25)):
            out.append(el("u%d" % i, id=i, category=rnd.choice(["Doors", "Walls", None, "Windows"]),
                          type=rnd.choice(["T1", "T2"]), level=rnd.choice(["L1", "L2"]),
                          loc=rnd.choice([None, [rnd.choice([0, 0.5, 2, 1000.1236]), 0, rnd.choice([0, 1])]]),
                          phash=rnd.choice(["a", "b", None]),
                          params=rnd.choice([None, {}, {"Mark": rnd.choice(["A", "B"]), "X": rnd.choice([1, 2, None])}])))
        return {"elements": out}
    rec.call("diff_snapshots", diff, snap(), snap(), rnd.choice([0.4, 1.0, 5]), rnd.choice([500, 3, 1]))

# ---------------------------------------------------------------- match_by_location
rec.call("match_by_location", match, A["elements"], B["elements"], 10)
rec.call("match_by_location", match, A["elements"], B["elements"], 10, ["category"])
rec.call("match_by_location", match, A["elements"], B["elements"], 200, ["category"])
rec.call("match_by_location", match, A["elements"], B["elements"], 200, ["category", "type"])
rec.call("match_by_location", match, A["elements"], B["elements"], 200, [])
rec.call("match_by_location", match, [], [], 10)
rec.call("match_by_location", match, A["elements"], [], 10)
rec.call("match_by_location", match, [], B["elements"], 10)


def m(i, cat="Doors", fam="F", typ="T", loc=(0, 0, 0)):
    return {"id": i, "category": cat, "family": fam, "type": typ, "loc": None if loc is None else list(loc)}


src = [m(1), m(2, loc=(1000, 0, 0)), m(3, loc=None), m(4, cat="DOORS", loc=(2000, 0, 0)), m(5, cat=None, loc=(3000, 0, 0)),
       m(6, cat="Walls", loc=(0, 0, 0)), m(7, loc=(5000, 0, 0)), m(8, loc=(5000, 1, 0)), m(9, loc=(5000, 2, 0)),
       m(10, loc=(9000, 0, 0), typ="X"), m(11, loc=(9500, 0, 0), fam=None, typ=None), m(12, loc=(0, 0)),
       {"id": 13, "loc": [7000, 0, 0]}]
tgt = [m(101, loc=(3, 4, 0)), m(102, loc=(1000, 50, 0)), m(103, loc=(1000, 49.9994, 0)), m(104, loc=None),
       m(105, cat="doors", loc=(2000, 0, 5)), m(106, cat="", loc=(3000, 0, 0)), m(107, cat="Walls", loc=(0, 0, 60)),
       m(108, loc=(5000, 1.4, 0)), m(109, loc=(5000, 1.6, 0)),
       m(110, loc=(9000, 0, 0), typ="Y"), m(111, loc=(9500, 0, 0), fam="None", typ="None"), m(112, loc=(0, 0, 500)),
       {"id": 113, "loc": [7000, 0, 0.0004]}]
for tol in (0, 1, 5, 50, 50.0, 49.9999, 1e9):
    rec.call("match_by_location", match, src, tgt, tol)
rec.call("match_by_location", match, src, tgt, 50, ["category", "family"])
rec.call("match_by_location", match, src, tgt, 50, ["type"])
rec.call("match_by_location", match, src, tgt, 50, ["category"], 2)
rec.call("match_by_location", match, src, tgt, 50, ["category"], 0)
rec.call("match_by_location", match, tgt, src, 50, ["category"], 500)
rec.call("match_by_location", match, [m(i, loc=(i, 0, 0)) for i in range(30)],
         [m(100 + i, loc=(i + 0.25, 0, 0), typ="T" if i % 3 else "U") for i in range(30)], 0.5)
for n in range(20):
    def pts(base):
        return [m(base + i, cat=rnd.choice(["Doors", "Walls"]), typ=rnd.choice(["T", "U"]),
                  loc=rnd.choice([None, (rnd.randint(0, 6) * 10, rnd.randint(0, 2) * 10, 0)])) for i in range(rnd.randint(0, 15))]
    rec.call("match_by_location", match, pts(0), pts(100), rnd.choice([0, 5, 10, 15, 25]), ["category"], rnd.choice([500, 2]))

rec.save()
