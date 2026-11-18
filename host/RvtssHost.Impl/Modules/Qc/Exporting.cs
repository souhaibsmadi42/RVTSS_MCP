using System.Diagnostics;
using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Exports written by Revit: PDF, DWG, DXF, IFC, NWC, schedule CSV (RVTSS v2.2). Port of revit_mcp/exporting.py.
///
/// Routes:
///     POST /export/settings/   DWG export setups, PDF export settings (2022+), view/sheet sets, IFC versions,
///                              Navisworks exporter availability, default folder
///     POST /export/run/        export sheets / views / schedules / the model to a folder on the Revit machine
///
/// Files are written by Revit, on the Revit machine. One file per sheet / view
/// (named from a template such as "{number} - {name}") unless combine=true (PDF).
/// Existing files are never overwritten unless overwrite=true.
/// </summary>
public static class Exporting
{
    public static void Register(RouteTable api)
    {
        api.Post("/export/settings/", Settings, "settings");
        api.Post("/export/run/", RunExport, "run_export");
    }

    /// <summary>os.path.expanduser("~")</summary>
    private static string UserHome()
    {
        var home = Environment.GetEnvironmentVariable("HOME");
        if (!string.IsNullOrEmpty(home))
            return home!;
        var profile = Environment.GetEnvironmentVariable("USERPROFILE");
        if (!string.IsNullOrEmpty(profile))
            return profile!;
        return Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    }

    private static string Stem(string title) => PyX.Splitext(title).root;

    public static string DefaultFolder(DB.Document doc)
    {
        var baseDir = PyX.Join(PyX.Join(PyX.Join(UserHome(), "Documents"), "RVTSS"), "exports");
        var stem = Exportnames.Sanitize(Stem(Utils.NormalizeString(doc.Title)));
        return PyX.Join(baseDir, stem);
    }

    private static List<DB.ElementId> IdList(IEnumerable<DB.ElementId> ids) => new(ids);

    private static Dict SheetFields(DB.Document doc, DB.View v)
    {
        var f = new Dict
        {
            ["name"] = Utils.NormalizeString(v.Name), ["title"] = Utils.NormalizeString(doc.Title),
            ["view_type"] = v.ViewType.ToString(), ["date"] = DateTime.Now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
            ["document"] = Stem(Utils.NormalizeString(doc.Title)),
        };
        if (v is DB.ViewSheet sheet)
        {
            f["number"] = Utils.NormalizeString(sheet.SheetNumber);
            try
            {
                var p = v.get_Parameter(DB.BuiltInParameter.SHEET_CURRENT_REVISION);
                f["revision"] = p != null ? Utils.NormalizeString(p.AsString() ?? "") : "";
            }
            catch
            {
                f["revision"] = "";
            }
        }
        else
        {
            f["number"] = v.Id.Value.ToString(CultureInfo.InvariantCulture);
        }
        return f;
    }

