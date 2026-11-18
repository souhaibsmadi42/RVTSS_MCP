using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Element inspection and editing routes (RVTSS): port of revit_mcp/elements.py.
///
/// Routes:
///     POST /find_elements/          query + paginate elements
///     POST /element_details/        full details for up to 50 ids
///     POST /selection/              get or set the Revit selection
///     POST /set_parameters/         batch parameter writes (unit-safe)
///     POST /bulk_update_parameter/  one parameter on many elements, value or template
///     POST /transform_elements/     move / copy / rotate / mirror
///     POST /delete_elements/        preview by default, confirm=true to delete
///     POST /create_elements/        levels, grids, walls, floors, family instances, rooms, roofs, ceilings,
///                                   columns, beams, foundations, wall foundations; (2.3) ducts, pipes,
///                                   cable trays, conduit, openings, shafts, railings, spaces, areas,
///                                   boundary lines, automatic rooms, rebar, toposolids, DirectShape meshes
///     POST /element_types/          duplicate / rename types, change element types
///
/// Files: Elements.cs (inspect, parameters, shared helpers), Elements.Transform.cs (transform, delete),
/// Elements.Create.cs (create_elements and the 2.2 kinds), Elements.Mep.cs (2.3 kinds),
/// Elements.Modelling.cs (2.4 kinds, element_types).
/// </summary>
public static partial class Elements
{
    // ------------------------------------------------------------------- routes
    /// <summary>register_elements_routes</summary>
    public static void Register(RouteTable api)
    {
        api.Post("/find_elements/", FindElements, "find_elements");
        api.Post("/element_details/", ElementDetails, "element_details");
        api.Post("/selection/", Selection, "selection");
        api.Post("/set_parameters/", SetParameters, "set_parameters");
        api.Post("/bulk_update_parameter/", BulkUpdateParameter, "bulk_update_parameter");
        api.Post("/transform_elements/", TransformElements, "transform_elements");
        api.Post("/delete_elements/", DeleteElements, "delete_elements");
        api.Post("/create_elements/", CreateElements, "create_elements");
        api.Post("/element_types/", ElementTypes, "element_types");
        Log.Write("RVTSS element routes registered");
    }

    // ------------------------------------------------- Python-flavoured helpers
    /// <summary>Python AttributeError: the type name is part of the error text of a 500 answer
    /// ("AttributeError: ...") and the message is what a failed batch item reports.</summary>
    public sealed class AttributeError(string message) : Exception(message);

    /// <summary>Python IOError (open() of a file that does not exist).</summary>
    public sealed class IOError(string message) : Exception(message);

    /// <summary>type(v).__name__ as IronPython names request values; the class name for .NET objects.</summary>
    private static string PyTypeName(object? v) => v switch
    {
        null => "NoneType",
        string => "str",
        bool => "bool",
        long or int => "int",
        double or float => "float",
        Lst => "list",
        Dict => "dict",
        _ => v.GetType().Name,
    };

    /// <summary>"'X' object has no attribute 'name'": what Python raised where the port would hit a null
    /// reference or a failed cast (a missing level, a type of the wrong class, an item that is not an object).</summary>
    private static AttributeError NoAttr(object? obj, string attr) =>
        new($"'{PyTypeName(obj)}' object has no attribute '{attr}'");

    /// <summary>obj.attr on a value that may be None: the value, or Python's AttributeError.</summary>
    private static T NN<T>(T? obj, string attr) where T : class => obj ?? throw NoAttr(null, attr);

    /// <summary>A batch item as an object (item.get(...) on anything else is an AttributeError).</summary>
    private static Dict ItemDict(object? item) => item as Dict ?? throw NoAttr(item, "get");

    /// <summary>bool(item.get(key))</summary>
    private static bool T(Dict item, string key) => Py.Truthy(item.Get(key));

    /// <summary>repr() of a list of integers: "[1, 2, 3]".</summary>
    private static string IntListRepr(IEnumerable<long> ids) =>
        "[" + string.Join(", ", ids.Select(i => i.ToString(CultureInfo.InvariantCulture))) + "]";

