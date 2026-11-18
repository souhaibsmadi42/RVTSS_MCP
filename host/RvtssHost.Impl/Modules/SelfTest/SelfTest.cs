using System.Diagnostics;

namespace RvtssHost.Modules;

/// <summary>
/// In-Revit runner of the RVTSS self-test (ribbon button "Run Self-Test"): port of revit_mcp/selftest_runtime.py.
/// The plan itself is the Python original, revit_mcp/pure/selftest.py, embedded in this assembly and run by
/// the embedded Python engine. HTTP cannot be used from a ribbon command: the command runs on Revit's main
/// thread and every route waits for that same thread, so routes are called directly, in process.
/// </summary>
public static class SelfTest
{
    private const string Driver = @"
import json, types
plan = types.ModuleType('rvtss_selftest')
exec(compile(_source, 'selftest.py', 'exec'), plan.__dict__)

def transport(method, path, payload):
    text = _call(method, path, json.dumps(payload) if payload is not None else '')
    i = text.index('\n')
    return int(text[:i]), json.loads(text[i + 1:])

def prepare_model(t):
    return _prepare(t.stamp) or None

# Revit runs a posted Undo only after this ribbon command has returned, so the undo step cannot pass in
# process. It is covered by the HTTP runner (tests/live/run_live.py).
def _skip_undo(t):
    raise plan.StepSkipped('a posted Undo runs only after this ribbon command returns; covered by the HTTP runner')

for _s in plan.STEPS:
    if _s['name'] == 'undo the last RVTSS change':
        _s['fn'] = _skip_undo

report = plan.run(transport, _scratch, prepare_model, groups=None, log=_log,
                  environment={'transport': 'in-process (RVTSS Host button)'})
s = report['summary']
_result['json'] = plan.to_json(report)
_result['md'] = plan.to_markdown(report)
_result['summary'] = '%d passed, %d failed, %d skipped in %.1f s' % (s['pass'], s['fail'], s['skip'], report['duration_s'])
_result['failed'] = s['fail']
";

    public static void Run(UIApplication uiapp)
    {
        var confirm = new TaskDialog("RVTSS self-test")
        {
            MainInstruction = "Run the RVTSS self-test?",
            MainContent = "A copy of the bundled test model will be opened and modified, and test families are "
                          + "written to %TEMP%\\RVTSS_live. Your open models are not changed.",
            CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
            DefaultButton = TaskDialogResult.No,
        };
        if (confirm.Show() != TaskDialogResult.Yes)
            return;

        var scratch = Path.Combine(Path.GetTempPath(), "RVTSS_live");
        Directory.CreateDirectory(scratch);

        string source;
        using (var stream = typeof(SelfTest).Assembly.GetManifestResourceStream("selftest.py")
                            ?? throw new FileNotFoundException("The self-test plan (selftest.py) is not embedded in this build."))
        using (var reader = new StreamReader(stream, Encoding.UTF8))
            source = reader.ReadToEnd();

        var result = new Dictionary<string, object?>();
        var variables = new Dictionary<string, object?>
        {
            ["_source"] = source,
            ["_scratch"] = scratch,
            ["_result"] = result,
            ["_call"] = new Func<string, string, string, string>((method, path, body) => Call(uiapp, method, path, body)),
            ["_prepare"] = new Func<string, string?>(stamp => PrepareModel(scratch, stamp)),
            ["_log"] = new Action<object>(line => Log.Write("self-test: " + line)),
        };

        var error = PyEngine.RunFile(Driver, "rvtss_selftest_driver.py", variables);
        if (error != null)
        {
            Log.Write("Self-test plan crashed: " + error);
            new TaskDialog("RVTSS self-test")
            {
                MainInstruction = "The self-test could not run.",
                MainContent = error.Length > 1500 ? error.Substring(error.Length - 1500) : error,
            }.Show();
            return;
        }

        var jsonPath = Path.Combine(scratch, "rvtss_live_report.json");
        var mdPath = Path.Combine(scratch, "rvtss_live_report.md");
        File.WriteAllText(jsonPath, Py.Str(result.TryGetValue("json", out var j) ? j : ""), new UTF8Encoding(false));
        File.WriteAllText(mdPath, Py.Str(result.TryGetValue("md", out var m) ? m : ""), new UTF8Encoding(false));

        var failed = result.TryGetValue("failed", out var f) && Py.TryInt(f, out var n) && n > 0;
        new TaskDialog("RVTSS self-test")
        {
            MainInstruction = Py.Str(result.TryGetValue("summary", out var s) ? s : "finished"),
            MainContent = "Report: " + mdPath,
            MainIcon = failed ? TaskDialogIcon.TaskDialogIconWarning : TaskDialogIcon.TaskDialogIconInformation,
        }.Show();
        try { Process.Start(new ProcessStartInfo(mdPath) { UseShellExecute = true }); }
        catch { /* no viewer for .md: the path is in the dialog */ }
    }

