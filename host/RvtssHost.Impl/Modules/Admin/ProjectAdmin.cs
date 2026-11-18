using System.Reflection;

namespace RvtssHost.Modules;

/// <summary>
/// Insert, manage and collaborate (RVTSS v2.4): port of revit_mcp/project_admin.py.
///
/// Routes:
///     POST /insert/files/         list CAD links / imports and images; link or import CAD (DWG, DXF, DGN, SAT,
///                                 SKP); place an image; reload or delete a CAD link
///     POST /insert/family/        load .rfa files (or one type) from disk into the document
///     POST /project/settings/     project information, project units, starting view, project location
///     POST /styles/manage/        object styles, subcategories, line styles, line patterns, fill patterns
///     POST /standards/transfer/   copy types / templates / filters / materials / patterns from another open
///                                 document (Transfer Project Standards)
///     POST /worksharing/          ownership status, relinquish, reload latest, shared coordinates with a link
///
/// Relinquish and reload latest talk to the central model outside a transaction and cannot be undone, so
/// they follow the same policy as sync_with_central (RVTSS_ALLOW_SYNC / "allow_sync").
///
/// Split over ProjectAdmin.cs (helpers, insert files, load family), ProjectAdmin.Settings.cs,
/// ProjectAdmin.Styles.cs and ProjectAdmin.Standards.cs (transfer standards, worksharing).
/// </summary>
public static partial class ProjectAdmin
{
    /// <summary>register_project_admin_routes</summary>
    public static void Register(RouteTable api)
    {
        api.Post("/insert/files/", InsertFiles, "insert_files");
        api.Post("/insert/family/", LoadFamily, "load_family");
        api.Post("/project/settings/", ProjectSettings, "project_settings");
        api.Post("/styles/manage/", ManageStyles, "manage_styles");
        api.Post("/standards/transfer/", TransferStandards, "transfer_standards");
        api.Post("/worksharing/", Worksharing, "worksharing");
    }

    // ------------------------------------------------------------------------ helpers
    internal static string Name(DB.Element? e) => Utils.NormalizeString(Utils.GetElementName(e));

    /// <summary>os.path.splitext on a Windows path: (root, ext); leading dots of the name are not an extension.</summary>
    internal static (string root, string ext) SplitExt(string path)
    {
        var sep = Math.Max(path.LastIndexOf('\\'), path.LastIndexOf('/'));
        var dot = path.LastIndexOf('.');
        if (dot > sep)
        {
            var i = sep + 1;
            while (i < dot && path[i] == '.')
                i++;
            if (i < dot)
                return (path.Substring(0, dot), path.Substring(dot));
        }
        return (path, "");
    }

    /// <summary>os.path.normpath (ntpath): forward slashes become backslashes, "." and ".." are collapsed.</summary>
    internal static string NormPath(string path)
    {
        if (path.Length == 0)
            return ".";
        var p = path.Replace('/', '\\');
        var prefix = "";
        if (p.StartsWith("\\\\", StringComparison.Ordinal) && !p.StartsWith("\\\\\\", StringComparison.Ordinal))
        {
            // UNC: \\host\share is the drive part
            var firstSep = p.IndexOf('\\', 2);
            if (firstSep > 2)
            {
                var secondSep = p.IndexOf('\\', firstSep + 1);
                var end = secondSep < 0 ? p.Length : secondSep;
                prefix = p.Substring(0, end);
                p = p.Substring(end);
            }
        }
        else if (p.Length >= 2 && p[1] == ':')
        {
            prefix = p.Substring(0, 2);
            p = p.Substring(2);
        }
        var rooted = p.StartsWith("\\", StringComparison.Ordinal);
        if (rooted)
            prefix += "\\";
        var comps = new List<string>();
        foreach (var c in p.Split(new[] { '\\' }))
        {
            if (c.Length == 0 || c == ".")
                continue;
            if (c == "..")
            {
                if (comps.Count > 0 && comps[comps.Count - 1] != "..")
                    comps.RemoveAt(comps.Count - 1);
                else if (!rooted)
                    comps.Add(c);
            }
            else
            {
                comps.Add(c);
            }
        }
        var result = prefix + string.Join("\\", comps);
        return result.Length == 0 ? "." : result;
    }

