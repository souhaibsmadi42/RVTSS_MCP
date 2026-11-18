namespace RvtssHost.Modules;

/// <summary>
/// Project-level model intelligence routes (RVTSS): port of revit_mcp/project_data.py.
///
/// Routes:
///     POST /project_overview/   project info, units, levels, grids, phases, worksets, design options
///     POST /list_links/         Revit links and CAD imports with status and transforms
///     POST /model_warnings/     warnings grouped by description, with element ids
///     POST /family_inventory/   loaded families grouped by category with type / instance counts
///     POST /find_views/         views with type, level, scale, template, sheet placement
///     POST /list_sheets/        sheets with title block, viewports and key parameters
///     POST /schedule_data/      read a schedule's table (paginated)
/// </summary>
public static partial class ProjectData
{
    /// <summary>register_project_data_routes</summary>
    public static void Register(RouteTable api)
    {
        // file access only: no `doc` argument, so the Python answered without waiting for Revit to be idle
        api.Raw("/rvtss_files/", new[] { "POST" },
            request => Core.Handle(request, RvtssFiles, "rvtss_files", needsDoc: false), apiContext: false);
        api.Post("/session_info/", SessionInfo, "session_info", needsDoc: false);
        api.Post("/project_overview/", ProjectOverview, "project_overview");
        api.Post("/list_links/", ListLinks, "list_links");
        api.Post("/model_warnings/", ModelWarnings, "model_warnings");
        api.Post("/family_inventory/", FamilyInventory, "family_inventory");
        api.Post("/find_views/", FindViews, "find_views");
        api.Post("/list_sheets/", ListSheets, "list_sheets");
        api.Post("/schedule_data/", ScheduleData, "schedule_data");
    }

    private const double RadToDeg = 180.0 / 3.141592653589793;

    private static string LowerOf(object? value) => Py.Truthy(value) ? Py.Str(value).ToLowerInvariant() : "";

