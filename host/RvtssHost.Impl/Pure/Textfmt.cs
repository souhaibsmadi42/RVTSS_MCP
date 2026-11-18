using System.Globalization;
using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>Python: class TemplateError(ValueError).</summary>
public class TemplateError : FormatException
{
    public TemplateError(string message) : base(message) { }
}

/// <summary>
/// Value templates used by bulk parameter updates and batch renaming.
///
/// Template syntax (any text outside braces is kept verbatim):
///     {n}           running sequence number (start/step configurable)
///     {n:03}        zero padded sequence number
///     {id}          element id
///     {value}       current value of the target parameter / current name
///     {Any Param}   display value of another parameter on the same element
///                   (falls back to the type parameter when not found on the instance)
///     {{ and }}     literal braces
/// </summary>
public static class Textfmt
{
    private static readonly Regex Token = new(@"\{\{|\}\}|\{([^{}:]+)(?::([^{}]*))?\}", RegexOptions.CultureInvariant);

    private static string FormatNumber(long n, string? spec)
    {
        if (string.IsNullOrEmpty(spec))
            return n.ToString(CultureInfo.InvariantCulture);
        try
        {
            return FormatInt(n, "0123456789<>^=+- ".IndexOf(spec![0]) >= 0 ? spec : "");
        }
        catch (FormatException)
        {
            throw new TemplateError("Bad number format '" + spec + "'");
        }
    }

    /// <summary>
    /// format(n, spec) for an integer: [[fill]align][sign][#][0][width][,][.precision][type] with the types
    /// b c d n o x X and the float types e E f F g G %. Throws FormatException where Python raises ValueError.
    /// </summary>
    internal static string FormatInt(long n, string spec)
    {
        if (spec.Length == 0)
            return n.ToString(CultureInfo.InvariantCulture);
        var i = 0;
        var fill = ' ';
        var align = '\0';
        var fillGiven = false;
        if (spec.Length >= 2 && "<>=^".IndexOf(spec[1]) >= 0)
        {
            fill = spec[0];
            align = spec[1];
            fillGiven = true;
            i = 2;
        }
        else if ("<>=^".IndexOf(spec[0]) >= 0)
        {
            align = spec[0];
            i = 1;
        }
        var sign = '-';
        var signGiven = false;
        if (i < spec.Length && "+- ".IndexOf(spec[i]) >= 0)
        {
            sign = spec[i++];
            signGiven = true;
        }
        var alt = false;
        if (i < spec.Length && spec[i] == '#')
        {
            alt = true;
            i++;
        }
        if (i < spec.Length && spec[i] == '0')
        {
            // the 0 flag: zero fill unless a fill character was given, sign-aware unless an alignment was given
            if (!fillGiven)
                fill = '0';
            if (align == '\0')
                align = '=';
            i++;
        }
        var width = 0;
        var widthStart = i;
        while (i < spec.Length && spec[i] >= '0' && spec[i] <= '9')
        {
            if (i - widthStart > 8)
                throw new FormatException("Too many decimal digits in format string");
            width = width * 10 + (spec[i++] - '0');
        }
        var comma = false;
        if (i < spec.Length && spec[i] == ',')
        {
            comma = true;
            i++;
        }
        var precision = -1;
        if (i < spec.Length && spec[i] == '.')
        {
            i++;
            var start = i;
            precision = 0;
            while (i < spec.Length && spec[i] >= '0' && spec[i] <= '9')
            {
                if (i - start > 8)
                    throw new FormatException("Too many decimal digits in format string");
                precision = precision * 10 + (spec[i++] - '0');
            }
            if (i == start)
                throw new FormatException("Format specifier missing precision");
        }
        var type = 'd';
        if (i < spec.Length)
            type = spec[i++];
        if (i != spec.Length)
            throw new FormatException("Invalid format specifier");
        if (align == '\0')
            align = '>';

        string prefix = "";
        string digits;
        var negative = n < 0;
        // magnitude as an unsigned value so long.MinValue works
        var magnitude = negative ? (ulong)(-(n + 1)) + 1UL : (ulong)n;
        switch (type)
        {
            case 'd':
            case 'n':
                if (precision >= 0)
                    throw new FormatException("Precision not allowed in integer format specifier");
                if (type == 'n' && comma)
                    throw new FormatException("Cannot specify ',' with 'n'.");
                digits = magnitude.ToString(CultureInfo.InvariantCulture);
                if (comma)
                    digits = Group(digits);
                break;
            case 'b':
            case 'o':
            case 'x':
            case 'X':
                if (precision >= 0)
                    throw new FormatException("Precision not allowed in integer format specifier");
                if (comma)
                    throw new FormatException("Cannot specify ',' with '" + type + "'.");
                digits = type == 'b' ? ToBase(magnitude, 2) : type == 'o' ? ToBase(magnitude, 8) : ToBase(magnitude, 16);
                if (type == 'X')
                    digits = digits.ToUpperInvariant();
                if (alt)
                    prefix = "0" + type;
                break;
            case 'c':
                if (precision >= 0)
                    throw new FormatException("Precision not allowed in integer format specifier");
                if (signGiven)
                    throw new FormatException("Sign not allowed with integer format specifier 'c'");
                if (alt)
                    throw new FormatException("Alternate form (#) not allowed with integer format specifier 'c'");
                if (comma)
                    throw new FormatException("Cannot specify ',' with 'c'.");
                if (n < 0 || n > 0x10ffff)
                    throw new FormatException("%c arg not in range(0x110000)");
                return Pad(char.ConvertFromUtf32((int)n), "", "", width, fill, align == '=' ? '>' : align, false);
            case 'e':
            case 'E':
            case 'f':
            case 'F':
            case 'g':
            case 'G':
            case '%':
                digits = FormatFloat(magnitude, type, precision < 0 ? 6 : precision, alt);
                if (comma)
                {
                    // group the integer part only
                    var cut = digits.IndexOfAny(new[] { '.', 'e', 'E', '%' });
                    digits = cut < 0 ? Group(digits) : Group(digits.Substring(0, cut)) + digits.Substring(cut);
                }
                break;
            default:
                throw new FormatException("Unknown format code '" + type + "' for object of type 'int'");
        }
        var signText = negative ? "-" : sign == '+' ? "+" : sign == ' ' ? " " : "";
        return Pad(digits, signText, prefix, width, fill, align, comma);
    }

