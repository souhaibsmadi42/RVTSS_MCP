namespace RvtssHost.Modules;

/// <summary>
/// Phases, design options, Revit links and saved selection sets (RVTSS v2.3): port of revit_mcp/model_state.py.
///
/// Routes:
///     POST /phases/manage/          list phases / phase filters / design options; set element phases;
///                                   set a view's phase and phase filter; elements of a design option
///     POST /links/manage/           list Revit links; reload, unload, reload_from a path; load a new link
///     POST /selection_sets/         list, save (ids or current selection), load (select), delete
///
/// The Revit API cannot create phases or design options; those stay manual.
/// </summary>
public static class ModelState
{
    // ------------------------------------------------------------------------- phases
    private static DB.Phase? FindPhase(DB.Document doc, object? reference)
    {
        if (reference == null || (reference is string s0 && (s0 == "" || s0 == "none")))
            return null;
        foreach (DB.Phase p in doc.Phases)
        {
            if (Py.Str(p.Id.Value) == Py.Str(reference)
                || Utils.NormalizeString(p.Name).ToLowerInvariant() == Py.Str(reference).Trim().ToLowerInvariant())
                return p;
        }
        var available = new List<string>();
        foreach (DB.Phase p in doc.Phases)
            available.Add(Utils.NormalizeString(p.Name));
        throw new RvtssError($"Phase '{Py.Str(reference)}' not found", status: 404).With("available", available);
    }

