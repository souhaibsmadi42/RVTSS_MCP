namespace RvtssHost;

/// <summary>One HTTP request as a route sees it (pyRevit's request plus doc / uidoc).</summary>
public sealed class Request
{
    public string Method = "GET";
    /// <summary>Path below /revit_mcp, with leading and trailing slash: "/find_elements/".</summary>
    public string Path = "/";
    public Dictionary<string, string> Headers = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>Query string parameters (text values).</summary>
    public Dict Query = new();
    /// <summary>Raw body text.</summary>
    public string Body = "";
    /// <summary>Parsed JSON body ({} when empty). Null when the body is not a JSON object: see BodyError.</summary>
    public Dict? Data = new();
    public string? BodyError;
    /// <summary>Values of &lt;name&gt; segments of the route path ("/get_view/&lt;view_name&gt;").</summary>
    public Dict UrlParams = new();

    // Set when the route runs in Revit API context.
    public UIApplication? UiApp;
    public UIDocument? UiDoc;
    public DB.Document? Doc;
}

/// <summary>routes.make_response(data=..., status=...)</summary>
public sealed class Response(object? data, int status = 200)
{
    public object? Data { get; } = data;
    public int Status { get; } = status;
}

public sealed class Route
{
    public string Path = "";
    public string[] Methods = { "GET" };
    /// <summary>True: runs on Revit's main thread (the Python handler took doc / uidoc).</summary>
    public bool ApiContext = true;
    public Func<Request, Response> Invoke = _ => new Response(new Dict());
}

/// <summary>
/// Route registration (pyRevit's routes.API). A module registers in
/// <c>public static void Register(RouteTable api)</c>; Entry finds these by reflection.
/// </summary>
public sealed class RouteTable
{
    public Dictionary<string, Route> Routes { get; } = new(StringComparer.Ordinal);

    /// <summary>Routes whose path has &lt;name&gt; segments, as (regex, parameter names, route).</summary>
    public List<(System.Text.RegularExpressions.Regex rx, List<string> names, Route route)> Patterns { get; } = new();

    /// <summary>Exact route, else the first pattern route that matches (its values go to request.UrlParams).</summary>
    public Route? Find(string path, Request request)
    {
        if (Routes.TryGetValue(path, out var exact))
            return exact;
        foreach (var (rx, names, route) in Patterns)
        {
            var m = rx.Match(path);
            if (!m.Success)
                continue;
            foreach (var n in names)
                request.UrlParams[n] = m.Groups[n].Value;
            return route;
        }
        return null;
    }

    public static string Normalize(string path)
    {
        if (!path.StartsWith("/")) path = "/" + path;
        if (!path.EndsWith("/")) path += "/";
        return path;
    }

    /// <summary>A route whose Python handler is <c>return handle(doc, request, impl, ...)</c>.</summary>
    public void Handle(string path, string[] methods, Func<Ctx, Dict?> impl, string? name = null, bool needsDoc = true)
    {
        var label = name ?? impl.Method.Name;
        Raw(path, methods, request => Core.Handle(request, impl, label, needsDoc), apiContext: true);
    }

    public void Post(string path, Func<Ctx, Dict?> impl, string? name = null, bool needsDoc = true) =>
        Handle(path, new[] { "POST" }, impl, name, needsDoc);

    public void Get(string path, Func<Ctx, Dict?> impl, string? name = null, bool needsDoc = true) =>
        Handle(path, new[] { "GET" }, impl, name, needsDoc);

    /// <summary>A route that builds its own Response (the legacy modules that do not use handle()).</summary>
    public void Raw(string path, string[] methods, Func<Request, Response> fn, bool apiContext = true)
    {
        path = Normalize(path);
        var route = new Route { Path = path, Methods = methods, ApiContext = apiContext, Invoke = fn };
        Routes[path] = route;
        if (path.IndexOf('<') < 0)
            return;
        // pyRevit style "<name>" / "<int:name>" segments: one path segment each.
        var names = new List<string>();
        var rx = "^" + System.Text.RegularExpressions.Regex.Replace(System.Text.RegularExpressions.Regex.Escape(path),
            @"<(?:\w+:)?(\w+)>", m => { names.Add(m.Groups[1].Value); return "(?<" + m.Groups[1].Value + ">[^/]+)"; }) + "$";
        Patterns.Add((new System.Text.RegularExpressions.Regex(rx), names, route));
    }
}
