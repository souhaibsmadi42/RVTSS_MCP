namespace RvtssHost.Modules;

/// <summary>
/// Parametric family geometry (RVTSS): port of revit_mcp/family_geometry.py.
///
/// Routes:
///     POST /family/reference_planes/  create (batch) or list reference planes
///     POST /family/forms/             extrusion / blend / revolution / sweep, solid or void
///     POST /family/dimension/         dimension between reference planes / Ref. Level, label, EQ, lock
///     POST /family/align/             lock form faces to coplanar reference planes
///     POST /family/build_box/         complete parametric box (planes, labelled dims, EQ, locked
///                                     extrusion, height + material parameters) + flex check
///     POST /family/flex/              flex types / parameter values and verify geometry responds
///
/// Coordinates are in `unit` (default mm). Axis convention in family templates:
/// X = left/right, Y = front/back, Z = up; the Ref. Level is at Z = 0.
///
/// Files: FamilyGeometry.cs (reference planes, sketching, forms, routes), FamilyGeometry.Constraints.cs
/// (dimensions, alignment, parametric box, flex).
/// </summary>
public static partial class FamilyGeometry
{
    /// <summary>ft, half-length of new reference planes</summary>
    public const double Extent = 3.0;

    public static void Register(RouteTable api)
    {
        api.Post("/family/reference_planes/", ReferencePlanesRoute, "reference_planes_route");
        api.Post("/family/forms/", FormsRoute, "forms_route");
        api.Post("/family/dimension/", DimensionRoute, "dimension_route");
        api.Post("/family/align/", AlignRoute, "align_route");
        api.Post("/family/build_box/", BuildBox, "build_box");
        api.Post("/family/flex/", FlexRoute, "flex_route");
        Log.Write("RVTSS family geometry routes registered");
    }

    // ------------------------------------------------------ reference planes
    private static DB.ReferencePlane NewRefPlane(DB.Document doc, object? orientation, double offset, object? name, double extent = Extent)
    {
        DB.XYZ bubble, free, cut;
        DB.View view;
        var o = orientation as string;
        if (o == "x")
        {
            (bubble, free, cut) = (new DB.XYZ(offset, extent, 0), new DB.XYZ(offset, -extent, 0), DB.XYZ.BasisZ);
            view = FamilyUtils.PlanView(doc);
        }
        else if (o == "y")
        {
            (bubble, free, cut) = (new DB.XYZ(extent, offset, 0), new DB.XYZ(-extent, offset, 0), DB.XYZ.BasisZ);
            view = FamilyUtils.PlanView(doc);
        }
        else if (o == "z")
        {
            (bubble, free, cut) = (new DB.XYZ(extent, 0, offset), new DB.XYZ(-extent, 0, offset), DB.XYZ.BasisY);
            view = FamilyUtils.ElevationView(doc, "front");
        }
        else
        {
            throw new RvtssError("orientation must be x (left/right planes), y (front/back) or z (horizontal)");
        }
        var rp = doc.FamilyCreate.NewReferencePlane(bubble, free, cut, view);
        if (Py.Truthy(name))
            rp.Name = Py.Str(name);
        return rp;
    }

    /// <summary>{lower-case plane name: plane}; a later plane with the same name wins, as in the Python dict.</summary>
    private static Dictionary<string, DB.ReferencePlane> PlanesByName(DB.Document doc)
    {
        var existing = new Dictionary<string, DB.ReferencePlane>(StringComparer.Ordinal);
        foreach (var rp in FamilyUtils.ReferencePlanes(doc))
            existing[Utils.NormalizeString(rp.Name).ToLowerInvariant()] = rp;
        return existing;
    }

