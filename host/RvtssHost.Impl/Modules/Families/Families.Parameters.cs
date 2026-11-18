namespace RvtssHost.Modules;

public static partial class Families
{
    // ------------------------------------------------------------ parameters
    private static DB.ExternalDefinition SharedDefinition(Ctx ctx, object? name, object? guid = null)
    {
        var app = ctx.App;
        var pathValue = ctx.Get("shared_parameter_file");
        var path = Py.Truthy(pathValue) ? Py.Str(pathValue) : null;
        var previous = app.SharedParametersFilename;
        try
        {
            if (path != null)
                app.SharedParametersFilename = path;
            var dfile = app.OpenSharedParameterFile();
            if (dfile == null)
                throw new RvtssError("No shared parameter file is set in Revit", status: 409,
                    hint: "Pass shared_parameter_file, or create definitions with shared_parameters.");
            var hasGuid = Py.Truthy(guid);
            var guidLow = hasGuid ? Py.Str(guid).ToLowerInvariant() : "";
            foreach (DB.DefinitionGroup g in dfile.Groups)
            {
                foreach (DB.Definition d in g.Definitions)
                {
                    if (d is not DB.ExternalDefinition ext)
                        continue;
                    if (hasGuid && ext.GUID.ToString().ToLowerInvariant() == guidLow)
                        return ext;
                    if (!hasGuid && name is string wanted && Utils.NormalizeString(ext.Name) == wanted)
                        return ext;
                }
            }
            throw new RvtssError($"Shared parameter '{Py.Str(hasGuid ? guid : name)}' not found in {app.SharedParametersFilename}",
                status: 404, hint: "Create it first with shared_parameters(action='create_definitions').");
        }
        finally
        {
            if (path != null && (previous ?? "") != path)
                app.SharedParametersFilename = previous ?? "";
        }
    }

    private static readonly string[] ParameterActions =
    {
        "add", "associate", "remove", "rename", "replace_with_shared", "set_formula", "set_instance", "set_reporting", "set_values",
    };

