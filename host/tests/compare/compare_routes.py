# -*- coding: utf-8 -*-
"""Send the same request to pyRevit Routes (reference) and to the C# host and diff the answers.

    uv run --project . python host/tests/compare/compare_routes.py [group ...] [--only NAME] [--ref-only] [-v]

Cases live in host/tests/compare/cases/<Group>.json:

    [{"name": "find doors", "method": "POST", "path": "/find_elements/",
      "body": {"categories": ["Doors"], "limit": 5},
      "ignore": ["elements.*.some_volatile_key"],      # optional, dotted paths, * = any key / index
      "unordered": ["category_counts"]}]               # optional, lists compared as sets

Only read-only requests and dry runs belong here: both servers are asked the same thing on the same open model.
Exit code 1 when any case differs.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REF = "http://127.0.0.1:{}/revit_mcp".format(os.environ.get("REVIT_PORT", "48884"))
NEW = "http://127.0.0.1:{}/revit_mcp".format(os.environ.get("RVTSS_HOST_PORT", "48885"))
TOKEN = os.environ.get("RVTSS_TOKEN") or None

# Element ids above this were created during this comparison run (dry runs consume ids).
FRESH_ID_FLOOR = int(os.environ.get("RVTSS_FRESH_ID_FLOOR", "210000"))

# Never comparable: clocks, timings, per-request ids, which server answered, stack traces.
ALWAYS_IGNORE = ["server_time", "host", "host_version", "revit_version", "rvtss_version", "elapsed_ms", "duration_ms",
                 "request_id", "traceback", "inner_exception", "timestamp", "code_executed"]


def call(client, base, case):
    body = dict(case.get("body") or {})
    headers = {"X-RVTSS-Token": TOKEN} if TOKEN else {}
    try:
        if case.get("method", "POST").upper() == "GET":
            r = client.get(base + case["path"], params={"rvtss_token": TOKEN} if TOKEN else None, headers=headers)
        else:
            if TOKEN:
                body["_rvtss_token"] = TOKEN
            r = client.post(base + case["path"], json=body, headers=headers)
    except httpx.HTTPError as e:
        return 599, {"status": "error", "error": "{}: {}".format(type(e).__name__, e)}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_text": r.text[:2000]}


def ignored(path, patterns):
    if path and path[-1] in ALWAYS_IGNORE:
        return True
    for pat in patterns:
        parts = pat.split(".")
        if len(parts) == len(path) and all(p == "*" or p == str(q) for p, q in zip(parts, path)):
            return True
    return False


def matches(path, patterns):
    for pat in patterns:
        parts = pat.split(".")
        if len(parts) == len(path) and all(p == "*" or p == str(q) for p, q in zip(parts, path)):
            return True
    return False


def diff(a, b, path, case, out):
    if ignored(path, case.get("ignore", [])):
        return
    where = ".".join(str(p) for p in path) or "<root>"
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if ignored(path + [k], case.get("ignore", [])):
                continue
            if k not in a:
                out.append("{}.{}: only in C# host = {}".format(where, k, short(b[k])))
            elif k not in b:
                out.append("{}.{}: missing in C# host (pyRevit = {})".format(where, k, short(a[k])))
            else:
                diff(a[k], b[k], path + [k], case, out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if matches(path, case.get("unordered", [])):
            key = lambda v: json.dumps(v, sort_keys=True)  # noqa: E731
            a, b = sorted(a, key=key), sorted(b, key=key)
        if len(a) != len(b):
            out.append("{}: list length {} vs {}".format(where, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, path + [i], case, out)
        return
    if isinstance(a, bool) or isinstance(b, bool):
        if a is not b:
            out.append("{}: {} vs {}".format(where, short(a), short(b)))
        return
    if isinstance(a, int) and isinstance(b, int) and min(a, b) > FRESH_ID_FLOOR and abs(a - b) < 500:
        return  # ids of elements created inside a dry run: each server gets the next free id
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a != b and abs(a - b) > 1e-6 * max(1.0, abs(a), abs(b)):
            out.append("{}: {} vs {}".format(where, a, b))
        return
    if a != b:
        out.append("{}: {} vs {}".format(where, short(a), short(b)))


def normalize_revit_error(ref, new):
    """pyRevit reports every .NET exception as "Exception: text" without a hint; the C# host names the real
    type ("ArgumentException: text") and adds a hint. That difference is intended: compare the text only."""
    if not (isinstance(ref, dict) and isinstance(new, dict)):
        return
    r, n = ref.get("error"), new.get("error")
    if isinstance(r, str) and isinstance(n, str) and r.startswith("Exception: ") and ": " in n:
        kind, text = n.split(": ", 1)
        if kind.endswith("Exception"):
            ref["error"], new["error"] = r[len("Exception: "):], text
            if "hint" not in ref:
                new.pop("hint", None)


def short(v):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 160 else s[:157] + "..."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("groups", nargs="*", help="case files (without .json); default: all")
    ap.add_argument("--only", help="run only cases whose name contains this text")
    ap.add_argument("--ref-only", action="store_true", help="call only pyRevit and print its answers (to write cases)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print both answers for differing cases")
    args = ap.parse_args()

    files = sorted((HERE / "cases").glob("*.json"))
    if args.groups:
        files = [f for f in files if f.stem in args.groups]
    total = bad = known = 0
    with httpx.Client(timeout=300) as client:
        for f in files:
            cases = json.loads(f.read_text(encoding="utf-8"))
            for case in cases:
                if args.only and args.only.lower() not in case["name"].lower():
                    continue
                total += 1
                label = "{}: {}".format(f.stem, case["name"])
                ref_status, ref = call(client, REF, case)
                if args.ref_only:
                    print("== {} -> {}\n{}".format(label, ref_status, json.dumps(ref, indent=1, ensure_ascii=False)[:6000]))
                    continue
                new_status, new = call(client, NEW, case)
                out = []
                normalize_revit_error(ref, new)
                if ref_status != new_status:
                    out.append("HTTP status {} vs {}".format(ref_status, new_status))
                diff(ref, new, [], case, out)
                if case.get("expect_different"):
                    # The C# host is right here and pyRevit is not (a fixed bug), or only the wording of an
                    # error for malformed input differs: see host/README.md "Intended differences".
                    known += 1
                    print("{} {}".format("known" if out else "KNOWN-BUT-SAME", label))
                    continue
                if out:
                    bad += 1
                    print("DIFF {}".format(label))
                    for line in out[:25]:
                        print("     " + line)
                    if len(out) > 25:
                        print("     ... {} more".format(len(out) - 25))
                    if args.verbose:
                        print("     pyRevit: " + short(ref))
                        print("     C# host: " + short(new))
                else:
                    print("same {}".format(label))
    if not args.ref_only:
        print("\n{} cases, {} differ, {} known differences".format(total, bad, known))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
