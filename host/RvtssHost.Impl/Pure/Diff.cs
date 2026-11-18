using System.Collections;

namespace RvtssHost.Pure;

/// <summary>
/// Snapshot comparison and location-based matching between element sets.
///
/// A snapshot element record looks like:
///     {"uid": "...", "id": 123, "category": "Doors", "family": "Single-Flush",
///      "type": "0915 x 2134mm", "level": "Level 1", "loc": [x, y, z] (mm),
///      "phash": "md5 of parameter values", "params": {"Mark": "D01", ...}}
/// </summary>
public static class Diff
{
    private static double? Dist(object? a, object? b)
    {
        if (a == null || b == null)
            return null;
        var la = a as IList ?? throw new InvalidCastException("loc must be a list");
        var lb = b as IList ?? throw new InvalidCastException("loc must be a list");
        var n = Math.Min(la.Count, lb.Count);
        var sum = 0.0;
        for (var i = 0; i < n; i++)
        {
            var d = Py.ToFloat(la[i]) - Py.ToFloat(lb[i]);
            sum += d * d;
        }
        return Math.Sqrt(sum);
    }

    private static Dict Rec(object? e) => e as Dict ?? throw new InvalidCastException("element record must be an object");

    private static string CatKey(object? category) => Py.Truthy(category) ? PyX.Fmt(category) : "?";

    private static Dict NewCounts() => new Dict { ["added"] = 0L, ["removed"] = 0L, ["modified"] = 0L };

    private static void Bump(Dict byCat, object? category, string label)
    {
        var key = CatKey(category);
        if (byCat.Get(key) is not Dict counts)
            byCat[key] = counts = NewCounts();
        counts[label] = (long)counts[label]! + 1;
    }

    /// <summary>uid -> record, in first-seen order; a later record with the same uid replaces the earlier one.</summary>
    private static (List<string> keys, Dictionary<string, Dict> map) ByUid(Dict snapshot)
    {
        var keys = new List<string>();
        var map = new Dictionary<string, Dict>(StringComparer.Ordinal);
        foreach (var item in PyX.Items(snapshot.Get("elements", new Lst())))
        {
            var e = Rec(item);
            var uid = Py.Str(PyX.Item(e, "uid"));
            if (!map.ContainsKey(uid))
                keys.Add(uid);
            map[uid] = e;
        }
        return (keys, map);
    }

    /// <summary>
    /// Compare two snapshots keyed by UniqueId.
    ///
    /// old/new: {"elements": [records]}; move_tolerance in the snapshot length unit.
    /// </summary>
    public static Dict DiffSnapshots(Dict old, Dict @new, double moveTolerance = 1.0, long maxItems = 500)
    {
        var (aKeys, a) = ByUid(old);
        var (bKeys, b) = ByUid(@new);
        var added = bKeys.Where(k => !a.ContainsKey(k)).Select(k => b[k]).ToList();
        var removed = aKeys.Where(k => !b.ContainsKey(k)).Select(k => a[k]).ToList();
        var modified = new List<Dict>();
        long common = 0;
        foreach (var k in aKeys)
        {
            if (!b.ContainsKey(k))
                continue;
            common++;
            Dict ea = a[k], eb = b[k];
            var changes = new Lst();
            foreach (var field in new[] { "category", "family", "type", "level" })
            {
                if (!PyX.Eq(ea.Get(field), eb.Get(field)))
                    changes.Add(new Dict { ["field"] = field, ["old"] = ea.Get(field), ["new"] = eb.Get(field) });
            }
            var d = Dist(ea.Get("loc"), eb.Get("loc"));
            if (d != null && d.Value > moveTolerance)
                changes.Add(new Dict { ["field"] = "location", ["moved_by"] = Py.Round(d.Value, 3) });
            if (!PyX.Eq(ea.Get("phash"), eb.Get("phash")))
            {
                var pa = Py.Truthy(ea.Get("params")) ? ea.Get("params") as Dict ?? new Dict() : new Dict();
                var pb = Py.Truthy(eb.Get("params")) ? eb.Get("params") as Dict ?? new Dict() : new Dict();
                var pchanges = new Lst();
                foreach (var pn in pa.Keys.Union(pb.Keys).OrderBy(x => x, StringComparer.Ordinal))
                {
                    if (!PyX.Eq(pa.Get(pn), pb.Get(pn)))
                        pchanges.Add(new Dict { ["parameter"] = pn, ["old"] = pa.Get(pn), ["new"] = pb.Get(pn) });
                }
                if (pchanges.Count > 0)
                    changes.AddRange(pchanges);
                else if (Py.Truthy(ea.Get("phash")) && Py.Truthy(eb.Get("phash")))
                    changes.Add(new Dict { ["field"] = "parameters", ["note"] = "parameter values changed" });
            }
            if (changes.Count > 0)
                modified.Add(new Dict
                {
                    ["uid"] = k, ["id"] = eb.Get("id"), ["category"] = eb.Get("category"),
                    ["name"] = eb.Get("type"), ["changes"] = changes,
                });
        }

        Dict Brief(Dict e) => new Dict
        {
            ["uid"] = e.Get("uid"), ["id"] = e.Get("id"), ["category"] = e.Get("category"),
            ["family"] = e.Get("family"), ["type"] = e.Get("type"), ["level"] = e.Get("level"),
        };

        var summary = new Dict
        {
            ["added"] = (long)added.Count, ["removed"] = (long)removed.Count, ["modified"] = (long)modified.Count,
            ["unchanged"] = common - modified.Count,
        };
        var byCat = new Dict();
        foreach (var e in added)
            Bump(byCat, e.Get("category"), "added");
        foreach (var e in removed)
            Bump(byCat, e.Get("category"), "removed");
        foreach (var m in modified)
            Bump(byCat, m.Get("category"), "modified");
        return new Dict
        {
            ["summary"] = summary,
            ["by_category"] = byCat,
            ["added"] = PyX.Head(added, maxItems).Select(Brief).ToList(),
            ["removed"] = PyX.Head(removed, maxItems).Select(Brief).ToList(),
            ["modified"] = PyX.Head(modified, maxItems),
            ["truncated"] = Math.Max(added.Count, Math.Max(removed.Count, modified.Count)) > maxItems,
        };
    }

