# -*- coding: utf-8 -*-
"""RVTSS live smoke run against a running Revit + pyRevit Routes server.

    uv run python tests/live/run_live.py                    # full plan
    uv run python tests/live/run_live.py --groups family qc  # only some groups
    uv run python tests/live/run_live.py --no-model          # read-only, on the active document

Writes rvtss_live_report.json and rvtss_live_report.md (current folder and the
scratch folder). Model-changing steps only run after a COPY of tests/test.rvt
has been opened in Revit; families and shared parameter files go to
%TEMP%\\RVTSS_live on the Revit machine. Exit code 1 if any step failed.
"""
import argparse
import os
import shutil
import sys

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from revit_mcp.pure import selftest  # noqa: E402


def make_transport(base_url, timeout, token=None):
    client = httpx.Client(timeout=timeout)

    def transport(method, path, payload):
        url = base_url + path
        params = None
        if token:
            # pyRevit Routes does not pass HTTP headers to handlers, so the token
            # travels in the body (POST) or the query string (GET)
            if method == "POST":
                payload = dict(payload or {}, _rvtss_token=token)
            else:
                params = {"rvtss_token": token}
        try:
            if method == "GET":
                r = client.get(url, params=params)
            else:
                r = client.post(url, json=payload or {}, params=params)
        except httpx.TimeoutException:
            return 599, {"status": "error", "error": "timeout after %ss" % timeout,
                         "hint": "Revit busy, a modal dialog is open, or the operation is slow."}
        except httpx.ConnectError as e:
            return 598, {"status": "error", "error": "cannot connect: %s" % e,
                         "hint": "Is Revit running with the pyRevit Routes Server enabled?"}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"status": "error", "error": r.text[:500]}

    return transport


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("REVIT_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("REVIT_PORT", "48884")))
    ap.add_argument("--api", default=os.environ.get("REVIT_API_NAME", "revit_mcp"))
    ap.add_argument("--token", default=os.environ.get("RVTSS_TOKEN"))
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--groups", nargs="*", help="status setup original read edit family parameters qc")
    ap.add_argument("--model", default=os.path.join(ROOT, "tests", "test.rvt"))
    ap.add_argument("--no-model", action="store_true", help="do not open the test model (read-only run)")
    ap.add_argument("--scratch", help="scratch folder on the Revit machine (default: Revit %%TEMP%%\\RVTSS_live)")
    ap.add_argument("--out", default=".", help="folder for the report files")
    args = ap.parse_args(argv)

    base = "http://%s:%s/%s" % (args.host, args.port, args.api)
    transport = make_transport(base, args.timeout, args.token)
    status, info = transport("POST", "/session_info/", {})
    if status >= 400:
        print("Cannot use RVTSS at %s: %s" % (base, info.get("error")), file=sys.stderr)
        return 2
    scratch = args.scratch or os.path.join(info.get("temp_dir") or os.environ.get("TEMP", "/tmp"), "RVTSS_live")
    local = args.host in ("127.0.0.1", "localhost", "::1")
    if local and not os.path.isdir(scratch):
        os.makedirs(scratch)

    def prepare_model(t):
        if args.no_model or not os.path.isfile(args.model):
            return None
        if not local:
            print("Remote Revit: copy tests/test.rvt to the Revit machine and pass --scratch/--model", file=sys.stderr)
            return None
        dst = os.path.join(scratch, "RVTSS_selftest_%s.rvt" % t.stamp)
        shutil.copy2(args.model, dst)
        return dst

    report = selftest.run(transport, scratch, prepare_model, groups=args.groups, log=print,
                          environment={"transport": "http %s" % base, "runner_python": sys.version.split()[0]})
    os.makedirs(args.out, exist_ok=True)
    targets = [args.out] + ([scratch] if local and os.path.abspath(scratch) != os.path.abspath(args.out) else [])
    for folder in targets:
        with open(os.path.join(folder, "rvtss_live_report.json"), "w", encoding="utf-8") as fh:
            fh.write(selftest.to_json(report))
        with open(os.path.join(folder, "rvtss_live_report.md"), "w", encoding="utf-8") as fh:
            fh.write(selftest.to_markdown(report))
    s = report["summary"]
    print("\n%d passed, %d failed, %d skipped - report: %s" % (
        s["pass"], s["fail"], s["skip"], os.path.join(args.out, "rvtss_live_report.md")))
    return 1 if s["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
