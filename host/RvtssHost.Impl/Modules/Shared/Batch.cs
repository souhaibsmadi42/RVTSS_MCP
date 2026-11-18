namespace RvtssHost.Modules;

/// <summary>
/// Atomic batches: port of revit_mcp/batch.py.
///
/// Routes:
///     POST /batch/   run up to 20 RVTSS route payloads inside one TransactionGroup
///
/// The MCP side (tools/batch_tools.py) builds each payload with the real tool and
/// sends {commands: [{index, tool, endpoint, payload}], continue_on_error, dry_run}.
/// Each command runs through its normal route handler (its own named transaction,
/// failure collection and error envelope). The group is assimilated into one undo
/// step when every command succeeded, and rolled back on the first failure (unless
/// continue_on_error), for dry_run, or when anything unexpected happens.
/// </summary>
public static class Batch
{
    public const int MaxCommands = 20;

    // The Python ROUTE_TABLE (path -> raw, unprotected route handler) is Entry.Table.Routes.

    /// <summary>Revit-side allowlist (the MCP side has its own): single-document edits that open their own transaction.</summary>
    public static readonly string[] BatchableEndpoints =
    {
        "/set_parameters/", "/bulk_update_parameter/", "/transform_elements/", "/delete_elements/",
        "/create_elements/", "/element_types/", "/views/create/", "/views/graphics/", "/sheets/manage/",
        "/schedules/create/", "/batch_rename/", "/groups/manage/", "/parameters/global/", "/parameters/map/",
        "/annotation/tag/", "/annotation/text/", "/materials/manage/", "/views/filters/", "/sheets/revisions/",
        "/worksets/manage/", "/modify/elements/", "/views/extents/", "/sheets/viewports/", "/annotation/detail/",
    };

    public static void Register(RouteTable api)
    {
        api.Post("/batch/", RunBatch, "run_batch");
    }

    /// <summary>Response -> (http status, data dict). The data is cleaned first, as every pyRevit response was
    /// when the handler returned it (lists are plain lists, ids are integers).</summary>
    public static (int status, Dict data) UnpackResponse(Response? resp)
    {
        var status = resp == null || resp.Status == 0 ? 200 : resp.Status;
        var data = Py.Clean(resp?.Data) as Dict;
        return (status, data ?? new Dict { ["status"] = "error", ["error"] = "non-JSON response" });
    }

    /// <summary>'ok' | 'needs_confirmation' | 'failed' for one sub-result.</summary>
    public static string Classify(int httpStatus, Dict? data)
    {
        var st = data?.Get("status");
        if (httpStatus >= 400 || (st is string s && s == "error"))
            return "failed";
        if ((st is string p && p == "preview") || Py.Truthy(data?.Get("requires_confirmation")))
            return "needs_confirmation";
        return "ok";
    }

    /// <summary>Sub-results without bulky lists (the batch answer must stay readable).</summary>
    private static Dict Brief(Dict? data)
    {
        var o = new Dict();
        if (data == null)
            return o;
        foreach (var kv in data)
        {
            if (kv.Value is Lst list && list.Count > 25)
            {
                o[kv.Key] = list.Take(25).ToList();
                o[kv.Key + "_truncated"] = (long)list.Count;
            }
            else
            {
                o[kv.Key] = kv.Value;
            }
        }
        return o;
    }

