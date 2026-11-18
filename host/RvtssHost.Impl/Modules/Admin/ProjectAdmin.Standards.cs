using System.Text;

namespace RvtssHost.Modules;

// Transfer project standards and worksharing (project_admin.py).
public static partial class ProjectAdmin
{
    // ------------------------------------------------------- transfer project standards
    private static Func<DB.Document, List<DB.Element>> ClassCollector(Type cls) =>
        d => new DB.FilteredElementCollector(d).OfClass(cls).ToList();

    private static List<DB.Element> ViewTemplates(DB.Document d) =>
        new DB.FilteredElementCollector(d).OfClass(typeof(DB.View)).Cast<DB.View>().Where(v => v.IsTemplate)
            .Cast<DB.Element>().ToList();

    internal static readonly Dictionary<string, Func<DB.Document, List<DB.Element>>> StandardKinds = new()
    {
        ["view_templates"] = ViewTemplates,
        ["filters"] = ClassCollector(typeof(DB.ParameterFilterElement)),
        ["materials"] = ClassCollector(typeof(DB.Material)),
        ["line_patterns"] = ClassCollector(typeof(DB.LinePatternElement)),
        ["fill_patterns"] = ClassCollector(typeof(DB.FillPatternElement)),
        ["text_types"] = ClassCollector(typeof(DB.TextNoteType)),
        ["dimension_types"] = ClassCollector(typeof(DB.DimensionType)),
        ["filled_region_types"] = ClassCollector(typeof(DB.FilledRegionType)),
        ["wall_types"] = ClassCollector(typeof(DB.WallType)),
        ["floor_types"] = ClassCollector(typeof(DB.FloorType)),
        ["ceiling_types"] = ClassCollector(typeof(DB.CeilingType)),
        ["roof_types"] = ClassCollector(typeof(DB.RoofType)),
    };

    private sealed class DuplicateTypes(bool abort) : DB.IDuplicateTypeNamesHandler
    {
        public bool Called;

        public DB.DuplicateTypeAction OnDuplicateTypeNamesFound(DB.DuplicateTypeNamesHandlerArgs args)
        {
            Called = true;
            return abort ? DB.DuplicateTypeAction.Abort : DB.DuplicateTypeAction.UseDestinationTypes;
        }
    }

    private static Dictionary<string, DB.Element> NamedElements(DB.Document d, string kind)
    {
        var result = new Dictionary<string, DB.Element>();
        foreach (var e in StandardKinds[kind](d))
        {
            var n = Name(e);
            if (n.Length > 0 && !result.ContainsKey(n))
                result[n] = e;
        }
        return result;
    }

    /// <summary>repr() of a list of unicode strings as IronPython printed it in "{}".format(list): [u'a', u'b'].</summary>
    private static string ReprList(IEnumerable<string> items)
    {
        var sb = new StringBuilder("[");
        var first = true;
        foreach (var s in items)
        {
            if (!first)
                sb.Append(", ");
            first = false;
            var quote = s.Contains("'") && !s.Contains("\"") ? '"' : '\'';
            sb.Append("u").Append(quote);
            foreach (var ch in s)
            {
                if (ch == '\\') sb.Append("\\\\");
                else if (ch == quote) sb.Append('\\').Append(ch);
                else if (ch == '\n') sb.Append("\\n");
                else if (ch == '\r') sb.Append("\\r");
                else if (ch == '\t') sb.Append("\\t");
                else if (ch < 32 || ch > 126) sb.Append("\\u").Append(((int)ch).ToString("x4"));
                else sb.Append(ch);
            }
            sb.Append(quote);
        }
        return sb.Append(']').ToString();
    }

