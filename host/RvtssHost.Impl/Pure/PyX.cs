using System.Globalization;
using System.Runtime.CompilerServices;

namespace RvtssHost.Pure;

/// <summary>
/// Python-flavoured helpers shared by the Pure modules ported in lane c (clash, diff, templates, sharedparams,
/// mapping_presets, family_library, filter_rules, exportnames, view_audit): Python equality, slicing,
/// ntpath functions and repr(). Revit-free.
/// </summary>
internal static class PyX
{
    // -------------------------------------------------------------- equality
    private static bool IsNumber(object? v) =>
        v is long || v is int || v is double || v is bool || v is float || v is short || v is byte || v is decimal;

    /// <summary>Python <c>a == b</c> on JSON-like values (1 == 1.0 == True, deep on dicts and lists).</summary>
    public static bool Eq(object? a, object? b)
    {
        if (a == null || b == null)
            return a == null && b == null;
        if (ReferenceEquals(a, b))
            return true;
        if (IsNumber(a) || IsNumber(b))
        {
            if (!IsNumber(a) || !IsNumber(b))
                return false;
            if (a is double || b is double || a is float || b is float || a is decimal || b is decimal)
                return Convert.ToDouble(a, CultureInfo.InvariantCulture) == Convert.ToDouble(b, CultureInfo.InvariantCulture);
            return Convert.ToInt64(a, CultureInfo.InvariantCulture) == Convert.ToInt64(b, CultureInfo.InvariantCulture);
        }
        if (a is string sa)
            return b is string sb && string.Equals(sa, sb, StringComparison.Ordinal);
        if (b is string)
            return false;
        if (a is Dict da)
        {
            if (b is not Dict db || da.Count != db.Count)
                return false;
            foreach (var kv in da)
                if (!db.TryGetValue(kv.Key, out var other) || !Eq(kv.Value, other))
                    return false;
            return true;
        }
        if (b is Dict)
            return false;
        if (a is System.Collections.IList la)
        {
            if (b is not System.Collections.IList lb || la.Count != lb.Count)
                return false;
            for (var i = 0; i < la.Count; i++)
                if (!Eq(la[i], lb[i]))
                    return false;
            return true;
        }
        return a.Equals(b);
    }

    /// <summary>Python <c>item in list</c>.</summary>
    public static bool In(object? item, System.Collections.IEnumerable seq)
    {
        foreach (var x in seq)
            if (Eq(item, x))
                return true;
        return false;
    }

    /// <summary>Hash/equality as a Python set or dict key would use (1, 1.0 and True are one key).</summary>
    public sealed class KeyComparer : IEqualityComparer<object?>
    {
        public static readonly KeyComparer Instance = new();

        bool IEqualityComparer<object?>.Equals(object? x, object? y) => Eq(x, y);

        int IEqualityComparer<object?>.GetHashCode(object? obj)
        {
            if (obj == null)
                return 0;
            if (obj is string s)
                return StringComparer.Ordinal.GetHashCode(s);
            if (IsNumber(obj))
                return Convert.ToDouble(obj, CultureInfo.InvariantCulture).GetHashCode();
            if (obj is Dict || obj is System.Collections.IList)
                return 1;
            return obj.GetHashCode();
        }
    }

    /// <summary>Identity comparison (Python <c>id(x)</c>).</summary>
    public sealed class RefComparer : IEqualityComparer<object>
    {
        public static readonly RefComparer Instance = new();

        bool IEqualityComparer<object>.Equals(object? x, object? y) => ReferenceEquals(x, y);

        int IEqualityComparer<object>.GetHashCode(object obj) => RuntimeHelpers.GetHashCode(obj);
    }

    // --------------------------------------------------------------- slicing
    /// <summary>Python <c>seq[:stop]</c> (a negative stop counts from the end).</summary>
    public static List<T> Head<T>(IList<T> seq, long stop)
    {
        var n = seq.Count;
        if (stop < 0)
            stop = Math.Max(0, n + stop);
        if (stop > n)
            stop = n;
        var res = new List<T>((int)stop);
        for (var i = 0; i < stop; i++)
            res.Add(seq[i]);
        return res;
    }

