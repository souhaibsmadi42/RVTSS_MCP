namespace RvtssHost.Modules;

/// <summary>Clash geometry and the /qc/clashes/ route (revit_mcp/qc.py).</summary>
public static partial class Qc
{
    // ---------------------------------------------------------------------- geometry
    /// <summary>The solids of an element (Fine detail level, instance geometry expanded), optionally moved by transform.
    /// Imported by spatial.py as _solids.</summary>
    internal static List<DB.Solid> Solids(DB.Element e, DB.Transform? transform = null)
    {
        var opt = new DB.Options { DetailLevel = DB.ViewDetailLevel.Fine };
        var geom = e.get_Geometry(opt);
        var res = new List<DB.Solid>();
        if (geom == null)
            return res;
        WalkSolids(geom, res);
        if (transform != null)
            for (var i = 0; i < res.Count; i++)
                res[i] = DB.SolidUtils.CreateTransformed(res[i], transform);
        return res;
    }

    private static void WalkSolids(DB.GeometryElement g, List<DB.Solid> res)
    {
        foreach (DB.GeometryObject obj in g)
        {
            if (obj is DB.Solid s)
            {
                if (s.Volume > 1e-6)
                    res.Add(s);
            }
            else if (obj is DB.GeometryInstance inst)
            {
                var inner = inst.GetInstanceGeometry();
                if (inner != null)
                    WalkSolids(inner, res);
            }
        }
    }

    /// <summary>Points spread over the faces (UV grid, n x n per face) and edges of the solids.</summary>
    private static List<DB.XYZ> SamplePoints(List<DB.Solid> solids, int n)
    {
        var pts = new List<DB.XYZ>();
        foreach (var s in solids)
        {
            foreach (DB.Face face in s.Faces)
            {
                try
                {
                    var bb = face.GetBoundingBox();
                    for (var i = 0; i < n; i++)
                    {
                        for (var j = 0; j < n; j++)
                        {
                            var uv = new DB.UV(bb.Min.U + (bb.Max.U - bb.Min.U) * (i + 0.5) / n,
                                bb.Min.V + (bb.Max.V - bb.Min.V) * (j + 0.5) / n);
                            if (face.IsInside(uv))
                                pts.Add(face.Evaluate(uv));
                        }
                    }
                }
                catch { continue; }
            }
            foreach (DB.Edge edge in s.Edges)
            {
                foreach (var t in EdgeParams)
                {
                    try { pts.Add(edge.Evaluate(t)); }
                    catch { continue; }
                }
            }
        }
        return pts;
    }

    private static readonly double[] EdgeParams = { 0.0, 0.5, 1.0 };

    /// <summary>A face or an edge curve of the target solids, in the order the Python loop visited them
    /// (per solid: faces, then edges): ties between equal distances resolve to the first one.</summary>
    private readonly struct SurfaceItem
    {
        public readonly DB.Face? Face;
        public readonly DB.Curve? Curve;

        public SurfaceItem(DB.Face? face, DB.Curve? curve)
        {
            Face = face;
            Curve = curve;
        }
    }

    /// <summary>Faces and edge curves of the solids, collected once per target set (not once per sample point).</summary>
    private static List<SurfaceItem> SurfaceItems(List<DB.Solid> solids)
    {
        var items = new List<SurfaceItem>();
        foreach (var s in solids)
        {
            foreach (DB.Face face in s.Faces)
                items.Add(new SurfaceItem(face, null));
            foreach (DB.Edge edge in s.Edges)
            {
                try { items.Add(new SurfaceItem(null, edge.AsCurve())); }
                catch { continue; } // the Python projection of such an edge raised and was skipped every time
            }
        }
        return items;
    }

    /// <summary>(distance, closest point) from p to the nearest face or edge, or (null, null).</summary>
    private static double? DistanceTo(DB.XYZ p, List<SurfaceItem> items, out DB.XYZ? bestPt)
    {
        var best = 0.0;
        var has = false;
        bestPt = null;
        for (var k = 0; k < items.Count; k++)
        {
            DB.IntersectionResult? r;
            try
            {
                var it = items[k];
                r = it.Face != null ? it.Face.Project(p) : it.Curve!.Project(p);
            }
            catch { r = null; }
            if (r != null && (!has || r.Distance < best))
            {
                best = r.Distance;
                bestPt = r.XYZPoint;
                has = true;
            }
        }
        return has ? best : null;
    }

