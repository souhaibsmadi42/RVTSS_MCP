using System.Globalization;

namespace RvtssHost;

/// <summary>
/// Shared infrastructure for RVTSS route modules: port of revit_mcp/core.py.
/// Function names are the Python names in PascalCase (run_transaction -> RunTransaction).
/// </summary>
public static class Core
{
    /// <summary>Operations touching more elements than this need confirm=true.</summary>
    public static readonly int ConfirmThreshold =
        int.TryParse(Environment.GetEnvironmentVariable("RVTSS_CONFIRM_THRESHOLD"), out var c) ? c : 100;

    public const int MaxLimit = 1000;

    // ------------------------------------------------------------- folders
    public static string RvtssHome()
    {
        var baseDir = Environment.GetEnvironmentVariable("APPDATA");
        if (string.IsNullOrEmpty(baseDir))
            baseDir = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var path = Path.Combine(baseDir, "RVTSS");
        try { Directory.CreateDirectory(path); } catch { /* reported by whoever writes there */ }
        return path;
    }

    public static string RvtssSubdir(string name)
    {
        var path = Path.Combine(RvtssHome(), name);
        Directory.CreateDirectory(path);
        return path;
    }

    /// <summary>(rules, error) from %APPDATA%/RVTSS/qc_rules.json; ({}, null) when the file does not exist.</summary>
    public static (Dict rules, string? error) LoadQcRules()
    {
        var path = Path.Combine(RvtssHome(), "qc_rules.json");
        if (!File.Exists(path))
            return (new Dict(), null);
        try
        {
            return (Py.JsonLoads(File.ReadAllText(path, Encoding.UTF8)) as Dict ?? new Dict(), null);
        }
        catch (Exception e)
        {
            return (new Dict(), "qc_rules.json is invalid: " + e.Message);
        }
    }

    /// <summary>Optional %APPDATA%/RVTSS/config.json.</summary>
    public static Dict LoadConfig()
    {
        var path = Path.Combine(RvtssHome(), "config.json");
        if (File.Exists(path))
        {
            try { return Py.JsonLoads(File.ReadAllText(path)) as Dict ?? new Dict(); }
            catch (Exception e) { Log.Write("Invalid RVTSS config.json: " + e.Message); }
        }
        return new Dict();
    }

    // ---------------------------------------------------------------- logs
    public const int AuditLineMax = 500;
    public const int CodeLogMax = 20000;
    public const int LogRetentionDays = 30;
    private static string? _rotatedDay;
    private static readonly object LogGate = new();

    private static void RotateLogs(string logdir)
    {
        var today = DateTime.Now.ToString("yyyyMMdd");
        if (_rotatedDay == today)
            return;
        _rotatedDay = today;
        try
        {
            var cutoff = DateTime.Now.AddDays(-LogRetentionDays);
            foreach (var f in Directory.GetFiles(logdir, "*.log"))
                if (f.EndsWith(".log", StringComparison.Ordinal) && File.GetLastWriteTime(f) < cutoff)
                    File.Delete(f);
        }
        catch { /* best effort */ }
    }

    public static void AppendLog(string prefix, string text)
    {
        var logdir = RvtssSubdir("logs");
        lock (LogGate)
        {
            RotateLogs(logdir);
            File.AppendAllText(Path.Combine(logdir, $"{prefix}-{DateTime.Now:yyyyMMdd}.log"), text, new UTF8Encoding(false));
        }
    }

    [ThreadStatic] private static string? _requestId;

    /// <summary>Correlation id of the request being handled on this thread (set by SecureApi.Around).</summary>
    public static void SetRequestId(string? requestId) => _requestId = requestId;

    public static string? CurrentRequestId() => _requestId;

    [ThreadStatic] private static bool _batchActive;
    [ThreadStatic] private static bool _batchDryRun;

    /// <summary>Batch.RunBatch marks the commands it runs (on this thread) as part of a batch / a batch dry run.</summary>
    public static void SetBatchState(bool active, bool dryRun = false)
    {
        _batchActive = active;
        _batchDryRun = active && dryRun;
    }

    public static bool InBatch() => _batchActive;

    public static bool InBatchDryRun() => _batchDryRun;

