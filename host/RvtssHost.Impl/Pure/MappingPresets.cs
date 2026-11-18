namespace RvtssHost.Pure;

/// <summary>
/// Parameter mapping presets for map_parameters (IFC export overrides, IFC common psets, COBie).
///
/// A preset is a list of mappings {from, to, categories?, allow_type?, verified, note?}.
/// `verified` says whether the TARGET parameter name was confirmed in Autodesk
/// documentation / Autodesk-hosted material while building RVTSS v2.1:
///
/// * IFC exporter overrides IfcName, IfcLongName, IfcObjectType, IfcDescription, IfcTag
///   (Autodesk University handout on the Revit IFC exporter).
/// * IFC common property sets: the exporter fills a common pset property from a
///   parameter with exactly the property's name and data type (e.g. FireRating for
///   Pset_DoorCommon / Pset_WallCommon) when "Export IFC common property sets" is on.
/// * COBie Extension: COBie.Type.Manufacturer, COBie.Component.SerialNumber (instance,
///   text) and COBie.Component.InstallationDate were confirmed; the other COBie.* names
///   follow the same scheme but were NOT confirmed - check them against the shared
///   parameter file your COBie Extension created before relying on them.
///
/// map_parameters skips mappings whose target parameter does not exist on an
/// element, so an unconfirmed name can never write to the wrong parameter.
/// Office presets: %APPDATA%/RVTSS/presets/&lt;name&gt;.json with {"description", "mappings"}.
/// </summary>
public static class MappingPresets
{
    public static readonly List<Dict> IfcOverrides = new()
    {
        new Dict { ["from"] = "Mark", ["to"] = "IfcTag", ["verified"] = true },
        new Dict { ["from"] = "Comments", ["to"] = "IfcDescription", ["verified"] = true },
        new Dict
        {
            ["from"] = "Number", ["to"] = "IfcName", ["categories"] = new Lst { "Rooms" }, ["verified"] = true,
            ["note"] = "IFC IfcSpace Name = room number by convention",
        },
        new Dict { ["from"] = "Name", ["to"] = "IfcLongName", ["categories"] = new Lst { "Rooms" }, ["verified"] = true },
        new Dict { ["from"] = "Type Mark", ["to"] = "IfcObjectType", ["allow_type"] = true, ["verified"] = true },
    };

    public static readonly List<Dict> IfcCommonPsets = new()
    {
        new Dict
        {
            ["from"] = "Fire Rating", ["to"] = "FireRating", ["categories"] = new Lst { "Doors", "Walls", "Windows", "Floors" },
            ["verified"] = true, ["note"] = "Pset_*Common.FireRating (IfcLabel): text parameter named FireRating",
        },
        new Dict
        {
            ["from"] = "Acoustic Rating", ["to"] = "AcousticRating", ["categories"] = new Lst { "Doors", "Walls", "Windows" },
            ["verified"] = true, ["note"] = "Pset_DoorCommon / Pset_WallCommon.AcousticRating",
        },
        new Dict
        {
            ["from"] = "Function", ["to"] = "IsExternal", ["categories"] = new Lst { "Walls" }, ["verified"] = false,
            ["note"] = "IsExternal is a boolean: the source must be a Yes/No parameter; map your own 'Is External' flag",
        },
    };

    public static readonly List<Dict> CobieType = new()
    {
        new Dict { ["from"] = "Manufacturer", ["to"] = "COBie.Type.Manufacturer", ["allow_type"] = true, ["verified"] = true },
        new Dict { ["from"] = "Model", ["to"] = "COBie.Type.ModelNumber", ["allow_type"] = true, ["verified"] = false },
        new Dict { ["from"] = "Description", ["to"] = "COBie.Type.Description", ["allow_type"] = true, ["verified"] = false },
        new Dict { ["from"] = "Assembly Code", ["to"] = "COBie.Type.Category", ["allow_type"] = true, ["verified"] = false },
    };

    public static readonly List<Dict> CobieComponent = new()
    {
        new Dict
        {
            ["from"] = "Serial Number", ["to"] = "COBie.Component.SerialNumber", ["verified"] = true,
            ["note"] = "instance text parameter; 'Serial Number' is your own source parameter",
        },
        new Dict { ["from"] = "Installation Date", ["to"] = "COBie.Component.InstallationDate", ["verified"] = true },
        new Dict { ["from"] = "Mark", ["to"] = "COBie.Component.TagNumber", ["verified"] = false },
        new Dict { ["from"] = "Comments", ["to"] = "COBie.Component.Description", ["verified"] = false },
    };

