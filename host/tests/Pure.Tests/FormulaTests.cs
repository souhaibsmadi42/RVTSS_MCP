namespace RvtssHost.Tests;

public static class FormulaTests
{
    public static void Run(T t)
    {
        List<string?> Names(object? v) => ((Lst)v!).Select(n => (string?)n).ToList();

        // formulas travel as [name, formula] pairs so the dict order of the Python call is kept
        Dict Formulas(object? pairs)
        {
            var d = new Dict();
            foreach (Lst p in (Lst)pairs!)
                d[(string)p[0]!] = p[1];
            return d;
        }

        var doc = LaneB.Run(t, "formula", c =>
        {
            switch (c.Fn)
            {
                case "references": return Formula.References(c.Str(0), Names(c.Arg(1)));
                case "unknown_identifiers": return Formula.UnknownIdentifiers(c.Str(0), Names(c.Arg(1)));
                case "check_balance": return Formula.CheckBalance(c.Str(0));
                case "find_cycles": return Formula.FindCycles(Formulas(c.Arg(0)), Names(c.Arg(1)));
                case "analyse": return Formula.Analyse(Formulas(c.Arg(0)), Names(c.Arg(1)));
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        t.Eq("FUNCTIONS", doc["functions"], Formula.Functions.OrderBy(x => x, StringComparer.Ordinal).ToList());
        t.Eq("UNIT_WORDS", doc["unit_words"], Formula.UnitWords.OrderBy(x => x, StringComparer.Ordinal).ToList());

        // typed dictionaries and name lists
        var typed = new Dictionary<string, string> { ["Width"] = "Height * 2", ["Height"] = "Width / 2" };
        var cycles = Formula.FindCycles(typed, new List<string> { "Width", "Height" });
        t.Eq("typed find_cycles", new Lst { new Lst { "Width", "Height", "Width" } }, cycles);
        t.Eq("typed analyse count", 1L, Formula.Analyse(typed, new[] { "Width", "Height" }).Count);
    }
}
