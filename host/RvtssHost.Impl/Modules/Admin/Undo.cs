using System.Globalization;
using Autodesk.Revit.DB.Events;

namespace RvtssHost.Modules;

/// <summary>
/// Undo the last RVTSS change, safely (RVTSS v2.3): port of revit_mcp/undo.py.
///
/// Routes:
///     POST /undo/   action=status: the latest undo steps in the document and who made them
///                   action=undo:   undo the latest step, only if RVTSS made it
///
/// The Revit API has no undo call. RVTSS listens to Application.DocumentChanged and keeps a
/// small ledger per document of committed / undone / redone steps, marking the ones committed while
/// an RVTSS request was running. Undo posts Revit's own Undo command, and only when the latest
/// step in the document is an RVTSS step, so it never undoes the user's own work. The command runs
/// right after this request returns; callers re-read the model to verify.
/// </summary>
public static class Undo
{
    /// <summary>document key -> [entry, ...] (oldest first)</summary>
    private static readonly Dictionary<string, List<Dict>> Ledger = new();
    private static readonly Dictionary<string, List<Dict>> Redo = new();
    private static bool _installed;
    private static string? _error;
    private const int Max = 50;
    private static readonly object Gate = new();

    // The handler is removed again on Entry.Stop (the implementation assembly can be reloaded while Revit runs).
    private static EventHandler<DocumentChangedEventArgs>? _handler;
    private static Autodesk.Revit.ApplicationServices.Application? _app;

    private static string Key(DB.Document doc) =>
        (!string.IsNullOrEmpty(doc.PathName) ? doc.PathName : !string.IsNullOrEmpty(doc.Title) ? doc.Title : "").ToLowerInvariant();

    private static List<Dict> StackFor(string k)
    {
        if (!Ledger.TryGetValue(k, out var stack))
        {
            stack = new List<Dict>();
            Ledger[k] = stack;
        }
        return stack;
    }

    private static bool SameSeq(Dict? entry) => entry != null && entry.Get("seq") is long s && s == Core.ActiveRequestSeq;

