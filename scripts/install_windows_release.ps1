param(
  [ValidateSet("claude-code", "claude-desktop", "cursor", "vscode-copilot", "opencode", "codex", "windsurf", "gemini", "zed", "antigravity")]
  [string]$Client = "opencode",

  [Parameter(Mandatory = $true)]
  [string]$InstanceUrl,

  [ValidateSet("browser", "basic", "oauth", "api_key")]
  [string]$AuthType = "browser",

  [string]$InstallDir = "$env:LOCALAPPDATA\servicenow-mcp",
  [switch]$InstallSkills
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

$BrowserZip = Get-ChildItem -Path $BundleDir -Filter "ms-playwright*.zip" -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($BrowserZip) {
  $BrowserCache = Join-Path $env:LOCALAPPDATA "ms-playwright"
  New-Item -ItemType Directory -Force $BrowserCache | Out-Null
  Expand-Archive -Path $BrowserZip.FullName -DestinationPath $BrowserCache -Force
  Write-Host "Installed bundled Playwright Chromium cache to $BrowserCache"
} else {
  Write-Host "No ms-playwright browser zip found next to install.ps1."
  Write-Host "If browser auth fails, install Chromium with Playwright or place the release ms-playwright zip next to install.ps1 and run again."
}

$setupArgs = @(
  "setup", $Client,
  "--server-command", $TargetExe,
  "--instance-url", $InstanceUrl,
  "--auth-type", $AuthType,
  "--skip-chromium"
)

if (-not $InstallSkills) {
  $setupArgs += "--skip-skills"
}

& $TargetExe @setupArgs

Write-Host ""
Write-Host "Installed ServiceNow MCP:"
Write-Host "  Server: $TargetExe"
Write-Host "Restart your MCP client so it loads the updated config."
