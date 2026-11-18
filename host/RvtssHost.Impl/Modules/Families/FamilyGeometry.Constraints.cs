namespace RvtssHost.Modules;

public static partial class FamilyGeometry
{
    // ------------------------------------------------------------ dimensions
    private static DB.Dimension Dimension(DB.Document doc, DB.FamilyManager fm, IList<DB.Element> datums, object? label = null,
        bool equality = false, bool lockDimension = false, double? lineOffset = null)
    {
        if (datums.Count < 2)
            throw new RvtssError("A dimension needs at least 2 reference planes");
        var orients = datums.Select(FamilyUtils.DatumOrientation).Distinct().OrderBy(x => x, StringComparer.Ordinal).ToList();
        if (orients.Count != 1 || orients.Contains("skew"))
            throw new RvtssError($"All references of a dimension must be parallel axis planes (got {PyX.Repr(orients)})");
        var o = orients[0];
        var offs = datums.Select(d => FamilyUtils.DatumOffset(d)!.Value).ToList();
        double lo = offs.Min() - 0.5, hi = offs.Max() + 0.5;
        var k = lineOffset ?? -2.0;
        DB.View view;
        DB.Line line;
        if (o == "x")
        {
            view = FamilyUtils.PlanView(doc);
            line = DB.Line.CreateBound(new DB.XYZ(lo, k, 0), new DB.XYZ(hi, k, 0));
        }
        else if (o == "y")
        {
            view = FamilyUtils.PlanView(doc);
            line = DB.Line.CreateBound(new DB.XYZ(k, lo, 0), new DB.XYZ(k, hi, 0));
        }
        else
        {
            view = FamilyUtils.ElevationView(doc, "front");
            line = DB.Line.CreateBound(new DB.XYZ(k, 0, lo), new DB.XYZ(k, 0, hi));
        }
        var refs = new DB.ReferenceArray();
        foreach (var d in datums)
            refs.Append(FamilyUtils.DatumReference(d));
        var dim = doc.FamilyCreate.NewDimension(view, line, refs);
        if (dim == null)
            throw new RvtssError("Revit could not create the dimension", status: 409);
        if (equality)
        {
            if (datums.Count < 3)
                throw new RvtssError("EQ needs at least 3 references (e.g. Left, Center, Right)");
            dim.AreSegmentsEqual = true;
        }
        if (Py.Truthy(label))
        {
            var fp = ParamsUtil.FamilyParameter(fm, label);
            if (fp == null)
                throw new RvtssError($"Family parameter '{Py.Str(label)}' not found", status: 404,
                    hint: "Create it first (family_add_parameters, type length).");
            var (spec, kind) = Compat.DefinitionSpec(fp.Definition);
            if (kind != "length" && kind != "angle")
                throw new RvtssError($"Only length/angle parameters can label a dimension ('{Py.Str(label)}' is {Py.Str(spec)})");
            dim.FamilyLabel = fp;
        }
        if (lockDimension)
            dim.IsLocked = true;
        return dim;
    }

    private static readonly string[] DimensionKeys = { "references", "label", "equality", "lock" };

    public static Dict? DimensionRoute(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var items = ctx.List("dimensions");
        if (items.Count == 0)
        {
            var single = new Dict();
            foreach (var key in DimensionKeys)
            {
                if (ctx.Data.ContainsKey(key))
                    single[key] = ctx.Data[key];
            }
            items = new Lst { single };
        }
        if (items.Count == 0 || !Py.Truthy(FamilyUtils.AsItem(items[0]).Get("references")))
            throw new RvtssError("Pass references: ['Left', 'Right'] (reference plane names or 'Ref. Level'), "
                                 + "label (parameter), equality, lock");
        var dry = ctx.DryRun;

        Dict? One(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var references = FamilyUtils.Req(item, "references");
            // find_ref_plane(doc, None) is None: the dimension then fails on that reference
            var datums = PureText.Iter(references).Select(n => FamilyUtils.FindRefPlane(doc, n)!).ToList();
            if (Py.Truthy(item.Get("label")))
                FamilyUtils.EnsureCurrentType(fm);
            var dim = Dimension(doc, fm, datums, item.Get("label"), Py.Truthy(item.Get("equality", false)),
                Py.Truthy(item.Get("lock", false)),
                item.Get("line_offset") != null ? Units.ToInternal(item["line_offset"], ctx.Unit) : null);
            doc.Regenerate();
            var value = dim.Value;
            return new Dict
            {
                ["id"] = Compat.IdInt(dim), ["references"] = references, ["label"] = item.Get("label"),
                ["equality"] = Py.Truthy(item.Get("equality")),
                ["value"] = value != null ? Units.FromInternal(value.Value, ctx.Unit, 3) : null,
            };
        }

        var (res, fails) = Core.RunTransaction(doc, "Dimensions", () => Core.Batch(doc, items, One, true), dryRun: dry);
        return Core.CommitResult(new Dict { ["unit"] = ctx.Unit, ["results"] = res }, fails, dry);
    }

