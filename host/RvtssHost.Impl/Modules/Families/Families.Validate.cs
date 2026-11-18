namespace RvtssHost.Modules;

public static partial class Families
{
    // -------------------------------------------------------------- validate
    public static Dict? FamilyValidate(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var findings = new List<Dict>();
        var labels = FamilyUtils.LabeledDimensions(doc);
        var all = fm.Parameters.Cast<DB.FamilyParameter>().ToList();
        // user parameters for "drives nothing" checks (built-ins like door Width are driven by Revit itself)
        var prms = all.Where(fp => !FamilyUtils.IsBuiltin(fp)).ToList();
        var relevant = all.Where(fp => FamilyUtils.IsRelevant(fp)).ToList();
        var names = prms.Select(fp => Utils.NormalizeString(fp.Definition.Name)).ToList();
        var relevantNames = relevant.Select(fp => Utils.NormalizeString(fp.Definition.Name)).ToList();
        var formulas = new Dict();
        foreach (var fp in relevant)
        {
            if (!string.IsNullOrEmpty(fp.Formula))
                formulas[Utils.NormalizeString(fp.Definition.Name)] = fp.Formula;
        }

        var cat = doc.OwnerFamily.FamilyCategory;
        var expected = ctx.Get("expected_category");
        if (Py.Truthy(expected))
        {
            var exp = Core.ResolveCategory(doc, expected);
            if (cat == null || cat.Id != exp.Id)
                findings.Add(Rules.Finding("category", "error",
                    $"Family category is '{(cat != null ? cat.Name : "None")}' but '{exp.Name}' was expected",
                    recommendation: "family_properties(category=...)"));
        }
        else if (cat != null && cat.Name == "Generic Models")
        {
            findings.Add(Rules.Finding("category", "info", "Family uses the Generic Models category",
                recommendation: "Use a specific category so it schedules and filters correctly."));
        }

        var known = names.Concat(all.Select(fp => Utils.NormalizeString(fp.Definition.Name))).Cast<string?>().ToList();
        foreach (var issue in Formula.Analyse(formulas, known))
            findings.Add(Rules.Finding("formulas", issue["severity"], $"{Py.Str(issue["parameter"])}: {Py.Str(issue["issue"])}",
                recommendation: "Correct the formula with family_parameters(action='set_formula')."));

        var referenced = new HashSet<string>(StringComparer.Ordinal);
        foreach (var f in formulas.Values)
            referenced.UnionWith(Formula.References((string?)f, relevantNames));
        var unused = new List<string>();
        foreach (var fp in prms)
        {
            var n = Utils.NormalizeString(fp.Definition.Name);
            if (fp.AssociatedParameters.Size == 0 && !Py.Truthy(labels.Get(n)) && string.IsNullOrEmpty(fp.Formula) && !referenced.Contains(n))
                unused.Add(n);
        }
        if (unused.Count > 0)
            findings.Add(Rules.Finding("parameters", "warning",
                $"{unused.Count} parameter(s) drive nothing (no dimension label, association or formula use): {string.Join(", ", unused.Take(15))}",
                recommendation: "Label a dimension, associate it, or remove it if it is pure data.",
                extra: new Dict { ["parameters"] = unused }));
        var pattern = ctx.Get("parameter_naming_pattern");
        if (!Py.Truthy(pattern))
        {
            // core.load_config().get("naming", {}).get("parameters", {}).get("pattern")
            var naming = Core.LoadConfig().Get("naming", new Dict());
            var parameters = FamilyUtils.AsItem(naming).Get("parameters", new Dict());
            pattern = FamilyUtils.AsItem(parameters).Get("pattern");
        }
        if (Py.Truthy(pattern))
            findings.AddRange(Rules.CheckNames(names.Select(n => (0L, (string?)n)), new Dict { ["pattern"] = pattern }, "naming", "parameters"));

        var types = fm.Types.Cast<DB.FamilyType>().ToList();
        if (types.Count == 0)
            findings.Add(Rules.Finding("types", "error", "Family has no types",
                recommendation: "Create at least one type with family_manage_types."));
        var checkDimensionValues = ctx.Bool("check_dimension_values", true);
        foreach (var t in types)
        {
            var missing = relevant.Where(fp => !fp.IsInstance && string.IsNullOrEmpty(fp.Formula) && !fp.IsReporting && !t.HasValue(fp)
                                               && fp.StorageType != DB.StorageType.String)
                .Select(fp => Utils.NormalizeString(fp.Definition.Name)).ToList();
            if (missing.Count > 0)
                findings.Add(Rules.Finding("types", "warning",
                    $"Type '{Utils.NormalizeString(t.Name)}' has no value for: {string.Join(", ", missing.Take(10))}"));
            if (checkDimensionValues)
            {
                foreach (var fp in relevant)
                {
                    if (fp.StorageType == DB.StorageType.Double && t.HasValue(fp))
                    {
                        if (Compat.DefinitionSpec(fp.Definition).kind == "length" && t.AsDouble(fp) <= 0)
                            findings.Add(Rules.Finding("types", "error",
                                $"Type '{Utils.NormalizeString(t.Name)}': {Utils.NormalizeString(fp.Definition.Name)} is zero or negative"));
                    }
                }
            }
        }

        var formList = FamilyUtils.Forms(doc);
        var solids = formList.Where(x => x.f.IsSolid).ToList();
        if (formList.Count == 0)
            findings.Add(Rules.Finding("geometry", "warning", "Family has no solid or void forms"));
        foreach (var (k, f) in formList)
        {
            try
            {
                var bb = f.get_BoundingBox(null);
                if (bb == null || bb.Min.DistanceTo(bb.Max) < 1e-6)
                    findings.Add(Rules.Finding("geometry", "error", $"{k} {Compat.IdInt(f)} has no valid geometry",
                        elementIds: new Lst { Compat.IdInt(f) }));
            }
            catch { /* not measurable */ }
        }
        if (solids.Count > 0 && labels.Count == 0)
            findings.Add(Rules.Finding("constraints", "warning",
                "Geometry exists but no dimension is labelled with a parameter - the family is not parametric",
                recommendation: "Use family_add_dimension with label=... or family_build_parametric_box."));
        try
        {
            var warns = doc.GetWarnings().ToList();
            if (warns.Count > 0)
            {
                var texts = warns.Select(w => Utils.NormalizeString(w.GetDescriptionText())).Distinct()
                    .OrderBy(x => x, StringComparer.Ordinal).Take(5);
                var ids = new Lst();
                foreach (var w in warns)
                    foreach (var i in w.GetFailingElements())
                        ids.Add(Compat.IdInt(i));
                findings.Add(Rules.Finding("warnings", "warning", $"{warns.Count} Revit warning(s): {string.Join("; ", texts)}",
                    elementIds: ids));
            }
        }
        catch { /* warnings are not available */ }

        findings = Rules.SortFindings(findings);
        var summary = Rules.Summarize(findings);
        var bySeverity = (Dict)summary["by_severity"]!;
        summary["passed"] = Py.ToInt(bySeverity.Get("error", 0L)) == 0 && Py.ToInt(bySeverity.Get("critical", 0L)) == 0;
        return new Dict
        {
            ["family"] = FamilyUtils.FamilyName(doc), ["summary"] = summary, ["findings"] = findings,
            ["next_step"] = "Run family_flex_test to verify that geometry follows the parameters.",
        };
    }

