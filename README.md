# MFA ServiceNow MCP

🌐 [English](./README.md) | 🇰🇷 [한국어](./README.ko.md) | 🚀 [**GitHub Pages**](https://jshsakura.github.io/mfa-servicenow-mcp/)

MFA-first ServiceNow MCP server. Authenticates via real browser (Playwright) so Okta, Entra ID, SAML, and any MFA/SSO login just works. Also supports API Key for headless/Docker environments.

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-live-blue?logo=github)](https://jshsakura.github.io/mfa-servicenow-mcp/)

```bash
# Paste this into any AI coding assistant for fully guided setup
Install and configure mfa-servicenow-mcp by following the instructions here:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

---

## Table of Contents

- [Features](#features)
- [AI-Powered Setup](#ai-powered-setup)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [MCP Client Configuration](#mcp-client-configuration)
- [Authentication](#authentication)
- [Tool Packages](#tool-packages)
- [CLI Reference](#cli-reference)
- [Keeping Up to Date](#keeping-up-to-date)
- [Safety Policy](#safety-policy)
- [Local Source Audit](#local-source-audit)
- [Skills](#skills)
- [Docker](#docker)
- [Developer Setup](#developer-setup)
- [Documentation](#documentation)
- [Related Projects](#related-projects-and-acknowledgements)
- [License](#license)

---

## AI-Powered Setup

> **One line. Any AI coding assistant. Everything configured automatically.**

Paste this into Claude Code, Cursor, Codex, OpenCode, Windsurf, VS Code Copilot, or Gemini CLI:

```
Install and configure mfa-servicenow-mcp by following the instructions here:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

Your AI will:
1. Install **uv** and **Playwright Chromium** (if needed — prevents first-login download stall)
2. Ask for your ServiceNow instance URL, auth type, and tool package
3. Generate the correct MCP config file for your client
4. Install **24 workflow skills** (if supported)

No manual config editing. No format differences to worry about. Works on macOS, Linux, and Windows.

After setup, **restart your AI client** (or reload MCP servers) to load the new configuration. A browser window will open on the first tool call for MFA login.

> For manual setup, see [Prerequisites](#prerequisites) and [Quick Start](#quick-start) below.

---

## Features

- **Browser authentication** for MFA/SSO environments (Okta, Entra ID, SAML, MFA)
- **4 auth modes**: Browser, Basic, OAuth, API Key
- **77 registered tools** with **6 active package profiles** plus disabled `none` — from minimal read-only to broad bundled CRUD
- **24 workflow skills** with safety gates, sub-agent delegation, and verified pipelines
- **Local source audit** with HTML report, cross-reference graph, dead code detection, and auto-generated domain knowledge
- **Cross-scope dep auto-resolve** in `download_app_sources` — pulls global-scope Script Includes, Widgets, Angular Providers, and UI Macros that the app references, so the local bundle is self-contained for analysis
- **Dry-run preview** on every write tool (`dry_run=True`) — returns field-level diff, dependency counts, and precision notes before any side effect. Uses read-only APIs, works under all auth modes.
- Safe write confirmation with `confirm='approve'`
- Payload safety limits, per-field truncation, and total response budget (200K chars)
- Transient network error retry with backoff
- Tool packages for core, standard, service desk, portal developers, and platform developers — `full` available for advanced users (see [warning](docs/TOOL_PACKAGES.md))
- Developer productivity tools: activity tracking, uncommitted changes, dependency mapping, daily summary
- Full coverage of core ServiceNow artifact tables (see [Supported Tables](#supported-servicenow-tables))
- CI/CD with auto-tagging, PyPI publishing, and Docker multi-platform builds

### Supported ServiceNow Tables

| Artifact Type | Table Name | Source Search | Developer Tracking | Safety (Heavy Table) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_client_script` | ✅ | ✅ | 🛡️ |
| Catalog Client Script | `catalog_script_client` | ✅ | ⬜ | ⬜ |
| UI Action | `sys_ui_action` | ✅ | ✅ | 🛡️ |
| UI Script | `sys_ui_script` | ✅ | ✅ | 🛡️ |
| UI Page | `sys_ui_page` | ✅ | ✅ | 🛡️ |
| UI Macro | `sys_ui_macro` | ✅ | ⬜ | 🛡️ |
| Scripted REST API | `sys_ws_operation` | ✅ | ✅ | 🛡️ |
| Fix Script | `sys_script_fix` | ✅ | ✅ | 🛡️ |
| Scheduled Job | `sysauto_script` | ✅ | ⬜ | ⬜ |
| Script Action | `sysevent_script_action` | ✅ | ⬜ | ⬜ |
| Email Notification | `sysevent_email_action` | ✅ | ⬜ | ⬜ |
| ACL | `sys_security_acl` | ✅ | ⬜ | ⬜ |
| Transform Script | `sys_transform_script` | ✅ | ⬜ | ⬜ |
| Processor | `sys_processor` | ✅ | ⬜ | ⬜ |
| Service Portal Widget | `sp_widget` | ✅ | ✅ | 🛡️ |
| Angular Provider | `sp_angular_provider` | ✅ | ✅ | ⬜ |
| Portal Header/Footer | `sp_header_footer` | ✅ | ⬜ | ⬜ |
| Portal CSS | `sp_css` | ✅ | ⬜ | ⬜ |
| Angular Template | `sp_ng_template` | ✅ | ⬜ | ⬜ |
| Metadata / XML Definitions | `sys_metadata` | ✅ | ⬜ | 🛡️ |
| Update XML | `sys_update_xml` | ✅ | ⬜ | ⬜ |

---

## Prerequisites

### 1. Install `uv`

[uv](https://astral.sh/uv) handles Python, packages, and execution in one tool — no separate Python install, no `pip`, no `venv`.

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

Restart your terminal after installation.

### 2. Pre-install Chromium (strongly recommended)

The MFA/SSO login flow needs a Playwright Chromium build. Without it, the **first** browser-auth tool call has to download Chromium (~150 MB) on the spot — which on a slow link can stretch MCP startup past the host's timeout and make the login window feel like it never opens. Install it once up front and the first tool call is instant:

```bash
uvx --with playwright playwright install chromium
```

Run again whenever you upgrade Playwright; the binary is cached locally and shared across MCP versions.

> Windows users: see the [Windows Installation Guide](./docs/WINDOWS_INSTALL.md) for PATH and antivirus notes.

---

## Quick Start

Recommended manual path: let the installer write the right MCP config for your client.

No clone needed. One command — works on macOS, Linux, and Windows:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

Replace `opencode` with your client (`claude-code`, `codex`, `cursor`, `gemini`, etc.). The installer merges the ServiceNow entry into your existing client config and installs skills when supported.

Add `--scope global` only if you want a global install instead of the default project-local setup.

To remove the setup later, run the matching client uninstall command:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp remove opencode
```

Add `--scope global` when removing a global install. Add `--keep-skills` if you only want to remove the MCP config entry and keep installed skills.

A browser window opens on the first browser-authenticated tool call for Okta/Entra ID/SAML/MFA login. Chromium is auto-installed if missing. Session persists after login — no need to re-authenticate every time.

> Want AI-guided setup instead? Use [AI-Powered Setup](#ai-powered-setup). Want raw server execution without writing client config? See [CLI Reference](#cli-reference).

---

## MCP Client Configuration

> Recommended: use the AI-guided flow above or run `servicenow-mcp setup <client> ...`. Use the copy-paste configs below when you need to inspect, repair, or hand-manage a client config file.

Each project can connect to a different ServiceNow instance. Set the config in your **project directory** so each project has its own instance URL and credentials.

| Client | Project Config | Global Config | Format |
|--------|---------------|--------------|--------|
| Claude Code | `.mcp.json` | `~/.claude.json` | JSON |
| Cursor | `.cursor/mcp.json` | *Project only* | JSON |
| VS Code (Copilot) | `.vscode/mcp.json` | *Project only* | JSON |
| Zed | *Global only* | `~/.config/zed/settings.json` | JSON |
| OpenAI Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML |
| Gemini CLI | `.gemini/settings.json` | `~/.gemini/settings.json` | JSON |
| OpenCode | `opencode.json` | *Project only* | JSON |
| Windsurf | *Global only* | `~/.codeium/windsurf/mcp_config.json` | JSON |
| Claude Desktop | *Global only* | `claude_desktop_config.json` | JSON |
| AntiGravity | *Global only* | `~/.gemini/antigravity/mcp_config.json` | JSON |
| Docker | *Env vars only* | *Env vars only* | Env vars |

Copy-paste configs for each client: **[Client Setup Guide](docs/CLIENT_SETUP.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` are optional — they prefill the MFA login form. On Windows, set these as system environment variables.

---

## Authentication

Choose the auth mode based on your ServiceNow environment.

### Browser Auth (MFA/SSO) — Default

The [Quick Start](#quick-start) command uses browser auth. Optional flags:

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | Prefill login form username |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | Prefill login form password |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | Run browser without GUI |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | Login timeout in seconds |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | Session TTL in minutes |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Persistent browser profile path. Session JSON is stored next to it, so multiple MCP hosts can share login state. |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | user-specific `sys_user` lookup when a username is known, otherwise `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | Session validation endpoint (avoids 401 on non-admin sessions) |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | Custom login page URL |

#### Sharing login across multiple MCP hosts (Codex + Claude, etc.)

When a single user runs the MCP server from more than one host (e.g. Claude Code **and** Codex side by side), each host normally resolves `~/.servicenow_mcp` to a different path — sandboxed apps may remap `HOME`, so they end up writing **different** session caches and each one prompts a fresh MFA login.

**Why a shared path is needed:** the server stores two artifacts — the Playwright profile (Chromium SSO cookies) and a session JSON (parsed cookies the MCP reuses on the next start). Without a shared root, host A's login is invisible to host B.

**Fix:** set `SERVICENOW_BROWSER_USER_DATA_DIR` to the **same absolute path** in every host's MCP config. The session JSON is now derived from the parent of that directory, so they share both the Chromium profile *and* the JSON cache.

```bash
# Pick any stable absolute path — example uses an instance-scoped folder
export SERVICENOW_BROWSER_USER_DATA_DIR="$HOME/.servicenow_mcp/shared/profile_acme"
```

Configure the same value in Codex's `~/.codex/config.toml`, Claude Desktop's `claude_desktop_config.json`, and any other client. Whichever host logs in first writes the session; the others pick it up on their next tool call without opening a browser.

### Basic Auth

Use this for PDIs or instances without MFA.

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth

Current CLI support expects OAuth password grant inputs.

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

If `--token-url` is omitted, the server defaults to `https://<instance>/oauth_token.do`.

### API Key

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

Default header: `X-ServiceNow-API-Key` (customizable with `--api-key-header`).

---

## Tool Packages

`MCP_TOOL_PACKAGE` controls which tools the server exposes. **Default: `standard`** — no config needed for most users.

> [!WARNING]
> **`full` is an advanced package for experienced users only.** It exposes all write tools across every domain simultaneously. An AI agent with `full` access can create, update, and delete records without domain constraints. Use the narrowest package that covers your actual work.

| Package | Tools | Description |
| :--- | :---: | :--- |
| `none` | 0 | Disabled profile for intentionally turning tools off |
| `core` | 15 | Minimal read-only essentials for health, schema, discovery, and key artifact lookups |
| `standard` | 45 | **(Default)** Read-only across incidents, changes, portal, logs, and source analysis |
| `service_desk` | 46 | standard + incident and change operational writes |
| `portal_developer` | 55 | standard + portal, changeset, script include, and local-sync delivery workflows |
| `platform_developer` | 55 | standard + workflow, Flow Designer, UI policy, incident/change, and script writes |
| `full` | 66 | ⚠️ **Advanced only** — all write tools across all domains. See warning above. |

If a tool is not available in your current package, the server tells you which package includes it.

For the full reference (all packages, inheritance details, config syntax): [Tool Packages Advanced Guide](docs/TOOL_PACKAGES.md).

---

## CLI Reference

### Server Options

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *required* | ServiceNow instance URL |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | Auth mode: `basic`, `oauth`, `api_key`, `browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | Tool package to load |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP request timeout (seconds) |
| `--debug` | `SERVICENOW_DEBUG` | `false` | Enable debug logging |

### Basic Auth

| Flag | Env Variable |
|------|-------------|
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### OAuth

| Flag | Env Variable |
|------|-------------|
| `--client-id` | `SERVICENOW_CLIENT_ID` |
| `--client-secret` | `SERVICENOW_CLIENT_SECRET` |
| `--token-url` | `SERVICENOW_TOKEN_URL` |
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### API Key

| Flag | Env Variable | Default |
|------|-------------|---------|
| `--api-key` | `SERVICENOW_API_KEY` | — |
| `--api-key-header` | `SERVICENOW_API_KEY_HEADER` | `X-ServiceNow-API-Key` |

### Script Execution

| Flag | Env Variable |
|------|-------------|
| `--script-execution-api-resource-path` | `SCRIPT_EXECUTION_API_RESOURCE_PATH` |

---

## Keeping Up to Date

> **`uvx` caches the last version it downloaded** and keeps reusing it.
> To get a new release you must explicitly refresh — it will NOT update on its own.

```bash
# Refresh the uvx cache to the latest PyPI release
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

After refreshing, **restart your MCP client** (Claude Code, Cursor, etc.) to load the new version.

### Pinning a specific version

```bash
# Example: pin to 1.8.17
uvx --from "mfa-servicenow-mcp==1.8.17" servicenow-mcp --version
```

To pin in an MCP client config, use the `--from` constraint in the command:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--from",
        "mfa-servicenow-mcp==1.8.17",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser"
      ]
    }
  }
}
```

### Version release process

1. Version is defined in `pyproject.toml` (`version = "x.y.z"`)
2. On push to `main`, CI auto-creates a git tag `v{version}` if it doesn't exist
3. Tagged pushes trigger PyPI publishing and GitHub Release creation
4. Docker images (standard + playwright variants) are built for `amd64` and `arm64`

---

## Safety Policy

All mutating tools are protected by explicit confirmation.

Rules:
1. Mutating tools with prefixes such as `create_`, `update_`, `delete_`, `remove_`, `add_`, `move_`, `activate_`, `deactivate_`, `commit_`, `publish_`, `submit_`, `approve_`, `reject_`, `resolve_`, `reorder_`, and `execute_` require confirmation.
2. You must pass `confirm='approve'`.
3. Without that parameter, the server rejects the request before execution.

This policy applies regardless of the selected tool package.

### Portal Investigation Safety

Portal investigation tools are conservative by default:

- `search_portal_regex_matches` starts with widget-only scanning, linked expansion off, and small default limits.
- `trace_portal_route_targets` is the preferred follow-up for compact Widget -> Provider -> route target evidence.
- `download_portal_sources` does not pull linked Script Includes or Angular Providers unless explicitly requested.
- Large portal scans are capped server-side and return warnings when the request exceeds safe defaults.

Pattern matching modes:

| Mode | Behavior |
|------|----------|
| `auto` (default) | Plain strings treated literally, regex-looking patterns remain regex |
| `literal` | Always escape the pattern first; safest for route/token strings |
| `regex` | Use only when you intentionally need regex operators |

---

## Performance Optimizations

The server includes several layers of performance optimization to minimize latency and token usage.

### Serialization

- **orjson backend**: All JSON serialization uses `json_fast` (orjson when available, stdlib fallback). 2-4x faster than stdlib `json` for both loads and dumps.
- **Compact output**: Tool responses are serialized without indentation or extra whitespace, saving 20-30% tokens per response.
- **Double-parse avoidance**: `serialize_tool_output` detects already-compact JSON strings and skips re-serialization.

### Caching

- **OrderedDict LRU cache**: Query results are cached with O(1) eviction using `OrderedDict.popitem()`. 256 max entries, 30-second TTL, thread-safe.
- **Tool schema cache**: Pydantic `model_json_schema()` output is cached per model type, avoiding repeated schema generation.
- **Lazy tool discovery**: Only tool modules required by the active `MCP_TOOL_PACKAGE` are imported at startup. Unused modules are skipped entirely.

### Network

- **HTTP session pooling**: Persistent `requests.Session` with 20-connection pool, TCP keep-alive, TLS session resumption, and gzip/deflate compression.
- **Parallel pagination**: `sn_query_all` fetches the first page sequentially for total count, then retrieves remaining pages concurrently via `ThreadPoolExecutor` (up to 4 workers).
- **Dynamic page sizing**: When remaining records fit in a single page (<=100), the page size is enlarged to avoid extra round-trips.
- **Batch API**: `sn_batch` combines multiple REST sub-requests into a single `/api/now/batch` POST, with automatic chunking at the 150-request limit.
- **Parallel chunked M2M queries**: Widget-to-provider M2M lookups split into 100-ID chunks are executed concurrently rather than sequentially.

### Schema & Startup

- **Shallow-copy schema injection**: Confirmation schema (`confirm='approve'`) is injected via lightweight dict copy instead of `copy.deepcopy`, reducing `list_tools` overhead.
- **No-count optimization**: Subsequent pagination pages use `sysparm_no_count=true` to skip server-side total count computation.
- **Payload safety**: Heavy tables (`sp_widget`, `sys_script`, etc.) have automatic field clamping and limit restrictions to prevent context window overflow.

## Local Source Audit

Download and analyze your entire ServiceNow application locally — no repeated API calls, no context waste.

```
Step 1: download_app_sources(scope="x_company_app")    → All server-side code + cross-scope deps to disk
Step 2: audit_local_sources(source_root="temp/...")     → Analysis + HTML report
```

Step 1 runs `auto_resolve_deps=True` by default: after the in-scope download it scans every
`.js/.html/.xml` file and fetches any referenced `sys_script_include`, `sp_widget`,
`sp_angular_provider`, or `sys_ui_macro` records not already in the bundle — no matter
what scope they live in. Pulled deps are saved into the same tree with
`"is_dependency": true` in their `_metadata.json`, so the audit in Step 2 sees the
complete call graph. Set `auto_resolve_deps=False` if you only want in-scope records.

### What Gets Generated

| File | Purpose |
|------|---------|
| `_audit_report.html` | Self-contained dark-theme HTML report — open in browser |
| `_cross_references.json` | Who calls who — Script Include chains, GlideRecord table refs |
| `_orphans.json` | Dead code candidates — unreferenced SIs, unused widgets |
| `_execution_order.json` | Per-table BR/CS/ACL execution sequence with order numbers |
| `_domain_knowledge.md` | Auto-generated app profile — table maps, hub scripts, warnings |
| `_schema/*.json` | Field definitions for every referenced table |

### Individual Download Tools

Each source type has a dedicated download tool — use the orchestrator for everything, or pick what you need:

| Tool | Sources |
|------|---------|
| `download_portal_sources` | Widgets, Angular Providers, linked Script Includes |
| `download_script_includes` | Script Includes (scope-wide) |
| `download_server_scripts` | Business Rules, Client Scripts, Catalog Client Scripts |
| `download_ui_components` | UI Actions, UI Scripts, UI Pages, UI Macros |
| `download_api_sources` | Scripted REST APIs, Processors |
| `download_security_sources` | ACLs (script-only by default) |
| `download_admin_scripts` | Fix Scripts, Scheduled Jobs, Script Actions, Email Notifications |
| `download_table_schema` | sys_dictionary field definitions |

All downloads write full source to disk with zero truncation. Only a summary is returned to the LLM context.

---

## Skills

Tools are raw API calls. Skills are what make your LLM actually useful — verified pipelines with safety gates, rollback, and context-aware sub-agent delegation. **MCP server + skills is the complete setup** for LLM-driven ServiceNow automation.

16 skills today, more coming with every release.

| | Tools Only | Tools + Skills |
|---|---|---|
| Safety | LLM decides | Gates enforced (snapshot → preview → apply) |
| Tokens | Source dumps in context | Delegate to sub-agent, summary only |
| Accuracy | LLM guesses tool order | Verified pipeline |
| Rollback | Might forget | Snapshot mandatory |

### Install Skills

```bash
# Claude Code
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude

# OpenAI Codex
uvx --from mfa-servicenow-mcp servicenow-mcp-skills codex

# OpenCode
uvx --from mfa-servicenow-mcp servicenow-mcp-skills opencode

# Gemini CLI
uvx --from mfa-servicenow-mcp servicenow-mcp-skills gemini
```

The installer downloads 24 skill files from this repository's `skills/` directory and places them in a project-local LLM directory. No authentication or configuration needed.

| Client | Install Path | Auto-Discovery |
|--------|-------------|----------------|
| Claude Code | `.claude/commands/servicenow/` | `/servicenow` slash commands appear on next startup |
| OpenAI Codex | `.codex/skills/servicenow/` | Skills loaded on next agent session |
| OpenCode | `.opencode/skills/servicenow/` | Skills loaded on next session |
| Gemini CLI | `.gemini/skills/servicenow/` | Skills activated on next session |

**How it works:** Each skill is a standalone Markdown file with YAML frontmatter (metadata) and pipeline instructions. The LLM client reads these files from the install path and exposes them as callable commands or skill triggers.

**Update:** Re-run the same install command — it replaces all existing skill files (clean install, no merge).

**Remove full setup:** `uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp remove claude-code`

**Remove skills only:** delete the skill install directory manually (for example `rm -rf .claude/commands/servicenow/`) if you intentionally want to keep the MCP config entry.

### Skill Categories

| Category | Skills | Purpose |
|----------|--------|---------|
| `analyze/` | 6 | Widget analysis, portal diagnosis, provider audit, dependency mapping, ESC audit, **local source audit** |
| `fix/` | 3 | Widget patching (staged gates), debugging, code review |
| `manage/` | 8 | Page layout, script includes, source export, **app source download**, changeset workflow, local sync, workflow management, **skill management** |
| `deploy/` | 2 | Change request lifecycle, incident triage |
| `explore/` | 5 | Health check, schema discovery, route tracing, flow trigger tracing, ESC catalog flow |

### Skill Metadata

Each skill includes metadata that helps LLMs optimize execution:

```yaml
context_cost: low|medium|high    # → high = delegate to sub-agent
safety_level: none|confirm|staged # → staged = mandatory snapshot/preview/apply
delegatable: true|false           # → can run in sub-agent to save context
triggers: ["위젯 분석", "analyze widget"]  # → LLM trigger matching
```

For the full skill reference, see [skills/SKILL.md](skills/SKILL.md).

### MCP Resources (Built-in Skill Guides)

Skills are also exposed as **MCP resources** directly from the server — no client-side installation required. Any MCP-compliant client can discover and read them on demand.

```
# List available skill guides
list_resources → skill://fix/widget-patching, skill://deploy/change-lifecycle, ...

# Read a specific guide
read_resource("skill://fix/widget-patching") → full pipeline with safety gates
```

Tools that have a matching skill guide show a `→ skill://...` hint in their description. The guide content is **pull-based** — zero token cost until the client actually reads it.

| Feature | Client-side Skills | MCP Resources |
|---------|-------------------|---------------|
| Availability | Requires install command | Built-in, any client |
| Token cost | Loaded by client | Pull on demand (0 until read) |
| Discovery | Slash commands / triggers | `list_resources` |
| Best for | Power users, slash commands | Universal guidance |

## Docker

API Key auth only (MFA browser auth requires GUI, not available in containers).

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

See [Client Setup Guide](docs/CLIENT_SETUP.md#docker-api-key-only) for local build options.

## Developer Setup

If you want to modify the source locally:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uv run playwright install chromium
```

### Running Tests

```bash
uv run pytest
```

### Linting & Formatting

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

### Building

```bash
uv build
```

> Windows: see [Windows Installation Guide](./docs/WINDOWS_INSTALL.md)

---

## Documentation

- [LLM Setup Guide](docs/llm-setup.md) — AI-guided one-line installation flow
- [Client Setup Guide](docs/CLIENT_SETUP.md) — Installer-first setup plus fallback client configs
- [Tool Inventory](docs/TOOL_INVENTORY.md) — Complete tool list by category and package
- [Windows Installation Guide](docs/WINDOWS_INSTALL.md)
- [Catalog Guide](docs/catalog.md) — Service catalog CRUD and optimization
- [Change Management](docs/change_management.md) — Change request lifecycle and approval
- [Workflow Management](docs/workflow_management.md) — Workflow (wf_workflow engine) and Flow Designer tools
- [Korean README](./README.ko.md)

---

## Related Projects and Acknowledgements

- This repository includes tools consolidated and refactored from earlier internal / legacy ServiceNow MCP implementations. The current surface is organized around bundled `manage_*` tools (see [tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py)).
- Some developer productivity workflows, especially server-side source lookup, were designed with ideas inspired by [SN Utils](https://github.com/arnoudkooi/SN-Utils). This project does not bundle or redistribute SN Utils code.
- This project is focused on MCP server use cases rather than browser-extension UX. If you want in-browser productivity features inside ServiceNow, SN Utils remains a strong companion tool.

---

## License

Apache License 2.0
