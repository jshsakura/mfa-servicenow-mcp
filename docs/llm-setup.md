# MFA ServiceNow MCP — LLM Setup Guide

> **This file is for LLM agents, not humans.**
> A human pastes the curl command below into their AI coding assistant.
> The LLM reads this file and walks the user through setup interactively.

---

## How to use (for humans)

Paste this into your AI coding assistant (Claude Code, Cursor, Codex, OpenCode, Windsurf, etc.):

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

That's it. Your AI handles the rest.

---

## Instructions for the LLM agent

You are setting up **mfa-servicenow-mcp** — an MCP server that gives AI agents access to ServiceNow platforms with MFA/SSO support. Follow every step below in order. Ask the user questions interactively; do NOT assume values.

### Step 0 — Detect environment

1. Detect the operating system: run `uname -s 2>/dev/null || echo Windows`
2. Detect which AI client you are running inside. Use this mapping:

| Signal | Client |
|--------|--------|
| You have access to `claude mcp add` or `.claude/` directory | **claude-code** |
| You are inside Cursor IDE or `.cursor/` exists | **cursor** |
| You have access to OpenCode CLI or `opencode.json` exists | **opencode** |
| You are inside Codex CLI or `.codex/` exists | **codex** |
| You are inside Windsurf IDE or `.windsurf/` exists | **windsurf** |
| You are inside VS Code with Copilot | **vscode-copilot** |
| You are inside Gemini CLI | **gemini** |
| You are inside Zed editor or `~/.config/zed/` exists | **zed** |
| None of the above | Ask the user which client they use |

3. If you cannot auto-detect, ask:
   > Which AI coding tool are you using?
   > 1. Claude Code
   > 2. Claude Desktop
   > 3. Cursor
   > 4. OpenCode
   > 5. Codex (OpenAI)
   > 6. Windsurf
   > 7. VS Code Copilot
   > 8. Gemini CLI
   > 9. Zed
   > 10. AntiGravity (Google)

Store the result as `$CLIENT`.

### Step 1 — Install uv

Check if `uv` is already installed: `uv --version`

If NOT installed:

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

After install, verify: `uv --version`
If the command is not found, the user may need to restart their shell or add `~/.local/bin` to PATH.

### Step 2 — Install Playwright browser

Run:
```bash
uvx --with playwright playwright install chromium
```

This installs a Chromium browser that handles MFA/SSO login flows. It is required for browser auth mode.

### Step 3 — Collect user configuration

Ask the user these questions one by one. Provide defaults in brackets.

1. **ServiceNow instance URL**
   > What is your ServiceNow instance URL?
   > Example: `https://your-company.service-now.com`

   Store as `$INSTANCE_URL`. Validate it looks like a URL.

2. **Authentication type**
   > How do you authenticate to ServiceNow?
   > 1. browser — MFA/SSO via real browser (recommended)
   > 2. basic — Username + password
   > 3. oauth — OAuth 2.0 client credentials
   > 4. api_key — REST API key

   Store as `$AUTH_TYPE`. Default: `browser`

3. **Credentials** (optional, for form pre-fill with browser auth)
   > (Optional) Enter your ServiceNow username to pre-fill the login form.
   > Leave blank to type it manually each time.

   Store as `$USERNAME` (may be empty).
   If provided, also ask for `$PASSWORD`.

4. **Tool package**
   > Which tool package do you need?
   > 1. standard — Core tools (incidents, changes, catalog) [default]
   > 2. service_desk — Standard + assignment, SLA, escalation
   > 3. portal_developer — Standard + portal widgets, pages, themes
   > 4. platform_developer — Standard + scripts, flows, update sets
   > 5. full — Everything (97+ tools)

   Store as `$TOOL_PACKAGE`. Default: `standard`

5. **Headless browser**
   > Run browser in headless mode? (no visible window)
   > Recommended: No (so you can see and complete MFA prompts)

   Store as `$HEADLESS`. Default: `false`

### Step 4 — Configure MCP for the client

**IMPORTANT: Always default to project-local installation.** Write config files in the user's current working directory (project root). Only use global/user-level config if the user explicitly asks for it. Each project should have its own ServiceNow instance configuration.

Based on `$CLIENT`, write the config file in the current directory. Replace all `$VARIABLES` with collected values.

---

#### claude-code

**Default: Project-local install.** Write `.mcp.json` in the current project root. This is the recommended approach — each project gets its own ServiceNow instance config.

Ask the user: "Install to this project, or globally for all projects?"
- **Project (default):** Write `.mcp.json` in the current project root
- **Global:** Use `claude mcp add --global` or write to `~/.claude.json`

