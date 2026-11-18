namespace RvtssHost.Modules;

/// <summary>
/// Change-impact survey: what else a change to these elements touches (RVTSS v2.2). Read-only.
/// Port of revit_mcp/impact.py.
///
/// Routes:
///     POST /impact/survey/   relationships of up to 20 elements, grouped, each "found", "none" or "not_checked"
///
/// Groups: type (shared by N instances), host / hosted, joins, group / assembly,
/// rooms, tags / dimensions, dependents (deleted with it), views / sheets, levels,
/// MEP connections. Every group says how it was checked; anything not checked is
/// reported as such - absence of evidence is never reported as "none".
/// </summary>
public static class Impact
{
    public const int MaxElements = 20;
    public const int IdCap = 50;

    private static Lst LongList(IEnumerable<long> ids) => ids.Select(i => (object?)i).ToList();

    private static Dict Group(Dict? found = null, IEnumerable<long>? ids = null, string? note = null, string? reason = null,
        long? count = null)
    {
        if (reason != null)
            return new Dict { ["status"] = "not_checked", ["reason"] = reason };
        var sorted = new SortedSet<long>(ids ?? Enumerable.Empty<long>()).ToList();
        var n = count ?? sorted.Count;
        var o = new Dict
        {
            ["status"] = n != 0 ? "found" : "none", ["count"] = n, ["ids"] = LongList(sorted.Take(IdCap)),
        };
        if (sorted.Count > IdCap)
            o["ids_truncated"] = true;
        if (found != null && found.Count > 0)
            o.Update(found);
        if (!string.IsNullOrEmpty(note))
            o["note"] = note;
        return o;
    }

    /// <summary>Model-wide reverse lookups, built lazily once per request.</summary>
    private sealed class Index
    {
        private readonly DB.Document _doc;
        private Dictionary<long, List<long>>? _tags;
        private Dictionary<long, HashSet<long>>? _dims;
        private Dictionary<long, List<long>>? _hosted;
        private Dictionary<long, string>? _sheetOfView;

        public Index(DB.Document doc)
        {
            _doc = doc;
        }

        private static void Add(Dictionary<long, List<long>> map, long key, long value)
        {
            if (!map.TryGetValue(key, out var list))
                map[key] = list = new List<long>();
            list.Add(value);
        }

        public Dictionary<long, List<long>> Tags()
        {
            if (_tags == null)
            {
                _tags = new Dictionary<long, List<long>>();
                foreach (var el in new DB.FilteredElementCollector(_doc).OfClass(typeof(DB.IndependentTag)))
                {
                    var t = (DB.IndependentTag)el;
                    List<long> ids;
                    try
                    {
                        ids = t.GetTaggedLocalElementIds().Select(i => i.Value).ToList();
                    }
                    catch
                    {
                        ids = new List<long>();
                    }
                    foreach (var i in ids)
                        Add(_tags, i, t.Id.Value);
                }
                foreach (var bic in new[] { "OST_RoomTags", "OST_MEPSpaceTags", "OST_AreaTags" })
                {
                    DB.FilteredElementCollector col;
                    try
                    {
                        var b = Py.EnumOrNull<DB.BuiltInCategory>(bic) ?? throw new MissingMemberException(bic);
                        col = new DB.FilteredElementCollector(_doc).OfCategory(b).WhereElementIsNotElementType();
                    }
                    catch
                    {
                        continue;
                    }
                    foreach (var t in col)
                    {
                        try
                        {
                            DB.Element? target = t switch
                            {
                                DB.Architecture.RoomTag rt => rt.Room,
                                DB.Mechanical.SpaceTag st => st.Space,
                                DB.AreaTag at => at.Area,
                                _ => throw new MissingMemberException("target"),
                            };
                            if (target != null)
                                Add(_tags, target.Id.Value, t.Id.Value);
                        }
                        catch
                        {
                            continue;
                        }
                    }
                }
            }
            return _tags;
        }

