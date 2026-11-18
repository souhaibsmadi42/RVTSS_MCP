namespace RvtssHost.Modules;

/// <summary>
/// MEP systems and connectivity (RVTSS v2.2). Read-only. Port of revit_mcp/mep.py.
///
/// Routes:
///     POST /mep/systems/       mechanical / piping / electrical systems with type, classification, element counts
///     POST /mep/connectors/    connectors of elements: domain, shape, size, flow, what they connect to
///     POST /mep/disconnects/   open connectors (nothing attached) on ducts, pipes, trays, conduits, fittings, equipment
/// </summary>
public static class Mep
{
    /// <summary>categories scanned by default for open connectors</summary>
    public static readonly string[] MepCategories =
    {
        "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctTerminal", "OST_FlexDuctCurves",
        "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves",
        "OST_PlumbingFixtures", "OST_MechanicalEquipment", "OST_CableTray", "OST_CableTrayFitting",
        "OST_Conduit", "OST_ConduitFitting", "OST_Sprinklers",
    };

    /// <summary>ConnectorManager of an MEP curve (pipe, duct...) or of a family instance (fittings, equipment).</summary>
    internal static DB.ConnectorManager? ConnectorManager(DB.Element e)
    {
        try
        {
            // MEPCurve
            DB.ConnectorManager? cm = e is DB.MEPCurve mc ? mc.ConnectorManager
                : e is DB.FabricationPart fp ? fp.ConnectorManager : null;
            if (cm != null)
                return cm;
        }
        catch { /* fall through to the family instance */ }
        try
        {
            // FamilyInstance
            var mm = (e as DB.FamilyInstance)?.MEPModel;
            return mm?.ConnectorManager;
        }
        catch
        {
            return null;
        }
    }

    internal static List<DB.Connector> Connectors(DB.Element e)
    {
        var cm = ConnectorManager(e);
        if (cm == null)
            return new List<DB.Connector>();
        try
        {
            return cm.Connectors.Cast<DB.Connector>().ToList();
        }
        catch
        {
            return new List<DB.Connector>();
        }
    }

    private static string? EnumText(object? v)
    {
        try { return v == null ? "None" : v.ToString(); }
        catch { return null; }
    }

    internal static bool IsPhysical(DB.Connector c)
    {
        try
        {
            var t = c.ConnectorType;
            return t == DB.ConnectorType.End || t == DB.ConnectorType.Curve || t == DB.ConnectorType.Physical;
        }
        catch
        {
            return true;
        }
    }

    internal static Dict DescribeConnector(DB.Document doc, DB.Element owner, DB.Connector c, string unit)
    {
        var d = new Dict { ["id"] = (long)c.Id, ["domain"] = EnumText(c.Domain), ["type"] = EnumText(c.ConnectorType), ["connected"] = c.IsConnected };
        try
        {
            d["origin"] = Core.XyzList(c.Origin, unit);
        }
        catch { }
        try
        {
            d["shape"] = EnumText(c.Shape);
            if (c.Shape == DB.ConnectorProfileType.Round)
            {
                d["diameter"] = Units.FromInternal(c.Radius * 2.0, unit, 1);
            }
            else if (c.Shape == DB.ConnectorProfileType.Rectangular || c.Shape == DB.ConnectorProfileType.Oval)
            {
                d["width"] = Units.FromInternal(c.Width, unit, 1);
                d["height"] = Units.FromInternal(c.Height, unit, 1);
            }
        }
        catch { }
        // Direction, PipeSystemType, DuctSystemType, ElectricalSystemType (each may throw for another domain)
        try { d["direction"] = EnumText(c.Direction); } catch { }
        try { d["pipe_system_type"] = EnumText(c.PipeSystemType); } catch { }
        try { d["duct_system_type"] = EnumText(c.DuctSystemType); } catch { }
        try { d["electrical_system_type"] = EnumText(c.ElectricalSystemType); } catch { }
        try
        {
            if (c.MEPSystem != null)
                d["system"] = Utils.NormalizeString(c.MEPSystem.Name);
        }
        catch { }
        var peers = new Lst();
        try
        {
            foreach (DB.Connector rf in c.AllRefs)
            {
                var o = rf.Owner;
                if (o == null || o.Id == owner.Id || !IsPhysical(rf))
                    continue;
                peers.Add(new Dict
                {
                    ["element_id"] = Compat.IdInt(o), ["category"] = o.Category != null ? Utils.NormalizeString(o.Category.Name) : null,
                    ["connector_id"] = (long)rf.Id,
                });
            }
        }
        catch { }
        d["connected_to"] = peers;
        return d;
    }