    private static string ToBase(ulong v, int b)
    {
        if (v == 0)
            return "0";
        var sb = new StringBuilder();
        while (v > 0)
        {
            sb.Insert(0, "0123456789abcdef"[(int)(v % (ulong)b)]);
            v /= (ulong)b;
        }
        return sb.ToString();
    }

    private static string Group(string digits)
    {
        var sb = new StringBuilder();
        for (var k = 0; k < digits.Length; k++)
        {
            if (k > 0 && (digits.Length - k) % 3 == 0)
                sb.Append(',');
            sb.Append(digits[k]);
        }
        return sb.ToString();
    }

    private static string Pad(string digits, string sign, string prefix, int width, char fill, char align, bool comma)
    {
        var length = sign.Length + prefix.Length + digits.Length;
        if (length >= width)
            return sign + prefix + digits;
        var pad = width - length;
        switch (align)
        {
            case '<':
                return sign + prefix + digits + new string(fill, pad);
            case '^':
                return new string(fill, pad / 2) + sign + prefix + digits + new string(fill, pad - pad / 2);
            case '=':
                if (fill == '0' && comma)
                {
                    // zero padding takes part in the grouping, and the result never starts with a comma
                    var cut = digits.IndexOfAny(new[] { '.', 'e', 'E', '%' });
                    var head = (cut < 0 ? digits : digits.Substring(0, cut)).Replace(",", "");
                    var tail = cut < 0 ? "" : digits.Substring(cut);
                    while (sign.Length + prefix.Length + Group(head).Length + tail.Length < width)
                        head = "0" + head;
                    return sign + prefix + Group(head) + tail;
                }
                return sign + prefix + new string(fill, pad) + digits;
            default:
                return new string(fill, pad) + sign + prefix + digits;
        }
    }

    /// <summary>The float presentation types for an integer value (Python converts the int to float first).</summary>
    private static string FormatFloat(ulong magnitude, char type, int precision, bool alt)
    {
        var inv = CultureInfo.InvariantCulture;
        string Fixed(string whole, int decimals) =>
            whole + (decimals > 0 ? "." + new string('0', decimals) : alt ? "." : "");
        switch (type)
        {
            case 'f':
            case 'F':
                return Fixed(magnitude.ToString(inv), precision);
            case '%':
                return Fixed(((decimal)magnitude * 100m).ToString("F0", inv), precision) + "%";
            case 'e':
            case 'E':
                return Exponent(magnitude, precision, type, alt);
            default:
            {
                // g / G: precision is the number of significant digits
                var p = precision == 0 ? 1 : precision;
                var exp = magnitude == 0 ? 0 : int.Parse(Exponent(magnitude, p - 1, 'e', false).Split('e')[1], inv);
                string s;
                if (exp >= -4 && exp < p)
                {
                    s = magnitude.ToString(inv);
                    if (alt)
                        s += "." + new string('0', Math.Max(0, p - 1 - exp));
                }
                else
                {
                    s = Exponent(magnitude, p - 1, 'e', alt);
                    if (!alt)
                    {
                        var parts = s.Split('e');
                        if (parts[0].IndexOf('.') >= 0)
                            parts[0] = parts[0].TrimEnd('0').TrimEnd('.');
                        s = parts[0] + "e" + parts[1];
                    }
                }
                return type == 'G' ? s.ToUpperInvariant() : s;
            }
        }
    }

