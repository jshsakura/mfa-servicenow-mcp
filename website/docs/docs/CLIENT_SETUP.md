# MCP Client Configuration

Detailed setup for each MCP client. All clients use the same MCP server — only the config format differs.

> **Recommended first:** run `servicenow-mcp setup <client> --instance-url ...` or use the AI-guided flow in [`llm-setup.md`](llm-setup.md). Use the config snippets below when you need to inspect, repair, or hand-manage an MCP config file.

---

## Before You Start

You need **two** things installed up front. Skip either and the first browser-auth tool call will stall trying to download mid-flight.

### 1. Install `uv`

`uv` handles Python, packages, and execution in one tool. The MCP server runs through `uvx`, which requires `uv`.

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installation. No Python install, pip, or venv needed.

### 2. Pre-install Chromium (REQUIRED)

The MFA/SSO login window is a Playwright-driven Chromium build — a hard dependency. Install it once via `uv tool install`, which adds the `playwright` binary to your PATH:

```bash
uv tool install playwright
playwright install chromium
```

> One-liner alternative: `uvx --with playwright playwright install chromium` — same result, slower per call because uvx creates an ephemeral venv each time.

The browser binary is cached at `~/.cache/ms-playwright/` (macOS/Linux) or `%USERPROFILE%\AppData\Local\ms-playwright\` (Windows) and shared across MCP versions. Re-run `playwright install chromium` only when you upgrade Playwright itself.

> Windows users: see [Windows Installation Guide](WINDOWS_INSTALL.md) for step-by-step details and proxy/antivirus notes.

### Quick Test

Verify the server starts before configuring your client:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

If the server starts and a browser window opens for login, you're ready to configure your client below.

---

## Configuration Guide

> **`args` is for the package only** — instance URL, auth, credentials all go in `env` (or `environment`). This keeps args clean and makes it easy to swap instances per project.

> **Project-local recommended**: Use project-scoped config so each project can connect to a different ServiceNow instance.

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
        "SERVICENOW_USERNAME": "your.username",
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
        "SERVICENOW_USERNAME": "your.username",
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
# Share login state with other MCP hosts (Claude, Cursor, ...) by pointing
# them all at the SAME absolute path. Codex.app on macOS is sandboxed and
# remaps `~`, so without this each host writes its own session cache and
# every host prompts a fresh MFA login. Replace `/Users/me` with $HOME.
SERVICENOW_BROWSER_USER_DATA_DIR = "/Users/me/.servicenow_mcp/shared/profile_acme"
MCP_TOOL_PACKAGE = "standard"
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
        "SERVICENOW_USERNAME": "your.username",
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
        "SERVICENOW_USERNAME": "your.username",
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
        "SERVICENOW_USERNAME": "your.username",
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
