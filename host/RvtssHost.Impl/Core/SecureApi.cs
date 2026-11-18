namespace RvtssHost;

/// <summary>
/// Optional shared-secret protection for every revit_mcp route: port of revit_mcp/secure_api.py.
///
/// Settings (environment of the Revit process, or %APPDATA%/RVTSS/config.json):
///     RVTSS_TOKEN / "token"                                 shared secret; unset = no token (default)
///     RVTSS_ALLOW_CODE_EXECUTION / "allow_code_execution"   default allowed (backward compatible)
///     RVTSS_ALLOW_REMOTE / "allow_remote"                   accept a Host header that is not loopback
///     RVTSS_READ_ONLY / "read_only"                         refuse every model/file change (dry runs still work)
///     RVTSS_ALLOW_SAVE / "allow_save"                       allow save_document / close_document(save) (default off)
///     RVTSS_ALLOW_SYNC / "allow_sync"                       allow sync_with_central (default off)
///
/// pyRevit wrapped every handler (protect / SecureAPI); here Entry calls Check before routing and Around
/// around the handler, so no wrapper is generated.
/// </summary>
public static class SecureApi
{
    private static Dict Config()
    {
        try { return Core.LoadConfig(); }
        catch { return new Dict(); }
    }

    private static string? Env(string name)
    {
        var v = Environment.GetEnvironmentVariable(name);
        return string.IsNullOrEmpty(v) ? null : v;
    }

    public static Dict Settings()
    {
        var cfg = Config();
        object? token = Env("RVTSS_TOKEN");
        if (!Py.Truthy(token))
            token = Py.Truthy(cfg.Get("token")) ? cfg.Get("token") : null;
        var allowCode = Security.ParseFlag(Env("RVTSS_ALLOW_CODE_EXECUTION"), Security.ParseFlag(cfg.Get("allow_code_execution"), true));
        var allowRemote = Security.ParseFlag(Env("RVTSS_ALLOW_REMOTE"), Security.ParseFlag(cfg.Get("allow_remote"), false));
        var readOnly = Security.ParseFlag(Env("RVTSS_READ_ONLY"), Security.ParseFlag(cfg.Get("read_only"), false));
        var allowSave = Security.ParseFlag(Env("RVTSS_ALLOW_SAVE"), Security.ParseFlag(cfg.Get("allow_save"), false));
        var allowSync = Security.ParseFlag(Env("RVTSS_ALLOW_SYNC"), Security.ParseFlag(cfg.Get("allow_sync"), false));
        return new Dict
        {
            ["token"] = token, ["allow_code_execution"] = allowCode, ["allow_remote"] = allowRemote,
            ["read_only"] = Py.Truthy(readOnly), ["allow_save"] = Py.Truthy(allowSave), ["allow_sync"] = Py.Truthy(allowSync),
        };
    }

    /// <summary>The address the HTTP server listens on. The C# host always binds the loopback interface
    /// (pyRevit: Settings > Routes > Host).</summary>
    public static string? RoutesHost() => "127.0.0.1";

    /// <summary>Public summary for /status/ and session info (never includes the token).</summary>
    public static Dict SecurityStatus()
    {
        var st = Settings();
        var host = RoutesHost();
        var exposed = Security.BindsAllInterfaces(host) || !Security.IsLoopback(host ?? "");
        var warnings = new Lst();
        if (exposed && !Py.Truthy(st["token"]))
            warnings.Add($"pyRevit Routes listens on '{(string.IsNullOrEmpty(host) ? "0.0.0.0" : host)}' (all interfaces / non-loopback) without an RVTSS token: "
                         + "anyone who can reach port 48884 can drive Revit. Set pyRevit Settings > Routes > Host "
                         + "to 127.0.0.1 or set RVTSS_TOKEN.");
        if (exposed && !Py.Truthy(st["allow_remote"]) && Py.Truthy(st["token"]))
            warnings.Add("Routes is reachable beyond loopback; set RVTSS_ALLOW_REMOTE=1 to acknowledge (VM setups).");
        return new Dict
        {
            ["token_required"] = Py.Truthy(st["token"]), ["code_execution_allowed"] = st["allow_code_execution"],
            ["routes_host"] = string.IsNullOrEmpty(host) ? "0.0.0.0 (all interfaces)" : host, ["reachable_beyond_loopback"] = exposed,
            ["allow_remote"] = st["allow_remote"], ["read_only"] = st["read_only"], ["allow_save"] = st["allow_save"],
            ["allow_sync"] = st["allow_sync"], ["warnings"] = warnings,
        };
    }

    private static Response Unauthorized() => new(new Dict
    {
        ["status"] = "error", ["error"] = "RVTSS token missing or invalid",
        ["hint"] = "Set the same RVTSS_TOKEN for the MCP server (main.py) and for Revit, then restart the MCP server.",
    }, 401);

    private static Response Forbidden(string message, string hint, string code) => new(new Dict
    {
        ["status"] = "error", ["error"] = message, ["hint"] = hint, ["code"] = code,
    }, 403);

