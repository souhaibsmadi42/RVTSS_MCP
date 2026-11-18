namespace RvtssHost.Modules;

/// <summary>
/// Core.ElementBrief / Core.ElementLevel with per-type, per-category and per-level caches.
///
/// Snapshots, material take-offs and clash reports describe thousands of elements that share a few hundred
/// types, categories and levels: the lookups (GetElement of the type, names) are done once per id instead of once
/// per element. The answers are identical to the Core functions.
/// </summary>
internal sealed class ElementInfoCache
{
    private sealed class TypeRec
    {
        public string Family = "";
        public string Type = "";
    }

    private readonly DB.Document _doc;
    private readonly Dictionary<long, TypeRec?> _types = new();
    private readonly Dictionary<long, string> _categories = new();
    private readonly Dictionary<long, string?> _levels = new();

    public ElementInfoCache(DB.Document doc)
    {
        _doc = doc;
    }

    private string CategoryName(DB.Category cat)
    {
        var key = cat.Id.Value;
        if (!_categories.TryGetValue(key, out var name))
        {
            name = Utils.NormalizeString(cat.Name);
            _categories[key] = name;
        }
        return name;
    }

    private TypeRec? TypeOf(DB.ElementId tid)
    {
        var key = tid.Value;
        if (_types.TryGetValue(key, out var rec))
            return rec;
        var t = _doc.GetElement(tid);
        if (t != null)
        {
            rec = new TypeRec
            {
                Family = Utils.NormalizeString((t as DB.ElementType)?.FamilyName ?? ""),
                Type = Utils.NormalizeString(Utils.GetElementName(t)),
            };
        }
        _types[key] = rec;
        return rec;
    }

    /// <summary>Core.ElementBrief(doc, e).</summary>
    public Dict Brief(DB.Element e)
    {
        var info = new Dict { ["id"] = e.Id.Value, ["name"] = Utils.NormalizeString(Utils.GetElementName(e)) };
        var cat = e.Category;
        info["category"] = cat != null ? CategoryName(cat) : null;
        try
        {
            var tid = e.GetTypeId();
            if (Compat.IsValidId(tid))
            {
                var rec = TypeOf(tid);
                if (rec != null)
                {
                    info["family"] = rec.Family;
                    info["type"] = rec.Type;
                    info["type_id"] = tid.Value;
                }
            }
            else if (e is DB.ElementType et)
            {
                info["family"] = Utils.NormalizeString(et.FamilyName ?? "");
            }
        }
        catch { /* leave the brief without type info */ }
        return info;
    }

    /// <summary>Core.ElementLevel(doc, e).</summary>
    public string? Level(DB.Element e)
    {
        try
        {
            var lid = e.LevelId;
            if (Compat.IsValidId(lid))
            {
                if (!_levels.TryGetValue(lid.Value, out var name))
                {
                    var lv = _doc.GetElement(lid);
                    name = lv != null ? Utils.NormalizeString(lv.Name) : null;
                    _levels[lid.Value] = name;
                }
                return name;
            }
        }
        catch { /* fall through to the level parameters */ }
        return Core.ElementLevel(_doc, e);
    }
}