    /// <summary>
    /// The bundled test model, copied to the scratch folder. A model saved for this Revit year
    /// (test_&lt;year&gt;.rvt) wins over test.rvt, which newer Revit versions upgrade in the copy and older ones cannot open.
    /// </summary>
    private static string? PrepareModel(string scratch, string stamp)
    {
        var home = Path.GetDirectoryName(typeof(RevitDispatcher).Assembly.Location) ?? "";
        var folders = new[]
        {
            home,
            Path.Combine(home, "tests"),
            Path.GetFullPath(Path.Combine(home, "..", "tests")),                        // installed: {app}\host\tests
            Path.GetFullPath(Path.Combine(home, "..", "..", "..", "tests")),            // development checkout: host/dist/R<year>
            Path.GetFullPath(Path.Combine(home, "..", "..", "tests", "models")),        // host/tests/models
        };
        foreach (var name in new[] { "test_" + Hosting.RevitVersion + ".rvt", "test.rvt" })
        {
            foreach (var folder in folders)
            {
                var src = Path.Combine(folder, name);
                if (!File.Exists(src))
                    continue;
                var dst = Path.Combine(scratch, "RVTSS_selftest_" + stamp + ".rvt");
                File.Copy(src, dst, true);
                return dst;
            }
        }
        return null;
    }

    /// <summary>One request, served in process on this (Revit's main) thread: "status\njson".</summary>
    private static string Call(UIApplication uiapp, string method, string path, string body)
    {
        Response response;
        try
        {
            var q = path.IndexOf('?');
            var request = new Request
            {
                Method = method.ToUpperInvariant(),
                Path = RouteTable.Normalize(Uri.UnescapeDataString(q < 0 ? path : path.Substring(0, q))),
            };
            if (q >= 0)
            {
                foreach (var pair in path.Substring(q + 1).Split(new[] { '&' }, StringSplitOptions.RemoveEmptyEntries))
                {
                    var i = pair.IndexOf('=');
                    request.Query[Uri.UnescapeDataString(i < 0 ? pair : pair.Substring(0, i))] =
                        i < 0 ? "" : Uri.UnescapeDataString(pair.Substring(i + 1));
                }
            }
            if (!string.IsNullOrEmpty(body))
            {
                request.Body = body;
                request.Data = Py.JsonLoads(body) as Dict ?? new Dict();
            }
            Hosting.UiApp = uiapp;
            request.UiApp = uiapp;
            request.UiDoc = uiapp.ActiveUIDocument;
            request.Doc = request.UiDoc?.Document;

            var route = Entry.Table.Find(request.Path, request);
            if (route == null)
                response = new Response(new Dict { ["status"] = "error", ["error"] = $"No route for {method} {path}" }, 404);
            else if (Array.IndexOf(route.Methods, request.Method) < 0)
                response = new Response(new Dict { ["status"] = "error", ["error"] = "Method not allowed: " + request.Method }, 405);
            else
                response = SecureApi.Around(request, () => route.Invoke(request));   // in-process calls are trusted: no token check
        }
        catch (Exception e)
        {
            Log.Write($"self-test {method} {path} failed: {e}");
            response = new Response(new Dict { ["status"] = "error", ["error"] = e.GetType().Name + ": " + e.Message }, 500);
        }
        return response.Status.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\n" + Py.JsonDumps(response.Data);
    }
}