    /// <summary>A request list as a C# list of objects (Lst, List&lt;Dict&gt;, arrays ...); null becomes empty.</summary>
    public static List<object?> Items(object? seq)
    {
        var res = new List<object?>();
        if (seq == null || seq is string)
            return res;
        if (seq is System.Collections.IEnumerable e)
            foreach (var x in e)
                res.Add(x);
        return res;
    }

    /// <summary>len(x) for strings, dicts and lists; 0 for null.</summary>
    public static int Len(object? v) => v switch
    {
        null => 0,
        string s => s.Length,
        System.Collections.ICollection c => c.Count,
        System.Collections.IEnumerable e => e.Cast<object?>().Count(),
        _ => 0,
    };

    /// <summary>d[key] with Python's KeyError.</summary>
    public static object? Item(Dict d, string key) =>
        d.TryGetValue(key, out var v) ? v : throw new KeyNotFoundException(key);

    /// <summary>Python <c>a + b</c> for JSON numbers: integers stay integers.</summary>
    public static object Add(object? a, object? b)
    {
        if ((Py.IsInt(a) || a is bool) && (Py.IsInt(b) || b is bool))
            return Py.ToInt(a) + Py.ToInt(b);
        return Py.ToFloat(a) + Py.ToFloat(b);
    }

    // ---------------------------------------------------------------- ntpath
    private static bool IsSep(char c) => c == '\\' || c == '/';

    /// <summary>os.path.splitext (ntpath).</summary>
    public static (string root, string ext) Splitext(string p)
    {
        var sepIndex = Math.Max(p.LastIndexOf('\\'), p.LastIndexOf('/'));
        var dotIndex = p.LastIndexOf('.');
        if (dotIndex > sepIndex)
        {
            // skip all leading dots
            for (var i = sepIndex + 1; i < dotIndex; i++)
                if (p[i] != '.')
                    return (p.Substring(0, dotIndex), p.Substring(dotIndex));
        }
        return (p, "");
    }

    /// <summary>os.path.basename (ntpath).</summary>
    public static string Basename(string p)
    {
        if (p.Length >= 2 && p[1] == ':')
            p = p.Substring(2);
        var i = Math.Max(p.LastIndexOf('\\'), p.LastIndexOf('/'));
        return p.Substring(i + 1);
    }

    /// <summary>os.path.join(a, b) (ntpath).</summary>
    public static string Join(string a, string b)
    {
        if (b.Length >= 2 && b[1] == ':')
        {
            // b carries its own drive: it wins unless it is a relative path on the same drive
            var sameDrive = a.Length >= 2 && a[1] == ':' && char.ToLowerInvariant(a[0]) == char.ToLowerInvariant(b[0]);
            if (!sameDrive || (b.Length > 2 && IsSep(b[2])))
                return b;
            a = b.Substring(0, 2) + a.Substring(2);
            b = b.Substring(2);
        }
        if (b.Length > 0 && IsSep(b[0]))
            return (a.Length >= 2 && a[1] == ':' ? a.Substring(0, 2) : "") + b;
        if (a.Length == 0)
            return b;
        if (IsSep(a[a.Length - 1]) || (a.Length == 2 && a[1] == ':'))
            return a + b;
        return a + "\\" + b;
    }