    // ------------------------------------------------------------- alignment
    private static Lst AlignForm(DB.Document doc, DB.Element form, IEnumerable<object?>? datumNames, bool lockAlignment = true)
    {
        var names = datumNames?.ToList();
        List<DB.Element> datums;
        if (names != null && names.Count > 0)
        {
            datums = names.Select(n => FamilyUtils.FindRefPlane(doc, n)!).ToList();
        }
        else
        {
            datums = FamilyUtils.ReferencePlanes(doc).Cast<DB.Element>().ToList();
            var level = FamilyUtils.RefLevel(doc);
            if (level != null)
                datums.Add(level);
        }
        var faces = FamilyUtils.SolidFaces(form);
        var made = new Lst();
        foreach (var d in datums)
        {
            var o = FamilyUtils.DatumOrientation(d);
            if (o == "skew")
                continue;
            var axis = o == "x" ? DB.XYZ.BasisX : o == "y" ? DB.XYZ.BasisY : DB.XYZ.BasisZ;
            var off = FamilyUtils.DatumOffset(d)!.Value;
            foreach (var f in faces)
            {
                var n = f.FaceNormal;
                if (Math.Abs(Math.Abs(n.DotProduct(axis)) - 1.0) > 1e-6)
                    continue;
                var pos = f.Origin.DotProduct(axis);
                if (Math.Abs(pos - off) > 1e-5 || f.Reference == null)
                    continue;
                DB.View view = o == "z" ? FamilyUtils.ElevationView(doc, "front") : FamilyUtils.PlanView(doc);
                try
                {
                    var al = doc.FamilyCreate.NewAlignment(view, FamilyUtils.DatumReference(d), f.Reference);
                    if (lockAlignment)
                    {
                        try { al.IsLocked = true; }
                        catch { /* some alignments cannot be locked */ }
                    }
                    made.Add(new Dict { ["plane"] = Utils.NormalizeString(d.Name), ["alignment_id"] = Compat.IdInt(al) });
                }
                catch (Exception e)
                {
                    made.Add(new Dict { ["plane"] = Utils.NormalizeString(d.Name), ["error"] = FamilyUtils.ErrText(e) });
                }
                break;
            }
        }
        return made;
    }

    public static Dict? AlignRoute(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireFamily(doc);
        var formIds = ctx.List("form_ids");
        if (formIds.Count == 0)
            formIds = FamilyUtils.Forms(doc).Where(x => x.f.IsSolid).Select(x => (object?)Compat.IdInt(x.f)).ToList();
        var planes = ctx.List("planes");
        var names = planes.Count > 0 ? planes : null;
        var dry = ctx.DryRun;

        var (res, fails) = Core.RunTransaction(doc, "Align forms", () =>
        {
            var o = new Lst();
            foreach (var fid in formIds)
                o.Add(new Dict
                {
                    ["form_id"] = fid,
                    ["alignments"] = AlignForm(doc, Core.GetElement(doc, fid), names, ctx.Bool("lock", true)),
                });
            doc.Regenerate();
            return new Dict { ["results"] = o };
        }, dryRun: dry);
        return Core.CommitResult(res, fails, dry);
    }

