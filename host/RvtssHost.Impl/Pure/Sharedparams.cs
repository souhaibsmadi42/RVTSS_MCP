using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Read-only parser for Revit shared parameter files (.txt).
///
/// Writing is always done through the Revit API (DefinitionFile) so Revit keeps
/// control of the file format and existing GUIDs are never rewritten.
/// </summary>
public static class Sharedparams
{
    private static readonly Regex Guid = new(
        "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", RegexOptions.CultureInvariant);

    public static bool IsGuid(string? text) => !string.IsNullOrEmpty(text) && Guid.IsMatch(text!.Trim());

    private static bool StartsWith(byte[] data, params byte[] bom)
    {
        if (data.Length < bom.Length)
            return false;
        for (var i = 0; i < bom.Length; i++)
            if (data[i] != bom[i])
                return false;
        return true;
    }

    /// <summary>Read a shared parameter file honouring the UTF-16 BOM Revit writes.</summary>
    public static string ReadText(string path)
    {
        var data = File.ReadAllBytes(path);
        if (StartsWith(data, 0xff, 0xfe))
            return new UnicodeEncoding(false, false, true).GetString(data, 2, data.Length - 2);
        if (StartsWith(data, 0xfe, 0xff))
            return new UnicodeEncoding(true, false, true).GetString(data, 2, data.Length - 2);
        var strict = new UTF8Encoding(false, true);
        if (StartsWith(data, 0xef, 0xbb, 0xbf))
            return strict.GetString(data, 3, data.Length - 3);
        try
        {
            return strict.GetString(data);
        }
        catch (DecoderFallbackException)
        {
            // latin-1: every byte is the code point
            var chars = new char[data.Length];
            for (var i = 0; i < data.Length; i++)
                chars[i] = (char)data[i];
            return new string(chars);
        }
    }

    private static string Field(Dict row, string key, string def) => row.TryGetValue(key, out var v) ? (string)v! : def;

    /// <summary>
    /// Parse shared parameter file text.
    ///
    /// Returns {"meta": {...}, "groups": {id: name}, "params": [ {...} ], "issues": [...]}
    /// </summary>
    public static Dict Parse(string text)
    {
        var meta = new Dict();
        var groups = new Dict();
        // a GROUP row without an ID column has the key None in Python; in JSON that is "null"
        var groupsById = new Dictionary<string, object?>(StringComparer.Ordinal);
        var prms = new List<Dict>();
        var issues = new List<Dict>();
        var headers = new Dictionary<string, List<string>>(StringComparer.Ordinal);
        // io.StringIO yields lines ending at "\n" only
        var lines = text.Split(new[] { '\n' });
        var count = lines.Length;
        if (count > 0 && lines[count - 1].Length == 0)
            count--;
        for (var n = 0; n < count; n++)
        {
            long lineno = n + 1;
            var line = lines[n].TrimEnd('\r', '\n');
            if (line.Trim().Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
                continue;
            var cols = line.Split(new[] { '\t' });
            var kind = cols[0];
            if (kind.StartsWith("*", StringComparison.Ordinal))
            {
                headers[kind.Substring(1)] = cols.Skip(1).ToList();
                continue;
            }
            if (!headers.TryGetValue(kind, out var hdr))
            {
                issues.Add(new Dict { ["line"] = lineno, ["issue"] = "Row '" + kind + "' before its header" });
                continue;
            }
            var row = new Dict();
            for (var i = 0; i < hdr.Count && i + 1 < cols.Length; i++)
                row[hdr[i]] = cols[i + 1];
            if (kind == "META")
            {
                meta = row;
            }
            else if (kind == "GROUP")
            {
                var id = row.Get("ID") as string;
                groups[id ?? "null"] = row.Get("NAME");
                if (id != null)
                    groupsById[id] = row.Get("NAME");
            }
            else if (kind == "PARAM")
            {
                prms.Add(new Dict
                {
                    ["guid"] = Field(row, "GUID", ""),
                    ["name"] = Field(row, "NAME", ""),
                    ["datatype"] = Field(row, "DATATYPE", ""),
                    ["datacategory"] = Field(row, "DATACATEGORY", ""),
                    ["group_id"] = Field(row, "GROUP", ""),
                    ["visible"] = Field(row, "VISIBLE", "1") == "1",
                    ["description"] = Field(row, "DESCRIPTION", ""),
                    ["user_modifiable"] = Field(row, "USERMODIFIABLE", "1") == "1",
                    ["hide_when_no_value"] = Field(row, "HIDEINPROPERTIES", "0") == "1",
                    ["line"] = lineno,
                });
            }
        }
        foreach (var p in prms)
        {
            var groupId = (string)p["group_id"]!;
            var group = groupsById.TryGetValue(groupId, out var g) ? g : null;
            p["group"] = group;
            if (group == null)
                issues.Add(new Dict
                {
                    ["line"] = p["line"],
                    ["issue"] = "Parameter '" + (string)p["name"]! + "' references unknown group " + groupId,
                });
            if (!IsGuid((string)p["guid"]!))
                issues.Add(new Dict { ["line"] = p["line"], ["issue"] = "Parameter '" + (string)p["name"]! + "' has an invalid GUID" });
        }
        issues.AddRange(FindDuplicates(prms));
        return new Dict { ["meta"] = meta, ["groups"] = groups, ["params"] = prms, ["issues"] = issues };
    }

    public static List<Dict> FindDuplicates(IEnumerable<object?> @params)
    {
        var issues = new List<Dict>();
        var byGuid = new Dictionary<string, List<Dict>>(StringComparer.Ordinal);
        var byName = new Dictionary<string, List<Dict>>(StringComparer.Ordinal);
        var guidOrder = new List<string>();
        var nameOrder = new List<string>();
        foreach (var item in @params)
        {
            var p = item as Dict ?? throw new InvalidCastException("parameter must be an object");
            var guid = Py.Str(PyX.Item(p, "guid")).ToLowerInvariant();
            var name = Py.Str(PyX.Item(p, "name")).ToLowerInvariant();
            if (!byGuid.TryGetValue(guid, out var gl))
            {
                byGuid[guid] = gl = new List<Dict>();
                guidOrder.Add(guid);
            }
            gl.Add(p);
            if (!byName.TryGetValue(name, out var nl))
            {
                byName[name] = nl = new List<Dict>();
                nameOrder.Add(name);
            }
            nl.Add(p);
        }
        foreach (var guid in guidOrder)
        {
            var ps = byGuid[guid];
            if (ps.Count > 1)
                issues.Add(new Dict
                {
                    ["issue"] = "Duplicate GUID " + guid + " used by " + string.Join(", ",
                        ps.Select(x => Py.Str(x["name"])).Distinct().OrderBy(x => x, StringComparer.Ordinal)),
                    ["severity"] = "error",
                });
        }
        foreach (var name in nameOrder)
        {
            var ps = byName[name];
            if (ps.Count > 1)
                issues.Add(new Dict
                {
                    ["issue"] = "Parameter name '" + Py.Str(ps[0]["name"]) + "' defined " + ps.Count + " times with different GUIDs",
                    ["severity"] = "warning",
                });
        }
        return issues;
    }

    public static Dict ParseFile(string path) => Parse(ReadText(path));
}
