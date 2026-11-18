namespace RvtssHost.Modules;

/// <summary>
/// Stairs by component (RVTSS v2.3). Port of revit_mcp/stairs.py.
///
/// Routes:
///     POST /stairs/create/   straight runs between two levels, automatic landings between runs,
///                            optional railings; one undo step, dry_run rolls everything back
///
/// Revit needs a StairsEditScope for stairs, which cannot run inside create_elements' transaction,
/// so stairs have their own route. Run lines are horizontal; their height is set by the run's
/// riser count, Revit distributes risers between base and top level.
/// </summary>
public static class Stairs
{
    /// <summary>The Python AttributeError of "base_level missing": base is None, so base.Elevation fails. The type name
    /// is part of the error text a client sees ("AttributeError: ...").</summary>
    private sealed class AttributeError(string message) : Exception(message);

    /// <summary>core._start_tx (private in Core.cs): a transaction whose failures are collected.</summary>
    private static (DB.Transaction t, Core.FailureCollector collector) StartTx(DB.Document doc, string name)
    {
        var t = new DB.Transaction(doc, name);
        var collector = new Core.FailureCollector();
        var opts = t.GetFailureHandlingOptions();
        opts.SetFailuresPreprocessor(collector);
        opts.SetClearAfterRollback(true);
        t.SetFailureHandlingOptions(opts);
        t.Start();
        return (t, collector);
    }

