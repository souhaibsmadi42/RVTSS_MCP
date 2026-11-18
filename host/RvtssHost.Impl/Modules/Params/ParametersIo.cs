namespace RvtssHost.Modules;

// Export / import / map of parameter values (revit_mcp/parameters.py).
public static partial class Parameters
{
    // ------------------------------------------------------------- export/import
    public static Dict? ExportValues(Ctx ctx)
    {
        var doc = ctx.Doc;
        var spec = Query.QuerySpec(ctx.Data);
        if (spec.Count == 0)
            throw new RvtssError("Select elements to export (categories, element_ids, view, ...)");
        var elements = Query.Collect(ctx, spec);
        var names = ctx.List("parameters");
        if (names.Count == 0)
            throw new RvtssError("'parameters' (names to export) is required");
        var mode = ctx.Get("value_mode", "display");
        var displayMode = mode is string ms && ms == "display";
        var unit = ctx.Unit;
        var header = new Lst { "ElementId", "UniqueId", "Category", "Family", "Type" };
        header.AddRange(names);
        var rows = new Lst();
        var columnUnits = new Dict();
        foreach (var e in elements)
        {
            var b = Core.ElementBrief(doc, e);
            var row = new Lst { e.Id.Value, e.UniqueId, b.Get("category"), b.Get("family"), b.Get("type") };
            foreach (var n in names)
            {
                var (p, _) = ParamsUtil.Find(doc, e, n);
                if (p == null)
                {
                    row.Add(null);
                    continue;
                }
                var r = ParamsUtil.Read(doc, p, unit);
                if (Py.Truthy(r.Get("unit")) && !columnUnits.ContainsKey(Py.Str(n)))
                    columnUnits[Py.Str(n)] = r["unit"];
                row.Add(displayMode ? (r.ContainsKey("display") ? r["display"] : r.Get("value")) : r.Get("value"));
            }
            rows.Add(row);
        }
        if (ctx.Get("format") is string fmt && fmt == "json")
        {
            // structured rows for the MCP-side .xlsx export (raw values in column_units)
            var maxRows = ctx.I("max_rows", 20000);
            var jsonOut = new Dict
            {
                ["columns"] = header, ["rows"] = PyX.Head(rows, maxRows), ["row_count"] = (long)rows.Count,
                ["column_units"] = columnUnits, ["value_mode"] = mode, ["unit"] = unit,
            };
            if (rows.Count > maxRows)
                jsonOut["truncated"] = true;
            return jsonOut;
        }
        var text = Csvutil.ToCsv(header, rows);
        var pathValue = ctx.Get("path");
        var path = Py.Truthy(pathValue) ? Py.Str(pathValue) : null;
        if (path != null)
        {
            if (!path.ToLowerInvariant().EndsWith(".csv", StringComparison.Ordinal))
                throw new RvtssError("path must end with .csv");
            if ((File.Exists(path) || Directory.Exists(path)) && !ctx.Bool("overwrite", false))
                throw new RvtssError($"File exists: {path}", status: 409, hint: "Pass overwrite=true.");
            Csvutil.WriteFile(path, text);
        }
        var result = new Dict
        {
            ["rows"] = (long)rows.Count, ["columns"] = header, ["path"] = pathValue, ["value_mode"] = mode, ["unit"] = unit,
            ["column_units"] = columnUnits,
        };
        if (path == null)
        {
            if (text.Length > 200000)
                throw new RvtssError($"Export is too large to return inline ({rows.Count} rows)",
                    hint: "Pass path='C:/.../export.csv' to write a file.");
            result["csv"] = text;
        }
        return result;
    }