    internal static string ExistingFile(object? path, ICollection<string>? extensions = null, string what = "File")
    {
        if (!Py.Truthy(path))
            throw new RvtssError("'path' is required");
        var full = NormPath(Environment.ExpandEnvironmentVariables(Py.Str(path)));
        if (!File.Exists(full))
            throw new RvtssError($"{what} not found: {full}", status: 404,
                hint: "Give the full path as Revit's machine sees it.");
        var ext = SplitExt(full).ext.ToLowerInvariant();
        if (extensions != null && extensions.Count > 0 && !extensions.Contains(ext))
            throw new RvtssError($"{what} must be one of {string.Join(", ", extensions.OrderBy(x => x, StringComparer.Ordinal))} (got '{ext}')");
        return full;
    }

    /// <summary>[r, g, b] or '#rrggbb' -> DB.Color.</summary>
    internal static DB.Color Color(object? value)
    {
        int[] rgb;
        if (value is Lst list && list.Count == 3)
        {
            rgb = new[] { (int)Py.ToInt(list[0]), (int)Py.ToInt(list[1]), (int)Py.ToInt(list[2]) };
        }
        else
        {
            var s = Py.Str(value).Trim().TrimStart('#');
            if (s.Length != 6)
                throw new RvtssError($"Colour must be [r, g, b] or '#rrggbb' (got '{Py.Str(value)}')");
            try
            {
                rgb = new[]
                {
                    Convert.ToInt32(s.Substring(0, 2), 16), Convert.ToInt32(s.Substring(2, 2), 16),
                    Convert.ToInt32(s.Substring(4, 2), 16),
                };
            }
            catch (Exception)
            {
                throw new RvtssError($"Colour must be [r, g, b] or '#rrggbb' (got '{Py.Str(value)}')");
            }
        }
        if (rgb.Any(v => v < 0 || v > 255))
            throw new RvtssError("Colour components must be 0-255");
        return new DB.Color((byte)rgb[0], (byte)rgb[1], (byte)rgb[2]);
    }