    public static Dict? CreateStairs(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        Core.CheckModifiable(doc);
        var dry = ctx.DryRun;
        if (!dry)
            Core.RequireWritable("create_stairs");
        if (doc.IsModifiable)
            throw new RvtssError("A transaction is already open; stairs need their own edit scope", status: 409);
        var baseLevel = Core.FindLevel(doc, Py.Truthy(ctx.Get("base_level")) ? ctx.Get("base_level") : ctx.Get("level"));
        var top = Core.FindLevel(doc, ctx.Require("top_level"))!;
        if (baseLevel == null)
            throw new AttributeError("'NoneType' object has no attribute 'Elevation'");
        if (top.Elevation <= baseLevel.Elevation)
            throw new RvtssError("top_level must be above base_level");
        var runs = ctx.List("runs");
        if (runs.Count == 0 && Py.Truthy(ctx.Get("start")) && Py.Truthy(ctx.Get("end")))
            runs = new Lst { new Dict { ["start"] = ctx.Get("start"), ["end"] = ctx.Get("end") } };
        if (runs.Count == 0)
            throw new RvtssError("Give 'runs': [{start:[x,y], end:[x,y], width?}, ...] or start + end");
        var width = ctx.Get("width");
        var justText = ctx.Get("justification", "center") as string;
        var just = justText == "left" ? DB.Architecture.StairsRunJustification.Left
            : justText == "right" ? DB.Architecture.StairsRunJustification.Right
            : DB.Architecture.StairsRunJustification.Center;
        DB.ElementType? stype = null;
        if (Py.Truthy(ctx.Get("type")))
            stype = Core.FindType(doc, typeName: ctx.Get("type"), ofClass: typeof(DB.Architecture.StairsType));

        var group = new DB.TransactionGroup(doc, "RVTSS: Create stairs");
        group.Start();
        var result = new Dict();
        DB.StairsEditScope? scope = null;
        DB.Transaction? t = null;
        try
        {
            scope = new DB.StairsEditScope(doc, "RVTSS: Create stairs");
            var stairsId = scope.Start(baseLevel.Id, top.Id);
            Core.FailureCollector collector;
            (t, collector) = StartTx(doc, "RVTSS: stairs runs");
            var made = new List<DB.Architecture.StairsRun>();
            var landings = new List<DB.ElementId>();
            var z = 0.0; // run lines are relative to the stairs base (the first run starts on the base level)
            for (var i = 0; i < runs.Count; i++)
            {
                var r = runs[i] as Dict ?? throw new AttributeError($"'{Py.TypeName(runs[i])}' object has no attribute 'get'");
                var a = Units.PointFrom(r.Get("start"), ctx.Unit);
                var b = Units.PointFrom(r.Get("end"), ctx.Unit);
                var line = DB.Line.CreateBound(new DB.XYZ(a.x, a.y, z), new DB.XYZ(b.x, b.y, z));
                var run = DB.Architecture.StairsRun.CreateStraightRun(doc, stairsId, line, just);
                var w = r.TryGetValue("width", out var rw) ? rw : width;
                if (w != null)
                    run.ActualRunWidth = Units.ToInternal(w, ctx.Unit);
                made.Add(run);
                z = run.TopElevation;
                if (i > 0 && ctx.Bool("landings", true))
                {
                    try
                    {
                        // returns the new landing ids (a list), not a landing
                        landings.AddRange(DB.Architecture.StairsLanding.CreateAutomaticLanding(doc, made[i - 1].Id, run.Id));
                    }
                    catch (Exception ex)
                    {
                        if (result.Get("landing_errors") is not Lst errors)
                            result["landing_errors"] = errors = new Lst();
                        errors.Add(Utils.NormalizeString(ex.Message));
                    }
                }
            }
            if (t.Commit() != DB.TransactionStatus.Committed)
                throw new RvtssError("Revit rejected the stairs runs", status: 409).With("failures", collector.Messages);
            scope.Commit(new Core.FailureCollector());
            var stairs = doc.GetElement(stairsId);
            if (stype != null)
            {
                var (t2, _) = StartTx(doc, "RVTSS: stairs type");
                stairs.ChangeTypeId(stype.Id);
                t2.Commit();
            }
            // many stairs types add their railings automatically; only add one when there is none
            var st = doc.GetElement(stairsId);
            var railingIds = new List<long>();
            if (st is DB.Architecture.Stairs stSt)
                railingIds = stSt.GetAssociatedRailings().Select(x => x.Value).ToList();
            if (ctx.Bool("railings", false) && railingIds.Count == 0)
            {
                var (t3, _) = StartTx(doc, "RVTSS: stairs railings");
                var rt = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Architecture.RailingType)).FirstElement();
                if (rt != null)
                    railingIds = DB.Architecture.Railing.Create(doc, stairsId, rt.Id, DB.Architecture.RailingPlacementPosition.Treads)
                        .Select(x => x.Value).ToList();
                t3.Commit();
            }
            var stairsObj = st as DB.Architecture.Stairs;
            result["stairs_id"] = Compat.IdInt(stairsId);
            result["run_ids"] = made.Select(r => (object?)Compat.IdInt(r.Id)).ToList();
            result["landing_ids"] = landings.Select(l => (object?)Compat.IdInt(l)).ToList();
            result["railing_ids"] = railingIds.Select(x => (object?)x).ToList();
            result["type"] = Utils.NormalizeString(Utils.GetElementName(doc.GetElement(st.GetTypeId())));
            result["risers"] = stairsObj != null ? (long?)stairsObj.ActualRisersNumber : null;
            result["riser_height"] = stairsObj != null ? Units.FromInternal(stairsObj.ActualRiserHeight, ctx.Unit, 1) : (double?)null;
            result["warnings"] = collector.Messages;
            if (dry)
                group.RollBack();
            else
                group.Assimilate();
        }
        catch
        {
            // the Python left an open transaction / edit scope to the rollback of the group; close them here so
            // the group can roll back (best effort, the original error is what the caller gets)
            try { if (t != null && t.HasStarted() && !t.HasEnded()) t.RollBack(); } catch { }
            try { if (scope != null && scope.IsActive) scope.Cancel(); } catch { }
            throw;
        }
        finally
        {
            if (group.HasStarted() && !group.HasEnded())
                group.RollBack();
        }
        return Core.CommitResult(result, new Lst(), dry, new Dict { ["unit"] = ctx.Unit });
    }

    public static void Register(RouteTable api)
    {
        api.Post("/stairs/create/", CreateStairs, "create_stairs");
    }
}
