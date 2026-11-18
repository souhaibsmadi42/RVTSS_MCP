<#
.SYNOPSIS
  Registers (or unregisters) an installed RVTSS extension folder with pyRevit. Used by the RVTSS installer.

.DESCRIPTION
  -Register:   adds -ExtRoot (the folder that CONTAINS RVTSS.extension) to [core] userextensions in
               pyRevit_config.ini and turns on the pyRevit Routes server ([routes] enabled = true, host and
               port added only when missing: 127.0.0.1:48884). Creates the ini when pyRevit has not written one yet.
  -Unregister: removes -ExtRoot from [core] userextensions. Routes settings are left as they are.
  The ini is backed up as <ini>.bak-<yyyyMMdd-HHmmss> before any change and written back as UTF-8 without BOM.

  Exit codes: 0 done, 2 done but another RVTSS copy (a second extension registering the revit_mcp API) is
  visible to pyRevit; only one copy may be enabled. Details go to -Log.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExtRoot,
    [string]$Ini = (Join-Path $env:APPDATA "pyRevit\pyRevit_config.ini"),
    [switch]$Register,
    [switch]$Unregister,
    [string]$Log = ""
)

$ErrorActionPreference = "Stop"
$ExtRoot = [IO.Path]::GetFullPath($ExtRoot).TrimEnd('\')
$lines = New-Object System.Collections.ArrayList
function Say([string]$m) { [void]$lines.Add($m); Write-Host $m }
$utf8 = New-Object Text.UTF8Encoding $false
$exit = 0

try {
    $text = if (Test-Path -LiteralPath $Ini) { [IO.File]::ReadAllText($Ini) } else { "" }
    $text = $text.TrimStart([char]0xFEFF)
    $nl = if ($text -match "`r`n") { "`r`n" } elseif ($text -match "`n") { "`n" } else { "`r`n" }

    # value of key in section (raw text after '=') or $null
    function Get-Key([string]$t, [string]$section, [string]$key) {
        $m = [regex]::Match($t, "(?ms)^\[$section\][^\[]*?^$key\s*=\s*([^\r\n]*)")
        if ($m.Success) { return $m.Groups[1].Value.Trim() }
        return $null
    }
    function Set-Key([string]$t, [string]$section, [string]$key, [string]$value) {
        if ($t -notmatch "(?m)^\[$section\]") {
            $t = $(if ($t.Trim()) { $t.TrimEnd() + "$nl$nl" } else { "" }) + "[$section]$nl"
        }
        if ($null -ne (Get-Key $t $section $key)) {
            return [regex]::Replace($t, "(?ms)(^\[$section\][^\[]*?^)$key\s*=[^\r\n]*", { param($m) $m.Groups[1].Value + "$key = $value" })
        }
        return [regex]::Replace($t, "(?m)^\[$section\][ \t]*\r?$", { param($m) $m.Value.TrimEnd("`r") + "$nl$key = $value" + $(if ($m.Value.EndsWith("`r")) { "`r" } else { "" }) })
    }

    $raw = Get-Key $text "core" "userextensions"
    $paths = @()
    if ($raw) {
        # Windows PowerShell 5.1 emits a JSON array as ONE object; pipe it through to enumerate the items
        try { $parsed = ConvertFrom-Json $raw; $paths = @($parsed | ForEach-Object { [string]$_ }) } catch { throw "Cannot parse [core] userextensions in ${Ini}: $raw" }
    }
    $paths = @($paths | Where-Object { $_ })
    $isOurs = { param($p) ([IO.Path]::GetFullPath([string]$p).TrimEnd('\')) -ieq $ExtRoot }
    $new = $text

    if ($Register) {
        if (-not ($paths | Where-Object { & $isOurs $_ })) { $paths += $ExtRoot }
        $new = Set-Key $new "core" "userextensions" (ConvertTo-Json -InputObject @($paths) -Compress)
        $new = Set-Key $new "routes" "enabled" "true"
        if ($null -eq (Get-Key $new "routes" "host")) { $new = Set-Key $new "routes" "host" '"127.0.0.1"' }
        if ($null -eq (Get-Key $new "routes" "port")) { $new = Set-Key $new "routes" "port" "48884" }
        $hostValue = Get-Key $new "routes" "host"
        $port = Get-Key $new "routes" "port"
        if ($port -ne "48884") { Say "NOTE: pyRevit Routes uses port $port; set REVIT_PORT=$port in the MCP server environment." }
        if ($hostValue -match '0\.0\.0\.0') { Say "WARNING: pyRevit Routes listens on all interfaces ($hostValue); 127.0.0.1 is safer." }
    } elseif ($Unregister) {
        $paths = @($paths | Where-Object { -not (& $isOurs $_) })
        if ($null -ne $raw) { $new = Set-Key $new "core" "userextensions" (ConvertTo-Json -InputObject @($paths) -Compress) }
    } else { throw "Pass -Register or -Unregister" }

    if ($new -ne $text) {
        if (Test-Path -LiteralPath $Ini) {
            $bak = "$Ini.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
            Copy-Item -LiteralPath $Ini $bak
            Say "backup: $bak"
        } else { New-Item -ItemType Directory -Force (Split-Path $Ini) | Out-Null }
        [IO.File]::WriteAllText($Ini, $new, $utf8)
        Say ("updated: $Ini (" + $(if ($Register) { "registered" } else { "unregistered" }) + " $ExtRoot)")
    } else { Say "no change needed in $Ini" }

    if ($Register) {
        # other extension folders pyRevit will load that also register the revit_mcp API
        $roots = @((Join-Path $env:APPDATA "pyRevit\Extensions")) + @($paths | Where-Object { -not (& $isOurs $_) })
        $others = @()
        foreach ($r in $roots) {
            if (-not (Test-Path -LiteralPath $r)) { continue }
            $cands = @(Get-ChildItem -LiteralPath $r -Directory -Filter "*.extension" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
            if ($r -like "*.extension") { $cands += $r }
            foreach ($c in $cands) {
                $s = Join-Path $c "startup.py"
                if ((Test-Path -LiteralPath $s) -and (Select-String -LiteralPath $s -Pattern 'routes.API\("revit_mcp"\)' -Quiet)) { $others += $c }
            }
        }
        $others = @($others | Sort-Object -Unique)
        if ($others) {
            Say ("WARNING: another RVTSS copy is visible to pyRevit: " + ($others -join "; ") + ". Keep only one enabled (pyRevit Settings > Extensions).")
            $exit = 2
        }
    }
} catch {
    Say ("ERROR: " + $_.Exception.Message)
    $exit = 1
}
if ($Log) { [IO.File]::WriteAllLines($Log, [string[]]$lines, $utf8) }
exit $exit