    internal static Lst? ColorList(DB.Color? c)
    {
        try
        {
            if (c == null || !c.IsValid)
                return null;
            return new Lst { (long)c.Red, (long)c.Green, (long)c.Blue };
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Same switch as sync_with_central: talking to central is off unless allow_sync is set.</summary>
    internal static void RequireSyncPolicy(string action)
    {
        bool allowed;
        try { allowed = Py.Truthy(SecureApi.Settings().Get("allow_sync")); }
        catch { allowed = false; }
        if (!allowed)
            throw new RvtssError(
                $"{action} is refused: synchronize with central is off in the RVTSS policy (allow_sync)",
                status: 403,
                hint: "Do it in Revit yourself, or set \"allow_sync\": true in %APPDATA%/RVTSS/config.json (or "
                      + "RVTSS_ALLOW_SYNC=1 for Revit) and restart Revit.")
                .With("code", "POLICY_DENIED").With("policy", "allow_sync");
    }

    internal static void NoOpenTransaction(DB.Document doc, string action)
    {
        if (doc.IsModifiable)
            throw new RvtssError($"{action} cannot run while a transaction is open", status: 409);
        if (Core.InBatch())
            throw new RvtssError($"{action} cannot run in batch_execute (it is not a transaction and cannot be rolled back)");
    }

    // ------------------------------------------------------------------- insert files
    internal static readonly Dictionary<string, string> CadExt = new()
    {
        [".dwg"] = "dwg", [".dxf"] = "dwg", [".dgn"] = "dgn", [".sat"] = "sat", [".skp"] = "skp",
    };

    internal static readonly string[] ImageExt = { ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pdf" };

    private static readonly Dictionary<string, DB.ImportPlacement> Placement = new()
    {
        ["origin"] = DB.ImportPlacement.Origin, ["center"] = DB.ImportPlacement.Centered,
        ["shared"] = DB.ImportPlacement.Shared, ["site"] = DB.ImportPlacement.Site,
    };

    private static readonly Dictionary<string, DB.ImportUnit> ImportUnits = new()
    {
        ["auto"] = DB.ImportUnit.Default, ["mm"] = DB.ImportUnit.Millimeter, ["cm"] = DB.ImportUnit.Centimeter,
        ["dm"] = DB.ImportUnit.Decimeter, ["m"] = DB.ImportUnit.Meter, ["ft"] = DB.ImportUnit.Foot,
        ["in"] = DB.ImportUnit.Inch,
    };

    private static readonly Dictionary<string, DB.ImportColorMode> ColorModes = new()
    {
        ["preserve"] = DB.ImportColorMode.Preserved, ["invert"] = DB.ImportColorMode.Inverted,
        ["black_white"] = DB.ImportColorMode.BlackAndWhite,
    };

    private static string SortedKeys<T>(Dictionary<string, T> map) =>
        string.Join(", ", map.Keys.OrderBy(x => x, StringComparer.Ordinal));

    private static bool InMap<T>(Dictionary<string, T> map, object? key, out T value)
    {
        if (key is string s && map.TryGetValue(s, out var v))
        {
            value = v;
            return true;
        }
        value = default!;
        return false;
    }

    internal static (DB.BaseImportOptions opts, Dict applied, List<string> ignored) CadOptions(Ctx ctx, string kind)
    {
        var cls = kind switch
        {
            "dwg" => "DWGImportOptions", "dgn" => "DGNImportOptions", "sat" => "SATImportOptions",
            _ => "SKPImportOptions",
        };
        // hasattr(DB, cls): the option classes are looked up by name, as not every Revit version has all of them
        var type = typeof(DB.Document).Assembly.GetType("Autodesk.Revit.DB." + cls);
        if (type == null)
            throw new RvtssError($"This Revit version has no {cls}", status: 501);
        var opts = (DB.BaseImportOptions)Activator.CreateInstance(type)!;
        var applied = new Dict();
        var ignored = new List<string>();

        void Put(string attr, object value, string label)
        {
            try
            {
                var prop = type.GetProperty(attr, BindingFlags.Public | BindingFlags.Instance);
                if (prop == null)
                    throw new MissingMemberException(attr);
                prop.SetValue(opts, value);
                applied[label] = Py.Str(value);
            }
            catch
            {
                ignored.Add(label);
            }
        }

        var placement = ctx.Get("placement", "origin");
        if (!InMap(Placement, placement, out var place))
            throw new RvtssError($"placement must be one of: {SortedKeys(Placement)}");
        Put("Placement", place, "placement");
        var unit = ctx.Get("import_unit", "auto");
        if (!InMap(ImportUnits, unit, out var importUnit))
            throw new RvtssError($"import_unit must be one of: {SortedKeys(ImportUnits)}");
        Put("Unit", importUnit, "import_unit");
        if (kind == "dwg" || kind == "dgn")
        {
            var colour = ctx.Get("color_mode", "preserve");
            if (!InMap(ColorModes, colour, out var colorMode))
                throw new RvtssError($"color_mode must be one of: {SortedKeys(ColorModes)}");
            Put("ColorMode", colorMode, "color_mode");
            Put("ThisViewOnly", ctx.Bool("current_view_only", false), "current_view_only");
            Put("VisibleLayersOnly", ctx.Bool("visible_layers_only", false), "visible_layers_only");
            if (ctx.Bool("orient_to_view", false))
                Put("OrientToView", true, "orient_to_view");
        }
        return (opts, applied, ignored);
    }

    /// <summary>doc.Link / doc.Import: the API has one overload per options class.</summary>
    private static bool LinkOrImport(DB.Document doc, bool link, string path, DB.BaseImportOptions opts, DB.View view,
        out DB.ElementId? id)
    {
        switch (opts)
        {
            case DB.DWGImportOptions dwg:
                return link ? doc.Link(path, dwg, view, out id) : doc.Import(path, dwg, view, out id);
            case DB.DGNImportOptions dgn:
                return link ? doc.Link(path, dgn, view, out id) : doc.Import(path, dgn, view, out id);
            default:
            {
                // SAT / SKP: the overload, when this Revit version has one, is found by reflection
                var method = typeof(DB.Document).GetMethod(link ? "Link" : "Import",
                    new[] { typeof(string), opts.GetType(), typeof(DB.View), typeof(DB.ElementId).MakeByRefType() });
                if (method == null)
                    throw new RvtssError($"This Revit version cannot {(link ? "link" : "import")} files with {opts.GetType().Name}",
                        status: 501);
                var args = new object?[] { path, opts, view, null };
                var ok = (bool)method.Invoke(doc, args)!;
                id = (DB.ElementId?)args[3];
                return ok;
            }
        }
    }

    internal static List<DB.ImportInstance> CadInstances(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ImportInstance)).Cast<DB.ImportInstance>().ToList();

    internal static string? CadPath(DB.Document doc, DB.ElementId typeId)
    {
        try
        {
            var t = doc.GetElement(typeId);
            var reference = t.GetExternalFileReference();
            return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(reference.GetAbsolutePath());
        }
        catch
        {
            return null;
        }
    }

    internal static Dict CadBrief(DB.Document doc, DB.ImportInstance inst)
    {
        string? owner = null;
        try
        {
            if (inst.ViewSpecific && Compat.IsValidId(inst.OwnerViewId))
                owner = Utils.NormalizeString(doc.GetElement(inst.OwnerViewId).Name);
        }
        catch { /* owner stays null */ }
        return new Dict
        {
            ["id"] = inst.Id.Value, ["type_id"] = inst.GetTypeId().Value, ["name"] = Name(doc.GetElement(inst.GetTypeId())),
            ["is_linked"] = inst.IsLinked, ["pinned"] = inst.Pinned, ["view_specific_in"] = owner,
            ["path"] = inst.IsLinked ? CadPath(doc, inst.GetTypeId()) : null,
        };
    }

    internal static Lst Images(DB.Document doc)
    {
        var result = new Lst();
        foreach (DB.ImageType t in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ImageType)))
        {
            var d = new Dict { ["type_id"] = t.Id.Value, ["name"] = Name(t) };
            try { d["path"] = Utils.NormalizeString(t.Path); }
            catch { /* no path for this image type */ }
            result.Add(d);
        }
        var byType = new Dictionary<long, Lst>();
        foreach (DB.ImageInstance i in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ImageInstance)))
        {
            var tid = i.GetTypeId().Value;
            if (!byType.TryGetValue(tid, out var ids))
                byType[tid] = ids = new Lst();
            ids.Add(i.Id.Value);
        }
        foreach (Dict d in result)
            d["instance_ids"] = byType.TryGetValue((long)d["type_id"]!, out var found) ? found : new Lst();
        return result;
    }

    internal static (DB.ImportInstance inst, DB.Element? type) FindCad(DB.Document doc, object? reference)
    {
        var key = Py.Str(reference).Trim().ToLowerInvariant();
        foreach (var inst in CadInstances(doc))
        {
            var t = doc.GetElement(inst.GetTypeId());
            if (key == Py.Str(inst.Id.Value) || key == Py.Str(inst.GetTypeId().Value) || key == Name(t).ToLowerInvariant())
                return (inst, t);
        }
        throw Core.NotFound("CAD link / import", reference, CadInstances(doc).Select(i => Name(doc.GetElement(i.GetTypeId()))));
    }

    /// <summary>ImageType from a file (the options class changed in 2020 and 2021).</summary>
    internal static DB.ImageType ImageTypeFrom(DB.Document doc, string path)
    {
        var errors = new List<string>();
        try
        {
            return DB.ImageType.Create(doc, new DB.ImageTypeOptions(path, false, DB.ImageTypeSource.Import));
        }
        catch (Exception e)
        {
            errors.Add(e.Message);
        }
        throw new RvtssError($"Revit could not create an image type from '{path}'",
            hint: string.Join("; ", errors.Skip(Math.Max(0, errors.Count - 2)).Select(x => Utils.NormalizeString(x))));
    }

    public static Dict? InsertFiles(Ctx ctx)
    {
        var doc = ctx.Doc;
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var cad = CadInstances(doc).Select(i => CadBrief(doc, i)).ToList();
            return new Dict
            {
                ["cad_count"] = cad.Count, ["cad"] = cad, ["images"] = Images(doc),
                ["cad_linked"] = cad.Count(c => (bool)c["is_linked"]!),
                ["cad_imported"] = cad.Count(c => !(bool)c["is_linked"]!),
            };
        }
        if (action == "link_cad" || action == "import_cad")
        {
            var path = ExistingFile(ctx.Get("path"), new HashSet<string>(CadExt.Keys), "CAD file");
            var kind = CadExt[SplitExt(path).ext.ToLowerInvariant()];
            var (opts, applied, ignored) = CadOptions(ctx, kind);
            var view = Core.FindView(doc, ctx.Get("view", "active"), uidoc: ctx.UiDoc)!;
            if (view.IsTemplate)
                throw new RvtssError("A view template cannot host a CAD file");
            var plan = new Dict
            {
                ["action"] = action, ["path"] = path, ["format"] = kind, ["options"] = applied,
                ["options_not_supported_for_format"] = ignored, ["view"] = Utils.NormalizeString(view.Name),
            };
            if (ctx.DryRun)
            {
                var preview = new Dict(plan);
                preview["status"] = "dry_run";
                preview["committed"] = false;
                preview["message"] = "Dry run: the file and options were checked; the file was not loaded.";
                return preview;
            }

            Dict Run()
            {
                DB.ElementId? newId;
                var ok = LinkOrImport(doc, action == "link_cad", path, opts, view, out newId);
                if (!ok || !Compat.IsValidId(newId))
                    throw new RvtssError($"Revit did not {(action == "link_cad" ? "link" : "import")} '{Path.GetFileName(path)}'",
                        status: 409, hint: "Check that the file opens in its own application and is not empty.");
                var inst = doc.GetElement(newId);
                if (ctx.Bool("pin", true))
                {
                    try { inst.Pinned = true; }
                    catch { /* pinning is a convenience */ }
                }
                return new Dict { ["element_id"] = newId!.Value };
            }

            var (res, fails) = Core.RunTransaction(doc, action == "link_cad" ? "Link CAD" : "Import CAD", Run);
            return Core.CommitResult(res, fails, false, plan);
        }
        if (action == "place_image")
        {
            var path = ExistingFile(ctx.Get("path"), new HashSet<string>(ImageExt), "Image");
            var view = Core.FindView(doc, ctx.Get("view", "active"), uidoc: ctx.UiDoc)!;
            var pointValue = ctx.Get("point");
            var (x, y, z) = Units.PointFrom(Py.Truthy(pointValue) ? pointValue : new Lst { 0L, 0L, 0L }, ctx.Unit);
            var width = ctx.Float("width");

            Dict Run()
            {
                var itype = ImageTypeFrom(doc, path);
                var placement = new DB.ImagePlacementOptions(new DB.XYZ(x, y, z), DB.BoxPlacement.Center);
                var inst = DB.ImageInstance.Create(doc, view, itype.Id, placement);
                var o = new Dict { ["image_type_id"] = itype.Id.Value, ["image_id"] = inst.Id.Value };
                if (width != null && width.Value != 0.0)
                {
                    try
                    {
                        inst.LockProportions = true;
                        inst.Width = Units.ToInternal(width.Value, ctx.Unit);
                        o["width"] = width.Value;
                    }
                    catch (Exception e)
                    {
                        ctx.Warn("Width was not set: " + Utils.NormalizeString(e.Message));
                    }
                }
                return o;
            }

            var (res, fails) = Core.RunTransaction(doc, "Place image", Run, ctx.DryRun);
            return Core.CommitResult(res, fails, ctx.DryRun, new Dict { ["view"] = Utils.NormalizeString(view.Name), ["path"] = path });
        }
        if (action == "reload_cad")
        {
            var (inst, ltype) = FindCad(doc, ctx.Require("link"));
            if (!inst.IsLinked || ltype is not DB.CADLinkType cadType)
                throw new RvtssError($"'{Name(ltype)}' is an import, not a link; imports cannot be reloaded", status: 409);
            if (ctx.DryRun)
                return new Dict { ["status"] = "dry_run", ["would_reload"] = CadBrief(doc, inst) };
            Core.RequireWritable("reload CAD link");
            NoOpenTransaction(doc, "Reloading a CAD link");
            try
            {
                cadType.Reload();
            }
            catch (Exception e)
            {
                // some versions want a transaction around the reload
                if (!e.Message.ToLowerInvariant().Contains("transaction"))
                    throw;
                Core.RunTransaction(doc, "Reload CAD link", () => { cadType.Reload(); });
            }
            return new Dict { ["reloaded"] = CadBrief(doc, inst) };
        }
        if (action == "delete")
        {
            var (inst, ltype) = FindCad(doc, ctx.Require("link"));
            var brief = CadBrief(doc, inst);
            var whole = ctx.Bool("all_instances", true);
            if (!ctx.Confirmed && !ctx.DryRun)
                return new Dict
                {
                    ["status"] = "preview", ["requires_confirmation"] = true, ["would_delete"] = brief,
                    ["message"] = "Preview only - nothing was deleted. Re-run with confirm=true to apply.",
                };

            Dict Run()
            {
                var target = whole ? ltype!.Id : inst.Id;
                var deleted = doc.Delete(target).Select(i => i.Value).ToList();
                return new Dict { ["deleted"] = brief, ["deleted_ids"] = deleted.Take(200).ToList(), ["deleted_count"] = deleted.Count };
            }

            var (res, fails) = Core.RunTransaction(doc, "Delete CAD", Run, ctx.DryRun);
            return Core.CommitResult(res, fails, ctx.DryRun);
        }
        throw new RvtssError("action must be list, link_cad, import_cad, place_image, reload_cad or delete");
    }

    // -------------------------------------------------------------------- load family
    private sealed class FamilyLoadOptions(bool overwrite, bool overwriteValues) : DB.IFamilyLoadOptions
    {
        public bool Found;

        public bool OnFamilyFound(bool familyInUse, out bool overwriteParameterValues)
        {
            Found = true;
            overwriteParameterValues = overwriteValues;
            return overwrite;
        }

        public bool OnSharedFamilyFound(DB.Family sharedFamily, bool familyInUse, out DB.FamilySource source,
            out bool overwriteParameterValues)
        {
            Found = true;
            source = DB.FamilySource.Family;
            overwriteParameterValues = overwriteValues;
            return overwrite;
        }
    }

    internal static DB.Family? FamilyNamed(DB.Document doc, string name)
    {
        foreach (DB.Family f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
            if (Utils.NormalizeString(f.Name) == name)
                return f;
        return null;
    }

    internal static List<string> FamilyTypes(DB.Document doc, DB.Family fam) =>
        fam.GetFamilySymbolIds().Select(s => Name(doc.GetElement(s))).OrderBy(x => x, StringComparer.Ordinal).ToList();

    public static Dict? LoadFamily(Ctx ctx)
    {
        var doc = ctx.Doc;
        var paths = ctx.List("paths");
        if (paths.Count == 0)
            paths = ctx.List("path");
        if (paths.Count == 0)
            throw new RvtssError("'paths' is required: one or more .rfa files");
        if (paths.Count > 100)
            throw new RvtssError("At most 100 families per call");
        var rfa = new HashSet<string> { ".rfa" };
        var files = paths.Select(p => ExistingFile(p, rfa, "Family file")).ToList();
        var typeName = ctx.Get("type");
        if (Py.Truthy(typeName) && files.Count != 1)
            throw new RvtssError("'type' loads one type from one family: give a single path");
        var overwrite = ctx.Bool("overwrite", false);
        var overwriteValues = ctx.Bool("overwrite_parameter_values", false);

        Dict One(object? item)
        {
            var path = (string)item!;
            var baseName = Utils.NormalizeString(SplitExt(Path.GetFileName(path)).root);
            var before = FamilyNamed(doc, baseName);
            var beforeTypes = before != null ? FamilyTypes(doc, before) : new List<string>();
            var opts = new FamilyLoadOptions(overwrite, overwriteValues);
            bool ok;
            if (Py.Truthy(typeName))
                ok = doc.LoadFamilySymbol(path, Py.Str(typeName), opts, out DB.FamilySymbol? _);
            else
                ok = doc.LoadFamily(path, opts, out DB.Family? _);
            var fam = FamilyNamed(doc, baseName);
            if (fam == null)
                throw new RvtssError($"Revit did not load '{baseName}'",
                    hint: "The family may be from a newer Revit version, or the type name is wrong.");
            var types = FamilyTypes(doc, fam);
            string result;
            if (before == null)
                result = "loaded";
            else if (ok)
                result = "reloaded";
            else
                result = "already_loaded";
            var o = new Dict
            {
                ["family"] = baseName, ["family_id"] = fam.Id.Value, ["result"] = result, ["types"] = types,
                ["new_types"] = types.Where(t => !beforeTypes.Contains(t)).ToList(),
            };
            if (result == "already_loaded" && !overwrite && !Py.Truthy(typeName))
                o["hint"] = "Pass overwrite=true to reload the family from the file.";
            return o;
        }

        Dict Run() => new() { ["results"] = Core.Batch(doc, files.Cast<object?>(), One, ctx.Bool("atomic", false)) };

        var (res, fails) = Core.RunTransaction(doc, "Load families", Run, ctx.DryRun);
        var results = (Lst)res["results"]!;
        res["loaded"] = results.Cast<Dict>().Count(r => Py.Truthy(r.Get("ok")) && !(r.Get("result") is string rs && rs == "already_loaded"));
        res["failed"] = results.Cast<Dict>().Count(r => !Py.Truthy(r.Get("ok")));
        for (var i = 0; i < results.Count && i < files.Count; i++)
            ((Dict)results[i]!)["path"] = files[i];
        return Core.CommitResult(res, fails, ctx.DryRun);
    }
}
