using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Correlation ids: MCP server -> Routes request -> audit log -> response.
///
/// pyRevit Routes does not hand HTTP headers to handlers, so the id travels in the
/// JSON body (`_rvtss_request_id`, POST) or the query string (`rvtss_request_id`,
/// GET), like the RVTSS token.
/// </summary>
public static class Tracing
{
    public const string RequestIdBodyKey = "_rvtss_request_id";
    public const string RequestIdQueryKey = "rvtss_request_id";
    private static readonly Regex Valid = new(@"^[A-Za-z0-9._:\-]{1,64}$", RegexOptions.CultureInvariant);

    /// <summary>The id if it is a short safe token, else None (it ends up in log lines).</summary>
    public static string? CleanRequestId(object? value)
    {
        if (value == null)
            return null;
        string text;
        try
        {
            text = Py.Str(value).Trim();
        }
        catch
        {
            return null;
        }
        return Valid.IsMatch(text) ? text : null;
    }

    /// <summary>Take the id out of the body (so handlers never see it) or read it from the query.</summary>
    public static string? PopRequestId(Dict? data = null, Dict? queryParams = null)
    {
        object? rid = null;
        if (data != null && data.ContainsKey(RequestIdBodyKey))
            rid = data.Pop(RequestIdBodyKey);
        if (rid == null && queryParams != null && queryParams.Count > 0)
            rid = queryParams.Get(RequestIdQueryKey);
        return CleanRequestId(rid);
    }

    private static Dict? Payload(object? response)
    {
        // a Routes response object: its data (Python attribute `data`, here the Data property or field)
        if (response != null && response is not Dict)
        {
            var data = Py.GetAttr(response, "Data") ?? Py.GetAttr(response, "data");
            if (data is Dict d)
                return d;
        }
        if (response is Dict r)
        {
            // routes.make_response shape in the unit-test stubs: {"data": {...}, "status": 200}
            if (r.Get("data") is Dict inner && r.Count == 2 && r.ContainsKey("status"))
                return inner;
            return r;
        }
        return null;
    }

    /// <summary>Add request_id to a Routes response / plain dict payload (no-op for other bodies).</summary>
    public static T AttachRequestId<T>(T response, string? requestId)
    {
        if (string.IsNullOrEmpty(requestId))
            return response;
        var payload = Payload(response);
        if (payload != null && !payload.ContainsKey("request_id"))
            payload["request_id"] = requestId;
        return response;
    }
}