    public static Dict? TransferStandards(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var source = Core.ResolveDocument(ctx.ActiveDoc, ctx.Require("source", "title or path of another open document"));
        if (source.Equals(doc))
            throw new RvtssError("Source and target are the same document", hint: "Pass `document` for the target.");
        if (source.IsFamilyDocument)
            throw new RvtssError("The source must be a project, not a family", status: 409);
        var kinds = ctx.List("kinds");
        var bad = kinds.Where(k => !(k is string ks && StandardKinds.ContainsKey(ks))).ToList();
        var sortedKinds = string.Join(", ", StandardKinds.Keys.OrderBy(x => x, StringComparer.Ordinal));
        if (bad.Count > 0)
            throw new RvtssError($"Unknown kinds {ReprList(bad.Select(Py.Str))}: use {sortedKinds}");
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var result = new Dict();
            var wantedKinds = kinds.Count > 0
                ? kinds.Cast<string>().ToList()
                : StandardKinds.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();
            foreach (var k in wantedKinds)
            {
                var src = NamedElements(source, k);
                var dst = NamedElements(doc, k);
                var names = src.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();
                result[k] = new Dict
                {
                    ["in_source"] = names.Count, ["already_in_target"] = names.Count(n => dst.ContainsKey(n)),
                    ["new"] = names.Where(n => !dst.ContainsKey(n)).Take(ctx.I("limit", 100, 1, 1000)).ToList(),
                };
            }
            return new Dict { ["source"] = Utils.NormalizeString(source.Title), ["target"] = Utils.NormalizeString(doc.Title), ["kinds"] = result };
        }
        if (action != "copy")
            throw new RvtssError("action must be list or copy");
        if (kinds.Count == 0)
            throw new RvtssError($"'kinds' is required for copy: {sortedKinds}");
        var wanted = new HashSet<string>(ctx.List("names").Select(n => Py.Str(n).Trim().ToLowerInvariant()));
        var skipExisting = ctx.Bool("skip_existing", true);
        var toCopy = new List<DB.ElementId>();
        var skipped = new List<Dict>();
        var plan = new Dict();
        foreach (string k in kinds)
        {
            var src = NamedElements(source, k);
            var dst = NamedElements(doc, k);
            var picked = new List<string>();
            foreach (var n in src.Keys.OrderBy(x => x, StringComparer.Ordinal))
            {
                if (wanted.Count > 0 && !wanted.Contains(n.ToLowerInvariant()))
                    continue;
                if (skipExisting && dst.ContainsKey(n))
                {
                    skipped.Add(new Dict { ["kind"] = k, ["name"] = n, ["reason"] = "already in the target" });
                    continue;
                }
                picked.Add(n);
                toCopy.Add(src[n].Id);
            }
            plan[k] = picked;
        }
        if (wanted.Count > 0)
        {
            var found = new HashSet<string>(plan.Values.SelectMany(v => (List<string>)v!).Select(n => n.ToLowerInvariant()));
            foreach (var s in skipped)
                found.Add(((string)s["name"]!).ToLowerInvariant());
            var missing = wanted.Where(w => !found.Contains(w)).OrderBy(x => x, StringComparer.Ordinal).ToList();
            if (missing.Count > 0)
                throw new RvtssError($"Not found in the source: {ReprList(missing)}", status: 404,
                    hint: "transfer_project_standards(action='list') shows the names.");
        }
        var summary = new Dict
        {
            ["source"] = Utils.NormalizeString(source.Title), ["target"] = Utils.NormalizeString(doc.Title), ["to_copy"] = plan,
            ["to_copy_count"] = toCopy.Count, ["skipped"] = skipped.Take(200).ToList(), ["skipped_count"] = skipped.Count,
        };
        if (toCopy.Count == 0)
        {
            var empty = new Dict(summary);
            empty["message"] = "Nothing to copy.";
            return empty;
        }
        var preview = Core.ConfirmGate(ctx, toCopy.Count, "transfer_project_standards");
        var dry = preview || ctx.DryRun;
        var handler = new DuplicateTypes(Py.Str(ctx.Get("on_duplicate_types", "use_target")) == "abort");

