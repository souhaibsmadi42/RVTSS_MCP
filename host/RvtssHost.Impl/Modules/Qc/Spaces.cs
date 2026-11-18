namespace RvtssHost.Modules;

/// <summary>
/// Rooms, MEP spaces and areas (RVTSS v2.2). Port of revit_mcp/spaces.py.
///
/// Routes:
///     POST /rooms/list/      rooms / spaces / areas with area, perimeter, volume, level, phase, status
///     POST /rooms/details/   boundaries, doors/windows (From/To room), wall/floor/ceiling finishes, contents
/// </summary>
public static class Spaces
{
    public static void Register(RouteTable api)
    {
        api.Post("/rooms/list/", ListSpaces, "list_spaces");
        api.Post("/rooms/details/", SpaceDetails, "space_details");
    }

    public static readonly Dictionary<string, DB.BuiltInCategory> KindCategory = new(StringComparer.Ordinal)
    {
        ["room"] = DB.BuiltInCategory.OST_Rooms,
        ["space"] = DB.BuiltInCategory.OST_MEPSpaces,
        ["area"] = DB.BuiltInCategory.OST_Areas,
    };

    private static string? ParamText(DB.Element e, DB.BuiltInParameter bip)
    {
        try
        {
            var p = e.get_Parameter(bip);
            if (p == null)
                return null;
            var text = p.AsString();
            if (string.IsNullOrEmpty(text))
                text = p.AsValueString();
            var norm = Utils.NormalizeString(string.IsNullOrEmpty(text) ? "" : text);
            return norm.Length > 0 ? norm : null;
        }
        catch
        {
            return null;
        }
    }

    private static DB.Element? PhaseOf(DB.Document doc, DB.Element e)
    {
        foreach (var bip in new[] { DB.BuiltInParameter.ROOM_PHASE, DB.BuiltInParameter.PHASE_CREATED })
        {
            try
            {
                var p = e.get_Parameter(bip);
                if (p != null && Compat.IsValidId(p.AsElementId()))
                    return doc.GetElement(p.AsElementId());
            }
            catch { continue; }
        }
        return null;
    }

    /// <summary>{element id: 'not_enclosed' | 'redundant'} from the model warnings (English texts).</summary>
    private static Dictionary<long, string> WarningKinds(DB.Document doc)
    {
        var kinds = new Dictionary<long, string>();
        try
        {
            foreach (var w in doc.GetWarnings())
            {
                var kind = Pure.Spaces.ClassifyWarning(Utils.NormalizeString(w.GetDescriptionText()));
                if (!string.IsNullOrEmpty(kind))
                    foreach (var i in w.GetFailingElements())
                        kinds[i.Value] = kind!;
            }
        }
        catch { /* warnings are optional */ }
        return kinds;
    }

    private static string AreaUnit(Ctx ctx)
    {
        try
        {
            var requested = ctx.Get("area_unit");
            return Pure.Units.LengthUnitFor("area", Py.Truthy(requested) ? Py.Str(requested) : "m2")!;
        }
        catch (UnitError e)
        {
            throw new RvtssError(e.Message);
        }
    }

    private static List<DB.Element> SpatialElements(DB.Document doc, string kind) =>
        new DB.FilteredElementCollector(doc).OfCategory(KindCategory[kind]).WhereElementIsNotElementType().ToList();

