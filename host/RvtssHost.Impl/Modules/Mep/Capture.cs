namespace RvtssHost.Modules;

/// <summary>
/// Look at elements: a temporary 3D view framed on them, exported as an image (RVTSS v2.3).
/// Port of revit_mcp/capture.py.
///
/// Routes:
///     POST /views/capture/   section box around element_ids (+ margin), orientation preset or eye/target,
///                            optional isolate / highlight / perspective; PNG or JPG, base64
///
/// Everything happens inside a TransactionGroup that is rolled back after the export, so the model,
/// its views and the undo history are unchanged (works in read-only mode too).
/// </summary>
public static class Capture
{
    /// <summary>direction the camera looks (forward); the eye sits on the opposite side of the box centre</summary>
    public static readonly Dictionary<string, (double x, double y, double z)> Orientations = new()
    {
        ["iso_se"] = (-1.0, 1.0, -1.0), ["iso_sw"] = (1.0, 1.0, -1.0), ["iso_ne"] = (-1.0, -1.0, -1.0),
        ["iso_nw"] = (1.0, -1.0, -1.0), ["top"] = (0.0, 0.0, -1.0), ["front"] = (0.0, 1.0, 0.0),
        ["back"] = (0.0, -1.0, 0.0), ["left"] = (1.0, 0.0, 0.0), ["right"] = (-1.0, 0.0, 0.0),
    };

    private static (DB.XYZ? lo, DB.XYZ? hi) UnionBbox(IEnumerable<DB.Element> elements)
    {
        DB.XYZ? lo = null;
        DB.XYZ? hi = null;
        foreach (var e in elements)
        {
            var bb = e.get_BoundingBox(null);
            if (bb == null)
                continue;
            if (lo == null)
            {
                lo = bb.Min;
                hi = bb.Max;
            }
            else
            {
                lo = new DB.XYZ(Math.Min(lo.X, bb.Min.X), Math.Min(lo.Y, bb.Min.Y), Math.Min(lo.Z, bb.Min.Z));
                hi = new DB.XYZ(Math.Max(hi!.X, bb.Max.X), Math.Max(hi.Y, bb.Max.Y), Math.Max(hi.Z, bb.Max.Z));
            }
        }
        return (lo, hi);
    }

    private static DB.XYZ UpFor(DB.XYZ forward)
    {
        if (Math.Abs(forward.Z) > 0.999)
            return DB.XYZ.BasisY;
        var right = forward.CrossProduct(DB.XYZ.BasisZ).Normalize();
        return right.CrossProduct(forward).Normalize();
    }