    /// <summary>One line per request; secret-looking values are redacted and the line is capped.</summary>
    public static void AuditLog(string method, bool ok, double durationSeconds, object? detail = null, string? requestId = null)
    {
        try
        {
            // `detail or ""`: a falsy detail (None, "", 0, False) logs as empty text
            var text = Security.Redact((Py.Truthy(detail) ? Py.Str(detail) : "").Replace("\n", " "), AuditLineMax);
            AppendLog("rvtss", string.Format(CultureInfo.InvariantCulture, "{0:HH:mm:ss}\t{1}\t{2}\t{3:0}ms\t{4}\t{5}\n",
                DateTime.Now, method, ok ? "ok" : "ERROR", durationSeconds * 1000.0, requestId ?? "-", text));
        }
        catch { /* logging must never break a request */ }
    }

    /// <summary>Write executed code to logs/code-YYYYMMDD.log (redacted, capped).</summary>
    public static void AuditCode(string? description, string mode, string? code)
    {
        try
        {
            // a missing description / code is written as "None", as Python formatted it
            AppendLog("code", $"=== {DateTime.Now:yyyy-MM-dd HH:mm:ss} | mode={mode} | "
                              + (description == null ? "None" : Security.Redact(description, 200)) + "\n"
                              + (code == null ? "None" : Security.Redact(code, CodeLogMax)) + "\n");
        }
        catch { /* logging must never break a request */ }
    }

    // -------------------------------------------------------------- errors
    public static RvtssError NotFound(string what, object? name, IEnumerable<string?>? choices = null, string? hint = null)
    {
        var error = new RvtssError($"{what} not found: {Py.Str(name)}", status: 404, hint: hint);
        if (choices != null)
        {
            var list = choices.Where(x => !string.IsNullOrEmpty(x)).Select(x => x!).ToList();
            error.With("did_you_mean", Py.CloseMatches(Py.Str(name), list, 5, 0.5).Cast<object?>().ToList());
            error.With("available_sample", list.OrderBy(x => x, StringComparer.Ordinal).Take(25).Cast<object?>().ToList());
        }
        return error;
    }

    // ----------------------------------------------------------- responses
    /// <summary>Text without stripping (Utils.NormalizeString strips and renames null).</summary>
    public static string? ToText(object? value) => value == null ? null : Py.Str(value);

    /// <summary>Make a value JSON-serialisable (Py.Clean; ElementId becomes its integer value).</summary>
    public static object? Clean(object? value) => Py.Clean(value);

    static Core()
    {
        Py.ForeignScalar = v => v is DB.ElementId id ? id.Value : null;
    }

    public static Response Ok(Dict? data = null)
    {
        var payload = new Dict { ["status"] = "success" };
        payload.Update(data);
        return new Response(payload);
    }

    public static Response Respond(object? payload, int status = 200) => new(payload, status);

    public static Response ErrorResponse(string message, int status = 400, string? hint = null, Dict? extra = null)
    {
        var payload = new Dict { ["status"] = "error", ["error"] = message };
        if (!string.IsNullOrEmpty(hint))
            payload["hint"] = hint;
        payload.Update(extra);
        return new Response(payload, status);
    }

    // ------------------------------------------------------------- request
    /// <summary>The RVTSS request being handled (read by the undo module's DocumentChanged listener).</summary>
    public static string? ActiveRequestMethod;
    public static long ActiveRequestSeq;

    /// <summary>Run impl(ctx) and turn its result / errors into a Response (core.handle).</summary>
    public static Response Handle(Request request, Func<Ctx, Dict?> impl, string method, bool needsDoc = true)
    {
        var start = DateTime.UtcNow;
        double Elapsed() => (DateTime.UtcNow - start).TotalSeconds;
        try
        {
            if (request.Data == null)
                throw new RvtssError(request.BodyError ?? "Request body must be a JSON object");
            var data = request.Data;
            if (needsDoc && request.Doc == null && !Py.Truthy(data.Get("document")))
                throw new RvtssError("No active Revit document", status: 503,
                    hint: "Open a project or family in Revit (open_document) and retry.");
            var ctx = new Ctx(request.Doc, request.UiDoc, data, needsDoc);
            ActiveRequestMethod = method;
            ActiveRequestSeq++;
            Dict? result;
            try { result = impl(ctx); }
            finally { ActiveRequestMethod = null; }
            result ??= new Dict();
            if (ctx.Warnings.Count > 0)
            {
                // result.setdefault("warnings", []).extend(ctx.warnings): keep what the implementation put
                // there, also when it is a typed list (List<string>)
                if (result.Get("warnings") is not Lst warnings)
                {
                    warnings = new Lst();
                    if (result.Get("warnings") is System.Collections.IEnumerable existing && existing is not string)
                        foreach (var w in existing)
                            warnings.Add(w);
                    result["warnings"] = warnings;
                }
                warnings.AddRange(ctx.Warnings);
            }
            result.SetDefault("status", "success");
            AuditLog(method, true, Elapsed(), result.Get("status"), CurrentRequestId());
            return Respond(result);
        }
        catch (RvtssError e)
        {
            AuditLog(method, false, Elapsed(), e.Message, CurrentRequestId());
            return ErrorResponse(e.Message, e.Status, e.Hint, e.Extra);
        }
        catch (Exception e)
        {
            var tb = e.ToString();
            Log.Write($"RVTSS {method} failed: {tb}");
            AuditLog(method, false, Elapsed(), e.Message, CurrentRequestId());
            return ErrorResponse($"{e.GetType().Name}: {Utils.NormalizeString(e.Message)}", 500, RevitErrorHint(e), new Dict
            {
                ["traceback"] = tb.Length > 3000 ? tb.Substring(tb.Length - 3000) : tb,
                ["inner_exception"] = e.InnerException?.ToString(),
            });
        }
    }

