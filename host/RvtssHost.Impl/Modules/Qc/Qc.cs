using System.Diagnostics;
using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// BIM coordination and quality control (RVTSS): port of revit_mcp/qc.py. This file holds the routes and
/// the model checks; the clash geometry is in QcClash.cs and snapshots / compare in QcSnapshot.cs.
///
/// Routes:
///     POST /qc/model_checks/  configurable checks -> findings with severity, ids and recommendations
///     POST /qc/clashes/       hard clashes between two element sets (optionally against a Revit link)
///     POST /qc/snapshot/      create / list model snapshots (JSON files) for change detection
///     POST /qc/compare/       compare snapshots (or a snapshot with the live model), or match two
///                             element sets by location (design model vs shop/fabrication model)
///
/// Rules come from the request and from %APPDATA%/RVTSS/qc_rules.json (see Pure/Rules.cs).
/// </summary>
public static partial class Qc
{
    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    public static readonly string[] AllChecks =
    {
        "warnings", "duplicates", "naming", "similar_family_names", "duplicate_types", "unused_families",
        "in_place_families", "cad_imports", "links", "rooms", "views_not_on_sheets", "sheets",
        "required_parameters", "groups", "iso19650", "view_audit",
    };

    public static void Register(RouteTable api)
    {
        api.Post("/qc/model_checks/", ModelChecks, "model_checks");
        api.Post("/qc/clashes/", Clashes, "clashes");
        api.Post("/qc/snapshot/", Snapshot, "snapshot");
        api.Post("/qc/compare/", Compare, "compare");
    }

    private delegate List<Dict> CheckFn(Ctx ctx, DB.Document doc, Dict rules);

    private static readonly Dictionary<string, CheckFn> Checks = new(StringComparer.Ordinal)
    {
        ["warnings"] = CheckWarnings,
        ["duplicates"] = CheckDuplicates,
        ["naming"] = CheckNaming,
        ["similar_family_names"] = CheckSimilarFamilies,
        ["duplicate_types"] = CheckDuplicateTypes,
        ["unused_families"] = CheckUnusedFamilies,
        ["in_place_families"] = CheckInPlace,
        ["cad_imports"] = CheckCad,
        ["links"] = CheckLinks,
        ["rooms"] = CheckRooms,
        ["views_not_on_sheets"] = CheckViews,
        ["sheets"] = CheckSheets,
        ["required_parameters"] = CheckRequired,
        ["groups"] = CheckGroups,
        ["iso19650"] = CheckIso19650,
        ["view_audit"] = CheckViewAudit,
    };

    /// <summary>Python's AttributeError: its type name is part of the 500 error text ("AttributeError: 'list' object has no
    /// attribute 'items'").</summary>
    internal sealed class AttributeError : Exception
    {
        public AttributeError(string message) : base(message) { }
    }

    /// <summary>type(v).__name__ for a request value.</summary>
    internal static string PyType(object? v) => v switch
    {
        null => "NoneType",
        Dict => "dict",
        Lst => "list",
        System.Collections.IList => "list",
        string => "unicode",
        bool => "bool",
        long or int => "int",
        double => "float",
        _ => v.GetType().Name,
    };

    /// <summary>A value that must be a JSON object (`record.get(...)` raised AttributeError in Python).</summary>
    internal static Dict Obj(object? v, string attribute = "get") =>
        v as Dict ?? throw new AttributeError("'" + PyType(v) + "' object has no attribute '" + attribute + "'");

    private static Dict Rules(Ctx ctx)
    {
        var (rules, error) = Core.LoadQcRules();
        if (!string.IsNullOrEmpty(error))
            ctx.Warn(error!);
        var over = ctx.Get("rules");
        if (Py.Truthy(over))
        {
            if (over is not Dict overrides)
                throw new AttributeError("'" + PyType(over) + "' object has no attribute 'items'");
            foreach (var kv in overrides)
                rules[kv.Key] = kv.Value;
        }
        return rules;
    }

    // ------------------------------------------------------------------ small helpers
    private static string D6(double v) => (v + 0.0).ToString("R", Inv);

    /// <summary>`p.AsString() or p.AsValueString()` is a non-empty text.</summary>
    private static bool HasText(DB.Parameter p)
    {
        if (!string.IsNullOrEmpty(p.AsString()))
            return true;
        return !string.IsNullOrEmpty(p.AsValueString());
    }

    private static List<Dict> One(Dict finding) => new() { finding };

    // ------------------------------------------------------------------ checks
    private static readonly string[] SeriousWarnings =
    {
        "identical instances", "overlap", "cannot be", "not enclosed", "duplicate", "inaccurate", "joined",
        "highlighted walls overlap", "room separation",
    };

