<#
.SYNOPSIS
  Copies the bundled servicenow-mcp.exe to %LOCALAPPDATA%\servicenow-mcp
  (or -InstallDir) and, if a ms-playwright Chromium zip sits next to
  this script, extracts it into the standard Playwright browser cache.

.DESCRIPTION
  This script does NOT modify any MCP client config — paste the config
  snippet from the README's "Local install" section into your client by
  hand to avoid breaking existing entries.
#>
param(
  [string]$InstallDir = "$env:LOCALAPPDATA\servicenow-mcp"
)

$ErrorActionPreference = "Stop"

$BundleDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe = Join-Path $BundleDir "servicenow-mcp.exe"
if (-not (Test-Path $SourceExe)) {
  throw "Missing $SourceExe. Run this script from the extracted release zip."
}

New-Item -ItemType Directory -Force $InstallDir | Out-Null
$TargetExe = Join-Path $InstallDir "servicenow-mcp.exe"
Copy-Item $SourceExe $TargetExe -Force

$BrowserDir = Join-Path $InstallDir "ms-playwright"
$ExistingChromium = Get-ChildItem -Path $BrowserDir -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ExistingChromium) {
  Write-Host "Chromium already installed at $($ExistingChromium.FullName) - skipping bundled zip."
} else {
  $BrowserZip = Get-ChildItem -Path $BundleDir -Filter "ms-playwright*.zip" -File -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($BrowserZip) {
    New-Item -ItemType Directory -Force $BrowserDir | Out-Null
    Expand-Archive -Path $BrowserZip.FullName -DestinationPath $BrowserDir -Force
    Write-Host "Extracted bundled Chromium to $BrowserDir"
  } else {
    Write-Host "No ms-playwright zip found next to install.ps1 and $BrowserDir is empty."
    Write-Host "Place the matching ms-playwright zip next to install.ps1 and rerun, or run"
    Write-Host "  `$env:PLAYWRIGHT_BROWSERS_PATH = '$BrowserDir'; playwright install chromium"
    Write-Host "on a host with internet access."
  }
}

Write-Host ""
Write-Host "Installed ServiceNow MCP:"
Write-Host "  Server:                   $TargetExe"
Write-Host "  PLAYWRIGHT_BROWSERS_PATH: $BrowserDir"
Write-Host ""
Write-Host "Next: paste the MCP config snippet from the README 'Local install' section"
Write-Host "      into your client's config file (e.g. .mcp.json / %USERPROFILE%\.codex\config.toml / opencode.json)."
Write-Host "      Set 'command' to:                     $TargetExe"
Write-Host "      Set env 'PLAYWRIGHT_BROWSERS_PATH' to: $BrowserDir"
Write-Host "      Then restart your MCP client."