    public static string? RevitErrorHint(Exception e)
    {
        var msg = e.Message;
        var name = e.GetType().Name;
        if (name.Contains("ModificationOutsideTransaction") || msg.Contains("outside of a transaction"))
            return "This change needs a transaction; RVTSS tools open one automatically.";
        if (name.Contains("ModificationForbidden") || msg.ToLowerInvariant().Contains("read-only"))
            return "The document is read-only or in a state that forbids modification (linked, being edited, or modal UI open).";
        if (name.Contains("ArgumentException") || name.Contains("ArgumentOutOfRange"))
            return "Revit rejected one of the arguments. Re-check ids, names and units (lengths default to mm).";
        if (name.Contains("InvalidOperation"))
            return "Revit refused the operation in the current state. Inspect the element/document state and retry.";
        return null;
    }

    // ----------------------------------------------------------- documents
    public static List<DB.Document> AllDocuments(DB.Document? doc)
    {
        var app = doc != null ? doc.Application : Hosting.App!;
        return app.Documents.Cast<DB.Document>().ToList();
    }

    public static Dict DescribeDocument(DB.Document d) => new()
    {
        ["title"] = Utils.NormalizeString(d.Title),
        ["path"] = string.IsNullOrEmpty(d.PathName) ? null : d.PathName,
        ["is_family"] = d.IsFamilyDocument,
        ["is_linked"] = d.IsLinked,
        ["is_modified"] = d.IsModified,
        ["is_workshared"] = d.IsWorkshared,
        ["is_read_only"] = d.IsReadOnly,
        ["family_category"] = d.IsFamilyDocument && d.OwnerFamily.FamilyCategory != null ? d.OwnerFamily.FamilyCategory.Name : null,
    };

    /// <summary>Find an open document by title (with/without extension) or full path.</summary>
    public static DB.Document ResolveDocument(DB.Document? activeDoc, object? target)
    {
        if (!Py.Truthy(target) || (target is string ts && ts.ToLowerInvariant() == "active"))
        {
            if (activeDoc == null)
                throw new RvtssError("No active Revit document", status: 503);
            return activeDoc;
        }
        var t = Py.Str(target).Trim().ToLowerInvariant();
        var docs = AllDocuments(activeDoc).Where(d => !d.IsLinked).ToList();
        foreach (var d in docs)
        {
            var title = (d.Title ?? "").ToLowerInvariant();
            var path = (d.PathName ?? "").ToLowerInvariant();
            if (t == title || t == path || t == StripExtension(title)
                || (path.Length > 0 && t == StripExtension(Path.GetFileName(path))))
                return d;
        }
        throw NotFound("Open document", target, docs.Select(d => d.Title),
            hint: "Use get_revit_status to list open documents (family documents opened by "
                  + "family_open/family_create stay open in the background).");
    }

    /// <summary>os.path.splitext(name)[0]</summary>
    private static string StripExtension(string name)
    {
        var i = name.LastIndexOf('.');
        return i > 0 && name.IndexOfAny(new[] { '/', '\\' }, i) < 0 ? name.Substring(0, i) : name;
    }

    public static void RequireProject(DB.Document doc)
    {
        if (doc.IsFamilyDocument)
            throw new RvtssError($"This operation needs a project document but '{doc.Title}' is a family document",
                hint: "Pass document='<project title>' or activate the project.");
    }

    public static DB.FamilyManager RequireFamily(DB.Document doc)
    {
        if (!doc.IsFamilyDocument)
            throw new RvtssError($"'{doc.Title}' is not a family document", status: 400,
                hint: "Open the family first with family_open (path or loaded family name) "
                      + "or family_create, then pass its title as 'document'.");
        return doc.FamilyManager;
    }

