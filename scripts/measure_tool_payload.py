# -*- coding: utf-8 -*-
"""Measure the tools/list payload the MCP server sends to the client.

python scripts/measure_tool_payload.py [--json out.json] [--top 20]

Counts the JSON of each tool as the client receives it (name, description,
inputSchema, outputSchema, annotations). Tokens are estimated as chars / 4.
Honours RVTSS_TOOLSETS like the real server.
"""
import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def tool_json(tool):
    if hasattr(tool, "model_dump"):
        data = tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    else:  # pragma: no cover
        data = dict(tool)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def measure():
    import main

    tools = asyncio.run(main.mcp.list_tools())
    sizes = sorted(((t.name, len(tool_json(t))) for t in tools), key=lambda x: -x[1])
    total = sum(s for _n, s in sizes)
    return {"tool_count": len(sizes), "total_chars": total, "approx_tokens": total // 4,
            "per_tool": dict(sizes)}


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    res = measure()
    print("tools: {tool_count}  chars: {total_chars}  ~tokens: {approx_tokens}".format(**res))
    for name, size in list(res["per_tool"].items())[:args.top]:
        print("  {:<34} {:>6}".format(name, size))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main_()
