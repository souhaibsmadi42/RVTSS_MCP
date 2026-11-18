namespace RvtssHost;

/// <summary>
/// Element selection shared by find_elements, bulk updates, audits, exports and QC: port of revit_mcp/query.py.
///
/// Query spec (all keys optional, combined with AND):
///     element_ids      [int]           explicit ids (other filters still apply)
///     selection        bool            current Revit selection (active document only)
///     categories       [str]           'Doors', 'OST_Doors' or category id
///     class_name       str             Revit API class, e.g. 'Wall', 'FamilyInstance'
///     include_types    bool            return element types instead of instances
///     view             id|name|active  only elements visible in that view
///     level            id|name         elements associated with that level
///     family, type     str             exact (case-insensitive) family / type name
///     name_contains    str             substring of the element name
///     text             str             all words must appear in category/family/type/name/mark
///     param_filters    [{name, op, value, unit}]  see Filters.Ops
/// </summary>
public static class Query
{
    public static readonly string[] QueryKeys =
    {
        "element_ids", "selection", "categories", "class_name", "include_types", "view",
        "level", "family", "type", "name_contains", "text", "param_filters",
    };

    /// <summary>Allow either a nested {"filter": {...}} or top-level query keys.</summary>
    public static Dict QuerySpec(Dict data, string key = "filter")
    {
        if (data.Get(key) is Dict nested)
            return nested;
        var spec = new Dict();
        foreach (var k in QueryKeys)
        {
            if (data.TryGetValue(k, out var v))
                spec[k] = v;
        }
        return spec;
    }

    private static readonly string[] ApiNamespaces =
    {
        "Autodesk.Revit.DB.", "Autodesk.Revit.DB.Architecture.", "Autodesk.Revit.DB.Mechanical.",
        "Autodesk.Revit.DB.Plumbing.", "Autodesk.Revit.DB.Electrical.", "Autodesk.Revit.DB.Structure.",
    };

    /// <summary>Revit API class by name: DB, then DB.Architecture / Mechanical / Plumbing / Electrical / Structure.</summary>
    internal static Type ApiClass(object? name)
    {
        var text = Py.Str(name);
        Type? cls = null;
        if (text.Length > 0 && text.IndexOfAny(new[] { '.', '+', ',', '[', '`' }) < 0)
        {
            var assembly = typeof(DB.Element).Assembly;
            foreach (var ns in ApiNamespaces)
            {
                try { cls = assembly.GetType(ns + text, false, false); }
                catch { cls = null; }
                if (cls != null)
                    break;
            }
        }
        if (cls == null)
            throw new RvtssError($"Unknown Revit API class '{text}'",
                hint: "Examples: Wall, Floor, FamilyInstance, FamilySymbol, Level, Grid, View, "
                      + "ViewSheet, Room (use categories for rooms), RevitLinkInstance, Group.");
        return cls;
    }

    public static List<DB.ElementId> SelectionIds(Ctx ctx)
    {
        if (ctx.UiDoc == null || ctx.UiDoc.Document == null || !ctx.UiDoc.Document.Equals(ctx.Doc))
            throw new RvtssError("Selection is only available for the active document", status: 409);
        return ctx.UiDoc.Selection.GetElementIds().ToList();
    }

    /// <summary>`value or []` of a request value that is iterated.</summary>
    private static Lst Items(object? value)
    {
        if (!Py.Truthy(value))
            return new Lst();
        if (value is Lst list)
            return list;
        if (value is Dict map) // iterating a dict gives its keys
            return map.Keys.Cast<object?>().ToList();
        if (value is string s)
            return s.Select(c => (object?)c.ToString()).ToList();
        return new Lst { value };
    }

    /// <summary>The "categories" value as a list (a single name is accepted).</summary>
    private static Lst Categories(Dict spec)
    {
        var cats = spec.Get("categories");
        if (cats is string single)
            return single.Length > 0 ? new Lst { single } : new Lst();
        return Items(cats);
    }

    /// <summary>(value or "").strip().lower() or None</summary>
    private static string? Wanted(object? value)
    {
        if (!Py.Truthy(value))
            return null;
        var s = Py.Str(value).Trim().ToLowerInvariant();
        return s.Length > 0 ? s : null;
    }

    private static string Lowered(object? value) => Py.Truthy(value) ? Py.Str(value).ToLowerInvariant() : "";

    private static bool HasView(object? view) => view != null && !(view is string s && s.Length == 0);

    private static DB.View ViewOf(Ctx ctx, object? view) =>
        Core.FindView(ctx.Doc, view, uidoc: view is string s && s == "active" ? ctx.UiDoc : null)!;

