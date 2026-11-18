using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Materials: inventory, quantity take-off and editing (RVTSS v2.2). Port of revit_mcp/materials.py.
///
/// Routes:
///     POST /materials/list/      materials with class, colour, transparency, appearance asset, patterns, usage
///     POST /materials/takeoff/   area / volume per material from element geometry, grouped
///     POST /materials/manage/    create, duplicate, rename, set properties, assign to elements / types / layers
/// </summary>
public static class Materials
{
    public static void Register(RouteTable api)
    {
        api.Post("/materials/list/", ListMaterials, "list_materials");
        api.Post("/materials/takeoff/", Takeoff, "takeoff");
        api.Post("/materials/manage/", Manage, "manage");
    }

    /// <summary>'#RRGGBB'. (The Python format string "{:02X}" printed a .NET Byte as e.g. "2292X": that is a
    /// bug of the original, the real hex colour is returned here.)</summary>
    private static string? Hex(DB.Color? color)
    {
        try
        {
            if (color == null || !color.IsValid)
                return null;
            return "#" + color.Red.ToString("X2", CultureInfo.InvariantCulture) + color.Green.ToString("X2", CultureInfo.InvariantCulture)
                   + color.Blue.ToString("X2", CultureInfo.InvariantCulture);
        }
        catch
        {
            return null;
        }
    }

    private static string? NameOf(DB.Document doc, DB.ElementId eid)
    {
        if (!Compat.IsValidId(eid))
            return null;
        var e = doc.GetElement(eid);
        return e != null ? Utils.NormalizeString(e.Name) : null;
    }

    /// <summary>Surface / cut pattern ids: the foreground pattern properties of Revit 2019 and later (the Python
    /// version also tried the older SurfacePatternId / CutPatternId names).</summary>
    private static List<(string key, DB.ElementId id)> PatternIds(DB.Material m)
    {
        var res = new List<(string, DB.ElementId)>();
        try { res.Add(("surface_pattern", m.SurfaceForegroundPatternId)); }
        catch { /* not available */ }
        try { res.Add(("cut_pattern", m.CutForegroundPatternId)); }
        catch { /* not available */ }
        return res;
    }

    private static Dict Describe(DB.Document doc, DB.Material m)
    {
        var d = new Dict
        {
            ["id"] = m.Id.Value, ["name"] = Utils.NormalizeString(m.Name),
            ["class"] = Utils.NormalizeString(m.MaterialClass ?? ""),
            ["category"] = Utils.NormalizeString(m.MaterialCategory ?? ""), ["color"] = Hex(m.Color),
            ["transparency"] = (long)m.Transparency, ["shininess"] = (long)m.Shininess,
        };
        try { d["appearance_asset"] = NameOf(doc, m.AppearanceAssetId); }
        catch { /* no appearance asset */ }
        foreach (var (key, pid) in PatternIds(m))
            d[key] = NameOf(doc, pid);
        return d;
    }

    private static Dictionary<long, long> UsageCounts(DB.Document doc)
    {
        var counts = new Dictionary<long, long>();
        var isModel = new Dictionary<long, bool>();
        foreach (var e in new DB.FilteredElementCollector(doc).WhereElementIsNotElementType())
        {
            var cat = e.Category;
            if (cat == null)
                continue;
            var cid = cat.Id.Value;
            if (!isModel.TryGetValue(cid, out var model))
            {
                model = cat.CategoryType == DB.CategoryType.Model;
                isModel[cid] = model;
            }
            if (!model)
                continue;
            try
            {
                // the ids are listed for the material and the paint (list(...) + list(...))
                var ids = e.GetMaterialIds(false);
                var paint = e.GetMaterialIds(true);
                foreach (var mid in ids)
                    counts[mid.Value] = (counts.TryGetValue(mid.Value, out var c1) ? c1 : 0) + 1;
                foreach (var mid in paint)
                    counts[mid.Value] = (counts.TryGetValue(mid.Value, out var c2) ? c2 : 0) + 1;
            }
            catch { continue; }
        }
        return counts;
    }

    private static string LowerOf(object? value) => Py.Truthy(value) ? Py.Str(value).ToLowerInvariant() : "";

