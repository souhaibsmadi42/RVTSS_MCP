namespace RvtssHost.Modules;

// Object styles, subcategories, line styles, line patterns, fill patterns (project_admin.py, "styles").
public static partial class ProjectAdmin
{
    private static DB.GraphicsStyleType Gst(string name) =>
        name == "cut" ? DB.GraphicsStyleType.Cut : DB.GraphicsStyleType.Projection;

    private static List<DB.LinePatternElement> LinePatterns(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.LinePatternElement)).Cast<DB.LinePatternElement>().ToList();

    private static DB.ElementId LinePatternId(DB.Document doc, object? name)
    {
        var key = Py.Str(name).Trim().ToLowerInvariant();
        if (key == "solid" || key == "<solid>")
            return DB.LinePatternElement.GetSolidPatternId();
        foreach (var p in LinePatterns(doc))
            if (Name(p).ToLowerInvariant() == key || Py.Str(p.Id.Value) == key)
                return p.Id;
        throw Core.NotFound("Line pattern", name, new[] { "Solid" }.Concat(LinePatterns(doc).Select(p => Name(p))));
    }

    private static Dict StyleInfo(DB.Document doc, DB.Category cat)
    {
        var o = new Dict { ["name"] = Utils.NormalizeString(cat.Name), ["id"] = cat.Id.Value };
        foreach (var key in new[] { "projection", "cut" })
        {
            try
            {
                var w = cat.GetLineWeight(Gst(key));
                o["line_weight_" + key] = w != null ? (object)(long)w.Value : null;
            }
            catch
            {
                o["line_weight_" + key] = null;
            }
        }
        try { o["line_color"] = ColorList(cat.LineColor); }
        catch { o["line_color"] = null; }
        try
        {
            var pid = cat.GetLinePatternId(Gst("projection"));
            if (pid == DB.LinePatternElement.GetSolidPatternId())
            {
                o["line_pattern"] = "Solid";
            }
            else
            {
                var p = doc.GetElement(pid);
                o["line_pattern"] = p != null ? Name(p) : null;
            }
        }
        catch
        {
            o["line_pattern"] = null;
        }
        try { o["material"] = cat.Material != null ? Name(cat.Material) : null; }
        catch { o["material"] = null; }
        return o;
    }

    private static DB.Category? Subcategory(DB.Category parent, object? name)
    {
        var key = Py.Str(name).Trim().ToLowerInvariant();
        foreach (DB.Category sub in parent.SubCategories)
            if (Utils.NormalizeString(sub.Name).ToLowerInvariant() == key)
                return sub;
        return null;
    }

    private static (DB.Category parent, DB.Category target) TargetCategory(Ctx ctx, DB.Document doc)
    {
        var parent = Core.ResolveCategory(doc, ctx.Require("category"));
        var subName = ctx.Get("subcategory");
        if (!Py.Truthy(subName))
            return (parent, parent);
        var sub = Subcategory(parent, subName);
        if (sub == null)
            throw Core.NotFound("Subcategory of " + Utils.NormalizeString(parent.Name), subName,
                parent.SubCategories.Cast<DB.Category>().Select(s => Utils.NormalizeString(s.Name)));
        return (parent, sub);
    }

    private static Dict ApplyStyle(Ctx ctx, DB.Document doc, DB.Category cat)
    {
        var changed = new Dict();
        foreach (var key in new[] { "projection", "cut" })
        {
            var w = ctx.Int(key == "cut" ? "line_weight_" + key : "line_weight");
            if (w != null)
            {
                if (!(1 <= w && w <= 16))
                    throw new RvtssError("Line weights are 1-16");
                try
                {
                    cat.SetLineWeight((int)w.Value, Gst(key));
                    changed["line_weight_" + key] = w.Value;
                }
                catch (Exception e)
                {
                    if (key == "projection")
                        throw;
                    ctx.Warn("Cut line weight not set: " + Utils.NormalizeString(e.Message));
                }
            }
        }
        if (ctx.Get("line_color") != null)
        {
            cat.LineColor = Color(ctx.Get("line_color"));
            changed["line_color"] = ColorList(cat.LineColor);
        }
        if (Py.Truthy(ctx.Get("line_pattern")))
        {
            cat.SetLinePatternId(LinePatternId(doc, ctx.Get("line_pattern")), Gst("projection"));
            changed["line_pattern"] = ctx.Get("line_pattern");
        }
        if (ctx.Get("material") != null)
        {
            var mname = Py.Str(ctx.Get("material")).Trim();
            if (mname.ToLowerInvariant() == "" || mname.ToLowerInvariant() == "none")
            {
                cat.Material = null;
            }
            else
            {
                var mats = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Material)).Cast<DB.Material>().ToList();
                var mat = mats.FirstOrDefault(m => Name(m).ToLowerInvariant() == mname.ToLowerInvariant());
                if (mat == null)
                    throw Core.NotFound("Material", mname, mats.Select(m => Name(m)));
                cat.Material = mat;
            }
            changed["material"] = mname.Length > 0 ? mname : null;
        }
        return changed;
    }

    public static Dict? ManageStyles(Ctx ctx)
    {
        var doc = ctx.Doc;
        var action = Py.Str(ctx.Get("action", "list_object_styles"));
        var dry = ctx.DryRun;
        if (action == "list_object_styles")
        {
            List<DB.Category> cats;
            if (Py.Truthy(ctx.Get("category")))
            {
                cats = new List<DB.Category> { Core.ResolveCategory(doc, ctx.Get("category")) };
            }
            else
            {
                var ctypeKey = ctx.Get("category_type", "model") as string;
                DB.CategoryType? ctype = ctypeKey == "model" ? DB.CategoryType.Model
                    : ctypeKey == "annotation" ? DB.CategoryType.Annotation
                    : null;
                cats = doc.Settings.Categories.Cast<DB.Category>().Where(c => ctype == null || c.CategoryType == ctype)
                    .OrderBy(c => Utils.NormalizeString(c.Name).ToLowerInvariant(), StringComparer.Ordinal).ToList();
            }
            var limit = ctx.I("limit", 80, 1, 500);
            var includeSub = ctx.Bool("include_subcategories", Py.Truthy(ctx.Get("category")));
            var result = new Lst();
            foreach (var c in cats.Take(limit))
            {
                var d = StyleInfo(doc, c);
                var subs = c.SubCategories.Cast<DB.Category>().ToList();
                d["subcategory_count"] = subs.Count;
                if (includeSub)
                    d["subcategories"] = subs.Select(s => StyleInfo(doc, s))
                        .OrderBy(x => ((string)x["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
                result.Add(d);
            }
            return new Dict { ["count"] = cats.Count, ["truncated"] = cats.Count > limit, ["categories"] = result };
        }
        if (action == "list_patterns")
        {
            var kinds = ctx.List("kinds");
            var wanted = kinds.Count > 0 ? new HashSet<string>(kinds.OfType<string>()) : new HashSet<string> { "line", "fill" };
            var result = new Dict();
            if (wanted.Contains("line"))
                result["line_patterns"] = new[] { "Solid" }.Concat(LinePatterns(doc).Select(p => Name(p)).OrderBy(x => x, StringComparer.Ordinal))
                    .ToList();
            if (wanted.Contains("fill"))
            {
                var fills = new List<Dict>();
                foreach (DB.FillPatternElement f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement)))
                {
                    var d = new Dict { ["id"] = f.Id.Value, ["name"] = Name(f) };
                    try
                    {
                        var fp = f.GetFillPattern();
                        d["target"] = fp.Target.ToString();
                        d["solid"] = fp.IsSolidFill;
                    }
                    catch { /* no pattern details */ }
                    fills.Add(d);
                }
                result["fill_patterns"] = fills.OrderBy(d => ((string)d["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
            }
            return result;
        }
        if (action == "set_object_style")
        {
            var (_, cat) = TargetCategory(ctx, doc);
            var before = StyleInfo(doc, cat);

            Dict Run()
            {
                var changed = ApplyStyle(ctx, doc, cat);
                if (changed.Count == 0)
                    throw new RvtssError("Nothing to set: give line_weight, line_weight_cut, line_color, line_pattern "
                                         + "or material");
                return new Dict { ["changed"] = changed, ["style"] = StyleInfo(doc, cat) };
            }

            var (res, fails) = Core.RunTransaction(doc, "Object style", Run, dry);
            return Core.CommitResult(res, fails, dry, new Dict { ["before"] = before });
        }
        if (action == "create_subcategory" || action == "create_line_style")
        {
            var name = Py.Str(ctx.Require("name")).Trim();
            DB.Category parent;
            if (action == "create_line_style")
                parent = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines);
            else
                parent = Core.ResolveCategory(doc, ctx.Require("category"));
            if (Subcategory(parent, name) != null)
                throw new RvtssError($"'{name}' already exists under {Utils.NormalizeString(parent.Name)}", status: 409,
                    hint: $"Use set_object_style with subcategory='{name}' to change it.");

            Dict Run()
            {
                var sub = doc.Settings.Categories.NewSubcategory(parent, name);
                ApplyStyle(ctx, doc, sub);
                return new Dict { ["created"] = StyleInfo(doc, sub), ["parent"] = Utils.NormalizeString(parent.Name) };
            }

            var (res, fails) = Core.RunTransaction(doc, "New subcategory", Run, dry);
            return Core.CommitResult(res, fails, dry);
        }
        if (action == "create_line_pattern")
        {
            var name = Py.Str(ctx.Require("name")).Trim();
            var segs = ctx.List("segments");
            if (segs.Count < 2 || segs.Count % 2 != 0)
                throw new RvtssError("'segments' needs an even number of entries alternating dash/dot and space, e.g. "
                                     + "[{type:'dash', length:6}, {type:'space', length:3}]");
            if (LinePatterns(doc).Any(p => Name(p).ToLowerInvariant() == name.ToLowerInvariant()))
                throw new RvtssError($"Line pattern '{name}' already exists", status: 409);
            var kinds = new Dictionary<string, DB.LinePatternSegmentType>
            {
                ["dash"] = DB.LinePatternSegmentType.Dash, ["space"] = DB.LinePatternSegmentType.Space,
                ["dot"] = DB.LinePatternSegmentType.Dot,
            };
            var built = new List<DB.LinePatternSegment>();
            foreach (var item in segs)
            {
                if (item is not Dict s)
                    throw new InvalidCastException("'" + Py.TypeName(item) + "' object has no attribute 'get'");
                var kind = Py.Str(s.Get("type", "")).ToLowerInvariant();
                if (!kinds.ContainsKey(kind))
                    throw new RvtssError("Segment type must be dash, space or dot");
                var length = kind == "dot"
                    ? 0.0
                    : Units.ToInternal(Py.Truthy(s.Get("length")) ? Py.ToFloat(s.Get("length")) : 0.0, ctx.Unit);
                if (kind != "dot" && length <= 0)
                    throw new RvtssError("Dash and space segments need a positive length");
                built.Add(new DB.LinePatternSegment(kinds[kind], length));
            }

            Dict Run()
            {
                var lp = new DB.LinePattern(name);
                lp.SetSegments(built);
                var el = DB.LinePatternElement.Create(doc, lp);
                return new Dict { ["created"] = new Dict { ["id"] = el.Id.Value, ["name"] = Name(el), ["segments"] = segs.Count } };
            }

            var (res, fails) = Core.RunTransaction(doc, "New line pattern", Run, dry);
            return Core.CommitResult(res, fails, dry);
        }
        if (action == "create_fill_pattern")
        {
            var name = Py.Str(ctx.Require("name")).Trim();
            foreach (DB.FillPatternElement f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement)))
                if (Name(f).ToLowerInvariant() == name.ToLowerInvariant())
                    throw new RvtssError($"Fill pattern '{name}' already exists", status: 409);
            var target = ctx.Get("target", "drafting") is string ts && ts == "model"
                ? DB.FillPatternTarget.Model
                : DB.FillPatternTarget.Drafting;
            var spacing = ctx.Float("spacing");
            if (spacing == null || spacing.Value == 0.0 || spacing.Value <= 0)
                throw new RvtssError("'spacing' (in `unit`) is required and must be positive");
            var spacing2 = ctx.Float("spacing2");
            var angle = Radians(ctx.F("angle", 0.0));

            Dict Run()
            {
                var orient = DB.FillPatternHostOrientation.ToHost;
                var s1 = Units.ToInternal(spacing.Value, ctx.Unit);
                DB.FillPattern fp;
                if (spacing2 != null && spacing2.Value != 0.0)
                    fp = new DB.FillPattern(name, target, orient, angle, s1, Units.ToInternal(spacing2.Value, ctx.Unit));
                else
                    fp = new DB.FillPattern(name, target, orient, angle, s1);
                var el = DB.FillPatternElement.Create(doc, fp);
                return new Dict
                {
                    ["created"] = new Dict
                    {
                        ["id"] = el.Id.Value, ["name"] = Name(el), ["target"] = target.ToString(),
                        ["crosshatch"] = spacing2 != null && spacing2.Value != 0.0,
                    },
                };
            }

            var (res, fails) = Core.RunTransaction(doc, "New fill pattern", Run, dry);
            return Core.CommitResult(res, fails, dry);
        }
        throw new RvtssError("action must be list_object_styles, set_object_style, create_subcategory, "
                             + "create_line_style, list_patterns, create_line_pattern or create_fill_pattern");
    }
}
