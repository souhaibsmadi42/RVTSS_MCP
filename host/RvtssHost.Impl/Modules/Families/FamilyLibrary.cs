namespace RvtssHost.Modules;

/// <summary>
/// Family library audit (RVTSS v2.1): port of revit_mcp/family_library.py.
///
/// Route:
///     POST /family/library_audit/   open every .rfa in a folder read-only, inspect, close without saving
///
/// Each family is opened with Application.OpenDocumentFile, inspected (category, size,
/// parameters, types, nested families, warnings, family_validate findings) and closed
/// with Close(False) - nothing is ever saved. Families that are already open in Revit
/// are inspected but left open. dry_run lists the files without opening them.
///
/// The Revit-free part is RvtssHost.Pure.FamilyLibrary (written here as Pure.FamilyLibrary).
/// </summary>
public static class FamilyLibrary
{
    public static void Register(RouteTable api)
    {
        api.Post("/family/library_audit/", LibraryAudit, "library_audit", needsDoc: false);
        Log.Write("RVTSS family library routes registered");
    }

    private static Dict Inspect(DB.Document fdoc, string path)
    {
        var fm = fdoc.FamilyManager;
        var cat = fdoc.OwnerFamily.FamilyCategory;
        var prms = new Lst();
        foreach (DB.FamilyParameter fp in fm.Parameters)
        {
            if (FamilyUtils.IsBuiltin(fp))
                continue;
            prms.Add(new Dict
            {
                ["name"] = Utils.NormalizeString(fp.Definition.Name), ["shared"] = fp.IsShared,
                ["instance"] = fp.IsInstance, ["formula"] = !string.IsNullOrEmpty(fp.Formula),
            });
        }
        var owner = Compat.IdInt(fdoc.OwnerFamily);
        var nested = new DB.FilteredElementCollector(fdoc).OfClass(typeof(DB.Family)).Where(f => Compat.IdInt(f) != owner)
            .Select(f => Utils.NormalizeString(f.Name)).Distinct().OrderBy(x => x, StringComparer.Ordinal).ToList();
        var warnings = fdoc.GetWarnings().Select(w => Utils.NormalizeString(w.GetDescriptionText())).Distinct()
            .OrderBy(x => x, StringComparer.Ordinal).ToList();
        return new Dict
        {
            ["category"] = cat != null ? Utils.NormalizeString(cat.Name) : null, ["parameters"] = prms,
            ["types"] = fm.Types.Cast<DB.FamilyType>().Select(t => Utils.NormalizeString(t.Name)).ToList(),
            ["nested"] = nested, ["warnings"] = warnings,
        };
    }

    private static Dict Validate(DB.Document fdoc)
    {
        var vctx = new Ctx(fdoc, null, new Dict { ["check_dimension_values"] = true }, needsDoc: false);
        var res = Families.FamilyValidate(vctx)!;
        return new Dict { ["summary"] = res.Get("summary"), ["findings"] = PyX.Head(PyX.Items(res.Get("findings")), 20) };
    }

    /// <summary>os.walk(folder): (dirpath, dirnames, filenames), top down; folders that cannot be listed are skipped.</summary>
    private static IEnumerable<(string dirpath, List<string> dirnames, List<string> filenames)> Walk(string top)
    {
        List<string> dirs, files;
        try
        {
            dirs = Directory.GetDirectories(top).Select(Path.GetFileName).ToList()!;
            files = Directory.GetFiles(top).Select(Path.GetFileName).ToList()!;
        }
        catch (Exception)
        {
            yield break;
        }
        yield return (top, dirs, files);
        foreach (var d in dirs)
        {
            foreach (var item in Walk(PyX.Join(top, d)))
                yield return item;
        }
    }

    /// <summary>os.path.getsize</summary>
    private static long GetSize(string path) => new FileInfo(path).Length;

