using System.Security.Cryptography;

namespace RvtssHost.Modules;

/// <summary>Snapshots and comparisons: /qc/snapshot/ and /qc/compare/ (revit_mcp/qc.py).</summary>
public static partial class Qc
{
    // ---------------------------------------------------------------------- Python json.dumps (the hash input)
    /// <summary>json.dumps(value, sort_keys=True, default=str) as Python 2 wrote it: ", " and ": " separators,
    /// non-ASCII escaped as \uXXXX. The snapshot hashes of the Python implementation stay comparable.</summary>
    private static string PyDumps(object? value)
    {
        var sb = new StringBuilder();
        WriteJson(value, sb);
        return sb.ToString();
    }

    private static void WriteJson(object? v, StringBuilder sb)
    {
        switch (v)
        {
            case null:
                sb.Append("null");
                break;
            case bool b:
                sb.Append(b ? "true" : "false");
                break;
            case string s:
                WriteJsonString(s, sb);
                break;
            case long l:
                sb.Append(l.ToString(Inv));
                break;
            case int i:
                sb.Append(i.ToString(Inv));
                break;
            case double d:
                sb.Append(PyFloat(d));
                break;
            case Dict map:
                sb.Append('{');
                var first = true;
                foreach (var key in map.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    if (!first)
                        sb.Append(", ");
                    first = false;
                    WriteJsonString(key, sb);
                    sb.Append(": ");
                    WriteJson(map[key], sb);
                }
                sb.Append('}');
                break;
            case System.Collections.IList list:
                sb.Append('[');
                for (var k = 0; k < list.Count; k++)
                {
                    if (k > 0)
                        sb.Append(", ");
                    WriteJson(list[k], sb);
                }
                sb.Append(']');
                break;
            default:
                WriteJsonString(Py.Str(v), sb); // default=text_type
                break;
        }
    }

    private static string PyFloat(double d)
    {
        if (double.IsNaN(d)) return "NaN";
        if (double.IsInfinity(d)) return d > 0 ? "Infinity" : "-Infinity";
        var s = d.ToString("R", Inv);
        var e = s.IndexOf('E');
        if (e >= 0)
        {
            // 1E-05 -> 1e-05, 1E+20 -> 1e+20
            var mant = s.Substring(0, e);
            var exp = s.Substring(e + 1);
            var sign = exp.StartsWith("-", StringComparison.Ordinal) ? "-" : "+";
            exp = exp.TrimStart('+', '-');
            if (exp.Length < 2) exp = "0" + exp;
            return mant + "e" + sign + exp;
        }
        return s.IndexOf('.') < 0 ? s + ".0" : s;
    }

