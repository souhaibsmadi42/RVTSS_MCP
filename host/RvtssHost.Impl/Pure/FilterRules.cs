namespace RvtssHost.Pure;

/// <summary>View filter rules (RVTSS v2.2): validate user rules and pick the Revit rule kind - Revit independent.</summary>
public static class FilterRules
{
    public static readonly string[] StringOps =
    {
        "equals", "not_equals", "contains", "not_contains", "begins_with", "not_begins_with",
        "ends_with", "not_ends_with", "greater", "greater_or_equal", "less", "less_or_equal",
    };

    public static readonly string[] NumberOps = { "equals", "not_equals", "greater", "greater_or_equal", "less", "less_or_equal" };

    public static readonly string[] ValuelessOps = { "has_value", "has_no_value" };

    public static readonly string[] AllOps =
        StringOps.Concat(NumberOps).Concat(ValuelessOps).Distinct().OrderBy(x => x, StringComparer.Ordinal).ToArray();

    public static readonly string[] Kinds = { "string", "double", "integer", "element_id" };

    /// <summary>op -> ParameterFilterRuleFactory method</summary>
    public static readonly Dictionary<string, string> Factory = new()
    {
        ["equals"] = "CreateEqualsRule", ["not_equals"] = "CreateNotEqualsRule",
        ["contains"] = "CreateContainsRule", ["not_contains"] = "CreateNotContainsRule",
        ["begins_with"] = "CreateBeginsWithRule", ["not_begins_with"] = "CreateNotBeginsWithRule",
        ["ends_with"] = "CreateEndsWithRule", ["not_ends_with"] = "CreateNotEndsWithRule",
        ["greater"] = "CreateGreaterRule", ["greater_or_equal"] = "CreateGreaterOrEqualRule",
        ["less"] = "CreateLessRule", ["less_or_equal"] = "CreateLessOrEqualRule",
        ["has_value"] = "CreateHasValueParameterRule", ["has_no_value"] = "CreateHasNoValueParameterRule",
    };

    private static bool IsFloat(object? v) => v is double || v is float || v is decimal;

    /// <summary>string | double | integer | element_id for a rule value (explicit kind wins).</summary>
    public static string InferKind(object? value, object? unit = null, object? kind = null)
    {
        if (Py.Truthy(kind))
        {
            if (kind is not string k || Array.IndexOf(Kinds, k) < 0)
                throw new RuleError("rule type must be one of " + string.Join(", ", Kinds));
            return k;
        }
        if (value is bool)
            return "integer";
        if (IsFloat(value) || (Py.Truthy(unit) && Py.IsInt(value)))
            return "double";
        if (Py.IsInt(value))
            return "integer";
        return "string";
    }

    /// <summary>Normalised copy of {parameter, op, value, unit, type} or RuleError.</summary>
    public static Dict ValidateRule(object? rule)
    {
        if (rule is not Dict r)
            throw new RuleError("each rule must be an object {parameter, op, value}");
        var param = r.Get("parameter");
        if (!Py.Truthy(param))
            throw new RuleError("rule needs 'parameter'");
        var op = Py.Str(Py.Truthy(r.Get("op")) ? r.Get("op") : "equals").ToLowerInvariant();
        if (Array.IndexOf(AllOps, op) < 0)
            throw new RuleError("unknown op '" + op + "'. Use: " + string.Join(", ", AllOps));
        var res = new Dict { ["parameter"] = param, ["op"] = op, ["unit"] = r.Get("unit") };
        if (Array.IndexOf(ValuelessOps, op) >= 0)
        {
            res["kind"] = null;
            res["value"] = null;
            return res;
        }
        if (r.Get("value") == null)
            throw new RuleError("op '" + op + "' needs a value");
        var kind = InferKind(r["value"], r.Get("unit"), r.Get("type"));
        if (kind == "string" && Array.IndexOf(StringOps, op) < 0)
            throw new RuleError("op '" + op + "' does not apply to text");
        if (kind != "string" && Array.IndexOf(NumberOps, op) < 0)
            throw new RuleError("op '" + op + "' needs a text value");
        var value = r["value"];
        if (kind == "integer")
            value = value is bool b ? (b ? 1L : 0L) : Py.ToInt(value);
        else if (kind == "double")
            value = Py.ToFloat(value);
        else if (kind == "element_id")
            value = Py.ToInt(value);
        else
            value = PyX.Fmt(value);
        res["kind"] = kind;
        res["value"] = value;
        return res;
    }
}

public class RuleError : FormatException
{
    public RuleError(string message) : base(message)
    {
    }
}