    /// <summary>RVTSS_READ_ONLY (Revit environment) or "read_only": true in config.json.</summary>
    public static bool ReadOnlyMode()
    {
        try { return Py.Truthy(SecureApi.Settings().Get("read_only")); }
        catch { return false; }
    }

    /// <summary>Refuse model / file changes in read-only mode (dry runs and previews do not call this).
    /// Commands of a batch dry run strip their own dry_run, but the whole group is rolled back, so they pass.</summary>
    public static void RequireWritable(string action = "This operation")
    {
        if (ReadOnlyMode() && !InBatchDryRun())
            throw new RvtssError($"{action} is refused: RVTSS runs in read-only mode on this Revit machine", status: 403,
                hint: "Dry runs still work. Unset RVTSS_READ_ONLY (or 'read_only' in "
                      + "%APPDATA%/RVTSS/config.json) and restart Revit to allow changes.").With("read_only", true);
    }

    /// <summary>For route handlers outside Handle(): an error Response in read-only mode, else null.</summary>
    public static Response? ReadOnlyResponse(string action = "This operation")
    {
        try { RequireWritable(action); }
        catch (RvtssError e) { return ErrorResponse(e.Message, e.Status, e.Hint, e.Extra); }
        return null;
    }

    /// <summary>Save and sync with central are off by default. kind: "save" | "sync".
    /// Error Response unless allowed, else null. Applies after ReadOnlyResponse.</summary>
    public static Response? FilePolicyResponse(string kind, string action)
    {
        var (key, env, what) = kind == "save"
            ? ("allow_save", "RVTSS_ALLOW_SAVE", "Saving the document")
            : ("allow_sync", "RVTSS_ALLOW_SYNC", "Synchronize with central");
        bool allowed;
        try { allowed = Py.Truthy(SecureApi.Settings().Get(key)); }
        catch { allowed = false; }
        if (allowed)
            return null;
        return ErrorResponse($"{action} is refused: {what.ToLowerInvariant()} is off in the RVTSS policy ({key})", 403,
            $"Do it in Revit yourself, or set \"{key}\": true in %APPDATA%/RVTSS/config.json (or {env}=1 for Revit) "
            + "and restart Revit.", new Dict { ["code"] = "POLICY_DENIED", ["policy"] = key });
    }

    public static void CheckModifiable(DB.Document doc)
    {
        if (doc.IsReadOnly)
            throw new RvtssError($"Document '{doc.Title}' is read-only", status: 409);
        if (doc.IsLinked)
            throw new RvtssError("Linked documents cannot be modified", status: 409,
                hint: "Open the linked file itself to edit it.");
    }

    // ------------------------------------------------------------- lookups
    public static DB.Element GetElement(DB.Document doc, object? elementId, string what = "Element")
    {
        DB.Element? e;
        try { e = doc.GetElement(Compat.MakeId(elementId)); }
        catch { e = null; }
        if (e == null)
            throw new RvtssError($"{what} id {Py.Str(elementId)} does not exist in '{doc.Title}'", status: 404,
                hint: "Ids are document specific; use find_elements to get current ids.");
        return e;
    }

    public static List<DB.Element> GetElements(DB.Document doc, IEnumerable<object?> ids, string what = "Element")
    {
        var found = new List<DB.Element>();
        var missing = new Lst();
        foreach (var i in ids)
        {
            DB.Element? e;
            try { e = doc.GetElement(Compat.MakeId(i)); }
            catch { e = null; }
            if (e == null)
                missing.Add(i);
            else
                found.Add(e);
        }
        if (missing.Count > 0)
            throw new RvtssError($"{what} ids not found: [{string.Join(", ", missing.Take(20).Select(PyX.Repr))}]", status: 404,
                hint: "Ids are document specific; use find_elements to get current ids.").With("missing_ids", missing);
        return found;
    }

    private static readonly Dictionary<string, Dictionary<string, long>> CategoryCache = new();

    private static string CacheKey(DB.Document doc) => doc.Title + "\n" + doc.PathName;

    /// <summary>{lower-case display name: category id}. Ids (not Category objects) are cached so a cache
    /// entry can never hold objects of a closed document.</summary>
    private static Dictionary<string, long> CategoryMap(DB.Document doc)
    {
        var key = CacheKey(doc);
        if (CategoryCache.TryGetValue(key, out var cached))
            return cached;
        var m = new Dictionary<string, long>();
        foreach (DB.Category c in doc.Settings.Categories)
            m[Utils.NormalizeString(c.Name).ToLowerInvariant()] = c.Id.Value;
        CategoryCache[key] = m;
        return m;
    }

