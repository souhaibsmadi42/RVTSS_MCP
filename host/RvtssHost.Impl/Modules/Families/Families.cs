namespace RvtssHost.Modules;

/// <summary>
/// Family document (.rfa) management, parameters, types and QC (RVTSS): port of revit_mcp/families.py.
///
/// Family documents are opened in the background (not shown in the Revit UI) and
/// addressed by their title or path through the "document" field, so Claude can
/// edit several families while the project stays active.
///
/// Routes:
///     POST /family/templates/          template folders, matching templates, missing kinds
///     POST /family/create/             new family from a template (optionally saved)
///     POST /family/open/               open an .rfa or edit a family loaded in a project
///     POST /family/info/               category, parameters, formulas, types, planes, dims, forms, nested
///     POST /family/properties/         category and family-level settings
///     POST /family/parameters/         add / remove / rename / formulas / instance-type / reporting /
///                                      replace_with_shared / associate
///     POST /family/types/              list / create / duplicate / rename / delete / set_values /
///                                      export_catalog / import_catalog
///     POST /family/nested/             load + place nested families, associate parameters
///     POST /family/validate/           quality control report
///     POST /family/save/               save / save as with automatic backup
///     POST /family/load_into_project/  load or reload into a project and verify
///     POST /family/close/              close a background family document
///
/// Files: Families.cs (templates, create / open, info, properties, routes), Families.Parameters.cs
/// (parameters, types, catalogs, nested), Families.Validate.cs (validate, save, load, close).
/// </summary>
public static partial class Families
{
    // ---------------------------------------------------------------- routes
    public static void Register(RouteTable api)
    {
        api.Post("/family/templates/", FamilyTemplates, "family_templates", needsDoc: false);
        api.Post("/family/create/", FamilyCreate, "family_create", needsDoc: false);
        api.Post("/family/open/", FamilyOpen, "family_open", needsDoc: false);
        api.Post("/family/info/", FamilyInfo, "family_info");
        api.Post("/family/properties/", FamilyProperties, "family_properties");
        api.Post("/family/parameters/", FamilyParameters, "family_parameters");
        api.Post("/family/types/", FamilyTypes, "family_types");
        api.Post("/family/nested/", FamilyNested, "family_nested");
        api.Post("/family/validate/", FamilyValidate, "family_validate");
        api.Post("/family/save/", FamilySave, "family_save");
        api.Post("/family/load_into_project/", FamilyLoadIntoProject, "family_load_into_project");
        api.Post("/family/close/", FamilyClose, "family_close");
        Log.Write("RVTSS family routes registered");
    }

    /// <summary>sorted(T.TEMPLATE_KINDS)</summary>
    private static List<string> SortedKinds() => Templates.TemplateKinds.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();

    // ------------------------------------------------------------- templates
    private static List<string> TemplateDirs(Ctx ctx)
    {
        var dirs = new Lst();
        try
        {
            if (!string.IsNullOrEmpty(ctx.App.FamilyTemplatePath))
                dirs.Add(ctx.App.FamilyTemplatePath);
        }
        catch { /* no application / no template path */ }
        var cfg = Core.LoadConfig();
        dirs.AddRange(PyX.Items(cfg.Get("family_template_dirs")));
        dirs.AddRange(ctx.List("search_dirs"));
        var o = new List<string>();
        foreach (var d in dirs)
        {
            if (!Py.Truthy(d))
                continue;
            var s = Py.Str(d);
            if (!o.Contains(s))
                o.Add(s);
        }
        return o;
    }

