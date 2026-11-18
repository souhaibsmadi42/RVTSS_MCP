namespace RvtssHost.Pure;

/// <summary>Python: class SchemeError(ValueError).</summary>
public class SchemeError : FormatException
{
    public SchemeError(string message) : base(message) { }
}

/// <summary>
/// ISO 19650-style field-by-field name checks driven by qc_rules.json ("iso19650" section).
///
/// Scheme (see docs/examples/qc_rules.iso19650.json):
/// {
///   "delimiter": "-",
///   "fields": [
///     {"name": "project",    "values": ["P123"]},
///     {"name": "originator", "values": ["ABC", "XYZ"]},
///     {"name": "volume",     "pattern": "^(ZZ|XX|[A-Z0-9]{2})$"},
///     {"name": "level",      "values": ["00", "01", "02", "B1", "RF", "ZZ", "XX"]},
///     {"name": "type",       "values": ["DR", "M3", "SH", "SC"]},
///     {"name": "role",       "values": ["A", "S", "M", "E", "P"]},
///     {"name": "number",     "pattern": "^\\d{4}$"}
///   ],
///   "targets": {
///     "sheets":         {"source": "number", "severity": "error"},
///     "views":          {"fields": [...], "delimiter": "_"},
///     "view_templates": {...}, "families": {...}, "types": {...}, "worksets": {...}
///   }
/// }
/// A target uses the top-level fields unless it defines its own. Each field may set
/// "values" (allowed list), "pattern" (regex), "length" / "min_length" / "max_length",
/// "optional": true (may be empty) and "case_sensitive" (default true).
/// </summary>
public static class Naming
{
    public static readonly string[] Targets = { "sheets", "views", "view_templates", "families", "types", "worksets" };

    private static Dict Obj(object? v) =>
        v as Dict ?? throw new FormatException("'" + Py.TypeName(v) + "' object has no attribute 'get'");

    private static List<Dict> Fields(object? fields) => PureText.Iter(fields).Select(Obj).ToList();

    /// <summary>Effective {delimiter, fields, severity, source} for one target, or None if not configured.</summary>
    public static Dict? TargetScheme(Dict scheme, string target)
    {
        var targetsValue = scheme.Get("targets");
        var targets = Py.Truthy(targetsValue) ? Obj(targetsValue) : new Dict();
        if (!targets.ContainsKey(target))
            return null;
        var tValue = targets.Get(target);
        var t = Py.Truthy(tValue) ? Obj(tValue) : new Dict();
        var fields = Py.Truthy(t.Get("fields")) ? t.Get("fields") : scheme.Get("fields");
        if (!Py.Truthy(fields))
            throw new SchemeError("iso19650: no fields defined for target '" + target + "'");
        var result = new Dict
        {
            ["delimiter"] = t.ContainsKey("delimiter") ? t["delimiter"] : scheme.Get("delimiter", "-"),
            ["fields"] = fields,
            ["severity"] = t.ContainsKey("severity") ? t["severity"] : scheme.Get("severity", "warning"),
            ["source"] = t.Get("source", "name"),
            ["description"] = Py.Truthy(t.Get("description")) ? t.Get("description") : scheme.Get("description"),
        };
        foreach (var f in Fields(fields))
        {
            var pattern = f.Get("pattern");
            if (!Py.Truthy(pattern))
                continue;
            var text = PureText.Pattern(pattern);
            try
            {
                PureText.Re(text);
            }
            catch (ArgumentException e)
            {
                throw new SchemeError("iso19650: invalid pattern for field '" + Py.Str(f.Get("name")) + "': " + e.Message);
            }
        }
        return result;
    }

