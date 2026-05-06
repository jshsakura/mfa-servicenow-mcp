# Windows Installation Guide

`uv` handles Python and packages. **Chromium for the MFA/SSO login window must be installed up front** — without it, the first tool call has to download ~150 MB on the spot, which on a slow link pushes MCP startup past the host's timeout and looks like the login window never opens.

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

## Step 2: Pre-install Chromium (REQUIRED)

This is a **hard dependency**, not an optional step. ServiceNow MFA/SSO login goes through a Playwright-driven Chromium window; if Chromium is missing when the MCP server starts, it tries to download mid-flight and the host times out before login can finish.

Install Chromium once. The recommended path is `uv tool install playwright` so the `playwright.exe` lands in `%USERPROFILE%\.local\bin\` and you can call it directly afterwards:

```powershell
uv tool install playwright
playwright install chromium
```

> One-liner alternative: `uvx --with playwright playwright install chromium` — same result, slightly slower because uvx spins up a fresh venv each call.

The browser binary is cached at `%USERPROFILE%\AppData\Local\ms-playwright\` and shared across MCP versions. Re-run `playwright install chromium` only when you upgrade Playwright itself.

> Behind a strict proxy / antivirus? Whitelist `playwright.azureedge.net` and `*.googleapis.com` for the duration of this install.

---

## Step 3: Run the MCP Server

With uv and Chromium in place, MCP startup is instant on every call:

```powershell
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser" `
  --browser-headless "false"
```

A browser window opens on the first tool call for MFA/SSO login (Okta, Entra ID, SAML). After authentication, the browser closes automatically and the session persists.

---

## Step 4: Configure Your MCP Client

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

### OpenCode

Config file location: `opencode.json` in your project root.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Zed

Config file location: `~/.config/zed/settings.json`

> Add via **Settings** > **MCP Servers** in Zed:

```json
{
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

---

## Step 5: Install Skills (Optional)

Skills are AI execution blueprints — verified pipelines with safety gates that turn raw MCP tools into reliable workflows. 16 skills across 5 categories.

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# Or with uvx (no install needed)
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

| Client | Install Path | Auto-Discovery |
|--------|-------------|----------------|
| Claude Code | `.claude\commands\servicenow\` | `/servicenow` slash commands appear on next startup |
| OpenAI Codex | `.codex\skills\servicenow\` | Skills loaded on next agent session |
| OpenCode | `.opencode\skills\servicenow\` | Skills loaded on next session |

| Category | Skills | Purpose |
|----------|--------|---------|
| `analyze/` | 6 | Widget analysis, portal diagnosis, dependency mapping, code detection |
| `fix/` | 3 | Widget patching (staged safety gates), debugging, code review |
| `manage/` | 8 | Page layout, script includes, source export, app source download, changeset workflow, local sync, workflow management, skill management |
| `deploy/` | 2 | Change request lifecycle, incident triage |
| `explore/` | 5 | Health check, schema discovery, route tracing, flow trigger tracing, ESC catalog flow |

**Update:** Re-run the same install command to replace all existing skill files.
**Remove full setup:** `uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp remove claude-code`
**Remove skills only:** delete the skill directory manually (for example `Remove-Item -Recurse .claude\commands\servicenow\`) if you intentionally want to keep the MCP config.

---

## Step 6: Verify

1. **Fully quit and restart** your MCP client (close the tray icon too).
2. The browser window opens on the first tool call (not on server start).
3. Complete MFA authentication via Okta/Microsoft Authenticator/etc.
4. After authentication, the browser closes automatically and the session persists.

Test: call the `sn_health` tool from your client.

> If the browser doesn't open, check that Chromium was installed automatically. You can force-install it with: `uvx playwright install chromium`

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
|---------|:-----:|-------------|
| `core` | 15 | Minimal read-only essentials for health, schema, discovery, and key lookups |
| `standard` | 45 | **(Default)** Read-only package across incidents, changes, portal, logs, and source analysis |
| `service_desk` | 46 | standard + incident and change operational writes |
| `portal_developer` | 55 | standard + portal, changeset, script include, and local-sync delivery workflows |
| `platform_developer` | 55 | standard + workflow, Flow Designer, UI policy, incident/change, and script writes |
| `full` | 66 | Broadest packaged surface: all `manage_*` workflows plus advanced operations |

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
→ Chromium is auto-installed on first run. If it fails, install manually:
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
`uvx` reuses the last cached version it downloaded. It does **not** automatically refresh to a newer release on every run. To pull the latest published version into cache:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

After refreshing, fully restart your MCP client so it launches the new cached version.
