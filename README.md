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

### 4. Browser Auth Setup

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

- Browser authentication for MFA/SSO environments
- Safe write confirmation with `confirm='approve'`
- Payload safety limits and truncation for large records
- Tool packages for standard users, service desk, portal developers, and platform developers
- Developer-focused tools for logs, source lookup, workflow inspection, and update set operations

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
| `portal_developer` | Portal developers | Portal code, script includes, safe logs, source lookup, workflow read, update set commit/publish |
| `platform_developer` | Platform developers | Script includes, safe logs, source lookup, workflows, UI policy, change set management |
| `service_desk` | Operations | Incident handling, comments, user lookup, article lookup |
| `full` | Admin / unrestricted | Broad access across all implemented tool domains |

## Safety Policy

All mutating tools are protected by explicit confirmation.

Rules:
1. Tools such as `create_`, `update_`, `delete_`, `execute_`, `add_`, `commit_`, and `publish_` require confirmation.
2. You must pass `confirm='approve'`.
3. Without that parameter, the server rejects the request before execution.

This policy applies regardless of the selected tool package.

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