    /// <summary>Views / sheets / schedules to export, in a stable order.</summary>
    private static List<DB.View> ResolveTargets(Ctx ctx, string fmt)
    {
        var doc = ctx.Doc;
        var res = new List<DB.View>();
        var seen = new HashSet<long>();

        void Add(DB.View? v)
        {
            if (v != null && seen.Add(v.Id.Value))
                res.Add(v);
        }

        var allSheets = new List<DB.ViewSheet>();
        foreach (DB.ViewSheet s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)))
            if (!s.IsTemplate && !s.IsPlaceholder)
                allSheets.Add(s);
        allSheets = allSheets.OrderBy(s => Utils.NormalizeString(s.SheetNumber), StringComparer.Ordinal).ToList();
        if (ctx.Bool("all_sheets", false))
            foreach (var s in allSheets)
                Add(s);
        var byNumber = new Dictionary<string, DB.ViewSheet>(StringComparer.Ordinal);
        foreach (var s in allSheets)
            byNumber[Utils.NormalizeString(s.SheetNumber).ToLowerInvariant()] = s;
        foreach (var s in ctx.List("sheets"))
        {
            var key = Py.Str(s).Trim();
            byNumber.TryGetValue(key.ToLowerInvariant(), out var sheet);
            if (sheet == null && key.Length > 0 && key.All(char.IsDigit))
                sheet = doc.GetElement(Compat.MakeId(Py.ToInt(key))) as DB.ViewSheet;
            if (sheet == null)
                throw Core.NotFound("Sheet", s, allSheets.Select(x => x.SheetNumber));
            Add(sheet);
        }
        foreach (var v in ctx.List("views"))
            Add(Core.FindView(doc, v));
        if (Py.Truthy(ctx.Get("view_set")))
        {
            var name = Py.Str(ctx.Get("view_set")).ToLowerInvariant();
            var sets = new List<DB.ViewSheetSet>();
            foreach (DB.ViewSheetSet set in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheetSet)))
                sets.Add(set);
            var match = sets.Where(s => Utils.NormalizeString(s.Name).ToLowerInvariant() == name).ToList();
            if (match.Count == 0)
                throw Core.NotFound("View/sheet set", ctx.Get("view_set"), sets.Select(s => s.Name));
            var members = new List<DB.View>();
            foreach (DB.View v in match[0].Views)
                members.Add(v);
            // sheets first, then by sheet number (or name)
            foreach (var v in members
                         .OrderBy(v => !(v is DB.ViewSheet))
                         .ThenBy(v => Utils.NormalizeString(v is DB.ViewSheet vs && !string.IsNullOrEmpty(vs.SheetNumber) ? vs.SheetNumber : v.Name),
                             StringComparer.Ordinal))
                Add(v);
        }
        if (fmt == "csv")
        {
            var bad = res.Where(v => v is not DB.ViewSchedule).Select(v => (object?)Utils.NormalizeString(v.Name)).ToList();
            if (bad.Count > 0)
                throw new RvtssError("CSV export takes schedules only; not schedules: " + PyX.Repr(PyX.Head(bad, 10)));
        }
        else if (Array.IndexOf(Exportnames.ModelFormats, fmt) < 0)
        {
            var bad = res.Where(v => v is DB.ViewSchedule || v.IsTemplate).Select(v => (object?)Utils.NormalizeString(v.Name)).ToList();
            if (bad.Count > 0)
                throw new RvtssError($"These views cannot be exported as {fmt.ToUpperInvariant()}: {PyX.Repr(PyX.Head(bad, 10))}",
                    hint: "Place schedules on sheets and export the sheets, or use format='csv'.");
        }
        return res;
    }

    private static List<string> CheckFiles(string folder, List<string> stems, string fmt, bool overwrite)
    {
        var paths = stems.Select(s => PyX.Join(folder, s + Exportnames.Formats[fmt])).ToList();
        var existing = paths.Where(p => File.Exists(p) || Directory.Exists(p)).ToList();
        if (existing.Count > 0 && !overwrite)
            throw new RvtssError($"{existing.Count} file(s) already exist, e.g. {existing[0]}", status: 409,
                hint: "Pass overwrite=true, another folder or another naming template.")
                .With("existing", existing.Take(20).Cast<object?>().ToList());
        return paths;
    }

    private static DB.PDFExportOptions PdfOptions(DB.Document doc, Ctx ctx)
    {
        // Revit 2022+ has PDFExportOptions: the "needs Revit 2022 or newer" refusal cannot happen on 2024 - 2027
        DB.PDFExportOptions? opts = null;
        if (Py.Truthy(ctx.Get("setup")))
        {
            try
            {
                var found = DB.ExportPDFSettings.FindByName(doc, Py.Str(ctx.Get("setup")));
                opts = found?.GetOptions();
            }
            catch
            {
                opts = null;
            }
            if (opts == null)
                throw Core.NotFound("PDF export setting", ctx.Get("setup"), PdfSettingNames(doc));
        }
        if (opts == null)
        {
            opts = new DB.PDFExportOptions();
            try { opts.HideCropBoundaries = true; } catch { /* not available */ }
            try { opts.HideScopeBoxes = true; } catch { /* not available */ }
            try { opts.HideReferencePlane = true; } catch { /* not available */ }
            try { opts.HideUnreferencedViewTags = true; } catch { /* not available */ }
        }
        var color = ctx.Get("pdf_color");
        if (Py.Truthy(color))
        {
            try
            {
                opts.ColorDepth = (color as string) switch
                {
                    "color" => DB.ColorDepthType.Color,
                    "grayscale" => DB.ColorDepthType.GrayScale,
                    "black_line" => DB.ColorDepthType.BlackLine,
                    _ => throw new KeyNotFoundException(Py.Str(color)),
                };
            }
            catch
            {
                ctx.Warn("pdf_color not applied on this Revit version");
            }
        }
        return opts;
    }

    private static List<string> PdfSettingNames(DB.Document doc)
    {
        try
        {
            return new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ExportPDFSettings)).Select(s => Utils.NormalizeString(s.Name)).ToList();
        }
        catch
        {
            return new List<string>();
        }
    }

    private static DB.BaseExportOptions DwgOptions(DB.Document doc, Ctx ctx, bool dxf = false)
    {
        if (dxf)
            return new DB.DXFExportOptions();
        if (Py.Truthy(ctx.Get("setup")))
        {
            var predefined = DB.DWGExportOptions.GetPredefinedOptions(doc, Py.Str(ctx.Get("setup")));
            if (predefined == null)
                throw Core.NotFound("DWG export setup", ctx.Get("setup"), DwgSetupNames(doc));
            return predefined;
        }
        var opts = new DB.DWGExportOptions();
        try { opts.MergedViews = true; } // one DWG per view, xrefs off
        catch { /* not available */ }
        return opts;
    }

    private static List<string> DwgSetupNames(DB.Document doc)
    {
        try
        {
            return new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ExportDWGSettings)).Select(s => Utils.NormalizeString(s.Name)).ToList();
        }
        catch
        {
            return new List<string>();
        }
    }

    private static DB.IFCExportOptions IfcOptions(DB.Document doc, Ctx ctx)
    {
        var opts = new DB.IFCExportOptions();
        var version = ctx.Get("ifc_version");
        if (Py.Truthy(version))
        {
            var member = Py.EnumOrNull<DB.IFCVersion>(Py.Str(version));
            if (member == null)
                throw new RvtssError($"Unknown ifc_version '{Py.Str(version)}'. Available: {string.Join(", ", IfcVersions())}");
            opts.FileVersion = member.Value;
        }
        if (Py.Truthy(ctx.Get("ifc_view")))
        {
            var v = Core.FindView(doc, ctx.Get("ifc_view"))!;
            opts.FilterViewId = v.Id;
        }
        var extra = ctx.Get("ifc_options");
        if (Py.Truthy(extra))
        {
            // exporter options by name, e.g. {"ExportBaseQuantities": "true", "SpaceBoundaries": "1"}
            if (extra is not Dict map)
                throw new Qc.AttributeError("'" + Qc.PyType(extra) + "' object has no attribute 'items'");
            foreach (var kv in map)
                opts.AddOption(kv.Key, Py.Str(kv.Value));
        }
        return opts;
    }

    private static List<string> IfcVersions()
    {
        try
        {
            return Enum.GetNames(typeof(DB.IFCVersion)).ToList();
        }
        catch
        {
            return new List<string> { "IFC2x3", "IFC4", "IFC2x3CV2", "IFC4RV", "IFC4DTV" };
        }
    }

    private static bool NwcAvailable()
    {
        try { return DB.OptionalFunctionalityUtils.IsNavisworksExporterAvailable(); }
        catch { return false; }
    }

    public static Dict? Settings(Ctx ctx)
    {
        var doc = ctx.Doc;
        var sets = new Lst();
        try
        {
            foreach (DB.ViewSheetSet s in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheetSet)))
                sets.Add(new Dict { ["id"] = s.Id.Value, ["name"] = Utils.NormalizeString(s.Name), ["views"] = (long)s.Views.Size });
        }
        catch { /* keep the sets found so far */ }
        return new Dict
        {
            ["default_folder"] = DefaultFolder(doc), ["dwg_setups"] = DwgSetupNames(doc), ["pdf_settings"] = PdfSettingNames(doc),
            ["pdf_supported"] = true, ["view_sheet_sets"] = sets, ["ifc_versions"] = IfcVersions(),
            ["navisworks_exporter_available"] = NwcAvailable(),
            ["formats"] = Exportnames.Formats.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList(),
            ["naming_fields"] = Exportnames.Fields.Select(f => "{" + f + "}").ToList(),
        };
    }

    /// <summary>os.path.isabs (ntpath): a drive-less path counts as absolute when it starts with a slash.</summary>
    private static bool IsAbs(string path)
    {
        var rest = path;
        if (path.Length >= 2 && path[1] == ':')
        {
            rest = path.Substring(2);
        }
        else if (path.Length >= 2 && (path[0] == '\\' || path[0] == '/') && (path[1] == '\\' || path[1] == '/'))
        {
            // UNC: \\server\share is the drive
            var norm = path.Replace('/', '\\');
            var i = norm.IndexOf('\\', 2);
            if (i < 0)
            {
                rest = "";
            }
            else
            {
                var j = norm.IndexOf('\\', i + 1);
                rest = j < 0 ? "" : norm.Substring(j);
            }
        }
        return rest.Length > 0 && (rest[0] == '/' || rest[0] == '\\');
    }

    private static string Lower(object? value) => Py.Truthy(value) ? Py.Str(value).ToLowerInvariant() : "";

    public static Dict? RunExport(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var fmt = Lower(ctx.Require("format"));
        if (!Exportnames.Formats.ContainsKey(fmt))
            throw new RvtssError("format must be one of: " + string.Join(", ", Exportnames.Formats.Keys.OrderBy(k => k, StringComparer.Ordinal)));
        var folder = Py.Truthy(ctx.Get("folder")) ? Py.Str(ctx.Get("folder")) : DefaultFolder(doc);
        if (!IsAbs(folder))
            throw new RvtssError("folder must be an absolute path on the Revit machine: " + folder);
        var overwrite = ctx.Bool("overwrite", false);
        var modelFormat = Array.IndexOf(Exportnames.ModelFormats, fmt) >= 0;
        var targets = modelFormat ? new List<DB.View>() : ResolveTargets(ctx, fmt);
        if (!modelFormat && targets.Count == 0)
            throw new RvtssError("Nothing to export: give sheets, views, view_set or all_sheets=true");
        var template = ctx.Get("naming");
        List<string> stems;
        var docStem = Stem(Utils.NormalizeString(doc.Title));
        if (modelFormat)
        {
            var fileName = Py.Truthy(ctx.Get("file_name")) ? Py.Str(ctx.Get("file_name")) : docStem;
            var stem = Exportnames.StripExtension(fileName, fmt);
            stems = new List<string> { Exportnames.Sanitize(stem) };
        }
        else if (fmt == "pdf" && ctx.Bool("combine", false))
        {
            var fileName = Py.Truthy(ctx.Get("file_name")) ? Py.Str(ctx.Get("file_name")) : docStem + " - combined";
            stems = new List<string> { Exportnames.Sanitize(Exportnames.StripExtension(fileName, fmt)) };
        }
        else
        {
            try
            {
                stems = Exportnames.Unique(targets.Select(v => Exportnames.Render(
                    Py.Truthy(template) ? Py.Str(template) : Exportnames.DefaultTemplate(v is DB.ViewSheet), SheetFields(doc, v))));
            }
            catch (NamingError e)
            {
                throw new RvtssError(e.Message);
            }
        }
        var ext = Exportnames.Formats[fmt];
        var planned = stems.Select(s => PyX.Join(folder, s + ext)).ToList();
        var preview = new Dict
        {
            ["format"] = fmt, ["folder"] = folder, ["files"] = planned, ["file_count"] = (long)planned.Count,
            ["targets"] = PyX.Head(targets.Select(v =>
            {
                var number = v is DB.ViewSheet vs ? Utils.NormalizeString(vs.SheetNumber ?? "") : "";
                return (object?)new Dict { ["id"] = v.Id.Value, ["name"] = Utils.NormalizeString(v.Name), ["number"] = number.Length > 0 ? number : null };
            }).ToList(), 200),
        };
        if (ctx.DryRun)
        {
            preview.Update(new Dict { ["status"] = "dry_run", ["message"] = "Dry run: nothing was exported." });
            return preview;
        }
        Core.RequireWritable("Export");
        if (fmt == "nwc" && !NwcAvailable())
            throw new RvtssError("The Navisworks NWC exporter is not installed for this Revit version", status: 501,
                hint: "Install 'Navisworks NWC Export Utility' (Autodesk) for this Revit year.");
        if (!Directory.Exists(folder))
            Directory.CreateDirectory(folder);
        CheckFiles(folder, stems, fmt, overwrite);
        var started = Stopwatch.StartNew();
        var results = new List<Dict>();
        if (fmt == "pdf")
        {
            var opts = PdfOptions(doc, ctx);
            if (ctx.Bool("combine", false))
            {
                opts.Combine = true;
                opts.FileName = stems[0];
                var ok = doc.Export(folder, IdList(targets.Select(v => v.Id)), opts);
                results.Add(new Dict { ["file"] = planned[0], ["ok"] = ok });
            }
            else
            {
                opts.Combine = true; // one view per call -> exact file name per sheet
                for (var i = 0; i < targets.Count; i++)
                {
                    var v = targets[i];
                    opts.FileName = stems[i];
                    try
                    {
                        var ok = doc.Export(folder, IdList(new[] { v.Id }), opts);
                        results.Add(new Dict { ["id"] = v.Id.Value, ["file"] = planned[i], ["ok"] = ok });
                    }
                    catch (Exception e)
                    {
                        results.Add(new Dict { ["id"] = v.Id.Value, ["file"] = planned[i], ["ok"] = false, ["error"] = Utils.NormalizeString(e.Message) });
                    }
                }
            }
        }
        else if (fmt == "dwg" || fmt == "dxf")
        {
            var opts = DwgOptions(doc, ctx, dxf: fmt == "dxf");
            for (var i = 0; i < targets.Count; i++)
            {
                var v = targets[i];
                try
                {
                    var ids = IdList(new[] { v.Id });
                    var ok = opts is DB.DWGExportOptions dwg
                        ? doc.Export(folder, stems[i], ids, dwg)
                        : doc.Export(folder, stems[i], ids, (DB.DXFExportOptions)opts);
                    results.Add(new Dict { ["id"] = v.Id.Value, ["file"] = planned[i], ["ok"] = ok });
                }
                catch (Exception e)
                {
                    results.Add(new Dict { ["id"] = v.Id.Value, ["file"] = planned[i], ["ok"] = false, ["error"] = Utils.NormalizeString(e.Message) });
                }
            }
        }
        else if (fmt == "csv")
        {
            var opts = new DB.ViewScheduleExportOptions();
            opts.FieldDelimiter = Py.Truthy(ctx.Get("delimiter")) ? Py.Str(ctx.Get("delimiter")) : ",";
            for (var i = 0; i < targets.Count; i++)
            {
                var v = targets[i];
                try
                {
                    ((DB.ViewSchedule)v).Export(folder, stems[i] + ".csv", opts);
                    results.Add(new Dict { ["id"] = v.Id.Value, ["file"] = planned[i], ["ok"] = true });
                }
                catch (Exception e)
                {
                    results.Add(new Dict { ["id"] = v.Id.Value, ["file"] = planned[i], ["ok"] = false, ["error"] = Utils.NormalizeString(e.Message) });
                }
            }
        }
        else if (fmt == "ifc")
        {
            Core.CheckModifiable(doc);
            var opts = IfcOptions(doc, ctx);
            // the IFC exporter must run inside a transaction; nothing it does is kept
            using var t = new DB.Transaction(doc, "RVTSS: IFC export");
            t.Start();
            bool ok;
            try
            {
                ok = doc.Export(folder, stems[0], opts);
            }
            finally
            {
                if (t.HasStarted() && !t.HasEnded())
                    t.RollBack();
            }
            results.Add(new Dict { ["file"] = planned[0], ["ok"] = ok });
        }
        else if (fmt == "nwc")
        {
            var opts = new DB.NavisworksExportOptions();
            if (Py.Truthy(ctx.Get("nwc_view")))
            {
                var v = Core.FindView(doc, ctx.Get("nwc_view"))!;
                opts.ExportScope = DB.NavisworksExportScope.View;
                opts.ViewId = v.Id;
            }
            else
            {
                opts.ExportScope = DB.NavisworksExportScope.Model;
            }
            doc.Export(folder, stems[0], opts);
            results.Add(new Dict { ["file"] = planned[0], ["ok"] = true });
        }
        foreach (var r in results)
        {
            var file = (string)r["file"]!;
            var exists = File.Exists(file) || Directory.Exists(file);
            if (Py.Truthy(r.Get("ok")) && !exists)
            {
                r["ok"] = false;
                r["error"] = "Revit reported success but the file was not found";
            }
            if (exists)
                r["size_kb"] = (long)(new FileInfo(file).Length / 1024);
        }
        var failed = results.Where(r => !Py.Truthy(r.Get("ok"))).ToList();
        var o = new Dict
        {
            ["format"] = fmt, ["folder"] = folder, ["exported"] = (long)(results.Count - failed.Count), ["failed"] = failed,
            ["files"] = results.Where(r => Py.Truthy(r.Get("ok"))).ToList(),
            ["seconds"] = Py.Round(started.Elapsed.TotalSeconds, 1),
        };
        if (failed.Count > 0 && failed.Count == results.Count)
        {
            o["status"] = "error";
            o["error"] = "No file was exported";
            o["hint"] = Py.Truthy(failed[0].Get("error")) ? failed[0]["error"] : "Check the views (empty / not printable) and the export setup.";
        }
        return o;
    }
}
