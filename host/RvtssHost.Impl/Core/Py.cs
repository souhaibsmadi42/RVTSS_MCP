using System.Globalization;
using System.Reflection;
using System.Text.Json;

namespace RvtssHost;

/// <summary>
/// Small helpers that keep ported code close to the Python it came from.
/// Request and response data are plain CLR values: Dict, Lst, string, long, double, bool, null.
/// </summary>
public static class Py
{
    // ------------------------------------------------------------------ JSON
    public static object? FromJson(JsonElement e)
    {
        switch (e.ValueKind)
        {
            case JsonValueKind.Object:
                var d = new Dict();
                foreach (var p in e.EnumerateObject())
                    d[p.Name] = FromJson(p.Value);
                return d;
            case JsonValueKind.Array:
                var l = new Lst();
                foreach (var v in e.EnumerateArray())
                    l.Add(FromJson(v));
                return l;
            case JsonValueKind.String:
                return e.GetString();
            case JsonValueKind.Number:
                return e.TryGetInt64(out var i) ? (object)i : e.GetDouble();
            case JsonValueKind.True:
                return true;
            case JsonValueKind.False:
                return false;
            default:
                return null;
        }
    }

    /// <summary>json.loads: text to Dict / Lst / scalars. Throws JsonException on bad input.</summary>
    public static object? JsonLoads(string text)
    {
        using var doc = JsonDocument.Parse(text);
        return FromJson(doc.RootElement);
    }

