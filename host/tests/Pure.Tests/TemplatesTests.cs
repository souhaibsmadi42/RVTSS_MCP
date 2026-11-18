namespace RvtssHost.Tests;

public static class TemplatesTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "templates");
        var k = LaneC.D(data["constants"]);
        var kinds = new Dict();
        foreach (var kv in Templates.TemplateKinds)
            kinds[kv.Key] = new Lst { kv.Value.must, kv.Value.mustNot };
        t.Eq("TEMPLATE_KINDS", k["TEMPLATE_KINDS"], kinds);
        t.Eq("KIND_CATEGORY", k["KIND_CATEGORY"], Templates.KindCategory);
        t.Eq("UNIT_SYSTEM_HINTS", k["UNIT_SYSTEM_HINTS"], Templates.UnitSystemHints);

        var paths = LaneC.Strings(data["paths"]);
        var units = LaneC.L(data["units"]).Select(x => (string?)x).ToList();
        var kindNames = LaneC.Strings(data["kinds"]);
        var scores = LaneC.L(data["scores"]);
        var matches = LaneC.L(data["matches"]);
        for (var u = 0; u < units.Count; u++)
        {
            for (var n = 0; n < kindNames.Count; n++)
            {
                var expected = LaneC.L(LaneC.L(scores[u])[n]);
                for (var p = 0; p < paths.Count; p++)
                    LaneC.Same(t, "score " + paths[p] + " | " + kindNames[n] + " | " + units[u], expected[p],
                        Templates.Score(paths[p], kindNames[n], units[u]));
                LaneC.Same(t, "match " + kindNames[n] + " | " + units[u], LaneC.L(matches[u])[n],
                    Templates.Match(paths, kindNames[n], units[u]));
            }
        }
        var defaults = LaneC.L(data["score_default_unit"]);
        for (var n = 0; n < kindNames.Count; n++)
            for (var p = 0; p < paths.Count; p++)
                LaneC.Same(t, "score default unit " + paths[p] + " | " + kindNames[n], LaneC.L(defaults[n])[p],
                    Templates.Score(paths[p], kindNames[n]));

        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "score": return Templates.Score((string?)a[0], (string)a[1]!, (string?)a[2]);
                case "match": return Templates.Match(LaneC.Strings(a[0]), (string)a[1]!, (string?)a[2]);
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });

        // find_template_files: the same folder tree the generator built
        var tree = LaneC.D(data["tree"]);
        var root = Path.Combine(Path.GetTempPath(), "rvtss_tpl_" + Guid.NewGuid().ToString("N"));
        try
        {
            foreach (var rel in LaneC.Strings(tree["files"]))
            {
                var full = Path.Combine(root, rel.Replace('/', '\\'));
                Directory.CreateDirectory(Path.GetDirectoryName(full)!);
                File.WriteAllText(full, "x");
            }
            foreach (var rel in LaneC.Strings(tree["dirs"]))
                Directory.CreateDirectory(Path.Combine(root, rel));
            var i = 0;
            foreach (var item in LaneC.L(tree["cases"]))
            {
                var c = LaneC.D(item);
                var dirs = LaneC.L(c["dirs"]).Select(d => d is string s && s.Length > 0 ? root + "\\" + s.Replace('/', '\\') : (string?)d).ToList();
                var found = c["max_files"] == null
                    ? Templates.FindTemplateFiles(dirs)
                    : Templates.FindTemplateFiles(dirs, Py.ToInt(c["max_files"]));
                LaneC.Same(t, "find_template_files#" + i++, c["expected"],
                    found.Select(f => f.StartsWith(root + "\\", StringComparison.Ordinal) ? f.Substring(root.Length + 1) : f).ToList());
            }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }
}