    public static Dict? Systems(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var domain = Py.Truthy(ctx.Get("domain")) ? Py.Str(ctx.Get("domain")).ToLowerInvariant() : "";
        var contains = Py.Truthy(ctx.Get("contains")) ? Py.Str(ctx.Get("contains")).ToLowerInvariant() : "";
        var outList = new List<Dict>();
        foreach (var el in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.MEPSystem)))
        {
            var s = (DB.MEPSystem)el;
            var cls = s.GetType().Name;
            var dom = cls.Contains("Electrical") ? "electrical"
                : cls.Contains("Piping") ? "piping" : cls.Contains("Mechanical") ? "mechanical" : "other";
            if (domain.Length > 0 && dom != domain)
                continue;
            var name = Utils.NormalizeString(s.Name);
            if (contains.Length > 0 && !name.ToLowerInvariant().Contains(contains))
                continue;
            var d = new Dict { ["id"] = Compat.IdInt(s), ["name"] = name, ["domain"] = dom };
            try
            {
                var st = doc.GetElement(s.GetTypeId());
                d["system_type"] = st != null ? Utils.NormalizeString(Utils.GetElementName(st)) : null;
            }
            catch { }
            // SystemType, then SystemClassification (the same response key)
            try
            {
                d["classification"] = s switch
                {
                    DB.Mechanical.MechanicalSystem ms => EnumText(ms.SystemType),
                    DB.Plumbing.PipingSystem ps => EnumText(ps.SystemType),
                    DB.Electrical.ElectricalSystem es => EnumText(es.SystemType),
                    _ => throw new MissingMemberException("SystemType"),
                };
            }
            catch { }
            try { d["element_count"] = (long)s.Elements.Size; } catch { }
            try
            {
                DB.FamilyInstance? be = s switch
                {
                    DB.Mechanical.MechanicalSystem ms => ms.BaseEquipment,
                    DB.Plumbing.PipingSystem ps => ps.BaseEquipment,
                    DB.Electrical.ElectricalSystem es => es.BaseEquipment,
                    _ => throw new MissingMemberException("BaseEquipment"),
                };
                d["base_equipment"] = be != null ? Core.ElementBrief(doc, be) : null;
            }
            catch { }
            try
            {
                d["is_well_connected"] = s switch
                {
                    DB.Mechanical.MechanicalSystem ms => ms.IsWellConnected,
                    DB.Plumbing.PipingSystem ps => ps.IsWellConnected,
                    _ => throw new MissingMemberException("IsWellConnected"),
                };
            }
            catch { }
            if (ctx.Bool("include_elements", false))
            {
                try
                {
                    d["element_ids"] = s.Elements.Cast<DB.Element>().Select(e => (object?)Compat.IdInt(e)).Take(500).ToList();
                }
                catch { }
            }
            outList.Add(d);
        }
        outList = outList.OrderBy(d => (string)d["domain"]!, StringComparer.Ordinal)
            .ThenBy(d => (string)d["name"]!, StringComparer.Ordinal).ToList();
        var (page, meta) = Filters.Paginate(outList, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, Core.MaxLimit));
        var byDomain = new Dict();
        foreach (var d in outList)
        {
            var k = (string)d["domain"]!;
            byDomain[k] = (byDomain.TryGetValue(k, out var n) ? (long)n! : 0L) + 1;
        }
        return new Dict
        {
            ["count"] = (long)outList.Count, ["by_domain"] = byDomain,
            ["not_well_connected"] = outList.Where(d => d.TryGetValue("is_well_connected", out var w) && w is bool b && !b)
                .Select(d => (object?)d["name"]).Take(100).ToList(),
            ["pagination"] = meta, ["systems"] = page,
        };
    }

    public static Dict? ConnectorsOf(Ctx ctx)
    {
        var doc = ctx.Doc;
        var ids = ctx.List("element_ids");
        if (ids.Count == 0)
            throw new RvtssError("'element_ids' is required (max 50)");
        if (ids.Count > 50)
            throw new RvtssError("At most 50 elements per call");
        var outList = new Lst();
        foreach (var e in Core.GetElements(doc, ids))
        {
            var cons = Connectors(e);
            var d = Core.ElementBrief(doc, e);
            d["connectors"] = cons.Select(c => (object?)DescribeConnector(doc, e, c, ctx.Unit)).ToList();
            d["open_connectors"] = (long)cons.Count(c => IsPhysical(c) && !c.IsConnected);
            if (cons.Count == 0)
                d["note"] = "no connectors (not an MEP element)";
            outList.Add(d);
        }
        return new Dict { ["unit"] = ctx.Unit, ["elements"] = outList };
    }

    public static Dict? Disconnects(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var spec = Query.QuerySpec(ctx.Data);
        if (!Py.Truthy(spec.Get("categories")) && !Py.Truthy(spec.Get("element_ids")) && !Py.Truthy(spec.Get("selection")))
        {
            spec = new Dict(spec);
            spec["categories"] = MepCategories.Where(c => CategoryExists(doc, c)).Cast<object?>().ToList();
        }
        var maxScan = ctx.Int("max_scan", 300000);
        var elements = Query.Collect(ctx, spec, maxScan: maxScan == null ? null : (int)Math.Min(maxScan.Value, int.MaxValue));
        var found = new List<Dict>();
        var byCat = new Dict();
        long scanned = 0;
        foreach (var e in elements)
        {
            var cons = Connectors(e);
            if (cons.Count == 0)
                continue;
            scanned++;
            foreach (var c in cons)
            {
                if (!IsPhysical(c) || c.IsConnected)
                    continue;
                var brief = Core.ElementBrief(doc, e);
                var item = new Dict
                {
                    ["element_id"] = brief["id"], ["category"] = brief.Get("category"), ["family"] = brief.Get("family"),
                    ["type"] = brief.Get("type"), ["connector_id"] = (long)c.Id, ["domain"] = EnumText(c.Domain),
                    ["level"] = Core.ElementLevel(doc, e),
                };
                try { item["origin"] = Core.XyzList(c.Origin, ctx.Unit); } catch { }
                try
                {
                    if (c.MEPSystem != null)
                        item["system"] = Utils.NormalizeString(c.MEPSystem.Name);
                }
                catch { }
                found.Add(item);
                var key = Py.Truthy(item["category"]) ? (string)item["category"]! : "(none)";
                byCat[key] = (byCat.TryGetValue(key, out var n) ? (long)n! : 0L) + 1;
            }
        }
        var (page, meta) = Filters.Paginate(found, ctx.Int("offset", 0), ctx.Int("limit", 200, 1, 2000));
        return new Dict
        {
            ["elements_scanned"] = scanned, ["open_connectors"] = (long)found.Count, ["by_category"] = byCat, ["unit"] = ctx.Unit,
            ["note"] = "An open connector is a physical end with nothing attached: missing fitting, cap, terminal or "
                       + "a gap. Equipment connectors waiting for future work are reported too.",
            ["pagination"] = meta, ["items"] = page,
        };
    }

    private static bool CategoryExists(DB.Document doc, string bicName)
    {
        try
        {
            var bic = Py.EnumOrNull<DB.BuiltInCategory>(bicName);
            if (bic == null)
                return false;
            return DB.Category.GetCategory(doc, bic.Value) != null;
        }
        catch
        {
            return false;
        }
    }

    public static void Register(RouteTable api)
    {
        api.Post("/mep/systems/", Systems, "systems");
        api.Post("/mep/connectors/", ConnectorsOf, "connectors_of");
        api.Post("/mep/disconnects/", Disconnects, "disconnects");
    }
}
