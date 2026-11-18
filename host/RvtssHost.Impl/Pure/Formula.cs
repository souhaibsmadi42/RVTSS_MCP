using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Static analysis of Revit family formulas.
///
/// This is a pre-check only: Revit's FamilyManager.SetFormula (run inside a
/// rolled-back transaction) is the authoritative validator. The analysis here
/// finds parameter references, references to unknown names and dependency
/// cycles across a whole family, which Revit only reports one formula at a time.
/// </summary>
public static class Formula
{
    public static readonly HashSet<string> Functions = new(StringComparer.Ordinal)
    {
        "if", "and", "or", "not", "sin", "cos", "tan", "asin", "acos", "atan",
        "exp", "abs", "sqrt", "round", "roundup", "rounddown", "log", "ln", "pi",
        "size_lookup", "e",
    };

    public static readonly HashSet<string> UnitWords = new(StringComparer.Ordinal)
    {
        "mm", "cm", "m", "ft", "in", "deg", "rad", "sf", "sm", "m2", "m3", "ft2", "ft3",
        "mm2", "mm3", "cm2", "cm3", "kg", "n", "kn", "pa", "kpa", "w", "kw", "l", "s",
        "yes", "no", "true", "false", "degree", "degrees",
    };

    private static readonly Regex StringLiteral = new("\"[^\"]*\"", RegexOptions.CultureInvariant);
    private static readonly Regex Word = new("[A-Za-z_][A-Za-z_0-9]*", RegexOptions.CultureInvariant);

    private static string StripStrings(string? formula) => StringLiteral.Replace(formula ?? "", " ");

    /// <summary>sorted(known_names, key=len, reverse=True): longest first, equal lengths keep their order.</summary>
    private static IEnumerable<string> LongestFirst(IEnumerable<string?> knownNames) =>
        knownNames.Select(n => n ?? throw new FormatException("object of type 'NoneType' has no len()")).ToList()
            .OrderByDescending(n => n.Length);

    private static Regex NamePattern(string name) =>
        new(@"(?<![\w])" + Regex.Escape(name) + @"(?![\w])", RegexOptions.CultureInvariant);

    /// <summary>
    /// Return the known parameter names referenced by a formula.
    ///
    /// Parameter names may contain spaces and symbols, so matching is done
    /// longest-name-first against the list of known names.
    /// </summary>
    public static List<string> References(string? formula, IEnumerable<string?> knownNames)
    {
        var text = StripStrings(formula);
        var found = new List<string>();
        foreach (var name in LongestFirst(knownNames))
        {
            if (name.Length == 0)
                continue;
            var pat = NamePattern(name);
            if (pat.IsMatch(text))
            {
                found.Add(name);
                text = pat.Replace(text, " ");
            }
        }
        return found;
    }

    /// <summary>Words in a formula that are not known parameters, functions, units or numbers.</summary>
    public static List<string> UnknownIdentifiers(string? formula, IEnumerable<string?> knownNames)
    {
        var text = StripStrings(formula);
        foreach (var name in LongestFirst(knownNames))
            if (name.Length > 0)
                text = NamePattern(name).Replace(text, " ");
        var result = new List<string>();
        foreach (Match m in Word.Matches(text))
        {
            var w = m.Value;
            var lw = w.ToLowerInvariant();
            if (Functions.Contains(lw) || UnitWords.Contains(lw))
                continue;
            if (!result.Contains(w))
                result.Add(w);
        }
        return result;
    }

    public static string? CheckBalance(string? formula)
    {
        var depth = 0;
        foreach (var ch in StripStrings(formula))
        {
            if (ch == '(')
            {
                depth++;
            }
            else if (ch == ')')
            {
                depth--;
                if (depth < 0)
                    return "Unbalanced ')'";
            }
        }
        if (depth != 0)
            return "Missing ')'";
        if ((formula ?? "").Count(c => c == '"') % 2 != 0)
            return "Unterminated string literal";
        return null;
    }

    private static string? FormulaText(object? f) => Py.Truthy(f) ? f as string ?? Py.Str(f) : null;

    /// <summary>formulas: {param_name: formula}. Returns list of cycles (lists of names).</summary>
    public static List<List<string>> FindCycles<TFormula>(IEnumerable<KeyValuePair<string, TFormula>> formulas,
        IEnumerable<string?> knownNames)
    {
        var known = knownNames.ToList();
        var order = new List<string>();
        var graph = new Dictionary<string, List<string>>(StringComparer.Ordinal);
        foreach (var kv in formulas)
        {
            var name = kv.Key;
            var f = FormulaText(kv.Value);
            if (f == null)
                continue;
            var refs = References(f, known);
            var edges = refs.Where(r => r != name).ToList();
            if (refs.Contains(name))
                edges.Add(name);
            if (!graph.ContainsKey(name))
                order.Add(name);
            graph[name] = edges;
        }
        var cycles = new List<List<string>>();
        var state = new Dictionary<string, int>(StringComparer.Ordinal);
        var stack = new List<string>();

        string Key(IEnumerable<string> cyc) =>
            string.Join("\u0000", cyc.Distinct().OrderBy(x => x, StringComparer.Ordinal));

        void Visit(string n)
        {
            state[n] = 1;
            stack.Add(n);
            if (graph.TryGetValue(n, out var next))
            {
                foreach (var m in next)
                {
                    state.TryGetValue(m, out var st);
                    if (st == 1)
                    {
                        var cyc = stack.GetRange(stack.IndexOf(m), stack.Count - stack.IndexOf(m));
                        cyc.Add(m);
                        var key = Key(cyc);
                        if (!cycles.Any(c => Key(c) == key))
                            cycles.Add(cyc);
                    }
                    else if (st == 0)
                    {
                        Visit(m);
                    }
                }
            }
            stack.RemoveAt(stack.Count - 1);
            state[n] = 2;
        }

        foreach (var n in order)
        {
            state.TryGetValue(n, out var st);
            if (st == 0)
                Visit(n);
        }
        return cycles;
    }

    /// <summary>Full-family analysis. Returns a list of issues.</summary>
    public static List<Dict> Analyse<TFormula>(IEnumerable<KeyValuePair<string, TFormula>> formulas,
        IEnumerable<string?> knownNames)
    {
        var known = knownNames.ToList();
        var all = formulas.ToList();
        var issues = new List<Dict>();
        foreach (var kv in all.OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            var name = kv.Key;
            var f = FormulaText(kv.Value);
            if (f == null)
                continue;
            var bal = CheckBalance(f);
            if (bal != null)
            {
                issues.Add(new Dict
                {
                    ["parameter"] = name, ["severity"] = "error", ["issue"] = bal, ["formula"] = kv.Value,
                });
            }
            var unknown = UnknownIdentifiers(f, known);
            if (unknown.Count > 0)
            {
                issues.Add(new Dict
                {
                    ["parameter"] = name, ["severity"] = "warning",
                    ["issue"] = "Formula references unknown names: " + string.Join(", ", unknown),
                    ["formula"] = kv.Value,
                });
            }
        }
        foreach (var cyc in FindCycles(all, known))
        {
            issues.Add(new Dict
            {
                ["parameter"] = cyc[0], ["severity"] = "error",
                ["issue"] = "Circular formula reference: " + string.Join(" -> ", cyc),
            });
        }
        return issues;
    }
}
