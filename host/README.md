# RVTSS Host: the Revit side in C#

A plain Revit add-in that serves the same `/revit_mcp/...` routes as the pyRevit extension, without pyRevit.
The MCP server (`main.py`, `tools/`) is unchanged: it only needs `REVIT_PORT=48885`.

| | pyRevit extension | RVTSS Host |
|---|---|---|
| Needs in Revit | pyRevit + Routes server enabled | nothing |
| Port | 48884 | 48885 (`RVTSS_HOST_PORT`) |
| Revit versions | what pyRevit supports | 2024, 2025, 2026, 2027 |
| `execute_revit_code` | IronPython 2.7 | IronPython 3.4 (embedded) |
| Token | body / query (Routes drops headers) | `X-RVTSS-Token` header, body or query |

Both can be loaded in the same Revit at the same time; they do not share anything.

## Layout

```
Directory.Build.props   build settings, one build per Revit year (-p:RevitYear=2024|2025|2026|2027)
RvtssHost/              shell add-in: HTTP server, main-thread dispatcher, loader, ribbon button
RvtssHost.Impl/         every route (Core/, Pure/, Modules/<Group>/); loaded from bytes by the shell
deploy.ps1              build + copy to dist\R<year> + write the .addin manifest (development)
PORTING.md              the rules the port follows (naming, data model, .NET Framework limits)
tests/Pure.Tests        Revit-free logic against vectors produced by the Python originals
tests/Exec.Tests        the embedded Python engine, outside Revit
tests/compare           same request to pyRevit and to the host, answers diffed
bench/                  speed comparison
```

## Install

* **Workstations:** `installer\build.ps1` builds one setup that installs the add-in for every Revit
  2024-2027 found, the MCP server and its Python. pyRevit is optional there.
* **Development:** close Revit, then `powershell -ExecutionPolicy Bypass -File host\deploy.ps1 -Year 2026`.
  It writes `%APPDATA%\Autodesk\Revit\Addins\2026\RvtssHost.addin`; `-Remove` deletes it.
* **Claude Code:** `claude mcp add -s user RVTSS -e REVIT_PORT=48885 -- uv run --project <ext> python <ext>\main.py`

After a change to the routes, `deploy.ps1 -Year 2026 -Reload` loads the new build into the running Revit
(needs the file `%APPDATA%\RVTSS\host-dev.flag`; without it the reload route does not exist).
A change to the shell (`RvtssHost/`) needs Revit closed.

## Verify

```
dotnet run --project host/tests/Pure.Tests -c Release -p:RevitYear=2026      # and RevitYear=2024 (.NET Framework)
uv run python tests/live/run_live.py --port 48885                            # the live self-test plan
uv run python host/tests/compare/compare_routes.py                           # needs pyRevit on 48884 too
```

The ribbon tab **RVTSS Host → Diagnostics → Run Self-Test** runs the same plan in process.
On Revit 2024 the bundled `tests/test.rvt` (2026 format) cannot be opened; put a model saved by 2024 next to
it as `test_2024.rvt` (or in `host/tests/models/`) to run the model-changing steps there.

Status on 2026-11-18:

| Revit | Runtime | Live self-test | Notes |
|---|---|---|---|
| 2026 | .NET 10 | 65 passed, 0 failed | 1,034 comparison cases against pyRevit: 0 unexplained differences |
| 2027 | .NET 10 | 63 passed, 2 skipped | skips: no document at start, no second project |
| 2024 | .NET Framework 4.8 | 64 passed, 1 failed | pyRevit fails the same step on that model (toposolid too thin for the template's type) |
| 2025 | .NET 8 | not run | builds; Revit 2025 was not available |

Not exercised by any test: real exports (PDF, DWG, IFC, NWC), links and CAD imports, synchronize with
central, worksets, rebar, MEP systems, purge with confirm.

## Intended differences from the pyRevit version

* **Bugs fixed.** `manage_element_types` duplicate / rename, `create_view` with a named view family type and
  `manage_groups` create with a name failed with `AttributeError: Name` (IronPython cannot read
  `ElementType.Name`). Material colours were returned as text like `#2292X2292X2292X`; they are real hex
  colours now. `list_category_parameters` returns sample values it could not read before.
* **Errors from Revit name their type** (`ArgumentException: ...`) and carry a hint; pyRevit reported every
  one as `Exception: ...`.
* **A request that waited too long for Revit's main thread is cancelled** (HTTP 503, code `REVIT_BUSY`) and
  never runs later. `/status/` waits for the main thread; `/ping/` does not.
* **Requests with an `Origin` header or a non-loopback `Host` header are refused.**
* **`execute_revit_code` is Python 3.** `print "x"`, `except E, e`, `dict.iteritems()` fail with a hint.
  `unicode`, `basestring`, `long`, `xrange` and `reduce` exist; `from pyrevit import revit, DB, UI, HOST_APP`
  is emulated, the rest of pyRevit is not there.
* **`session_info`** describes the host: `python_engine` is `csharp`, `pyrevit_version` is null.
* **Lists whose order came from a Python 2 dict** are in insertion order.
* **Malformed input** (a number where text is expected, a missing key) is still refused, but the error text
  can name a .NET type where Python named its own.