    private static List<Dict> CheckWarnings(Ctx ctx, DB.Document doc, Dict rules)
    {
        var groups = new Dictionary<string, List<long>>(StringComparer.Ordinal);
        var order = new List<string>();
        foreach (var w in doc.GetWarnings())
        {
            var t = Utils.NormalizeString(w.GetDescriptionText());
            if (!groups.TryGetValue(t, out var ids))
            {
                groups[t] = ids = new List<long>();
                order.Add(t);
            }
            foreach (var i in w.GetFailingElements())
                ids.Add(i.Value);
        }
        var res = new List<Dict>();
        // sorted() is stable: equal counts keep the order the warnings were first seen
        foreach (var t in order.OrderBy(k => -groups[k].Count))
        {
            var low = t.ToLowerInvariant();
            var sev = low.Contains("identical instances") ? "error"
                : SeriousWarnings.Any(s => low.Contains(s)) ? "warning" : "info";
            res.Add(Pure.Rules.Finding("warnings", sev, t, groups[t],
                recommendation: "Resolve in Revit (Manage > Warnings) or with the affected element ids."));
        }
        return res;
    }

    private static int CompareTuple((double, double, double) a, (double, double, double) b)
    {
        var c = a.Item1.CompareTo(b.Item1);
        if (c != 0) return c;
        c = a.Item2.CompareTo(b.Item2);
        return c != 0 ? c : a.Item3.CompareTo(b.Item3);
    }