If global, run:
```bash
claude mcp add --global servicenow -- \
  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --browser-headless "$HEADLESS"
```

For project-local (default), write `.mcp.json`:
```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

Remove `SERVICENOW_USERNAME` and `SERVICENOW_PASSWORD` from `env` if the user left them blank.

---

#### claude-desktop

Config file location:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

If the file already exists, **merge** into the existing `mcpServers` object — do NOT overwrite other servers.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### cursor

Config file: `.cursor/mcp.json` in project root.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### vscode-copilot

Config file: `.vscode/mcp.json` in project root.

```json
{
  "servers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### opencode

Config file: `opencode.json` in project root. Key differences: uses `environment` (not `env`), passes config via environment variables, wraps command in array.

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
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### codex

Config file: `.codex/config.toml` in project root (or `~/.codex/config.toml` for global).

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "$INSTANCE_URL",
  "--auth-type", "$AUTH_TYPE",
  "--browser-headless", "$HEADLESS",
  "--tool-package", "$TOOL_PACKAGE",
]
```

---

#### windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### gemini

Works with Gemini CLI. Config file: `~/.gemini/settings.json` (merge into existing).

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      },
      "enabled": true
    }
  }
}
```

---

#### zed

Config file: `~/.config/zed/settings.json` (macOS/Linux)

Merge the `context_servers` block into the existing `settings.json` — do NOT overwrite the entire file.

```json
{
  "context_servers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### antigravity

Config file:
- **macOS / Linux:** `~/.gemini/antigravity/mcp_config.json`
- **Windows:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

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
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

### Step 5 — Install skills (if supported)

Skills are LLM execution blueprints — verified pipelines with safety gates and exact tool calls. They are available for clients that support custom commands/skills.

Ask the user:
> Install ServiceNow skills (20+ workflow recipes for analysis, debugging, deployment)? [Y/n]

If yes, determine the skill target from `$CLIENT`:

| Client | Skill target | Install path |
|--------|-------------|--------------|
| claude-code | `claude` | `.claude/commands/servicenow/` |
| codex | `codex` | `.codex/skills/servicenow/` |
| opencode | `opencode` | `.opencode/skills/servicenow/` |
| gemini | `gemini` | `.gemini/skills/servicenow/` |
| cursor | — | Not yet supported (use CLAUDE.md rules instead) |
| windsurf | — | Not yet supported |
| zed | — | Not yet supported |
| vscode-copilot | — | Not yet supported |
| claude-desktop | — | Not applicable (no project workspace) |

For supported clients, run:
```bash
uvx --from mfa-servicenow-mcp servicenow-mcp-skills $SKILL_TARGET
```

For unsupported clients, inform the user:
> Skills are not yet supported for $CLIENT. MCP tools (97+) are fully available — skills support will be added in a future release.

### Step 6 — Verify installation

1. **Check uv:** `uv --version`
2. **Check playwright:** `uvx --with playwright playwright --version`
3. **Check config file exists:** Read the config file created in Step 4
4. **Check skills (if installed):** List the skill files to confirm they're in place

Report a summary to the user:

```
Setup complete!

  Client:       $CLIENT
  Instance:     $INSTANCE_URL
  Auth:         $AUTH_TYPE
  Tool package: $TOOL_PACKAGE
  Skills:       $SKILL_COUNT installed (or "not applicable")
  Config:       $CONFIG_FILE_PATH
```

**Next: Restart required**

After completing all installation steps above, tell the user:

> **Installation is complete!**
> To start using ServiceNow MCP tools, **restart your AI client** (or reload MCP servers).
>
> The MCP server loads when your client starts up. After restarting:
>
> 1. A browser window will open on the first tool call for MFA/SSO login
> 2. Complete the login — the session persists after that
> 3. Try: "Run a health check on my ServiceNow instance"
> 4. Full docs: https://jshsakura.github.io/mfa-servicenow-mcp/

This is the end of setup. Do NOT attempt to call ServiceNow MCP tools (`sn_health`, `sn_query`, etc.) in this session — they won't be available until the client restarts and loads the server process. Do not try to work around this by running the server via shell commands.

### Important notes for the LLM

- **Never hardcode credentials** in config files without asking. If the user skips credentials, omit them entirely from the config.
- **Always merge** into existing config files — never overwrite other MCP servers the user has configured.
- **Windows paths** use backslashes. Use the correct path separator for the OS.
- If any step fails, diagnose the error and help the user fix it before moving on.
- Keep the conversation friendly and concise. Don't dump walls of text.
- After installation, do NOT try to test MCP tools. Just tell the user to restart and they're good to go.
