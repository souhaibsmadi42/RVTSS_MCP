namespace RvtssHost.Modules;

// Global parameters and the parameter audit (revit_mcp/parameters.py).
public static partial class Parameters
{
    // -------------------------------------------------------------------- global
    private static object? GpValue(DB.GlobalParameter gp, string unit)
    {
        var v = gp.GetValue();
        var (_, kind) = Compat.DefinitionSpec(gp.GetDefinition());
        if (v is DB.DoubleParameterValue dv)
        {
            if (kind == "length" || kind == "area" || kind == "volume")
                return Units.FromInternal(dv.Value, Units.LengthUnitFor(kind, unit), 6);
            if (kind == "angle")
                return Units.FromInternal(dv.Value, "deg", 6);
            return dv.Value;
        }
        if (v is DB.IntegerParameterValue iv)
            return (long)iv.Value;
        if (v is DB.StringParameterValue sv)
            return sv.Value;
        if (v is DB.ElementIdParameterValue ev)
            return Compat.IdInt(ev.Value);
        return null;
    }

    private static DB.GlobalParameter FindGp(DB.Document doc, object? name)
    {
        var gid = DB.GlobalParametersManager.FindByName(doc, Py.Str(name));
        if (!Compat.IsValidId(gid))
        {
            var names = DB.GlobalParametersManager.GetAllGlobalParameters(doc)
                .Select(i => (string?)Utils.NormalizeString(doc.GetElement(i).Name)).ToList();
            throw Core.NotFound("Global parameter", name, names);
        }
        return (DB.GlobalParameter)doc.GetElement(gid);
    }