    private static void OnChanged(object? sender, DocumentChangedEventArgs args)
    {
        try
        {
            lock (Gate)
            {
                var doc = args.GetDocument();
                var op = args.Operation.ToString();
                var names = args.GetTransactionNames().Select(n => Utils.NormalizeString(n)).ToList();
                var k = Key(doc);
                var stack = StackFor(k);
                var method = Core.ActiveRequestMethod;
                var hasMethod = !string.IsNullOrEmpty(method);
                if (op.EndsWith("TransactionCommitted", StringComparison.Ordinal))
                {
                    var rv = hasMethod && names.All(n => n.StartsWith("RVTSS", StringComparison.Ordinal));
                    var top = stack.Count > 0 ? stack[stack.Count - 1] : null;
                    if (rv && top != null && Py.Truthy(top.Get("rvtss")) && SameSeq(top))
                    {
                        // same request, e.g. an assimilated transaction group
                        ((List<string>)top["names"]!).AddRange(names);
                    }
                    else
                    {
                        stack.Add(new Dict
                        {
                            ["names"] = names, ["rvtss"] = rv, ["tool"] = rv ? method : null,
                            ["seq"] = rv ? Core.ActiveRequestSeq : null,
                            ["time"] = DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture),
                            ["added"] = args.GetAddedElementIds().Count,
                            ["modified"] = args.GetModifiedElementIds().Count,
                            ["deleted"] = args.GetDeletedElementIds().Count,
                        });
                    }
                    if (stack.Count > Max)
                        stack.RemoveRange(0, stack.Count - Max);
                    Redo.Remove(k);
                }
                else if (op.EndsWith("TransactionUndone", StringComparison.Ordinal))
                {
                    if (stack.Count > 0)
                    {
                        if (!Redo.TryGetValue(k, out var redo))
                            Redo[k] = redo = new List<Dict>();
                        redo.Add(stack[stack.Count - 1]);
                        stack.RemoveAt(stack.Count - 1);
                    }
                }
                else if (op.EndsWith("TransactionRedone", StringComparison.Ordinal))
                {
                    if (Redo.TryGetValue(k, out var redo) && redo.Count > 0)
                    {
                        stack.Add(redo[redo.Count - 1]);
                        redo.RemoveAt(redo.Count - 1);
                    }
                }
                else if (op.EndsWith("TransactionGroupRolledBack", StringComparison.Ordinal))
                {
                    // an RVTSS dry run: its inner commits were recorded above, then thrown away with the group
                    if (hasMethod)
                    {
                        while (stack.Count > 0 && Py.Truthy(stack[stack.Count - 1].Get("rvtss")) && SameSeq(stack[stack.Count - 1]))
                            stack.RemoveAt(stack.Count - 1);
                    }
                }
            }
        }
        catch (Exception e)  // never break Revit's event chain
        {
            _error = e.Message;
        }
    }

    /// <summary>Subscribe once per Revit session; safe to call again (an earlier handler is removed first).</summary>
    public static bool Install(Autodesk.Revit.ApplicationServices.Application app)
    {
        try
        {
            Uninstall();
            var handler = new EventHandler<DocumentChangedEventArgs>(OnChanged);
            app.DocumentChanged += handler;
            _handler = handler;
            _app = app;
            _installed = true;
            _error = null;
        }
        catch (Exception e)
        {
            _installed = false;
            _error = e.Message;
            Log.Write("RVTSS undo listener not installed: " + e.Message);
        }
        return _installed;
    }

    /// <summary>Remove the DocumentChanged handler (Entry.OnStop).</summary>
    public static void Uninstall()
    {
        var handler = _handler;
        var app = _app;
        _handler = null;
        _app = null;
        _installed = false;
        if (handler == null || app == null)
            return;
        try { app.DocumentChanged -= handler; }
        catch { /* the application may already be shutting down */ }
    }

    private static RevitCommandId? UndoCommandId()
    {
        var pc = Py.EnumOrNull<PostableCommand>("Undo");
        if (pc != null)
        {
            try { return RevitCommandId.LookupPostableCommandId(pc.Value); }
            catch { /* fall back to the command id */ }
        }
        return RevitCommandId.LookupCommandId("ID_EDIT_UNDO");
    }

    public static Dict? UndoRoute(Ctx ctx)
    {
        var doc = ctx.Doc;
        Dict? top;
        List<Dict> stack;
        lock (Gate)
        {
            stack = Ledger.TryGetValue(Key(doc), out var s) ? new List<Dict>(s) : new List<Dict>();
        }
        top = stack.Count > 0 ? stack[stack.Count - 1] : null;
        var action = ctx.Get("action", "status");
        if (action is string a0 && a0 == "status")
        {
            var limit = ctx.I("limit", 10, 1, Max);
            var latest = new Lst();
            foreach (var e in Enumerable.Reverse(stack.Skip(Math.Max(0, stack.Count - limit))))
                latest.Add(new Dict(e));
            return new Dict
            {
                ["listening"] = _installed, ["listener_error"] = _error,
                ["can_undo"] = top != null && Py.Truthy(top.Get("rvtss")),
                ["latest_steps"] = latest,
                ["note"] = "Steps made before RVTSS started listening (Revit start / pyRevit reload) are unknown.",
            };
        }
        if (!(action is string a1 && a1 == "undo"))
            throw new RvtssError("action must be status or undo");
        if (!_installed)
            throw new RvtssError("The undo listener is not running", status: 503, hint: _error);
        if (top == null)
            throw new RvtssError($"No change recorded in '{doc.Title}' since RVTSS started listening", status: 409);
        if (!Py.Truthy(top.Get("rvtss")))
        {
            var topNames = (top["names"] as IEnumerable<string>)?.ToList() ?? new List<string>();
            throw new RvtssError("The latest change in the model was not made by RVTSS ("
                                 + (topNames.Count > 0 ? string.Join(", ", topNames) : "unnamed") + "); nothing was undone",
                status: 409, hint: "Undo it in Revit (Ctrl+Z) if that is what you want.");
        }
        var expect = ctx.Get("expect_tool");
        if (Py.Truthy(expect) && !Equals(top.Get("tool"), expect))
            throw new RvtssError($"The latest RVTSS step came from '{Py.Str(top.Get("tool"))}', not '{Py.Str(expect)}'", status: 409);
        if (ctx.UiDoc == null || !ctx.UiDoc.Document.Equals(doc))
            throw new RvtssError("Undo works on the active document only", status: 409,
                hint: "Activate the document's view in Revit first.");
        if (ctx.DryRun)
            return new Dict { ["status"] = "dry_run", ["would_undo"] = top };
        Core.RequireWritable("undo");
        ctx.UiApp.PostCommand(UndoCommandId());
        return new Dict
        {
            ["status"] = "posted", ["undoing"] = top,
            ["message"] = "Revit runs the undo right after this answer. Re-read the elements to verify; call "
                          + "undo_last_change(action='status') to see the next step.",
        };
    }

    /// <summary>register_undo_routes; also subscribes the DocumentChanged listener on Revit's main thread
    /// (startup.py: undo.install(HOST_APP.app)) and removes it again when the implementation is unloaded.</summary>
    public static void Register(RouteTable api)
    {
        api.Post("/undo/", UndoRoute, "undo");
        Entry.OnMainThread(app => Install(app.Application));
        Entry.OnStop(Uninstall);
    }
}
