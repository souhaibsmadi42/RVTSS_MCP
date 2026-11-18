using System.Globalization;
using System.Text.RegularExpressions;

namespace RvtssHost.Modules;

/// <summary>
/// Color management functionality for Revit elements: port of revit_mcp/colors.py.
/// Provides tools for color splashing elements based on parameter values.
/// </summary>
public static partial class Colors
{
    private static readonly Random Rng = new();

    /// <summary>Register color-related routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        api.Raw("/color_splash/", new[] { "POST" }, ColorSplash, apiContext: true);
        api.Raw("/clear_colors/", new[] { "POST" }, ClearColors, apiContext: true);
        api.Raw("/list_category_parameters/", new[] { "POST" }, ListParameters, apiContext: true);
    }

    // ---------------------------------------------------------------- small helpers
    /// <summary>DB.Color(r, g, b): out-of-range values raise OverflowException as the .NET call from Python did.</summary>
    private static DB.Color MakeColor(int r, int g, int b) => new(checked((byte)r), checked((byte)g), checked((byte)b));

    /// <summary>str(float) of IronPython 2 (12 significant digits).</summary>
    private static string PyFloatStr(double d)
    {
        if (double.IsNaN(d)) return "nan";
        if (double.IsInfinity(d)) return d > 0 ? "inf" : "-inf";
        var s = d.ToString("G12", CultureInfo.InvariantCulture);
        if (s.IndexOf('E') >= 0)
            return s.Replace("E", "e");
        if (s.IndexOf('.') < 0)
            s += ".0";
        return s;
    }

    private static string PyTypeName(object? v) => v switch
    {
        null => "NoneType",
        string => "str",
        bool => "bool",
        long or int => "int",
        double or float => "float",
        Dict => "dict",
        Lst => "list",
        _ => v.GetType().Name,
    };

    private static double Num(object? v) => v switch
    {
        long l => l,
        int i => i,
        double d => d,
        _ => 0.0,
    };

    private static bool IsNumber(object? v) => v is long || v is int || v is double;

    // ------------------------------------------------------------------ colors
    /// <summary>Generate visually distinct colors using predefined RGB values.</summary>
    public static List<DB.Color> GenerateDistinctColors(int count)
    {
        if (count == 0)
            return new List<DB.Color>();

        // Predefined RGB colors that are visually distinct
        var baseColors = new (int, int, int)[]
        {
            (255, 0, 0),  // Red
            (0, 255, 0),  // Green
            (0, 0, 255),  // Blue
            (255, 255, 0),  // Yellow
            (255, 0, 255),  // Magenta
            (0, 255, 255),  // Cyan
            (255, 128, 0),  // Orange
            (128, 0, 255),  // Purple
            (255, 128, 128),  // Pink
            (128, 255, 128),  // Light Green
            (128, 128, 255),  // Light Blue
            (255, 255, 128),  // Light Yellow
            (128, 0, 0),  // Dark Red
            (0, 128, 0),  // Dark Green
            (0, 0, 128),  // Dark Blue
            (128, 128, 0),  // Olive
            (128, 0, 128),  // Dark Magenta
            (0, 128, 128),  // Teal
            (192, 192, 192),  // Silver
            (128, 128, 128),  // Gray
            (255, 192, 203),  // Light Pink
            (255, 165, 0),  // Orange Red
            (255, 20, 147),  // Deep Pink
            (50, 205, 50),  // Lime Green
            (30, 144, 255),  // Dodger Blue
        };

        var colors = new List<DB.Color>();
        for (var i = 0; i < count; i++)
        {
            int r, g, b;
            if (i < baseColors.Length)
            {
                // Use predefined colors
                (r, g, b) = baseColors[i];
            }
            else
            {
                // Generate additional colors by cycling and modifying
                var baseIdx = i % baseColors.Length;
                var cycle = i / baseColors.Length;
                (r, g, b) = baseColors[baseIdx];

                // Modify brightness to create variations
                var factor = 1.0 - (cycle * 0.15);  // Reduce brightness by 15% each cycle
                factor = Math.Max(0.3, factor);  // Don't go too dark

                r = (int)(r * factor);
                g = (int)(g * factor);
                b = (int)(b * factor);
            }

            colors.Add(MakeColor(r, g, b));
        }

        return colors;
    }

    /// <summary>Generate gradient colors from blue to red with better distribution.</summary>
    public static List<DB.Color> GenerateGradientColors(int count)
    {
        if (count <= 1)
            return new List<DB.Color> { MakeColor(255, 0, 0) };

        var colors = new List<DB.Color>();
        for (var i = 0; i < count; i++)
        {
            // Create more distinct gradient from blue to red
            var ratio = (double)i / (count - 1);

            // Use HSV color space for better distribution
            var red = (int)(255 * ratio);
            var green = (int)(255 * (1 - Math.Abs(2 * ratio - 1)));  // Peak at middle
            var blue = (int)(255 * (1 - ratio));

            colors.Add(MakeColor(red, green, blue));
        }

        return colors;
    }

    /// <summary>Interpolate color based on position (0.0 to 1.0) for smooth gradients.</summary>
    public static DB.Color InterpolateColor(double position)
    {
        // Clamp position to valid range
        position = Math.Max(0.0, Math.Min(1.0, position));

        // Blue to Red gradient with green in middle
        var red = (int)(255 * position);
        var green = (int)(255 * (1 - Math.Abs(2 * position - 1)));  // Peak at middle
        var blue = (int)(255 * (1 - position));

        return MakeColor(red, green, blue);
    }

    /// <summary>Check if current view is compatible with color overrides: compatibility status and recommendations.</summary>
    public static Dict CheckViewCompatibility(DB.Document doc)
    {
        try
        {
            var activeView = doc.ActiveView;

            // Check visual style
            var visualStyleParam = activeView.get_Parameter(DB.BuiltInParameter.MODEL_GRAPHICS_STYLE);
            if (visualStyleParam != null)
            {
                var styleId = visualStyleParam.AsInteger();

                // Recommend better visual styles for color visibility
                if (styleId == 0 || styleId == 4)  // Wireframe or certain realistic modes
                {
                    return new Dict
                    {
                        ["warning"] = "Current visual style may not show colors well",
                        ["recommendation"] = "Try switching to 'Hidden Line' or 'Shaded' visual style",
                        ["current_style_id"] = (long)styleId,
                    };
                }
            }

            return new Dict { ["status"] = "ok" };
        }
        catch
        {
            return new Dict { ["status"] = "unknown" };
        }
    }

    /// <summary>int(text, 16) for the short slices hex_to_rgb cuts out; ValueError on anything else.</summary>
    private static int ParseHexSlice(string slice)
    {
        var t = slice.Trim();
        var neg = false;
        if (t.StartsWith("+", StringComparison.Ordinal) || t.StartsWith("-", StringComparison.Ordinal))
        {
            neg = t[0] == '-';
            t = t.Substring(1);
        }
        if (t.Length == 0)
            throw new FormatException("invalid literal for int() with base 16: '" + slice + "'");
        var v = 0;
        foreach (var c in t)
        {
            int dgt;
            if (c >= '0' && c <= '9') dgt = c - '0';
            else if (c >= 'a' && c <= 'f') dgt = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') dgt = c - 'A' + 10;
            else throw new FormatException("invalid literal for int() with base 16: '" + slice + "'");
            v = v * 16 + dgt;
        }
        return neg ? -v : v;
    }

    /// <summary>Convert hex color string to RGB tuple ("#FF0000" or "FF0000"); red for an invalid string.</summary>
    public static (int r, int g, int b) HexToRgb(object? hexColor)
    {
        if (hexColor is not string hex)
            throw new InvalidOperationException($"'{PyTypeName(hexColor)}' object has no attribute 'lstrip'");

        // Remove # if present
        hex = hex.TrimStart('#');

        // Convert to RGB
        try
        {
            var vals = new int[3];
            for (var k = 0; k < 3; k++)
            {
                var i = k * 2;
                var slice = i >= hex.Length ? "" : hex.Substring(i, Math.Min(2, hex.Length - i));
                vals[k] = ParseHexSlice(slice);
            }
            return (vals[0], vals[1], vals[2]);
        }
        catch (FormatException)
        {
            Log.Write("Invalid hex color: " + hex + ". Using red as fallback.");
            return (255, 0, 0);
        }
    }

    // ------------------------------------------------------- parameter values
    /// <summary>Safely get parameter value from element: the value as string, or "No Value" if not found.</summary>
    public static string GetParameterValueSafe(DB.Element element, string parameterName)
    {
        try
        {
            // Try to get parameter by name
            var param = element.LookupParameter(parameterName);
            if (param != null && param.HasValue)
            {
                string? value;
                if (param.StorageType == DB.StorageType.String)
                    value = param.AsString();
                else if (param.StorageType == DB.StorageType.Integer)
                    value = Py.Str((long)param.AsInteger());
                else if (param.StorageType == DB.StorageType.Double)
                    value = PyFloatStr(Py.Round(param.AsDouble(), 2));
                else if (param.StorageType == DB.StorageType.ElementId)
                {
                    var elemId = param.AsElementId();
                    if (elemId != null && elemId != DB.ElementId.InvalidElementId)
                        value = Py.Str(Utils.ElementIdValue(elemId));
                    else
                        value = "No Value";
                }
                else
                {
                    value = !string.IsNullOrEmpty(param.AsValueString()) ? param.AsValueString() : "No Value";
                }

                return !string.IsNullOrEmpty(value) ? Utils.NormalizeString(value) : "No Value";
            }

            return "No Value";
        }
        catch
        {
            return "No Value";
        }
    }

    /// <summary>The Name of the element an ElementId parameter points to, or null (hasattr(elem, "Name") and elem.Name).</summary>
    private static string? ElementIdParamName(DB.Element element, DB.ElementId idVal)
    {
        try
        {
            var elem = element.Document.GetElement(idVal);
            if (elem != null)
            {
                var n = elem.Name;
                return string.IsNullOrEmpty(n) ? "None" : n;
            }
        }
        catch { /* fall through */ }
        return null;
    }

    private static bool IsYesNo(DB.Parameter param) => param.Definition.GetDataType() == DB.SpecTypeId.Boolean.YesNo;

    /// <summary>Improved parameter value extraction based on the baseline code: the value as string, or "None" if not found.</summary>
    public static string GetParameterValueImproved(DB.Element element, string parameterName)
    {
        try
        {
            // Try to get parameter by name from element
            foreach (DB.Parameter param in element.Parameters)
            {
                if (param.Definition.Name == parameterName)
                {
                    if (!param.HasValue)
                        return "None";

                    if (param.StorageType == DB.StorageType.Double)
                    {
                        return OrNone(param.AsValueString());
                    }
                    else if (param.StorageType == DB.StorageType.ElementId)
                    {
                        var idVal = param.AsElementId();
                        if (idVal != null && idVal != DB.ElementId.InvalidElementId)
                        {
                            var n = ElementIdParamName(element, idVal);
                            if (n != null)
                                return n;
                        }
                        return "None";
                    }
                    else if (param.StorageType == DB.StorageType.Integer)
                    {
                        // Handle Yes/No parameters
                        try
                        {
                            if (IsYesNo(param))
                                return param.AsInteger() == 1 ? "True" : "False";

                            var vs = param.AsValueString();
                            return !string.IsNullOrEmpty(vs) ? vs : Py.Str((long)param.AsInteger());
                        }
                        catch
                        {
                            return Py.Str((long)param.AsInteger());
                        }
                    }
                    else if (param.StorageType == DB.StorageType.String)
                    {
                        return OrNone(param.AsString());
                    }
                    else
                    {
                        return OrNone(param.AsValueString());
                    }
                }
            }

            // Try type parameters if not found in instance
            try
            {
                var elementType = element.Document.GetElement(element.GetTypeId());
                if (elementType != null)
                {
                    foreach (DB.Parameter param in elementType.Parameters)
                    {
                        if (param.Definition.Name == parameterName)
                        {
                            if (!param.HasValue)
                                return "None";

                            if (param.StorageType == DB.StorageType.Double)
                            {
                                return OrNone(param.AsValueString());
                            }
                            else if (param.StorageType == DB.StorageType.ElementId)
                            {
                                var idVal = param.AsElementId();
                                if (idVal != null && idVal != DB.ElementId.InvalidElementId)
                                {
                                    var n = ElementIdParamName(element, idVal);
                                    if (n != null)
                                        return n;
                                }
                                // no return here in the Python: the search goes on with the next parameter
                            }
                            else if (param.StorageType == DB.StorageType.Integer)
                            {
                                var vs = param.AsValueString();
                                return !string.IsNullOrEmpty(vs) ? vs : Py.Str((long)param.AsInteger());
                            }
                            else if (param.StorageType == DB.StorageType.String)
                            {
                                return OrNone(param.AsString());
                            }
                            else
                            {
                                return OrNone(param.AsValueString());
                            }
                        }
                    }
                }
            }
            catch { /* type lookup failed */ }

            return "None";
        }
        catch
        {
            return "None";
        }
    }

    /// <summary>`x or "None"`</summary>
    private static string OrNone(string? s) => string.IsNullOrEmpty(s) ? "None" : s!;

    /// <summary>Clean parameter values to be JSON-safe by removing special characters.</summary>
    public static string CleanParameterValueForJson(object? paramValue)
    {
        if (!Py.Truthy(paramValue) || (paramValue is string ps && ps == "None"))
            return "None";

        try
        {
            var valueStr = Py.Str(paramValue);
            var stripped = valueStr.Replace(".", "").Replace("-", "").Replace("+", "");
            if (stripped.Length > 0 && stripped.All(char.IsDigit))
            {
                if (Py.TryFloat(valueStr, out var floatVal))
                    return floatVal.ToString("F2", CultureInfo.InvariantCulture);
            }

            var cleaned = Regex.Replace(valueStr, @"[^\x20-\x7E]", "");

            cleaned = Regex.Replace(cleaned, @"[^\w\s\.\-\(\)\/\+\=\:\,]", "");
            cleaned = Regex.Replace(cleaned, @"\s+", " ").Trim();
            return cleaned.Length > 0 ? cleaned : "None";
        }
        catch
        {
            return "None";
        }
    }

    /// <summary>JSON-safe parameter value extraction (uses the sorting-optimized method).</summary>
    public static string GetParameterValueJsonSafe(DB.Element element, string parameterName)
    {
        try
        {
            var (_, displayValue) = GetParameterValueForSorting(element, parameterName);
            return CleanParameterValueForJson(displayValue);
        }
        catch (Exception e)
        {
            Log.Write($"Error getting parameter {parameterName} from element: {e.Message}");
            return "None";
        }
    }

    public static string SafeColorToHex(DB.Color color)
    {
        try
        {
            var r = Math.Max(0, Math.Min(255, (int)color.Red));
            var g = Math.Max(0, Math.Min(255, (int)color.Green));
            var b = Math.Max(0, Math.Min(255, (int)color.Blue));
            return $"#{r:x2}{g:x2}{b:x2}";
        }
        catch
        {
            return "#FF0000";
        }
    }

    /// <summary>Get the solid fill pattern ID for the document, or null if not found.</summary>
    public static DB.ElementId? SolidFillPatternId(DB.Document doc)
    {
        try
        {
            // Get all fill patterns
            var collector = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement));

            foreach (var element in collector)
            {
                var patternElem = (DB.FillPatternElement)element;
                var pattern = patternElem.GetFillPattern();
                if (pattern.IsSolidFill)
                    return patternElem.Id;
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Generate a random RGB color.</summary>
    public static (int r, int g, int b) GenerateRandomColor() => (Rng.Next(0, 256), Rng.Next(0, 256), Rng.Next(0, 256));

    /// <summary>
    /// Safely convert a string value to float for sorting, based on script.py approach:
    /// the converted value or infinity for non-numeric values.
    /// </summary>
    public static double SafeFloatConversion(string? valueStr)
    {
        if (string.IsNullOrEmpty(valueStr) || valueStr == "None")
            return double.PositiveInfinity;  // Put "None" values at the end

        try
        {
            // Handle unit suffixes like in script.py
            var cleanValue = valueStr!.Trim();

            // Check if it has unit suffix (non-digit characters at the end)
            var suffixIndex = 0;
            for (var k = cleanValue.Length - 1; k >= 0; k--)
            {
                var ch = cleanValue[k];
                if (char.IsDigit(ch) || ch == '.' || ch == '-' || ch == '+')
                    break;
                suffixIndex++;
            }

            // Remove unit suffix
            var numericPart = suffixIndex > 0 ? cleanValue.Substring(0, cleanValue.Length - suffixIndex) : cleanValue;

            return Py.TryFloat(numericPart, out var f) ? f : double.PositiveInfinity;
        }
        catch
        {
            return double.PositiveInfinity;  // Non-numeric values go to end
        }
    }

    /// <summary>
    /// Get parameter value optimized for numeric sorting, following script.py pattern:
    /// (raw_value, display_value) for sorting and display. raw_value is a double, a long or a string.
    /// </summary>
    public static (object raw, string display) GetParameterValueForSorting(DB.Element element, string parameterName)
    {
        try
        {
            // Try instance parameters first
            foreach (DB.Parameter param in element.Parameters)
            {
                if (param.Definition.Name == parameterName)
                {
                    if (!param.HasValue)
                        return ("None", "None");
                    return SortingValue(element, param, true)!.Value;
                }
            }

            // Try type parameters if not found in instance
            try
            {
                var elementType = element.Document.GetElement(element.GetTypeId());
                if (elementType != null)
                {
                    foreach (DB.Parameter param in elementType.Parameters)
                    {
                        if (param.Definition.Name == parameterName)
                        {
                            if (!param.HasValue)
                                return ("None", "None");
                            return SortingValue(element, param, false)!.Value;
                        }
                    }
                }
            }
            catch { /* type lookup failed */ }

            return ("None", "None");
        }
        catch
        {
            return ("None", "None");
        }
    }

    /// <summary>The (raw, display) pair of a parameter that has a value. The instance and the type branch of the
    /// Python were identical copies; instance: true only matters for nothing here (kept for readability).</summary>
    private static (object raw, string display)? SortingValue(DB.Element element, DB.Parameter param, bool instance)
    {
        if (param.StorageType == DB.StorageType.Double)
        {
            // Get both raw and display values
            var rawValue = param.AsDouble();
            var vs = param.AsValueString();
            var displayValue = !string.IsNullOrEmpty(vs) ? vs! : PyFloatStr(rawValue);
            return (rawValue, displayValue);
        }
        else if (param.StorageType == DB.StorageType.Integer)
        {
            // Handle Yes/No and regular integers
            try
            {
                if (IsYesNo(param))
                {
                    var boolVal = param.AsInteger() == 1 ? "True" : "False";
                    return (boolVal, boolVal);
                }

                long intValue = param.AsInteger();
                var vs = param.AsValueString();
                var displayValue = !string.IsNullOrEmpty(vs) ? vs! : Py.Str(intValue);
                return (intValue, displayValue);
            }
            catch
            {
                long intValue = param.AsInteger();
                return (intValue, Py.Str(intValue));
            }
        }
        else if (param.StorageType == DB.StorageType.String)
        {
            var stringValue = OrNone(param.AsString());
            return (stringValue, stringValue);
        }
        else if (param.StorageType == DB.StorageType.ElementId)
        {
            var idVal = param.AsElementId();
            if (idVal != null && idVal != DB.ElementId.InvalidElementId)
            {
                try
                {
                    var elem = element.Document.GetElement(idVal);
                    if (elem != null)
                    {
                        var elemName = OrNone(elem.Name);
                        return (elemName, elemName);
                    }
                }
                catch { /* fall through */ }
            }
            return ("None", "None");
        }
        else
        {
            var valueStr = OrNone(param.AsValueString());
            return (valueStr, valueStr);
        }
    }

    // ------------------------------------------------------------ sort key
    private readonly struct SortKey
    {
        public readonly double Tier;
        public readonly double Num;
        public readonly string Str;

        public SortKey(double tier, double num, string str)
        {
            Tier = tier;
            Num = num;
            Str = str;
        }
    }

    private sealed class SortKeyComparer : IComparer<SortKey>
    {
        public int Compare(SortKey a, SortKey b)
        {
            var c = a.Tier.CompareTo(b.Tier);
            if (c != 0)
                return c;
            if (a.Tier == 1.5)
                return string.CompareOrdinal(a.Str, b.Str);
            return a.Num.CompareTo(b.Num);
        }
    }

    /// <summary>Find a category of the document by exact name.</summary>
    private static DB.Category? FindCategory(DB.Document doc, object? categoryName)
    {
        foreach (DB.Category cat in doc.Settings.Categories)
        {
            if (categoryName is string s && cat.Name == s)
                return cat;
        }
        return null;
    }

    /// <summary>A parameter name from the request; a non-text value can never equal a parameter name.</summary>
    private static string ParamNameText(object? parameterName) => parameterName as string ?? "\u0000";

    // ------------------------------------------------------- color splash
    /// <summary>
    /// Color elements in a category based on parameter values with proper gradient support.
    /// Returns the result dict; a Response only when read-only mode refuses the change.
    /// </summary>
    public static object ColorElementsByParameter(DB.Document doc, object? categoryName, object? parameterName,
        object? useGradient = null, object? customColors = null)
    {
        try
        {
            var useGradientOn = Py.Truthy(useGradient);
            var parameterText = ParamNameText(parameterName);

            // Find the category
            var targetCategory = FindCategory(doc, categoryName);

            if (targetCategory == null)
            {
                return new Dict
                {
                    ["status"] = "error",
                    ["message"] = $"Category '{Py.Str(categoryName)}' not found",
                };
            }

            // Get elements from the category
            var collector = new DB.FilteredElementCollector(doc)
                .OfCategoryId(targetCategory.Id)
                .WhereElementIsNotElementType();
            var elements = collector.ToElements();

            if (elements.Count == 0)
            {
                return new Dict
                {
                    ["status"] = "error",
                    ["message"] = $"No elements found in category '{Py.Str(categoryName)}'",
                };
            }

            // Group elements by parameter value using improved method
            var parameterGroups = new Dictionary<string, List<DB.Element>>();
            var groupOrder = new List<string>();  // dict order of the Python (insertion)
            var valueData = new Dictionary<string, object>();  // Store both raw and display values

            foreach (var element in elements)
            {
                var (rawValue, displayValue) = GetParameterValueForSorting(element, parameterText);

                // Use display value as key for grouping
                if (!parameterGroups.TryGetValue(displayValue, out var grp))
                {
                    grp = new List<DB.Element>();
                    parameterGroups[displayValue] = grp;
                    groupOrder.Add(displayValue);
                }
                grp.Add(element);

                // Store raw value for sorting
                if (!valueData.ContainsKey(displayValue))
                    valueData[displayValue] = rawValue;
            }

            // Sort values properly based on their type and content
            // Advanced sorting key that handles different data types
            SortKey SortKeyOf(string displayValue)
            {
                var rawValue = valueData[displayValue];

                // Handle None values
                if (displayValue == "None" || (rawValue is string rs && rs == "None"))
                    return new SortKey(2, 0, "");  // Put None at the end

                // Handle boolean values
                if (displayValue == "True" || displayValue == "False")
                    return new SortKey(1, displayValue == "False" ? 0 : 1, "");

                // Handle numeric values (int or float)
                if (IsNumber(rawValue))
                    return new SortKey(0, Num(rawValue), "");

                // Handle string values that might contain numbers
                try
                {
                    var numericSortValue = SafeFloatConversion(displayValue);
                    if (!double.IsPositiveInfinity(numericSortValue))
                        return new SortKey(0, numericSortValue, "");
                }
                catch { }

                // Fallback to string sorting
                return new SortKey(1.5, 0, displayValue.ToLowerInvariant());
            }

            var comparer = new SortKeyComparer();

            // Check for numeric gradient mode
            var isNumericGradient = false;
            if (useGradientOn)
            {
                var low = Py.Str(parameterName).ToLowerInvariant();
                foreach (var name in new[] { "length", "longueur", "area", "volume", "height", "width", "thickness" })
                {
                    if (low.IndexOf(name, StringComparison.Ordinal) >= 0)
                    {
                        isNumericGradient = true;
                        break;
                    }
                }
            }

            List<string> uniqueValues;
            int valueCount;
            var valuePositions = new Dictionary<string, double>();

            if (isNumericGradient)
            {
                // For numeric parameters in gradient mode, treat each unique value individually
                // but still group elements with identical values
                uniqueValues = groupOrder.OrderBy(k => SortKeyOf(k), comparer).ToList();
                valueCount = uniqueValues.Count;

                // Create mapping from value to position in gradient
                var numericValues = new List<object>();

                foreach (var displayValue in uniqueValues)
                {
                    var rawValue = valueData[displayValue];
                    if (IsNumber(rawValue))
                        numericValues.Add(rawValue);
                }

                if (numericValues.Count > 0)
                {
                    var minVal = numericValues[0];
                    var maxVal = numericValues[0];
                    foreach (var n in numericValues)
                    {
                        if (Num(n) < Num(minVal)) minVal = n;
                        if (Num(n) > Num(maxVal)) maxVal = n;
                    }

                    foreach (var displayValue in uniqueValues)
                    {
                        var rawValue = valueData[displayValue];
                        if (IsNumber(rawValue) && Num(maxVal) != Num(minVal))
                        {
                            double position;
                            if (rawValue is long a && minVal is long b && maxVal is long c)
                                position = (a - b) / (c - b);  // int / int is integer division in Python 2
                            else
                                position = (Num(rawValue) - Num(minVal)) / (Num(maxVal) - Num(minVal));
                            valuePositions[displayValue] = position;
                        }
                        else
                        {
                            valuePositions[displayValue] = 0.5;
                        }
                    }
                }
                else
                {
                    // Fallback if no numeric values
                    for (var i = 0; i < uniqueValues.Count; i++)
                        valuePositions[uniqueValues[i]] = (double)i / Math.Max(1, uniqueValues.Count - 1);
                }
            }
            else
            {
                uniqueValues = groupOrder.OrderBy(k => SortKeyOf(k), comparer).ToList();
                valueCount = uniqueValues.Count;
            }

            // Generate colors based on the sorted order
            List<DB.Color> colors;
            if (Py.Truthy(customColors))
            {
                // Use custom colors
                colors = new List<DB.Color>();
                var i = 0;
                foreach (var hexColor in PyIter(customColors))
                {
                    if (i >= valueCount)
                        break;
                    var rgb = HexToRgb(hexColor);
                    colors.Add(MakeColor(rgb.r, rgb.g, rgb.b));
                    i++;
                }

                // Fill remaining with distinct colors if needed
                if (colors.Count < valueCount)
                {
                    var remainingCount = valueCount - colors.Count;
                    var additionalColors = GenerateDistinctColors(remainingCount);
                    colors.AddRange(additionalColors);
                }
            }
            else if (useGradientOn && isNumericGradient)
            {
                // Use interpolated colors for numeric gradients
                colors = new List<DB.Color>();
                foreach (var paramValue in uniqueValues)
                {
                    var position = valuePositions.TryGetValue(paramValue, out var p) ? p : 0.5;
                    colors.Add(InterpolateColor(position));
                }
            }
            else if (useGradientOn)
            {
                // Generate proper gradient colors for non-numeric
                colors = GenerateGradientColors(valueCount);
            }
            else
            {
                // Use distinct colors
                colors = GenerateDistinctColors(valueCount);
            }

            // Apply colors to elements
            var colorAssignments = new Dict();
            long elementsColored = 0;
            var solidFillId = SolidFillPatternId(doc);

            var refused = Core.ReadOnlyResponse("color_splash");
            if (refused != null)
                return refused;

            List<DB.View>? otherViews = null;
            using (var t = new DB.Transaction(doc, "Color Elements by Parameter"))
            {
                t.Start();

                // Ensure we have enough colors
                if (colors.Count < valueCount)
                {
                    var additionalNeeded = valueCount - colors.Count;
                    var additionalColors = GenerateDistinctColors(additionalNeeded);
                    colors.AddRange(additionalColors);
                }

                for (var i = 0; i < uniqueValues.Count; i++)
                {
                    var paramValue = uniqueValues[i];
                    var groupElements = parameterGroups[paramValue];

                    // Get color for this group
                    DB.Color color;
                    if (i < colors.Count)
                    {
                        color = colors[i];
                    }
                    else
                    {
                        var rgb = GenerateRandomColor();
                        color = MakeColor(rgb.r, rgb.g, rgb.b);
                    }

                    colorAssignments[paramValue] = new Dict
                    {
                        ["color"] = SafeColorToHex(color),
                        ["element_count"] = (long)groupElements.Count,
                        ["sort_index"] = (long)i,  // Add sort index for debugging
                    };

                    // Apply color override to each element with improved settings
                    var overrideSettings = new DB.OverrideGraphicSettings();
                    overrideSettings.SetProjectionLineColor(color);
                    overrideSettings.SetSurfaceForegroundPatternColor(color);
                    overrideSettings.SetCutForegroundPatternColor(color);
                    overrideSettings.SetCutLineColor(color);
                    overrideSettings.SetProjectionLineWeight(3);  // Make lines more visible

                    if (solidFillId != null)
                    {
                        overrideSettings.SetSurfaceForegroundPatternId(solidFillId);
                        overrideSettings.SetCutForegroundPatternId(solidFillId);
                    }

                    foreach (var element in groupElements)
                    {
                        try
                        {
                            // Apply to active view first (CRITICAL FIX!)
                            var activeView = doc.ActiveView;
                            activeView.SetElementOverrides(element.Id, overrideSettings);
                            elementsColored++;

                            // Optionally apply to other views of same type
                            try
                            {
                                otherViews ??= OtherViewsOfSameType(doc, activeView);
                                foreach (var view in otherViews)
                                    view.SetElementOverrides(element.Id, overrideSettings);
                            }
                            catch
                            {
                                // Don't fail if we can't apply to other views
                            }
                        }
                        catch (Exception e)
                        {
                            Log.Write($"Failed to color element {Utils.ElementIdValue(element.Id)}: {e.Message}");
                        }
                    }
                }

                t.Commit();
            }

            var result = new Dict
            {
                ["status"] = "success",
                ["message"] = $"Successfully colored {elementsColored} elements in {valueCount} color groups",
                ["category"] = categoryName,
                ["parameter"] = parameterName,
                ["color_assignments"] = colorAssignments,
                ["statistics"] = new Dict
                {
                    ["total_elements"] = (long)elements.Count,
                    ["elements_colored"] = elementsColored,
                    ["unique_parameter_values"] = (long)valueCount,
                    ["use_gradient"] = useGradient,
                    ["sorted_values"] = uniqueValues,  // Include sorted values for debugging
                },
            };

            // Add view compatibility warning if needed
            var viewCheck = CheckViewCompatibility(doc);
            if (Py.Truthy(viewCheck.Get("warning")))
                result["view_warning"] = viewCheck;

            return result;
        }
        catch (Exception e)
        {
            Log.Write("Error in color_elements_by_parameter: " + e.Message);
            return new Dict
            {
                ["status"] = "error",
                ["message"] = "Failed to color elements: " + e.Message,
            };
        }
    }

    /// <summary>The non-template views of the same ViewType as the active view, other than the active view.</summary>
    private static List<DB.View> OtherViewsOfSameType(DB.Document doc, DB.View activeView)
    {
        var result = new List<DB.View>();
        var viewType = activeView.ViewType;
        var otherViews = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).WhereElementIsNotElementType();
        foreach (var e in otherViews)
        {
            var view = (DB.View)e;
            if (!view.IsTemplate && view.ViewType == viewType && view.Id != activeView.Id)
                result.Add(view);
        }
        return result;
    }

    /// <summary>`for x in value`: list items, characters of a string, keys of a dict.</summary>
    private static IEnumerable<object?> PyIter(object? v)
    {
        if (v is Lst l)
            return l;
        if (v is string s)
            return s.Select(ch => (object?)ch.ToString());
        if (v is Dict d)
            return d.Keys.Cast<object?>();
        throw new InvalidOperationException($"'{PyTypeName(v)}' object is not iterable");
    }

    // --------------------------------------------------------- clear colors
    /// <summary>Clear color overrides for elements in a category. Returns the result dict (a Response only when read-only mode refuses).</summary>
    public static object ClearElementColors(DB.Document doc, object? categoryName)
    {
        try
        {
            // Find the category
            var targetCategory = FindCategory(doc, categoryName);

            if (targetCategory == null)
            {
                return new Dict
                {
                    ["status"] = "error",
                    ["message"] = $"Category '{Py.Str(categoryName)}' not found",
                };
            }

            // Get elements from the category
            var collector = new DB.FilteredElementCollector(doc)
                .OfCategoryId(targetCategory.Id)
                .WhereElementIsNotElementType();
            var elements = collector.ToElements();

            if (elements.Count == 0)
            {
                return new Dict
                {
                    ["status"] = "warning",
                    ["message"] = $"No elements found in category '{Py.Str(categoryName)}'",
                };
            }

            long elementsCleared = 0;

            // Get active view for clearing overrides
            var activeView = doc.ActiveView;

            var refused = Core.ReadOnlyResponse("clear_colors");
            if (refused != null)
                return refused;

            List<DB.View>? otherViews = null;
            using (var t = new DB.Transaction(doc, "Clear Element Colors"))
            {
                t.Start();

                // Clear overrides for each element in active view
                foreach (var element in elements)
                {
                    try
                    {
                        var emptyOverride = new DB.OverrideGraphicSettings();
                        activeView.SetElementOverrides(element.Id, emptyOverride);
                        elementsCleared++;

                        // Optionally clear from other views of same type
                        try
                        {
                            otherViews ??= OtherViewsOfSameType(doc, activeView);
                            foreach (var view in otherViews)
                                view.SetElementOverrides(element.Id, emptyOverride);
                        }
                        catch
                        {
                            // Don't fail if we can't clear from other views
                        }
                    }
                    catch (Exception e)
                    {
                        Log.Write($"Failed to clear colors for element {Utils.ElementIdValue(element.Id)}: {e.Message}");
                    }
                }

                t.Commit();
            }

            return new Dict
            {
                ["status"] = "success",
                ["message"] = $"Successfully cleared color overrides for {elementsCleared} elements",
                ["category"] = categoryName,
                ["elements_processed"] = elementsCleared,
            };
        }
        catch (Exception e)
        {
            Log.Write("Error in clear_element_colors: " + e.Message);
            return new Dict
            {
                ["status"] = "error",
                ["message"] = "Failed to clear colors: " + e.Message,
            };
        }
    }

    // ------------------------------------------------- list category parameters
    /// <summary>Get available parameters for elements in a category, with their types.</summary>
    public static Dict ListCategoryParameters(DB.Document doc, object? categoryName)
    {
        try
        {
            // Find the category
            var targetCategory = FindCategory(doc, categoryName);

            if (targetCategory == null)
            {
                return new Dict
                {
                    ["status"] = "error",
                    ["message"] = $"Category '{Py.Str(categoryName)}' not found",
                };
            }

            // Get a sample element from the category to check parameters
            var collector = new DB.FilteredElementCollector(doc)
                .OfCategoryId(targetCategory.Id)
                .WhereElementIsNotElementType();
            var elements = collector.ToElements();

            if (elements.Count == 0)
            {
                return new Dict
                {
                    ["status"] = "error",
                    ["message"] = $"No elements found in category '{Py.Str(categoryName)}'",
                };
            }

            // Get parameters from the first element
            var sampleElement = elements.First();
            var parameters = new List<Dict>();

            // Get all parameters
            foreach (DB.Parameter param in sampleElement.Parameters)
            {
                try
                {
                    var paramName = param.Definition.Name;
                    var storageType = param.StorageType.ToString();
                    var hasValue = param.HasValue;

                    // Get a sample value if available (JSON-safe)
                    var sampleValue = "N/A";
                    if (hasValue)
                        sampleValue = GetParameterValueJsonSafe(sampleElement, paramName);

                    parameters.Add(new Dict
                    {
                        ["name"] = paramName,
                        ["storage_type"] = storageType,
                        ["has_value"] = hasValue,
                        ["sample_value"] = sampleValue,
                    });
                }
                catch
                {
                    continue;
                }
            }

            // Sort parameters by name for easier reading
            parameters = parameters.OrderBy(x => (string)x["name"]!, StringComparer.Ordinal).ToList();

            return new Dict
            {
                ["status"] = "success",
                ["category"] = categoryName,
                ["parameter_count"] = (long)parameters.Count,
                ["parameters"] = parameters,
            };
        }
        catch (Exception e)
        {
            Log.Write("Error in list_category_parameters: " + e.Message);
            return new Dict
            {
                ["status"] = "error",
                ["message"] = "Failed to list parameters: " + e.Message,
            };
        }
    }

    // ---------------------------------------------------------------- routes
    /// <summary>The request body as a dict, or the 500 answer the Python gave for a body that is no JSON object.</summary>
    private static Response? BodyProblem(Request request, out Dict data)
    {
        if (request.Data != null)
        {
            data = request.Data;
            return null;
        }
        data = new Dict();
        string msg;
        if (string.IsNullOrWhiteSpace(request.Body))
            msg = "'NoneType' object has no attribute 'get'";
        else if (request.BodyError != null && request.BodyError.StartsWith("Request body must be", StringComparison.Ordinal))
            msg = "'list' object has no attribute 'get'";
        else
            msg = "No JSON object could be decoded";
        return new Response(new Dict { ["error"] = msg }, 500);
    }

    private static Response RouteResult(object result) => result is Response r ? r : new Response(result);

    /// <summary>
    /// Color elements in a category based on parameter values.
    /// Expected JSON payload: category_name, parameter_name, use_gradient (false), custom_colors (optional hex list).
    /// </summary>
    public static Response ColorSplash(Request request)
    {
        try
        {
            var problem = BodyProblem(request, out var data);
            if (problem != null)
                return problem;

            var categoryName = data.Get("category_name");
            var parameterName = data.Get("parameter_name");
            var useGradient = data.Get("use_gradient", false);
            var customColors = data.Get("custom_colors", null);

            if (!Py.Truthy(categoryName) || !Py.Truthy(parameterName))
                return new Response(new Dict { ["error"] = "category_name and parameter_name are required" }, 400);

            var result = ColorElementsByParameter(request.Doc!, categoryName, parameterName, useGradient, customColors);

            return RouteResult(result);
        }
        catch (Exception e)
        {
            Log.Write("Error in color_splash route: " + e.Message);
            return new Response(new Dict { ["error"] = e.Message }, 500);
        }
    }

    /// <summary>Clear color overrides for elements in a category. Expected JSON payload: category_name.</summary>
    public static Response ClearColors(Request request)
    {
        try
        {
            var problem = BodyProblem(request, out var data);
            if (problem != null)
                return problem;

            var categoryName = data.Get("category_name");

            if (!Py.Truthy(categoryName))
                return new Response(new Dict { ["error"] = "category_name is required" }, 400);

            var result = ClearElementColors(request.Doc!, categoryName);

            return RouteResult(result);
        }
        catch (Exception e)
        {
            Log.Write("Error in clear_colors route: " + e.Message);
            return new Response(new Dict { ["error"] = e.Message }, 500);
        }
    }

    /// <summary>Get available parameters for elements in a category. Expected JSON payload: category_name.</summary>
    public static Response ListParameters(Request request)
    {
        try
        {
            var problem = BodyProblem(request, out var data);
            if (problem != null)
                return problem;

            var categoryName = data.Get("category_name");

            if (!Py.Truthy(categoryName))
                return new Response(new Dict { ["error"] = "category_name is required" }, 400);

            var result = ListCategoryParameters(request.Doc!, categoryName);

            return RouteResult(result);
        }
        catch (Exception e)
        {
            Log.Write("Error in list_category_parameters route: " + e.Message);
            return new Response(new Dict { ["error"] = e.Message }, 500);
        }
    }

    // ------------------------------------------------- numeric helpers
    /// <summary>Get the raw numeric value from a parameter, bypassing display formatting (null if not available).</summary>
    public static double? GetNumericParameterRawValue(DB.Parameter param)
    {
        try
        {
            if (param.StorageType == DB.StorageType.Double)
                return param.AsDouble();
            else if (param.StorageType == DB.StorageType.Integer)
                return (double)param.AsInteger();
            else
                return null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Format a numeric value for JSON-safe serialization.</summary>
    public static string FormatNumericForJson(double? value)
    {
        try
        {
            if (value == null)
                return "None";
            var v = value.Value;

            if (double.IsNaN(v))
                return "nan";
            if (double.IsInfinity(v))
                return v > 0 ? "inf" : "-inf";

            // Handle very small values as zero
            if (Math.Abs(v) < 1e-10)
                return "0.000";

            // Handle very large values
            if (Math.Abs(v) > 1e10)
                return v.ToString("0.00e+00", CultureInfo.InvariantCulture);

            // Normal values - use reasonable precision
            return v.ToString("F3", CultureInfo.InvariantCulture);
        }
        catch
        {
            return "None";
        }
    }
}
