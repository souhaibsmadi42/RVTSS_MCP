using System.Reflection;
using System.Text.Json;

namespace RvtssHost;

/// <summary>What the shell (ImplLoader) calls: builds the route table and answers HTTP requests.</summary>
public static class Entry
{
    /// <summary>Version of the RVTSS route contract this host implements. Must equal RVTSS_VERSION of the MCP
    /// server (revit_mcp/__init__.py), which rvtss_health compares.</summary>
    public const string RvtssVersion = "2.4.0";
    private const string Prefix = "/revit_mcp";

    /// <summary>{module: error} for modules whose Register failed (revit_mcp.REGISTRATION_ERRORS).</summary>
    public static readonly Dict RegistrationErrors = new();

    public static RouteTable Table { get; private set; } = new();

    private static RevitDispatcher? _dispatcher;
    private static readonly List<Action> StopActions = new();

    /// <summary>How long a request may wait for Revit's main thread before it is cancelled.</summary>
    private static readonly TimeSpan QueueTimeout = TimeSpan.FromSeconds(
        double.TryParse(Environment.GetEnvironmentVariable("RVTSS_HOST_QUEUE_TIMEOUT"), out var t) && t > 0 ? t : 20);

    public static Func<HttpRequest, Task<HttpResponse>> Start(RevitDispatcher dispatcher, string revitVersion, int port)
    {
        _dispatcher = dispatcher;
        Py.ForeignScalar = v => v is DB.ElementId id ? id.Value : null;
        Hosting.RevitVersion = revitVersion;
        Hosting.Port = port;
        RegistrationErrors.Clear();
        var table = new RouteTable();
        foreach (var type in typeof(Entry).Assembly.GetTypes().OrderBy(t => t.FullName, StringComparer.Ordinal))
        {
            if (!type.IsClass || type.Namespace == null || !type.Namespace.StartsWith("RvtssHost.Modules"))
                continue;
            var register = type.GetMethod("Register", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(RouteTable) }, null);
            if (register == null)
                continue;
            try
            {
                register.Invoke(null, new object[] { table });
            }
            catch (Exception e)
            {
                var inner = e is TargetInvocationException && e.InnerException != null ? e.InnerException : e;
                RegistrationErrors[type.Name] = inner.GetType().Name + ": " + inner.Message;
                Log.Write($"Failed to register {type.Name}: {inner}");
            }
        }
        Table = table;
        Log.Write($"RVTSS routes loaded: {table.Routes.Count} routes, {RegistrationErrors.Count} module errors");
        return HandleHttp;
    }

    /// <summary>Ribbon button "Run Self-Test" (called by the shell on Revit's main thread).</summary>
    public static void RunSelfTest(UIApplication app) => Modules.SelfTest.Run(app);

    /// <summary>Run once on Revit's main thread, without blocking the caller (event subscriptions and the like).</summary>
    public static void OnMainThread(Action<UIApplication> work)
    {
        var dispatcher = _dispatcher;
        if (dispatcher == null)
            return;
        _ = dispatcher.Run(app =>
        {
            try { work(app); }
            catch (Exception e) { Log.Write("Main-thread start-up work failed: " + e); }
            return null;
        }, TimeSpan.FromMinutes(10));
    }

    /// <summary>Register clean-up that must run before the implementation is unloaded (unsubscribe events).</summary>
    public static void OnStop(Action action)
    {
        lock (StopActions)
            StopActions.Add(action);
    }

    public static void Stop()
    {
        List<Action> actions;
        lock (StopActions)
        {
            actions = new List<Action>(StopActions);
            StopActions.Clear();
        }
        foreach (var a in actions)
        {
            try { a(); }
            catch (Exception e) { Log.Write("Stop action failed: " + e.Message); }
        }
    }

    // ----------------------------------------------------------------- HTTP
    private static async Task<HttpResponse> HandleHttp(HttpRequest http)
    {
        try
        {
            if (!http.Path.StartsWith(Prefix, StringComparison.OrdinalIgnoreCase))
                return Reply(new Response(new Dict { ["status"] = "error", ["error"] = "Route does not exist" }, 404));
            var path = RouteTable.Normalize(http.Path.Substring(Prefix.Length));
            var request = BuildRequest(http, path);

            // Token, loopback and origin checks apply before anything else, also to unknown routes.
            var refused = SecureApi.Check(request);
            if (refused != null)
                return Reply(refused);

            var route = Table.Find(path, request);
            if (route == null)
                return Reply(new Response(new Dict
                {
                    ["status"] = "error", ["error"] = "Route does not exist: " + path,
                    ["hint"] = "The MCP server and the Revit add-in are different versions, or the route module failed "
                               + "to load (see /status/).",
                }, 404));
            if (Array.IndexOf(route.Methods, http.Method) < 0)
                return Reply(new Response(new Dict { ["status"] = "error", ["error"] = "Method not allowed: " + http.Method }, 405));

            Response response;
            if (route.ApiContext)
            {
                var result = await _dispatcher!.Run(app =>
                {
                    Hosting.UiApp = app;
                    request.UiApp = app;
                    request.UiDoc = app.ActiveUIDocument;
                    request.Doc = request.UiDoc?.Document;
                    return Guarded(route, request);
                }, QueueTimeout).ConfigureAwait(false);
                response = (Response)result!;
            }
            else
            {
                response = Guarded(route, request);
            }
            return Reply(response);
        }
        catch (RevitBusyException e)
        {
            return Reply(new Response(new Dict
            {
                ["status"] = "error", ["error"] = e.Message, ["code"] = "REVIT_BUSY",
                ["hint"] = "Revit is busy with a modal dialog, an edit mode (sketch / in-place family / group edit) or a "
                           + "long operation. The request was cancelled and will not run later. Close dialogs / finish "
                           + "the edit mode, then retry.",
            }, 503));
        }
        catch (Exception e)
        {
            Log.Write($"{http.Path} failed: {e}");
            return Reply(new Response(new Dict { ["status"] = "error", ["error"] = e.GetType().Name + ": " + e.Message }, 500));
        }
    }

    private static Response Guarded(Route route, Request request)
    {
        try
        {
            return SecureApi.Around(request, () => route.Invoke(request));
        }
        catch (Exception e)
        {
            Log.Write($"{request.Path} failed: {e}");
            var text = e.ToString();
            return new Response(new Dict
            {
                ["status"] = "error", ["error"] = e.GetType().Name + ": " + e.Message,
                ["traceback"] = text.Length > 3000 ? text.Substring(text.Length - 3000) : text,
            }, 500);
        }
    }

    private static Request BuildRequest(HttpRequest http, string path)
    {
        var request = new Request { Method = http.Method, Path = path, Headers = http.Headers };
        foreach (var pair in http.Query.Split(new[] { '&' }, StringSplitOptions.RemoveEmptyEntries))
        {
            var i = pair.IndexOf('=');
            var key = Uri.UnescapeDataString((i < 0 ? pair : pair.Substring(0, i)).Replace('+', ' '));
            request.Query[key] = i < 0 ? "" : Uri.UnescapeDataString(pair.Substring(i + 1).Replace('+', ' '));
        }
        request.Body = Encoding.UTF8.GetString(http.Body);
        if (request.Body.Trim().Length > 0)
        {
            try
            {
                request.Data = Py.JsonLoads(request.Body) as Dict;
                if (request.Data == null)
                    request.BodyError = "Request body must be a JSON object";
            }
            catch (JsonException e)
            {
                request.Data = null;
                request.BodyError = "Invalid JSON body: " + e.Message;
            }
        }
        return request;
    }

    private static HttpResponse Reply(Response response) => new(response.Status, Py.JsonBytes(response.Data));
}