    /// <summary>str.title(): first letter of every word upper case, the rest lower case.</summary>
    private static string Title(string s)
    {
        var sb = new StringBuilder(s.Length);
        var start = true;
        foreach (var ch in s)
        {
            if (char.IsLetter(ch))
            {
                sb.Append(start ? char.ToUpperInvariant(ch) : char.ToLowerInvariant(ch));
                start = false;
            }
            else
            {
                sb.Append(ch);
                start = true;
            }
        }
        return sb.ToString();
    }

    /// <summary>"{:.0f}".format(v)</summary>
    private static string F0(double v) => v.ToString("F0", CultureInfo.InvariantCulture);

    /// <summary>r.get("display", r.get("value"))</summary>
    private static object? DisplayOrValue(Dict r) => r.TryGetValue("display", out var d) ? d : r.Get("value");

    /// <summary>v in (None, "")</summary>
    private static bool IsBlank(object? v) => v == null || (v is string s && s.Length == 0);

    private static DB.XYZ Xyz((double x, double y, double z) p) => new(p.x, p.y, p.z);

    /// <summary>A request value that is used as a unit name (None stays None).</summary>
    private static string? UnitOf(object? v) => v == null ? null : Py.Str(v);

    // ---------------------------------------------------------------------- inspect
    private static Dict Describe(Ctx ctx, DB.Element e, List<string> fields, Lst paramNames)
    {
        var doc = ctx.Doc;
        var info = Core.ElementBrief(doc, e);
        if (fields.Contains("level"))
            info["level"] = Core.ElementLevel(doc, e);
        if (fields.Contains("location"))
            info["location"] = Core.ElementLocation(e, ctx.Unit);
        if (fields.Contains("bbox"))
            info["bbox"] = Core.ElementBbox(e, ctx.Unit);
        if (paramNames.Count > 0)
        {
            var vals = new Dict();
            foreach (var n in paramNames)
            {
                var (p, _) = ParamsUtil.Find(doc, e, n);
                if (p == null)
                {
                    vals[Py.Str(n)] = null;
                }
                else
                {
                    var r = ParamsUtil.Read(doc, p, ctx.Unit);
                    vals[Py.Str(n)] = DisplayOrValue(r);
                }
            }
            info["parameters"] = vals;
        }
        return info;
    }

    private static readonly string[] FindFilterKeys =
    {
        "element_ids", "selection", "categories", "class_name", "view",
        "level", "family", "type", "text", "param_filters", "name_contains",
    };

    public static Dict? FindElements(Ctx ctx)
    {
        var spec = Query.QuerySpec(ctx.Data);
        if (!FindFilterKeys.Any(k => Py.Truthy(spec.Get(k))))
            throw new RvtssError("Give at least one filter (categories, class_name, view, level, text, ...)",
                hint: "Broad unfiltered queries on large models are slow; start with get_revit_model_info.");
        var elements = Query.Collect(ctx, spec, maxScan: (int?)ctx.Int("max_scan", 200000));
        var counts = Query.CategoryCounts(elements);
        if (Py.Truthy(ctx.Get("count_only")))
            return new Dict { ["count"] = (long)elements.Count, ["category_counts"] = counts };
        var (page, meta) = Filters.Paginate(elements, ctx.Int("offset", 0, 0), ctx.Int("limit", 100, 1, Core.MaxLimit));
        var fields = ctx.List("fields").Select(f => f is string s ? s.ToLowerInvariant() : throw NoAttr(f, "lower")).ToList();
        var parameters = ctx.List("parameters");
        return new Dict
        {
            ["count"] = meta["total"],
            ["pagination"] = meta,
            ["unit"] = ctx.Unit,
            ["category_counts"] = counts,
            ["elements"] = page.Select(e => (object?)Describe(ctx, e, fields, parameters)).ToList(),
        };
    }

    private static IEnumerable<DB.Solid> WalkSolids(DB.GeometryElement g)
    {
        foreach (var obj in g)
        {
            if (obj is DB.Solid solid && solid.Volume > 0)
            {
                yield return solid;
            }
            else if (obj is DB.GeometryInstance gi)
            {
                foreach (var s in WalkSolids(gi.GetInstanceGeometry()))
                    yield return s;
            }
        }
    }

