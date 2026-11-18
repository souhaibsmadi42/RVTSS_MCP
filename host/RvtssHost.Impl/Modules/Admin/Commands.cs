using System.Text.RegularExpressions;

namespace RvtssHost.Modules;

/// <summary>
/// Ribbon command launcher (RVTSS v2.4): port of revit_mcp/commands.py.
///
/// Routes:
///     POST /commands/list/   Revit's postable ribbon commands (UI.PostableCommand), filtered by text
///     POST /commands/run/    post one command: Revit runs it right after the request returns, exactly as
///                            if the user had pressed the button (its dialog or tool opens for the user)
///
/// This covers every button RVTSS has no dedicated tool for. The command is not run by RVTSS: it is
/// queued with UIApplication.PostCommand, so nothing can be verified from the answer. Commands that save,
/// synchronize, undo or redo are refused here: they have their own guarded tools.
/// </summary>
public static class Commands
{
    /// <summary>command name pattern -> (reason, tool to use instead)</summary>
    private static readonly (Regex rx, string reason, string tool)[] Blocked =
    {
        (new Regex(@"^(Undo|Redo)$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant),
            "undo and redo go through the RVTSS ledger", "undo_last_change"),
        (new Regex(@"^(Save|SaveAs.*|SaveSelection)$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant),
            "saving is controlled by the RVTSS save policy", "save_document"),
        (new Regex(@"(Synchroni[sz]e|ReloadLatest|RelinquishAllMine)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant),
            "worksharing is controlled by the RVTSS sync policy", "sync_with_central"),
        (new Regex(@"^(ExitRevit|Close.*)$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant),
            "closing documents or Revit is not posted from RVTSS", "close_document"),
    };

    private static readonly Regex WordBreak =
        new(@"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", RegexOptions.CultureInvariant);

    /// <summary>'StructuralFoundationWall' -> 'Structural Foundation Wall' (pure, unit-tested).</summary>
    public static string SplitWords(object? name)
    {
        var outText = WordBreak.Replace(Py.Str(name), " ");
        return outText.Replace("_", " ").Trim();
    }

    /// <summary>(reason, replacement tool) when a command must not be posted, else null (pure, unit-tested).</summary>
    public static (string reason, string tool)? BlockedReason(object? name)
    {
        var text = Py.Str(name);
        foreach (var (rx, reason, tool) in Blocked)
            if (rx.IsMatch(text))
                return (reason, tool);
        return null;
    }

    /// <summary>Filter command names: every word of `contains` must appear in the name or its spaced label.</summary>
    public static (List<string> names, int total) MatchCommands(IEnumerable<string> names, object? contains = null, int limit = 200)
    {
        var text = (Py.Truthy(contains) ? Py.Str(contains) : "").ToLowerInvariant();
        var words = text.Split(new char[0], StringSplitOptions.RemoveEmptyEntries);
        var found = new List<string>();
        foreach (var n in names.OrderBy(x => x, StringComparer.Ordinal))
        {
            var hay = (n + " " + SplitWords(n)).ToLowerInvariant();
            if (words.All(w => hay.Contains(w)))
                found.Add(n);
        }
        return (found.Take(limit).ToList(), found.Count);
    }

    private static List<string> AllNames() => Enum.GetNames(typeof(PostableCommand)).ToList();

    private static (RevitCommandId cid, string label) CommandId(object? name = null, object? commandId = null)
    {
        if (Py.Truthy(commandId))
        {
            var found = RevitCommandId.LookupCommandId(Py.Str(commandId));
            if (found == null)
                throw new RvtssError($"Command id '{Py.Str(commandId)}' is not known to Revit", status: 404,
                    hint: "Use a PostableCommand name from list_revit_commands, or an add-in command id.");
            return (found, Py.Str(commandId));
        }
        var names = AllNames();
        var low = new Dictionary<string, string>();
        foreach (var n in names)
            low[n.ToLowerInvariant()] = n;
        var key = (Py.Truthy(name) ? Py.Str(name) : "").Replace(" ", "").ToLowerInvariant();
        if (!low.TryGetValue(key, out var real))
        {
            var (close, _) = MatchCommands(names, name, 15);
            throw Core.NotFound("Revit command", name, close.Count > 0 ? close : names.Take(15).ToList(),
                hint: "list_revit_commands(contains=...) searches the command names.");
        }
        var pc = (PostableCommand)Enum.Parse(typeof(PostableCommand), real);
        return (RevitCommandId.LookupPostableCommandId(pc), real);
    }

    public static Dict? ListCommands(Ctx ctx)
    {
        var names = AllNames();
        var limit = ctx.I("limit", 200, 1, 2000);
        var (found, total) = MatchCommands(names, ctx.Get("contains"), limit);
        var check = ctx.Bool("check_available", false);
        var uiapp = check ? ctx.UiApp : null;
        var items = new Lst();
        foreach (var n in found)
        {
            var item = new Dict { ["name"] = n, ["label"] = SplitWords(n) };
            var blocked = BlockedReason(n);
            if (blocked != null)
                item["blocked"] = "use " + blocked.Value.tool;
            if (check)
            {
                try
                {
                    item["available_now"] = uiapp!.CanPostCommand(
                        RevitCommandId.LookupPostableCommandId((PostableCommand)Enum.Parse(typeof(PostableCommand), n)));
                }
                catch
                {
                    item["available_now"] = null;
                }
            }
            items.Add(item);
        }
        return new Dict
        {
            ["count"] = total, ["returned"] = items.Count, ["truncated"] = total > items.Count, ["commands"] = items,
            ["note"] = "These are Revit's own ribbon commands. run_revit_command starts one for the user; "
                       + "prefer a dedicated RVTSS tool when one exists.",
        };
    }

    public static Dict? RunCommand(Ctx ctx)
    {
        var name = ctx.Get("name");
        var commandId = ctx.Get("command_id");
        if (!Py.Truthy(name) && !Py.Truthy(commandId))
            throw new RvtssError("Give 'name' (a PostableCommand name) or 'command_id'");
        var (cid, label) = CommandId(name, commandId);
        var blocked = BlockedReason(label);
        if (blocked != null)
            throw new RvtssError($"'{label}' is not posted by RVTSS: {blocked.Value.reason}", status: 403,
                hint: $"Use {blocked.Value.tool} instead.").With("code", "POLICY_DENIED");
        var uiapp = ctx.UiApp;
        if (uiapp.ActiveUIDocument == null)
            throw new RvtssError("No document is open in Revit", status: 409);
        var can = uiapp.CanPostCommand(cid);
        if (ctx.DryRun)
            return new Dict { ["status"] = "dry_run", ["command"] = label, ["label"] = SplitWords(label), ["available_now"] = can };
        if (!can)
            throw new RvtssError($"Revit cannot start '{label}' right now", status: 409,
                hint: "The command is disabled in the active view or document state (for example a plan "
                      + "command in a 3D view, or an open edit mode). Activate a suitable view and retry.");
        Core.RequireWritable($"Running the Revit command '{label}'");
        try
        {
            uiapp.PostCommand(cid);
        }
        catch (Exception e)
        {
            throw new RvtssError($"Revit refused to queue '{label}': {Py.Str(e.Message)}", status: 409,
                hint: "Only one command can be queued per request, and none while another is running.");
        }
        return new Dict
        {
            ["status"] = "posted", ["command"] = label, ["label"] = SplitWords(label),
            ["message"] = "Revit starts this command for the user right after this answer; its dialog or tool is "
                          + "now theirs to complete. RVTSS cannot see the outcome: re-read the model to verify.",
        };
    }

    /// <summary>register_command_routes</summary>
    public static void Register(RouteTable api)
    {
        api.Post("/commands/list/", ListCommands, "list_commands", needsDoc: false);
        api.Post("/commands/run/", RunCommand, "run_command", needsDoc: false);
    }
}
