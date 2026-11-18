using System.Text.RegularExpressions;

namespace RvtssHost.Modules;

/// <summary>
/// Annotation: untagged-element checks, tagging and text notes: port of revit_mcp/annotation.py.
///
/// Routes:
///     POST /annotation/untagged/   elements of categories visible in a view without a tag in that view
///     POST /annotation/tag/        tag elements (by ids or category) - rooms/spaces/areas get their own tags
///     POST /annotation/text/       place text notes
///     POST /annotation/detail/     dimensions, detail lines and filled regions in one view (v2.3)
///     POST /annotation/types/      text, tag, dimension, filled region types and line styles (v2.3)
///     POST /annotation/text/replace/   find and replace in text notes (v2.4)
/// </summary>
public static class Annotation
{
    public static readonly string[] NoAnnotationViews =
    {
        "Schedule", "ColumnSchedule", "ProjectBrowser", "SystemBrowser", "Internal", "Undefined",
        "Report", "CostReport", "LoadsReport", "PresureLossReport", "PanelSchedule",
    };

    public static readonly Dictionary<string, string> SpatialTag = new()
    {
        ["OST_Rooms"] = "room", ["OST_MEPSpaces"] = "space", ["OST_Areas"] = "area",
    };

    public static void Register(RouteTable api)
    {
        api.Post("/annotation/detail/", Detailing, "detailing");
        api.Post("/annotation/text/replace/", ReplaceText, "replace_text");
        api.Post("/annotation/types/", AnnotationTypes, "annotation_types");
        api.Post("/annotation/untagged/", Untagged, "untagged");
        api.Post("/annotation/tag/", Tag, "tag");
        api.Post("/annotation/text/", TextNotes, "text_notes");
    }

    private static string? SpatialKind(string? bic) => bic != null && SpatialTag.TryGetValue(bic, out var kind) ? kind : null;

    private static DB.View AnnotationView(Ctx ctx)
    {
        var view = Core.FindView(ctx.Doc, ctx.Get("view", "active"), uidoc: ctx.UiDoc)!;
        if (view.IsTemplate || Array.IndexOf(NoAnnotationViews, view.ViewType.ToString()) >= 0)
            throw new RvtssError($"View '{Utils.NormalizeString(view.Name)}' ({view.ViewType}) cannot hold tags or text",
                status: 409, hint: "Use a plan, section, elevation, 3D (locked) or drafting view.");
        return view;
    }

    private static List<long> TaggedLocalIds(DB.IndependentTag tag)
    {
        try
        {
            return tag.GetTaggedLocalElementIds().Select(i => i.Value).ToList(); // 2022+
        }
        catch
        {
            // fall through to the old property
        }
        try
        {
            var missing = new object();
            var eid = Py.GetAttr(tag, "TaggedLocalElementId", missing);
            if (ReferenceEquals(eid, missing))
                return new List<long>();
            return eid is DB.ElementId id && Compat.IsValidId(id) ? new List<long> { id.Value } : new List<long>();
        }
        catch
        {
            return new List<long>();
        }
    }

    /// <summary>Ids of elements tagged in this view (independent tags, room / space / area tags).</summary>
    public static HashSet<long> TaggedIdsInView(DB.Document doc, DB.View view)
    {
        var ids = new HashSet<long>();
        foreach (DB.IndependentTag tag in new DB.FilteredElementCollector(doc, view.Id).OfClass(typeof(DB.IndependentTag)))
            ids.UnionWith(TaggedLocalIds(tag));
        foreach (var (bic, attr) in new[] { ("OST_RoomTags", "Room"), ("OST_MEPSpaceTags", "Space"), ("OST_AreaTags", "Area") })
        {
            DB.FilteredElementCollector col;
            try
            {
                var cat = Py.EnumOrNull<DB.BuiltInCategory>(bic);
                if (cat == null)
                    throw new DocsPy.AttributeError(bic);
                col = new DB.FilteredElementCollector(doc, view.Id).OfCategory(cat.Value).WhereElementIsNotElementType();
            }
            catch
            {
                continue;
            }
            foreach (var t in col)
            {
                try
                {
                    var target = Py.GetAttr(t, attr);
                    if (target is DB.Element el)
                        ids.Add(el.Id.Value);
                }
                catch
                {
                    continue;
                }
            }
        }
        return ids;
    }

    private static List<DB.Element> Visible(DB.Document doc, DB.View view, DB.Category cat) =>
        new DB.FilteredElementCollector(doc, view.Id).OfCategoryId(cat.Id).WhereElementIsNotElementType().ToList();

