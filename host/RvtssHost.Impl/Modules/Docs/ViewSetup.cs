using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// View extents, view templates and viewports on sheets: port of revit_mcp/view_setup.py (RVTSS v2.4).
///
/// Routes:
///     POST /views/extents/     get; crop region (on/off, visible, fit to elements or a box); 3D section box;
///                              plan view range; far clip of sections and elevations
///     POST /views/templates/   list, create from a view, duplicate, apply to views, remove, delete,
///                              include / exclude the parameters a template controls
///     POST /sheets/viewports/  list a sheet's viewports and schedules; move, change type, set detail number,
///                              rotate, remove
/// </summary>
public static class ViewSetup
{
    public static readonly (string key, DB.PlanViewPlane plane)[] Planes =
    {
        ("top", DB.PlanViewPlane.TopClipPlane), ("cut", DB.PlanViewPlane.CutPlane),
        ("bottom", DB.PlanViewPlane.BottomClipPlane), ("view_depth", DB.PlanViewPlane.ViewDepthPlane),
    };

    public static readonly Dictionary<string, int> FarClip = new()
    {
        ["no_clip"] = 0, ["clip_with_line"] = 1, ["clip_without_line"] = 2,
    };

    public static void Register(RouteTable api)
    {
        api.Post("/views/extents/", ViewExtents, "view_extents");
        api.Post("/views/templates/", ViewTemplates, "view_templates");
        api.Post("/sheets/viewports/", Viewports, "viewports");
    }