    /// <summary>Approximate minimum distance between two solid sets (sampled; never below the true distance):
    /// (distance, point on A, point on B), all null when nothing could be measured. Imported by spatial.py as _min_distance.</summary>
    internal static (double? distance, DB.XYZ? pa, DB.XYZ? pb) MinDistance(List<DB.Solid> solidsA, List<DB.Solid> solidsB, int n)
    {
        double? bestD = null;
        DB.XYZ? bestA = null, bestB = null;
        for (var pass = 0; pass < 2; pass++)
        {
            var flip = pass == 1;
            var src = flip ? solidsB : solidsA;
            var dst = flip ? solidsA : solidsB;
            var items = SurfaceItems(dst);
            foreach (var p in SamplePoints(src, n))
            {
                var d = DistanceTo(p, items, out var q);
                if (d != null && (bestD == null || d.Value < bestD.Value))
                {
                    bestD = d;
                    if (flip)
                    {
                        bestA = q;
                        bestB = p;
                    }
                    else
                    {
                        bestA = p;
                        bestB = q;
                    }
                }
            }
        }
        return (bestD, bestA, bestB);
    }

    private static DB.XYZ BboxCenterOverlap(DB.Outline aOutline, DB.Element bElem, DB.View? view = null)
    {
        var bb = bElem.get_BoundingBox(view);
        DB.XYZ lo = aOutline.MinimumPoint, hi = aOutline.MaximumPoint;
        if (bb == null)
            return (lo + hi) * 0.5;
        var mn = new DB.XYZ(Math.Max(lo.X, bb.Min.X), Math.Max(lo.Y, bb.Min.Y), Math.Max(lo.Z, bb.Min.Z));
        var mx = new DB.XYZ(Math.Min(hi.X, bb.Max.X), Math.Min(hi.Y, bb.Max.Y), Math.Min(hi.Z, bb.Max.Z));
        return (mn + mx) * 0.5;
    }

    private static DB.Outline Outline(DB.Solid solid, double grow = 0.0)
    {
        var bb = solid.GetBoundingBox();
        // the box is in the solid's own frame (bb.Transform may rotate): transform all 8
        // corners so the world-aligned outline really encloses the solid
        var t = bb.Transform;
        double minX = double.MaxValue, minY = double.MaxValue, minZ = double.MaxValue;
        double maxX = double.MinValue, maxY = double.MinValue, maxZ = double.MinValue;
        for (var xi = 0; xi < 2; xi++)
            for (var yi = 0; yi < 2; yi++)
                for (var zi = 0; zi < 2; zi++)
                {
                    var c = t.OfPoint(new DB.XYZ(xi == 0 ? bb.Min.X : bb.Max.X, yi == 0 ? bb.Min.Y : bb.Max.Y,
                        zi == 0 ? bb.Min.Z : bb.Max.Z));
                    if (c.X < minX) minX = c.X;
                    if (c.Y < minY) minY = c.Y;
                    if (c.Z < minZ) minZ = c.Z;
                    if (c.X > maxX) maxX = c.X;
                    if (c.Y > maxY) maxY = c.Y;
                    if (c.Z > maxZ) maxZ = c.Z;
                }
        return new DB.Outline(new DB.XYZ(minX - grow, minY - grow, minZ - grow), new DB.XYZ(maxX + grow, maxY + grow, maxZ + grow));
    }