        public Dictionary<long, HashSet<long>> Dimensions()
        {
            if (_dims == null)
            {
                _dims = new Dictionary<long, HashSet<long>>();
                foreach (var el in new DB.FilteredElementCollector(_doc).OfClass(typeof(DB.Dimension)))
                {
                    var d = (DB.Dimension)el;
                    try
                    {
                        foreach (DB.Reference rf in d.References)
                        {
                            var k = rf.ElementId.Value;
                            if (!_dims.TryGetValue(k, out var set))
                                _dims[k] = set = new HashSet<long>();
                            set.Add(d.Id.Value);
                        }
                    }
                    catch
                    {
                        continue;
                    }
                }
            }
            return _dims;
        }

        public Dictionary<long, List<long>> Hosted()
        {
            if (_hosted == null)
            {
                _hosted = new Dictionary<long, List<long>>();
                foreach (var el in new DB.FilteredElementCollector(_doc).OfClass(typeof(DB.FamilyInstance)))
                {
                    var fi = (DB.FamilyInstance)el;
                    try
                    {
                        if (fi.Host != null)
                            Add(_hosted, fi.Host.Id.Value, fi.Id.Value);
                    }
                    catch
                    {
                        continue;
                    }
                }
            }
            return _hosted;
        }

        public Dictionary<long, string> SheetOfView()
        {
            if (_sheetOfView == null)
            {
                _sheetOfView = new Dictionary<long, string>();
                foreach (var el in new DB.FilteredElementCollector(_doc).OfClass(typeof(DB.Viewport)))
                {
                    var vp = (DB.Viewport)el;
                    var sh = _doc.GetElement(vp.SheetId);
                    if (sh != null)
                        _sheetOfView[vp.ViewId.Value] = Utils.NormalizeString(((DB.ViewSheet)sh).SheetNumber);
                }
            }
            return _sheetOfView;
        }
    }

    private static Dict TypeGroup(DB.Document doc, DB.Element e)
    {
        DB.ElementId tid = e is DB.ElementType ? e.Id : e.GetTypeId();
        if (!Compat.IsValidId(tid))
            return Group(reason: "element has no type");
        var t = doc.GetElement(tid);
        List<long> ids;
        string method;
        if (t is DB.FamilySymbol)
        {
            ids = new DB.FilteredElementCollector(doc).WherePasses(new DB.FamilyInstanceFilter(doc, tid)).ToElementIds()
                .Select(i => i.Value).ToList();
            method = "FamilyInstanceFilter (exact)";
        }
        else
        {
            var cat = t != null ? t.Category : null;
            var col = new DB.FilteredElementCollector(doc).WhereElementIsNotElementType();
            if (cat != null)
                col = col.OfCategoryId(cat.Id);
            ids = col.Where(x => x.GetTypeId() == tid).Select(x => x.Id.Value).ToList();
            method = "category scan (exact)";
        }
        var family = Utils.NormalizeString((t as DB.ElementType)?.FamilyName ?? "");
        return Group(new Dict
        {
            ["type_id"] = tid.Value, ["type"] = t != null ? Utils.NormalizeString(Utils.GetElementName(t)) : null,
            ["family"] = family.Length > 0 ? family : null, ["method"] = method,
        }, ids, note: "Editing a type parameter changes every one of these instances.");
    }

    private static Dict HostGroup(DB.Document doc, DB.Element e, Index idx)
    {
        var o = new Dict();
        var host = e is DB.FamilyInstance fiHost ? fiHost.Host : null;
        o["host_id"] = host != null ? host.Id.Value : null;
        var hosted = new List<long>();
        if (idx.Hosted().TryGetValue(e.Id.Value, out var known))
            hosted.AddRange(known);
        if (e is DB.HostObject ho)
        {
            try
            {
                hosted.AddRange(ho.FindInserts(true, true, true, true).Select(i => i.Value).ToList());
            }
            catch { }
        }
        if (e is DB.FamilyInstance fi)
        {
            try
            {
                if (fi.SuperComponent != null)
                    o["super_component_id"] = fi.SuperComponent.Id.Value;
                hosted.AddRange(fi.GetSubComponentIds().Select(i => i.Value).ToList());
            }
            catch { }
        }
        return Group(o, hosted, note: "Hosted / nested elements move or are deleted with their host.");
    }