    /// <summary>Reason the value is invalid for the field, or None.</summary>
    public static string? CheckField(Dict field, string? value)
    {
        if (string.IsNullOrEmpty(value))
            return Py.Truthy(field.Get("optional")) ? null : "empty";
        var v = value!;
        var cs = Py.Truthy(field.Get("case_sensitive", true));
        var allowed = field.Get("values");
        if (Py.Truthy(allowed))
        {
            var items = PureText.Iter(allowed).ToList();
            var probe = cs ? v : v.ToLowerInvariant();
            bool found;
            if (allowed is string allowedText && cs)
                found = allowedText.IndexOf(probe, StringComparison.Ordinal) >= 0; // `in` on a string is a substring test
            else if (cs)
                found = items.Any(a => a is string s && s == probe);
            else
                found = items.Any(a => Py.Str(a).ToLowerInvariant() == probe);
            if (!found)
            {
                var shown = PureText.Join(", ", items.Take(12)) + (items.Count > 12 ? " ..." : "");
                return "'" + v + "' not in allowed values (" + shown + ")";
            }
        }
        var pattern = field.Get("pattern");
        if (Py.Truthy(pattern) && !PureText.Re(PureText.Pattern(pattern), ignoreCase: !cs).IsMatch(v))
            return "'" + v + "' does not match " + Py.Str(pattern);
        var n = v.Length;
        if (field.Get("length") != null && n != Py.ToInt(field["length"]))
            return "'" + v + "' must be " + Py.Str(field["length"]) + " characters";
        if (field.Get("min_length") != null && n < Py.ToInt(field["min_length"]))
            return "'" + v + "' is shorter than " + Py.Str(field["min_length"]);
        if (field.Get("max_length") != null && n > Py.ToInt(field["max_length"]))
            return "'" + v + "' is longer than " + Py.Str(field["max_length"]);
        return null;
    }

    /// <summary>[(field_name, reason)] for one name ([] = compliant).</summary>
    public static List<(string field, string reason)> CheckName(string? name, Dict tscheme)
    {
        var delimValue = tscheme["delimiter"];
        var fields = Fields(tscheme["fields"]);
        List<string> parts;
        if (Py.Truthy(delimValue))
        {
            var delim = delimValue as string ?? throw new FormatException("must be str, not " + Py.TypeName(delimValue));
            parts = (name ?? "").Split(new[] { delim }, StringSplitOptions.None).ToList();
        }
        else
        {
            parts = new List<string> { name ?? "" };
        }
        var required = fields.Count(f => !Py.Truthy(f.Get("optional")));
        if (parts.Count > fields.Count || parts.Count < required)
        {
            return new List<(string, string)>
            {
                ("structure", "expected " + fields.Count + " field(s) separated by '" + Py.Str(delimValue) + "', found "
                              + parts.Count),
            };
        }
        while (parts.Count < fields.Count)
            parts.Add("");
        var errors = new List<(string, string)>();
        for (var i = 0; i < fields.Count; i++)
        {
            var reason = CheckField(fields[i], parts[i]);
            if (!string.IsNullOrEmpty(reason))
                errors.Add((Py.Str(fields[i].Get("name", "?")), reason!));
        }
        return errors;
    }

    /// <summary>items: [(id, name)] -> findings (one summary finding per violated field).</summary>
    public static List<Dict> CheckItems<TId>(IEnumerable<(TId id, string? name)> items, Dict scheme, string target,
        string? label = null, int maxExamples = 15)
    {
        var ts = TargetScheme(scheme, target);
        if (ts == null)
            return new List<Dict>();
        label = !string.IsNullOrEmpty(label) ? label : target.Replace("_", " ");
        var perField = new Dictionary<string, long>(StringComparer.Ordinal);
        var badIds = new Lst();
        var examples = new Lst();
        var all = items.ToList();
        foreach (var (eid, name) in all)
        {
            var errs = CheckName(name, ts);
            if (errs.Count == 0)
                continue;
            badIds.Add(eid);
            if (examples.Count < maxExamples)
            {
                examples.Add(new Dict
                {
                    ["id"] = eid, ["name"] = name,
                    ["errors"] = errs.Select(e => (object?)(e.field + ": " + e.reason)).ToList(),
                });
            }
            foreach (var (field, _) in errs)
                perField[field] = (perField.TryGetValue(field, out var c) ? c : 0) + 1;
        }
        if (badIds.Count == 0)
            return new List<Dict>();
        var fieldsViolated = new Dict();
        foreach (var kv in perField.OrderBy(kv => kv.Key, StringComparer.Ordinal))
            fieldsViolated[kv.Key] = kv.Value;
        var description = ts.Get("description");
        return new List<Dict>
        {
            Rules.Finding("iso19650", ts["severity"],
                badIds.Count + " of " + all.Count + " " + label + " do not follow the naming scheme", badIds,
                recommendation: Py.Truthy(description)
                    ? Py.Str(description)
                    : "Rename to the project naming standard (batch_rename with dry_run).",
                extra: new Dict
                {
                    ["target"] = target,
                    ["fields_violated"] = fieldsViolated,
                    ["examples"] = examples,
                    ["scheme"] = Fields(ts["fields"]).Select(f => f.Get("name")).ToList(),
                    ["delimiter"] = ts["delimiter"],
                }),
        };
    }
}
