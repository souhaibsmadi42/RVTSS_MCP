namespace RvtssHost.Tests;

public static class MappingPresetsTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "mapping_presets");
        var k = LaneC.D(data["constants"]);
        t.Eq("IFC_OVERRIDES", k["IFC_OVERRIDES"], MappingPresets.IfcOverrides);
        t.Eq("IFC_COMMON_PSETS", k["IFC_COMMON_PSETS"], MappingPresets.IfcCommonPsets);
        t.Eq("COBIE_TYPE", k["COBIE_TYPE"], MappingPresets.CobieType);
        t.Eq("COBIE_COMPONENT", k["COBIE_COMPONENT"], MappingPresets.CobieComponent);
        t.Eq("COBIE_SPACE", k["COBIE_SPACE"], MappingPresets.CobieSpace);
        t.Eq("PRESETS", k["PRESETS"], MappingPresets.Presets);

        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "get_preset":
                    return LaneC.Has(a, 1)
                        ? MappingPresets.GetPreset((string)a[0]!, a[1] as Dict)
                        : MappingPresets.GetPreset((string)a[0]!);
                case "preset_categories": return MappingPresets.PresetCategories(LaneC.L(a[0]));
                case "applies": return MappingPresets.Applies(LaneC.D(a[0]), (string?)a[1]);
                case "describe": return MappingPresets.Describe();
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });

        // copies, not shared
        var ms = MappingPresets.GetPreset("ifc_overrides");
        ms[0]["to"] = "changed";
        ms.RemoveAt(1);
        t.Eq("get_preset returns copies", "IfcTag", MappingPresets.GetPreset("ifc_overrides")[0]["to"]);
        t.Eq("get_preset returns a new list", 5L, MappingPresets.GetPreset("ifc_overrides").Count);
        t.Check("PresetError is a ValueError", typeof(FormatException).IsAssignableFrom(typeof(PresetError)));
        t.Eq("typed mappings", new Lst { "Rooms" }, MappingPresets.PresetCategories(MappingPresets.CobieSpace));
    }
}