    /// <summary>The token check of one request: null when the token matches, else the 401 response.
    /// The token is taken out of the body either way, so handlers never see it. (secure_api.make_checker)</summary>
    private static Response? CheckToken(Request request, object? token)
    {
        var data = request.Data;
        var provided = Security.ExtractToken(data, request.Query, request.Headers);
        data?.Pop(Security.TokenBodyKey);
        if (!Security.ConstantTimeEqual(provided, token))
            return Unauthorized();
        return null;
    }

    /// <summary>Token and allow_remote are read once, when the first request arrives: as with pyRevit, where
    /// secured() read them when the routes were registered, a change needs a reload / Revit restart.</summary>
    private static readonly Lazy<Dict> Startup = new(() =>
    {
        var st = Settings();
        if (Py.Truthy(st["token"]))
            Log.Write("RVTSS token protection enabled for revit_mcp routes");
        return st;
    });

    private static string? Header(Request request, string name)
    {
        foreach (var kv in request.Headers)
        {
            if (string.Equals(kv.Key, name, StringComparison.OrdinalIgnoreCase))
                return kv.Value;
        }
        return null;
    }

    /// <summary>"127.0.0.1:48884" -> "127.0.0.1", "[::1]:48884" -> "::1", "LocalHost" -> "localhost".</summary>
    private static string HostPart(string header)
    {
        var h = header.Trim();
        if (h.StartsWith("["))
        {
            var end = h.IndexOf(']');
            return (end > 0 ? h.Substring(1, end - 1) : h.Substring(1)).ToLowerInvariant();
        }
        var colon = h.LastIndexOf(':');
        // exactly one colon: host:port. Several colons: a bare IPv6 address without brackets.
        if (colon >= 0 && h.IndexOf(':') == colon)
            h = h.Substring(0, colon);
        return h.Trim().ToLowerInvariant();
    }

    /// <summary>
    /// Called by Entry for every request before routing. Null allows the request, otherwise the error response.
    ///
    /// Two checks pyRevit Routes could not make (it never passed headers on): a request with an Origin header
    /// comes from a web page in a browser and is refused, and a Host header that is not the loopback name
    /// (DNS rebinding: a foreign name resolving to 127.0.0.1) is refused unless allow_remote is set. Then the
    /// token check of secure_api (protect / make_checker); /status/ and /ping/ stay open.
    /// </summary>
    public static Response? Check(Request request)
    {
        var denied = CheckRequest(request);
        if (denied != null)
        {
            // pyRevit attached the request id to the 401 as well (the check ran inside protect()).
            try { Attach(denied, Tracing.PopRequestId(request.Data, request.Query)); }
            catch { /* the refusal itself matters */ }
        }
        return denied;
    }

    private static Response? CheckRequest(Request request)
    {
        if (Header(request, "Origin") != null)
            return Forbidden("Requests from a web browser are not accepted (Origin header present)",
                "RVTSS answers the RVTSS MCP server only. Call it without an Origin header.", "ORIGIN_REFUSED");

        var st = Startup.Value;
        var host = Header(request, "Host");
        if (host != null && !Py.Truthy(st["allow_remote"]))
        {
            var part = HostPart(host);
            if (part != "127.0.0.1" && part != "localhost" && part != "::1")
                return Forbidden($"Host '{host.Trim()}' is not accepted: RVTSS answers on 127.0.0.1 / localhost only",
                    "Call http://127.0.0.1:<port>/revit_mcp/... or set RVTSS_ALLOW_REMOTE=1 (\"allow_remote\": true in "
                    + "%APPDATA%/RVTSS/config.json) for Revit and restart Revit.", "HOST_REFUSED");
        }

        var token = st["token"];
        if (Py.Truthy(token) && Array.IndexOf(Security.UnprotectedPaths, request.Path) < 0)
            return CheckToken(request, token);
        return null;
    }

    /// <summary>Add request_id to a JSON object response (tracing.attach_request_id).</summary>
    private static Response Attach(Response response, string? requestId)
    {
        if (!string.IsNullOrEmpty(requestId) && response.Data is Dict payload && !payload.ContainsKey("request_id"))
            payload["request_id"] = requestId;
        return response;
    }

    /// <summary>Take the correlation id out of the request and make it current on this thread. (_begin_request)</summary>
    private static string? BeginRequest(Request request)
    {
        var rid = Tracing.PopRequestId(request.Data, request.Query);
        try { Core.SetRequestId(rid); }
        catch { /* tracing must never break a request */ }
        return rid;
    }

    private static void EndRequest()
    {
        try { Core.SetRequestId(null); }
        catch { /* tracing must never break a request */ }
    }

    /// <summary>Run a handler with the request's correlation id current (audit log) and add `request_id`
    /// to its response. (the wrapper secure_api.protect generated)</summary>
    public static Response Around(Request request, Func<Response> run)
    {
        var rid = BeginRequest(request);
        try
        {
            return Attach(run(), rid);
        }
        finally
        {
            EndRequest();
        }
    }
}