    // --------------------------------------------------- save / load / close
    internal static string Backup(string path)
    {
        var folder = Core.RvtssSubdir("backups");
        var stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss", System.Globalization.CultureInfo.InvariantCulture);
        var (root, ext) = PyX.Splitext(PyX.Basename(path));
        var dest = PyX.Join(folder, $"{root}_{stamp}{ext}");
        File.Copy(path, dest, true);
        return dest;
    }

    public static Dict? FamilySave(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireFamily(doc);
        Core.RequireWritable("family_save");
        var savePathValue = ctx.Get("save_path");
        var savePath = Py.Truthy(savePathValue) ? Py.Str(savePathValue) : null;
        string? backup = null;
        var compact = ctx.Bool("compact", false);
        string saved;
        if (savePath != null)
        {
            if (!savePath.ToLowerInvariant().EndsWith(".rfa", StringComparison.Ordinal))
                throw new RvtssError("save_path must end with .rfa");
            if (FamilyUtils.PathExists(savePath))
            {
                if (!ctx.Bool("overwrite", false))
                    throw new RvtssError($"File exists: {savePath}", status: 409,
                        hint: "Pass overwrite=true (the existing file is backed up first).");
                backup = Backup(savePath);
            }
            var folder = FamilyUtils.Dirname(savePath);
            if (folder.Length > 0 && !Directory.Exists(folder))
                Directory.CreateDirectory(folder);
            var opts = new DB.SaveAsOptions
            {
                OverwriteExistingFile = true,
                Compact = compact,
                MaximumBackups = ctx.I("maximum_backups", 3, 1, 99),
            };
            doc.SaveAs(savePath, opts);
            saved = savePath;
        }
        else
        {
            if (string.IsNullOrEmpty(doc.PathName))
                throw new RvtssError("This family has never been saved", status: 409, hint: "Pass save_path (.rfa).");
            if (FamilyUtils.PathExists(doc.PathName) && ctx.Bool("backup", true))
                backup = Backup(doc.PathName);
            var opts = new DB.SaveOptions { Compact = compact };
            doc.Save(opts);
            saved = doc.PathName;
        }
        return new Dict
        {
            ["saved_path"] = saved, ["backup"] = backup, ["document"] = Utils.NormalizeString(doc.Title),
            ["size_kb"] = File.Exists(saved) ? new FileInfo(saved).Length / 1024 : null,
        };
    }

