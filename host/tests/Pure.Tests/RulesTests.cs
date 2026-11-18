namespace RvtssHost.Tests;

public static class RulesTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "rules", c =>
        {
            switch (c.Fn)
            {
                case "severity_rank": return Rules.SeverityRank(c.Arg(0));
                case "finding":
                {
                    // args: the positional arguments, then the **extra keyword arguments
                    var a = new LaneB.Case { Args = (Lst)c.Arg(0)! };
                    var extra = (Dict)c.Arg(1)!;
                    var ids = a.Arg(3) as Lst;
                    return a.Has(6)
                        ? Rules.Finding(a.Str(0)!, a.Arg(1), a.Str(2)!, ids, a.Str(4), a.Long(5), a.Int(6)!.Value,
                            extra.Count > 0 ? extra : null)
                        : Rules.Finding(a.Str(0)!, a.Arg(1), a.Str(2)!, ids, a.Str(4), a.Long(5),
                            extra: extra.Count > 0 ? extra : null);
                }
                case "summarize": return Rules.Summarize((Lst)c.Arg(0)!);
                case "sort_findings": return Rules.SortFindings((Lst)c.Arg(0)!);
                case "check_names":
                {
                    var found = Rules.CheckNames(LaneB.Pairs(c.Arg(0)), (Dict)c.Arg(1)!, c.Str(2)!, c.Str(3)!);
                    // an invalid pattern is reported with the regex engine's own text, which differs from Python's:
                    // compare up to that text
                    const string prefix = "Invalid naming pattern for sheets: ";
                    if (found.Count == 1 && found[0]["message"] is string m && m.StartsWith(prefix) && m.Length > prefix.Length
                        && c.Raw.Get("out") is Lst { Count: 1 } want && ((Dict)want[0]!)["message"] is string pm
                        && pm.StartsWith(prefix))
                        found[0]["message"] = pm;
                    return found;
                }
                case "check_duplicate_names":
                    return Rules.CheckDuplicateNames(LaneB.Pairs(c.Arg(0)), c.Str(1)!, c.Str(2)!);
                case "similar_names":
                {
                    var names = ((Lst)c.Arg(0)!).Select(n => (string?)n).ToList();
                    return LaneB.Tuples(c.Has(1, "threshold")
                        ? Rules.SimilarNames(names, Convert.ToDouble(c.Arg(1, "threshold")))
                        : Rules.SimilarNames(names));
                }
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("SEVERITIES", doc["severities"], Rules.Severities);

        // typed lists, as the route modules hold them
        var findings = new List<Dict>
        {
            Rules.Finding("a", "info", "m", new List<long> { 1 }),
            Rules.Finding("b", "error", "m", new long[] { 1, 2 }, recommendation: "r", extra: new Dict { ["examples"] = new Lst { "x" } }),
        };
        List<Dict> sorted = Rules.SortFindings(findings);
        t.Eq("typed sort", "b", sorted[0]["check"]);
        t.Eq("typed summarize", "error", Rules.Summarize(findings)["worst_severity"]);
        t.Eq("finding key order", "check,severity,message,count,element_ids,recommendation,examples",
            string.Join(",", sorted[0].Keys));
        var named = Rules.CheckNames(new List<(long, string)> { (7, "bad") }, new Dict { ["pattern"] = "^A" }, "naming", "views");
        t.Eq("typed check_names", new Lst { 7L }, named[0]["element_ids"]);
        var broken = Rules.CheckNames(new[] { (0, "x") }, new Dict { ["pattern"] = "(" }, "naming", "v");
        t.Eq("invalid pattern finding", "error", broken[0]["severity"]);
        t.Check("invalid pattern text", ((string)broken[0]["message"]!).StartsWith("Invalid naming pattern for v: "));
    }
}
