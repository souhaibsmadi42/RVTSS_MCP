using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Views, graphics, sheets, schedules, renaming, groups and assemblies: port of revit_mcp/documentation.py.
///
/// Routes:
///     POST /views/create/      floor/ceiling/structural plans, 3D (optionally boxed), sections, elevations,
///                              drafting views, duplicates
///     POST /views/graphics/    overrides, hide/unhide, isolate, category visibility, templates, scale/detail
///     POST /sheets/manage/     create sheets, place views/schedules, list title blocks
///     POST /schedules/create/  schedule with fields, sorting and filters
///     POST /batch_rename/      views, sheets, levels, grids, families, types, rooms, materials (find/replace/regex)
///     POST /groups/manage/     list / create / ungroup model groups
///     POST /assemblies/manage/ list / create / add or remove members / rename / create views + sheet
/// </summary>
public static class Documentation
{
    public static void Register(RouteTable api)
    {
        api.Post("/views/create/", CreateView, "create_view");
        api.Post("/views/graphics/", ViewGraphics, "view_graphics");
        api.Post("/sheets/manage/", SheetsManage, "sheets_manage");
        api.Post("/schedules/create/", CreateSchedule, "create_schedule");
        api.Post("/batch_rename/", BatchRename, "batch_rename");
        api.Post("/groups/manage/", GroupsManage, "groups_manage");
        api.Post("/assemblies/manage/", AssembliesManage, "assemblies_manage");
    }