    private static Dict? GeometrySummary(DB.Element e, string unit)
    {
        var opt = new DB.Options { DetailLevel = DB.ViewDetailLevel.Fine };
        var geom = e.get_Geometry(opt);
        if (geom == null)
            return null;
        double vol = 0.0, area = 0.0;
        long solids = 0, faces = 0;
        foreach (var s in WalkSolids(geom))
        {
            solids += 1;
            vol += s.Volume;
            area += s.SurfaceArea;
            faces += s.Faces.Size;
        }
        return new Dict
        {
            ["solids"] = solids, ["faces"] = faces,
            ["volume"] = Units.FromInternal(vol, Units.LengthUnitFor("volume", unit), 4),
            ["surface_area"] = Units.FromInternal(area, Units.LengthUnitFor("area", unit), 4),
            ["volume_unit"] = Units.LengthUnitFor("volume", unit), ["area_unit"] = Units.LengthUnitFor("area", unit),
        };
    }

    public static Dict? ElementDetails(Ctx ctx)
    {
        var ids = ctx.List("element_ids");
        if (ids.Count == 0)
            throw new RvtssError("element_ids is required");
        if (ids.Count > 50)
            throw new RvtssError("At most 50 elements per call", hint: "Page through ids or use find_elements with parameters=[...].");
        var doc = ctx.Doc;
        var names = ctx.List("parameters");
        var wanted = names.Count > 0 ? names : null;
        var meta = ctx.Bool("include_parameter_meta", false);
        var result = new Lst();
        foreach (var e in Core.GetElements(doc, ids))
        {
            var d = Core.ElementBrief(doc, e);
            d["unique_id"] = e.UniqueId;
            d["class"] = e.GetType().Name;
            d["level"] = Core.ElementLevel(doc, e);
            d["location"] = Core.ElementLocation(e, ctx.Unit);
            d["bbox"] = Core.ElementBbox(e, ctx.Unit);
            d["pinned"] = e.Pinned;
            try
            {
                if (doc.IsWorkshared)
                    d["workset"] = Utils.NormalizeString(doc.GetWorksetTable().GetWorkset(e.WorksetId).Name);
            }
            catch { /* no workset */ }
            try
            {
                var pid = e.CreatedPhaseId;
                if (Compat.IsValidId(pid))
                    d["phase_created"] = Utils.NormalizeString(doc.GetElement(pid).Name);
            }
            catch { /* no phase */ }
            try
            {
                var pid = e.DemolishedPhaseId;
                if (Compat.IsValidId(pid))
                    d["phase_demolished"] = Utils.NormalizeString(doc.GetElement(pid).Name);
            }
            catch { /* no phase */ }
            try
            {
                if (e.DesignOption != null)
                    d["design_option"] = Utils.NormalizeString(e.DesignOption.Name);
            }
            catch { /* no design option */ }
            try
            {
                var v = e.GroupId;
                if (Compat.IsValidId(v))
                    d["group_id"] = Compat.IdInt(v);
            }
            catch { /* not in a group */ }
            try
            {
                var v = e.AssemblyInstanceId;
                if (Compat.IsValidId(v))
                    d["assembly_id"] = Compat.IdInt(v);
            }
            catch { /* not in an assembly */ }
            if (e is DB.FamilyInstance fi)
            {
                try
                {
                    d["host_id"] = fi.Host != null ? Compat.IdInt(fi.Host) : null;
                    d["super_component_id"] = fi.SuperComponent != null ? Compat.IdInt(fi.SuperComponent) : null;
                    d["sub_component_ids"] = fi.GetSubComponentIds().Select(i => (object?)Compat.IdInt(i)).ToList();
                    d["mirrored"] = fi.Mirrored;
                    d["hand_flipped"] = fi.HandFlipped;
                    d["facing_flipped"] = fi.FacingFlipped;
                }
                catch { /* keep what was read */ }
            }
            if (ctx.Bool("include_parameters", true))
                d["parameters"] = ParamsUtil.ReadAll(doc, e, ctx.Unit, wanted, meta);
            if (ctx.Bool("include_type_parameters", false))
            {
                var tid = e.GetTypeId();
                if (Compat.IsValidId(tid))
                    d["type_parameters"] = ParamsUtil.ReadAll(doc, doc.GetElement(tid), ctx.Unit, wanted, meta);
            }
            if (ctx.Bool("include_geometry", false))
            {
                try { d["geometry"] = GeometrySummary(e, ctx.Unit); }
                catch (Exception ex) { d["geometry"] = new Dict { ["error"] = ex.Message }; }
            }
            result.Add(d);
        }
        return new Dict { ["unit"] = ctx.Unit, ["elements"] = result };
    }