    public static Dict? FamilyParameters(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var actionValue = ctx.Require("action");
        var action = actionValue as string;
        var dry = ctx.DryRun;
        var items = ctx.List("parameters");
        if (action == "list")
        {
            var labels = FamilyUtils.LabeledDimensions(doc);
            return new Dict
            {
                ["parameters"] = fm.Parameters.Cast<DB.FamilyParameter>()
                    .Select(fp => FamilyUtils.FamilyParamInfo(doc, fm, fp, ctx.Unit, labels)).ToList(),
            };
        }
        if (items.Count == 0)
            throw new RvtssError($"'parameters' list is required for action '{Py.Str(actionValue)}'");
        var atomic = ctx.Bool("atomic", true);
        var naming = ctx.Get("naming_pattern");

        Dict? Add(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var name = item.Get("name");
            if (!Py.Truthy(name))
                throw new RvtssError("Parameter needs a name");
            var nameText = Py.Str(name);
            if (Py.Truthy(naming))
            {
                var issues = Rules.CheckNames(new[] { (0L, (string?)nameText) }, new Dict { ["pattern"] = naming }, "naming", "parameter");
                if (issues.Count > 0)
                    throw new RvtssError($"'{nameText}' violates naming pattern {Py.Str(naming)}");
            }
            var existing = ParamsUtil.FamilyParameter(fm, name);
            if (existing != null)
            {
                if (item.Get("if_exists", "skip") is string ifExists && ifExists == "error")
                    throw new RvtssError($"Parameter '{nameText}' already exists", status: 409);
                return new Dict { ["name"] = name, ["action"] = "exists", ["id"] = Compat.IdInt(existing.Id) };
            }
            var instance = Py.Truthy(item.Get("instance", false));
            var ptype = item.Get("type", "length");
            var ptypeText = ptype as string;
            var group = item.Get("group");
            if (!Py.Truthy(group))
                group = ptypeText == "length" || ptypeText == "angle" || ptypeText == "area" || ptypeText == "volume" ? "dimensions"
                    : ptypeText == "material" ? "materials" : "data";
            DB.FamilyParameter fp;
            if (Py.Truthy(item.Get("shared")))
                fp = Compat.AddSharedFamilyParameter(fm, SharedDefinition(ctx, name, item.Get("guid")), group, instance);
            else
                fp = Compat.AddFamilyParameter(fm, nameText, ptype, group, instance);
            var o = new Dict { ["name"] = name, ["action"] = "added", ["id"] = Compat.IdInt(fp.Id), ["instance"] = instance };
            if (item.Get("value") != null && !Py.Truthy(item.Get("formula")))
            {
                FamilyUtils.EnsureCurrentType(fm);
                ParamsUtil.SetFamilyValue(doc, fm, fp, item["value"], FamilyUtils.UnitOf(item.Get("unit")));
                o["value_set"] = true;
            }
            // formulas are applied in a second pass so they may reference
            // parameters added later in the same batch
            if (Py.Truthy(item.Get("reporting")))
            {
                fm.MakeReporting(fp);
                o["reporting"] = true;
            }
            return o;
        }

        Dict? Remove(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            if (FamilyUtils.IsBuiltin(fp))
                throw new RvtssError($"Built-in parameter '{Py.Str(item.Get("name"))}' cannot be removed", status: 409);
            fm.RemoveParameter(fp);
            return new Dict { ["name"] = item.Get("name"), ["action"] = "removed" };
        }

        Dict? Rename(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            if (fp.IsShared)
                throw new RvtssError($"Shared parameter '{Py.Str(item.Get("name"))}' cannot be renamed (its name belongs to the GUID)",
                    status: 409, hint: "Use replace_with_shared to swap it for another shared definition.");
            var newName = FamilyUtils.Req(item, "new_name");
            fm.RenameParameter(fp, newName as string ?? (newName == null ? null : Py.Str(newName)));
            return new Dict { ["name"] = newName, ["old_name"] = item.Get("name"), ["action"] = "renamed" };
        }

        Dict? SetFormula(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            var f = item.Get("formula");
            if (Py.Truthy(f))
            {
                if (!fp.CanAssignFormula)
                    throw new RvtssError($"A formula cannot be assigned to '{Py.Str(item.Get("name"))}' (e.g. instance-driven by type, reporting)",
                        status: 409);
                fm.SetFormula(fp, Py.Str(f));
            }
            else
            {
                fm.SetFormula(fp, null);
            }
            return new Dict
            {
                ["name"] = item.Get("name"), ["action"] = Py.Truthy(f) ? "formula_set" : "formula_cleared",
                ["formula"] = Py.Truthy(f) ? f : null,
            };
        }

        Dict? InstanceType(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            var instance = Py.Truthy(item.Get("instance"));
            if (instance)
                fm.MakeInstance(fp);
            else
                fm.MakeType(fp);
            return new Dict { ["name"] = item.Get("name"), ["action"] = instance ? "made_instance" : "made_type" };
        }

        Dict? Reporting(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            var reporting = Py.Truthy(item.Get("reporting", true));
            if (reporting)
                fm.MakeReporting(fp);
            else
                fm.MakeNonReporting(fp);
            return new Dict { ["name"] = item.Get("name"), ["action"] = reporting ? "reporting" : "non_reporting" };
        }

        Dict? ReplaceShared(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            var ext = SharedDefinition(ctx, Py.Truthy(item.Get("shared_name")) ? item.Get("shared_name") : item.Get("name"), item.Get("guid"));
            var replaced = fm.ReplaceParameter(fp, ext, Compat.GroupId(item.Get("group", "data")),
                Py.Truthy(item.Get("instance", fp.IsInstance)));
            return new Dict
            {
                ["name"] = Utils.NormalizeString(replaced.Definition.Name), ["action"] = "replaced_with_shared",
                ["guid"] = replaced.GUID.ToString(),
            };
        }

        Dict? Associate(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            var e = Core.GetElement(doc, item.Get("element_id"));
            var ep = ParamsUtil.Lookup(e, item.Get("element_parameter"));
            if (ep == null)
                throw new RvtssError($"Element {Py.Str(item.Get("element_id"))} has no parameter '{Py.Str(item.Get("element_parameter"))}'",
                    status: 404);
            var fp = Py.Truthy(item.Get("name")) ? ParamsUtil.RequireFamilyParameter(fm, item.Get("name")) : null;
            if (fp != null && !fm.CanElementParameterBeAssociated(ep))
                throw new RvtssError($"Parameter '{Py.Str(item.Get("element_parameter"))}' of element {Py.Str(item.Get("element_id"))} cannot be associated",
                    status: 409);
            fm.AssociateElementParameterToFamilyParameter(ep, fp);
            return new Dict
            {
                ["element_id"] = item.Get("element_id"), ["element_parameter"] = item.Get("element_parameter"),
                ["family_parameter"] = item.Get("name"), ["action"] = fp != null ? "associated" : "dissociated",
            };
        }

        Dict? SetValues(object? raw)
        {
            var item = FamilyUtils.AsItem(raw);
            FamilyUtils.EnsureCurrentType(fm);
            var fp = ParamsUtil.RequireFamilyParameter(fm, item.Get("name"));
            ParamsUtil.SetFamilyValue(doc, fm, fp, item.Get("value"), FamilyUtils.UnitOf(item.Get("unit")));
            return new Dict
            {
                ["name"] = item.Get("name"), ["action"] = "value_set",
                ["value"] = ParamsUtil.FamilyTypeValue(fm, fm.CurrentType, fp, ctx.Unit),
            };
        }

        Func<object?, Dict?>? fn = action switch
        {
            "add" => Add,
            "remove" => Remove,
            "rename" => Rename,
            "set_formula" => SetFormula,
            "set_instance" => InstanceType,
            "set_reporting" => Reporting,
            "replace_with_shared" => ReplaceShared,
            "associate" => Associate,
            "set_values" => SetValues,
            _ => null,
        };
        if (fn == null)
            throw new RvtssError("action must be one of: list, " + string.Join(", ", ParameterActions));

        if (action == "add" || action == "set_formula")
        {
            // formula static pre-check across the whole family
            var dicts = items.Select(FamilyUtils.AsItem).ToList();
            var known = fm.Parameters.Cast<DB.FamilyParameter>().Select(fp => (string?)Utils.NormalizeString(fp.Definition.Name))
                .Concat(dicts.Select(i => i.Get("name") as string)).ToList();
            var formulas = new Dict();
            foreach (DB.FamilyParameter fp in fm.Parameters)
            {
                if (!string.IsNullOrEmpty(fp.Formula))
                    formulas[Utils.NormalizeString(fp.Definition.Name)] = fp.Formula;
            }
            foreach (var i in dicts)
            {
                if (Py.Truthy(i.Get("formula")))
                    formulas[Py.Str(FamilyUtils.Req(i, "name"))] = i["formula"];
            }
            var pre = Formula.Analyse(formulas, known).Where(x => x["severity"] is string sev && sev == "error").ToList();
            if (pre.Count > 0)
                throw new RvtssError("Formula pre-check failed: " + string.Join("; ", pre.Take(5).Select(x => Py.Str(x["issue"]))),
                    hint: "Nothing was changed. Fix the formulas and retry.").With("issues", pre);
        }

        var (results, fails) = Core.RunTransaction(doc, "Family parameters: " + action, () =>
        {
            var res = Core.Batch(doc, items, fn, atomic);
            if (action == "add")
            {
                for (var k = 0; k < res.Count && k < items.Count; k++)
                {
                    var r = (Dict)res[k]!;
                    var item = FamilyUtils.AsItem(items[k]);
                    if (!Py.Truthy(r.Get("ok")) || !Py.Truthy(item.Get("formula")) || (r.Get("action") is string act && act == "exists"))
                        continue;
                    var fp = ParamsUtil.RequireFamilyParameter(fm, item["name"]);
                    try
                    {
                        fm.SetFormula(fp, Py.Str(item["formula"]));
                        r["formula"] = item["formula"];
                    }
                    catch (Exception e)
                    {
                        if (atomic)
                            throw new RvtssError($"Formula for '{Py.Str(item["name"])}' rejected by Revit: {FamilyUtils.ErrText(e)}",
                                hint: "Nothing was changed. Check parameter names, units and result type.");
                        r.Update(new Dict { ["ok"] = false, ["error"] = "formula rejected: " + FamilyUtils.ErrText(e) });
                    }
                }
            }
            doc.Regenerate();
            return res;
        }, dryRun: dry);
        return Core.CommitResult(new Dict { ["action"] = action, ["results"] = results }, fails, dry);
    }

