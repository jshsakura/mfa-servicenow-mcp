# ServiceNow MCP Windows Setup Script
$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " ServiceNow MCP Windows Setup (Native/Browser) " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# 1. Check/Install uv
if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "`n[*] Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path += ";$env:USERPROFILE\.cargo\bin"
}

# 2. Setup Environment
if (Test-Path "pyproject.toml") {
    Write-Host "`n[*] Source code detected. Setting up local virtual environment..." -ForegroundColor Green
    uv venv
    uv pip install -e ".[dev]"
    $runCmd = "uv run servicenow-mcp"
} else {
    Write-Host "`n[*] Source code not found. Installing mfa-servicenow-mcp as a global tool..." -ForegroundColor Yellow
    uv tool install mfa-servicenow-mcp
    $runCmd = "servicenow-mcp"
}

# 3. Install Playwright Browser (Mandatory for MFA)
Write-Host "`n[*] Installing Playwright Chromium engine..." -ForegroundColor Yellow
uv run playwright install chromium

# 4. Configuration Helper
$envPath = Join-Path (Get-Location) ".env"
if (!(Test-Path $envPath)) {
    Write-Host "`n[*] Creating initial .env configuration..." -ForegroundColor Yellow
    $instanceUrl = Read-Host "Enter your ServiceNow Instance URL"
    
    $envContent = @"
SERVICENOW_INSTANCE_URL=$instanceUrl
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_USER_DATA_DIR=$env:USERPROFILE\.mfa-servicenow-browser
"@
    $envContent | Out-File -FilePath $envPath -Encoding UTF8
}

Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host " Setup Complete!" -ForegroundColor Green
Write-Host " To start the server:" -ForegroundColor White
Write-Host "   $runCmd" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Cyan
