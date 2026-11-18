namespace RvtssHost.Pure;

/// <summary>Python: class CatalogError(ValueError).</summary>
public class CatalogError : FormatException
{
    public CatalogError(string message) : base(message) { }
}

/// <summary>
/// Revit type catalog (.txt next to the .rfa) reader/writer.
///
/// Format:
///     ,Width##LENGTH##MILLIMETERS,Height##LENGTH##MILLIMETERS,Fire Rating##OTHER##
///     D1 900x2100,900,2100,60 min
/// </summary>
public static class Catalog
{
    /// <summary>catalog unit token -> rvtss unit</summary>
    public static readonly Dictionary<string, string> CatalogUnits = new()
    {
        ["MILLIMETERS"] = "mm", ["CENTIMETERS"] = "cm", ["METERS"] = "m", ["FEET"] = "ft", ["INCHES"] = "in",
        ["SQUARE_METERS"] = "m2", ["SQUARE_FEET"] = "ft2", ["CUBIC_METERS"] = "m3", ["CUBIC_FEET"] = "ft3",
        ["DEGREES"] = "deg", ["DECIMAL_DEGREES"] = "deg", ["RADIANS"] = "rad",
    };

    public static readonly Dictionary<string, string> RvtssToCatalog =
        CatalogUnits.Where(kv => kv.Key != "DECIMAL_DEGREES").ToDictionary(kv => kv.Value, kv => kv.Key);

    /// <summary>rvtss spec name -> catalog type token</summary>
    public static readonly Dictionary<string, string> SpecToCatalog = new()
    {
        ["length"] = "LENGTH", ["area"] = "AREA", ["volume"] = "VOLUME", ["angle"] = "ANGLE",
        ["number"] = "OTHER", ["integer"] = "OTHER", ["text"] = "OTHER", ["yesno"] = "OTHER",
        ["material"] = "OTHER", ["url"] = "OTHER",
    };

    public static Dict ParseHeaderCell(string cell)
    {
        var parts = cell.Split(new[] { "##" }, StringSplitOptions.None);
        var name = parts[0].Trim();
        var kind = parts.Length > 1 ? parts[1].Trim().ToUpperInvariant() : "OTHER";
        var unitTok = parts.Length > 2 ? parts[2].Trim().ToUpperInvariant() : "";
        var unit = unitTok.Length > 0 && CatalogUnits.TryGetValue(unitTok, out var u) ? u : null;
        return new Dict { ["name"] = name, ["kind"] = kind, ["unit"] = unit, ["unit_token"] = unitTok };
    }

    public static Dict Parse(string text)
    {
        var rows = Csvutil.Reader(text).Where(r => r.Any(c => c.Trim().Length > 0)).ToList();
        if (rows.Count == 0)
            throw new CatalogError("Type catalog is empty");
        var header = rows[0];
        if (header.Count > 0 && header[0].Trim().Length > 0)
            throw new CatalogError("Type catalog header must start with an empty cell (',Param##TYPE##UNIT,...')");
        var columns = header.Skip(1).Select(ParseHeaderCell).ToList();
        var types = new List<Dict>();
        for (var k = 1; k < rows.Count; k++)
        {
            var r = rows[k];
            var line = k + 1;
            if (r.Count - 1 > columns.Count)
                throw new CatalogError("Line " + line + " has more values than header columns");
            var name = r[0].Trim();
            if (name.Length == 0)
                throw new CatalogError("Line " + line + " has no type name");
            var values = new Dict();
            for (var i = 0; i < columns.Count && i + 1 < r.Count; i++)
            {
                var val = r[i + 1];
                if (val.Trim().Length == 0)
                    continue;
                var col = columns[i];
                values[Py.Str(col["name"])] = new Dict
                {
                    ["value"] = val.Trim(), ["unit"] = col["unit"], ["kind"] = col["kind"],
                };
            }
            types.Add(new Dict { ["name"] = name, ["values"] = values });
        }
        return new Dict { ["columns"] = columns, ["types"] = types };
    }

    private static Dict Obj(object? v) =>
        v as Dict ?? throw new FormatException("'" + Py.TypeName(v) + "' object has no attribute 'get'");

    /// <summary>columns: [{"name", "spec", "unit"}]; types: [{"name", "values": {param: value}}]</summary>
    public static string Write(System.Collections.IEnumerable columns, System.Collections.IEnumerable types)
    {
        var cols = columns.Cast<object?>().Select(Obj).ToList();
        var sb = new StringBuilder();
        var hdr = new List<string> { "" };
        foreach (var c in cols)
        {
            var spec = c.Get("spec");
            var kind = Py.Truthy(spec) && spec is string sp && SpecToCatalog.TryGetValue(sp, out var k) ? k : "OTHER";
            var unitValue = c.Get("unit");
            var unit = kind != "OTHER" && Py.Truthy(unitValue) && unitValue is string un
                                       && RvtssToCatalog.TryGetValue(un, out var tok) ? tok : "";
            hdr.Add(Py.Str(c["name"]) + "##" + kind + "##" + unit);
        }
        sb.Append(Csvutil.WriteRow(hdr, "\n"));
        foreach (var item in types)
        {
            var t = Obj(item);
            var row = new List<string> { CsvText(t["name"]) };
            var values = Obj(t["values"]);
            foreach (var c in cols)
            {
                var v = values.Get(Py.Str(c["name"]));
                row.Add(v == null ? "" : Py.Str(v));
            }
            sb.Append(Csvutil.WriteRow(row, "\n"));
        }
        return sb.ToString();
    }

    /// <summary>A cell as csv.writer writes it: None is an empty cell, anything else its str().</summary>
    private static string CsvText(object? v) => v == null ? "" : Py.Str(v);
}
