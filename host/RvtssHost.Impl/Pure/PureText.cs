using System.Globalization;
using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Python text semantics shared by the ported pure modules: `re` patterns and replacement templates,
/// float(), iteration and slicing. Not a port of a Python module.
/// </summary>
internal static class PureText
{
    // ------------------------------------------------------------------- re
    /// <summary>re.compile(pattern, flags). Throws ArgumentException where Python raises re.error.</summary>
    public static Regex Re(string pattern, bool ignoreCase = false)
    {
        var options = RegexOptions.CultureInvariant;
        if (ignoreCase)
            options |= RegexOptions.IgnoreCase;
        return new Regex(Translate(pattern), options);
    }

    /// <summary>The pattern argument of a re function: Python raises TypeError for anything but a string.</summary>
    public static string Pattern(object? pattern) =>
        pattern as string ?? throw new FormatException("first argument must be string or compiled pattern");

    /// <summary>
    /// Python `re` syntax to .NET: (?P&lt;n&gt;...) -> (?&lt;n&gt;...), (?P=n) -> \k&lt;n&gt;, \Z -> \z, and the
    /// inline flags .NET does not know (u, L, a) are dropped. Everything else is the same syntax; IronPython's
    /// own `re` runs on the .NET engine too, so \d \w \s are the Unicode classes in both.
    /// </summary>
    public static string Translate(string pattern)
    {
        var sb = new StringBuilder(pattern.Length + 8);
        var inClass = false;
        for (var i = 0; i < pattern.Length; i++)
        {
            var c = pattern[i];
            if (c == '\\' && i + 1 < pattern.Length)
            {
                var n = pattern[i + 1];
                sb.Append('\\').Append(n == 'Z' && !inClass ? 'z' : n);
                i++;
                continue;
            }
            if (inClass)
            {
                if (c == ']')
                    inClass = false;
                sb.Append(c);
                continue;
            }
            if (c == '[')
            {
                inClass = true;
                sb.Append(c);
                // a ']' right after '[' or '[^' is a literal member of the set
                if (i + 1 < pattern.Length && pattern[i + 1] == '^')
                {
                    sb.Append('^');
                    i++;
                }
                if (i + 1 < pattern.Length && pattern[i + 1] == ']')
                {
                    sb.Append("\\]");
                    i++;
                }
                continue;
            }
            if (c == '(' && i + 2 < pattern.Length && pattern[i + 1] == '?')
            {
                if (pattern[i + 2] == 'P' && i + 3 < pattern.Length)
                {
                    if (pattern[i + 3] == '<')
                    {
                        sb.Append("(?<");
                        i += 3;
                        continue;
                    }
                    if (pattern[i + 3] == '=')
                    {
                        var close = pattern.IndexOf(')', i + 4);
                        if (close > 0)
                        {
                            sb.Append("\\k<").Append(pattern, i + 4, close - i - 4).Append('>');
                            i = close;
                            continue;
                        }
                    }
                }
                // (?iLmsuxa) global flags group
                var j = i + 2;
                while (j < pattern.Length && "iLmsuxa".IndexOf(pattern[j]) >= 0)
                    j++;
                if (j > i + 2 && j < pattern.Length && pattern[j] == ')')
                {
                    var flags = new string(pattern.Substring(i + 2, j - i - 2).Where(f => "imsx".IndexOf(f) >= 0).ToArray());
                    if (flags.Length > 0)
                        sb.Append("(?").Append(flags).Append(')');
                    i = j;
                    continue;
                }
            }
            sb.Append(c);
        }
        return sb.ToString();
    }

    /// <summary>re.sub(rx, repl, input) with a Python replacement template (\1, \g&lt;name&gt;, \n ...).</summary>
    public static string Sub(Regex rx, string repl, string input)
    {
        if (repl.IndexOf('\\') < 0)
            return rx.Replace(input, _ => repl);
        var parts = ParseTemplate(rx, repl);
        return rx.Replace(input, m =>
        {
            var sb = new StringBuilder();
            foreach (var (literal, group) in parts)
            {
                if (literal != null)
                    sb.Append(literal);
                else
                    sb.Append(m.Groups[group!].Value); // an unmatched group is the empty string
            }
            return sb.ToString();
        });
    }