    // ------------------------------------------------------------------- box
    private static DB.FamilyParameter EnsureLengthParam(DB.FamilyManager fm, object? name, double? value, bool instance)
    {
        var fp = ParamsUtil.FamilyParameter(fm, name);
        if (fp == null)
            fp = Compat.AddFamilyParameter(fm, Py.Str(name), "length", "dimensions", instance);
        else if (Compat.DefinitionSpec(fp.Definition).kind != "length")
            throw new RvtssError($"Existing parameter '{Py.Str(name)}' is not a length", status: 409);
        FamilyUtils.EnsureCurrentType(fm);
        if (value != null && string.IsNullOrEmpty(fp.Formula))
            fm.Set(fp, value.Value);
        return fp;
    }

    /// <summary>Get or create the two planes at -half/+half.</summary>
    private static List<DB.ReferencePlane> PlanePair(DB.Document doc, (string first, string second) names, string orientation,
        double half, Dictionary<string, DB.ReferencePlane> existing)
    {
        var o = new List<DB.ReferencePlane>();
        foreach (var (name, sign) in new[] { (names.first, -1), (names.second, 1) })
        {
            existing.TryGetValue(name.ToLowerInvariant(), out var rp);
            if (rp != null && FamilyUtils.PlaneOrientation(rp) != orientation)
                throw new RvtssError($"Plane '{name}' exists with orientation {FamilyUtils.PlaneOrientation(rp)}", status: 409);
            rp ??= NewRefPlane(doc, orientation, sign * half, name);
            o.Add(rp);
        }
        return o;
    }

    private static DB.ReferencePlane CenterPlane(DB.Document doc, string orientation, Dictionary<string, DB.ReferencePlane> existing)
    {
        var key = orientation == "x" ? "center (left/right)" : "center (front/back)";
        if (existing.TryGetValue(key, out var named))
            return named;
        foreach (var rp in existing.Values)
        {
            // abs(None) is a TypeError in Python: a skew plane never has the wanted orientation
            if (FamilyUtils.PlaneOrientation(rp) == orientation && Math.Abs(FamilyUtils.PlaneOffset(rp)!.Value) < 1e-6)
                return rp;
        }
        return NewRefPlane(doc, orientation, 0.0, orientation == "x" ? "Center (Left/Right)" : "Center (Front/Back)");
    }

