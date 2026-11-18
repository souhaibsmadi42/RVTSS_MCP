namespace RvtssHost;

/// <summary>
/// Revit API version shims: port of revit_mcp/compat.py for Revit 2024 - 2027.
///
/// The shims for Revit 2023 and older are gone (Int32 ElementId / IntegerValue, ParameterType,
/// BuiltInParameterGroup, doc.Create.NewFloor): only ForgeTypeId (SpecTypeId / GroupTypeId) and the
/// Int64 ElementId remain. The friendly names and the public function set are unchanged.
/// </summary>
public static class Compat
{
    /// <summary>Python ValueError: its type name is part of the error text the routes return
    /// ("ValueError: Unknown parameter type ..."). Caught by <c>catch (FormatException)</c> like the
    /// other ported ValueErrors (Py.ToInt / Py.ToFloat).</summary>
    public sealed class ValueError(string message) : FormatException(message);

    /// <summary>2024 ... 2027 (0 before the add-in has started).</summary>
    public static int RevitYear => Hosting.RevitYear;

    /// <summary>SpecTypeId and GroupTypeId exist on every supported version.</summary>
    public const bool HasForge = true;

    /// <summary>int -> ElementId. Accepts an ElementId, an integer or a numeric string; anything else
    /// throws FormatException as Python's int() raised ValueError / TypeError.</summary>
    public static DB.ElementId MakeId(object? value)
    {
        if (value is DB.ElementId id)
            return id;
        return new DB.ElementId(Py.ToInt(value));
    }

    public static long IdInt(DB.ElementId id) => id.Value;

    public static long IdInt(DB.Element e) => e.Id.Value;

    public static readonly DB.ElementId InvalidId = DB.ElementId.InvalidElementId;

    public static bool IsValidId(DB.ElementId? id) => id != null && id != DB.ElementId.InvalidElementId;

    // ------------------------------------------------------------------- specs
    /// <summary>friendly name -> (SpecTypeId attribute path, legacy ParameterType name, unit kind)</summary>
    public static readonly Dictionary<string, (string Forge, string Legacy, string? Kind)> Specs = new()
    {
        ["length"] = ("Length", "Length", "length"),
        ["area"] = ("Area", "Area", "area"),
        ["volume"] = ("Volume", "Volume", "volume"),
        ["angle"] = ("Angle", "Angle", "angle"),
        ["slope"] = ("Slope", "Slope", null),
        ["number"] = ("Number", "Number", null),
        ["integer"] = ("Int.Integer", "Integer", null),
        ["text"] = ("String.Text", "Text", null),
        ["multiline_text"] = ("String.MultilineText", "MultilineText", null),
        ["url"] = ("String.Url", "URL", null),
        ["yesno"] = ("Boolean.YesNo", "YesNo", null),
        ["material"] = ("Reference.Material", "Material", null),
        ["image"] = ("Reference.Image", "Image", null),
        ["currency"] = ("Currency", "Currency", null),
        ["mass"] = ("Mass", "Mass", null),
        ["force"] = ("Force", "Force", null),
    };

    public static readonly Dictionary<string, string> SpecAliases = new()
    {
        ["string"] = "text", ["bool"] = "yesno", ["boolean"] = "yesno", ["yes/no"] = "yesno", ["yes_no"] = "yesno",
        ["int"] = "integer", ["double"] = "number", ["float"] = "number", ["distance"] = "length",
        ["dimension"] = "length", ["multiline"] = "multiline_text",
    };

    public static List<string> SpecNames() => Specs.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();

    /// <summary>SpecTypeId attribute path ("String.Text") -> ForgeTypeId (_resolve_path on DB.SpecTypeId).</summary>
    private static DB.ForgeTypeId ResolvePath(string path) => path switch
    {
        "Length" => DB.SpecTypeId.Length,
        "Area" => DB.SpecTypeId.Area,
        "Volume" => DB.SpecTypeId.Volume,
        "Angle" => DB.SpecTypeId.Angle,
        "Slope" => DB.SpecTypeId.Slope,
        "Number" => DB.SpecTypeId.Number,
        "Int.Integer" => DB.SpecTypeId.Int.Integer,
        "String.Text" => DB.SpecTypeId.String.Text,
        "String.MultilineText" => DB.SpecTypeId.String.MultilineText,
        "String.Url" => DB.SpecTypeId.String.Url,
        "Boolean.YesNo" => DB.SpecTypeId.Boolean.YesNo,
        "Reference.Material" => DB.SpecTypeId.Reference.Material,
        "Reference.Image" => DB.SpecTypeId.Reference.Image,
        "Currency" => DB.SpecTypeId.Currency,
        "Mass" => DB.SpecTypeId.Mass,
        "Force" => DB.SpecTypeId.Force,
        _ => throw new MissingMemberException("SpecTypeId", path),
    };