    private static Dict JoinGroup(DB.Document doc, DB.Element e)
    {
        var ids = new List<long>();
        try
        {
            ids.AddRange(DB.JoinGeometryUtils.GetJoinedElements(doc, e).Select(i => i.Value).ToList());
        }
        catch { }
        var loc = e.Location;
        if (loc is DB.LocationCurve lc)
        {
            foreach (var end in new[] { 0, 1 })
            {
                try
                {
                    var found = lc.get_ElementsAtJoin(end).Cast<DB.Element>().Select(x => x.Id.Value).Where(x => x != e.Id.Value).ToList();
                    ids.AddRange(found);
                }
                catch
                {
                    continue;
                }
            }
        }
        return Group(null, ids, note: "Geometry joins and wall end joins; cuts/attachments are not traced.");
    }

    private static Dict GroupAssembly(DB.Document doc, DB.Element e)
    {
        var o = new Dict();
        var ids = new List<long>();
        try
        {
            if (Compat.IsValidId(e.GroupId))
            {
                var g = (DB.Group)doc.GetElement(e.GroupId);
                var gt = g.GroupType;
                var instances = gt.Groups.Cast<DB.Element>().Select(x => x.Id.Value).ToList();
                o["group_id"] = g.Id.Value;
                o["group_type"] = Utils.NormalizeString(gt.Name);
                o["group_instances"] = (long)instances.Count;
                ids.AddRange(instances);
            }
        }
        catch { }
        try
        {
            if (Compat.IsValidId(e.AssemblyInstanceId))
            {
                var a = (DB.AssemblyInstance)doc.GetElement(e.AssemblyInstanceId);
                o["assembly_id"] = a.Id.Value;
                o["assembly"] = Utils.NormalizeString(a.AssemblyTypeName);
                ids.Add(a.Id.Value);
            }
        }
        catch { }
        var note = Py.Truthy(o.Get("group_instances"))
            ? "Group member: editing it in place changes every instance of the group type."
            : null;
        return Group(o, ids, note: note);
    }

    private static Dict RoomsGroup(DB.Document doc, DB.Element e)
    {
        if (e is not DB.FamilyInstance fi)
            return Group(reason: "only family instances report From/To rooms");
        var found = new Dict();
        try { var r = fi.Room; if (r != null) found["room"] = r.Id.Value; } catch { }
        try { var r = fi.FromRoom; if (r != null) found["fromroom"] = r.Id.Value; } catch { }
        try { var r = fi.ToRoom; if (r != null) found["toroom"] = r.Id.Value; } catch { }
        try { var r = fi.Space; if (r != null) found["space"] = r.Id.Value; } catch { }
        return Group(new Dict { ["rooms"] = found }, found.Values.Select(v => (long)v!).ToList(), note: "Final project phase only.");
    }

    private static Dict AnnotationGroup(DB.Document doc, DB.Element e, Index idx)
    {
        var tags = idx.Tags().TryGetValue(e.Id.Value, out var tg) ? tg : new List<long>();
        var dims = idx.Dimensions().TryGetValue(e.Id.Value, out var dm) ? dm.OrderBy(x => x).ToList() : new List<long>();
        return Group(new Dict
        {
            ["tag_ids"] = LongList(tags.Take(IdCap)), ["dimension_ids"] = LongList(dims.Take(IdCap)), ["tags"] = (long)tags.Count,
            ["dimensions"] = (long)dims.Count,
        }, tags.Concat(dims),
            note: "Local tags and dimensions; keynotes, spot dimensions in links and text are not traced.");
    }

    private static Dict Dependents(DB.Document doc, DB.Element e)
    {
        List<DB.ElementId> deps;
        try
        {
            deps = e.GetDependentElements(null).Where(i => i.Value != e.Id.Value).ToList();
        }
        catch (Exception ex)
        {
            return Group(reason: $"GetDependentElements unavailable: {ex.Message}");
        }
        var byCat = new Dict();
        foreach (var i in deps)
        {
            var x = doc.GetElement(i);
            var cat = x != null && x.Category != null ? Utils.NormalizeString(x.Category.Name) : "(no category)";
            byCat[cat] = (byCat.TryGetValue(cat, out var n) ? (long)n! : 0L) + 1;
        }
        return Group(new Dict { ["by_category"] = byCat }, deps.Select(i => i.Value).ToList(),
            note: "Elements Revit would delete together with this one (sketches, tags, hosted...).");
    }