    public static Dict? ReferencePlanesRoute(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireFamily(doc);
        var unit = ctx.Unit;
        if (ctx.Get("action", "create") is string action && action == "list")
            return new Dict
            {
                ["unit"] = unit,
                ["reference_planes"] = FamilyUtils.ReferencePlanes(doc).Select(rp => FamilyUtils.DescribeRefPlane(rp, unit)).ToList(),
            };
        var items = ctx.List("planes");
        if (items.Count == 0)
            throw new RvtssError("'planes' is required: [{name: 'Left', orientation: 'x', offset: -450}]");
        var existing = PlanesByName(doc);
        var dry = ctx.DryRun;

        Dict? One(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var name = item.Get("name");
            var o = item.Get("orientation");
            var off = Units.ToInternal(item.Get("offset", 0L), unit);
            if (Py.Truthy(name) && existing.TryGetValue(Py.Str(name).ToLowerInvariant(), out var found))
            {
                if (item.Get("if_exists", "reuse") is string ifExists && ifExists == "error")
                    throw new RvtssError($"Reference plane '{Py.Str(name)}' exists", status: 409);
                return new Dict
                {
                    ["name"] = name, ["id"] = Compat.IdInt(found), ["action"] = "exists",
                    ["offset"] = Units.FromInternal((object?)FamilyUtils.PlaneOffset(found), unit, 3),
                };
            }
            var rp = NewRefPlane(doc, o, off, name);
            if (Py.Truthy(item.Get("is_reference")))
            {
                try { FamilyUtils.SetIsReference(rp, item["is_reference"]); }
                catch (RvtssError e) { ctx.Warn($"{Py.Str(name)}: {e.Message}"); }
            }
            return new Dict
            {
                ["name"] = name, ["id"] = Compat.IdInt(rp), ["action"] = "created", ["orientation"] = o,
                ["offset"] = item.Get("offset", 0L),
            };
        }

        var (res, fails) = Core.RunTransaction(doc, "Reference planes", () => Core.Batch(doc, items, One, true), dryRun: dry);
        return Core.CommitResult(new Dict { ["unit"] = unit, ["results"] = res }, fails, dry);
    }

    // ----------------------------------------------------------- sketch plane
    /// <summary>Return (SketchPlane, origin XYZ, x axis, y axis, normal).</summary>
    private static (DB.SketchPlane sp, DB.XYZ origin, DB.XYZ xv, DB.XYZ yv, DB.XYZ normal) SketchPlane(DB.Document doc, object? workPlane)
    {
        var wp = Py.Truthy(workPlane) ? workPlane : "level";
        var datum = FamilyUtils.FindRefPlane(doc, wp)!;
        DB.SketchPlane sp;
        try { sp = DB.SketchPlane.Create(doc, datum.Id); }
        catch { sp = DB.SketchPlane.Create(doc, FamilyUtils.DatumReference(datum)); }
        var plane = sp.GetPlane();
        return (sp, plane.Origin, plane.XVec, plane.YVec, plane.Normal);
    }

    private static DB.XYZ Local(DB.XYZ origin, DB.XYZ xv, DB.XYZ yv, double u, double v) => origin + xv * u + yv * v;

    /// <summary>A request point [a, b, ...] as a list (tuple unpacking / indexing in the Python code).</summary>
    private static List<object?> Seq(object? v) => PureText.Iter(v).ToList();