    /// <summary>(name or default).lower() of a request value.</summary>
    private static string Lower(object? name, string def) => Py.Truthy(name) ? Py.Str(name).ToLowerInvariant() : def;

    private static string SpecKey(object? name)
    {
        var low = Lower(name, "");
        return SpecAliases.TryGetValue(low, out var alias) ? alias : low;
    }

    /// <summary>Friendly spec name -> ForgeTypeId.</summary>
    public static DB.ForgeTypeId SpecId(object? name)
    {
        var key = SpecKey(name);
        if (!Specs.TryGetValue(key, out var spec))
            throw new ValueError($"Unknown parameter type '{Py.Str(name)}'. Use one of: {string.Join(", ", SpecNames())}");
        return ResolvePath(spec.Forge);
    }

    public static string? SpecKind(object? name) => Specs.TryGetValue(SpecKey(name), out var spec) ? spec.Kind : null;

    private static List<(string name, DB.ForgeTypeId id, string? kind)>? _specTable;

    /// <summary>Definition -> (friendly name or raw type id, unit kind or null).</summary>
    public static (string? spec, string? kind) DefinitionSpec(DB.Definition? definition)
    {
        if (definition == null)
            return (null, null);
        var dt = definition.GetDataType();
        // resolved once: this runs for every parameter that is read
        var table = _specTable ??= Specs.Select(kv => (kv.Key, ResolvePath(kv.Value.Forge), kv.Value.Kind)).ToList();
        foreach (var (name, id, kind) in table)
        {
            if (dt == id)
                return (name, kind);
        }
        try
        {
            if (DB.UnitUtils.IsMeasurableSpec(dt))
                return (dt.TypeId, "measurable");
        }
        catch { /* not a spec (category / empty type id) */ }
        return (dt != null ? dt.TypeId : null, null);
    }

    public static bool IsMeasurable(DB.Definition? definition)
    {
        var kind = DefinitionSpec(definition).kind;
        return kind == "length" || kind == "area" || kind == "volume" || kind == "angle" || kind == "measurable";
    }

    // ------------------------------------------------------------------ groups
    /// <summary>friendly name -> (GroupTypeId attribute, legacy BuiltInParameterGroup)</summary>
    public static readonly Dictionary<string, (string? Forge, string Legacy)> Groups = new()
    {
        ["dimensions"] = ("Geometry", "PG_GEOMETRY"),
        ["constraints"] = ("Constraints", "PG_CONSTRAINTS"),
        ["construction"] = ("Construction", "PG_CONSTRUCTION"),
        ["data"] = ("Data", "PG_DATA"),
        ["identity_data"] = ("IdentityData", "PG_IDENTITY_DATA"),
        ["materials"] = ("Materials", "PG_MATERIALS"),
        ["graphics"] = ("Graphics", "PG_GRAPHICS"),
        ["text"] = ("Text", "PG_TEXT"),
        ["general"] = ("General", "PG_GENERAL"),
        ["phasing"] = ("Phasing", "PG_PHASING"),
        ["visibility"] = ("Visibility", "PG_VISIBILITY"),
        ["fire_protection"] = ("FireProtection", "PG_FIRE_PROTECTION"),
        ["structural"] = ("Structural", "PG_STRUCTURAL"),
        ["mechanical"] = ("Mechanical", "PG_MECHANICAL"),
        ["electrical"] = ("Electrical", "PG_ELECTRICAL"),
        ["plumbing"] = ("Plumbing", "PG_PLUMBING"),
        ["energy_analysis"] = ("EnergyAnalysis", "PG_ENERGY_ANALYSIS"),
        ["ifc"] = ("Ifc", "PG_IFC"),
        ["other"] = (null, "INVALID"),
    };

    public static readonly Dictionary<string, string> GroupAliases = new()
    {
        ["geometry"] = "dimensions", ["identity"] = "identity_data", ["identitydata"] = "identity_data",
        ["material"] = "materials", ["fire"] = "fire_protection",
    };

    public static List<string> GroupNames() => Groups.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();

