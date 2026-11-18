using System.Collections;

namespace RvtssHost.Pure;

/// <summary>
/// Clash post-processing: grid zones, nearest grid intersection, grouping and CSV/HTML reports.
///
/// Used by the Revit route /qc/clashes/ and by the MCP tool export_clash_report. Coordinates are plan XY in
/// one unit (mm on the wire).
///
/// Grid input: [{"name": "A", "start": [x, y], "end": [x, y]}] - straight grids only (arc grids are skipped by
/// the Revit side). Clash input: dicts with "a", "b" (element briefs: id, category, family, type, name),
/// "type" ("hard"/"clearance"), "distance", "point" [x, y, z], "level".
/// </summary>
public static class Clash
{
    public const double AngleTolDeg = 1.0;

    private const double DegPerRad = 180.0 / Math.PI;
    private const double RadPerDeg = Math.PI / 180.0;

    // ------------------------------------------------------------ typed data
    /// <summary>One grid line as plain numbers (the hot loops never touch the dictionaries).</summary>
    private struct Line
    {
        public Dict Src;
        public double Sx, Sy;
        public bool HasDir;
        public double Vx, Vy;
    }

    /// <summary>A direction family prepared for zone lookups: unit normal and the grid offsets along it, sorted.</summary>
    private sealed class Zone
    {
        public double Nx, Ny;
        public double[] Offs = Array.Empty<double>();
        public object?[] Names = Array.Empty<object?>();
    }

    private sealed class Family
    {
        public double Angle, Dx, Dy;
        public List<int> Members = new();
    }

    private static Dict AsGrid(object? g) => g as Dict ?? throw new InvalidCastException("grid must be an object");

    private static IList Seq(object? v) => v as IList ?? throw new InvalidCastException("expected a list");

    private static double Num(IList seq, int i) => Py.ToFloat(seq[i]);

    private static Line ToLine(Dict g)
    {
        var s = Seq(PyX.Item(g, "start"));
        var e = Seq(PyX.Item(g, "end"));
        var line = new Line { Src = g, Sx = Num(s, 0), Sy = Num(s, 1) };
        double dx = Num(e, 0) - line.Sx, dy = Num(e, 1) - line.Sy;
        var n = Math.Sqrt(dx * dx + dy * dy);
        if (n < 1e-9)
            return line;
        line.HasDir = true;
        line.Vx = dx / n;
        line.Vy = dy / n;
        return line;
    }

    private static Line[] ToLines(IEnumerable<object?> grids) => grids.Select(g => ToLine(AsGrid(g))).ToArray();

    private static double Angle(double vx, double vy)
    {
        // Python float %: the result takes the sign of the divisor
        var a = Math.Atan2(vy, vx) * DegPerRad % 180.0;
        if (a != 0 && a < 0)
            a += 180.0;
        return a > 180.0 - AngleTolDeg ? 0.0 : a;
    }

    private static (int digit, string s) LabelKey(object? name)
    {
        var s = Py.Truthy(name) ? Py.Str(name) : "";
        // letters before numbers so intersections read "A/1" like drawings do
        return (s.Length > 0 && char.IsDigit(s[0]) ? 1 : 0, s);
    }

    private static int CompareLabel((int digit, string s) x, (int digit, string s) y) =>
        x.digit != y.digit ? x.digit.CompareTo(y.digit) : string.CompareOrdinal(x.s, y.s);

    public static string IntersectionName(object? n1, object? n2)
    {
        // sorted() is stable: n1 stays first when the keys are equal
        var swap = CompareLabel(LabelKey(n2), LabelKey(n1)) < 0;
        return PyX.Fmt(swap ? n2 : n1) + "/" + PyX.Fmt(swap ? n1 : n2);
    }

    private static bool Intersect(in Line a, in Line b, out double x, out double y)
    {
        x = y = 0;
        if (!a.HasDir || !b.HasDir)
            return false;
        var cross = a.Vx * b.Vy - a.Vy * b.Vx;
        if (Math.Abs(cross) < Math.Sin(AngleTolDeg * RadPerDeg))
            return false;
        var t = ((b.Sx - a.Sx) * b.Vy - (b.Sy - a.Sy) * b.Vx) / cross;
        x = a.Sx + t * a.Vx;
        y = a.Sy + t * a.Vy;
        return true;
    }

