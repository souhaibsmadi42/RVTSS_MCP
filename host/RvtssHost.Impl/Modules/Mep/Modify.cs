using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Modify panel operations (RVTSS v2.4). Port of revit_mcp/modify.py.
///
/// Routes:
///     POST /modify/elements/   operation = align | offset | trim_extend | split | scale | flip |
///                              cut | uncut | paint | remove_paint | create_parts | divide_parts
///
/// Each call is one transaction (one undo step) with dry_run support. Move / copy / rotate / mirror /
/// array / pin / join stay in /transform_elements/.
///
/// Not possible through the Revit API (left to the user): attaching wall tops / bases to roofs and
/// floors, editing a wall profile sketch, Split Face, wall join display, linework.
/// </summary>
public static class Modify
{
    public static readonly string[] Operations =
    {
        "align", "offset", "trim_extend", "split", "scale", "flip", "cut", "uncut", "paint",
        "remove_paint", "create_parts", "divide_parts",
    };

    private static readonly string[] Axes = { "x", "y", "z" };
    private const double Eps = 1e-6;

    // ------------------------------------------------------------------------ helpers
    /// <summary>repr() of a list of integers: "[1, 2, 3]".</summary>
    private static string IntListRepr(IEnumerable<long> ids) =>
        "[" + string.Join(", ", ids.Select(i => i.ToString(CultureInfo.InvariantCulture))) + "]";

    private static DB.XYZ Xyz(Ctx ctx, object? value, string what)
    {
        if (value == null)
            throw new RvtssError($"'{what}' is required ([x, y] or [x, y, z] in {ctx.Unit})");
        var (x, y, z) = Units.PointFrom(value, ctx.Unit);
        return new DB.XYZ(x, y, z);
    }

    private static double Coord(DB.XYZ p, string axis) => axis == "x" ? p.X : axis == "y" ? p.Y : p.Z;

    private static DB.XYZ AxisVector(string axis, double value) =>
        new(axis == "x" ? value : 0.0, axis == "y" ? value : 0.0, axis == "z" ? value : 0.0);

    private static DB.LocationCurve LocationCurve(DB.Element e, string what = "operation")
    {
        if (e.Location is not DB.LocationCurve loc)
            throw new RvtssError($"Element {Compat.IdInt(e)} has no location line; {what} works on walls, beams, ducts, pipes and lines");
        return loc;
    }

    private static (DB.LocationCurve loc, DB.Line line) Straight(DB.Element e, string what)
    {
        var loc = LocationCurve(e, what);
        var c = loc.Curve;
        if (c is not DB.Line line || !c.IsBound)
            throw new RvtssError($"Element {Compat.IdInt(e)} is not straight; {what} needs straight elements");
        return (loc, line);
    }

    private static void UnpinCheck(Ctx ctx, IEnumerable<DB.Element> elements)
    {
        var pinned = elements.Where(e => e.Pinned).Select(e => Compat.IdInt(e)).ToList();
        if (pinned.Count > 0 && !ctx.Bool("unpin", false))
            throw new RvtssError($"Pinned elements cannot be modified: {IntListRepr(pinned.Take(20))}", status: 409,
                hint: "Pass unpin=true to unpin them first (they stay unpinned).");
    }

    private static void Unpin(IEnumerable<DB.Element> elements)
    {
        foreach (var e in elements)
        {
            if (e.Pinned)
                e.Pinned = false;
        }
    }

    /// <summary>Apply one(element) to every element in one transaction, behind the confirm gate.</summary>
    private static Dict Run(Ctx ctx, string name, List<DB.Element> elements, Func<DB.Element, Dict?> one, Dict? extra = null,
        bool atomicDefault = true)
    {
        var doc = ctx.Doc;
        var preview = Core.ConfirmGate(ctx, elements.Count, "modify_elements " + name);
        var dry = preview || ctx.DryRun;

        Lst RunAll()
        {
            var res = Core.Batch(doc, elements, o => one((DB.Element)o!), ctx.Bool("atomic", atomicDefault));
            doc.Regenerate();
            return res;
        }

        var (results, failures) = Core.RunTransaction<Lst>(doc, "Modify " + name, RunAll, dry);
        var o = new Dict
        {
            ["operation"] = name, ["count"] = (long)elements.Count,
            ["succeeded"] = (long)results.Count(r => r is Dict rd && Py.Truthy(rd.Get("ok"))),
            ["results"] = results.Take(200).ToList(), ["results_truncated"] = results.Count > 200, ["unit"] = ctx.Unit,
        };
        if (extra != null && extra.Count > 0)
            o.Update(extra);
        return Core.PreviewStatus(Core.CommitResult(o, failures, dry), preview);
    }

