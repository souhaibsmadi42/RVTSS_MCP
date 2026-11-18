namespace RvtssHost.Modules;

/// <summary>
/// Rule-based view filters and revisions: port of revit_mcp/graphics.py (RVTSS v2.2).
///
/// Routes:
///     POST /views/filters/      list filters (rules, where used), create rule-based filters, apply to views /
///                               templates with visibility and overrides, remove, delete
///     POST /sheets/revisions/   list revisions (with sheets), create, assign / unassign to sheets, mark issued
/// </summary>
public static class Graphics
{
    public static void Register(RouteTable api)
    {
        api.Post("/views/filters/", ViewFilters, "view_filters");
        api.Post("/sheets/revisions/", Revisions, "revisions");
    }

    private static List<DB.ElementId> IdList(IEnumerable<DB.ElementId> ids) => new(ids);

    // ---------------------------------------------------------------- view filters
    private static string ParamLabel(DB.Document doc, DB.ElementId pid)
    {
        var v = pid.Value;
        if (v < 0)
        {
            try
            {
                var bip = (DB.BuiltInParameter)(int)v;
                return Utils.NormalizeString(DB.LabelUtils.GetLabelFor(bip));
            }
            catch
            {
                return Py.Str(v);
            }
        }
        var e = doc.GetElement(pid);
        return e != null ? Utils.NormalizeString(e.Name) : Py.Str(v);
    }

    /// <summary>{lower-case label / BuiltInParameter name: ElementId} common to the categories.</summary>
    private static Dictionary<string, DB.ElementId> Filterable(DB.Document doc, List<DB.ElementId> catIds)
    {
        var output = new Dictionary<string, DB.ElementId>();
        foreach (var pid in DB.ParameterFilterUtilities.GetFilterableParametersInCommon(doc, IdList(catIds)))
        {
            output[ParamLabel(doc, pid).ToLowerInvariant()] = pid;
            if (pid.Value < 0)
            {
                try
                {
                    output[((DB.BuiltInParameter)(int)pid.Value).ToString().ToLowerInvariant()] = pid;
                }
                catch
                {
                    // no built-in name
                }
            }
        }
        return output;
    }

    private static DB.ElementId RuleParameter(DB.Document doc, object? name, Dictionary<string, DB.ElementId> filterable)
    {
        var key = DocsPy.Key(name);
        if (filterable.TryGetValue(key, out var pid))
            return pid;
        throw Core.NotFound("Filterable parameter (common to all the filter's categories)", name,
            filterable.Values.Select(p => ParamLabel(doc, p)).Distinct().OrderBy(x => x, StringComparer.Ordinal).Cast<string?>().ToList(),
            hint: "A filter rule can only use a parameter every chosen category has.");
    }

    /// <summary>(StorageType name, unit kind) of a filter parameter, read from one element of the categories.</summary>
    private static (string? storage, string? kind) ParamStorage(DB.Document doc, List<DB.ElementId> catIds, DB.ElementId pid)
    {
        foreach (var cid in catIds)
        {
            foreach (var col in new[]
                     {
                         new DB.FilteredElementCollector(doc).OfCategoryId(cid).WhereElementIsNotElementType(),
                         new DB.FilteredElementCollector(doc).OfCategoryId(cid).WhereElementIsElementType(),
                     })
            {
                foreach (var e in col)
                {
                    DB.Parameter? p = null;
                    try
                    {
                        if (pid.Value < 0)
                        {
                            p = e.get_Parameter((DB.BuiltInParameter)(int)pid.Value);
                        }
                        else
                        {
                            foreach (DB.Parameter q in e.Parameters)
                            {
                                if (q.Id == pid)
                                {
                                    p = q;
                                    break;
                                }
                            }
                        }
                    }
                    catch
                    {
                        p = null;
                    }
                    if (p != null)
                    {
                        var (_, kind) = Compat.DefinitionSpec(p.Definition);
                        return (p.StorageType.ToString(), kind);
                    }
                    break; // the first element of a category is representative
                }
            }
        }
        return (null, null);
    }