    private sealed class LoadOptions(bool overwriteValues) : DB.IFamilyLoadOptions
    {
        public bool OnFamilyFound(bool familyInUse, out bool overwriteParameterValues)
        {
            overwriteParameterValues = overwriteValues;
            return true;
        }

        public bool OnSharedFamilyFound(DB.Family sharedFamily, bool familyInUse, out DB.FamilySource source,
            out bool overwriteParameterValues)
        {
            source = DB.FamilySource.Family;
            overwriteParameterValues = overwriteValues;
            return true;
        }
    }

    private static DB.Document TargetProject(Ctx ctx, DB.Document famdoc)
    {
        var target = ctx.Get("project");
        DB.Document d;
        if (Py.Truthy(target))
        {
            d = Core.ResolveDocument(ctx.ActiveDoc, target);
        }
        else
        {
            var projects = ctx.App.Documents.Cast<DB.Document>().Where(p => !p.IsFamilyDocument && !p.IsLinked).ToList();
            if (ctx.ActiveDoc != null && !ctx.ActiveDoc.IsFamilyDocument)
                d = ctx.ActiveDoc;
            else if (projects.Count == 1)
                d = projects[0];
            else
                throw new RvtssError("Several projects are open; pass project='<title>'", status: 409)
                    .With("candidates", projects.Select(p => p.Title).ToList());
        }
        Core.RequireProject(d);
        return d;
    }

    public static Dict? FamilyLoadIntoProject(Ctx ctx)
    {
        var famdoc = ctx.Doc;
        Core.RequireFamily(famdoc);
        var project = TargetProject(ctx, famdoc);
        Core.CheckModifiable(project);
        if (project.IsModifiable || famdoc.IsModifiable)
            throw new RvtssError("A transaction is open in one of the documents", status: 409);
        var name = FamilyUtils.FamilyName(famdoc);
        DB.Family? before = null;
        foreach (var f in new DB.FilteredElementCollector(project).OfClass(typeof(DB.Family)))
        {
            if (Utils.NormalizeString(f.Name) == name)
                before = (DB.Family)f;
        }
        if (before != null && !ctx.Bool("overwrite", true))
            throw new RvtssError($"Family '{name}' is already loaded in '{project.Title}'", status: 409,
                hint: "Pass overwrite=true to reload.");
        var overwriteValues = ctx.Bool("overwrite_parameter_values", false);
        DB.Family? fam = famdoc.LoadFamily(project, new LoadOptions(overwriteValues));
        if (fam == null)
        {
            foreach (var f in new DB.FilteredElementCollector(project).OfClass(typeof(DB.Family)))
            {
                if (Utils.NormalizeString(f.Name) == name)
                    fam = (DB.Family)f;
            }
        }
        if (fam == null)
            throw new RvtssError("Revit did not load the family", status: 500);
        var types = fam.GetFamilySymbolIds().Select(s => Utils.NormalizeString(Utils.GetElementName(project.GetElement(s)))).ToList();
        var inst = new DB.FilteredElementCollector(project).OfClass(typeof(DB.FamilyInstance)).Cast<DB.FamilyInstance>()
            .Count(fi => fi.Symbol.Family.Id == fam.Id);
        var familyTypesInDoc = famdoc.FamilyManager.Types.Cast<DB.FamilyType>().Select(t => Utils.NormalizeString(t.Name)).ToList();
        var missing = familyTypesInDoc.Where(t => !types.Contains(t)).ToList();
        return new Dict
        {
            ["project"] = Utils.NormalizeString(project.Title), ["family"] = name, ["family_id"] = Compat.IdInt(fam),
            ["action"] = before != null ? "reloaded" : "loaded", ["types_in_project"] = types,
            ["instances_in_project"] = (long)inst, ["overwrite_parameter_values"] = overwriteValues,
            ["verified"] = missing.Count == 0, ["types_missing_in_project"] = missing,
        };
    }

    public static Dict? FamilyClose(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireFamily(doc);
        if (ctx.ActiveDoc != null && doc.Equals(ctx.ActiveDoc))
            throw new RvtssError("The active document cannot be closed through the API", status: 409,
                hint: "Switch Revit to another document, or use close_document for the active one.");
        var save = ctx.Bool("save", false);
        if (doc.IsModified && !save && !ctx.Bool("discard_changes", false))
            throw new RvtssError($"Family '{doc.Title}' has unsaved changes", status: 409,
                hint: "Pass save=true, or discard_changes=true to close without saving.");
        if (save && string.IsNullOrEmpty(doc.PathName))
            throw new RvtssError("Family was never saved; use family_save with save_path first", status: 409);
        var title = Utils.NormalizeString(doc.Title);
        if (save)
            Core.RequireWritable("family_close(save=true)");
        if (save && !string.IsNullOrEmpty(doc.PathName) && FamilyUtils.PathExists(doc.PathName))
            Backup(doc.PathName);
        doc.Close(save);
        return new Dict { ["closed"] = title, ["saved"] = save };
    }
}