    /// <summary>
    /// Match two element sets (e.g. design model vs shop model) by key + proximity.
    ///
    /// Returns matched pairs, unmatched elements on each side and pairs that
    /// match on location but differ on type (likely substitutions).
    /// </summary>
    public static Dict MatchByLocation(IEnumerable<object?> source, IEnumerable<object?> target, double tolerance,
        IEnumerable<object?>? keyFields = null, long maxItems = 500)
    {
        var fields = keyFields == null ? new List<string> { "category" } : keyFields.Select(Py.Str).ToList();
        var src = source.Select(Rec).ToList();
        var tgt = target.Select(Rec).ToList();

        // the key tuple as one string; \u001f cannot appear in a category or type name
        string Key(Dict e) => string.Join("\u001f", fields.Select(f =>
            (Py.Truthy(e.Get(f)) ? Py.Str(e.Get(f)) : "").ToLowerInvariant()));

        var buckets = new Dictionary<string, List<Dict>>(StringComparer.Ordinal);
        foreach (var t in tgt)
        {
            if (t.Get("loc") == null)
                continue;
            var key = Key(t);
            if (!buckets.TryGetValue(key, out var bucket))
                buckets[key] = bucket = new List<Dict>();
            bucket.Add(t);
        }
        var used = new HashSet<object>(PyX.RefComparer.Instance);
        var matched = new List<Dict>();
        var typeMismatch = new List<Dict>();
        var onlySource = new List<Dict>();
        foreach (var s in src)
        {
            if (s.Get("loc") == null)
            {
                onlySource.Add(s);
                continue;
            }
            Dict? best = null;
            var bestD = 0.0;
            if (buckets.TryGetValue(Key(s), out var candidates))
            {
                foreach (var t in candidates)
                {
                    if (used.Contains(t))
                        continue;
                    var d = Dist(s["loc"], t["loc"]);
                    if (d != null && d.Value <= tolerance && (best == null || d.Value < bestD))
                    {
                        best = t;
                        bestD = d.Value;
                    }
                }
            }
            if (best == null)
            {
                onlySource.Add(s);
                continue;
            }
            used.Add(best);
            var pair = new Dict
            {
                ["source_id"] = s.Get("id"), ["target_id"] = best.Get("id"), ["category"] = s.Get("category"),
                ["distance"] = Py.Round(bestD, 3),
            };
            if (!PyX.Eq(s.Get("family"), best.Get("family")) || !PyX.Eq(s.Get("type"), best.Get("type")))
            {
                pair["source_type"] = PyX.Fmt(s.Get("family")) + " : " + PyX.Fmt(s.Get("type"));
                pair["target_type"] = PyX.Fmt(best.Get("family")) + " : " + PyX.Fmt(best.Get("type"));
                typeMismatch.Add(pair);
            }
            else
            {
                matched.Add(pair);
            }
        }
        var onlyTarget = tgt.Where(t => !used.Contains(t)).ToList();

        Dict Brief(Dict e) => new Dict
        {
            ["id"] = e.Get("id"), ["category"] = e.Get("category"), ["family"] = e.Get("family"),
            ["type"] = e.Get("type"), ["loc"] = e.Get("loc"),
        };

        return new Dict
        {
            ["summary"] = new Dict
            {
                ["source"] = (long)src.Count, ["target"] = (long)tgt.Count, ["matched"] = (long)matched.Count,
                ["type_mismatch"] = (long)typeMismatch.Count, ["only_in_source"] = (long)onlySource.Count,
                ["only_in_target"] = (long)onlyTarget.Count,
            },
            ["type_mismatch"] = PyX.Head(typeMismatch, maxItems),
            ["only_in_source"] = PyX.Head(onlySource, maxItems).Select(Brief).ToList(),
            ["only_in_target"] = PyX.Head(onlyTarget, maxItems).Select(Brief).ToList(),
            ["matched_sample"] = PyX.Head(matched, 20),
        };
    }
}
