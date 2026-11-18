namespace RvtssHost.Tests;

public static class ClashTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "clash");
        var k = LaneC.D(data["constants"]);
        t.Eq("ANGLE_TOL_DEG", k["ANGLE_TOL_DEG"], Clash.AngleTolDeg);
        t.Eq("GROUP_KEYS", k["GROUP_KEYS"], Clash.GroupKeys);
        t.Eq("ROW_HEADER", k["ROW_HEADER"], Clash.RowHeader);

        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "intersection_name": return Clash.IntersectionName(a[0], a[1]);
                case "line_intersection": return Clash.LineIntersection(LaneC.D(a[0]), LaneC.D(a[1]));
                case "grid_intersections": return Clash.GridIntersections(LaneC.L(a[0]));
                case "direction_families": return Clash.DirectionFamilies(LaneC.L(a[0]));
                case "grid_zone": return Clash.GridZone(a[0] as Lst, a[1] as Lst);
                case "nearest_intersection": return Clash.NearestIntersection(LaneC.L(a[0]), LaneC.L(a[1]));
                case "locate": return Clash.Locate(LaneC.L(a[0]), a[1] as Lst);
                case "group_key": return Clash.GroupKey(LaneC.D(a[0]), (string)a[1]!);
                case "group_clashes": return Clash.GroupClashes(LaneC.L(a[0]), (string)a[1]!);
                case "clash_rows": return Clash.ClashRows(LaneC.L(a[0]));
                case "to_html":
                    return LaneC.Has(a, 1) ? Clash.ToHtml(LaneC.D(a[0]), (string)a[1]!) : Clash.ToHtml(LaneC.D(a[0]));
                default: throw new InvalidOperationException("no such function " + fn);
            }
        }, "group_key", "group_clashes");

        // locate changes the clashes it is given and returns the same list; typed lists work as well
        var grids = new List<Dict>
        {
            new Dict { ["name"] = "A", ["start"] = new Lst { 0L, 0L }, ["end"] = new Lst { 0L, 1000L } },
            new Dict { ["name"] = "1", ["start"] = new Lst { 0.0, 0.0 }, ["end"] = new Lst { 1000.0, 0.0 } },
        };
        var clashes = new List<Dict> { new Dict { ["point"] = new Lst { 30.0, 40.0, 0.0 } } };
        var same = Clash.Locate(clashes, grids);
        t.Check("locate returns its argument", ReferenceEquals(same, clashes));
        t.Eq("locate in place", new Dict { ["name"] = "A/1", ["distance"] = 50.0 }, clashes[0].Get("nearest_grid"));
        t.Eq("grid_zone typed point", ">A/>1", Clash.GridZone(new List<double> { 30, 40 }, grids));
        t.Eq("row header is not changed by to_html", "Distance", Clash.RowHeader[2]);
    }
}
