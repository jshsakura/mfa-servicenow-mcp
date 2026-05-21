# MCP Client Configuration

Detailed setup for each MCP client. All clients use the same MCP server — only the config format differs.

> **Recommended first:** use the `uvx` setup command below. If `uvx` is blocked by corporate security tooling, use the release zip/exe section.

---

## Before You Start

Use `uvx` by default. It keeps install and client config consistent across macOS, Linux, and Windows.

### 1. Install uv

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Install Playwright Chromium

```bash
uvx --with "playwright==1.58.0" playwright install chromium
```

Playwright uses its standard browser cache. `uvx` does not use a locally installed Playwright Python package, but it can reuse a matching Chromium already present in that cache.

### 3. Run setup

```bash
uvx --with "playwright==1.58.0" --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

```powershell
uvx --with "playwright==1.58.0" --from mfa-servicenow-mcp servicenow-mcp setup opencode `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser"
```

### Local install (release zip/exe)

Use this when `uvx` or PyPI is blocked. The release zip is a single PyInstaller-built executable — **no installer script, no Python required, no system-cache pollution**. The executable auto-detects a `ms-playwright/` directory sitting next to itself.

**1. Download.** Executable from the [latest release](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest); the optional Chromium bundle (only if the network also blocks Playwright's Chromium download) from the long-lived [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) release.

| Platform | Required (latest release) | Add if Chromium download is blocked (chromium-bundle release) |
|----------|---------------------------|----------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. Lay it out** in any stable directory you control. **Extract both zips up front** — don't leave the `.zip` files alongside the executable. The Chromium zip's extracted folder just has to start with `ms-play` and contain a `chromium-*` subdirectory:

```
~/apps/servicenow-mcp/                                  (any directory you choose)
├── servicenow-mcp                                      ← from the platform zip (.exe on Windows)
└── ms-playwright-chromium-linux-x64-<ver>/             ← default extracted name works
    └── chromium-1185/
        └── …
```

(Rename to `ms-playwright/` if you want a tidier name — both work.) At startup the executable globs for any sibling `ms-play*` directory and, on finding a `chromium-*` subdirectory inside, points Playwright at it via `PLAYWRIGHT_BROWSERS_PATH` for the current process only. It does **not** touch the system Playwright cache, **not** modify any MCP client config, **not** write anywhere on disk.

**3. Verify, then wire your MCP client:**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

Paste the MCP config snippet from the [Configuration Guide](#configuration-guide) below into your client's config file, setting `command` to the absolute path of your executable. The `env` block is the same as the uvx setup — only `command` changes. If you put Chromium somewhere other than next to the executable, add `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` to the `env` block.

If you skipped the Chromium zip and Playwright's auto-download is blocked, pre-stage the directory on a machine with Python:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

The auto-detect picks it up with no extra config.

> Windows users: see [Windows Installation Guide](WINDOWS_INSTALL.md) for step-by-step details and proxy/antivirus notes.

### Quick Test

Verify the server starts before configuring your client:

```bash
uvx --with "playwright==1.58.0" --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

If the server starts and a browser window opens for login, you're ready to configure your client below.

---

## Configuration Guide

> **`args` is for the package only** — instance URL, auth, credentials all go in `env` (or `environment`). This keeps args clean and makes it easy to swap instances per project.

> **Project-local recommended**: Use project-scoped config so each project can connect to a different ServiceNow instance.

> **Single active instance by design**: ordinary tools route to one active ServiceNow instance only. This intentionally avoids request-time write switching, which can cause accidental writes to production when moving between dev/test/prod.

---

## Streamable HTTP

The default transport is `stdio`. For remote MCP clients or a local HTTP bridge, start the server with Streamable HTTP:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`; `/health` returns a lightweight status response. Keep the default loopback host unless the server is behind trusted network controls.

---

## Read-Only Data Comparison Mode

For dev/test drift analysis, you can configure named instances with `SERVICENOW_INSTANCE_CONFIG`. This mode is intentionally limited to data comparison:

- Ordinary tools still route only to `SERVICENOW_ACTIVE_INSTANCE`.
- Write-capable tools do not expose an instance selector.
- `compare_instances` is read-only and compares records across aliases.
- `list_instances` only reports configured aliases.
- Configure comparison aliases with read-only packages and `allow_writes=false`.
- Do not use this mode for write work across environments.

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev": {
    "url": "https://dev.service-now.com",
    "role": "development",
    "tool_package": "standard",
    "allow_writes": false
  },
  "test": {
    "url": "https://test.service-now.com",
    "role": "test",
    "tool_package": "standard",
    "allow_writes": false
  }
}'
```

Example comparison:

```json
{
  "source": "dev",
  "target": "test",
  "table": "sys_script_include",
  "key_field": "api_name",
  "fields": "api_name,name,active,script",
  "query": "sys_scope.scope=x_company_app"
}
```

Use separate project/client configs for actual work against another instance.

---

## Claude Desktop

| Scope | Path |
|-------|------|
| Global | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Global | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Claude Desktop does not support project-local config. Use Claude Code for per-project setup.

---

## Claude Code

| Scope | Path |
|-------|------|
| Global | `~/.claude.json` |
| Project | `.mcp.json` in project root |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Zed

| Scope | Path |
|-------|------|
| Global | `~/.config/zed/settings.json` |

Add via **Settings** > **MCP Servers** in Zed:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
    "env": {
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "SERVICENOW_USERNAME": "your-username",
      "SERVICENOW_PASSWORD": "your-password",
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

---

## OpenAI Codex (CLI & App)

Both **Codex CLI** (`codex` command) and **Codex App** (chatgpt.com/codex) read from the same `config.toml`.

| Scope | Path | Note |
|-------|------|------|
| Global | `~/.codex/config.toml` | Shared across all projects |
| Project | `.codex/config.toml` | Overrides global (trusted projects only) |

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
# Login is shared across hosts automatically (scoped per instance + user under
# ~/.mfa_servicenow_mcp). Only set SERVICENOW_BROWSER_USER_DATA_DIR if a sandboxed
# host remapped HOME — see the README "Login sharing" note. Do NOT set it when you
# run multiple instances; it collapses them into one Chromium profile.
```

---

## OpenCode

| Scope | Path |
|-------|------|
| Project | `opencode.json` in project root |

> OpenCode uses `environment` (not `env`).

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Gemini CLI

| Scope | Path |
|-------|------|
| Global | `~/.gemini/settings.json` |
| Project | `.gemini/settings.json` in project root |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## AntiGravity

| Scope | Path |
|-------|------|
| Global | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| Global | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> Edit via agent panel: **...** > **Manage MCP Servers** > **View raw config**. Click **Refresh** after saving.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Docker (API Key only)

> Browser auth (MFA/SSO) requires a GUI browser and does not work inside containers.

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
