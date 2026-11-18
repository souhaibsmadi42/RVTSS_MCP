using System.Text.RegularExpressions;

namespace RvtssHost;

/// <summary>
/// Parameter lookup, reading and writing with explicit unit handling: port of revit_mcp/params_util.py.
///
/// Writing rules (SetValue):
///   * String parameters: value is converted to text.
///   * Integer parameters: ints, booleans and "yes"/"no" for Yes/No parameters.
///   * Double parameters with a measurable spec (length, area, angle...):
///       - number + unit ("mm", "m", "ft", "deg"...) -> converted exactly, or
///       - string with units ("900 mm", "3'-0\"") -> Parameter.SetValueString,
///       - a bare number without unit is REJECTED (prevents 900 being read as 900 ft).
///     unit="internal" passes Revit internal units through unchanged.
///   * Double parameters without units (Number): numbers are set directly.
///   * ElementId parameters: an element id, or a name for material/level parameters.
/// </summary>
public static class ParamsUtil
{
    private static readonly Regex GuidRx = new("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", RegexOptions.CultureInvariant);

    /// <summary>str.isupper(): at least one cased character and no lower-case one.</summary>
    private static bool IsUpper(string s)
    {
        var cased = false;
        foreach (var c in s)
        {
            if (char.IsLower(c))
                return false;
            if (char.IsUpper(c))
                cased = true;
        }
        return cased;
    }

    /// <summary>str.isdigit() after lstrip("-")</summary>
    private static bool IsIntegerText(object? v)
    {
        if (v is not string s)
            return false;
        s = s.TrimStart('-');
        return s.Length > 0 && s.All(char.IsDigit);
    }

    private static bool Measured(string? kind) => kind == "length" || kind == "area" || kind == "volume" || kind == "angle";

    /// <summary>Parameter by name, BuiltInParameter name (e.g. 'ALL_MODEL_MARK') or shared GUID.</summary>
    public static DB.Parameter? Lookup(DB.Element? element, object? name)
    {
        if (element == null || !Py.Truthy(name))
            return null;
        if (name is string text)
        {
            var n = text.Trim();
            if (GuidRx.IsMatch(n))
            {
                try { return element.get_Parameter(new Guid(n)); }
                catch { return null; }
            }
            DB.Parameter? p;
            if (IsUpper(n) && n.IndexOf('_') >= 0)
            {
                var bip = Py.EnumOrNull<DB.BuiltInParameter>(n);
                if (bip != null)
                {
                    p = element.get_Parameter(bip.Value);
                    if (p != null)
                        return p;
                }
            }
            p = element.LookupParameter(n);
            if (p != null)
                return p;
            // case-insensitive fallback
            var low = n.ToLowerInvariant();
            foreach (DB.Parameter q in element.Parameters)
            {
                if (Utils.NormalizeString(q.Definition.Name).ToLowerInvariant() == low)
                    return q;
            }
        }
        return null;
    }

    /// <summary>Return (parameter, owner) where owner is 'instance' or 'type'.</summary>
    public static (DB.Parameter? p, string? owner) Find(DB.Document doc, DB.Element? element, object? name, bool allowType = true)
    {
        var p = Lookup(element, name);
        if (p != null)
            return (p, element is DB.ElementType ? "type" : "instance");
        if (allowType && element is not DB.ElementType)
        {
            try
            {
                var tid = element!.GetTypeId();
                if (Compat.IsValidId(tid))
                {
                    var t = doc.GetElement(tid);
                    p = Lookup(t, name);
                    if (p != null)
                        return (p, "type");
                }
            }
            catch { /* no type, or the element is null */ }
        }
        return (null, null);
    }

    private static bool IsYesno(DB.Parameter p) => Compat.DefinitionSpec(p.Definition).spec == "yesno";

    /// <summary>Comparable value: text, int/bool, float (converted to unit when measurable), id.</summary>
    public static object? RawValue(DB.Parameter p, string? unit = null)
    {
        var st = p.StorageType;
        if (st == DB.StorageType.String)
            return Core.ToText(p.AsString());
        if (st == DB.StorageType.Integer)
        {
            var v = p.AsInteger();
            return IsYesno(p) ? v != 0 : (long)v;
        }
        if (st == DB.StorageType.Double)
        {
            var v = p.AsDouble();
            var (_, kind) = Compat.DefinitionSpec(p.Definition);
            if (Measured(kind) && !string.IsNullOrEmpty(unit))
            {
                var target = Units.LengthUnitFor(kind!, unit);
                return Units.FromInternal(v, target, 6);
            }
            return v;
        }
        if (st == DB.StorageType.ElementId)
            return Compat.IdInt(p.AsElementId());
        return null;
    }

