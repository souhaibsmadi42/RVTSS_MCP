namespace RvtssHost.Modules;

/// <summary>
/// Coordinates and spatial queries (RVTSS v2.2). Read-only. Port of revit_mcp/spatial.py.
///
/// Routes:
///     POST /coordinates/       internal origin, project base point, survey point, true north, project locations,
///                              link transforms; optional internal -> shared conversion of points
///     POST /spatial/query/     distance between elements, elements in a box / near a point, ray cast in a 3D view
/// </summary>
public static class Spatial
{
    private const double DegPerRad = 180.0 / Math.PI;

    public static void Register(RouteTable api)
    {
        api.Post("/coordinates/", Coordinates, "coordinates");
        api.Post("/spatial/query/", SpatialQuery, "spatial_query");
    }

    /// <summary>
    /// Internal -> shared coordinates through the active ProjectLocation transform.
    ///
    /// ProjectLocation.GetProjectPosition is only documented for the origin, so points use
    /// GetTotalTransform(). Its direction is checked against a base point whose shared position Revit
    /// reports itself (survey point, then project base point); `verified` says whether that check ran.
    /// </summary>
    internal sealed class SharedConverter
    {
        public string Method;
        public bool Verified;
        public DB.Transform Transform;

        public SharedConverter(DB.Document doc, DB.ProjectLocation location)
        {
            var tr = location.GetTotalTransform();
            var candidates = new[] { ("transform_inverse", tr.Inverse), ("transform", tr) };
            Transform = candidates[0].Item2;
            Method = candidates[0].Item1;
            Verified = false;
            foreach (var getter in new Func<DB.Document, DB.BasePoint>[] { DB.BasePoint.GetSurveyPoint, DB.BasePoint.GetProjectBasePoint })
            {
                DB.XYZ internalPos, shared;
                try
                {
                    var bp = getter(doc);
                    internalPos = bp.Position;
                    shared = bp.SharedPosition;
                }
                catch { continue; }
                // only the first base point that can be read decides, as in the Python loop
                foreach (var (name, t) in candidates)
                {
                    if (t.OfPoint(internalPos).DistanceTo(shared) < 1e-4)
                    {
                        Transform = t;
                        Method = name;
                        Verified = true;
                        return;
                    }
                }
                return;
            }
        }

        public Dict Convert(DB.XYZ p, string unit)
        {
            var q = Transform.OfPoint(p);
            return new Dict
            {
                ["east_west"] = Pure.Units.FromInternal(q.X, unit, 1), ["north_south"] = Pure.Units.FromInternal(q.Y, unit, 1),
                ["elevation"] = Pure.Units.FromInternal(q.Z, unit, 1),
            };
        }
    }

    private static Dict? BasePointInfo(Func<DB.BasePoint?> getter, SharedConverter conv, string unit)
    {
        DB.BasePoint? bp;
        try { bp = getter(); }
        catch { return null; }
        if (bp == null)
            return null;
        var o = new Dict { ["id"] = bp.Id.Value };
        try
        {
            o["internal"] = Core.XyzList(bp.Position, unit);
            o["shared"] = Core.XyzList(bp.SharedPosition, unit);
        }
        catch
        {
            try { o["shared"] = conv.Convert(bp.Position, unit); }
            catch { /* no shared position either */ }
        }
        try
        {
            o["pinned"] = bp.Pinned;
            o["clipped"] = bp.Clipped;
        }
        catch { /* not available */ }
        return o;
    }

