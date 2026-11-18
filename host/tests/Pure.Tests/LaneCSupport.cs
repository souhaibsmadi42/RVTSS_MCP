namespace RvtssHost.Tests;

/// <summary>
/// Runs the cases of a lane-c vector file (host/tests/vectors/_lane_c.py): {"fn", "args", "expected"} or
/// {"fn", "args", "error", "message"}.
/// </summary>
internal static class LaneC
{
    private static readonly string[] CustomErrors = { "PresetError", "RuleError", "NamingError" };

    /// <summary>
    /// The vector file as Dict / Lst / scalars with JSON integers as long. Not t.Vectors: Py.FromJson has
    /// `TryGetInt64(out var i) ? i : e.GetDouble()`, a conditional of long and double, so every integer comes out
    /// as a double (reported; Py.cs is not ours to change). The types matter here: "%s" % 1 is "1", not "1.0".
    /// </summary>
    public static Dict Load(T t, string name)
    {
        var dir = AppContext.BaseDirectory;
        while (dir != null && !Directory.Exists(Path.Combine(dir, "tests", "vectors")))
            dir = Path.GetDirectoryName(dir);
        if (dir == null)
            throw new DirectoryNotFoundException("host/tests/vectors");
        using var doc = System.Text.Json.JsonDocument.Parse(
            File.ReadAllText(Path.Combine(dir, "tests", "vectors", name + ".json"), Encoding.UTF8));
        return (Dict)FromJson(doc.RootElement)!;
    }

    private static object? FromJson(System.Text.Json.JsonElement e)
    {
        switch (e.ValueKind)
        {
            case System.Text.Json.JsonValueKind.Object:
                var d = new Dict();
                foreach (var p in e.EnumerateObject())
                    d[p.Name] = FromJson(p.Value);
                return d;
            case System.Text.Json.JsonValueKind.Array:
                var l = new Lst();
                foreach (var v in e.EnumerateArray())
                    l.Add(FromJson(v));
                return l;
            case System.Text.Json.JsonValueKind.String:
                return e.GetString();
            case System.Text.Json.JsonValueKind.Number:
                if (e.TryGetInt64(out var i))
                    return i;
                return e.GetDouble();
            case System.Text.Json.JsonValueKind.True:
                return true;
            case System.Text.Json.JsonValueKind.False:
                return false;
            default:
                return null;
        }
    }

    /// <summary>call(fn, args) runs the C# port; messageFns: functions whose ValueError text is compared too.</summary>
    public static void RunCases(T t, Dict data, Func<string, Lst, object?> call, params string[] messageFns)
    {
        var i = 0;
        foreach (var item in (Lst)data["cases"]!)
        {
            var c = (Dict)item!;
            var fn = (string)c["fn"]!;
            var args = (Lst)c["args"]!;
            var name = fn + "#" + i++;
            if (c.TryGetValue("error", out var err))
            {
                var error = (string)err!;
                try
                {
                    var got = call(fn, args);
                    t.Fail(name, "did not throw " + error + ", returned " + Short(Py.JsonDumps(got)));
                }
                catch (Exception ex)
                {
                    t.Check(name, ErrorMatches(error, ex), "expected " + error + ", threw " + ex.GetType().Name + ": " + ex.Message);
                    if (Array.IndexOf(CustomErrors, error) >= 0 || (error == "ValueError" && Array.IndexOf(messageFns, fn) >= 0))
                        Same(t, name + " message", c["message"], ex.Message);
                }
                continue;
            }
            object? actual;
            try
            {
                actual = call(fn, args);
            }
            catch (Exception ex)
            {
                t.Fail(name, "threw " + ex.GetType().Name + ": " + ex.Message + " args " + Short(Py.JsonDumps(args)));
                continue;
            }
            Same(t, name, c["expected"], actual);
        }
    }

    /// <summary>t.Eq with a short failure text (some expected values are whole HTML reports).</summary>
    public static void Same(T t, string name, object? expected, object? actual)
    {
        var e = Py.Clean(expected);
        var a = Py.Clean(actual);
        t.Check(name, T.Same(e, a), "expected " + Short(Py.JsonDumps(e)) + " got " + Short(Py.JsonDumps(a)));
    }

    private static string Short(string s) => s.Length <= 700 ? s : s.Substring(0, 700) + "...";

    /// <summary>The C# exception that stands for a Python one.</summary>
    public static bool ErrorMatches(string pythonError, Exception ex)
    {
        switch (pythonError)
        {
            case "KeyError": return ex is KeyNotFoundException;
            case "IndexError": return ex is ArgumentOutOfRangeException || ex is IndexOutOfRangeException;
            case "ValueError": return ex is FormatException;
            case "FileNotFoundError": return ex is FileNotFoundException || ex is DirectoryNotFoundException;
            // Python fails on the wrong type somewhere inside; the port fails too, with whatever .NET throws there
            case "TypeError":
            case "AttributeError": return true;
            default: return ex.GetType().Name == pythonError && ex is FormatException;
        }
    }

    public static bool Has(Lst args, int i) => args.Count > i;

    public static Dict D(object? v) => (Dict)v!;

    public static Lst L(object? v) => (Lst)v!;

    public static List<string> Strings(object? v) => ((Lst)v!).Select(x => (string)x!).ToList();
}