    private static Dict ViewsGroup(DB.Document doc, DB.Element e, Index idx)
    {
        var o = new Dict();
        var ids = new List<long>();
        try
        {
            if (e.ViewSpecific && Compat.IsValidId(e.OwnerViewId))
            {
                var v = doc.GetElement(e.OwnerViewId);
                o["owner_view"] = new Dict
                {
                    ["id"] = v.Id.Value, ["name"] = Utils.NormalizeString(v.Name),
                    ["sheet"] = idx.SheetOfView().TryGetValue(v.Id.Value, out var sn) ? sn : null,
                };
                ids.Add(v.Id.Value);
            }
        }
        catch { }
        if (e is DB.View)
            o["on_sheet"] = idx.SheetOfView().TryGetValue(e.Id.Value, out var sheet) ? sheet : null;
        return Group(o, ids, note: "View-specific ownership and sheet placement; visibility in other views is not "
                                   + "computed (use find_elements(view=...) for a view).");
    }

    private static Dict DatumGroup(DB.Document doc, DB.Element e)
    {
        var found = new Dict();
        var specs = new (string key, string? bip)[]
        {
            ("level", null), ("base_constraint", "WALL_BASE_CONSTRAINT"), ("top_constraint", "WALL_HEIGHT_TYPE"),
            ("schedule_level", "SCHEDULE_LEVEL_PARAM"), ("reference_level", "INSTANCE_REFERENCE_LEVEL_PARAM"),
        };
        foreach (var (key, bipName) in specs)
        {
            try
            {
                DB.ElementId? lid;
                if (bipName == null)
                {
                    lid = e.LevelId;
                }
                else
                {
                    var bip = Py.EnumOrNull<DB.BuiltInParameter>(bipName) ?? throw new MissingMemberException(bipName);
                    var p = e.get_Parameter(bip);
                    lid = p != null ? p.AsElementId() : null;
                }
                if (lid != null && Compat.IsValidId(lid))
                {
                    if (doc.GetElement(lid) is DB.Level lv)
                        found[key] = new Dict { ["id"] = lv.Id.Value, ["name"] = Utils.NormalizeString(lv.Name) };
                }
            }
            catch
            {
                continue;
            }
        }
        return Group(new Dict { ["levels"] = found }, found.Values.Select(v => (long)((Dict)v!)["id"]!).ToList(),
            note: "Moving or deleting these levels moves or breaks this element. Grids and reference planes "
                  + "are not traced.");
    }

    private static Dict MepGroup(DB.Document doc, DB.Element e)
    {
        var cons = Mep.Connectors(e);
        if (cons.Count == 0)
            return Group(reason: "no MEP connectors");
        var ids = new List<long>();
        long openCount = 0;
        foreach (var c in cons)
        {
            try
            {
                if (!c.IsConnected)
                    openCount++;
                foreach (DB.Connector rf in c.AllRefs)
                {
                    if (rf.Owner != null && rf.Owner.Id != e.Id)
                        ids.Add(rf.Owner.Id.Value);
                }
            }
            catch
            {
                continue;
            }
        }
        return Group(new Dict { ["connectors"] = (long)cons.Count, ["open_connectors"] = openCount }, ids,
            note: "Directly connected elements (includes logical system owners).");
    }