    private static List<(string? literal, string? group)> ParseTemplate(Regex rx, string repl)
    {
        var parts = new List<(string?, string?)>();
        var lit = new StringBuilder();
        void Group(string name)
        {
            var numbered = int.TryParse(name, NumberStyles.None, CultureInfo.InvariantCulture, out var number);
            var known = numbered
                ? rx.GetGroupNumbers().Contains(number)
                : rx.GetGroupNames().Contains(name);
            if (!known && !numbered)
                throw new IndexOutOfRangeException("unknown group name '" + name + "'"); // Python: IndexError
            if (!known)
                throw new ArgumentException("invalid group reference " + name);
            if (lit.Length > 0)
            {
                parts.Add((lit.ToString(), null));
                lit.Clear();
            }
            parts.Add((null, name));
        }
        for (var i = 0; i < repl.Length; i++)
        {
            var c = repl[i];
            if (c != '\\' || i + 1 >= repl.Length)
            {
                lit.Append(c);
                continue;
            }
            var n = repl[++i];
            if (n == 'g')
            {
                var close = i + 1 < repl.Length && repl[i + 1] == '<' ? repl.IndexOf('>', i + 2) : -1;
                if (close < 0)
                    throw new ArgumentException("missing <");
                var name = repl.Substring(i + 2, close - i - 2);
                if (name.Length == 0)
                    throw new ArgumentException("missing group name");
                Group(name);
                i = close;
            }
            else if (n == '0')
            {
                // octal escape, up to 3 digits
                var j = i;
                var v = 0;
                while (j < repl.Length && j < i + 3 && repl[j] >= '0' && repl[j] <= '7')
                    v = v * 8 + (repl[j++] - '0');
                lit.Append((char)v);
                i = j - 1;
            }
            else if (n >= '1' && n <= '9')
            {
                var j = i + 1;
                if (j < repl.Length && char.IsDigit(repl[j]) && repl[j] < 128)
                    j++;
                Group(repl.Substring(i, j - i));
                i = j - 1;
            }
            else
            {
                switch (n)
                {
                    case 'n': lit.Append('\n'); break;
                    case 't': lit.Append('\t'); break;
                    case 'r': lit.Append('\r'); break;
                    case 'a': lit.Append('\a'); break;
                    case 'b': lit.Append('\b'); break;
                    case 'f': lit.Append('\f'); break;
                    case 'v': lit.Append('\v'); break;
                    case '\\': lit.Append('\\'); break;
                    default: lit.Append('\\').Append(n); break; // Python 2 keeps an unknown escape as it is
                }
            }
        }
        if (lit.Length > 0)
            parts.Add((lit.ToString(), null));
        return parts;
    }

    // ---------------------------------------------------------------- float
    /// <summary>float(text) as Python parses it (surrounding blanks, inf / nan), or null (ValueError).</summary>
    public static double? ParseFloat(string text)
    {
        var s = text.Trim();
        if (s.Length == 0)
            return null;
        var body = s[0] == '+' || s[0] == '-' ? s.Substring(1) : s;
        var lower = body.ToLowerInvariant();
        if (lower == "inf" || lower == "infinity")
            return s[0] == '-' ? double.NegativeInfinity : double.PositiveInfinity;
        if (lower == "nan")
            return double.NaN;
        // digits, one optional point, optional exponent: nothing else (.NET would also take "Infinity", "NaN", "∞")
        var digits = 0;
        var k = 0;
        while (k < body.Length && body[k] >= '0' && body[k] <= '9') { k++; digits++; }
        if (k < body.Length && body[k] == '.')
        {
            k++;
            while (k < body.Length && body[k] >= '0' && body[k] <= '9') { k++; digits++; }
        }
        if (digits == 0)
            return null;
        if (k < body.Length && (body[k] == 'e' || body[k] == 'E'))
        {
            k++;
            if (k < body.Length && (body[k] == '+' || body[k] == '-'))
                k++;
            var exp = 0;
            while (k < body.Length && body[k] >= '0' && body[k] <= '9') { k++; exp++; }
            if (exp == 0)
                return null;
        }
        if (k != body.Length)
            return null;
        return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var r) ? r : null;
    }

    /// <summary>float(v) for a request value. Throws FormatException (Python ValueError / TypeError).</summary>
    public static double ToFloat(object? v)
    {
        switch (v)
        {
            case double d: return d;
            case long l: return l;
            case int i: return i;
            case float f: return f;
            case short s: return s;
            case byte b: return b;
            case decimal m: return (double)m;
            case bool b: return b ? 1 : 0;
            case string s:
                return ParseFloat(s) ?? throw new FormatException("could not convert string to float: " + s);
            default:
                throw new FormatException("float() argument must be a string or a number, not " + Py.TypeName(v));
        }
    }

    /// <summary>isinstance(v, (int, float)): numbers and bool.</summary>
    public static bool IsNumber(object? v) => v is bool || Py.IsNum(v);

    // ------------------------------------------------------------ sequences
    /// <summary>Iterate a value the way a Python for loop does: lists, tuples, strings (characters).</summary>
    public static IEnumerable<object?> Iter(object? v)
    {
        switch (v)
        {
            case null:
                throw new FormatException("NoneType is not iterable");
            case string s:
                return s.Select(c => (object?)c.ToString());
            case System.Collections.IDictionary map:
                return map.Keys.Cast<object?>();
            case System.Collections.IEnumerable seq:
                return seq.Cast<object?>();
            case System.Runtime.CompilerServices.ITuple t:
                var items = new List<object?>();
                for (var i = 0; i < t.Length; i++)
                    items.Add(t[i]);
                return items;
            default:
                throw new FormatException("'" + Py.TypeName(v) + "' object is not iterable");
        }
    }

    /// <summary>seq[:n] with Python's handling of a negative or oversized n.</summary>
    public static int SliceEnd(int length, long n)
    {
        if (n < 0)
            n += length;
        return (int)Math.Max(0, Math.Min(length, n));
    }

    public static string Join(string sep, IEnumerable<object?> items) => string.Join(sep, items.Select(Py.Str));
}
