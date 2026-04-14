# MCP Client Configuration

Detailed setup for each MCP client. All clients use the same MCP server — only the config format differs.

> **Credentials**: `SERVICENOW_USERNAME` and `SERVICENOW_PASSWORD` are optional. They prefill the browser login form for MFA/SSO. On Windows, set these as system environment variables instead of config files.

---

## Claude Desktop

Config file: `claude_desktop_config.json`

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Claude Code

### Option A: CLI (one command)

```bash
claude mcp add servicenow -- \
  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

### Option B: `.mcp.json` in project root

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## OpenCode

Config file: `opencode.json` in project root.

> OpenCode uses `environment` (not `env`) and supports `$schema`.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "SERVICENOW_BROWSER_TIMEOUT": "120",
        "SERVICENOW_BROWSER_SESSION_TTL": "30",
        "MCP_TOOL_PACKAGE": "standard"
      }
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
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://your-instance.service-now.com",
  "--auth-type", "browser",
  "--browser-headless", "false",
  "--browser-username", "your.username",
  "--browser-password", "your-password",
  "--tool-package", "standard",
]
```

---

## AntiGravity

Config file:
- **macOS / Linux:** `~/.gemini/antigravity/mcp_config.json`
- **Windows:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> Edit via agent panel: **...** → **Manage MCP Servers** → **View raw config**. Click **Refresh** after saving.

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Gemini / Vertex AI

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
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
