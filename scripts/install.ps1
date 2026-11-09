<#
.SYNOPSIS
  Check and set up RVTSS on this Windows machine (pyRevit extension + MCP server).

.DESCRIPTION
  Default (no switch): read-only report of every requirement, with the fix for each.
  -Apply: makes the changes, after a yes/no question per change (or -Yes for all):
    * enables the pyRevit Routes server on 127.0.0.1:48884 and the RVTSS extension (pyRevit_config.ini)
    * runs `uv sync` for the MCP server
    * registers the MCP server in Claude Code (-Client code) or Claude Desktop (-Client desktop)
  Every config file is backed up as <file>.bak-<yyyyMMdd-HHmmss> first. Other extensions and MCP servers are
  never removed. Close Revit (and fully quit Claude Desktop) before -Apply.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Apply -Client code
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Yes,
    [ValidateSet("none", "code", "desktop")][string]$Client = "none",
    [string]$Toolsets = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Results = New-Object System.Collections.ArrayList
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Report([string]$Item, [string]$State, [string]$Detail, [string]$Fix = "") {
    [void]$Results.Add([pscustomobject]@{ Check = $Item; State = $State; Detail = $Detail; Fix = $Fix })
}

function Confirm-Change([string]$What) {
    if (-not $Apply) { return $false }
    if ($Yes) { return $true }
    $a = Read-Host "$What  [y/N]"
    return ($a -match '^(y|yes)$')
}

function Backup([string]$Path) {
    if (Test-Path $Path) {
        Copy-Item $Path "$Path.bak-$Stamp"
        Write-Host "  backup: $Path.bak-$Stamp"
    }
}

# --- Revit must be closed for config changes
$revit = Get-Process -Name Revit -ErrorAction SilentlyContinue
if ($revit) { Report "Revit running" "warn" "$($revit.Count) Revit process(es)" "Close Revit before -Apply" }

# --- pyRevit
$pyrevit = Get-Command pyrevit -ErrorAction SilentlyContinue
$master = Join-Path $env:APPDATA "pyRevit-Master"
if ($pyrevit -or (Test-Path $master)) {
    $ver = ""
    if ($pyrevit) { try { $ver = (& pyrevit --version 2>$null | Select-Object -First 1) } catch { } }
    Report "pyRevit" "ok" ("installed " + $ver).Trim()
} else {
    Report "pyRevit" "missing" "pyRevit not found" "Install pyRevit from https://github.com/pyrevitlabs/pyRevit/releases"
}

# --- extension copies (only one may register revit_mcp)
$extDir = Join-Path $env:APPDATA "pyRevit\Extensions"
$copies = @()
if (Test-Path $extDir) {
    Get-ChildItem $extDir -Directory -Filter "*.extension" | ForEach-Object {
        $s = Join-Path $_.FullName "startup.py"
        if ((Test-Path $s) -and (Select-String -Path $s -Pattern 'routes.API\("revit_mcp"\)' -Quiet)) { $copies += $_.FullName }
    }
}
if ($copies.Count -eq 1) { Report "Extension copies" "ok" $copies[0] }
elseif ($copies.Count -eq 0) { Report "Extension copies" "missing" "no RVTSS extension in $extDir" "git clone https://github.com/souhaibsmadi42/RVTSS_MCP `"$extDir\RVTSS.extension`"" }
else { Report "Extension copies" "warn" ($copies -join "; ") "Keep one; disable the others in pyRevit Settings > Extensions (do not delete)" }

# --- pyRevit config: routes + extension enabled
$ini = Join-Path $env:APPDATA "pyRevit\pyRevit_config.ini"
$iniText = if (Test-Path $ini) { Get-Content $ini -Raw } else { "" }
$routesOn = $iniText -match '(?ms)^\[routes\][^\[]*^enabled\s*=\s*true'
$hostOk = -not ($iniText -match '(?ms)^\[routes\][^\[]*^host\s*=\s*"?0\.0\.0\.0')
$extDisabled = $iniText -match '(?ms)^\[RVTSS\.extension\][^\[]*^disabled\s*=\s*true'
if ($routesOn -and $hostOk) { Report "Routes server" "ok" "enabled" } else {
    Report "Routes server" "missing" ("enabled=" + $routesOn + ", host ok=" + $hostOk) "pyRevit Settings > Routes: on, host 127.0.0.1, port 48884"
    if (Confirm-Change "Enable pyRevit Routes on 127.0.0.1:48884 in $ini?") {
        Backup $ini
        $t = $iniText
        if ($t -notmatch '(?m)^\[routes\]') { $t = $t.TrimEnd() + "`r`n`r`n[routes]`r`n" }
        foreach ($kv in @(@("enabled", "true"), @("host", '"127.0.0.1"'), @("port", "48884"))) {
            $k = $kv[0]; $v = $kv[1]
            if ($t -match "(?ms)^\[routes\][^\[]*^$k\s*=") {
                $t = [regex]::Replace($t, "(?ms)(^\[routes\][^\[]*?^)$k\s*=[^\r\n]*", "`${1}$k = $v")
            } else {
                $t = [regex]::Replace($t, "(?m)^\[routes\]\s*$", "[routes]`r`n$k = $v")
            }
        }
        Set-Content -Path $ini -Value $t -Encoding UTF8
        Write-Host "  Routes enabled."
    }
}
if ($extDisabled) {
    Report "RVTSS extension" "warn" "disabled in pyRevit_config.ini" "Set [RVTSS.extension] disabled = false"
    if (Confirm-Change "Enable the RVTSS extension in $ini?") {
        Backup $ini
        $t = Get-Content $ini -Raw
        $t = [regex]::Replace($t, "(?ms)(^\[RVTSS\.extension\][^\[]*?^)disabled\s*=\s*true", "`${1}disabled = false")
        Set-Content -Path $ini -Value $t -Encoding UTF8
    }
} else { Report "RVTSS extension" "ok" "not disabled" }

