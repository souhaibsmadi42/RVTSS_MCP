namespace RvtssHost.Modules;

/// <summary>
/// MEP editing: connections and fittings, flex / placeholder / inline parts, insulation, systems (RVTSS v2.4).
/// Port of revit_mcp/mep_edit.py.
///
/// Routes:
///     POST /mep/connect/          connect two connectors; elbow / tee / cross / transition / union fittings;
///                                 cap open ends; disconnect
///     POST /mep/create/           flex ducts and pipes, duct / pipe placeholders (and converting them), a family
///                                 instance inserted on a duct or pipe, an air terminal connected to a duct
///     POST /mep/insulation/       list / add / remove insulation on ducts and pipes, lining on ducts
///     POST /mep/systems/manage/   create a duct or piping system, add / remove elements, rename, set the system
///                                 type of ducts / pipes; electrical circuits and panel schedules
///
/// The Revit API has no automatic duct / pipe sizing; sizes are set with set_parameters.
/// </summary>
public static class MepEdit
{
    public static readonly string[] DuctCats = { "OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_FlexDuctCurves" };
    public static readonly string[] PipeCats = { "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves" };
    public static readonly string[] LiningCats = { "OST_DuctCurves", "OST_DuctFitting" };

    public static readonly Dictionary<string, int> Fittings = new()
    {
        ["elbow"] = 2, ["transition"] = 2, ["union"] = 2, ["tee"] = 3, ["cross"] = 4,
    };

    private static string? Bic(DB.Element e)
    {
        try
        {
            return e.Category != null ? Compat.BicFromCategory(e.Category) : null;
        }
        catch
        {
            return null;
        }
    }

    private static string? Family(DB.Element e)
    {
        var b = Bic(e);
        if (DuctCats.Contains(b) || b == "OST_DuctTerminal")
            return "duct";
        if (PipeCats.Contains(b))
            return "pipe";
        return null;
    }

    private static string Err(Exception ex) => ex is RvtssError ? ex.Message : Utils.NormalizeString(ex.Message);

    private static DB.ElementType NamedType(DB.Document doc, Type cls, object? name, string what)
    {
        var types = new DB.FilteredElementCollector(doc).OfClass(cls).Cast<DB.ElementType>().ToList();
        if (types.Count == 0)
            throw new RvtssError($"No {what} exists in '{doc.Title}'", status: 409,
                hint: "Start from an MEP template or transfer the types into this project.");
        if (name == null || (name is string empty && empty.Length == 0))
            return types[0];
        var key = Py.Str(name).Trim().ToLowerInvariant();
        foreach (var t in types)
        {
            if (Utils.NormalizeString(Utils.GetElementName(t)).ToLowerInvariant() == key
                || Py.Str(Compat.IdInt(t)) == key)
                return t;
        }
        throw Core.NotFound(what, name, types.Select(t => Utils.GetElementName(t)));
    }

    private static List<DB.Connector> Physical(DB.Element e) => Mep.Connectors(e).Where(Mep.IsPhysical).ToList();

    private static List<DB.Connector> Open(DB.Element e) => Physical(e).Where(c => !c.IsConnected).ToList();

    /// <summary>Closest pair of connectors of two elements, open ones first.</summary>
    private static (double d, DB.Connector x, DB.Connector y) NearestPair(DB.Element a, DB.Element b)
    {
        var ca = Open(a);
        if (ca.Count == 0)
            ca = Physical(a);
        var cb = Open(b);
        if (cb.Count == 0)
            cb = Physical(b);
        if (ca.Count == 0 || cb.Count == 0)
        {
            var missing = ca.Count == 0 ? a : b;
            throw new RvtssError($"Element {Compat.IdInt(missing)} has no connectors", status: 409,
                hint: "Use ducts, pipes, cable trays, conduit, fittings, accessories or equipment.");
        }
        (double d, DB.Connector x, DB.Connector y)? best = null;
        foreach (var x in ca)
        {
            foreach (var y in cb)
            {
                var d = x.Origin.DistanceTo(y.Origin);
                if (best == null || d < best.Value.d)
                    best = (d, x, y);
            }
        }
        return best!.Value;
    }

    private static DB.Connector NearestTo(DB.Element e, DB.XYZ point, IList<DB.Connector>? exclude = null)
    {
        exclude ??= new List<DB.Connector>();
        (double d, DB.Connector c)? best = null;
        var open = Open(e);
        foreach (var c in open.Count > 0 ? open : Physical(e))
        {
            if (exclude.Any(x => c.Id == x.Id && c.Owner.Id == x.Owner.Id))
                continue;
            var d = c.Origin.DistanceTo(point);
            if (best == null || d < best.Value.d)
                best = (d, c);
        }
        if (best == null)
            throw new RvtssError($"Element {Compat.IdInt(e)} has no free connector", status: 409);
        return best.Value.c;
    }

    // ------------------------------------------------------------------- connect / fittings
    /// <summary>Connectors meeting at one joint: the pair of the first two elements, then the nearest of the others.</summary>
    private static List<DB.Connector> FittingConnectors(List<DB.Element> elements, int n)
    {
        var (_, c1, c2) = NearestPair(elements[0], elements[1]);
        var cons = new List<DB.Connector> { c1, c2 };
        // elements[2:n]
        for (var i = 2; i < Math.Min(n, elements.Count); i++)
            cons.Add(NearestTo(elements[i], c1.Origin, cons));
        return cons;
    }

