namespace RvtssHost;

/// <summary>Port of revit_mcp/utils.py.</summary>
public static class Utils
{
    /// <summary>
    /// Safely normalize string values, always returning text: null gives "Unnamed", text is stripped,
    /// any other value (a number, a .NET object) is converted like Python's unicode() and stripped.
    /// </summary>
    public static string NormalizeString(object? text)
    {
        if (text == null)
            return "Unnamed";
        if (text is string s)
            return s.Trim();
        try { return Py.Str(text).Trim(); }
        catch { return "Unnamed"; }
    }

    /// <summary>The integer value of an ElementId (Int64 on every supported Revit version).</summary>
    public static long ElementIdValue(DB.ElementId elementId) => elementId.Value;

    /// <summary>
    /// Get the name of a Revit element.
    /// Useful for both FamilySymbol and other elements. "" for null.
    /// </summary>
    public static string GetElementName(DB.Element? element) => element == null ? "" : element.Name;

    /// <summary>Safely find a family symbol by name.</summary>
    public static DB.FamilySymbol? FindFamilySymbolSafely(DB.Document doc, object? targetFamilyName, object? targetTypeName = null)
    {
        // One bad symbol must not end the whole search ("Family type not found" for a type that exists).
        // Compare per symbol, safely.
        var famKey = NormalizeString(targetFamilyName).Trim().ToLowerInvariant();
        var typeKey = Py.Truthy(targetTypeName) ? NormalizeString(targetTypeName).Trim().ToLowerInvariant() : null;
        try
        {
            var collector = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol));
            foreach (var element in collector)
            {
                try
                {
                    if (element is not DB.FamilySymbol symbol)
                        continue;
                    if (NormalizeString(symbol.Family.Name).Trim().ToLowerInvariant() != famKey)
                        continue;
                    if (typeKey == null || NormalizeString(GetElementName(symbol)).Trim().ToLowerInvariant() == typeKey)
                        return symbol;
                }
                catch { /* next symbol */ }
            }
            return null;
        }
        catch (Exception e)
        {
            Log.Write("Error finding family symbol: " + e.Message);
            return null;
        }
    }
}