    /// <summary>
    /// profile: {rectangle: {min, max}} | {circle: {center, radius}} | {loops: [[pt, ...], ...]}.
    ///
    /// Points are local (u, v) in the sketch plane (default) or world [x, y, z]
    /// (coordinates='world', projected onto the plane).
    /// </summary>
    private static List<List<DB.Curve>> LoopsFromProfile(object? profileValue, string unit, DB.XYZ origin, DB.XYZ xv, DB.XYZ yv,
        DB.XYZ normal, object? coordinates)
    {
        var profile = profileValue as Dict
                      ?? throw new FormatException("argument of type '" + Py.TypeName(profileValue) + "' is not iterable");
        var loops = new List<List<DB.XYZ>>();
        if (profile.ContainsKey("rectangle"))
        {
            var r = FamilyUtils.AsItem(profile["rectangle"]);
            var min = Seq(FamilyUtils.Req(r, "min"));
            var max = Seq(FamilyUtils.Req(r, "max"));
            if (min.Count != 2 || max.Count != 2)
                throw new FormatException("rectangle min / max need 2 values each");
            object? x0 = min[0], y0 = min[1], x1 = max[0], y1 = max[1];
            var pts = new[] { (x0, y0), (x1, y0), (x1, y1), (x0, y1) };
            loops.Add(pts.Select(p => Local(origin, xv, yv, Units.ToInternal(p.Item1, unit), Units.ToInternal(p.Item2, unit))).ToList());
        }
        else if (profile.ContainsKey("circle"))
        {
            var c = FamilyUtils.AsItem(profile["circle"]);
            var cen = Seq(c.Get("center", new Lst { 0L, 0L }));
            if (cen.Count != 2)
                throw new FormatException("circle center needs 2 values");
            var center = Local(origin, xv, yv, Units.ToInternal(cen[0], unit), Units.ToInternal(cen[1], unit));
            var radius = Units.ToInternal(FamilyUtils.Req(c, "radius"), unit);
            return new List<List<DB.Curve>>
            {
                new()
                {
                    DB.Arc.Create(center, radius, 0.0, Math.PI, xv, yv),
                    DB.Arc.Create(center, radius, Math.PI, 2 * Math.PI, xv, yv),
                },
            };
        }
        else if (profile.ContainsKey("loops"))
        {
            var world = coordinates is string cs && cs == "world";
            foreach (var loop in Seq(profile["loops"]))
            {
                var pts = new List<DB.XYZ>();
                foreach (var p in Seq(loop))
                {
                    if (world)
                    {
                        var (x, y, z) = Units.PointFrom(p, unit);
                        var w = new DB.XYZ(x, y, z);
                        w = w - normal * (w - origin).DotProduct(normal); // project onto plane
                        pts.Add(w);
                    }
                    else
                    {
                        var uv = Seq(p);
                        pts.Add(Local(origin, xv, yv, Units.ToInternal(uv[0], unit), Units.ToInternal(uv[1], unit)));
                    }
                }
                if (pts.Count < 3)
                    throw new RvtssError("Each profile loop needs at least 3 points");
                loops.Add(pts);
            }
        }
        else
        {
            throw new RvtssError("profile needs 'rectangle', 'circle' or 'loops'");
        }
        var o = new List<List<DB.Curve>>();
        foreach (var pts in loops)
        {
            var curves = new List<DB.Curve>();
            for (var i = 0; i < pts.Count; i++)
            {
                var a = pts[i];
                var b = pts[(i + 1) % pts.Count];
                if (a.DistanceTo(b) < 1e-5)
                    continue;
                curves.Add(DB.Line.CreateBound(a, b));
            }
            o.Add(curves);
        }
        return o;
    }

    private static DB.CurveArrArray CurveArrArr(IEnumerable<IEnumerable<DB.Curve>> loops)
    {
        var arrarr = new DB.CurveArrArray();
        foreach (var loop in loops)
        {
            var arr = new DB.CurveArray();
            foreach (var c in loop)
                arr.Append(c);
            arrarr.Append(arr);
        }
        return arrarr;
    }

    private static DB.CurveArray CurveArr(IEnumerable<DB.Curve> curves)
    {
        var arr = new DB.CurveArray();
        foreach (var c in curves)
            arr.Append(c);
        return arr;
    }

    // ----------------------------------------------------------------- forms
    private static readonly (string key, DB.BuiltInParameter bip, string bipName, string ptype, string group)[] FormParameters =
    {
        ("material_parameter", DB.BuiltInParameter.MATERIAL_ID_PARAM, "MATERIAL_ID_PARAM", "material", "materials"),
        ("visible_parameter", DB.BuiltInParameter.IS_VISIBLE_PARAM, "IS_VISIBLE_PARAM", "yesno", "graphics"),
        ("end_parameter", DB.BuiltInParameter.EXTRUSION_END_PARAM, "EXTRUSION_END_PARAM", "length", "dimensions"),
        ("start_parameter", DB.BuiltInParameter.EXTRUSION_START_PARAM, "EXTRUSION_START_PARAM", "length", "dimensions"),
    };

