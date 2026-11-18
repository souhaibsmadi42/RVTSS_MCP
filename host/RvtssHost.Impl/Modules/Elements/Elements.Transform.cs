namespace RvtssHost.Modules;

/// <summary>elements.py: transform_elements (move / copy / rotate / mirror / array / pin / join) and delete_elements.</summary>
public static partial class Elements
{
    // -------------------------------------------------------------------- transform
    private static DB.XYZ Vector(Ctx ctx, string key)
    {
        var v = ctx.Get(key);
        if (v == null)
            throw new RvtssError($"'{key}' is required ([x, y, z] in {ctx.Unit})");
        return Xyz(Units.PointFrom(v, ctx.Unit));
    }

    private static double Radians(double degrees) => degrees * Math.PI / 180.0;

    public static Dict? TransformElements(Ctx ctx)
    {
        var doc = ctx.Doc;
        var op = ctx.Require("operation") as string;
        var opText = Py.Str(ctx.Data.Get("operation"));
        var elements = Core.GetElements(doc, ctx.List("element_ids"));
        if (elements.Count == 0)
            throw new RvtssError("element_ids is required");
        if (op == "pin" || op == "unpin" || op == "join" || op == "unjoin" || op == "switch_join")
            return ModifyElements(ctx, doc, op, elements);
        var pinned = elements.Where(e => e.Pinned).Select(e => Compat.IdInt(e)).ToList();
        if (pinned.Count > 0 && !ctx.Bool("unpin", false))
            throw new RvtssError($"Pinned elements cannot be transformed: {IntListRepr(pinned.Take(20))}", status: 409,
                hint: "Pass unpin=true to unpin them first (they stay unpinned).");
        var ids = Core.ToIdList(elements.Select(e => e.Id).ToList());
        var preview = Core.ConfirmGate(ctx, elements.Count, "transform_elements");

        DB.XYZ Center()
        {
            var c = ctx.Get("center");
            if (c != null)
                return Xyz(Units.PointFrom(c, ctx.Unit));
            var pts = elements.Select(Core.ElementPoint).Where(p => p != null).Select(p => p!).ToList();
            if (pts.Count == 0)
                throw new RvtssError("Cannot determine a rotation centre; pass 'center'");
            return new DB.XYZ(pts.Sum(p => p.X) / pts.Count, pts.Sum(p => p.Y) / pts.Count, pts.Sum(p => p.Z) / pts.Count);
        }

        Dict Run()
        {
            foreach (var e in elements)
            {
                if (e.Pinned)
                    e.Pinned = false;
            }
            var newIds = new List<DB.ElementId>();
            if (op == "move")
            {
                DB.ElementTransformUtils.MoveElements(doc, ids, Vector(ctx, "vector"));
            }
            else if (op == "copy")
            {
                newIds = DB.ElementTransformUtils.CopyElements(doc, ids, Vector(ctx, "vector")).ToList();
            }
            else if (op == "rotate")
            {
                var angle = Radians(ctx.F("angle_deg", 0.0));
                if (ctx.Bool("each_about_own_center", false))
                {
                    foreach (var e in elements)
                    {
                        var p = Core.ElementPoint(e);
                        if (p == null)
                            throw new RvtssError($"Element {Compat.IdInt(e)} has no location or bounding box to rotate about",
                                hint: "Pass 'center' and each_about_own_center=false.");
                        var axis = DB.Line.CreateBound(p, p + DB.XYZ.BasisZ);
                        DB.ElementTransformUtils.RotateElement(doc, e.Id, axis, angle);
                    }
                }
                else
                {
                    var c = Center();
                    DB.ElementTransformUtils.RotateElements(doc, ids, DB.Line.CreateBound(c, c + DB.XYZ.BasisZ), angle);
                }
            }
            else if (op == "mirror")
            {
                var normalName = ctx.Get("plane_normal", "x") as string;
                var normal = normalName == "x" ? DB.XYZ.BasisX : normalName == "y" ? DB.XYZ.BasisY : null;
                if (normal == null)
                    throw new RvtssError("plane_normal must be 'x' or 'y' (vertical mirror plane)");
                var plane = DB.Plane.CreateByNormalAndOrigin(normal, Center());
                var res = DB.ElementTransformUtils.MirrorElements(doc, ids, plane, ctx.Bool("mirror_copy", false));
                if (res != null)
                    newIds = res.ToList();
            }
            else if (op == "array")
            {
                // non-associative array: count-1 copies, linear (vector) or radial (angle_deg in total, center)
                var count = ctx.Int("count", minimum: 2, maximum: 200);
                if (count == null)
                    throw new RvtssError("array needs 'count' (2-200, including the originals)");
                if (ctx.Get("vector") != null)
                {
                    var step = Vector(ctx, "vector");
                    for (var i = 1; i < count.Value; i++)
                        newIds.AddRange(DB.ElementTransformUtils.CopyElements(doc, ids, step * (double)i));
                }
                else if (ctx.Get("angle_deg") != null)
                {
                    var c = Center();
                    var axis = DB.Line.CreateBound(c, c + DB.XYZ.BasisZ);
                    var angleDeg = ctx.Float("angle_deg")!.Value;
                    var total = Radians(angleDeg);
                    var full = Math.Abs(Math.Abs(angleDeg) - 360.0) < 1e-6;
                    var step = total / (full ? count.Value : count.Value - 1);
                    for (var i = 1; i < count.Value; i++)
                    {
                        var copies = DB.ElementTransformUtils.CopyElements(doc, ids, DB.XYZ.Zero);
                        DB.ElementTransformUtils.RotateElements(doc, copies, axis, step * i);
                        newIds.AddRange(copies);
                    }
                }
                else
                {
                    throw new RvtssError("array needs 'vector' (linear) or 'angle_deg' (radial, about 'center')");
                }
            }
            else
            {
                throw new RvtssError("operation must be move, copy, rotate, mirror, array, pin, unpin, join, unjoin "
                                     + "or switch_join");
            }
            doc.Regenerate();
            var moved = elements.Take(50).Select(e => (object?)new Dict
            {
                ["id"] = Compat.IdInt(e), ["location"] = Core.ElementLocation(e, ctx.Unit),
            }).ToList();
            return new Dict
            {
                ["operation"] = op, ["count"] = (long)elements.Count,
                ["new_element_ids"] = newIds.Select(i => (object?)Compat.IdInt(i)).ToList(),
                ["elements"] = moved,
            };
        }

        var dry = preview || ctx.DryRun;
        var (result, failures) = Core.RunTransaction(doc, "Transform " + opText, () => Run(), dryRun: dry);
        return Core.PreviewStatus(Core.CommitResult(result, failures, dry, new Dict { ["unit"] = ctx.Unit }), preview);
    }