    private static Dict Describe(DB.Document doc, DB.Element e, string kind, string unit, string areaUnit,
        Dictionary<long, string> warnKinds)
    {
        var se = e as DB.SpatialElement;
        var area = se != null ? se.Area : 0.0;
        var placed = e.Location != null;
        string? level = null;
        try
        {
            var lv = se?.Level;
            level = lv != null ? Utils.NormalizeString(lv.Name) : null;
        }
        catch { /* no level */ }
        var phase = PhaseOf(doc, e);
        var o = new Dict
        {
            ["id"] = e.Id.Value, ["number"] = ParamText(e, DB.BuiltInParameter.ROOM_NUMBER),
            ["name"] = ParamText(e, DB.BuiltInParameter.ROOM_NAME), ["level"] = level,
            ["phase"] = phase != null ? Utils.NormalizeString(phase.Name) : null,
            ["area"] = Pure.Units.FromInternal(area, areaUnit, 3),
            ["status"] = Pure.Spaces.SpatialStatus(placed, area, warnKinds.TryGetValue(e.Id.Value, out var wk) ? wk : null),
        };
        try
        {
            o["perimeter"] = Pure.Units.FromInternal(se!.Perimeter, unit, 1);
        }
        catch { /* no perimeter */ }
        if (kind == "room" || kind == "space")
        {
            try
            {
                var volume = e is DB.Architecture.Room rm ? rm.Volume : ((DB.Mechanical.Space)e).Volume;
                o["volume"] = Pure.Units.FromInternal(volume, Pure.Units.LengthUnitFor("volume", areaUnit), 3);
            }
            catch { /* no volume */ }
            try
            {
                var height = e is DB.Architecture.Room rm ? rm.UnboundedHeight : ((DB.Mechanical.Space)e).UnboundedHeight;
                o["unbounded_height"] = Pure.Units.FromInternal(height, unit, 1);
            }
            catch { /* no unbounded height */ }
            o["department"] = ParamText(e, DB.BuiltInParameter.ROOM_DEPARTMENT);
        }
        if (kind == "area")
        {
            try { o["area_scheme"] = Utils.NormalizeString(((DB.Area)e).AreaScheme.Name); }
            catch { /* no area scheme */ }
        }
        if (kind == "space")
        {
            try
            {
                var room = ((DB.Mechanical.Space)e).Room;
                if (room != null)
                    o["room_id"] = room.Id.Value;
            }
            catch { /* no room */ }
        }
        return o;
    }