    private static void WriteJsonString(string s, StringBuilder sb)
    {
        sb.Append('"');
        foreach (var c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                case '\b': sb.Append("\\b"); break;
                case '\f': sb.Append("\\f"); break;
                default:
                    if (c < ' ' || c > '\u007f')
                        sb.Append("\\u").Append(((int)c).ToString("x4", Inv));
                    else
                        sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }

    /// <summary>hashlib.md5(text.encode("utf-8")).hexdigest()</summary>
    private static string Md5Hex(MD5 md5, string text)
    {
        var hash = md5.ComputeHash(Encoding.UTF8.GetBytes(text));
        var chars = new char[hash.Length * 2];
        const string hex = "0123456789abcdef";
        for (var i = 0; i < hash.Length; i++)
        {
            chars[2 * i] = hex[hash[i] >> 4];
            chars[2 * i + 1] = hex[hash[i] & 15];
        }
        return new string(chars);
    }

    // ---------------------------------------------------------------------- snapshot
    /// <summary>Elements of another document (a link) through the normal query: collect(_DocCtx(ctx, doc), spec).</summary>
    private static List<DB.Element> CollectIn(Ctx ctx, DB.Document doc, Dict spec)
    {
        if (ReferenceEquals(doc, ctx.Doc))
            return Query.Collect(ctx, spec);
        var sub = new Ctx(doc, ctx.UiDoc, new Dict());
        var res = Query.Collect(sub, spec);
        foreach (var w in sub.Warnings)
            ctx.Warn(Py.Str(w));
        return res;
    }

    private static Dict BuildSnapshot(Ctx ctx, DB.Document doc, Dict? spec, Lst track, DB.Transform? transform = null,
        bool hashAll = false)
    {
        const string unit = "mm";
        var info = new ElementInfoCache(doc);
        var records = new Lst();
        var isModel = new Dictionary<long, bool>();
        IEnumerable<DB.Element> elements;
        if (spec != null && spec.Count > 0)
        {
            elements = CollectIn(ctx, doc, spec);
        }
        else
        {
            elements = new DB.FilteredElementCollector(doc).WhereElementIsNotElementType();
        }
        var noSpec = !(spec != null && spec.Count > 0);
        using var md5 = MD5.Create();
        var trackNames = track.Select(Py.Str).ToList();
        foreach (var e in elements)
        {
            if (noSpec)
            {
                // model elements only (the Python list comprehension)
                var cat0 = e.Category;
                if (cat0 == null)
                    continue;
                var cid = cat0.Id.Value;
                if (!isModel.TryGetValue(cid, out var model))
                {
                    model = cat0.CategoryType == DB.CategoryType.Model;
                    isModel[cid] = model;
                }
                if (!model || e is DB.ElementType)
                    continue;
            }
            var b = info.Brief(e);
            var p = Core.ElementPoint(e);
            if (p != null && transform != null)
                p = transform.OfPoint(p);
            var rec = new Dict
            {
                ["uid"] = e.UniqueId, ["id"] = e.Id.Value, ["category"] = b.Get("category"), ["family"] = b.Get("family"),
                ["type"] = b.Get("type"), ["level"] = info.Level(e),
                ["loc"] = p != null
                    ? new Lst
                    {
                        Py.Round(Pure.Units.FromInternal(p.X, unit), 1), Py.Round(Pure.Units.FromInternal(p.Y, unit), 1),
                        Py.Round(Pure.Units.FromInternal(p.Z, unit), 1),
                    }
                    : null,
            };
            var vals = new Dict();
            for (var k = 0; k < track.Count; k++)
            {
                var (prm, _) = ParamsUtil.Find(doc, e, track[k], allowType: false);
                if (prm != null)
                {
                    var r = ParamsUtil.Read(doc, prm, unit);
                    vals[trackNames[k]] = r.ContainsKey("display") ? r["display"] : r.Get("value");
                }
            }
            if (hashAll)
            {
                var items = new List<string>();
                foreach (DB.Parameter prm in e.Parameters)
                {
                    try
                    {
                        var text = prm.AsValueString();
                        if (string.IsNullOrEmpty(text))
                            text = prm.AsString();
                        items.Add(prm.Definition.Name + "=" + (string.IsNullOrEmpty(text) ? "" : text));
                    }
                    catch { continue; }
                }
                items.Sort(StringComparer.Ordinal);
                rec["phash"] = Md5Hex(md5, string.Join("|", items));
            }
            else
            {
                rec["phash"] = Md5Hex(md5, PyDumps(vals));
            }
            rec["params"] = vals;
            records.Add(rec);
        }
        return new Dict
        {
            ["document"] = Utils.NormalizeString(doc.Title),
            ["created"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", Inv), ["unit"] = unit,
            ["tracked_parameters"] = track, ["hash_all_parameters"] = hashAll, ["elements"] = records,
        };
    }

    private static string SnapshotPath(Ctx ctx, object? name = null, object? path = null)
    {
        if (Py.Truthy(path))
            return Py.Str(path);
        if (!Py.Truthy(name))
            throw new RvtssError("Pass a snapshot 'name' or 'path'");
        var safe = new StringBuilder();
        foreach (var c in Py.Str(name))
            if (char.IsLetterOrDigit(c) || "-_. ".IndexOf(c) >= 0)
                safe.Append(c);
        return Path.Combine(Core.RvtssSubdir("snapshots"), safe + ".json");
    }

    /// <summary>(document, transform to host coordinates): the host model, or a loaded Revit link.</summary>
    private static (DB.Document doc, DB.Transform? transform) SourceDoc(Ctx ctx, object? linkId)
    {
        if (linkId == null)
            return (ctx.Doc, null);
        var link = Core.GetElement(ctx.Doc, linkId, "Link");
        if (link is not DB.RevitLinkInstance li || li.GetLinkDocument() == null)
            throw new RvtssError("link_instance_id must be a loaded Revit link", status: 409);
        return (li.GetLinkDocument(), li.GetTotalTransform());
    }

    public static Dict? Snapshot(Ctx ctx)
    {
        var action = ctx.Get("action", "create");
        if (PyX.Eq(action, "list"))
        {
            var folder = Core.RvtssSubdir("snapshots");
            var files = Directory.GetFileSystemEntries(folder).Select(f => Path.GetFileName(f))
                .Where(f => f.EndsWith(".json", StringComparison.Ordinal)).OrderBy(f => f, StringComparer.Ordinal).ToList();
            var list = new Lst();
            foreach (var f in files)
            {
                var full = Path.Combine(folder, f);
                var size = new FileInfo(full).Length;
                list.Add(new Dict
                {
                    ["name"] = f.Substring(0, f.Length - 5), ["size_kb"] = size / 1024,
                    ["modified"] = File.GetLastWriteTime(full).ToString("yyyy-MM-dd HH:mm", Inv),
                });
            }
            return new Dict { ["folder"] = folder, ["snapshots"] = list };
        }
        var (doc, transform) = SourceDoc(ctx, ctx.Get("link_instance_id"));
        var spec = Query.QuerySpec(ctx.Data);
        var track = ctx.List("track_parameters");
        if (track.Count == 0)
            track = new Lst { "Mark", "Comments" };
        var snap = BuildSnapshot(ctx, doc, spec, track, transform, ctx.Bool("hash_all_parameters", false));
        var path = SnapshotPath(ctx, ctx.Get("name"), ctx.Get("path"));
        if ((File.Exists(path) || Directory.Exists(path)) && !ctx.Bool("overwrite", false))
            throw new RvtssError("Snapshot exists: " + path, status: 409, hint: "Pass overwrite=true or another name.");
        File.WriteAllText(path, Py.JsonDumps(snap), new UTF8Encoding(false));
        var cats = new Dictionary<string, long>(StringComparer.Ordinal);
        var catOrder = new List<string>();
        var records = (Lst)snap["elements"]!;
        foreach (var recObj in records)
        {
            var r = (Dict)recObj!;
            // a missing category is the JSON key "null" (Python wrote None as a key)
            var key = r["category"] == null ? "null" : Py.Str(r["category"]);
            if (!cats.ContainsKey(key))
            {
                cats[key] = 0;
                catOrder.Add(key);
            }
            cats[key]++;
        }
        var byCategory = new Dict();
        foreach (var key in catOrder.OrderBy(k => -cats[k]).Take(30))
            byCategory[key] = cats[key];
        return new Dict { ["path"] = path, ["elements"] = (long)records.Count, ["by_category"] = byCategory, ["source"] = snap["document"] };
    }

    private static Dict LoadSnapshot(string path)
    {
        if (!File.Exists(path))
            throw new RvtssError("Snapshot not found: " + path, status: 404, hint: "qc_snapshot(action='list')");
        return Obj(Py.JsonLoads(File.ReadAllText(path, Encoding.UTF8)));
    }

    public static Dict? Compare(Ctx ctx)
    {
        var mode = ctx.Get("mode", "snapshots");
        var maxItems = ctx.Int("max_items", 300)!.Value;
        if (PyX.Eq(mode, "snapshots"))
        {
            var a = LoadSnapshot(SnapshotPath(ctx, ctx.Get("baseline"), ctx.Get("baseline_path")));
            Dict b;
            if (Py.Truthy(ctx.Get("current")) || Py.Truthy(ctx.Get("current_path")))
            {
                b = LoadSnapshot(SnapshotPath(ctx, ctx.Get("current"), ctx.Get("current_path")));
            }
            else
            {
                var spec = Query.QuerySpec(ctx.Data);
                var tracked = Py.Truthy(a.Get("tracked_parameters")) ? Py.ListOf(a.Get("tracked_parameters")) : new Lst { "Mark", "Comments" };
                b = BuildSnapshot(ctx, ctx.Doc, spec, tracked, null, Py.Truthy(a.Get("hash_all_parameters", false)));
            }
            var result = Pure.Diff.DiffSnapshots(a, b, ctx.F("move_tolerance", 1.0), maxItems);
            result.Update(new Dict
            {
                ["baseline"] = a.Get("created"), ["baseline_document"] = a.Get("document"),
                ["compared_with"] = Py.Truthy(ctx.Get("current")) ? b.Get("created") : "live model",
            });
            return result;
        }
        if (PyX.Eq(mode, "match"))
        {
            var source = Py.Truthy(ctx.Get("source")) ? Obj(ctx.Get("source")) : new Dict();
            var target = Py.Truthy(ctx.Get("target")) ? Obj(ctx.Get("target")) : new Dict();
            var (sdoc, st) = SourceDoc(ctx, source.Get("link_instance_id"));
            var (tdoc, tt) = SourceDoc(ctx, target.Get("link_instance_id"));
            var sspec = Query.QuerySpec(source);
            var tspec = Query.QuerySpec(target);
            var s = BuildSnapshot(ctx, sdoc, sspec.Count > 0 ? sspec : null, new Lst(), st);
            var t = BuildSnapshot(ctx, tdoc, tspec.Count > 0 ? tspec : null, new Lst(), tt);
            var keys = ctx.List("match_on");
            if (keys.Count == 0)
                keys = new Lst { "category" };
            var result = Pure.Diff.MatchByLocation((Lst)s["elements"]!, (Lst)t["elements"]!, ctx.F("tolerance", 50.0), keys, maxItems);
            result.Update(new Dict
            {
                ["source_document"] = s["document"], ["target_document"] = t["document"], ["unit"] = "mm",
                ["tolerance"] = ctx.F("tolerance", 50.0),
            });
            return result;
        }
        throw new RvtssError("mode must be snapshots or match");
    }
}