    // -------------------------------------------------------------------------- align
    private static Dict Align(Ctx ctx, List<DB.Element> elements)
    {
        var axis = Py.Str(ctx.Get("axis", "x")).ToLowerInvariant();
        if (!Axes.Contains(axis))
            throw new RvtssError("axis must be x, y or z");
        double target;
        if (ctx.Get("reference_id") != null)
        {
            var rf = Core.GetElement(ctx.Doc, ctx.Get("reference_id"), "Reference element");
            var p = Core.ElementPoint(rf);
            if (p == null)
                throw new RvtssError($"Reference element {Compat.IdInt(rf)} has no location");
            target = Coord(p, axis);
        }
        else if (ctx.Get("coordinate") != null)
        {
            target = Units.ToInternal(ctx.Float("coordinate")!.Value, ctx.Unit);
        }
        else
        {
            throw new RvtssError("align needs 'reference_id' (align to that element) or 'coordinate' (a value on the axis)");
        }
        UnpinCheck(ctx, elements);

        Dict? One(DB.Element e)
        {
            var p = Core.ElementPoint(e);
            if (p == null)
                throw new RvtssError($"Element {Compat.IdInt(e)} has no location to align");
            var delta = target - Coord(p, axis);
            if (e.Pinned)
                e.Pinned = false;
            if (Math.Abs(delta) > Eps)
                DB.ElementTransformUtils.MoveElement(ctx.Doc, e.Id, AxisVector(axis, delta));
            return new Dict { ["id"] = Compat.IdInt(e), ["moved"] = Units.FromInternal(delta, ctx.Unit, 2) };
        }

        return Run(ctx, "align", elements, One,
            new Dict { ["axis"] = axis, ["aligned_to"] = Units.FromInternal(target, ctx.Unit, 2) });
    }

    // ------------------------------------------------------------------------- offset
    private static Dict Offset(Ctx ctx, List<DB.Element> elements)
    {
        var doc = ctx.Doc;
        if (ctx.Get("distance") == null)
            throw new RvtssError($"offset needs 'distance' (in {ctx.Unit}; positive = left of start -> end)");
        var dist = Units.ToInternal(ctx.Float("distance")!.Value, ctx.Unit);
        var copy = ctx.Bool("copy", false);
        UnpinCheck(ctx, elements);

        Dict? One(DB.Element e)
        {
            var loc = LocationCurve(e, "offset");
            var c = loc.Curve;
            if (e.Pinned && !copy)
                e.Pinned = false;
            if (c is DB.Line line)
            {
                var d = line.Direction;
                var vec = DB.XYZ.BasisZ.CrossProduct(d);
                if (vec.GetLength() < Eps)
                    throw new RvtssError($"Element {Compat.IdInt(e)} is vertical; offset works in plan");
                vec = vec.Normalize().Multiply(dist);
                if (copy)
                {
                    var copied = DB.ElementTransformUtils.CopyElement(doc, e.Id, vec).ToList();
                    return new Dict { ["id"] = Compat.IdInt(e), ["new_element_ids"] = copied.Select(i => (object?)Compat.IdInt(i)).ToList() };
                }
                DB.ElementTransformUtils.MoveElement(doc, e.Id, vec);
                return new Dict { ["id"] = Compat.IdInt(e) };
            }
            // arcs and other planar curves: a true offset curve (the radius changes)
            var newCurve = c.CreateOffset(dist, DB.XYZ.BasisZ);
            if (copy)
            {
                var newIds = DB.ElementTransformUtils.CopyElement(doc, e.Id, DB.XYZ.Zero).ToList();
                if (newIds.Count == 0)
                    throw new RvtssError($"Element {Compat.IdInt(e)} could not be copied");
                LocationCurve(doc.GetElement(newIds[0]), "offset").Curve = newCurve;
                return new Dict { ["id"] = Compat.IdInt(e), ["new_element_ids"] = newIds.Select(i => (object?)Compat.IdInt(i)).ToList() };
            }
            loc.Curve = newCurve;
            return new Dict { ["id"] = Compat.IdInt(e) };
        }

        return Run(ctx, "offset", elements, One, new Dict { ["distance"] = ctx.Float("distance"), ["copy"] = copy });
    }

    // -------------------------------------------------------------------- trim_extend
    /// <summary>Intersection of two unbounded lines in plan -> (x, y) or null when parallel.</summary>
    private static (double x, double y)? Intersect2D(DB.Line a, DB.Line b)
    {
        var p = a.GetEndPoint(0);
        var r = a.Direction;
        var q = b.GetEndPoint(0);
        var s = b.Direction;
        var den = r.X * s.Y - r.Y * s.X;
        if (Math.Abs(den) < 1e-9)
            return null;
        var t = ((q.X - p.X) * s.Y - (q.Y - p.Y) * s.X) / den;
        return (p.X + r.X * t, p.Y + r.Y * t);
    }