    // ----------------------------------------------------------------- types
    private static (Lst applied, Lst errors) ApplyTypeValues(DB.Document doc, DB.FamilyManager fm, object? values, object? unit)
    {
        var applied = new Lst();
        var errors = new Lst();
        var map = Py.Truthy(values) ? FamilyUtils.AsItem(values) : new Dict();
        foreach (var (pname, val) in map)
        {
            var fp = ParamsUtil.FamilyParameter(fm, pname);
            if (fp == null)
            {
                errors.Add(new Dict { ["parameter"] = pname, ["error"] = "not found" });
                continue;
            }
            var (v, u) = val is Dict vd ? (vd.Get("value"), vd.Get("unit", unit)) : (val, unit);
            try
            {
                ParamsUtil.SetFamilyValue(doc, fm, fp, v, FamilyUtils.UnitOf(u));
                applied.Add(pname);
            }
            catch (RvtssError e)
            {
                errors.Add(new Dict { ["parameter"] = pname, ["error"] = e.Message });
            }
            catch (Exception e)
            {
                errors.Add(new Dict { ["parameter"] = pname, ["error"] = FamilyUtils.ErrText(e) });
            }
        }
        return (applied, errors);
    }

    public static Dict? FamilyTypes(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var actionValue = ctx.Get("action", "list");
        var action = actionValue as string;
        var unit = ctx.Unit;
        var dry = ctx.DryRun;
        if (action == "list")
        {
            var includeBuiltin = ctx.Bool("include_builtin", false);
            var names = fm.Parameters.Cast<DB.FamilyParameter>().Where(fp => FamilyUtils.IsRelevant(fp, includeBuiltin)).ToList();
            var only = new HashSet<string>(ctx.List("parameters").OfType<string>(), StringComparer.Ordinal);
            var filtered = ctx.List("parameters").Count > 0;
            var types = new List<Dict>();
            foreach (DB.FamilyType t in fm.Types)
            {
                var vals = new Dict();
                foreach (var fp in names)
                {
                    var n = Utils.NormalizeString(fp.Definition.Name);
                    if (filtered && !only.Contains(n))
                        continue;
                    vals[n] = ParamsUtil.FamilyTypeValue(fm, t, fp, unit);
                }
                types.Add(new Dict { ["name"] = Utils.NormalizeString(t.Name), ["values"] = vals });
            }
            return new Dict
            {
                ["unit"] = unit, ["current_type"] = fm.CurrentType != null ? Utils.NormalizeString(fm.CurrentType.Name) : null,
                ["types"] = types,
            };
        }
        if (action == "export_catalog")
            return ExportCatalog(ctx, doc, fm);
        var items = ctx.List("types");
        if (action == "import_catalog")
        {
            items = CatalogItems(ctx);
            action = "upsert";
        }
        if (items.Count == 0)
            throw new RvtssError("'types' list is required, e.g. [{name: 'W900', values: {Width: 900}}]");
        var strict = ctx.Bool("strict", true);

        var (res, fails) = Core.RunTransaction(doc, "Family types: " + (action ?? Py.Str(actionValue)), () =>
        {
            var results = new Lst();
            foreach (var raw in items)
            {
                var it = FamilyUtils.AsItem(raw);
                var name = it.Get("name");
                if (action == "create" || action == "upsert")
                {
                    DB.FamilyType? exists = null;
                    foreach (DB.FamilyType t in fm.Types)
                    {
                        if (name is string wanted && Utils.NormalizeString(t.Name) == wanted)
                            exists = t;
                    }
                    if (exists != null && action == "create")
                        throw new RvtssError($"Type '{Py.Str(name)}' already exists", status: 409,
                            hint: "Use action='set_values' or 'upsert'.");
                    if (exists != null)
                    {
                        fm.CurrentType = exists;
                    }
                    else
                    {
                        if (Py.Truthy(it.Get("based_on")))
                            fm.CurrentType = FamilyUtils.FindFamilyType(fm, it["based_on"]);
                        fm.NewType(TypeName(name));
                    }
                    var (applied, errors) = ApplyTypeValues(doc, fm, it.Get("values"), it.Get("unit", unit));
                    results.Add(new Dict
                    {
                        ["name"] = name, ["action"] = exists != null ? "updated" : "created",
                        ["values_set"] = applied, ["errors"] = errors,
                    });
                }
                else if (action == "duplicate")
                {
                    var source = Py.Truthy(it.Get("source")) ? it.Get("source") : name;
                    fm.CurrentType = FamilyUtils.FindFamilyType(fm, source);
                    var newName = FamilyUtils.Req(it, "new_name");
                    fm.NewType(TypeName(newName));
                    var (applied, errors) = ApplyTypeValues(doc, fm, it.Get("values"), it.Get("unit", unit));
                    results.Add(new Dict
                    {
                        ["name"] = newName, ["action"] = "duplicated", ["source"] = source,
                        ["values_set"] = applied, ["errors"] = errors,
                    });
                }
                else if (action == "rename")
                {
                    fm.CurrentType = FamilyUtils.FindFamilyType(fm, name);
                    var newName = FamilyUtils.Req(it, "new_name");
                    fm.RenameCurrentType(TypeName(newName));
                    results.Add(new Dict { ["name"] = newName, ["old_name"] = name, ["action"] = "renamed" });
                }
                else if (action == "delete")
                {
                    if (fm.Types.Size <= 1)
                        throw new RvtssError("Cannot delete the last family type", status: 409);
                    fm.CurrentType = FamilyUtils.FindFamilyType(fm, name);
                    fm.DeleteCurrentType();
                    results.Add(new Dict { ["name"] = name, ["action"] = "deleted" });
                }
                else if (action == "set_values")
                {
                    fm.CurrentType = FamilyUtils.FindFamilyType(fm, name);
                    var (applied, errors) = ApplyTypeValues(doc, fm, it.Get("values"), it.Get("unit", unit));
                    results.Add(new Dict { ["name"] = name, ["action"] = "values_set", ["values_set"] = applied, ["errors"] = errors });
                }
                else
                {
                    throw new RvtssError("action must be list, create, upsert, duplicate, rename, delete, set_values, "
                                         + "export_catalog or import_catalog");
                }
                doc.Regenerate();
            }
            var errs = new Lst();
            foreach (Dict? r in results)
                errs.AddRange(PyX.Items(r!.Get("errors")));
            if (strict && errs.Count > 0)
                throw new RvtssError($"Some values could not be set: {PyX.Repr(errs.Take(5).ToList())}", status: 409,
                    hint: "Nothing was changed (strict=true). Fix the values or pass strict=false.").With("results", results);
            return new Dict { ["results"] = results };
        }, dryRun: dry);
        var o = Core.CommitResult(res, fails, dry);
        o["types_now"] = fm.Types.Cast<DB.FamilyType>().Select(t => Utils.NormalizeString(t.Name)).ToList();
        return o;
    }