    private static List<Dict> CheckDuplicates(Ctx ctx, DB.Document doc, Dict rules)
    {
        var tol = Pure.Units.ToInternal(ctx.F("duplicate_tolerance", 1.0), ctx.Unit);
        var buckets = new Dictionary<string, List<long>>(StringComparer.Ordinal);
        var order = new List<string>();

        void Add(string key, long id)
        {
            if (!buckets.TryGetValue(key, out var list))
            {
                buckets[key] = list = new List<long>();
                order.Add(key);
            }
            list.Add(id);
        }

        foreach (DB.FamilyInstance fi in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilyInstance)))
        {
            if (fi.Location is not DB.LocationPoint loc)
                continue;
            var p = loc.Point;
            if (tol == 0.0)
                throw new DivideByZeroException(); // Python: float division by zero (text "Attempted to divide by zero.")
            var lid = fi.LevelId;
            Add(string.Concat("i|", fi.GetTypeId().Value.ToString(Inv), "|", D6(Py.Round(p.X / tol)), "|",
                D6(Py.Round(p.Y / tol)), "|", D6(Py.Round(p.Z / tol)), "|", D6(Py.Round(loc.Rotation, 3)), "|",
                Compat.IsValidId(lid) ? lid.Value.ToString(Inv) : "-"), fi.Id.Value);
        }
        foreach (DB.Wall w in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Wall)))
        {
            var c = (w.Location as DB.LocationCurve)?.Curve;
            if (c == null)
                continue;
            var a = c.GetEndPoint(0);
            var b = c.GetEndPoint(1);
            if (tol == 0.0)
                throw new DivideByZeroException();
            var pa = (Py.Round(a.X / tol) + 0.0, Py.Round(a.Y / tol) + 0.0, Py.Round(a.Z / tol) + 0.0);
            var pb = (Py.Round(b.X / tol) + 0.0, Py.Round(b.Y / tol) + 0.0, Py.Round(b.Z / tol) + 0.0);
            if (CompareTuple(pa, pb) > 0)
                (pa, pb) = (pb, pa);
            Add(string.Concat("w|", w.GetTypeId().Value.ToString(Inv), "|", D6(pa.Item1), "|", D6(pa.Item2), "|", D6(pa.Item3),
                "|", D6(pb.Item1), "|", D6(pb.Item2), "|", D6(pb.Item3)), w.Id.Value);
        }
        var dups = order.Select(k => buckets[k]).Where(ids => ids.Count > 1).ToList();
        if (dups.Count == 0)
            return new List<Dict>();
        var extras = new Lst();
        foreach (var d in dups)
            foreach (var id in d.Skip(1))
                extras.Add(id);
        var sets = new Lst();
        foreach (var d in dups.Take(50))
            sets.Add(d.Cast<object?>().ToList());
        return One(Pure.Rules.Finding("duplicates", "error",
            $"{dups.Count} set(s) of duplicate elements at the same location ({dups.Sum(d => d.Count)} elements)", extras,
            recommendation: "Delete the extra copies (element_ids lists all but the first of each set).",
            extra: new Dict { ["sets"] = sets }));
    }

    private static List<Dict> CheckNaming(Ctx ctx, DB.Document doc, Dict rules)
    {
        var naming = Py.Truthy(rules.Get("naming")) ? rules.Get("naming") as Dict ?? new Dict() : new Dict();
        var res = new List<Dict>();
        if (naming.Count == 0)
            return res;
        if (naming.ContainsKey("views"))
        {
            var items = new List<(long id, string? name)>();
            foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
            {
                if (v.IsTemplate)
                    continue;
                var vt = v.ViewType;
                if (vt == DB.ViewType.Internal || vt == DB.ViewType.ProjectBrowser || vt == DB.ViewType.SystemBrowser
                    || vt == DB.ViewType.DrawingSheet)
                    continue;
                items.Add((v.Id.Value, Utils.NormalizeString(v.Name)));
            }
            res.AddRange(Pure.Rules.CheckNames(items, Obj(naming["views"]), "naming", "views"));
        }
        if (naming.ContainsKey("sheets"))
        {
            var rule = Obj(naming["sheets"]);
            var number = PyX.Eq(rule.Get("field", "number"), "number");
            var items = new List<(long id, string? name)>();
            foreach (DB.ViewSheet s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
                items.Add((s.Id.Value, Utils.NormalizeString(number ? s.SheetNumber : s.Name)));
            res.AddRange(Pure.Rules.CheckNames(items, rule, "naming", "sheets"));
        }
        if (naming.ContainsKey("levels"))
        {
            var items = new List<(long id, string? name)>();
            foreach (DB.Level l in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Level)))
                items.Add((l.Id.Value, Utils.NormalizeString(l.Name)));
            res.AddRange(Pure.Rules.CheckNames(items, Obj(naming["levels"]), "naming", "levels"));
        }
        if (naming.ContainsKey("families"))
        {
            var items = new List<(long id, string? name)>();
            foreach (DB.Family f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
                if (f.IsEditable)
                    items.Add((f.Id.Value, Utils.NormalizeString(f.Name)));
            res.AddRange(Pure.Rules.CheckNames(items, Obj(naming["families"]), "naming", "families"));
        }
        if (naming.ContainsKey("types"))
        {
            var items = new List<(long id, string? name)>();
            foreach (DB.FamilySymbol t in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)))
                items.Add((t.Id.Value, Utils.NormalizeString(Utils.GetElementName(t))));
            res.AddRange(Pure.Rules.CheckNames(items, Obj(naming["types"]), "naming", "family types"));
        }
        var sheetNames = new List<(long id, string? name)>();
        foreach (DB.ViewSheet v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
            sheetNames.Add((v.Id.Value, Utils.NormalizeString(v.Name)));
        res.AddRange(Pure.Rules.CheckDuplicateNames(sheetNames, "naming", "sheet"));
        return res;
    }

    private static List<Dict> CheckSimilarFamilies(Ctx ctx, DB.Document doc, Dict rules)
    {
        // the O(n^2) comparison is capped at 600 families
        var fams = new List<(long id, string name)>();
        foreach (DB.Family f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
        {
            if (!f.IsEditable)
                continue;
            fams.Add((f.Id.Value, Utils.NormalizeString(f.Name)));
            if (fams.Count >= 600)
                break;
        }
        var pairs = Pure.Rules.SimilarNames(fams.Select(f => (string?)f.name));
        if (pairs.Count == 0)
            return new List<Dict>();
        var byName = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var (i, n) in fams)
            byName[n] = i;
        var ids = new Lst();
        foreach (var (a, _) in pairs)
            ids.Add(byName[a]);
        foreach (var (_, b) in pairs)
            ids.Add(byName[b]);
        return One(Pure.Rules.Finding("similar_family_names", "warning", $"{pairs.Count} pair(s) of near-duplicate family names",
            ids, recommendation: "Merge duplicated families (Revit: reload one over the other) and purge.",
            extra: new Dict { ["pairs"] = pairs.Take(30).Select(p => (object?)new Lst { p.Item1, p.Item2 }).ToList() }));
    }

    private static readonly HashSet<string> TypeSignatureSkip = new(StringComparer.Ordinal)
    {
        "Type Name", "Type Mark", "Type Comments", "Description", "Keynote", "Assembly Code", "URL", "Cost", "Model",
        "Manufacturer",
    };

    private static List<Dict> CheckDuplicateTypes(Ctx ctx, DB.Document doc, Dict rules)
    {
        var byFamily = new Dictionary<long, List<DB.FamilySymbol>>();
        var famOrder = new List<long>();
        foreach (DB.FamilySymbol s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)))
        {
            try
            {
                var fid = s.Family.Id.Value;
                if (!byFamily.TryGetValue(fid, out var list))
                {
                    byFamily[fid] = list = new List<DB.FamilySymbol>();
                    famOrder.Add(fid);
                }
                list.Add(s);
            }
            catch { continue; }
        }
        var dups = new List<List<(long id, string family, string type)>>();
        foreach (var fid in famOrder)
        {
            var syms = byFamily[fid];
            if (syms.Count < 2 || syms.Count > 200)
                continue;
            // the md5 of the sorted values only served as a grouping key: the joined text groups the same way
            var sig = new Dictionary<string, List<DB.FamilySymbol>>(StringComparer.Ordinal);
            var sigOrder = new List<string>();
            foreach (var s in syms)
            {
                var vals = new List<string>();
                foreach (DB.Parameter p in s.Parameters)
                {
                    try
                    {
                        var name = p.Definition.Name;
                        if (TypeSignatureSkip.Contains(name))
                            continue;
                        var text = p.AsValueString();
                        if (string.IsNullOrEmpty(text))
                            text = p.AsString();
                        vals.Add(name + "=" + (string.IsNullOrEmpty(text) ? "" : text));
                    }
                    catch { continue; }
                }
                vals.Sort(StringComparer.Ordinal);
                var key = string.Join("|", vals);
                if (!sig.TryGetValue(key, out var group))
                {
                    sig[key] = group = new List<DB.FamilySymbol>();
                    sigOrder.Add(key);
                }
                group.Add(s);
            }
            foreach (var key in sigOrder)
            {
                var group = sig[key];
                if (group.Count > 1)
                    dups.Add(group.Select(s => (s.Id.Value, Utils.NormalizeString(s.Family.Name),
                        Utils.NormalizeString(Utils.GetElementName(s)))).ToList());
            }
        }
        if (dups.Count == 0)
            return new List<Dict>();
        var ids = new Lst();
        foreach (var g in dups)
            foreach (var d in g.Skip(1))
                ids.Add(d.id);
        var groups = dups.Take(30).Select(g => (object?)g.Select(x => (object?)(x.family + " : " + x.type)).ToList()).ToList();
        return One(Pure.Rules.Finding("duplicate_types", "warning", $"{dups.Count} group(s) of family types with identical values",
            ids, recommendation: "Swap instances to one type (manage_element_types change_type) and delete the duplicates.",
            extra: new Dict { ["groups"] = groups }));
    }

    private static List<Dict> CheckUnusedFamilies(Ctx ctx, DB.Document doc, Dict rules)
    {
        var used = new HashSet<long>();
        var familyOfSymbol = new Dictionary<long, long?>();
        foreach (DB.FamilyInstance fi in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilyInstance)))
        {
            try
            {
                // fi.Symbol.Family.Id, looked up once per symbol
                var sid = fi.GetTypeId().Value;
                if (!familyOfSymbol.TryGetValue(sid, out var fid))
                {
                    fid = (doc.GetElement(fi.GetTypeId()) as DB.FamilySymbol)?.Family.Id.Value;
                    familyOfSymbol[sid] = fid;
                }
                if (fid != null)
                    used.Add(fid.Value);
            }
            catch { continue; }
        }
        var unused = new List<DB.Family>();
        foreach (DB.Family f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
        {
            if (f.IsEditable && !used.Contains(f.Id.Value) && f.FamilyCategory != null
                && f.FamilyCategory.CategoryType == DB.CategoryType.Model)
                unused.Add(f);
        }
        if (unused.Count == 0)
            return new List<Dict>();
        return One(Pure.Rules.Finding("unused_families", "info", $"{unused.Count} model families have no placed instances",
            unused.Select(f => f.Id.Value).ToList(),
            recommendation: "Purge unused families (Manage > Purge Unused) to reduce file size.",
            extra: new Dict { ["examples"] = unused.Take(15).Select(f => (object?)Utils.NormalizeString(f.Name)).ToList() }));
    }

    private static List<Dict> CheckInPlace(Ctx ctx, DB.Document doc, Dict rules)
    {
        var fams = new List<DB.Family>();
        foreach (DB.Family f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
            if (f.IsInPlace)
                fams.Add(f);
        if (fams.Count == 0)
            return new List<Dict>();
        return One(Pure.Rules.Finding("in_place_families", "warning", $"{fams.Count} in-place families",
            fams.Select(f => f.Id.Value).ToList(),
            recommendation: "Replace in-place families with loadable families where they repeat.",
            extra: new Dict { ["examples"] = fams.Take(15).Select(f => (object?)Utils.NormalizeString(f.Name)).ToList() }));
    }

    private static List<Dict> CheckCad(Ctx ctx, DB.Document doc, Dict rules)
    {
        var imported = new List<DB.ImportInstance>();
        foreach (DB.ImportInstance i in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ImportInstance)))
            if (!i.IsLinked)
                imported.Add(i);
        if (imported.Count == 0)
            return new List<Dict>();
        return One(Pure.Rules.Finding("cad_imports", "warning", $"{imported.Count} imported (not linked) CAD files",
            imported.Select(i => i.Id.Value).ToList(),
            recommendation: "Link CAD instead of importing; delete imports that are no longer needed."));
    }

    private static List<Dict> CheckLinks(Ctx ctx, DB.Document doc, Dict rules)
    {
        var res = new List<Dict>();
        var unloaded = new List<DB.RevitLinkInstance>();
        foreach (DB.RevitLinkInstance i in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkInstance)))
            if (i.GetLinkDocument() == null)
                unloaded.Add(i);
        if (unloaded.Count > 0)
            res.Add(Pure.Rules.Finding("links", "error", $"{unloaded.Count} Revit link(s) not loaded",
                unloaded.Select(i => i.Id.Value).ToList(),
                recommendation: "Reload or remove the links (Manage Links).",
                extra: new Dict { ["examples"] = unloaded.Select(i => (object?)Utils.NormalizeString(i.Name)).ToList() }));
        var unpinned = new List<DB.RevitLinkInstance>();
        foreach (DB.RevitLinkInstance i in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkInstance)))
            if (!i.Pinned)
                unpinned.Add(i);
        if (unpinned.Count > 0)
            res.Add(Pure.Rules.Finding("links", "warning", $"{unpinned.Count} Revit link(s) are not pinned",
                unpinned.Select(i => i.Id.Value).ToList(), recommendation: "Pin links to prevent accidental moves."));
        return res;
    }

    private static List<Dict> CheckRooms(Ctx ctx, DB.Document doc, Dict rules)
    {
        var unplaced = new List<long>();
        var unbounded = new List<long>();
        foreach (var r in new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType())
        {
            if (r.Location == null)
                unplaced.Add(r.Id.Value);
            else if (((DB.SpatialElement)r).Area <= 0)
                unbounded.Add(r.Id.Value);
        }
        var res = new List<Dict>();
        if (unplaced.Count > 0)
            res.Add(Pure.Rules.Finding("rooms", "warning", $"{unplaced.Count} unplaced rooms", unplaced,
                recommendation: "Place or delete unplaced rooms."));
        if (unbounded.Count > 0)
            res.Add(Pure.Rules.Finding("rooms", "error", $"{unbounded.Count} rooms are not enclosed / redundant", unbounded,
                recommendation: "Fix room boundaries or delete redundant rooms."));
        return res;
    }

    private static HashSet<long> PlacedViewIds(DB.Document doc)
    {
        var placed = new HashSet<long>();
        foreach (DB.Viewport vp in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Viewport)))
            placed.Add(vp.ViewId.Value);
        foreach (DB.ScheduleSheetInstance s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ScheduleSheetInstance)))
            placed.Add(s.ScheduleId.Value);
        return placed;
    }

    private static List<Dict> CheckViews(Ctx ctx, DB.Document doc, Dict rules)
    {
        var placed = PlacedViewIds(doc);
        var unplaced = new List<DB.View>();
        foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
        {
            if (v.IsTemplate || placed.Contains(v.Id.Value))
                continue;
            var vt = v.ViewType;
            if (vt == DB.ViewType.FloorPlan || vt == DB.ViewType.CeilingPlan || vt == DB.ViewType.Section
                || vt == DB.ViewType.Elevation || vt == DB.ViewType.DraftingView || vt == DB.ViewType.Detail
                || vt == DB.ViewType.EngineeringPlan || vt == DB.ViewType.AreaPlan)
                unplaced.Add(v);
        }
        if (unplaced.Count == 0)
            return new List<Dict>();
        return One(Pure.Rules.Finding("views_not_on_sheets", "info", $"{unplaced.Count} views are not placed on any sheet",
            unplaced.Select(v => v.Id.Value).ToList(),
            recommendation: "Place them on sheets or delete working views before issue.",
            extra: new Dict { ["examples"] = unplaced.Take(15).Select(v => (object?)Utils.NormalizeString(v.Name)).ToList() }));
    }

    private static List<Dict> CheckSheets(Ctx ctx, DB.Document doc, Dict rules)
    {
        var res = new List<Dict>();
        var sheets = new List<DB.ViewSheet>();
        foreach (DB.ViewSheet s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
            if (!s.IsPlaceholder)
                sheets.Add(s);
        var empty = sheets.Where(s => s.GetAllPlacedViews().Count == 0).Select(s => s.Id.Value).ToList();
        if (empty.Count > 0)
            res.Add(Pure.Rules.Finding("sheets", "warning", $"{empty.Count} sheets have no views", empty,
                recommendation: "Place views or delete the empty sheets."));
        var tbOwner = new HashSet<long>();
        foreach (var t in new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType())
            tbOwner.Add(t.OwnerViewId.Value);
        var noTb = sheets.Where(s => !tbOwner.Contains(s.Id.Value)).Select(s => s.Id.Value).ToList();
        if (noTb.Count > 0)
            res.Add(Pure.Rules.Finding("sheets", "warning", $"{noTb.Count} sheets have no title block", noTb));
        var required = ctx.List("sheet_parameters");
        if (required.Count == 0)
            required = Py.Truthy(rules.Get("sheet_parameters")) ? Py.ListOf(rules.Get("sheet_parameters")) : new Lst();
        foreach (var pname in required)
        {
            var missing = new List<long>();
            foreach (var s in sheets)
            {
                var (p, _) = ParamsUtil.Find(doc, s, pname, allowType: false);
                if (p == null || !HasText(p))
                    missing.Add(s.Id.Value);
            }
            if (missing.Count > 0)
                res.Add(Pure.Rules.Finding("sheets", "warning", $"'{Py.Str(pname)}' is empty on {missing.Count} sheets", missing,
                    recommendation: "Fill sheet parameters with bulk_update_parameter (class_name='ViewSheet')."));
        }
        return res;
    }

    private static List<Dict> CheckRequired(Ctx ctx, DB.Document doc, Dict rules)
    {
        var res = new List<Dict>();
        foreach (var ruleObj in PyX.Items(rules.Get("required_parameters")))
        {
            var rule = Obj(ruleObj);
            foreach (var cat in PyX.Items(rule.Get("categories", new Lst())))
            {
                DB.Category c;
                try
                {
                    c = Core.ResolveCategory(doc, cat);
                }
                catch (RvtssError)
                {
                    res.Add(Pure.Rules.Finding("required_parameters", "warning", $"Rule category '{Py.Str(cat)}' not found"));
                    continue;
                }
                var elems = new DB.FilteredElementCollector(doc).OfCategoryId(c.Id).WhereElementIsNotElementType().ToElements();
                foreach (var pname in PyX.Items(rule.Get("parameters", new Lst())))
                {
                    var missing = new List<long>();
                    var empty = new List<long>();
                    foreach (var e in elems)
                    {
                        var (p, _) = ParamsUtil.Find(doc, e, pname);
                        if (p == null)
                            missing.Add(e.Id.Value);
                        else if (!HasText(p))
                            empty.Add(e.Id.Value);
                    }
                    if (missing.Count > 0)
                        res.Add(Pure.Rules.Finding("required_parameters", rule.Get("severity", "error"),
                            $"{c.Name}: '{Py.Str(pname)}' missing on {missing.Count} elements", missing,
                            recommendation: "Bind the parameter (shared_parameters bind) or update families."));
                    if (empty.Count > 0)
                        res.Add(Pure.Rules.Finding("required_parameters", "warning",
                            $"{c.Name}: '{Py.Str(pname)}' empty on {empty.Count} elements", empty));
                }
            }
        }
        return res;
    }

    private static List<Dict> CheckGroups(Ctx ctx, DB.Document doc, Dict rules)
    {
        var used = new HashSet<long>();
        foreach (DB.Group g in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Group)))
            used.Add(g.GroupType.Id.Value);
        var unused = new List<DB.GroupType>();
        foreach (DB.GroupType t in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.GroupType)))
            if (!used.Contains(t.Id.Value))
                unused.Add(t);
        if (unused.Count == 0)
            return new List<Dict>();
        return One(Pure.Rules.Finding("groups", "info", $"{unused.Count} group types are unused",
            unused.Select(t => t.Id.Value).ToList(),
            recommendation: "Purge unused groups.",
            extra: new Dict { ["examples"] = unused.Take(15).Select(t => (object?)Utils.NormalizeString(t.Name)).ToList() }));
    }

    private static readonly string[] NonViews = { "Internal", "ProjectBrowser", "SystemBrowser", "Undefined", "DrawingSheet" };

    /// <summary>view types that are printed / placed on sheets (template and placement checks)</summary>
    private static readonly string[] Printable =
    {
        "FloorPlan", "CeilingPlan", "Section", "Elevation", "DraftingView", "Detail", "EngineeringPlan",
        "AreaPlan", "ThreeD", "Legend", "Schedule",
    };

    /// <summary>view types expected to carry a view template (configurable: view_audit.template_view_types)</summary>
    private static readonly string[] TemplateTypes =
    {
        "FloorPlan", "CeilingPlan", "Section", "Elevation", "ThreeD", "AreaPlan", "EngineeringPlan",
    };

    private static List<DB.View> Views(DB.Document doc)
    {
        var res = new List<DB.View>();
        foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
            if (Array.IndexOf(NonViews, v.ViewType.ToString()) < 0)
                res.Add(v);
        return res;
    }

    private static List<Dict> CheckIso19650(Ctx ctx, DB.Document doc, Dict rules)
    {
        var scheme = Py.Truthy(rules.Get("iso19650")) ? Obj(rules.Get("iso19650")) : new Dict();
        if (!Py.Truthy(scheme.Get("targets")))
            return One(Pure.Rules.Finding("iso19650", "info", "No iso19650 naming scheme configured",
                recommendation: "Add an 'iso19650' section to qc_rules.json "
                                + "(see docs/examples/qc_rules.iso19650.json) or pass rules={iso19650: ...}."));
        var targets = Obj(scheme["targets"]);
        var res = new List<Dict>();
        try
        {
            if (targets.ContainsKey("sheets"))
            {
                var src = Obj(targets["sheets"]).Get("source", "number");
                var number = PyX.Eq(src, "number");
                var items = new List<(long id, string? name)>();
                foreach (DB.ViewSheet s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
                    if (!s.IsPlaceholder)
                        items.Add((s.Id.Value, Utils.NormalizeString(number ? s.SheetNumber : s.Name)));
                res.AddRange(Pure.Naming.CheckItems(items, scheme, "sheets"));
            }
            var views = Views(doc);
            if (targets.ContainsKey("views"))
                res.AddRange(Pure.Naming.CheckItems(
                    views.Where(v => !v.IsTemplate).Select(v => (v.Id.Value, (string?)Utils.NormalizeString(v.Name))).ToList(),
                    scheme, "views"));
            if (targets.ContainsKey("view_templates"))
                res.AddRange(Pure.Naming.CheckItems(
                    views.Where(v => v.IsTemplate).Select(v => (v.Id.Value, (string?)Utils.NormalizeString(v.Name))).ToList(),
                    scheme, "view_templates"));
            if (targets.ContainsKey("families"))
            {
                var items = new List<(long id, string? name)>();
                foreach (DB.Family f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
                    if (f.IsEditable)
                        items.Add((f.Id.Value, Utils.NormalizeString(f.Name)));
                res.AddRange(Pure.Naming.CheckItems(items, scheme, "families"));
            }
            if (targets.ContainsKey("types"))
            {
                var items = new List<(long id, string? name)>();
                foreach (DB.FamilySymbol t in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)))
                    items.Add((t.Id.Value, Utils.NormalizeString(Utils.GetElementName(t))));
                res.AddRange(Pure.Naming.CheckItems(items, scheme, "types"));
            }
            if (targets.ContainsKey("worksets"))
            {
                if (doc.IsWorkshared)
                {
                    var items = new List<(long id, string? name)>();
                    foreach (var w in new DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))
                        items.Add((w.Id.IntegerValue, Utils.NormalizeString(w.Name)));
                    res.AddRange(Pure.Naming.CheckItems(items, scheme, "worksets"));
                }
                else
                {
                    res.Add(Pure.Rules.Finding("iso19650", "info", "Worksets not checked: the model is not workshared"));
                }
            }
        }
        catch (SchemeError e)
        {
            return One(Pure.Rules.Finding("iso19650", "error", e.Message,
                recommendation: "Fix the iso19650 section of qc_rules.json"));
        }
        return res;
    }

    private static DB.BuiltInParameter? Bip(string name) => Py.EnumOrNull<DB.BuiltInParameter>(name);

    private static readonly DB.BuiltInParameter? ViewerVolume = Bip("VIEWER_VOLUME_OF_INTEREST_CROP");
    private static readonly DB.BuiltInParameter? DatumVolume = Bip("DATUM_VOLUME_OF_INTEREST");

    private static long? ParamId(DB.Element e, DB.BuiltInParameter? bip)
    {
        if (bip == null)
            return null;
        try
        {
            var p = e.get_Parameter(bip.Value);
            if (p != null && Compat.IsValidId(p.AsElementId()))
                return p.AsElementId().Value;
        }
        catch { /* not readable on this element */ }
        return null;
    }

    private static List<Dict> CheckViewAudit(Ctx ctx, DB.Document doc, Dict rules)
    {
        var placed = PlacedViewIds(doc);
        var views = new Lst();
        foreach (var v in Views(doc))
        {
            var vt = v.ViewType.ToString();
            bool dependent;
            try { dependent = Compat.IsValidId(v.GetPrimaryViewId()); }
            catch { dependent = false; }
            var tid = v.ViewTemplateId;
            views.Add(new Dict
            {
                ["id"] = v.Id.Value, ["name"] = Utils.NormalizeString(v.Name), ["view_type"] = vt,
                ["is_template"] = v.IsTemplate,
                ["template_id"] = Compat.IsValidId(tid) ? tid.Value : (long?)null,
                ["on_sheet"] = placed.Contains(v.Id.Value), ["is_dependent"] = dependent,
                ["printable"] = Array.IndexOf(Printable, vt) >= 0,
                // scope box of a view: VIEWER_VOLUME_OF_INTEREST_CROP (looked up defensively)
                ["scope_box_id"] = ParamId(v, ViewerVolume),
            });
        }
        // schedules are audited for placement only when asked; they rarely use templates
        if (!ctx.Bool("include_schedules", false))
            views = views.Where(v => !PyX.Eq(((Dict)v!)["view_type"], "Schedule")).ToList();
        var sheets = new Lst();
        foreach (DB.ViewSheet s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
            sheets.Add(new Dict
            {
                ["id"] = s.Id.Value, ["number"] = Utils.NormalizeString(s.SheetNumber), ["name"] = Utils.NormalizeString(s.Name),
                ["is_placeholder"] = s.IsPlaceholder, ["view_count"] = (long)s.GetAllPlacedViews().Count,
            });
        var boxes = new Lst();
        foreach (var b in new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType())
            boxes.Add(new Dict { ["id"] = b.Id.Value, ["name"] = Utils.NormalizeString(b.Name) });
        var datumBoxes = new Lst();
        if (boxes.Count > 0)
        {
            var seen = new HashSet<long>();
            foreach (var cls in new[] { typeof(DB.Grid), typeof(DB.Level), typeof(DB.ReferencePlane) })
                foreach (var d in new DB.FilteredElementCollector(doc).OfClass(cls))
                {
                    var bid = ParamId(d, DatumVolume);
                    if (bid != null && bid.Value != 0 && seen.Add(bid.Value))
                        datumBoxes.Add(bid.Value);
                }
        }
        System.Collections.IEnumerable templateTypes = ctx.List("template_view_types");
        if (((Lst)templateTypes).Count == 0)
        {
            var configured = Py.Truthy(rules.Get("view_audit")) ? Obj(rules.Get("view_audit")).Get("template_view_types") : null;
            templateTypes = Py.Truthy(configured) ? (System.Collections.IEnumerable)Py.ListOf(configured) : TemplateTypes;
        }
        var res = Pure.ViewAudit.Audit(views, sheets, boxes, datumBoxes, templateTypes);
        if (boxes.Count > 0 && (ViewerVolume == null || DatumVolume == null))
            res.Add(Pure.Rules.Finding("view_audit", "info", "Scope box usage could not be read in this Revit version"));
        return res;
    }

    // ------------------------------------------------------------------ model_checks
    public static Dict? ModelChecks(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var rules = Rules(ctx);
        var checks = ctx.List("checks");
        if (checks.Count == 0)
            checks = AllChecks.Cast<object?>().ToList();
        var unknown = checks.Where(c => !(c is string cs && Checks.ContainsKey(cs))).ToList();
        if (unknown.Count > 0)
            throw new RvtssError("Unknown checks: " + PyX.Repr(unknown), hint: "Use: " + string.Join(", ", AllChecks));
        var findings = new List<Dict>();
        var timings = new Dict();
        var failed = new Dict();
        foreach (var nameObj in checks)
        {
            var name = (string)nameObj!;
            var sw = Stopwatch.StartNew();
            try
            {
                findings.AddRange(Checks[name](ctx, doc, rules));
            }
            catch (Exception e)
            {
                failed[name] = Utils.NormalizeString(e.Message);
            }
            timings[name] = (long)sw.ElapsedMilliseconds;
        }
        var minSev = ctx.Get("min_severity", "info");
        var minRank = Pure.Rules.SeverityRank(minSev);
        findings = findings.Where(f => Pure.Rules.SeverityRank(f["severity"]) >= minRank).ToList();
        findings = Pure.Rules.SortFindings(findings);
        var o = new Dict
        {
            ["document"] = Utils.NormalizeString(doc.Title), ["summary"] = Pure.Rules.Summarize(findings),
            ["findings"] = PyX.Head(findings, ctx.Int("max_findings", 200)!.Value), ["timings_ms"] = timings,
            ["rules_file"] = Path.Combine(Core.RvtssHome(), "qc_rules.json"),
        };
        if (failed.Count > 0)
            o["checks_failed"] = failed;
        return o;
    }
}