    /// <summary>Move the end of the line nearest to (x, y) onto it; the far end stays.</summary>
    private static long ToCorner(DB.LocationCurve loc, DB.Line line, double x, double y)
    {
        var a = line.GetEndPoint(0);
        var b = line.GetEndPoint(1);
        var pa = new DB.XYZ(x, y, a.Z);
        var pb = new DB.XYZ(x, y, b.Z);
        if (a.DistanceTo(pa) <= b.DistanceTo(pb))
        {
            if (pa.DistanceTo(b) < 1e-4)
                throw new RvtssError("Trimming would leave a zero-length element");
            loc.Curve = DB.Line.CreateBound(pa, b);
            return 0;
        }
        if (a.DistanceTo(pb) < 1e-4)
            throw new RvtssError("Trimming would leave a zero-length element");
        loc.Curve = DB.Line.CreateBound(a, pb);
        return 1;
    }

    private static Dict TrimExtend(Ctx ctx, List<DB.Element> elements)
    {
        var doc = ctx.Doc;
        if (elements.Count != 2)
            throw new RvtssError("trim_extend needs exactly 2 element_ids (two walls or two lines)");
        var mode = Py.Str(ctx.Get("mode", "corner")).ToLowerInvariant();
        if (mode != "corner" && mode != "single")
            throw new RvtssError("mode must be 'corner' (both elements meet) or 'single' (only the first is "
                                 + "trimmed / extended to the second)");
        var (locA, lineA) = Straight(elements[0], "trim_extend");
        var (locB, lineB) = Straight(elements[1], "trim_extend");
        var hit = Intersect2D(lineA, lineB);
        if (hit == null)
            throw new RvtssError("The two elements are parallel; there is no corner to trim or extend to");
        UnpinCheck(ctx, elements);

        Dict RunIt()
        {
            Unpin(elements);
            var ends = new Dict { ["first_end_moved"] = ToCorner(locA, lineA, hit.Value.x, hit.Value.y) };
            if (mode == "corner")
                ends["second_end_moved"] = ToCorner(locB, lineB, hit.Value.x, hit.Value.y);
            doc.Regenerate();
            ends["operation"] = "trim_extend";
            ends["mode"] = mode;
            ends["intersection"] = new Lst
            {
                Units.FromInternal(hit.Value.x, ctx.Unit, 1), Units.FromInternal(hit.Value.y, ctx.Unit, 1),
            };
            ends["elements"] = elements.Select(e => (object?)new Dict
            {
                ["id"] = Compat.IdInt(e), ["location"] = Core.ElementLocation(e, ctx.Unit),
            }).ToList();
            ends["unit"] = ctx.Unit;
            return ends;
        }

        var (result, failures) = Core.RunTransaction<Dict>(doc, "Modify trim_extend", RunIt, ctx.DryRun);
        return Core.CommitResult(result, failures, ctx.DryRun);
    }

    // -------------------------------------------------------------------------- split
    /// <summary>Point on the line from 'point' (projected onto it in plan) or 'parameter' (0-1 from the start).</summary>
    private static (DB.XYZ point, double ratio) SplitPoint(Ctx ctx, DB.Line line)
    {
        var a = line.GetEndPoint(0);
        var b = line.GetEndPoint(1);
        double ratio;
        if (ctx.Get("point") != null)
        {
            var p = Xyz(ctx, ctx.Get("point"), "point");
            var plan = Math.Pow(b.X - a.X, 2) + Math.Pow(b.Y - a.Y, 2);
            if (plan > 1e-9)
                ratio = ((p.X - a.X) * (b.X - a.X) + (p.Y - a.Y) * (b.Y - a.Y)) / plan;
            else if (Math.Abs(b.Z - a.Z) > 1e-9) // a vertical run: use the height of the point
                ratio = (p.Z - a.Z) / (b.Z - a.Z);
            else
                throw new RvtssError("The element has no length");
        }
        else if (ctx.Get("parameter") != null)
        {
            ratio = ctx.Float("parameter")!.Value;
        }
        else
        {
            throw new RvtssError("split needs 'point' (on or near the element) or 'parameter' (0-1 from its start)");
        }
        if (ratio <= 0.001 || ratio >= 0.999)
            throw new RvtssError($"The split point is not inside the element (position {ratio.ToString("F3", CultureInfo.InvariantCulture)} of its length)",
                hint: "Give a point between the two ends, or parameter between 0 and 1.");
        return (a + (b - a).Multiply(ratio), ratio);
    }

