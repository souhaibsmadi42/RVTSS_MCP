namespace RvtssHost.Modules;

/// <summary>
/// Status module: port of revit_mcp/status.py.
/// Handles API status and health check endpoints.
/// </summary>
public static class Status
{
    /// <summary>Register all status-related routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        api.Raw("/status/", new[] { "GET" }, RevitStatus, apiContext: true);
        api.Raw("/ping/", new[] { "GET" }, RevitPing, apiContext: false);
    }

    /// <summary>Health check endpoint that verifies Revit context availability:
    /// health status with Revit document information.</summary>
    public static Response RevitStatus(Request request)
    {
        try
        {
            var doc = request.Doc;
            if (doc != null)
            {
                var data = new Dict
                {
                    ["status"] = "active",
                    ["health"] = "healthy",
                    ["revit_available"] = true,
                    ["document_title"] = string.IsNullOrEmpty(doc.Title) ? "Untitled" : doc.Title,
                    ["api_name"] = "revit_mcp",
                    ["rvtss_version"] = Entry.RvtssVersion,
                    ["host"] = "csharp",
                    ["revit_version"] = Hosting.RevitVersion,
                };
                if (Entry.RegistrationErrors.Count > 0)
                {
                    data["health"] = "degraded";
                    data["route_modules_failed"] = new Dict(Entry.RegistrationErrors);
                }
                try { data["security"] = SecureApi.SecurityStatus(); }
                catch (Exception secErr) { data["security"] = new Dict { ["error"] = secErr.Message }; }
                return new Response(data);
            }
            return new Response(new Dict
            {
                ["status"] = "unhealthy",
                ["revit_available"] = false,
                ["error"] = "No active Revit document",
                ["api_name"] = "revit_mcp",
                ["host"] = "csharp",
                ["revit_version"] = Hosting.RevitVersion,
            }, 503);
        }
        catch (Exception e)
        {
            Log.Write("Health check failed:" + e.Message);
            return new Response(new Dict
            {
                ["status"] = "unhealthy",
                ["revit_available"] = false,
                ["error"] = e.Message,
                ["api_name"] = "revit_mcp",
                ["host"] = "csharp",
                ["revit_version"] = Hosting.RevitVersion,
            }, 503);
        }
    }

    /// <summary>Liveness of the HTTP server itself, answered without Revit API context.
    ///
    /// Only API-context handlers wait for Revit's main thread, so /ping/ answers while Revit is busy
    /// (modal dialog, edit mode, long operation). The MCP server uses it to tell
    /// "Revit busy" from "server not running" after a timeout.</summary>
    public static Response RevitPing(Request request) => new(new Dict
    {
        ["status"] = "success", ["pong"] = true, ["api_name"] = "revit_mcp",
        ["rvtss_version"] = Entry.RvtssVersion,
        ["server_time"] = DateTime.Now.ToString("yyyy-MM-dd'T'HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture),
        ["host"] = "csharp", ["revit_version"] = Hosting.RevitVersion,
    });
}
