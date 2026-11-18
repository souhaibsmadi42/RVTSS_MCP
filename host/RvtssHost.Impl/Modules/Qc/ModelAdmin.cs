namespace RvtssHost.Modules;

/// <summary>
/// Model administration: worksets and purge (RVTSS v2.2). Port of revit_mcp/model_admin.py.
///
/// Routes:
///     POST /worksets/manage/   list (with element counts), create, rename, move elements, set active
///     POST /purge/             purgeable elements (Revit 2024+ API, older: unused family types); preview first
/// </summary>
public static class ModelAdmin
{
    public static void Register(RouteTable api)
    {
        api.Post("/worksets/manage/", Worksets, "worksets");
        api.Post("/purge/", Purge, "purge");
    }

    // -------------------------------------------------------------------- worksets
    private static List<DB.Workset> UserWorksets(DB.Document doc) =>
        new DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset).ToList();

    private static long WorksetIdInt(DB.Workset w) => w.Id.IntegerValue;

    private static DB.Workset FindWorkset(DB.Document doc, object? nameOrId)
    {
        var ws = UserWorksets(doc);
        var s = Py.Str(nameOrId).Trim();
        foreach (var w in ws)
        {
            if (Utils.NormalizeString(w.Name).ToLowerInvariant() == s.ToLowerInvariant()
                || WorksetIdInt(w).ToString(System.Globalization.CultureInfo.InvariantCulture) == s)
                return w;
        }
        throw Core.NotFound("Workset", nameOrId, ws.Select(w => w.Name));
    }

    private static long? Count(DB.Document doc, DB.Workset w)
    {
        try
        {
            return new DB.FilteredElementCollector(doc).WherePasses(new DB.ElementWorksetFilter(w.Id, false))
                .WhereElementIsNotElementType().GetElementCount();
        }
        catch
        {
            return null;
        }
    }

    public static Dict? Worksets(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var actionValue = ctx.Get("action", "list");
        var action = Py.Str(actionValue);
        if (!doc.IsWorkshared)
        {
            if (action == "list")
                return new Dict { ["workshared"] = false, ["worksets"] = new Lst(), ["message"] = "The model is not workshared." };
            throw new RvtssError("The model is not workshared", status: 409,
                hint: "Enable worksharing in Revit (Collaborate > Worksets) first.");
        }
        var table = doc.GetWorksetTable();
        if (action == "list")
        {
            var active = table.GetActiveWorksetId();
            var list = new List<Dict>();
            foreach (var w in UserWorksets(doc))
            {
                var d = new Dict
                {
                    ["id"] = WorksetIdInt(w), ["name"] = Utils.NormalizeString(w.Name), ["is_open"] = w.IsOpen,
                    ["is_editable"] = w.IsEditable,
                    ["owner"] = NullIfEmpty(Utils.NormalizeString(w.Owner ?? "")),
                    ["visible_by_default"] = w.IsVisibleByDefault, ["is_active"] = w.Id.Equals(active),
                };
                if (ctx.Bool("include_counts", true))
                    d["element_count"] = Count(doc, w);
                list.Add(d);
            }
            list = list.OrderBy(d => ((string)d["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
            return new Dict
            {
                ["workshared"] = true, ["count"] = (long)list.Count, ["worksets"] = list,
                ["empty"] = list.Where(d => d.Get("element_count") is long n && n == 0).Select(d => (object?)d["name"]).ToList(),
            };
        }
        if (action == "set_active")
        {
            var w = FindWorkset(doc, ctx.Require("workset"));
            if (Core.InBatch())
                throw new RvtssError("set_active cannot run in batch_execute (it is not a transaction and cannot be "
                                     + "rolled back)", hint: "Call manage_worksets(action='set_active') on its own.");
            if (ctx.DryRun)
                return new Dict
                {
                    ["status"] = "dry_run", ["would_activate"] = Utils.NormalizeString(w.Name),
                    ["message"] = "Dry run: the active workset was not changed.",
                };
            Core.RequireWritable("set_active workset");
            table.SetActiveWorksetId(w.Id);
            return new Dict { ["active_workset"] = Utils.NormalizeString(w.Name) };
        }
        var dry = ctx.DryRun;
        var preview = false;
        if (action == "move_elements")
        {
            var ids = ctx.List("element_ids");
            if (ids.Count == 0)
                throw new RvtssError("move_elements needs element_ids");
            preview = Core.ConfirmGate(ctx, ids.Count, "Moving elements to a workset");
            dry = dry || preview;
        }

        Dict Run()
        {
            if (action == "create")
            {
                var name = Py.Str(ctx.Require("name"));
                if (!DB.WorksetTable.IsWorksetNameUnique(doc, name))
                    throw new RvtssError($"Workset name '{name}' is already used", status: 409);
                var created = DB.Workset.Create(doc, name);
                return new Dict { ["workset"] = new Dict { ["id"] = WorksetIdInt(created), ["name"] = Utils.NormalizeString(created.Name) } };
            }
            if (action == "rename")
            {
                var w = FindWorkset(doc, ctx.Require("workset"));
                var name = Py.Str(ctx.Require("name"));
                var old = Utils.NormalizeString(w.Name);
                DB.WorksetTable.RenameWorkset(doc, w.Id, name);
                return new Dict { ["workset_id"] = WorksetIdInt(w), ["old_name"] = old, ["new_name"] = name };
            }
            if (action == "move_elements")
            {
                var w = FindWorkset(doc, ctx.Require("workset"));
                var moved = new Lst();
                var skipped = new Lst();
                foreach (var e in Core.GetElements(doc, ctx.List("element_ids")))
                {
                    var p = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM);
                    if (p == null || p.IsReadOnly)
                    {
                        skipped.Add(new Dict
                        {
                            ["id"] = e.Id.Value,
                            ["reason"] = "workset is read-only for this element (view-specific, in a group, hosted or a type)",
                        });
                        continue;
                    }
                    p.Set((int)WorksetIdInt(w));
                    moved.Add(e.Id.Value);
                }
                return new Dict { ["workset"] = Utils.NormalizeString(w.Name), ["moved"] = moved, ["skipped"] = skipped };
            }
            throw new RvtssError("action must be list, create, rename, move_elements or set_active");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Worksets: " + action, Run, dry);
        return Core.PreviewStatus(Core.CommitResult(res, fails, dry), preview && !ctx.DryRun);
    }

    private static string? NullIfEmpty(string s) => s.Length > 0 ? s : null;

    // ----------------------------------------------------------------------- purge
    private static readonly string[] FallbackSkip = { "OST_ProfileFamilies", "OST_DetailComponents" };

    /// <summary>(ids, method). Revit 2024+ exposes the Purge Unused query; the fallback (kept from the Python version
    /// for the case that the query fails): unused family types.</summary>
    private static (List<DB.ElementId> ids, string method) UnusedElements(DB.Document doc)
    {
        try
        {
            return (doc.GetUnusedElements(new HashSet<DB.ElementId>()).ToList(), "Document.GetUnusedElements (Revit 2024+)");
        }
        catch (Exception e)
        {
            Log.Write("GetUnusedElements failed, falling back: " + e.Message);
        }
        var used = new HashSet<long>();
        foreach (DB.FamilyInstance fi in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilyInstance)))
        {
            try { used.Add(fi.Symbol.Id.Value); }
            catch { continue; }
        }
        var ids = new List<DB.ElementId>();
        foreach (DB.Family fam in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
        {
            if (!fam.IsEditable || fam.IsInPlace)
                continue;
            var cat = fam.FamilyCategory;
            // only model families: annotation families (tags, heads, titles) and profiles are used without a
            // FamilyInstance, so "no instance" would wrongly mark them unused
            if (cat == null || cat.CategoryType != DB.CategoryType.Model || Array.IndexOf(FallbackSkip, Compat.BicFromCategory(cat)) >= 0)
                continue;
            var sids = fam.GetFamilySymbolIds().ToList();
            var unused = sids.Where(s => !used.Contains(s.Value)).ToList();
            // Revit keeps at least one type per family: delete the whole family when no type is used
            if (unused.Count > 0 && unused.Count == sids.Count)
                ids.Add(fam.Id);
            else
                ids.AddRange(unused);
        }
        return (ids, "unused loadable model family types (Revit " + (Hosting.RevitYear != 0 ? Hosting.RevitYear.ToString() : "<2024")
                     + " has no purge API; annotation and profile families are not checked)");
    }

    public static Dict? Purge(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        Core.CheckModifiable(doc);
        var cats = new HashSet<string>(ctx.List("categories").Select(c => Core.ResolveCategory(doc, c).Name), StringComparer.Ordinal);
        var exclude = new HashSet<long>(ctx.List("exclude_ids").Select(Py.ToInt));
        var (ids, method) = UnusedElements(doc);
        var candidates = new List<(DB.Element e, string cat)>();
        foreach (var eid in ids)
        {
            if (exclude.Contains(eid.Value))
                continue;
            var e = doc.GetElement(eid);
            if (e == null)
                continue;
            var cat = e.Category != null ? Utils.NormalizeString(e.Category.Name) : e.GetType().Name;
            if (cats.Count > 0 && !cats.Contains(cat))
                continue;
            candidates.Add((e, cat));
        }
        var byCat = new Dict();
        foreach (var (_, cat) in candidates)
            byCat[cat] = (byCat.TryGetValue(cat, out var n) ? (long)n! : 0L) + 1;
        var listing = new Lst();
        foreach (var (e, cat) in candidates.Take((int)ctx.Int("list_limit", 300, 1, 5000)!.Value))
        {
            var family = Utils.NormalizeString((e as DB.ElementType)?.FamilyName ?? "");
            listing.Add(new Dict
            {
                ["id"] = e.Id.Value, ["category"] = cat, ["name"] = Utils.NormalizeString(Utils.GetElementName(e)),
                ["family"] = family.Length > 0 ? family : null,
            });
        }
        var o = new Dict { ["method"] = method, ["candidates"] = (long)candidates.Count, ["by_category"] = byCat, ["elements"] = listing };
        if (candidates.Count == 0)
        {
            o["message"] = "Nothing to purge.";
            return o;
        }
        if (!ctx.Confirmed || ctx.DryRun)
        {
            o.Update(new Dict
            {
                ["status"] = "preview", ["requires_confirmation"] = true,
                ["message"] = "Preview only - nothing was deleted. Review the list, then call again with "
                              + "confirm=true (optionally categories / exclude_ids to narrow it).",
            });
            return o;
        }
        var passes = ctx.I("passes", 1, 1, 5);
        Core.RequireWritable("purge_unused");
        var deletedTotal = new Lst();
        var fails = new Lst();

        // all passes form one undo step; any failure rolls every pass back
        using var group = new DB.TransactionGroup(doc, "RVTSS: Purge unused");
        group.Start();
        try
        {
            var candidateIds = candidates.Select(c => c.e.Id).ToList();
            var (res, f) = Core.RunTransaction<Dict>(doc, "Purge unused", () =>
                new Dict { ["deleted"] = doc.Delete(Core.ToIdList(candidateIds)).Select(i => (object?)i.Value).ToList() });
            deletedTotal.AddRange((Lst)res["deleted"]!);
            fails.AddRange(f);
            for (var pass = 0; pass < passes - 1; pass++)
            {
                var (more, _) = UnusedElements(doc);
                more = more.Where(i =>
                {
                    if (exclude.Contains(i.Value))
                        return false;
                    if (cats.Count == 0)
                        return true;
                    var el = doc.GetElement(i);
                    return el != null && el.Category != null && cats.Contains(Utils.NormalizeString(el.Category.Name));
                }).ToList();
                if (more.Count == 0)
                    break;
                var moreIds = more;
                var (r, f2) = Core.RunTransaction<Dict>(doc, "Purge unused (next pass)", () =>
                    new Dict { ["deleted"] = doc.Delete(Core.ToIdList(moreIds)).Select(i => (object?)i.Value).ToList() });
                deletedTotal.AddRange((Lst)r["deleted"]!);
                fails.AddRange(f2);
            }
            group.Assimilate();
        }
        catch
        {
            if (group.HasStarted() && !group.HasEnded())
                group.RollBack();
            throw;
        }
        var outResult = Core.CommitResult(new Dict
        {
            ["deleted_count"] = (long)deletedTotal.Count, ["deleted_ids"] = deletedTotal.Take(500).ToList(), ["method"] = method,
            ["by_category"] = byCat,
        }, fails, false);
        outResult["note"] = "Deletion count includes dependent elements Revit removed with the purged ones. Undo is available.";
        return outResult;
    }
}