    public static Dict? ListMaterials(Ctx ctx)
    {
        var doc = ctx.Doc;
        var contains = LowerOf(ctx.Get("contains"));
        var mclass = LowerOf(ctx.Get("material_class"));
        var usage = ctx.Bool("include_usage", false) ? UsageCounts(doc) : null;
        var items = new List<Dict>();
        foreach (DB.Material m in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Material)))
        {
            var d = Describe(doc, m);
            if (contains.Length > 0 && ((string)d["name"]!).ToLowerInvariant().IndexOf(contains, StringComparison.Ordinal) < 0)
                continue;
            if (mclass.Length > 0 && ((string)d["class"]!).ToLowerInvariant() != mclass)
                continue;
            if (usage != null)
                d["used_by_elements"] = usage.TryGetValue((long)d["id"]!, out var n) ? n : 0L;
            items.Add(d);
        }
        if (usage != null && ctx.Bool("unused_only", false))
            items = items.Where(d => !Py.Truthy(d["used_by_elements"])).ToList();
        items = items.OrderBy(d => ((string)d["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
        var (page, meta) = Pure.Filters.Paginate(items, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, Core.MaxLimit));
        var classes = new Dict();
        foreach (var d in items)
        {
            var key = Py.Truthy(d["class"]) ? (string)d["class"]! : "(none)";
            classes[key] = (classes.TryGetValue(key, out var v) ? (long)v! : 0L) + 1;
        }
        return new Dict { ["count"] = (long)items.Count, ["by_class"] = classes, ["pagination"] = meta, ["materials"] = page };
    }

    private sealed class TakeoffGroup
    {
        public string[] Parts = Array.Empty<string>();
        public double Area;
        public double Volume;
        public double PaintedArea;
        public readonly HashSet<long> Elements = new();
    }

    public static Dict? Takeoff(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var spec = Query.QuerySpec(ctx.Data);
        if (!new[] { "element_ids", "selection", "categories", "view", "level", "class_name" }.Any(k => Py.Truthy(spec.Get(k))))
            throw new RvtssError("Give a scope: categories, element_ids, view, level or selection",
                hint: "e.g. categories=['Walls','Floors'] for a structure take-off.");
        string areaUnit, volumeUnit;
        try
        {
            var au = ctx.Get("area_unit");
            areaUnit = Pure.Units.LengthUnitFor("area", Py.Truthy(au) ? Py.Str(au) : "m2")!;
            var vu = ctx.Get("volume_unit");
            volumeUnit = Pure.Units.LengthUnitFor("volume", Py.Truthy(vu) ? Py.Str(vu) : "m3")!;
        }
        catch (UnitError e)
        {
            throw new RvtssError(e.Message);
        }
        var groupBy = ctx.List("group_by");
        if (groupBy.Count == 0)
            groupBy = new Lst { "material" };
        foreach (var g in groupBy)
        {
            if (!(g is string gs && (gs == "material" || gs == "category" || gs == "level" || gs == "type")))
                throw new RvtssError("group_by entries must be material, category, level or type");
        }
        var groupNames = groupBy.Select(g => (string)g!).ToArray();
        var includePaint = ctx.Bool("include_paint", true);
        var maxScan = ctx.Int("max_scan", 200000)!.Value;
        var elements = Query.Collect(ctx, spec, (int)Math.Min(maxScan, int.MaxValue));
        var groups = new Dictionary<string, TakeoffGroup>(StringComparer.Ordinal);
        var order = new List<TakeoffGroup>();
        var scanned = 0L;
        var info = new ElementInfoCache(doc);
        var materialNames = new Dictionary<long, string?>();

        string? MaterialName(DB.ElementId id)
        {
            if (!materialNames.TryGetValue(id.Value, out var n))
            {
                n = NameOf(doc, id);
                materialNames[id.Value] = n;
            }
            return n;
        }

        foreach (var e in elements)
        {
            ICollection<DB.ElementId> mids;
            ICollection<DB.ElementId> pids;
            try
            {
                mids = e.GetMaterialIds(false);
                pids = includePaint ? e.GetMaterialIds(true) : new List<DB.ElementId>();
            }
            catch { continue; }
            if (mids.Count == 0 && pids.Count == 0)
                continue;
            scanned++;
            Dict? brief = null;
            string? briefLevel = null;
            var eid = e.Id.Value;
            for (var pass = 0; pass < 2; pass++)
            {
                var painted = pass == 1;
                foreach (var mid in painted ? pids : mids)
                {
                    double area, volume;
                    try
                    {
                        area = e.GetMaterialArea(mid, painted);
                        volume = painted ? 0.0 : e.GetMaterialVolume(mid);
                    }
                    catch { continue; }
                    if (brief == null)
                    {
                        brief = info.Brief(e);
                        briefLevel = info.Level(e);
                    }
                    var parts = new string[groupNames.Length];
                    for (var k = 0; k < groupNames.Length; k++)
                    {
                        switch (groupNames[k])
                        {
                            case "material":
                                var mn = MaterialName(mid);
                                parts[k] = string.IsNullOrEmpty(mn) ? "(none)" : mn!;
                                break;
                            case "category":
                                parts[k] = Py.Truthy(brief["category"]) ? (string)brief["category"]! : "(none)";
                                break;
                            case "level":
                                parts[k] = string.IsNullOrEmpty(briefLevel) ? "(none)" : briefLevel!;
                                break;
                            default:
                                parts[k] = (Py.Truthy(brief.Get("family")) ? Py.Str(brief["family"]) : "") + " : "
                                           + (Py.Truthy(brief.Get("type")) ? Py.Str(brief["type"]) : "");
                                break;
                        }
                    }
                    var key = string.Join("\u001f", parts);
                    if (!groups.TryGetValue(key, out var grp))
                    {
                        grp = new TakeoffGroup { Parts = parts };
                        groups[key] = grp;
                        order.Add(grp);
                    }
                    if (painted)
                    {
                        grp.PaintedArea += area;
                    }
                    else
                    {
                        grp.Area += area;
                        grp.Volume += volume;
                    }
                    grp.Elements.Add(eid);
                }
            }
        }
        var rows = new List<Dict>();
        foreach (var grp in order)
        {
            var row = new Dict();
            for (var k = 0; k < groupNames.Length; k++)
                row[groupNames[k]] = grp.Parts[k];
            row["area"] = Pure.Units.FromInternal(grp.Area, areaUnit, 3);
            row["volume"] = Pure.Units.FromInternal(grp.Volume, volumeUnit, 4);
            row["painted_area"] = Pure.Units.FromInternal(grp.PaintedArea, areaUnit, 3);
            row["element_count"] = (long)grp.Elements.Count;
            row["element_ids"] = grp.Elements.OrderBy(i => i).Take(50).Cast<object?>().ToList();
            rows.Add(row);
        }
        rows = rows.OrderBy(r => -(double)r["volume"]! - (double)r["area"]! * 1e-6).ToList();
        var (page, meta) = Pure.Filters.Paginate(rows, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, 2000));
        var totalArea = 0.0;
        var totalVolume = 0.0;
        foreach (var r in rows)
        {
            totalArea += (double)r["area"]!;
            totalVolume += (double)r["volume"]!;
        }
        return new Dict
        {
            ["area_unit"] = areaUnit, ["volume_unit"] = volumeUnit, ["group_by"] = groupBy,
            ["elements_in_scope"] = (long)elements.Count, ["elements_with_materials"] = scanned,
            ["total_area"] = Py.Round(totalArea, 3), ["total_volume"] = Py.Round(totalVolume, 4),
            ["note"] = "Area is the material's exposed face area Revit reports (GetMaterialArea); volume comes from "
                       + "element geometry. Paint is reported separately (painted_area).",
            ["pagination"] = meta, ["rows"] = page,
        };
    }

    private static byte HexByte(string part)
    {
        // int(h[0:2], 16): Python also accepts a sign, spaces and "0x"; anything else is a ValueError
        var text = part.Trim();
        if (text.Length == 0 || !text.All(Uri.IsHexDigit))
            throw new Compat.ValueError("invalid literal for int() with base 16: '" + part + "'");
        return byte.Parse(text, NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture);
    }

    private static DB.Color Color(object? hex)
    {
        var h = Py.Str(hex).TrimStart('#');
        if (h.Length != 6)
            throw new RvtssError("Colours must be hex like '#C0C0C0'");
        return new DB.Color(HexByte(h.Substring(0, 2)), HexByte(h.Substring(2, 2)), HexByte(h.Substring(4, 2)));
    }

    /// <summary>A material by name or id.</summary>
    public static DB.Material FindMaterial(DB.Document doc, object? nameOrId)
    {
        if (nameOrId == null)
            throw new RvtssError("'material' (name or id) is required");
        var mats = new List<DB.Material>();
        foreach (DB.Material m in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Material)))
            mats.Add(m);
        var s = Py.Str(nameOrId).Trim();
        if (s.Length > 0 && s.All(char.IsDigit))
        {
            if (doc.GetElement(Compat.MakeId(Py.ToInt(s))) is DB.Material byId)
                return byId;
        }
        foreach (var m in mats)
        {
            if (Utils.NormalizeString(m.Name).ToLowerInvariant() == s.ToLowerInvariant())
                return m;
        }
        throw Core.NotFound("Material", nameOrId, mats.Select(m => m.Name), hint: "Use list_materials.");
    }

    /// <summary>Cut patterns must be drafting patterns; surface patterns may be model or drafting (2019+).</summary>
    private static DB.FillPatternElement FillPattern(DB.Document doc, object? name, bool drafting = true)
    {
        var wanted = Py.Str(name).ToLowerInvariant();
        foreach (DB.FillPatternElement fp in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement)))
        {
            try
            {
                var pat = fp.GetFillPattern();
                if (Utils.NormalizeString(fp.Name).ToLowerInvariant() == wanted
                    && (!drafting || pat.Target == DB.FillPatternTarget.Drafting || pat.IsSolidFill))
                    return fp;
            }
            catch { continue; }
        }
        throw Core.NotFound("Fill pattern", name, new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement))
            .Select(fp => fp.Name));
    }

    private static void SetProps(DB.Document doc, DB.Material m, Dict props, Action<string> warn)
    {
        if (Py.Truthy(props.Get("color")))
            m.Color = Color(props["color"]);
        if (props.Get("transparency") != null)
            m.Transparency = (int)Math.Max(0, Math.Min(100, Py.ToInt(props["transparency"])));
        if (props.Get("shininess") != null)
            m.Shininess = (int)Math.Max(0, Math.Min(128, Py.ToInt(props["shininess"])));
        if (Py.Truthy(props.Get("material_class")))
            m.MaterialClass = Py.Str(props["material_class"]);
        if (props.Get("use_render_appearance") != null)
            m.UseRenderAppearanceForShading = Py.Truthy(props["use_render_appearance"]);
        foreach (var (key, drafting) in new[] { ("surface_pattern", false), ("cut_pattern", true) })
        {
            if (!Py.Truthy(props.Get(key)))
                continue;
            var fp = FillPattern(doc, props[key], drafting);
            try
            {
                if (key == "surface_pattern")
                    m.SurfaceForegroundPatternId = fp.Id;
                else
                    m.CutForegroundPatternId = fp.Id;
            }
            catch
            {
                warn($"{key} not applied on this Revit version");
            }
        }
        foreach (var key in new[] { "surface_pattern_color", "cut_pattern_color" })
        {
            if (!Py.Truthy(props.Get(key)))
                continue;
            var c = Color(props[key]);
            try
            {
                if (key == "surface_pattern_color")
                    m.SurfaceForegroundPatternColor = c;
                else
                    m.CutForegroundPatternColor = c;
            }
            catch { /* not available on this version: silently ignored, as in the Python loop */ }
        }
    }

    /// <summary>Material -> instance/type material parameters, or compound-structure layers of host types.</summary>
    private static (Lst done, Lst skipped) Assign(DB.Document doc, Ctx ctx, DB.Material mat)
    {
        var paramName = Py.Truthy(ctx.Get("parameter")) ? ctx.Get("parameter") : "Material";
        var done = new Lst();
        var skipped = new Lst();
        var layer = ctx.Get("layer_index");
        foreach (var e in Core.GetElements(doc, ctx.List("element_ids")))
        {
            if (layer != null)
            {
                var target = e as DB.HostObjAttributes ?? doc.GetElement(e.GetTypeId()) as DB.HostObjAttributes;
                if (target == null)
                {
                    skipped.Add(new Dict { ["id"] = e.Id.Value, ["reason"] = "no compound structure (walls, floors, roofs, ceilings)" });
                    continue;
                }
                var cs = target.GetCompoundStructure();
                var index = Py.ToInt(layer);
                if (cs == null || index < 0 || index >= cs.LayerCount)
                {
                    skipped.Add(new Dict { ["id"] = e.Id.Value, ["reason"] = "layer_index out of range" });
                    continue;
                }
                cs.SetMaterialId((int)index, mat.Id);
                target.SetCompoundStructure(cs);
                done.Add(new Dict { ["id"] = target.Id.Value, ["layer_index"] = index, ["type_edit"] = true });
                continue;
            }
            var (p, owner) = ParamsUtil.Find(doc, e, paramName);
            if (p == null || p.IsReadOnly || p.StorageType != DB.StorageType.ElementId)
            {
                skipped.Add(new Dict
                {
                    ["id"] = e.Id.Value, ["reason"] = $"no writable material parameter '{Py.Str(paramName)}'",
                });
                continue;
            }
            p.Set(mat.Id);
            done.Add(new Dict
            {
                ["id"] = e.Id.Value, ["parameter"] = paramName, ["on"] = owner,
                ["note"] = owner == "type" ? "type parameter: every instance of the type changes" : null,
            });
        }
        if (done.Count == 0 && skipped.Count > 0)
            throw new RvtssError("Nothing assigned: " + Py.Str(((Dict)skipped[0]!)["reason"]))
                .With("skipped", skipped.Take(20).ToList());
        return (done, skipped);
    }

    public static Dict? Manage(Ctx ctx)
    {
        var doc = ctx.Doc;
        var actionValue = ctx.Require("action");
        var action = Py.Str(actionValue);
        var dry = ctx.DryRun;
        var props = Py.Truthy(ctx.Get("properties")) ? Obj(ctx.Get("properties")) : new Dict();
        var forced = false;
        if (action == "assign")
        {
            var ids = ctx.List("element_ids");
            if (ids.Count == 0)
                throw new RvtssError("assign needs element_ids");
            if (Core.ConfirmGate(ctx, ids.Count, "Material assignment"))
            {
                forced = !ctx.DryRun;
                dry = true;
            }
        }

        Dict Run()
        {
            if (action == "create")
            {
                var name = Py.Str(ctx.Require("name"));
                if (new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Material)).Cast<DB.Material>()
                    .Any(mm => Utils.NormalizeString(mm.Name).ToLowerInvariant() == name.ToLowerInvariant()))
                    throw new RvtssError($"A material named '{name}' already exists", status: 409,
                        hint: "Use action='set_properties' or pick another name.");
                var created = (DB.Material)doc.GetElement(DB.Material.Create(doc, name));
                SetProps(doc, created, props, ctx.Warn);
                return new Dict { ["material"] = Describe(doc, created) };
            }
            var mat = FindMaterial(doc, ctx.Get("material"));
            if (action == "duplicate")
            {
                var copy = mat.Duplicate(Py.Str(ctx.Require("name")));
                SetProps(doc, copy, props, ctx.Warn);
                return new Dict { ["material"] = Describe(doc, copy), ["source"] = Utils.NormalizeString(mat.Name) };
            }
            if (action == "rename")
            {
                var old = Utils.NormalizeString(mat.Name);
                mat.Name = Py.Str(ctx.Require("name"));
                return new Dict { ["material"] = Describe(doc, mat), ["old_name"] = old };
            }
            if (action == "set_properties")
            {
                if (props.Count == 0)
                    throw new RvtssError("set_properties needs 'properties'");
                SetProps(doc, mat, props, ctx.Warn);
                return new Dict { ["material"] = Describe(doc, mat) };
            }
            if (action == "assign")
            {
                var (done, skipped) = Assign(doc, ctx, mat);
                return new Dict { ["material"] = Utils.NormalizeString(mat.Name), ["assigned"] = done, ["skipped"] = skipped };
            }
            throw new RvtssError("action must be create, duplicate, rename, set_properties or assign");
        }

        var (res, fails) = Core.RunTransaction(doc, "Materials: " + action, Run, dry);
        return Core.PreviewStatus(Core.CommitResult(res, fails, dry), forced);
    }

    private static Dict Obj(object? v) => Qc.Obj(v);
}