    public static Dict? LibraryAudit(Ctx ctx)
    {
        var folder = Py.Str(ctx.Require("folder", "folder with .rfa files"));
        if (!Directory.Exists(folder))
            throw new RvtssError($"Folder not found: {folder}", status: 404);
        var recursive = ctx.Bool("recursive", true);
        var walk = recursive
            ? Walk(folder)
            : new[] { (folder, new List<string>(), Directory.GetFileSystemEntries(folder).Select(Path.GetFileName).ToList()!) };
        var files = Pure.FamilyLibrary.ListFiles(walk, recursive, folder);
        var containsValue = ctx.Get("name_contains");
        var contains = Py.Truthy(containsValue) ? Py.Str(containsValue).ToLowerInvariant() : "";
        if (contains.Length > 0)
            files = files.Where(f => PyX.Basename(f).ToLowerInvariant().Contains(contains)).ToList();
        var maxFiles = ctx.Int("max_files", 50, 1, 500)!.Value;
        var maxMb = ctx.Float("max_file_mb", 50.0)!.Value;
        var skipped = new Lst();
        var selected = new List<string>();
        foreach (var f in files)
        {
            var sizeMb = GetSize(f) / 1048576.0;
            if (sizeMb > maxMb)
                skipped.Add(new Dict { ["file"] = PyX.Basename(f), ["reason"] = $"larger than {Py.Str(maxMb)} MB" });
            else if (selected.Count < maxFiles)
                selected.Add(f);
            else
                skipped.Add(new Dict { ["file"] = PyX.Basename(f), ["reason"] = $"max_files={maxFiles} reached" });
        }
        if (ctx.DryRun)
            return new Dict
            {
                ["status"] = "dry_run", ["folder"] = folder, ["families_found"] = (long)files.Count,
                ["would_open"] = selected.Select(f => FamilyUtils.Relpath(f, folder)).ToList(), ["skipped"] = skipped.Take(100).ToList(),
                ["total_size_mb"] = Py.Round(selected.Sum(GetSize) / 1048576.0, 1),
                ["note"] = "Families are opened read-only and closed without saving.",
            };

        var app = ctx.App;
        var openDocs = new Dictionary<string, DB.Document>(StringComparer.Ordinal);
        foreach (DB.Document d in app.Documents)
        {
            if (!string.IsNullOrEmpty(d.PathName))
                openDocs[d.PathName.ToLowerInvariant()] = d;
        }
        var records = new Lst();
        var t0 = DateTime.UtcNow;
        var validate = ctx.Bool("validate", true);
        foreach (var path in selected)
        {
            var rec = new Dict { ["file"] = FamilyUtils.Relpath(path, folder), ["path"] = path, ["size_kb"] = GetSize(path) / 1024 };
            openDocs.TryGetValue(path.ToLowerInvariant(), out var fdoc);
            var openedHere = fdoc == null;
            try
            {
                if (openedHere)
                    fdoc = app.OpenDocumentFile(path);
                if (!fdoc!.IsFamilyDocument)
                    throw new RvtssError("not a family document");
                rec.Update(Inspect(fdoc, path));
                if (validate)
                    rec["validation"] = Validate(fdoc);
                if (!openedHere)
                    rec["already_open"] = true;
            }
            catch (Exception e)
            {
                var text = FamilyUtils.ErrText(e);
                rec["error"] = text.Length > 300 ? text.Substring(0, 300) : text;
            }
            finally
            {
                if (openedHere && fdoc != null)
                {
                    try { fdoc.Close(false); }
                    catch (Exception e) { Log.Write($"Could not close {path}: {e.Message}"); }
                }
            }
            records.Add(rec);
        }

        var rules = Core.LoadQcRules().rules;
        var namingRule = (Py.Truthy(rules.Get("naming")) ? FamilyUtils.AsItem(rules.Get("naming")) : new Dict()).Get("families") as Dict;
        var isoValue = Py.Truthy(rules.Get("iso19650")) ? FamilyUtils.AsItem(rules.Get("iso19650")) : new Dict();
        var targets = FamilyUtils.AsItem(isoValue.Get("targets", new Dict()));
        var iso = Py.Truthy(targets.Get("families")) ? rules.Get("iso19650") as Dict : null;
        var findings = Pure.FamilyLibrary.LibraryFindings(records, namingRule, iso, ctx.Int("max_size_kb", 2048)!.Value,
            ctx.Int("max_nested", 10)!.Value);
        return new Dict
        {
            ["folder"] = folder, ["families_found"] = (long)files.Count, ["audited"] = (long)records.Count,
            ["skipped"] = skipped.Take(100).ToList(),
            ["seconds"] = Py.Round((DateTime.UtcNow - t0).TotalSeconds, 1), ["summary"] = Rules.Summarize(findings),
            ["findings"] = findings,
            ["families"] = records.Select(r => Pure.FamilyLibrary.SummaryRow((Dict)r!)).ToList(),
            ["details"] = ctx.Bool("include_details", false) ? records : null,
        };
    }
}
