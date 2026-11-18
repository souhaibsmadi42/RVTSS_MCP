# -*- coding: utf-8 -*-
"""Side-by-side timing: pyRevit Routes (IronPython) vs the RVTSS Host add-in (C#).

Run with Revit open on a model, pyRevit loaded and the host add-in installed:

    uv run --project . python host/bench/run_bench.py [--repeat 1] [--runs 5]

Both sides read the model only. The scan is the same workload on both sides
(scan_workload.py / Routes.cs Scan) and the counters must match exactly.
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
PY_URL = "http://127.0.0.1:{}/revit_mcp".format(os.environ.get("REVIT_PORT", "48884"))
CS_URL = "http://127.0.0.1:{}/revit_mcp".format(os.environ.get("RVTSS_HOST_PORT", "48885"))
TOKEN = os.environ.get("RVTSS_TOKEN") or None
CHECK_KEYS = ("elements", "parameters", "chars", "isum", "dsum", "id_params", "boxes", "categories", "errors")


def headers():
    return {"X-RVTSS-Token": TOKEN} if TOKEN else {}


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return (time.perf_counter() - t) * 1000.0, out


def get(client, url, path):
    params = {"rvtss_token": TOKEN} if TOKEN else None
    r = client.get(url + path, headers=headers(), params=params)
    r.raise_for_status()
    return r.json()


def scan_cs(client, repeat, rows):
    r = client.post(CS_URL + "/bench/scan/", json={"repeat": repeat, "return_rows": rows}, headers=headers())
    r.raise_for_status()
    return r.json()


def scan_py(client, repeat, rows):
    code = "REPEAT = {}\nRETURN_ROWS = {}\n".format(int(repeat), bool(rows))
    code += (HERE / "scan_workload.py").read_text(encoding="utf-8")
    body = {"code": code, "description": "RVTSS host benchmark scan (read only)", "transaction_mode": "read_only"}
    if TOKEN:
        body["_rvtss_token"] = TOKEN
    r = client.post(PY_URL + "/execute_code/", json=body, headers=headers())
    data = r.json()
    if r.status_code != 200 or data.get("status") != "success":
        raise RuntimeError("pyRevit scan failed ({}): {}".format(r.status_code, json.dumps(data)[:800]))
    return json.loads(data["output"])


def med(values):
    return round(statistics.median(values), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1, help="scan the model this many times per call")
    ap.add_argument("--runs", type=int, default=5, help="calls per engine (median is reported)")
    args = ap.parse_args()

    result = {"when": time.strftime("%Y-%m-%dT%H:%M:%S"), "repeat": args.repeat, "runs": args.runs}
    with httpx.Client(timeout=600) as client:
        try:
            result["pyrevit_status"] = get(client, PY_URL, "/status/")
            result["host_status"] = get(client, CS_URL, "/status/")
        except Exception as e:
            sys.exit("Cannot reach both servers ({}). Revit open on a model? pyRevit loaded? Host add-in "
                     "installed?".format(e))

        # 1. Transport only (no Revit main thread) and 2. main-thread dispatch round trip.
        for name, path, n in (("ping", "/ping/", 50), ("status", "/status/", 30)):
            get(client, PY_URL, path), get(client, CS_URL, path)  # warm up
            py, cs = [], []
            for _ in range(n):
                py.append(timed(lambda: get(client, PY_URL, path))[0])
                cs.append(timed(lambda: get(client, CS_URL, path))[0])
            result[name] = {"pyrevit_ms": med(py), "host_ms": med(cs)}

        # 3. The scan, without and with rows (rows add JSON serialisation of every element).
        for rows in (False, True):
            scan_py(client, 1, rows), scan_cs(client, 1, rows)  # warm up (JIT, caches)
            py_in, py_rt, cs_in, cs_rt = [], [], [], []
            check = None
            for _ in range(args.runs):
                ms, p = timed(lambda: scan_py(client, args.repeat, rows))
                py_rt.append(ms), py_in.append(p["scan_ms"])
                ms, c = timed(lambda: scan_cs(client, args.repeat, rows))
                cs_rt.append(ms), cs_in.append(c["scan_ms"])
                check = {k: (p[k], c[k]) for k in CHECK_KEYS}
                if rows and p["rows"] != c["rows"]:
                    check["rows"] = ("differ", "differ")
            mismatch = {k: v for k, v in check.items() if v[0] != v[1]}
            key = "scan_rows" if rows else "scan"
            result[key] = {
                "elements_per_call": check["elements"][1], "parameters_per_call": check["parameters"][1],
                "same_work": not mismatch, "mismatch": mismatch,
                "pyrevit_scan_ms": med(py_in), "host_scan_ms": med(cs_in),
                "pyrevit_round_trip_ms": med(py_rt), "host_round_trip_ms": med(cs_rt),
                "speedup_scan": round(med(py_in) / max(med(cs_in), 0.01), 1),
                "speedup_round_trip": round(med(py_rt) / max(med(cs_rt), 0.01), 1),
            }

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "bench-{}.json".format(time.strftime("%Y%m%d-%H%M%S"))
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("Model: {}   (Revit {})".format(result["host_status"].get("document_title"),
                                          result["host_status"].get("revit_version")))
    print("{:<34}{:>14}{:>14}{:>10}".format("median ms", "pyRevit", "C# host", "speedup"))
    for label, k in (("ping (transport only)", "ping"), ("status (main-thread round trip)", "status")):
        r = result[k]
        print("{:<34}{:>14}{:>14}{:>9}x".format(label, r["pyrevit_ms"], r["host_ms"],
                                                round(r["pyrevit_ms"] / max(r["host_ms"], 0.01), 1)))
    for label, k in (("scan", "scan"), ("scan + rows", "scan_rows")):
        r = result[k]
        print("{:<34}{:>14}{:>14}{:>9}x".format(label + " (inside Revit)", r["pyrevit_scan_ms"], r["host_scan_ms"],
                                                r["speedup_scan"]))
        print("{:<34}{:>14}{:>14}{:>9}x".format(label + " (round trip)", r["pyrevit_round_trip_ms"],
                                                r["host_round_trip_ms"], r["speedup_round_trip"]))
        print("    {} elements, {} parameters per call, same work on both sides: {}".format(
            r["elements_per_call"], r["parameters_per_call"], r["same_work"]))
        if r["mismatch"]:
            print("    MISMATCH (pyRevit, host): {}".format(r["mismatch"]))
    print("Saved: {}".format(out))


if __name__ == "__main__":
    main()
