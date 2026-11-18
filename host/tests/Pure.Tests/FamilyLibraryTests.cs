namespace RvtssHost.Tests;

public static class FamilyLibraryTests
{
    private static List<(string dirpath, List<string> dirnames, List<string> filenames)> Walk(object? items) =>
        LaneC.L(items).Select(w =>
        {
            var l = LaneC.L(w);
            return ((string)l[0]!, LaneC.Strings(l[1]), LaneC.Strings(l[2]));
        }).ToList();

    public static void Run(T t)
    {
        var data = LaneC.Load(t, "family_library");
        t.Eq("BACKUP_RX", LaneC.D(data["constants"])["BACKUP_RX"], FamilyLibrary.BackupRx.ToString());

        // The text of a regex syntax error is the regex engine's own (Python re vs .NET): compare up to it.
        foreach (var c in LaneC.L(data["cases"]))
            CutPatternError(LaneC.D(c).Get("expected"));

        LaneC.RunCases(t, data, (fn, a) =>
        {
            if (fn == "library_findings")
                return CutPatternError(Findings(a));
            switch (fn)
            {
                case "is_family_file": return FamilyLibrary.IsFamilyFile((string)a[0]!);
                case "list_files":
                    if (!LaneC.Has(a, 1)) return FamilyLibrary.ListFiles(Walk(a[0]));
                    if (!LaneC.Has(a, 2)) return FamilyLibrary.ListFiles(Walk(a[0]), (bool)a[1]!);
                    return FamilyLibrary.ListFiles(Walk(a[0]), (bool)a[1]!, (string?)a[2]);
                case "family_name": return FamilyLibrary.FamilyName((string)a[0]!);
                case "summary_row": return FamilyLibrary.SummaryRow(LaneC.D(a[0]));
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });
    }

    private static List<Dict> Findings(Lst a)
    {
        var recs = LaneC.L(a[0]);
        if (!LaneC.Has(a, 1)) return FamilyLibrary.LibraryFindings(recs);
        if (!LaneC.Has(a, 2)) return FamilyLibrary.LibraryFindings(recs, a[1] as Dict);
        if (!LaneC.Has(a, 3)) return FamilyLibrary.LibraryFindings(recs, a[1] as Dict, a[2] as Dict);
        return FamilyLibrary.LibraryFindings(recs, a[1] as Dict, a[2] as Dict, Py.ToFloat(a[3]), Py.ToInt(a[4]));
    }

    private static object? CutPatternError(object? findings)
    {
        const string prefix = "Invalid naming pattern for family files: ";
        if (findings is System.Collections.IEnumerable list && findings is not string && findings is not Dict)
            foreach (var f in list)
                if (f is Dict d && d.Get("message") is string m && m.StartsWith(prefix, StringComparison.Ordinal))
                    d["message"] = prefix;
        return findings;
    }
}
