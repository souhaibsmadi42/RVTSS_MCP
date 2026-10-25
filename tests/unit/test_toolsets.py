# -*- coding: utf-8 -*-
"""Phase 3: toolsets, deprecated aliases, schema compaction and the tool payload budget."""
import asyncio
import json
import os
import subprocess
import sys


from tools import toolsets as TS
from tools._compat import compact_schema

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE_V20 = 119369  # docs/metrics/tool_payload_v2.0.json (mcp 2.3)


def test_parse_toolsets():
    assert TS.enabled_toolsets("") == set(TS.TOOLSETS)
    assert TS.enabled_toolsets("all") == set(TS.TOOLSETS)
    assert TS.enabled_toolsets("families") == {"core", "families"}
    assert TS.enabled_toolsets("bim_coordinator") == {"core", "model", "parameters", "documentation", "qc"}
    assert TS.enabled_toolsets("qc, nonsense") == {"core", "qc"}


def test_toolset_tables_are_consistent():
    seen = {}
    for name, tools in TS.TOOLSETS.items():
        for t in tools:
            assert t not in seen, "%s in %s and %s" % (t, seen[t], name)
            seen[t] = name
    assert set(TS.DEPRECATED) <= set(TS.TOOLSETS["legacy"])
    for profile in TS.PROFILES.values():
        assert set(profile) <= set(TS.TOOLSETS)


class Recorder(object):
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def deco(func):
            self.tools[kwargs.get("name") or func.__name__] = kwargs
            return func
        return deco

    def resource(self, *a, **k):
        return lambda func: func

    prompt = resource


def _register(toolsets):
    from tools import register_tools

    async def fake(*a, **k):
        return {"status": "success"}
    rec = Recorder()
    proxy = register_tools(rec, fake, fake, fake, toolsets=toolsets)
    return rec, proxy


def test_every_registered_tool_belongs_to_a_toolset():
    rec, proxy = _register(set(TS.TOOLSETS))
    unmapped = [n for n in rec.tools if n not in TS.TOOL_TO_SET]
    assert unmapped == []
    assert proxy.skipped == []


def test_toolset_filter_and_deprecation_notes():
    rec, proxy = _register({"core", "qc"})
    assert set(rec.tools) == set(TS.TOOLSETS["core"]) | set(n for n in TS.TOOLSETS["qc"] if n in rec.tools)
    assert "family_create" in proxy.skipped and "list_families" in proxy.skipped
    rec, _ = _register({"legacy"} | {"core"})
    assert rec.tools["list_families"]["description"].startswith("[Deprecated: use get_family_inventory]")
    # descriptions are one paragraph; full docs kept for the docs resource
    desc = rec.tools["get_session_info"]["description"]
    assert "\n\n" not in desc
    assert len(TS.TOOL_DOCS["get_session_info"]) > len(desc) + 50


def test_compact_schema_keeps_meaning():
    schema = {"title": "Args", "type": "object", "required": ["a"],
              "properties": {"a": {"title": "A", "type": "string"},
                             "title": {"title": "Title", "type": "string"},  # a field literally named title
                             "b": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "B",
                                   "description": "bee"},
                             "c": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}],
                                   "default": None}},
              "$defs": {"M": {"title": "M", "type": "object", "properties": {"x": {"title": "X", "type": "boolean",
                                                                                   "default": False}}}}}
    out = compact_schema(schema)
    assert out == {"type": "object", "required": ["a"],
                   "properties": {"a": {"type": "string"}, "title": {"type": "string"},
                                  "b": {"type": "integer", "description": "bee"},
                                  "c": {"anyOf": [{"type": "string"}, {"type": "number"}]}},
                   "$defs": {"M": {"type": "object", "properties": {"x": {"type": "boolean", "default": False}}}}}


def _payload(env=None):
    code = ("import json,sys; sys.path.insert(0, %r); from scripts.measure_tool_payload import measure; "
            "print(json.dumps(measure()))" % ROOT)
    e = dict(os.environ, **(env or {}))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=e, cwd=ROOT, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


V21_CHARS_PER_TOOL = 71202 / 77.0  # docs/metrics/tool_payload_v2.1_phase6.json


def test_default_payload_stays_compact():
    """v2.2 adds 22 tools (99 in all): still smaller than v2.0's 74 tools, and per tool within 5 % of v2.1."""
    res = _payload({"RVTSS_TOOLSETS": ""})
    assert res["tool_count"] >= 99
    assert res["total_chars"] <= BASELINE_V20 * 0.82, res["total_chars"]
    assert res["total_chars"] / float(res["tool_count"]) <= V21_CHARS_PER_TOOL * 1.05, res["total_chars"]


def test_profile_payload_is_smaller_still():
    res = _payload({"RVTSS_TOOLSETS": "bim_coordinator"})
    assert res["tool_count"] < 50 and res["total_chars"] < BASELINE_V20 * 0.4


def test_server_still_accepts_valid_arguments_after_compaction():
    import main

    async def go():
        names = [t.name for t in await main.mcp.list_tools()]
        return names
    assert "find_elements" in asyncio.run(go())
