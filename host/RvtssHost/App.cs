using System.Text;
using Autodesk.Revit.UI;

namespace RvtssHost;

/// <summary>
/// RVTSS Host: the Revit add-in that serves /revit_mcp/... without pyRevit.
/// This shell only owns the HTTP server, the main-thread dispatcher and the loader;
/// every route lives in RvtssHost.Impl.dll next to it.
/// Port: RVTSS_HOST_PORT, default 48885 while it runs next to pyRevit Routes (48884).
/// </summary>
public sealed class App : IExternalApplication
{
    public const string Version = "3.0.0-dev";
    public const int DefaultPort = 48885;
    private const string Prefix = "/revit_mcp";

    private HttpServer? _server;
    private ImplLoader? _loader;

    /// <summary>The loader of the running add-in (ribbon commands reach the routes through it).</summary>
    public static ImplLoader? Loader { get; private set; }

    public Result OnStartup(UIControlledApplication application)
    {
        // Never block Revit start-up: every failure is logged and swallowed.
        try
        {
            var revitVersion = application.ControlledApplication.VersionNumber;
            var port = DefaultPort;
            if (int.TryParse(Environment.GetEnvironmentVariable("RVTSS_HOST_PORT"), out var p) && p > 0 && p < 65536)
                port = p;
            _loader = new ImplLoader(new RevitDispatcher(), revitVersion, port);
            Loader = _loader;
            try { AddRibbon(application); }
            catch (Exception e) { Log.Write("RVTSS Host: ribbon not created: " + e.Message); }
            var error = _loader.Load();
            if (error != null)
                Log.Write("RVTSS Host: routes not loaded: " + error);
            _server = new HttpServer(port, Handle);
            _server.Start();
            Log.Write($"RVTSS Host {Version} listening on 127.0.0.1:{port} (Revit {revitVersion})");
        }
        catch (Exception e)
        {
            Log.Write("RVTSS Host failed to start: " + e);
        }
        return Result.Succeeded;
    }

    /// <summary>Tab "RVTSS Host" (the pyRevit extension owns the tab "RVTSS" while both are installed).</summary>
    private static void AddRibbon(UIControlledApplication application)
    {
        const string tab = "RVTSS Host";
        try { application.CreateRibbonTab(tab); } catch { /* exists */ }
        var panel = application.GetRibbonPanels(tab).FirstOrDefault(p => p.Name == "Diagnostics")
                    ?? application.CreateRibbonPanel(tab, "Diagnostics");
        var button = new PushButtonData("RvtssHostSelfTest", "Run\nSelf-Test", typeof(App).Assembly.Location,
            typeof(SelfTestCommand).FullName)
        {
            ToolTip = "Runs the RVTSS self-test on a copy of the bundled test model and writes a report.",
        };
        panel.AddItem(button);
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        try { _loader?.Unload(); } catch { /* shutting down */ }
        try { _server?.Stop(); } catch { /* shutting down */ }
        return Result.Succeeded;
    }

    private Task<HttpResponse> Handle(HttpRequest request)
    {
        var loader = _loader!;
        var path = request.Path.TrimEnd('/').ToLowerInvariant();
        if (path == Prefix + "/_reload")
            return Task.FromResult(Reload(request, loader));
        var handler = loader.Handler;
        if (handler == null)
            return Task.FromResult(Json(503, "{\"status\":\"error\",\"error\":\"RVTSS routes are not loaded\",\"detail\":"
                                             + Quote(loader.LastError ?? "unknown") + "}"));
        return handler(request);
    }

    /// <summary>Development only: load a rebuilt RvtssHost.Impl.dll without restarting Revit.
    /// Enabled by the file %APPDATA%\RVTSS\host-dev.flag.</summary>
    private static HttpResponse Reload(HttpRequest request, ImplLoader loader)
    {
        var flag = Path.Combine(Log.Home, "host-dev.flag");
        request.Headers.TryGetValue("host", out var host);
        var name = (host ?? "").Split(':')[0];
        if (request.Method != "POST" || request.Headers.ContainsKey("origin") || (name != "127.0.0.1" && name != "localhost")
            || !File.Exists(flag))
            return Json(404, "{\"status\":\"error\",\"error\":\"Route does not exist\"}");
        var error = loader.Load();
        Log.Write(error == null ? "RVTSS Host: routes reloaded" : "RVTSS Host: reload failed: " + error);
        return error == null
            ? Json(200, "{\"status\":\"success\",\"reloaded\":true}")
            : Json(500, "{\"status\":\"error\",\"error\":" + Quote(error) + "}");
    }

    private static HttpResponse Json(int status, string body) => new(status, Encoding.UTF8.GetBytes(body));

    private static string Quote(string s)
    {
        var sb = new StringBuilder("\"");
        foreach (var c in s)
        {
            if (c == '"' || c == '\\') sb.Append('\\').Append(c);
            else if (c < 32) sb.Append(' ');
            else sb.Append(c);
        }
        return sb.Append('"').ToString();
    }
}

public static class Log
{
    private static readonly object Gate = new();

    /// <summary>%APPDATA%\RVTSS</summary>
    public static string Home => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RVTSS");

    public static void Write(string message)
    {
        try
        {
            var dir = Path.Combine(Home, "logs");
            Directory.CreateDirectory(dir);
            var file = Path.Combine(dir, $"host-{DateTime.Now:yyyyMMdd}.log");
            lock (Gate)
                File.AppendAllText(file, $"{DateTime.Now:HH:mm:ss}\t{message}{Environment.NewLine}");
        }
        catch { /* logging must never break a request */ }
    }
}
