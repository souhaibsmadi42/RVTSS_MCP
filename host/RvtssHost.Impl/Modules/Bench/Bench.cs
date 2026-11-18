using System.Diagnostics;

namespace RvtssHost.Modules;

/// <summary>
/// Benchmark route used by host/bench/run_bench.py. Not part of the RVTSS tool set.
/// Must stay step-for-step identical to host/bench/scan_workload.py: every non-type element, its category,
/// name, type id, bounding box and every parameter value. The counters double as a checksum.
/// </summary>
public static class Bench
{
    public static void Register(RouteTable api)
    {
        api.Post("/bench/scan/", Scan, "bench_scan");
    }

    public static Dict? Scan(Ctx ctx)
    {
        var doc = ctx.Doc;
        var repeat = ctx.I("repeat", 1, 1, 1000);
        var returnRows = ctx.Bool("return_rows");

        long elements = 0, parameters = 0, chars = 0, isum = 0, idParams = 0, boxes = 0, errors = 0;
        double dsum = 0;
        var categories = new HashSet<string>();
        Lst? rows = null;

        var watch = Stopwatch.StartNew();
        for (var pass = 0; pass < repeat; pass++)
        {
            rows = returnRows ? new Lst() : null;
            foreach (var e in new DB.FilteredElementCollector(doc).WhereElementIsNotElementType())
            {
                try
                {
                    elements++;
                    var cat = e.Category;
                    var cname = cat == null ? "" : cat.Name;
                    categories.Add(cname);
                    var name = e.Name;
                    var typeId = e.GetTypeId();
                    if (e.get_BoundingBox(null) != null)
                        boxes++;
                    foreach (DB.Parameter p in e.Parameters)
                    {
                        parameters++;
                        if (!p.HasValue)
                            continue;
                        switch (p.StorageType)
                        {
                            case DB.StorageType.String:
                                var s = p.AsString();
                                if (s != null)
                                    chars += s.Length;
                                break;
                            case DB.StorageType.Double:
                                dsum += p.AsDouble();
                                break;
                            case DB.StorageType.Integer:
                                isum += p.AsInteger();
                                break;
                            case DB.StorageType.ElementId:
                                p.AsElementId();
                                idParams++;
                                break;
                        }
                    }
                    rows?.Add(new Lst { e.Id.Value, cname, name });
                }
                catch
                {
                    errors++;
                }
            }
        }
        watch.Stop();

        return new Dict
        {
            ["engine"] = "csharp",
            ["repeat"] = repeat,
            ["elements"] = elements,
            ["parameters"] = parameters,
            ["chars"] = chars,
            ["isum"] = isum,
            ["dsum"] = Math.Round(dsum, 3),
            ["id_params"] = idParams,
            ["boxes"] = boxes,
            ["categories"] = categories.Count,
            ["errors"] = errors,
            ["scan_ms"] = Math.Round(watch.Elapsed.TotalMilliseconds, 2),
            ["rows"] = rows,
        };
    }
}
