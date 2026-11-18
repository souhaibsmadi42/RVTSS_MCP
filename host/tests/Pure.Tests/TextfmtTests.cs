namespace RvtssHost.Tests;

public static class TextfmtTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "textfmt", c =>
        {
            switch (c.Fn)
            {
                case "_format_number":
                    // the private helper is reached through a {n:spec} token, as render calls it
                    return FormatNumber((long)c.Arg(0)!, c.Str(1));
                case "tokens": return Textfmt.Tokens(c.Str(0)!);
                case "render":
                {
                    var resolve = (Dict)c.Raw["resolve"]!;
                    object? Resolver(string name) => resolve.Get(name);
                    return Textfmt.Render(c.Str(0)!, Resolver, c.Long(1, "n"), c.Arg(2, "element_id"), c.Arg(3, "current"));
                }
                case "apply_rename":
                    return Textfmt.ApplyRename(c.Str(0)!, c.Arg(1, "find"), c.Arg(2, "replace", ""), c.Bool(3, "regex"),
                        c.Arg(4, "prefix", ""), c.Arg(5, "suffix", ""), c.Arg(6, "case"));
                case "invalid_name_chars": return Textfmt.InvalidNameChars(c.Str(0)!);
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("INVALID_NAME_CHARS", doc["invalid_name_chars"], Textfmt.InvalidNameCharSet);

        // defaults and a string-returning resolver
        t.Eq("rename defaults", "Level 1", Textfmt.ApplyRename("Level 1"));
        t.Eq("rename named", "A_L01 - PLAN",
            Textfmt.ApplyRename("Level 1 - Plan", @"Level (\d)", @"L0\1", regex: true, prefix: "A_", @case: "upper"));
        string? Lookup(string name) => name == "Level" ? "L1" : null;
        t.Eq("render typed", "D-L1-007", Textfmt.Render("D-{Level}-{n:03}", Lookup, n: 7, elementId: 99L));
        t.Throws("render missing", () => Textfmt.Render("{Fire Rating}", Lookup), "TemplateError");
        t.Check("TemplateError base", new TemplateError("x") is FormatException);
    }

    private static string FormatNumber(long n, string? spec)
    {
        // "{n}" has no spec (None); "{n:}" has the empty one: both format as str(n)
        if (spec == null)
            return Textfmt.Render("{n}", _ => null, n);
        if (spec.IndexOfAny(new[] { '{', '}' }) >= 0)
            throw new InvalidOperationException("spec cannot travel in a template");
        return Textfmt.Render("{n:" + spec + "}", _ => null, n);
    }
}
