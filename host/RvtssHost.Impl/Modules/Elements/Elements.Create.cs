namespace RvtssHost.Modules;

/// <summary>elements.py: create_elements, the basic kinds and roofs / ceilings / structure (2.2).</summary>
public static partial class Elements
{
    // ----------------------------------------------------------------------- create
    private static DB.XYZ Pt(Ctx ctx, Dict item, string key)
    {
        var v = item.Get(key);
        if (v == null)
            throw new RvtssError($"'{key}' is required").With("failed_item", item);
        return Xyz(Units.PointFrom(v, ctx.Unit));
    }

    private static DB.Line Line(Ctx ctx, Dict item)
    {
        var a = Pt(ctx, item, "start");
        var b = Pt(ctx, item, "end");
        if (a.DistanceTo(b) < 1e-4)
            throw new RvtssError("start and end are the same point").With("failed_item", item);
        return DB.Line.CreateBound(a, b);
    }

    /// <summary>[U.point_from(p, unit) for p in item.get(key) or []]</summary>
    private static List<(double x, double y, double z)> PointList(Dict item, string key, string unit)
    {
        var raw = item.Get(key);
        var pts = new List<(double x, double y, double z)>();
        if (!Py.Truthy(raw))
            return pts;
        foreach (var p in PureText.Iter(raw))
            pts.Add(Units.PointFrom(p, unit));
        return pts;
    }

    /// <summary>float(item.get(key, 0) or 0)</summary>
    private static double FloatOrZero(Dict item, string key) => T(item, key) ? Py.ToFloat(item[key]) : 0.0;

    /// <summary>The FamilySymbol core.find_type found; any other type fails where Python read sym.IsActive.</summary>
    private static DB.FamilySymbol AsSymbol(DB.ElementType t) => t as DB.FamilySymbol ?? throw NoAttr(t, "IsActive");