    public static Dict Read(DB.Document doc, DB.Parameter p, string? unit = "mm", bool meta = false)
    {
        var d = p.Definition;
        var (spec, kind) = Compat.DefinitionSpec(d);
        var info = new Dict { ["name"] = Utils.NormalizeString(d.Name) };
        try { info["value"] = RawValue(p, unit); }
        catch { info["value"] = null; }
        if (p.StorageType == DB.StorageType.Double && Measured(kind))
            info["unit"] = Units.LengthUnitFor(kind!, unit);
        else if (p.StorageType == DB.StorageType.Double && kind == "measurable")
            info["unit"] = "internal";
        try
        {
            var vs = p.AsValueString();
            if (vs != null && !(info.Get("value") is string same && same == vs))
                info["display"] = Core.ToText(vs);
        }
        catch { /* no display text */ }
        if (p.StorageType == DB.StorageType.ElementId)
        {
            try
            {
                var reference = doc.GetElement(p.AsElementId());
                if (reference != null)
                    info["display"] = Utils.NormalizeString(Utils.GetElementName(reference));
            }
            catch { /* keep the value string */ }
        }
        if (meta)
        {
            info["storage"] = p.StorageType.ToString();
            info["spec"] = spec;
            info["group"] = Compat.DefinitionGroup(d);
            info["read_only"] = p.IsReadOnly;
            info["shared"] = p.IsShared;
            info["has_value"] = p.HasValue;
            if (p.IsShared)
            {
                try { info["guid"] = p.GUID.ToString(); }
                catch { /* not available */ }
            }
            try
            {
                // only internal definitions have a BuiltInParameter
                if (d is DB.InternalDefinition internalDefinition)
                {
                    var bip = internalDefinition.BuiltInParameter;
                    if (bip != DB.BuiltInParameter.INVALID)
                        info["builtin"] = bip.ToString();
                }
            }
            catch { /* not available */ }
        }
        return info;
    }

    public static List<Dict> ReadAll(DB.Document doc, DB.Element element, string? unit = "mm", IEnumerable<object?>? names = null,
        bool meta = false, bool includeEmpty = false)
    {
        var result = new List<Dict>();
        var wanted = names?.ToList();
        if (wanted != null && wanted.Count > 0)
        {
            foreach (var n in wanted)
            {
                var p = Lookup(element, n);
                if (p == null)
                    result.Add(new Dict { ["name"] = n, ["missing"] = true });
                else
                    result.Add(Read(doc, p, unit, meta));
            }
            return result;
        }
        foreach (DB.Parameter p in element.Parameters)
        {
            try
            {
                if (!includeEmpty && !p.HasValue && p.StorageType != DB.StorageType.Integer)
                    continue;
                result.Add(Read(doc, p, unit, meta));
            }
            catch { /* skip a parameter that cannot be read */ }
        }
        return result.OrderBy(x => ((string)x["name"]!).ToLowerInvariant(), StringComparer.Ordinal).ToList();
    }

    /// <summary>Yes/No from a bool, a number or text ("yes", "on", "0", ...). (params_util._parse_bool)</summary>
    internal static bool ParseBool(object? value)
    {
        if (value is bool b)
            return b;
        if (Py.IsNum(value))
            return Py.Truthy(value);
        var s = Py.Str(value).Trim().ToLowerInvariant();
        if (s == "1" || s == "true" || s == "yes" || s == "y" || s == "on" || s == "checked")
            return true;
        if (s == "0" || s == "false" || s == "no" || s == "n" || s == "off" || s == "unchecked" || s == "")
            return false;
        throw new RvtssError($"Cannot interpret '{Py.Str(value)}' as Yes/No");
    }

    /// <summary>An element id for an ElementId parameter: an id, or the name of a material / level / phase.
    /// (params_util._resolve_id_value; takes the definition so it serves Parameter and FamilyParameter.)</summary>
    internal static DB.ElementId ResolveIdValue(DB.Document doc, DB.Definition definition, object? value)
    {
        if (value == null || (value is string empty && empty.Length == 0) || (Py.IsNum(value) && Py.ToFloat(value) == -1.0))
            return DB.ElementId.InvalidElementId;
        if (value is bool flag) // a Python bool is an int
            return Compat.MakeId(flag ? 1L : 0L);
        if (Py.IsInt(value) || IsIntegerText(value))
            return Compat.MakeId(Py.ToInt(value));
        var name = Py.Str(value).Trim().ToLowerInvariant();
        var spec = Compat.DefinitionSpec(definition).spec;
        var classes = spec == "material"
            ? new[] { typeof(DB.Material) }
            : new[] { typeof(DB.Level), typeof(DB.Material), typeof(DB.Phase) };
        foreach (var cls in classes)
        {
            foreach (var e in new DB.FilteredElementCollector(doc).OfClass(cls))
            {
                if (Utils.NormalizeString(e.Name).ToLowerInvariant() == name)
                    return e.Id;
            }
        }
        throw new RvtssError($"No element named '{Py.Str(value)}' found for parameter '{definition.Name}'", status: 404,
            hint: "Pass an element id instead.");
    }