        Dict Run()
        {
            var opts = new DB.CopyPasteOptions();
            opts.SetDuplicateTypeNamesHandler(handler);
            var newIds = DB.ElementTransformUtils.CopyElements(source, Core.ToIdList(toCopy), doc, DB.Transform.Identity, opts);
            var ids = newIds.Select(i => i.Value).ToList();
            return new Dict { ["copied_count"] = ids.Count, ["new_ids"] = ids.Take(500).ToList(), ["duplicate_type_names_found"] = handler.Called };
        }

        var (res, fails) = Core.RunTransaction(doc, "Transfer project standards", Run, dry);
        return Core.PreviewStatus(Core.CommitResult(res, fails, dry, summary), preview);
    }

    // ------------------------------------------------------------------- worksharing
    internal static DB.RevitLinkInstance LinkInstance(DB.Document doc, object? reference)
    {
        var key = Py.Str(reference).Trim().ToLowerInvariant();
        var links = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkInstance)).Cast<DB.RevitLinkInstance>().ToList();
        foreach (var li in links)
        {
            var names = new[] { Name(li).ToLowerInvariant(), Name(doc.GetElement(li.GetTypeId())).ToLowerInvariant() };
            if (Py.Str(li.Id.Value) == key || names.Contains(key) || names.Contains(key + ".rvt"))
                return li;
        }
        throw Core.NotFound("Revit link instance", reference, links.Select(li => Name(doc.GetElement(li.GetTypeId()))));
    }

    internal static string? CentralPath(DB.Document doc)
    {
        try
        {
            return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(doc.GetWorksharingCentralModelPath());
        }
        catch
        {
            return null;
        }
    }

    /// <summary>`normalize_string(x or "") or None`</summary>
    private static string? TextOrNull(string? value)
    {
        var text = Utils.NormalizeString(value ?? "");
        return text.Length > 0 ? text : null;
    }

    public static Dict? Worksharing(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "status"));
        if (action == "status")
        {
            var o = new Dict { ["workshared"] = doc.IsWorkshared };
            if (!doc.IsWorkshared)
            {
                o["message"] = "The model is not workshared.";
                return o;
            }
            o["central_path"] = CentralPath(doc);
            try { o["is_detached"] = doc.IsDetached; }
            catch { /* not available */ }
            var owned = new Lst();
            foreach (var w in new DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))
            {
                if (w.IsEditable || !string.IsNullOrEmpty(w.Owner))
                    owned.Add(new Dict
                    {
                        ["name"] = Utils.NormalizeString(w.Name), ["owner"] = TextOrNull(w.Owner), ["editable_by_you"] = w.IsEditable,
                    });
            }
            o["worksets_owned"] = owned;
            var items = new List<Dict>();
            foreach (var e in Core.GetElements(doc, ctx.List("element_ids").Take(500)))
            {
                var d = new Dict { ["id"] = e.Id.Value };
                try
                {
                    d["checkout_status"] = DB.WorksharingUtils.GetCheckoutStatus(doc, e.Id).ToString();
                    d["updates_status"] = DB.WorksharingUtils.GetModelUpdatesStatus(doc, e.Id).ToString();
                    var info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, e.Id);
                    var owner = TextOrNull(info.Owner);
                    var creator = TextOrNull(info.Creator);
                    var lastChangedBy = TextOrNull(info.LastChangedBy);
                    d["owner"] = owner;
                    d["creator"] = creator;
                    d["last_changed_by"] = lastChangedBy;
                }
                catch (Exception ex)
                {
                    d["error"] = Utils.NormalizeString(ex.Message);
                }
                items.Add(d);
            }
            if (items.Count > 0)
            {
                o["elements"] = items;
                o["owned_by_others"] = items.Where(d => d.Get("checkout_status") is string cs && cs == "OwnedByOtherUser")
                    .Select(d => d["id"]).ToList();
            }
            return o;
        }
        if (action == "relinquish" || action == "reload_latest")
        {
            if (!doc.IsWorkshared)
                throw new RvtssError("The model is not workshared", status: 409);
            var label = action == "relinquish" ? "Relinquish" : "Reload latest";
            if (ctx.DryRun)
                return new Dict
                {
                    ["status"] = "dry_run", ["would"] = action, ["central_path"] = CentralPath(doc),
                    ["message"] = "Dry run: nothing was sent to or read from central.",
                };
            Core.RequireWritable(label);
            RequireSyncPolicy(label);
            NoOpenTransaction(doc, label);
            if (action == "reload_latest")
            {
                doc.ReloadLatest(new DB.ReloadLatestOptions());
                return new Dict
                {
                    ["reloaded_latest"] = true, ["central_path"] = CentralPath(doc),
                    ["note"] = "Revit's undo history was cleared by the reload.",
                };
            }
            var relinquished = DB.WorksharingUtils.RelinquishOwnership(doc, new DB.RelinquishOptions(true),
                new DB.TransactWithCentralOptions());
            var o = new Dict { ["relinquished"] = true, ["central_path"] = CentralPath(doc) };
            try
            {
                // pyRevit called items.GetRelinquishedElements() / GetRelinquishedWorksets(); RelinquishedItems has no
                // such methods, so the call failed and the route never returned "items". Same here.
                var elementsCall = relinquished.GetType().GetMethod("GetRelinquishedElements", Type.EmptyTypes);
                var worksetsCall = relinquished.GetType().GetMethod("GetRelinquishedWorksets", Type.EmptyTypes);
                if (elementsCall == null || worksetsCall == null)
                    throw new MissingMethodException("GetRelinquishedElements");
                var elementsResult = (System.Collections.ICollection)elementsCall.Invoke(relinquished, null)!;
                var worksetsResult = (System.Collections.ICollection)worksetsCall.Invoke(relinquished, null)!;
                o["items"] = new Dict { ["elements"] = elementsResult.Count, ["worksets"] = worksetsResult.Count };
            }
            catch { /* no item counts */ }
            return o;
        }
        if (action == "acquire_coordinates" || action == "publish_coordinates")
        {
            var li = LinkInstance(doc, ctx.Require("link"));
            var linkDoc = li.GetLinkDocument();
            if (linkDoc == null)
                throw new RvtssError("The link is not loaded", status: 409, hint: "manage_links(action='reload') first.");
            var brief = new Dict { ["link_instance_id"] = li.Id.Value, ["link"] = Name(doc.GetElement(li.GetTypeId())) };
            if (action == "acquire_coordinates")
            {
                Dict RunAcquire()
                {
                    doc.AcquireCoordinates(li.Id);
                    var o2 = new Dict(brief);
                    o2["acquired"] = true;
                    o2["location"] = Location(doc, ctx.Unit);
                    return o2;
                }

                var (res, fails) = Core.RunTransaction(doc, "Acquire coordinates", RunAcquire, ctx.DryRun);
                return Core.CommitResult(res, fails, ctx.DryRun);
            }
            var target = new Dict(brief);
            target["link_location"] = Utils.NormalizeString(linkDoc.ActiveProjectLocation.Name);
            if (ctx.DryRun || !ctx.Confirmed)
                return new Dict
                {
                    ["status"] = ctx.DryRun ? "dry_run" : "preview", ["requires_confirmation"] = !ctx.DryRun,
                    ["would_publish_to"] = target,
                    ["message"] = "Publishing changes the linked file's shared coordinates; Revit will ask to save "
                                  + "the link. Re-run with confirm=true to apply.",
                };

            Dict RunPublish()
            {
                doc.PublishCoordinates(new DB.LinkElementId(li.Id, linkDoc.ActiveProjectLocation.Id));
                var o3 = new Dict(target);
                o3["published"] = true;
                return o3;
            }

            var (res2, fails2) = Core.RunTransaction(doc, "Publish coordinates", RunPublish);
            var published = Core.CommitResult(res2, fails2, false);
            published["note"] = "The linked model was modified in memory; save the link when Revit asks (or on sync).";
            return published;
        }
        throw new RvtssError("action must be status, relinquish, reload_latest, acquire_coordinates or "
                             + "publish_coordinates");
    }
}
