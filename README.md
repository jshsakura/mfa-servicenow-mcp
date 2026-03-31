# ServiceNow MCP Server

[English](./README.md) | [한국어](./README.ko.md)

ServiceNow MCP server with browser-based authentication for MFA/SSO environments. Designed for direct use from MCP clients such as Claude Desktop, Claude Code, OpenCode, Gemini Code Assist, and similar local MCP hosts.

[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)

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
        "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ]
    }
  }
}
```

#### OpenCode / Gemini / Vertex AI

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "enabled": true
    }
  }
}
```

### 2. Run Directly From a Terminal

```bash
uvx mfa-servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
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

#### macOS / Linux

```bash
# uvx (always runs the latest from PyPI — no manual update needed)
uvx mfa-servicenow-mcp --version

# uv tool
uv tool upgrade mfa-servicenow-mcp

# pip
pip install --upgrade mfa-servicenow-mcp
```

#### Windows

```powershell
# uv tool
uv tool upgrade mfa-servicenow-mcp

# pip
pip install --upgrade mfa-servicenow-mcp
```

### 5. Browser Auth Setup

Browser authentication uses [Playwright](https://playwright.dev/) to drive your local browser for MFA/SSO login. Playwright is an **optional** dependency — install it separately:

```bash
# 1. Install Playwright
pip install playwright
# or
uv pip install playwright

# 2. Install the browser binary (uses your local Chromium)
playwright install chromium
```

With `uvx`:

```bash
uvx --with playwright mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

Or install as a bundle:

```bash
pip install "mfa-servicenow-mcp[browser]"
playwright install chromium
```

Playwright is only needed for browser auth. Basic, OAuth, and API Key auth work without it.

> Windows users can also use [WINDOWS_INSTALL.md](./WINDOWS_INSTALL.md).

## Features

- Browser authentication for MFA/SSO environments (Okta, Entra ID, SAML, MFA)
- Safe write confirmation with `confirm='approve'`
- Payload safety limits, per-field truncation, and total response budget (200K chars)
- Transient network error retry with backoff
- Tool packages for standard users, service desk, portal developers, and platform developers
- Developer productivity tools: activity tracking, uncommitted changes, dependency mapping, daily summary
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
uvx mfa-servicenow-mcp \
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

Environment variables:

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
```

### Basic Auth

Use this for PDIs or instances without MFA.

```bash
uvx mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth

Current CLI support expects OAuth password grant inputs.

```bash
uvx mfa-servicenow-mcp \
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
uvx mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

Default header: `X-ServiceNow-API-Key`

## Tool Packages

Set `MCP_TOOL_PACKAGE` to choose a smaller tool set. Default: `standard`

| Package | Intended Use | Highlights |
| :--- | :--- | :--- |
| `standard` | General users | Incidents, catalog, knowledge, core queries |
| `portal_developer` | Portal developers | Portal code, script includes, source search (all 9 artifact types), developer activity tracking, dependency mapping, daily summary, safe logs, workflow read, update set commit/publish |
| `platform_developer` | Platform developers | Everything in portal_developer + delete script include, full workflow CRUD, UI policy |
| `service_desk` | Operations | Incident handling, comments, user lookup, article lookup |
| `full` | Admin / unrestricted | Broad access across all implemented tool domains |

### Developer Productivity Tools

These tools are available in `portal_developer`, `platform_developer`, and `full` packages:

| Tool | Description |
| :--- | :--- |
| `get_developer_changes` | List recent changes by a developer across all artifact tables. Supports `count_only` for cost preview. |
| `get_uncommitted_changes` | Find items in uncommitted (in-progress) update sets, grouped by update set. |
| `get_provider_dependency_map` | Map Widget → Angular Provider → Script Include dependency chains. |
| `trace_portal_route_targets` | Return LLM-friendly widget/provider route traces with minimal evidence rows instead of raw script bodies. |
| `get_developer_daily_summary` | Generate a daily work report in Jira markdown, plain text, or structured JSON. |

## Safety Policy

All mutating tools are protected by explicit confirmation.

Rules:
1. Tools such as `create_`, `update_`, `delete_`, `execute_`, `add_`, `commit_`, and `publish_` require confirmation.
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
  "regex": "btnClickLoadData|myQuery",
  "widget_ids": ["jobWFMngt2Wd"],
  "max_widgets": 1,
  "max_matches": 20
}
```

Example broader search with explicit opt-in:

```json
{
  "regex": "btnClickLoadData|myQuery",
  "widget_ids": ["jobWFMngt2Wd", "jobWFMngtLegacyWd"],
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
  "regex": "hopesinitplanbudgetmanhour",
  "match_mode": "auto",
  "widget_ids": ["jobWFMngt2Wd"],
  "include_linked_angular_providers": true,
  "output_mode": "minimal"
}
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

> Windows-specific setup: [WINDOWS_INSTALL.md](./WINDOWS_INSTALL.md)

## Documentation

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