    private static string? DisplayLengthUnit(DB.Document doc)
    {
        try
        {
            var fo = doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Length);
            return DB.LabelUtils.GetLabelForUnit(fo.GetUnitTypeId());
        }
        catch
        {
            return null;
        }
    }

    public static Dict? ProjectOverview(Ctx ctx)
    {
        var doc = ctx.Doc;
        var unit = ctx.Unit;
        var includeList = ctx.List("include");
        var include = new HashSet<string>(StringComparer.Ordinal);
        if (includeList.Count > 0)
        {
            foreach (var i in includeList)
                if (i is string s)
                    include.Add(s);
        }
        else
        {
            foreach (var s in new[] { "info", "levels", "grids", "phases", "worksets", "design_options" })
                include.Add(s);
        }
        var result = new Dict
        {
            ["document"] = Core.DescribeDocument(doc),
            ["revit_version"] = Hosting.RevitYear > 0 ? (object)(long)Hosting.RevitYear : null,
            ["display_length_unit"] = DisplayLengthUnit(doc),
            ["unit"] = unit,
        };
        if (include.Contains("info") && !doc.IsFamilyDocument)
        {
            var pi = doc.ProjectInformation;
            var info = new Dict();
            foreach (var p in ParamsUtil.ReadAll(doc, pi, unit))
                info[(string)p["name"]!] = p.ContainsKey("display") ? p["display"] : p.Get("value");
            result["project_information"] = info;
            try
            {
                var site = doc.SiteLocation;
                result["site"] = new Dict
                {
                    ["place"] = Utils.NormalizeString(site.PlaceName),
                    ["latitude_deg"] = Py.Round(site.Latitude * RadToDeg, 6),
                    ["longitude_deg"] = Py.Round(site.Longitude * RadToDeg, 6),
                };
            }
            catch { /* no site location */ }
        }
        if (include.Contains("levels"))
        {
            var levels = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Level)).Cast<DB.Level>()
                .OrderBy(lv => lv.Elevation).ToList();
            result["levels"] = levels.Select(lv => new Dict
            {
                ["id"] = lv.Id.Value, ["name"] = Utils.NormalizeString(lv.Name),
                ["elevation"] = Units.FromInternal(lv.Elevation, unit, 2),
            }).ToList();
        }
        if (include.Contains("grids") && !doc.IsFamilyDocument)
        {
            var grids = new List<Dict>();
            foreach (DB.Grid g in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Grid)))
            {
                var c = g.Curve;
                grids.Add(new Dict
                {
                    ["id"] = g.Id.Value, ["name"] = Utils.NormalizeString(g.Name),
                    ["start"] = Core.XyzList(c.GetEndPoint(0), unit),
                    ["end"] = Core.XyzList(c.GetEndPoint(1), unit),
                    ["curved"] = c is not DB.Line,
                });
            }
            result["grids"] = grids.OrderBy(g => (string)g["name"]!, StringComparer.Ordinal).ToList();
        }
        if (include.Contains("phases") && !doc.IsFamilyDocument)
        {
            var phases = new List<Dict>();
            foreach (DB.Phase p in doc.Phases)
                phases.Add(new Dict { ["id"] = p.Id.Value, ["name"] = Utils.NormalizeString(p.Name) });
            result["phases"] = phases;
        }
        if (include.Contains("worksets") && doc.IsWorkshared)
        {
            var ws = new DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset);
            var list = new List<Dict>();
            foreach (DB.Workset w in ws)
                list.Add(new Dict
                {
                    ["id"] = (long)w.Id.IntegerValue, ["name"] = Utils.NormalizeString(w.Name), ["is_open"] = w.IsOpen,
                    ["is_editable"] = w.IsEditable, ["owner"] = Utils.NormalizeString(w.Owner ?? ""),
                });
            result["worksets"] = list;
            try
            {
                var table = doc.GetWorksetTable();
                result["active_workset"] = Utils.NormalizeString(table.GetWorkset(table.GetActiveWorksetId()).Name);
            }
            catch { /* no active workset */ }
        }
        if (include.Contains("design_options") && !doc.IsFamilyDocument)
        {
            var opts = new List<Dict>();
            foreach (DB.DesignOption o in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.DesignOption)))
            {
                string? setName;
                try
                {
                    setName = Utils.NormalizeString(doc.GetElement(o.get_Parameter(DB.BuiltInParameter.OPTION_SET_ID).AsElementId()).Name);
                }
                catch
                {
                    setName = null;
                }
                opts.Add(new Dict
                {
                    ["id"] = o.Id.Value, ["name"] = Utils.NormalizeString(o.Name), ["is_primary"] = o.IsPrimary,
                    ["option_set"] = setName,
                });
            }
            result["design_options"] = opts;
        }
        return result;
    }

    public static Dict? ListLinks(Ctx ctx)
    {
        var doc = ctx.Doc;
        var unit = ctx.Unit;
        var links = new List<Dict>();
        foreach (DB.RevitLinkInstance inst in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkInstance)))
        {
            var ltype = doc.GetElement(inst.GetTypeId());
            var info = new Dict
            {
                ["instance_id"] = inst.Id.Value, ["type_id"] = ltype != null ? ltype.Id.Value : null,
                ["name"] = Utils.NormalizeString(inst.Name), ["pinned"] = inst.Pinned,
            };
            try
            {
                var reference = DB.ExternalFileUtils.GetExternalFileReference(doc, ltype!.Id);
                info["path"] = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(reference.GetAbsolutePath());
                info["status"] = reference.GetLinkedFileStatus().ToString();
            }
            catch { /* no external file reference */ }
            var ldoc = inst.GetLinkDocument();
            info["loaded"] = ldoc != null;
            try
            {
                var tr = inst.GetTotalTransform();
                info["transform"] = new Dict
                {
                    ["origin"] = Core.XyzList(tr.Origin, unit),
                    ["rotation_deg"] = Py.Round(Math.Atan2(tr.BasisX.Y, tr.BasisX.X) * RadToDeg, 4),
                };
            }
            catch { /* no transform */ }
            if (ldoc != null)
            {
                info["link_title"] = Utils.NormalizeString(ldoc.Title);
                if (ctx.Bool("include_counts", false))
                {
                    var order = new List<string>();
                    var counts = new Dictionary<string, long>(StringComparer.Ordinal);
                    foreach (var e in new DB.FilteredElementCollector(ldoc).WhereElementIsNotElementType())
                    {
                        if (e.Category != null && e.Category.CategoryType == DB.CategoryType.Model)
                        {
                            var n = Utils.NormalizeString(e.Category.Name);
                            if (!counts.ContainsKey(n))
                            {
                                counts[n] = 0;
                                order.Add(n);
                            }
                            counts[n]++;
                        }
                    }
                    var top = new Dict();
                    foreach (var n in order.OrderByDescending(x => counts[x]).Take(40))
                        top[n] = counts[n];
                    info["model_category_counts"] = top;
                }
            }
            links.Add(info);
        }
        var imports = new List<Dict>();
        foreach (DB.ImportInstance imp in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ImportInstance)))
        {
            try
            {
                imports.Add(new Dict
                {
                    ["id"] = imp.Id.Value, ["name"] = Utils.NormalizeString(imp.Category != null ? imp.Category.Name : ""),
                    ["is_linked"] = imp.IsLinked, ["view_specific"] = imp.ViewSpecific,
                    ["owner_view_id"] = Compat.IsValidId(imp.OwnerViewId) ? imp.OwnerViewId.Value : (long?)null,
                    ["pinned"] = imp.Pinned,
                });
            }
            catch { continue; }
        }
        return new Dict
        {
            ["revit_links"] = links, ["revit_link_count"] = (long)links.Count,
            ["not_loaded"] = links.Where(l => !(bool)l["loaded"]!).Select(l => l["name"]).ToList(),
            ["cad_imports"] = imports, ["cad_import_count"] = (long)imports.Count,
            ["cad_imported_not_linked"] = (long)imports.Count(i => !(bool)i["is_linked"]!),
        };
    }

    public static Dict? ModelWarnings(Ctx ctx)
    {
        var doc = ctx.Doc;
        var order = new List<string>();
        var groups = new Dictionary<string, Dict>(StringComparer.Ordinal);
        foreach (var w in doc.GetWarnings())
        {
            var text = Utils.NormalizeString(w.GetDescriptionText());
            if (!groups.TryGetValue(text, out var g))
            {
                g = new Dict
                {
                    ["description"] = text, ["count"] = 0L, ["severity"] = w.GetSeverity().ToString(), ["element_ids"] = new Lst(),
                };
                groups[text] = g;
                order.Add(text);
            }
            g["count"] = (long)g["count"]! + 1;
            var elementIds = (Lst)g["element_ids"]!;
            if (elementIds.Count < ctx.I("ids_per_warning", 30))
            {
                var ids = new Lst();
                foreach (var i in w.GetFailingElements())
                    ids.Add(i.Value);
                try
                {
                    foreach (var i in w.GetAdditionalElements())
                        ids.Add(i.Value);
                }
                catch { /* no additional elements */ }
                elementIds.Add(ids);
            }
        }
        var items = order.Select(k => groups[k]).OrderByDescending(g => (long)g["count"]!).ToList();
        var contains = LowerOf(ctx.Get("contains"));
        if (contains.Length > 0)
            items = items.Where(g => ((string)g["description"]!).ToLowerInvariant().Contains(contains)).ToList();
        var (page, meta) = Filters.Paginate(items, ctx.Int("offset", 0), ctx.Int("limit", 50, 1, 500));
        return new Dict
        {
            ["total_warnings"] = groups.Values.Sum(g => (long)g["count"]!), ["distinct_warnings"] = (long)groups.Count,
            ["pagination"] = meta, ["warnings"] = page,
        };
    }

    public static Dict? FamilyInventory(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        DB.ElementId? catFilter = null;
        if (Py.Truthy(ctx.Get("category")))
            catFilter = Core.ResolveCategory(doc, ctx.Get("category")).Id;
        var contains = LowerOf(ctx.Get("contains"));
        var instanceCounts = new Dictionary<long, long>();
        foreach (DB.FamilyInstance fi in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilyInstance)))
        {
            try
            {
                var k = fi.Symbol.Id.Value;
                instanceCounts[k] = (instanceCounts.TryGetValue(k, out var c0) ? c0 : 0) + 1;
            }
            catch { continue; }
        }
        var fams = new List<Dict>();
        foreach (DB.Family fam in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
        {
            var cat = fam.FamilyCategory;
            if (catFilter != null && (cat == null || cat.Id != catFilter))
                continue;
            var name = Utils.NormalizeString(fam.Name);
            if (contains.Length > 0 && !name.ToLowerInvariant().Contains(contains))
                continue;
            var types = new List<Dict>();
            long total = 0;
            foreach (var sid in fam.GetFamilySymbolIds())
            {
                var s = doc.GetElement(sid);
                var n = instanceCounts.TryGetValue(sid.Value, out var c1) ? c1 : 0;
                total += n;
                types.Add(new Dict { ["id"] = sid.Value, ["name"] = Utils.NormalizeString(Utils.GetElementName(s)), ["instances"] = n });
            }
            var entry = new Dict
            {
                ["id"] = fam.Id.Value, ["name"] = name, ["category"] = cat != null ? Utils.NormalizeString(cat.Name) : null,
                ["in_place"] = fam.IsInPlace, ["editable"] = fam.IsEditable, ["type_count"] = (long)types.Count,
                ["instance_count"] = total,
            };
            if (ctx.Bool("include_types", true))
                entry["types"] = types.OrderBy(t => (string)t["name"]!, StringComparer.Ordinal).ToList();
            fams.Add(entry);
        }
        fams = fams.OrderBy(f => (f["category"] as string) ?? "", StringComparer.Ordinal)
            .ThenBy(f => (string)f["name"]!, StringComparer.Ordinal).ToList();
        if (ctx.Bool("unused_only", false))
            fams = fams.Where(f => (long)f["instance_count"]! == 0).ToList();
        var (page, meta) = Filters.Paginate(fams, ctx.Int("offset", 0), ctx.Int("limit", 100, 1, Core.MaxLimit));
        var byCat = new Dict();
        foreach (var f in fams)
        {
            var key = (f["category"] as string) ?? "(none)";
            byCat[key] = (byCat.TryGetValue(key, out var v) ? (long)v! : 0L) + 1;
        }
        return new Dict
        {
            ["family_count"] = (long)fams.Count, ["families_by_category"] = byCat, ["pagination"] = meta, ["families"] = page,
        };
    }

    private static Dictionary<long, string?> SheetOfViews(DB.Document doc)
    {
        var placed = new Dictionary<long, string?>();
        foreach (DB.Viewport vp in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Viewport)))
        {
            var sh = doc.GetElement(vp.SheetId);
            placed[vp.ViewId.Value] = sh != null ? Utils.NormalizeString(((DB.ViewSheet)sh).SheetNumber) : null;
        }
        foreach (DB.ScheduleSheetInstance ssi in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ScheduleSheetInstance)))
        {
            var sh = doc.GetElement(ssi.OwnerViewId);
            var key = ssi.ScheduleId.Value;
            if (!placed.ContainsKey(key))
                placed[key] = sh != null ? Utils.NormalizeString(((DB.ViewSheet)sh).SheetNumber) : null;
        }
        return placed;
    }

    public static Dict? FindViews(Ctx ctx)
    {
        var doc = ctx.Doc;
        var vtypes = new HashSet<string>(ctx.List("view_types").Select(t => Py.Str(t).ToLowerInvariant()), StringComparer.Ordinal);
        var contains = LowerOf(ctx.Get("name_contains"));
        var templates = ctx.Get("templates", "exclude"); // exclude | include | only
        var placed = !doc.IsFamilyDocument ? SheetOfViews(doc) : new Dictionary<long, string?>();
        var onSheet = ctx.Get("on_sheet"); // None | True | False
        var templatesText = templates as string;
        var result = new List<Dict>();
        foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
        {
            if (v.ViewType == DB.ViewType.Internal || v.ViewType == DB.ViewType.ProjectBrowser
                || v.ViewType == DB.ViewType.SystemBrowser)
                continue;
            if ((templatesText == "exclude" && v.IsTemplate) || (templatesText == "only" && !v.IsTemplate))
                continue;
            var vt = v.ViewType.ToString();
            if (vtypes.Count > 0 && !vtypes.Contains(vt.ToLowerInvariant()))
                continue;
            var name = Utils.NormalizeString(v.Name);
            if (contains.Length > 0 && !name.ToLowerInvariant().Contains(contains))
                continue;
            placed.TryGetValue(v.Id.Value, out var sheet);
            var hasSheet = !string.IsNullOrEmpty(sheet);
            if ((onSheet is bool ob && ob && !hasSheet) || (onSheet is bool ob2 && !ob2 && hasSheet))
                continue;
            var d = new Dict { ["id"] = v.Id.Value, ["name"] = name, ["view_type"] = vt, ["is_template"] = v.IsTemplate, ["sheet"] = sheet };
            try { d["scale"] = (long)v.Scale; }
            catch { /* no scale */ }
            try
            {
                if (Compat.IsValidId(v.ViewTemplateId))
                    d["template"] = Utils.NormalizeString(doc.GetElement(v.ViewTemplateId).Name);
            }
            catch { /* no template */ }
            try
            {
                if (v is DB.ViewPlan vp && vp.GenLevel != null)
                    d["level"] = Utils.NormalizeString(vp.GenLevel.Name);
            }
            catch { /* no level */ }
            try { d["detail_level"] = v.DetailLevel.ToString(); }
            catch { /* no detail level */ }
            result.Add(d);
        }
        result = result.OrderBy(d => (string)d["view_type"]!, StringComparer.Ordinal)
            .ThenBy(d => (string)d["name"]!, StringComparer.Ordinal).ToList();
        var (page, meta) = Filters.Paginate(result, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, Core.MaxLimit));
        var byType = new Dict();
        foreach (var d in result)
        {
            var key = (string)d["view_type"]!;
            byType[key] = (byType.TryGetValue(key, out var n) ? (long)n! : 0L) + 1;
        }
        return new Dict { ["count"] = (long)result.Count, ["by_type"] = byType, ["pagination"] = meta, ["views"] = page };
    }

    public static Dict? ListSheets(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var prms = ctx.List("parameters");
        var contains = LowerOf(ctx.Get("contains"));
        var tbs = new Dictionary<long, Lst>();
        foreach (var tb in new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                     .WhereElementIsNotElementType())
        {
            var key = tb.OwnerViewId.Value;
            if (!tbs.TryGetValue(key, out var list))
                tbs[key] = list = new Lst();
            list.Add(Core.ElementBrief(doc, tb));
        }
        var sheets = new List<Dict>();
        foreach (DB.ViewSheet sh in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
        {
            if (sh.IsTemplate)
                continue;
            var num = Utils.NormalizeString(sh.SheetNumber);
            var name = Utils.NormalizeString(sh.Name);
            if (contains.Length > 0 && !(num + " " + name).ToLowerInvariant().Contains(contains))
                continue;
            var vps = new Lst();
            foreach (var vid in sh.GetAllPlacedViews())
            {
                var v = doc.GetElement(vid);
                if (v != null)
                    vps.Add(new Dict
                    {
                        ["id"] = v.Id.Value, ["name"] = Utils.NormalizeString(v.Name),
                        ["view_type"] = ((DB.View)v).ViewType.ToString(),
                    });
            }
            var d = new Dict
            {
                ["id"] = sh.Id.Value, ["number"] = num, ["name"] = name, ["placeholder"] = sh.IsPlaceholder,
                ["views"] = vps, ["title_blocks"] = tbs.TryGetValue(sh.Id.Value, out var found) ? found : new Lst(),
            };
            try
            {
                d["revisions"] = sh.GetAllRevisionIds().Select(r => Utils.NormalizeString(doc.GetElement(r).Name)).ToList();
            }
            catch { /* no revisions */ }
            if (prms.Count > 0)
            {
                var values = new Dict();
                foreach (var p in ParamsUtil.ReadAll(doc, sh, ctx.Unit, prms))
                    values[Py.Str(p["name"])] = p.ContainsKey("display") ? p["display"] : p.Get("value");
                d["parameters"] = values;
            }
            sheets.Add(d);
        }
        sheets = sheets.OrderBy(s => (string)s["number"]!, StringComparer.Ordinal).ToList();
        var (page, meta) = Filters.Paginate(sheets, ctx.Int("offset", 0), ctx.Int("limit", 100, 1, Core.MaxLimit));
        return new Dict
        {
            ["count"] = (long)sheets.Count, ["pagination"] = meta, ["sheets"] = page,
            ["sheets_without_views"] = (long)sheets.Count(s => ((Lst)s["views"]!).Count == 0 && !(bool)s["placeholder"]!),
            ["sheets_without_title_block"] = (long)sheets.Count(s => ((Lst)s["title_blocks"]!).Count == 0 && !(bool)s["placeholder"]!),
        };
    }

    public static Dict? ScheduleData(Ctx ctx)
    {
        var doc = ctx.Doc;
        var sid = ctx.Get("schedule");
        if (sid == null)
            throw new RvtssError("'schedule' (id or name) is required");
        DB.Element? sched = null;
        var sidText = Py.Str(sid);
        if (Py.IsInt(sid) || (sidText.Length > 0 && sidText.All(char.IsDigit)))
        {
            sched = doc.GetElement(Compat.MakeId(Py.ToInt(sid)));
        }
        else
        {
            foreach (DB.ViewSchedule v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSchedule)))
            {
                if (Utils.NormalizeString(v.Name).ToLowerInvariant() == sidText.ToLowerInvariant())
                {
                    sched = v;
                    break;
                }
            }
        }
        if (sched is not DB.ViewSchedule schedule)
            throw Core.NotFound("Schedule", sid,
                new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSchedule)).Cast<DB.ViewSchedule>()
                    .Where(v => !v.IsTemplate).Select(v => (string?)v.Name).ToList());
        var table = schedule.GetTableData();
        var body = table.GetSectionData(DB.SectionType.Body);
        int rows = body.NumberOfRows, cols = body.NumberOfColumns;
        var dataRows = new List<Lst>();
        for (var r = 0; r < rows; r++)
        {
            var row = new Lst();
            for (var c = 0; c < cols; c++)
                row.Add(schedule.GetCellText(DB.SectionType.Body, r, c) ?? "");
            dataRows.Add(row);
        }
        var headerRows = 1;
        try
        {
            if (!schedule.Definition.ShowHeaders)
                headerRows = 0;
        }
        catch { /* keep the default */ }
        var headers = headerRows > 0 && dataRows.Count > 0 ? dataRows[0] : new Lst();
        var records = dataRows.Skip(headerRows).ToList();
        var (page, meta) = Filters.Paginate(records, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, 2000));
        return new Dict
        {
            ["schedule_id"] = schedule.Id.Value, ["name"] = Utils.NormalizeString(schedule.Name), ["columns"] = headers,
            ["row_count"] = (long)records.Count, ["pagination"] = meta, ["rows"] = page,
        };
    }

    public static Dict? SessionInfo(Ctx ctx)
    {
        var docs = Core.AllDocuments(ctx.ActiveDoc).Select(Core.DescribeDocument).ToList();
        var active = ctx.ActiveDoc;
        var result = new Dict
        {
            ["revit_version"] = Hosting.RevitYear > 0 ? (object)(long)Hosting.RevitYear : null,
            // the Python reported revit_mcp.__version__ and RVTSS_VERSION: one version in the C# host
            ["extension_version"] = Entry.RvtssVersion,
            ["rvtss_version"] = Entry.RvtssVersion,
            ["active_document"] = active != null ? Utils.NormalizeString(active.Title) : null,
            ["open_documents"] = docs.Where(d => !(bool)d["is_linked"]!).ToList(),
            ["linked_documents"] = docs.Where(d => (bool)d["is_linked"]!).Select(d => d["title"]).ToList(),
        };
        try
        {
            var app = ctx.App;
            result["revit_build"] = app.VersionBuild;
            result["pyrevit_language"] = app.Language.ToString();
        }
        catch { /* not available */ }
        if (ctx.UiDoc != null && active != null)
        {
            try
            {
                var v = ctx.UiDoc.ActiveView;
                result["active_view"] = new Dict { ["id"] = v.Id.Value, ["name"] = Utils.NormalizeString(v.Name), ["type"] = v.ViewType.ToString() };
                result["selection_count"] = (long)ctx.UiDoc.Selection.GetElementIds().Count;
            }
            catch { /* no active view */ }
        }
        try
        {
            var shared = ctx.App.SharedParametersFilename;
            result["shared_parameter_file"] = string.IsNullOrEmpty(shared) ? null : shared;
            var template = ctx.App.FamilyTemplatePath;
            result["family_template_path"] = string.IsNullOrEmpty(template) ? null : template;
        }
        catch { /* not available */ }
        result["rvtss_data_folder"] = Core.RvtssHome();
        try { result["security"] = SecureApi.SecurityStatus(); }
        catch { /* security status is optional */ }
        // keys kept from the Python host: they describe the runtime of the add-in here
        result["python_version"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription;
        result["python_engine"] = "csharp";
        result["temp_dir"] = Path.GetTempPath().TrimEnd('\\', '/');
        result["pyrevit_version"] = null;
        return result;
    }

    /// <summary>str.splitlines() for text read in universal-newline mode.</summary>
    private static List<string> SplitLines(string text)
    {
        var lines = text.Replace("\r\n", "\n").Replace("\r", "\n").Split(new[] { '\n' }).ToList();
        if (lines.Count > 0 && lines[lines.Count - 1].Length == 0)
            lines.RemoveAt(lines.Count - 1);
        return lines;
    }

    private static string ReadShared(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = new StreamReader(stream, new UTF8Encoding(false), true);
        return reader.ReadToEnd();
    }

    /// <summary>config.json / qc_rules.json / today's audit log from %APPDATA%/RVTSS (secrets masked).</summary>
    public static Dict? RvtssFiles(Ctx ctx)
    {
        var kind = ctx.Require("kind") as string;
        var home = Core.RvtssHome();
        if (kind == "config" || kind == "qc_rules")
        {
            var path = Path.Combine(home, kind == "config" ? "config.json" : "qc_rules.json");
            if (!File.Exists(path))
                return new Dict { ["kind"] = kind, ["path"] = path, ["exists"] = false, ["content"] = new Dict() };
            object? content;
            try
            {
                content = Py.JsonLoads(ReadShared(path));
            }
            catch (System.Text.Json.JsonException e)
            {
                return new Dict { ["kind"] = kind, ["path"] = path, ["exists"] = true, ["error"] = $"invalid JSON: {e.Message}" };
            }
            return new Dict { ["kind"] = kind, ["path"] = path, ["exists"] = true, ["content"] = Security.RedactMapping(content) };
        }
        if (kind == "log_today")
        {
            var path = Path.Combine(home, "logs", $"rvtss-{DateTime.Now:yyyyMMdd}.log");
            var lines = new List<string>();
            if (File.Exists(path))
                lines = SplitLines(ReadShared(path));
            var n = ctx.I("max_lines", 200, 1, 2000);
            var tail = lines.Skip(Math.Max(0, lines.Count - n)).Select(l => (object?)Security.Redact(l)).ToList();
            return new Dict { ["kind"] = kind, ["path"] = path, ["lines"] = tail, ["total_lines"] = (long)lines.Count };
        }
        throw new RvtssError("kind must be config, qc_rules or log_today");
    }
}