    private static DB.ForgeTypeId ResolveGroup(string name) => name switch
    {
        "Geometry" => DB.GroupTypeId.Geometry,
        "Constraints" => DB.GroupTypeId.Constraints,
        "Construction" => DB.GroupTypeId.Construction,
        "Data" => DB.GroupTypeId.Data,
        "IdentityData" => DB.GroupTypeId.IdentityData,
        "Materials" => DB.GroupTypeId.Materials,
        "Graphics" => DB.GroupTypeId.Graphics,
        "Text" => DB.GroupTypeId.Text,
        "General" => DB.GroupTypeId.General,
        "Phasing" => DB.GroupTypeId.Phasing,
        "Visibility" => DB.GroupTypeId.Visibility,
        "FireProtection" => DB.GroupTypeId.FireProtection,
        "Structural" => DB.GroupTypeId.Structural,
        "Mechanical" => DB.GroupTypeId.Mechanical,
        "Electrical" => DB.GroupTypeId.Electrical,
        "Plumbing" => DB.GroupTypeId.Plumbing,
        "EnergyAnalysis" => DB.GroupTypeId.EnergyAnalysis,
        "Ifc" => DB.GroupTypeId.Ifc,
        _ => throw new MissingMemberException("GroupTypeId", name),
    };

    /// <summary>Friendly group name -> GroupTypeId; null / "" / "other" is the empty ForgeTypeId ("Other").</summary>
    public static DB.ForgeTypeId GroupId(object? name)
    {
        var low = Lower(name, "other");
        var key = GroupAliases.TryGetValue(low, out var alias) ? alias : low.Replace(" ", "_");
        if (!Groups.TryGetValue(key, out var group))
            throw new ValueError($"Unknown parameter group '{Py.Str(name)}'. Use one of: {string.Join(", ", GroupNames())}");
        return group.Forge == null ? new DB.ForgeTypeId("") : ResolveGroup(group.Forge);
    }

    /// <summary>The group's label as Revit shows it ("Dimensions"), "Other" for the empty group.</summary>
    public static string? DefinitionGroup(DB.Definition? definition)
    {
        if (definition == null)
            return null;
        var gid = definition.GetGroupTypeId();
        string? label;
        try { label = DB.LabelUtils.GetLabelForGroup(gid); }
        catch { label = gid.TypeId; }
        return string.IsNullOrEmpty(label) ? "Other" : label;
    }

    // ---------------------------------------------------------- family manager
    /// <summary>FamilyManager.AddParameter for a family (non-shared) parameter.</summary>
    public static DB.FamilyParameter AddFamilyParameter(DB.FamilyManager fm, string name, object? spec, object? group, bool isInstance) =>
        fm.AddParameter(name, GroupId(group), SpecId(spec), isInstance);

    public static DB.FamilyParameter AddSharedFamilyParameter(DB.FamilyManager fm, DB.ExternalDefinition externalDefinition,
        object? group, bool isInstance) =>
        fm.AddParameter(externalDefinition, GroupId(group), isInstance);

    public static DB.ExternalDefinitionCreationOptions ExternalDefinitionOptions(string name, object? spec) =>
        new(name, SpecId(spec));

    public static bool InsertBinding(DB.Document doc, DB.Definition definition, DB.Binding binding, object? group) =>
        doc.ParameterBindings.Insert(definition, binding, GroupId(group));

    public static bool ReinsertBinding(DB.Document doc, DB.Definition definition, DB.Binding binding, object? group) =>
        doc.ParameterBindings.ReInsert(definition, binding, GroupId(group));

    /// <summary>Category -> BuiltInCategory name (e.g. 'OST_Doors', 'INVALID' for a user subcategory) or null.</summary>
    public static string? BicFromCategory(DB.Category? cat) => cat == null ? null : cat.BuiltInCategory.ToString();

    /// <summary>Floor.Create from closed loops; structural sets the floor's Structural parameter.</summary>
    public static DB.Floor NewFloor(DB.Document doc, IEnumerable<DB.CurveLoop> curveLoops, DB.Element floorType, DB.Level level,
        bool structural = false)
    {
        var loops = new List<DB.CurveLoop>(curveLoops);
        var floor = DB.Floor.Create(doc, loops, floorType.Id, level.Id);
        if (structural)
        {
            var p = floor.get_Parameter(DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);
            if (p != null && !p.IsReadOnly)
                p.Set(1);
        }
        return floor;
    }
}