    private static DB.Category? CategoryById(DB.Document doc, long cid)
    {
        try { return DB.Category.GetCategory(doc, Compat.MakeId(cid)); }
        catch { return null; }
    }

    /// <summary>Category by display name ('Doors'), BuiltInCategory ('OST_Doors') or id.</summary>
    public static DB.Category ResolveCategory(DB.Document doc, object? name)
    {
        if (name is DB.Category already)
            return already;
        if (Py.IsInt(name) || (name is string digits && digits.TrimStart('-').Length > 0 && digits.TrimStart('-').All(char.IsDigit)))
        {
            var byId = CategoryById(doc, Py.ToInt(name));
            if (byId != null)
                return byId;
        }
        var s = Py.Str(name).Trim();
        var candidates = new[] { s.ToUpperInvariant().StartsWith("OST_") ? s : null, "OST_" + s.Replace(" ", "") };
        foreach (var cand in candidates)
        {
            var bic = Py.EnumOrNull<DB.BuiltInCategory>(cand);
            if (bic == null)
                continue;
            try
            {
                var cat = DB.Category.GetCategory(doc, bic.Value);
                if (cat != null)
                    return cat;
            }
            catch { /* not a category of this document */ }
        }
        var low = s.ToLowerInvariant();
        for (var attempt = 0; attempt < 2; attempt++)
        {
            var m = CategoryMap(doc);
            foreach (var variant in new[] { low, low + "s", low.TrimEnd('s'), low + "es" })
            {
                if (!m.TryGetValue(variant, out var cid))
                    continue;
                var cat = CategoryById(doc, cid);
                if (cat != null)
                    return cat;
            }
            CategoryCache.Remove(CacheKey(doc));
        }
        throw NotFound("Category", name, doc.Settings.Categories.Cast<DB.Category>().Select(x => x.Name),
            hint: "Use the display name (e.g. 'Doors', 'Generic Models') or 'OST_Doors'.");
    }

    public static Dict? CategoryInfo(DB.Category? cat) => cat == null ? null : new Dict
    {
        ["name"] = Utils.NormalizeString(cat.Name), ["id"] = cat.Id.Value, ["builtin"] = Compat.BicFromCategory(cat),
    };

    private static bool IsDigits(object? v) => v is string s && s.Length > 0 && s.All(char.IsDigit);

