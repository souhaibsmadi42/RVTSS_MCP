using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>elements.py: MEP runs, openings, shafts, railings, spaces, areas, boundaries, rebar, toposolid,
/// DirectShape mesh (2.3).</summary>
public static partial class Elements
{
    // ------------------------------------------- MEP, openings, shafts, railings (2.3)
    /// <summary>item.get("points") or ([start, end] if start and end else None)</summary>
    private static List<object?>? RawRoute(Dict item)
    {
        if (T(item, "points"))
            return PureText.Iter(item["points"]).ToList();
        if (T(item, "start") && T(item, "end"))
            return new Lst { item["start"], item["end"] };
        return null;
    }

    /// <summary>'points' [[x,y(,z)],...] (or start/end) -> XYZ list. z defaults to level elevation + 'offset'.</summary>
    private static List<DB.XYZ> RoutePoints(Ctx ctx, Dict item, DB.Level? level)
    {
        var raw = RawRoute(item);
        if (raw == null || raw.Count < 2)
            throw new RvtssError("'points' needs at least 2 points (or start and end)").With("failed_item", item);
        var off = Units.ToInternal(item.Get("offset", 0L), ctx.Unit);
        var pts = new List<DB.XYZ>();
        foreach (var p in raw)
        {
            var (x, y, z) = Units.PointFrom(p, ctx.Unit);
            pts.Add(new DB.XYZ(x, y, CoordCount(p) == 3 ? z : NN(level, "Elevation").Elevation + off));
        }
        for (var i = 0; i + 1 < pts.Count; i++)
        {
            if (pts[i].DistanceTo(pts[i + 1]) < 1e-4)
                throw new RvtssError("route has two equal consecutive points").With("failed_item", item);
        }
        return pts;
    }

    private static DB.Connector? EndConnector(DB.MEPCurve curveEl, DB.XYZ point)
    {
        DB.Connector? best = null;
        double? dist = null;
        foreach (DB.Connector c in curveEl.ConnectorManager.Connectors)
        {
            var d = c.Origin.DistanceTo(point);
            if (dist == null || d < dist)
            {
                best = c;
                dist = d;
            }
        }
        return best;
    }

    private static DB.Element MepSystemType(DB.Document doc, Dict item, Type cls, string what)
    {
        var name = item.Get("system_type");
        var types = new DB.FilteredElementCollector(doc).OfClass(cls).ToList();
        if (types.Count == 0)
            throw new RvtssError($"No {what} system type exists in '{doc.Title}'",
                hint: "Use a project started from an MEP template, or load the system types.");
        if (Py.Truthy(name))
        {
            var wanted = Py.Str(name).Trim().ToLowerInvariant();
            foreach (var t in types)
            {
                if (Utils.NormalizeString(Utils.GetElementName(t)).ToLowerInvariant() == wanted)
                    return t;
            }
            throw NotFoundType(what + " system type", name, types.Select(t => Utils.GetElementName(t)));
        }
        return types[0];
    }

    internal static RvtssError NotFoundType(string what, object? name, IEnumerable<string?> names) =>
        new RvtssError($"{what} '{Py.Str(name)}' not found", status: 404)
            .With("available", new HashSet<string>(names.Select(n => Utils.NormalizeString(n)))
                .OrderBy(n => n, StringComparer.Ordinal).Take(50).Cast<object?>().ToList());

    /// <summary>mapping: {'width': [BIP, ...], ...}; values in ctx.unit.</summary>
    private static Dict SetSize(Ctx ctx, DB.Element el, Dict item, Dictionary<string, DB.BuiltInParameter[]> mapping)
    {
        var done = new Dict();
        foreach (var kv in mapping)
        {
            if (item.Get(kv.Key) != null)
            {
                if (SetParam(el, kv.Value, Units.ToInternal(item[kv.Key], ctx.Unit)))
                    done[kv.Key] = item[kv.Key];
            }
        }
        return done;
    }

