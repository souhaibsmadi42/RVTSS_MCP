namespace RvtssHost.Modules;

/// <summary>
/// Python behaviours shared by the Docs group (documentation, annotation, view_setup, graphics): getattr on an
/// enum type, dict access on a request item, and the exception types whose Python names show in error texts
/// ("AttributeError: ...", "KeyError: ...").
/// </summary>
internal static class DocsPy
{
    /// <summary>Python AttributeError (the type name is part of the 500 error text).</summary>
    internal sealed class AttributeError(string message) : Exception(message);

    /// <summary>Python KeyError.</summary>
    internal sealed class KeyError(string message) : Exception(message);

    /// <summary>Python IndexError.</summary>
    internal sealed class IndexError(string message) : Exception(message);

    /// <summary>Python re.error (named like the Python class: the 500 text starts with "error: ").</summary>
    internal sealed class error(string message) : Exception(message);

    /// <summary>str.capitalize(): first character upper case, the rest lower case.</summary>
    internal static string Capitalize(string s) =>
        s.Length == 0 ? s : char.ToUpperInvariant(s[0]) + s.Substring(1).ToLowerInvariant();

    /// <summary>getattr(DB.SomeEnum, name): the member with exactly that name or an AttributeError.</summary>
    internal static T EnumAttr<T>(object? name) where T : struct, Enum
    {
        var text = name as string;
        if (text != null && Enum.TryParse<T>(text, false, out var v) && Enum.IsDefined(typeof(T), v))
            return v;
        throw new AttributeError($"'type' object has no attribute '{Py.Str(name)}'");
    }

    /// <summary>A request item that the code reads with .get(): a dict, else AttributeError.</summary>
    internal static Dict D(object? item)
    {
        if (item is Dict d)
            return d;
        var type = item is string ? "str" : item is Lst ? "list" : item is bool ? "bool" : item is double ? "float"
            : Py.IsInt(item) ? "int" : "NoneType";
        throw new AttributeError($"'{type}' object has no attribute 'get'");
    }

    /// <summary>`str(x).isdigit()` for a request value.</summary>
    internal static bool IsDigits(object? v)
    {
        var s = Py.Str(v);
        return s.Length > 0 && s.All(char.IsDigit);
    }

    /// <summary>`x or default` on a request value.</summary>
    internal static object? Or(object? x, object? def) => Py.Truthy(x) ? x : def;

    /// <summary>`str(name).strip().lower()`</summary>
    internal static string Key(object? name) => Py.Str(name).Trim().ToLowerInvariant();

    /// <summary>`normalize_string(x).lower()`</summary>
    internal static string NLower(object? x) => Utils.NormalizeString(x).ToLowerInvariant();

    /// <summary>The names of Revit objects for a not_found() choices list.</summary>
    internal static IEnumerable<string?> Names(IEnumerable<DB.Element> elements) => elements.Select(e => (string?)e.Name);

    /// <summary>list slice seq[:n]</summary>
    internal static List<T> Head<T>(List<T> seq, int n) => seq.Count <= n ? seq : seq.GetRange(0, n);

    /// <summary>_id_list(ids): a List[ElementId].</summary>
    internal static List<DB.ElementId> IdList(IEnumerable<DB.ElementId> ids) => new(ids);
}
