<#
.SYNOPSIS
  Builds the per-user Windows installer for RVTSS (pyRevit extension + MCP server), for Coordify workstations.

.DESCRIPTION
  1. Stages the extension (tracked files only, without tests/media/website/CI) as payload\RVTSS.extension
  2. Copies a relocatable CPython (uv-managed python-build-standalone) to payload\python and installs the
     runtime dependencies pinned in uv.lock into it (no dev/test packages)
  3. Smoke-tests the payload: MCP initialize + tools/list (Revit does not need to run)
  4. Compiles installer\rvtss.iss with Inno Setup into installer\Output\

  The payload is staged OUTSIDE this folder (%TEMP%\rvtss-installer-build) so pyRevit never sees a second
  copy of the extension. Build machine needs git, uv and Inno Setup 6; the installer needs none of them
  and no internet. pyRevit itself must be installed on the workstation (the installer checks).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\build.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.13",
    [string]$Iscc = "",
    [string]$Build = (Join-Path $env:TEMP "rvtss-installer-build"),
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Root = Split-Path -Parent $Here
$Payload = Join-Path $Build "payload"
$Ext = Join-Path $Payload "RVTSS.extension"
# tracked top-level entries that are development-only
$Skip = @(".github", "tests", "media", "website", "vercel.json", "installer", ".gitignore", ".python-version")

function Invoke-Checked([string]$What, [scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Copy-Tree([string]$From, [string]$To, [string[]]$ExcludeDirs = @(), [string[]]$ExcludeFiles = @()) {
    $rcArgs = @($From, $To, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($ExcludeDirs) { $rcArgs += "/XD"; $rcArgs += $ExcludeDirs }
    if ($ExcludeFiles) { $rcArgs += "/XF"; $rcArgs += $ExcludeFiles }
    & robocopy @rcArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

if (-not $Iscc) {
    foreach ($c in @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $c) { $Iscc = $c; break }
    }
}
if (-not $Iscc -or -not (Test-Path $Iscc)) { throw "Inno Setup 6 (ISCC.exe) not found; pass -Iscc <path>" }
foreach ($tool in @("uv", "git")) { if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is needed on the build machine" } }

$Version = (& uv run --no-project --python $PythonVersion python -c "import tomllib;print(tomllib.load(open(r'$Root\pyproject.toml','rb'))['project']['version'])").Trim()
Write-Host "RVTSS $Version, Python $PythonVersion"

# --- 1. extension files (tracked files, working-tree content)
if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }
New-Item -ItemType Directory -Force $Ext | Out-Null
$files = & git -C $Root ls-files
if ($LASTEXITCODE -ne 0) { throw "git ls-files failed" }
foreach ($f in $files) {
    if ($Skip -contains ($f -split "/")[0]) { continue }
    $src = Join-Path $Root $f
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }
    $dst = Join-Path $Ext $f
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath $src $dst
}

# --- 2. relocatable Python + locked dependencies
Invoke-Checked "uv python install" { & uv python install $PythonVersion }
$srcPython = (& uv python find --managed-python $PythonVersion).Trim()
$py = Join-Path $Payload "python\python.exe"
Copy-Tree (Split-Path -Parent $srcPython) (Join-Path $Payload "python") @("test", "idlelib", "turtledemo", "tkinter", "tcl", "__pycache__", "site-packages", "Scripts", "include", "libs") @("EXTERNALLY-MANAGED")
New-Item -ItemType Directory -Force (Join-Path $Payload "python\Lib\site-packages") | Out-Null
$req = Join-Path $Build "requirements.txt"
Push-Location $Root
try {
    Invoke-Checked "uv export" { & uv export --frozen --no-dev --no-hashes --no-emit-project --format requirements-txt -o $req }
} finally { Pop-Location }
Invoke-Checked "uv pip install" { & uv pip install --python $py --no-deps --link-mode copy --compile-bytecode -r $req }
Invoke-Checked "compileall" { & $py -m compileall -q -j 0 (Join-Path $Payload "python\Lib") (Join-Path $Ext "main.py") (Join-Path $Ext "tools") }
New-Item -ItemType Directory -Force (Join-Path $Payload "setup") | Out-Null
Copy-Item (Join-Path $Here "pyrevit-register.ps1") (Join-Path $Payload "setup")

# --- 3. smoke test
if (-not $SkipSmokeTest) {
    Write-Host "Smoke test (payload):"
    Invoke-Checked "smoke test" { & $py -I (Join-Path $Here "smoke_test.py") -- $py (Join-Path $Ext "main.py") }
}

# --- 4. installer
Invoke-Checked "ISCC" { & $Iscc "/DAppVersion=$Version" "/DPayloadDir=$Payload" (Join-Path $Here "rvtss.iss") }
$out = Get-ChildItem (Join-Path $Here "Output") -Filter "RVTSS-Setup-$Version.exe" | Select-Object -First 1
Write-Host ("Installer: " + $out.FullName + "  (" + [math]::Round($out.Length / 1MB, 1) + " MB)")