    /// <summary>Fit the rule's value type and unit to the parameter: doubles in project units, mm by default.</summary>
    private static Dict AdaptRule(DB.Document doc, List<DB.ElementId> catIds, DB.ElementId pid, Dict rule, string defaultUnit,
        Action<string> warn)
    {
        var r = new Dict(rule);
        var (storage, kind) = ParamStorage(doc, catIds, pid);
        var rkind = r["kind"] as string;
        if ((rkind == "integer" || rkind == "double") && storage == "Double")
        {
            r["kind"] = "double";
            r["value"] = Py.ToFloat(r["value"]);
            if (kind == "length" || kind == "area" || kind == "volume" || kind == "angle" || kind == "measurable")
            {
                var baseKind = kind != "measurable" ? kind : "length";
                r["unit"] = Units.LengthUnitFor(baseKind, Py.Truthy(r.Get("unit")) ? Py.Str(r["unit"]) : defaultUnit);
            }
            else
            {
                r["unit"] = r.Get("unit"); // plain number: no conversion unless a unit was given
            }
        }
        else if (rkind == "double" && storage == "Integer" && !Py.Truthy(r.Get("unit")))
        {
            r["kind"] = "integer";
            r["value"] = Py.ToInt(r["value"]);
        }
        else if (rkind == "integer" && storage == "ElementId")
        {
            r["kind"] = "element_id";
        }
        else if (storage == null && rkind == "double")
        {
            r["unit"] = Py.Truthy(r.Get("unit")) ? r["unit"] : defaultUnit;
            warn($"Could not sample parameter '{Py.Str(r["parameter"])}' on the categories; the value was read as a length in {Py.Str(r["unit"])}.");
        }
        return r;
    }

    private static DB.FilterRule? StringRule(string op, DB.ElementId pid, string v) => op switch
    {
        "equals" => DB.ParameterFilterRuleFactory.CreateEqualsRule(pid, v),
        "not_equals" => DB.ParameterFilterRuleFactory.CreateNotEqualsRule(pid, v),
        "contains" => DB.ParameterFilterRuleFactory.CreateContainsRule(pid, v),
        "not_contains" => DB.ParameterFilterRuleFactory.CreateNotContainsRule(pid, v),
        "begins_with" => DB.ParameterFilterRuleFactory.CreateBeginsWithRule(pid, v),
        "not_begins_with" => DB.ParameterFilterRuleFactory.CreateNotBeginsWithRule(pid, v),
        "ends_with" => DB.ParameterFilterRuleFactory.CreateEndsWithRule(pid, v),
        "not_ends_with" => DB.ParameterFilterRuleFactory.CreateNotEndsWithRule(pid, v),
        "greater" => DB.ParameterFilterRuleFactory.CreateGreaterRule(pid, v),
        "greater_or_equal" => DB.ParameterFilterRuleFactory.CreateGreaterOrEqualRule(pid, v),
        "less" => DB.ParameterFilterRuleFactory.CreateLessRule(pid, v),
        "less_or_equal" => DB.ParameterFilterRuleFactory.CreateLessOrEqualRule(pid, v),
        _ => null,
    };

    private static DB.FilterRule? DoubleRule(string op, DB.ElementId pid, double v, double eps) => op switch
    {
        "equals" => DB.ParameterFilterRuleFactory.CreateEqualsRule(pid, v, eps),
        "not_equals" => DB.ParameterFilterRuleFactory.CreateNotEqualsRule(pid, v, eps),
        "greater" => DB.ParameterFilterRuleFactory.CreateGreaterRule(pid, v, eps),
        "greater_or_equal" => DB.ParameterFilterRuleFactory.CreateGreaterOrEqualRule(pid, v, eps),
        "less" => DB.ParameterFilterRuleFactory.CreateLessRule(pid, v, eps),
        "less_or_equal" => DB.ParameterFilterRuleFactory.CreateLessOrEqualRule(pid, v, eps),
        _ => null,
    };

    private static DB.FilterRule? IdRule(string op, DB.ElementId pid, DB.ElementId v) => op switch
    {
        "equals" => DB.ParameterFilterRuleFactory.CreateEqualsRule(pid, v),
        "not_equals" => DB.ParameterFilterRuleFactory.CreateNotEqualsRule(pid, v),
        "greater" => DB.ParameterFilterRuleFactory.CreateGreaterRule(pid, v),
        "greater_or_equal" => DB.ParameterFilterRuleFactory.CreateGreaterOrEqualRule(pid, v),
        "less" => DB.ParameterFilterRuleFactory.CreateLessRule(pid, v),
        "less_or_equal" => DB.ParameterFilterRuleFactory.CreateLessOrEqualRule(pid, v),
        _ => null,
    };