    public static Dict? ListSpaces(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var kindValue = ctx.Get("kind", "room");
        if (!(kindValue is string kind && KindCategory.ContainsKey(kind)))
            throw new RvtssError("kind must be room, space or area");
        var unit = ctx.Unit;
        var areaUnit = AreaUnit(ctx);
        var level = Py.Truthy(ctx.Get("level")) ? Core.FindLevel(doc, ctx.Get("level")) : null;
        var phaseName = Py.Truthy(ctx.Get("phase")) ? Py.Str(ctx.Get("phase")).ToLowerInvariant() : "";
        var statuses = new HashSet<string>(ctx.List("status").Where(s => s is string).Select(s => (string)s!), StringComparer.Ordinal);
        var hasStatuses = ctx.List("status").Count > 0;
        var contains = Py.Truthy(ctx.Get("contains")) ? Py.Str(ctx.Get("contains")).ToLowerInvariant() : "";
        var warnKinds = WarningKinds(doc);
        var items = new List<Dict>();
        foreach (var e in SpatialElements(doc, kind))
        {
            if (level != null)
            {
                try
                {
                    if (e.LevelId != level.Id)
                        continue;
                }
                catch { continue; }
            }
            var d = Describe(doc, e, kind, unit, areaUnit, warnKinds);
            if (phaseName.Length > 0 && (Py.Truthy(d.Get("phase")) ? Py.Str(d["phase"]).ToLowerInvariant() : "") != phaseName)
                continue;
            if (hasStatuses && !statuses.Contains((string)d["status"]!))
                continue;
            if (contains.Length > 0
                && (Py.Str(Py.Truthy(d.Get("number")) ? d["number"] : "") + " " + Py.Str(Py.Truthy(d.Get("name")) ? d["name"] : ""))
                    .ToLowerInvariant().IndexOf(contains, StringComparison.Ordinal) < 0)
                continue;
            items.Add(d);
        }
        items = items.OrderBy(d => Py.Truthy(d.Get("level")) ? Py.Str(d["level"]) : "", StringComparer.Ordinal)
            .ThenBy(d => Py.Truthy(d.Get("number")) ? Py.Str(d["number"]) : "", StringComparer.Ordinal)
            .ThenBy(d => Py.Truthy(d.Get("name")) ? Py.Str(d["name"]) : "", StringComparer.Ordinal).ToList();
        var (page, meta) = Pure.Filters.Paginate(items, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, Core.MaxLimit));
        var placed = items.Where(d => (string)d["status"]! == "placed").ToList();
        var totalArea = 0.0;
        foreach (var d in placed)
            totalArea += Py.Truthy(d.Get("area")) ? Py.ToFloat(d["area"]) : 0.0;
        var byStatus = new Dict();
        foreach (var kv in Pure.Spaces.SummarizeBy(items, "status"))
            byStatus[kv.Key] = ((Dict)kv.Value!)["count"];
        return new Dict
        {
            ["kind"] = kind, ["count"] = (long)items.Count, ["unit"] = unit, ["area_unit"] = areaUnit,
            ["total_area"] = Py.Round(totalArea, 3), ["by_status"] = byStatus,
            ["by_level"] = Pure.Spaces.SummarizeBy(placed, "level"),
            ["by_department"] = kind != "area" ? Pure.Spaces.SummarizeBy(placed, "department") : null,
            ["pagination"] = meta, ["items"] = page,
        };
    }

    // ------------------------------------------------------------------ details
    private static List<List<Dict>> Segments(DB.Document doc, DB.Element e, string unit, object? location)
    {
        var opts = new DB.SpatialElementBoundaryOptions();
        try
        {
            var name = location as string ?? "";
            opts.SpatialElementBoundaryLocation = name switch
            {
                "center" => DB.SpatialElementBoundaryLocation.Center,
                "core_center" => DB.SpatialElementBoundaryLocation.CoreCenter,
                "core_boundary" => DB.SpatialElementBoundaryLocation.CoreBoundary,
                _ => DB.SpatialElementBoundaryLocation.Finish,
            };
        }
        catch { /* keep the default */ }
        var loops = new List<List<Dict>>();
        IList<IList<DB.BoundarySegment>>? raw;
        try { raw = ((DB.SpatialElement)e).GetBoundarySegments(opts); }
        catch { raw = null; }
        if (raw == null)
            return loops;
        foreach (var loop in raw)
        {
            var segs = new List<Dict>();
            foreach (var s in loop)
            {
                var c = s.GetCurve();
                var seg = new Dict
                {
                    ["start"] = Core.XyzList(c.GetEndPoint(0), unit), ["end"] = Core.XyzList(c.GetEndPoint(1), unit),
                    ["length"] = Pure.Units.FromInternal(c.Length, unit, 1), ["_length_internal"] = c.Length,
                };
                var eid = s.ElementId;
                if (Compat.IsValidId(eid))
                {
                    seg["element_id"] = eid.Value;
                    var be = doc.GetElement(eid);
                    if (be != null)
                    {
                        seg["element_category"] = be.Category != null ? Utils.NormalizeString(be.Category.Name) : null;
                        seg["element_bic"] = Compat.BicFromCategory(be.Category);
                    }
                }
                try
                {
                    if (Compat.IsValidId(s.LinkElementId))
                        seg["link_element_id"] = s.LinkElementId.Value;
                }
                catch { /* not a linked boundary */ }
                segs.Add(seg);
            }
            loops.Add(segs);
        }
        return loops;
    }

    /// <summary>fi.get_FromRoom(phase) / fi.FromRoom (and ToRoom, Room, Space): the phase overload when a phase is known,
    /// the property when it is not or when the overload fails.</summary>
    private static DB.Element? RoomOf(DB.FamilyInstance fi, string getter, DB.Element? phase)
    {
        var ph = phase as DB.Phase;
        try
        {
            if (ph != null)
            {
                return getter switch
                {
                    "FromRoom" => fi.get_FromRoom(ph),
                    "ToRoom" => fi.get_ToRoom(ph),
                    "Space" => fi.get_Space(ph),
                    _ => fi.get_Room(ph),
                };
            }
            return PlainRoomOf(fi, getter);
        }
        catch
        {
            try { return PlainRoomOf(fi, getter); }
            catch { return null; }
        }
    }

    private static DB.Element? PlainRoomOf(DB.FamilyInstance fi, string getter) => getter switch
    {
        "FromRoom" => fi.FromRoom,
        "ToRoom" => fi.ToRoom,
        "Space" => fi.Space,
        _ => fi.Room,
    };

    private static readonly DB.BuiltInParameter[] WidthParams = Bips("DOOR_WIDTH", "WINDOW_WIDTH", "FAMILY_WIDTH_PARAM", "FURNITURE_WIDTH");
    private static readonly DB.BuiltInParameter[] HeightParams = Bips("DOOR_HEIGHT", "WINDOW_HEIGHT", "FAMILY_HEIGHT_PARAM", "GENERIC_HEIGHT");

    /// <summary>The BuiltInParameter members that exist in this Revit version (getattr raised for the others).</summary>
    private static DB.BuiltInParameter[] Bips(params string[] names) =>
        names.Select(n => Py.EnumOrNull<DB.BuiltInParameter>(n)).Where(b => b != null).Select(b => b!.Value).ToArray();

    /// <summary>(width, height) in internal feet from the instance or its type, or (null, null).</summary>
    private static (double? w, double? h) OpeningSize(DB.Document doc, DB.FamilyInstance fi)
    {
        var owners = new DB.Element?[] { fi, doc.GetElement(fi.GetTypeId()) };
        var vals = new double?[2];
        var index = 0;
        foreach (var names in new[] { WidthParams, HeightParams })
        {
            double? v = null;
            foreach (var owner in owners)
            {
                if (owner == null)
                    continue;
                foreach (var bip in names)
                {
                    try
                    {
                        var p = owner.get_Parameter(bip);
                        if (p != null && p.HasValue && p.AsDouble() > 0)
                        {
                            v = p.AsDouble();
                            break;
                        }
                    }
                    catch { continue; }
                }
                if (v != null)
                    break;
            }
            vals[index++] = v;
        }
        return (vals[0], vals[1]);
    }

    /// <summary>'from' / 'to' when a point 300 mm in front of / behind the opening lies in the MEP space.
    ///
    /// FamilyInstance has From/ToRoom but no From/ToSpace, so spaces are tested geometrically.</summary>
    private static string? SpaceSide(DB.Mechanical.Space space, DB.FamilyInstance fi)
    {
        DB.XYZ p, f;
        try
        {
            if (fi.Location is not DB.LocationPoint lp)
                return null;
            p = lp.Point;
            f = fi.FacingOrientation;
        }
        catch { return null; }
        foreach (var (side, sign) in new[] { ("to", 1.0), ("from", -1.0) })
        {
            var q = new DB.XYZ(p.X + f.X * sign, p.Y + f.Y * sign, p.Z + 1.0);
            try
            {
                if (space.IsPointInSpace(q))
                    return side;
            }
            catch { return null; }
        }
        return null;
    }

    /// <summary>Doors and windows of the model, collected once per request (every room tests the same instances).</summary>
    private sealed class RequestCache
    {
        public List<DB.FamilyInstance>? Openings;
        public List<DB.FamilyInstance>? Instances;
        public HashSet<long>? ContentCategories;
        public readonly Dictionary<long, (double? w, double? h)> Sizes = new();
    }

    private static List<DB.FamilyInstance> OpeningInstances(DB.Document doc, RequestCache cache)
    {
        if (cache.Openings == null)
        {
            // doors first, then windows: the order of the Python loop
            var list = new List<DB.FamilyInstance>();
            foreach (var bic in new[] { DB.BuiltInCategory.OST_Doors, DB.BuiltInCategory.OST_Windows })
                foreach (DB.FamilyInstance fi in new DB.FilteredElementCollector(doc).OfCategory(bic).OfClass(typeof(DB.FamilyInstance)))
                    list.Add(fi);
            cache.Openings = list;
        }
        return cache.Openings;
    }

    private static List<Dict> Openings(DB.Document doc, DB.Element room, DB.Element? phase, string unit, string kind, RequestCache cache)
    {
        var res = new List<Dict>();
        var elementInfo = new ElementInfoCache(doc);
        foreach (var fi in OpeningInstances(doc, cache))
        {
            DB.Element? fr = null, to = null;
            string? side;
            if (kind == "space")
            {
                side = SpaceSide((DB.Mechanical.Space)room, fi);
            }
            else
            {
                fr = RoomOf(fi, "FromRoom", phase);
                to = RoomOf(fi, "ToRoom", phase);
                side = null;
                if (fr != null && fr.Id == room.Id)
                    side = "from";
                else if (to != null && to.Id == room.Id)
                    side = "to";
            }
            if (side == null)
                continue;
            if (!cache.Sizes.TryGetValue(fi.Id.Value, out var size))
            {
                size = OpeningSize(doc, fi);
                cache.Sizes[fi.Id.Value] = size;
            }
            var (w, h) = size;
            var d = elementInfo.Brief(fi);
            var other = side == "from" ? to : fr;
            d["side"] = side;
            d["host_id"] = fi.Host != null ? fi.Host.Id.Value : (long?)null;
            d["width"] = w != null && w.Value != 0 ? Pure.Units.FromInternal(w.Value, unit, 1) : (double?)null;
            d["height"] = h != null && h.Value != 0 ? Pure.Units.FromInternal(h.Value, unit, 1) : (double?)null;
            d["_w"] = w;
            d["_h"] = h;
            d["other_room_id"] = other != null ? other.Id.Value : (long?)null;
            res.Add(d);
        }
        return res;
    }

    private static List<Dict> Contents(DB.Document doc, DB.Element room, DB.Element? phase, Lst categories, string kind, RequestCache cache)
    {
        var found = new List<Dict>();
        if (cache.Instances == null)
        {
            cache.Instances = new List<DB.FamilyInstance>();
            foreach (DB.FamilyInstance fi in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilyInstance)))
                cache.Instances.Add(fi);
        }
        if (cache.ContentCategories == null && categories.Count > 0)
        {
            cache.ContentCategories = new HashSet<long>();
            foreach (var c in categories)
                cache.ContentCategories.Add(Core.ResolveCategory(doc, c).Id.Value);
        }
        var catIds = categories.Count > 0 ? cache.ContentCategories : null;
        var elementInfo = new ElementInfoCache(doc);
        var getter = kind == "space" ? "Space" : "Room";
        foreach (var fi in cache.Instances)
        {
            var cat = fi.Category;
            if (cat == null || (catIds != null && !catIds.Contains(cat.Id.Value)))
                continue;
            var bic = Compat.BicFromCategory(cat);
            if (bic == "OST_Doors" || bic == "OST_Windows")
                continue;
            var r = RoomOf(fi, getter, phase);
            if (r == null)
            {
                try
                {
                    var pt = Core.ElementPoint(fi);
                    if (pt != null)
                    {
                        var probe = new DB.XYZ(pt.X, pt.Y, pt.Z + 0.3);
                        var inside = kind == "space"
                            ? ((DB.Mechanical.Space)room).IsPointInSpace(probe)
                            : ((DB.Architecture.Room)room).IsPointInRoom(probe);
                        if (inside)
                            r = room;
                    }
                }
                catch { r = null; }
            }
            if (r != null && r.Id == room.Id)
                found.Add(elementInfo.Brief(fi));
        }
        return found;
    }

    private static bool IsPrivate(string key) => key.StartsWith("_", StringComparison.Ordinal);

    public static Dict? SpaceDetails(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var ids = ctx.List("element_ids");
        if (ids.Count == 0)
            throw new RvtssError("'element_ids' (room / space / area ids) is required", hint: "Get ids with list_rooms.");
        if (ids.Count > 50)
            throw new RvtssError("At most 50 rooms per call", hint: "Page through list_rooms results.");
        var unit = ctx.Unit;
        var areaUnit = AreaUnit(ctx);
        var includeList = ctx.List("include");
        var include = includeList.Count > 0
            ? new HashSet<string>(includeList.Where(s => s is string).Select(s => (string)s!), StringComparer.Ordinal)
            : new HashSet<string>(new[] { "boundaries", "openings", "finishes" }, StringComparer.Ordinal);
        var warnKinds = WarningKinds(doc);
        var cache = new RequestCache();
        var results = new Lst();
        foreach (var e in Core.GetElements(doc, ids, "Room"))
        {
            if (e is not DB.SpatialElement)
                throw new RvtssError($"Element {e.Id.Value} is not a room, space or area");
            var bic = Compat.BicFromCategory(e.Category);
            var kind = bic == "OST_MEPSpaces" ? "space" : bic == "OST_Areas" ? "area" : "room";
            var d = Describe(doc, e, kind, unit, areaUnit, warnKinds);
            var phase = PhaseOf(doc, e);
            var loops = include.Contains("boundaries") || include.Contains("finishes")
                ? Segments(doc, e, unit, ctx.Get("boundary_location", "finish"))
                : new List<List<Dict>>();
            var openings = kind != "area" && (include.Contains("openings") || include.Contains("finishes"))
                ? Openings(doc, e, phase, unit, kind, cache)
                : new List<Dict>();
            if (include.Contains("finishes") && kind != "area")
            {
                var height = 0.0;
                if (e is DB.Architecture.Room rm)
                    height = rm.UnboundedHeight;
                else if (e is DB.Mechanical.Space sp)
                    height = sp.UnboundedHeight;
                var byHost = new Dictionary<long, List<Lst>>();
                foreach (var o in openings)
                {
                    var host = o.Get("host_id");
                    if (Py.Truthy(host) && Py.Truthy(o.Get("_w")) && Py.Truthy(o.Get("_h")))
                    {
                        var hostId = Py.ToInt(host);
                        if (!byHost.TryGetValue(hostId, out var list))
                            byHost[hostId] = list = new List<Lst>();
                        list.Add(new Lst { o["_w"], o["_h"] });
                    }
                }
                var walls = new Lst();
                var totalNet = 0.0;
                foreach (var loop in loops)
                {
                    foreach (var s in loop)
                    {
                        if (!PyX.Eq(s.Get("element_bic"), "OST_Walls"))
                            continue; // room separation lines, columns, area boundaries are not wall finish
                        var holes = new List<Lst>();
                        if (Py.Truthy(s.Get("element_id")))
                        {
                            var key = Py.ToInt(s["element_id"]);
                            if (byHost.TryGetValue(key, out var found))
                            {
                                holes = found;
                                byHost.Remove(key); // dict.pop: each host's openings count once
                            }
                        }
                        var (gross, hole, net) = Pure.Spaces.WallFinish(s["_length_internal"], height, holes);
                        totalNet += net;
                        walls.Add(new Dict
                        {
                            ["element_id"] = s.Get("element_id"), ["category"] = s.Get("element_category"), ["length"] = s["length"],
                            ["gross_area"] = Pure.Units.FromInternal(gross, areaUnit, 3),
                            ["openings_area"] = Pure.Units.FromInternal(hole, areaUnit, 3),
                            ["net_area"] = Pure.Units.FromInternal(net, areaUnit, 3),
                        });
                    }
                }
                d["finishes"] = new Dict
                {
                    ["floor_area"] = d.Get("area"), ["ceiling_area"] = d.Get("area"),
                    ["wall_net_area"] = Pure.Units.FromInternal(totalNet, areaUnit, 3),
                    ["height_used"] = Pure.Units.FromInternal(height, unit, 1), ["walls"] = walls,
                    ["method"] = "estimate: boundary length x unbounded height minus door/window "
                                 + "width x height; sloped ceilings, columns and reveals are ignored",
                };
            }
            if (include.Contains("boundaries"))
                d["boundaries"] = loops.Select(loop => (object?)loop.Select(s =>
                {
                    var c = new Dict();
                    foreach (var kv in s)
                        if (!IsPrivate(kv.Key) && kv.Key != "element_bic")
                            c[kv.Key] = kv.Value;
                    return (object?)c;
                }).ToList()).ToList();
            if (include.Contains("openings") && kind != "area")
                d["openings"] = openings.Select(o =>
                {
                    var c = new Dict();
                    foreach (var kv in o)
                        if (!IsPrivate(kv.Key))
                            c[kv.Key] = kv.Value;
                    return (object?)c;
                }).ToList();
            if (include.Contains("contents") && kind != "area")
                d["contents"] = PyX.Head(Contents(doc, e, phase, ctx.List("content_categories"), kind, cache), 500);
            results.Add(d);
        }
        return new Dict { ["unit"] = unit, ["area_unit"] = areaUnit, ["count"] = (long)results.Count, ["items"] = results };
    }
}