    public static Dict? Selection(Ctx ctx)
    {
        var action = ctx.Get("action", "get") as string;
        if (action == "get")
        {
            var ids = Query.SelectionIds(ctx);
            var doc = ctx.Doc;
            // ids[:None] is every id, and any number is greater than None in IronPython 2
            var limit = ctx.Int("limit", 200, 1, Core.MaxLimit);
            var els = (limit == null ? ids : ids.Take((int)limit.Value)).Select(i => doc.GetElement(i)).ToList();
            return new Dict
            {
                ["count"] = (long)ids.Count,
                ["category_counts"] = Query.CategoryCounts(ids.Select(i => doc.GetElement(i))),
                ["elements"] = els.Where(e => e != null).Select(e => (object?)Core.ElementBrief(doc, e)).ToList(),
                ["truncated"] = limit == null || ids.Count > limit.Value,
            };
        }
        if (action == "set" || action == "add" || action == "clear")
        {
            var uidoc = ctx.UiDoc;
            if (uidoc == null || !uidoc.Document.Equals(ctx.Doc))
                throw new RvtssError("Selection can only be changed in the active document", status: 409);
            var current = action == "add" ? uidoc.Selection.GetElementIds().ToList() : new List<DB.ElementId>();
            var newIds = action == "clear"
                ? new List<DB.ElementId>()
                : Core.GetElements(ctx.Doc, ctx.List("element_ids")).Select(e => e.Id).ToList();
            uidoc.Selection.SetElementIds(Core.ToIdList(current.Concat(newIds).ToList()));
            if (ctx.Bool("zoom", false) && newIds.Count > 0)
                uidoc.ShowElements(Core.ToIdList(newIds));
            return new Dict { ["selected_count"] = (long)(current.Count + newIds.Count) };
        }
        throw new RvtssError("action must be get, set, add or clear");
    }

    // ----------------------------------------------------------------------- params
    private static List<Dict> NormaliseUpdates(Ctx ctx)
    {
        var updates = ctx.List("updates");
        if (updates.Count == 0 && Py.Truthy(ctx.Get("element_ids")) && Py.Truthy(ctx.Get("parameter")))
        {
            foreach (var i in ctx.List("element_ids"))
                updates.Add(new Dict
                {
                    ["element_id"] = i, ["parameter"] = ctx.Get("parameter"),
                    ["value"] = ctx.Data.Get("value"), ["unit"] = ctx.Get("value_unit"),
                });
        }
        if (updates.Count == 0)
            throw new RvtssError("Provide 'updates': [{element_id, parameter, value, unit?}] "
                                 + "or element_ids + parameter + value");
        var result = new List<Dict>();
        foreach (var item in updates)
        {
            if (item is not Dict u || !u.ContainsKey("element_id") || !Py.Truthy(u.Get("parameter")) || !u.ContainsKey("value"))
                throw new RvtssError("Each update needs element_id, parameter and value").With("failed_item", item);
            result.Add(u);
        }
        return result;
    }

    /// <summary>Hashable form of a request value for set(): 1 and 1.0 are the same member, as in Python.</summary>
    private static object SetKey(object? v) => v switch
    {
        null => "\0None",
        bool b => b ? 1.0 : 0.0,
        long l => (double)l,
        int i => (double)i,
        _ => v,
    };

