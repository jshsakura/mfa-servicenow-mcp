# Windows Installation Guide

Use `uvx` by default. If endpoint security/Zscaler blocks `uvx` or package downloads, use the release zip/exe section below.

---

## Step 1: Default uvx install

Open PowerShell without admin privileges:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --with playwright playwright install chromium
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser"
```

`uvx` does not use a locally installed Playwright Python package. It can reuse a matching Chromium already present in the standard Playwright browser cache. If Chromium is missing, run the Playwright install command above.

---

## Step 2: Release zip/exe install

Use this when `uvx` is blocked. Download `servicenow-mcp-windows-x64-<version>.zip` from GitHub Releases. It contains a single PyInstaller-built `servicenow-mcp.exe` plus `LICENSE`. No installer script is needed — the executable handles Chromium discovery itself. Pick a stable folder you control (e.g. `C:\Users\you\apps\servicenow-mcp\`), extract `servicenow-mcp.exe` into it, and — if you have the Chromium zip — **extract it up front** into the same folder. Don't leave the `.zip` lying around. The extracted folder name can stay as Windows produced it or be renamed to `ms-playwright\`; the executable globs for any sibling `ms-play*` directory at startup:

```
C:\Users\you\apps\servicenow-mcp\
├── servicenow-mcp.exe
└── ms-playwright-chromium-windows-x64-<ver>\   (default extracted name works)
    └── chromium-1185\
        └── …
```

At startup the executable looks for any sibling `ms-play*\chromium-*` directory and points Playwright at it via `PLAYWRIGHT_BROWSERS_PATH` for the current process only. It does not touch the system standard Playwright cache (`%LOCALAPPDATA%\ms-playwright`), does not modify any MCP client config, and does not write anywhere on disk.

Then paste this into your client config file (Claude Code / Claude Desktop example):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe",
      "args": [],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

`SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` are optional MFA login pre-fill. If you put Chromium somewhere other than the sibling `ms-playwright\` directory, add `"PLAYWRIGHT_BROWSERS_PATH": "C:/abs/path/to/ms-playwright"` to the `env` block. Snippets for Codex (`config.toml`) / OpenCode (`opencode.json`) / Cursor / Gemini / Zed live in the [Client Setup Guide](CLIENT_SETUP.md).

This keeps `uvx` out of runtime entirely.

If Chromium isn't bundled and downloads are allowed, install Python from <https://www.python.org/downloads/>, then run:

```powershell
py -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = "$HOME\apps\servicenow-mcp\ms-playwright"
py -m playwright install chromium
```

If the Playwright browser download is blocked too, download `ms-playwright-chromium-windows-x64-<version>.zip` from the same release and extract its contents to:

```text
%LOCALAPPDATA%\ms-playwright
```

Playwright browser docs: <https://playwright.dev/python/docs/browsers>

---

## Step 3: Build release assets

Maintainers build the release zip on Windows:

```powershell
py scripts\build_desktop_release.py --browser-zip
```

This creates the executable zip and the optional Playwright Chromium cache zip for blocked networks.

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
**Remove skills only:** delete the skill directory manually (for example `Remove-Item -Recurse .claude\commands\servicenow\`).

---

## Step 6: Verify

1. **Fully quit and restart** your MCP client (close the tray icon too).
2. The browser window opens on the first tool call (not on server start).
3. Complete MFA authentication via Okta/Microsoft Authenticator/etc.
4. After authentication, the browser closes automatically and the session persists.

Test: call the `sn_health` tool from your client.

> If the browser doesn't open, check that Chromium was installed. You can force-install it with: `uvx --with playwright playwright install chromium`

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
| `core` | 12 | Minimal read-only essentials for health, schema, discovery, and key lookups |
| `standard` | 31 | **(Default)** Read-only package across incidents, changes, portal, logs, and source analysis |
| `service_desk` | 33 | standard + incident and change operational writes |
| `portal_developer` | 43 | standard + portal, changeset, script include, and local-sync delivery workflows |
| `platform_developer` | 47 | standard + workflow, Flow Designer, UI policy, incident/change, and script writes |
| `full` | 62 | Broadest packaged surface: all `manage_*` workflows plus advanced operations |

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
→ Chromium must be installed before MCP startup:
```powershell
uvx --with playwright playwright install chromium
```
→ If browser download is blocked, use the matching `ms-playwright-chromium-windows-x64-<version>.zip` release asset and extract it to `%LOCALAPPDATA%\ms-playwright`.

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
