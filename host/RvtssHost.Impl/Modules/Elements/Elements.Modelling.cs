namespace RvtssHost.Modules;

/// <summary>elements.py: curtain walls, sweeps, model lines, reference planes, structure (2.4) and element_types.</summary>
public static partial class Elements
{
    // ------------------- curtain walls, sweeps, model lines, reference planes, structure (2.4)
    private static DB.Wall WallOf(Ctx ctx, Dict item, string what)
    {
        if (item.Get("wall_id") == null)
            throw new RvtssError("'wall_id' is required").With("failed_item", item);
        var wall = Core.GetElement(ctx.Doc, item["wall_id"], "Wall");
        if (wall is not DB.Wall w)
            throw new RvtssError($"Element {Py.Str(item["wall_id"])} is not a wall ({what} needs one)");
        return w;
    }

    private static (DB.Wall wall, DB.CurtainGrid grid) CurtainGrid(Ctx ctx, Dict item, string what)
    {
        var wall = WallOf(ctx, item, what);
        var grid = wall.CurtainGrid;
        if (grid == null)
            throw new RvtssError($"Wall {Compat.IdInt(wall)} is not a curtain wall",
                hint: "Create the wall with a curtain wall type first.");
        return (wall, grid);
    }

    /// <summary>(start point, direction, length, base z) of a straight wall.</summary>
    private static (DB.XYZ p0, DB.XYZ d, double length, double z) WallBase(DB.Document doc, DB.Wall wall)
    {
        if (wall.Location is not DB.LocationCurve location || location.Curve is not DB.Line line)
            throw new RvtssError($"Wall {Compat.IdInt(wall)} is not straight");
        var baseLevel = doc.GetElement(wall.LevelId) as DB.Level;
        var z = baseLevel != null ? baseLevel.Elevation : line.GetEndPoint(0).Z;
        try { z += wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble(); }
        catch { /* no base offset */ }
        return (line.GetEndPoint(0), line.Direction, line.Length, z);
    }

    /// <summary>text_type(item.get(key) or default).lower()</summary>
    private static string LowerOr(Dict item, string key, string def) =>
        (T(item, key) ? Py.Str(item[key]) : def).ToLowerInvariant();

    /// <summary>A grid line on a curtain wall: vertical at 'offset_along' from the wall start, or horizontal at
    /// 'height' above the wall base ('point' [x, y, z] on the wall face works for both).</summary>
    private static Dict CurtainGridLine(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var (wall, grid) = CurtainGrid(ctx, item, "curtain_grid_line");
        var direction = LowerOr(item, "direction", "vertical");
        if (direction != "vertical" && direction != "horizontal")
            throw new RvtssError("direction must be 'vertical' or 'horizontal'").With("failed_item", item);
        DB.XYZ pt;
        if (item.Get("point") != null)
        {
            pt = Pt(ctx, item, "point");
        }
        else
        {
            var (p0, d, length, z0) = WallBase(doc, wall);
            if (direction == "vertical")
            {
                if (item.Get("offset_along") == null)
                    throw new RvtssError("a vertical grid line needs 'offset_along' (from the wall start) or 'point'")
                        .With("failed_item", item);
                var a = Units.ToInternal(item["offset_along"], ctx.Unit);
                if (a <= 0 || a >= length)
                    throw new RvtssError($"offset_along is outside the wall (length {F0(Units.FromInternal(length, ctx.Unit))} {ctx.Unit})")
                        .With("failed_item", item);
                var h = Units.ToInternal(item.Get("height", 0L), ctx.Unit);
                pt = new DB.XYZ(p0.X + d.X * a, p0.Y + d.Y * a, z0 + h);
            }
            else
            {
                if (item.Get("height") == null)
                    throw new RvtssError("a horizontal grid line needs 'height' (above the wall base) or 'point'")
                        .With("failed_item", item);
                var a = item.Get("offset_along") != null ? Units.ToInternal(item["offset_along"], ctx.Unit) : length / 2.0;
                pt = new DB.XYZ(p0.X + d.X * a, p0.Y + d.Y * a, z0 + Units.ToInternal(item["height"], ctx.Unit));
            }
        }
        // U grid lines are the horizontal ones on a curtain wall, V grid lines the vertical ones
        var gl = grid.AddGridLine(direction == "horizontal", pt, Py.Truthy(item.Get("one_segment_only", false)));
        if (gl == null)
            throw new RvtssError("Revit did not add the grid line (is the point on the curtain wall?)").With("failed_item", item);
        return new Dict
        {
            ["kind"] = "curtain_grid_line", ["id"] = Compat.IdInt(gl), ["wall_id"] = Compat.IdInt(wall), ["direction"] = direction,
        };
    }

