# MFA ServiceNow MCP

🌐 [English](./README.md) | 🇰🇷 [한국어](./README.ko.md) | 🚀 [**GitHub Pages**](https://jshsakura.github.io/mfa-servicenow-mcp/)

MFA-first ServiceNow MCP server. Authenticates via real browser (Playwright) so Okta, Entra ID, SAML, and any MFA/SSO login just works. Also supports API Key for headless/Docker environments.

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-live-blue?logo=github)](https://jshsakura.github.io/mfa-servicenow-mcp/)

---

## Table of Contents

- [Features](#features)
- [Setup](#setup)
- [Prerequisites](#prerequisites)
- [MCP Client Configuration](#mcp-client-configuration)
- [Authentication](#authentication)
- [Tool Packages](#tool-packages)
- [CLI Reference](#cli-reference)
- [Keeping Up to Date](#keeping-up-to-date)
- [Safety Policy](#safety-policy)
- [Performance Optimizations](#performance-optimizations)
- [Local Source Audit](#local-source-audit)
- [Skills](#skills)
- [Docker](#docker)
- [Developer Setup](#developer-setup)
- [Documentation](#documentation)
- [Related Projects](#related-projects-and-acknowledgements)
- [License](#license)

---

## Setup

Pick one path. Both end at the same configured MCP server; you don't need both.

### Path A — Let an AI do it

> **One line. Any AI coding assistant. Everything configured automatically.**

Paste this into Claude Code, Cursor, Codex, OpenCode, Windsurf, VS Code Copilot, Gemini CLI, or Zed:

```
Install and configure mfa-servicenow-mcp by following the instructions here:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

The AI installs `uv` + Chromium, asks for your instance URL / auth type / tool package, writes the right MCP config for your client, and installs the workflow skills.

### Path B — One-line command (manual)

If you'd rather run the installer yourself:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

Replace `opencode` with your client (`claude-code`, `codex`, `cursor`, `gemini`, etc.). The installer merges the entry into your existing config, installs Chromium (`--skip-chromium` to opt out), and pulls the skills when supported. Add `--scope global` for a global install (default is project-local).

### After either path

Restart the MCP client so it loads the new config. The first browser-authenticated tool call opens a window for Okta/Entra ID/SAML/MFA login. Sessions persist — no re-login every time.

> Need to write the client config by hand? See [MCP Client Configuration](#mcp-client-configuration). Need to launch the server directly? See [CLI Reference](#cli-reference).

---

## Features

- **Browser authentication** for MFA/SSO environments (Okta, Entra ID, SAML, MFA)
- **4 auth modes**: Browser, Basic, OAuth, API Key
- **72 registered tools** with **6 active package profiles** plus disabled `none` — from minimal read-only to broad bundled CRUD
- **16 workflow skills** with safety gates, sub-agent delegation, and verified pipelines
- **Streamable HTTP transport** — keep stdio as the default, or expose `/mcp` for HTTP-capable clients and bridges
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
| Client Script | `sys_script_client` | ✅ | ✅ | 🛡️ |
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

## Install

### Default: uvx

Use this unless your company security tools block `uvx` or package downloads.

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx --with playwright playwright install chromium
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --with playwright playwright install chromium
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser"
```

`uvx` does not use a locally installed Playwright Python package, but it does use the standard Playwright browser cache when the matching Chromium revision is already installed. If Chromium is missing, run the Playwright install command above.

### Release zip/exe (local install)

Use this path when `uvx` or PyPI is blocked by corporate security. The release zip ships a **PyInstaller-built single-file executable** — no Python required, no installer script, no system-cache pollution. The executable auto-detects a `ms-playwright/` directory sitting next to itself, so the entire install is "unzip and point your MCP client at it".

#### 1. Download

From <https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest>:

| Platform | Required | Add this too if Chromium download is also blocked |
|----------|----------|---------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64-<version>.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>-<version>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64-<version>.zip` |

#### 2. Build this folder layout

Pick any directory you control (`~/apps/servicenow-mcp/`, `D:\Tools\servicenow-mcp\`, etc. — just keep it stable). **Extract both zips up front** — don't leave the `.zip` files lying next to the executable. The Chromium zip's extracted directory just has to start with `ms-play` and contain a `chromium-*` subdirectory; whatever name your unzip tool produces is fine:

```
~/apps/servicenow-mcp/                                  (any directory you choose)
├── servicenow-mcp                                      ← from the platform zip (.exe on Windows)
└── ms-playwright-chromium-linux-x64-1.13.7/            ← default extracted name works
    └── chromium-1185/                                  (one of these is enough)
        └── …
```

Or, if you'd rather have a clean name, extract into a folder simply called `ms-playwright/`. Both work — the executable globs for any sibling `ms-play*` directory at startup and, on finding a `chromium-*` subdirectory inside, sets `PLAYWRIGHT_BROWSERS_PATH` to that path **for the current process only**. It does not write anywhere on disk, does not edit your MCP client config, and does not touch the system-wide Playwright cache (`~/.cache/ms-playwright`, `%LOCALAPPDATA%\ms-playwright`, …). If Chromium isn't bundled, Playwright falls back to its own discovery — set `PLAYWRIGHT_BROWSERS_PATH` in your MCP env yourself or run `playwright install chromium` somewhere reachable.

#### 3. Sanity-check the binary

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

If the version prints, you're done with the binary half — every remaining step is just config.

#### 4. Wire it up in your MCP client (copy-paste)

Paste the snippet for your client into the file it reads. The `env` block is identical to the uvx setup; only `command` changes to the absolute path of your executable.

**Claude Code** — `.mcp.json` (project root) / `~/.claude.json` (global):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "/home/you/apps/servicenow-mcp/servicenow-mcp",
      "args": [],
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

On Windows replace `"command"` with `"C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe"`.

**Codex** — `.codex/config.toml` (project) / `~/.codex/config.toml` (global):

```toml
[mcp_servers.servicenow]
command = "/home/you/apps/servicenow-mcp/servicenow-mcp"
args = []
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
```

**OpenCode** — `opencode.json` (project root):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["/home/you/apps/servicenow-mcp/servicenow-mcp"],
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

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` are optional (MFA login pre-fill). If you put Chromium *somewhere else* than next to the executable, add `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` to the env block — the auto-detect only kicks in for the sibling-directory layout above. Configs for other clients (Cursor, VS Code Copilot, Gemini, Zed, …) live in the [Client Setup Guide](docs/CLIENT_SETUP.md).

#### Chromium fallback (optional)

If you skipped the Chromium zip and Playwright's auto-download is blocked, pre-stage the directory on any machine with Python:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

The result is the same `ms-playwright/chromium-*/…` layout the bundled zip produces, so the auto-detect picks it up with no extra config.

> Windows users: see the [Windows Installation Guide](./docs/WINDOWS_INSTALL.md) for PATH and antivirus notes.

---

## MCP Client Configuration

> Recommended: use [Setup](#setup) above. Use the copy-paste configs below when you need to inspect, repair, or hand-manage a client config file.

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

The [Setup](#setup) command uses browser auth by default. Optional flags:

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | Prefill login form username |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | Prefill login form password |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | Run browser without GUI |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | Login timeout in seconds |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | Session TTL in minutes |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Override the Chromium profile path. Rarely needed — see the sandbox note below before setting it. |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | user-specific `sys_user` lookup when a username is known, otherwise `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | Session validation endpoint (avoids 401 on non-admin sessions) |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | Custom login page URL |

#### Login sharing across hosts and instances — how it actually works

The server caches two things under `~/.mfa_servicenow_mcp/`: the Playwright profile (Chromium SSO cookies) and a session JSON (parsed cookies reused on the next start). Both are **scoped per instance + username** — files are named `profile_<host>_<user>` and `session_<host>_<user>.json`.

That scoping does two things for you automatically, with **no configuration**:

- **Multiple hosts share one login.** Claude Code and Codex on the same machine both resolve `~/.mfa_servicenow_mcp/`, so whichever logs in first writes the session and the other reuses it — no second MFA prompt.
- **Different instances / different credentials stay isolated.** Each instance+user gets its own profile and session file, so dev and test (or two accounts) never collide. For multiple instances, configure them in `SERVICENOW_INSTANCE_CONFIG` (JSON) — each alias gets its own scoped cache; you do **not** manage this with a profile path.

**Do not set `SERVICENOW_BROWSER_USER_DATA_DIR` to "share" logins.** It overrides the profile path verbatim — the per-instance scoping is bypassed, so every instance you run is forced into one Chromium profile and their cookies collide. The only legitimate use is a narrow one: a **sandboxed** host (e.g. Claude Desktop on macOS) that remaps `HOME` to a container path, so its `~/.mfa_servicenow_mcp/` no longer matches the terminal's. In that single-instance case, point the sandboxed host at the real home path:

```bash
# Only when a sandbox remapped HOME, and only for a single-instance host
export SERVICENOW_BROWSER_USER_DATA_DIR="/Users/you/.mfa_servicenow_mcp/profile_acme"
```

If you run more than one instance, leave this unset and let the per-instance scoping do its job.

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
> **Any package above `standard` grants write access and is an advanced option.** `service_desk`, `portal_developer`, `platform_developer`, and `full` all let an AI agent create, update, and delete records — `full` does so across every domain at once. Most users should stay on the read-only default `standard` and only opt up to the narrowest write package their task actually requires.

Read-only (safe defaults):

| Package | Tools | Description |
| :--- | :---: | :--- |
| `none` | 0 | Disabled profile for intentionally turning tools off |
| `core` | 12 | Minimal read-only essentials for health, schema, discovery, and key artifact lookups |
| `standard` | 30 | **(Default)** Read-only across incidents, changes, portal, logs, and source analysis |

⚠️ Write-capable (advanced — grants create/update/delete):

| Package | Tools | Description |
| :--- | :---: | :--- |
| `service_desk` | 32 | ⚠️ standard + incident and change operational writes |
| `portal_developer` | 42 | ⚠️ standard + portal, changeset, script include, and local-sync delivery writes |
| `platform_developer` | 46 | ⚠️ standard + workflow, Flow Designer, UI policy, incident/change, and script writes |
| `full` | 61 | ⚠️ **Most advanced** — all write tools across all domains at once |

Each server process is intentionally bound to one active ServiceNow instance for ordinary tools. For safety, there is no per-request write routing across instances.

### Read-Only Data Comparison Mode

When you need to compare development and test data, you can opt into named instances with `SERVICENOW_INSTANCE_CONFIG`. `SERVICENOW_ACTIVE_INSTANCE` is still required.

Two things are global, one is per-instance:

- **Tool surface is global** — set once with `MCP_TOOL_PACKAGE`. Only one instance is ever active per server process, so there is no per-instance tool package.
- **Write permission is per-instance** — each alias carries `allow_writes`. It is enforced at call time against the active instance: a write tool can be loaded but still refused if the active instance has `allow_writes: false`. `role: "prod"` defaults `allow_writes` to false automatically.
- **Credentials are per-instance with global fallback** — put `username` / `password` / `api_key` (and `auth_type`) on an alias to override; omit them and the alias inherits the global `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` / etc. So if every instance shares one login, set it once globally and leave the alias entries credential-free.

Other rules:

- Write-capable tools always use the active instance and do not accept an instance selector.
- **Read tools accept an `instance` argument** to run a single read against a non-active instance — e.g. `sn_query(instance="test", table="incident", ...)` or `sn_health(instance="test")` while `dev` stays active. Every read tool in your package exposes it (enum of configured aliases); write tools don't. This is how you peek at another instance's data without restarting.
- `list_instances` reports configured aliases plus the active one. `compare_instances` performs read-only table comparisons across aliases.
- Switching the *active* (write) instance requires restarting the MCP client — it is read once at server startup, not refreshed live.

Example — shared global login, per-instance write gating:

```bash
export MCP_TOOL_PACKAGE=standard
export SERVICENOW_USERNAME=svc_account
export SERVICENOW_PASSWORD='...'
export SERVICENOW_ACTIVE_INSTANCE=dev
export SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://dev.service-now.com",  "role": "development", "allow_writes": true },
  "test": { "url": "https://test.service-now.com", "role": "test",        "allow_writes": false }
}'
```

To give an instance its own login instead, add the fields to that alias (a `${ENV}` reference is resolved, so you can keep secrets out of the JSON):

```json
"prod": { "url": "https://prod.service-now.com", "role": "prod", "username": "prod_user", "password": "${SERVICENOW_PROD_PASSWORD}" }
```

Use `compare_instances` for dev/test drift checks. Use separate project/client configs for actual work against a different instance.

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
| `--transport` | `SERVICENOW_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` or `http` |
| `--http-host` | `SERVICENOW_MCP_HTTP_HOST` | `127.0.0.1` | Host for `--transport http` |
| `--http-port` | `SERVICENOW_MCP_HTTP_PORT` | `8000` | Port for `--transport http` |
| `--http-path` | `SERVICENOW_MCP_HTTP_PATH` | `/mcp` | Streamable HTTP endpoint path |
| `--http-allowed-hosts` | `SERVICENOW_MCP_HTTP_ALLOWED_HOSTS` | loopback hosts | Comma-separated Host allowlist for DNS rebinding protection |
| `--http-disable-dns-rebinding-protection` | `SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | Disable DNS rebinding protection behind trusted network controls |
| `--http-json-response` | `SERVICENOW_MCP_HTTP_JSON_RESPONSE` | `false` | Return JSON responses instead of SSE streams |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP request timeout (seconds) |
| `--debug` | `SERVICENOW_DEBUG` | `false` | Enable debug logging |

HTTP transport example:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`; `/health` returns a lightweight health response.

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

**Recommended for stable setups.** uvx happily downloads the latest Playwright when it pulls the MCP server, and a new Playwright release ships a new Chromium build. When that happens the *first* tool call has to fetch ~150 MB of browser binaries — which on a slow link can blow past the MCP host's handshake timeout and surface as:

```text
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

Pin **both** `playwright` and `mfa-servicenow-mcp` so the install is deterministic. Then `uvx --with playwright playwright install chromium` is a one-time op until you bump the pin yourself.

```bash
# One-off run
uvx --with "playwright==1.58.0" --from "mfa-servicenow-mcp==1.13.16" servicenow-mcp --version
```

#### MCP client configs (project-local examples)

Put project-local config in the repository root. This lets each dev/test/prod project point at its own ServiceNow instance and tool profile.

Choose one execution style:

- `uvx`: default recommended path. Runs from PyPI and uses the `uvx` cache.
- Local release zip/exe: use when endpoint security blocks `uvx` or package execution. Extract `servicenow-mcp-<platform>-<version>.zip`, run the included installer, then point MCP `command` at the installed executable.

##### `uvx`

**Claude Code** (`.mcp.json` in repo root):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright==1.58.0",
        "--from", "mfa-servicenow-mcp==1.13.16",
        "servicenow-mcp"
      ],
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

**Codex** (`.codex/config.toml` in repo root — project-local; `~/.codex/config.toml` is the global form):

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright==1.58.0",
  "--from", "mfa-servicenow-mcp==1.13.16",
  "servicenow-mcp",
]
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
```

**OpenCode** (`opencode.json` in repo root):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx",
        "--with", "playwright==1.58.0",
        "--from", "mfa-servicenow-mcp==1.13.16",
        "servicenow-mcp"
      ],
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

##### Local release zip/exe

See [Step 5 of the local install section](#step-5--wire-it-up-in-your-mcp-client-copy-paste) above for per-client copy-paste snippets. Two key differences from the uvx config: `command` points at the local executable, and the env block includes `PLAYWRIGHT_BROWSERS_PATH` pointing at the Chromium directory next to the executable — that's how the server stays out of the system standard Playwright cache. The installer prints both values when it finishes, so copy those directly.

#### Upgrading

When you bump `mfa-servicenow-mcp`, decide whether to bump `playwright` at the same time:

```bash
# 1. Refresh Chromium for the new Playwright (if you bumped playwright)
uvx --with "playwright==<new>" playwright install chromium

# 2. Update both pins in your client config to the new versions
# 3. Restart your MCP client
```

> **Why we no longer auto-install Chromium inside the MCP server:** that download used to run during the first tool call. On a slow link the subprocess outlived the host's handshake deadline and the client reported "connection closed". v1.13.1 changed this — the MCP server now only *warns* if Chromium is missing, and the `servicenow-mcp setup <client>` command handles the install at setup time (out-of-band, no handshake timer).

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

**Remove skills only:** delete the skill install directory manually (for example `rm -rf .claude/commands/servicenow/`).

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
uvx --with playwright playwright install chromium
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