    private static DB.FilterRule? IntRule(string op, DB.ElementId pid, int v) => op switch
    {
        "equals" => DB.ParameterFilterRuleFactory.CreateEqualsRule(pid, v),
        "not_equals" => DB.ParameterFilterRuleFactory.CreateNotEqualsRule(pid, v),
        "greater" => DB.ParameterFilterRuleFactory.CreateGreaterRule(pid, v),
        "greater_or_equal" => DB.ParameterFilterRuleFactory.CreateGreaterOrEqualRule(pid, v),
        "less" => DB.ParameterFilterRuleFactory.CreateLessRule(pid, v),
        "less_or_equal" => DB.ParameterFilterRuleFactory.CreateLessOrEqualRule(pid, v),
        _ => null,
    };

    private static DB.FilterRule MakeRule(DB.Document doc, DB.ElementId pid, Dict r)
    {
        var op = Py.Str(r["op"]);
        var kind = r.Get("kind") as string;
        var value = r.Get("value");
        DB.FilterRule? rule;
        if (kind == null)
        {
            rule = op == "has_value" ? DB.ParameterFilterRuleFactory.CreateHasValueParameterRule(pid)
                : op == "has_no_value" ? DB.ParameterFilterRuleFactory.CreateHasNoValueParameterRule(pid) : null;
        }
        else if (kind == "string")
        {
            rule = StringRule(op, pid, Py.Str(value));
        }
        else if (kind == "double")
        {
            var v = Py.Truthy(r.Get("unit")) ? Units.ToInternal(Py.ToFloat(value), Py.Str(r["unit"])) : Py.ToFloat(value);
            rule = DoubleRule(op, pid, v, 1e-6);
        }
        else if (kind == "element_id")
        {
            rule = IdRule(op, pid, Compat.MakeId(value));
        }
        else
        {
            rule = IntRule(op, pid, (int)Py.ToInt(value));
        }
        if (rule == null)
            throw new RvtssError($"Rule op '{op}' is not available in this Revit version", status: 501,
                hint: "has_value / has_no_value rules need Revit 2023+.");
        return rule;
    }

    private static DB.OverrideGraphicSettings Ogs(DB.Document doc, object? specObj)
    {
        var spec = DocsPy.D(specObj);
        var ogs = new DB.OverrideGraphicSettings();
        if (Py.Truthy(spec.Get("color")))
        {
            var c = Documentation.Color(spec["color"]);
            ogs.SetProjectionLineColor(c);
            ogs.SetCutLineColor(c);
            var fill = Documentation.SolidFill(doc);
            if (fill != null && Py.Truthy(spec.Get("fill", true)))
            {
                ogs.SetSurfaceForegroundPatternId(fill);
                ogs.SetSurfaceForegroundPatternColor(c);
                ogs.SetCutForegroundPatternId(fill);
                ogs.SetCutForegroundPatternColor(c);
            }
        }
        if (Py.Truthy(spec.Get("line_weight")))
            ogs.SetProjectionLineWeight((int)Math.Max(1, Math.Min(16, Py.ToInt(spec["line_weight"]))));
        if (spec.Get("halftone") != null)
            ogs.SetHalftone(Py.Truthy(spec["halftone"]));
        if (spec.Get("transparency") != null)
            ogs.SetSurfaceTransparency((int)Math.Max(0, Math.Min(100, Py.ToInt(spec["transparency"]))));
        return ogs;
    }