    /// <summary>pin / unpin every element; join / unjoin / switch_join the first element with each of the others.</summary>
    private static Dict? ModifyElements(Ctx ctx, DB.Document doc, string op, List<DB.Element> elements)
    {
        if ((op == "join" || op == "unjoin" || op == "switch_join") && elements.Count < 2)
            throw new RvtssError($"{op} needs at least 2 element_ids (the first is joined with each of the others)");

        Dict Run()
        {
            var o = new Lst();
            if (op == "pin" || op == "unpin")
            {
                foreach (var e in elements)
                {
                    try
                    {
                        e.Pinned = op == "pin";
                        o.Add(new Dict { ["id"] = Compat.IdInt(e), ["ok"] = true, ["pinned"] = e.Pinned });
                    }
                    catch (Exception ex)
                    {
                        o.Add(new Dict { ["id"] = Compat.IdInt(e), ["ok"] = false, ["error"] = Utils.NormalizeString(ex.Message) });
                    }
                }
                return new Dict { ["operation"] = op, ["results"] = o };
            }
            var a = elements[0];
            foreach (var b in elements.Skip(1))
            {
                var r = new Dict { ["pair"] = new Lst { Compat.IdInt(a), Compat.IdInt(b) } };
                try
                {
                    var joined = DB.JoinGeometryUtils.AreElementsJoined(doc, a, b);
                    if (op == "join")
                    {
                        if (!joined)
                            DB.JoinGeometryUtils.JoinGeometry(doc, a, b);
                        r["joined"] = true;
                    }
                    else if (op == "unjoin")
                    {
                        if (joined)
                            DB.JoinGeometryUtils.UnjoinGeometry(doc, a, b);
                        r["joined"] = false;
                    }
                    else
                    {
                        if (!joined)
                            throw new RvtssError("elements are not joined");
                        DB.JoinGeometryUtils.SwitchJoinOrder(doc, a, b);
                        r["cutting_first"] = DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, a, b);
                    }
                    r["ok"] = true;
                }
                catch (Exception ex)
                {
                    r["ok"] = false;
                    r["error"] = Utils.NormalizeString(ex.Message);
                }
                o.Add(r);
            }
            if (ctx.Bool("atomic", false) && o.Any(r => !Py.Truthy(((Dict)r!)["ok"])))
                throw new RvtssError($"{op} failed for {o.Count(r => !Py.Truthy(((Dict)r!)["ok"]))} pair(s)",
                    hint: "Nothing was changed (atomic=true).").With("results", o);
            return new Dict { ["operation"] = op, ["results"] = o };
        }

