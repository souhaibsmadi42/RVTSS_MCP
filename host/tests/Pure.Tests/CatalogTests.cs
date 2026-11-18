namespace RvtssHost.Tests;

public static class CatalogTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "catalog", c =>
        {
            switch (c.Fn)
            {
                case "parse_header_cell": return Catalog.ParseHeaderCell(c.Str(0)!);
                case "parse": return Catalog.Parse(c.Str(0)!);
                case "write": return Catalog.Write((Lst)c.Arg(0)!, (Lst)c.Arg(1)!);
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("CATALOG_UNITS", doc["catalog_units"], Catalog.CatalogUnits.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));
        t.Eq("RVTSS_TO_CATALOG", doc["rvtss_to_catalog"], Catalog.RvtssToCatalog.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));
        t.Eq("SPEC_TO_CATALOG", doc["spec_to_catalog"], Catalog.SpecToCatalog.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));

        // typed lists
        var cols = new List<Dict> { new() { ["name"] = "Width", ["spec"] = "length", ["unit"] = "mm" } };
        var types = new List<Dict> { new() { ["name"] = "A", ["values"] = new Dict { ["Width"] = 900L } } };
        t.Eq("typed write", ",Width##LENGTH##MILLIMETERS\nA,900\n", Catalog.Write(cols, types));
        // Python 2 csv (IronPython) quotes for the characters of the line terminator only, so a lone \r is not
        // quoted; CPython 3.13 quotes it, which is why this is not a vector
        t.Eq("write \\r", ",N##OTHER##\nA,x\ry\n", Catalog.Write(
            new Lst { new Dict { ["name"] = "N" } },
            new Lst { new Dict { ["name"] = "A", ["values"] = new Dict { ["N"] = "x\ry" } } }));
        t.Check("CatalogError base", new CatalogError("x") is FormatException);
    }
}