    public static Dict? Untagged(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var cats = ctx.List("categories");
        if (cats.Count == 0)
            throw new RvtssError("'categories' is required, e.g. ['Doors','Windows','Rooms']");
        var view = AnnotationView(ctx);
        var limit = ctx.I("limit", 200, 1, 2000);
        var tagged = TaggedIdsInView(doc, view);
        var outList = new Lst();
        long totalUntagged = 0;
        foreach (var name in cats)
        {
            var cat = Core.ResolveCategory(doc, name);
            var elems = Visible(doc, view, cat);
            if (SpatialKind(Compat.BicFromCategory(cat)) != null)
            {
                elems = elems.Where(e =>
                {
                    if (e.Location == null)
                        return false;
                    var area = Py.GetAttr(e, "Area", 0L);
                    return Py.Truthy(area) && Py.ToFloat(area) > 0;
                }).ToList();
            }
            var missing = elems.Where(e => !tagged.Contains(e.Id.Value)).ToList();
            totalUntagged += missing.Count;
            outList.Add(new Dict
            {
                ["category"] = Utils.NormalizeString(cat.Name), ["visible"] = elems.Count,
                ["tagged"] = elems.Count - missing.Count, ["untagged"] = missing.Count, ["truncated"] = missing.Count > limit,
                ["untagged_elements"] = DocsPy.Head(missing, limit).Select(e => (object?)Core.ElementBrief(doc, e)).ToList(),
            });
        }
        return new Dict
        {
            ["view"] = Utils.NormalizeString(view.Name), ["view_id"] = view.Id.Value, ["untagged_total"] = totalUntagged,
            ["categories"] = outList,
            ["next_step"] = totalUntagged > 0
                ? "tag_elements(view=..., categories=[...]) tags only what is untagged (skip_tagged=true)."
                : null,
        };
    }

    /// <summary>A family / type by id, 'Family : Type' or type name (imported by other modules).</summary>
    internal static DB.ElementType? TagType(DB.Document doc, object? spec)
    {
        if (spec == null)
            return null;
        if (DocsPy.IsDigits(spec))
            return Core.FindType(doc, typeId: Py.ToInt(Py.Str(spec)));
        var text = Py.Str(spec);
        var i = text.IndexOf(':');
        var fam = i < 0 ? text : text.Substring(0, i);
        var typ = i < 0 ? "" : text.Substring(i + 1);
        if (typ.Length > 0)
            return Core.FindType(doc, family: fam.Trim(), typeName: typ.Trim());
        return Core.FindType(doc, typeName: fam.Trim());
    }