    /// <summary>Intersection of the two grid lines (extended), or None when parallel.</summary>
    public static Lst? LineIntersection(Dict g1, Dict g2)
    {
        var a = ToLine(g1);
        var b = ToLine(g2);
        return Intersect(a, b, out var x, out var y) ? new Lst { x, y } : null;
    }

    public static List<Dict> GridIntersections(IEnumerable<object?> grids)
    {
        var lines = ToLines(grids);
        var res = new List<Dict>();
        for (var i = 0; i < lines.Length; i++)
            for (var j = i + 1; j < lines.Length; j++)
                if (Intersect(lines[i], lines[j], out var x, out var y))
                    res.Add(new Dict
                    {
                        ["name"] = IntersectionName(PyX.Item(lines[i].Src, "name"), PyX.Item(lines[j].Src, "name")),
                        ["point"] = new Lst { x, y },
                    });
        return res;
    }

    private static Dict? Nearest(double px, double py, double[] xs, double[] ys, object?[] names)
    {
        var best = -1;
        var bestD = 0.0;
        for (var i = 0; i < xs.Length; i++)
        {
            double dx = px - xs[i], dy = py - ys[i];
            var d = Math.Sqrt(dx * dx + dy * dy);
            if (best < 0 || d < bestD)
            {
                best = i;
                bestD = d;
            }
        }
        if (best < 0)
            return null;
        return new Dict { ["name"] = names[best], ["distance"] = Py.Round(bestD, 1) };
    }

    private static (double[] xs, double[] ys, object?[] names) IntersectionArrays(IEnumerable<object?> intersections)
    {
        var list = intersections.ToList();
        var xs = new double[list.Count];
        var ys = new double[list.Count];
        var names = new object?[list.Count];
        for (var i = 0; i < list.Count; i++)
        {
            var it = list[i] as Dict ?? throw new InvalidCastException("intersection must be an object");
            var pt = Seq(PyX.Item(it, "point"));
            xs[i] = Num(pt, 0);
            ys[i] = Num(pt, 1);
            names[i] = PyX.Item(it, "name");
        }
        return (xs, ys, names);
    }

    public static Dict? NearestIntersection(IList point, IEnumerable<object?> intersections)
    {
        var (xs, ys, names) = IntersectionArrays(intersections);
        if (xs.Length == 0)
            return null;
        return Nearest(Num(point, 0), Num(point, 1), xs, ys, names);
    }

    private static List<Family> Families(Line[] lines)
    {
        var fams = new List<Family>();
        for (var i = 0; i < lines.Length; i++)
        {
            if (!lines[i].HasDir)
                continue;
            var a = Angle(lines[i].Vx, lines[i].Vy);
            var found = false;
            foreach (var f in fams)
            {
                var diff = Math.Abs(f.Angle - a);
                if (Math.Min(diff, 180.0 - diff) <= AngleTolDeg)
                {
                    f.Members.Add(i);
                    found = true;
                    break;
                }
            }
            if (!found)
                fams.Add(new Family { Angle = a, Dx = Math.Cos(a * RadPerDeg), Dy = Math.Sin(a * RadPerDeg), Members = { i } });
        }
        // stable, like list.sort
        return fams.OrderBy(f => -f.Members.Count).ToList();
    }

    /// <summary>Group grids by direction (parallel within ANGLE_TOL_DEG); largest families first.</summary>
    public static List<Dict> DirectionFamilies(IEnumerable<object?> grids)
    {
        var lines = ToLines(grids);
        return Families(lines).Select(f => new Dict
        {
            ["angle"] = f.Angle,
            ["dir"] = new Lst { f.Dx, f.Dy },
            ["grids"] = new Lst(f.Members.Select(i => (object?)lines[i].Src)),
        }).ToList();
    }

