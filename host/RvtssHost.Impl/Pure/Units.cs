namespace RvtssHost.Pure;

/// <summary>Python: class UnitError(ValueError).</summary>
public class UnitError : FormatException
{
    public UnitError(string message) : base(message) { }
}

/// <summary>
/// Unit conversion between user units and Revit internal units.
///
/// Revit stores lengths in decimal feet, areas in square feet, volumes in cubic
/// feet and angles in radians. Conversions here are exact (1 ft = 304.8 mm) so
/// they do not depend on the Revit API and can be unit-tested offline.
/// </summary>
public static class Units
{
    private static readonly (string unit, double factor)[] FtPer =
    {
        ("mm", 1.0 / 304.8),
        ("cm", 1.0 / 30.48),
        ("m", 1.0 / 0.3048),
        ("ft", 1.0),
        ("in", 1.0 / 12.0),
    };

    /// <summary>unit -> (kind, factor to internal). Python name: UNITS (a member cannot be named like its class).</summary>
    public static readonly Dictionary<string, (string kind, double factor)> UnitTable = BuildUnits();

    private static Dictionary<string, (string kind, double factor)> BuildUnits()
    {
        var units = new Dictionary<string, (string kind, double factor)>();
        foreach (var (u, f) in FtPer)
        {
            units[u] = ("length", f);
            units[u + "2"] = ("area", Math.Pow(f, 2));
            units[u + "3"] = ("volume", Math.Pow(f, 3));
        }
        units["deg"] = ("angle", Math.PI / 180.0);
        units["rad"] = ("angle", 1.0);
        units["internal"] = ("any", 1.0);
        return units;
    }

    public static readonly Dictionary<string, string> Aliases = new()
    {
        ["millimeter"] = "mm", ["millimeters"] = "mm", ["millimetre"] = "mm", ["millimetres"] = "mm",
        ["centimeter"] = "cm", ["centimeters"] = "cm",
        ["meter"] = "m", ["meters"] = "m", ["metre"] = "m", ["metres"] = "m",
        ["feet"] = "ft", ["foot"] = "ft", ["'"] = "ft",
        ["inch"] = "in", ["inches"] = "in", ["\""] = "in",
        ["degree"] = "deg", ["degrees"] = "deg", ["°"] = "deg",
        ["radian"] = "rad", ["radians"] = "rad",
        ["sqm"] = "m2", ["m^2"] = "m2", ["sqft"] = "ft2", ["ft^2"] = "ft2", ["mm^2"] = "mm2",
        ["m^3"] = "m3", ["ft^3"] = "ft3", ["cum"] = "m3",
    };

    [return: System.Diagnostics.CodeAnalysis.NotNullIfNotNull("unit")]
    public static string? NormalizeUnit(string? unit)
    {
        if (unit == null)
            return null;
        var u = unit.Trim().ToLowerInvariant();
        if (Aliases.TryGetValue(u, out var alias))
            u = alias;
        if (!UnitTable.ContainsKey(u))
            throw new UnitError("Unknown unit '" + unit + "'. Supported: "
                                + string.Join(", ", UnitTable.Keys.OrderBy(x => x, StringComparer.Ordinal)));
        return u;
    }

    public static string UnitKind(string? unit) => Entry(unit).kind;

    /// <summary>UNITS[normalize_unit(unit)]; a None unit is a KeyError in Python.</summary>
    private static (string kind, double factor) Entry(string? unit)
    {
        var u = NormalizeUnit(unit);
        if (u == null)
            throw new KeyNotFoundException("None");
        return UnitTable[u];
    }

    /// <summary>Convert value expressed in `unit` to Revit internal units.</summary>
    public static double ToInternal(double value, string? unit)
    {
        if (unit == null)
            return value;
        return value * Entry(unit).factor;
    }

    /// <summary>to_internal for a request value (a number or a numeric string, as Python float() takes).</summary>
    public static double ToInternal(object? value, string? unit) => ToInternal(PureText.ToFloat(value), unit);

    /// <summary>Convert a Revit internal value to `unit`.</summary>
    public static double FromInternal(double value, string? unit, int? ndigits = null)
    {
        var result = unit == null ? value : value / Entry(unit).factor;
        if (ndigits != null)
            result = Py.Round(result, ndigits.Value);
        return result;
    }

    /// <summary>from_internal for a value that may be None (stays None) or a request value.</summary>
    public static double? FromInternal(object? value, string? unit, int? ndigits = null)
    {
        if (value == null)
            return null;
        return FromInternal(PureText.ToFloat(value), unit, ndigits);
    }

    /// <summary>
    /// Adapt a unit to a quantity kind: mm -> mm2 for area, m2 stays m2, any -> deg for angles.
    ///
    /// A unit that already matches the kind is returned unchanged; an area/volume
    /// unit is reduced to its length base first (m2 -> m3 for volumes). An angle
    /// unit given for a dimensional kind falls back to millimetres.
    /// </summary>
    public static string? LengthUnitFor(string? kind, string? unit)
    {
        string u;
        if (kind == "angle")
        {
            u = !string.IsNullOrEmpty(unit) ? NormalizeUnit(unit)! : "deg";
            return UnitTable[u].kind == "angle" ? u : "deg";
        }
        if (kind != "length" && kind != "area" && kind != "volume")
            return null;
        u = !string.IsNullOrEmpty(unit) ? NormalizeUnit(unit)! : "mm";
        var uk = UnitTable[u].kind;
        if (uk == kind || uk == "any")
            return u;
        string baseUnit;
        if (uk == "angle")
            baseUnit = "mm";
        else if (uk == "area" || uk == "volume")
            baseUnit = u.Substring(0, u.Length - 1);
        else
            baseUnit = u;
        return kind == "length" ? baseUnit : kind == "area" ? baseUnit + "2" : baseUnit + "3";
    }

    /// <summary>[x, y, z] in `unit` -> tuple of internal feet. Accepts 2D (z=0).</summary>
    public static (double x, double y, double z) PointFrom(object? values, string? unit)
    {
        var vals = PureText.Iter(values).ToList();
        if (vals.Count == 2)
            vals.Add(0.0);
        if (vals.Count != 3)
            throw new UnitError("A point needs 2 or 3 coordinates, got " + vals.Count);
        return (ToInternal(vals[0], unit), ToInternal(vals[1], unit), ToInternal(vals[2], unit));
    }

    public static Lst PointTo(System.Collections.IEnumerable xyz, string? unit, int? ndigits = 3)
    {
        var result = new Lst();
        foreach (var c in xyz)
            result.Add(FromInternal(c, unit, ndigits));
        return result;
    }

    public static Lst PointTo((double x, double y, double z) xyz, string? unit, int? ndigits = 3) =>
        PointTo(new[] { xyz.x, xyz.y, xyz.z }, unit, ndigits);
}
