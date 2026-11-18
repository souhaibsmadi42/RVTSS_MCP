using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// QC findings, severities and configurable naming/parameter rules.
///
/// Rule file (JSON, optional; default location %APPDATA%/RVTSS/qc_rules.json):
/// {
///   "naming": {
///     "views":    {"pattern": "^[A-Z]{2}-", "severity": "warning", "description": "..."},
///     "sheets":   {"pattern": "^[A-Z]-\\d{3}$", "field": "number"},
///     "families": {"pattern": "^[A-Z]{3}_"},
///     "types":    {"pattern": "..."},
///     "levels":   {"pattern": "..."},
///     "parameters": {"pattern": "^[A-Z][A-Za-z0-9 ]+$"}
///   },
///   "required_parameters": [
///     {"categories": ["Doors"], "parameters": ["Fire Rating", "Mark"], "severity": "error"}
///   ],
///   "sheet_parameters": ["Drawn By", "Checked By"]
/// }
/// </summary>
public static class Rules
{
    public static readonly string[] Severities = { "info", "warning", "error", "critical" };

    public static int SeverityRank(object? sev)
    {
        var i = sev is string s ? Array.IndexOf(Severities, s) : -1;
        return i >= 0 ? i : 1;
    }

    /// <summary>
    /// One QC finding. `extra` holds the Python keyword arguments beyond the named ones (**extra); they are
    /// added after the standard keys, in the order given.
    /// </summary>
    public static Dict Finding(string check, object? severity, string message,
        System.Collections.IEnumerable? elementIds = null, string? recommendation = null, long? count = null,
        int maxIds = 50, Dict? extra = null)
    {
        var ids = new Lst();
        if (elementIds != null && !(elementIds is string text && text.Length == 0))
            foreach (var id in PureText.Iter(elementIds))
                ids.Add(id);
        var f = new Dict
        {
            ["check"] = check,
            ["severity"] = severity is string s && Severities.Contains(s) ? s : "warning",
            ["message"] = message,
            ["count"] = count ?? ids.Count,
            ["element_ids"] = ids.GetRange(0, PureText.SliceEnd(ids.Count, maxIds)),
        };
        if (ids.Count > maxIds)
            f["element_ids_truncated"] = true;
        if (!string.IsNullOrEmpty(recommendation))
            f["recommendation"] = recommendation;
        f.Update(extra);
        return f;
    }

    public static Dict Summarize(System.Collections.IEnumerable findings)
    {
        var list = findings.Cast<object?>().Select(AsFinding).ToList();
        var bySev = new Dict();
        foreach (var s in Severities)
            bySev[s] = 0L;
        var byCheck = new Dict();
        foreach (var f in list)
        {
            var sev = Py.Str(f["severity"]);
            bySev[sev] = Py.ToInt(bySev.Get(sev, 0L)) + 1;
            var check = Py.Str(f["check"]);
            byCheck[check] = Py.ToInt(byCheck.Get(check, 0L)) + 1;
        }
        object? worst = null;
        foreach (var f in list)
            if (worst == null || SeverityRank(f["severity"]) > SeverityRank(worst))
                worst = f["severity"];
        return new Dict
        {
            ["total_findings"] = (long)list.Count, ["by_severity"] = bySev, ["by_check"] = byCheck,
            ["worst_severity"] = worst,
        };
    }

    private static Dict AsFinding(object? f) =>
        f as Dict ?? throw new FormatException("'" + Py.TypeName(f) + "' object is not subscriptable");

    /// <summary>Highest severity first, then the larger count; the sort is stable like Python's.</summary>
    public static List<Dict> SortFindings(IEnumerable<Dict> findings) =>
        findings.OrderBy(f => -SeverityRank(f["severity"])).ThenBy(f => -PureText.ToFloat(f.Get("count", 0L))).ToList();

    /// <summary>sort_findings for an untyped list of findings.</summary>
    public static Lst SortFindings(Lst findings) =>
        SortFindings(findings.Select(AsFinding)).Cast<object?>().ToList();

    /// <summary>items: [(id, name)]; rule: {"pattern", "severity", "description"}.</summary>
    public static List<Dict> CheckNames<TId>(IEnumerable<(TId id, string? name)> items, Dict rule, string checkName,
        string label)
    {
        var patternValue = rule.Get("pattern");
        if (!Py.Truthy(patternValue))
            return new List<Dict>();
        Regex rx;
        try
        {
            rx = PureText.Re(PureText.Pattern(patternValue));
        }
        catch (ArgumentException ex)
        {
            return new List<Dict>
            {
                Finding(checkName, "error", "Invalid naming pattern for " + label + ": " + ex.Message),
            };
        }
        var bad = items.Where(it => !rx.IsMatch(it.name ?? "")).ToList();
        if (bad.Count == 0)
            return new List<Dict>();
        var description = rule.Get("description");
        return new List<Dict>
        {
            Finding(
                checkName, rule.Get("severity", "warning"),
                bad.Count + " " + label + " do not match naming pattern " + Py.Str(patternValue),
                elementIds: bad.Select(it => (object?)it.id).ToList(),
                recommendation: Py.Truthy(description)
                    ? Py.Str(description)
                    : "Rename to match the project naming standard (see batch_rename).",
                extra: new Dict { ["examples"] = bad.Take(10).Select(it => (object?)it.name).ToList() }),
        };
    }

    public static List<Dict> CheckDuplicateNames<TId>(IEnumerable<(TId id, string? name)> items, string checkName,
        string label)
    {
        var order = new List<string>();
        var seen = new Dictionary<string, Lst>(StringComparer.Ordinal);
        foreach (var (i, n) in items)
        {
            var key = (n ?? "").Trim().ToLowerInvariant();
            if (!seen.TryGetValue(key, out var group))
            {
                seen[key] = group = new Lst();
                order.Add(key);
            }
            group.Add(i);
        }
        var dups = order.Where(k => seen[k].Count > 1 && k.Length > 0).ToList();
        if (dups.Count == 0)
            return new List<Dict>();
        var ids = new Lst();
        foreach (var k in dups)
            ids.AddRange(seen[k]);
        return new List<Dict>
        {
            Finding(checkName, "warning", dups.Count + " " + label + " names are used more than once",
                elementIds: ids,
                recommendation: "Make names unique so schedules, tags and exports stay unambiguous.",
                extra: new Dict
                {
                    ["examples"] = dups.OrderBy(k => k, StringComparer.Ordinal).Take(10).Cast<object?>().ToList(),
                }),
        };
    }

    private static readonly Regex SimilarNoise = new(@"[\s_\-\.]+", RegexOptions.CultureInvariant);

    /// <summary>Detect near-duplicate names (e.g. 'Door 900' vs 'Door_900'). O(n^2) - capped by caller.</summary>
    public static List<(string, string)> SimilarNames(IEnumerable<string?> names, double threshold = 0.92)
    {
        string Norm(string? s) => SimilarNoise.Replace((s ?? "").ToLowerInvariant(), "");

        var result = new List<(string, string)>();
        var normed = names.Select(n => (name: n, norm: Norm(n))).ToList();
        for (var i = 0; i < normed.Count; i++)
        {
            for (var j = i + 1; j < normed.Count; j++)
            {
                var a = normed[i].norm;
                var b = normed[j].norm;
                if (a.Length == 0 || b.Length == 0)
                    continue;
                if (a == b || Py.Ratio(a, b) >= threshold)
                    result.Add((normed[i].name!, normed[j].name!));
            }
        }
        return result;
    }
}
