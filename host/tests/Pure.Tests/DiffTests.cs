namespace RvtssHost.Tests;

public static class DiffTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "diff");
        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "diff_snapshots":
                {
                    Dict o = LaneC.D(a[0]), n = LaneC.D(a[1]);
                    if (!LaneC.Has(a, 2)) return Diff.DiffSnapshots(o, n);
                    if (!LaneC.Has(a, 3)) return Diff.DiffSnapshots(o, n, Py.ToFloat(a[2]));
                    return Diff.DiffSnapshots(o, n, Py.ToFloat(a[2]), Py.ToInt(a[3]));
                }
                case "match_by_location":
                {
                    Lst s = LaneC.L(a[0]), g = LaneC.L(a[1]);
                    var tol = Py.ToFloat(a[2]);
                    if (!LaneC.Has(a, 3)) return Diff.MatchByLocation(s, g, tol);
                    if (!LaneC.Has(a, 4)) return Diff.MatchByLocation(s, g, tol, LaneC.L(a[3]));
                    return Diff.MatchByLocation(s, g, tol, LaneC.L(a[3]), Py.ToInt(a[4]));
                }
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });

        // typed inputs, as a route module would pass them
        var src = new List<Dict> { new Dict { ["id"] = 1L, ["category"] = "Doors", ["loc"] = new List<double> { 0, 0, 0 } } };
        var tgt = new List<Dict> { new Dict { ["id"] = 2L, ["category"] = "doors", ["loc"] = new List<double> { 3, 4, 0 } } };
        var r = Diff.MatchByLocation(src, tgt, 10, new List<string> { "category" });
        t.Eq("typed lists", new Lst { new Dict { ["source_id"] = 1L, ["target_id"] = 2L, ["category"] = "Doors", ["distance"] = 5.0 } },
            r["matched_sample"]);
    }
}
