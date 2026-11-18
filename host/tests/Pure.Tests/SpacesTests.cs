namespace RvtssHost.Tests;

public static class SpacesTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "spaces", c =>
        {
            switch (c.Fn)
            {
                case "classify_warning": return RvtssHost.Pure.Spaces.ClassifyWarning(c.Str(0));
                case "spatial_status":
                    return RvtssHost.Pure.Spaces.SpatialStatus(c.Arg(0), c.Arg(1), c.Str(2, "warning_kind"));
                case "wall_finish":
                {
                    var (gross, holes, net) = RvtssHost.Pure.Spaces.WallFinish(c.Arg(0), c.Arg(1), c.Arg(2, "openings") as Lst);
                    return new Lst { gross, holes, net };
                }
                case "summarize_by":
                {
                    var items = (Lst)c.Arg(0)!;
                    var key = c.Str(1)!;
                    return c.Has(2, "value_keys")
                        ? RvtssHost.Pure.Spaces.SummarizeBy(items, key, ((Lst)c.Arg(2, "value_keys")!).Select(k => (string)k!).ToList())
                        : RvtssHost.Pure.Spaces.SummarizeBy(items, key);
                }
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("NOT_ENCLOSED_MARKERS", doc["not_enclosed_markers"], RvtssHost.Pure.Spaces.NotEnclosedMarkers);
        t.Eq("REDUNDANT_MARKERS", doc["redundant_markers"], RvtssHost.Pure.Spaces.RedundantMarkers);

        // typed callers: bool / double arguments and tuple openings
        t.Eq("typed status", "placed", RvtssHost.Pure.Spaces.SpatialStatus(true, 12.5));
        var (g, h, n) = RvtssHost.Pure.Spaces.WallFinish(5.0, 3.0, new[] { (1.0, 2.0) });
        t.Eq("typed wall_finish", new Lst { 15.0, 2.0, 13.0 }, new Lst { g, h, n });
        var grouped = RvtssHost.Pure.Spaces.SummarizeBy(
            new List<Dict> { new() { ["level"] = "L1", ["area"] = 10.0 }, new() { ["level"] = "L1", ["area"] = 5.5 } }, "level");
        t.Eq("typed summarize_by", new Dict { ["L1"] = new Dict { ["count"] = 2L, ["area"] = 15.5 } }, grouped);
    }
}
