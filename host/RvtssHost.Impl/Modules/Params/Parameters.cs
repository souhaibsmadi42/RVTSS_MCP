namespace RvtssHost.Modules;

/// <summary>
/// Project / shared / global parameter management (RVTSS): port of revit_mcp/parameters.py.
///
/// Routes:
///     POST /parameters/project/   list project parameter bindings (categories, instance/type, shared GUID)
///     POST /parameters/shared/    read_file | create_definitions | bind | create_file
///     POST /parameters/global/    list | create | set_value | set_formula | associate | dissociate |
///                                 label_dimensions | unlabel_dimensions
///     POST /parameters/audit/     missing / empty / invalid values, wrong data types, duplicate definitions
///     POST /parameters/export/    element parameter values to CSV
///     POST /parameters/import/    CSV (ElementId column) back into the model
///     POST /parameters/map/       copy values between parameters (naming-standard migrations)
///
/// API limits respected: existing shared parameter GUIDs are never rewritten; a
/// definition name already present in the file is reused, not duplicated;
/// project parameters are created from shared definitions (the reliable cross-
/// version path); bound parameters are extended with ReInsert, never replaced.
/// </summary>
public static partial class Parameters
{
    /// <summary>register_parameter_routes</summary>
    public static void Register(RouteTable api)
    {
        api.Post("/parameters/project/", ProjectParameters, "project_parameters");
        api.Post("/parameters/shared/", SharedParameters, "shared_parameters", needsDoc: false);
        api.Post("/parameters/global/", GlobalParameters, "global_parameters");
        api.Post("/parameters/audit/", Audit, "audit");
        api.Post("/parameters/export/", ExportValues, "export_values");
        api.Post("/parameters/import/", ImportValues, "import_values");
        api.Post("/parameters/map/", MapValues, "map_values");
    }

    /// <summary>(value or "").lower()</summary>
    private static string LowerOf(object? value) => Py.Truthy(value) ? Py.Str(value).ToLowerInvariant() : "";

    // ------------------------------------------------------------------- project
    internal static List<(DB.Definition d, DB.ElementBinding b, Dict entry)> Bindings(DB.Document doc)
    {
        var result = new List<(DB.Definition d, DB.ElementBinding b, Dict entry)>();
        var it = doc.ParameterBindings.ForwardIterator();
        it.Reset();
        while (it.MoveNext())
        {
            var d = it.Key;
            var b = (DB.ElementBinding)it.Current;
            var cats = new List<string>();
            foreach (DB.Category c in b.Categories)
                cats.Add(Utils.NormalizeString(c.Name));
            cats.Sort(StringComparer.Ordinal);
            var (spec, _) = Compat.DefinitionSpec(d);
            var entry = new Dict
            {
                ["name"] = Utils.NormalizeString(d.Name),
                ["binding"] = b is DB.InstanceBinding ? "instance" : "type",
                ["categories"] = cats,
                ["spec"] = spec,
                ["group"] = Compat.DefinitionGroup(d),
            };
            try
            {
                var did = ((DB.InternalDefinition)d).Id;
                var pe = doc.GetElement(did);
                if (pe is DB.SharedParameterElement spe)
                {
                    entry["shared"] = true;
                    entry["guid"] = spe.GuidValue.ToString();
                }
                else
                {
                    entry["shared"] = false;
                }
                entry["id"] = Compat.IdInt(did);
            }
            catch { /* no element behind the definition */ }
            try { entry["vary_between_groups"] = ((DB.InternalDefinition)d).VariesAcrossGroups; }
            catch { /* not an internal definition */ }
            result.Add((d, b, entry));
        }
        return result;
    }