    public static Dict? GlobalParameters(Ctx ctx)
    {
        var doc = ctx.Doc;
        if (!DB.GlobalParametersManager.AreGlobalParametersAllowed(doc))
            throw new RvtssError("Global parameters are not available in this document", status: 409);
        var actionValue = ctx.Get("action", "list");
        var action = actionValue as string;
        var unit = ctx.Unit;
        var dry = ctx.DryRun;
        if (action == "list")
        {
            var outList = new List<Dict>();
            foreach (var gid in DB.GlobalParametersManager.GetAllGlobalParameters(doc))
            {
                var gp = (DB.GlobalParameter)doc.GetElement(gid);
                var (spec, _) = Compat.DefinitionSpec(gp.GetDefinition());
                var formula = gp.GetFormula();
                var d = new Dict
                {
                    ["id"] = gp.Id.Value, ["name"] = Utils.NormalizeString(gp.Name), ["spec"] = spec,
                    ["value"] = GpValue(gp, unit),
                    ["formula"] = string.IsNullOrEmpty(formula) ? null : formula, ["reporting"] = gp.IsReporting,
                };
                try { d["affected_elements"] = (long)gp.GetAffectedElements().Count; }
                catch { /* not available */ }
                try { d["labeled_dimensions"] = gp.GetLabeledDimensions().Select(i => i.Value).ToList(); }
                catch { /* not available */ }
                outList.Add(d);
            }
            return new Dict
            {
                ["unit"] = unit,
                ["global_parameters"] = outList.OrderBy(d => ((string)d["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList(),
            };
        }

        void SetVal(DB.GlobalParameter gp, object? value, object? vunit)
        {
            var (spec, kind) = Compat.DefinitionSpec(gp.GetDefinition());
            if (kind == "length" || kind == "area" || kind == "volume" || kind == "angle")
            {
                if (Py.Truthy(vunit))
                {
                    if (!Py.TryFloat(value, out var num))
                        throw new RvtssError($"Global parameter '{gp.Name}' needs a number with value_unit");
                    gp.SetValue(new DB.DoubleParameterValue(Units.ToInternal(num, Units.LengthUnitFor(kind, Py.Str(vunit)))));
                    return;
                }
                var text = value != null ? Py.Str(value).Trim() : "";
                var isBareNumber = Py.TryFloat(text, out _);
                if (isBareNumber || text.Length == 0)
                    throw new RvtssError($"Global parameter '{gp.Name}' is {Py.Str(spec)}: pass value_unit (e.g. 'mm') or a string with "
                                         + "units such as '900 mm'");
                if (!DB.UnitFormatUtils.TryParse(doc.GetUnits(), gp.GetDefinition().GetDataType(), text, out var parsed))
                    throw new RvtssError($"Revit could not parse '{text}' for '{gp.Name}'");
                gp.SetValue(new DB.DoubleParameterValue(parsed));
            }
            else if (spec == "yesno")
            {
                gp.SetValue(new DB.IntegerParameterValue(ParamsUtil.ParseBool(value) ? 1 : 0));
            }
            else if (spec == "integer")
            {
                gp.SetValue(new DB.IntegerParameterValue(checked((int)Py.ToInt(value))));
            }
            else if (spec == "text" || spec == "multiline_text" || spec == "url")
            {
                gp.SetValue(new DB.StringParameterValue(Py.Str(value)));
            }
            else if (spec == "material")
            {
                gp.SetValue(new DB.ElementIdParameterValue(Compat.MakeId(Py.ToInt(value))));
            }
            else if (kind == "measurable")
            {
                if (!(vunit is string vs && vs == "internal"))
                    throw new RvtssError($"Global parameter '{gp.Name}' uses spec {Py.Str(spec)}; pass value_unit='internal'");
                gp.SetValue(new DB.DoubleParameterValue(Py.ToFloat(value)));
            }
            else
            {
                gp.SetValue(new DB.DoubleParameterValue(Py.ToFloat(value)));
            }
        }

        Dict Run()
        {
            if (action == "create")
            {
                var nameValue = ctx.Require("name");
                var name = Py.Str(nameValue);
                if (name.Trim().Length == 0 || !DB.GlobalParametersManager.IsUniqueName(doc, name))
                    throw new RvtssError($"'{name}' is not a valid/unique global parameter name", status: 409);
                var created = DB.GlobalParameter.Create(doc, name, Compat.SpecId(ctx.Get("type", "length")));
                if (ctx.Data.Get("value") != null)
                    SetVal(created, ctx.Data["value"], ctx.Get("value_unit"));
                if (Py.Truthy(ctx.Get("formula")))
                    created.SetFormula(Py.Str(ctx.Get("formula")));
                return new Dict { ["id"] = created.Id.Value, ["name"] = nameValue, ["action"] = "created" };
            }
            var gp = FindGp(doc, ctx.Require("name"));
            if (action == "set_value")
            {
                SetVal(gp, ctx.Data.Get("value"), ctx.Get("value_unit"));
                return new Dict { ["name"] = gp.Name, ["action"] = "value_set", ["value"] = GpValue(gp, unit) };
            }
            if (action == "set_formula")
            {
                var formulaValue = ctx.Get("formula");
                gp.SetFormula(Py.Truthy(formulaValue) ? Py.Str(formulaValue) : "");
                return new Dict { ["name"] = gp.Name, ["action"] = "formula_set", ["formula"] = formulaValue };
            }
            if (action == "associate" || action == "dissociate")
            {
                var pname = ctx.Require("parameter");
                var done = new Lst();
                foreach (var e in Core.GetElements(doc, ctx.List("element_ids")))
                {
                    var (p, _) = ParamsUtil.Find(doc, e, pname, allowType: false);
                    if (p == null)
                        throw new RvtssError($"Element {e.Id.Value} has no parameter '{Py.Str(pname)}'", status: 404);
                    if (action == "associate")
                    {
                        if (!p.CanBeAssociatedWithGlobalParameter(gp.Id))
                            throw new RvtssError($"'{Py.Str(pname)}' on element {e.Id.Value} cannot be associated with '{gp.Name}' (type mismatch or "
                                                 + "not supported)", status: 409);
                        p.AssociateWithGlobalParameter(gp.Id);
                    }
                    else
                    {
                        p.DissociateFromGlobalParameter();
                    }
                    done.Add(e.Id.Value);
                }
                return new Dict { ["name"] = gp.Name, ["action"] = action, ["element_ids"] = done };
            }
            if (action == "label_dimensions" || action == "unlabel_dimensions")
            {
                // GlobalParameter.CanLabelDimension / LabelDimension / UnlabelDimension
                // (verified in the Revit 2025-2027 API reference)
                var done = new Lst();
                foreach (var el in Core.GetElements(doc, ctx.List("element_ids")))
                {
                    if (el is not DB.Dimension dim)
                        throw new RvtssError($"Element {el.Id.Value} is not a dimension", status: 400);
                    if (action == "label_dimensions")
                    {
                        if (!gp.CanLabelDimension(dim.Id))
                            throw new RvtssError(
                                $"Dimension {dim.Id.Value} cannot be labelled with '{gp.Name}'", status: 409,
                                hint: "Only single-segment linear/angular/radial dimensions whose type matches the "
                                      + "parameter (length vs angle) and that reference model geometry can be labelled.");
                        gp.LabelDimension(dim.Id);
                    }
                    else
                    {
                        gp.UnlabelDimension(dim.Id);
                    }
                    done.Add(dim.Id.Value);
                }
                return new Dict
                {
                    ["name"] = gp.Name, ["action"] = action, ["dimension_ids"] = done,
                    ["labeled_dimensions"] = gp.GetLabeledDimensions().Select(i => i.Value).ToList(),
                };
            }
            throw new RvtssError("action must be list, create, set_value, set_formula, associate, dissociate, "
                                 + "label_dimensions or unlabel_dimensions");
        }

        var (res, fails) = Core.RunTransaction<Dict>(doc, "Global parameters: " + Py.Str(actionValue), Run, dry);
        return Core.CommitResult(res, fails, dry);
    }

    // --------------------------------------------------------------------- audit
    private static Lst StatLists() => new();

    public static Dict? Audit(Ctx ctx)
    {
        var doc = ctx.Doc;
        var spec = Query.QuerySpec(ctx.Data);
        if (spec.Count == 0)
            throw new RvtssError("Select elements to audit (categories, element_ids, view, level, ...)");
        var elements = Query.Collect(ctx, spec);
        var required = ctx.List("required");
        var rules = ctx.List("rules");
        var expectedTypes = ctx.Get("expected_types") as Dict ?? new Dict();
        var allowType = ctx.Bool("include_type_parameters", true);
        var findings = new List<Dict>();
        var order = new List<string>();
        var stats = new Dictionary<string, Dict>(StringComparer.Ordinal);
        void AddStat(object? n)
        {
            var key = Py.Str(n);
            if (!stats.ContainsKey(key))
                order.Add(key);
            stats[key] = new Dict { ["missing"] = StatLists(), ["empty"] = StatLists(), ["invalid"] = StatLists(), ["wrong_type"] = StatLists() };
        }
        foreach (var n in required)
            AddStat(n);
        var extraNames = new List<object?>();
        foreach (var r in rules)
        {
            var rd = (Dict)r!;
            if (!PyX.In(rd.Get("name"), required))
                extraNames.Add(PyX.Item(rd, "name"));
        }
        foreach (var n in extraNames)
            AddStat(n);
        foreach (var r in rules)
        {
            try { Filters.ValidateFilter(r); }
            catch (FilterError e) { throw new RvtssError($"Invalid rule: {e.Message}"); }
        }
        foreach (var e in elements)
        {
            var eid = e.Id.Value;
            foreach (var name in order)
            {
                var (p, _) = ParamsUtil.Find(doc, e, name, allowType);
                if (p == null)
                {
                    ((Lst)stats[name]["missing"]!).Add(eid);
                    continue;
                }
                if (expectedTypes.ContainsKey(name))
                {
                    var (s, _) = Compat.DefinitionSpec(p.Definition);
                    if (!PyX.Eq(s, expectedTypes[name]))
                        ((Lst)stats[name]["wrong_type"]!).Add(eid);
                }
                if (PyX.In(name, required) && ctx.Bool("check_empty", true))
                {
                    var r = ParamsUtil.Read(doc, p, "mm");
                    var rv = r.Get("value");
                    if ((rv == null || (rv is string rs && rs.Length == 0)) && !Py.Truthy(r.Get("display")))
                        ((Lst)stats[name]["empty"]!).Add(eid);
                }
            }
            foreach (var item in rules)
            {
                var r = (Dict)item!;
                var (p, _) = ParamsUtil.Find(doc, e, r["name"], allowType);
                if (p == null)
                    continue;
                object? raw;
                try { raw = ParamsUtil.RawValue(p, Py.Truthy(r.Get("unit")) ? Py.Str(r["unit"]) : "mm"); }
                catch { raw = null; }
                var disp = p.AsValueString();
                if (!Filters.Match(r.Get("op", "eq"), r.Get("value"), raw, disp, true, Py.Truthy(r.Get("case_sensitive"))))
                    ((Lst)stats[Py.Str(r["name"])]["invalid"]!).Add(eid);
            }
        }
        foreach (var name in order)
        {
            var s = stats[name];
            var sevRule = rules.Where(r => PyX.Eq(((Dict)r!)["name"], name)).Select(r => ((Dict)r!).Get("severity")).ToList();
            var missing = (Lst)s["missing"]!;
            var empty = (Lst)s["empty"]!;
            var invalid = (Lst)s["invalid"]!;
            var wrongType = (Lst)s["wrong_type"]!;
            if (missing.Count > 0)
                findings.Add(Rules.Finding("missing_parameter", "error", $"'{name}' does not exist on {missing.Count} element(s)",
                    missing, recommendation: "Bind it with shared_parameters(action='bind') or add it to the families.",
                    extra: new Dict { ["parameter"] = name }));
            if (empty.Count > 0)
                findings.Add(Rules.Finding("empty_value", "warning", $"'{name}' is empty on {empty.Count} element(s)",
                    empty, recommendation: "Fill it with bulk_update_parameter or set_parameters.",
                    extra: new Dict { ["parameter"] = name }));
            if (invalid.Count > 0)
                findings.Add(Rules.Finding("invalid_value", sevRule.Count > 0 && Py.Truthy(sevRule[0]) ? sevRule[0] : "warning",
                    $"'{name}' fails the rule on {invalid.Count} element(s)", invalid,
                    extra: new Dict { ["parameter"] = name }));
            if (wrongType.Count > 0)
                findings.Add(Rules.Finding("wrong_data_type", "error",
                    $"'{name}' is not of type {Py.Str(expectedTypes.Get(name))} on {wrongType.Count} element(s)", wrongType,
                    recommendation: "A same-named parameter with another data type exists; map values to the correct one.",
                    extra: new Dict { ["parameter"] = name }));
        }
        if (!doc.IsFamilyDocument && ctx.Bool("check_definitions", true))
        {
            var keys = new List<string>();
            var names = new Dictionary<string, List<Dict>>(StringComparer.Ordinal);
            var all = Bindings(doc);
            foreach (var (_, _, entry) in all)
            {
                var key = ((string)entry["name"]!).ToLowerInvariant();
                if (!names.TryGetValue(key, out var list))
                {
                    names[key] = list = new List<Dict>();
                    keys.Add(key);
                }
                list.Add(entry);
            }
            foreach (var key in keys)
            {
                var v = names[key];
                if (v.Count > 1)
                    findings.Add(Rules.Finding("duplicate_definition", "error",
                        $"Project parameter name '{v[0]["name"]}' is defined {v.Count} times",
                        recommendation: "Keep one definition; map values from the duplicate, then remove it.",
                        extra: new Dict { ["definitions"] = v }));
            }
            var pattern = ctx.Get("naming_pattern");
            if (Py.Truthy(pattern))
                findings.AddRange(Rules.CheckNames<object?>(
                    all.Select(t => (id: t.entry.Get("id"), name: (string?)t.entry["name"])),
                    new Dict { ["pattern"] = pattern }, "parameter_naming", "project parameters"));
        }
        findings = Rules.SortFindings(findings);
        var perParameter = new Dict();
        foreach (var kv in stats)
        {
            var counts = new Dict();
            foreach (var k in kv.Value)
                counts[k.Key] = (long)((Lst)k.Value!).Count;
            perParameter[kv.Key] = counts;
        }
        return new Dict
        {
            ["elements_checked"] = (long)elements.Count, ["summary"] = Rules.Summarize(findings), ["findings"] = findings,
            ["per_parameter"] = perParameter,
        };
    }
}