    /// <summary>os.path.normpath (ntpath).</summary>
    public static string Normpath(string path)
    {
        path = path.Replace('/', '\\');
        string drive = "", root = "";
        if (path.StartsWith("\\\\", StringComparison.Ordinal) && !(path.Length > 2 && path[2] == '\\'))
        {
            // UNC: \\server\share is the drive
            var i = path.IndexOf('\\', 2);
            if (i < 0)
            {
                drive = path;
                path = "";
            }
            else
            {
                var j = path.IndexOf('\\', i + 1);
                if (j < 0)
                {
                    drive = path;
                    path = "";
                }
                else
                {
                    drive = path.Substring(0, j);
                    path = path.Substring(j);
                }
            }
        }
        else if (path.Length >= 2 && path[1] == ':')
        {
            drive = path.Substring(0, 2);
            path = path.Substring(2);
        }
        if (path.Length > 0 && path[0] == '\\')
        {
            root = "\\";
            path = path.TrimStart('\\');
        }
        var comps = path.Split(new[] { '\\' }).ToList();
        var k = 0;
        while (k < comps.Count)
        {
            if (comps[k].Length == 0 || comps[k] == ".")
            {
                comps.RemoveAt(k);
            }
            else if (comps[k] == "..")
            {
                if (k > 0 && comps[k - 1] != "..")
                {
                    comps.RemoveRange(k - 1, 2);
                    k--;
                }
                else if (k == 0 && root.Length > 0)
                {
                    comps.RemoveAt(k);
                }
                else
                {
                    k++;
                }
            }
            else
            {
                k++;
            }
        }
        var prefix = drive + root;
        if (prefix.Length == 0 && comps.Count == 0)
            comps.Add(".");
        return prefix + string.Join("\\", comps);
    }

    // ------------------------------------------------------------------ text
    /// <summary>str.split() without arguments: split on runs of whitespace.</summary>
    public static List<string> SplitWs(string s)
    {
        var res = new List<string>();
        var start = -1;
        for (var i = 0; i < s.Length; i++)
        {
            if (char.IsWhiteSpace(s[i]))
            {
                if (start >= 0)
                {
                    res.Add(s.Substring(start, i - start));
                    start = -1;
                }
            }
            else if (start < 0)
            {
                start = i;
            }
        }
        if (start >= 0)
            res.Add(s.Substring(start));
        return res;
    }

    /// <summary>"%s" % v: Py.Str for scalars, repr for dicts and lists.</summary>
    public static string Fmt(object? v) => v is Dict || (v is System.Collections.IList && v is not string) ? Repr(v) : Py.Str(v);

    /// <summary>repr(v) of a JSON-like value as Python 3 prints it (what "%s" % a_dict shows).</summary>
    public static string Repr(object? v)
    {
        var sb = new StringBuilder();
        Repr(v, sb);
        return sb.ToString();
    }

    private static void Repr(object? v, StringBuilder sb)
    {
        switch (v)
        {
            case string s:
                ReprStr(s, sb);
                break;
            case Dict d:
                sb.Append('{');
                var first = true;
                foreach (var kv in d)
                {
                    if (!first)
                        sb.Append(", ");
                    first = false;
                    ReprStr(kv.Key, sb);
                    sb.Append(": ");
                    Repr(kv.Value, sb);
                }
                sb.Append('}');
                break;
            case System.Collections.IList l:
                sb.Append('[');
                for (var i = 0; i < l.Count; i++)
                {
                    if (i > 0)
                        sb.Append(", ");
                    Repr(l[i], sb);
                }
                sb.Append(']');
                break;
            default:
                sb.Append(Py.Str(v));
                break;
        }
    }

    private static void ReprStr(string s, StringBuilder sb)
    {
        var quote = s.IndexOf('\'') >= 0 && s.IndexOf('"') < 0 ? '"' : '\'';
        sb.Append(quote);
        foreach (var c in s)
        {
            if (c == quote || c == '\\')
                sb.Append('\\').Append(c);
            else if (c == '\n')
                sb.Append("\\n");
            else if (c == '\r')
                sb.Append("\\r");
            else if (c == '\t')
                sb.Append("\\t");
            else if (c < ' ' || c == '\x7f')
                sb.Append("\\x").Append(((int)c).ToString("x2", CultureInfo.InvariantCulture));
            else
                sb.Append(c);
        }
        sb.Append(quote);
    }
}