    public static Dict? BuildBox(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var unit = ctx.Unit;
        var w = Units.ToInternal(ctx.F("width", 900), unit);
        var dpt = Units.ToInternal(ctx.F("depth", 600), unit);
        var h = Units.ToInternal(ctx.F("height", 750), unit);
        if (Math.Min(w, Math.Min(dpt, h)) <= 0)
            throw new RvtssError("width, depth and height must be positive");
        object? pw = ctx.Get("width_parameter", "Width"), pd = ctx.Get("depth_parameter", "Depth"),
            ph = ctx.Get("height_parameter", "Height");
        var material = ctx.Get("material_parameter", "Material");
        var instance = ctx.Bool("instance_parameters", false);
        var dry = ctx.DryRun;

        var (res, fails) = Core.RunTransaction(doc, "Build parametric box", () =>
        {
            var existing = PlanesByName(doc);
            EnsureLengthParam(fm, pw, w, instance);
            EnsureLengthParam(fm, pd, dpt, instance);
            var fph = EnsureLengthParam(fm, ph, h, instance);
            var lr = PlanePair(doc, ("Left", "Right"), "x", w / 2.0, existing);
            var fb = PlanePair(doc, ("Front", "Back"), "y", dpt / 2.0, existing);
            DB.ReferencePlane left = lr[0], right = lr[1], front = fb[0], back = fb[1];
            var cx = CenterPlane(doc, "x", existing);
            var cy = CenterPlane(doc, "y", existing);
            doc.Regenerate();
            var xs = new[] { FamilyUtils.PlaneOffset(left)!.Value, FamilyUtils.PlaneOffset(right)!.Value };
            var ys = new[] { FamilyUtils.PlaneOffset(front)!.Value, FamilyUtils.PlaneOffset(back)!.Value };
            double x0 = xs.Min(), x1 = xs.Max(), y0 = ys.Min(), y1 = ys.Max();
            var level = FamilyUtils.RefLevel(doc)!;
            var sp = DB.SketchPlane.Create(doc, level.Id);
            var z = level.Elevation;
            var pts = new[] { new DB.XYZ(x0, y0, z), new DB.XYZ(x1, y0, z), new DB.XYZ(x1, y1, z), new DB.XYZ(x0, y1, z) };
            var loop = new List<DB.Curve>();
            for (var i = 0; i < 4; i++)
                loop.Add(DB.Line.CreateBound(pts[i], pts[(i + 1) % 4]));
            var ext = doc.FamilyCreate.NewExtrusion(true, CurveArrArr(new[] { loop }), sp, h);
            doc.Regenerate();
            var aligned = AlignForm(doc, ext, new object?[] { left.Name, right.Name, front.Name, back.Name }, true);
            var dims = new List<DB.Dimension>
            {
                Dimension(doc, fm, new DB.Element[] { left, right }, label: pw),
                Dimension(doc, fm, new DB.Element[] { front, back }, label: pd, lineOffset: -2.0),
            };
            if (ctx.Bool("center_equality", true))
            {
                dims.Add(Dimension(doc, fm, new DB.Element[] { left, cx, right }, equality: true, lineOffset: -2.5));
                dims.Add(Dimension(doc, fm, new DB.Element[] { front, cy, back }, equality: true, lineOffset: -2.5));
            }
            fm.AssociateElementParameterToFamilyParameter(ext.get_Parameter(DB.BuiltInParameter.EXTRUSION_END_PARAM), fph);
            if (Py.Truthy(material))
            {
                var mat = ParamsUtil.FamilyParameter(fm, material)
                          ?? Compat.AddFamilyParameter(fm, Py.Str(material), "material", "materials", instance);
                fm.AssociateElementParameterToFamilyParameter(ext.get_Parameter(DB.BuiltInParameter.MATERIAL_ID_PARAM), mat);
            }
            var sub = ctx.Get("subcategory");
            if (Py.Truthy(sub))
                ApplyFormOptions(ctx, doc, fm, ext, new Dict { ["subcategory"] = sub });
            doc.Regenerate();
            var errors = aligned.Where(a => ((Dict)a!).ContainsKey("error")).ToList();
            if (aligned.Count(a => ((Dict)a!).ContainsKey("alignment_id")) < 4)
                throw new RvtssError($"Could not lock all four sides of the extrusion: {PyX.Repr(aligned)}", status: 409,
                    hint: "Nothing was kept. Check that Left/Right/Front/Back planes are not pinned or "
                          + "already constrained differently.");
            var parameters = new Lst { pw, pd, ph };
            if (Py.Truthy(material))
                parameters.Add(material);
            return new Dict
            {
                ["extrusion_id"] = Compat.IdInt(ext), ["parameters"] = parameters,
                ["reference_planes"] = new[] { left, right, front, back, cx, cy }.Select(p => Utils.NormalizeString(p.Name)).ToList(),
                ["dimension_ids"] = dims.Select(d => Compat.IdInt(d)).ToList(), ["alignments"] = aligned,
                ["alignment_errors"] = errors,
            };
        }, dryRun: dry);
        var o = Core.CommitResult(res, fails, dry, new Dict { ["unit"] = unit });
        if (!dry && ctx.Bool("flex_check", true))
        {
            Dict Values(double factor) => new()
            {
                [Py.Str(pw)] = new Dict { ["value"] = ctx.F("width", 900) * factor, ["unit"] = unit },
                [Py.Str(pd)] = new Dict { ["value"] = ctx.F("depth", 600) * factor, ["unit"] = unit },
                [Py.Str(ph)] = new Dict { ["value"] = ctx.F("height", 750) * factor, ["unit"] = unit },
            };

            var factorCases = new Lst
            {
                new Dict { ["name"] = "x1.5", ["values"] = Values(1.5) },
                new Dict { ["name"] = "x0.5", ["values"] = Values(0.5) },
            };
            var expect = new Dict { ["x"] = pw, ["y"] = pd, ["z"] = ph };
            o["flex_check"] = Flex(doc, fm, factorCases, unit, expect, ctx.F("tolerance", 0.5));
        }
        return o;
    }

