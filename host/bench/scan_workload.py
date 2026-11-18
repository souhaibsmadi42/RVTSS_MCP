# -*- coding: UTF-8 -*-
# Benchmark workload, IronPython side. Sent to pyRevit through /execute_code/ (read_only).
# Must stay step-for-step identical to Scan() in host/RvtssHost/Routes.cs.
# run_bench.py prepends:  REPEAT = <int>  and  RETURN_ROWS = <bool>
import json
from System.Diagnostics import Stopwatch

# Bound once so the loop does not pay for the read_only DB proxy.
Collector = DB.FilteredElementCollector
ST_STRING = DB.StorageType.String
ST_DOUBLE = DB.StorageType.Double
ST_INTEGER = DB.StorageType.Integer
ST_ID = DB.StorageType.ElementId

elements = parameters = chars = isum = id_params = boxes = errors = 0
dsum = 0.0
categories = set()
rows = None

watch = Stopwatch.StartNew()
for _pass in range(REPEAT):
    rows = [] if RETURN_ROWS else None
    for e in Collector(doc).WhereElementIsNotElementType():
        try:
            elements += 1
            cat = e.Category
            cname = "" if cat is None else cat.Name
            categories.add(cname)
            name = e.Name
            type_id = e.GetTypeId()
            if e.get_BoundingBox(None) is not None:
                boxes += 1
            for p in e.Parameters:
                parameters += 1
                if not p.HasValue:
                    continue
                st = p.StorageType
                if st == ST_STRING:
                    s = p.AsString()
                    if s is not None:
                        chars += len(s)
                elif st == ST_DOUBLE:
                    dsum += p.AsDouble()
                elif st == ST_INTEGER:
                    isum += p.AsInteger()
                elif st == ST_ID:
                    p.AsElementId()
                    id_params += 1
            if rows is not None:
                rows.append([int(e.Id.Value), cname, name])  # Int64 is not JSON serialisable in IronPython 2
        except Exception:
            errors += 1
watch.Stop()

print(json.dumps({
    "status": "success", "engine": "ironpython", "repeat": REPEAT,
    "elements": elements, "parameters": parameters, "chars": chars, "isum": isum,
    "dsum": round(dsum, 3), "id_params": id_params, "boxes": boxes,
    "categories": len(categories), "errors": errors,
    "scan_ms": round(watch.Elapsed.TotalMilliseconds, 2), "rows": rows,
}))