    private static Dict ApplyFormOptions(Ctx ctx, DB.Document doc, DB.FamilyManager fm, DB.GenericForm form, Dict item)
    {
        var o = new Dict();
        var visValue = item.Get("visibility");
        if (Py.Truthy(visValue))
        {
            var vis = FamilyUtils.AsItem(visValue);
            var v = new DB.FamilyElementVisibility(DB.FamilyElementVisibilityType.Model)
            {
                IsShownInCoarse = Py.Truthy(vis.Get("coarse", true)),
                IsShownInMedium = Py.Truthy(vis.Get("medium", true)),
                IsShownInFine = Py.Truthy(vis.Get("fine", true)),
            };
            if (vis.ContainsKey("plan"))
                v.IsShownInPlanRCPCut = Py.Truthy(vis["plan"]);
            if (vis.ContainsKey("front_back"))
                v.IsShownInFrontBack = Py.Truthy(vis["front_back"]);
            if (vis.ContainsKey("left_right"))
                v.IsShownInLeftRight = Py.Truthy(vis["left_right"]);
            form.SetVisibility(v);
            o["visibility"] = visValue;
        }
        var sub = item.Get("subcategory");
        if (Py.Truthy(sub))
        {
            var subName = Py.Str(sub);
            var parent = doc.OwnerFamily.FamilyCategory;
            DB.Category? subcat = null;
            foreach (DB.Category c in parent.SubCategories)
            {
                if (Utils.NormalizeString(c.Name).ToLowerInvariant() == subName.ToLowerInvariant())
                    subcat = c;
            }
            subcat ??= doc.Settings.Categories.NewSubcategory(parent, subName);
            form.Subcategory = subcat;
            o["subcategory"] = sub;
        }
        foreach (var (key, bip, bipName, ptype, group) in FormParameters)
        {
            var pname = item.Get(key);
            if (!Py.Truthy(pname))
                continue;
            var ep = form.get_Parameter(bip);
            if (ep == null)
                throw new RvtssError($"This form has no {bipName} to associate");
            var fp = ParamsUtil.FamilyParameter(fm, pname);
            if (fp == null)
            {
                fp = Compat.AddFamilyParameter(fm, Py.Str(pname), ptype, group, Py.Truthy(item.Get("instance_parameters", false)));
                if (ptype == "yesno")
                {
                    FamilyUtils.EnsureCurrentType(fm);
                    fm.Set(fp, 1);
                }
                else if (ptype == "length")
                {
                    FamilyUtils.EnsureCurrentType(fm);
                    fm.Set(fp, ep.AsDouble());
                }
            }
            fm.AssociateElementParameterToFamilyParameter(ep, fp);
            o[key] = pname;
        }
        return o;
    }

    private static Lst CutSolids(DB.Document doc, DB.GenericForm voidForm)
    {
        var cut = new Lst();
        var vb = voidForm.get_BoundingBox(null);
        foreach (var (_, f) in FamilyUtils.Forms(doc))
        {
            if (!f.IsSolid)
                continue;
            var bb = f.get_BoundingBox(null);
            if (vb == null || bb == null)
                continue;
            if (bb.Max.X < vb.Min.X || bb.Min.X > vb.Max.X || bb.Max.Y < vb.Min.Y || bb.Min.Y > vb.Max.Y
                || bb.Max.Z < vb.Min.Z || bb.Min.Z > vb.Max.Z)
                continue;
            try
            {
                DB.SolidSolidCutUtils.AddCutBetweenSolids(doc, f, voidForm);
                cut.Add(Compat.IdInt(f));
            }
            catch (Exception e)
            {
                Log.Write("Void cut failed: " + e.Message);
            }
        }
        return cut;
    }

