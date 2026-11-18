using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>File names for exports (RVTSS v2.2): templates, sanitising, uniqueness.</summary>
public static class Exportnames
{
    public static readonly Dictionary<string, string> Formats = new()
    {
        ["pdf"] = ".pdf", ["dwg"] = ".dwg", ["dxf"] = ".dxf", ["ifc"] = ".ifc", ["nwc"] = ".nwc", ["csv"] = ".csv",
    };

    /// <summary>formats exported once per model (not per view / sheet)</summary>
    public static readonly string[] ModelFormats = { "ifc", "nwc" };

    private static readonly Regex Invalid = new("[\\\\/:*?\"<>|\\x00-\\x1f]", RegexOptions.CultureInvariant);
    private static readonly Regex FieldRx = new(@"\{(\w+)\}", RegexOptions.CultureInvariant);
    private static readonly Regex Spaces = new(@"\s+", RegexOptions.CultureInvariant);
    private static readonly Regex TrailingDash = new(@"(\s*-\s*)+$", RegexOptions.CultureInvariant);
    private static readonly Regex LeadingDash = new(@"^(\s*-\s*)+", RegexOptions.CultureInvariant);

    public static readonly string[] Fields = { "number", "name", "title", "revision", "view_type", "date", "document" };

    public static string DefaultTemplate(bool isSheet) => isSheet ? "{number} - {name}" : "{name}";

    /// <summary>The replacement is a Python re.sub template: backslash escapes are processed, "$" is literal.</summary>
    private static string Template(string replacement)
    {
        if (replacement.IndexOf('\\') < 0)
            return replacement;
        var sb = new StringBuilder();
        for (var i = 0; i < replacement.Length; i++)
        {
            var c = replacement[i];
            if (c != '\\')
            {
                sb.Append(c);
                continue;
            }
            i++;
            var e = i < replacement.Length ? replacement[i] : '\0';
            switch (e)
            {
                case '\\': sb.Append('\\'); break;
                case 'n': sb.Append('\n'); break;
                case 'r': sb.Append('\r'); break;
                case 't': sb.Append('\t'); break;
                case 'f': sb.Append('\f'); break;
                case 'v': sb.Append('\v'); break;
                case 'a': sb.Append('\a'); break;
                case 'b': sb.Append('\b'); break;
                // group references and unknown escapes are errors in Python too (the pattern has no groups)
                default: throw new FormatException("bad escape in replacement " + replacement);
            }
        }
        return sb.ToString();
    }

    public static string Sanitize(string? name, string replacement = "_", long maxLen = 180)
    {
        var literal = Template(replacement);
        var s = Invalid.Replace(name ?? "", _ => literal).Trim().Trim('.');
        s = Spaces.Replace(s, " ");
        if (s.Length > maxLen)
            s = string.Concat(PyX.Head(s.ToCharArray(), maxLen)).TrimEnd();
        return s.Length > 0 ? s : "export";
    }

    /// <summary>'{number} - {name}' + {'number': 'A101', 'name': 'Plan'} -> 'A101 - Plan' (sanitised).</summary>
    public static string Render(string? template, Dict fields)
    {
        var unknown = FieldRx.Matches(template ?? "").Cast<Match>().Select(m => m.Groups[1].Value)
            .Where(f => Array.IndexOf(Fields, f) < 0).ToList();
        if (unknown.Count > 0)
            throw new NamingError("Unknown naming field(s) " + string.Join(", ", unknown.Distinct().OrderBy(x => x, StringComparer.Ordinal))
                                  + ". Use: " + string.Join(", ", Fields.Select(f => "{" + f + "}")));
        if (template == null)
            throw new ArgumentNullException(nameof(template), "expected string or bytes-like object");
        var res = FieldRx.Replace(template, m =>
        {
            var v = fields.Get(m.Groups[1].Value);
            return Py.Truthy(v) ? PyX.Fmt(v) : "";
        });
        res = TrailingDash.Replace(res, ""); // "A101 - " when name is empty
        res = LeadingDash.Replace(res, "");
        return Sanitize(res);
    }

    /// <summary>Make a list of stems unique (case-insensitive, as on Windows) by appending _2, _3...</summary>
    public static List<string> Unique(IEnumerable<string> names)
    {
        var seen = new Dictionary<string, long>(StringComparer.Ordinal);
        var res = new List<string>();
        foreach (var n in names)
        {
            var key = n.ToLowerInvariant();
            if (!seen.ContainsKey(key))
            {
                seen[key] = 1;
                res.Add(n);
                continue;
            }
            var i = seen[key] + 1;
            while (seen.ContainsKey((n + "_" + i).ToLowerInvariant()))
                i++;
            seen[key] = i;
            var candidate = n + "_" + i;
            seen[candidate.ToLowerInvariant()] = 1;
            res.Add(candidate);
        }
        return res;
    }

    public static string? StripExtension(string? name, string? fmt)
    {
        var ext = fmt != null && Formats.TryGetValue(fmt, out var e) ? e : "";
        if (ext.Length > 0 && (name ?? "").ToLowerInvariant().EndsWith(ext, StringComparison.Ordinal))
            return name!.Substring(0, name.Length - ext.Length);
        return name;
    }
}

public class NamingError : FormatException
{
    public NamingError(string message) : base(message)
    {
    }
}