    /// <summary>A request value as the type name Revit gets (null stays null and is rejected by Revit).</summary>
    private static string? TypeName(object? name) => name == null ? null : name as string ?? Py.Str(name);

    private static List<(DB.FamilyParameter fp, Dict c)> CatalogColumns(DB.FamilyManager fm)
    {
        var cols = new List<(DB.FamilyParameter fp, Dict c)>();
        foreach (DB.FamilyParameter fp in fm.Parameters)
        {
            if (fp.IsInstance || fp.IsReporting || !string.IsNullOrEmpty(fp.Formula) || !FamilyUtils.IsRelevant(fp))
                continue;
            var (spec, kind) = Compat.DefinitionSpec(fp.Definition);
            cols.Add((fp, new Dict
            {
                ["name"] = Utils.NormalizeString(fp.Definition.Name), ["spec"] = spec,
                ["unit"] = kind switch { "length" => "mm", "area" => "m2", "volume" => "m3", "angle" => "deg", _ => null },
            }));
        }
        return cols;
    }

    private static Dict ExportCatalog(Ctx ctx, DB.Document doc, DB.FamilyManager fm)
    {
        var cols = CatalogColumns(fm);
        var types = new List<Dict>();
        foreach (DB.FamilyType t in fm.Types)
        {
            var vals = new Dict();
            foreach (var (fp, c) in cols)
            {
                if (!t.HasValue(fp))
                    continue;
                var cname = (string)c["name"]!;
                if (fp.StorageType == DB.StorageType.ElementId)
                {
                    var e = doc.GetElement(t.AsElementId(fp));
                    vals[cname] = e != null ? Utils.NormalizeString(e.Name) : "";
                }
                else if (c["unit"] is string cunit)
                {
                    vals[cname] = Units.FromInternal(t.AsDouble(fp)!.Value, cunit, 4);
                }
                else
                {
                    var v = ParamsUtil.FamilyTypeValue(fm, t, fp, "mm");
                    vals[cname] = v is bool flag ? (flag ? 1L : 0L) : v;
                }
            }
            types.Add(new Dict { ["name"] = Utils.NormalizeString(t.Name), ["values"] = vals });
        }
        var columns = cols.Select(x => x.c).ToList();
        var text = Catalog.Write(columns, types);
        var pathValue = ctx.Get("path");
        var path = Py.Truthy(pathValue) ? Py.Str(pathValue) : null;
        if (path == null && !string.IsNullOrEmpty(doc.PathName))
            path = PyX.Splitext(doc.PathName).root + ".txt";
        string? written = null;
        if (path != null && ctx.Bool("write", true))
        {
            if (FamilyUtils.PathExists(path) && !ctx.Bool("overwrite", false))
                throw new RvtssError($"Catalog exists: {path}", status: 409, hint: "Pass overwrite=true.");
            // io.open(path, "w", encoding="utf-16"): BOM, little endian, "\n" written as the platform line end
            File.WriteAllText(path, text.Replace("\n", "\r\n"), new UnicodeEncoding(false, true));
            written = path;
        }
        return new Dict
        {
            ["path"] = written, ["columns"] = columns, ["type_count"] = (long)types.Count,
            ["preview"] = text.Length < 6000 ? text : text.Substring(0, 6000) + "...",
        };
    }