    private static Dict CreateForm(Ctx ctx, DB.Document doc, DB.FamilyManager fm, Dict item)
    {
        var unit = ctx.Unit;
        var kind = item.Get("kind", "extrusion") as string;
        var solid = !Py.Truthy(item.Get("void", false));
        var (sp, origin, xv, yv, normal) = SketchPlane(doc, item.Get("work_plane"));
        var coords = item.Get("coordinates", "local");
        var create = doc.FamilyCreate;
        DB.GenericForm form;
        if (kind == "extrusion")
        {
            var loops = LoopsFromProfile(FamilyUtils.Req(item, "profile"), unit, origin, xv, yv, normal, coords);
            var end = Units.ToInternal(item.Get("end", item.Get("depth", 1000L)), unit);
            var ext = create.NewExtrusion(solid, CurveArrArr(loops), sp, end);
            var start = Units.ToInternal(item.Get("start", 0L), unit);
            if (start != 0.0)
                ext.StartOffset = start;
            ext.EndOffset = end;
            form = ext;
        }
        else if (kind == "blend")
        {
            var baseLoop = LoopsFromProfile(FamilyUtils.Req(item, "base_profile"), unit, origin, xv, yv, normal, coords)[0];
            var height = Units.ToInternal(item.Get("height", 1000L), unit);
            var topOrigin = origin + normal * height;
            var top = LoopsFromProfile(FamilyUtils.Req(item, "top_profile"), unit, topOrigin, xv, yv, normal, coords)[0];
            var blend = create.NewBlend(solid, CurveArr(top), CurveArr(baseLoop), sp);
            blend.TopOffset = height;
            blend.BottomOffset = 0.0;
            form = blend;
        }
        else if (kind == "revolution")
        {
            var loops = LoopsFromProfile(FamilyUtils.Req(item, "profile"), unit, origin, xv, yv, normal, coords);
            var ends = Seq(item.Get("axis", new Lst { new Lst { 0L, 0L }, new Lst { 0L, 1L } }));
            if (ends.Count != 2)
                throw new FormatException("axis needs 2 points");
            var a0 = Seq(ends[0]);
            var a1 = Seq(ends[1]);
            var axis = DB.Line.CreateBound(
                Local(origin, xv, yv, Units.ToInternal(a0[0], unit), Units.ToInternal(a0[1], unit)),
                Local(origin, xv, yv, Units.ToInternal(a1[0], unit), Units.ToInternal(a1[1], unit)));
            form = create.NewRevolution(solid, CurveArrArr(loops), sp, axis,
                Radians(item.Get("start_angle", 0L)), Radians(item.Get("end_angle", 360L)));
        }
        else if (kind == "sweep")
        {
            var pathPts = Seq(FamilyUtils.Req(item, "path")).Select(p =>
            {
                var uv = Seq(p);
                return Local(origin, xv, yv, Units.ToInternal(uv[0], unit), Units.ToInternal(uv[1], unit));
            }).ToList();
            if (pathPts.Count < 2)
                throw new RvtssError("sweep needs a 'path' of at least 2 points");
            var path = new List<DB.Curve>();
            for (var i = 0; i < pathPts.Count - 1; i++)
                path.Add(DB.Line.CreateBound(pathPts[i], pathPts[i + 1]));
            // NewSweep wants the profile drawn in the XY plane around the origin; Revit moves it to the
            // start of the path, perpendicular to it (profile x across the path, y along the plane normal).
            // A profile already placed at the path start fails with "conditions for the inputs not satisfied".
            var loops = LoopsFromProfile(FamilyUtils.Req(item, "profile"), unit, DB.XYZ.Zero, DB.XYZ.BasisX, DB.XYZ.BasisY,
                DB.XYZ.BasisZ, "local");
            var profile = doc.Application.Create.NewCurveLoopsProfile(CurveArrArr(loops));
            form = create.NewSweep(solid, CurveArr(path), sp, profile, 0, DB.ProfilePlaneLocation.Start);
        }
        else
        {
            throw new RvtssError("kind must be extrusion, blend, revolution or sweep");
        }
        doc.Regenerate();
        var o = new Dict
        {
            ["id"] = Compat.IdInt(form), ["kind"] = kind, ["solid"] = solid,
            ["work_plane"] = item.Get("work_plane", "level"),
            ["plane_axes"] = new Dict
            {
                ["origin"] = Core.XyzList(origin, unit),
                ["x"] = new Lst { Py.Round(xv.X, 4), Py.Round(xv.Y, 4), Py.Round(xv.Z, 4) },
                ["y"] = new Lst { Py.Round(yv.X, 4), Py.Round(yv.Y, 4), Py.Round(yv.Z, 4) },
            },
        };
        o.Update(ApplyFormOptions(ctx, doc, fm, form, item));
        if (!solid && Py.Truthy(item.Get("cut_solids", true)))
            o["cuts_solids"] = CutSolids(doc, form);
        if (Py.Truthy(item.Get("align", false)))
            o["alignments"] = AlignForm(doc, form, null, true);
        return o;
    }

    /// <summary>math.radians(v) of a request value.</summary>
    private static double Radians(object? v) => PureText.ToFloat(v) * Math.PI / 180.0;

    public static Dict? FormsRoute(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        if (ctx.Get("action", "create") is string action && action == "list")
            return new Dict
            {
                ["unit"] = ctx.Unit,
                ["forms"] = FamilyUtils.Forms(doc).Select(x => FamilyUtils.DescribeForm(doc, x.kind, x.f, ctx.Unit, fm)).ToList(),
            };
        var items = ctx.List("forms");
        if (items.Count == 0)
            throw new RvtssError("'forms' is required, e.g. [{kind: 'extrusion', profile: {rectangle: {min: [-450,-300], "
                                 + "max: [450,300]}}, end: 750, material_parameter: 'Material'}]");
        var dry = ctx.DryRun;
        var (res, fails) = Core.RunTransaction(doc, "Create forms",
            () => Core.Batch(doc, items, it => CreateForm(ctx, doc, fm, FamilyUtils.AsItem(it)), true), dryRun: dry);
        return Core.CommitResult(new Dict { ["unit"] = ctx.Unit, ["results"] = res }, fails, dry);
    }
}
