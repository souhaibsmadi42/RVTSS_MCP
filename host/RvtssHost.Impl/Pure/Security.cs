using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Security helpers: token comparison, secret redaction, loopback checks, env flags.
///
/// pyRevit Routes (checked in pyrevitlib/pyrevit/routes/server/server.py) builds the
/// handler Request from path, method, body and query string only - HTTP headers
/// and the client address never reach a route handler. The RVTSS token is
/// therefore accepted from the JSON body (`_rvtss_token`, POST) or the query
/// string (`rvtss_token`, GET); the X-RVTSS-Token header is also checked in case
/// a future pyRevit forwards headers.
/// </summary>
public static class Security
{
    public const string TokenBodyKey = "_rvtss_token";
    public const string TokenQueryKey = "rvtss_token";
    public const string TokenHeader = "X-RVTSS-Token";
    public static readonly string[] UnprotectedPaths = { "/status/", "/ping/" };

    private static readonly Regex SecretKeys = new(
        @"(?i)(password|passwd|secret|token|api[_-]?key|apikey|authorization|bearer|"
        + @"connection[_-]?string|private[_-]?key|access[_-]?key)", RegexOptions.CultureInvariant);

    private static readonly Regex SecretValue = new(
        @"(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
        + @"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}|"
        + @"-----BEGIN [A-Z ]*PRIVATE KEY-----)", RegexOptions.CultureInvariant);

    private static readonly Regex KeyValue = new(
        @"(?i)([""']?(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
        + @"authorization)[""']?\s*[:=]\s*)([""']?)([^""'\s,}]+)", RegexOptions.CultureInvariant);

    private static readonly Regex LongOpaque = new(@"\b[A-Za-z0-9+/=_\-]{40,}\b", RegexOptions.CultureInvariant);
    private static readonly Regex UuidLike = new(@"^[0-9a-fA-F\-]{36}$", RegexOptions.CultureInvariant);

    public const string Redacted = "[REDACTED]";

    /// <summary>'1/true/yes/on' -> True, '0/false/no/off' -> False, None/'' -> default.</summary>
    public static bool? ParseFlag(object? value, bool? def = null)
    {
        if (value == null)
            return def;
        if (value is bool b)
            return b;
        switch (Py.Str(value).Trim().ToLowerInvariant())
        {
            case "1":
            case "true":
            case "yes":
            case "on":
            case "allow":
            case "allowed":
                return true;
            case "0":
            case "false":
            case "no":
            case "off":
            case "deny":
            case "denied":
            case "disabled":
                return false;
        }
        return def;
    }

    public static bool ConstantTimeEqual(object? a, object? b)
    {
        if (a == null || b == null)
            return false;
        var x = Py.Str(a);
        var y = Py.Str(b);
        if (x.Length != y.Length)
            return false;
        var diff = 0;
        for (var i = 0; i < x.Length; i++)
            diff |= x[i] ^ y[i];
        return diff == 0;
    }

    /// <summary>The token of a request: JSON body, then query string, then header. A token that is not a
    /// string (a JSON number) is returned as its text; the comparison works on text anyway.</summary>
    public static string? ExtractToken(Dict? data = null, Dict? queryParams = null,
        IDictionary<string, string>? headers = null)
    {
        if (data != null && Py.Truthy(data.Get(TokenBodyKey)))
            return Py.Str(data.Get(TokenBodyKey));
        if (queryParams != null && queryParams.Count > 0 && Py.Truthy(queryParams.Get(TokenQueryKey)))
        {
            var v = queryParams.Get(TokenQueryKey);
            if (v is System.Collections.IList list && v is not string)
                v = list[0];
            return v == null ? null : Py.Str(v);
        }
        if (headers != null && headers.Count > 0)
        {
            foreach (var kv in headers)
                if (kv.Key.ToLowerInvariant() == TokenHeader.ToLowerInvariant())
                    return kv.Value;
        }
        return null;
    }

    public static bool IsLoopback(string? host)
    {
        var h = (host ?? "").Trim().ToLowerInvariant().Trim('[', ']');
        return h == "127.0.0.1" || h == "localhost" || h == "::1" || h.StartsWith("127.", StringComparison.Ordinal);
    }

    public static bool BindsAllInterfaces(string? host)
    {
        var h = (host ?? "").Trim();
        return h == "" || h == "0.0.0.0" || h == "::" || h == "*";
    }

    /// <summary>Mask secret-looking values (API keys, tokens, key=value secrets, long opaque strings).</summary>
    [return: System.Diagnostics.CodeAnalysis.NotNullIfNotNull("text")]
    public static string? Redact(string? text, int? maxLen = null)
    {
        if (text == null)
            return null;
        var s = text;
        s = SecretValue.Replace(s, _ => Redacted);
        s = KeyValue.Replace(s, m => m.Groups[1].Value + m.Groups[2].Value + Redacted);
        s = LongOpaque.Replace(s, m => UuidLike.IsMatch(m.Value) ? m.Value : Redacted);
        if (maxLen != null && maxLen != 0 && s.Length > maxLen)
        {
            var keep = PureText.SliceEnd(s.Length, maxLen.Value);
            s = s.Substring(0, keep) + "...[+" + (s.Length - maxLen.Value) + " chars]";
        }
        return s;
    }

    /// <summary>redact for a value that is not a string: its text is redacted (None stays None).</summary>
    [return: System.Diagnostics.CodeAnalysis.NotNullIfNotNull("text")]
    public static string? Redact(object? text, int? maxLen = null) =>
        text == null ? null : Redact(text as string ?? Py.Str(text), maxLen);

    /// <summary>Copy of a dict/list with values under secret-looking keys masked (recursively).</summary>
    public static object? RedactMapping(object? data)
    {
        if (data is string text)
            return Redact(text);
        if (data is System.Collections.IDictionary map)
        {
            var result = new Dict();
            foreach (System.Collections.DictionaryEntry kv in map)
            {
                var key = Py.Str(kv.Key);
                result[key] = SecretKeys.IsMatch(key) ? Redacted : RedactMapping(kv.Value);
            }
            return result;
        }
        if (data is System.Collections.IList list)
        {
            var result = new Lst();
            foreach (var v in list)
                result.Add(RedactMapping(v));
            return result;
        }
        return data;
    }
}
