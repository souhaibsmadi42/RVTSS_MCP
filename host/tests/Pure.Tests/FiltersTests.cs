namespace RvtssHost.Tests;

public static class FiltersTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "filters", c =>
        {
            switch (c.Fn)
            {
                case "_num":
                {
                    var n = Filters.Num(c.Arg(0));
                    // the generator writes inf / nan as their Python repr
                    if (n is double d && (double.IsNaN(d) || double.IsInfinity(d)))
                        return double.IsNaN(d) ? "nan" : d > 0 ? "inf" : "-inf";
                    return n;
                }
                case "_is_empty": return Filters.IsEmpty(c.Arg(0));
                case "validate_filter":
                    Filters.ValidateFilter(c.Arg(0));
                    return null;
                case "match":
                    return Filters.Match(c.Arg(0), c.Arg(1), c.Arg(2), c.Arg(3), c.Bool(4, "exists", true),
                        c.Bool(5, "case_sensitive"));
                case "text_match": return Filters.TextMatch(c.Arg(0), (Lst)c.Arg(1)!);
                case "paginate":
                {
                    var items = (Lst)c.Arg(0)!;
                    var (page, meta) = c.Has(2, "limit") && c.Has(1, "offset")
                        ? Filters.Paginate(items, c.Long(1, "offset"), c.Long(2, "limit"))
                        : c.Has(1, "offset") ? Filters.Paginate(items, c.Long(1, "offset"))
                        : c.Has(2, "limit") ? Filters.Paginate(items, limit: c.Long(2, "limit"))
                        : Filters.Paginate(items);
                    return new Lst { page, meta };
                }
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("OPS", doc["ops"], Filters.Ops);
        t.Eq("NUMERIC_OPS", doc["numeric_ops"], Filters.NumericOps);

        // typed callers
        var (typedPage, typedMeta) = Filters.Paginate(new List<Dict> { new() { ["a"] = 1L }, new() { ["a"] = 2L } }, 1, 5);
        t.Eq("typed paginate", new Lst { new Dict { ["a"] = 2L } }, typedPage);
        t.Eq("typed paginate meta", new Dict { ["total"] = 2L, ["offset"] = 1L, ["limit"] = 5L, ["next_offset"] = null }, typedMeta);
        t.Check("text_match string[]", Filters.TextMatch("fire door", new[] { "Doors", "Fire 60" }));
        t.Check("FilterError base", new FilterError("x") is FormatException);
    }
}
