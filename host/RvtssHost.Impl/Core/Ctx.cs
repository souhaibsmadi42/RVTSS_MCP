namespace RvtssHost;

/// <summary>What the running Revit session is (pyRevit's HOST_APP).</summary>
public static class Hosting
{
    /// <summary>Set for every request that runs in Revit API context.</summary>
    public static UIApplication? UiApp { get; internal set; }

    public static Autodesk.Revit.ApplicationServices.Application? App => UiApp?.Application;

    /// <summary>"2026"</summary>
    public static string RevitVersion { get; internal set; } = "";

    public static int RevitYear => int.TryParse(RevitVersion, out var y) ? y : 0;

    public static int Port { get; internal set; }
}

/// <summary>Typed accessors for request fields (core.Ctx).</summary>
public sealed class Ctx
{
    public DB.Document? ActiveDoc { get; }
    public UIDocument? UiDoc { get; }
    public Dict Data { get; }
    public Lst Warnings { get; } = new();

    /// <summary>The target document ("document" field or the active one). Null only for needsDoc=false routes
    /// called without a document.</summary>
    public DB.Document Doc { get; }

    public Ctx(DB.Document? doc, UIDocument? uidoc, Dict? data, bool needsDoc = true)
    {
        ActiveDoc = doc;
        UiDoc = uidoc;
        Data = data ?? new Dict();
        if (needsDoc || doc != null || Py.Truthy(Data.Get("document")))
            Doc = Core.ResolveDocument(doc, Data.Get("document"));
        else
            Doc = null!;
    }

    public UIApplication UiApp => Hosting.UiApp!;

    public Autodesk.Revit.ApplicationServices.Application App => Doc != null ? Doc.Application : Hosting.App!;

    /// <summary>ctx.get(key, default): the default also replaces an explicit null.</summary>
    public object? Get(string key, object? def = null) => Data.Get(key) ?? def;

    public bool Has(string key) => Data.Get(key) != null;

    public object Require(string key, string? what = null)
    {
        var v = Data.Get(key);
        if (v == null || (v is string s && s.Trim().Length == 0) || (v is Lst l && l.Count == 0))
            throw new RvtssError($"Missing required field '{key}'" + (what != null ? $" ({what})" : ""));
        return v;
    }

    public bool Bool(string key, bool def = false)
    {
        if (!Data.TryGetValue(key, out var v))
            return def;
        if (v is string s)
        {
            s = s.Trim().ToLowerInvariant();
            return s == "1" || s == "true" || s == "yes" || s == "y";
        }
        return Py.Truthy(v);
    }

    /// <summary>ctx.int(key, default, minimum, maximum); null when absent and no default.</summary>
    public long? Int(string key, long? def = null, long? minimum = null, long? maximum = null)
    {
        var v = Data.TryGetValue(key, out var raw) ? raw : def;
        if (v == null)
            return null;
        if (!Py.TryInt(v, out var i))
            throw new RvtssError($"Field '{key}' must be an integer");
        if (minimum != null && i < minimum) i = minimum.Value;
        if (maximum != null && i > maximum) i = maximum.Value;
        return i;
    }

    /// <summary>ctx.int with a non-null default, as an int.</summary>
    public int I(string key, int def, int? minimum = null, int? maximum = null) => (int)Int(key, def, minimum, maximum)!.Value;

    /// <summary>ctx.float(key, default); null when absent and no default.</summary>
    public double? Float(string key, double? def = null)
    {
        var v = Data.TryGetValue(key, out var raw) ? raw : def;
        if (v == null)
            return null;
        if (!Py.TryFloat(v, out var d))
            throw new RvtssError($"Field '{key}' must be a number");
        return d;
    }

    /// <summary>ctx.float with a non-null default.</summary>
    public double F(string key, double def) => Float(key, def)!.Value;

    /// <summary>ctx.list(key): [] when absent, a scalar becomes a one-item list. Always a copy, as in Python
    /// (list(v)): changing the result does not change the request data.</summary>
    public Lst List(string key) => new(Py.ListOf(Data.Get(key)));

    /// <summary>The field as text (numbers are converted), or the default when absent / null.</summary>
    public string? Str(string key, string? def = null)
    {
        var v = Data.Get(key);
        return v == null ? def : Py.Str(v);
    }

    public string Unit => Py.Truthy(Data.Get("unit")) ? Py.Str(Data.Get("unit")) : "mm";

    public bool DryRun => Bool("dry_run");

    public bool Confirmed => Bool("confirm");

    public void Warn(string message) => Warnings.Add(message);
}