    // ------------------------------------------------------------------ flex
    private static Lst? BboxSize(DB.Document doc, string unit)
    {
        var bb = FamilyUtils.CombinedBbox(doc);
        if (bb == null)
            return null;
        var (mins, maxs) = bb.Value;
        var size = new Lst();
        for (var i = 0; i < 3; i++)
            size.Add(Units.FromInternal(maxs[i] - mins[i], unit, 3));
        return size;
    }

    /// <summary>list == list for two bbox sizes (None == None is true).</summary>
    private static bool SameSize(Lst? a, Lst? b)
    {
        if (a == null || b == null)
            return a == null && b == null;
        return a.Count == b.Count && a.Zip(b, (x, y) => (double)x! == (double)y!).All(same => same);
    }

    /// <summary>core._start_tx: a started transaction whose failures are collected (Core.StartTx is private).</summary>
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

    /// <summary>
    /// Apply each case in its own rolled-back TransactionGroup (inside an outer group that is
    /// also rolled back) and measure the geometry while the case is applied.
    /// </summary>
    private static Dict Flex(DB.Document doc, DB.FamilyManager fm, Lst cases, string unit, object? expect = null, double tol = 0.5)
    {
        var results = new List<Dict>();
        Lst? baseSize;
        var group = new DB.TransactionGroup(doc, "RVTSS: flex test");
        group.Start();
        try
        {
            baseSize = BboxSize(doc, unit);
            foreach (var raw in cases)
            {
                var c = FamilyUtils.AsItem(raw);
                var entry = new Dict
                {
                    ["case"] = Py.Truthy(c.Get("name")) ? c.Get("name") : Py.Truthy(c.Get("type")) ? c.Get("type") : "case",
                    ["ok"] = true,
                };
                // each case is isolated: its own group is rolled back after measuring, so cases
                // never accumulate and every case starts from the original family state
                var caseGroup = new DB.TransactionGroup(doc, "RVTSS: flex case");
                caseGroup.Start();
                try
                {
                    var (t, collector) = StartTx(doc, "RVTSS: flex case");
                    try
                    {
                        if (Py.Truthy(c.Get("type")))
                            fm.CurrentType = FamilyUtils.FindFamilyType(fm, c["type"]);
                        var values = Py.Truthy(c.Get("values")) ? FamilyUtils.AsItem(c.Get("values")) : new Dict();
                        foreach (var (pname, val) in values)
                        {
                            var fp = ParamsUtil.FamilyParameter(fm, pname);
                            if (fp == null)
                                throw new RvtssError($"Parameter '{pname}' not found");
                            var (v, u) = val is Dict vd ? (vd.Get("value"), vd.Get("unit", unit)) : (val, unit);
                            ParamsUtil.SetFamilyValue(doc, fm, fp, v, FamilyUtils.UnitOf(u));
                        }
                        doc.Regenerate();
                        var status = t.Commit();
                        if (status != DB.TransactionStatus.Committed)
                        {
                            entry["ok"] = false;
                            entry["errors"] = collector.Messages.Cast<Dict>().Where(m => (string?)m["severity"] != "Warning")
                                .Select(m => m["message"]).ToList();
                        }
                    }
                    catch (Exception e)
                    {
                        if (t.HasStarted() && !t.HasEnded())
                            t.RollBack();
                        entry["ok"] = false;
                        entry["errors"] = new Lst { e is RvtssError ? e.Message : FamilyUtils.ErrText(e) };
                    }
                    finally
                    {
                        t.Dispose();
                    }
                    if (collector.Messages.Count > 0)
                        entry["revit_messages"] = collector.Messages.Take(10).ToList();
                    var size = BboxSize(doc, unit);
                    entry["bbox_size"] = size;
                    entry["changed_from_base"] = !SameSize(size, baseSize);
                    if (Py.Truthy(expect) && Py.Truthy(entry["ok"]) && size != null && size.Count > 0)
                    {
                        var checks = new Dict();
                        foreach (var (axis, pname) in FamilyUtils.AsItem(expect))
                        {
                            var fp = ParamsUtil.FamilyParameter(fm, pname);
                            if (fp == null)
                                continue;
                            var want = ParamsUtil.FamilyTypeValue(fm, fm.CurrentType, fp, unit);
                            var index = "xyz".IndexOf(axis, StringComparison.Ordinal);
                            if (index < 0 || axis.Length == 0)
                                throw new FormatException("substring not found");
                            var got = (double)size[index]!;
                            checks[Py.Str(pname)] = new Dict
                            {
                                ["expected"] = want, ["actual"] = got,
                                ["pass"] = want != null && Math.Abs(got - Py.ToFloat(want)) <= tol,
                            };
                        }
                        entry["checks"] = checks;
                        if (checks.Values.Any(x => !Py.Truthy(((Dict)x!)["pass"])))
                            entry["ok"] = false;
                    }
                }
                finally
                {
                    if (caseGroup.HasStarted() && !caseGroup.HasEnded())
                        caseGroup.RollBack();
                    caseGroup.Dispose();
                }
                results.Add(entry);
            }
        }
        finally
        {
            if (group.HasStarted() && !group.HasEnded())
                group.RollBack();
            group.Dispose();
        }
        return new Dict
        {
            ["base_bbox_size"] = baseSize, ["cases"] = results, ["unit"] = unit,
            ["passed"] = results.All(r => Py.Truthy(r["ok"])),
            ["note"] = "All flex changes were rolled back; the family is unchanged.",
        };
    }