    private static DB.ElementId? SolidFill(DB.Document doc)
    {
        foreach (var el in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FillPatternElement)))
        {
            try
            {
                if (((DB.FillPatternElement)el).GetFillPattern().IsSolidFill)
                    return el.Id;
            }
            catch
            {
                continue;
            }
        }
        return null;
    }

    /// <summary>core._start_tx (private in Core.cs): a transaction whose failures are collected.</summary>
    private static DB.Transaction StartTx(DB.Document doc, string name)
    {
        var t = new DB.Transaction(doc, name);
        var collector = new Core.FailureCollector();
        var opts = t.GetFailureHandlingOptions();
        opts.SetFailuresPreprocessor(collector);
        opts.SetClearAfterRollback(true);
        t.SetFailureHandlingOptions(opts);
        t.Start();
        return t;
    }

    private static byte[] Export(DB.Document doc, DB.View view, string fmt, int pixelSize)
    {
        var folder = Path.Combine(Path.GetTempPath(), "rvtss_capture_" + Guid.NewGuid().ToString("N").Substring(0, 8));
        Directory.CreateDirectory(folder);
        var prefix = Path.Combine(folder, "capture");
        var ieo = new DB.ImageExportOptions { ExportRange = DB.ExportRange.SetOfViews };
        var ids = new List<DB.ElementId> { view.Id };
        ieo.SetViewsAndSheets(ids);
        ieo.FilePath = prefix;
        var ft = fmt == "jpg" ? DB.ImageFileType.JPEGMedium : DB.ImageFileType.PNG;
        ieo.HLRandWFViewsFileType = ft;
        ieo.ShadowViewsFileType = ft;
        ieo.ImageResolution = DB.ImageResolution.DPI_150;
        ieo.ZoomType = DB.ZoomFitType.FitToPage;
        ieo.PixelSize = pixelSize;
        doc.ExportImage(ieo);
        var files = Directory.GetFileSystemEntries(folder).ToList();
        if (files.Count == 0)
            throw new RvtssError("Revit exported no image", status: 500);
        var path = files.OrderByDescending(f => new FileInfo(f).Length).First();
        try
        {
            return File.ReadAllBytes(path);
        }
        finally
        {
            foreach (var f in files)
            {
                try { File.Delete(f); } catch { }
            }
            try { Directory.Delete(folder); } catch { }
        }
    }

    public static Dict? CaptureView(Ctx ctx)
    {
        var doc = ctx.Doc;
        if (doc.IsFamilyDocument)
            throw new RvtssError("capture works in project documents", hint: "Use get_revit_view in the family editor.");
        var elements = Core.GetElements(doc, ctx.List("element_ids"));
        if (elements.Count == 0)
            throw new RvtssError("element_ids is required");
        var (lo0, hi0) = UnionBbox(elements);
        if (lo0 == null || hi0 == null)
            throw new RvtssError("None of the elements has a 3D bounding box (annotation only?)");
        var elo = lo0;
        var ehi = hi0;
        var margin = Units.ToInternal(ctx.Float("margin", 1000.0) ?? 1000.0, ctx.Unit);
        var lo = new DB.XYZ(lo0.X - margin, lo0.Y - margin, lo0.Z - margin);
        var hi = new DB.XYZ(hi0.X + margin, hi0.Y + margin, hi0.Z + margin);
        var center = (lo + hi) * 0.5;
        var imageFormat = Py.Str(ctx.Get("image_format", "png")).ToLowerInvariant();
        var fmt = imageFormat == "jpg" || imageFormat == "jpeg" ? "jpg" : "png";
        var pixelSize = (int)(ctx.Int("pixel_size", 1024, minimum: 128, maximum: 4096) ?? 1024);
        var orientation = ctx.Get("orientation", "iso_se");
        DB.XYZ eye;
        DB.XYZ forward;
        if (Py.Truthy(ctx.Get("eye")) && Py.Truthy(ctx.Get("target")))
        {
            var e3 = Units.PointFrom(ctx.Get("eye"), ctx.Unit);
            var t3 = Units.PointFrom(ctx.Get("target"), ctx.Unit);
            eye = new DB.XYZ(e3.x, e3.y, e3.z);
            var target = new DB.XYZ(t3.x, t3.y, t3.z);
            forward = (target - eye).Normalize();
        }
        else
        {
            if (orientation is not string orientationName || !Orientations.TryGetValue(orientationName, out var dir))
                throw new RvtssError("orientation must be one of "
                                     + "[" + string.Join(", ", Orientations.Keys.OrderBy(k => k, StringComparer.Ordinal).Select(k => "'" + k + "'"))
                                     + "] (or pass eye + target)");
            forward = new DB.XYZ(dir.x, dir.y, dir.z).Normalize();
            eye = center - forward.Multiply((hi - lo).GetLength()).Multiply(1.5);
        }
        var vft = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewFamilyType)).Cast<DB.ViewFamilyType>()
            .Where(t => t.ViewFamily == DB.ViewFamily.ThreeDimensional).ToList();
        if (vft.Count == 0)
            throw new RvtssError("The model has no 3D view type");
        var ids = Core.ToIdList(elements.Select(e => e.Id).ToList());

        var group = new DB.TransactionGroup(doc, "RVTSS: capture (temporary, rolled back)");
        group.Start();
        byte[] data;
        DB.Transaction? tx = null;
        try
        {
            tx = StartTx(doc, "RVTSS: capture view");
            var persp = ctx.Bool("perspective", false);
            var v = persp ? DB.View3D.CreatePerspective(doc, vft[0].Id) : DB.View3D.CreateIsometric(doc, vft[0].Id);
            var box = new DB.BoundingBoxXYZ { Min = lo, Max = hi };
            v.SetSectionBox(box);
            v.SetOrientation(new DB.ViewOrientation3D(eye, UpFor(forward), forward));
            v.DetailLevel = DB.ViewDetailLevel.Fine;
            // datums run far outside the section box and would shrink the zoom-to-fit image
            foreach (var bicName in new[] { "OST_Levels", "OST_Grids", "OST_CLines", "OST_SectionBox", "OST_Cameras" })
            {
                try
                {
                    var bic = Py.EnumOrNull<DB.BuiltInCategory>(bicName) ?? throw new MissingMemberException(bicName);
                    var cat = DB.Category.GetCategory(doc, bic);
                    if (cat != null && v.CanCategoryBeHidden(cat.Id))
                        v.SetCategoryHidden(cat.Id, true);
                }
                catch { }
            }
            var style = ctx.Get("display_style", "shaded") as string;
            v.DisplayStyle = style == "wireframe" ? DB.DisplayStyle.Wireframe
                : style == "hidden" ? DB.DisplayStyle.HLR
                : style == "realistic" ? DB.DisplayStyle.Realistic
                : DB.DisplayStyle.ShadingWithEdges;
            if (ctx.Bool("isolate", false))
            {
                v.IsolateElementsTemporary(ids);
                v.ConvertTemporaryHideIsolateToPermanent();
            }
            if (ctx.Bool("highlight", true) && !ctx.Bool("isolate", false))
            {
                var ogs = new DB.OverrideGraphicSettings();
                var color = new DB.Color(255, 120, 0);
                var fill = SolidFill(doc);
                ogs.SetProjectionLineColor(color);
                if (fill != null)
                {
                    ogs.SetSurfaceForegroundPatternId(fill);
                    ogs.SetSurfaceForegroundPatternColor(color);
                }
                foreach (var e in elements)
                    v.SetElementOverrides(e.Id, ogs);
            }
            if (!persp)
            {
                // image export fits the whole view, not the section box: crop to the elements (view coordinates)
                doc.Regenerate();
                var cb = v.CropBox;
                var inv = cb.Transform.Inverse;
                var pad = Math.Max((ehi - elo).GetLength() * 0.04, Units.ToInternal(100.0, "mm"));
                var corners = new List<DB.XYZ>();
                foreach (var x in new[] { elo.X - pad, ehi.X + pad })
                    foreach (var y in new[] { elo.Y - pad, ehi.Y + pad })
                        foreach (var z in new[] { elo.Z - pad, ehi.Z + pad })
                            corners.Add(inv.OfPoint(new DB.XYZ(x, y, z)));
                var crop = new DB.BoundingBoxXYZ { Transform = cb.Transform };
                crop.Min = new DB.XYZ(corners.Min(p => p.X), corners.Min(p => p.Y), cb.Min.Z);
                crop.Max = new DB.XYZ(corners.Max(p => p.X), corners.Max(p => p.Y), cb.Max.Z);
                v.CropBox = crop;
                v.CropBoxActive = true;
                v.CropBoxVisible = false;
            }
            if (tx.Commit() != DB.TransactionStatus.Committed)
                throw new RvtssError("Revit rejected the temporary 3D view", status: 409);
            data = Export(doc, v, fmt, pixelSize);
        }
        catch
        {
            // close an open transaction so the group can roll back (best effort; the original error is kept)
            try { if (tx != null && tx.HasStarted() && !tx.HasEnded()) tx.RollBack(); } catch { }
            throw;
        }
        finally
        {
            if (group.HasStarted() && !group.HasEnded())
                group.RollBack();
        }
        return new Dict
        {
            ["image_data"] = Convert.ToBase64String(data),
            ["content_type"] = fmt == "jpg" ? "image/jpeg" : "image/png",
            ["file_size_bytes"] = (long)data.Length,
            ["elements"] = elements.Take(50).Select(e => (object?)Compat.IdInt(e)).ToList(),
            ["orientation"] = Py.Truthy(ctx.Get("eye")) ? "custom" : orientation,
            ["section_box"] = new Dict
            {
                ["min"] = Units.PointTo((lo.X, lo.Y, lo.Z), ctx.Unit),
                ["max"] = Units.PointTo((hi.X, hi.Y, hi.Z), ctx.Unit),
            },
        };
    }

    public static void Register(RouteTable api)
    {
        api.Post("/views/capture/", CaptureView, "capture");
    }
}