    public static Dict? SetParameters(Ctx ctx)
    {
        var doc = ctx.Doc;
        var updates = NormaliseUpdates(ctx);
        var distinct = new HashSet<object>(updates.Select(u => SetKey(u["element_id"]))).Count;
        var preview = Core.ConfirmGate(ctx, distinct, "set_parameters");
        var targetDefault = ctx.Get("target", "auto");
        var typeHits = new HashSet<long>();

        Dict? ApplyOne(object? item)
        {
            var u = (Dict)item!;
            var e = Core.GetElement(doc, u["element_id"]);
            var target = (u.TryGetValue("target", out var t) ? t : targetDefault) as string;
            var (p, owner) = ParamsUtil.Find(doc, e, u["parameter"], allowType: target != "instance");
            if (p == null)
                throw new RvtssError($"Parameter '{Py.Str(u["parameter"])}' not found on element {Py.Str(u["element_id"])}",
                    status: 404);
            if (target == "type" && owner != "type")
            {
                var typeElement = doc.GetElement(e.GetTypeId());
                p = typeElement != null ? ParamsUtil.Find(doc, typeElement, u["parameter"], allowType: false).p : null;
                owner = "type";
                if (p == null)
                    throw new RvtssError($"Type parameter '{Py.Str(u["parameter"])}' not found", status: 404);
            }
            if (owner == "type" && e is not DB.ElementType)
                typeHits.Add(Compat.IdInt(e.GetTypeId()));
            var before = ParamsUtil.Read(doc, p, "mm");
            var after = ParamsUtil.SetValue(doc, p, u["value"], UnitOf(u.Get("unit")));
            return new Dict
            {
                ["element_id"] = u["element_id"], ["parameter"] = after["name"], ["owner"] = owner,
                ["before"] = DisplayOrValue(before),
                ["after"] = DisplayOrValue(after),
            };
        }

        var atomic = ctx.Bool("atomic", true);
        var dry = preview || ctx.DryRun;
        var (results, failures) = Core.RunTransaction(doc, "Set parameters",
            () => Core.Batch(doc, updates, ApplyOne, atomic), dryRun: dry);
        var o = Core.CommitResult(new Dict
        {
            ["results"] = results,
            ["succeeded"] = (long)results.Count(r => Py.Truthy(((Dict)r!)["ok"])),
            ["failed"] = (long)results.Count(r => !Py.Truthy(((Dict)r!)["ok"])),
        }, failures, dry);
        if (typeHits.Count > 0)
            o["note"] = $"Type parameters were changed on {typeHits.Count} type(s); every instance of those types is affected.";
        return Core.PreviewStatus(o, preview);
    }

    /// <summary>Orders the keys of SortKey: one type per mode (integers, numbers, text by code unit,
    /// pairs of numbers).</summary>
    private sealed class KeyComparer : IComparer<object>
    {
        public static readonly KeyComparer Instance = new();

        public int Compare(object? a, object? b)
        {
            if (a is long la && b is long lb)
                return la.CompareTo(lb);
            if (a is double da && b is double db)
                return da.CompareTo(db);
            if (a is string sa && b is string sb)
                return string.CompareOrdinal(sa, sb);
            if (a is ValueTuple<double, double> ta && b is ValueTuple<double, double> tb)
                return ta.Item1 != tb.Item1 ? ta.Item1.CompareTo(tb.Item1) : ta.Item2.CompareTo(tb.Item2);
            return 0;
        }
    }

    private static Func<DB.Element, object> SortKey(DB.Document doc, object? mode)
    {
        if (mode == null)
            return e => Compat.IdInt(e);
        if (mode is string m)
        {
            if (m == "" || m == "id")
                return e => Compat.IdInt(e);
            if (m == "name")
                return e => Utils.NormalizeString(Utils.GetElementName(e) ?? "").ToLowerInvariant();
            if (m == "x" || m == "y" || m == "z" || m == "xy" || m == "yx")
            {
                return e =>
                {
                    var p = Core.ElementPoint(e);
                    if (p == null) // keys must have one type per mode (IronPython 3 cannot compare tuple/float)
                        return m == "xy" || m == "yx" ? (object)(0.0, 0.0) : 0.0;
                    if (m == "xy")
                        return (Py.Round(p.X, 3), Py.Round(p.Y, 3));
                    if (m == "yx")
                        return (Py.Round(-p.Y, 3), Py.Round(p.X, 3));
                    return m == "x" ? p.X : m == "y" ? p.Y : p.Z;
                };
            }
            if (m.StartsWith("param:", StringComparison.Ordinal))
            {
                var name = m.Substring(6);
                return e =>
                {
                    var (p, _) = ParamsUtil.Find(doc, e, name);
                    if (p == null)
                        return "";
                    var v = p.AsValueString();
                    if (string.IsNullOrEmpty(v))
                        v = p.AsString();
                    if (string.IsNullOrEmpty(v))
                        v = "";
                    return Utils.NormalizeString(v).ToLowerInvariant();
                };
            }
        }
        throw new RvtssError("sort_by must be id, name, x, y, z, xy, yx or param:<name>");
    }

