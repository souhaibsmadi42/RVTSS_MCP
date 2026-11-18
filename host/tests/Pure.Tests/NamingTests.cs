namespace RvtssHost.Tests;

public static class NamingTests
{
    public static void Run(T t)
    {
        var schemes = (Dict)((Dict)t.Vectors("naming")!)["schemes"]!;
        Dict Scheme(object? key) => (Dict)schemes[(string)key!]!;

        var doc = LaneB.Run(t, "naming", c =>
        {
            switch (c.Fn)
            {
                case "target_scheme": return Naming.TargetScheme(Scheme(c.Arg(0)), c.Str(1)!);
                case "check_field": return Naming.CheckField((Dict)c.Arg(0)!, c.Str(1));
                case "check_name":
                {
                    var ts = (Dict)c.Arg(1)!;
                    if (ts.ContainsKey("scheme"))
                        ts = Naming.TargetScheme(Scheme(ts["scheme"]), (string)ts["target"]!)!;
                    return Naming.CheckName(c.Str(0), ts).Select(e => (object?)new Lst { e.field, e.reason }).ToList();
                }
                case "check_items":
                {
                    var items = LaneB.Pairs(c.Arg(0));
                    var scheme = Scheme(c.Arg(1));
                    var target = c.Str(2)!;
                    if (c.Has(4, "max_examples"))
                        return Naming.CheckItems(items, scheme, target, c.Str(3, "label"), c.Int(4, "max_examples")!.Value);
                    if (c.Has(3, "label"))
                        return Naming.CheckItems(items, scheme, target, c.Str(3, "label"));
                    return Naming.CheckItems(items, scheme, target);
                }
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("TARGETS", doc["targets"], Naming.Targets);

        // typed ids, as the route modules pass them
        var typed = new List<(long, string)> { (1, "bad name"), (2, "ARC_Plan") };
        var found = Naming.CheckItems(typed, Scheme("main"), "views");
        t.Eq("typed check_items ids", new Lst { 1L }, found[0]["element_ids"]);
        t.Check("SchemeError base", new SchemeError("x") is FormatException);
    }
}
