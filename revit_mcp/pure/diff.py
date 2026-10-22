# -*- coding: utf-8 -*-
"""Snapshot comparison and location-based matching between element sets.

A snapshot element record looks like:
    {"uid": "...", "id": 123, "category": "Doors", "family": "Single-Flush",
     "type": "0915 x 2134mm", "level": "Level 1", "loc": [x, y, z] (mm),
     "phash": "md5 of parameter values", "params": {"Mark": "D01", ...}}
"""
import math


def _dist(a, b):
    if a is None or b is None:
        return None
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def diff_snapshots(old, new, move_tolerance=1.0, max_items=500):
    """Compare two snapshots keyed by UniqueId.

    old/new: {"elements": [records]}; move_tolerance in the snapshot length unit.
    """
    a = dict((e["uid"], e) for e in old.get("elements", []))
    b = dict((e["uid"], e) for e in new.get("elements", []))
    added = [b[k] for k in b if k not in a]
    removed = [a[k] for k in a if k not in b]
    modified = []
    for k in a:
        if k not in b:
            continue
        ea, eb = a[k], b[k]
        changes = []
        for field in ("category", "family", "type", "level"):
            if ea.get(field) != eb.get(field):
                changes.append({"field": field, "old": ea.get(field), "new": eb.get(field)})
        d = _dist(ea.get("loc"), eb.get("loc"))
        if d is not None and d > move_tolerance:
            changes.append({"field": "location", "moved_by": round(d, 3)})
        if ea.get("phash") != eb.get("phash"):
            pa, pb = ea.get("params") or {}, eb.get("params") or {}
            pchanges = []
            for pn in sorted(set(pa) | set(pb)):
                if pa.get(pn) != pb.get(pn):
                    pchanges.append({"parameter": pn, "old": pa.get(pn), "new": pb.get(pn)})
            if pchanges:
                changes.extend(pchanges)
            elif ea.get("phash") and eb.get("phash"):
                changes.append({"field": "parameters", "note": "parameter values changed"})
        if changes:
            modified.append({"uid": k, "id": eb.get("id"), "category": eb.get("category"),
                             "name": eb.get("type"), "changes": changes})

    def brief(e):
        return {"uid": e.get("uid"), "id": e.get("id"), "category": e.get("category"),
                "family": e.get("family"), "type": e.get("type"), "level": e.get("level")}

    summary = {"added": len(added), "removed": len(removed), "modified": len(modified),
               "unchanged": len([k for k in a if k in b]) - len(modified)}
    by_cat = {}
    for label, items in (("added", added), ("removed", removed)):
        for e in items:
            by_cat.setdefault(e.get("category") or "?", {"added": 0, "removed": 0, "modified": 0})[label] += 1
    for m in modified:
        by_cat.setdefault(m.get("category") or "?", {"added": 0, "removed": 0, "modified": 0})["modified"] += 1
    return {
        "summary": summary,
        "by_category": by_cat,
        "added": [brief(e) for e in added[:max_items]],
        "removed": [brief(e) for e in removed[:max_items]],
        "modified": modified[:max_items],
        "truncated": max(len(added), len(removed), len(modified)) > max_items,
    }


def match_by_location(source, target, tolerance, key_fields=("category",), max_items=500):
    """Match two element sets (e.g. design model vs shop model) by key + proximity.

    Returns matched pairs, unmatched elements on each side and pairs that
    match on location but differ on type (likely substitutions).
    """
    def key(e):
        return tuple((e.get(f) or "").lower() for f in key_fields)

    buckets = {}
    for t in target:
        if t.get("loc") is not None:
            buckets.setdefault(key(t), []).append(t)
    used = set()
    matched, type_mismatch, only_source = [], [], []
    for s in source:
        if s.get("loc") is None:
            only_source.append(s)
            continue
        best, best_d = None, None
        for t in buckets.get(key(s), []):
            if id(t) in used:
                continue
            d = _dist(s["loc"], t["loc"])
            if d is not None and d <= tolerance and (best_d is None or d < best_d):
                best, best_d = t, d
        if best is None:
            only_source.append(s)
            continue
        used.add(id(best))
        pair = {"source_id": s.get("id"), "target_id": best.get("id"), "category": s.get("category"),
                "distance": round(best_d, 3)}
        if (s.get("family"), s.get("type")) != (best.get("family"), best.get("type")):
            pair.update({"source_type": "%s : %s" % (s.get("family"), s.get("type")),
                         "target_type": "%s : %s" % (best.get("family"), best.get("type"))})
            type_mismatch.append(pair)
        else:
            matched.append(pair)
    only_target = [t for t in target if id(t) not in used]

    def brief(e):
        return {"id": e.get("id"), "category": e.get("category"), "family": e.get("family"),
                "type": e.get("type"), "loc": e.get("loc")}

    return {
        "summary": {"source": len(source), "target": len(target), "matched": len(matched),
                    "type_mismatch": len(type_mismatch), "only_in_source": len(only_source),
                    "only_in_target": len(only_target)},
        "type_mismatch": type_mismatch[:max_items],
        "only_in_source": [brief(e) for e in only_source[:max_items]],
        "only_in_target": [brief(e) for e in only_target[:max_items]],
        "matched_sample": matched[:20],
    }
