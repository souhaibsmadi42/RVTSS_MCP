"""Start an MCP stdio server, initialize it and list its tools.

Usage:
    python smoke_test.py [--env NAME=VALUE]... -- <command> [args...]

Exits 0 when the server answers initialize and returns at least one tool.
Only the standard library is used, so any Python 3.8+ can run it.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time


def main():
    argv = sys.argv[1:]
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    while argv and argv[0] == "--env":
        key, _, value = argv[1].partition("=")
        env[key] = value
        argv = argv[2:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(__doc__)
        return 2

    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=os.path.expanduser("~"))
    lines = queue.Queue()
    stderr = []
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout], daemon=True).start()
    threading.Thread(target=lambda: [stderr.append(l) for l in proc.stderr], daemon=True).start()

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        proc.stdin.flush()

    def wait(msg_id, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            try:
                raw = lines.get(timeout=0.5)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if obj.get("id") == msg_id:
                return obj
        tail = b"".join(stderr[-30:]).decode("utf-8", "replace")
        raise SystemExit("no answer to request %s (exit code %s)\n%s" % (msg_id, proc.poll(), tail))

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "installer-smoke-test", "version": "1"}}})
        init = wait(1)
        if "error" in init:
            raise SystemExit("initialize failed: %s" % init["error"])
        info = init["result"].get("serverInfo", {})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools, cursor, msg_id = [], None, 2
        while True:
            send({"jsonrpc": "2.0", "id": msg_id, "method": "tools/list",
                  "params": {"cursor": cursor} if cursor else {}})
            page = wait(msg_id)
            if "error" in page:
                raise SystemExit("tools/list failed: %s" % page["error"])
            tools += [t["name"] for t in page["result"].get("tools", [])]
            cursor = page["result"].get("nextCursor")
            msg_id += 1
            if not cursor:
                break
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=15)
        except Exception:
            proc.kill()

    print("server: %s %s" % (info.get("name", "?"), info.get("version", "")))
    print("tools: %d" % len(tools))
    print(", ".join(tools))
    return 0 if tools else 1


if __name__ == "__main__":
    sys.exit(main())