    private static DB.ParameterFilterElement FindFilter(DB.Document doc, object? nameOrId)
    {
        var filters = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ParameterFilterElement))
            .Cast<DB.ParameterFilterElement>().ToList();
        var s = Py.Str(nameOrId).Trim();
        foreach (var f in filters)
        {
            if (Utils.NormalizeString(f.Name).ToLowerInvariant() == s.ToLowerInvariant() || Py.Str(f.Id.Value) == s)
                return f;
        }
        throw Core.NotFound("View filter", nameOrId, filters.Select(f => (string?)f.Name));
    }

    private static Dict DescribeFilter(DB.Document doc, DB.ParameterFilterElement f, Dictionary<long, Lst> usage)
    {
        var d = new Dict
        {
            ["id"] = f.Id.Value, ["name"] = Utils.NormalizeString(f.Name),
            ["categories"] = f.GetCategories().Where(c => DB.Category.GetCategory(doc, c) != null)
                .Select(c => (object?)Utils.NormalizeString(DB.Category.GetCategory(doc, c).Name)).ToList(),
        };
        try
        {
            var ef = f.GetElementFilter();
            d["logic"] = ef != null ? ef.GetType().Name : null;
            var rules = new Lst();
            var subs = new List<DB.ElementFilter?> { ef };
            try
            {
                if (ef is DB.LogicalAndFilter and1)
                    subs = and1.GetFilters().Cast<DB.ElementFilter?>().ToList();
                else if (ef is DB.LogicalOrFilter or1)
                    subs = or1.GetFilters().Cast<DB.ElementFilter?>().ToList();
            }
            catch
            {
                // not a logical filter
            }
            foreach (var sub in subs)
            {
                try
                {
                    if (sub is not DB.ElementParameterFilter epf)
                        throw new DocsPy.AttributeError("GetRules");
                    foreach (var rule in epf.GetRules())
                    {
                        var rd = new Dict
                        {
                            ["parameter"] = ParamLabel(doc, rule.GetRuleParameter()), ["rule"] = rule.GetType().Name,
                        };
                        try
                        {
                            object? ev = rule is DB.FilterStringRule sr ? sr.GetEvaluator()
                                : rule is DB.FilterNumericValueRule nr ? nr.GetEvaluator() : null;
                            if (ev != null)
                                rd["evaluator"] = ev.GetType().Name;
                        }
                        catch
                        {
                            // no evaluator
                        }
                        var missing = new object();
                        foreach (var attr in new[] { "RuleString", "RuleValue" })
                        {
                            try
                            {
                                var value = Py.GetAttr(rule, attr, missing);
                                if (ReferenceEquals(value, missing))
                                    continue;
                                rd["value"] = Py.Str(value);
                                break;
                            }
                            catch
                            {
                                continue;
                            }
                        }
                        rules.Add(rd);
                    }
                }
                catch
                {
                    continue;
                }
            }
            d["rules"] = rules;
        }
        catch
        {
            d["rules"] = null;
        }
        d["used_in"] = usage.TryGetValue(f.Id.Value, out var used) ? used : new Lst();
        return d;
    }

    private static Dictionary<long, Lst> Usage(DB.Document doc)
    {
        var output = new Dictionary<long, Lst>();
        foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
        {
            ICollection<DB.ElementId> fids;
            try
            {
                fids = v.GetFilters();
            }
            catch
            {
                continue;
            }
            foreach (var fid in fids)
            {
                bool? vis;
                try
                {
                    vis = v.GetFilterVisibility(fid);
                }
                catch
                {
                    vis = null;
                }
                if (!output.TryGetValue(fid.Value, out var list))
                    output[fid.Value] = list = new Lst();
                list.Add(new Dict
                {
                    ["view_id"] = v.Id.Value, ["view"] = Utils.NormalizeString(v.Name), ["is_template"] = v.IsTemplate, ["visible"] = vis,
                });
            }
        }
        return output;
    }

    public static Dict? ViewFilters(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var usage = Usage(doc);
            var outList = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ParameterFilterElement))
                .Cast<DB.ParameterFilterElement>().Select(f => DescribeFilter(doc, f, usage)).ToList();
            var contains = Py.Truthy(ctx.Get("contains")) ? Py.Str(ctx.Get("contains")).ToLowerInvariant() : "";
            if (contains.Length > 0)
                outList = outList.Where(d => ((string)d["name"]!).ToLowerInvariant().IndexOf(contains, StringComparison.Ordinal) >= 0).ToList();
            outList = outList.OrderBy(d => ((string)d["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
            return new Dict
            {
                ["count"] = outList.Count, ["filters"] = outList,
                ["unused"] = outList.Where(d => !Py.Truthy(d["used_in"])).Select(d => d["name"]).ToList(),
            };
        }
        var dry = ctx.DryRun;

        Dict Run()
        {
            if (action == "create")
            {
                var name = Py.Str(ctx.Require("name"));
                if (!DB.ParameterFilterElement.IsNameUnique(doc, name))
                    throw new RvtssError($"A filter named '{name}' already exists", status: 409);
                var cats = ctx.List("categories").Select(c => Core.ResolveCategory(doc, c)).ToList();
                if (cats.Count == 0)
                    throw new RvtssError("create needs categories");
                var catIds = cats.Select(c => c.Id).ToList();
                var rulesIn = ctx.List("rules");
                if (rulesIn.Count == 0)
                    throw new RvtssError("create needs rules: [{parameter, op, value, unit?}]",
                        hint: "ops: " + string.Join(", ", FilterRules.AllOps));
                var filterable = Filterable(doc, catIds);
                var rules = new List<DB.FilterRule>();
                foreach (var r in rulesIn)
                {
                    Dict nr;
                    try
                    {
                        nr = FilterRules.ValidateRule(r);
                    }
                    catch (RuleError e)
                    {
                        throw new RvtssError(e.Message);
                    }
                    var pid = RuleParameter(doc, nr["parameter"], filterable);
                    nr = AdaptRule(doc, catIds, pid, nr, ctx.Unit, ctx.Warn);
                    rules.Add(MakeRule(doc, pid, nr));
                }
                DB.ElementFilter ef;
                if (ctx.Get("logic", "and") is string logic && logic == "or")
                {
                    var subs = new List<DB.ElementFilter>();
                    foreach (var rule in rules)
                        subs.Add(new DB.ElementParameterFilter(rule));
                    ef = new DB.LogicalOrFilter(subs);
                }
                else
                {
                    ef = new DB.ElementParameterFilter(rules);
                }
                var f = DB.ParameterFilterElement.Create(doc, name, IdList(catIds), ef);
                var created = new Dict { ["filter_id"] = f.Id.Value, ["name"] = Utils.NormalizeString(f.Name), ["rules"] = rules.Count };
                if (ctx.List("apply_to").Count > 0)
                    created["applied"] = ctx.List("apply_to").Select(v => (object?)Apply(doc, ctx, f, v)).ToList();
                return created;
            }
            var filter = FindFilter(doc, ctx.Require("filter"));
            if (action == "apply")
            {
                var views = ctx.List("apply_to");
                if (views.Count == 0)
                    views = new Lst { ctx.Get("view", "active") };
                return new Dict
                {
                    ["filter"] = Utils.NormalizeString(filter.Name),
                    ["applied"] = views.Select(v => (object?)Apply(doc, ctx, filter, v)).ToList(),
                };
            }
            if (action == "remove")
            {
                var done = new Lst();
                var targets = ctx.List("apply_to");
                if (targets.Count == 0)
                    targets = new Lst { ctx.Get("view", "active") };
                foreach (var vname in targets)
                {
                    var v = ViewOrTemplate(doc, ctx, vname);
                    if (v.GetFilters().Contains(filter.Id))
                    {
                        v.RemoveFilter(filter.Id);
                        done.Add(Utils.NormalizeString(v.Name));
                    }
                }
                return new Dict { ["filter"] = Utils.NormalizeString(filter.Name), ["removed_from"] = done };
            }
            if (action == "delete")
            {
                if (!ctx.Confirmed)
                    throw new RvtssError("Deleting a filter removes it from every view and template; pass confirm=true", status: 409)
                        .With("used_in", Usage(doc).TryGetValue(filter.Id.Value, out var used) ? used : new Lst());
                var name = Utils.NormalizeString(filter.Name);
                doc.Delete(filter.Id);
                return new Dict { ["deleted"] = name };
            }
            throw new RvtssError("action must be list, create, apply, remove or delete");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "View filters: " + action, Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    private static DB.View ViewOrTemplate(DB.Document doc, Ctx ctx, object? name)
    {
        if (name == null || (name is string s && (s == "" || s == "active")))
            return Core.FindView(doc, "active", uidoc: ctx.UiDoc)!;
        foreach (DB.View v in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)))
        {
            if (v.IsTemplate && (Utils.NormalizeString(v.Name).ToLowerInvariant() == Py.Str(name).ToLowerInvariant()
                                 || Py.Str(v.Id.Value) == Py.Str(name)))
                return v;
        }
        return Core.FindView(doc, name)!;
    }

    private static Dict Apply(DB.Document doc, Ctx ctx, DB.ParameterFilterElement f, object? vname)
    {
        var v = ViewOrTemplate(doc, ctx, vname);
        if (!v.IsTemplate && Compat.IsValidId(v.ViewTemplateId))
        {
            var tpl = doc.GetElement(v.ViewTemplateId);
            ctx.Warn($"View '{Utils.NormalizeString(v.Name)}' uses template '{Utils.NormalizeString(tpl.Name)}': filters may be "
                     + "controlled by the template - apply to the template instead.");
        }
        if (!v.IsFilterApplied(f.Id))
            v.AddFilter(f.Id);
        var vis = ctx.Get("visible");
        if (vis != null)
            v.SetFilterVisibility(f.Id, Py.Truthy(vis));
        var ov = ctx.Get("overrides");
        if (Py.Truthy(ov))
            v.SetFilterOverrides(f.Id, Ogs(doc, ov));
        return new Dict
        {
            ["view_id"] = v.Id.Value, ["view"] = Utils.NormalizeString(v.Name), ["is_template"] = v.IsTemplate,
            ["visible"] = v.GetFilterVisibility(f.Id),
        };
    }

    // -------------------------------------------------------------------- revisions
    private static (List<DB.ViewSheet> sheets, Dictionary<string, DB.ViewSheet> byNumber) SheetsByKey(DB.Document doc)
    {
        var sheets = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewSheet)).Cast<DB.ViewSheet>()
            .Where(s => !s.IsTemplate).ToList();
        var byNumber = new Dictionary<string, DB.ViewSheet>();
        foreach (var s in sheets)
            byNumber[Utils.NormalizeString(s.SheetNumber).ToLowerInvariant()] = s;
        return (sheets, byNumber);
    }

    private static List<DB.ViewSheet> ResolveSheets(DB.Document doc, IEnumerable<object?> keys)
    {
        var (sheets, byNum) = SheetsByKey(doc);
        var output = new List<DB.ViewSheet>();
        foreach (var k in keys)
        {
            byNum.TryGetValue(DocsPy.Key(k), out var s);
            if (s == null && DocsPy.IsDigits(k))
            {
                var e = doc.GetElement(Compat.MakeId(Py.ToInt(Py.Str(k))));
                s = e as DB.ViewSheet;
            }
            if (s == null)
                throw Core.NotFound("Sheet", k, sheets.Select(x => (string?)x.SheetNumber));
            output.Add(s);
        }
        return output;
    }

    private static DB.Revision FindRevision(DB.Document doc, object? key)
    {
        var revs = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Revision)).Cast<DB.Revision>().ToList();
        var s = Py.Str(key).Trim();
        foreach (var r in revs)
        {
            if (Py.Str(r.Id.Value) == s || Utils.NormalizeString(r.Description ?? "").ToLowerInvariant() == s.ToLowerInvariant()
                || Py.Str(r.SequenceNumber) == s)
                return r;
        }
        throw Core.NotFound("Revision (id, sequence number or description)", key,
            revs.Select(r => (string?)$"{r.SequenceNumber} {r.Description}"));
    }

    private static Dict DescribeRevision(DB.Revision r, Dictionary<long, List<string>>? sheetsByRev)
    {
        var d = new Dict
        {
            ["id"] = r.Id.Value, ["sequence"] = r.SequenceNumber, ["number"] = Utils.NormalizeString(r.RevisionNumber ?? ""),
            ["date"] = Utils.NormalizeString(r.RevisionDate ?? ""), ["description"] = Utils.NormalizeString(r.Description ?? ""),
            ["issued"] = r.Issued, ["issued_to"] = Utils.NormalizeString(r.IssuedTo ?? ""),
            ["issued_by"] = Utils.NormalizeString(r.IssuedBy ?? ""), ["visibility"] = r.Visibility.ToString(),
        };
        if (sheetsByRev != null)
            d["sheets"] = (sheetsByRev.TryGetValue(r.Id.Value, out var l) ? l : new List<string>())
                .OrderBy(x => x, StringComparer.Ordinal).Cast<object?>().ToList();
        return d;
    }

    private static void SetRevisionFields(Ctx ctx, DB.Revision r)
    {
        if (ctx.Get("description") != null)
            r.Description = Py.Str(ctx.Get("description"));
        if (ctx.Get("date") != null)
            r.RevisionDate = Py.Str(ctx.Get("date"));
        if (ctx.Get("issued_to") != null)
            r.IssuedTo = Py.Str(ctx.Get("issued_to"));
        if (ctx.Get("issued_by") != null)
            r.IssuedBy = Py.Str(ctx.Get("issued_by"));
    }

    public static Dict? Revisions(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "list"));
        if (action == "list")
        {
            var (sheets, _) = SheetsByKey(doc);
            var byRev = new Dictionary<long, List<string>>();
            foreach (var s in sheets)
            {
                try
                {
                    foreach (var rid in s.GetAllRevisionIds())
                    {
                        if (!byRev.TryGetValue(rid.Value, out var l))
                            byRev[rid.Value] = l = new List<string>();
                        l.Add(Utils.NormalizeString(s.SheetNumber));
                    }
                }
                catch
                {
                    continue;
                }
            }
            var revs = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Revision)).Cast<DB.Revision>()
                .OrderBy(r => r.SequenceNumber).ToList();
            return new Dict
            {
                ["count"] = revs.Count, ["revisions"] = revs.Select(r => (object?)DescribeRevision(r, byRev)).ToList(),
            };
        }
        var dry = ctx.DryRun;

        Dict Run()
        {
            if (action == "create")
            {
                var r = DB.Revision.Create(doc);
                SetRevisionFields(ctx, r);
                var created = new Dict { ["revision"] = DescribeRevision(r, null) };
                if (ctx.List("sheets").Count > 0)
                    created["assigned"] = Assign(doc, new List<DB.Revision> { r }, ResolveSheets(doc, ctx.List("sheets")), true);
                return created;
            }
            var rev = FindRevision(doc, ctx.Require("revision"));
            if (action == "assign" || action == "unassign")
            {
                var sheets = ResolveSheets(doc, ctx.List("sheets"));
                if (sheets.Count == 0)
                    throw new RvtssError($"{action} needs sheets (numbers or ids)");
                var assigned = new Dict
                {
                    ["revision"] = DescribeRevision(rev, null),
                    [action + "ed"] = Assign(doc, new List<DB.Revision> { rev }, sheets, action == "assign"),
                };
                if (action == "unassign")
                {
                    var still = sheets.Where(s => s.GetAllRevisionIds().Contains(rev.Id))
                        .Select(s => Utils.NormalizeString(s.SheetNumber)).ToList();
                    if (still.Count > 0)
                    {
                        assigned["still_shown_by_clouds"] = still.Cast<object?>().ToList();
                        ctx.Warn($"The revision stays on {string.Join(", ", still)} because revision clouds in views on those sheets "
                                 + "use it; delete or change the clouds to remove it.");
                    }
                }
                return assigned;
            }
            if (action == "issue")
            {
                rev.Issued = true;
                return new Dict
                {
                    ["revision"] = DescribeRevision(rev, null),
                    ["note"] = "Issued revisions are locked: clouds and fields can no longer be edited.",
                };
            }
            if (action == "update")
            {
                if (rev.Issued)
                    throw new RvtssError("Revision is issued (locked); set issued=false in Revit first", status: 409);
                SetRevisionFields(ctx, rev);
                return new Dict { ["revision"] = DescribeRevision(rev, null) };
            }
            throw new RvtssError("action must be list, create, update, assign, unassign or issue");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Revisions: " + action, Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    private static Lst Assign(DB.Document doc, List<DB.Revision> revs, List<DB.ViewSheet> sheets, bool add)
    {
        var done = new Lst();
        foreach (var s in sheets)
        {
            var current = s.GetAdditionalRevisionIds().ToList();
            var ids = new SortedSet<long>(current.Select(i => i.Value));
            foreach (var r in revs)
            {
                if (add)
                    ids.Add(r.Id.Value);
                else
                    ids.Remove(r.Id.Value);
            }
            s.SetAdditionalRevisionIds(IdList(ids.Select(i => Compat.MakeId(i))));
            done.Add(Utils.NormalizeString(s.SheetNumber));
        }
        return done;
    }
}