    public static Dict? ImportValues(Ctx ctx)
    {
        var doc = ctx.Doc;
        var textValue = ctx.Get("csv_text");
        var pathValue = ctx.Get("path");
        string text;
        if (Py.Truthy(textValue))
        {
            text = Py.Str(textValue);
        }
        else
        {
            if (!Py.Truthy(pathValue) || !File.Exists(Py.Str(pathValue)))
                throw new RvtssError("Pass csv_text or an existing path");
            text = Csvutil.ReadFile(Py.Str(pathValue));
        }
        var (header, rows) = Csvutil.ParseCsv(text);
        if (!header.Contains("ElementId") && !header.Contains("UniqueId"))
            throw new RvtssError("CSV needs an ElementId or UniqueId column");
        var skip = new HashSet<string>(new[] { "ElementId", "UniqueId", "Category", "Family", "Type" }, StringComparer.Ordinal);
        var columns = header.Where(h => !skip.Contains(h) && !PyX.In(h, ctx.List("ignore_columns"))).ToList();
        var units = ctx.Get("units") as Dict ?? new Dict();
        var preview = Core.ConfirmGate(ctx, rows.Count, "import_parameter_values");
        var skipEmpty = ctx.Bool("skip_empty", true);

        Dict One(object? item)
        {
            var row = (Dict)item!;
            DB.Element? e = null;
            if (Py.Truthy(row.Get("UniqueId")))
                e = doc.GetElement(Py.Str(row["UniqueId"]));
            if (e == null && Py.Truthy(row.Get("ElementId")))
                e = Core.GetElement(doc, Py.ToInt(row["ElementId"]));
            if (e == null)
                throw new RvtssError($"Row element not found: {Py.Str(Py.Truthy(row.Get("ElementId")) ? row.Get("ElementId") : row.Get("UniqueId"))}",
                    status: 404);
            var changed = new Lst();
            foreach (var col in columns)
            {
                var val = row.Get(col) as string;
                if (skipEmpty && string.IsNullOrEmpty(val))
                    continue;
                var (p, _) = ParamsUtil.Find(doc, e, col, allowType: ctx.Bool("allow_type", false));
                if (p == null)
                    throw new RvtssError($"Element {e.Id.Value} has no parameter '{col}'", status: 404);
                if (p.IsReadOnly)
                    continue;
                var before = ParamsUtil.Read(doc, p, "mm");
                var beforeV = before.ContainsKey("display") ? before["display"] : before.Get("value");
                if (Py.Str(beforeV) == val)
                    continue;
                var u = units.Get(col);
                var unitText = Py.Truthy(u) ? Py.Str(u) : null;
                var after = ParamsUtil.SetValue(doc, p, unitText != null ? (object?)Py.ToFloat(val) : val, unitText);
                changed.Add(new Dict
                {
                    ["parameter"] = col, ["before"] = beforeV,
                    ["after"] = after.ContainsKey("display") ? after["display"] : after.Get("value"),
                });
            }
            return new Dict { ["element_id"] = e.Id.Value, ["changes"] = changed };
        }

        var dry = preview || ctx.DryRun;
        var atomic = ctx.Bool("atomic", false);
        var (res, fails) = Core.RunTransaction<Lst>(doc, "Import parameter values",
            () => Core.Batch(doc, rows.Cast<object?>(), One, atomic), dry);
        var changedRows = res.Where(r => Py.Truthy(((Dict)r!).Get("changes"))).ToList();
        var failed = res.Where(r => !Py.Truthy(((Dict)r!)["ok"])).ToList();
        var result = Core.CommitResult(new Dict
        {
            ["rows"] = (long)rows.Count, ["rows_changed"] = (long)changedRows.Count,
            ["failed"] = PyX.Head(failed, 100),
            ["changes"] = PyX.Head(changedRows, ctx.I("max_results", 100)),
        }, fails, dry);
        return Core.PreviewStatus(result, preview);
    }