    private static Zone ToZone(Family fam, Line[] lines)
    {
        double nx = -fam.Dy, ny = fam.Dx;
        // measure towards +X / +Y so zones read in drawing order (A-B, 1-2), whatever the grid direction
        if ((Math.Abs(nx) >= Math.Abs(ny) && nx < 0) || (Math.Abs(ny) > Math.Abs(nx) && ny < 0))
        {
            nx = -nx;
            ny = -ny;
        }
        var offs = fam.Members
            .Select(i => (off: lines[i].Sx * nx + lines[i].Sy * ny, name: PyX.Item(lines[i].Src, "name")))
            .OrderBy(t => t.off)
            .ToList();
        return new Zone { Nx = nx, Ny = ny, Offs = offs.Select(t => t.off).ToArray(), Names = offs.Select(t => t.name).ToArray() };
    }

    private static string FamilyZone(double px, double py, Zone z)
    {
        var offs = z.Offs;
        var last = offs.Length - 1;
        var p = px * z.Nx + py * z.Ny;
        if (p < offs[0])
            return "<" + PyX.Fmt(z.Names[0]);
        if (p > offs[last])
            return ">" + PyX.Fmt(z.Names[last]);
        for (var i = 0; i < last; i++)
        {
            if (offs[i] <= p && p <= offs[i + 1])
                return !PyX.Eq(z.Names[i], z.Names[i + 1])
                    ? PyX.Fmt(z.Names[i]) + "-" + PyX.Fmt(z.Names[i + 1])
                    : Py.Str(z.Names[i]);
        }
        return Py.Str(z.Names[last]);
    }

    private static Zone[] MainZones(Line[] lines) => Families(lines).Take(2).Select(f => ToZone(f, lines)).ToArray();

    private static string? ZoneLabel(double px, double py, Zone[] zones)
    {
        if (zones.Length == 0)
            return null;
        string label;
        if (zones.Length == 1)
        {
            label = FamilyZone(px, py, zones[0]);
        }
        else
        {
            var a = FamilyZone(px, py, zones[0]);
            var b = FamilyZone(px, py, zones[1]);
            var swap = CompareLabel(LabelKey(b.TrimStart('<', '>')), LabelKey(a.TrimStart('<', '>'))) < 0;
            label = swap ? b + "/" + a : a + "/" + b;
        }
        return label.Length > 0 ? label : null;
    }

    /// <summary>Zone label between the bounding grids of the two main directions, e.g. 'A-B/1-2'.</summary>
    public static string? GridZone(IList? point, IEnumerable<object?>? grids)
    {
        if (point == null || point.Count == 0 || grids == null)
            return null;
        var lines = ToLines(grids);
        if (lines.Length == 0)
            return null;
        return ZoneLabel(Num(point, 0), Num(point, 1), MainZones(lines));
    }

    /// <summary>Add grid_zone and nearest_grid to every clash that has a point.</summary>
    public static T Locate<T>(T clashes, IEnumerable<object?>? grids) where T : IEnumerable<object?>
    {
        var lines = ToLines(grids ?? Enumerable.Empty<object?>());
        // every pair of grids once, as flat arrays
        var names = new List<object?>();
        var xs = new List<double>();
        var ys = new List<double>();
        for (var i = 0; i < lines.Length; i++)
            for (var j = i + 1; j < lines.Length; j++)
                if (Intersect(lines[i], lines[j], out var x, out var y))
                {
                    names.Add(IntersectionName(PyX.Item(lines[i].Src, "name"), PyX.Item(lines[j].Src, "name")));
                    xs.Add(x);
                    ys.Add(y);
                }
        if (lines.Length == 0)
            return clashes;
        double[] ax = xs.ToArray(), ay = ys.ToArray();
        var an = names.ToArray();
        Zone[]? zones = null;
        foreach (var item in clashes)
        {
            var c = item as Dict ?? throw new InvalidCastException("clash must be an object");
            var pv = c.Get("point");
            if (!Py.Truthy(pv))
                continue;
            var pt = Seq(pv);
            double px = Num(pt, 0), py = Num(pt, 1);
            zones ??= MainZones(lines);
            c["grid_zone"] = ZoneLabel(px, py, zones);
            var near = Nearest(px, py, ax, ay, an);
            if (near != null)
                c["nearest_grid"] = near;
        }
        return clashes;
    }

