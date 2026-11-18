using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Family library audit on plain records (filled by revit_mcp/family_library.py).
///
/// Record: {"file", "path", "size_kb", "category", "parameters": [{"name", "shared", "instance", "formula"}],
///          "types": [names], "nested": [names], "warnings": [texts], "validation": {"summary", "findings"},
///          "error": str (open failed)}
/// </summary>
public static class FamilyLibrary
{
    public static readonly Regex BackupRx = new(@"\.\d{4}\.rfa$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public static bool IsFamilyFile(string name) =>
        name.ToLowerInvariant().EndsWith(".rfa", StringComparison.Ordinal) && !BackupRx.IsMatch(name);

    /// <summary>walk_items: os.walk-like [(dirpath, dirnames, filenames)] -> sorted .rfa paths (backups skipped).</summary>
    public static List<string> ListFiles(IEnumerable<(string dirpath, List<string> dirnames, List<string> filenames)> walkItems,
        bool recursive = true, string? root = null)
    {
        var res = new List<string>();
        foreach (var (dirpath, _, files) in walkItems)
        {
            if (!recursive && root != null && PyX.Normpath(dirpath) != PyX.Normpath(root))
                continue;
            foreach (var f in files)
                if (IsFamilyFile(f))
                    res.Add(PyX.Join(dirpath, f));
        }
        // stable, like sorted()
        return res.OrderBy(p => p.ToLowerInvariant(), StringComparer.Ordinal).ToList();
    }

    public static string FamilyName(string path) => PyX.Splitext(PyX.Basename(path)).root;

    private static Dict Rec(object? r) => r as Dict ?? throw new InvalidCastException("family record must be an object");

    private static object? Or(object? v, object? def) => Py.Truthy(v) ? v : def;

    private static Dict DictOr(object? v) => Py.Truthy(v) && v is Dict d ? d : new Dict();

    /// <summary>family_name(rec.get("path") or rec.get("file") or "")</summary>
    private static string NameOf(Dict rec) => FamilyName(Py.Str(Or(rec.Get("path"), Or(rec.Get("file"), ""))));

    private static List<object?> ListOr(object? v) => Py.Truthy(v) ? PyX.Items(v) : new List<object?>();

    public static Dict SummaryRow(Dict rec)
    {
        var prms = ListOr(rec.Get("parameters"));
        var v = DictOr(DictOr(rec.Get("validation")).Get("summary"));
        var sev = DictOr(v.Get("by_severity"));
        return new Dict
        {
            ["family"] = NameOf(rec), ["file"] = rec.Get("file"),
            ["category"] = rec.Get("category"), ["size_kb"] = rec.Get("size_kb"), ["types"] = (long)PyX.Len(Or(rec.Get("types"), null)),
            ["parameters"] = (long)prms.Count, ["shared_parameters"] = (long)prms.Count(p => Py.Truthy(Rec(p).Get("shared"))),
            ["nested"] = (long)PyX.Len(Or(rec.Get("nested"), null)), ["warnings"] = (long)PyX.Len(Or(rec.Get("warnings"), null)),
            ["validation_errors"] = PyX.Add(sev.Get("error", 0L), sev.Get("critical", 0L)),
            ["validation_warnings"] = sev.Get("warning", 0L), ["error"] = rec.Get("error"),
        };
    }

    public static List<Dict> LibraryFindings(IEnumerable<object?> records, Dict? namingRule = null, Dict? isoScheme = null,
        double maxSizeKb = 2048, long maxNested = 10)
    {
        var res = new List<Dict>();
        var recs = records.Select(Rec).ToList();

        Lst Ids(IEnumerable<Dict> rs) => new Lst(rs.Select(r => (object?)NameOf(r)));

        string PathName(Dict r) => FamilyName(Py.Str(PyX.Item(r, "path")));

        var failed = recs.Where(r => Py.Truthy(r.Get("error"))).ToList();
        if (failed.Count > 0)
            res.Add(Rules.Finding("library_open", "error", failed.Count + " families could not be opened",
                Ids(failed),
                recommendation: "Open them manually in Revit to see the error (corrupt or newer version).",
                extra: new Dict
                {
                    ["errors"] = PyX.Head(failed, 20)
                        .Select(r => new Dict { ["file"] = r.Get("file"), ["error"] = r.Get("error") }).ToList(),
                }));
        var ok = recs.Where(r => !Py.Truthy(r.Get("error"))).ToList();
        var big = ok.Where(r => Py.ToFloat(Or(r.Get("size_kb"), 0L)) > maxSizeKb).ToList();
        if (big.Count > 0)
        {
            var sizes = new Dict();
            foreach (var r in PyX.Head(big, 30))
                sizes[PathName(r)] = r.Get("size_kb");
            res.Add(Rules.Finding("library_size", "warning", big.Count + " families are larger than " + (long)Math.Truncate(maxSizeKb) + " KB",
                Ids(big),
                recommendation: "Purge unused nested families/materials, remove imported CAD, simplify geometry.",
                extra: new Dict { ["sizes"] = sizes }));
        }
        var generic = ok.Where(r =>
        {
            var c = r.Get("category");
            return c == null || PyX.Eq(c, "") || PyX.Eq(c, "Generic Models");
        }).ToList();
        if (generic.Count > 0)
            res.Add(Rules.Finding("library_category", "info", generic.Count + " families use Generic Models or no category",
                Ids(generic), recommendation: "Use a specific category so the family schedules and filters."));
        var noTypes = ok.Where(r => !Py.Truthy(r.Get("types"))).ToList();
        if (noTypes.Count > 0)
            res.Add(Rules.Finding("library_types", "warning", noTypes.Count + " families have no types", Ids(noTypes)));
        var nested = ok.Where(r => PyX.Len(Or(r.Get("nested"), null)) > maxNested).ToList();
        if (nested.Count > 0)
            res.Add(Rules.Finding("library_nested", "info",
                nested.Count + " families nest more than " + maxNested + " families", Ids(nested)));
        var warned = ok.Where(r => Py.Truthy(r.Get("warnings"))).ToList();
        if (warned.Count > 0)
        {
            var examples = new Dict();
            foreach (var r in PyX.Head(warned, 15))
                examples[PathName(r)] = PyX.Head(PyX.Items(r["warnings"]), 3);
            res.Add(Rules.Finding("library_warnings", "warning", warned.Count + " families contain Revit warnings",
                Ids(warned), extra: new Dict { ["examples"] = examples }));
        }
        var invalid = ok.Where(r => Py.Truthy(SummaryRow(r)["validation_errors"])).ToList();
        if (invalid.Count > 0)
        {
            var details = new Dict();
            foreach (var r in PyX.Head(invalid, 20))
            {
                var messages = PyX.Items(DictOr(r.Get("validation")).Get("findings", new Lst()))
                    .Select(Rec)
                    .Where(f => PyX.Eq(f.Get("severity"), "error") || PyX.Eq(f.Get("severity"), "critical"))
                    .Select(f => f.Get("message")).ToList();
                details[PathName(r)] = PyX.Head(messages, 5);
            }
            res.Add(Rules.Finding("library_validation", "error", invalid.Count + " families fail family_validate",
                Ids(invalid),
                recommendation: "Open the family and fix the errors listed (family_validate).",
                extra: new Dict { ["details"] = details }));
        }
        var dupParams = new List<Dict>();
        foreach (var r in ok)
        {
            var seen = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var p in ListOr(r.Get("parameters")))
            {
                var key = Py.Str(Or(Rec(p).Get("name"), "")).ToLowerInvariant();
                seen[key] = (seen.TryGetValue(key, out var n) ? n : 0) + 1;
            }
            if (seen.Values.Any(n => n > 1))
                dupParams.Add(r);
        }
        if (dupParams.Count > 0)
            res.Add(Rules.Finding("library_parameters", "warning", dupParams.Count + " families have parameters with the same name "
                + "(differing only in case or shared vs family)", Ids(dupParams)));
        var items = recs.Select(r => (id: (object?)NameOf(r), name: (string?)NameOf(r))).ToList();
        if (Py.Truthy(namingRule) && Py.Truthy(namingRule!.Get("pattern")))
            res.AddRange(Rules.CheckNames(items, namingRule!, "library_naming", "family files"));
        if (Py.Truthy(isoScheme))
            res.AddRange(Naming.CheckItems(items, isoScheme!, "families", "family files"));
        return Rules.SortFindings(res);
    }
}