    public static readonly List<Dict> CobieSpace = new()
    {
        new Dict { ["from"] = "Number", ["to"] = "COBie.Space.Name", ["categories"] = new Lst { "Rooms" }, ["verified"] = false },
        new Dict { ["from"] = "Name", ["to"] = "COBie.Space.Description", ["categories"] = new Lst { "Rooms" }, ["verified"] = false },
    };

    public static readonly Dict Presets = new()
    {
        ["ifc_overrides"] = new Dict
        {
            ["description"] = "Revit IFC exporter override parameters (IfcName/IfcLongName/IfcDescription/"
                              + "IfcObjectType/IfcTag)",
            ["mappings"] = IfcOverrides,
        },
        ["ifc_common_psets"] = new Dict
        {
            ["description"] = "Parameters named like IFC common pset properties (FireRating, ...)",
            ["mappings"] = IfcCommonPsets,
        },
        ["cobie_type"] = new Dict { ["description"] = "COBie Type sheet fields from type parameters", ["mappings"] = CobieType },
        ["cobie_component"] = new Dict
        {
            ["description"] = "COBie Component sheet fields from instance parameters",
            ["mappings"] = CobieComponent,
        },
        ["cobie_space"] = new Dict { ["description"] = "COBie Space sheet fields from rooms", ["mappings"] = CobieSpace },
    };

    /// <summary>Mappings of a built-in or office preset (office presets win). Returns a new list.</summary>
    public static List<Dict> GetPreset(string name, Dict? userPresets = null)
    {
        var pool = new Dict(Presets);
        if (Py.Truthy(userPresets))
            pool.Update(userPresets);
        if (name == null || !pool.ContainsKey(name))
            throw new PresetError("Unknown preset '" + Py.Str(name) + "'. Available: "
                                  + string.Join(", ", pool.Keys.OrderBy(x => x, StringComparer.Ordinal)));
        var preset = pool[name] as Dict ?? throw new InvalidCastException("preset must be an object");
        var mappings = Py.Truthy(preset.Get("mappings")) ? PyX.Items(preset.Get("mappings")) : new List<object?>();
        var res = new List<Dict>();
        foreach (var item in mappings)
        {
            var m = item as Dict ?? throw new InvalidCastException("mapping must be an object");
            if (!Py.Truthy(m.Get("from")) || !Py.Truthy(m.Get("to")))
                throw new PresetError("Preset '" + name + "' has a mapping without from/to: " + PyX.Repr(m));
        }
        foreach (var item in mappings)
            res.Add(new Dict((Dict)item!));
        return res;
    }

    public static Lst PresetCategories(IEnumerable<object?> mappings)
    {
        var cats = new Lst();
        foreach (var item in mappings)
        {
            var m = item as Dict ?? throw new InvalidCastException("mapping must be an object");
            if (!Py.Truthy(m.Get("categories")))
                continue;
            foreach (var c in PyX.Items(m.Get("categories")))
                if (!PyX.In(c, cats))
                    cats.Add(c);
        }
        return cats;
    }

    public static bool Applies(Dict mapping, string? categoryName)
    {
        var cats = mapping.Get("categories");
        if (!Py.Truthy(cats))
            return true;
        var name = (categoryName ?? "").ToLowerInvariant();
        return PyX.Items(cats).Any(c => Py.Str(c).ToLowerInvariant() == name);
    }

    public static Dict Describe()
    {
        var res = new Dict();
        foreach (var kv in Presets)
        {
            var v = (Dict)kv.Value!;
            var mappings = (List<Dict>)v["mappings"]!;
            res[kv.Key] = new Dict
            {
                ["description"] = v["description"],
                ["mappings"] = (long)mappings.Count,
                ["unverified_targets"] = mappings.Where(m => !Py.Truthy(m.Get("verified"))).Select(m => m["to"]).ToList(),
            };
        }
        return res;
    }
}

public class PresetError : FormatException
{
    public PresetError(string message) : base(message)
    {
    }
}