    private static readonly JsonSerializerOptions JsonOut = new()
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    private static readonly JsonSerializerOptions JsonOutIndented = new()
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = true,
    };

    /// <summary>json.dumps of a value (cleaned first, see Clean).</summary>
    public static string JsonDumps(object? value, bool indent = false) =>
        JsonSerializer.Serialize(Clean(value), indent ? JsonOutIndented : JsonOut);

    public static byte[] JsonBytes(object? value) => JsonSerializer.SerializeToUtf8Bytes(Clean(value), JsonOut);

    /// <summary>Set by Core: turns a Revit value (ElementId) into its JSON scalar, or returns null.
    /// Keeps this file free of Revit types so the pure logic can be tested outside Revit.</summary>
    public static Func<object, object?>? ForeignScalar;

    /// <summary>Make a value JSON-serialisable: Dict / Lst / scalars only, no .NET objects, finite floats.</summary>
    public static object? Clean(object? value)
    {
        switch (value)
        {
            case null:
            case bool:
            case string:
            case long:
                return value;
            case int i: return (long)i;
            case short s: return (long)s;
            case byte b: return (long)b;
            case uint u: return (long)u;
            case double d: return double.IsNaN(d) || double.IsInfinity(d) ? null : d;
            case float f: return float.IsNaN(f) || float.IsInfinity(f) ? null : (double)f;
            case decimal m: return (double)m;
            case Enum e: return e.ToString();
            case System.Collections.IDictionary map:
                var d2 = new Dict();
                foreach (System.Collections.DictionaryEntry kv in map)
                    d2[Str(kv.Key)] = Clean(kv.Value);
                return d2;
            case System.Collections.IEnumerable seq:
                var l = new Lst();
                foreach (var item in seq)
                    l.Add(Clean(item));
                return l;
            case System.Runtime.CompilerServices.ITuple tuple:
                var t = new Lst();
                for (var k = 0; k < tuple.Length; k++)
                    t.Add(Clean(tuple[k]));
                return t;
            default:
                return ForeignScalar?.Invoke(value) ?? Str(value);
        }
    }

    // ------------------------------------------------------------------ dict
    /// <summary>dict.get(key, default)</summary>
    public static object? Get(this Dict d, string key, object? def = null) => d.TryGetValue(key, out var v) ? v : def;

    /// <summary>dict.setdefault(key, default)</summary>
    public static object? SetDefault(this Dict d, string key, object? def)
    {
        if (d.TryGetValue(key, out var v))
            return v;
        d[key] = def;
        return def;
    }

    /// <summary>dict.update(other); other may be null.</summary>
    public static Dict Update(this Dict d, Dict? other)
    {
        if (other != null)
            foreach (var kv in other)
                d[kv.Key] = kv.Value;
        return d;
    }

    /// <summary>dict.pop(key, default)</summary>
    public static object? Pop(this Dict d, string key, object? def = null)
    {
        if (!d.TryGetValue(key, out var v))
            return def;
        d.Remove(key);
        return v;
    }

    public static void Deconstruct<TKey, TValue>(this KeyValuePair<TKey, TValue> kv, out TKey key, out TValue value)
    {
        key = kv.Key;
        value = kv.Value;
    }

    public static Dict? AsDict(object? v) => v as Dict;

    public static Lst? AsList(object? v) => v as Lst;

    /// <summary>A request value as a list: a list stays a list, a scalar becomes [scalar], null becomes [].</summary>
    public static Lst ListOf(object? v) => v == null ? new Lst() : v is Lst l ? l : new Lst { v };

    // ----------------------------------------------------------------- types
    public static bool IsStr(object? v) => v is string;

    /// <summary>isinstance(v, int) (bool is not an int here).</summary>
    public static bool IsInt(object? v) => v is long || v is int || v is short || v is byte;

    public static bool IsNum(object? v) => IsInt(v) || v is double || v is float || v is decimal;

    /// <summary>Python truthiness.</summary>
    public static bool Truthy(object? v) => v switch
    {
        null => false,
        bool b => b,
        string s => s.Length > 0,
        long l => l != 0,
        int i => i != 0,
        double d => d != 0.0,
        System.Collections.ICollection c => c.Count > 0,
        _ => true,
    };

    /// <summary>int(v): numbers and numeric strings. Throws FormatException (Python ValueError / TypeError).</summary>
    public static long ToInt(object? v)
    {
        switch (v)
        {
            case long l: return l;
            case int i: return i;
            case bool b: return b ? 1 : 0;
            case double d:
                if (double.IsNaN(d) || double.IsInfinity(d)) throw new FormatException("cannot convert float to integer");
                return (long)Math.Truncate(d);
            case string s:
                if (long.TryParse(s.Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var r)) return r;
                throw new FormatException("invalid literal for int(): " + s);
            default:
                if (v != null && ForeignScalar?.Invoke(v) is long foreign) return foreign;
                throw new FormatException("int() argument must be a string or a number, not " + TypeName(v));
        }
    }

    /// <summary>float(v): numbers and numeric strings. Throws FormatException (Python ValueError / TypeError).</summary>
    public static double ToFloat(object? v)
    {
        switch (v)
        {
            case double d: return d;
            case long l: return l;
            case int i: return i;
            case float f: return f;
            case bool b: return b ? 1 : 0;
            case string s:
                if (double.TryParse(s.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var r)) return r;
                throw new FormatException("invalid literal for float(): " + s);
            default: throw new FormatException("float() argument must be a string or a number, not " + TypeName(v));
        }
    }

    public static bool TryInt(object? v, out long result)
    {
        try { result = ToInt(v); return true; }
        catch (FormatException) { result = 0; return false; }
    }

    public static bool TryFloat(object? v, out double result)
    {
        try { result = ToFloat(v); return true; }
        catch (FormatException) { result = 0; return false; }
    }

    /// <summary>str(v) as Python prints it (None, True/False, 1.0, .NET objects via ToString).</summary>
    public static string Str(object? v) => v switch
    {
        null => "None",
        string s => s,
        bool b => b ? "True" : "False",
        double d => FloatStr(d),
        float f => FloatStr(f),
        IFormattable f => f.ToString(null, CultureInfo.InvariantCulture),
        _ => v.ToString() ?? "",
    };

    private static string FloatStr(double d)
    {
        if (double.IsNaN(d)) return "nan";
        if (double.IsInfinity(d)) return d > 0 ? "inf" : "-inf";
        var s = d.ToString("R", CultureInfo.InvariantCulture);
        var exp = s.IndexOf('E');
        if (exp >= 0)
        {
            // .NET writes 1E-07 / 1E+16, Python 1e-07 / 1e+16.
            var digits = s.Substring(exp + 2);
            return s.Substring(0, exp) + "e" + s[exp + 1] + (digits.Length < 2 ? "0" + digits : digits);
        }
        return s.IndexOf('.') < 0 ? s + ".0" : s;
    }

    public static string TypeName(object? v) => v == null ? "NoneType" : v.GetType().Name;

    /// <summary>round(v, nd) with halves away from zero (IronPython 2 behaviour the current responses have).</summary>
    public static double Round(double v, int nd = 0)
    {
        if (double.IsNaN(v) || double.IsInfinity(v))
            return v;
        if (nd < 0)
        {
            var scale = Math.Pow(10, -nd);
            return Math.Round(v / scale, MidpointRounding.AwayFromZero) * scale;
        }
        // Through decimal: exact decimal rounding, so .NET Framework and .NET give the same double.
        if (Math.Abs(v) < 1e15 && nd <= 15)
            return (double)Math.Round((decimal)v, nd, MidpointRounding.AwayFromZero);
        return Math.Round(v, Math.Min(nd, 15), MidpointRounding.AwayFromZero);
    }

    public static double Clamp(double v, double lo, double hi) => v < lo ? lo : v > hi ? hi : v;

    public static long Clamp(long v, long lo, long hi) => v < lo ? lo : v > hi ? hi : v;

    public static int Clamp(int v, int lo, int hi) => v < lo ? lo : v > hi ? hi : v;

    // ------------------------------------------------------------ reflection
    /// <summary>getattr(obj, name, default) for the few places that are truly dynamic.</summary>
    public static object? GetAttr(object? obj, string name, object? def = null)
    {
        if (obj == null)
            return def;
        try
        {
            var t = obj.GetType();
            var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
            if (p != null && p.GetIndexParameters().Length == 0)
                return p.GetValue(obj);
            var f = t.GetField(name, BindingFlags.Public | BindingFlags.Instance);
            return f != null ? f.GetValue(obj) : def;
        }
        catch
        {
            return def;
        }
    }

    public static bool HasAttr(object? obj, string name) =>
        obj != null && (obj.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance) != null
                        || obj.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance).Any(m => m.Name == name));

    /// <summary>getattr(EnumType, name, None): enum member by exact name, or null.</summary>
    public static T? EnumOrNull<T>(string? name) where T : struct, Enum =>
        name != null && Enum.TryParse<T>(name, false, out var v) && Enum.IsDefined(typeof(T), v) ? v : null;

    // --------------------------------------------------------------- strings
    /// <summary>difflib.get_close_matches(word, choices, n, cutoff)</summary>
    public static List<string> CloseMatches(string word, IEnumerable<string> choices, int n = 3, double cutoff = 0.6)
    {
        var scored = new List<(double score, string s)>();
        foreach (var c in choices)
        {
            var r = Ratio(word, c);
            if (r >= cutoff)
                scored.Add((r, c));
        }
        return scored.OrderByDescending(x => x.score).ThenByDescending(x => x.s, StringComparer.Ordinal)
            .Take(n).Select(x => x.s).ToList();
    }

    /// <summary>difflib.SequenceMatcher(None, a, b).ratio() (without the junk heuristic).</summary>
    public static double Ratio(string a, string b)
    {
        if (a.Length + b.Length == 0)
            return 1.0;
        return 2.0 * Matches(a, 0, a.Length, b, 0, b.Length) / (a.Length + b.Length);
    }

    private static int Matches(string a, int alo, int ahi, string b, int blo, int bhi)
    {
        if (alo >= ahi || blo >= bhi)
            return 0;
        int bestI = alo, bestJ = blo, best = 0;
        var prev = new int[bhi - blo + 1];
        for (var i = alo; i < ahi; i++)
        {
            var cur = new int[bhi - blo + 1];
            for (var j = blo; j < bhi; j++)
            {
                if (a[i] != b[j])
                    continue;
                var k = prev[j - blo] + 1;
                cur[j - blo + 1] = k;
                if (k > best)
                {
                    best = k;
                    bestI = i - k + 1;
                    bestJ = j - k + 1;
                }
            }
            prev = cur;
        }
        if (best == 0)
            return 0;
        return best + Matches(a, alo, bestI, b, blo, bestJ) + Matches(a, bestI + best, ahi, b, bestJ + best, bhi);
    }
}
