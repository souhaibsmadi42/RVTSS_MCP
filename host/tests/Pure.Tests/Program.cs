using System.Reflection;

namespace RvtssHost.Tests;

/// <summary>
/// Test runner. A test class is any static class in this assembly with
/// <c>public static void Run(T t)</c>; one file per ported module (UnitsTests.cs ...).
/// Optional argument: only run classes whose name contains it.
/// </summary>
public static class Program
{
    public static int Main(string[] args)
    {
        var filter = args.Length > 0 ? args[0] : null;
        var t = new T();
        foreach (var type in typeof(Program).Assembly.GetTypes().OrderBy(x => x.Name, StringComparer.Ordinal))
        {
            var run = type.GetMethod("Run", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(T) }, null);
            if (run == null || (filter != null && type.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0))
                continue;
            t.Suite = type.Name;
            try { run.Invoke(null, new object[] { t }); }
            catch (Exception e)
            {
                var inner = e is TargetInvocationException && e.InnerException != null ? e.InnerException : e;
                t.Fail("suite crashed", inner.ToString());
            }
        }
        Console.WriteLine($"{t.Passed} passed, {t.Failed} failed");
        return t.Failed == 0 ? 0 : 1;
    }
}

public sealed class T
{
    public string Suite = "";
    public int Passed, Failed;

    /// <summary>host/tests/vectors/&lt;name&gt;.json as Dict / Lst / scalars.</summary>
    public object? Vectors(string name)
    {
        var dir = AppContext.BaseDirectory;
        while (dir != null && !Directory.Exists(Path.Combine(dir, "tests", "vectors")))
            dir = Path.GetDirectoryName(dir);
        if (dir == null)
            throw new DirectoryNotFoundException("host/tests/vectors");
        return Py.JsonLoads(File.ReadAllText(Path.Combine(dir, "tests", "vectors", name + ".json"), Encoding.UTF8));
    }

    public void Check(string name, bool ok, string detail = "")
    {
        if (ok) Passed++;
        else Fail(name, detail);
    }

    public void Fail(string name, string detail)
    {
        Failed++;
        Console.WriteLine($"FAIL {Suite}: {name} {detail}");
    }

    /// <summary>Deep equality of JSON-like values; floats within a relative 1e-9.</summary>
    public void Eq(string name, object? expected, object? actual)
    {
        var e = Py.Clean(expected);
        var a = Py.Clean(actual);
        Check(name, Same(e, a), $"expected {Py.JsonDumps(e)} got {Py.JsonDumps(a)}");
    }

    /// <summary>The call must throw; when typeName is given the exception type name must contain it.</summary>
    public void Throws(string name, Action call, string? typeName = null)
    {
        try { call(); }
        catch (Exception ex)
        {
            Check(name, typeName == null || ex.GetType().Name.Contains(typeName), "threw " + ex.GetType().Name);
            return;
        }
        Fail(name, "did not throw");
    }

    public static bool Same(object? e, object? a)
    {
        if (e == null || a == null) return e == null && a == null;
        if (e is Dict de)
            return a is Dict da && de.Count == da.Count && de.All(kv => da.TryGetValue(kv.Key, out var v) && Same(kv.Value, v));
        if (e is Lst le)
            return a is Lst la && le.Count == la.Count && le.Zip(la, Same).All(x => x);
        if (e is string || a is string) return e is string es && a is string s && es == s;
        if (e is bool || a is bool) return e is bool eb && a is bool ab && eb == ab;
        var x = Convert.ToDouble(e);
        var y = Convert.ToDouble(a);
        return x == y || Math.Abs(x - y) <= 1e-9 * Math.Max(1.0, Math.Max(Math.Abs(x), Math.Abs(y)));
    }
}
