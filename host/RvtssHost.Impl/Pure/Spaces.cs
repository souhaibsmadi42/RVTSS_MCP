namespace RvtssHost.Pure;

/// <summary>Revit-independent helpers for rooms / spaces / areas (RVTSS v2.2).</summary>
public static class Spaces
{
    // Warning texts Revit raises for spatial elements (English UI); used to split
    // "placed with zero area" into not enclosed vs redundant. Localised Revit builds
    // fall back to the generic "not_enclosed_or_redundant".
    public static readonly string[] NotEnclosedMarkers = { "not in a properly enclosed region", "not enclosed" };
    public static readonly string[] RedundantMarkers = { "same enclosed region", "redundant" };

    public static string? ClassifyWarning(string? text)
    {
        var t = (text ?? "").ToLowerInvariant();
        if (RedundantMarkers.Any(m => t.IndexOf(m, StringComparison.Ordinal) >= 0))
            return "redundant";
        if (NotEnclosedMarkers.Any(m => t.IndexOf(m, StringComparison.Ordinal) >= 0))
            return "not_enclosed";
        return null;
    }

    /// <summary>placed | unplaced | not_enclosed | redundant | not_enclosed_or_redundant.</summary>
    public static string SpatialStatus(object? placed, object? area, string? warningKind = null)
    {
        if (!Py.Truthy(placed))
            return "unplaced";
        if (Py.Truthy(area) && PureText.ToFloat(area) > 1e-9)
            return "placed";
        return !string.IsNullOrEmpty(warningKind) ? warningKind! : "not_enclosed_or_redundant";
    }

    private static double NonNegative(object? v) => Math.Max(0.0, Py.Truthy(v) ? PureText.ToFloat(v) : 0.0);

    /// <summary>
    /// Net wall area of one boundary segment: length x height minus openings (width x height).
    ///
    /// Inputs in any consistent unit; openings that do not fit are clamped so the
    /// net area is never negative. Returns (gross, openings_area, net).
    /// </summary>
    public static (double gross, double openingsArea, double net) WallFinish(object? segmentLength, object? height,
        System.Collections.IEnumerable? openings = null)
    {
        var gross = NonNegative(segmentLength) * NonNegative(height);
        var holes = 0.0;
        if (openings != null)
        {
            foreach (var opening in openings)
            {
                var pair = PureText.Iter(opening).ToList();
                if (pair.Count != 2)
                    throw new FormatException(pair.Count < 2
                        ? "need more than " + pair.Count + " values to unpack"
                        : "too many values to unpack");
                holes += NonNegative(pair[0]) * NonNegative(pair[1]);
            }
        }
        holes = Math.Min(holes, gross);
        return (gross, holes, gross - holes);
    }

    /// <summary>Group dict items by key with counts and sums of value_keys (rounded to 3 decimals).</summary>
    public static Dict SummarizeBy(System.Collections.IEnumerable items, string key, IEnumerable<string>? valueKeys = null)
    {
        var keys = valueKeys?.ToList() ?? new List<string> { "area" };
        var result = new Dict();
        // Python dict keys: True == 1 == 1.0 are one key (shown as the first one seen), "1" is another
        var groups = new Dictionary<string, Dict>(StringComparer.Ordinal);
        foreach (var item in items)
        {
            var it = item as Dict ?? throw new FormatException("'" + Py.TypeName(item) + "' object has no attribute 'get'");
            var k = it.Get(key);
            if (k == null || (k is string s && s.Length == 0))
                k = "(none)";
            var identity = k is string text ? "s:" + text
                : PureText.IsNumber(k) ? "n:" + PureText.ToFloat(k).ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                : "o:" + Py.Str(k);
            if (!groups.TryGetValue(identity, out var g))
            {
                var name = Py.Str(k);
                // in JSON a number key and the same text are one key: they share the group
                if (result.Get(name) is not Dict existing)
                    result[name] = existing = new Dict { ["count"] = 0L };
                groups[identity] = g = existing;
            }
            g["count"] = Py.ToInt(g["count"]) + 1;
            foreach (var vk in keys)
            {
                var v = it.Get(vk);
                if (PureText.IsNumber(v))
                    g[vk] = Py.Round(PureText.ToFloat(g.Get(vk, 0.0)) + PureText.ToFloat(v), 3);
            }
        }
        return result;
    }
}