    public static DB.Level? FindLevel(DB.Document doc, object? level)
    {
        if (level == null)
            return null;
        if (Py.IsInt(level) || IsDigits(level))
        {
            if (doc.GetElement(Compat.MakeId(Py.ToInt(level))) is DB.Level byId)
                return byId;
        }
        var levels = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Level)).Cast<DB.Level>().ToList();
        var wanted = Py.Str(level).Trim().ToLowerInvariant();
        foreach (var lv in levels)
            if (Utils.NormalizeString(lv.Name).ToLowerInvariant() == wanted)
                return lv;
        throw NotFound("Level", level, levels.Select(lv => lv.Name));
    }

    /// <summary>View by id or name; null / "" / "active" gives the active view (or null when defaultActive is false).</summary>
    public static DB.View? FindView(DB.Document doc, object? view, bool defaultActive = true, UIDocument? uidoc = null)
    {
        if (view == null || (view is string vs && (vs == "" || vs == "active")))
        {
            if (!defaultActive)
                return null;
            var v = uidoc == null ? doc.ActiveView : uidoc.ActiveView;
            if (v == null)
                throw new RvtssError("No active view", status: 404);
            return v;
        }
        if (Py.IsInt(view) || IsDigits(view))
        {
            if (doc.GetElement(Compat.MakeId(Py.ToInt(view))) is DB.View byId)
                return byId;
        }
        var views = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>().Where(v => !v.IsTemplate).ToList();
        var wanted = Py.Str(view).Trim().ToLowerInvariant();
        var matches = views.Where(v => Utils.NormalizeString(v.Name).ToLowerInvariant() == wanted).ToList();
        if (matches.Count == 1)
            return matches[0];
        if (matches.Count > 1)
            throw new RvtssError($"View name '{Py.Str(view)}' is ambiguous ({matches.Count} views)", status: 409,
                    hint: "Pass the view id instead.")
                .With("candidates", matches.Select(v => (object?)new Dict { ["id"] = v.Id.Value, ["type"] = v.ViewType.ToString() }).ToList());
        throw NotFound("View", view, views.Select(v => v.Name));
    }

    /// <summary>Find an ElementType by id or family/type name (FamilySymbol and system types).</summary>
    public static DB.ElementType FindType(DB.Document doc, object? family = null, object? typeName = null, object? typeId = null,
        object? category = null, Type? ofClass = null)
    {
        if (typeId != null)
        {
            var e = GetElement(doc, typeId, "Type");
            if (e is not DB.ElementType et)
                throw new RvtssError($"Element {Py.Str(typeId)} is not a type");
            return et;
        }
        var col = new DB.FilteredElementCollector(doc).WhereElementIsElementType();
        if (ofClass != null)
            col = col.OfClass(ofClass);
        if (category != null)
            col = col.OfCategoryId(ResolveCategory(doc, category).Id);
        var famL = Py.Truthy(family) ? Py.Str(family).Trim().ToLowerInvariant() : null;
        var typL = Py.Truthy(typeName) ? Py.Str(typeName).Trim().ToLowerInvariant() : null;
        // `if fam_l and ...`: a name of only spaces is no filter, as in Python
        if (famL != null && famL.Length == 0) famL = null;
        if (typL != null && typL.Length == 0) typL = null;
        var seen = new List<string>();
        foreach (var el in col)
        {
            if (el is not DB.ElementType t)
                continue;
            var fam = Utils.NormalizeString(t.FamilyName ?? "");
            var name = Utils.NormalizeString(Utils.GetElementName(t));
            seen.Add($"{fam} : {name}");
            if (famL != null && fam.ToLowerInvariant() != famL)
                continue;
            if (typL != null && name.ToLowerInvariant() != typL)
                continue;
            if (famL != null || typL != null)
                return t;
        }
        throw NotFound("Type", $"{(Py.Truthy(family) ? Py.Str(family) : "*")} : {(Py.Truthy(typeName) ? Py.Str(typeName) : "*")}", seen,
            hint: "Use list_families / find_elements(include_types=true) to see available types.");
    }

    // -------------------------------------------------------- element info
    public static Dict ElementBrief(DB.Document doc, DB.Element e)
    {
        var info = new Dict { ["id"] = e.Id.Value, ["name"] = Utils.NormalizeString(Utils.GetElementName(e) ?? "") };
        var cat = e.Category;
        info["category"] = cat != null ? Utils.NormalizeString(cat.Name) : null;
        try
        {
            var tid = e.GetTypeId();
            if (Compat.IsValidId(tid))
            {
                var t = doc.GetElement(tid);
                if (t != null)
                {
                    info["family"] = Utils.NormalizeString((t as DB.ElementType)?.FamilyName ?? "");
                    info["type"] = Utils.NormalizeString(Utils.GetElementName(t));
                    info["type_id"] = tid.Value;
                }
            }
            else if (e is DB.ElementType et)
            {
                info["family"] = Utils.NormalizeString(et.FamilyName ?? "");
            }
        }
        catch { /* leave the brief without type info */ }
        return info;
    }

    private static readonly string[] LevelParams =
    {
        "FAMILY_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM", "WALL_BASE_CONSTRAINT", "SCHEDULE_LEVEL_PARAM", "LEVEL_PARAM",
    };

    public static string? ElementLevel(DB.Document doc, DB.Element e)
    {
        try
        {
            var lid = e.LevelId;
            if (Compat.IsValidId(lid))
            {
                var lv = doc.GetElement(lid);
                return lv != null ? Utils.NormalizeString(lv.Name) : null;
            }
        }
        catch { /* fall through to parameters */ }
        foreach (var bipName in LevelParams)
        {
            try
            {
                var bip = Py.EnumOrNull<DB.BuiltInParameter>(bipName);
                if (bip == null)
                    continue;
                var p = e.get_Parameter(bip.Value);
                if (p != null && Compat.IsValidId(p.AsElementId()))
                {
                    var lv = doc.GetElement(p.AsElementId());
                    if (lv != null)
                        return Utils.NormalizeString(lv.Name);
                }
            }
            catch { /* next parameter */ }
        }
        return null;
    }

    public static Lst XyzList(DB.XYZ p, string unit = "mm", int nd = 1) => new()
    {
        Units.FromInternal(p.X, unit, nd), Units.FromInternal(p.Y, unit, nd), Units.FromInternal(p.Z, unit, nd),
    };

    public static Dict? ElementLocation(DB.Element e, string unit = "mm")
    {
        var loc = e.Location;
        if (loc is DB.LocationPoint lp)
        {
            var result = new Dict { ["type"] = "point", ["point"] = XyzList(lp.Point, unit) };
            try { result["rotation_deg"] = Py.Round(lp.Rotation * 180.0 / 3.141592653589793, 3); }
            catch { /* some point locations have no rotation */ }
            return result;
        }
        if (loc is DB.LocationCurve lc)
        {
            var c = lc.Curve;
            return new Dict
            {
                ["type"] = "curve", ["start"] = XyzList(c.GetEndPoint(0), unit), ["end"] = XyzList(c.GetEndPoint(1), unit),
                ["length"] = Units.FromInternal(c.Length, unit, 1),
            };
        }
        return null;
    }

    /// <summary>Representative XYZ for an element (location point, curve midpoint or bbox centre).</summary>
    public static DB.XYZ? ElementPoint(DB.Element e)
    {
        var loc = e.Location;
        if (loc is DB.LocationPoint lp)
            return lp.Point;
        if (loc is DB.LocationCurve lc)
        {
            var c = lc.Curve;
            if (c.IsBound)
                return c.Evaluate(0.5, true);
            // unbound curves (some MEP / analytical elements) cannot be evaluated as normalized
            try { return c is DB.Line line ? line.Origin : c.Evaluate(0.0, false); }
            catch { /* fall through to the bounding box */ }
        }
        var bb = e.get_BoundingBox(null);
        return bb != null ? (bb.Min + bb.Max) * 0.5 : null;
    }

    public static Dict? ElementBbox(DB.Element e, string unit = "mm", DB.View? view = null)
    {
        var bb = e.get_BoundingBox(view);
        return bb == null ? null : new Dict { ["min"] = XyzList(bb.Min, unit), ["max"] = XyzList(bb.Max, unit) };
    }

    /// <summary>ICollection of ElementId from ids / ElementIds / elements.</summary>
    public static List<DB.ElementId> ToIdList(System.Collections.IEnumerable ids)
    {
        var list = new List<DB.ElementId>();
        foreach (var i in ids)
            list.Add(i is DB.ElementId id ? id : i is DB.Element el ? el.Id : Compat.MakeId(i));
        return list;
    }

    // -------------------------------------------------------- transactions
    /// <summary>Collects warnings/errors raised while committing. Warnings are recorded and dismissed so they
    /// do not block the transaction or pop up dialogs; errors make the transaction roll back and are reported.</summary>
    public sealed class FailureCollector : DB.IFailuresPreprocessor
    {
        public Lst Messages { get; } = new();
        public bool HasErrors { get; private set; }

        public DB.FailureProcessingResult PreprocessFailures(DB.FailuresAccessor failuresAccessor)
        {
            foreach (var f in failuresAccessor.GetFailureMessages())
            {
                var sev = f.GetSeverity();
                Lst ids;
                try { ids = f.GetFailingElementIds().Take(20).Select(i => (object?)i.Value).ToList(); }
                catch { ids = new Lst(); }
                Messages.Add(new Dict
                {
                    ["severity"] = sev.ToString(), ["message"] = Utils.NormalizeString(f.GetDescriptionText()), ["element_ids"] = ids,
                });
                if (sev == DB.FailureSeverity.Warning)
                    failuresAccessor.DeleteWarning(f);
                else
                    HasErrors = true;
            }
            return HasErrors ? DB.FailureProcessingResult.ProceedWithRollBack : DB.FailureProcessingResult.Continue;
        }
    }

    internal static (DB.Transaction, FailureCollector) StartTx(DB.Document doc, string name)
    {
        var t = new DB.Transaction(doc, name);
        var collector = new FailureCollector();
        var opts = t.GetFailureHandlingOptions();
        opts.SetFailuresPreprocessor(collector);
        opts.SetClearAfterRollback(true);
        t.SetFailureHandlingOptions(opts);
        t.Start();
        return (t, collector);
    }

    /// <summary>
    /// Run func() inside a transaction. Returns (result, failure messages).
    /// dryRun: commit inside a TransactionGroup and roll the group back, so the preview reflects Revit's own
    /// validation without keeping any change. If a transaction is already open on doc, func runs inside it.
    /// </summary>
    public static (T result, Lst failures) RunTransaction<T>(DB.Document doc, string name, Func<T> func, bool dryRun = false)
    {
        CheckModifiable(doc);
        if (!dryRun)
            RequireWritable($"'{name}'");
        if (doc.IsModifiable)
            return (func(), new Lst());
        name = "RVTSS: " + name;
        DB.TransactionGroup? group = null;
        if (dryRun)
        {
            group = new DB.TransactionGroup(doc, name + " (dry run)");
            group.Start();
        }
        DB.Transaction? t = null;
        try
        {
            FailureCollector collector;
            (t, collector) = StartTx(doc, name);
            var result = func();
            var status = t.Commit();
            if (status != DB.TransactionStatus.Committed)
            {
                var errors = collector.Messages.Cast<Dict>().Where(m => (string?)m["severity"] != "Warning")
                    .Select(m => (string?)m["message"]).ToList();
                var joined = string.Join("; ", errors);
                throw new RvtssError("Revit rejected the change and rolled it back: " + (joined.Length > 0 ? joined : status.ToString()),
                    status: 409, hint: "Nothing was changed. Adjust the request to avoid the reported errors.")
                    .With("failures", collector.Messages);
            }
            return (result, collector.Messages);
        }
        catch
        {
            if (t != null && t.HasStarted() && !t.HasEnded())
                t.RollBack();
            throw;
        }
        finally
        {
            if (group != null && group.HasStarted() && !group.HasEnded())
                group.RollBack();
            t?.Dispose();
            group?.Dispose();
        }
    }

    /// <summary>RunTransaction for work that returns nothing.</summary>
    public static Lst RunTransaction(DB.Document doc, string name, Action action, bool dryRun = false) =>
        RunTransaction<object?>(doc, name, () => { action(); return null; }, dryRun).failures;

    /// <summary>
    /// Apply func(item) to each item inside an open transaction (core.batch).
    /// atomic=true: first failure aborts (caller's transaction rolls back).
    /// atomic=false: each item runs in a SubTransaction; failures are recorded and rolled back individually.
    /// Returns a list of {"index", "ok", ...result | "error"}.
    /// </summary>
    public static Lst Batch(DB.Document doc, IEnumerable<object?> items, Func<object?, Dict?> func, bool atomic = true)
    {
        var results = new Lst();
        var i = 0;
        foreach (var item in items)
        {
            Dict r;
            if (atomic)
            {
                try
                {
                    r = func(item) ?? new Dict();
                }
                catch (RvtssError e)
                {
                    throw new RvtssError($"Item {i} failed: {e.Message}", e.Status,
                            "Batch is atomic: nothing was changed. Fix the item or pass atomic=false.")
                        .With("failed_index", i).With("failed_item", item);
                }
                catch (Exception e)
                {
                    throw new RvtssError($"Item {i} failed: {Utils.NormalizeString(e.Message)}", 400,
                            "Batch is atomic: nothing was changed. Fix the item or pass atomic=false.")
                        .With("failed_index", i).With("failed_item", item);
                }
                r["index"] = i;
                r["ok"] = true;
            }
            else
            {
                using var st = new DB.SubTransaction(doc);
                st.Start();
                try
                {
                    r = func(item) ?? new Dict();
                    st.Commit();
                    r["index"] = i;
                    r["ok"] = true;
                }
                catch (Exception e)
                {
                    if (st.HasStarted() && !st.HasEnded())
                        st.RollBack();
                    r = new Dict { ["index"] = i, ["ok"] = false, ["error"] = e is RvtssError ? e.Message : Utils.NormalizeString(e.Message) };
                }
            }
            results.Add(r);
            i++;
        }
        return results;
    }

    /// <summary>Standard envelope for modifying operations.</summary>
    public static Dict CommitResult(Dict? result, Lst? failures, bool dryRun, Dict? extra = null)
    {
        var o = new Dict { ["status"] = dryRun ? "dry_run" : "success", ["committed"] = !dryRun };
        if (dryRun)
            o["message"] = "Dry run: Revit validated the change and it was rolled back. Nothing was modified.";
        if (failures != null && failures.Count > 0)
            o["revit_warnings"] = failures;
        o.Update(result);
        o.Update(extra);
        return o;
    }

    /// <summary>
    /// Big/destructive operations need confirm=true; otherwise force a dry run. Returns true when the operation
    /// must run as a forced preview. An explicit dry_run is not a forced preview: callers run it as a dry run
    /// (dry = preview || ctx.DryRun) and report status "dry_run".
    /// </summary>
    public static bool ConfirmGate(Ctx ctx, long count, string action)
    {
        if (ctx.Confirmed || ctx.DryRun)
            return false;
        if (count > ConfirmThreshold)
        {
            ctx.Warn($"{action} affects {count} elements (> {ConfirmThreshold}). Showing a preview; re-run with confirm=true to apply.");
            return true;
        }
        return false;
    }

    public static Dict PreviewStatus(Dict o, bool forced)
    {
        if (forced)
        {
            o["status"] = "preview";
            o["requires_confirmation"] = true;
            o["message"] = "Preview only - nothing was modified. Re-run with confirm=true to apply.";
        }
        return o;
    }
}
