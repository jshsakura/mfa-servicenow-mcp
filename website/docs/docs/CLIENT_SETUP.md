# MCP Client Configuration

Detailed setup for each MCP client. All clients use the same MCP server — only the config format differs.

> **Recommended first:** use the `uvx` setup command below. If `uvx` is blocked by corporate security tooling, use the release zip/exe section.

---

## Before You Start

Use `uvx` by default. It keeps install and client config consistent across macOS, Linux, and Windows.

### 1. Install uv

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Fetch the server + install Chromium

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

The first command pre-fetches and verifies the server in the exact `--with playwright` env the client uses, so the first start is instant. The second downloads Chromium; `uvx` reuses a matching Chromium already in the standard cache.

### 3. Add the server to your MCP client config

Add an entry to your client's config file (no installer command needed):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Per-client file paths and formats (Codex TOML, etc.) are below; restart the client afterward.

### Local install (release zip/exe)

Use this when `uvx` or PyPI is blocked. The release zip is a single PyInstaller-built executable — **no installer script, no Python required, no system-cache pollution**. The executable auto-detects a `ms-playwright/` directory sitting next to itself.

**1. Download.** Executable from the [latest release](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest); the optional Chromium bundle (only if the network also blocks Playwright's Chromium download) from the long-lived [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) release.

| Platform | Required (latest release) | Add if Chromium download is blocked (chromium-bundle release) |
|----------|---------------------------|----------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. Lay it out** in any stable directory you control. **Extract both zips up front** — don't leave the `.zip` files alongside the executable. The Chromium zip's extracted folder just has to start with `ms-play` and contain a `chromium-*` subdirectory:

```
~/apps/servicenow-mcp/                                  (any directory you choose)
├── servicenow-mcp                                      ← from the platform zip (.exe on Windows)
└── ms-playwright-chromium-linux-x64-<ver>/             ← default extracted name works
    └── chromium-1185/
        └── …
```

(Rename to `ms-playwright/` if you want a tidier name — both work.) At startup the executable globs for any sibling `ms-play*` directory and, on finding a `chromium-*` subdirectory inside, points Playwright at it via `PLAYWRIGHT_BROWSERS_PATH` for the current process only. It does **not** touch the system Playwright cache, **not** modify any MCP client config, **not** write anywhere on disk.

**3. Verify, then wire your MCP client:**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

Paste the MCP config snippet from the [Configuration Guide](#configuration-guide) below into your client's config file, setting `command` to the absolute path of your executable. The `env` block is the same as the uvx setup — only `command` changes. If you put Chromium somewhere other than next to the executable, add `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` to the `env` block.

If you skipped the Chromium zip and Playwright's auto-download is blocked, pre-stage the directory on a machine with Python:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

The auto-detect picks it up with no extra config.

> Windows users: see [Windows Installation Guide](WINDOWS_INSTALL.md) for step-by-step details and proxy/antivirus notes.

### Quick Test

Verify the server starts before configuring your client:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

If the server starts and a browser window opens for login, you're ready to configure your client below.

---

## Configuration Guide

> **`args` is for the package only** — instance URL, auth, credentials all go in `env` (or `environment`). This keeps args clean and makes it easy to swap instances per project.

> **Project-local recommended**: Use project-scoped config so each project can connect to a different ServiceNow instance.

> **Deliberate write targeting**: ordinary tools route to the active instance (`SERVICENOW_ACTIVE_INSTANCE`). Writing to a *different* configured instance is possible but never silent — it requires naming the target and approving it on that same call (see [Multi-Instance Mode](#multi-instance-mode-comparison--guarded-single-call-writes)), so moving between dev/test/prod cannot cause an accidental production write.

---

## Streamable HTTP

The default transport is `stdio`. For remote MCP clients or a local HTTP bridge, start the server with Streamable HTTP:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`; `/health` returns a lightweight status response. Keep the default loopback host unless the server is behind trusted network controls.

---

## Multi-Instance Mode (comparison + guarded single-call writes)

Configure named instances (e.g. `dev` / `test` / `prod` aliases) with `SERVICENOW_INSTANCE_CONFIG` so one session can both compare across environments AND deploy to a chosen one — without switching the active instance or restarting the server. Route a single call with the `instance=<alias>` argument:

- **Read-only** calls route freely: `instance=test` reads `test` while `dev` stays active.
- **Writes** to a non-active instance are allowed but never silent. The one call must *name the target and approve it* — `instance=test confirm_instance=test confirm=approve` — and the target must have `allow_writes=true`. Only that one write is routed there; the active instance is restored immediately after. A target/confirm mismatch or a read-only target is refused with an explicit message, so a dev/test/prod mix-up cannot land on the wrong instance.
- **The write is verified on the target.** The result echoes `target_instance` and a `landed` verdict: the tool re-reads the pushed fields on the target and returns `WRITE_NOT_LANDED` if the content did not persist (e.g. an `sp_*` Service Portal field silently dropped). "Success" means the content is confirmed present on the intended instance — not merely that the request returned 200.
- `compare_instances` compares records across aliases (read-only); `list_instances` reports the configured aliases and each one's write flag.
- Keep `prod` at `allow_writes=false` unless you deliberately intend production writes — then a forgotten flag can never enable one.

> For promoting MANY records (especially Service Portal / scoped tables), prefer an Update Set — commit on the source, retrieve + commit on the target in the UI — over per-record cross-instance writes; it bypasses the per-table/SP ACLs that single Table-API writes hit.

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "auth_type": "browser", "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "auth_type": "browser", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "auth_type": "browser", "allow_writes": false }
}'
```

Per-instance credentials, in an MCP client `env` block (each alias can carry its own `username` / `password` / `auth_type` / `api_key`; `${ENV}` keeps secrets out of the JSON; the single-instance `SERVICENOW_INSTANCE_URL` form still works as a fallback):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mfa-servicenow-mcp@latest"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

Example comparison:

```json
{
  "source": "dev",
  "target": "test",
  "table": "sys_script_include",
  "key_field": "api_name",
  "fields": "api_name,name,active,script",
  "query": "sys_scope.scope=x_company_app"
}
```

For a single write against a non-active instance, use the guarded `instance=<alias> confirm_instance=<alias> confirm=approve` routing above. For promoting MANY records, prefer an Update Set over per-record cross-instance writes.

---

## Claude Desktop

| Scope | Path |
|-------|------|
| Global | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Global | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

> Claude Desktop does not support project-local config. Use Claude Code for per-project setup.

---

## Claude Code

| Scope | Path |
|-------|------|
| Global | `~/.claude.json` |
| Project | `.mcp.json` in project root |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

---

## Zed

| Scope | Path |
|-------|------|
| Global | `~/.config/zed/settings.json` |

Add via **Settings** > **MCP Servers** in Zed:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
# Login is shared across hosts automatically (scoped per instance + user under
# ~/.mfa_servicenow_mcp). Only set SERVICENOW_BROWSER_USER_DATA_DIR if a sandboxed
# host remapped HOME — see the README "Login sharing" note. Do NOT set it when you
# run multiple instances; it collapses them into one Chromium profile.
```

---

## OpenCode

| Scope | Path |
|-------|------|
| Project | `opencode.json` in project root |

> OpenCode uses `environment` (not `env`).

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

---

## AntiGravity

| Scope | Path |
|-------|------|
| Global | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| Global | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> Edit via agent panel: **...** > **Manage MCP Servers** > **View raw config**. Click **Refresh** after saving.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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
