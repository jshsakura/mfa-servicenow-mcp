# ServiceNow MCP Server

[English](./README.md) | [한국어](./README.ko.md)

**MFA-first** ServiceNow MCP server. Built for enterprises where MFA/SSO is mandatory — authenticates via real browser (Playwright) so Okta, Entra ID, SAML, and any interactive login just works. Also supports API Key for headless/Docker environments. Designed for Claude Desktop, Claude Code, OpenCode, Gemini Code Assist, AntiGravity, and OpenAI Codex.

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

```bash
# Install and run (one-liner)
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [MCP Client Configuration](#mcp-client-configuration)
- [Authentication](#authentication)
- [Tool Packages](#tool-packages)
- [CLI Reference](#cli-reference)
- [Keeping Up to Date (PyPI)](#keeping-up-to-date-pypi)
- [Safety Policy](#safety-policy)
- [Docker](#docker)
- [Developer Setup](#developer-setup)
- [Documentation](#documentation)
- [Related Projects](#related-projects-and-acknowledgements)
- [License](#license)

---

## Features

- **Browser authentication** for MFA/SSO environments (Okta, Entra ID, SAML, MFA)
- **4 auth modes**: Browser, Basic, OAuth, API Key
- **86 tools** across 5 role-based packages — from read-only to full CRUD
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

Before registering the server, ensure your environment is ready.

### 1. Install `uv` (Required)

This project is optimized for [uv](https://astral.sh/uv), the fast Python package manager.

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

After installation, restart your terminal and verify:

```bash
uv --version
```

### 2. Install Browser Binary (Required for `browser` auth)

If you plan to use `auth-type: browser` (MFA/SSO), you must install the Chromium browser binary:

```bash
uvx playwright install chromium
```

> This only needs to be done once. The binary is shared across all uvx runs.

### 3. Windows Specifics

If you are on Windows, ensure your PowerShell execution policy allows script execution:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

For a step-by-step Windows setup guide, see [docs/WINDOWS_INSTALL.md](./docs/WINDOWS_INSTALL.md).

---

## Quick Start

Most users do **not** need to clone this repository. If you have `uv`, you can register the server directly in your MCP client.

### Run from terminal (one-liner)

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

### Install as a persistent local command

```bash
uv tool install mfa-servicenow-mcp
servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

---

## MCP Client Configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

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

```bash
claude mcp add servicenow -- \
  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

Or add to `.mcp.json` in your project root:

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

### OpenCode / Gemini / Vertex AI

#### Run with `uvx`

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
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
    }
  }
}
```

#### Run from a checked-out source tree

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uv", "run", "--project", "/absolute/path/to/mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
    }
  }
}
```

> `SERVICENOW_BROWSER_USERNAME` and `SERVICENOW_BROWSER_PASSWORD` are optional but help prefill the browser login form in MFA/SSO flows.

### AntiGravity

AntiGravity Editor uses a Claude Desktop-style `mcpServers` config. Edit via the agent panel: **three dots (...)** -> **Manage MCP Servers** -> **View raw config**.

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
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> After saving, click **Refresh** in the AntiGravity MCP management view.

### OpenAI Codex

Add to `codex.json` or pass via CLI:

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
        "--browser-headless", "false",
        "--tool-package", "standard"
      ]
    }
  }
}
```

---

## Authentication

Choose the auth mode based on your ServiceNow environment.

### Browser Auth (MFA/SSO)

Use this for Okta, Entra ID, SAML, MFA, or any interactive SSO flow.

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

Optional browser-related flags:

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_BROWSER_USERNAME` | — | Prefill login form username |
| `--browser-password` | `SERVICENOW_BROWSER_PASSWORD` | — | Prefill login form password |
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
| `standard` | 48 | **(Default)** Read-only safe mode. All query/analysis tools across every domain. |
| `service_desk` | 52 | standard + incident create/update/resolve/comment |
| `portal_developer` | 58 | standard + portal/widget updates, script include writes, changeset commit/publish |
| `platform_developer` | 71 | standard + workflow CRUD, UI policy, incident/change management writes |
| `full` | 86 | All write operations across every domain |

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

## Keeping Up to Date (PyPI)

This project is published to [PyPI](https://pypi.org/project/mfa-servicenow-mcp/) and follows semantic versioning. New releases are automatically published via GitHub Actions when a version tag (`v*`) is pushed.

### How `uvx` handles versions

`uvx` **caches** the installed package. It does **not** automatically pull the latest version on every run. To ensure you're on the latest:

```bash
# Check current version
uvx --from mfa-servicenow-mcp servicenow-mcp --version

# Force refresh to latest PyPI release
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

### `uv tool` upgrade

If you installed via `uv tool install`:

```bash
uv tool upgrade mfa-servicenow-mcp
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

## Docker

Docker images are published to `ghcr.io/jshsakura/mfa-servicenow-mcp` on every main branch push.

> **Note:** Browser auth (MFA/SSO) requires a GUI browser and does not work inside containers. ServiceNow instances with MFA enabled should use `api_key` auth for Docker deployments.

### Quick Run (API Key)

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

### SSE Mode (HTTP Server)

```bash
docker run -p 8080:8080 \
  -e MCP_MODE=sse \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

### Build Locally

```bash
docker build --target runtime -t servicenow-mcp .
```

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

> For Windows-specific setup, see [WINDOWS_INSTALL.md](./WINDOWS_INSTALL.md).

---

## Documentation

- [Tool Inventory](docs/TOOL_INVENTORY.md) — Complete tool reference by category
- [Catalog Guide](docs/catalog.md)
- [Catalog Variables](docs/catalog_variables.md)
- [Change Management Guide](docs/change_management.md)
- [Changeset Management](docs/changeset_management.md)
- [Incident Management](docs/incident_management.md)
- [User Management](docs/user_management.md)
- [Workflow and Developer Tools](docs/workflow_management.md)
- [Korean README](./README.ko.md)
- [Windows Install Guide](./WINDOWS_INSTALL.md)

---

## Related Projects and Acknowledgements

- This repository includes tools consolidated and refactored from earlier internal / legacy ServiceNow MCP implementations. You can still see that lineage in modules such as [core_plus.py](./src/servicenow_mcp/tools/core_plus.py) and [tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py).
- Some developer productivity workflows, especially server-side source lookup, were designed with ideas inspired by [SN Utils](https://github.com/arnoudkooi/SN-Utils). This project does not bundle or redistribute SN Utils code.
- This project is focused on MCP server use cases rather than browser-extension UX. If you want in-browser productivity features inside ServiceNow, SN Utils remains a strong companion tool.

---

## License

MIT License
