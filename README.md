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
# One command — MFA/SSO browser login, works on macOS/Linux/Windows
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
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
1. Install **uv** and **Playwright** (if needed)
2. Ask for your ServiceNow instance URL, auth type, and tool package
3. Generate the correct MCP config file for your client
4. Install **20 workflow skills** (if supported)

No manual config editing. No format differences to worry about. Works on macOS, Linux, and Windows.

After setup, **restart your AI client** (or reload MCP servers) to load the new configuration. A browser window will open on the first tool call for MFA login.

> For manual setup, see [Prerequisites](#prerequisites) and [Quick Start](#quick-start) below.

---

## Features

- **Browser authentication** for MFA/SSO environments (Okta, Entra ID, SAML, MFA)
- **4 auth modes**: Browser, Basic, OAuth, API Key
- **89 tools** across 5 role-based packages — from read-only to full CRUD
- Safe write confirmation with `confirm='approve'`
- Payload safety limits, per-field truncation, and total response budget (200K chars)
- Transient network error retry with backoff
- Tool packages for standard users, service desk, portal developers, and platform developers
- Developer productivity tools: activity tracking, uncommitted changes, dependency mapping, daily summary
- Full coverage of core ServiceNow artifact tables (see [Supported Tables](#supported-servicenow-tables))
- CI/CD with auto-tagging, PyPI publishing, and Docker multi-platform builds

### Supported ServiceNow Tables

| Artifact Type | Table Name | Source Search | Developer Tracking | Safety (Heavy Table) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | O | O | O |
| Business Rule | `sys_script` | O | O | O |
| Client Script | `sys_client_script` | O | O | O |
| UI Action | `sys_ui_action` | O | O | O |
| UI Script | `sys_ui_script` | O | O | O |
| UI Page | `sys_ui_page` | O | O | O |
| Scripted REST API | `sys_ws_operation` | O | O | O |
| Fix Script | `sys_script_fix` | O | O | O |
| Service Portal Widget | `sp_widget` | O | O | O |
| Angular Provider | `sp_angular_provider` | - | O | - |
| Update XML | `sys_update_xml` | O | - | - |

---

## Prerequisites

Install [uv](https://astral.sh/uv) — it handles Python, packages, and execution in one tool.

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

Restart your terminal after installation. That's it — no Python install, no pip, no venv needed.

> Chromium for MFA/SSO browser login is installed automatically on first use.
> Windows users: see [Windows Installation Guide](./docs/WINDOWS_INSTALL.md) for details.

---

## Quick Start

No clone needed. One command — works on macOS, Linux, and Windows:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

A browser window opens on the first tool call for Okta/Entra ID/SAML/MFA login. Chromium is auto-installed if missing. Session persists after login — no need to re-authenticate every time.

---

## MCP Client Configuration

Each project can connect to a different ServiceNow instance. Set the config in your **project directory** so each project has its own instance URL and credentials.

| Client | Config File | Format |
|--------|------------|--------|
| Claude Desktop | `claude_desktop_config.json` | JSON (`mcpServers`) |
| Claude Code | `.mcp.json` or `claude mcp add` | JSON / CLI |
| OpenCode | `opencode.json` | JSON (`mcp`, uses `environment`) |
| OpenAI Codex (CLI & App) | `~/.codex/config.toml` | TOML |
| AntiGravity | `mcp_config.json` | JSON (`mcpServers`) |
| Gemini / Vertex AI | project config | JSON (`mcp`) |
| Docker | — | Environment variables |

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
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Persistent browser profile path |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | `/api/now/table/sys_user?sysparm_limit=1&sysparm_fields=sys_id` | Session validation endpoint |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | Custom login page URL |

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

Set `MCP_TOOL_PACKAGE` to choose a specific tool set. Default: `standard`

All packages except `none` include the full set of read-only tools (55 tools). Higher packages add write capabilities for their domain.

| Package | Tools | Description |
| :--- | :---: | :--- |
| `standard` | 45 | **(Default)** Read-only safe mode. All query/analysis tools across every domain. |
| `service_desk` | 49 | standard + incident create/update/resolve/comment |
| `portal_developer` | 61 | standard + portal/widget updates, script include writes, changeset commit/publish |
| `platform_developer` | 69 | standard + workflow CRUD, UI policy, incident/change management writes |
| `full` | 89 | All write operations across every domain |

If a tool is not available in your current package, the server tells you which package includes it.

For the complete tool list by category, see [Tool Inventory](docs/TOOL_INVENTORY.md).

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

`uvx` automatically uses the latest cached version. In most cases, updates happen without any action.

To force the latest PyPI release immediately:

```bash
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

### pip upgrade

```bash
pip install --upgrade mfa-servicenow-mcp
```

### Pinning a specific version

If you need a specific version (e.g., for stability):

```bash
# uvx with pinned version
uvx --from "mfa-servicenow-mcp==1.5.0" servicenow-mcp --version

# uv tool with pinned version
uv tool install "mfa-servicenow-mcp==1.5.0"

# pip with pinned version
pip install "mfa-servicenow-mcp==1.5.0"
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

## Skills

Tools are raw API calls. Skills are what make your LLM actually useful — verified pipelines with safety gates, rollback, and context-aware sub-agent delegation. **MCP server + skills is the complete setup** for LLM-driven ServiceNow automation.

20 skills today, more coming with every release.

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

The installer downloads 20 skill files from this repository's `skills/` directory and places them in a project-local LLM directory. No authentication or configuration needed.

| Client | Install Path | Auto-Discovery |
|--------|-------------|----------------|
| Claude Code | `.claude/commands/servicenow/` | `/servicenow` slash commands appear on next startup |
| OpenAI Codex | `.codex/skills/servicenow/` | Skills loaded on next agent session |
| OpenCode | `.opencode/skills/servicenow/` | Skills loaded on next session |
| Gemini CLI | `.gemini/skills/servicenow/` | Skills activated on next session |

**How it works:** Each skill is a standalone Markdown file with YAML frontmatter (metadata) and pipeline instructions. The LLM client reads these files from the install path and exposes them as callable commands or skill triggers.

**Update:** Re-run the same install command — it replaces all existing skill files (clean install, no merge).

**Remove:** Delete the install directory (e.g., `rm -rf .claude/commands/servicenow/`).

### Skill Categories

| Category | Skills | Purpose |
|----------|--------|---------|
| `analyze/` | 6 | Widget analysis, portal diagnosis, provider audit, dependency mapping, code detection, ESC audit |
| `fix/` | 3 | Widget patching (staged gates), debugging, code review |
| `manage/` | 5 | Page layout, script includes, source export, changeset workflow, local sync |
| `deploy/` | 2 | Change request lifecycle, incident triage |
| `explore/` | 4 | Health check, schema discovery, route tracing, ESC catalog flow |

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

See [Client Setup Guide](docs/CLIENT_SETUP.md#docker-api-key-only) for SSE mode and local build options.

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

- [Client Setup Guide](docs/CLIENT_SETUP.md) — Copy-paste configs for every MCP client
- [Tool Inventory](docs/TOOL_INVENTORY.md) — Complete list of 89 tools by category and package
- [Windows Installation Guide](docs/WINDOWS_INSTALL.md)
- [Catalog Guide](docs/catalog.md) — Service catalog CRUD and optimization
- [Change Management](docs/change_management.md) — Change request lifecycle and approval
- [Workflow Management](docs/workflow_management.md) — Legacy workflow and Flow Designer tools
- [Korean README](./README.ko.md)

---

## Related Projects and Acknowledgements

- This repository includes tools consolidated and refactored from earlier internal / legacy ServiceNow MCP implementations. You can still see that lineage in modules such as [core_plus.py](./src/servicenow_mcp/tools/core_plus.py) and [tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py).
- Some developer productivity workflows, especially server-side source lookup, were designed with ideas inspired by [SN Utils](https://github.com/arnoudkooi/SN-Utils). This project does not bundle or redistribute SN Utils code.
- This project is focused on MCP server use cases rather than browser-extension UX. If you want in-browser productivity features inside ServiceNow, SN Utils remains a strong companion tool.

---

## License

Apache License 2.0
