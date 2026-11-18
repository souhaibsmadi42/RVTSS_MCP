namespace RvtssHost.Tests;

public static class CsvutilTests
{
    public static void Run(T t)
    {
        var path = Path.Combine(Path.GetTempPath(), "rvtss-pure-tests-" + Guid.NewGuid().ToString("N") + ".csv");
        try
        {
            LaneB.Run(t, "csvutil", c =>
            {
                switch (c.Fn)
                {
                    case "_cell":
                    {
                        // the private helper is one cell of a one-row table; a single empty header gives "\r\n" first
                        var text = Csvutil.ToCsv(new Lst(), new Lst { new Lst { c.Arg(0) } });
                        return text.Substring(2, text.Length - 4);
                    }
                    case "to_csv": return Csvutil.ToCsv((Lst)c.Arg(0)!, (Lst)c.Arg(1)!);
                    case "parse_csv":
                    {
                        var (header, rows) = Csvutil.ParseCsv(c.Str(0));
                        return new Lst { header, rows };
                    }
                    case "reader": return Csvutil.Reader(c.Str(0)!);
                    case "write_file":
                        Csvutil.WriteFile(path, c.Str(0)!);
                        return LaneB.ToHex(File.ReadAllBytes(path));
                    case "read_file":
                        File.WriteAllBytes(path, LaneB.Hex(c.Str(0)!));
                        return Csvutil.ReadFile(path);
                    default: throw new InvalidOperationException("no dispatch for " + c.Fn);
                }
            });
        }
        finally
        {
            if (File.Exists(path))
                File.Delete(path);
        }

        // typed rows
        t.Eq("typed to_csv", "id,name\r\n1,\"a,b\"\r\n",
            Csvutil.ToCsv(new[] { "id", "name" }, new List<List<object?>> { new() { 1L, "a,b" } }));
        // IronPython 2 / CPython 2 reject a NUL in the input (CPython 3.11+ accepts it, so no vector)
        t.Throws("reader NUL", () => Csvutil.ParseCsv("a,b\n1,\0\n"), "CsvError");
    }
}
