namespace RvtssHost.Tests;

public static class SharedparamsTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "sharedparams");
        var missing = Path.Combine(Path.GetTempPath(), "rvtss_sp_" + Guid.NewGuid().ToString("N"), "missing.txt");
        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "is_guid": return Sharedparams.IsGuid((string?)a[0]);
                case "parse": return Sharedparams.Parse((string)a[0]!);
                case "find_duplicates": return Sharedparams.FindDuplicates(LaneC.L(a[0]));
                case "read_text": return Sharedparams.ReadText(missing);
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });

        var dir = Path.Combine(Path.GetTempPath(), "rvtss_sp_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            var i = 0;
            foreach (var item in LaneC.L(data["files"]))
            {
                var f = LaneC.D(item);
                var path = Path.Combine(dir, "sp" + i + ".txt");
                File.WriteAllBytes(path, Convert.FromBase64String((string)f["base64"]!));
                if (f.ContainsKey("error"))
                {
                    t.Throws("read_text file#" + i, () => Sharedparams.ReadText(path));
                }
                else
                {
                    LaneC.Same(t, "read_text file#" + i, f["text"], Sharedparams.ReadText(path));
                    LaneC.Same(t, "parse_file file#" + i, f["parsed"], Sharedparams.ParseFile(path));
                }
                i++;
            }
        }
        finally
        {
            try { Directory.Delete(dir, true); } catch (Exception) { }
        }
    }
}
