# ServiceNow MCP Server

[English](./README.md) | [한국어](./README.ko.md)

ServiceNow MCP server with browser-based authentication for MFA/SSO environments. Designed for direct use from MCP clients such as Claude Desktop, Claude Code, OpenCode, Gemini Code Assist, and similar local MCP hosts.

[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)

## Prerequisites

Before registering the server, ensure your environment is ready.

### 1. Install `uv` (Recommended)

This project is optimized for [uv](https://astral.sh/uv).

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### 2. Install Browser Binary (Required for `browser` auth)

If you plan to use `auth-type: browser` (MFA/SSO), you must install the Chromium browser binary on your machine:

```bash
# Using uvx to install the browser without global pip installation
uvx playwright install chromium
```

### 3. Windows Specifics

If you are on Windows, ensure your PowerShell execution policy allows script execution:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

For a step-by-step Windows setup guide, see [docs/WINDOWS_INSTALL.md](./docs/WINDOWS_INSTALL.md).

## Quick Start

Most users do not need to clone this repository. If you have [uv](https://astral.sh/uv), you can register the server directly in your MCP client.

### 1. Register in Your MCP Client

#### Claude Desktop

Add this to `claude_desktop_config.json`:

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

#### OpenCode / Gemini / Vertex AI

These hosts are easiest to manage with one of the following two execution styles.

##### Run with `uvx`

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

##### Run directly from a checked-out source tree

If you cloned this repository locally, point the MCP host at the project and run it with `uv run`:

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "--project",
        "/absolute/path/to/mfa-servicenow-mcp",
        "servicenow-mcp"
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

> `SERVICENOW_BROWSER_USERNAME` and `SERVICENOW_BROWSER_PASSWORD` are optional, but they help prefill the browser login form in MFA/SSO flows.

#### AntiGravity

AntiGravity Editor uses a Claude Desktop-style `mcpServers` config. You can edit this by clicking the "three dots" at the top of the agent panel -> **Manage MCP Servers** -> **View raw config**.

- **macOS / Linux:** `~/.gemini/antigravity/mcp_config.json`
- **Windows:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

##### Run with `uvx` (Recommended)

When using `auth-type: browser`, you **must** include `--with playwright` to ensure the browser dependencies are available in the ephemeral environment.

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

##### Run directly from a checked-out source tree

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/absolute/path/to/mfa-servicenow-mcp",
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

> **Note:** After saving the config, click **Refresh** in the AntiGravity MCP management view. If you are using browser auth, ensure you have run `playwright install chromium` on your machine.

#### OpenAI Codex

Add this to your `agents.toml` (usually `~/.codex/agents.toml` or `.codex/agents.toml` in your project root):

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

### 2. Run Directly From a Terminal

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

- The first run may install browser dependencies automatically.
- Browser auth may open a login window.
- Use `--browser-headless false` if you want an interactive MFA/SSO flow.

### 3. Install as a Local Command

```bash
uv tool install mfa-servicenow-mcp
servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

### 4. Update to Latest Version

#### uvx

`uvx` automatically fetches the latest version on every run. To force a cache refresh (e.g., right after a new release):

```bash
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

#### uv tool

```bash
uv tool upgrade mfa-servicenow-mcp
```

#### pip

```bash
pip install --upgrade mfa-servicenow-mcp
```

### 5. Browser Auth Setup

Browser authentication uses [Playwright](https://playwright.dev/) to drive your local browser. 

If you use `uvx` with the `--with playwright` flag, the package is handled automatically, but you still need the **browser binary** as mentioned in the [Prerequisites](#2-install-browser-binary-required-for-browser-auth).

```bash
# Step 1: Ensure browser binary is installed
uvx playwright install chromium

# Step 2: Run with playwright dependency injected
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

Playwright is only needed for browser auth. Basic, OAuth, and API Key auth work without it.

> Windows users can also use [docs/WINDOWS_INSTALL.md](./docs/WINDOWS_INSTALL.md).

## Features

- Browser authentication for MFA/SSO environments (Okta, Entra ID, SAML, MFA)
- Safe write confirmation with `confirm='approve'`
- Payload safety limits, per-field truncation, and total response budget (200K chars)
- Transient network error retry with backoff
- Tool packages for standard users, service desk, portal developers, and platform developers
- Developer productivity tools: activity tracking, uncommitted changes, dependency mapping, daily summary
- Performance: orjson serialization, parallel pagination, batch API, LRU cache, lazy tool discovery (see [Performance Optimizations](#performance-optimizations))
- Full coverage of core ServiceNow artifact tables (see below)

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

## Authentication

Choose the auth mode based on your ServiceNow environment.

### Browser Auth

Use this for Okta, Entra ID, SAML, MFA, or any interactive SSO flow.

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

Optional browser-related flags:
- `--browser-username`
- `--browser-password`
- `--browser-user-data-dir`
- `--browser-timeout`
- `--browser-probe-path`

Other flags:
- `--tool-package` — Tool package to load (env: `MCP_TOOL_PACKAGE`, default: `standard`)
- `--timeout` — HTTP request timeout in seconds (env: `SERVICENOW_TIMEOUT`, default: `30`)

Environment variables:

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_USERNAME=your.username
SERVICENOW_BROWSER_PASSWORD=your-password
MCP_TOOL_PACKAGE=standard
```

### Basic Auth

Use this for PDIs or instances without MFA.

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

With environment variables:

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=your.username
SERVICENOW_PASSWORD=your-password
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

Default header: `X-ServiceNow-API-Key`

## Tool Packages

Set `MCP_TOOL_PACKAGE` to choose a specific tool set. Default: `standard`

All packages except `none` include the full set of read-only tools (55 tools). Higher packages add write capabilities for their domain.

| Package | Tools | Description |
| :--- | :--- | :--- |
| `standard` | 55 | **(Default)** Read-only safe mode. All query/analysis tools across every domain. |
| `portal_developer` | 70 | standard + portal/widget updates, script include writes, changeset commit/publish |
| `platform_developer` | 78 | standard + workflow CRUD, UI policy, incident/change management writes |
| `service_desk` | 59 | standard + incident create/update/resolve/comment |
| `full` | 98 | All write operations across every domain |

If a tool is not available in your current package, the server tells you which package includes it.

For the complete tool list by category, see [Tool Inventory](docs/TOOL_INVENTORY.md).

## Safety Policy

All mutating tools are protected by explicit confirmation.

Rules:
1. Mutating tools with prefixes such as `create_`, `update_`, `delete_`, `remove_`, `add_`, `move_`, `activate_`, `deactivate_`, `commit_`, `publish_`, `submit_`, `approve_`, `reject_`, `resolve_`, `reorder_`, and `execute_` require confirmation.
2. You must pass `confirm='approve'`.
3. Without that parameter, the server rejects the request before execution.

This policy applies regardless of the selected tool package.

Portal investigation tools are also conservative by default.

- `search_portal_regex_matches` starts with widget-only scanning, linked expansion off, and small default limits.
- `trace_portal_route_targets` is the preferred follow-up when the model needs a compact table of Widget → Provider → route target evidence.
- `sn_query` should be treated as a generic fallback for ordinary records, not the first choice for portal source/routing analysis.
- `download_portal_sources` does not pull linked Script Includes or Angular Providers unless explicitly requested.
- Large portal scans are capped server-side and return warnings when the request is broader than the safe default.
- The intended workflow is: target one widget or a small widget list first, then opt in to broader expansion only when needed.

Example targeted portal search:

```json
{
  "regex": "click-event|another-query",
  "widget_ids": ["portal-widget-id"],
  "max_widgets": 1,
  "max_matches": 20
}
```

Example broader search with explicit opt-in:

```json
{
  "regex": "click-event|another-query",
  "widget_ids": ["portal-widget-id", "legacy-widget-id"],
  "include_linked_script_includes": true,
  "include_linked_angular_providers": true,
  "max_widgets": 2,
  "max_matches": 50
}
```

Pattern matching modes for LLM-friendly use:

- `match_mode: "auto"` (default): plain strings are treated literally, regex-looking patterns remain regex.
- `match_mode: "literal"`: always escape the pattern first; safest when the model just has a route or token.
- `match_mode: "regex"`: use only when you intentionally need regex operators.

Example LLM-friendly route trace:

```json
{
  "regex": "my-search-regex",
  "match_mode": "auto",
  "widget_ids": ["portal-widget-id"],
  "include_linked_angular_providers": true,
  "output_mode": "minimal"
}
```

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

## Developer Setup

If you want to modify the source locally:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uv run playwright install chromium
```

> Windows setup: [docs/WINDOWS_INSTALL.md](./docs/WINDOWS_INSTALL.md)

## Documentation

- [Windows Installation Guide](docs/WINDOWS_INSTALL.md)
- [Tool Inventory](docs/TOOL_INVENTORY.md)
- [Catalog Guide](docs/catalog.md)
- [Change Management Guide](docs/change_management.md)
- [Workflow and Developer Tools](docs/workflow_management.md)
- [Korean README](./README.ko.md)

## Related Projects and Acknowledgements

- This repository includes tools that were consolidated and refactored from earlier internal / legacy ServiceNow MCP implementations. You can still see that lineage in modules such as [core_plus.py](./src/servicenow_mcp/tools/core_plus.py) and [tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py).
- Some developer productivity workflows, especially server-side source lookup, were designed with ideas inspired by [SN Utils](https://github.com/arnoudkooi/SN-Utils). This project does not bundle or redistribute SN Utils code. It implements MCP-oriented server tools separately.
- This project is focused on MCP server use cases rather than browser-extension UX. If you want in-browser productivity features directly inside ServiceNow, SN Utils remains a strong companion tool.

## License

MIT License