    private static Lst DesignOptions(DB.Document doc)
    {
        var result = new Lst();
        foreach (DB.DesignOption o in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.DesignOption)))
        {
            string? setName = null;
            try
            {
                var p = o.get_Parameter(DB.BuiltInParameter.OPTION_SET_ID);
                var osEl = p != null ? doc.GetElement(p.AsElementId()) : null;
                setName = osEl != null ? Utils.NormalizeString(osEl.Name) : null;
            }
            catch { /* option set name stays null */ }
            result.Add(new Dict
            {
                ["id"] = o.Id.Value, ["name"] = Utils.NormalizeString(o.Name), ["option_set"] = setName,
                ["is_primary"] = o.IsPrimary,
            });
        }
        return result;
    }

    private static List<DB.PhaseFilter> PhaseFilters(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.PhaseFilter)).Cast<DB.PhaseFilter>().ToList();

    private static void SetParam(DB.Element e, DB.BuiltInParameter bip, DB.ElementId value)
    {
        // Python: e.get_Parameter(...).Set(...) on a missing parameter is an AttributeError, caught by the callers
        var p = e.get_Parameter(bip) ?? throw new InvalidOperationException("'NoneType' object has no attribute 'Set'");
        p.Set(value);
    }

    public static Dict? Phases(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var filters = new Lst();
            foreach (var f in PhaseFilters(doc))
                filters.Add(new Dict { ["id"] = f.Id.Value, ["name"] = Utils.NormalizeString(f.Name) });
            var phaseList = new Lst();
            var i = 0;
            foreach (DB.Phase p in doc.Phases)
            {
                phaseList.Add(new Dict { ["id"] = p.Id.Value, ["name"] = Utils.NormalizeString(p.Name), ["sequence"] = i + 1 });
                i++;
            }
            var result = new Dict { ["phases"] = phaseList, ["phase_filters"] = filters, ["design_options"] = DesignOptions(doc) };
            if (ctx.Bool("counts", false))
            {
                foreach (Dict ph in phaseList)
                {
                    var f = new DB.ElementPhaseStatusFilter(Compat.MakeId(ph["id"]), DB.ElementOnPhaseStatus.New);
                    ph["new_elements"] = new DB.FilteredElementCollector(doc).WhereElementIsNotElementType().WherePasses(f)
                        .GetElementCount();
                }
            }
            return result;
        }
        if (action == "option_elements")
        {
            // the name test runs per option: ctx.Require("option") only fails when a design option exists
            var opt = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.DesignOption)).Cast<DB.DesignOption>()
                .Where(o => Utils.NormalizeString(o.Name).ToLowerInvariant() == Py.Str(ctx.Require("option")).Trim().ToLowerInvariant()
                            || Py.Str(o.Id.Value) == Py.Str(ctx.Get("option")))
                .ToList();
            if (opt.Count == 0)
                throw new RvtssError($"Design option '{Py.Str(ctx.Get("option"))}' not found", status: 404)
                    .With("available", DesignOptions(doc).Cast<Dict>().Select(o => o["name"]).ToList());
            var col = new DB.FilteredElementCollector(doc).WherePasses(new DB.ElementDesignOptionFilter(opt[0].Id));
            var ids = col.ToElementIds().Select(i => i.Value).ToList();
            var limit = ctx.I("limit", 500, 1, Core.MaxLimit);
            return new Dict
            {
                ["option"] = Utils.NormalizeString(opt[0].Name), ["count"] = ids.Count, ["element_ids"] = ids.Take(limit).ToList(),
                ["truncated"] = ids.Count > limit,
            };
        }
        if (action == "set_element_phase")
        {
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            if (elements.Count == 0)
                throw new RvtssError("element_ids is required");
            var created = Py.Truthy(ctx.Get("created")) ? FindPhase(doc, ctx.Get("created")) : null;
            var demolishedRef = ctx.Get("demolished");
            var demolished = !(demolishedRef == null || (demolishedRef is string ds && ds == ""))
                ? FindPhase(doc, demolishedRef)
                : null;
            var preview = Core.ConfirmGate(ctx, elements.Count, "set_element_phase");

            Dict Run()
            {
                var res = new Lst();
                foreach (var e in elements)
                {
                    var r = new Dict { ["id"] = e.Id.Value, ["ok"] = true };
                    try
                    {
                        if (created != null)
                            SetParam(e, DB.BuiltInParameter.PHASE_CREATED, created.Id);
                        if (demolishedRef != null)
                            SetParam(e, DB.BuiltInParameter.PHASE_DEMOLISHED,
                                demolished != null ? demolished.Id : DB.ElementId.InvalidElementId);
                    }
                    catch (Exception ex)
                    {
                        r["ok"] = false;
                        r["error"] = Utils.NormalizeString(ex.Message);
                    }
                    res.Add(r);
                }
                if (ctx.Bool("atomic", true) && res.Cast<Dict>().Any(r => !(bool)r["ok"]!))
                    throw new RvtssError("Phase could not be set on every element").With("results", res);
                return new Dict { ["results"] = res };
            }

            var dry = preview || ctx.DryRun;
            var (result, fails) = Core.RunTransaction(doc, "Set element phase", Run, dry);
            return Core.PreviewStatus(Core.CommitResult(result, fails, dry), preview);
        }
        if (action == "set_view_phase")
        {
            var v = Core.FindView(doc, ctx.Get("view"), uidoc: ctx.UiDoc)!;
            var ph = Py.Truthy(ctx.Get("phase")) ? FindPhase(doc, ctx.Get("phase")) : null;
            DB.PhaseFilter? pf = null;
            if (Py.Truthy(ctx.Get("phase_filter")))
            {
                var want = Py.Str(ctx.Get("phase_filter")).Trim().ToLowerInvariant();
                var matches = PhaseFilters(doc).Where(f => Utils.NormalizeString(f.Name).ToLowerInvariant() == want).ToList();
                if (matches.Count == 0)
                    throw new RvtssError($"Phase filter '{Py.Str(ctx.Get("phase_filter"))}' not found", status: 404);
                pf = matches[0];
            }

            Dict Run()
            {
                if (ph != null)
                    SetParam(v, DB.BuiltInParameter.VIEW_PHASE, ph.Id);
                if (pf != null)
                    SetParam(v, DB.BuiltInParameter.VIEW_PHASE_FILTER, pf.Id);
                return new Dict
                {
                    ["view_id"] = v.Id.Value, ["phase"] = ph != null ? Utils.NormalizeString(ph.Name) : null,
                    ["phase_filter"] = pf != null ? Utils.NormalizeString(pf.Name) : null,
                };
            }

            var (result, fails) = Core.RunTransaction(doc, "Set view phase", Run, ctx.DryRun);
            return Core.CommitResult(result, fails, ctx.DryRun);
        }
        throw new RvtssError("action must be list, option_elements, set_element_phase or set_view_phase");
    }

    // -------------------------------------------------------------------------- links
    private static List<DB.RevitLinkType> LinkTypes(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkType)).Cast<DB.RevitLinkType>().ToList();

    private static Dict LinkInfo(DB.Document doc, DB.RevitLinkType lt)
    {
        string? path = null;
        try
        {
            var ext = lt.GetExternalFileReference();
            path = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(ext.GetAbsolutePath());
        }
        catch { /* path stays null */ }
        string? status = null;
        // pyRevit called RevitLinkType.GetLinkedFileStatus(lt.Id) like a static method, which fails for the
        // instance method and falls through to IsLoaded: the status the route has always returned is "Loaded" /
        // "Unloaded".
        try
        {
            status = DB.RevitLinkType.IsLoaded(doc, lt.Id) ? "Loaded" : "Unloaded";
        }
        catch { /* status stays null */ }
        var inst = new List<long>();
        foreach (DB.Element i in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkInstance)))
            if (i.GetTypeId() == lt.Id)
                inst.Add(i.Id.Value);
        return new Dict
        {
            ["id"] = lt.Id.Value, ["name"] = Utils.NormalizeString(Utils.GetElementName(lt)), ["path"] = path, ["status"] = status,
            ["is_nested"] = lt.IsNestedLink, ["instance_ids"] = inst,
        };
    }

    private static DB.RevitLinkType FindLink(DB.Document doc, object? reference)
    {
        var key = Py.Str(reference).Trim().ToLowerInvariant();
        foreach (var lt in LinkTypes(doc))
        {
            var name = Utils.NormalizeString(Utils.GetElementName(lt)).ToLowerInvariant();
            if (Py.Str(lt.Id.Value) == Py.Str(reference) || name == key || name == key + ".rvt")
                return lt;
        }
        throw new RvtssError($"Revit link '{Py.Str(reference)}' not found", status: 404)
            .With("available", LinkTypes(doc).Select(l => Utils.NormalizeString(Utils.GetElementName(l))).ToList());
    }

    public static Dict? Links(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var items = LinkTypes(doc).Select(lt => (object?)LinkInfo(doc, lt)).ToList();
            return new Dict { ["count"] = items.Count, ["links"] = items };
        }
        if (action == "reload" || action == "unload" || action == "reload_from")
        {
            var lt = FindLink(doc, ctx.Require("link"));
            if (lt.IsNestedLink)
                throw new RvtssError("Nested links are reloaded through their parent link");
            if (ctx.DryRun)
                return new Dict { ["status"] = "dry_run", ["would"] = action, ["link"] = LinkInfo(doc, lt) };
            Core.RequireWritable(action + " link");
            if (doc.IsModifiable)
                throw new RvtssError("Links cannot be reloaded while a transaction is open", status: 409);
            DB.LinkLoadResult? res;
            if (action == "reload")
            {
                res = lt.Reload();
            }
            else if (action == "unload")
            {
                lt.Unload(null);
                res = null;
            }
            else
            {
                var mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(Py.Str(ctx.Require("path")));
                res = lt.LoadFrom(mp, new DB.WorksetConfiguration());
            }
            var result = new Dict { ["action"] = action, ["link"] = LinkInfo(doc, lt) };
            if (res != null)
            {
                try { result["load_result"] = res.LoadResult.ToString(); }
                catch { /* some results carry no load result */ }
            }
            return result;
        }
        if (action == "load")
        {
            var path = Py.Str(ctx.Require("path"));
            var placementName = ctx.Get("placement", "origin") as string;
            var placement = placementName switch
            {
                "origin" => DB.ImportPlacement.Origin,
                "center" => DB.ImportPlacement.Centered,
                "shared" => DB.ImportPlacement.Shared,
                _ => DB.ImportPlacement.Origin,
            };

            Dict Run()
            {
                var mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(path);
                var opts = new DB.RevitLinkOptions(ctx.Bool("relative", true));
                var res = DB.RevitLinkType.Create(doc, mp, opts);
                var inst = DB.RevitLinkInstance.Create(doc, res.ElementId, placement);
                return new Dict
                {
                    ["link_type_id"] = res.ElementId.Value, ["instance_id"] = inst.Id.Value,
                    ["load_result"] = res.LoadResult.ToString(),
                };
            }

            var (result, fails) = Core.RunTransaction(doc, "Load Revit link", Run, ctx.DryRun);
            return Core.CommitResult(result, fails, ctx.DryRun);
        }
        throw new RvtssError("action must be list, reload, unload, reload_from or load");
    }

    // ----------------------------------------------------------------- selection sets
    private static List<DB.SelectionFilterElement> Sets(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.SelectionFilterElement)).Cast<DB.SelectionFilterElement>().ToList();

    private static DB.SelectionFilterElement? FindSet(DB.Document doc, object? name)
    {
        var low = Py.Str(name).Trim().ToLowerInvariant();
        foreach (var s in Sets(doc))
            if (Utils.NormalizeString(s.Name).ToLowerInvariant() == low)
                return s;
        return null;
    }

    public static Dict? SelectionSets(Ctx ctx)
    {
        var doc = ctx.Doc;
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var sets = new Lst();
            foreach (var s in Sets(doc))
                sets.Add(new Dict { ["id"] = s.Id.Value, ["name"] = Utils.NormalizeString(s.Name), ["count"] = s.GetElementIds().Count });
            return new Dict { ["sets"] = sets };
        }
        var name = ctx.Require("name");
        var existing = FindSet(doc, name);
        if (action == "load")
        {
            if (existing == null)
                throw new RvtssError($"Selection set '{Py.Str(name)}' not found", status: 404);
            var ids = existing.GetElementIds().ToList();
            bool selected;
            if (ctx.UiDoc != null && ctx.UiDoc.Document.Equals(doc))
            {
                ctx.UiDoc.Selection.SetElementIds(Core.ToIdList(ids));
                selected = true;
            }
            else
            {
                selected = false;
            }
            return new Dict
            {
                ["name"] = Utils.NormalizeString(existing.Name), ["element_ids"] = ids.Take(1000).Select(i => i.Value).ToList(),
                ["count"] = ids.Count, ["selected_in_revit"] = selected,
            };
        }
        if (action == "save")
        {
            var ids = ctx.List("element_ids");
            if (ids.Count == 0)
            {
                if (ctx.UiDoc == null || !ctx.UiDoc.Document.Equals(doc))
                    throw new RvtssError("Pass element_ids (no active selection in this document)");
                ids = new Lst(ctx.UiDoc.Selection.GetElementIds().Select(i => (object?)i.Value));
            }
            if (ids.Count == 0)
                throw new RvtssError("Nothing to save: pass element_ids or select elements in Revit");
            if (existing != null && !ctx.Bool("overwrite", false))
                throw new RvtssError($"Selection set '{Py.Str(name)}' exists", status: 409, hint: "Pass overwrite=true.");
            var elements = Core.GetElements(doc, ids);

            Dict Run()
            {
                var s = existing;
                if (s == null)
                    s = DB.SelectionFilterElement.Create(doc, Py.Str(name));
                s.SetElementIds(Core.ToIdList(elements.Select(e => e.Id)));
                return new Dict { ["id"] = s.Id.Value, ["name"] = Utils.NormalizeString(s.Name), ["count"] = elements.Count };
            }

            var (result, fails) = Core.RunTransaction(doc, "Save selection set", Run, ctx.DryRun);
            return Core.CommitResult(result, fails, ctx.DryRun);
        }
        if (action == "delete")
        {
            if (existing == null)
                throw new RvtssError($"Selection set '{Py.Str(name)}' not found", status: 404);

            Dict Run()
            {
                doc.Delete(existing.Id);
                return new Dict { ["deleted"] = Utils.NormalizeString(name) };
            }

            var (result, fails) = Core.RunTransaction(doc, "Delete selection set", Run, ctx.DryRun);
            return Core.CommitResult(result, fails, ctx.DryRun);
        }
        throw new RvtssError("action must be list, save, load or delete");
    }

    /// <summary>register_model_state_routes</summary>
    public static void Register(RouteTable api)
    {
        api.Post("/phases/manage/", Phases, "phases");
        api.Post("/links/manage/", Links, "links");
        api.Post("/selection_sets/", SelectionSets, "selection_sets");
    }
}
