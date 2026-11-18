<#
.SYNOPSIS
  Builds the per-user Windows installer for RVTSS (pyRevit extension + MCP server), for Coordify workstations.

.DESCRIPTION
  1. Stages the extension (tracked files only, without tests/media/website/CI) as payload\RVTSS.extension
  2. Copies a relocatable CPython (uv-managed python-build-standalone) to payload\python and installs the
     runtime dependencies pinned in uv.lock into it (no dev/test packages)
  3. Builds the RVTSS Host add-in (host\, C#) for Revit 2024-2027 into payload\host\R<year> and stages the
     self-test model as payload\host\tests\test.rvt (skipped with -SkipHost; needs the .NET SDK)
  4. Smoke-tests the payload: MCP initialize + tools/list (Revit does not need to run)
  5. Compiles installer\rvtss.iss with Inno Setup into installer\Output\

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
    [switch]$SkipSmokeTest,
    [switch]$SkipHost,
    [string[]]$RevitYears = @("2024", "2025", "2026", "2027")
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Root = Split-Path -Parent $Here
$Payload = Join-Path $Build "payload"
$Ext = Join-Path $Payload "RVTSS.extension"
# tracked top-level entries that are development-only
$Skip = @(".github", "tests", "media", "website", "vercel.json", "installer", "host", ".gitignore", ".python-version")

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
$srcPython = (& uv python find --managed-python --system $PythonVersion).Trim()
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

# --- 3. RVTSS Host add-in (C#), one build per Revit year
if (-not $SkipHost) {
    if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw "The .NET SDK (dotnet) is needed to build the RVTSS Host add-in; pass -SkipHost to leave it out" }
    $hostSrc = Join-Path $Root "host"
    foreach ($y in $RevitYears) {
        Invoke-Checked "dotnet build (Revit $y)" { & dotnet build (Join-Path $hostSrc "RvtssHost.Impl") -c Release "-p:RevitYear=$y" "-p:Lane=installer" -nologo -v q | Out-Host }
        $from = Join-Path $hostSrc "out\installer\R$y"
        if (-not (Test-Path (Join-Path $from "RvtssHost.dll")) -or -not (Test-Path (Join-Path $from "RvtssHost.Impl.dll"))) { throw "RVTSS Host build for Revit $y is incomplete: $from" }
        Copy-Tree $from (Join-Path $Payload "host\R$y") @("exec-tests") @("*.pdb", "Pure.Tests.*", "Exec.*")
    }
    $model = Join-Path $Root "tests\test.rvt"
    if (Test-Path $model) {
        New-Item -ItemType Directory -Force (Join-Path $Payload "host\tests") | Out-Null
        Copy-Item -LiteralPath $model (Join-Path $Payload "host\tests\test.rvt")
    }
}

# --- 4. smoke test
if (-not $SkipSmokeTest) {
    Write-Host "Smoke test (payload):"
    Invoke-Checked "smoke test" { & $py -I (Join-Path $Here "smoke_test.py") -- $py (Join-Path $Ext "main.py") }
}

# --- 5. installer
Invoke-Checked "ISCC" { & $Iscc "/DAppVersion=$Version" "/DPayloadDir=$Payload" (Join-Path $Here "rvtss.iss") }
$out = Get-ChildItem (Join-Path $Here "Output") -Filter "RVTSS-Setup-$Version.exe" | Select-Object -First 1
Write-Host ("Installer: " + $out.FullName + "  (" + [math]::Round($out.Length / 1MB, 1) + " MB)")