    public static Dict? ProjectParameters(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var contains = LowerOf(ctx.Get("contains"));
        var items = Bindings(doc).Select(t => t.entry)
            .Where(e => contains.Length == 0 || ((string)e["name"]!).ToLowerInvariant().Contains(contains))
            .OrderBy(e => ((string)e["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
        var order = new List<string>();
        var names = new Dictionary<string, List<Dict>>(StringComparer.Ordinal);
        foreach (var e in items)
        {
            var key = ((string)e["name"]!).ToLowerInvariant();
            if (!names.TryGetValue(key, out var list))
            {
                names[key] = list = new List<Dict>();
                order.Add(key);
            }
            list.Add(e);
        }
        var dups = new List<string>();
        foreach (var key in order)
            if (names[key].Count > 1)
                dups.Add((string)names[key][0]["name"]!);
        return new Dict { ["count"] = (long)items.Count, ["parameters"] = items, ["duplicate_names"] = dups };
    }

    // -------------------------------------------------------------------- shared
    /// <summary>Temporarily point Revit at a shared parameter file and restore afterwards
    /// (Python class _SharedFile; call Enter() for __enter__, Dispose() is __exit__).</summary>
    internal sealed class SharedFile : IDisposable
    {
        private readonly Autodesk.Revit.ApplicationServices.Application _app;
        private readonly string? _path;
        private readonly bool _create;
        private string? _previous;
        private bool _entered;

        public SharedFile(Autodesk.Revit.ApplicationServices.Application app, string? path = null, bool create = false)
        {
            _app = app;
            _path = string.IsNullOrEmpty(path) ? null : path;
            _create = create;
        }

        public DB.DefinitionFile Enter()
        {
            _previous = _app.SharedParametersFilename;
            _entered = true;
            if (_path != null)
            {
                if (!File.Exists(_path))
                {
                    if (!_create)
                        throw new RvtssError($"Shared parameter file not found: {_path}", status: 404,
                            hint: "Pass create_file=true to create it.");
                    var folder = Path.GetDirectoryName(_path);
                    if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder))
                        Directory.CreateDirectory(folder);
                    File.WriteAllBytes(_path, new byte[0]);
                }
                _app.SharedParametersFilename = _path;
            }
            var dfile = _app.OpenSharedParameterFile();
            if (dfile == null)
                throw new RvtssError("No shared parameter file is configured in Revit", status: 409,
                    hint: "Pass shared_parameter_file (and create_file=true for a new one).");
            return dfile;
        }

        public void Dispose()
        {
            // restore even when no file was configured before (previous None/""), otherwise
            // Revit would keep pointing at the temporary file
            if (_entered && _path != null && (_previous ?? "") != _path)
            {
                try { _app.SharedParametersFilename = _previous ?? ""; }
                catch { /* best effort */ }
            }
        }
    }

    private static IEnumerable<(DB.DefinitionGroup g, DB.Definition d)> AllDefinitions(DB.DefinitionFile dfile)
    {
        foreach (DB.DefinitionGroup g in dfile.Groups)
            foreach (DB.Definition d in g.Definitions)
                yield return (g, d);
    }

    private static string DefinitionGuid(DB.Definition d) => ((DB.ExternalDefinition)d).GUID.ToString();

    private static (DB.DefinitionGroup? g, DB.Definition? d) FindDefinition(DB.DefinitionFile dfile, object? name = null, object? guid = null)
    {
        if (Py.Truthy(guid))
        {
            var wanted = Py.Str(guid).ToLowerInvariant();
            foreach (var (g, d) in AllDefinitions(dfile))
                if (DefinitionGuid(d).ToLowerInvariant() == wanted)
                    return (g, d);
        }
        if (Py.Truthy(name))
        {
            foreach (var (g, d) in AllDefinitions(dfile))
                if (name is string ns && Utils.NormalizeString(d.Name) == ns)
                    return (g, d);
        }
        return (null, null);
    }

    /// <summary>{lower-case guid: parameter name} of the shared parameters in the project.</summary>
    private static Dictionary<string, string> ProjectSharedGuids(DB.Document doc)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var el in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.SharedParameterElement)))
        {
            try
            {
                var spe = (DB.SharedParameterElement)el;
                result[spe.GuidValue.ToString().ToLowerInvariant()] = Utils.NormalizeString(spe.GetDefinition().Name);
            }
            catch { continue; }
        }
        return result;
    }

    /// <summary>`ctx.get(key)` used as a path: null when empty.</summary>
    private static string? OptionalPath(Ctx ctx, string key)
    {
        var v = ctx.Get(key);
        return Py.Truthy(v) ? Py.Str(v) : null;
    }

    private static Dict ReadFile(Ctx ctx)
    {
        var given = OptionalPath(ctx, "shared_parameter_file");
        var path = given ?? ctx.App.SharedParametersFilename;
        if (string.IsNullOrEmpty(path))
            throw new RvtssError("No shared parameter file configured", status: 404,
                hint: "Pass shared_parameter_file or set one in Manage > Shared Parameters.");
        if (!File.Exists(path))
            throw new RvtssError($"Shared parameter file not found: {path}", status: 404);
        var parsed = Sharedparams.ParseFile(path);
        var inProject = new Dictionary<string, string>(StringComparer.Ordinal);
        if (ctx.Doc != null && !ctx.Doc.IsFamilyDocument)
            inProject = ProjectSharedGuids(ctx.Doc);
        var contains = LowerOf(ctx.Get("contains"));
        var parsedParams = (List<Dict>)parsed["params"]!;
        var issues = (List<Dict>)parsed["issues"]!;
        var prms = new Lst();
        foreach (var p in parsedParams)
        {
            if (contains.Length > 0 && !((string)p["name"]!).ToLowerInvariant().Contains(contains))
                continue;
            var q = new Dict();
            foreach (var k in new[] { "name", "guid", "datatype", "group", "description", "visible" })
                q[k] = p[k];
            if (inProject.Count > 0)
                q["in_project"] = inProject.ContainsKey(((string)p["guid"]!).ToLowerInvariant());
            prms.Add(q);
        }
        foreach (var kv in inProject)
        {
            foreach (var p in parsedParams)
            {
                if (((string)p["guid"]!).ToLowerInvariant() == kv.Key && (string)p["name"]! != kv.Value)
                    issues.Add(new Dict
                    {
                        ["issue"] = $"GUID {kv.Key} is '{p["name"]}' in the file but '{kv.Value}' in the project",
                        ["severity"] = "warning",
                    });
            }
        }
        var groupNames = ((Dict)parsed["groups"]!).Values.Select(v => v as string).Distinct()
            .OrderBy(x => x, StringComparer.Ordinal).ToList();
        return new Dict
        {
            ["path"] = path,
            ["is_current_file"] = path == ctx.App.SharedParametersFilename,
            ["groups"] = groupNames,
            ["count"] = (long)prms.Count,
            ["parameters"] = prms,
            ["issues"] = issues,
        };
    }

    private static Dict CreateDefinitions(Ctx ctx)
    {
        var defs = ctx.List("definitions");
        if (defs.Count == 0)
            throw new RvtssError("'definitions' is required: [{name, type, group?, guid?, description?}]");
        var dry = ctx.DryRun;
        var results = new Lst();
        string? path;
        using (var shared = new SharedFile(ctx.App, OptionalPath(ctx, "shared_parameter_file"), ctx.Bool("create_file", false)))
        {
            var dfile = shared.Enter();
            var existingGuids = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var (_, d) in AllDefinitions(dfile))
                existingGuids[DefinitionGuid(d).ToLowerInvariant()] = Utils.NormalizeString(d.Name);
            foreach (var entry in defs)
            {
                var item = (Dict)entry!;
                var name = item.Get("name");
                if (!Py.Truthy(name))
                    throw new RvtssError("Each definition needs a name");
                var (_, found) = FindDefinition(dfile, name: name);
                var guidValue = item.Get("guid");
                var guid = (Py.Truthy(guidValue) ? Py.Str(guidValue) : "").Trim();
                if (found != null)
                {
                    var foundGuid = DefinitionGuid(found);
                    var res = new Dict
                    {
                        ["name"] = name, ["action"] = "exists", ["guid"] = foundGuid,
                        ["note"] = "Existing definition reused; its GUID was not changed.",
                    };
                    results.Add(res);
                    if (guid.Length > 0 && guid.ToLowerInvariant() != foundGuid.ToLowerInvariant())
                        res["warning"] = $"Requested GUID {guid} differs from the existing one";
                    continue;
                }
                if (guid.Length > 0)
                {
                    if (!Sharedparams.IsGuid(guid))
                        throw new RvtssError($"Invalid GUID '{guid}'");
                    if (existingGuids.TryGetValue(guid.ToLowerInvariant(), out var usedBy))
                        throw new RvtssError($"GUID {guid} is already used by '{usedBy}'", status: 409,
                            hint: "A GUID identifies one parameter; never reuse it for another name.");
                }
                if (dry)
                {
                    results.Add(new Dict { ["name"] = name, ["action"] = "would_create", ["guid"] = guid.Length > 0 ? guid : "(new)" });
                    continue;
                }
                var groupValue = item.Get("group");
                var groupName = Py.Truthy(groupValue) ? groupValue : "RVTSS";
                var groupText = Py.Str(groupName);
                var group = dfile.Groups.get_Item(groupText) ?? dfile.Groups.Create(groupText);
                var opts = Compat.ExternalDefinitionOptions(Py.Str(name), item.Get("type", "text"));
                if (guid.Length > 0)
                    opts.GUID = new Guid(guid);
                if (Py.Truthy(item.Get("description")))
                    opts.Description = Py.Str(item["description"]);
                opts.Visible = Py.Truthy(item.Get("visible", true));
                opts.UserModifiable = Py.Truthy(item.Get("user_modifiable", true));
                if (item.ContainsKey("hide_when_no_value"))
                {
                    try { opts.HideWhenNoValue = Py.Truthy(item["hide_when_no_value"]); }
                    catch { /* older API */ }
                }
                var created = group.Definitions.Create(opts);
                var createdGuid = DefinitionGuid(created);
                existingGuids[createdGuid.ToLowerInvariant()] = Py.Str(name);
                results.Add(new Dict { ["name"] = name, ["action"] = "created", ["guid"] = createdGuid, ["group"] = groupName });
            }
            path = ctx.App.SharedParametersFilename;
        }
        return new Dict { ["status"] = dry ? "dry_run" : "success", ["file"] = path, ["results"] = results };
    }

    private static List<DB.Category> ResolveCategories(DB.Document doc, IEnumerable<object?> names)
    {
        var cats = new List<DB.Category>();
        foreach (var n in names)
        {
            var c = Core.ResolveCategory(doc, n);
            if (!c.AllowsBoundParameters)
                throw new RvtssError($"Category '{c.Name}' does not allow bound parameters", status: 409);
            cats.Add(c);
        }
        return cats;
    }

    private static Dict Bind(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var name = ctx.Get("name");
        var guid = ctx.Get("guid");
        if (!Py.Truthy(name) && !Py.Truthy(guid))
            throw new RvtssError("Pass the shared parameter 'name' or 'guid'");
        var cats = ResolveCategories(doc, ctx.List("categories"));
        if (cats.Count == 0)
            throw new RvtssError("'categories' is required, e.g. ['Doors', 'Walls']");
        var bindingKind = ctx.Get("binding", "instance");
        var isInstance = bindingKind is string bk && bk == "instance";
        var group = ctx.Get("group", "data");
        var dry = ctx.DryRun;
        using var shared = new SharedFile(ctx.App, OptionalPath(ctx, "shared_parameter_file"));
        var dfile = shared.Enter();
        var (_, definition) = FindDefinition(dfile, name: name, guid: guid);
        if (definition == null)
            throw new RvtssError($"Shared parameter '{Py.Str(Py.Truthy(guid) ? guid : name)}' not found in {ctx.App.SharedParametersFilename}",
                status: 404, hint: "Create it with action='create_definitions' first.");
        var definitionName = Utils.NormalizeString(definition.Name);
        var definitionGuid = DefinitionGuid(definition);
        DB.ElementBinding? existing = null;
        foreach (var (_, b, entry) in Bindings(doc))
        {
            if ((string)entry["name"]! == definitionName)
            {
                var entryGuid = entry.Get("guid") as string ?? "";
                if (!Py.Truthy(entry.Get("shared")) || entryGuid.ToLowerInvariant() != definitionGuid.ToLowerInvariant())
                    throw new RvtssError($"A different parameter named '{entry["name"]}' is already bound (guid {(entry.ContainsKey("guid") ? entryGuid : "not shared")})",
                        status: 409,
                        hint: "Two parameters with the same name cause schedule/tag ambiguity. Rename or remove the "
                              + "existing project parameter first (Revit UI).");
                existing = b;
            }
        }

        Dict Run()
        {
            var app = doc.Application;
            var catset = app.Create.NewCategorySet();
            var merged = new List<string>();
            if (existing != null)
            {
                foreach (DB.Category c in existing.Categories)
                {
                    catset.Insert(c);
                    merged.Add(Utils.NormalizeString(c.Name));
                }
                var kind = existing is DB.InstanceBinding ? "instance" : "type";
                if (!(bindingKind is string bs && bs == kind))
                    throw new RvtssError($"'{definition.Name}' is already bound as a {kind} parameter", status: 409,
                        hint: "Changing instance/type binding would delete existing values; do it in Revit.");
            }
            foreach (var c in cats)
                catset.Insert(c);
            DB.ElementBinding binding = isInstance
                ? app.Create.NewInstanceBinding(catset)
                : app.Create.NewTypeBinding(catset);
            bool ok;
            string action;
            if (existing != null)
            {
                ok = Compat.ReinsertBinding(doc, definition, binding, group);
                action = "categories_extended";
            }
            else
            {
                ok = Compat.InsertBinding(doc, definition, binding, group);
                action = "bound";
            }
            if (!ok)
                throw new RvtssError("Revit refused the binding", status: 409);
            if (ctx.Get("vary_between_groups") != null && isInstance)
            {
                foreach (var (d, _, entry) in Bindings(doc))
                {
                    if ((string)entry["name"]! == definitionName && d is DB.InternalDefinition internalDefinition)
                        internalDefinition.SetAllowVaryBetweenGroups(doc, Py.Truthy(ctx.Get("vary_between_groups")));
                }
            }
            var all = new HashSet<string>(merged, StringComparer.Ordinal);
            foreach (var c in cats)
                all.Add(Utils.NormalizeString(c.Name));
            return new Dict
            {
                ["name"] = definitionName, ["guid"] = definitionGuid, ["action"] = action,
                ["binding"] = bindingKind, ["categories"] = all.OrderBy(x => x, StringComparer.Ordinal).ToList(),
            };
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Bind shared parameter", Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    public static Dict? SharedParameters(Ctx ctx)
    {
        var action = ctx.Require("action") as string;
        if (action == "read_file")
            return ReadFile(ctx);
        if (action == "create_definitions")
            return CreateDefinitions(ctx);
        if (action == "create_file")
        {
            var path = Py.Str(ctx.Require("shared_parameter_file"));
            if (File.Exists(path) || Directory.Exists(path))
                throw new RvtssError($"File exists: {path}", status: 409);
            using (var shared = new SharedFile(ctx.App, path, create: true))
                shared.Enter();
            if (ctx.Bool("set_as_current", false))
                ctx.App.SharedParametersFilename = path;
            return new Dict { ["created"] = path, ["is_current_file"] = ctx.App.SharedParametersFilename == path };
        }
        if (action == "bind")
            return Bind(ctx);
        throw new RvtssError("action must be read_file, create_definitions, create_file or bind");
    }
}