    /// <summary>Set a parameter value (inside a transaction). Returns the new Read() dict.</summary>
    public static Dict SetValue(DB.Document doc, DB.Parameter p, object? value, string? unit = null)
    {
        var name = Utils.NormalizeString(p.Definition.Name);
        if (p.IsReadOnly)
            throw new RvtssError($"Parameter '{name}' is read-only", status: 409,
                hint: "It may be computed by Revit, driven by a formula, or a type parameter "
                      + "locked by the family.");
        var hasUnit = !string.IsNullOrEmpty(unit);
        var st = p.StorageType;
        bool ok;
        if (st == DB.StorageType.String)
        {
            ok = p.Set(value == null ? "" : Py.Str(value));
        }
        else if (st == DB.StorageType.Integer)
        {
            if (IsYesno(p))
            {
                ok = p.Set(ParseBool(value) ? 1 : 0);
            }
            else
            {
                int number;
                try { number = checked((int)Py.ToInt(value)); }
                catch (Exception e) when (e is FormatException || e is OverflowException)
                {
                    throw new RvtssError($"Parameter '{name}' needs an integer, got '{Py.Str(value)}'");
                }
                ok = p.Set(number);
            }
        }
        else if (st == DB.StorageType.Double)
        {
            var (spec, kind) = Compat.DefinitionSpec(p.Definition);
            var measurable = Measured(kind) || kind == "measurable";
            if (value is string text && !hasUnit)
            {
                var s = text.Trim();
                double? num = Py.TryFloat(s, out var parsed) ? parsed : null;
                if (num != null && !measurable)
                {
                    ok = p.Set(num.Value);
                }
                else if (num != null)
                {
                    throw new RvtssError($"Parameter '{name}' has units ({Py.Str(spec)}); '{text}' has none",
                        hint: $"Pass unit (e.g. 'mm') or a string with units such as '{s} mm'.");
                }
                else
                {
                    ok = p.SetValueString(s);
                    if (!ok)
                        throw new RvtssError($"Revit could not parse '{s}' for '{name}'",
                            hint: "Use project display units syntax, e.g. '900 mm' or 3'-0\"");
                }
            }
            else
            {
                if (!Py.TryFloat(value, out var num))
                    throw new RvtssError($"Parameter '{name}' needs a number, got '{Py.Str(value)}'");
                if (measurable && !hasUnit)
                    throw new RvtssError($"Parameter '{name}' has units ({Py.Str(spec)}) but no unit was given for {Py.Str(value)}",
                        hint: "Add unit='mm' (or m, cm, ft, in, deg, m2, m3, internal).");
                if (hasUnit && measurable && kind != "measurable")
                {
                    var u = Units.NormalizeUnit(unit);
                    var unitKind = Units.UnitKind(u!);
                    if (unitKind != kind && unitKind != "any")
                        throw new RvtssError($"Unit '{unit}' does not fit parameter '{name}' ({kind})");
                    num = Units.ToInternal(num, u);
                }
                else if (hasUnit && kind == "measurable" && Units.NormalizeUnit(unit) != "internal")
                {
                    throw new RvtssError($"Parameter '{name}' uses spec {Py.Str(spec)}; pass unit='internal' or a string with units");
                }
                ok = p.Set(num);
            }
        }
        else if (st == DB.StorageType.ElementId)
        {
            ok = p.Set(ResolveIdValue(doc, p.Definition, value));
        }
        else
        {
            throw new RvtssError($"Parameter '{name}' has no settable storage type");
        }
        if (!ok)
            throw new RvtssError($"Revit refused value '{Py.Str(value)}' for '{name}'", status: 409);
        return Read(doc, p, hasUnit ? unit : "mm");
    }

