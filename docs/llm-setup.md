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
   > 5. full — Broadest packaged surface with bundled workflows (124 tools)

   Store as `$TOOL_PACKAGE`. Default: `standard`

5. **Headless browser**
   > Run browser in headless mode? (no visible window)
   > Recommended: No (so you can see and complete MFA prompts)

   Store as `$HEADLESS`. Default: `false`

### Step 4 — Run the installer command

**IMPORTANT: Always default to project-local installation when the client supports it.** Use `--scope global` only if the user explicitly asks for a global install.

Build a single installer command and run it from the current project root. The installer now owns:
- client-specific config file paths
- merge/update behavior for existing config files
- optional skills installation for supported clients

Base command:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS"
```

Add flags only when needed:

- If the user provided username: `--username "$USERNAME"`
- If the user provided password: `--password "$PASSWORD"`
- For OAuth: add `--client-id`, `--client-secret`, and optionally `--token-url`
- For API key: add `--api-key` and optionally `--api-key-header`
- If the user wants global install: add `--scope global`
- If the user does **not** want skills: add `--skip-skills`

Examples:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup codex \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type basic \
  --username "your.username" \
  --password "your-password"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup claude-code \
  --instance-url "https://your-instance.service-now.com" \
  --scope global \
  --skip-skills
```

### Step 5 — Verify installation

1. Confirm the installer exited successfully
2. Read the config file path reported by the installer summary
3. If skills were installed, confirm the installed skills directory exists
4. Do **not** manually rewrite the config unless the installer failed and you are explicitly repairing it

### Step 6 — Tell the user what happens next

After installation, tell the user:

> **Installation is complete!**
> Restart your AI client (or reload MCP servers) so it picks up the new configuration.
>
> On the first browser-authenticated tool call, a browser window will open for MFA/SSO login.
> After login, try: `Run a health check on my ServiceNow instance`
> Full docs: https://jshsakura.github.io/mfa-servicenow-mcp/

Do **not** attempt to call ServiceNow MCP tools in the current session after setup. The client must restart first.

### Important notes for the LLM

- **Never hardcode credentials** in config files without asking. If the user skips credentials, omit them entirely from the config.
- The installer merges into existing config files. Do not hand-roll config merges unless recovery is needed.
- **Windows paths** use backslashes. Use the correct path separator for the OS.
- If any step fails, diagnose the error and help the user fix it before moving on.
- Keep the conversation friendly and concise. Don't dump walls of text.
- After installation, do NOT try to test MCP tools. Just tell the user to restart and they're good to go.