    /// <summary>Python %e: d.ddde+XX with at least two exponent digits.
    /// Worked on the decimal digits of the integer, so an exact half rounds to even as in Python.</summary>
    private static string Exponent(ulong magnitude, int precision, char type, bool alt)
    {
        var digits = magnitude.ToString(CultureInfo.InvariantCulture);
        var exp = digits.Length - 1;
        var want = precision + 1;
        string head;
        if (digits.Length > want)
        {
            var kept = digits.Substring(0, want).ToCharArray();
            var rest = digits.Substring(want);
            var half = "5" + new string('0', rest.Length - 1);
            var cmp = string.CompareOrdinal(rest, half);
            if (cmp > 0 || (cmp == 0 && (kept[want - 1] - '0') % 2 == 1))
            {
                var k = want - 1;
                while (k >= 0 && kept[k] == '9')
                    kept[k--] = '0';
                if (k >= 0)
                {
                    kept[k]++;
                }
                else
                {
                    // 9.99 -> 10.0: one more digit in front, the exponent grows
                    kept = ("1" + new string(kept)).Substring(0, want).ToCharArray();
                    exp++;
                }
            }
            head = new string(kept);
        }
        else
        {
            head = digits + new string('0', want - digits.Length);
        }
        var s = head.Substring(0, 1) + (precision > 0 ? "." + head.Substring(1) : alt ? "." : "")
                + "e+" + exp.ToString("00", CultureInfo.InvariantCulture);
        return type == 'E' ? s.ToUpperInvariant() : s;
    }

    /// <summary>Return the names of the tokens referenced by a template (excluding n/id/value).</summary>
    public static List<string> Tokens(string template)
    {
        var result = new List<string>();
        foreach (Match m in Token.Matches(template))
        {
            if (!m.Groups[1].Success)
                continue;
            var name = m.Groups[1].Value.Trim();
            if (name != "n" && name != "id" && name != "value" && !result.Contains(name))
                result.Add(name);
        }
        return result;
    }

    /// <summary>
    /// Render a template.
    ///
    /// resolver(name) -> string or None. Missing values raise TemplateError so a
    /// bulk update never silently writes half-filled values.
    /// </summary>
    public static string Render(string template, Func<string, object?> resolver, long? n = null,
        object? elementId = null, object? current = null)
    {
        return Token.Replace(template, m =>
        {
            var raw = m.Value;
            if (raw == "{{")
                return "{";
            if (raw == "}}")
                return "}";
            var name = m.Groups[1].Value.Trim();
            var spec = m.Groups[2].Success ? m.Groups[2].Value : null;
            if (name == "n")
            {
                if (n == null)
                    throw new TemplateError("{n} used but no sequence number available");
                return FormatNumber(n.Value, spec);
            }
            if (name == "id")
                return Py.Str(elementId);
            if (name == "value")
                return current == null ? "" : Py.Str(current);
            var val = resolver(name);
            if (val == null)
                throw new TemplateError("Parameter '" + name + "' referenced in template has no value");
            return Py.Str(val);
        });
    }

    /// <summary>Apply a rename rule to a single string. Returns the new string.</summary>
    public static string ApplyRename(string name, object? find = null, object? replace = null, bool regex = false,
        object? prefix = null, object? suffix = null, object? @case = null)
    {
        var result = name;
        if (Py.Truthy(find))
        {
            var findText = find as string ?? throw new FormatException("must be str, not " + Py.TypeName(find));
            var replaceText = Py.Truthy(replace)
                ? replace as string ?? throw new FormatException("must be str, not " + Py.TypeName(replace))
                : "";
            if (regex)
            {
                try
                {
                    result = PureText.Sub(PureText.Re(findText), replaceText, result);
                }
                catch (ArgumentException ex)
                {
                    throw new TemplateError("Invalid regex '" + findText + "': " + ex.Message);
                }
            }
            else
            {
                result = result.Replace(findText, replaceText);
            }
        }
        var mode = @case as string;
        if (mode == "upper")
            result = result.ToUpperInvariant();
        else if (mode == "lower")
            result = result.ToLowerInvariant();
        else if (mode == "title")
            result = Title(result);
        return (Py.Truthy(prefix) ? Py.Str(prefix) : "") + result + (Py.Truthy(suffix) ? Py.Str(suffix) : "");
    }

    /// <summary>str.title(): first letter of every run of letters upper case, the rest lower case.</summary>
    private static string Title(string s)
    {
        var sb = new StringBuilder(s.Length);
        var previousCased = false;
        foreach (var c in s)
        {
            if (char.IsLower(c))
            {
                sb.Append(previousCased ? c : char.ToUpperInvariant(c));
                previousCased = true;
            }
            else if (char.IsUpper(c) || char.GetUnicodeCategory(c) == UnicodeCategory.TitlecaseLetter)
            {
                sb.Append(previousCased ? char.ToLowerInvariant(c) : c);
                previousCased = true;
            }
            else
            {
                sb.Append(c);
                previousCased = false;
            }
        }
        return sb.ToString();
    }

    /// <summary>Characters Revit refuses in names of views, sheets, families, types, etc.
    /// Python name: INVALID_NAME_CHARS (the function invalid_name_chars takes the name InvalidNameChars).</summary>
    public const string InvalidNameCharSet = "\\:{}[]|;<>?`~";

    public static List<string> InvalidNameChars(string name) =>
        name.Where(c => InvalidNameCharSet.IndexOf(c) >= 0).Distinct().OrderBy(c => c).Select(c => c.ToString()).ToList();
}
