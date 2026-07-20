# MCP Client Configuration

Detailed setup for each MCP client. All clients use the same MCP server — only the config format differs.

> **Start here:** `uvx` is the default install on every platform. If `uvx` won't run — Windows Smart App Control is the usual reason — fall back to `pip`. If PyPI itself is unreachable, use the release zip/exe section.

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

#### If uvx is blocked — `pip`

Windows [Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0) stops `uvx` from running at all: uvx unpacks an unsigned temporary executable on every run, and SAC blocks it. If uvx stopped working right after a Windows update, this is almost certainly why. Install with pip instead:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

A Python from the [python.org installer](https://www.python.org/downloads/) (signed, 3.10+) passes SAC as-is. Start the server with `python -m servicenow_mcp` — **not** the `servicenow-mcp` console script, which is an unsigned `.exe` shim pip generates and SAC blocks too.

> On macOS/Linux the one pip caveat is that Homebrew and distro Pythons refuse global installs under [PEP 668](https://peps.python.org/pep-0668/) (`externally-managed-environment`). Use the python.org installer, or just stay on uvx.

### 3. Add the server to your MCP client config

Add an entry to your client's config file (no installer command needed). **The `env` block is identical no matter how you installed** — only `command`/`args` follow the path you picked above:

| Install | `command` | `args` |
|---|---|---|
| uvx (default) | `uvx` | `["--with","playwright","--from","mfa-servicenow-mcp","servicenow-mcp"]` |
| pip (uvx blocked) | `python` | `["-m","servicenow_mcp"]` |
| release exe | absolute path to the executable | `[]` |

Every per-client example below shows the uvx form. On pip, swap those two keys and leave everything else untouched.

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

Use this when PyPI itself is blocked, so neither `uvx` nor `pip` can reach the package. The release zip is a single PyInstaller-built executable — **no installer script, no Python required, no system-cache pollution**. The executable auto-detects a `ms-playwright/` directory sitting next to itself.

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

Paste the MCP config snippet from the [Configuration Guide](#configuration-guide) below into your client's config file, setting `command` to the absolute path of your executable and `args` to `[]`. The `env` block is the same as the uvx setup — only `command`/`args` change. If you put Chromium somewhere other than next to the executable, add `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` to the `env` block.

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

# pip install: replace the first line with
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

If the server starts and a browser window opens for login, you're ready to configure your client below.

---

## Configuration Guide

> **`args` is for the package only** — instance URL, auth, credentials all go in `env` (or `environment`). This keeps args clean and makes it easy to swap instances per project.

> **Project-local recommended**: Use project-scoped config so each project can connect to a different ServiceNow instance.

Everything below varies only inside `env`. `command`/`args` stay exactly as they were in [step 3](#3-add-the-server-to-your-mcp-client-config), whichever install path you took.

### Profiles — start here

If you touch more than one ServiceNow instance, **configure profiles rather than running a server per instance.** Name each environment as an alias and pick the active one:

```json
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"prod\": { \"url\": \"https://acme-prod.service-now.com\", \"auth_type\": \"browser\" } }"
      }
```

That one block replaces `SERVICENOW_INSTANCE_URL`, and it is what makes the rest of this guide work:

- **Production is protected by omission.** An alias without `allow_writes` is read-only. `prod` above cannot be written to at all — a forgotten flag can never enable a production write.
- **Reach another instance without restarting.** Read tools take an `instance` argument: `sn_query(instance="prod", …)` while `dev` stays active.
- **Compare environments directly.** `compare_instances` diffs the same record across two aliases; `list_instances` reports every alias and its write flag.
- **One browser login.** The session is shared across aliases instead of one login per server process.
- **Writes to a non-active instance are guarded**, never silent — see [Multi-Instance Mode](#multi-instance-mode-comparison--guarded-single-call-writes) for the routing rules, the `confirm_instance` gate, and `${ENV}` secret references.

### Single instance

One instance only? Skip profiles entirely — two variables is the whole configuration:

```json
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
```

This form keeps working and is not deprecated; it is simply the degenerate case of the profile setup above.

### One connection or several?

Profiles put every instance behind **one** client connection, which is what almost everyone wants. If instead you need connections that are visually distinct in the client UI — a separate `snow-dev` and `snow-prd` entry — see [Naming multiple server entries](#naming-multiple-server-entries---server-name). That trades away `compare_instances`, the shared login, and the `allow_writes` gate, so choose it only for the UI separation.

---

## Streamable HTTP

The default transport is `stdio`. For remote MCP clients or a local HTTP bridge, start the server with Streamable HTTP:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
# pip install: python -m servicenow_mcp --transport http --http-host 127.0.0.1 --http-port 8000
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
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

## Naming multiple server entries (`--server-name`)

This is a different topology from the multi-instance mode above. Multi-instance = **one** connection that can reach several instances. This section = **several separate connections**, one process per instance, each pinned to its own instance — worth it only when you want dev/stg/prd visibly split apart in the client UI.

The catch: every entry advertises itself as `ServiceNow` by default, so the client disambiguates them by load order — `mcp_servicenow`, `mcp_servicenow2`, `mcp_servicenow3`. That numbering can shift between restarts, which makes it **untrustworthy for telling which connection is production.** Give each one a name with `--server-name`:

```json
{
  "mcpServers": {
    "snow-dev": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-dev"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme-dev.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    },
    "snow-prd": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-prd"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

Tool names are then pinned to `mcp_snow-dev_*` / `mcp_snow-prd_*`. `SERVICENOW_MCP_SERVER_NAME` does the same thing as an env var, and the flag wins if both are set. Unset, the name stays `ServiceNow`, so existing configs keep working.

**Prefer profiles when you can.** For moving between instances inside one connection, [Multi-Instance Mode](#multi-instance-mode-comparison--guarded-single-call-writes) is the recommended approach: only it gives you `compare_instances`, a single shared browser login, and the per-alias `allow_writes` gate. Separate processes get none of that — each one only knows its own instance, logs in on its own, and the tool package is the only thing standing between you and a production write.

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
