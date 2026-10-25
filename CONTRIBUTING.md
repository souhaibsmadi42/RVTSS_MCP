# Contributing to RVTSS

Thanks for helping. RVTSS has two halves that talk over HTTP:

* `revit_mcp/` + `startup.py`: pyRevit Routes inside Revit, **IronPython 2.7 and 3.4** (no f-strings, walrus,
  type hints or pathlib).
* `main.py` + `tools/`: the MCP server, CPython 3.11+, MCP SDK 1.9 and 2.x.

Read [LLM.txt](LLM.txt) "RVTSS additions" first: it lists the conventions in detail.

## Set up

```powershell
uv sync --extra test
uv run --extra test pytest tests/unit -q
```

## Add a tool (checklist)

1. **Revit route** in a module under `revit_mcp/` (or a new module registered in `revit_mcp/registry.py`):
   * an explicit route signature (`def x_route(doc, request)`, add `uidoc` if you need the selection or
     active view) that calls `core.handle(doc, request, impl)`;
   * `impl(ctx)` reads inputs with `ctx.get/require/int/list`, raises `core.RvtssError(message, status,
     hint=...)` for expected problems, and changes the model only through
     `core.run_transaction(doc, name, func, dry_run=ctx.dry_run)` + `core.commit_result(...)`;
   * large or destructive work: `core.confirm_gate()` + `core.preview_status()`;
   * Revit-independent logic goes to `revit_mcp/pure/` with unit tests.
2. **MCP tool** in `tools/`: annotate it (`READ_ONLY`, `MODIFIES`, `IDEMPOTENT`, `DESTRUCTIVE` from
   `tools/_compat.py`), build the payload with `_common.compact(...)` and send it with `_common.post` /
   `post_confirmable` / `call_with_progress`. The first docstring paragraph is what clients see: keep it to
   one or two lines; details go below (served as `rvtss://docs/tools/<name>`).
3. **Toolset:** add the name to `TOOLSETS` in `tools/toolsets.py`. If the tool is a single-POST edit that
   opens its own transaction, consider adding it to `BATCHABLE` (`tools/batch_tools.py`) **and**
   `BATCHABLE_ENDPOINTS` (`revit_mcp/batch.py`).
4. **Self-test:** add a step to `revit_mcp/pure/selftest.py` (model changes only after
   `t.require_test_model()`).
5. **Docs:** `python scripts/generate_tool_docs.py` (regenerates `docs/TOOLS.md` and the README allow list),
   then a CHANGELOG line.

## Before you open a pull request

```powershell
uv run --extra test pytest tests/unit -q
uv run --extra test python -m pyflakes tools main.py revit_mcp tests scripts startup.py
uv run --extra test vermin -q --no-tips -t=2.7- -t=3.4- --violations revit_mcp startup.py "RVTSS.tab"
uv run python scripts/generate_tool_docs.py
```

CI runs the same on Python 3.11–3.13 × MCP SDK 1.9 / 2.x. Revit API behaviour cannot be unit-tested here:
run **Diagnostics → Run Self-Test** in Revit and attach the report summary to the pull request when you
touch Revit-side code.