    /// <summary>Straight grids of the host model as plan lines in `unit` (arc / multi-segment grids skipped).</summary>
    public static List<Dict> ProjectGrids(DB.Document doc, string unit)
    {
        var res = new List<Dict>();
        foreach (DB.Grid g in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Grid)))
        {
            DB.Curve? curve;
            try { curve = g.Curve; }
            catch { continue; } // multi-segment grids have no single curve
            if (curve is not DB.Line c)
                continue;
            var a = c.GetEndPoint(0);
            var b = c.GetEndPoint(1);
            res.Add(new Dict
            {
                ["name"] = Utils.NormalizeString(g.Name),
                ["start"] = new Lst { Pure.Units.FromInternal(a.X, unit, 1), Pure.Units.FromInternal(a.Y, unit, 1) },
                ["end"] = new Lst { Pure.Units.FromInternal(b.X, unit, 1), Pure.Units.FromInternal(b.Y, unit, 1) },
            });
        }
        return res;
    }

    // ---------------------------------------------------------------------- clashes
    /// <summary>The ids of a request list as a set (ints, numeric floats and numeric strings are not mixed up with names).</summary>
    private static HashSet<long> IdSet(object? value)
    {
        var set = new HashSet<long>();
        foreach (var item in Py.ListOf(value))
        {
            if (Py.IsInt(item))
                set.Add(Py.ToInt(item));
            else if (item is double d && d == Math.Floor(d) && !double.IsInfinity(d))
                set.Add((long)d);
        }
        return set;
    }

    public static Dict? Clashes(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var setA = Py.Truthy(ctx.Get("set_a")) ? Obj(ctx.Get("set_a")) : new Dict();
        var setB = Py.Truthy(ctx.Get("set_b")) ? Obj(ctx.Get("set_b")) : new Dict();
        if (setA.Count == 0 || setB.Count == 0)
            throw new RvtssError("set_a and set_b are required, e.g. {categories: ['Ducts']} and {categories: ['Structural Framing']}");
        var unit = ctx.Unit;
        var clearance = ctx.Float("clearance", 0.0) ?? 0.0;
        if (clearance < 0)
            throw new RvtssError("clearance must be >= 0 (distance in `unit`)");
        var clr = clearance != 0.0 ? Pure.Units.ToInternal(clearance, unit) : 0.0;
        var samples = ctx.I("samples", 5, 2, 12);
        var groupBy = ctx.List("group_by");
        foreach (var g in groupBy)
        {
            if (!(g is string gs && Array.IndexOf(Pure.Clash.GroupKeys, gs) >= 0))
                throw new RvtssError("group_by values must be in " + string.Join(", ", Pure.Clash.GroupKeys));
        }
        var maxEl = ctx.Int("max_elements", 2000)!.Value;
        var aElems = PyX.Head(Query.Collect(ctx, setA), maxEl);
        DB.RevitLinkInstance? link = null;
        var bDoc = doc;
        DB.Transform? toB = null;
        DB.Transform? toHost = null;
        if (setB.Get("link_instance_id") != null)
        {
            var linkEl = Core.GetElement(doc, setB["link_instance_id"], "Link");
            if (linkEl is not DB.RevitLinkInstance li || li.GetLinkDocument() == null)
                throw new RvtssError("link_instance_id must be a loaded Revit link", status: 409);
            link = li;
            bDoc = li.GetLinkDocument();
            toHost = li.GetTotalTransform();
            toB = toHost.Inverse;
        }
        var bCats = new List<DB.ElementId>();
        foreach (var c in Py.ListOf(setB.Get("categories")))
            bCats.Add(Core.ResolveCategory(bDoc, c).Id);
        var bIds = IdSet(setB.Get("element_ids"));
        if (ctx.DryRun)
        {
            return new Dict
            {
                ["status"] = "dry_run", ["set_a_count"] = (long)aElems.Count, ["set_b_categories"] = (long)bCats.Count,
                ["clearance"] = clearance, ["unit"] = unit,
                ["against_link"] = link != null ? Utils.NormalizeString(link.Name) : null,
                ["note"] = "No geometry was checked. Run without dry_run to compute clashes.",
            };
        }
        var pairs = new Lst();
        var seen = new HashSet<(long, long)>();
        var maxPairs = ctx.Int("max_pairs", 200)!.Value;
        var computeVolume = ctx.Bool("compute_volume", false);
        long checkedCount = 0;
        var bSolidsCache = new Dictionary<long, List<DB.Solid>>();
        var aInfo = new ElementInfoCache(doc);
        var bInfo = ReferenceEquals(bDoc, doc) ? aInfo : new ElementInfoCache(bDoc);
        // built once: only the bounding box filter changes from solid to solid
        var catFilter = bCats.Count > 0 ? new DB.ElementMulticategoryFilter(Core.ToIdList(bCats)) : null;

        DB.XYZ? HostPt(DB.XYZ? p) => toHost != null && p != null ? toHost.OfPoint(p) : p;

        List<DB.Solid> BSolids(DB.Element b)
        {
            var key = b.Id.Value;
            if (!bSolidsCache.TryGetValue(key, out var list))
            {
                list = Solids(b);
                bSolidsCache[key] = list;
            }
            return list;
        }

        foreach (var a in aElems)
        {
            var solids = Solids(a, toB);
            if (solids.Count == 0)
                continue;
            checkedCount++;
            var aId = a.Id.Value;
            Dict? aBrief = null;
            string? aLevel = null;
            foreach (var s in solids)
            {
                var outline = Outline(s, clr);
                var col = new DB.FilteredElementCollector(bDoc).WhereElementIsNotElementType();
                if (catFilter != null)
                    col = col.WherePasses(catFilter);
                col = col.WherePasses(new DB.BoundingBoxIntersectsFilter(outline));
                var hardFilter = new DB.ElementIntersectsSolidFilter(s);
                foreach (var b in col)
                {
                    var bid = b.Id.Value;
                    if (ReferenceEquals(bDoc, doc) && bid == aId)
                        continue;
                    if (bIds.Count > 0 && !bIds.Contains(bid))
                        continue;
                    var key = link != null || aId < bid ? (aId, bid) : (bid, aId);
                    if (seen.Contains(key))
                        continue;
                    var hard = hardFilter.PassesFilter(b);
                    var distance = 0.0;
                    DB.XYZ point;
                    if (!hard)
                    {
                        if (clr == 0.0)
                            continue;
                        var other = BSolids(b);
                        if (other.Count == 0)
                            continue;
                        var (d, pa, pb) = MinDistance(new List<DB.Solid> { s }, other, samples);
                        if (d == null || d.Value > clr)
                            continue;
                        distance = d.Value;
                        point = (pa! + pb!) * 0.5;
                    }
                    else
                    {
                        point = BboxCenterOverlap(outline, b);
                    }
                    seen.Add(key);
                    if (aBrief == null)
                    {
                        aBrief = aInfo.Brief(a);
                        aLevel = aInfo.Level(a);
                    }
                    var pair = new Dict
                    {
                        ["a"] = new Dict(aBrief), ["b"] = bInfo.Brief(b), ["type"] = hard ? "hard" : "clearance",
                        ["distance"] = hard ? 0.0 : Pure.Units.FromInternal(distance, unit, 1), ["level"] = aLevel,
                    };
                    var hp = HostPt(point);
                    if (hp != null)
                        pair["point"] = Core.XyzList(hp, unit, 1);
                    if (hard && computeVolume && pairs.Count < 50)
                    {
                        var vol = 0.0;
                        foreach (var bs in BSolids(b))
                        {
                            try
                            {
                                var inter = DB.BooleanOperationsUtils.ExecuteBooleanOperation(s, bs, DB.BooleanOperationsType.Intersect);
                                vol += inter != null ? inter.Volume : 0.0;
                            }
                            catch { continue; }
                        }
                        pair["intersection_volume"] = Pure.Units.FromInternal(vol, Pure.Units.LengthUnitFor("volume", unit), 6);
                    }
                    pairs.Add(pair);
                    if (pairs.Count >= maxPairs)
                        break;
                }
                if (pairs.Count >= maxPairs)
                    break;
            }
            if (pairs.Count >= maxPairs)
            {
                ctx.Warn($"Stopped at max_pairs={maxPairs}");
                break;
            }
        }
        var grids = ctx.Bool("locate", true) ? ProjectGrids(doc, unit) : new List<Dict>();
        Pure.Clash.Locate(pairs, grids);
        var groups = new Dict();
        foreach (var g in groupBy)
            groups[(string)g!] = Pure.Clash.GroupClashes(pairs, (string)g!);
        var o = new Dict
        {
            ["elements_checked"] = checkedCount, ["set_a_count"] = (long)aElems.Count, ["clash_count"] = (long)pairs.Count,
            ["hard_count"] = (long)pairs.Count(p => PyX.Eq(((Dict)p!)["type"], "hard")),
            ["clearance_count"] = (long)pairs.Count(p => PyX.Eq(((Dict)p!)["type"], "clearance")),
            ["clearance"] = clearance, ["unit"] = unit,
            ["against_link"] = link != null ? Utils.NormalizeString(link.Name) : null, ["clashes"] = pairs,
            ["groups"] = groups.Count > 0 ? groups : null,
            ["grids"] = ctx.Bool("include_grids", false) ? grids : null,
            ["document"] = Utils.NormalizeString(doc.Title),
            ["created"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm", Inv),
        };
        if (clearance != 0.0)
            o["note"] = $"Clearance distances are sampled ({samples}x{samples} points per face plus edges): they are never "
                        + "below the true distance, so pairs just inside the clearance can be missed - raise "
                        + "`samples` for critical checks.";
        return o;
    }
}