    /// <summary>Mullions on the grid lines of a curtain wall (lines: all | horizontal | vertical, or grid_line_ids).</summary>
    private static Dict Mullions(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var (wall, grid) = CurtainGrid(ctx, item, "mullions");
        var types = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.MullionType)).ToList();
        if (types.Count == 0)
            throw new RvtssError($"No mullion type exists in '{doc.Title}'",
                hint: "Load or create a mullion type (rectangular / circular mullion) first.");
        DB.Element mt;
        if (T(item, "type") || item.Get("type_id") != null)
            mt = Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"),
                typeId: item.Get("type_id"), ofClass: typeof(DB.MullionType));
        else
            mt = types[0];
        var which = LowerOr(item, "lines", "all");
        var lineIds = new List<DB.ElementId>();
        if (T(item, "grid_line_ids"))
        {
            foreach (var i in PureText.Iter(item["grid_line_ids"]))
                lineIds.Add(Core.GetElement(doc, i, "Curtain grid line").Id);
        }
        else
        {
            if (which == "all" || which == "horizontal")
                lineIds.AddRange(grid.GetUGridLineIds());
            if (which == "all" || which == "vertical")
                lineIds.AddRange(grid.GetVGridLineIds());
            if (which != "all" && which != "horizontal" && which != "vertical")
                throw new RvtssError("lines must be all, horizontal or vertical").With("failed_item", item);
        }
        if (lineIds.Count == 0)
            throw new RvtssError($"Curtain wall {Compat.IdInt(wall)} has no grid lines",
                hint: "Add them with kind='curtain_grid_line' first.");
        var created = new Lst();
        var errors = new List<Dict>();
        foreach (var lid in lineIds)
        {
            var element = doc.GetElement(lid);
            try
            {
                var gl = element as DB.CurtainGridLine ?? throw NoAttr(element, "AllSegmentCurves");
                DB.Curve? seg = null;
                foreach (DB.Curve c in gl.AllSegmentCurves)
                {
                    seg = c;
                    break;
                }
                if (seg == null)
                    throw new RvtssError("grid line has no segment");
                foreach (DB.Element m in gl.AddMullions(seg, (DB.MullionType)mt, false))
                    created.Add(Compat.IdInt(m));
            }
            catch (Exception ex) // e.g. mullions already exist on the line
            {
                errors.Add(new Dict
                {
                    ["grid_line_id"] = Compat.IdInt(lid),
                    ["error"] = ex is RvtssError ? ex.Message : Utils.NormalizeString(ex.Message),
                });
            }
        }
        if (created.Count == 0 && errors.Count > 0)
            throw new RvtssError($"No mullion was added: {Py.Str(errors[0]["error"])}").With("failed_item", item)
                .With("errors", errors.Take(20).ToList());
        var o = new Dict
        {
            ["kind"] = "mullions", ["ids"] = created, ["wall_id"] = Compat.IdInt(wall),
            ["type"] = Utils.NormalizeString(Utils.GetElementName(mt)), ["grid_lines"] = (long)lineIds.Count,
        };
        if (errors.Count > 0)
            o["errors"] = errors.Take(20).ToList();
        return o;
    }

    /// <summary>Change the type of curtain panels: all panels of a curtain wall, or panel_ids.</summary>
    private static Dict CurtainPanelType(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        List<DB.Element?> panels;
        long? wallId;
        if (T(item, "panel_ids"))
        {
            panels = Core.GetElements(doc, PureText.Iter(item["panel_ids"]), "Panel").Cast<DB.Element?>().ToList();
            wallId = null;
        }
        else
        {
            var (wall, grid) = CurtainGrid(ctx, item, "curtain_panel_type");
            panels = grid.GetPanelIds().Select(i => (DB.Element?)doc.GetElement(i)).ToList();
            wallId = Compat.IdInt(wall);
        }
        if (!(T(item, "type") || item.Get("type_id") != null))
            throw new RvtssError("'type' (or type_id) is required: a panel type, a wall type or a curtain panel family "
                                 + "type").With("failed_item", item);
        var t = Core.FindType(doc, family: item.Get("family"), typeName: item.Get("type"), typeId: item.Get("type_id"));
        var unpin = Py.Truthy(item.Get("unpin", false));
        var changed = new Lst();
        var skipped = new List<Dict>();
        foreach (var p in panels)
        {
            if (p == null)
                continue;
            if (p.Pinned)
            {
                if (!unpin)
                {
                    skipped.Add(new Dict { ["id"] = Compat.IdInt(p), ["reason"] = "pinned (set by the curtain wall type); pass unpin=true" });
                    continue;
                }
                p.Pinned = false;
            }
            try
            {
                if (!p.GetValidTypes().Any(i => i == t.Id))
                {
                    skipped.Add(new Dict { ["id"] = Compat.IdInt(p), ["reason"] = "type is not valid for this panel" });
                    continue;
                }
                p.ChangeTypeId(t.Id);
                changed.Add(Compat.IdInt(p));
            }
            catch (Exception ex)
            {
                skipped.Add(new Dict { ["id"] = Compat.IdInt(p), ["reason"] = Utils.NormalizeString(ex.Message) });
            }
        }
        if (changed.Count == 0)
            throw new RvtssError("No panel was changed").With("failed_item", item).With("skipped", skipped.Take(20).ToList());
        return new Dict
        {
            ["kind"] = "curtain_panel_type", ["ids"] = changed, ["wall_id"] = wallId,
            ["type"] = Utils.NormalizeString(Utils.GetElementName(t)), ["skipped"] = skipped.Take(50).ToList(),
        };
    }

    /// <summary>A wall sweep or reveal: horizontal at 'distance' above the base, or vertical at 'distance' along the wall.</summary>
    private static Dict WallSweep(Ctx ctx, Dict item, string kind)
    {
        var doc = ctx.Doc;
        var wall = WallOf(ctx, item, kind);
        // WallSweep.Create exists on every supported version
        var reveal = kind == "reveal";
        var bic = reveal ? DB.BuiltInCategory.OST_Reveals : DB.BuiltInCategory.OST_Cornices;
        var types = new DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType().ToList();
        if (types.Count == 0)
            throw new RvtssError($"No {(reveal ? "reveal" : "wall sweep")} type exists in '{doc.Title}'",
                hint: $"Create a type in Revit (Architecture > Wall > Wall: {(reveal ? "Reveal" : "Sweep")}) and load a profile "
                      + "family.");
        var st = types[0];
        if (item.Get("type_id") != null)
        {
            st = Core.FindType(doc, typeId: item["type_id"]);
        }
        else if (T(item, "type"))
        {
            var key = Py.Str(item["type"]).Trim().ToLowerInvariant();
            var match = types.Where(t => Utils.NormalizeString(Utils.GetElementName(t)).ToLowerInvariant() == key).ToList();
            if (match.Count == 0)
                throw NotFoundType($"{kind} type", item["type"], types.Select(t => Utils.GetElementName(t)));
            st = match[0];
        }
        var vertical = Py.Truthy(item.Get("vertical", false));
        var info = new DB.WallSweepInfo(reveal ? DB.WallSweepType.Reveal : DB.WallSweepType.Sweep, vertical);
        info.Distance = Units.ToInternal(item.Get("distance", 0L), ctx.Unit);
        var side = LowerOr(item, "side", "exterior");
        info.WallSide = side == "interior" ? DB.WallSide.Interior : DB.WallSide.Exterior;
        if (!vertical)
            info.DistanceMeasuredFrom = T(item, "from_top") ? DB.DistanceMeasuredFrom.Top : DB.DistanceMeasuredFrom.Base;
        if (item.Get("wall_offset") != null)
            info.WallOffset = Units.ToInternal(item["wall_offset"], ctx.Unit);
        var ws = DB.WallSweep.Create(wall, st.Id, info);
        return new Dict
        {
            ["kind"] = kind, ["id"] = Compat.IdInt(ws), ["wall_id"] = Compat.IdInt(wall), ["vertical"] = vertical,
            ["type"] = Utils.NormalizeString(Utils.GetElementName(st)),
        };
    }

    /// <summary>Model lines on a horizontal plane: at 'level' (+ 'offset'), else at the z of the first point.</summary>
    private static Dict ModelLine(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var raw = RawRoute(item);
        if (raw == null || raw.Count < 2)
            throw new RvtssError("'points' needs at least 2 points (or start and end)").With("failed_item", item);
        double z;
        if (item.Get("level") != null)
            z = NN(Core.FindLevel(doc, item["level"]), "Elevation").Elevation + Units.ToInternal(item.Get("offset", 0L), ctx.Unit);
        else
            z = Units.PointFrom(raw[0], ctx.Unit).z;
        var pts = new List<DB.XYZ>();
        foreach (var p in raw)
        {
            var (x, y, _) = Units.PointFrom(p, ctx.Unit);
            pts.Add(new DB.XYZ(x, y, z));
        }
        if (T(item, "closed") && pts.Count > 2)
            pts.Add(pts[0]);
        var sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, new DB.XYZ(0, 0, z)));
        DB.GraphicsStyle? style = null;
        if (T(item, "line_style"))
        {
            var key = Py.Str(item["line_style"]).Trim().ToLowerInvariant();
            var cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines);
            var names = new List<string>();
            foreach (DB.Category sub in cat.SubCategories)
            {
                names.Add(sub.Name);
                if (Utils.NormalizeString(sub.Name).ToLowerInvariant() == key)
                    style = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection);
            }
            if (style == null)
                throw Core.NotFound("Line style", item["line_style"], names);
        }
        var ids = new Lst();
        for (var i = 0; i + 1 < pts.Count; i++)
        {
            var a = pts[i];
            var b = pts[i + 1];
            if (a.DistanceTo(b) < 1e-4)
                throw new RvtssError("model_line has two equal consecutive points").With("failed_item", item);
            var line = DB.Line.CreateBound(a, b);
            var mc = doc.IsFamilyDocument ? doc.FamilyCreate.NewModelCurve(line, sp) : doc.Create.NewModelCurve(line, sp);
            if (style != null)
                mc.LineStyle = style;
            ids.Add(Compat.IdInt(mc));
        }
        return new Dict { ["kind"] = "model_line", ["ids"] = ids, ["sketch_plane_id"] = Compat.IdInt(sp) };
    }

    /// <summary>A vertical reference plane drawn in plan from start to end (shown in 'view', default the active view).</summary>
    private static Dict ReferencePlane(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var a = Pt(ctx, item, "start");
        var b = Pt(ctx, item, "end");
        if (item.Get("level") != null)
        {
            var z = NN(Core.FindLevel(doc, item["level"]), "Elevation").Elevation;
            a = new DB.XYZ(a.X, a.Y, z);
            b = new DB.XYZ(b.X, b.Y, z);
        }
        if (a.DistanceTo(b) < 1e-4)
            throw new RvtssError("start and end are the same point").With("failed_item", item);
        var view = Core.FindView(doc, item.Get("view"));
        var rp = doc.IsFamilyDocument
            ? doc.FamilyCreate.NewReferencePlane(a, b, DB.XYZ.BasisZ, view)
            : doc.Create.NewReferencePlane(a, b, DB.XYZ.BasisZ, view);
        if (rp == null)
            throw new RvtssError("Revit did not create the reference plane (use a plan view)").With("failed_item", item);
        if (T(item, "name"))
            rp.Name = Py.Str(item["name"]);
        return new Dict
        {
            ["kind"] = "reference_plane", ["id"] = Compat.IdInt(rp), ["name"] = Utils.NormalizeString(rp.Name),
            ["view_id"] = Compat.IdInt(NN(view, "Id")),
        };
    }

    /// <summary>A structural brace between two 3D points (z defaults to the level elevation).</summary>
    private static Dict Brace(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        var level = Core.FindLevel(doc, item.Get("level"));
        var sym = Symbol(doc, item, new[] { DB.BuiltInCategory.OST_StructuralFraming }, "structural framing (brace)");
        var a = LevelPoint(ctx, item, level, "start");
        var b = LevelPoint(ctx, item, level, "end");
        if (a.DistanceTo(b) < 1e-4)
            throw new RvtssError("start and end are the same point").With("failed_item", item);
        var fi = doc.Create.NewFamilyInstance(DB.Line.CreateBound(a, b), sym, level, DB.Structure.StructuralType.Brace);
        return new Dict
        {
            ["kind"] = "brace", ["id"] = Compat.IdInt(fi), ["family"] = Utils.NormalizeString(sym.Family.Name),
            ["type"] = Utils.NormalizeString(Utils.GetElementName(sym)),
        };
    }

    private static Dict Truss(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var level = Core.FindLevel(doc, item.Get("level"));
        // TrussType cannot be collected with OfClass ("not in Revit's native object model"): go by category
        var types = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Truss)
            .WhereElementIsElementType().ToList();
        if (types.Count == 0)
            throw new RvtssError($"No truss family is loaded in '{doc.Title}'",
                hint: "Load one (Insert > Load Family > Structural Trusses), then retry.");
        DB.Element? tt;
        if (T(item, "type") || item.Get("type_id") != null)
        {
            var famL = (T(item, "family") ? Py.Str(item["family"]) : "").Trim().ToLowerInvariant();
            var typL = (T(item, "type") ? Py.Str(item["type"]) : "").Trim().ToLowerInvariant();
            tt = null;
            foreach (var t in types)
            {
                if (item.Get("type_id") != null)
                {
                    if (Compat.IdInt(t) == Py.ToInt(item["type_id"]))
                        tt = t;
                }
                else if ((famL.Length == 0 || Utils.NormalizeString((t as DB.ElementType)?.FamilyName ?? "").ToLowerInvariant() == famL)
                         && (typL.Length == 0 || Utils.NormalizeString(Utils.GetElementName(t)).ToLowerInvariant() == typL))
                {
                    tt = t;
                }
                if (tt != null)
                    break;
            }
            if (tt == null)
                throw Core.NotFound("Truss type",
                    T(item, "type") ? item["type"] : T(item, "type_id") ? item["type_id"] : item.Get("family"),
                    types.Select(t => Utils.GetElementName(t)));
        }
        else
        {
            tt = types[0];
        }
        var z = NN(level, "Elevation").Elevation + Units.ToInternal(item.Get("offset", 0L), ctx.Unit);
        var a = Pt(ctx, item, "start");
        var b = Pt(ctx, item, "end");
        a = new DB.XYZ(a.X, a.Y, z);
        b = new DB.XYZ(b.X, b.Y, z);
        if (a.DistanceTo(b) < 1e-4)
            throw new RvtssError("start and end are the same point").With("failed_item", item);
        var sp = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, new DB.XYZ(0, 0, z)));
        var tr = DB.Structure.Truss.Create(doc, tt.Id, sp.Id, DB.Line.CreateBound(a, b));
        return new Dict { ["kind"] = "truss", ["id"] = Compat.IdInt(tr), ["type"] = Utils.NormalizeString(Utils.GetElementName(tt)) };
    }

    /// <summary>A beam system inside a closed boundary; beams run parallel to boundary edge 'direction_edge' (0-based).</summary>
    private static Dict BeamSystem(Ctx ctx, Dict item)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var level = Core.FindLevel(doc, item.Get("level"));
        var profile = new List<DB.Curve>();
        var lines = Outline(ctx, item, level);
        foreach (var ln in lines)
            profile.Add(ln);
        var edge = T(item, "direction_edge") ? Py.ToInt(item["direction_edge"]) : 0;
        if (edge < 0 || edge >= lines.Count)
            throw new RvtssError($"direction_edge must be between 0 and {lines.Count - 1}").With("failed_item", item);
        var bs = DB.BeamSystem.Create(doc, profile, level, (int)edge, Py.Truthy(item.Get("is_3d", false))); // not in DB.Structure
        var o = new Dict { ["kind"] = "beam_system", ["id"] = Compat.IdInt(bs) };
        if (T(item, "type") || item.Get("type_id") != null || T(item, "family"))
        {
            var sym = Symbol(doc, item, new[] { DB.BuiltInCategory.OST_StructuralFraming }, "structural framing (beam)");
            bs.BeamType = sym;
            o["beam_type"] = Utils.NormalizeString(Utils.GetElementName(sym));
        }
        try
        {
            doc.Regenerate();
            o["beam_ids"] = bs.GetBeamIds().Select(i => (object?)Compat.IdInt(i)).ToList();
        }
        catch { /* the system is created; its beams are listed when Revit can regenerate */ }
        return o;
    }

    // ------------------------------------------------------------------------ types
    public static Dict? ElementTypes(Ctx ctx)
    {
        var doc = ctx.Doc;
        var action = ctx.Require("action") as string;
        var dry = ctx.DryRun;
        if (action == "list_valid_types")
        {
            var e = Core.GetElement(doc, ctx.Require("element_id"));
            var valid = e.GetValidTypes().Select(i => doc.GetElement(i)).ToList();
            return new Dict
            {
                ["element_id"] = Compat.IdInt(e), ["current_type_id"] = Compat.IdInt(e.GetTypeId()),
                ["valid_types"] = valid.Where(t => t != null).Select(t => (object?)new Dict
                {
                    ["id"] = Compat.IdInt(t), ["family"] = Utils.NormalizeString((t as DB.ElementType)?.FamilyName ?? ""),
                    ["type"] = Utils.NormalizeString(Utils.GetElementName(t)),
                }).ToList(),
            };
        }

        DB.ElementType GetType() =>
            Core.FindType(doc, family: ctx.Get("family"), typeName: ctx.Get("type"), typeId: ctx.Get("type_id"),
                category: ctx.Get("category"));

        if (action == "duplicate")
        {
            var src = GetType();
            var newName = Py.Str(ctx.Require("new_name"));

            Dict Run()
            {
                var t = doc.GetElement(src.Duplicate(newName).Id);
                if (t == null)
                    throw new RvtssError("This type cannot be duplicated");
                var setVals = new Lst();
                var parameters = ctx.Get("parameters");
                if (Py.Truthy(parameters))
                {
                    foreach (var kv in parameters as Dict ?? throw NoAttr(parameters, "items"))
                    {
                        var (p, _) = ParamsUtil.Find(doc, t, kv.Key, allowType: false);
                        if (p == null)
                            throw new RvtssError($"Type parameter '{kv.Key}' not found", status: 404);
                        var (v, unit) = kv.Value is Dict val ? (val.Get("value"), val.Get("unit")) : (kv.Value, null);
                        setVals.Add(ParamsUtil.SetValue(doc, p, v, UnitOf(unit)));
                    }
                }
                return new Dict { ["new_type_id"] = Compat.IdInt(t), ["name"] = t.Name, ["parameters_set"] = setVals };
            }

            var (res, fails) = Core.RunTransaction(doc, "Duplicate type", () => Run(), dryRun: dry);
            return Core.CommitResult(res, fails, dry);
        }
        if (action == "rename")
        {
            var t = GetType();
            var newName = Py.Str(ctx.Require("new_name"));

            Dict Run()
            {
                var old = t.Name;
                t.Name = newName;
                return new Dict { ["type_id"] = Compat.IdInt(t), ["old_name"] = old, ["new_name"] = t.Name };
            }

            var (res, fails) = Core.RunTransaction(doc, "Rename type", () => Run(), dryRun: dry);
            return Core.CommitResult(res, fails, dry);
        }
        if (action == "change_type")
        {
            var t = GetType();
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            var preview = Core.ConfirmGate(ctx, elements.Count, "change_type");

            Dict? Change(object? item)
            {
                var e = (DB.Element)item!;
                if (!e.GetValidTypes().Any(i => i == t.Id))
                    throw new RvtssError($"Type {Compat.IdInt(t)} is not valid for element {Compat.IdInt(e)}",
                        hint: "Use action=list_valid_types to see allowed types.");
                var old = Compat.IdInt(e.GetTypeId());
                e.ChangeTypeId(t.Id);
                return new Dict { ["element_id"] = Compat.IdInt(e), ["old_type_id"] = old, ["new_type_id"] = Compat.IdInt(t) };
            }

            var d = preview || dry;
            var (res, fails) = Core.RunTransaction(doc, "Change type",
                () => Core.Batch(doc, elements.Cast<object?>(), Change, ctx.Bool("atomic", true)), dryRun: d);
            return Core.PreviewStatus(Core.CommitResult(new Dict { ["results"] = res }, fails, d), preview);
        }
        throw new RvtssError("action must be list_valid_types, duplicate, rename or change_type");
    }
}