    private static Func<string, object?> TemplateResolver(DB.Document doc, DB.Element e, string unit)
    {
        return name =>
        {
            var low = name.ToLowerInvariant();
            if (low == "level")
                return Core.ElementLevel(doc, e);
            var b = Core.ElementBrief(doc, e);
            if (low == "category" || low == "family" || low == "type" || low == "name")
                return b.Get(low);
            var (p, _) = ParamsUtil.Find(doc, e, name);
            if (p == null)
                return null;
            var r = ParamsUtil.Read(doc, p, unit);
            var v = DisplayOrValue(r);
            return IsBlank(v) ? null : v;
        };
    }

    public static Dict? BulkUpdateParameter(Ctx ctx)
    {
        var doc = ctx.Doc;
        var pnameValue = ctx.Require("parameter");
        var pname = Py.Str(pnameValue);
        var template = ctx.Get("template");
        var hasValue = ctx.Data.ContainsKey("value");
        if (!Py.Truthy(template) && !hasValue)
            throw new RvtssError("Provide either 'value' or 'template' (e.g. 'D-{Level}-{n:03}')");
        var spec = Query.QuerySpec(ctx.Data);
        var elements = spec.Count > 0 ? Query.Collect(ctx, spec) : new List<DB.Element>();
        if (elements.Count == 0)
            throw new RvtssError("No elements matched", status: 404,
                hint: "Pass element_ids, selection=true or filter keys (categories, level, ...).");
        // list.sort(key=...) is stable, as OrderBy is
        elements = elements.OrderBy(SortKey(doc, ctx.Get("sort_by")), KeyComparer.Instance).ToList();
        var start = ctx.Int("start", 1);
        var step = ctx.Int("step", 1);
        var onlyEmpty = ctx.Bool("only_empty", false);
        var preview = Core.ConfirmGate(ctx, elements.Count, "bulk_update_parameter");
        var counter = start;

        Dict? ApplyOne(object? item)
        {
            var e = (DB.Element)item!;
            var (p, _) = ParamsUtil.Find(doc, e, pnameValue, allowType: ctx.Bool("allow_type", false));
            if (p == null)
                throw new RvtssError($"Parameter '{pname}' not found on element {Compat.IdInt(e)}", status: 404);
            var current = ParamsUtil.Read(doc, p, ctx.Unit);
            var curVal = DisplayOrValue(current);
            if (onlyEmpty && !IsBlank(curVal))
                return new Dict { ["element_id"] = Compat.IdInt(e), ["skipped"] = "already has a value", ["value"] = curVal };
            object? newVal;
            if (Py.Truthy(template))
            {
                try
                {
                    newVal = Textfmt.Render(Py.Str(template), TemplateResolver(doc, e, ctx.Unit), n: counter,
                        elementId: Compat.IdInt(e), current: curVal);
                }
                catch (TemplateError te)
                {
                    throw new RvtssError(te.Message);
                }
                counter += step;
            }
            else
            {
                newVal = ctx.Data.Get("value");
            }
            var after = ParamsUtil.SetValue(doc, p, newVal, UnitOf(ctx.Get("value_unit")));
            return new Dict { ["element_id"] = Compat.IdInt(e), ["before"] = curVal, ["after"] = DisplayOrValue(after) };
        }

        var dry = preview || ctx.DryRun;
        var (results, failures) = Core.RunTransaction(doc, "Bulk update " + pname,
            () => Core.Batch(doc, elements.Cast<object?>(), ApplyOne, ctx.Bool("atomic", true)), dryRun: dry);
        var maxResults = ctx.Int("max_results", 200);
        var o = Core.CommitResult(new Dict
        {
            ["parameter"] = pnameValue, ["matched"] = (long)elements.Count,
            // results[:None] is the whole list, and any number is greater than None in IronPython 2
            ["results"] = maxResults == null ? results : results.Take(PureText.SliceEnd(results.Count, maxResults.Value)).ToList(),
            ["results_truncated"] = maxResults == null || results.Count > maxResults.Value,
        }, failures, dry);
        return Core.PreviewStatus(o, preview);
    }
}
