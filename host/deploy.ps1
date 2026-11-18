<#
.SYNOPSIS
  Builds the RVTSS Host add-in for one Revit year and puts it where Revit loads it from.

.DESCRIPTION
  Build output goes to host\out\main\R<year>; the add-in Revit loads lives in host\dist\R<year>
  (Revit locks RvtssHost.dll there while it runs, so builds never write to it directly).

    .\deploy.ps1 -Year 2026              build, copy to dist, write the .addin manifest (Revit <year> closed)
    .\deploy.ps1 -Year 2026 -Reload      build, copy only the routes (RvtssHost.Impl.dll) and reload them in
                                         the running Revit - needs %APPDATA%\RVTSS\host-dev.flag
    .\deploy.ps1 -Year 2026 -Remove      delete the .addin manifest (Revit <year> closed)

  The manifest is %APPDATA%\Autodesk\Revit\Addins\<year>\RvtssHost.addin. Nothing else outside this folder is
  touched. pyRevit keeps port 48884; the host listens on 48885 (RVTSS_HOST_PORT).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet("2024", "2025", "2026", "2027")][string]$Year,
    [switch]$Reload,
    [switch]$Remove,
    [int]$Port = 48885
)

$ErrorActionPreference = "Stop"
$addinDir = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$Year"
$manifest = Join-Path $addinDir "RvtssHost.addin"
$out = Join-Path $PSScriptRoot "out\main\R$Year"
$dist = Join-Path $PSScriptRoot "dist\R$Year"

function Test-RevitRunning {
    foreach ($p in Get-Process -Name Revit -ErrorAction SilentlyContinue) {
        try { if ($p.Path -like "*Revit $Year*") { return $true } } catch { return $true }
    }
    return $false
}

if ($Remove) {
    if (Test-RevitRunning) { Write-Host "Revit $Year is running. Close it first."; exit 1 }
    if (Test-Path -LiteralPath $manifest) {
        Remove-Item -LiteralPath $manifest -Confirm:$false
        Write-Host "Removed $manifest"
    } else {
        Write-Host "Nothing to remove: $manifest does not exist"
    }
    exit 0
}

& dotnet build (Join-Path $PSScriptRoot "RvtssHost.Impl") -c Release "-p:RevitYear=$Year" -nologo -v q
if ($LASTEXITCODE -ne 0) { Write-Host "Build failed."; exit 1 }

New-Item -ItemType Directory -Force $dist | Out-Null

if ($Reload) {
    # Only the files Revit does not lock: the routes assembly and its private dependencies.
    Get-ChildItem -LiteralPath $out -File | Where-Object { $_.Name -notlike "RvtssHost.dll" -and $_.Name -notlike "RvtssHost.pdb" } |
        ForEach-Object { try { Copy-Item -LiteralPath $_.FullName -Destination $dist -Force } catch { } }
    try {
        $r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/revit_mcp/_reload/" -TimeoutSec 60
        Write-Host ("Reloaded: " + ($r | ConvertTo-Json -Compress))
    } catch {
        Write-Host "Reload failed: $($_.Exception.Message)"
        Write-Host "Is Revit $Year running with the host loaded, and does %APPDATA%\RVTSS\host-dev.flag exist?"
        exit 1
    }
    exit 0
}

if (Test-RevitRunning) {
    Write-Host "Revit $Year is running. Close it first (or use -Reload to update only the routes)."
    exit 1
}
if (-not (Test-Path -LiteralPath $addinDir)) {
    Write-Host "Revit $Year add-ins folder not found: $addinDir"
    exit 1
}
Get-ChildItem -LiteralPath $dist -File | Remove-Item -Confirm:$false
Copy-Item -Path (Join-Path $out "*") -Destination $dist -Recurse -Force

$dll = Join-Path $dist "RvtssHost.dll"
$xml = @"
<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>RVTSS Host</Name>
    <Assembly>$dll</Assembly>
    <FullClassName>RvtssHost.App</FullClassName>
    <ClientId>6f0c2a51-9d3e-4b7a-8c15-2e4d7a9b3f10</ClientId>
    <VendorId>RVTSS</VendorId>
    <VendorDescription>RVTSS, Suhaib Al Smadi</VendorDescription>
  </AddIn>
</RevitAddIns>
"@
[IO.File]::WriteAllText($manifest, $xml, (New-Object Text.UTF8Encoding $false))
Write-Host "Deployed to $dist"
Write-Host "Manifest: $manifest"
Write-Host "Start Revit $Year and choose 'Always Load' if it asks about RvtssHost."
