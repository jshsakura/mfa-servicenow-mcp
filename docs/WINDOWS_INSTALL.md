# Windows Installation Guide

No need to install Python manually. `uv` handles everything.

---

## Step 1: Install uv

`uv` is a tool that manages Python versions and packages in one step.

Open PowerShell **without admin privileges** and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installation, **close and reopen PowerShell** (to refresh PATH).

Verify:
```powershell
uv --version
```

> If you get "uv not found", make sure you reopened PowerShell.
> If it still fails, check that `$env:USERPROFILE\.local\bin` is in your PATH.

---

## Step 2: Install Browser Engine

A Chromium browser engine is required for MFA/SSO authentication:

```powershell
uvx playwright install chromium
```

Verify installation:
```powershell
uvx playwright --version
```

> This installs a standalone binary, independent of your system Chrome.
> Chromium is stored in `%APPDATA%\ms-playwright`.
> "uvx not found" error → check that you restarted PowerShell in Step 1.

---

## Step 3: Configure Your MCP Client

Copy the configuration for your MCP client below.
Replace `your-instance` with your actual ServiceNow instance address.

### Claude Desktop

Config file location: `%APPDATA%\Claude\claude_desktop_config.json`

> Create the file if it doesn't exist. If the folder is missing, launch Claude Desktop once to create it.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Claude Code

Register via CLI — no config file needed:

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

Verify:
```powershell
claude mcp list
```

### AntiGravity

Config file location: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> Also accessible via agent panel **...** → **Manage MCP Servers** → **View raw config**.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Save the config, then click **Refresh** in AntiGravity.

### OpenAI Codex

Config file location: `%USERPROFILE%\.codex\agents.toml` or `.codex\agents.toml` in your project root.

> Create the file and folder if they don't exist.

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://your-instance.service-now.com",
  "--auth-type", "browser",
  "--browser-headless", "false",
  "--tool-package", "standard",
]
```

---

## Step 4: Verify

1. **Fully quit and restart** your MCP client (close the tray icon too).
2. The browser window opens on the first tool call (not on server start).
3. Complete MFA authentication via Okta/Microsoft Authenticator/etc.
4. After authentication, the browser closes automatically and the session persists.

Test: call the `sn_health` tool from your client.

> If the browser doesn't open, re-check Step 2 (Chromium installation).

---

## Session Management

Authenticated sessions are saved to disk automatically — no need to log in every time.

- **Session file location**: `%USERPROFILE%\.servicenow_mcp\session_*.json`
- **Default session TTL**: 30 minutes (keepalive thread extends every 15 minutes)
- **On session expiry**: browser window opens automatically for re-authentication

To change the TTL, use the `--browser-session-ttl` option (in minutes):
```
--browser-session-ttl 60
```

To persist the browser profile, add the `--browser-user-data-dir` option:
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
This stores cookies and login state in the directory for longer session persistence.

---

## Tool Packages

Set `MCP_TOOL_PACKAGE` to choose a tool set. Default: `standard` (read-only).

| Package | Tools | Description |
|---------|-------|-------------|
| `standard` | 55 | **(Default)** Read-only safe mode. All query tools included |
| `portal_developer` | 70 | standard + portal/widget/changeset writes |
| `platform_developer` | 78 | standard + workflow/incident/change management writes |
| `service_desk` | 59 | standard + incident create/resolve |
| `full` | 98 | All capabilities (including delete) |

To change, update the `MCP_TOOL_PACKAGE` value:

JSON clients (Claude Desktop, AntiGravity):
```json
"env": {
  "MCP_TOOL_PACKAGE": "portal_developer"
}
```

TOML clients (Codex) — add inside the `args` array:
```toml
"--tool-package", "portal_developer",
```

---

## Troubleshooting

### "uvx not found"
→ Make sure you **closed and reopened** PowerShell after Step 1. If still failing:
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### "Python is not installed"
→ `uv` automatically downloads Python 3.11+. No manual install needed.
If there's a conflict with system Python, uninstall and reinstall `uv`.

### "Browser won't open"
→ Check if Chromium is installed:
```powershell
uvx playwright --version
```
→ If not, reinstall:
```powershell
uvx playwright install chromium
```
→ Corporate proxies/firewalls may block the download. Check with your IT team.

### "MCP server won't connect"
→ Check config file syntax:
  - JSON: commas, quotes, matching braces
  - TOML: brackets, quotes, commas
→ Verify `instance-url` starts with `https://`.
→ Claude Desktop requires a **full quit and restart** after config changes (close tray icon too).

### "PowerShell script execution is blocked"
→ Allow execution for the current user:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "Corporate proxy/SSL certificate errors"
→ For environments with internal CA certificates:
```powershell
$env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
```
Or, after registering your company root certificate:
```powershell
$env:REQUESTS_CA_BUNDLE = "C:\path\to\company-ca-bundle.crt"
```

### Reset Session
If login issues persist, delete the session cache and retry:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### Version Update
`uvx` automatically fetches the latest version on every run. To force a cache refresh:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```
