namespace RvtssHost.Tests;

public static class FilterRulesTests
{
    private static string PyType(object? v) => v switch
    {
        null => "NoneType",
        bool => "bool",
        long => "int",
        int => "int",
        double => "float",
        string => "str",
        _ => v.GetType().Name,
    };

    public static void Run(T t)
    {
        var data = LaneC.Load(t, "filter_rules");
        var k = LaneC.D(data["constants"]);
        t.Eq("STRING_OPS", k["STRING_OPS"], FilterRules.StringOps);
        t.Eq("NUMBER_OPS", k["NUMBER_OPS"], FilterRules.NumberOps);
        t.Eq("VALUELESS_OPS", k["VALUELESS_OPS"], FilterRules.ValuelessOps);
        t.Eq("ALL_OPS", k["ALL_OPS"], FilterRules.AllOps);
        t.Eq("KINDS", k["KINDS"], FilterRules.Kinds);
        t.Eq("FACTORY", k["FACTORY"], FilterRules.Factory);

        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "infer_kind":
                    if (!LaneC.Has(a, 1)) return FilterRules.InferKind(a[0]);
                    if (!LaneC.Has(a, 2)) return FilterRules.InferKind(a[0], a[1]);
                    return FilterRules.InferKind(a[0], a[1], a[2]);
                case "validate_rule":
                    var res = FilterRules.ValidateRule(a[0]);
                    return new Dict { ["rule"] = res, ["value_type"] = PyType(res["value"]) };
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });
        t.Check("RuleError is a ValueError", typeof(FormatException).IsAssignableFrom(typeof(RuleError)));
    }
}