    public static readonly string[] GroupKeys = { "pair", "type_pair", "level", "grid_zone" };

    private static Dict Side(Dict clash, string key) => Py.Truthy(clash.Get(key)) && clash.Get(key) is Dict d ? d : new Dict();

    private static string Or(object? a, object? b, string def = "?") =>
        PyX.Fmt(Py.Truthy(a) ? a : Py.Truthy(b) ? b : def);

    public static string GroupKey(Dict clash, string by)
    {
        Dict a = Side(clash, "a"), b = Side(clash, "b");
        switch (by)
        {
            case "pair":
                return Or(a.Get("category"), null) + " x " + Or(b.Get("category"), null);
            case "type_pair":
                return Or(a.Get("family"), a.Get("category")) + " : " + Or(a.Get("type"), null) + " x "
                       + Or(b.Get("family"), b.Get("category")) + " : " + Or(b.Get("type"), null);
            case "level":
                return Or(clash.Get("level"), null, "(no level)");
            case "grid_zone":
                return Or(clash.Get("grid_zone"), null, "(no grid zone)");
        }
        throw new FormatException("group_by must be one of " + string.Join(", ", GroupKeys));
    }

    private static bool IsHard(Dict c) => PyX.Eq(c.Get("type", "hard"), "hard");

    public static List<Dict> GroupClashes(IEnumerable<object?> clashes, string by)
    {
        var groups = new Dictionary<string, Dict>(StringComparer.Ordinal);
        var order = new List<Dict>();
        long index = 0;
        foreach (var item in clashes)
        {
            var c = item as Dict ?? throw new InvalidCastException("clash must be an object");
            var key = GroupKey(c, by);
            if (!groups.TryGetValue(key, out var g))
            {
                g = new Dict
                {
                    ["key"] = key, ["count"] = 0L, ["hard"] = 0L, ["clearance"] = 0L,
                    ["clash_indices"] = new Lst(), ["element_ids"] = new Lst(),
                };
                groups[key] = g;
                order.Add(g);
            }
            g["count"] = (long)g["count"]! + 1;
            var kind = IsHard(c) ? "hard" : "clearance";
            g[kind] = (long)g[kind]! + 1;
            ((Lst)g["clash_indices"]!).Add(index);
            var ids = (Lst)g["element_ids"]!;
            foreach (var side in new[] { "a", "b" })
            {
                var eid = Side(c, side).Get("id");
                if (eid != null && !PyX.In(eid, ids))
                    ids.Add(eid);
            }
            index++;
        }
        return order.OrderBy(g => -(long)g["count"]!).ThenBy(g => (string)g["key"]!, StringComparer.Ordinal).ToList();
    }

    public static readonly string[] RowHeader =
    {
        "#", "Type", "Distance", "Level", "Grid zone", "Nearest grid", "Grid offset",
        "A id", "A category", "A family", "A type", "B id", "B category", "B family", "B type",
        "X", "Y", "Z",
    };

    public static List<Lst> ClashRows(IEnumerable<object?> clashes)
    {
        var rows = new List<Lst>();
        long i = 0;
        foreach (var item in clashes)
        {
            var c = item as Dict ?? throw new InvalidCastException("clash must be an object");
            Dict a = Side(c, "a"), b = Side(c, "b");
            var near = Side(c, "nearest_grid");
            var pt = Py.Truthy(c.Get("point")) ? PyX.Items(c.Get("point")) : new List<object?>();
            pt.Add(null);
            pt.Add(null);
            pt.Add(null);
            i++;
            rows.Add(new Lst
            {
                i, c.Get("type", "hard"), c.Get("distance"), c.Get("level"), c.Get("grid_zone"),
                near.Get("name"), near.Get("distance"),
                a.Get("id"), a.Get("category"), a.Get("family"), a.Get("type"),
                b.Get("id"), b.Get("category"), b.Get("family"), b.Get("type"),
                pt[0], pt[1], pt[2],
            });
        }
        return rows;
    }