    private static DB.ViewFamilyType Vft(DB.Document doc, DB.ViewFamily family, object? name = null)
    {
        var types = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewFamilyType)).Cast<DB.ViewFamilyType>()
            .Where(t => t.ViewFamily == family).ToList();
        if (Py.Truthy(name))
        {
            var wanted = Py.Str(name).ToLowerInvariant();
            foreach (var t in types)
            {
                if (Utils.NormalizeString(t.Name).ToLowerInvariant() == wanted)
                    return t;
            }
            throw Core.NotFound("View family type", name, types.Select(t => (string?)t.Name));
        }
        if (types.Count == 0)
            throw new RvtssError($"No view family type for {family}", status: 409);
        return types[0];
    }

    private static DB.View Template(DB.Document doc, object? name)
    {
        foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
        {
            if (v.IsTemplate && (Utils.NormalizeString(v.Name).ToLowerInvariant() == Py.Str(name).ToLowerInvariant()
                                 || Py.Str(v.Id.Value) == Py.Str(name)))
                return v;
        }
        throw Core.NotFound("View template", name, new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
            .Where(v => v.IsTemplate).Select(v => (string?)v.Name));
    }

    private static DB.BoundingBoxXYZ BboxOf(DB.Document doc, IEnumerable<object?> ids, string unit, double margin)
    {
        DB.XYZ? mins = null, maxs = null;
        foreach (var e in Core.GetElements(doc, ids))
        {
            var bb = e.get_BoundingBox(null);
            if (bb == null)
                continue;
            if (mins == null || maxs == null)
            {
                mins = bb.Min;
                maxs = bb.Max;
            }
            else
            {
                mins = new DB.XYZ(Math.Min(mins.X, bb.Min.X), Math.Min(mins.Y, bb.Min.Y), Math.Min(mins.Z, bb.Min.Z));
                maxs = new DB.XYZ(Math.Max(maxs.X, bb.Max.X), Math.Max(maxs.Y, bb.Max.Y), Math.Max(maxs.Z, bb.Max.Z));
            }
        }
        if (mins == null || maxs == null)
            throw new RvtssError("Elements have no bounding box");
        var m = Units.ToInternal(margin, unit);
        var box = new DB.BoundingBoxXYZ();
        box.Min = new DB.XYZ(mins.X - m, mins.Y - m, mins.Z - m);
        box.Max = new DB.XYZ(maxs.X + m, maxs.Y + m, maxs.Z + m);
        return box;
    }

    public static Dict? CreateView(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var kind = Py.Str(ctx.Require("kind"));
        var unit = ctx.Unit;
        var dry = ctx.DryRun;

        Dict Run()
        {
            DB.View v;
            if (kind == "area_plan")
            {
                // area plans need an area scheme, not a view family type
                var level = Core.FindLevel(doc, ctx.Require("level"))!;
                var schemes = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.AreaScheme)).Cast<DB.AreaScheme>().ToList();
                var wanted = Py.Truthy(ctx.Get("area_scheme")) ? Py.Str(ctx.Get("area_scheme")).ToLowerInvariant() : "";
                DB.AreaScheme? scheme = null;
                foreach (var sc in schemes)
                {
                    if (wanted.Length == 0 || Utils.NormalizeString(sc.Name).ToLowerInvariant() == wanted)
                    {
                        scheme = sc;
                        break;
                    }
                }
                if (scheme == null)
                    throw Core.NotFound("Area scheme", ctx.Get("area_scheme"), schemes.Select(sc => (string?)sc.Name));
                v = DB.ViewPlan.CreateAreaPlan(doc, scheme.Id, level.Id);
            }
            else if (kind == "floor_plan" || kind == "ceiling_plan" || kind == "structural_plan")
            {
                var fam = kind == "floor_plan" ? DB.ViewFamily.FloorPlan
                    : kind == "ceiling_plan" ? DB.ViewFamily.CeilingPlan : DB.ViewFamily.StructuralPlan;
                var level = Core.FindLevel(doc, ctx.Require("level"))!;
                v = DB.ViewPlan.Create(doc, Vft(doc, fam, ctx.Get("view_family_type")).Id, level.Id);
            }
            else if (kind == "three_d")
            {
                var v3 = DB.View3D.CreateIsometric(doc, Vft(doc, DB.ViewFamily.ThreeDimensional, ctx.Get("view_family_type")).Id);
                v = v3;
                if (ctx.List("element_ids").Count > 0)
                    v3.SetSectionBox(BboxOf(doc, ctx.List("element_ids"), unit, ctx.F("margin", 500)));
            }
            else if (kind == "section")
            {
                var ids = ctx.List("element_ids");
                if (ids.Count == 0)
                    throw new RvtssError("section needs element_ids to frame (a section box is fitted around them)");
                var bb = BboxOf(doc, ids, unit, ctx.F("margin", 500));
                var direction = ctx.Get("looking", "north") as string;
                var dirs = new Dictionary<string, DB.XYZ>
                {
                    ["north"] = new DB.XYZ(0, 1, 0), ["south"] = new DB.XYZ(0, -1, 0),
                    ["east"] = new DB.XYZ(1, 0, 0), ["west"] = new DB.XYZ(-1, 0, 0),
                };
                if (direction == null || !dirs.ContainsKey(direction))
                    throw new RvtssError("looking must be north, south, east or west");
                var vd = dirs[direction];
                var up = DB.XYZ.BasisZ;
                var right = vd.CrossProduct(up); // right-handed: right x up = -view direction
                var center = (bb.Min + bb.Max) * 0.5;
                var halfW = Math.Abs((bb.Max - bb.Min).DotProduct(right)) / 2.0;
                var halfD = Math.Abs((bb.Max - bb.Min).DotProduct(vd)) / 2.0;
                var t = DB.Transform.Identity;
                t.Origin = center;
                t.BasisX = right;
                t.BasisY = up;
                t.BasisZ = vd.Negate();
                var box = new DB.BoundingBoxXYZ();
                box.Transform = t;
                box.Min = new DB.XYZ(-halfW, bb.Min.Z - center.Z, -halfD);
                box.Max = new DB.XYZ(halfW, bb.Max.Z - center.Z, halfD);
                v = DB.ViewSection.CreateSection(doc, Vft(doc, DB.ViewFamily.Section, ctx.Get("view_family_type")).Id, box);
            }
            else if (kind == "elevation")
            {
                var plan = Core.FindView(doc, ctx.Require("plan_view"))!;
                var (x, y, z) = Units.PointFrom(ctx.Require("point"), unit);
                var marker = DB.ElevationMarker.CreateElevationMarker(
                    doc, Vft(doc, DB.ViewFamily.Elevation, ctx.Get("view_family_type")).Id, new DB.XYZ(x, y, z),
                    ctx.I("scale", 100));
                var facing = ctx.Get("facing", "north") as string;
                var idx = facing == "north" ? 1 : facing == "east" ? 2 : facing == "south" ? 3 : facing == "west" ? 0 : 1;
                v = marker.CreateElevation(doc, plan.Id, idx);
            }
            else if (kind == "drafting")
            {
                v = DB.ViewDrafting.Create(doc, Vft(doc, DB.ViewFamily.Drafting, ctx.Get("view_family_type")).Id);
            }
            else if (kind == "callout")
            {
                // v2.4: a callout (detail view by default) of a rectangle in a plan, section or elevation
                var parent = Core.FindView(doc, ctx.Require("source_view"))!;
                var a = Units.PointFrom(ctx.Require("min"), unit);
                var b = Units.PointFrom(ctx.Require("max"), unit);
                var wanted = ctx.Get("view_family_type");
                DB.ViewFamilyType? vft = null;
                if (Py.Truthy(wanted))
                {
                    foreach (DB.ViewFamilyType t in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewFamilyType)))
                    {
                        if (Utils.NormalizeString(t.Name).ToLowerInvariant() == Py.Str(wanted).ToLowerInvariant())
                        {
                            vft = t;
                            break;
                        }
                    }
                    if (vft == null)
                        throw Core.NotFound("View family type", wanted,
                            new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewFamilyType)).Select(t => (string?)t.Name));
                }
                else
                {
                    vft = Vft(doc, DB.ViewFamily.Detail);
                }
                v = DB.ViewSection.CreateCallout(doc, parent.Id, vft.Id, new DB.XYZ(a.x, a.y, a.z), new DB.XYZ(b.x, b.y, b.z));
            }
            else if (kind == "legend")
            {
                // the Revit API cannot create a legend from nothing; an existing legend is duplicated
                var legends = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
                    .Where(x => x.ViewType == DB.ViewType.Legend && !x.IsTemplate).ToList();
                DB.View src;
                if (Py.Truthy(ctx.Get("source_view")))
                {
                    src = Core.FindView(doc, ctx.Get("source_view"))!;
                    if (src.ViewType != DB.ViewType.Legend)
                        throw new RvtssError($"source_view '{Utils.NormalizeString(src.Name)}' is not a legend");
                }
                else if (legends.Count > 0)
                {
                    src = legends[0];
                }
                else
                {
                    throw new RvtssError("This model has no legend to copy; the Revit API cannot create the first one",
                        status: 409, hint: "Create one legend in Revit (View > Legends > Legend, or "
                                           + "run_revit_command), then call this again.");
                }
                var opt = ctx.Get("duplicate_option") is string dupName && dupName == "with_detailing"
                    ? DB.ViewDuplicateOption.WithDetailing
                    : DB.ViewDuplicateOption.Duplicate;
                v = (DB.View)doc.GetElement(src.Duplicate(opt));
            }
            else if (kind == "duplicate")
            {
                var src = Core.FindView(doc, ctx.Require("source_view"))!;
                var optName = ctx.Get("duplicate_option", "duplicate") as string;
                DB.ViewDuplicateOption opt;
                if (optName == "duplicate")
                    opt = DB.ViewDuplicateOption.Duplicate;
                else if (optName == "with_detailing")
                    opt = DB.ViewDuplicateOption.WithDetailing;
                else if (optName == "as_dependent")
                    opt = DB.ViewDuplicateOption.AsDependent;
                else
                    throw new DocsPy.KeyError(Py.Str(ctx.Get("duplicate_option", "duplicate")));
                if (!src.CanViewBeDuplicated(opt))
                    throw new RvtssError($"View '{src.Name}' cannot be duplicated with option {opt}", status: 409);
                v = (DB.View)doc.GetElement(src.Duplicate(opt));
            }
            else
            {
                throw new RvtssError("kind must be floor_plan, ceiling_plan, structural_plan, area_plan, three_d, section, "
                                     + "elevation, drafting, callout, legend or duplicate");
            }
            if (Py.Truthy(ctx.Get("name")))
                v.Name = Py.Str(ctx.Get("name"));
            if (Py.Truthy(ctx.Get("template")))
                v.ViewTemplateId = Template(doc, ctx.Get("template")).Id;
            if (Py.Truthy(ctx.Get("scale")) && kind != "elevation")
            {
                try
                {
                    v.Scale = (int)ctx.Int("scale")!.Value;
                }
                catch (Exception e)
                {
                    ctx.Warn($"Scale not applied: {e.Message}");
                }
            }
            if (Py.Truthy(ctx.Get("detail_level")))
                v.DetailLevel = DocsPy.EnumAttr<DB.ViewDetailLevel>(DocsPy.Capitalize(Py.Str(ctx.Get("detail_level"))));
            return new Dict
            {
                ["view_id"] = v.Id.Value, ["name"] = Utils.NormalizeString(v.Name), ["view_type"] = v.ViewType.ToString(),
            };
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Create view", Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    /// <summary>Colour from '#RRGGBB' (imported by graphics.py).</summary>
    internal static DB.Color Color(object? hexstr)
    {
        if (hexstr is not string text)
            throw new DocsPy.AttributeError($"'{Py.TypeName(hexstr)}' object has no attribute 'lstrip'");
        var h = text.TrimStart('#');
        if (h.Length != 6)
            throw new RvtssError("Colors must be hex like '#FF0000'");
        return new DB.Color(Hex(h.Substring(0, 2)), Hex(h.Substring(2, 2)), Hex(h.Substring(4, 2)));
    }

    /// <summary>int(s, 16) as a colour byte.</summary>
    private static byte Hex(string s)
    {
        if (!int.TryParse(s, NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out var n))
            throw new Compat.ValueError($"invalid literal for int() with base 16: '{s}'");
        return (byte)n;
    }

    /// <summary>The id of a solid fill pattern (imported by graphics.py), or null.</summary>
    internal static DB.ElementId? SolidFill(DB.Document doc)
    {
        foreach (DB.FillPatternElement fp in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement)))
        {
            try
            {
                if (fp.GetFillPattern().IsSolidFill)
                    return fp.Id;
            }
            catch
            {
                continue;
            }
        }
        return null;
    }

    public static Dict? ViewGraphics(Ctx ctx)
    {
        var doc = ctx.Doc;
        var action = Py.Str(ctx.Require("action"));
        var view = Core.FindView(doc, ctx.Get("view", "active"), uidoc: ctx.UiDoc)!;
        var dry = ctx.DryRun;
        var ids = ctx.List("element_ids");
        string? templWarning = null;
        if (Compat.IsValidId(view.ViewTemplateId) && (action == "override" || action == "category_hidden" || action == "hide"))
        {
            templWarning = $"View uses template '{doc.GetElement(view.ViewTemplateId).Name}'; settings it controls may be overridden or locked.";
        }

        Dict Run()
        {
            if (action == "override")
            {
                var ogs = new DB.OverrideGraphicSettings();
                if (Py.Truthy(ctx.Get("color")))
                {
                    var c = Color(ctx.Get("color"));
                    ogs.SetProjectionLineColor(c);
                    ogs.SetCutLineColor(c);
                    var fill = SolidFill(doc);
                    if (fill != null && ctx.Bool("fill", true))
                    {
                        ogs.SetSurfaceForegroundPatternId(fill);
                        ogs.SetSurfaceForegroundPatternColor(c);
                    }
                }
                if (Py.Truthy(ctx.Get("line_weight")))
                    ogs.SetProjectionLineWeight(ctx.I("line_weight", 1, 1, 16));
                if (ctx.Get("halftone") != null)
                    ogs.SetHalftone(ctx.Bool("halftone"));
                if (ctx.Get("transparency") != null)
                    ogs.SetSurfaceTransparency(ctx.I("transparency", 0, 0, 100));
                var targets = ids.Count > 0 ? Core.GetElements(doc, ids) : new List<DB.Element>();
                foreach (var e in targets)
                    view.SetElementOverrides(e.Id, ogs);
                foreach (var cat in ctx.List("categories"))
                    view.SetCategoryOverrides(Core.ResolveCategory(doc, cat).Id, ogs);
                return new Dict { ["overridden_elements"] = targets.Count, ["overridden_categories"] = ctx.List("categories") };
            }
            if (action == "reset")
            {
                foreach (var e in Core.GetElements(doc, ids))
                    view.SetElementOverrides(e.Id, new DB.OverrideGraphicSettings());
                return new Dict { ["reset_elements"] = ids.Count };
            }
            if (action == "hide" || action == "unhide")
            {
                var lst = Core.ToIdList(Core.GetElements(doc, ids).Select(e => e.Id).ToList());
                if (action == "hide")
                    view.HideElements(lst);
                else
                    view.UnhideElements(lst);
                return new Dict { [action] = ids.Count };
            }
            if (action == "temporary_isolate" || action == "temporary_hide")
            {
                var lst = Core.ToIdList(Core.GetElements(doc, ids).Select(e => e.Id).ToList());
                if (action == "temporary_isolate")
                    view.IsolateElementsTemporary(lst);
                else
                    view.HideElementsTemporary(lst);
                return new Dict { [action] = ids.Count };
            }
            if (action == "reset_temporary")
            {
                view.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate);
                return new Dict { ["reset_temporary"] = true };
            }
            if (action == "category_hidden")
            {
                var done = new Lst();
                foreach (var cat in ctx.List("categories"))
                {
                    var c = Core.ResolveCategory(doc, cat);
                    view.SetCategoryHidden(c.Id, ctx.Bool("hidden", true));
                    done.Add(c.Name);
                }
                return new Dict { ["categories"] = done, ["hidden"] = ctx.Bool("hidden", true) };
            }
            if (action == "apply_template")
            {
                view.ViewTemplateId = Template(doc, ctx.Require("template")).Id;
                return new Dict { ["template"] = ctx.Get("template") };
            }
            if (action == "remove_template")
            {
                view.ViewTemplateId = DB.ElementId.InvalidElementId;
                return new Dict { ["template"] = null };
            }
            if (action == "set_scale")
            {
                view.Scale = (int)ctx.Int("scale")!.Value;
                return new Dict { ["scale"] = view.Scale };
            }
            if (action == "set_detail_level")
            {
                view.DetailLevel = DocsPy.EnumAttr<DB.ViewDetailLevel>(DocsPy.Capitalize(Py.Str(ctx.Require("detail_level"))));
                return new Dict { ["detail_level"] = view.DetailLevel.ToString() };
            }
            throw new RvtssError($"Unknown action '{action}'");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "View graphics: " + action, Run, dry);
        var output = Core.CommitResult(res, fails, dry, new Dict
        {
            ["view"] = Utils.NormalizeString(view.Name), ["view_id"] = view.Id.Value,
        });
        if (templWarning != null)
            ((Lst)output.SetDefault("warnings", new Lst())!).Add(templWarning);
        return output;
    }

    public static Dict? SheetsManage(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Require("action"));
        var unit = ctx.Unit;
        var dry = ctx.DryRun;
        if (action == "list_titleblocks")
        {
            var tbs = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType();
            var list = new Lst();
            foreach (var t in tbs)
            {
                list.Add(new Dict
                {
                    ["id"] = t.Id.Value, ["family"] = Utils.NormalizeString((t as DB.ElementType)?.FamilyName),
                    ["type"] = Utils.NormalizeString(Utils.GetElementName(t)),
                });
            }
            return new Dict { ["title_blocks"] = list };
        }

        Dict Run()
        {
            if (action == "create")
            {
                var results = new Lst();
                var sheetList = ctx.List("sheets");
                if (sheetList.Count == 0)
                    sheetList = new Lst { new Dict { ["number"] = ctx.Get("number"), ["name"] = ctx.Get("name") } };
                foreach (var item in sheetList)
                {
                    var s = DocsPy.D(item);
                    var tb = DocsPy.Or(s.Get("title_block"), ctx.Get("title_block"));
                    DB.ElementId tbid;
                    if (tb != null)
                    {
                        var tbt = DocsPy.IsDigits(tb)
                            ? Core.FindType(doc, typeId: tb)
                            : Core.FindType(doc, family: null, typeName: tb, category: "OST_TitleBlocks");
                        tbid = tbt.Id;
                    }
                    else
                    {
                        var first = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                            .WhereElementIsElementType().FirstElement();
                        tbid = first != null ? first.Id : DB.ElementId.InvalidElementId;
                    }
                    var sh = DB.ViewSheet.Create(doc, tbid);
                    if (Py.Truthy(s.Get("number")))
                        sh.SheetNumber = Py.Str(s["number"]);
                    if (Py.Truthy(s.Get("name")))
                        sh.Name = Py.Str(s["name"]);
                    results.Add(new Dict { ["sheet_id"] = sh.Id.Value, ["number"] = sh.SheetNumber, ["name"] = sh.Name });
                }
                return new Dict { ["sheets"] = results };
            }
            if (action == "place_view")
            {
                var sheet = Core.GetElement(doc, ctx.Require("sheet_id"), "Sheet");
                if (sheet is not DB.ViewSheet viewSheet)
                    throw new RvtssError("sheet_id is not a sheet");
                var view = Core.FindView(doc, ctx.Require("view"))!;
                var location = ctx.Get("location");
                var (x, y, _) = Units.PointFrom(Py.Truthy(location) ? location : new Lst { 400L, 300L }, unit);
                var pt = new DB.XYZ(x, y, 0);
                if (view is DB.ViewSchedule)
                {
                    var inst = DB.ScheduleSheetInstance.Create(doc, viewSheet.Id, view.Id, pt);
                    return new Dict { ["schedule_instance_id"] = inst.Id.Value };
                }
                if (!DB.Viewport.CanAddViewToSheet(doc, viewSheet.Id, view.Id))
                    throw new RvtssError($"View '{view.Name}' cannot be placed (already on a sheet, a template, or empty)",
                        status: 409, hint: "Duplicate the view first with create_view(kind='duplicate').");
                var vp = DB.Viewport.Create(doc, viewSheet.Id, view.Id, pt);
                return new Dict
                {
                    ["viewport_id"] = vp.Id.Value, ["view"] = Utils.NormalizeString(view.Name), ["sheet"] = viewSheet.SheetNumber,
                };
            }
            throw new RvtssError("action must be create, place_view or list_titleblocks");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Sheets: " + action, Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    public static readonly string[] ScheduleKinds = { "category", "key", "material_takeoff", "sheet_list", "view_list", "note_block" };

    public static Dict? CreateSchedule(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var kindObj = ctx.Get("kind", "category");
        var kind = kindObj as string;
        if (kind == null || Array.IndexOf(ScheduleKinds, kind) < 0)
            throw new RvtssError("kind must be one of: " + string.Join(", ", ScheduleKinds));
        var needsCat = kind == "category" || kind == "key" || kind == "material_takeoff";
        var cat = needsCat ? Core.ResolveCategory(doc, ctx.Require("category")) : null;
        var fields = ctx.List("fields");
        if (fields.Count == 0 && kind != "key")
            throw new RvtssError("'fields' (parameter names) is required");
        DB.Family? family = null;
        if (kind == "note_block")
        {
            var want = Py.Str(ctx.Require("family")).Trim().ToLowerInvariant();
            var fams = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)).Cast<DB.Family>().ToList();
            family = fams.FirstOrDefault(f => Utils.NormalizeString(f.Name).ToLowerInvariant() == want);
            if (family == null)
                throw Core.NotFound("Annotation family", ctx.Get("family"), fams
                    .Where(f => f.FamilyCategory != null && f.FamilyCategory.Id.Value == (long)DB.BuiltInCategory.OST_GenericAnnotation)
                    .Select(f => (string?)f.Name));
        }
        var dry = ctx.DryRun;

        Dict Run()
        {
            DB.ViewSchedule sched;
            if (kind == "key")
                sched = DB.ViewSchedule.CreateKeySchedule(doc, cat!.Id);
            else if (kind == "material_takeoff")
                sched = DB.ViewSchedule.CreateMaterialTakeoff(doc, cat!.Id);
            else if (kind == "sheet_list")
                sched = DB.ViewSchedule.CreateSheetList(doc);
            else if (kind == "view_list")
                sched = DB.ViewSchedule.CreateViewList(doc);
            else if (kind == "note_block")
                sched = DB.ViewSchedule.CreateNoteBlock(doc, family!.Id);
            else
                sched = DB.ViewSchedule.CreateSchedule(doc, cat!.Id);
            if (Py.Truthy(ctx.Get("name")))
                sched.Name = Py.Str(ctx.Get("name"));
            var definition = sched.Definition;
            var available = new Dictionary<string, DB.SchedulableField>();
            foreach (var sf in definition.GetSchedulableFields())
                available[Utils.NormalizeString(sf.GetName(doc)).ToLowerInvariant()] = sf;
            var added = new Dictionary<string, DB.ScheduleField>();
            var addedOrder = new List<string>();
            var missing = new Lst();
            foreach (var f in fields)
            {
                var fname = Py.Str(f);
                if (!available.TryGetValue(fname.ToLowerInvariant(), out var sf))
                {
                    missing.Add(f);
                    continue;
                }
                if (!added.ContainsKey(fname))
                    addedOrder.Add(fname);
                added[fname] = definition.AddField(sf);
            }
            if (missing.Count > 0 && ctx.Bool("strict", true))
                throw new RvtssError($"Fields not schedulable for {(cat != null ? cat.Name : kind)}: {PyX.Repr(missing)}", status: 404)
                    .With("available_sample", available.Keys.OrderBy(x => x, StringComparer.Ordinal).Take(60).Cast<object?>().ToList());
            foreach (var s in ctx.List("sort_by"))
            {
                if (s is string sname && added.TryGetValue(sname, out var fld))
                    definition.AddSortGroupField(new DB.ScheduleSortGroupField(fld.FieldId));
            }
            foreach (var item in ctx.List("filters"))
            {
                var flt = DocsPy.D(item);
                var fieldName = flt.Get("field") as string;
                if (fieldName == null || !added.TryGetValue(fieldName, out var fld))
                    throw new RvtssError($"Filter field '{Py.Str(flt.Get("field"))}' must also be in fields");
                var ftype = DocsPy.EnumAttr<DB.ScheduleFilterType>(flt.Get("type", "Equal"));
                var val = flt.Get("value", "");
                // ScheduleFilter takes a double (internal units) for numeric/dimensional fields,
                // an int for integer/yes-no fields and a string for text fields
                if (val is bool vb)
                {
                    definition.AddFilter(new DB.ScheduleFilter(fld.FieldId, ftype, vb ? 1 : 0));
                }
                else if (val is double || (Py.IsInt(val) && Py.Truthy(flt.Get("unit"))))
                {
                    double dv = Py.Truthy(flt.Get("unit")) ? Units.ToInternal(Py.ToFloat(val), Py.Str(flt["unit"])) : Py.ToFloat(val);
                    definition.AddFilter(new DB.ScheduleFilter(fld.FieldId, ftype, dv));
                }
                else if (!Py.IsInt(val))
                {
                    definition.AddFilter(new DB.ScheduleFilter(fld.FieldId, ftype, Py.Str(val)));
                }
                else
                {
                    definition.AddFilter(new DB.ScheduleFilter(fld.FieldId, ftype, (int)Py.ToInt(val)));
                }
            }
            if (kind != "key") // Revit refuses IsItemized on key schedules
                definition.IsItemized = ctx.Bool("itemized", true);
            return new Dict
            {
                ["schedule_id"] = sched.Id.Value, ["name"] = Utils.NormalizeString(sched.Name), ["kind"] = kind,
                ["fields"] = addedOrder.Cast<object?>().ToList(), ["missing_fields"] = missing,
            };
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Create schedule", Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    private static readonly DB.ViewType[] NonRenameViewTypes =
    {
        DB.ViewType.Internal, DB.ViewType.ProjectBrowser, DB.ViewType.SystemBrowser, DB.ViewType.DrawingSheet,
    };

    private static List<DB.Element> OfClass(DB.Document doc, Type cls) =>
        new DB.FilteredElementCollector(doc).OfClass(cls).ToList();

    public static readonly Dictionary<string, Func<DB.Document, List<DB.Element>>> RenameTargets = new()
    {
        ["views"] = doc => new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
            .Where(v => !v.IsTemplate && Array.IndexOf(NonRenameViewTypes, v.ViewType) < 0).Cast<DB.Element>().ToList(),
        ["view_templates"] = doc => new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
            .Where(v => v.IsTemplate).Cast<DB.Element>().ToList(),
        ["sheets"] = doc => OfClass(doc, typeof(DB.ViewSheet)),
        ["levels"] = doc => OfClass(doc, typeof(DB.Level)),
        ["grids"] = doc => OfClass(doc, typeof(DB.Grid)),
        ["families"] = doc => new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)).Cast<DB.Family>()
            .Where(f => f.IsEditable || f.IsInPlace).Cast<DB.Element>().ToList(),
        ["family_types"] = doc => OfClass(doc, typeof(DB.FamilySymbol)),
        ["system_types"] = doc => new DB.FilteredElementCollector(doc).WhereElementIsElementType().ToElements()
            .Where(t => t is not DB.FamilySymbol && (t is DB.WallType || t is DB.FloorType || t is DB.RoofType || t is DB.CeilingType))
            .ToList(),
        ["materials"] = doc => OfClass(doc, typeof(DB.Material)),
        ["rooms"] = doc => new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms)
            .WhereElementIsNotElementType().ToList(),
    };

    private static string NameOf(DB.Element e, string target, string field)
    {
        if (target == "sheets" && field == "number")
            return Utils.NormalizeString(((DB.ViewSheet)e).SheetNumber);
        if (target == "rooms")
            return Utils.NormalizeString(e.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() ?? "");
        return Utils.NormalizeString(Utils.GetElementName(e) ?? "");
    }

    private static void SetName(DB.Element e, string target, string field, string value)
    {
        if (target == "sheets" && field == "number")
            ((DB.ViewSheet)e).SheetNumber = value;
        else if (target == "rooms")
            e.get_Parameter(DB.BuiltInParameter.ROOM_NAME).Set(value);
        else
            e.Name = value;
    }

    /// <summary>Key within which Revit requires names to be unique; null = no uniqueness rule.</summary>
    private static string? UniquenessScope(DB.Element e, string target, string field)
    {
        if (target == "rooms" || (target == "sheets" && field == "name"))
            return null;
        if (target == "family_types")
            return "family|" + ((DB.FamilySymbol)e).Family.Id.Value.ToString(CultureInfo.InvariantCulture);
        if (target == "system_types")
            return "class|" + e.GetType().Name;
        if (target == "views" || target == "view_templates")
            return "view_type|" + ((DB.View)e).ViewType;
        return "all";
    }

    public static Dict? BatchRename(Ctx ctx)
    {
        var doc = ctx.Doc;
        var target = Py.Str(ctx.Require("target"));
        if (!RenameTargets.ContainsKey(target))
            throw new RvtssError("target must be one of: " + string.Join(", ", RenameTargets.Keys.OrderBy(x => x, StringComparer.Ordinal)));
        var field = Py.Str(ctx.Get("field", "name"));
        var include = ctx.Get("include_regex");
        System.Text.RegularExpressions.Regex? rx = null;
        if (Py.Truthy(include))
        {
            try
            {
                rx = PureText.Re(Py.Str(include));
            }
            catch (ArgumentException e)
            {
                throw new DocsPy.error(e.Message);
            }
        }
        var idItems = ctx.List("element_ids");
        var ids = new HashSet<long>();
        foreach (var i in idItems)
        {
            if (Py.IsInt(i))
                ids.Add(Py.ToInt(i));
            else if (i is double d && d == Math.Floor(d) && !double.IsInfinity(d))
                ids.Add((long)d);
        }
        var elements = RenameTargets[target](doc).Where(e => idItems.Count == 0 || ids.Contains(e.Id.Value)).ToList();
        elements = elements.Where(e => rx == null || rx.IsMatch(NameOf(e, target, field))).ToList();
        var plan = new List<(DB.Element e, string old, string neu)>();
        var conflicts = new Lst();
        var existing = new Dictionary<string, HashSet<string>>();
        foreach (var e in RenameTargets[target](doc))
        {
            var scope = UniquenessScope(e, target, field);
            if (scope != null)
            {
                if (!existing.TryGetValue(scope, out var set))
                    existing[scope] = set = new HashSet<string>();
                set.Add(NameOf(e, target, field));
            }
        }
        foreach (var e in elements)
        {
            var old = NameOf(e, target, field);
            string neu;
            try
            {
                neu = Textfmt.ApplyRename(old, ctx.Get("find"), ctx.Get("replace", ""), ctx.Bool("regex", false),
                    ctx.Get("prefix", ""), ctx.Get("suffix", ""), ctx.Get("case"));
            }
            catch (TemplateError te)
            {
                throw new RvtssError(te.Message);
            }
            if (neu == old)
                continue;
            var bad = Textfmt.InvalidNameChars(neu);
            if (bad.Count > 0)
            {
                conflicts.Add(new Dict
                {
                    ["id"] = e.Id.Value, ["old"] = old, ["new"] = neu,
                    ["reason"] = $"invalid characters {PyX.Repr(bad.Cast<object?>().ToList())}",
                });
                continue;
            }
            plan.Add((e, old, neu));
        }
        // names that stay after the rename, and planned new names, per uniqueness scope
        var renamedOld = new Dictionary<string, HashSet<string>>();
        var planned = new Dictionary<string, List<string>>();
        foreach (var (e, old, neu) in plan)
        {
            var scope = UniquenessScope(e, target, field);
            if (scope == null)
                continue;
            if (!renamedOld.TryGetValue(scope, out var ro))
                renamedOld[scope] = ro = new HashSet<string>();
            ro.Add(old);
            if (!planned.TryGetValue(scope, out var pl))
                planned[scope] = pl = new List<string>();
            pl.Add(neu);
        }
        foreach (var (e, old, neu) in plan)
        {
            var scope = UniquenessScope(e, target, field);
            if (scope == null)
                continue;
            var staying = existing.TryGetValue(scope, out var ex) ? new HashSet<string>(ex) : new HashSet<string>();
            if (renamedOld.TryGetValue(scope, out var rold))
                staying.ExceptWith(rold);
            if (staying.Contains(neu) || planned[scope].Count(x => x == neu) > 1)
                conflicts.Add(new Dict { ["id"] = e.Id.Value, ["old"] = old, ["new"] = neu, ["reason"] = "name already used" });
        }
        var conflictIds = new HashSet<long>(conflicts.Select(c => (long)((Dict)c!)["id"]!));
        plan = plan.Where(p => !conflictIds.Contains(p.e.Id.Value)).ToList();
        var preview = Core.ConfirmGate(ctx, plan.Count, "batch_rename");
        var dry = preview || ctx.DryRun;

        Dict Run()
        {
            var done = new Lst();
            foreach (var (e, old, neu) in plan)
            {
                SetName(e, target, field, neu);
                done.Add(new Dict { ["id"] = e.Id.Value, ["old"] = old, ["new"] = neu });
            }
            return new Dict { ["renamed"] = done };
        }

        Dict res;
        Lst fails;
        if (plan.Count > 0)
            (res, fails) = Core.RunTransaction<Dict>(doc, "Batch rename " + target, Run, dry);
        else
            (res, fails) = (new Dict { ["renamed"] = new Lst() }, new Lst());
        var output = Core.CommitResult(res, fails, dry, new Dict
        {
            ["target"] = target, ["matched"] = elements.Count, ["conflicts"] = conflicts,
        });
        return Core.PreviewStatus(output, preview);
    }

    public static Dict? GroupsManage(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        var dry = ctx.DryRun;
        if (action == "list")
        {
            var counts = new Dictionary<long, List<object?>>();
            foreach (DB.Group g in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Group)))
            {
                var key = g.GroupType.Id.Value;
                if (!counts.TryGetValue(key, out var l))
                    counts[key] = l = new List<object?>();
                l.Add(g.Id.Value);
            }
            var outList = new List<Dict>();
            foreach (DB.GroupType gt in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.GroupType)))
            {
                var inst = counts.TryGetValue(gt.Id.Value, out var found) ? found : new List<object?>();
                outList.Add(new Dict
                {
                    ["type_id"] = gt.Id.Value, ["name"] = Utils.NormalizeString(gt.Name),
                    ["category"] = gt.Category != null ? Utils.NormalizeString(gt.Category.Name) : null,
                    ["instances"] = inst.Count, ["instance_ids"] = inst.Take(50).ToList(),
                });
            }
            return new Dict
            {
                ["group_types"] = outList.OrderBy(g => (string)g["name"]!, StringComparer.Ordinal).ToList(),
                ["unused_group_types"] = outList.Where(g => (int)g["instances"]! == 0).Select(g => g["name"]).ToList(),
            };
        }

        Dict Run()
        {
            if (action == "create")
            {
                var members = Core.GetElements(doc, ctx.List("element_ids"));
                var g = doc.Create.NewGroup(Core.ToIdList(members.Select(e => e.Id).ToList()));
                if (Py.Truthy(ctx.Get("name")))
                    g.GroupType.Name = Py.Str(ctx.Get("name"));
                return new Dict
                {
                    ["group_id"] = g.Id.Value, ["group_type"] = Utils.NormalizeString(g.GroupType.Name), ["members"] = members.Count,
                };
            }
            if (action == "ungroup")
            {
                var g = Core.GetElement(doc, ctx.Require("group_id"), "Group");
                if (g is not DB.Group group)
                    throw new DocsPy.AttributeError($"'{g.GetType().Name}' object has no attribute 'UngroupMembers'");
                var members = group.UngroupMembers().Select(i => (object?)i.Value).ToList();
                return new Dict { ["ungrouped_member_ids"] = members };
            }
            throw new RvtssError("action must be list, create or ungroup");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Groups: " + action, Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    private static string? CategoryName(DB.Document doc, DB.AssemblyInstance assembly)
    {
        try
        {
            return Utils.NormalizeString(DB.Category.GetCategory(doc, assembly.NamingCategoryId).Name);
        }
        catch
        {
            return null;
        }
    }

    public static Dict? AssembliesManage(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        var dry = ctx.DryRun;
        if (action == "list")
        {
            var outList = new Lst();
            foreach (DB.AssemblyInstance a in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.AssemblyInstance)))
            {
                outList.Add(new Dict
                {
                    ["id"] = a.Id.Value, ["name"] = Utils.NormalizeString(a.AssemblyTypeName),
                    ["naming_category"] = CategoryName(doc, a), ["members"] = a.GetMemberIds().Count,
                    ["views"] = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
                        .Where(v => !v.IsTemplate && v.AssociatedAssemblyInstanceId == a.Id).Select(v => (object?)v.Id.Value).ToList(),
                });
            }
            return new Dict { ["assemblies"] = outList };
        }
        if (action == "create")
        {
            var members = Core.GetElements(doc, ctx.List("element_ids"));
            DB.ElementId catId;
            if (Py.Truthy(ctx.Get("naming_category")))
            {
                catId = Core.ResolveCategory(doc, ctx.Get("naming_category")).Id;
            }
            else
            {
                if (members.Count == 0)
                    throw new DocsPy.IndexError("index out of range: 0");
                catId = members[0].Category!.Id;
            }
            var memberIds = Core.ToIdList(members.Select(e => e.Id).ToList());
            if (!DB.AssemblyInstance.IsValidNamingCategory(doc, catId, memberIds))
                throw new RvtssError("Invalid naming category for these members", status: 409);

            var (a, fails0) = Core.RunTransaction<DB.AssemblyInstance>(doc, "Create assembly",
                () => DB.AssemblyInstance.Create(doc, memberIds, catId), dry);
            if (dry)
                return Core.CommitResult(new Dict { ["members"] = members.Count }, fails0, dry);
            var name = ctx.Get("name");
            if (Py.Truthy(name))
            {
                // Revit requires the assembly creation to be committed before renaming its type
                Core.RunTransaction(doc, "Name assembly", () => { a.AssemblyTypeName = Py.Str(name); });
            }
            return Core.CommitResult(new Dict
            {
                ["assembly_id"] = a.Id.Value, ["name"] = Utils.NormalizeString(a.AssemblyTypeName), ["members"] = members.Count,
            }, fails0, false);
        }
        var element = Core.GetElement(doc, ctx.Require("assembly_id"), "Assembly");

        DB.AssemblyInstance Asm(string attr) =>
            element as DB.AssemblyInstance ?? throw new DocsPy.AttributeError($"'{element.GetType().Name}' object has no attribute '{attr}'");

        Dict Run()
        {
            if (action == "add_members")
            {
                var a = Asm("AddMemberIds");
                a.AddMemberIds(Core.ToIdList(ctx.List("element_ids")));
                return new Dict { ["members"] = a.GetMemberIds().Count };
            }
            if (action == "remove_members")
            {
                var a = Asm("RemoveMemberIds");
                a.RemoveMemberIds(Core.ToIdList(ctx.List("element_ids")));
                return new Dict { ["members"] = a.GetMemberIds().Count };
            }
            if (action == "rename")
            {
                var a = Asm("AssemblyTypeName");
                a.AssemblyTypeName = Py.Str(ctx.Require("name"));
                return new Dict { ["name"] = a.AssemblyTypeName };
            }
            if (action == "create_views")
            {
                var a = element;
                var made = new Dict();
                var viewKinds = ctx.List("views");
                if (viewKinds.Count == 0)
                    viewKinds = new Lst { "3d", "front", "top", "parts_list" };
                foreach (var kindObj in viewKinds)
                {
                    var kind = Py.Str(kindObj);
                    DB.View v;
                    if (kind == "3d")
                    {
                        v = DB.AssemblyViewUtils.Create3DOrthographic(doc, a.Id);
                    }
                    else if (kind == "parts_list")
                    {
                        v = DB.AssemblyViewUtils.CreatePartList(doc, a.Id);
                    }
                    else if (kind == "material_takeoff")
                    {
                        v = DB.AssemblyViewUtils.CreateMaterialTakeoff(doc, a.Id);
                    }
                    else
                    {
                        string? orient;
                        switch (kind)
                        {
                            case "front": orient = "ElevationFront"; break;
                            case "back": orient = "ElevationBack"; break;
                            case "left": orient = "ElevationLeft"; break;
                            case "right": orient = "ElevationRight"; break;
                            case "top": orient = "ElevationTop"; break;
                            case "bottom": orient = "ElevationBottom"; break;
                            case "detail_front": orient = "DetailSectionA"; break;
                            case "detail_side": orient = "DetailSectionB"; break;
                            case "horizontal": orient = "HorizontalDetail"; break;
                            default: orient = null; break;
                        }
                        if (orient == null)
                            throw new RvtssError($"Unknown assembly view '{kind}'");
                        v = DB.AssemblyViewUtils.CreateDetailSection(doc, a.Id, DocsPy.EnumAttr<DB.AssemblyDetailViewOrientation>(orient));
                    }
                    made[kind] = v.Id.Value;
                }
                if (ctx.Bool("create_sheet", false))
                {
                    var tb = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                        .WhereElementIsElementType().FirstElement();
                    var sheet = DB.AssemblyViewUtils.CreateSheet(doc, a.Id, tb != null ? tb.Id : DB.ElementId.InvalidElementId);
                    made["sheet"] = sheet.Id.Value;
                    var x = 0.3;
                    foreach (var kv in made.ToList())
                    {
                        if (kv.Key == "sheet")
                            continue;
                        var v = doc.GetElement(Compat.MakeId(kv.Value));
                        if (v is DB.ViewSchedule)
                            DB.ScheduleSheetInstance.Create(doc, sheet.Id, v.Id, new DB.XYZ(x, 0.8, 0));
                        else if (DB.Viewport.CanAddViewToSheet(doc, sheet.Id, v.Id))
                            DB.Viewport.Create(doc, sheet.Id, v.Id, new DB.XYZ(x, 0.5, 0));
                        x += 0.4;
                    }
                }
                return new Dict { ["views"] = made };
            }
            throw new RvtssError("action must be list, create, add_members, remove_members, rename or create_views");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Assembly: " + action, Run, dry);
        return Core.CommitResult(res, fails, dry, new Dict { ["assembly_id"] = element.Id.Value });
    }
}