    private static Lst CatalogItems(Ctx ctx)
    {
        var textValue = ctx.Get("catalog_text");
        var pathValue = ctx.Get("path");
        var text = Py.Truthy(textValue) ? Py.Str(textValue) : null;
        if (text == null)
        {
            var path = Py.Truthy(pathValue) ? Py.Str(pathValue) : null;
            if (path == null || !File.Exists(path))
                throw new RvtssError("Pass catalog_text or an existing catalog path");
            text = Sharedparams.ReadText(path);
        }
        Dict parsed;
        try
        {
            parsed = Catalog.Parse(text);
        }
        catch (CatalogError e)
        {
            throw new RvtssError($"Invalid type catalog: {e.Message}");
        }
        var items = new Lst();
        foreach (var t in PyX.Items(parsed["types"]).Cast<Dict>())
        {
            var vals = new Dict();
            foreach (var (pname, raw) in (Dict)t["values"]!)
            {
                var v = (Dict)raw!;
                if (Py.Truthy(v["unit"]))
                    vals[pname] = new Dict { ["value"] = Py.ToFloat(v["value"]), ["unit"] = v["unit"] };
                else
                    vals[pname] = new Dict { ["value"] = v["value"], ["unit"] = null };
            }
            items.Add(new Dict { ["name"] = t["name"], ["values"] = vals });
        }
        return items;
    }