    public static Dict? FamilyTemplates(Ctx ctx)
    {
        var dirs = TemplateDirs(ctx);
        var files = Templates.FindTemplateFiles(dirs);
        var kind = ctx.Get("kind");
        var unitSystemValue = ctx.Get("unit_system");
        var unitSystem = Py.Truthy(unitSystemValue) ? Py.Str(unitSystemValue) : null;
        var result = new Dict
        {
            ["template_dirs"] = dirs.Select(d => new Dict { ["path"] = d, ["exists"] = Directory.Exists(d) }).ToList(),
            ["template_count"] = (long)files.Count, ["kinds"] = SortedKinds(),
        };
        if (Py.Truthy(kind))
        {
            if (kind is not string kindName || !Templates.TemplateKinds.ContainsKey(kindName))
                throw new RvtssError($"Unknown template kind '{Py.Str(kind)}'", hint: "Use one of: " + string.Join(", ", SortedKinds()));
            var matches = Templates.Match(files, kindName, unitSystem);
            result["kind"] = kind;
            result["matches"] = matches.Take(15).ToList();
            if (matches.Count == 0)
            {
                result["missing"] = true;
                result["hint"] = $"No template for '{kindName}' found. Install the Revit family templates for your language "
                                 + "or pass search_dirs / template_path.";
            }
        }
        else
        {
            var coverage = new Dict();
            foreach (var k in SortedKinds())
            {
                var m = Templates.Match(files, k, unitSystem);
                coverage[k] = m.Count > 0 ? PyX.Basename(m[0]) : null;
            }
            result["best_template_per_kind"] = coverage;
            result["missing_kinds"] = coverage.Where(kv => kv.Value == null).Select(kv => kv.Key).ToList();
            var containsValue = ctx.Get("contains");
            var contains = Py.Truthy(containsValue) ? Py.Str(containsValue).ToLowerInvariant() : "";
            if (contains.Length > 0)
                result["files"] = files.Where(f => PyX.Basename(f).ToLowerInvariant().Contains(contains)).Take(200).ToList();
        }
        if (files.Count == 0)
            result["hint"] = "No .rft files found. Check Revit Options > File Locations > Family Template Files, "
                             + "or pass search_dirs.";
        return result;
    }

    // --------------------------------------------------------- open / create
    private static DB.Document? FindOpenByPath(Ctx ctx, string path)
    {
        var target = FamilyUtils.NormCasePath(path);
        foreach (DB.Document d in ctx.App.Documents)
        {
            if (!string.IsNullOrEmpty(d.PathName) && FamilyUtils.NormCasePath(d.PathName) == target)
                return d;
        }
        return null;
    }

    private static Dict FamilySummary(DB.Document doc)
    {
        var fm = doc.FamilyManager;
        var cat = doc.OwnerFamily.FamilyCategory;
        return new Dict
        {
            ["document"] = Utils.NormalizeString(doc.Title), ["path"] = string.IsNullOrEmpty(doc.PathName) ? null : doc.PathName,
            ["family_name"] = FamilyUtils.FamilyName(doc), ["category"] = cat != null ? Utils.NormalizeString(cat.Name) : null,
            ["parameter_count"] = (long)fm.Parameters.Size, ["type_count"] = (long)fm.Types.Size,
            ["types"] = fm.Types.Cast<DB.FamilyType>().Select(t => Utils.NormalizeString(t.Name)).ToList(),
        };
    }