    /// <summary>Office presets: %APPDATA%/RVTSS/presets/&lt;name&gt;.json -> {name: {description, mappings}}.</summary>
    internal static Dict UserPresets()
    {
        var folder = Path.Combine(Core.RvtssHome(), "presets");
        var result = new Dict();
        if (!Directory.Exists(folder))
            return result;
        foreach (var f in Directory.GetFiles(folder).OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
        {
            if (!f.ToLowerInvariant().EndsWith(".json", StringComparison.Ordinal))
                continue;
            try
            {
                result[Path.GetFileNameWithoutExtension(f)] = Py.JsonLoads(File.ReadAllText(f, new UTF8Encoding(false)));
            }
            catch (Exception e)
            {
                Log.Write($"Invalid mapping preset {Path.GetFileName(f)}: {e.Message}");
            }
        }
        return result;
    }

    private static bool IsEmptyTarget(object? v) =>
        v == null || (v is string s && s.Length == 0) || (v is bool b && !b) || (Py.IsNum(v) && Py.ToFloat(v) == 0.0);

    public static Dict? MapValues(Ctx ctx)
    {
        var doc = ctx.Doc;
        var mappings = ctx.List("mappings");
        var preset = ctx.Get("preset");
        if (Py.Truthy(preset))
        {
            try
            {
                var combined = new Lst();
                foreach (var m in MappingPresets.GetPreset(Py.Str(preset), UserPresets()))
                    combined.Add(m);
                combined.AddRange(mappings);
                mappings = combined;
            }
            catch (PresetError e)
            {
                throw new RvtssError(e.Message, status: 404);
            }
        }
        if (mappings.Count == 0)
            throw new RvtssError("'mappings' or 'preset' is required: [{from: 'Old Name', to: 'New Name'}]",
                hint: "Presets: " + string.Join(", ", MappingPresets.Presets.Keys.OrderBy(x => x, StringComparer.Ordinal)));
        var data = new Dict(ctx.Data);
        if (Py.Truthy(preset) && Query.QuerySpec(data).Count == 0)
        {
            // select the preset's categories only when every mapping is category-limited
            var cats = MappingPresets.PresetCategories(mappings);
            if (cats.Count == 0 || mappings.Any(m => !Py.Truthy(((Dict)m!).Get("categories"))))
                throw new RvtssError($"Preset '{Py.Str(preset)}' applies to all categories: select elements (categories, ...)");
            data["categories"] = cats;
        }
        var spec = Query.QuerySpec(data);
        if (spec.Count == 0)
            throw new RvtssError("Select elements (categories, element_ids, ...)");
        var elements = Query.Collect(ctx, spec);
        var preview = Core.ConfirmGate(ctx, elements.Count, "map_parameters");
        var onlyEmpty = ctx.Bool("only_empty_target", false);

        Dict One(object? item)
        {
            var e = (DB.Element)item!;
            var changes = new Lst();
            var skipped = new Lst();
            var cat = e.Category != null ? e.Category.Name : null;
            foreach (var mo in mappings)
            {
                var m = (Dict)mo!;
                if (!MappingPresets.Applies(m, cat))
                    continue;
                var (src, _) = ParamsUtil.Find(doc, e, PyX.Item(m, "from"));
                var (dst, _2) = ParamsUtil.Find(doc, e, PyX.Item(m, "to"),
                    allowType: Py.Truthy(m.Get("allow_type", ctx.Bool("allow_type", false))));
                if (src == null || dst == null)
                {
                    skipped.Add(new Dict { ["mapping"] = m, ["reason"] = src == null ? "source missing" : "target missing" });
                    continue;
                }
                if (dst.IsReadOnly)
                {
                    skipped.Add(new Dict { ["mapping"] = m, ["reason"] = "target read-only" });
                    continue;
                }
                var cur = ParamsUtil.Read(doc, dst, "mm");
                if (onlyEmpty && !IsEmptyTarget(cur.Get("value")))
                {
                    skipped.Add(new Dict { ["mapping"] = m, ["reason"] = "target has a value" });
                    continue;
                }
                if (src.StorageType == dst.StorageType)
                {
                    if (src.StorageType == DB.StorageType.Double)
                        dst.Set(src.AsDouble());
                    else if (src.StorageType == DB.StorageType.Integer)
                        dst.Set(src.AsInteger());
                    else if (src.StorageType == DB.StorageType.String)
                        dst.Set(src.AsString() ?? "");
                    else
                        dst.Set(src.AsElementId());
                }
                else
                {
                    var vs = src.AsValueString();
                    var v = !string.IsNullOrEmpty(vs) ? vs : src.AsString();
                    ParamsUtil.SetValue(doc, dst, v ?? "", null);
                }
                var after = ParamsUtil.Read(doc, dst, ctx.Unit);
                changes.Add(new Dict
                {
                    ["from"] = m["from"], ["to"] = m["to"],
                    ["value"] = Py.Truthy(after.Get("display")) ? after.Get("display") : after.Get("value"),
                });
            }
            return new Dict { ["element_id"] = e.Id.Value, ["changes"] = changes, ["skipped"] = skipped };
        }

        var dry = preview || ctx.DryRun;
        var atomic = ctx.Bool("atomic", false);
        var (res, fails) = Core.RunTransaction<Lst>(doc, "Map parameters",
            () => Core.Batch(doc, elements.Cast<object?>(), One, atomic), dry);
        var summary = new Dict
        {
            ["elements"] = (long)elements.Count,
            ["changed"] = (long)res.Count(r => Py.Truthy(((Dict)r!).Get("changes"))),
            ["results"] = PyX.Head(res, ctx.I("max_results", 100)),
        };
        if (Py.Truthy(preset))
        {
            summary["preset"] = preset;
            summary["unverified_targets"] = mappings.Where(m => ((Dict)m!).Get("verified") is bool vb && !vb)
                .Select(m => ((Dict)m!)["to"]).ToList();
        }
        var result = Core.CommitResult(summary, fails, dry);
        return Core.PreviewStatus(result, preview);
    }
}