    private static Dict MepRun(Ctx ctx, Dict item, string kind)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var level = Core.FindLevel(doc, item.Get("level"));
        var pts = RoutePoints(ctx, item, level);
        DB.Element? st = null;
        DB.Element tt;
        Func<DB.XYZ, DB.XYZ, DB.MEPCurve> make;
        Dictionary<string, DB.BuiltInParameter[]> sizes;
        if (kind == "duct")
        {
            st = MepSystemType(doc, item, typeof(DB.Mechanical.MechanicalSystemType), "duct");
            tt = SystemType(doc, item, typeof(DB.Mechanical.DuctType), null, "duct");
            make = (a, b) => DB.Mechanical.Duct.Create(doc, st.Id, tt.Id, NN(level, "Id").Id, a, b);
            sizes = new Dictionary<string, DB.BuiltInParameter[]>
            {
                ["width"] = new[] { DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM },
                ["height"] = new[] { DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM },
                ["diameter"] = new[] { DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM },
            };
        }
        else if (kind == "pipe")
        {
            st = MepSystemType(doc, item, typeof(DB.Plumbing.PipingSystemType), "piping");
            tt = SystemType(doc, item, typeof(DB.Plumbing.PipeType), null, "pipe");
            make = (a, b) => DB.Plumbing.Pipe.Create(doc, st.Id, tt.Id, NN(level, "Id").Id, a, b);
            sizes = new Dictionary<string, DB.BuiltInParameter[]>
            {
                ["diameter"] = new[] { DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM },
            };
        }
        else if (kind == "cable_tray")
        {
            tt = SystemType(doc, item, typeof(DB.Electrical.CableTrayType), null, "cable tray");
            make = (a, b) => DB.Electrical.CableTray.Create(doc, tt.Id, a, b, NN(level, "Id").Id);
            sizes = new Dictionary<string, DB.BuiltInParameter[]>
            {
                ["width"] = new[] { DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM },
                ["height"] = new[] { DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM },
            };
        }
        else // conduit
        {
            tt = SystemType(doc, item, typeof(DB.Electrical.ConduitType), null, "conduit");
            make = (a, b) => DB.Electrical.Conduit.Create(doc, tt.Id, a, b, NN(level, "Id").Id);
            sizes = new Dictionary<string, DB.BuiltInParameter[]>
            {
                ["diameter"] = new[] { DB.BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM },
            };
        }
        var segs = new List<DB.MEPCurve>();
        for (var i = 0; i + 1 < pts.Count; i++)
        {
            var s = make(pts[i], pts[i + 1]);
            SetSize(ctx, s, item, sizes);
            segs.Add(s);
        }
        var fittings = new Lst();
        var fittingErrors = new Lst();
        if (Py.Truthy(item.Get("fittings", true)) && segs.Count > 1)
        {
            doc.Regenerate();
            for (var i = 0; i < segs.Count - 1; i++)
            {
                var joint = pts[i + 1];
                try
                {
                    var f = doc.Create.NewElbowFitting(EndConnector(segs[i], joint), EndConnector(segs[i + 1], joint));
                    fittings.Add(Compat.IdInt(f));
                }
                catch (Exception ex) // routing preferences without an elbow, too-short segment, ...
                {
                    fittingErrors.Add(new Dict { ["joint"] = (long)(i + 1), ["error"] = Utils.NormalizeString(ex.Message) });
                }
            }
        }
        var o = new Dict
        {
            ["kind"] = kind, ["id"] = Compat.IdInt(segs[0]), ["segment_ids"] = segs.Select(s => (object?)Compat.IdInt(s)).ToList(),
            ["type"] = Utils.NormalizeString(Utils.GetElementName(tt)), ["fitting_ids"] = fittings,
        };
        if (kind == "duct" || kind == "pipe")
            o["system_type"] = Utils.NormalizeString(Utils.GetElementName(st));
        if (fittingErrors.Count > 0)
            o["fitting_errors"] = fittingErrors;
        return o;
    }

    /// <summary>Rectangular opening in a straight wall: offset along the wall from its start, width, sill, height.</summary>
    private static Dict WallOpening(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var wall = Core.GetElement(doc, item.Get("wall_id"), "Wall") as DB.Wall;
        if (wall == null || wall.Location is not DB.LocationCurve location)
            throw new RvtssError($"Element {Py.Str(item.Get("wall_id"))} is not a wall with a location line");
        if (location.Curve is not DB.Line line)
            throw new RvtssError("wall_opening needs a straight wall");
        foreach (var key in new[] { "offset_along", "width", "height" })
        {
            if (item.Get(key) == null)
                throw new RvtssError($"'{key}' is required").With("failed_item", item);
        }
        var p0 = line.GetEndPoint(0);
        var d = line.Direction;
        var baseLevel = doc.GetElement(wall.LevelId) as DB.Level;
        var z0 = baseLevel != null ? baseLevel.Elevation : p0.Z;
        try { z0 += wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble(); }
        catch { /* no base offset */ }
        var a = Units.ToInternal(item["offset_along"], ctx.Unit);
        var w = Units.ToInternal(item["width"], ctx.Unit);
        var sill = Units.ToInternal(item.Get("sill", 0L), ctx.Unit);
        var h = Units.ToInternal(item["height"], ctx.Unit);
        if (a < 0 || a + w > line.Length + 1e-6)
            throw new RvtssError($"Opening runs past the wall end (wall length {F0(Units.FromInternal(line.Length, ctx.Unit))} {ctx.Unit})")
                .With("failed_item", item);
        var pa = new DB.XYZ(p0.X + d.X * a, p0.Y + d.Y * a, z0 + sill);
        var pb = new DB.XYZ(p0.X + d.X * (a + w), p0.Y + d.Y * (a + w), z0 + sill + h);
        var op = doc.Create.NewOpening(wall, pa, pb);
        return new Dict { ["kind"] = "wall_opening", ["id"] = Compat.IdInt(op), ["wall_id"] = Compat.IdInt(wall) };
    }

    /// <summary>Opening cut perpendicular through a floor, roof or ceiling from a plan boundary.</summary>
    private static Dict HostOpening(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var host = Core.GetElement(doc, item.Get("host_id"), "Host");
        var lv = Compat.IsValidId(host.LevelId) ? doc.GetElement(host.LevelId) as DB.Level : null;
        var z = lv != null ? lv.Elevation : 0.0;
        var prof = new DB.CurveArray();
        var pts = PointList(item, "boundary", ctx.Unit);
        if (pts.Count < 3)
            throw new RvtssError("'boundary' needs at least 3 points").With("failed_item", item);
        for (var i = 0; i < pts.Count; i++)
        {
            var a = pts[i];
            var b = pts[(i + 1) % pts.Count];
            prof.Append(DB.Line.CreateBound(new DB.XYZ(a.x, a.y, z), new DB.XYZ(b.x, b.y, z)));
        }
        var op = doc.Create.NewOpening(host, prof, true);
        return new Dict { ["kind"] = "opening", ["id"] = Compat.IdInt(op), ["host_id"] = Compat.IdInt(host) };
    }

    private static Dict Shaft(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var bottom = Core.FindLevel(doc, T(item, "level") ? item["level"] : item.Get("base_level"));
        var top = Core.FindLevel(doc, item.Get("top_level"));
        var prof = new DB.CurveArray();
        foreach (var ln in Outline(ctx, item, bottom))
            prof.Append(ln);
        var op = doc.Create.NewOpening(bottom, top, prof);
        if (item.Get("base_offset") != null)
            SetParam(op, new[] { DB.BuiltInParameter.WALL_BASE_OFFSET }, Units.ToInternal(item["base_offset"], ctx.Unit));
        if (item.Get("top_offset") != null)
            SetParam(op, new[] { DB.BuiltInParameter.WALL_TOP_OFFSET }, Units.ToInternal(item["top_offset"], ctx.Unit));
        return new Dict { ["kind"] = "shaft", ["id"] = Compat.IdInt(op) };
    }

    private static Dict Railing(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var rt = SystemType(doc, item, typeof(DB.Architecture.RailingType), null, "railing");
        if (item.Get("host_id") != null) // stairs or ramp
        {
            var host = Core.GetElement(doc, item["host_id"], "Stairs/ramp");
            var positionValue = item.Get("position", "treads");
            var positionName = positionValue is string ps ? Title(ps) : throw NoAttr(positionValue, "title");
            var pos = Py.EnumOrNull<DB.Architecture.RailingPlacementPosition>(positionName)
                      ?? DB.Architecture.RailingPlacementPosition.Treads;
            var ids = DB.Architecture.Railing.Create(doc, host.Id, rt.Id, pos);
            return new Dict
            {
                ["kind"] = "railing", ["ids"] = ids.Select(i => (object?)Compat.IdInt(i)).ToList(),
                ["type"] = Utils.NormalizeString(Utils.GetElementName(rt)),
            };
        }
        var level = Core.FindLevel(doc, item.Get("level"));
        var pts = RoutePoints(ctx, item, level);
        var loop = new DB.CurveLoop();
        for (var i = 0; i + 1 < pts.Count; i++)
            loop.Append(DB.Line.CreateBound(pts[i], pts[i + 1]));
        var r = DB.Architecture.Railing.Create(doc, loop, rt.Id, NN(level, "Id").Id);
        return new Dict { ["kind"] = "railing", ["id"] = Compat.IdInt(r), ["type"] = Utils.NormalizeString(Utils.GetElementName(rt)) };
    }

    // ------------------------------- spaces, areas, boundaries, rebar, toposolid, mesh (2.3)
    private static void NamedSpatial(DB.Element el, Dict item)
    {
        if (T(item, "name"))
            SetParam(el, new[] { DB.BuiltInParameter.ROOM_NAME }, Py.Str(item["name"]));
        if (item.Get("number") != null)
            SetParam(el, new[] { DB.BuiltInParameter.ROOM_NUMBER }, Py.Str(item["number"]));
    }

    private static Dict Space(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var level = Core.FindLevel(doc, item.Get("level"));
        var (x, y, _) = Units.PointFrom(item.Get("point"), ctx.Unit);
        var sp = doc.Create.NewSpace(level, new DB.UV(x, y));
        NamedSpatial(sp, item);
        return new Dict { ["kind"] = "space", ["id"] = Compat.IdInt(sp) };
    }

    private static DB.ViewPlan AreaView(Ctx ctx, Dict item)
    {
        var v = Core.FindView(ctx.Doc, T(item, "area_view") ? item["area_view"] : item.Get("view"), defaultActive: true, uidoc: ctx.UiDoc)!;
        if (v is not DB.ViewPlan plan || v.ViewType != DB.ViewType.AreaPlan)
            throw new RvtssError($"'area_view' must be an area plan (got {v.ViewType})",
                hint: "Create one with create_view(kind='area_plan').");
        return plan;
    }

    private static Dict Area(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var v = AreaView(ctx, item);
        var (x, y, _) = Units.PointFrom(item.Get("point"), ctx.Unit);
        var a = doc.Create.NewArea(v, new DB.UV(x, y));
        NamedSpatial(a, item);
        return new Dict { ["kind"] = "area", ["id"] = Compat.IdInt(a), ["area_view_id"] = Compat.IdInt(v) };
    }

    /// <summary>area_boundary (area plan) or room_separation / space_separation (plan view) lines from 'points'.</summary>
    private static Dict BoundaryLines(Ctx ctx, Dict item, string kind)
    {
        var doc = ctx.Doc;
        DB.ViewPlan v;
        double z;
        if (kind == "area_boundary")
        {
            v = AreaView(ctx, item);
            z = v.GenLevel != null ? v.GenLevel.Elevation : 0.0;
        }
        else
        {
            var view = Core.FindView(doc, item.Get("view"), defaultActive: true, uidoc: ctx.UiDoc);
            if (view is not DB.ViewPlan plan || plan.GenLevel == null)
                throw new RvtssError($"'view' must be a floor plan for {kind} lines");
            v = plan;
            z = plan.GenLevel.Elevation;
        }
        var raw = T(item, "points") ? PureText.Iter(item["points"]).ToList() : new Lst();
        if (raw.Count < 2)
            throw new RvtssError("'points' needs at least 2 points").With("failed_item", item);
        var pts = raw.Select(p => Units.PointFrom(p, ctx.Unit)).ToList();
        if (T(item, "closed"))
            pts.Add(pts[0]);
        var curves = new DB.CurveArray();
        for (var i = 0; i + 1 < pts.Count; i++)
        {
            var a = pts[i];
            var b = pts[i + 1];
            curves.Append(DB.Line.CreateBound(new DB.XYZ(a.x, a.y, z), new DB.XYZ(b.x, b.y, z)));
        }
        var sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, new DB.XYZ(0, 0, z)));
        var ids = new Lst();
        if (kind == "area_boundary")
        {
            foreach (DB.Curve c in curves)
                ids.Add(Compat.IdInt(doc.Create.NewAreaBoundaryLine(sp, c, v)));
        }
        else if (kind == "room_separation")
        {
            foreach (DB.ModelCurve m in doc.Create.NewRoomBoundaryLines(sp, curves, v))
                ids.Add(Compat.IdInt(m));
        }
        else
        {
            foreach (DB.ModelCurve m in doc.Create.NewSpaceBoundaryLines(sp, curves, v))
                ids.Add(Compat.IdInt(m));
        }
        return new Dict { ["kind"] = kind, ["ids"] = ids, ["view_id"] = Compat.IdInt(v) };
    }

    private static Dict AutoRooms(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var level = Core.FindLevel(doc, item.Get("level"));
        var ids = doc.Create.NewRooms2(level).ToList();
        return new Dict
        {
            ["kind"] = "auto_rooms", ["ids"] = ids.Select(i => (object?)Compat.IdInt(i)).ToList(), ["count"] = (long)ids.Count,
        };
    }

    /// <summary>Rebar from a polyline in a host (beam, column, wall, floor, foundation), optional fixed-number layout.</summary>
    private static Dict Rebar(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var host = Core.GetElement(doc, item.Get("host_id"), "Host");
        if (!DB.Structure.RebarHostData.IsValidHost(host))
            throw new RvtssError($"Element {Compat.IdInt(host)} cannot host rebar");
        var bt = SystemType(doc, item, typeof(DB.Structure.RebarBarType), null, "rebar bar");
        var raw = T(item, "points") ? PureText.Iter(item["points"]).ToList() : new Lst();
        if (raw.Count < 2)
            throw new RvtssError("'points' needs at least 2 [x, y, z] points (bar centre line)").With("failed_item", item);
        var pts = raw.Select(p => Xyz(Units.PointFrom(p, ctx.Unit))).ToList();
        var curves = new List<DB.Curve>();
        for (var i = 0; i + 1 < pts.Count; i++)
            curves.Add(DB.Line.CreateBound(pts[i], pts[i + 1]));
        var n3 = T(item, "normal") ? PureText.Iter(item["normal"]).ToList() : new Lst { 0L, 0L, 1L };
        if (n3.Count != 3)
            throw new FormatException(n3.Count > 3 ? "too many values to unpack" : $"need more than {n3.Count} values to unpack");
        var normal = new DB.XYZ(Py.ToFloat(n3[0]), Py.ToFloat(n3[1]), Py.ToFloat(n3[2])).Normalize();
        var style = item.Get("style") is string styleName && styleName == "stirrup_tie"
            ? DB.Structure.RebarStyle.StirrupTie
            : DB.Structure.RebarStyle.Standard;
        var bar = CreateRebar(doc, style, (DB.Structure.RebarBarType)bt, host, normal, curves);
        if (bar == null)
            throw new RvtssError("Revit could not create the bar (curves outside the host or not planar?)");
        var o = new Dict { ["kind"] = "rebar", ["id"] = Compat.IdInt(bar), ["bar_type"] = Utils.NormalizeString(Utils.GetElementName(bt)) };
        if (T(item, "count"))
        {
            var n = (int)Py.ToInt(item["count"]);
            var spacing = Units.ToInternal(item.Get("spacing", 200L), ctx.Unit);
            bar.GetShapeDrivenAccessor().SetLayoutAsFixedNumber(n, spacing * (n - 1), true, true, true);
            o["layout"] = new Dict { ["count"] = (long)n, ["spacing"] = item.Get("spacing", 200L) };
        }
        return o;
    }

    /// <summary>Rebar.CreateFromCurves without hooks, hook orientation left / left, existing shape if possible.</summary>
    private static DB.Structure.Rebar? CreateRebar(DB.Document doc, DB.Structure.RebarStyle style, DB.Structure.RebarBarType barType,
        DB.Element host, DB.XYZ normal, IList<DB.Curve> curves)
    {
#if REVIT2027_OR_GREATER
        // Revit 2027 removed the hook overload and RebarHookOrientation: the same request as terminations data
        // (no hook types, orientation left at both ends)
        var terminations = new DB.Structure.BarTerminationsData(doc)
        {
            TerminationOrientationAtStart = DB.Structure.RebarTerminationOrientation.Left,
            TerminationOrientationAtEnd = DB.Structure.RebarTerminationOrientation.Left,
        };
        return DB.Structure.Rebar.CreateFromCurves(doc, style, barType, host, normal, curves, terminations, true, true);
#else
#pragma warning disable CS0618 // the hook overload is the one the Python code calls; it is obsolete from Revit 2026
        return DB.Structure.Rebar.CreateFromCurves(doc, style, barType, null, null, host, normal, curves,
            DB.Structure.RebarHookOrientation.Left, DB.Structure.RebarHookOrientation.Left, true, true);
#pragma warning restore CS0618
#endif
    }

    private static Dict Toposolid(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        // Toposolid exists on every supported version (Revit 2024 or later)
        var level = Core.FindLevel(doc, item.Get("level"));
        var tt = SystemType(doc, item, typeof(DB.ToposolidType), null, "toposolid");
        var raw = T(item, "points") ? PureText.Iter(item["points"]).ToList() : new Lst();
        if (raw.Count < 3)
            throw new RvtssError("'points' needs at least 3 [x, y, z] survey points").With("failed_item", item);
        var pts = new List<DB.XYZ>();
        foreach (var p in raw)
            pts.Add(Xyz(Units.PointFrom(p, ctx.Unit)));
        var ts = DB.Toposolid.Create(doc, pts, tt.Id, NN(level, "Id").Id);
        return new Dict { ["kind"] = "toposolid", ["id"] = Compat.IdInt(ts), ["type"] = Utils.NormalizeString(Utils.GetElementName(tt)) };
    }

    private static (List<double[]> verts, Lst faces) ReadObj(string path, int limit = 200000)
    {
        var verts = new List<double[]>();
        var faces = new Lst();
        IEnumerable<string> lines;
        try
        {
            lines = File.ReadAllLines(path);
        }
        catch (Exception e) when (e is FileNotFoundException || e is DirectoryNotFoundException)
        {
            throw new IOError($"[Errno 2] {e.Message}: {path}");
        }
        foreach (var line in lines)
        {
            var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0)
                continue;
            if (parts[0] == "v" && parts.Length >= 4)
            {
                verts.Add(new[] { Py.ToFloat(parts[1]), Py.ToFloat(parts[2]), Py.ToFloat(parts[3]) });
            }
            else if (parts[0] == "f" && parts.Length >= 4)
            {
                var face = new Lst();
                foreach (var x in parts.Skip(1))
                    face.Add(Py.ToInt(x.Split('/')[0]) - 1);
                faces.Add(face);
                if (faces.Count > limit)
                    throw new RvtssError("Mesh has more than " + limit.ToString(CultureInfo.InvariantCulture) + " faces");
            }
        }
        return (verts, faces);
    }

    /// <summary>DirectShape mesh: inline vertices/faces (in `unit`, faces = vertex index lists) or an .obj file.</summary>
    private static Dict DirectShape(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        List<double[]> verts;
        Lst faces;
        if (T(item, "obj_file"))
        {
            (verts, faces) = ReadObj(Py.Str(item["obj_file"]));
            var scale = Units.ToInternal(1.0, T(item, "obj_unit") ? Py.Str(item["obj_unit"]) : ctx.Unit);
            verts = verts.Select(v => new[] { v[0] * scale, v[1] * scale, v[2] * scale }).ToList();
        }
        else
        {
            verts = PointList(item, "vertices", ctx.Unit).Select(v => new[] { v.x, v.y, v.z }).ToList();
            faces = T(item, "faces") ? PureText.Iter(item["faces"]).ToList() : new Lst();
        }
        if (verts.Count < 3 || faces.Count == 0)
            throw new RvtssError("direct_shape needs 'vertices' + 'faces' or 'obj_file'").With("failed_item", item);
        var cat = Core.ResolveCategory(doc, T(item, "category") ? item["category"] : "Generic Models");
        var mat = DB.ElementId.InvalidElementId;
        if (T(item, "material"))
        {
            var wanted = Py.Str(item["material"]).Trim().ToLowerInvariant();
            var m = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Material))
                .FirstOrDefault(x => Utils.NormalizeString(x.Name).ToLowerInvariant() == wanted);
            if (m != null)
                mat = m.Id;
        }
        var b = new DB.TessellatedShapeBuilder();
        b.OpenConnectedFaceSet(false);
        foreach (var f in faces)
        {
            var loop = new List<DB.XYZ>();
            foreach (var i in PureText.Iter(f))
            {
                var index = Py.ToInt(i);
                if (index < 0) // a negative index counts from the end, as in a Python list
                    index += verts.Count;
                if (index < 0 || index >= verts.Count)
                    throw new IndexOutOfRangeException("index out of range: " + Py.Str(Py.ToInt(i)));
                var v = verts[(int)index];
                loop.Add(new DB.XYZ(v[0], v[1], v[2]));
            }
            b.AddFace(new DB.TessellatedFace(loop, mat));
        }
        b.CloseConnectedFaceSet();
        b.Target = DB.TessellatedShapeBuilderTarget.AnyGeometry;
        b.Fallback = DB.TessellatedShapeBuilderFallback.Mesh;
        b.Build();
        var res = b.GetBuildResult();
        var ds = DB.DirectShape.CreateElement(doc, cat.Id);
        ds.SetShape(res.GetGeometricalObjects());
        if (T(item, "name"))
            ds.Name = Py.Str(item["name"]);
        return new Dict
        {
            ["kind"] = "direct_shape", ["id"] = Compat.IdInt(ds), ["faces"] = (long)faces.Count,
            ["outcome"] = res.Outcome.ToString(), ["category"] = Utils.NormalizeString(cat.Name),
        };
    }
}