    public static Dict? Tag(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var view = AnnotationView(ctx);
        var unit = ctx.Unit;
        var ids = ctx.List("element_ids");
        var cats = ctx.List("categories");
        if (ids.Count == 0 && cats.Count == 0)
            throw new RvtssError("Give element_ids or categories (tagged in the view)");
        var elements = new List<DB.Element>();
        var seen = new HashSet<long>();
        foreach (var e in ids.Count > 0 ? Core.GetElements(doc, ids) : new List<DB.Element>())
        {
            if (seen.Add(e.Id.Value))
                elements.Add(e);
        }
        foreach (var name in cats)
        {
            foreach (var e in Visible(doc, view, Core.ResolveCategory(doc, name)))
            {
                if (seen.Add(e.Id.Value))
                    elements.Add(e);
            }
        }
        var skipped = new Lst();
        if (ctx.Bool("skip_tagged", true))
        {
            var tagged = TaggedIdsInView(doc, view);
            var kept = new List<DB.Element>();
            foreach (var e in elements)
            {
                if (tagged.Contains(e.Id.Value))
                    skipped.Add(new Dict { ["id"] = e.Id.Value, ["reason"] = "already tagged in this view" });
                else
                    kept.Add(e);
            }
            elements = kept;
        }
        var ttype = TagType(doc, ctx.Get("tag_type"));
        var offsetList = ctx.List("offset");
        var (dx, dy, _) = Units.PointFrom(offsetList.Count > 0 ? offsetList : new Lst { 0L, 0L }, unit);
        var leader = ctx.Bool("leader", false);
        var orient = ctx.Get("orientation") is string os && os == "vertical" ? DB.TagOrientation.Vertical : DB.TagOrientation.Horizontal;
        var preview = Core.ConfirmGate(ctx, elements.Count, "tag_elements");
        var dry = preview || ctx.DryRun;

        Dict TagOne(DB.Element e)
        {
            var kind = SpatialKind(e.Category != null ? Compat.BicFromCategory(e.Category) : null);
            if (kind != null)
            {
                if (e.Location == null)
                    throw new RvtssError($"unplaced {kind} cannot be tagged");
                var p = ((DB.LocationPoint)e.Location).Point;
                var uv = new DB.UV(p.X + dx, p.Y + dy);
                DB.Element? t;
                if (kind == "room")
                {
                    t = doc.Create.NewRoomTag(new DB.LinkElementId(e.Id), uv, view.Id);
                }
                else if (kind == "space")
                {
                    t = doc.Create.NewSpaceTag((DB.Mechanical.Space)e, uv, view);
                }
                else
                {
                    if (view is not DB.ViewPlan viewPlan)
                        throw new RvtssError("area tags need an area plan view");
                    t = doc.Create.NewAreaTag(viewPlan, (DB.Area)e, uv);
                }
                if (t == null)
                    throw new RvtssError($"Revit returned no tag (is a {kind} tag family loaded?)");
                if (ttype != null)
                    t.ChangeTypeId(ttype.Id);
                return new Dict { ["element_id"] = e.Id.Value, ["tag_id"] = t.Id.Value };
            }
            var pt0 = Core.ElementPoint(e);
            if (pt0 == null)
                throw new RvtssError("element has no location to place a tag");
            var pt = new DB.XYZ(pt0.X + dx, pt0.Y + dy, pt0.Z);
            var reference = new DB.Reference(e);
            DB.IndependentTag? tag;
            if (ttype != null)
                tag = DB.IndependentTag.Create(doc, ttype.Id, view.Id, reference, leader, orient, pt);
            else
                tag = DB.IndependentTag.Create(doc, view.Id, reference, leader, DB.TagMode.TM_ADDBY_CATEGORY, orient, pt);
            if (tag == null)
                throw new RvtssError($"no tag created - load a tag family for '{(e.Category != null ? Utils.NormalizeString(e.Category.Name) : "?")}'");
            return new Dict
            {
                ["element_id"] = e.Id.Value, ["tag_id"] = tag.Id.Value,
                ["tag_type"] = Utils.NormalizeString(Utils.GetElementName(doc.GetElement(tag.GetTypeId()))),
            };
        }

        Dict Run() => new() { ["results"] = Core.Batch(doc, elements.Cast<object?>(), o => TagOne((DB.Element)o!), ctx.Bool("atomic", false)) };

        Dict res;
        Lst fails;
        if (elements.Count > 0)
            (res, fails) = Core.RunTransaction<Dict>(doc, "Tag elements", Run, dry);
        else
            (res, fails) = (new Dict { ["results"] = new Lst() }, new Lst());
        var results = (res.Get("results") as Lst) ?? new Lst();
        bool Ok(object? r) => Py.Truthy(((Dict)r!).Get("ok"));
        var okList = results.Where(Ok).ToList();
        var failed = results.Where(r => !Ok(r)).ToList();
        var output = Core.CommitResult(new Dict
        {
            ["tagged"] = okList.Count, ["failed"] = DocsPy.Head(failed, 50), ["created"] = DocsPy.Head(okList, 200),
            ["skipped"] = DocsPy.Head(skipped, 100), ["skipped_count"] = skipped.Count,
        }, fails, dry, new Dict { ["view"] = Utils.NormalizeString(view.Name), ["view_id"] = view.Id.Value });
        if (failed.Count > 0 && failed.Any(r =>
            {
                var err = Py.Truthy(((Dict)r!).Get("error")) ? Py.Str(((Dict)r)["error"]).ToLowerInvariant() : "";
                return err.Contains("tag family") || err.Contains("no tag");
            }))
        {
            output["hint"] = "Load a tag family for the category (Insert > Load Family > Annotations) or pass tag_type.";
        }
        return Core.PreviewStatus(output, preview && !ctx.DryRun);
    }

    public static Dict? TextNotes(Ctx ctx)
    {
        var doc = ctx.Doc;
        var view = AnnotationView(ctx);
        var unit = ctx.Unit;
        var notes = ctx.List("notes");
        if (notes.Count == 0)
            throw new RvtssError("'notes' is required: [{text, point:[x,y], type?}]");
        var defaultType = ctx.Get("text_type");
        var dry = ctx.DryRun;

        DB.ElementId TypeId(object? name)
        {
            if (!Py.Truthy(name))
                return doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType);
            return Core.FindType(doc, typeName: name, ofClass: typeof(DB.TextNoteType)).Id;
        }

        Dict One(object? item)
        {
            var n = DocsPy.D(item);
            if (!Py.Truthy(n.Get("text")))
                throw new RvtssError("note without text");
            var (x, y, z) = Units.PointFrom(DocsPy.Or(n.Get("point"), new Lst { 0L, 0L }), unit);
            var t = DB.TextNote.Create(doc, view.Id, new DB.XYZ(x, y, z), Py.Str(n["text"]),
                TypeId(DocsPy.Or(n.Get("type"), defaultType)));
            return new Dict { ["text_note_id"] = t.Id.Value };
        }