    // ---------------------------------------------------------------- nested
    public static Dict? FamilyNested(Ctx ctx)
    {
        var doc = ctx.Doc;
        var fm = Core.RequireFamily(doc);
        var action = ctx.Require("action") as string;
        var dry = ctx.DryRun;
        if (action == "load")
        {
            var path = Py.Str(ctx.Require("path"));
            if (!File.Exists(path))
                throw new RvtssError($"File not found: {path}", status: 404);
            var baseName = PyX.Splitext(PyX.Basename(path)).root;

            var (res, fails) = Core.RunTransaction(doc, "Load nested family", () =>
            {
                var loaded = doc.LoadFamily(path);
                DB.Family? fam = null;
                foreach (var f in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Family)))
                {
                    if (Utils.NormalizeString(f.Name) == baseName)
                        fam = (DB.Family)f;
                }
                if (fam == null)
                    throw new RvtssError($"Family {baseName} did not load (it may already be loaded or be incompatible)",
                        status: 409);
                return new Dict
                {
                    ["family"] = baseName, ["family_id"] = Compat.IdInt(fam), ["newly_loaded"] = loaded,
                    ["types"] = fam.GetFamilySymbolIds().Select(s => Utils.NormalizeString(Utils.GetElementName(doc.GetElement(s)))).ToList(),
                };
            }, dryRun: dry);
            return Core.CommitResult(res, fails, dry);
        }
        if (action == "place")
        {
            var sym = (DB.FamilySymbol)Core.FindType(doc, family: ctx.Require("family"), typeName: ctx.Get("type"),
                ofClass: typeof(DB.FamilySymbol));
            var pointValue = ctx.Get("point");
            var (x, y, z) = Units.PointFrom(Py.Truthy(pointValue) ? pointValue : new Lst { 0L, 0L, 0L }, ctx.Unit);

            var (res, fails) = Core.RunTransaction(doc, "Place nested family", () =>
            {
                if (!sym.IsActive)
                {
                    sym.Activate();
                    doc.Regenerate();
                }
                var inst = doc.FamilyCreate.NewFamilyInstance(new DB.XYZ(x, y, z), sym, DB.Structure.StructuralType.NonStructural);
                var assoc = new Lst();
                var associateValue = ctx.Get("associate");
                var associate = Py.Truthy(associateValue) ? FamilyUtils.AsItem(associateValue) : new Dict();
                foreach (var (epName, fpName) in associate)
                {
                    var ep = ParamsUtil.Lookup(inst, epName) ?? ParamsUtil.Lookup(sym, epName);
                    if (ep == null)
                        throw new RvtssError($"Nested family has no parameter '{epName}'", status: 404);
                    fm.AssociateElementParameterToFamilyParameter(ep, ParamsUtil.RequireFamilyParameter(fm, fpName));
                    assoc.Add(new Dict { ["nested_parameter"] = epName, ["family_parameter"] = fpName });
                }
                return new Dict { ["instance_id"] = Compat.IdInt(inst), ["associations"] = assoc };
            }, dryRun: dry);
            return Core.CommitResult(res, fails, dry);
        }
        throw new RvtssError("action must be load or place (use family_parameters action=associate for more links)");
    }
}
