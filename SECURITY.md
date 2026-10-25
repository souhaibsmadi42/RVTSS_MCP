# Security

RVTSS lets an AI client read and change a live Revit model. Treat it like giving that client a seat at your
Revit session.

## Threat model in one paragraph

pyRevit Routes is an HTTP server **without authentication**: any process that can reach its port (48884)
can call every RVTSS route, including `execute_revit_code` (arbitrary IronPython inside Revit). RVTSS adds
optional protection on top; the defaults favour backward compatibility, so harden them for shared or
networked machines.

## Recommended settings

| Goal | Setting |
|---|---|
| Nothing outside this PC can reach Revit | pyRevit Settings → Routes → host `127.0.0.1` (`/status/` warns otherwise) |
| Other local processes cannot drive Revit | `RVTSS_TOKEN=<random>` for the Revit process **and** the MCP server |
| No arbitrary code | `RVTSS_ALLOW_CODE_EXECUTION=0` (Revit env) or omit the `code` toolset |
| Review / audit without any change | `RVTSS_READ_ONLY=1` on the MCP server (hides modifying tools) **and** in Revit (refuses changes, saves, syncs, exports) |
| Revit in a VM | keep the token, set `RVTSS_ALLOW_REMOTE=1` on the MCP server deliberately |
| Fewer tools in the client's reach | `RVTSS_TOOLSETS=<profile>` |

## What RVTSS does for you

* Every model change runs in a named Revit transaction (undoable); dry runs roll back; large or destructive
  operations return a preview until confirmed.
* Unknown tool arguments are refused (a typo cannot turn a dry run into a real change).
* `batch_execute` is all-or-nothing and only accepts an allow-listed set of editing routes.
* The audit log (`%APPDATA%\RVTSS\logs`) records every request with a correlation id; secrets are redacted,
  lines capped, files rotated after 30 days. Executed code is logged (redacted).
* Claude Code: allow only the generated read-only list in the README, never `mcp__RVTSS__*`.

## Reporting a vulnerability

Please do not open a public issue for security problems. Contact the maintainer through GitHub
([souhaibsmadi42](https://github.com/souhaibsmadi42)) with a description, the affected version
(`rvtss_version`) and reproduction steps.