    public static Dict? Coordinates(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var unit = ctx.Unit;
        var loc = doc.ActiveProjectLocation;
        var conv = new SharedConverter(doc, loc);
        var o = new Dict
        {
            ["unit"] = unit, ["active_location"] = Utils.NormalizeString(loc.Name),
            ["shared_conversion"] = new Dict { ["method"] = conv.Method, ["verified_against_base_point"] = conv.Verified },
        };
        try
        {
            var originPos = loc.GetProjectPosition(DB.XYZ.Zero);
            o["angle_to_true_north_deg"] = Py.Round(originPos.Angle * DegPerRad, 6);
            o["internal_origin_in_shared"] = conv.Convert(DB.XYZ.Zero, unit);
        }
        catch (Exception e)
        {
            o["warnings"] = new Lst { "Project position unavailable: " + e.Message };
        }
        o["project_base_point"] = BasePointInfo(() => DB.BasePoint.GetProjectBasePoint(doc), conv, unit);
        o["survey_point"] = BasePointInfo(() => DB.BasePoint.GetSurveyPoint(doc), conv, unit);
        try
        {
            var names = new Lst();
            foreach (DB.ProjectLocation l in doc.ProjectLocations)
                names.Add(Utils.NormalizeString(l.Name));
            o["project_locations"] = names;
        }
        catch { /* not available */ }
        try
        {
            var site = doc.SiteLocation;
            o["site"] = new Dict
            {
                ["place"] = Utils.NormalizeString(site.PlaceName), ["latitude_deg"] = Py.Round(site.Latitude * DegPerRad, 6),
                ["longitude_deg"] = Py.Round(site.Longitude * DegPerRad, 6),
            };
        }
        catch { /* no site location */ }
        var links = new Lst();
        var positioning = Py.EnumOrNull<DB.BuiltInParameter>("RVT_LINK_INSTANCE_POSITIONING");
        foreach (DB.RevitLinkInstance inst in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.RevitLinkInstance)))
        {
            var d = new Dict { ["instance_id"] = inst.Id.Value, ["name"] = Utils.NormalizeString(inst.Name) };
            try
            {
                var tr = inst.GetTotalTransform();
                d["origin_internal"] = Core.XyzList(tr.Origin, unit);
                d["rotation_deg"] = Py.Round(Math.Atan2(tr.BasisX.Y, tr.BasisX.X) * DegPerRad, 6);
                d["origin_shared"] = conv.Convert(tr.Origin, unit);
                d["is_identity"] = tr.IsIdentity;
            }
            catch { /* keep what was read */ }
            try
            {
                var p = positioning != null ? inst.get_Parameter(positioning.Value) : null;
                if (p != null)
                    d["positioning"] = Utils.NormalizeString(p.AsValueString() ?? "");
            }
            catch { /* not available */ }
            links.Add(d);
        }
        o["links"] = links;
        var pts = ctx.List("points");
        if (pts.Count > 0)
        {
            var converted = new Lst();
            foreach (var p in PyX.Head(pts, 200))
            {
                var (x, y, z) = Pure.Units.PointFrom(p, unit);
                converted.Add(new Dict { ["internal"] = new Lst(PyX.Items(p)), ["shared"] = conv.Convert(new DB.XYZ(x, y, z), unit) });
            }
            o["converted_points"] = converted;
        }
        return o;
    }

    // ------------------------------------------------------------------ spatial query
    /// <summary>Gap between two bounding boxes (0 when they overlap).</summary>
    private static double? BboxGap(DB.BoundingBoxXYZ? a, DB.BoundingBoxXYZ? b)
    {
        if (a == null || b == null)
            return null;
        var dx = Math.Max(0.0, Math.Max(a.Min.X, b.Min.X) - Math.Min(a.Max.X, b.Max.X));
        var dy = Math.Max(0.0, Math.Max(a.Min.Y, b.Min.Y) - Math.Min(a.Max.Y, b.Max.Y));
        var dz = Math.Max(0.0, Math.Max(a.Min.Z, b.Min.Z) - Math.Min(a.Max.Z, b.Max.Z));
        return Math.Sqrt(dx * dx + dy * dy + dz * dz);
    }

    private static DB.ElementMulticategoryFilter? CatFilter(DB.Document doc, Lst cats)
    {
        if (cats.Count == 0)
            return null;
        var ids = new List<DB.ElementId>();
        foreach (var c in cats)
            ids.Add(Core.ResolveCategory(doc, c).Id);
        return new DB.ElementMulticategoryFilter(ids);
    }

    private static List<DB.Element> BoxQuery(DB.Document doc, DB.XYZ lo, DB.XYZ hi, Lst cats, long limit, ICollection<long>? exclude = null)
    {
        var col = new DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
            .WherePasses(new DB.BoundingBoxIntersectsFilter(new DB.Outline(lo, hi)));
        var f = CatFilter(doc, cats);
        if (f != null)
            col = col.WherePasses(f);
        var res = new List<DB.Element>();
        foreach (var e in col)
        {
            if ((exclude != null && exclude.Contains(e.Id.Value)) || e.Category == null
                || e.Category.CategoryType != DB.CategoryType.Model)
                continue;
            res.Add(e);
            if (res.Count >= limit)
                break;
        }
        return res;
    }

    private static DB.View3D View3d(DB.Document doc, object? name)
    {
        if (Py.Truthy(name))
        {
            var v = Core.FindView(doc, name);
            if (v is not DB.View3D v3 || v3.IsTemplate)
                throw new RvtssError("ray casting needs a 3D view (not a template)");
            return v3;
        }
        foreach (DB.View3D v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View3D)))
        {
            if (!v.IsTemplate && !v.IsPerspective)
                return v;
        }
        throw new RvtssError("No 3D view in the model", hint: "Create one with create_view(kind='three_d').");
    }

    public static Dict? SpatialQuery(Ctx ctx)
    {
        var doc = ctx.Doc;
        var unit = ctx.Unit;
        var modeValue = ctx.Require("mode");
        var mode = modeValue as string;
        var limit = ctx.I("limit", 100, 1, 1000);
        var cats = ctx.List("categories");
        if (mode == "distance")
        {
            var a = Core.GetElement(doc, ctx.Require("element_a"));
            var b = Core.GetElement(doc, ctx.Require("element_b"));
            DB.XYZ? pa = Core.ElementPoint(a), pb = Core.ElementPoint(b);
            var gap = BboxGap(a.get_BoundingBox(null), b.get_BoundingBox(null));
            var o = new Dict
            {
                ["element_a"] = Core.ElementBrief(doc, a), ["element_b"] = Core.ElementBrief(doc, b), ["unit"] = unit,
                ["center_distance"] = pa != null && pb != null ? Pure.Units.FromInternal(pa.DistanceTo(pb), unit, 1) : (double?)null,
                ["bbox_gap"] = gap != null ? Pure.Units.FromInternal(gap.Value, unit, 1) : (double?)null,
            };
            if (ctx.Bool("exact", true))
            {
                var sa = Qc.Solids(a);
                var sb = Qc.Solids(b);
                if (sa.Count > 0 && sb.Count > 0)
                {
                    var (d, p1, p2) = Qc.MinDistance(sa, sb, ctx.I("samples", 4, 2, 10));
                    if (d != null)
                    {
                        o["surface_distance"] = Pure.Units.FromInternal(d.Value, unit, 1);
                        o["closest_points"] = new Lst { Core.XyzList(p1!, unit), Core.XyzList(p2!, unit) };
                        o["surface_distance_note"] = "sampled over faces and edges: never below the true distance";
                    }
                }
                else
                {
                    o["surface_distance_note"] = "no solid geometry on one of the elements";
                }
            }
            return o;
        }
        if (mode == "in_box")
        {
            var a = Pure.Units.PointFrom(ctx.Require("min"), unit);
            var b = Pure.Units.PointFrom(ctx.Require("max"), unit);
            var lo = new DB.XYZ(Math.Min(a.x, b.x), Math.Min(a.y, b.y), Math.Min(a.z, b.z));
            var hi = new DB.XYZ(Math.Max(a.x, b.x), Math.Max(a.y, b.y), Math.Max(a.z, b.z));
            var found = BoxQuery(doc, lo, hi, cats, limit);
            return new Dict
            {
                ["mode"] = mode, ["count"] = (long)found.Count, ["truncated"] = found.Count >= limit,
                ["elements"] = found.Select(e => (object?)Core.ElementBrief(doc, e)).ToList(),
            };
        }
        if (mode == "near_point")
        {
            var pt = Pure.Units.PointFrom(ctx.Require("point"), unit);
            var c = new DB.XYZ(pt.x, pt.y, pt.z);
            var r = Pure.Units.ToInternal(ctx.F("radius", 1000.0), unit);
            var found = BoxQuery(doc, c - new DB.XYZ(r, r, r), c + new DB.XYZ(r, r, r), cats, 5000);
            var rows = new List<Dict>();
            foreach (var e in found)
            {
                var p = Core.ElementPoint(e);
                double? d = p != null ? p.DistanceTo(c) : null;
                if (d != null && d.Value <= r)
                {
                    var brief = Core.ElementBrief(doc, e);
                    brief["distance"] = Pure.Units.FromInternal(d.Value, unit, 1);
                    rows.Add(brief);
                }
            }
            // list.sort is stable, as is OrderBy
            rows = rows.OrderBy(x => (double)x["distance"]!).ToList();
            return new Dict
            {
                ["mode"] = mode, ["count"] = (long)rows.Count, ["unit"] = unit, ["elements"] = PyX.Head(rows, limit),
                ["note"] = "distance from each element's location point / curve midpoint / box centre",
            };
        }
        if (mode == "raycast")
        {
            var pt = Pure.Units.PointFrom(ctx.Require("point"), unit);
            var origin = new DB.XYZ(pt.x, pt.y, pt.z);
            var dirList = ctx.List("direction");
            if (dirList.Count == 0)
                dirList = new Lst { 0L, 0L, -1L };
            var dirVals = dirList.Select(Py.ToFloat).ToList();
            if (dirVals.Count != 3)
                throw new Compat.ValueError(dirVals.Count < 3
                    ? "need more than " + dirVals.Count + " values to unpack"
                    : "too many values to unpack");
            var direction = new DB.XYZ(dirVals[0], dirVals[1], dirVals[2]);
            if (direction.GetLength() < 1e-9)
                throw new RvtssError("direction must not be zero");
            var view = View3d(doc, ctx.Get("view"));
            DB.ElementFilter f = (DB.ElementFilter?)CatFilter(doc, cats) ?? new DB.ElementIsElementTypeFilter(true);
            var ri = new DB.ReferenceIntersector(f, DB.FindReferenceTarget.Element, view);
            ri.FindReferencesInRevitLinks = ctx.Bool("include_links", false);
            var hits = new List<Dict>();
            var seen = new HashSet<(long, long)>();
            foreach (var ctxref in ri.Find(origin, direction.Normalize()).OrderBy(x => x.Proximity))
            {
                var reference = ctxref.GetReference();
                var key = (reference.ElementId.Value, reference.LinkedElementId.Value);
                if (!seen.Add(key))
                    continue;
                var e = doc.GetElement(reference.ElementId);
                var h = e != null ? Core.ElementBrief(doc, e) : new Dict { ["id"] = key.Item1 };
                h["distance"] = Pure.Units.FromInternal(ctxref.Proximity, unit, 1);
                try { h["hit_point"] = Core.XyzList(reference.GlobalPoint, unit); }
                catch { /* no global point */ }
                if (key.Item2 > 0)
                    h["linked_element_id"] = key.Item2;
                hits.Add(h);
                if (hits.Count >= limit)
                    break;
            }
            return new Dict
            {
                ["mode"] = mode, ["view"] = Utils.NormalizeString(view.Name), ["unit"] = unit, ["hits"] = hits,
                ["nearest"] = hits.Count > 0 ? hits[0] : null,
                ["note"] = "Only elements visible in the 3D view are hit (section box and hidden categories apply).",
            };
        }
        throw new RvtssError("mode must be distance, in_box, near_point or raycast");
    }
}