    // ------------------------------------------------------------------------ extents
    /// <summary>Model-space box from element_ids (+ margin) or min / max points. Null when neither is given.</summary>
    private static (DB.XYZ lo, DB.XYZ hi)? ModelBox(Ctx ctx)
    {
        var doc = ctx.Doc;
        var unit = ctx.Unit;
        var ids = ctx.List("element_ids");
        var lo = ctx.Get("min");
        var hi = ctx.Get("max");
        if (ids.Count > 0)
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
                throw new RvtssError("None of the elements has a bounding box");
            var m = Units.ToInternal(ctx.F("margin", 500), unit);
            return (new DB.XYZ(mins.X - m, mins.Y - m, mins.Z - m), new DB.XYZ(maxs.X + m, maxs.Y + m, maxs.Z + m));
        }
        if (lo != null && hi != null)
        {
            var a = Units.PointFrom(lo, unit);
            var b = Units.PointFrom(hi, unit);
            return (new DB.XYZ(Math.Min(a.x, b.x), Math.Min(a.y, b.y), Math.Min(a.z, b.z)),
                new DB.XYZ(Math.Max(a.x, b.x), Math.Max(a.y, b.y), Math.Max(a.z, b.z)));
        }
        if (lo != null || hi != null)
            throw new RvtssError("Give both 'min' and 'max'");
        return null;
    }

    private static List<DB.XYZ> Corners(DB.XYZ lo, DB.XYZ hi)
    {
        var pts = new List<DB.XYZ>();
        foreach (var x in new[] { lo.X, hi.X })
            foreach (var y in new[] { lo.Y, hi.Y })
                foreach (var z in new[] { lo.Z, hi.Z })
                    pts.Add(new DB.XYZ(x, y, z));
        return pts;
    }

    private static Lst Pt(DB.XYZ p, string unit) => new()
    {
        Units.FromInternal(p.X, unit, 1), Units.FromInternal(p.Y, unit, 1), Units.FromInternal(p.Z, unit, 1),
    };

    private static DB.XYZ MinOf(List<DB.XYZ> pts) =>
        new(pts.Min(p => p.X), pts.Min(p => p.Y), pts.Min(p => p.Z));

    private static DB.XYZ MaxOf(List<DB.XYZ> pts) =>
        new(pts.Max(p => p.X), pts.Max(p => p.Y), pts.Max(p => p.Z));

    private static Dict CropInfo(DB.View view, string unit)
    {
        var output = new Dict();
        try
        {
            output["crop_active"] = view.CropBoxActive;
            output["crop_visible"] = view.CropBoxVisible;
            var bb = view.CropBox;
            if (bb != null)
            {
                var t = bb.Transform;
                var pts = Corners(bb.Min, bb.Max).Select(p => t.OfPoint(p)).ToList();
                output["crop_min"] = Pt(MinOf(pts), unit);
                output["crop_max"] = Pt(MaxOf(pts), unit);
            }
        }
        catch (Exception e)
        {
            output["crop_error"] = Utils.NormalizeString(e.Message);
        }
        return output;
    }

    private static Dict RangeInfo(DB.Document doc, DB.ViewPlan view, string unit)
    {
        var vr = view.GetViewRange();
        var output = new Dict();
        foreach (var (key, p) in Planes)
        {
            var lvl = doc.GetElement(vr.GetLevelId(p));
            output[key] = new Dict
            {
                ["offset"] = Units.FromInternal(vr.GetOffset(p), unit, 1),
                ["level"] = lvl != null ? Utils.NormalizeString(lvl.Name) : null,
            };
        }
        return output;
    }

    private static Dict ExtentsInfo(Ctx ctx, DB.View view)
    {
        var doc = ctx.Doc;
        var unit = ctx.Unit;
        var output = new Dict
        {
            ["view"] = Utils.NormalizeString(view.Name), ["view_id"] = view.Id.Value, ["view_type"] = view.ViewType.ToString(),
            ["scale"] = view.Scale, ["unit"] = unit,
        };
        output.Update(CropInfo(view, unit));
        try
        {
            var (_, sb) = ScopeBoxOf(doc, view);
            output["scope_box"] = sb != null ? Utils.NormalizeString(sb.Name) : null;
        }
        catch
        {
            // a view without the parameter
        }
        if (view is DB.View3D view3d)
        {
            output["section_box_active"] = view3d.IsSectionBoxActive;
            if (view3d.IsSectionBoxActive)
            {
                var sb = view3d.GetSectionBox();
                var pts = Corners(sb.Min, sb.Max).Select(p => sb.Transform.OfPoint(p)).ToList();
                output["section_box_min"] = Pt(MinOf(pts), unit);
                output["section_box_max"] = Pt(MaxOf(pts), unit);
            }
        }
        if (view is DB.ViewPlan viewPlan)
        {
            try
            {
                output["view_range"] = RangeInfo(doc, viewPlan, unit);
            }
            catch (Exception e)
            {
                output["view_range_error"] = Utils.NormalizeString(e.Message);
            }
        }
        var far = view.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR);
        if (far != null && far.HasValue)
            output["far_clip_offset"] = Units.FromInternal(far.AsDouble(), unit, 1);
        return output;
    }

    private static List<DB.Element> ScopeBoxes(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)
            .WhereElementIsNotElementType().ToList();

    private static (DB.Parameter? p, DB.Element? sb) ScopeBoxOf(DB.Document doc, DB.View view)
    {
        var p = view.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP);
        if (p == null || !Compat.IsValidId(p.AsElementId()))
            return (p, null);
        return (p, doc.GetElement(p.AsElementId()));
    }

    private static void SetCrop(Ctx ctx, DB.View view)
    {
        var doc = ctx.Doc;
        var box = ModelBox(ctx);
        var (sbParam, sb) = ScopeBoxOf(doc, view);
        var wanted = ctx.Get("scope_box");
        if (wanted != null)
        {
            // assign an existing scope box (the Revit API cannot create one), or 'none' to detach
            if (sbParam == null || sbParam.IsReadOnly)
                throw new RvtssError($"View '{Utils.NormalizeString(view.Name)}' cannot use a scope box", status: 409);
            var key = DocsPy.Key(wanted);
            if (key == "none" || key == "")
            {
                sbParam.Set(DB.ElementId.InvalidElementId);
            }
            else
            {
                var boxes = ScopeBoxes(doc);
                var match = boxes.Where(b => Utils.NormalizeString(b.Name).ToLowerInvariant() == key
                                             || Py.Str(b.Id.Value) == key).ToList();
                if (match.Count == 0)
                    throw Core.NotFound("Scope box", wanted, boxes.Select(b => (string?)b.Name),
                        hint: "Scope boxes are drawn in Revit: run_revit_command('ScopeBox').");
                if (box != null)
                    throw new RvtssError("Give either scope_box or a crop box (element_ids / min, max), not both");
                sbParam.Set(match[0].Id);
            }
            sb = null;
        }
        if (box != null && sb != null)
        {
            // Revit silently ignores CropBox while a scope box controls the crop
            throw new RvtssError($"The crop of '{Utils.NormalizeString(view.Name)}' is controlled by scope box '{Utils.NormalizeString(sb.Name)}'",
                status: 409,
                hint: "Pass scope_box='none' to detach it in the same call, or edit the scope box in Revit.");
        }
        if (box != null)
        {
            var bb = view.CropBox;
            if (bb == null)
                throw new RvtssError($"View '{Utils.NormalizeString(view.Name)}' has no crop region", status: 409);
            var inv = bb.Transform.Inverse;
            var pts = Corners(box.Value.lo, box.Value.hi).Select(p => inv.OfPoint(p)).ToList();
            // keep the depth (local Z) of the existing crop box: only the region in the view plane changes
            var neu = new DB.BoundingBoxXYZ();
            neu.Transform = bb.Transform;
            neu.Min = new DB.XYZ(pts.Min(p => p.X), pts.Min(p => p.Y), bb.Min.Z);
            neu.Max = new DB.XYZ(pts.Max(p => p.X), pts.Max(p => p.Y), bb.Max.Z);
            view.CropBox = neu;
            view.CropBoxActive = true;
        }
        if (ctx.Get("crop_active") != null)
            view.CropBoxActive = ctx.Bool("crop_active");
        if (ctx.Get("crop_visible") != null)
            view.CropBoxVisible = ctx.Bool("crop_visible");
        if (ctx.Get("annotation_crop") != null)
        {
            var p = view.get_Parameter(DB.BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE);
            if (p == null || p.IsReadOnly)
                throw new RvtssError("This view has no annotation crop", status: 409);
            p.Set(ctx.Bool("annotation_crop") ? 1 : 0);
        }
    }

    private static void SetSectionBox(Ctx ctx, DB.View view)
    {
        if (view is not DB.View3D view3d)
            throw new RvtssError($"A section box needs a 3D view ('{Utils.NormalizeString(view.Name)}' is {view.ViewType})", status: 409);
        var box = ModelBox(ctx);
        if (box != null)
        {
            var bb = new DB.BoundingBoxXYZ();
            bb.Min = box.Value.lo;
            bb.Max = box.Value.hi;
            view3d.SetSectionBox(bb);
            view3d.IsSectionBoxActive = true;
        }
        if (ctx.Get("enabled") != null)
            view3d.IsSectionBoxActive = ctx.Bool("enabled");
        else if (box == null)
            throw new RvtssError("Give element_ids, min/max or enabled");
    }

    private static void SetViewRange(Ctx ctx, DB.View view)
    {
        if (view is not DB.ViewPlan viewPlan)
            throw new RvtssError($"A view range needs a plan view ('{Utils.NormalizeString(view.Name)}' is {view.ViewType})", status: 409);
        var vr = viewPlan.GetViewRange();
        var changed = new List<string>();
        foreach (var (key, p) in Planes)
        {
            if (ctx.Get(key) == null)
                continue;
            if (Py.Truthy(ctx.Get(key + "_level")))
                vr.SetLevelId(p, Core.FindLevel(ctx.Doc, ctx.Get(key + "_level"))!.Id);
            vr.SetOffset(p, Units.ToInternal(ctx.Float(key)!.Value, ctx.Unit));
            changed.Add(key);
        }
        if (changed.Count == 0)
            throw new RvtssError("Give at least one of top, cut, bottom, view_depth (offsets from the plane's level)");
        viewPlan.SetViewRange(vr);
    }

    private static void SetFarClip(Ctx ctx, DB.View view)
    {
        if (ctx.Get("far_clip_offset") != null)
        {
            var p = view.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR);
            if (p == null || p.IsReadOnly)
                throw new RvtssError($"View '{Utils.NormalizeString(view.Name)}' has no editable far clip offset", status: 409,
                    hint: "Sections, elevations and callouts have one; turn far clipping on.");
            p.Set(Units.ToInternal(ctx.Float("far_clip_offset")!.Value, ctx.Unit));
        }
        if (Py.Truthy(ctx.Get("far_clipping")))
        {
            var key = ctx.Get("far_clipping") as string;
            if (key == null || !FarClip.TryGetValue(key, out var mode))
                throw new RvtssError("far_clipping must be one of: " + string.Join(", ", FarClip.Keys.OrderBy(x => x, StringComparer.Ordinal)));
            var p = view.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING);
            if (p == null || p.IsReadOnly)
                throw new RvtssError($"View '{Utils.NormalizeString(view.Name)}' has no far clipping setting", status: 409);
            p.Set(mode);
        }
        if (ctx.Get("far_clip_offset") == null && !Py.Truthy(ctx.Get("far_clipping")))
            throw new RvtssError("Give far_clip_offset and/or far_clipping");
    }

    private static readonly Dictionary<string, Action<Ctx, DB.View>> ExtentActions = new()
    {
        ["set_crop"] = SetCrop, ["set_section_box"] = SetSectionBox, ["set_view_range"] = SetViewRange,
        ["set_far_clip"] = SetFarClip,
    };

    public static Dict? ViewExtents(Ctx ctx)
    {
        var doc = ctx.Doc;
        var action = Py.Str(ctx.Get("action", "get"));
        var view = Core.FindView(doc, ctx.Get("view", "active"), uidoc: ctx.UiDoc)!;
        if (action == "get")
            return ExtentsInfo(ctx, view);
        if (!ExtentActions.ContainsKey(action))
            throw new RvtssError("action must be get, " + string.Join(", ", ExtentActions.Keys.OrderBy(x => x, StringComparer.Ordinal)));
        if (view.IsTemplate)
            throw new RvtssError("View templates have no extents", status: 409);
        var dry = ctx.DryRun;

        Dict Run()
        {
            ExtentActions[action](ctx, view);
            doc.Regenerate();
            return ExtentsInfo(ctx, view);
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "View extents: " + action, Run, dry);
        var output = Core.CommitResult(res, fails, dry);
        if (Compat.IsValidId(view.ViewTemplateId))
            ((Lst)output.SetDefault("warnings", new Lst())!).Add(
                $"View uses template '{Utils.NormalizeString(doc.GetElement(view.ViewTemplateId).Name)}'; it may control these settings.");
        return output;
    }

    // ---------------------------------------------------------------------- templates
    private static List<DB.View> Templates(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>().Where(v => v.IsTemplate).ToList();

    private static DB.View FindTemplate(DB.Document doc, object? reference)
    {
        var key = DocsPy.Key(reference);
        foreach (var t in Templates(doc))
        {
            if (Utils.NormalizeString(t.Name).ToLowerInvariant() == key || Py.Str(t.Id.Value) == key)
                return t;
        }
        throw Core.NotFound("View template", reference, Templates(doc).Select(t => (string?)t.Name));
    }

    private static List<DB.View> ViewsUsing(DB.Document doc, DB.View template) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
            .Where(v => !v.IsTemplate && v.ViewTemplateId == template.Id).ToList();

    /// <summary>Name of a template-controlled parameter id (built-in ids are negative, so look on the view).</summary>
    private static string ParamName(DB.Document doc, DB.View template, DB.ElementId pid)
    {
        foreach (DB.Parameter p in template.Parameters)
        {
            if (p.Id == pid)
                return Utils.NormalizeString(p.Definition.Name);
        }
        return Py.Str(pid.Value);
    }

    private static List<Dict> TemplateParams(DB.Document doc, DB.View template)
    {
        var off = new HashSet<long>(template.GetNonControlledTemplateParameterIds().Select(i => i.Value));
        var output = new List<Dict>();
        foreach (var pid in template.GetTemplateParameterIds())
            output.Add(new Dict { ["name"] = ParamName(doc, template, pid), ["included"] = !off.Contains(pid.Value) });
        return output.OrderBy(d => (string)d["name"]!, StringComparer.Ordinal).ToList();
    }

    public static Dict? ViewTemplates(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        var dry = ctx.DryRun;
        if (action == "list")
        {
            var items = new List<Dict>();
            foreach (var t in Templates(doc))
            {
                var item = new Dict
                {
                    ["id"] = t.Id.Value, ["name"] = Utils.NormalizeString(t.Name), ["view_type"] = t.ViewType.ToString(),
                    ["used_by"] = ViewsUsing(doc, t).Count,
                };
                if (ctx.Bool("parameters", false))
                    item["parameters"] = TemplateParams(doc, t);
                items.Add(item);
            }
            return new Dict
            {
                ["count"] = items.Count,
                ["templates"] = items.OrderBy(d => (string)d["name"]!, StringComparer.Ordinal).ToList(),
                ["unused"] = items.Where(i => (int)i["used_by"]! == 0).Select(i => (string)i["name"]!)
                    .OrderBy(x => x, StringComparer.Ordinal).ToList(),
            };
        }

        if (action == "create_from_view")
        {
            var src = Core.FindView(doc, ctx.Get("view", "active"), uidoc: ctx.UiDoc)!;
            if (!src.IsViewValidForTemplateCreation())
                throw new RvtssError($"A template cannot be created from '{Utils.NormalizeString(src.Name)}' ({src.ViewType})", status: 409);

            Dict RunCreate()
            {
                var t = src.CreateViewTemplate();
                if (Py.Truthy(ctx.Get("name")))
                    t.Name = Py.Str(ctx.Get("name"));
                return new Dict
                {
                    ["template_id"] = t.Id.Value, ["name"] = Utils.NormalizeString(t.Name), ["view_type"] = t.ViewType.ToString(),
                };
            }

            var (res1, fails1) = Core.RunTransaction<Dict>(doc, "Create view template", RunCreate, dry);
            return Core.CommitResult(res1, fails1, dry);
        }

        if (action == "apply" || action == "remove")
        {
            var viewRefs = ctx.List("views");
            if (viewRefs.Count == 0)
                viewRefs = new Lst { "active" };
            var views = viewRefs.Select(v => Core.FindView(doc, v, uidoc: ctx.UiDoc)!).ToList();
            var tmpl = action == "apply" ? FindTemplate(doc, ctx.Require("template")) : null;
            var once = ctx.Bool("once", false);
            var preview = Core.ConfirmGate(ctx, views.Count, "manage_view_templates");
            var dryp = preview || dry;

            Dict One(object? o)
            {
                var v = (DB.View)o!;
                if (tmpl == null)
                {
                    v.ViewTemplateId = DB.ElementId.InvalidElementId;
                }
                else if (once)
                {
                    v.ApplyViewTemplateParameters(tmpl); // copy the settings, keep the view unassigned
                }
                else
                {
                    if (!v.IsValidViewTemplate(tmpl.Id))
                        throw new RvtssError($"template '{Utils.NormalizeString(tmpl.Name)}' ({tmpl.ViewType}) does not fit view "
                                             + $"'{Utils.NormalizeString(v.Name)}' ({v.ViewType})");
                    v.ViewTemplateId = tmpl.Id;
                }
                return new Dict { ["view_id"] = v.Id.Value, ["view"] = Utils.NormalizeString(v.Name) };
            }

            Dict RunApply() => new() { ["results"] = Core.Batch(doc, views.Cast<object?>(), One, ctx.Bool("atomic", true)) };

            var (res2, fails2) = Core.RunTransaction<Dict>(doc, "View template: " + action, RunApply, dryp);
            var output = Core.CommitResult(res2, fails2, dryp, new Dict
            {
                ["template"] = tmpl != null ? Utils.NormalizeString(tmpl.Name) : null, ["applied_once"] = once,
            });
            return Core.PreviewStatus(output, preview);
        }

        var template = FindTemplate(doc, ctx.Require("template"));
        if (action == "duplicate")
        {
            Dict RunDuplicate()
            {
                // View.Duplicate refuses templates ("View cannot be duplicated"): copy the element instead
                var newIds = DB.ElementTransformUtils.CopyElement(doc, template.Id, DB.XYZ.Zero).ToList();
                if (newIds.Count == 0)
                    throw new RvtssError("Revit did not copy the template", status: 409);
                var t = doc.GetElement(newIds[0]);
                if (Py.Truthy(ctx.Get("name")))
                    t.Name = Py.Str(ctx.Get("name"));
                return new Dict { ["template_id"] = t.Id.Value, ["name"] = Utils.NormalizeString(t.Name) };
            }

            var (res3, fails3) = Core.RunTransaction<Dict>(doc, "Duplicate view template", RunDuplicate, dry);
            return Core.CommitResult(res3, fails3, dry);
        }

        if (action == "delete")
        {
            var users = ViewsUsing(doc, template);
            var forced = users.Count > 0 && !ctx.Confirmed && !dry;
            var dryd = forced || dry;

            var name = Utils.NormalizeString(template.Name);
            var userIds = users.Take(100).Select(v => (object?)v.Id.Value).ToList();

            Dict RunDelete()
            {
                doc.Delete(template.Id);
                return new Dict { ["deleted"] = name, ["views_that_used_it"] = users.Count, ["view_ids"] = userIds };
            }

            var (res4, fails4) = Core.RunTransaction<Dict>(doc, "Delete view template", RunDelete, dryd);
            var output = Core.CommitResult(res4, fails4, dryd, new Dict { ["template"] = name });
            return Core.PreviewStatus(output, forced);
        }

        if (action == "set_included")
        {
            var include = new HashSet<string>(ctx.List("include").Select(DocsPy.Key));
            var exclude = new HashSet<string>(ctx.List("exclude").Select(DocsPy.Key));
            if (include.Count == 0 && exclude.Count == 0)
                throw new RvtssError("Give 'include' and/or 'exclude' (parameter names from action='list', parameters=true)");

            var ids = template.GetTemplateParameterIds().ToList();
            var names = new Dictionary<string, DB.ElementId>();
            foreach (var i in ids)
                names[ParamName(doc, template, i).ToLowerInvariant()] = i;
            var unknown = include.Union(exclude).Where(n => !names.ContainsKey(n)).OrderBy(n => n, StringComparer.Ordinal).ToList();
            if (unknown.Count > 0)
                throw new RvtssError($"Not template parameters: {string.Join(", ", unknown)}", status: 404)
                    .With("available", names.Keys.OrderBy(n => n, StringComparer.Ordinal).Cast<object?>().ToList());
            var off = new Dictionary<long, DB.ElementId>();
            foreach (var i in template.GetNonControlledTemplateParameterIds())
                off[i.Value] = i;
            foreach (var n in include)
                off.Remove(names[n].Value);
            foreach (var n in exclude)
                off[names[n].Value] = names[n];

            Dict RunIncluded()
            {
                var lst = new List<DB.ElementId>();
                foreach (var i in off.Values)
                    lst.Add(i);
                template.SetNonControlledTemplateParameterIds(lst);
                return new Dict { ["template"] = Utils.NormalizeString(template.Name), ["parameters"] = TemplateParams(doc, template) };
            }

            var (res5, fails5) = Core.RunTransaction<Dict>(doc, "View template parameters", RunIncluded, dry);
            return Core.CommitResult(res5, fails5, dry);
        }
        throw new RvtssError("action must be list, create_from_view, duplicate, apply, remove, delete or set_included");
    }

    // ---------------------------------------------------------------------- viewports
    private static readonly Dictionary<string, string> Rotation = new()
    {
        ["none"] = "None", ["clockwise"] = "Clockwise", ["counterclockwise"] = "Counterclockwise",
    };

    private static DB.ViewSheet SheetOf(DB.Document doc, object? reference)
    {
        var key = DocsPy.Key(reference);
        var sheets = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)).Cast<DB.ViewSheet>().ToList();
        foreach (var s in sheets)
        {
            if (Py.Str(s.Id.Value) == key || Utils.NormalizeString(s.SheetNumber).ToLowerInvariant() == key)
                return s;
        }
        foreach (var s in sheets)
        {
            if (Utils.NormalizeString(s.Name).ToLowerInvariant() == key)
                return s;
        }
        throw Core.NotFound("Sheet", reference, sheets.Select(s => (string?)s.SheetNumber), hint: "Pass the sheet number or id.");
    }

    private static Dict ViewportInfo(DB.Document doc, DB.Viewport vp, string unit)
    {
        var view = doc.GetElement(vp.ViewId);
        var c = vp.GetBoxCenter();
        var num = vp.get_Parameter(DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER);
        var output = new Dict
        {
            ["viewport_id"] = vp.Id.Value, ["view_id"] = vp.ViewId.Value,
            ["view"] = view != null ? Utils.NormalizeString(view.Name) : null,
            ["center"] = new Lst { Units.FromInternal(c.X, unit, 1), Units.FromInternal(c.Y, unit, 1) },
            ["type"] = Utils.NormalizeString(Utils.GetElementName(doc.GetElement(vp.GetTypeId()))),
            ["detail_number"] = num != null ? num.AsString() : null,
        };
        try
        {
            output["rotation"] = vp.Rotation.ToString().ToLowerInvariant();
        }
        catch
        {
            // no rotation
        }
        return output;
    }

    private static DB.Viewport ViewportOf(DB.Document doc, object? reference)
    {
        var vp = Core.GetElement(doc, reference, "Viewport");
        if (vp is not DB.Viewport viewport)
            throw new RvtssError($"Element {Py.Str(reference)} is not a viewport",
                hint: "manage_viewports(action='list', sheet=...) lists viewport ids.");
        return viewport;
    }

    public static Dict? Viewports(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        var unit = ctx.Unit;
        var dry = ctx.DryRun;
        if (action == "list")
        {
            var sheet = SheetOf(doc, ctx.Require("sheet"));
            var vps = sheet.GetAllViewports().Select(i => (object?)ViewportInfo(doc, (DB.Viewport)doc.GetElement(i), unit)).ToList();
            var scheds = new Lst();
            foreach (DB.ScheduleSheetInstance si in new DB.FilteredElementCollector(doc, sheet.Id).OfClass(typeof(DB.ScheduleSheetInstance)))
            {
                if (si.IsTitleblockRevisionSchedule)
                    continue;
                var sv = doc.GetElement(si.ScheduleId);
                scheds.Add(new Dict
                {
                    ["instance_id"] = si.Id.Value, ["schedule"] = sv != null ? Utils.NormalizeString(sv.Name) : null,
                    ["point"] = new Lst { Units.FromInternal(si.Point.X, unit, 1), Units.FromInternal(si.Point.Y, unit, 1) },
                });
            }
            var types = new Dictionary<long, string>();
            foreach (var i in sheet.GetAllViewports())
            {
                foreach (var tid in ((DB.Viewport)doc.GetElement(i)).GetValidTypes())
                    types[tid.Value] = Utils.NormalizeString(Utils.GetElementName(doc.GetElement(tid)));
                break;
            }
            return new Dict
            {
                ["sheet"] = sheet.SheetNumber, ["sheet_id"] = sheet.Id.Value, ["sheet_name"] = Utils.NormalizeString(sheet.Name),
                ["viewports"] = vps, ["schedules"] = scheds,
                ["viewport_types"] = types.Values.Distinct().OrderBy(x => x, StringComparer.Ordinal).Cast<object?>().ToList(),
                ["unit"] = unit,
            };
        }

        var vp = ViewportOf(doc, ctx.Require("viewport_id"));

        Dict Run()
        {
            if (action == "move")
            {
                var (x, y, _) = Units.PointFrom(ctx.Require("location"), unit);
                vp.SetBoxCenter(new DB.XYZ(x, y, 0));
            }
            else if (action == "set_type")
            {
                var want = DocsPy.Key(ctx.Require("type"));
                DB.ElementId? match = null;
                var names = new List<string?>();
                foreach (var tid in vp.GetValidTypes())
                {
                    var nm = Utils.NormalizeString(Utils.GetElementName(doc.GetElement(tid)));
                    names.Add(nm);
                    if (nm.ToLowerInvariant() == want || Py.Str(tid.Value) == want)
                        match = tid;
                }
                if (match == null)
                    throw Core.NotFound("Viewport type", ctx.Get("type"), names);
                vp.ChangeTypeId(match);
            }
            else if (action == "set_detail_number")
            {
                var p = vp.get_Parameter(DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER);
                if (p == null || p.IsReadOnly)
                    throw new RvtssError("This viewport's detail number cannot be changed", status: 409);
                p.Set(Py.Str(ctx.Require("detail_number")));
            }
            else if (action == "rotate")
            {
                var key = ctx.Get("rotation", "none") as string;
                if (key == null || !Rotation.TryGetValue(key, out var rot))
                    throw new RvtssError("rotation must be none, clockwise or counterclockwise");
                vp.Rotation = DocsPy.EnumAttr<DB.ViewportRotation>(rot);
            }
            else if (action == "remove")
            {
                var info = ViewportInfo(doc, vp, unit);
                var sheet = (DB.ViewSheet)doc.GetElement(vp.SheetId);
                sheet.DeleteViewport(vp);
                return new Dict { ["removed"] = info };
            }
            else
            {
                throw new RvtssError("action must be list, move, set_type, set_detail_number, rotate or remove");
            }
            return new Dict { ["viewport"] = ViewportInfo(doc, vp, unit) };
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Viewport: " + action, Run, dry);
        return Core.CommitResult(res, fails, dry, new Dict { ["unit"] = unit });
    }
}