    private static Dict CreateOne(Ctx ctx, object? rawItem)
    {
        var item = ItemDict(rawItem);
        var doc = ctx.Doc;
        var kindValue = item.Get("kind");
        var kind = kindValue as string;
        var unit = ctx.Unit;
        if (kind == "level")
        {
            var lv = DB.Level.Create(doc, Units.ToInternal(item.Get("elevation", 0L), unit));
            if (T(item, "name"))
                lv.Name = Py.Str(item["name"]);
            var o = new Dict { ["kind"] = kind, ["id"] = Compat.IdInt(lv), ["name"] = lv.Name };
            if (Py.Truthy(item.Get("create_plan_view", false)))
            {
                var vft = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewFamilyType)).Cast<DB.ViewFamilyType>()
                    .First(t => t.ViewFamily == DB.ViewFamily.FloorPlan);
                o["plan_view_id"] = Compat.IdInt(DB.ViewPlan.Create(doc, vft.Id, lv.Id));
            }
            return o;
        }
        if (kind == "grid")
        {
            var g = DB.Grid.Create(doc, Line(ctx, item));
            if (T(item, "name"))
                g.Name = Py.Str(item["name"]);
            return new Dict { ["kind"] = kind, ["id"] = Compat.IdInt(g), ["name"] = g.Name };
        }
        if (kind == "wall")
        {
            var level = Core.FindLevel(doc, item.Get("level"));
            DB.Element? wt = T(item, "type") || T(item, "type_id")
                ? Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"),
                    typeId: item.Get("type_id"), ofClass: typeof(DB.WallType))
                : doc.GetElement(doc.GetDefaultElementTypeId(DB.ElementTypeGroup.WallType));
            var height = Units.ToInternal(item.Get("height", 3000L), unit);
            var offset = Units.ToInternal(item.Get("base_offset", 0L), unit);
            // argument order of the Python call: the line, then wt.Id, then level.Id
            var line = Line(ctx, item);
            var wallTypeId = NN(wt, "Id").Id;
            var levelId = NN(level, "Id").Id;
            var w = DB.Wall.Create(doc, line, wallTypeId, levelId, height, offset,
                Py.Truthy(item.Get("flip", false)), Py.Truthy(item.Get("structural", false)));
            return new Dict { ["kind"] = kind, ["id"] = Compat.IdInt(w), ["type"] = Utils.NormalizeString(Utils.GetElementName(wt)) };
        }
        if (kind == "floor")
        {
            var level = Core.FindLevel(doc, item.Get("level"));
            var pts = PointList(item, "boundary", unit);
            if (pts.Count < 3)
                throw new RvtssError("floor needs a 'boundary' of at least 3 points").With("failed_item", item);
            var loop = new DB.CurveLoop();
            for (var i = 0; i < pts.Count; i++)
            {
                var a = pts[i];
                var b = pts[(i + 1) % pts.Count];
                var z = NN(level, "Elevation").Elevation;
                loop.Append(DB.Line.CreateBound(new DB.XYZ(a.x, a.y, z), new DB.XYZ(b.x, b.y, z)));
            }
            DB.Element? ft = T(item, "type") || T(item, "type_id")
                ? Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"),
                    typeId: item.Get("type_id"), ofClass: typeof(DB.FloorType))
                : doc.GetElement(doc.GetDefaultElementTypeId(DB.ElementTypeGroup.FloorType));
            var f = Compat.NewFloor(doc, new[] { loop }, NN(ft, "Id"), level!, Py.Truthy(item.Get("structural", false)));
            return new Dict { ["kind"] = kind, ["id"] = Compat.IdInt(f), ["type"] = Utils.NormalizeString(Utils.GetElementName(ft)) };
        }
        if (kind == "family_instance")
        {
            var sym = AsSymbol(Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"),
                typeId: item.Get("type_id"), ofClass: typeof(DB.FamilySymbol)));
            if (!sym.IsActive)
            {
                sym.Activate();
                doc.Regenerate();
            }
            var pt = Pt(ctx, item, "point");
            var st = DB.Structure.StructuralType.NonStructural;
            var level = item.Get("level") != null ? Core.FindLevel(doc, item.Get("level")) : null;
            var host = item.Get("host_id") != null ? Core.GetElement(doc, item["host_id"], "Host") : null;
            DB.FamilyInstance fi;
            if (host != null && level != null)
                fi = doc.Create.NewFamilyInstance(pt, sym, host, level, st);
            else if (host is DB.Level hostLevel) // IronPython bound a Level host to the (XYZ, symbol, Level, type) overload
                fi = doc.Create.NewFamilyInstance(pt, sym, hostLevel, st);
            else if (host != null)
                fi = doc.Create.NewFamilyInstance(pt, sym, host, st);
            else if (level != null)
                fi = doc.Create.NewFamilyInstance(pt, sym, level, st);
            else
                fi = doc.Create.NewFamilyInstance(pt, sym, st);
            var rot = FloatOrZero(item, "rotation_deg");
            if (rot != 0.0)
            {
                doc.Regenerate();
                DB.ElementTransformUtils.RotateElement(doc, fi.Id, DB.Line.CreateBound(pt, pt + DB.XYZ.BasisZ), Radians(rot));
            }
            return new Dict
            {
                ["kind"] = kind, ["id"] = Compat.IdInt(fi), ["family"] = Utils.NormalizeString(sym.Family.Name),
                ["type"] = Utils.NormalizeString(Utils.GetElementName(sym)),
            };
        }
        if (kind == "room")
        {
            Core.RequireProject(doc);
            var level = Core.FindLevel(doc, item.Get("level"));
            var (x, y, _) = Units.PointFrom(item.Get("point"), unit);
            var r = doc.Create.NewRoom(level, new DB.UV(x, y));
            if (T(item, "name"))
                r.get_Parameter(DB.BuiltInParameter.ROOM_NAME).Set(Py.Str(item["name"]));
            if (T(item, "number"))
                r.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER).Set(Py.Str(item["number"]));
            return new Dict { ["kind"] = kind, ["id"] = Compat.IdInt(r) };
        }
        if (kind != null && StructureKinds.TryGetValue(kind, out var structure))
            return structure(ctx, item);
        if (kind != null && ModellingKinds.TryGetValue(kind, out var modelling))
            return modelling(ctx, item);
        throw new RvtssError($"Unknown kind '{Py.Str(kindValue)}'. Use level, grid, wall, floor, family_instance, room, roof, ceiling, "
                             + "column, beam, foundation, wall_foundation, duct, pipe, cable_tray, conduit, wall_opening, "
                             + "opening, shaft, railing, space, area, area_boundary, room_separation, space_separation, auto_rooms, "
                             + "rebar, toposolid, direct_shape, curtain_grid_line, mullions, curtain_panel_type, wall_sweep, "
                             + "reveal, model_line, reference_plane, foundation_isolated, foundation_wall, brace, truss or "
                             + "beam_system").With("failed_item", item);
    }

    // ---------------------------------------------------- roofs, ceilings, structure (2.2)
    /// <summary>Closed boundary [[x, y], ...] at the level elevation -> list of lines.</summary>
    private static List<DB.Line> Outline(Ctx ctx, Dict item, DB.Level? level)
    {
        var pts = PointList(item, "boundary", ctx.Unit);
        if (pts.Count < 3)
            throw new RvtssError("'boundary' needs at least 3 points").With("failed_item", item);
        var z = NN(level, "Elevation").Elevation;
        var lines = new List<DB.Line>();
        for (var i = 0; i < pts.Count; i++)
        {
            var a = pts[i];
            var b = pts[(i + 1) % pts.Count];
            var pa = new DB.XYZ(a.x, a.y, z);
            var pb = new DB.XYZ(b.x, b.y, z);
            if (pa.DistanceTo(pb) < 1e-4)
                throw new RvtssError("boundary has two equal consecutive points").With("failed_item", item);
            lines.Add(DB.Line.CreateBound(pa, pb));
        }
        return lines;
    }

    private static DB.Element SystemType(DB.Document doc, Dict item, Type cls, DB.ElementTypeGroup? group, string what)
    {
        if (T(item, "type") || item.Get("type_id") != null)
            return Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"),
                typeId: item.Get("type_id"), ofClass: cls);
        DB.Element? t = null;
        if (group != null)
        {
            try { t = doc.GetElement(doc.GetDefaultElementTypeId(group.Value)); }
            catch { t = null; }
        }
        t ??= new DB.FilteredElementCollector(doc).OfClass(cls).FirstElement();
        if (t == null)
            throw new RvtssError($"No {what} type exists in '{doc.Title}'");
        return t;
    }

    /// <summary>FamilySymbol from family/type/type_id, else the first loaded symbol of the categories.</summary>
    private static DB.FamilySymbol Symbol(DB.Document doc, Dict item, DB.BuiltInCategory[] categories, string what)
    {
        DB.FamilySymbol? sym;
        if (T(item, "type") || item.Get("type_id") != null || T(item, "family"))
        {
            sym = AsSymbol(Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"),
                typeId: item.Get("type_id"), ofClass: typeof(DB.FamilySymbol)));
        }
        else
        {
            sym = null;
            foreach (var bic in categories)
            {
                sym = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)).OfCategory(bic).FirstElement() as DB.FamilySymbol;
                if (sym != null)
                    break;
            }
            if (sym == null)
                throw new RvtssError($"No {what} family is loaded in '{doc.Title}'",
                    hint: "Load one (family_load_into_project) or pass family/type.");
        }
        if (!sym.IsActive)
        {
            sym.Activate();
            doc.Regenerate();
        }
        return sym;
    }

    /// <summary>Set the first of the built-in parameters that exists and is writable. value: a number
    /// (internal units), an ElementId or text.</summary>
    private static bool SetParam(DB.Element e, DB.BuiltInParameter[] bips, object value)
    {
        foreach (var bip in bips)
        {
            var p = e.get_Parameter(bip);
            if (p != null && !p.IsReadOnly)
            {
                switch (value)
                {
                    case double d: p.Set(d); break;
                    case DB.ElementId id: p.Set(id); break;
                    case string s: p.Set(s); break;
                    case int i: p.Set(i); break;
                    case long l: p.Set((int)l); break;
                    default: p.Set(Py.Str(value)); break;
                }
                return true;
            }
        }
        return false;
    }

    /// <summary>len(list(v)) of a point value.</summary>
    private static int CoordCount(object? v) => PureText.Iter(v).Count();

    private static DB.XYZ LevelPoint(Ctx ctx, Dict item, DB.Level? level, string key = "point")
    {
        var v = item.Get(key);
        if (v == null)
            throw new RvtssError($"'{key}' is required").With("failed_item", item);
        var (x, y, z) = Units.PointFrom(v, ctx.Unit);
        return new DB.XYZ(x, y, CoordCount(v) == 3 ? z : NN(level, "Elevation").Elevation);
    }

    private static Dict Roof(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var level = Core.FindLevel(doc, item.Get("level"));
        var rt = SystemType(doc, item, typeof(DB.RoofType), DB.ElementTypeGroup.RoofType, "roof");
        var footprint = new DB.CurveArray();
        foreach (var ln in Outline(ctx, item, level))
            footprint.Append(ln);
        var modelCurves = new DB.ModelCurveArray();
        var roof = doc.Create.NewFootPrintRoof(footprint, level, (DB.RoofType)rt, out modelCurves);
        var slope = item.Get("slope_deg");
        var sloped = new Lst();
        if (Py.Truthy(slope))
        {
            var edges = item.Get("slope_edges");
            var wanted = edges == null ? null : PureText.Iter(edges).ToList();
            var i = 0L;
            foreach (DB.ModelCurve mc in modelCurves)
            {
                var index = i;
                if (wanted == null || wanted.Any(x => Py.IsNum(x) && Py.ToFloat(x) == index))
                {
                    roof.set_DefinesSlope(mc, true);
                    roof.set_SlopeAngle(mc, Math.Tan(Radians(Py.ToFloat(slope))));
                    sloped.Add(i);
                }
                i++;
            }
        }
        if (T(item, "base_offset"))
            SetParam(roof, new[] { DB.BuiltInParameter.ROOF_LEVEL_OFFSET_PARAM }, Units.ToInternal(item["base_offset"], ctx.Unit));
        return new Dict
        {
            ["kind"] = "roof", ["id"] = Compat.IdInt(roof), ["type"] = Utils.NormalizeString(Utils.GetElementName(rt)),
            ["sloped_edges"] = sloped,
        };
    }

    private static Dict Ceiling(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        // Ceiling.Create exists on every supported version (the Python check was for Revit 2021 and older)
        var level = Core.FindLevel(doc, item.Get("level"));
        var ct = SystemType(doc, item, typeof(DB.CeilingType), DB.ElementTypeGroup.CeilingType, "ceiling");
        var loop = new DB.CurveLoop();
        foreach (var ln in Outline(ctx, item, level))
            loop.Append(ln);
        var loops = new List<DB.CurveLoop> { loop };
        var c = DB.Ceiling.Create(doc, loops, ct.Id, level!.Id);
        if (item.Get("height") != null)
            SetParam(c, new[] { DB.BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM }, Units.ToInternal(item["height"], ctx.Unit));
        return new Dict { ["kind"] = "ceiling", ["id"] = Compat.IdInt(c), ["type"] = Utils.NormalizeString(Utils.GetElementName(ct)) };
    }

    private static Dict Column(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var baseLevel = Core.FindLevel(doc, T(item, "level") ? item["level"] : item.Get("base_level"));
        var sym = Symbol(doc, item, new[] { DB.BuiltInCategory.OST_StructuralColumns, DB.BuiltInCategory.OST_Columns }, "column");
        var structural = sym.Category != null && Compat.IdInt(sym.Category.Id) == (long)DB.BuiltInCategory.OST_StructuralColumns;
        var st = structural ? DB.Structure.StructuralType.Column : DB.Structure.StructuralType.NonStructural;
        var pt = LevelPoint(ctx, item, baseLevel);
        var fi = doc.Create.NewFamilyInstance(pt, sym, baseLevel, st);
        SetParam(fi, new[] { DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM }, Units.ToInternal(item.Get("base_offset", 0L), ctx.Unit));
        if (item.Get("top_level") != null)
        {
            var top = Core.FindLevel(doc, item.Get("top_level"));
            SetParam(fi, new[] { DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM }, NN(top, "Id").Id);
        }
        if (item.Get("top_offset") != null)
            SetParam(fi, new[] { DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM }, Units.ToInternal(item["top_offset"], ctx.Unit));
        var rot = FloatOrZero(item, "rotation_deg");
        if (rot != 0.0)
        {
            doc.Regenerate();
            DB.ElementTransformUtils.RotateElement(doc, fi.Id, DB.Line.CreateBound(pt, pt + DB.XYZ.BasisZ), Radians(rot));
        }
        return new Dict
        {
            ["kind"] = "column", ["id"] = Compat.IdInt(fi), ["structural"] = structural,
            ["family"] = Utils.NormalizeString(sym.Family.Name), ["type"] = Utils.NormalizeString(Utils.GetElementName(sym)),
        };
    }

    private static Dict Beam(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var level = Core.FindLevel(doc, item.Get("level"));
        var sym = Symbol(doc, item, new[] { DB.BuiltInCategory.OST_StructuralFraming }, "structural framing (beam)");
        var a = LevelPoint(ctx, item, level, "start");
        var b = LevelPoint(ctx, item, level, "end");
        if (a.DistanceTo(b) < 1e-4)
            throw new RvtssError("start and end are the same point").With("failed_item", item);
        var fi = doc.Create.NewFamilyInstance(DB.Line.CreateBound(a, b), sym, level, DB.Structure.StructuralType.Beam);
        return new Dict
        {
            ["kind"] = "beam", ["id"] = Compat.IdInt(fi), ["family"] = Utils.NormalizeString(sym.Family.Name),
            ["type"] = Utils.NormalizeString(Utils.GetElementName(sym)),
        };
    }

    private static Dict Foundation(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var level = Core.FindLevel(doc, item.Get("level"));
        var sym = Symbol(doc, item, new[] { DB.BuiltInCategory.OST_StructuralFoundation }, "structural foundation");
        var pt = LevelPoint(ctx, item, level);
        var fi = doc.Create.NewFamilyInstance(pt, sym, level, DB.Structure.StructuralType.Footing);
        if (item.Get("base_offset") != null)
            SetParam(fi, new[] { DB.BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM, DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM },
                Units.ToInternal(item["base_offset"], ctx.Unit));
        return new Dict
        {
            ["kind"] = "foundation", ["id"] = Compat.IdInt(fi), ["family"] = Utils.NormalizeString(sym.Family.Name),
            ["type"] = Utils.NormalizeString(Utils.GetElementName(sym)),
        };
    }

    private static Dict WallFoundation(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        if (item.Get("wall_id") == null)
            throw new RvtssError("'wall_id' is required").With("failed_item", item);
        var wall = Core.GetElement(doc, item["wall_id"], "Wall");
        if (wall is not DB.Wall)
            throw new RvtssError($"Element {Py.Str(item["wall_id"])} is not a wall");
        var ft = SystemType(doc, item, typeof(DB.WallFoundationType), null, "wall foundation");
        var wf = DB.WallFoundation.Create(doc, ft.Id, wall.Id);
        return new Dict
        {
            ["kind"] = "wall_foundation", ["id"] = Compat.IdInt(wf), ["wall_id"] = Compat.IdInt(wall),
            ["type"] = Utils.NormalizeString(Utils.GetElementName(ft)),
        };
    }

    // ------------------------------------------------------------- kinds and route
    private static readonly Dictionary<string, Func<Ctx, Dict, Dict>> StructureKinds = new()
    {
        ["roof"] = Roof, ["ceiling"] = Ceiling, ["column"] = Column, ["beam"] = Beam,
        ["foundation"] = Foundation, ["wall_foundation"] = WallFoundation,
        ["duct"] = (c, i) => MepRun(c, i, "duct"), ["pipe"] = (c, i) => MepRun(c, i, "pipe"),
        ["cable_tray"] = (c, i) => MepRun(c, i, "cable_tray"),
        ["conduit"] = (c, i) => MepRun(c, i, "conduit"),
        ["wall_opening"] = WallOpening, ["opening"] = HostOpening, ["shaft"] = Shaft,
        ["railing"] = Railing, ["space"] = Space, ["area"] = Area,
        ["area_boundary"] = (c, i) => BoundaryLines(c, i, "area_boundary"),
        ["room_separation"] = (c, i) => BoundaryLines(c, i, "room_separation"),
        ["space_separation"] = (c, i) => BoundaryLines(c, i, "space_separation"),
        ["auto_rooms"] = AutoRooms, ["rebar"] = Rebar, ["toposolid"] = Toposolid,
        ["direct_shape"] = DirectShape,
    };

    private static Func<Ctx, Dict, Dict> Alias(Func<Ctx, Dict, Dict> func, string kind) => (ctx, item) =>
    {
        var o = func(ctx, item);
        o["kind"] = kind;
        return o;
    };

    private static readonly Dictionary<string, Func<Ctx, Dict, Dict>> ModellingKinds = new()
    {
        ["curtain_grid_line"] = CurtainGridLine, ["mullions"] = Mullions,
        ["curtain_panel_type"] = CurtainPanelType,
        ["wall_sweep"] = (c, i) => WallSweep(c, i, "wall_sweep"),
        ["reveal"] = (c, i) => WallSweep(c, i, "reveal"),
        ["model_line"] = ModelLine, ["reference_plane"] = ReferencePlane,
        ["foundation_isolated"] = Alias(Foundation, "foundation_isolated"),
        ["foundation_wall"] = Alias(WallFoundation, "foundation_wall"),
        ["brace"] = Brace, ["truss"] = Truss, ["beam_system"] = BeamSystem,
    };

    public static Dict? CreateElements(Ctx ctx)
    {
        var doc = ctx.Doc;
        var items = ctx.List("items");
        if (items.Count == 0)
            throw new RvtssError("'items' is required: [{kind: 'wall', start: [..], end: [..], level: 'Level 1'}, ...]");
        if (items.Count > 500)
            throw new RvtssError("At most 500 items per call");
        var dry = ctx.DryRun;

        Lst Run()
        {
            var res = Core.Batch(doc, items, it => CreateOne(ctx, it), ctx.Bool("atomic", true));
            doc.Regenerate();
            return res;
        }

        var (results, failures) = Core.RunTransaction(doc, "Create elements", () => Run(), dryRun: dry);
        return Core.CommitResult(new Dict
        {
            ["results"] = results, ["unit"] = ctx.Unit,
            ["created"] = (long)results.Count(r => Py.Truthy(((Dict)r!)["ok"])),
        }, failures, dry);
    }
}