    public static Dict? RunBatch(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.CheckModifiable(doc);
        var commands = ctx.List("commands");
        if (commands.Count == 0)
            throw new RvtssError($"'commands' is required (1-{MaxCommands} commands)");
        if (commands.Count > MaxCommands)
            throw new RvtssError($"A batch takes at most {MaxCommands} commands, got {commands.Count}",
                hint: "Split the work into several batches (each is its own undo step).");
        var dry = ctx.DryRun;
        if (!dry)
            Core.RequireWritable("batch_execute");
        var keepGoing = ctx.Bool("continue_on_error", false);
        var targetTitle = Utils.NormalizeString(doc.Title);
        var plan = new List<(object? index, object? tool, Route route, Dict payload)>();
        for (var i = 0; i < commands.Count; i++)
        {
            var cmd = commands[i] as Dict ?? new Dict();
            var endpoint = cmd.Get("endpoint");
            if (endpoint is not string path || Array.IndexOf(BatchableEndpoints, path) < 0)
                throw new RvtssError($"Command {i} ({Py.Str(endpoint)}) is not batchable", status: 400)
                    .With("batchable", BatchableEndpoints.Cast<object?>().ToList());
            if (!Entry.Table.Routes.TryGetValue(path, out var route))
                throw new RvtssError($"Command {i}: route {path} is not registered", status: 500);
            var payload = new Dict(cmd.Get("payload") as Dict ?? new Dict());
            payload.Pop("dry_run");
            var subDoc = payload.Get("document");
            if (Py.Truthy(subDoc) && !Core.ResolveDocument(ctx.ActiveDoc, subDoc).Equals(doc))
                throw new RvtssError($"Command {i} targets document '{Py.Str(subDoc)}' but the batch runs on '{targetTitle}'",
                    hint: "A batch is one transaction group on one document.");
            if (Py.Truthy(ctx.Data.Get("document")))
                payload["document"] = ctx.Data.Get("document");
            plan.Add((cmd.TryGetValue("index", out var index) ? index : (long)i,
                Py.Truthy(cmd.Get("tool")) ? cmd.Get("tool") : path, route, payload));
        }

        var results = new List<Dict>();
        var failed = false;
        bool rolledBack;
        var groupName = Py.Truthy(ctx.Get("name")) ? Py.Str(ctx.Get("name")) : $"batch of {plan.Count} commands";
        using (var group = new DB.TransactionGroup(doc, "RVTSS: " + groupName))
        {
            group.Start();
            Core.SetBatchState(true, dry);
            try
            {
                foreach (var (index, tool, route, payload) in plan)
                {
                    // Stands in for the HTTP request: the handler runs in-process, on this thread.
                    var sub = new Request
                    {
                        Method = "POST", Path = route.Path, Data = payload,
                        UiApp = Hosting.UiApp, UiDoc = ctx.UiDoc, Doc = ctx.ActiveDoc,
                    };
                    var (httpStatus, data) = UnpackResponse(route.Invoke(sub));
                    var outcome = Classify(httpStatus, data);
                    var entry = new Dict { ["index"] = index, ["tool"] = tool, ["outcome"] = outcome, ["result"] = Brief(data) };
                    if (outcome == "needs_confirmation")
                        entry["hint"] = "This command only produced a preview; add confirm=true to its arguments.";
                    results.Add(entry);
                    if (outcome != "ok")
                    {
                        failed = true;
                        if (!keepGoing)
                            break;
                    }
                }
                if (dry || (failed && !keepGoing))
                {
                    group.RollBack();
                    rolledBack = true;
                }
                else
                {
                    group.Assimilate();
                    rolledBack = false;
                }
            }
            catch
            {
                if (group.HasStarted() && !group.HasEnded())
                    group.RollBack();
                throw;
            }
            finally
            {
                Core.SetBatchState(false);
            }
        }
        var ran = results.Count;
        var o = new Dict
        {
            ["commands"] = (long)plan.Count, ["ran"] = (long)ran,
            ["succeeded"] = (long)results.Count(r => (string)r["outcome"]! == "ok"),
            ["failed"] = (long)results.Count(r => (string)r["outcome"]! != "ok"), ["rolled_back"] = rolledBack,
            ["committed"] = !rolledBack, ["results"] = results, ["document"] = targetTitle,
        };
        if (ran < plan.Count)
            o["not_run"] = plan.Skip(ran).Select(p => p.index).ToList();
        if (dry)
        {
            o["status"] = "dry_run";
            o["message"] = "Dry run: every command ran and the whole group was rolled back. Nothing was modified.";
        }
        else if (rolledBack)
        {
            o["status"] = "error";
            o["error"] = $"Command {Py.Str(results.First(r => (string)r["outcome"]! != "ok")["index"])} failed; "
                         + "the whole batch was rolled back - nothing was changed.";
            o["hint"] = "Fix the failing command (see results) and run the batch again.";
        }
        else if (failed)
        {
            o["status"] = "partial";
            o["message"] = "continue_on_error: failed commands changed nothing; the others are kept as one undo step.";
        }
        else
        {
            o["message"] = "All commands committed as one undo step.";
        }
        return o;
    }
}
