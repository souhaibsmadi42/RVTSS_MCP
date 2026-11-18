namespace RvtssHost.Tests;

public static class ExportnamesTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "exportnames");
        var k = LaneC.D(data["constants"]);
        t.Eq("FORMATS", k["FORMATS"], Exportnames.Formats);
        t.Eq("MODEL_FORMATS", k["MODEL_FORMATS"], Exportnames.ModelFormats);
        t.Eq("FIELDS", k["FIELDS"], Exportnames.Fields);

        LaneC.RunCases(t, data, (fn, a) =>
        {
            switch (fn)
            {
                case "default_template": return Exportnames.DefaultTemplate((bool)a[0]!);
                case "sanitize":
                    if (!LaneC.Has(a, 1)) return Exportnames.Sanitize((string?)a[0]);
                    if (!LaneC.Has(a, 2)) return Exportnames.Sanitize((string?)a[0], (string)a[1]!);
                    return Exportnames.Sanitize((string?)a[0], (string)a[1]!, Py.ToInt(a[2]));
                case "render": return Exportnames.Render((string?)a[0], LaneC.D(a[1]));
                case "unique": return Exportnames.Unique(LaneC.Strings(a[0]));
                case "strip_extension": return Exportnames.StripExtension((string?)a[0], (string?)a[1]);
                default: throw new InvalidOperationException("no such function " + fn);
            }
        });
        t.Check("NamingError is a ValueError", typeof(FormatException).IsAssignableFrom(typeof(NamingError)));
    }
}