    public static Dict? Connect(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = ctx.Get("action", "connect") as string ?? "";
        var ids = ctx.List("element_ids");
        var unit = ctx.Unit;
        var dry = ctx.DryRun;

        if (Fittings.ContainsKey(action) || action == "connect")
        {
            var need = Fittings.TryGetValue(action, out var nn) ? nn : 2;
            if (ids.Count != need)
                throw new RvtssError($"{action} needs exactly {need} element_ids",
                    hint: "tee: [run 1, run 2, branch]; cross: [run 1, run 2, branch 1, branch 2].");
            var elements = Core.GetElements(doc, ids);

            Dict Run()
            {
                var cons = FittingConnectors(elements, need);
                var gap = cons[0].Origin.DistanceTo(cons[1].Origin);
                if (action == "connect")
                {
                    if (cons[0].IsConnectedTo(cons[1]))
                        return new Dict { ["action"] = action, ["already_connected"] = true };
                    if (gap > Units.ToInternal(ctx.Float("tolerance", 1.0) ?? 1.0, unit))
                        throw new RvtssError($"The nearest connectors are {Py.Str(Units.FromInternal(gap, unit, 1))} {unit} apart", status: 409,
                            hint: "Move the ends together (transform_elements) or use action='elbow' / 'transition'.");
                    cons[0].ConnectTo(cons[1]);
                    return new Dict
                    {
                        ["action"] = action,
                        ["connected"] = cons.Select(c => (object?)new Lst { Compat.IdInt(c.Owner), (long)c.Id }).ToList(),
                    };
                }
                var create = doc.Create;
                DB.FamilyInstance? fit;
                if (action == "elbow")
                    fit = create.NewElbowFitting(cons[0], cons[1]);
                else if (action == "transition")
                    fit = create.NewTransitionFitting(cons[0], cons[1]);
                else if (action == "union")
                    fit = create.NewUnionFitting(cons[0], cons[1]);
                else if (action == "tee")
                    fit = create.NewTeeFitting(cons[0], cons[1], cons[2]);
                else
                    fit = create.NewCrossFitting(cons[0], cons[1], cons[2], cons[3]);
                if (fit == null)
                    throw new RvtssError($"Revit created no {action} fitting", status: 409,
                        hint: "Check the routing preferences of the duct / pipe type.");
                var o = new Dict { ["action"] = action, ["fitting_id"] = Compat.IdInt(fit) };
                try
                {
                    var sym = doc.GetElement(fit.GetTypeId());
                    o["fitting_type"] = Utils.NormalizeString(Utils.GetElementName(sym));
                }
                catch { }
                return o;
            }

            Dict result;
            Lst fails;
            try
            {
                (result, fails) = Core.RunTransaction<Dict>(doc, "MEP " + action, Run, dry);
            }
            catch (RvtssError)
            {
                throw;
            }
            catch (Exception ex)
            {
                throw new RvtssError($"Revit could not create the {action}: {Err(ex)}", status: 409,
                    hint: "The type's routing preferences need a matching fitting, and the elements "
                          + "must meet at one point (tee / cross: the first two are the straight run).");
            }
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "cap")
        {
            if (ids.Count == 0)
                throw new RvtssError("'element_ids' is required (ducts or pipes with open ends)");
            var elements = Core.GetElements(doc, ids);
            var preview = Core.ConfirmGate(ctx, elements.Count, "mep_connect cap");
            dry = preview || ctx.DryRun;

            Dict? CapOne(object? item)
            {
                var e = (DB.Element)item!;
                var fam = Family(e);
                var before = Open(e).Count;
                if (before == 0)
                    return new Dict { ["id"] = Compat.IdInt(e), ["open_ends"] = 0L, ["capped"] = 0L };
                if (fam == "duct")
                {
                    // checked live (Revit 2026): MechanicalUtils has no PlaceCapOnOpenEnds, only PlumbingUtils does
                    throw new RvtssError("The Revit API caps open ends of pipes only, not ducts",
                        hint: "Cap the duct in Revit (Modify | Ducts > Cap Open Ends), or place an end-cap "
                              + "fitting with create_mep_parts(action='insert_on_curve').");
                }
                else if (fam == "pipe")
                {
                    try
                    {
                        DB.Plumbing.PlumbingUtils.PlaceCapOnOpenEnds(doc, e.Id, DB.ElementId.InvalidElementId);
                    }
                    catch (Exception ex)
                    {
                        throw new RvtssError($"Revit could not cap pipe {Compat.IdInt(e)}: {Err(ex)}",
                            hint: "The pipe type's routing preferences need a cap fitting: load a pipe "
                                  + "cap family and add it under Routing Preferences > Caps.");
                    }
                }
                else
                {
                    throw new RvtssError("caps exist for pipes only");
                }
                doc.Regenerate();
                return new Dict { ["id"] = Compat.IdInt(e), ["open_ends"] = (long)before, ["capped"] = (long)(before - Open(e).Count) };
            }

            Dict Run()
            {
                return new Dict { ["action"] = action, ["results"] = Core.Batch(doc, elements, CapOne, ctx.Bool("atomic", false)) };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP cap open ends", Run, dry);
            return Core.PreviewStatus(Core.CommitResult(result, fails, dry), preview);
        }

        if (action == "disconnect")
        {
            if (ids.Count == 0 || ids.Count > 2)
                throw new RvtssError("disconnect needs 1 element (all its connections) or 2 elements (between them)");
            var elements = Core.GetElements(doc, ids);
            DB.ElementId? other = elements.Count == 2 ? elements[1].Id : null;

            Dict Run()
            {
                var done = new Lst();
                foreach (var c in Physical(elements[0]))
                {
                    if (!c.IsConnected)
                        continue;
                    foreach (var rf in c.AllRefs.Cast<DB.Connector>().ToList())
                    {
                        var o = rf.Owner;
                        if (o == null || o.Id == elements[0].Id || !Mep.IsPhysical(rf))
                            continue;
                        if (other != null && o.Id != other)
                            continue;
                        c.DisconnectFrom(rf);
                        done.Add(new Dict { ["connector_id"] = (long)c.Id, ["from_element_id"] = Compat.IdInt(o), ["from_connector_id"] = (long)rf.Id });
                    }
                }
                return new Dict { ["action"] = action, ["disconnected"] = done, ["count"] = (long)done.Count };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP disconnect", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        throw new RvtssError("action must be connect, elbow, tee, cross, transition, union, cap or disconnect");
    }

    // ------------------------------------------------------------------------ create parts
    private static List<DB.XYZ> Points(Ctx ctx, DB.Level level, int minimum = 2)
    {
        var raw = ctx.List("points");
        if (raw.Count < minimum)
            throw new RvtssError($"'points' needs at least {minimum} points [[x, y(, z)], ...]");
        var off = Units.ToInternal(ctx.Float("offset", 0.0) ?? 0.0, ctx.Unit);
        var pts = new List<DB.XYZ>();
        foreach (var p in raw)
        {
            var (x, y, z) = Units.PointFrom(p, ctx.Unit);
            pts.Add(new DB.XYZ(x, y, PureText.Iter(p).Count() == 3 ? z : level.Elevation + off));
        }
        for (var i = 0; i + 1 < pts.Count; i++)
        {
            if (pts[i].DistanceTo(pts[i + 1]) < 1e-4)
                throw new RvtssError("Two consecutive points are the same");
        }
        return pts;
    }

    private static DB.XYZ Point(Ctx ctx, string key = "point")
    {
        var v = ctx.Get(key);
        if (v == null)
            throw new RvtssError($"'{key}' is required: [x, y, z]");
        var (x, y, z) = Units.PointFrom(v, ctx.Unit);
        return new DB.XYZ(x, y, z);
    }

    private static (DB.LocationCurve loc, DB.Curve curve) CurveOf(DB.Element e)
    {
        var loc = e.Location as DB.LocationCurve;
        var curve = loc?.Curve;
        if (curve == null || e is not DB.MEPCurve)
            throw new RvtssError($"Element {Compat.IdInt(e)} is not a duct or pipe", status: 409);
        return (loc!, curve);
    }

    /// <summary>Break a straight duct / pipe at a point, place a family instance there and connect both sides.</summary>
    private static Dict? InsertOnCurve(Ctx ctx)
    {
        var doc = ctx.Doc;
        var host = Core.GetElement(doc, ctx.Require("host_id"), "Duct / pipe");
        var fam = Family(host);
        if (fam != "duct" && fam != "pipe")
            throw new RvtssError("host_id must be a duct or a pipe", status: 409);
        var (_, curve) = CurveOf(host);
        DB.ElementType symType;
        if (ctx.Get("type_id") != null)
            symType = Core.FindType(doc, typeId: ctx.Get("type_id"));
        else
            symType = Core.FindType(doc, family: ctx.Get("family"), typeName: ctx.Require("type"));
        if (symType is not DB.FamilySymbol sym)
            throw new RvtssError("The type is not a loadable family type");
        var point = curve.Project(Point(ctx)).XYZPoint;
        var ends = new[] { curve.GetEndPoint(0), curve.GetEndPoint(1) };
        if (Math.Min(point.DistanceTo(ends[0]), point.DistanceTo(ends[1])) < 1e-3)
            throw new RvtssError("The point is at the end of the duct / pipe; pick a point along it");
        var direction = (ends[1] - ends[0]).Normalize();

        Dict Run()
        {
            if (!sym.IsActive)
                sym.Activate();
            DB.ElementId newId;
            if (fam == "duct")
                newId = DB.Mechanical.MechanicalUtils.BreakCurve(doc, host.Id, point);
            else
                newId = DB.Plumbing.PlumbingUtils.BreakCurve(doc, host.Id, point);
            var other = doc.GetElement(newId);
            var refLevel = ((DB.MEPCurve)host).ReferenceLevel;
            var level = refLevel != null ? doc.GetElement(refLevel.Id) as DB.Level : null;
            DB.FamilyInstance inst;
            if (level != null)
                inst = doc.Create.NewFamilyInstance(point, sym, level, DB.Structure.StructuralType.NonStructural);
            else
                inst = doc.Create.NewFamilyInstance(point, sym, DB.Structure.StructuralType.NonStructural);
            doc.Regenerate();
            string? note = null;
            if (Math.Abs(direction.Z) < 0.999)
            {
                var angle = Math.Atan2(direction.Y, direction.X);
                if (Math.Abs(angle) > 1e-9)
                {
                    var axis = DB.Line.CreateBound(point, new DB.XYZ(point.X, point.Y, point.Z + 1.0));
                    DB.ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle);
                }
            }
            else
            {
                note = "Vertical run: the instance was not rotated; check its orientation.";
            }
            try
            {
                var move = point - ((DB.LocationPoint)inst.Location).Point;
                if (move.GetLength() > 1e-6)
                    DB.ElementTransformUtils.MoveElement(doc, inst.Id, move);
            }
            catch { }
            doc.Regenerate();
            var connected = new Lst();
            var errors = new Lst();
            foreach (var c in Physical(inst))
            {
                try
                {
                    // which piece lies on this connector's side of the break
                    (DB.Element cand, DB.LocationCurve cl, DB.Curve cc)? piece = null;
                    foreach (var candidate in new[] { host, other })
                    {
                        var (cl0, cc0) = CurveOf(candidate);
                        var mid = cc0.Evaluate(0.5, true);
                        if (((mid - point).DotProduct(direction) < 0) == ((c.Origin - point).DotProduct(direction) < 0))
                            piece = (candidate, cl0, cc0);
                    }
                    if (piece == null)
                        throw new RvtssError("no duct / pipe piece on this side");
                    var (cand2, cl, cc) = piece.Value;
                    var e0 = cc.GetEndPoint(0);
                    var e1 = cc.GetEndPoint(1);
                    var far = e0.DistanceTo(point) > e1.DistanceTo(point) ? e0 : e1;
                    if (far.DistanceTo(c.Origin) < 1e-3)
                        throw new RvtssError("the remaining piece is shorter than the inserted part");
                    cl.Curve = far.IsAlmostEqualTo(e0) ? DB.Line.CreateBound(far, c.Origin) : DB.Line.CreateBound(c.Origin, far);
                    doc.Regenerate();
                    c.ConnectTo(NearestTo(cand2, c.Origin));
                    connected.Add(new Dict { ["connector_id"] = (long)c.Id, ["element_id"] = Compat.IdInt(cand2) });
                }
                catch (Exception ex)
                {
                    errors.Add(new Dict { ["connector_id"] = (long)c.Id, ["error"] = Err(ex) });
                }
            }
            var o = new Dict
            {
                ["action"] = "insert_on_curve", ["id"] = Compat.IdInt(inst), ["host_id"] = Compat.IdInt(host),
                ["new_piece_id"] = Compat.IdInt(other), ["family"] = Utils.NormalizeString(sym.FamilyName),
                ["type"] = Utils.NormalizeString(Utils.GetElementName(sym)), ["connected"] = connected,
            };
            if (errors.Count > 0)
                o["connection_errors"] = errors;
            if (!string.IsNullOrEmpty(note))
                o["note"] = note;
            return o;
        }

        var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP insert on curve", Run, ctx.DryRun);
        return Core.CommitResult(result, fails, ctx.DryRun);
    }

    public static Dict? CreateParts(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = ctx.Require("action") as string ?? "";
        var dry = ctx.DryRun;

        if (action == "flex_duct" || action == "flex_pipe" || action == "duct_placeholder" || action == "pipe_placeholder")
        {
            var level = Core.FindLevel(doc, ctx.Get("level"));
            if (level == null)
            {
                // default: the lowest level
                var levels = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Level)).Cast<DB.Level>()
                    .OrderBy(lv => lv.Elevation).ToList();
                if (levels.Count == 0)
                    throw new RvtssError("The project has no level", status: 409);
                level = levels[0];
            }
            var duct = action.EndsWith("duct", StringComparison.Ordinal) || action.StartsWith("duct", StringComparison.Ordinal);
            DB.ElementType st;
            if (duct)
                st = NamedType(doc, typeof(DB.Mechanical.MechanicalSystemType), ctx.Get("system_type"), "Duct system type");
            else
                st = NamedType(doc, typeof(DB.Plumbing.PipingSystemType), ctx.Get("system_type"), "Piping system type");
            DB.ElementType tt;
            if (action == "flex_duct")
                tt = NamedType(doc, typeof(DB.Mechanical.FlexDuctType), ctx.Get("type"), "Flex duct type");
            else if (action == "flex_pipe")
                tt = NamedType(doc, typeof(DB.Plumbing.FlexPipeType), ctx.Get("type"), "Flex pipe type");
            else if (action == "duct_placeholder")
                tt = NamedType(doc, typeof(DB.Mechanical.DuctType), ctx.Get("type"), "Duct type");
            else
                tt = NamedType(doc, typeof(DB.Plumbing.PipeType), ctx.Get("type"), "Pipe type");
            var pts = Points(ctx, level);

            Dict Run()
            {
                var ids = new Lst();
                if (action.StartsWith("flex", StringComparison.Ordinal))
                {
                    var plist = new List<DB.XYZ>(pts);
                    if (duct)
                        ids.Add(Compat.IdInt(DB.Mechanical.FlexDuct.Create(doc, st.Id, tt.Id, level.Id, plist)));
                    else
                        ids.Add(Compat.IdInt(DB.Plumbing.FlexPipe.Create(doc, st.Id, tt.Id, level.Id, plist)));
                }
                else
                {
                    for (var i = 0; i + 1 < pts.Count; i++)
                    {
                        if (duct)
                            ids.Add(Compat.IdInt(DB.Mechanical.Duct.CreatePlaceholder(doc, st.Id, tt.Id, level.Id, pts[i], pts[i + 1])));
                        else
                            ids.Add(Compat.IdInt(DB.Plumbing.Pipe.CreatePlaceholder(doc, st.Id, tt.Id, level.Id, pts[i], pts[i + 1])));
                    }
                }
                if (ctx.Get("diameter") != null)
                {
                    var bip = duct ? DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM : DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM;
                    foreach (var e in Core.GetElements(doc, ids))
                    {
                        var p = e.get_Parameter(bip);
                        if (p != null && !p.IsReadOnly)
                            p.Set(Units.ToInternal(ctx.Float("diameter")!.Value, ctx.Unit));
                    }
                }
                return new Dict
                {
                    ["action"] = action, ["ids"] = ids, ["type"] = Utils.NormalizeString(Utils.GetElementName(tt)),
                    ["system_type"] = Utils.NormalizeString(Utils.GetElementName(st)),
                };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP " + action.Replace("_", " "), Run, dry);
            return Core.CommitResult(result, fails, dry, new Dict { ["unit"] = ctx.Unit });
        }

        if (action == "convert_placeholders")
        {
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            if (elements.Count == 0)
                throw new RvtssError("'element_ids' is required (duct or pipe placeholders)");
            var ducts = elements.Where(e => Family(e) == "duct").Select(e => e.Id).ToList();
            var pipes = elements.Where(e => Family(e) == "pipe").Select(e => e.Id).ToList();
            if (ducts.Count + pipes.Count != elements.Count)
                throw new RvtssError("Only duct and pipe placeholders can be converted");

            Dict Run()
            {
                var o = new Lst();
                if (ducts.Count > 0)
                {
                    foreach (var i in DB.Mechanical.MechanicalUtils.ConvertDuctPlaceholders(doc, Core.ToIdList(ducts)))
                        o.Add(Compat.IdInt(i));
                }
                if (pipes.Count > 0)
                {
                    foreach (var i in DB.Plumbing.PlumbingUtils.ConvertPipePlaceholders(doc, Core.ToIdList(pipes)))
                        o.Add(Compat.IdInt(i));
                }
                return new Dict { ["action"] = action, ["created_ids"] = o };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP convert placeholders", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "insert_on_curve")
            return InsertOnCurve(ctx);

        if (action == "air_terminal_on_duct")
        {
            var terminal = Core.GetElement(doc, ctx.Require("terminal_id"), "Air terminal");
            var ductEl = Core.GetElement(doc, ctx.Require("host_id"), "Duct");

            Dict Run()
            {
                object? ok = DB.Mechanical.MechanicalUtils.ConnectAirTerminalOnDuct(doc, terminal.Id, ductEl.Id);
                if (ok is bool okFlag && !okFlag)
                    throw new RvtssError("Revit could not connect the air terminal to the duct", status: 409,
                        hint: "The terminal must sit on the duct face and be perpendicular to it.");
                return new Dict { ["action"] = action, ["terminal_id"] = Compat.IdInt(terminal), ["duct_id"] = Compat.IdInt(ductEl) };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP air terminal on duct", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        throw new RvtssError("action must be flex_duct, flex_pipe, duct_placeholder, pipe_placeholder, "
                             + "convert_placeholders, insert_on_curve or air_terminal_on_duct");
    }

    // -------------------------------------------------------------------------- insulation
    private static List<DB.ElementId> LayerIds(DB.Document doc, DB.Element e, string kind)
    {
        try
        {
            if (kind == "lining")
                return DB.InsulationLiningBase.GetLiningIds(doc, e.Id).ToList();
            return DB.InsulationLiningBase.GetInsulationIds(doc, e.Id).ToList();
        }
        catch
        {
            return new List<DB.ElementId>();
        }
    }

    private static Dict LayerInfo(DB.Document doc, DB.ElementId lid, string unit)
    {
        var el = doc.GetElement(lid);
        var d = new Dict { ["id"] = Compat.IdInt(lid) };
        if (el == null)
            return d;
        try
        {
            d["type"] = Utils.NormalizeString(Utils.GetElementName(doc.GetElement(el.GetTypeId())));
        }
        catch { }
        try
        {
            d["thickness"] = Units.FromInternal(((DB.InsulationLiningBase)el).Thickness, unit, 1);
        }
        catch { }
        return d;
    }

    public static Dict? Insulation(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = ctx.Get("action", "list") as string ?? "";
        var kind = Py.Str(Py.Truthy(ctx.Get("kind")) ? ctx.Get("kind") : "insulation").ToLowerInvariant();
        if (kind != "insulation" && kind != "lining")
            throw new RvtssError("kind must be insulation or lining");
        var ids = ctx.List("element_ids");
        if (ids.Count == 0)
            throw new RvtssError("'element_ids' is required (ducts, pipes, their fittings and accessories)");
        var elements = Core.GetElements(doc, ids);
        var unit = ctx.Unit;

        if (action == "list")
        {
            var o = new Lst();
            foreach (var e in elements)
            {
                var d = Core.ElementBrief(doc, e);
                d["insulation"] = LayerIds(doc, e, "insulation").Select(i => (object?)LayerInfo(doc, i, unit)).ToList();
                d["lining"] = LayerIds(doc, e, "lining").Select(i => (object?)LayerInfo(doc, i, unit)).ToList();
                o.Add(d);
            }
            return new Dict { ["unit"] = unit, ["elements"] = o };
        }

        if (action != "add" && action != "remove")
            throw new RvtssError("action must be list, add or remove");
        var preview = Core.ConfirmGate(ctx, elements.Count, "mep_insulation " + action);
        var dry = preview || ctx.DryRun;

        Func<Dict> run;
        if (action == "add")
        {
            var thickness = ctx.Float("thickness");
            if (thickness == null || thickness <= 0)
                throw new RvtssError("'thickness' (> 0, in `unit`) is required");
            var tInt = Units.ToInternal(thickness.Value, unit);
            var cache = new Dictionary<string, DB.ElementType>();

            DB.ElementType LayerType(string fam)
            {
                var key = fam + "|" + kind;
                if (!cache.ContainsKey(key))
                {
                    if (kind == "lining")
                        cache[key] = NamedType(doc, typeof(DB.Mechanical.DuctLiningType), ctx.Get("type"), "Duct lining type");
                    else if (fam == "duct")
                        cache[key] = NamedType(doc, typeof(DB.Mechanical.DuctInsulationType), ctx.Get("type"), "Duct insulation type");
                    else
                        cache[key] = NamedType(doc, typeof(DB.Plumbing.PipeInsulationType), ctx.Get("type"), "Pipe insulation type");
                }
                return cache[key];
            }

            Dict? AddOne(object? item)
            {
                var e = (DB.Element)item!;
                var b = Bic(e);
                var fam = DuctCats.Contains(b) ? "duct" : (PipeCats.Contains(b) ? "pipe" : null);
                if (fam == null || (kind == "lining" && !LiningCats.Contains(b)))
                    throw new RvtssError($"{(e.Category != null ? Utils.NormalizeString(e.Category.Name) : "element")} cannot take {kind}");
                if (LayerIds(doc, e, kind).Count > 0)
                {
                    if (!ctx.Bool("replace", false))
                        return new Dict { ["id"] = Compat.IdInt(e), ["skipped"] = $"already has {kind} (pass replace=true)" };
                    foreach (var i in LayerIds(doc, e, kind))
                        doc.Delete(i);
                }
                var lt = LayerType(fam);
                DB.Element layer;
                if (kind == "lining")
                    layer = DB.Mechanical.DuctLining.Create(doc, e.Id, lt.Id, tInt);
                else if (fam == "duct")
                    layer = DB.Mechanical.DuctInsulation.Create(doc, e.Id, lt.Id, tInt);
                else
                    layer = DB.Plumbing.PipeInsulation.Create(doc, e.Id, lt.Id, tInt);
                return new Dict { ["id"] = Compat.IdInt(e), [kind + "_id"] = Compat.IdInt(layer), ["type"] = Utils.NormalizeString(Utils.GetElementName(lt)) };
            }

            run = () => new Dict
            {
                ["action"] = action, ["kind"] = kind, ["thickness"] = thickness.Value, ["unit"] = unit,
                ["results"] = Core.Batch(doc, elements, AddOne, ctx.Bool("atomic", false)),
            };
        }
        else
        {
            Dict? RemoveOne(object? item)
            {
                var e = (DB.Element)item!;
                var layers = LayerIds(doc, e, kind);
                foreach (var i in layers)
                    doc.Delete(i);
                return new Dict { ["id"] = Compat.IdInt(e), ["removed"] = (long)layers.Count };
            }

            run = () => new Dict
            {
                ["action"] = action, ["kind"] = kind,
                ["results"] = Core.Batch(doc, elements, RemoveOne, ctx.Bool("atomic", false)),
            };
        }

        var (result, fails) = Core.RunTransaction<Dict>(doc, $"MEP {action} {kind}", run, dry);
        return Core.PreviewStatus(Core.CommitResult(result, fails, dry), preview);
    }

    // ----------------------------------------------------------------------------- systems
    private static DB.MEPSystem SystemOf(DB.Document doc, object? reference)
    {
        var key = Py.Str(reference).Trim().ToLowerInvariant();
        foreach (var el in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.MEPSystem)))
        {
            if (Py.Str(Compat.IdInt(el)) == key || Utils.NormalizeString(el.Name).ToLowerInvariant() == key)
                return (DB.MEPSystem)el;
        }
        throw new RvtssError($"MEP system '{Py.Str(reference)}' not found", status: 404, hint: "list_mep_systems lists them.");
    }

    private static (DB.ConnectorSet cs, Lst skipped) ConnectorSet(IEnumerable<DB.Element> elements, DB.Domain domain, bool freeOnly = true)
    {
        var cs = new DB.ConnectorSet();
        var skipped = new Lst();
        foreach (var e in elements)
        {
            DB.Connector? pick = null;
            foreach (var c in Mep.Connectors(e))
            {
                try
                {
                    if (c.Domain != domain)
                        continue;
                    if (freeOnly && c.MEPSystem != null)
                        continue;
                }
                catch
                {
                    continue;
                }
                pick = c;
                break;
            }
            if (pick == null)
                skipped.Add(new Dict { ["id"] = Compat.IdInt(e), ["reason"] = "no free connector of this domain" });
            else
                cs.Insert(pick);
        }
        return (cs, skipped);
    }

    private static Dict CircuitInfo(DB.Document doc, DB.Electrical.ElectricalSystem c)
    {
        var d = new Dict { ["id"] = Compat.IdInt(c), ["name"] = Utils.NormalizeString(c.Name) };
        try { d["circuit_number"] = Utils.NormalizeString(Py.Str(c.CircuitNumber)); } catch { }
        try { d["panel"] = Utils.NormalizeString(Py.Str(c.PanelName)); } catch { }
        try { d["load_name"] = Utils.NormalizeString(Py.Str(c.LoadName)); } catch { }
        try { d["system_type"] = Utils.NormalizeString(Py.Str(c.SystemType)); } catch { }
        try
        {
            d["element_ids"] = c.Elements.Cast<DB.Element>().Select(e => (object?)Compat.IdInt(e)).Take(200).ToList();
        }
        catch { }
        return d;
    }

    public static Dict? ManageSystems(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = ctx.Require("action") as string ?? "";
        var dry = ctx.DryRun;

        if (action == "list_circuits")
        {
            var items = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Electrical.ElectricalSystem))
                .Cast<DB.Electrical.ElectricalSystem>().Select(c => (object?)CircuitInfo(doc, c)).ToList();
            var limit = ctx.Int("limit", 200, 1, Core.MaxLimit)!.Value;
            return new Dict { ["count"] = (long)items.Count, ["circuits"] = items.Take((int)limit).ToList(), ["truncated"] = items.Count > limit };
        }

        if (action == "create")
        {
            var domain = Py.Truthy(ctx.Get("domain")) ? Py.Str(ctx.Get("domain")).ToLowerInvariant() : "";
            if (domain != "mechanical" && domain != "piping")
                throw new RvtssError("domain must be mechanical or piping (electrical: action='create_circuit')");
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            if (elements.Count == 0)
                throw new RvtssError("'element_ids' is required (terminals, fixtures or equipment)");
            DB.ElementType st;
            DB.Domain dom;
            if (domain == "mechanical")
            {
                st = NamedType(doc, typeof(DB.Mechanical.MechanicalSystemType), ctx.Get("system_type"), "Duct system type");
                dom = DB.Domain.DomainHvac;
            }
            else
            {
                st = NamedType(doc, typeof(DB.Plumbing.PipingSystemType), ctx.Get("system_type"), "Piping system type");
                dom = DB.Domain.DomainPiping;
            }

            Dict Run()
            {
                var (cs, skipped) = ConnectorSet(elements, dom);
                if (cs.Size == 0)
                    throw new RvtssError($"None of the elements has a free {domain} connector", status: 409).With("skipped", skipped);
                var name = ctx.Get("name");
                DB.MEPSystem system;
                if (domain == "mechanical")
                {
                    var ms = Py.Truthy(name)
                        ? DB.Mechanical.MechanicalSystem.Create(doc, st.Id, Py.Str(name))
                        : DB.Mechanical.MechanicalSystem.Create(doc, st.Id);
                    ms.Add(cs);
                    system = ms;
                }
                else
                {
                    var ps = Py.Truthy(name)
                        ? DB.Plumbing.PipingSystem.Create(doc, st.Id, Py.Str(name))
                        : DB.Plumbing.PipingSystem.Create(doc, st.Id);
                    ps.Add(cs);
                    system = ps;
                }
                return new Dict
                {
                    ["action"] = action, ["system_id"] = Compat.IdInt(system), ["name"] = Utils.NormalizeString(system.Name),
                    ["system_type"] = Utils.NormalizeString(Utils.GetElementName(st)), ["added"] = (long)cs.Size, ["skipped"] = skipped,
                };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP create system", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "add_elements" || action == "remove_elements")
        {
            var system = SystemOf(doc, ctx.Require("system"));
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            if (elements.Count == 0)
                throw new RvtssError("'element_ids' is required");
            DB.Domain dom;
            try
            {
                dom = system.ConnectorManager.Connectors.Cast<DB.Connector>().First().Domain;
            }
            catch
            {
                dom = system.GetType().Name.Contains("Piping") ? DB.Domain.DomainPiping : DB.Domain.DomainHvac;
            }

            Dict Run()
            {
                var (cs, skipped) = ConnectorSet(elements, dom, freeOnly: action == "add_elements");
                if (cs.Size == 0)
                    throw new RvtssError("No matching connector on the elements", status: 409).With("skipped", skipped);
                if (action == "add_elements")
                {
                    if (system is DB.Mechanical.MechanicalSystem ms) ms.Add(cs);
                    else if (system is DB.Plumbing.PipingSystem ps) ps.Add(cs);
                    else throw new MissingMemberException("Add");
                }
                else
                {
                    if (system is DB.Mechanical.MechanicalSystem ms) ms.Remove(cs);
                    else if (system is DB.Plumbing.PipingSystem ps) ps.Remove(cs);
                    else throw new MissingMemberException("Remove");
                }
                return new Dict { ["action"] = action, ["system_id"] = Compat.IdInt(system), ["connectors"] = (long)cs.Size, ["skipped"] = skipped };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP system " + action.Replace("_", " "), Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "rename")
        {
            var system = SystemOf(doc, ctx.Require("system"));
            var name = Py.Str(ctx.Require("name"));

            Dict Run()
            {
                var old = Utils.NormalizeString(system.Name);
                system.Name = name;
                return new Dict { ["action"] = action, ["system_id"] = Compat.IdInt(system), ["old_name"] = old, ["name"] = Utils.NormalizeString(system.Name) };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP rename system", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "set_system_type")
        {
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            if (elements.Count == 0)
                throw new RvtssError("'element_ids' is required (ducts or pipes)");
            var name = ctx.Require("system_type");
            var preview = Core.ConfirmGate(ctx, elements.Count, "manage_mep_systems set_system_type");
            dry = preview || ctx.DryRun;
            var cache = new Dictionary<string, DB.ElementType>();

            Dict? One(object? item)
            {
                var e = (DB.Element)item!;
                var fam = Family(e);
                if ((fam != "duct" && fam != "pipe") || e is not DB.MEPCurve curve)
                    throw new RvtssError("only ducts and pipes have a system type");
                if (!cache.ContainsKey(fam))
                {
                    if (fam == "duct")
                        cache[fam] = NamedType(doc, typeof(DB.Mechanical.MechanicalSystemType), name, "Duct system type");
                    else
                        cache[fam] = NamedType(doc, typeof(DB.Plumbing.PipingSystemType), name, "Piping system type");
                }
                var st = cache[fam];
                // The Python tried e.SetSystemType(st.Id) first; MEPCurve has no such method in any supported Revit
                // version (AttributeError there), so the parameter path below always ran.
                var bip = fam == "duct" ? DB.BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM : DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM;
                var p = e.get_Parameter(bip);
                if (p == null || p.IsReadOnly)
                    throw new RvtssError("the system type of this element is read-only");
                p.Set(st.Id);
                return new Dict { ["id"] = Compat.IdInt(e), ["system_type"] = Utils.NormalizeString(Utils.GetElementName(st)) };
            }

            Dict Run()
            {
                return new Dict { ["action"] = action, ["results"] = Core.Batch(doc, elements, One, ctx.Bool("atomic", false)) };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP set system type", Run, dry);
            return Core.PreviewStatus(Core.CommitResult(result, fails, dry), preview);
        }

        if (action == "create_circuit")
        {
            var elements = Core.GetElements(doc, ctx.List("element_ids"));
            if (elements.Count == 0)
                throw new RvtssError("'element_ids' is required (electrical fixtures, devices or equipment)");
            var kinds = new Dictionary<string, string>
            {
                ["power"] = "PowerCircuit", ["data"] = "Data", ["telephone"] = "Telephone", ["fire_alarm"] = "FireAlarm",
                ["security"] = "Security", ["nurse_call"] = "NurseCall", ["communication"] = "Communication",
                ["controls"] = "Controls",
            };
            var kind = Py.Str(Py.Truthy(ctx.Get("circuit_type")) ? ctx.Get("circuit_type") : "power").ToLowerInvariant();
            if (!kinds.ContainsKey(kind))
                throw new RvtssError("circuit_type must be one of: " + string.Join(", ", kinds.Keys.OrderBy(k => k, StringComparer.Ordinal)));
            var panel = ctx.Get("panel_id") != null ? Core.GetElement(doc, ctx.Get("panel_id"), "Panel") : null;

            Dict Run()
            {
                var circuitType = Py.EnumOrNull<DB.Electrical.ElectricalSystemType>(kinds[kind])
                                  ?? throw new MissingMemberException("ElectricalSystemType", kinds[kind]);
                var circuit = DB.Electrical.ElectricalSystem.Create(doc, Core.ToIdList(elements.Select(e => e.Id).ToList()), circuitType);
                if (circuit == null)
                    throw new RvtssError("Revit created no circuit", status: 409,
                        hint: "The elements need free electrical connectors of this circuit type.");
                if (panel != null)
                    circuit.SelectPanel((DB.FamilyInstance)panel);
                var o = CircuitInfo(doc, circuit);
                o["action"] = action;
                return o;
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP create circuit", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "select_panel")
        {
            var circuitEl = Core.GetElement(doc, ctx.Require("circuit_id"), "Circuit");
            var panel = Core.GetElement(doc, ctx.Require("panel_id"), "Panel");
            if (circuitEl is not DB.Electrical.ElectricalSystem circuit)
                throw new RvtssError($"Element {Compat.IdInt(circuitEl)} is not an electrical circuit", status: 409);

            Dict Run()
            {
                circuit.SelectPanel((DB.FamilyInstance)panel);
                var o = CircuitInfo(doc, circuit);
                o["action"] = action;
                return o;
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP select panel", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        if (action == "create_panel_schedule")
        {
            var panel = Core.GetElement(doc, ctx.Require("panel_id"), "Panel");

            Dict Run()
            {
                var view = DB.Electrical.PanelScheduleView.CreateInstanceView(doc, panel.Id);
                if (view == null)
                    throw new RvtssError("Revit created no panel schedule", status: 409,
                        hint: "The element must be electrical equipment with a distribution system, "
                              + "and a panel schedule template must exist.");
                return new Dict
                {
                    ["action"] = action, ["view_id"] = Compat.IdInt(view), ["name"] = Utils.NormalizeString(view.Name),
                    ["panel_id"] = Compat.IdInt(panel),
                };
            }

            var (result, fails) = Core.RunTransaction<Dict>(doc, "MEP panel schedule", Run, dry);
            return Core.CommitResult(result, fails, dry);
        }

        throw new RvtssError("action must be create, add_elements, remove_elements, rename, set_system_type, "
                             + "list_circuits, create_circuit, select_panel or create_panel_schedule");
    }

    public static void Register(RouteTable api)
    {
        api.Post("/mep/connect/", Connect, "connect");
        api.Post("/mep/create/", CreateParts, "create_parts");
        api.Post("/mep/insulation/", Insulation, "insulation");
        api.Post("/mep/systems/manage/", ManageSystems, "manage_systems");
    }
}
