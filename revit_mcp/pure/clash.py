# -*- coding: utf-8 -*-
"""Clash post-processing: grid zones, nearest grid intersection, grouping and CSV/HTML reports.

Pure Python (IronPython 2.7/3.4 and CPython): used by the Revit route /qc/clashes/
and by the MCP tool export_clash_report. Coordinates are plan XY in one unit
(mm on the wire).

Grid input: [{"name": "A", "start": [x, y], "end": [x, y]}] - straight grids only
(arc grids are skipped by the Revit side). Clash input: dicts with "a", "b"
(element briefs: id, category, family, type, name), "type" ("hard"/"clearance"),
"distance", "point" [x, y, z], "level".
"""
import math

ANGLE_TOL_DEG = 1.0


def _vec(g):
    (x1, y1), (x2, y2) = g["start"][:2], g["end"][:2]
    dx, dy = float(x2) - float(x1), float(y2) - float(y1)
    n = math.hypot(dx, dy)
    if n < 1e-9:
        return None
    return dx / n, dy / n


def _angle(v):
    a = math.degrees(math.atan2(v[1], v[0])) % 180.0
    return 0.0 if a > 180.0 - ANGLE_TOL_DEG else a


def _label_key(name):
    s = str(name or "")
    # letters before numbers so intersections read "A/1" like drawings do
    return (1 if s[:1].isdigit() else 0, s)


def intersection_name(n1, n2):
    a, b = sorted([n1, n2], key=_label_key)
    return "%s/%s" % (a, b)


def line_intersection(g1, g2):
    """Intersection of the two grid lines (extended), or None when parallel."""
    v1, v2 = _vec(g1), _vec(g2)
    if v1 is None or v2 is None:
        return None
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    if abs(cross) < math.sin(math.radians(ANGLE_TOL_DEG)):
        return None
    p, q = g1["start"], g2["start"]
    t = ((q[0] - p[0]) * v2[1] - (q[1] - p[1]) * v2[0]) / cross
    return [p[0] + t * v1[0], p[1] + t * v1[1]]


def grid_intersections(grids):
    out = []
    for i in range(len(grids)):
        for j in range(i + 1, len(grids)):
            pt = line_intersection(grids[i], grids[j])
            if pt is not None:
                out.append({"name": intersection_name(grids[i]["name"], grids[j]["name"]), "point": pt})
    return out


def nearest_intersection(point, intersections):
    best = None
    for it in intersections:
        d = math.hypot(point[0] - it["point"][0], point[1] - it["point"][1])
        if best is None or d < best["distance"]:
            best = {"name": it["name"], "distance": d}
    if best is not None:
        best["distance"] = round(best["distance"], 1)
    return best


def direction_families(grids):
    """Group grids by direction (parallel within ANGLE_TOL_DEG); largest families first."""
    fams = []
    for g in grids:
        v = _vec(g)
        if v is None:
            continue
        a = _angle(v)
        for f in fams:
            diff = abs(f["angle"] - a)
            if min(diff, 180.0 - diff) <= ANGLE_TOL_DEG:
                f["grids"].append(g)
                break
        else:
            fams.append({"angle": a, "dir": (math.cos(math.radians(a)), math.sin(math.radians(a))), "grids": [g]})
    fams.sort(key=lambda f: -len(f["grids"]))
    return fams


def _family_zone(point, fam):
    nx, ny = -fam["dir"][1], fam["dir"][0]
    # measure towards +X / +Y so zones read in drawing order (A-B, 1-2), whatever the grid direction
    if (abs(nx) >= abs(ny) and nx < 0) or (abs(ny) > abs(nx) and ny < 0):
        nx, ny = -nx, -ny
    offs = sorted(((g["start"][0] * nx + g["start"][1] * ny, g["name"]) for g in fam["grids"]),
                  key=lambda t: t[0])
    p = point[0] * nx + point[1] * ny
    if p < offs[0][0]:
        return "<%s" % offs[0][1]
    if p > offs[-1][0]:
        return ">%s" % offs[-1][1]
    for (o1, n1), (o2, n2) in zip(offs, offs[1:]):
        if o1 <= p <= o2:
            return "%s-%s" % (n1, n2) if n1 != n2 else str(n1)
    return str(offs[-1][1])


def grid_zone(point, grids):
    """Zone label between the bounding grids of the two main directions, e.g. 'A-B/1-2'."""
    if not point or not grids:
        return None
    fams = direction_families(grids)[:2]
    labels = [_family_zone(point, f) for f in fams if f["grids"]]
    labels.sort(key=lambda s: _label_key(s.lstrip("<>")))
    return "/".join(labels) or None


def locate(clashes, grids):
    """Add grid_zone and nearest_grid to every clash that has a point."""
    inters = grid_intersections(grids or [])
    for c in clashes:
        pt = c.get("point")
        if not pt or not grids:
            continue
        c["grid_zone"] = grid_zone(pt, grids)
        near = nearest_intersection(pt, inters)
        if near:
            c["nearest_grid"] = near
    return clashes