    public static Dict? FamilyCreate(Ctx ctx)
    {
        string template;
        var templateValue = ctx.Get("template_path");
        if (!Py.Truthy(templateValue))
        {
            var kind = ctx.Require("kind", "template kind, e.g. 'door', 'furniture', 'generic_model'");
            var unitSystemValue = ctx.Get("unit_system", "metric");
            var matches = kind is string kindName
                ? Templates.Match(Templates.FindTemplateFiles(TemplateDirs(ctx)), kindName,
                    Py.Truthy(unitSystemValue) ? Py.Str(unitSystemValue) : null)
                : new List<string>();
            if (matches.Count == 0)
                throw new RvtssError($"No family template found for kind '{Py.Str(kind)}'", status: 404,
                    hint: "Run family_list_templates to see available templates, or pass template_path.");
            template = matches[0];
        }
        else
        {
            template = Py.Str(templateValue);
        }
        if (!File.Exists(template))
            throw new RvtssError($"Template not found: {template}", status: 404);
        var savePathValue = ctx.Get("save_path");
        var savePath = Py.Truthy(savePathValue) ? Py.Str(savePathValue) : null;
        if (savePath != null)
        {
            if (!savePath.ToLowerInvariant().EndsWith(".rfa", StringComparison.Ordinal))
                throw new RvtssError("save_path must end with .rfa");
            var folder = FamilyUtils.Dirname(savePath);
            if (folder.Length > 0 && !Directory.Exists(folder))
            {
                if (ctx.Bool("create_folder", true))
                    Directory.CreateDirectory(folder);
                else
                    throw new RvtssError($"Folder does not exist: {folder}", status: 404);
            }
            if (FamilyUtils.PathExists(savePath) && !ctx.Bool("overwrite", false))
                throw new RvtssError($"File already exists: {savePath}", status: 409,
                    hint: "Use family_open to edit the existing family, or pass overwrite=true "
                          + "(a backup copy is made first).");
        }
        var famdoc = ctx.App.NewFamilyDocument(template);
        if (famdoc == null)
            throw new RvtssError($"Revit could not create a family from {template}", status: 500);
        var fm = famdoc.FamilyManager;
        var category = ctx.Get("category");
        var typeName = ctx.Get("type_name");

        var fails = Core.RunTransaction(famdoc, "Set up new family", () =>
        {
            if (Py.Truthy(category))
                famdoc.OwnerFamily.FamilyCategory = Core.ResolveCategory(famdoc, category);
            if (Py.Truthy(typeName) || fm.CurrentType == null)
                fm.NewType(Py.Truthy(typeName) ? Py.Str(typeName) : "Default");
        });
        string? backup = null;
        if (savePath != null)
        {
            Core.RequireWritable("Saving the new family");
            if (FamilyUtils.PathExists(savePath))
                backup = Backup(savePath);
            var opts = new DB.SaveAsOptions { OverwriteExistingFile = true };
            famdoc.SaveAs(savePath, opts);
        }
        var o = FamilySummary(famdoc);
        o.Update(new Dict
        {
            ["template"] = template, ["saved"] = savePath != null, ["backup"] = backup, ["revit_warnings"] = fails,
            ["next_steps"] = $"Pass document='{Utils.NormalizeString(famdoc.Title)}' to family_* tools. Add parameters, geometry, types, then "
                             + "family_flex_test, family_validate, family_save.",
        });
        if (savePath == null)
            o["note"] = "Family is not saved yet. Use family_save with save_path before loading or closing.";
        return o;
    }