    public static Dict? FlexRoute(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        Core.CheckModifiable(doc);
        var unit = ctx.Unit;
        var cases = ctx.List("cases");
        var expect = ctx.Get("expect");
        var auto = new List<string>();
        if (cases.Count == 0)
        {
            // every type, then +20% on each driving length parameter
            foreach (DB.FamilyType t in fm.Types)
                cases.Add(new Dict { ["type"] = Utils.NormalizeString(t.Name) });
            var labels = FamilyUtils.LabeledDimensions(doc);
            foreach (DB.FamilyParameter fp in fm.Parameters)
            {
                var n = Utils.NormalizeString(fp.Definition.Name);
                if (!string.IsNullOrEmpty(fp.Formula) || fp.IsReporting || Compat.DefinitionSpec(fp.Definition).kind != "length")
                    continue;
                if (!FamilyUtils.IsRelevant(fp))
                    continue;
                var cur = fm.CurrentType != null ? ParamsUtil.FamilyTypeValue(fm, fm.CurrentType, fp, unit) : null;
                if (!Py.Truthy(cur))
                    continue;
                auto.Add(n);
                cases.Add(new Dict
                {
                    ["name"] = n + " +20%",
                    ["values"] = new Dict { [n] = new Dict { ["value"] = Py.ToFloat(cur) * 1.2, ["unit"] = unit } },
                    ["parameter"] = n, ["labelled"] = Py.Truthy(labels.Get(n)),
                });
            }
        }
        var result = Flex(doc, fm, cases, unit, expect, ctx.F("tolerance", 0.5));
        if (auto.Count > 0)
        {
            var done = (List<Dict>)result["cases"]!;
            var inert = new List<string>();
            for (var i = 0; i < done.Count && i < cases.Count; i++)
            {
                var c = done[i];
                var src = FamilyUtils.AsItem(cases[i]);
                if (Py.Truthy(src.Get("parameter")) && Py.Truthy(c["ok"]) && !Py.Truthy(c["changed_from_base"]))
                    inert.Add(Py.Str(c["case"]).Replace(" +20%", ""));
            }
            result["parameters_without_geometric_effect"] = inert;
            if (inert.Count > 0)
                result["hint"] = "These length parameters do not change the overall bounding box. That is expected "
                                 + "for internal offsets, otherwise label a dimension or associate them.";
        }
        return result;
    }
}