GROUP_KEYS = ("pair", "type_pair", "level", "grid_zone")


def group_key(clash, by):
    a, b = clash.get("a") or {}, clash.get("b") or {}
    if by == "pair":
        return "%s x %s" % (a.get("category") or "?", b.get("category") or "?")
    if by == "type_pair":
        return "%s : %s x %s : %s" % (a.get("family") or a.get("category") or "?", a.get("type") or "?",
                                      b.get("family") or b.get("category") or "?", b.get("type") or "?")
    if by == "level":
        return clash.get("level") or "(no level)"
    if by == "grid_zone":
        return clash.get("grid_zone") or "(no grid zone)"
    raise ValueError("group_by must be one of %s" % ", ".join(GROUP_KEYS))


def group_clashes(clashes, by):
    groups = {}
    for i, c in enumerate(clashes):
        g = groups.setdefault(group_key(c, by), {"key": group_key(c, by), "count": 0, "hard": 0, "clearance": 0,
                                                  "clash_indices": [], "element_ids": []})
        g["count"] += 1
        g["hard" if c.get("type", "hard") == "hard" else "clearance"] += 1
        g["clash_indices"].append(i)
        for side in ("a", "b"):
            eid = (c.get(side) or {}).get("id")
            if eid is not None and eid not in g["element_ids"]:
                g["element_ids"].append(eid)
    return sorted(groups.values(), key=lambda g: (-g["count"], g["key"]))


ROW_HEADER = ["#", "Type", "Distance", "Level", "Grid zone", "Nearest grid", "Grid offset",
              "A id", "A category", "A family", "A type", "B id", "B category", "B family", "B type",
              "X", "Y", "Z"]


def clash_rows(clashes):
    rows = []
    for i, c in enumerate(clashes):
        a, b = c.get("a") or {}, c.get("b") or {}
        near = c.get("nearest_grid") or {}
        pt = list(c.get("point") or [None, None, None]) + [None, None, None]
        rows.append([i + 1, c.get("type", "hard"), c.get("distance"), c.get("level"), c.get("grid_zone"),
                     near.get("name"), near.get("distance"),
                     a.get("id"), a.get("category"), a.get("family"), a.get("type"),
                     b.get("id"), b.get("category"), b.get("family"), b.get("type"),
                     pt[0], pt[1], pt[2]])
    return rows


def _esc(v):
    s = u"" if v is None else (u"%s" % (v,))
    return s.replace(u"&", u"&amp;").replace(u"<", u"&lt;").replace(u">", u"&gt;").replace(u'"', u"&quot;")


def to_html(report, title=u"RVTSS clash report"):
    """Self-contained HTML report (summary, groups, all clashes)."""
    clashes = report.get("clashes") or []
    unit = report.get("unit") or "mm"
    parts = [u"<!doctype html><html><head><meta charset='utf-8'><title>%s</title><style>"
             u"body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}"
             u"table{border-collapse:collapse;margin:12px 0;font-size:13px}"
             u"th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}"
             u"th{background:#f0f0f0}.hard{color:#b00020}.clearance{color:#a15c00}"
             u"</style></head><body>" % _esc(title), u"<h1>%s</h1>" % _esc(title)]
    meta = [("Document", report.get("document")), ("Created", report.get("created")),
            ("Set A", report.get("set_a")), ("Set B", report.get("set_b")),
            ("Clearance", "%s %s" % (report.get("clearance"), unit) if report.get("clearance") else "hard only"),
            ("Clashes", len(clashes)), ("Hard", len([c for c in clashes if c.get("type", "hard") == "hard"])),
            ("Clearance violations", len([c for c in clashes if c.get("type") == "clearance"]))]
    parts.append(u"<table>%s</table>" % u"".join(u"<tr><th>%s</th><td>%s</td></tr>" % (_esc(k), _esc(v))
                                                for k, v in meta if v is not None))
    for by, groups in sorted((report.get("groups") or {}).items()):
        parts.append(u"<h2>Grouped by %s</h2><table><tr><th>Group</th><th>Clashes</th><th>Hard</th>"
                     u"<th>Clearance</th><th>Element ids</th></tr>" % _esc(by))
        for g in groups:
            parts.append(u"<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _esc(g["key"]), g["count"], g["hard"], g["clearance"],
                _esc(", ".join(str(i) for i in g["element_ids"][:40]))))
        parts.append(u"</table>")
    header = list(ROW_HEADER)
    header[2] = "Distance [%s]" % unit
    header[6] = "Grid offset [%s]" % unit
    parts.append(u"<h2>Clashes</h2><table><tr>%s</tr>" % u"".join(u"<th>%s</th>" % _esc(h) for h in header))
    for row in clash_rows(clashes):
        parts.append(u"<tr class='%s'>%s</tr>" % (_esc(row[1]), u"".join(u"<td>%s</td>" % _esc(v) for v in row)))
    parts.append(u"</table></body></html>")
    return u"\n".join(parts)