        var (result, failures) = Core.RunTransaction(doc, Title(op.Replace("_", " ")), () => Run(), dryRun: ctx.DryRun);
        return Core.CommitResult(result, failures, ctx.DryRun);
    }

    public static Dict? DeleteElements(Ctx ctx)
    {
        var doc = ctx.Doc;
        var elements = Core.GetElements(doc, ctx.List("element_ids"));
        if (elements.Count == 0)
            throw new RvtssError("element_ids is required");
        if (elements.Count > 5000)
            throw new RvtssError("Refusing to delete more than 5000 elements in one call", status: 409);
        var pinned = elements.Where(e => e.Pinned).Select(e => Compat.IdInt(e)).ToList();
        if (pinned.Count > 0 && !ctx.Bool("include_pinned", false))
            throw new RvtssError($"Pinned elements in the request: {IntListRepr(pinned.Take(20))}", status: 409,
                hint: "Pinned elements are protected. Pass include_pinned=true to delete them anyway.");
        var commit = ctx.Confirmed && !ctx.DryRun;
        var requested = new HashSet<long>(elements.Select(e => Compat.IdInt(e)));

        List<long> Run()
        {
            var removed = doc.Delete(Core.ToIdList(elements.Select(e => e.Id).ToList()));
            return removed.Select(i => Compat.IdInt(i)).ToList();
        }

        // Collect the full dependent set while the elements still exist
        var summary = new Dict();
        foreach (var e in elements)
        {
            var b = Core.ElementBrief(doc, e);
            var key = Py.Truthy(b.Get("category")) ? Py.Str(b.Get("category")) : "(none)";
            summary[key] = (long)summary.Get(key, 0L)! + 1;
        }
        var (deleted, failures) = Core.RunTransaction(doc, "Delete elements", () => Run(), dryRun: !commit);
        var dependents = deleted.Where(i => !requested.Contains(i)).ToList();
        var o = new Dict
        {
            ["requested"] = (long)requested.Count,
            ["deleted_total"] = (long)deleted.Count,
            ["dependent_elements_deleted"] = (long)dependents.Count,
            ["dependent_ids_sample"] = dependents.Take(50).Select(i => (object?)i).ToList(),
            ["requested_by_category"] = summary,
        };
        if (!commit)
        {
            o["status"] = "preview";
            o["committed"] = false;
            o["requires_confirmation"] = true;
            o["message"] = $"Preview: Revit would delete {deleted.Count} element(s) including {dependents.Count} dependent(s). "
                           + "Nothing was deleted. Re-run with confirm=true to delete.";
        }
        else
        {
            o["status"] = "success";
            o["committed"] = true;
            o["message"] = $"Deleted {deleted.Count} element(s). Revit's Undo (Ctrl+Z) can restore them while the "
                           + "session lasts.";
        }
        if (failures.Count > 0)
            o["revit_warnings"] = failures;
        return o;
    }
}
