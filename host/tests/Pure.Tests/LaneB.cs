namespace RvtssHost.Tests;

/// <summary>
/// Runs the vector files written by host/tests/vectors/gen_*.py (lane b format):
/// {"cases": [{"fn", "args", "kwargs", "out" | ("err", "msg")}], ...extras}.
/// </summary>
internal static class LaneB
{
    internal sealed class Case
    {
        public string Fn = "";
        public Lst Args = new();
        public Dict Kwargs = new();
        public Dict Raw = new();

        /// <summary>Positional argument i, or the keyword argument, or the default.</summary>
        public object? Arg(int i, string? keyword = null, object? def = null)
        {
            if (i < Args.Count)
                return Args[i];
            if (keyword != null && Kwargs.TryGetValue(keyword, out var v))
                return v;
            return def;
        }

        public bool Has(int i, string? keyword = null) => i < Args.Count || (keyword != null && Kwargs.ContainsKey(keyword));

        public string? Str(int i, string? keyword = null, string? def = null) => (string?)Arg(i, keyword, def);

        public int? Int(int i, string? keyword = null, int? def = null) =>
            Arg(i, keyword) is long l ? (int)l : Has(i, keyword) ? null : def;

        public long? Long(int i, string? keyword = null, long? def = null) =>
            Arg(i, keyword) is long l ? l : Has(i, keyword) ? null : def;

        public bool Bool(int i, string? keyword = null, bool def = false) => Arg(i, keyword) is bool b ? b : def;
    }

    /// <summary>Messages that quote the regex engine's own error text differ between Python and .NET.</summary>
    private static readonly string[] EngineTexts = { "Invalid regex", "invalid pattern", "Invalid naming pattern" };

    /// <summary>Run every case of vectors/&lt;module&gt;.json through `call`; returns the extras of the file.</summary>
    public static Dict Run(T t, string module, Func<Case, object?> call, Func<Case, bool>? skip = null)
    {
        var doc = (Dict)t.Vectors(module)!;
        var index = 0;
        foreach (Dict raw in (Lst)doc["cases"]!)
        {
            index++;
            var c = new Case { Fn = (string)raw["fn"]!, Args = (Lst)raw["args"]!, Kwargs = (Dict)raw["kwargs"]!, Raw = raw };
            if (skip != null && skip(c))
                continue;
            var name = c.Fn + " #" + index + " " + Short(Py.JsonDumps(c.Args) + (c.Kwargs.Count > 0 ? " " + Py.JsonDumps(c.Kwargs) : ""));
            if (raw.ContainsKey("err"))
            {
                var err = (string)raw["err"]!;
                var msg = (string)raw["msg"]!;
                try
                {
                    var result = call(c);
                    t.Fail(name, "did not throw " + err + ", returned " + Short(Py.JsonDumps(result)));
                }
                catch (Exception ex)
                {
                    t.Check(name, IsError(ex, err), "expected " + err + ", threw " + ex.GetType().Name + ": " + ex.Message);
                    // our own error classes carry the user-facing text: it must match character for character
                    if (ex.GetType().Name == err && !EngineTexts.Any(x => msg.Contains(x)))
                        t.Check(name + " (message)", ex.Message == msg, "expected \"" + msg + "\" got \"" + ex.Message + "\"");
                }
            }
            else
            {
                object? actual;
                try
                {
                    actual = call(c);
                }
                catch (Exception ex)
                {
                    t.Fail(name, "threw " + ex.GetType().Name + ": " + ex.Message + ", expected " + Short(Py.JsonDumps(raw["out"])));
                    continue;
                }
                Same(t, name, raw["out"], actual);
            }
        }
        return doc;
    }

    /// <summary>Equal values, and dictionaries with their keys in the same order.</summary>
    public static void Same(T t, string name, object? expected, object? actual)
    {
        var e = Py.Clean(expected);
        var a = Py.Clean(actual);
        if (!T.Same(e, a))
        {
            t.Fail(name, "expected " + Short(Py.JsonDumps(e), 400) + " got " + Short(Py.JsonDumps(a), 400));
            return;
        }
        t.Check(name, KeyOrder(e) == KeyOrder(a), "key order: expected " + Short(KeyOrder(e), 300) + " got " + Short(KeyOrder(a), 300));
    }

    private static string KeyOrder(object? v)
    {
        if (v is Dict d)
            return "{" + string.Join(",", d.Select(kv => kv.Key + KeyOrder(kv.Value))) + "}";
        if (v is Lst l)
            return "[" + string.Join(",", l.Select(KeyOrder)) + "]";
        return "";
    }

    /// <summary>Python exception name -> what the C# port throws for it.</summary>
    private static bool IsError(Exception ex, string python)
    {
        switch (python)
        {
            case "ValueError":
            case "TypeError":
            case "AttributeError":
                return ex is FormatException && ex.GetType() == typeof(FormatException);
            case "KeyError":
                return ex is KeyNotFoundException;
            case "IndexError":
                return ex is IndexOutOfRangeException || ex is ArgumentOutOfRangeException;
            case "error":
            case "PatternError":
                return ex is ArgumentException;
            case "Error":
                return ex.GetType().Name == "CsvError";
            case "UnicodeDecodeError":
                return ex is System.Text.DecoderFallbackException;
            default:
                return ex.GetType().Name == python;
        }
    }

    public static string Short(string s, int max = 160) => s.Length <= max ? s : s.Substring(0, max) + "...";

    public static List<(object? id, string? name)> Pairs(object? items) =>
        ((Lst)items!).Select(p => (((Lst)p!)[0], (string?)((Lst)p!)[1])).ToList();

    public static Lst Tuples(IEnumerable<(string, string)> pairs) =>
        pairs.Select(p => (object?)new Lst { p.Item1, p.Item2 }).ToList();

    public static byte[] Hex(string hex) =>
        Enumerable.Range(0, hex.Length / 2).Select(i => Convert.ToByte(hex.Substring(i * 2, 2), 16)).ToArray();

    public static string ToHex(byte[] bytes) => string.Concat(bytes.Select(b => b.ToString("x2")));
}
