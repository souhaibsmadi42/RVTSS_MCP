namespace RvtssHost.Tests;

public static class UnitsTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "units", c =>
        {
            switch (c.Fn)
            {
                case "normalize_unit": return Units.NormalizeUnit(c.Str(0));
                case "unit_kind": return Units.UnitKind(c.Str(0));
                case "to_internal":
                {
                    var viaObject = Units.ToInternal(c.Arg(0), c.Str(1));
                    // the typed overload must agree for plain numbers
                    if (c.Arg(0) is double d)
                        t.Check("to_internal typed", Units.ToInternal(d, c.Str(1)) == viaObject);
                    if (c.Arg(0) is long l)
                        t.Check("to_internal typed", Units.ToInternal(l, c.Str(1)) == viaObject);
                    return viaObject;
                }
                case "from_internal":
                {
                    var viaObject = Units.FromInternal(c.Arg(0), c.Str(1), c.Int(2, "ndigits"));
                    if (c.Arg(0) is double d)
                        t.Check("from_internal typed", Units.FromInternal(d, c.Str(1), c.Int(2, "ndigits")) == viaObject);
                    return viaObject;
                }
                case "length_unit_for": return Units.LengthUnitFor(c.Str(0), c.Str(1));
                case "point_from":
                {
                    var (x, y, z) = Units.PointFrom(c.Arg(0), c.Str(1));
                    return new Lst { x, y, z };
                }
                case "point_to":
                    return c.Has(2, "ndigits")
                        ? Units.PointTo((Lst)c.Arg(0)!, c.Str(1), c.Int(2, "ndigits"))
                        : Units.PointTo((Lst)c.Arg(0)!, c.Str(1));
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });

        // tables
        var units = (Dict)doc["units"]!;
        t.Check("UNITS keys", units.Keys.OrderBy(k => k, StringComparer.Ordinal)
            .SequenceEqual(Units.UnitTable.Keys.OrderBy(k => k, StringComparer.Ordinal)));
        foreach (var kv in units)
        {
            var pair = (Lst)kv.Value!;
            if (!Units.UnitTable.TryGetValue(kv.Key, out var entry))
                continue;
            t.Eq("UNITS " + kv.Key, pair, new Lst { entry.kind, entry.factor });
        }
        t.Eq("ALIASES", doc["aliases"], Units.Aliases.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));

        // IronPython 2 rounding (halves away from zero), which CPython 3 vectors cannot show
        t.Eq("round half 0.5", 1.0, Units.FromInternal(0.5, null, 0));
        t.Eq("round half 2.5", 3.0, Units.FromInternal(2.5, null, 0));
        t.Eq("round half -2.5", -3.0, Units.FromInternal(-2.5, null, 0));
        t.Eq("round half 0.125", 0.13, Units.FromInternal(0.125, null, 2));
        // overloads other code relies on
        t.Eq("tuple point_to", new Lst { 304.8, 609.6, 0.0 }, Units.PointTo((1.0, 2.0, 0.0), "mm"));
        t.Eq("array point_to", new Lst { 1.0, 2.0 }, Units.PointTo(new[] { 1.0, 2.0 }, null, 1));
        t.Eq("int from_internal", 304.8, Units.FromInternal(1, "mm"));
        double typed = Units.FromInternal(1.0, "mm", 1);
        t.Eq("typed from_internal", 304.8, typed);
        t.Throws("UnitError is a FormatException", () => Units.ToInternal(1.0, "furlong"), "UnitError");
        t.Check("UnitError base", new UnitError("x") is FormatException);
    }
}