    public static Dict? FamilyOpen(Ctx ctx)
    {
        var pathValue = ctx.Get("path");
        var nameValue = ctx.Get("family_name");
        if (Py.Truthy(pathValue))
        {
            var path = Py.Str(pathValue);
            if (!File.Exists(path))
                throw new RvtssError($"File not found: {path}", status: 404);
            var existing = FindOpenByPath(ctx, path);
            if (existing != null)
            {
                var already = FamilySummary(existing);
                already["already_open"] = true;
                return already;
            }
            var famdoc = ctx.App.OpenDocumentFile(path);
            if (!famdoc.IsFamilyDocument)
                throw new RvtssError($"{path} is not a family file");
            var opened = FamilySummary(famdoc);
            opened["opened_from"] = "file";
            return opened;
        }
        if (Py.Truthy(nameValue))
        {
            var name = Py.Str(nameValue);
            var doc = ctx.Doc;
            Core.RequireProject(doc);
            DB.Family? fam = null;
            foreach (var f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
            {
                if (Utils.NormalizeString(f.Name).ToLowerInvariant() == name.ToLowerInvariant())
                {
                    fam = (DB.Family)f;
                    break;
                }
            }
            if (fam == null)
                throw Core.NotFound("Loaded family", nameValue,
                    new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)).Select(f => (string?)f.Name));
            if (fam.IsInPlace || !fam.IsEditable)
                throw new RvtssError($"Family '{name}' is {(fam.IsInPlace ? "in-place" : "not editable")} and cannot be opened for editing",
                    status: 409);
            var famdoc = doc.EditFamily(fam);
            var o = FamilySummary(famdoc);
            o.Update(new Dict
            {
                ["opened_from"] = "project", ["project"] = Utils.NormalizeString(doc.Title),
                ["note"] = "This is an unsaved in-memory copy. Use family_load_into_project to push changes "
                           + "back, and/or family_save with save_path to keep an .rfa file.",
            });
            return o;
        }
        throw new RvtssError("Pass 'path' to an .rfa file or 'family_name' of a family loaded in the project");
    }

    // ------------------------------------------------------------------ info
    private static readonly (string bip, string key)[] InfoProperties =
    {
        ("FAMILY_WORK_PLANE_BASED", "work_plane_based"), ("FAMILY_ALWAYS_VERTICAL", "always_vertical"),
        ("FAMILY_SHARED", "shared"), ("FAMILY_ROOM_CALCULATION_POINT", "room_calculation_point"),
        ("FAMILY_ALLOW_CUT_WITH_VOIDS", "cut_with_voids"), ("FAMILY_IS_PARAMETRIC", "parametric"),
        ("FAMILY_HOSTING_BEHAVIOR", "hosting"),
    };

    public static Dict? FamilyInfo(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var unit = ctx.Unit;
        var includeList = ctx.List("include");
        if (includeList.Count == 0)
            includeList = new Lst { "parameters", "types", "reference_planes", "dimensions", "forms", "nested", "properties" };
        var include = new HashSet<string>(includeList.OfType<string>(), StringComparer.Ordinal);
        var labels = FamilyUtils.LabeledDimensions(doc);
        var o = FamilySummary(doc);
        o["unit"] = unit;
        if (include.Contains("properties"))
        {
            var fam = doc.OwnerFamily;
            var props = new Dict();
            foreach (var (bip, key) in InfoProperties)
            {
                var b = Py.EnumOrNull<DB.BuiltInParameter>(bip);
                if (b == null)
                    continue;
                try
                {
                    var p = fam.get_Parameter(b.Value);
                    if (p != null)
                    {
                        var text = p.AsValueString();
                        props[key] = !string.IsNullOrEmpty(text) ? text : (long)p.AsInteger();
                    }
                }
                catch { continue; }
            }
            o["properties"] = props;
            try { o["warnings"] = (long)doc.GetWarnings().Count; }
            catch { /* not available */ }
        }
        if (include.Contains("parameters"))
        {
            var includeBuiltin = ctx.Bool("include_builtin", false);
            var prms = fm.Parameters.Cast<DB.FamilyParameter>().Where(fp => FamilyUtils.IsRelevant(fp, includeBuiltin))
                .Select(fp => FamilyUtils.FamilyParamInfo(doc, fm, fp, unit, labels)).ToList();
            // sort key: ("builtin" in p, p["name"].lower()); the sort is stable like Python's
            o["parameters"] = prms.OrderBy(p => p.ContainsKey("builtin"))
                .ThenBy(p => ((string)p["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }
        if (include.Contains("types"))
        {
            var maxTypes = ctx.Int("max_types", 50)!.Value;
            var includeBuiltin = ctx.Bool("include_builtin", false);
            var names = fm.Parameters.Cast<DB.FamilyParameter>().Where(fp => FamilyUtils.IsRelevant(fp, includeBuiltin)).ToList();
            var types = new List<Dict>();
            foreach (var t in PyX.Head(fm.Types.Cast<DB.FamilyType>().ToList(), maxTypes))
            {
                var vals = new Dict();
                foreach (var fp in names)
                {
                    try { vals[Utils.NormalizeString(fp.Definition.Name)] = ParamsUtil.FamilyTypeValue(fm, t, fp, unit); }
                    catch { continue; }
                }
                types.Add(new Dict { ["name"] = Utils.NormalizeString(t.Name), ["values"] = vals });
            }
            o["types"] = types;
            o["current_type"] = fm.CurrentType != null ? Utils.NormalizeString(fm.CurrentType.Name) : null;
        }
        if (include.Contains("reference_planes"))
        {
            o["reference_planes"] = FamilyUtils.ReferencePlanes(doc).Select(rp => FamilyUtils.DescribeRefPlane(rp, unit)).ToList();
            var lv = FamilyUtils.RefLevel(doc);
            o["reference_level"] = lv != null ? Utils.NormalizeString(lv.Name) : null;
        }
        if (include.Contains("dimensions"))
        {
            o["dimensions"] = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Dimension)).Cast<DB.Dimension>()
                .Select(d => FamilyUtils.DescribeDimension(d, unit)).ToList();
        }
        if (include.Contains("forms"))
            o["forms"] = FamilyUtils.Forms(doc).Select(x => FamilyUtils.DescribeForm(doc, x.kind, x.f, unit, fm)).ToList();
        if (include.Contains("nested"))
        {
            var nested = new List<Dict>();
            foreach (var e in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
            {
                var f = (DB.Family)e;
                if (f.Id == doc.OwnerFamily.Id)
                    continue;
                long count = 0;
                foreach (var sid in f.GetFamilySymbolIds())
                    count += new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilyInstance)).Cast<DB.FamilyInstance>()
                        .Count(fi => fi.Symbol.Id == sid);
                bool? shared = null;
                try { shared = f.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED).AsInteger() == 1; }
                catch { /* not available */ }
                nested.Add(new Dict
                {
                    ["id"] = Compat.IdInt(f), ["name"] = Utils.NormalizeString(f.Name),
                    ["category"] = f.FamilyCategory != null ? Utils.NormalizeString(f.FamilyCategory.Name) : null,
                    ["types"] = f.GetFamilySymbolIds().Select(s => Utils.NormalizeString(Utils.GetElementName(doc.GetElement(s)))).ToList(),
                    ["instances"] = count, ["shared"] = shared,
                });
            }
            o["nested_families"] = nested;
        }
        return o;
    }

    private static readonly Dictionary<string, string> PropertyMapping = new()
    {
        ["work_plane_based"] = "FAMILY_WORK_PLANE_BASED", ["always_vertical"] = "FAMILY_ALWAYS_VERTICAL",
        ["shared"] = "FAMILY_SHARED", ["room_calculation_point"] = "FAMILY_ROOM_CALCULATION_POINT",
        ["cut_with_voids"] = "FAMILY_ALLOW_CUT_WITH_VOIDS",
    };

    public static Dict? FamilyProperties(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireFamily(doc);
        var fam = doc.OwnerFamily;
        var setValue = ctx.Get("set");
        var changes = Py.Truthy(setValue) ? FamilyUtils.AsItem(setValue) : new Dict();
        var category = ctx.Get("category");
        if (changes.Count == 0 && !Py.Truthy(category))
            throw new RvtssError("Pass category and/or set: {work_plane_based, always_vertical, shared, "
                                 + "room_calculation_point, cut_with_voids}");
        var dry = ctx.DryRun;

        var (res, fails) = Core.RunTransaction(doc, "Family properties", () =>
        {
            var done = new Dict();
            if (Py.Truthy(category))
            {
                var old = fam.FamilyCategory?.Name;
                fam.FamilyCategory = Core.ResolveCategory(doc, category);
                done["category"] = new Dict { ["old"] = old, ["new"] = fam.FamilyCategory.Name };
            }
            foreach (var (key, val) in changes)
            {
                var bip = Py.EnumOrNull<DB.BuiltInParameter>(PropertyMapping.TryGetValue(key, out var bipName) ? bipName : "");
                if (bip == null)
                    throw new RvtssError($"Unknown property '{key}'. Use: "
                                         + string.Join(", ", PropertyMapping.Keys.OrderBy(x => x, StringComparer.Ordinal)));
                var p = fam.get_Parameter(bip.Value);
                if (p == null || p.IsReadOnly)
                    throw new RvtssError($"Property '{key}' is not available for this family template", status: 409);
                p.Set(Py.Truthy(val) ? 1 : 0);
                done[key] = Py.Truthy(val);
            }
            return new Dict { ["changed"] = done };
        }, dryRun: dry);
        return Core.CommitResult(res, fails, dry);
    }
}