    public static Dict? Survey(Ctx ctx)
    {
        var doc = ctx.Doc;
        var ids = ctx.List("element_ids");
        if (ids.Count == 0)
            throw new RvtssError($"'element_ids' is required (max {MaxElements})");
        if (ids.Count > MaxElements)
            throw new RvtssError($"At most {MaxElements} elements per survey",
                hint: "Survey a representative subset, or the shared type instead of its instances.");
        var changeObj = ctx.Get("change_kind", "instance");
        var change = changeObj as string ?? "";
        if (change != "instance" && change != "type" && change != "move" && change != "delete" && change != "unknown")
            throw new RvtssError("change_kind must be instance, type, move, delete or unknown");
        var idx = new Index(doc);
        var results = new Lst();
        var allIds = new HashSet<long>();
        var flags = new Lst();
        foreach (var e in Core.GetElements(doc, ids))
        {
            var groups = new Dict
            {
                ["type"] = TypeGroup(doc, e),
                ["host_hosted"] = HostGroup(doc, e, idx),
                ["joins"] = JoinGroup(doc, e),
                ["group_assembly"] = GroupAssembly(doc, e),
                ["rooms"] = RoomsGroup(doc, e),
                ["tags_dimensions"] = AnnotationGroup(doc, e, idx),
                ["dependents"] = Dependents(doc, e),
                ["views_sheets"] = ViewsGroup(doc, e, idx),
                ["levels"] = DatumGroup(doc, e),
                ["mep_connections"] = MepGroup(doc, e),
            };
            string[] relevant = change switch
            {
                "instance" => new[] { "group_assembly", "tags_dimensions", "rooms", "host_hosted" },
                "type" => new[] { "type", "group_assembly" },
                "move" => new[] { "host_hosted", "joins", "tags_dimensions", "mep_connections", "rooms" },
                "delete" => new[] { "dependents", "host_hosted", "tags_dimensions", "mep_connections", "views_sheets" },
                // tuple(groups): the IronPython 2 dict iterates in hash order, not insertion order. The order is
                // part of the answer (a list), so it is fixed to what the pyRevit reference returns.
                _ => new[]
                {
                    "type", "tags_dimensions", "host_hosted", "rooms", "group_assembly", "joins", "levels",
                    "mep_connections", "views_sheets", "dependents",
                },
            };
            var brief = Core.ElementBrief(doc, e);
            foreach (var g in relevant)
            {
                var gd = (Dict)groups[g]!;
                if (gd.Get("status") as string == "found")
                {
                    foreach (var i in (Lst)gd.Get("ids", new Lst())!)
                        allIds.Add((long)i!);
                }
            }
            var typeGroup = (Dict)groups["type"]!;
            var assemblyGroup = (Dict)groups["group_assembly"]!;
            var hostGroup = (Dict)groups["host_hosted"]!;
            var depGroup = (Dict)groups["dependents"]!;
            if (change == "type" && Convert.ToInt64(typeGroup.Get("count", 0L)) > 1)
                flags.Add($"Element {Py.Str(brief["id"])}: type '{Py.Str(typeGroup.Get("type"))}' is shared by {Py.Str(typeGroup["count"])} instances");
            if (Convert.ToInt64(assemblyGroup.Get("group_instances", 0L)) > 1)
                flags.Add($"Element {Py.Str(brief["id"])} is in group type '{Py.Str(assemblyGroup.Get("group_type"))}' with {Py.Str(assemblyGroup["group_instances"])} instances");
            if ((change == "move" || change == "delete") && Py.Truthy(hostGroup.Get("count")))
                flags.Add($"Element {Py.Str(brief["id"])} hosts {Py.Str(hostGroup["count"])} element(s) that move/delete with it");
            if (change == "delete" && Py.Truthy(depGroup.Get("count")))
                flags.Add($"Deleting {Py.Str(brief["id"])} also deletes {Py.Str(depGroup["count"])} dependent element(s)");
            results.Add(new Dict { ["element"] = brief, ["relevant_groups"] = relevant.Cast<object?>().ToList(), ["groups"] = groups });
        }
        // len(all_ids - set(ids)): ids are the request values (a string id never equals an integer)
        var propagation = allIds.Count(i => !ids.Any(x => PyX.Eq(x, i)));
        return new Dict
        {
            ["change_kind"] = change, ["elements"] = results, ["propagation_candidates"] = (long)propagation,
            ["requires_discussion"] = flags,
            ["blind_spots"] = new Lst
            {
                "linked models", "schedules / filters / formulas reading these values",
                "visibility in views", "engineering intent and calculations", "keynotes and text",
            },
            ["next_step"] = "Agree the scope with the user before changing anything when requires_discussion is not "
                            + "empty. Use dry_run=true on the edit, then batch_execute for multi-step changes.",
        };
    }

    public static void Register(RouteTable api)
    {
        api.Post("/impact/survey/", Survey, "survey");
    }
}