    private static void CopyParam(DB.Element src, DB.Element dst, string bipName, bool asId = false)
    {
        try
        {
            var bip = Py.EnumOrNull<DB.BuiltInParameter>(bipName) ?? throw new MissingMemberException(bipName);
            var ps = src.get_Parameter(bip);
            var pd = dst.get_Parameter(bip);
            if (ps == null || pd == null || pd.IsReadOnly)
                return;
            if (asId)
                pd.Set(ps.AsElementId());
            else
                pd.Set(ps.AsDouble());
        }
        catch (Exception ex)
        {
            Log.Write($"split: {bipName} not copied: {ex.Message}");
        }
    }

    private static DB.Wall SplitWall(Ctx ctx, DB.Wall wall, DB.XYZ point, double ratio)
    {
        var doc = ctx.Doc;
        var (loc, line) = Straight(wall, "split");
        List<DB.ElementId> inserts;
        try
        {
            inserts = wall.FindInserts(true, false, false, false).ToList();
        }
        catch
        {
            inserts = new List<DB.ElementId>();
        }
        var beyond = new List<long>();
        foreach (var iid in inserts)
        {
            var ins = doc.GetElement(iid);
            var ip = ins != null ? Core.ElementPoint(ins) : null;
            if (ip == null)
                continue;
            var a0 = line.GetEndPoint(0);
            var d = line.Direction;
            if (((ip.X - a0.X) * d.X + (ip.Y - a0.Y) * d.Y) > line.Length * ratio)
                beyond.Add(Compat.IdInt(iid));
        }
        if (beyond.Count > 0)
            throw new RvtssError($"Wall {Compat.IdInt(wall)} hosts {beyond.Count} insert(s) beyond the split point: {IntListRepr(beyond.Take(20))}",
                status: 409,
                hint: "Revit would delete them. Split the wall in Revit (Modify > Split Element), or move / "
                      + "re-host the inserts first.");
        var a = line.GetEndPoint(0);
        var b = line.GetEndPoint(1);
        var height = wall.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble();
        var offset = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble();
        var structural = false;
        try
        {
            structural = wall.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT).AsInteger() == 1;
        }
        catch { }
        loc.Curve = DB.Line.CreateBound(a, point);
        var created = DB.Wall.Create(doc, DB.Line.CreateBound(point, b), wall.GetTypeId(), wall.LevelId, height, offset,
            wall.Flipped, structural);
        CopyParam(wall, created, "WALL_HEIGHT_TYPE", asId: true); // top constraint
        CopyParam(wall, created, "WALL_TOP_OFFSET");
        try
        {
            var ps = wall.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM);
            var pd = created.get_Parameter(DB.BuiltInParameter.WALL_KEY_REF_PARAM);
            if (ps != null && pd != null && !pd.IsReadOnly)
                pd.Set(ps.AsInteger()); // location line
        }
        catch { }
        return created;
    }

    private static Dict Split(Ctx ctx, List<DB.Element> elements)
    {
        var doc = ctx.Doc;
        if (elements.Count != 1)
            throw new RvtssError("split takes exactly one element id (a duct, a pipe or a straight wall)");
        var e = elements[0];
        UnpinCheck(ctx, elements);
        var (_, line) = Straight(e, "split");
        var (point, ratio) = SplitPoint(ctx, line);
        var kind = e.GetType().Name;

        Dict RunIt()
        {
            Unpin(elements);
            DB.ElementId newId;
            if (e is DB.Wall w)
                newId = SplitWall(ctx, w, point, ratio).Id;
            else if (kind == "Duct")
                newId = DB.Mechanical.MechanicalUtils.BreakCurve(doc, e.Id, point);
            else if (kind == "Pipe")
                newId = DB.Plumbing.PlumbingUtils.BreakCurve(doc, e.Id, point);
            else
                throw new RvtssError($"split supports ducts, pipes and straight walls (got {kind})",
                    hint: "Other elements: use Modify > Split Element in Revit.");
            doc.Regenerate();
            var created = doc.GetElement(newId);
            return new Dict
            {
                ["operation"] = "split", ["id"] = Compat.IdInt(e), ["new_element_id"] = Compat.IdInt(newId),
                ["position"] = Py.Round(ratio, 4), ["unit"] = ctx.Unit,
                ["elements"] = new[] { e, created }.Where(x => x != null).Select(x => (object?)new Dict
                {
                    ["id"] = Compat.IdInt(x), ["location"] = Core.ElementLocation(x, ctx.Unit),
                }).ToList(),
            };
        }

        var (result, failures) = Core.RunTransaction<Dict>(doc, "Modify split", RunIt, ctx.DryRun);
        return Core.CommitResult(result, failures, ctx.DryRun);
    }

    // -------------------------------------------------------------------------- scale
    /// <summary>Scale positions and lengths in plan about a centre. Sizes that come from types do not change.</summary>
    private static Dict Scale(Ctx ctx, List<DB.Element> elements)
    {
        var factorN = ctx.Float("factor");
        if (factorN == null || factorN <= 0)
            throw new RvtssError("scale needs 'factor' > 0 (2 doubles lengths, 0.5 halves them)");
        var factor = factorN.Value;
        DB.XYZ c;
        if (ctx.Get("center") != null)
        {
            c = Xyz(ctx, ctx.Get("center"), "center");
        }
        else
        {
            var pts = elements.Select(Core.ElementPoint).Where(p => p != null).Select(p => p!).ToList();
            if (pts.Count == 0)
                throw new RvtssError("Cannot determine a centre; pass 'center'");
            c = new DB.XYZ(pts.Sum(p => p.X) / pts.Count, pts.Sum(p => p.Y) / pts.Count, 0.0);
        }
        UnpinCheck(ctx, elements);

        DB.XYZ Sc(DB.XYZ p) => new(c.X + (p.X - c.X) * factor, c.Y + (p.Y - c.Y) * factor, p.Z);

        Dict? One(DB.Element e)
        {
            if (e.Pinned)
                e.Pinned = false;
            var loc = e.Location;
            if (loc is DB.LocationCurve lc)
            {
                var cv = lc.Curve;
                if (cv is DB.Line && cv.IsBound)
                    lc.Curve = DB.Line.CreateBound(Sc(cv.GetEndPoint(0)), Sc(cv.GetEndPoint(1)));
                else if (cv is DB.Arc && cv.IsBound)
                    lc.Curve = DB.Arc.Create(Sc(cv.GetEndPoint(0)), Sc(cv.GetEndPoint(1)), Sc(cv.Evaluate(0.5, true)));
                else
                    throw new RvtssError($"Element {Compat.IdInt(e)} is not a bound line or arc");
                return new Dict { ["id"] = Compat.IdInt(e), ["scaled"] = "curve" };
            }
            if (loc is DB.LocationPoint lp)
            {
                var p = lp.Point;
                DB.ElementTransformUtils.MoveElement(ctx.Doc, e.Id, Sc(p) - p);
                return new Dict { ["id"] = Compat.IdInt(e), ["scaled"] = "position_only" };
            }
            throw new RvtssError($"Element {Compat.IdInt(e)} has no location line or point (sketch-based elements such as floors "
                                 + "cannot be scaled)");
        }

        return Run(ctx, "scale", elements, One, new Dict
        {
            ["factor"] = factor, ["center"] = Core.XyzList(c, ctx.Unit),
            ["note"] = "Lengths of line-based elements and the positions of point-based ones are scaled in plan. "
                       + "Sizes that come from types (wall thickness, family sizes) and sketch-based elements do not "
                       + "scale.",
        });
    }

    // --------------------------------------------------------------------------- flip
    private static Dict Flip(Ctx ctx, List<DB.Element> elements)
    {
        var what = Py.Str(ctx.Get("flip", "auto")).ToLowerInvariant();
        if (what != "auto" && what != "hand" && what != "facing" && what != "both" && what != "work_plane")
            throw new RvtssError("flip must be auto, hand, facing, both or work_plane");

        Dict? One(DB.Element e)
        {
            if (e is DB.Wall wall)
            {
                wall.Flip();
                return new Dict { ["id"] = Compat.IdInt(e), ["flipped"] = new Lst { "wall" }, ["is_flipped"] = wall.Flipped };
            }
            if (e is DB.FamilyInstance fi)
            {
                var done = new Lst();
                if ((what == "auto" || what == "hand" || what == "both") && fi.CanFlipHand)
                {
                    fi.flipHand();
                    done.Add("hand");
                }
                if (what == "facing" || what == "both" || (what == "auto" && done.Count == 0))
                {
                    if (fi.CanFlipFacing)
                    {
                        fi.flipFacing();
                        done.Add("facing");
                    }
                }
                if (what == "work_plane")
                {
                    if (fi.CanFlipWorkPlane)
                    {
                        fi.IsWorkPlaneFlipped = !fi.IsWorkPlaneFlipped;
                        done.Add("work_plane");
                    }
                }
                if (done.Count == 0)
                    throw new RvtssError($"Family instance {Compat.IdInt(e)} cannot be flipped that way (the family has no '{what}' "
                                         + "flip control)");
                return new Dict { ["id"] = Compat.IdInt(e), ["flipped"] = done };
            }
            throw new RvtssError($"Element {Compat.IdInt(e)} ({e.GetType().Name}) cannot be flipped; flip works on walls and family "
                                 + "instances");
        }

        return Run(ctx, "flip", elements, One);
    }

    // ------------------------------------------------------------------- cut / uncut
    /// <summary>The first element is cut by each of the others (void family instances or solids).</summary>
    private static Dict Cut(Ctx ctx, List<DB.Element> elements, string op)
    {
        var doc = ctx.Doc;
        if (elements.Count < 2)
            throw new RvtssError($"{op} needs at least 2 element_ids: the element to cut, then the cutting "
                                 + "elements");
        var target = elements[0];
        var cutters = elements.Skip(1).ToList();
        var add = op == "cut";

        Dict? One(DB.Element cutter)
        {
            var r = new Dict { ["target_id"] = Compat.IdInt(target), ["cutter_id"] = Compat.IdInt(cutter) };
            var voidCut = false;
            if (cutter is DB.FamilyInstance)
            {
                try
                {
                    voidCut = DB.InstanceVoidCutUtils.CanBeCutWithVoid(target);
                }
                catch
                {
                    voidCut = false;
                }
            }
            if (voidCut)
            {
                var exists = DB.InstanceVoidCutUtils.InstanceVoidCutExists(target, cutter);
                if (add && !exists)
                {
                    try
                    {
                        DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, target, cutter);
                        r["method"] = "instance_void";
                        return r;
                    }
                    catch (Exception ex) // no unattached void in the family: try a solid cut below
                    {
                        r["instance_void_error"] = Utils.NormalizeString(ex.Message);
                    }
                }
                else if (!add && exists)
                {
                    DB.InstanceVoidCutUtils.RemoveInstanceVoidCut(doc, target, cutter);
                    r["method"] = "instance_void";
                    return r;
                }
                else if (add)
                {
                    r["method"] = "instance_void";
                    r["already"] = true;
                    return r;
                }
            }
            bool? solidExists;
            try
            {
                solidExists = DB.SolidSolidCutUtils.CutExistsBetweenElements(target, cutter, out _);
            }
            catch
            {
                solidExists = null;
            }
            if (add)
            {
                if (solidExists == true)
                {
                    r["method"] = "solid";
                    r["already"] = true;
                    return r;
                }
                DB.SolidSolidCutUtils.AddCutBetweenSolids(doc, target, cutter);
            }
            else
            {
                if (solidExists == false)
                    throw new RvtssError($"No cut exists between {Compat.IdInt(target)} and {Compat.IdInt(cutter)}");
                DB.SolidSolidCutUtils.RemoveCutBetweenSolids(doc, target, cutter);
            }
            r["method"] = "solid";
            return r;
        }

        return Run(ctx, op, cutters, One, new Dict
        {
            ["target_id"] = Compat.IdInt(target),
            ["note"] = "Solid cuts work for the category pairs Revit allows (e.g. a void-like generic model or "
                       + "structural framing cutting a wall, floor or column); instance voids need a family with an "
                       + "unattached void and 'Cut with Voids When Loaded'.",
        }, atomicDefault: false);
    }

    // ------------------------------------------------------------------------- paint
    private static DB.Material GetMaterial(DB.Document doc, object? reference)
    {
        if (reference == null || (reference is string empty && empty.Length == 0))
            throw new RvtssError("paint needs 'material' (name or id); list_materials lists them");
        var text = Py.Str(reference);
        var digits = text.TrimStart('-');
        if (digits.Length > 0 && digits.All(char.IsDigit))
        {
            var m = doc.GetElement(Compat.MakeId(Py.ToInt(reference)));
            if (m is DB.Material mat)
                return mat;
        }
        var mats = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Material)).Cast<DB.Material>().ToList();
        var low = text.Trim().ToLowerInvariant();
        foreach (var m in mats)
        {
            if (Utils.NormalizeString(m.Name).ToLowerInvariant() == low)
                return m;
        }
        throw Core.NotFound("Material", reference, mats.Select(m => m.Name), hint: "list_materials lists the materials.");
    }

    /// <summary>Faces of the element's own solids (faces inside family instance geometry cannot be painted).</summary>
    private static List<DB.Face> OwnFaces(DB.Element e)
    {
        var opt = new DB.Options { ComputeReferences = true, DetailLevel = DB.ViewDetailLevel.Fine };
        var geom = e.get_Geometry(opt);
        var faces = new List<DB.Face>();
        if (geom == null)
            return faces;
        foreach (var obj in geom)
        {
            if (obj is DB.Solid solid && solid.Faces.Size > 0)
            {
                foreach (DB.Face f in solid.Faces)
                    faces.Add(f);
            }
        }
        return faces;
    }

    private static List<DB.Face> FacesFromReferences(DB.Element e, IEnumerable<DB.Reference> refs) =>
        refs.Select(r => e.GetGeometryObjectFromReference(r)).Where(f => f != null).OfType<DB.Face>().ToList();

    private static List<DB.Face> Faces(DB.Document doc, DB.Element e, string side)
    {
        if (side == "interior" || side == "exterior")
        {
            if (e is not DB.Wall wall)
                throw new RvtssError($"faces='{side}' works on walls only (element {Compat.IdInt(e)})");
            var shell = side == "interior" ? DB.ShellLayerType.Interior : DB.ShellLayerType.Exterior;
            var refs = DB.HostObjectUtils.GetSideFaces(wall, shell).ToList();
            return FacesFromReferences(e, refs);
        }
        if (side == "top" || side == "bottom")
        {
            if (e is DB.HostObject && e is not DB.Wall)
            {
                try
                {
                    var refs = (side == "top" ? DB.HostObjectUtils.GetTopFaces((DB.HostObject)e)
                        : DB.HostObjectUtils.GetBottomFaces((DB.HostObject)e)).ToList();
                    var faces = FacesFromReferences(e, refs);
                    if (faces.Count > 0)
                        return faces;
                }
                catch (Exception ex)
                {
                    Log.Write($"paint: host faces of {Compat.IdInt(e)}: {ex.Message}");
                }
            }
            var want = side == "top" ? 1.0 : -1.0;
            var o = new List<DB.Face>();
            foreach (var f in OwnFaces(e))
            {
                if (f is DB.PlanarFace pf && Math.Abs(pf.FaceNormal.Z - want) < 1e-3)
                    o.Add(f);
            }
            return o;
        }
        return OwnFaces(e);
    }

    private static Dict Paint(Ctx ctx, List<DB.Element> elements, string op)
    {
        var doc = ctx.Doc;
        var side = Py.Str(ctx.Get("faces", "all")).ToLowerInvariant();
        if (side != "all" && side != "top" && side != "bottom" && side != "interior" && side != "exterior")
            throw new RvtssError("faces must be all, top, bottom, interior or exterior");
        var mat = op == "paint" ? GetMaterial(doc, ctx.Get("material")) : null;

        Dict? One(DB.Element e)
        {
            var faces = Faces(doc, e, side);
            if (faces.Count == 0)
                throw new RvtssError($"Element {Compat.IdInt(e)} has no '{side}' face that can be painted (family instances are painted "
                                     + "in the family)");
            long n = 0;
            foreach (var f in faces)
            {
                if (op == "paint")
                {
                    doc.Paint(e.Id, f, mat!.Id);
                    n++;
                }
                else if (doc.IsPainted(e.Id, f))
                {
                    doc.RemovePaint(e.Id, f);
                    n++;
                }
            }
            return new Dict { ["id"] = Compat.IdInt(e), ["faces"] = n };
        }

        var extra = new Dict { ["faces"] = side };
        if (mat != null)
            extra["material"] = Utils.NormalizeString(mat.Name);
        return Run(ctx, op, elements, One, extra);
    }

    // ------------------------------------------------------------------------- parts
    private static List<long> AssociatedParts(DB.Document doc, DB.Element e)
    {
        try
        {
            return DB.PartUtils.GetAssociatedParts(doc, e.Id, false, true).Select(i => i.Value).ToList();
        }
        catch
        {
            return new List<long>();
        }
    }

    private static Dict CreateParts(Ctx ctx, List<DB.Element> elements)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var ids = Core.ToIdList(elements.Select(e => e.Id).ToList());
        if (!DB.PartUtils.AreElementsValidForCreateParts(doc, ids))
        {
            var bad = elements.Where(e => !DB.PartUtils.AreElementsValidForCreateParts(doc, Core.ToIdList(new[] { e.Id })))
                .Select(e => Compat.IdInt(e)).ToList();
            throw new RvtssError($"Parts cannot be created from: {IntListRepr(bad.Take(20))}", status: 409,
                hint: "Parts come from walls, floors, roofs, ceilings and structural elements that "
                      + "have no parts yet.");
        }
        var preview = Core.ConfirmGate(ctx, elements.Count, "modify_elements create_parts");
        var dry = preview || ctx.DryRun;

        Dict RunIt()
        {
            DB.PartUtils.CreateParts(doc, ids);
            doc.Regenerate();
            var res = elements.Select(e => (id: Compat.IdInt(e), parts: AssociatedParts(doc, e))).ToList();
            return new Dict
            {
                ["operation"] = "create_parts", ["count"] = (long)elements.Count,
                ["results"] = res.Take(200).Select(r => (object?)new Dict { ["id"] = r.id, ["part_ids"] = r.parts.Select(p => (object?)p).ToList() }).ToList(),
                ["parts_created"] = (long)res.Sum(r => r.parts.Count),
                ["note"] = "Parts show in views whose Parts Visibility is 'Show Parts'.",
            };
        }

        var (result, failures) = Core.RunTransaction<Dict>(doc, "Modify create_parts", RunIt, dry);
        return Core.PreviewStatus(Core.CommitResult(result, failures, dry), preview);
    }

    /// <summary>Divide parts (or the parts of the given source elements) by levels / grids / reference planes
    /// and / or by plan lines sketched at a level.</summary>
    private static Dict DivideParts(Ctx ctx, List<DB.Element> elements)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var partIds = new List<DB.ElementId>();
        foreach (var e in elements)
        {
            if (e is DB.Part)
            {
                partIds.Add(e.Id);
            }
            else
            {
                var found = DB.PartUtils.GetAssociatedParts(doc, e.Id, false, true).ToList();
                if (found.Count == 0)
                    throw new RvtssError($"Element {Compat.IdInt(e)} is not a part and has no parts",
                        hint: "Run operation='create_parts' on it first.");
                partIds.AddRange(found);
            }
        }
        var dividers = Core.GetElements(doc, ctx.List("divider_ids"), "Divider");
        var rawLines = ctx.List("lines");
        if (dividers.Count == 0 && rawLines.Count == 0)
            throw new RvtssError("divide_parts needs 'divider_ids' (levels, grids, reference planes) and / or "
                                 + "'lines' ([[[x, y], [x, y]], ...])");
        var level = ctx.Get("level") != null ? Core.FindLevel(doc, ctx.Get("level")) : null;
        if (rawLines.Count > 0 && level == null)
            throw new RvtssError("'lines' need 'level' (the plane the dividing lines are sketched on)");
        var ids = Core.ToIdList(partIds);
        if (!DB.PartUtils.ArePartsValidForDivide(doc, ids))
            throw new RvtssError("These parts cannot be divided (already divided, or not parts)", status: 409);

        Dict RunIt()
        {
            var curves = new List<DB.Curve>();
            var sketchId = DB.ElementId.InvalidElementId;
            if (rawLines.Count > 0)
            {
                var z = level!.Elevation;
                foreach (var ln in rawLines)
                {
                    if (ln is not Lst pair || pair.Count != 2)
                        throw new RvtssError("Each line is [[x, y], [x, y]]");
                    var a = Units.PointFrom(pair[0], ctx.Unit);
                    var b = Units.PointFrom(pair[1], ctx.Unit);
                    curves.Add(DB.Line.CreateBound(new DB.XYZ(a.x, a.y, z), new DB.XYZ(b.x, b.y, z)));
                }
                sketchId = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, new DB.XYZ(0, 0, z))).Id;
            }
            var maker = DB.PartUtils.DivideParts(doc, ids, Core.ToIdList(dividers.Select(d => d.Id).ToList()), curves, sketchId);
            if (maker == null)
                throw new RvtssError("Revit did not divide the parts (do the dividers cross them?)");
            doc.Regenerate();
            var newParts = new List<long>();
            foreach (var pid in partIds)
            {
                try
                {
                    newParts.AddRange(DB.PartUtils.GetAssociatedParts(doc, pid, false, true).Select(i => i.Value).ToList());
                }
                catch { }
            }
            return new Dict
            {
                ["operation"] = "divide_parts", ["divided_part_ids"] = partIds.Select(i => (object?)Compat.IdInt(i)).Take(200).ToList(),
                ["part_maker_id"] = Compat.IdInt(maker), ["new_part_ids"] = newParts.Take(500).Select(i => (object?)i).ToList(),
                ["unit"] = ctx.Unit,
            };
        }

        var (result, failures) = Core.RunTransaction<Dict>(doc, "Modify divide_parts", RunIt, ctx.DryRun);
        return Core.CommitResult(result, failures, ctx.DryRun);
    }

    // ------------------------------------------------------------------------- route
    public static Dict? ModifyElements(Ctx ctx)
    {
        var doc = ctx.Doc;
        var op = Py.Str(ctx.Require("operation")).ToLowerInvariant();
        if (!Operations.Contains(op))
            throw new RvtssError("operation must be one of: " + string.Join(", ", Operations),
                hint: "move / copy / rotate / mirror / array / pin / join are in transform_elements.");
        var elements = Core.GetElements(doc, ctx.List("element_ids"));
        if (elements.Count == 0)
            throw new RvtssError("element_ids is required");
        if (op == "align")
            return Align(ctx, elements);
        if (op == "offset")
            return Offset(ctx, elements);
        if (op == "trim_extend")
            return TrimExtend(ctx, elements);
        if (op == "split")
            return Split(ctx, elements);
        if (op == "scale")
            return Scale(ctx, elements);
        if (op == "flip")
            return Flip(ctx, elements);
        if (op == "cut" || op == "uncut")
            return Cut(ctx, elements, op);
        if (op == "paint" || op == "remove_paint")
            return Paint(ctx, elements, op);
        if (op == "create_parts")
            return CreateParts(ctx, elements);
        return DivideParts(ctx, elements);
    }

    public static void Register(RouteTable api)
    {
        api.Post("/modify/elements/", ModifyElements, "modify_elements");
    }
}