    /// <summary>Return the list of elements matching spec.</summary>
    public static List<DB.Element> Collect(Ctx ctx, Dict spec, int? maxScan = null)
    {
        var doc = ctx.Doc;
        foreach (var f in Items(spec.Get("param_filters")))
        {
            try { Filters.ValidateFilter(f); }
            catch (FilterError e) { throw new RvtssError(e.Message); }
        }
        var includeTypes = Py.Truthy(spec.Get("include_types"));

        var ids = new Lst(Items(spec.Get("element_ids")));
        if (Py.Truthy(spec.Get("selection")))
        {
            foreach (var id in SelectionIds(ctx))
                ids.Add(id);
            if (ids.Count == 0)
                return new List<DB.Element>();
        }
        IEnumerable<DB.Element> elements;
        bool native;
        if (ids.Count > 0)
        {
            var found = Core.GetElements(doc, ids);
            native = false;
            // explicit ids / selection: the collector filters below are applied here too
            var cats = Categories(spec);
            if (cats.Count > 0)
            {
                var catIds = new HashSet<long>(cats.Select(c => Core.ResolveCategory(doc, c).Id.Value));
                found = found.Where(e => e.Category != null && catIds.Contains(e.Category.Id.Value)).ToList();
            }
            if (Py.Truthy(spec.Get("class_name")))
            {
                var cls = ApiClass(spec["class_name"]);
                found = found.Where(e => cls.IsInstanceOfType(e)).ToList();
            }
            if (spec.Get("level") != null)
            {
                var lid = Core.FindLevel(doc, spec["level"])!.Id;
                found = found.Where(e => e.LevelId != null && e.LevelId == lid).ToList();
            }
            var view = spec.Get("view");
            if (HasView(view))
            {
                var v = ViewOf(ctx, view);
                var visible = new HashSet<long>(new DB.FilteredElementCollector(doc, v.Id).ToElementIds().Select(i => i.Value));
                found = found.Where(e => visible.Contains(e.Id.Value)).ToList();
            }
            elements = found;
        }
        else
        {
            var view = spec.Get("view");
            var col = HasView(view)
                ? new DB.FilteredElementCollector(doc, ViewOf(ctx, view).Id)
                : new DB.FilteredElementCollector(doc);
            col = includeTypes ? col.WhereElementIsElementType() : col.WhereElementIsNotElementType();
            var cats = Categories(spec);
            if (cats.Count == 1)
                col = col.OfCategoryId(Core.ResolveCategory(doc, cats[0]).Id);
            else if (cats.Count > 1)
                col = col.WherePasses(new DB.ElementMulticategoryFilter(
                    Core.ToIdList(cats.Select(c => Core.ResolveCategory(doc, c).Id).ToList())));
            if (Py.Truthy(spec.Get("class_name")))
                col = col.OfClass(ApiClass(spec["class_name"]));
            if (spec.Get("level") != null && !includeTypes)
                col = col.WherePasses(new DB.ElementLevelFilter(Core.FindLevel(doc, spec["level"])!.Id));
            elements = col;
            native = true;
        }

        var fam = Wanted(spec.Get("family"));
        var typ = Wanted(spec.Get("type"));
        var nameContains = Wanted(spec.Get("name_contains"));
        var text = spec.Get("text");
        var hasText = Py.Truthy(text);
        var pfilters = Items(spec.Get("param_filters"));
        var needCat = native && !Py.Truthy(spec.Get("categories")) && !Py.Truthy(spec.Get("class_name"));

        var result = new List<DB.Element>();
        var scanned = 0;
        foreach (var e in elements)
        {
            scanned++;
            if (maxScan != null && maxScan.Value != 0 && scanned > maxScan.Value)
            {
                ctx.Warn($"Stopped after scanning {maxScan.Value} elements; narrow the query.");
                break;
            }
            if (needCat && e.Category == null)
                continue; // skip internal, uncategorised elements in broad queries
            if (fam != null || typ != null || hasText)
            {
                var b = Core.ElementBrief(doc, e);
                if (fam != null && Lowered(b.Get("family")) != fam)
                    continue;
                if (typ != null && Lowered(b.Get("type")) != typ && !(includeTypes && Lowered(b.Get("name")) == typ))
                    continue;
                if (hasText)
                {
                    string? mark = null;
                    try
                    {
                        var mp = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK);
                        mark = mp != null ? mp.AsString() : null;
                    }
                    catch { /* no mark */ }
                    if (!Filters.TextMatch(Py.Str(text), new Lst { b.Get("category"), b.Get("family"), b.Get("type"), b.Get("name"), mark }))
                        continue;
                }
            }
            if (nameContains != null)
            {
                var n = Utils.NormalizeString(Utils.GetElementName(e) ?? "").ToLowerInvariant();
                if (n.IndexOf(nameContains, StringComparison.Ordinal) < 0)
                    continue;
            }
            if (pfilters.Count > 0 && !PassesParams(doc, e, pfilters))
                continue;
            result.Add(e);
        }
        return result;
    }

    private static bool PassesParams(DB.Document doc, DB.Element e, Lst pfilters)
    {
        foreach (var item in pfilters)
        {
            var f = (Dict)item!; // validated by Collect
            var (p, _) = ParamsUtil.Find(doc, e, f["name"], allowType: true);
            var exists = p != null;
            object? raw = null;
            string? display = null;
            if (p != null)
            {
                try { raw = ParamsUtil.RawValue(p, Py.Truthy(f.Get("unit")) ? Py.Str(f.Get("unit")) : "mm"); }
                catch { raw = null; }
                try { display = p.AsValueString(); }
                catch { display = null; }
                if (raw == null && display == null && p.StorageType == DB.StorageType.String)
                    raw = "";
            }
            if (!Filters.Match(Py.Str(f.Get("op", "eq")), f.Get("value"), raw, display, exists, Py.Truthy(f.Get("case_sensitive"))))
                return false;
        }
        return true;
    }

    /// <summary>{category name: count}, largest first.</summary>
    public static Dict CategoryCounts(IEnumerable<DB.Element> elements)
    {
        var counts = new Dictionary<string, long>();
        var order = new List<string>();
        foreach (var e in elements)
        {
            var c = e.Category;
            var n = c != null ? Utils.NormalizeString(c.Name) : "(none)";
            if (!counts.ContainsKey(n))
            {
                counts[n] = 0;
                order.Add(n);
            }
            counts[n]++;
        }
        var sorted = new Dict();
        foreach (var n in order.OrderByDescending(x => counts[x])) // stable: ties keep first-seen order
            sorted[n] = counts[n];
        return sorted;
    }
}