    private static string Esc(object? v)
    {
        var s = v == null ? "" : PyX.Fmt(v);
        return s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
    }

    /// <summary>Self-contained HTML report (summary, groups, all clashes).</summary>
    public static string ToHtml(Dict report, string title = "RVTSS clash report")
    {
        var clashes = Py.Truthy(report.Get("clashes")) ? PyX.Items(report.Get("clashes")) : new List<object?>();
        var cl = clashes.Select(c => c as Dict ?? throw new InvalidCastException("clash must be an object")).ToList();
        var unit = Py.Truthy(report.Get("unit")) ? report.Get("unit") : "mm";
        var unitText = PyX.Fmt(unit);
        var parts = new List<string>
        {
            "<!doctype html><html><head><meta charset='utf-8'><title>" + Esc(title) + "</title><style>"
            + "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}"
            + "table{border-collapse:collapse;margin:12px 0;font-size:13px}"
            + "th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}"
            + "th{background:#f0f0f0}.hard{color:#b00020}.clearance{color:#a15c00}"
            + "</style></head><body>",
            "<h1>" + Esc(title) + "</h1>",
        };
        var meta = new List<(string k, object? v)>
        {
            ("Document", report.Get("document")), ("Created", report.Get("created")),
            ("Set A", report.Get("set_a")), ("Set B", report.Get("set_b")),
            ("Clearance", Py.Truthy(report.Get("clearance")) ? PyX.Fmt(report.Get("clearance")) + " " + unitText : "hard only"),
            ("Clashes", (long)cl.Count), ("Hard", (long)cl.Count(IsHard)),
            ("Clearance violations", (long)cl.Count(c => PyX.Eq(c.Get("type"), "clearance"))),
        };
        parts.Add("<table>" + string.Concat(meta.Where(m => m.v != null)
            .Select(m => "<tr><th>" + Esc(m.k) + "</th><td>" + Esc(m.v) + "</td></tr>")) + "</table>");
        var groupsBy = Py.Truthy(report.Get("groups")) ? report.Get("groups") as Dict ?? new Dict() : new Dict();
        foreach (var kv in groupsBy.OrderBy(x => x.Key, StringComparer.Ordinal))
        {
            parts.Add("<h2>Grouped by " + Esc(kv.Key) + "</h2><table><tr><th>Group</th><th>Clashes</th><th>Hard</th>"
                      + "<th>Clearance</th><th>Element ids</th></tr>");
            foreach (var item in PyX.Items(kv.Value))
            {
                var g = item as Dict ?? throw new InvalidCastException("group must be an object");
                var ids = PyX.Head(PyX.Items(PyX.Item(g, "element_ids")), 40);
                parts.Add("<tr><td>" + Esc(PyX.Item(g, "key")) + "</td><td>" + PyX.Fmt(PyX.Item(g, "count")) + "</td><td>"
                          + PyX.Fmt(PyX.Item(g, "hard")) + "</td><td>" + PyX.Fmt(PyX.Item(g, "clearance")) + "</td><td>"
                          + Esc(string.Join(", ", ids.Select(Py.Str))) + "</td></tr>");
            }
            parts.Add("</table>");
        }
        var header = RowHeader.ToList();
        header[2] = "Distance [" + unitText + "]";
        header[6] = "Grid offset [" + unitText + "]";
        parts.Add("<h2>Clashes</h2><table><tr>" + string.Concat(header.Select(h => "<th>" + Esc(h) + "</th>")) + "</tr>");
        foreach (var row in ClashRows(clashes))
            parts.Add("<tr class='" + Esc(row[1]) + "'>" + string.Concat(row.Select(v => "<td>" + Esc(v) + "</td>")) + "</tr>");
        parts.Add("</table></body></html>");
        return string.Join("\n", parts);
    }
}