# --- Python + uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Report "uv" "ok" ((& uv --version) -join " ")
    $venv = Join-Path $Root ".venv"
    if (Test-Path $venv) { Report "MCP server env" "ok" $venv } else {
        Report "MCP server env" "missing" "no .venv" "uv sync (in $Root)"
        if (Confirm-Change "Run 'uv sync' in $Root?") { Push-Location $Root; try { & uv sync } finally { Pop-Location } }
    }
} else {
    Report "uv" "missing" "uv not on PATH" "powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`""
}

# --- clients
$mainPy = Join-Path $Root "main.py"
if ($Client -eq "code" -or $Client -eq "none") {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
        $list = (& claude mcp list 2>$null) -join "`n"
        if ($list -match '(?m)^RVTSS\b') { Report "Claude Code" "ok" "RVTSS registered" } else {
            Report "Claude Code" $(if ($Client -eq "code") { "missing" } else { "info" }) "RVTSS not registered" "claude mcp add -s user RVTSS -- uv run --project `"$Root`" python `"$mainPy`""
            if ($Client -eq "code" -and (Confirm-Change "Register RVTSS in Claude Code (user scope)?")) {
                & claude mcp add -s user RVTSS -- uv run --project "$Root" python "$mainPy"
            }
        }
    } elseif ($Client -eq "code") { Report "Claude Code" "missing" "claude CLI not found" "Install Claude Code" }
}
if ($Client -eq "desktop" -or $Client -eq "none") {
    $cfg = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
    $msix = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json" } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($msix) { $cfg = $msix }
    $has = (Test-Path $cfg) -and ((Get-Content $cfg -Raw) -match '"RVTSS"\s*:')
    if ($has) { Report "Claude Desktop" "ok" "RVTSS in $cfg" } else {
        Report "Claude Desktop" $(if ($Client -eq "desktop") { "missing" } else { "info" }) "RVTSS not in $cfg" "scripts\install.ps1 -Apply -Client desktop"
        if ($Client -eq "desktop") {
            if (Get-Process -Name Claude -ErrorAction SilentlyContinue) { throw "Quit Claude Desktop fully (tray icon too) first." }
            if (Confirm-Change "Add the RVTSS entry to $cfg (other servers are kept)?") {
                Backup $cfg
                $json = if (Test-Path $cfg) { Get-Content $cfg -Raw | ConvertFrom-Json } else { New-Object psobject }
                if (-not $json.PSObject.Properties["mcpServers"]) { $json | Add-Member mcpServers (New-Object psobject) }
                $entry = [pscustomobject]@{ command = "uv"; args = @("run", "--project", $Root, "python", $mainPy) }
                if ($Toolsets) { $entry | Add-Member env ([pscustomobject]@{ RVTSS_TOOLSETS = $Toolsets }) }
                $json.mcpServers | Add-Member -NotePropertyName RVTSS -NotePropertyValue $entry -Force
                New-Item -ItemType Directory -Force (Split-Path $cfg) | Out-Null
                ($json | ConvertTo-Json -Depth 10) | Set-Content -Path $cfg -Encoding UTF8
                Write-Host "  Claude Desktop entry added. Start Claude Desktop again."
            }
        }
    }
}

# --- live check (only when Revit runs)
try {
    $st = Invoke-RestMethod -Uri "http://127.0.0.1:48884/revit_mcp/ping/" -TimeoutSec 3
    Report "Routes answer" "ok" ("rvtss " + $st.rvtss_version)
} catch { Report "Routes answer" "info" "no answer (normal while Revit is closed)" "Start Revit, then run this again" }

$Results | Format-Table -AutoSize -Wrap
if (-not $Apply) { Write-Host "Read-only check. Run with -Apply (and -Client code|desktop) to fix what is missing." }
$bad = @($Results | Where-Object { $_.State -eq "missing" }).Count
exit ([int]($bad -gt 0))
