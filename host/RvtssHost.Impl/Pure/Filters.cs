using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>Python: class FilterError(ValueError).</summary>
public class FilterError : FormatException
{
    public FilterError(string message) : base(message) { }
}

/// <summary>Value matching for parameter filters and free-text search.</summary>
public static class Filters
{
    public static readonly string[] Ops =
    {
        "eq", "ne", "contains", "not_contains", "startswith", "endswith", "regex",
        "gt", "ge", "lt", "le", "empty", "not_empty", "in", "exists", "missing",
    };

    public static readonly string[] NumericOps = { "gt", "ge", "lt", "le" };

    internal static double? Num(object? v)
    {
        if (v is bool b)
            return b ? 1.0 : 0.0;
        if (Py.IsNum(v))
            return PureText.ToFloat(v);
        return PureText.ParseFloat(Py.Str(v));
    }

    internal static bool IsEmpty(object? v) => v == null || (v is string s && s.Trim().Length == 0);

    public static void ValidateFilter(object? f)
    {
        if (f is not Dict d)
            throw new FilterError("Each parameter filter must be an object");
        if (!Py.Truthy(d.Get("name")))
            throw new FilterError("Parameter filter is missing 'name'");
        var opValue = d.Get("op", "eq");
        if (opValue is not string op || !Ops.Contains(op))
            throw new FilterError("Unknown filter op '" + Py.Str(opValue) + "'. Use one of: " + string.Join(", ", Ops));
        if (op == "empty" || op == "not_empty" || op == "exists" || op == "missing")
            return;
        if (!d.ContainsKey("value"))
            throw new FilterError("Filter on '" + Py.Str(d["name"]) + "' with op '" + op + "' needs a 'value'");
        var value = d["value"];
        if (NumericOps.Contains(op) && Num(value) == null)
            throw new FilterError("Filter op '" + op + "' needs a numeric value");
        if (op == "regex")
        {
            var pattern = PureText.Pattern(value);
            try
            {
                PureText.Re(pattern);
            }
            catch (ArgumentException ex)
            {
                throw new FilterError("Invalid regex '" + pattern + "': " + ex.Message);
            }
        }
        if (op == "in" && (value is string || value is not System.Collections.IList))
            throw new FilterError("Filter op 'in' needs a list value");
    }

    /// <summary>
    /// Evaluate one filter.
    ///
    /// raw: comparable value (number for numeric params, string otherwise),
    ///      already converted to the filter's unit by the caller.
    /// display: the user-facing string (AsValueString) or None.
    /// exists: whether the parameter exists on the element.
    /// </summary>
    public static bool Match(object? op, object? expected, object? raw, object? display, bool exists = true,
        bool caseSensitive = false)
    {
        var o = op as string;
        if (o == "exists")
            return exists;
        if (o == "missing")
            return !exists;
        if (!exists)
            return o == "ne" || o == "not_contains" || o == "empty";
        if (o == "empty")
            return IsEmpty(raw) && IsEmpty(display);
        if (o == "not_empty")
            return !(IsEmpty(raw) && IsEmpty(display));

        if (o != null && NumericOps.Contains(o))
        {
            var a = Num(raw);
            var b = Num(expected);
            if (a == null || b == null)
                return false;
            return o == "gt" ? a > b : o == "ge" ? a >= b : o == "lt" ? a < b : a <= b;
        }

        // numeric equality with tolerance when both sides are numbers
        if ((o == "eq" || o == "ne") && raw is not string && Num(expected) is double ne && Num(raw) is double nr)
        {
            var same = Math.Abs(nr - ne) <= 1e-6 * Math.Max(1.0, Math.Abs(ne));
            return o == "eq" ? same : !same;
        }

        var candidates = new List<string>();
        if (raw != null)
            candidates.Add(Py.Str(raw));
        if (display != null)
            candidates.Add(Py.Str(display));
        var texts = caseSensitive ? candidates : candidates.Select(t => t.ToLowerInvariant()).ToList();

        string Norm(object? x)
        {
            var s = Py.Str(x);
            return caseSensitive ? s : s.ToLowerInvariant();
        }

        switch (o)
        {
            case "eq":
                return texts.Contains(Norm(expected));
            case "ne":
                return !texts.Contains(Norm(expected));
            case "contains":
            {
                var e = Norm(expected);
                return texts.Any(t => t.IndexOf(e, StringComparison.Ordinal) >= 0);
            }
            case "not_contains":
            {
                var e = Norm(expected);
                return !texts.Any(t => t.IndexOf(e, StringComparison.Ordinal) >= 0);
            }
            case "startswith":
            {
                var e = Norm(expected);
                return texts.Any(t => t.StartsWith(e, StringComparison.Ordinal));
            }
            case "endswith":
            {
                var e = Norm(expected);
                return texts.Any(t => t.EndsWith(e, StringComparison.Ordinal));
            }
            case "in":
            {
                var wanted = new HashSet<string>(PureText.Iter(expected).Select(Norm), StringComparer.Ordinal);
                return texts.Any(wanted.Contains);
            }
            case "regex":
            {
                var rx = PureText.Re(PureText.Pattern(expected), ignoreCase: !caseSensitive);
                return candidates.Any(c => rx.IsMatch(c));
            }
        }
        throw new FilterError("Unknown op " + Py.Str(op));
    }

    /// <summary>All whitespace-separated query tokens must appear in the combined text.</summary>
    public static bool TextMatch(object? query, System.Collections.IEnumerable haystackParts)
    {
        if (!Py.Truthy(query))
            return true;
        if (query is not string q)
            throw new FormatException("'" + Py.TypeName(query) + "' object has no attribute 'lower'");
        var hay = string.Join(" ", haystackParts.Cast<object?>().Where(Py.Truthy).Select(Py.Str)).ToLowerInvariant();
        var tokens = q.ToLowerInvariant().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        return tokens.All(tok => hay.IndexOf(tok, StringComparison.Ordinal) >= 0);
    }

    /// <summary>Returns (page, {total, offset, limit, next_offset}).</summary>
    public static (List<T> page, Dict meta) Paginate<T>(IEnumerable<T> items, long? offset = 0, long? limit = 100)
    {
        var all = items as IList<T> ?? items.ToList();
        long total = all.Count;
        var off = Math.Max(0, offset ?? 0);
        var lim = Math.Max(1, limit == null || limit == 0 ? 100 : limit.Value);
        var page = new List<T>();
        for (var i = off; i < total && i - off < lim; i++)
            page.Add(all[(int)i]);
        // off + lim cannot overflow in practice; keep the Python comparison
        long? next = off + lim < total ? off + lim : null;
        return (page, new Dict { ["total"] = total, ["offset"] = off, ["limit"] = lim, ["next_offset"] = next });
    }
}
