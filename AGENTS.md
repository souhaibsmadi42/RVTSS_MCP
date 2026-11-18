# Installing RVTSS with an AI agent

This file is for coding agents (Claude Code, Codex, Cursor...) asked to install or repair RVTSS on a user's
Windows machine. Humans can follow the same steps. Work in this order, **show each change before making it,
and ask before writing** anything outside the RVTSS folder.

> Claude Code and Claude Desktop are different clients with different config files. Configure only the client
> the user named.

## 0. Ground rules

* Never delete another extension or MCP server entry. Rename or disable, and say what you did.
* Back up every config file before editing it (`<file>.bak-<date>`).
* Revit must be closed while you change pyRevit extensions; Claude Desktop must be fully quit (tray icon too)
  before you edit its config.
* Do not enable `RVTSS_ALLOW_REMOTE`, disable the token or turn on code execution policies on your own.

## 1. Inspect (read-only)

Shortcut: `powershell -ExecutionPolicy Bypass -File scripts\install.ps1` prints the checks below in one
table and changes nothing. Its `-Apply` mode asks before each change; still show the user the plan first.

Report what you find before changing anything:

1. pyRevit installed? `pyrevit env` (or look for `%APPDATA%\pyRevit-Master` / `%PROGRAMDATA%\pyRevit`).
2. Existing copies of the extension in `%APPDATA%\pyRevit\Extensions` and in pyRevit's custom extension
   directories: any `*.extension` folder containing `startup.py` with `routes.API("revit_mcp")`
   (`RVTSS.extension`, `revit-mcp-python.extension`, `mcp-server-for-revit-python.extension`...). **Only one
   may stay enabled**; two copies register the same API and conflict.
3. `%APPDATA%\pyRevit\pyRevit_config.ini`: `[routes]` section (`enabled`, `host`, `port`) and
   `[RVTSS.extension] disabled = ...`.
4. Python 3.11+ and `uv` (`uv --version`).
5. The target client's config:
   * Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json` (MSIX installs:
     `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude_desktop_config.json`).
   * Claude Code: `claude mcp list`.

## 2. Plan and ask

Propose the exact steps (clone path, config edits, which old copy to disable) and wait for the user's yes.

## 3. Install

```powershell
cd "$env:APPDATA\pyRevit\Extensions"
git clone https://github.com/souhaibsmadi42/RVTSS_MCP RVTSS.extension
cd RVTSS.extension
uv sync
```

pyRevit Routes: Settings → Routes → enable **Routes Server**, host `127.0.0.1`, port `48884`
(or in `pyRevit_config.ini` under `[routes]`: `enabled = true`, `host = "127.0.0.1"`, `port = 48884`).
If `[RVTSS.extension]` says `disabled = true`, set it to `false`.

## 4. Register the MCP server (only the requested client)

**Claude Code** (the server name `RVTSS` matches the README permission allow list):

```powershell
claude mcp add -s user RVTSS -- uv run --project "$env:APPDATA\pyRevit\Extensions\RVTSS.extension" python "$env:APPDATA\pyRevit\Extensions\RVTSS.extension\main.py"
```

**Claude Desktop**: merge this entry into `mcpServers` (keep every other entry):

```json
"RVTSS": {
  "command": "uv",
  "args": ["run", "--project", "C:\\Users\\<user>\\AppData\\Roaming\\pyRevit\\Extensions\\RVTSS.extension",
           "python", "C:\\Users\\<user>\\AppData\\Roaming\\pyRevit\\Extensions\\RVTSS.extension\\main.py"],
  "env": {"RVTSS_TOOLSETS": "all"}
}
```

Optional settings to offer (do not set them unasked): `RVTSS_TOOLSETS` (a profile such as
`bim_coordinator`, `architect`, `publisher`), `RVTSS_READ_ONLY=1` for review-only use, `RVTSS_TOKEN` (must
then also be set for Revit).

## 5. Verify

1. Start Revit, open a model. `http://127.0.0.1:48884/revit_mcp/status/` must show `"health": "healthy"` and
   the same `rvtss_version` as `revit_mcp/__init__.py`.
2. RVTSS tab → **Diagnostics → Run Self-Test** (works on a copy of `tests/test.rvt`); share the summary.
3. Restart the client and ask it to call `rvtss_health`. `next_step` must be empty.

## 5b. Alternative Revit side: RVTSS Host (C# add-in, no pyRevit)

Ask the user which Revit side they want; do not install both unasked. The add-in needs the .NET SDK to build.

1. Revit closed: `powershell -ExecutionPolicy Bypass -File host\deploy.ps1 -Year <2024|2025|2026|2027>`.
   It builds, copies to `host\dist\R<year>` and writes `%APPDATA%\Autodesk\Revit\Addins\<year>\RvtssHost.addin`
   (show this to the user first; `-Remove` deletes the manifest).
2. Register the MCP server with `-e REVIT_PORT=48885` (Claude Code) or `"env": {"REVIT_PORT": "48885"}`
   (Claude Desktop). Everything else in section 4 is unchanged.
3. Start Revit, choose **Always Load** for RvtssHost, open a model.
   `http://127.0.0.1:48885/revit_mcp/status/` must show `"health": "healthy"` and `"host": "csharp"`.
4. `uv run python tests/live/run_live.py --port 48885`, or the ribbon button *RVTSS Host → Diagnostics →
   Run Self-Test*.

The add-in and the pyRevit extension can be loaded together (ports 48885 and 48884); the MCP server talks to
one of them. Details and known differences: `host/README.md`.

## 6. Upgrade / uninstall

* Upgrade: close Revit, `git pull` in `RVTSS.extension`, `uv sync`, reload pyRevit, restart the client
  (the tool list changes between versions).
* Uninstall: remove the client entry (`claude mcp remove RVTSS` or the JSON entry), then delete or disable
  `RVTSS.extension`. `%APPDATA%\RVTSS` (logs, backups, snapshots, config) is kept unless the user asks.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Route does not exits` at `/revit_mcp/status/` | Extension disabled or not loaded: enable it, reload pyRevit. |
| `health: degraded` | `route_modules_failed` names the module; check the pyRevit log. |
| Timeouts, `/ping/` answers | Revit is busy (modal dialog, edit mode). Close it, then retry. |
| Version mismatch in `rvtss_health` | Revit loaded another copy of the extension, or the client runs an older checkout. |
| `RVTSS token missing or invalid` | Set the same `RVTSS_TOKEN` for Revit and the MCP server. |