        Dict Run() => new() { ["results"] = Core.Batch(doc, notes, One, true) };

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Text notes", Run, dry);
        return Core.CommitResult(res, fails, dry, new Dict { ["view"] = Utils.NormalizeString(view.Name), ["view_id"] = view.Id.Value });
    }

    // ------------------------------------------------- detailing (v2.3): dimensions, lines, regions
    private static readonly Dictionary<string, string> FiRefs = new()
    {
        ["center_left_right"] = "CenterLeftRight", ["center_front_back"] = "CenterFrontBack",
        ["center_elevation"] = "CenterElevation", ["left"] = "Left", ["right"] = "Right", ["front"] = "Front",
        ["back"] = "Back", ["top"] = "Top", ["bottom"] = "Bottom",
    };

    /// <summary>Project a model point onto the view plane ([x, y] is enough in plans).</summary>
    private static DB.XYZ OnPlane(DB.View view, DB.XYZ xyz)
    {
        var n = view.ViewDirection;
        return xyz - n.Multiply((xyz - view.Origin).DotProduct(n));
    }

    private static DB.XYZ ViewPoint(Ctx ctx, DB.View view, object? value, string what = "point")
    {
        if (value == null)
            throw new RvtssError($"'{what}' is required");
        var (x, y, z) = Units.PointFrom(value, ctx.Unit);
        return OnPlane(view, new DB.XYZ(x, y, z));
    }

    private static DB.Line Segment(DB.XYZ a, DB.XYZ b)
    {
        if (a.DistanceTo(b) < 1e-4)
            throw new RvtssError("Two consecutive points are the same (after projection onto the view)");
        return DB.Line.CreateBound(a, b);
    }

    private static DB.Element Named(DB.Document doc, Type cls, object? name, DB.ElementTypeGroup? defaultGroup = null,
        string what = "type")
    {
        var types = new DB.FilteredElementCollector(doc).OfClass(cls).ToList();
        if (Py.Truthy(name))
        {
            var key = DocsPy.Key(name);
            foreach (var t in types)
            {
                if (Utils.NormalizeString(Utils.GetElementName(t)).ToLowerInvariant() == key || Py.Str(t.Id.Value) == key)
                    return t;
            }
            throw Core.NotFound(what, name, types.Select(t => (string?)Utils.GetElementName(t)),
                hint: "list_annotation_types lists the available names.");
        }
        if (defaultGroup != null)
        {
            try
            {
                var t = doc.GetElement(doc.GetDefaultElementTypeId(defaultGroup.Value));
                if (t != null)
                    return t;
            }
            catch
            {
                // fall back to the first type
            }
        }
        if (types.Count == 0)
            throw new RvtssError($"No {what} exists in '{doc.Title}'");
        return types[0];
    }

    private static Dictionary<string, DB.GraphicsStyle> LineStyles(DB.Document doc)
    {
        var result = new Dictionary<string, DB.GraphicsStyle>();
        try
        {
            var lines = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines);
            foreach (DB.Category sub in lines.SubCategories)
            {
                var gs = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection);
                if (gs != null)
                    result[Utils.NormalizeString(sub.Name)] = gs;
            }
        }
        catch (Exception e)
        {
            Log.Write("line styles: " + e.Message);
        }
        return result;
    }

    private static DB.Reference DimReference(DB.Element e, Dict item)
    {
        if (e is DB.Grid)
            return new DB.Reference(e);
        if (e is DB.Level level)
            return level.GetPlaneReference();
        if (e is DB.ReferencePlane plane)
            return plane.GetReference();
        if (e is DB.Wall wall)
        {
            var side = Py.Str(DocsPy.Or(item.Get("wall_face"), "exterior")).ToLowerInvariant();
            var shell = side == "interior" ? DB.ShellLayerType.Interior : DB.ShellLayerType.Exterior;
            var faces = DB.HostObjectUtils.GetSideFaces(wall, shell).ToList();
            if (faces.Count == 0)
                throw new RvtssError($"Wall {e.Id.Value} has no {side} face to dimension");
            return faces[0];
        }
        if (e is DB.FamilyInstance fi)
        {
            var key = Py.Str(DocsPy.Or(item.Get("instance_reference"), "center_left_right")).ToLowerInvariant();
            if (!FiRefs.TryGetValue(key, out var name))
                throw new RvtssError("instance_reference must be one of: "
                                     + string.Join(", ", FiRefs.Keys.OrderBy(x => x, StringComparer.Ordinal)));
            var refs = fi.GetReferences(DocsPy.EnumAttr<DB.FamilyInstanceReferenceType>(name)).ToList();
            if (refs.Count == 0)
                throw new RvtssError($"Family instance {e.Id.Value} has no '{name}' reference",
                    hint: "Try another instance_reference, e.g. left / right / center_front_back.");
            return refs[0];
        }
        throw new RvtssError($"Cannot dimension {e.GetType().Name} (id {e.Id.Value}): use grids, levels, reference planes, "
                             + "walls or family instances");
    }

    private static Dict Dimension(Ctx ctx, DB.View view, Dict item)
    {
        var doc = ctx.Doc;
        var ids = Py.ListOf(DocsPy.Or(item.Get("element_ids"), new Lst()));
        if (ids.Count < 2)
            throw new RvtssError("dimension: 'element_ids' needs at least 2 elements");
        var arr = new DB.ReferenceArray();
        foreach (var i in ids)
            arr.Append(DimReference(Core.GetElement(doc, i), item));
        var line = Segment(ViewPoint(ctx, view, item.Get("start"), "start"), ViewPoint(ctx, view, item.Get("end"), "end"));
        DB.Dimension? dim;
        if (Py.Truthy(item.Get("type")))
            dim = doc.Create.NewDimension(view, line, arr, (DB.DimensionType)Named(doc, typeof(DB.DimensionType), item["type"], what: "Dimension type"));
        else
            dim = doc.Create.NewDimension(view, line, arr);
        if (dim == null)
            throw new RvtssError("Revit could not create the dimension (are the references parallel and visible?)");
        var output = new Dict { ["kind"] = "dimension", ["id"] = dim.Id.Value };
        try
        {
            var value = dim.Value;
            if (value != null)
                output["value"] = Units.FromInternal(value.Value, ctx.Unit, 2);
        }
        catch
        {
            // some dimensions have no single value
        }
        return output;
    }

    private static Dict DetailLine(Ctx ctx, DB.View view, Dict item)
    {
        var doc = ctx.Doc;
        var rawPts = item.Get("points");
        var raw = Py.Truthy(rawPts) ? Py.ListOf(rawPts) : new Lst { item.Get("start"), item.Get("end") };
        var pts = raw.Select(p => ViewPoint(ctx, view, p)).ToList();
        if (pts.Count < 2)
            throw new RvtssError("detail_line needs start/end or at least 2 points");
        if (Py.Truthy(item.Get("closed")) && pts.Count > 2)
            pts.Add(pts[0]);
        DB.GraphicsStyle? style = null;
        if (Py.Truthy(item.Get("line_style")))
        {
            var styles = LineStyles(doc);
            var key = DocsPy.Key(item["line_style"]);
            foreach (var kv in styles)
            {
                if (kv.Key.ToLowerInvariant() == key)
                {
                    style = kv.Value;
                    break;
                }
            }
            if (style == null)
                throw Core.NotFound("Line style", item["line_style"], styles.Keys);
        }
        var ids = new Lst();
        for (var i = 0; i < pts.Count - 1; i++)
        {
            var dc = doc.Create.NewDetailCurve(view, Segment(pts[i], pts[i + 1]));
            if (style != null)
                dc.LineStyle = style;
            ids.Add(dc.Id.Value);
        }
        return new Dict { ["kind"] = "detail_line", ["ids"] = ids };
    }

    private static Dict FilledRegion(Ctx ctx, DB.View view, Dict item)
    {
        var doc = ctx.Doc;
        var pts = Py.ListOf(DocsPy.Or(item.Get("boundary"), new Lst())).Select(p => ViewPoint(ctx, view, p)).ToList();
        if (pts.Count < 3)
            throw new RvtssError("filled_region: 'boundary' needs at least 3 points");
        var loop = new DB.CurveLoop();
        for (var i = 0; i < pts.Count; i++)
            loop.Append(Segment(pts[i], pts[(i + 1) % pts.Count]));
        var frt = Named(doc, typeof(DB.FilledRegionType), item.Get("type"), DB.ElementTypeGroup.FilledRegionType, "Filled region type");
        var loops = new List<DB.CurveLoop> { loop };
        var fr = DB.FilledRegion.Create(doc, frt.Id, view.Id, loops);
        return new Dict { ["kind"] = "filled_region", ["id"] = fr.Id.Value, ["type"] = Utils.NormalizeString(Utils.GetElementName(frt)) };
    }

    // ---- v2.4: masking regions, revision clouds, spot dimensions, detail components and symbols
    private static List<DB.Line> ClosedLoop(Ctx ctx, DB.View view, Dict item, string what)
    {
        var pts = Py.ListOf(DocsPy.Or(item.Get("boundary"), new Lst())).Select(p => ViewPoint(ctx, view, p)).ToList();
        if (pts.Count < 3)
            throw new RvtssError($"{what}: 'boundary' needs at least 3 points");
        var segs = new List<DB.Line>();
        for (var i = 0; i < pts.Count; i++)
            segs.Add(Segment(pts[i], pts[(i + 1) % pts.Count]));
        return segs;
    }

    private static Dict MaskingRegion(Ctx ctx, DB.View view, Dict item)
    {
        var doc = ctx.Doc;
        var types = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FilledRegionType)).Cast<DB.FilledRegionType>().ToList();
        DB.FilledRegionType? masking = null;
        foreach (var t in types)
        {
            try
            {
                if (t.IsMasking)
                {
                    masking = t;
                    break;
                }
            }
            catch
            {
                continue;
            }
        }
        if (masking == null)
            throw new RvtssError($"No masking filled region type exists in '{doc.Title}'", status: 409,
                hint: "Duplicate a filled region type in Revit and tick 'Masking', or draw one masking "
                      + "region by hand once.");
        var loop = new DB.CurveLoop();
        foreach (var seg in ClosedLoop(ctx, view, item, "masking_region"))
            loop.Append(seg);
        var loops = new List<DB.CurveLoop> { loop };
        var fr = DB.FilledRegion.Create(doc, masking.Id, view.Id, loops);
        return new Dict { ["kind"] = "masking_region", ["id"] = fr.Id.Value };
    }

    private static DB.Revision RevisionOf(DB.Document doc, object? reference)
    {
        var ids = DB.Revision.GetAllRevisionIds(doc).ToList();
        if (ids.Count == 0)
            throw new RvtssError("The project has no revision", status: 409, hint: "Create one with manage_revisions.");
        var revs = ids.Select(i => (DB.Revision)doc.GetElement(i)).ToList();
        if (reference == null || (reference is string rs && (rs == "" || rs == "latest")))
            return revs[revs.Count - 1];
        var key = DocsPy.Key(reference);
        foreach (var r in revs)
        {
            if (Py.Str(r.Id.Value) == key || Py.Str(r.SequenceNumber) == key
                || Utils.NormalizeString(r.Description ?? "").ToLowerInvariant() == key)
                return r;
        }
        throw Core.NotFound("Revision", reference, revs.Select(r => (string?)Utils.NormalizeString(r.Description ?? "")),
            hint: "Pass the revision id, its sequence number or its description.");
    }

    private static Dict RevisionCloud(Ctx ctx, DB.View view, Dict item)
    {
        var doc = ctx.Doc;
        var rev = RevisionOf(doc, item.Get("revision"));
        if (rev.Issued)
            throw new RvtssError($"Revision '{Utils.NormalizeString(rev.Description ?? "")}' is issued; clouds cannot be added to it",
                status: 409);
        var curves = new List<DB.Curve>();
        foreach (var seg in ClosedLoop(ctx, view, item, "revision_cloud"))
            curves.Add(seg);
        var cloud = DB.RevisionCloud.Create(doc, view, rev.Id, curves);
        return new Dict
        {
            ["kind"] = "revision_cloud", ["id"] = cloud.Id.Value, ["revision"] = Utils.NormalizeString(rev.Description ?? ""),
        };
    }

    private static DB.Reference TopFaceReference(DB.Element e)
    {
        try
        {
            if (e is DB.RoofBase || e is DB.CeilingAndFloor)
            {
                var refs = DB.HostObjectUtils.GetTopFaces((DB.HostObject)e).ToList();
                if (refs.Count > 0)
                    return refs[0];
            }
        }
        catch
        {
            // not a host with top faces
        }
        throw new RvtssError($"Spot dimensions are supported on floors, roofs, ceilings and toposolids (id {e.Id.Value} is a {e.GetType().Name})",
            hint: "For other elements use run_revit_command('SpotElevation').");
    }

    private static Dict Spot(Ctx ctx, DB.View view, Dict item, bool coordinate)
    {
        var doc = ctx.Doc;
        var e = Core.GetElement(doc, item.Get("element_id"));
        var reference = TopFaceReference(e);
        var (x, y, z) = Units.PointFrom(DocsPy.Or(item.Get("point"), new Lst { 0L, 0L }), ctx.Unit);
        var origin = new DB.XYZ(x, y, z);
        try
        {
            if (e.GetGeometryObjectFromReference(reference) is DB.Face face)
            {
                var hit = face.Project(origin);
                if (hit == null)
                    throw new RvtssError($"point is not over the top face of element {e.Id.Value}");
                origin = hit.XYZPoint;
            }
        }
        catch (RvtssError)
        {
            throw;
        }
        catch (Exception ex)
        {
            Log.Write("spot projection: " + ex.Message);
        }
        var leader = Py.Truthy(item.Get("leader", false));
        var (ox, oy, _) = Units.PointFrom(DocsPy.Or(item.Get("offset"), new Lst { 600L, 600L }), ctx.Unit);
        var bend = new DB.XYZ(origin.X + ox, origin.Y + oy, origin.Z);
        var end = new DB.XYZ(bend.X + Math.Abs(ox), bend.Y, bend.Z);
        var sd = coordinate
            ? doc.Create.NewSpotCoordinate(view, reference, origin, bend, end, origin, leader)
            : doc.Create.NewSpotElevation(view, reference, origin, bend, end, origin, leader);
        if (sd == null)
            throw new RvtssError("Revit created no spot dimension (is the face visible in this view?)");
        return new Dict { ["kind"] = coordinate ? "spot_coordinate" : "spot_elevation", ["id"] = sd.Id.Value };
    }

    private static Dict SpotElevation(Ctx ctx, DB.View view, Dict item) => Spot(ctx, view, item, false);

    private static Dict SpotCoordinate(Ctx ctx, DB.View view, Dict item) => Spot(ctx, view, item, true);

    /// <summary>Detail items and generic annotation symbols: a point, or start/end for line-based detail families.</summary>
    private static Dict DetailComponent(Ctx ctx, DB.View view, Dict item)
    {
        var doc = ctx.Doc;
        var spec = item.Get("type");
        if (!Py.Truthy(spec))
            throw new RvtssError("detail_component: 'type' is required ('Family : Type', type name or id)");
        var sym = TagType(doc, spec);
        if (sym is not DB.FamilySymbol symbol)
            throw new RvtssError($"'{Py.Str(spec)}' is not a loadable family type");
        if (!symbol.IsActive)
        {
            symbol.Activate();
            doc.Regenerate();
        }
        DB.FamilyInstance inst;
        if (item.Get("start") != null && item.Get("end") != null)
        {
            var line = Segment(ViewPoint(ctx, view, item.Get("start"), "start"), ViewPoint(ctx, view, item.Get("end"), "end"));
            inst = doc.Create.NewFamilyInstance(line, symbol, view);
        }
        else
        {
            inst = doc.Create.NewFamilyInstance(ViewPoint(ctx, view, item.Get("point")), symbol, view);
        }
        return new Dict
        {
            ["kind"] = "detail_component", ["id"] = inst.Id.Value, ["type"] = Utils.NormalizeString(Utils.GetElementName(symbol)),
        };
    }

    private static readonly Dictionary<string, Func<Ctx, DB.View, Dict, Dict>> DetailTable = new()
    {
        ["dimension"] = Dimension, ["detail_line"] = DetailLine, ["filled_region"] = FilledRegion,
        ["masking_region"] = MaskingRegion, ["revision_cloud"] = RevisionCloud,
        ["spot_elevation"] = SpotElevation, ["spot_coordinate"] = SpotCoordinate,
        ["detail_component"] = DetailComponent,
    };

    public static readonly string[] DetailKinds = DetailTable.Keys.OrderBy(x => x, StringComparer.Ordinal).ToArray();

    // ---- v2.4: find and replace in text notes
    /// <summary>(new text, number of replacements). Pure: unit-tested without Revit.</summary>
    public static (string text, long count) ReplaceInText(string text, string find, string replace, bool regex = false,
        bool matchCase = false, bool wholeWord = false)
    {
        if (find.Length == 0)
            throw new Compat.ValueError("'find' must not be empty");
        var pattern = regex ? find : Regex.Escape(find);
        if (wholeWord)
            pattern = @"\b(?:" + pattern + @")\b";
        var rx = PureText.Re(pattern, ignoreCase: !matchCase);
        var count = rx.Matches(text).Count;
        if (count == 0)
            return (text, 0); // the replacement template is only read when something matches (IronPython's re)
        var result = regex ? PureText.Sub(rx, replace, text) : rx.Replace(text, _ => replace);
        return (result, count);
    }

    public static Dict? ReplaceText(Ctx ctx)
    {
        var doc = ctx.Doc;
        var find = Py.Str(ctx.Require("find"));
        var replace = Py.Str(ctx.Get("replace", ""));
        bool regex = ctx.Bool("regex", false), matchCase = ctx.Bool("match_case", false), whole = ctx.Bool("whole_word", false);
        try
        {
            ReplaceInText("", find, replace, regex, matchCase, whole);
        }
        catch (Exception e) when (e is FormatException || e is ArgumentException)
        {
            throw new RvtssError($"Invalid find pattern: {e.Message}");
        }
        var views = ctx.List("views");
        var notes = new List<DB.TextNote>();
        if (views.Count > 0)
        {
            var seen = new HashSet<long>();
            foreach (var v in views)
            {
                var view = Core.FindView(doc, v, uidoc: ctx.UiDoc)!;
                foreach (DB.TextNote n in new DB.FilteredElementCollector(doc, view.Id).OfClass(typeof(DB.TextNote)))
                {
                    if (seen.Add(n.Id.Value))
                        notes.Add(n);
                }
            }
        }
        else
        {
            notes = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.TextNote)).Cast<DB.TextNote>().ToList();
        }
        var plan = new List<(DB.TextNote n, string old, string neu, long count)>();
        foreach (var n in notes)
        {
            var old = n.Text ?? "";
            var (neu, count) = ReplaceInText(old, find, replace, regex, matchCase, whole);
            if (count != 0 && neu != old)
                plan.Add((n, old, neu, count));
        }
        var preview = Core.ConfirmGate(ctx, plan.Count, "replace_text");
        var dry = preview || ctx.DryRun;

        static string Cut(string s) => s.Length > 200 ? s.Substring(0, 200) : s;

        Dict Run()
        {
            var done = new Lst();
            foreach (var (n, old, neu, count) in plan)
            {
                n.Text = neu;
                var owner = doc.GetElement(n.OwnerViewId);
                done.Add(new Dict
                {
                    ["id"] = n.Id.Value, ["view"] = owner != null ? Utils.NormalizeString(owner.Name) : null,
                    ["old"] = Cut(Utils.NormalizeString(old)), ["new"] = Cut(Utils.NormalizeString(neu)), ["replacements"] = count,
                });
            }
            return new Dict { ["changed"] = DocsPy.Head(done, 300) };
        }

        Dict res;
        Lst fails;
        if (plan.Count > 0)
            (res, fails) = Core.RunTransaction<Dict>(doc, "Replace text", Run, dry);
        else
            (res, fails) = (new Dict { ["changed"] = new Lst() }, new Lst());
        var output = Core.CommitResult(res, fails, dry, new Dict
        {
            ["text_notes_searched"] = notes.Count, ["text_notes_changed"] = plan.Count,
            ["replacements"] = plan.Sum(p => p.count), ["truncated"] = plan.Count > 300,
        });
        if (plan.Count > 0)
            ctx.Warn("Setting a text note's text drops mixed formatting (bold / italic runs) inside that note.");
        return Core.PreviewStatus(output, preview);
    }

    public static Dict? Detailing(Ctx ctx)
    {
        var doc = ctx.Doc;
        var items = ctx.List("items");
        if (items.Count == 0)
            throw new RvtssError("'items' is required: [{kind: 'detail_line', start: [x, y], end: [x, y]}, ...]");
        if (items.Count > 500)
            throw new RvtssError("At most 500 items per call");
        var view = AnnotationView(ctx);
        var dry = ctx.DryRun;

        Dict One(object? raw)
        {
            var item = DocsPy.D(raw);
            var kind = item.Get("kind");
            if (kind is not string name || !DetailTable.TryGetValue(name, out var fn))
                throw new RvtssError($"Unknown kind '{Py.Str(kind)}'. Use {string.Join(", ", DetailKinds)}");
            return fn(ctx, view, item);
        }

        Dict Run() => new() { ["results"] = Core.Batch(doc, items, One, ctx.Bool("atomic", true)) };

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Detailing", Run, dry);
        res["created"] = ((Lst)res["results"]!).Count(r => Py.Truthy(((Dict)r!).Get("ok")));
        return Core.CommitResult(res, fails, dry, new Dict
        {
            ["view"] = Utils.NormalizeString(view.Name), ["view_id"] = view.Id.Value, ["unit"] = ctx.Unit,
        });
    }

    public static Dict? AnnotationTypes(Ctx ctx)
    {
        var doc = ctx.Doc;
        var kinds = ctx.List("kinds");
        var wanted = kinds.Count > 0
            ? new HashSet<string>(kinds.OfType<string>())
            : new HashSet<string> { "text", "dimension", "filled_region", "line_style", "tag" };
        var output = new Dict();

        Dict Brief(DB.Element t) => new() { ["id"] = t.Id.Value, ["name"] = Utils.NormalizeString(Utils.GetElementName(t)) };

        if (wanted.Contains("text"))
            output["text"] = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.TextNoteType)).Select(t => (object?)Brief(t)).ToList();
        if (wanted.Contains("dimension"))
        {
            var dims = new Lst();
            foreach (DB.DimensionType t in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.DimensionType)))
            {
                if (Utils.NormalizeString(Utils.GetElementName(t)).Length == 0)
                    continue;
                var d = Brief(t);
                try
                {
                    d["style"] = t.StyleType.ToString();
                }
                catch
                {
                    // no style
                }
                dims.Add(d);
            }
            output["dimension"] = dims;
        }
        if (wanted.Contains("filled_region"))
            output["filled_region"] = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FilledRegionType))
                .Select(t => (object?)Brief(t)).ToList();
        if (wanted.Contains("line_style"))
            output["line_style"] = LineStyles(doc).Keys.OrderBy(x => x, StringComparer.Ordinal).Cast<object?>().ToList();
        if (wanted.Contains("tag"))
        {
            var tags = new Dict();
            foreach (DB.FamilySymbol s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)))
            {
                var cat = s.Category;
                if (cat == null)
                    continue;
                var isTag = cat.IsTagCategory;
                if (isTag)
                {
                    var catName = Utils.NormalizeString(cat.Name);
                    var entry = Brief(s);
                    entry["family"] = Utils.NormalizeString(s.FamilyName);
                    ((Lst)tags.SetDefault(catName, new Lst())!).Add(entry);
                }
            }
            output["tag"] = tags;
        }
        return output;
    }
}