    /// <summary>Value of a FamilyParameter in a FamilyType, converted like RawValue().</summary>
    public static object? FamilyTypeValue(DB.FamilyManager fm, DB.FamilyType ftype, DB.FamilyParameter fp, string? unit = "mm")
    {
        if (!ftype.HasValue(fp))
            return null;
        var st = fp.StorageType;
        if (st == DB.StorageType.String)
            return Core.ToText(ftype.AsString(fp));
        if (st == DB.StorageType.Integer)
        {
            var v = ftype.AsInteger(fp);
            if (v == null)
                return null;
            var spec = Compat.DefinitionSpec(fp.Definition).spec;
            return spec == "yesno" ? v.Value != 0 : (long)v.Value;
        }
        if (st == DB.StorageType.Double)
        {
            var v = ftype.AsDouble(fp);
            var kind = Compat.DefinitionSpec(fp.Definition).kind;
            if (kind == "length" || kind == "area" || kind == "volume")
                return Units.FromInternal(v, Units.LengthUnitFor(kind, unit), 6);
            if (kind == "angle")
                return Units.FromInternal(v, "deg", 6);
            return v;
        }
        if (st == DB.StorageType.ElementId)
        {
            var id = ftype.AsElementId(fp);
            return id == null ? null : Compat.IdInt(id);
        }
        return null;
    }

    /// <summary>FamilyManager.Set for the current type, with the same unit rules as SetValue.</summary>
    public static void SetFamilyValue(DB.Document doc, DB.FamilyManager fm, DB.FamilyParameter fp, object? value, string? unit = null)
    {
        var name = Utils.NormalizeString(fp.Definition.Name);
        if (fp.IsDeterminedByFormula)
            throw new RvtssError($"'{name}' is driven by formula '{fp.Formula}'", status: 409,
                hint: "Change the formula (family_set_formulas) or remove it first.");
        var hasUnit = !string.IsNullOrEmpty(unit);
        var st = fp.StorageType;
        if (st == DB.StorageType.String)
        {
            fm.Set(fp, value == null ? "" : Py.Str(value));
        }
        else if (st == DB.StorageType.Integer)
        {
            var spec = Compat.DefinitionSpec(fp.Definition).spec;
            fm.Set(fp, spec == "yesno" ? (ParseBool(value) ? 1 : 0) : checked((int)Py.ToInt(value)));
        }
        else if (st == DB.StorageType.Double)
        {
            var (spec, kind) = Compat.DefinitionSpec(fp.Definition);
            var measurable = Measured(kind) || kind == "measurable";
            if (value is string text && !hasUnit)
            {
                if (!Py.TryFloat(text, out var num))
                {
                    fm.SetValueString(fp, text);
                    return;
                }
                if (measurable)
                    throw new RvtssError($"'{name}' has units ({Py.Str(spec)}); pass unit or a string like '{text} mm'");
                fm.Set(fp, num);
            }
            else
            {
                var num = Py.ToFloat(value);
                if (measurable && !hasUnit)
                    throw new RvtssError($"'{name}' has units ({Py.Str(spec)}) but no unit was given",
                        hint: "Add unit='mm' (or m, cm, ft, in, deg).");
                if (hasUnit && Measured(kind))
                {
                    // the default unit is a length unit (ctx.Unit): adapt it to the parameter's
                    // kind (mm -> mm2 for areas, -> deg for angles) instead of applying a length
                    // factor to an angle or area
                    num = Units.ToInternal(num, Units.LengthUnitFor(kind!, unit));
                }
                else if (hasUnit && kind == "measurable" && Units.NormalizeUnit(unit) != "internal")
                {
                    throw new RvtssError($"'{name}' uses spec {Py.Str(spec)}; pass unit='internal' or a string with units");
                }
                fm.Set(fp, num);
            }
        }
        else if (st == DB.StorageType.ElementId)
        {
            fm.Set(fp, ResolveIdValue(doc, fp.Definition, value));
        }
    }

    public static DB.FamilyParameter? FamilyParameter(DB.FamilyManager fm, object? name)
    {
        foreach (DB.FamilyParameter fp in fm.Parameters)
        {
            if (name is string exact && Utils.NormalizeString(fp.Definition.Name) == exact)
                return fp;
        }
        var low = Py.Truthy(name) ? Py.Str(name).ToLowerInvariant() : "";
        foreach (DB.FamilyParameter fp in fm.Parameters)
        {
            if (Utils.NormalizeString(fp.Definition.Name).ToLowerInvariant() == low)
                return fp;
        }
        return null;
    }

    public static DB.FamilyParameter RequireFamilyParameter(DB.FamilyManager fm, object? name)
    {
        var fp = FamilyParameter(fm, name);
        if (fp == null)
            throw Core.NotFound("Family parameter", name, fm.Parameters.Cast<DB.FamilyParameter>().Select(p => p.Definition.Name));
        return fp;
    }
}
