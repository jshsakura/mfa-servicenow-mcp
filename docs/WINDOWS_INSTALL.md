# Windows Installation Guide

`uvx` is the default on Windows, same as everywhere else. There is one Windows-specific thing that can push you off it:

- **Smart App Control blocks `uvx`** → switch to **pip** (Step 1b). This is by far the most common Windows breakage, and it usually shows up abruptly right after a Windows update.

If **PyPI itself is unreachable** — a corporate network that blocks the package index — neither path can fetch anything. Ask IT to allowlist `pypi.org` and `files.pythonhosted.org`, or to mirror the package on an internal index you can point at with `pip install --index-url`.

---

## Step 1: Default uvx install

Open PowerShell without admin privileges:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

That installs `uv`, fetches+verifies the server, and downloads Chromium. Then add the server to your MCP client config file (no installer command):

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

`uvx` reuses a matching Chromium already in the standard Playwright cache; if Chromium is missing, run the install command above first.

**Updating:** `uvx` caches the version it downloaded and keeps reusing it, so a new release has to be pulled in explicitly:

```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

---

## Step 1b: Smart App Control blocks uvx — install with pip

### What you'll see

`uvx` stops working with no useful error. The MCP client reports the server failed to start, or PowerShell reports the program was blocked by your administrator / by system policy. Nothing in your config changed. Very often this starts **right after a Windows update**, which makes it look like the server broke rather than the launcher.

### Why it happens

[Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0) (SAC) is a Windows 11 feature that only lets **signed or otherwise known-good** executables run. `uvx` doesn't run a permanently installed program — on every single run it unpacks a **fresh, unsigned temporary executable** and launches it. That is precisely the shape SAC exists to stop, so SAC blocks it every time. No amount of retrying or reinstalling `uv` changes it: the file is new and unsigned on each run by design.

SAC ships in evaluation mode on new Windows 11 machines and can flip itself to **on** later, on its own. That's why this appears out of nowhere on a machine where `uvx` had been working for months.

To check: **Windows Security → App & browser control → Smart App Control settings**.

> **Do not turn Smart App Control off to fix this.** Turning it off is a **one-way switch** — once disabled, Windows will not let you turn it back on again. Getting it back requires **reinstalling Windows**. It is not worth trading a permanent OS security downgrade for a package launcher. Use pip instead; it solves the problem completely and leaves SAC on.

### The pip path

pip installs the server as ordinary Python files run by a **signed** Python interpreter, so SAC has nothing to object to.

Install Python **3.10 or newer** from the [python.org installer](https://www.python.org/downloads/) — that build is signed and passes SAC as-is. (Python from the Microsoft Store works too.) Tick **"Add python.exe to PATH"** during install. Then:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**Updating:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Install Chromium up front, as shown. Deferring it to the first tool call means a ~150 MB download racing your MCP client's handshake deadline, which surfaces as `connection closed`.

### Always launch it as a module, never the console script

pip also drops a `servicenow-mcp.exe` shim into your Scripts folder. **That shim is an unsigned `.exe` that pip generates on your machine, so SAC blocks it exactly like it blocked uvx.** Bypass it entirely by calling the module:

| Instead of | Use |
|---|---|
| `servicenow-mcp` | `python -m servicenow_mcp` |
| `servicenow-mcp setup` | `python -m servicenow_mcp setup` |
| `servicenow-mcp --version` | `python -m servicenow_mcp --version` |
| `servicenow-mcp-skills claude` | `python -m servicenow_mcp.setup_skills claude` |

Verify the install:

```powershell
python -m servicenow_mcp --version
```

### Client config on the pip path

Only `command` and `args` change. **The `env` block is identical to the uvx form** — copy any config in Step 2 and swap the top two lines:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

For Codex's TOML, the equivalent is `command = "python"` / `args = ["-m", "servicenow_mcp"]`.

> If `python` isn't found by your MCP client, give the absolute path instead (e.g. `C:/Users/you/AppData/Local/Programs/Python/Python312/python.exe`). MCP clients don't always inherit the PATH your shell has.

---

## Step 2: Configure Your MCP Client

Copy the configuration for your MCP client below.
Replace `your-instance` with your actual ServiceNow instance address.

> These examples use the default `uvx` install. **On the pip path (Step 1b), replace `command` with `python` and `args` with `["-m", "servicenow_mcp"]`** — keeping any `--instance-url` / `--auth-type` flags that follow, and leaving the `env` block exactly as written.

### Claude Desktop

Config file location: `%APPDATA%\Claude\claude_desktop_config.json`

> Create the file if it doesn't exist. If the folder is missing, launch Claude Desktop once to create it.

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

Register via CLI — no config file needed:

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

Verify:
```powershell
claude mcp list
```

### OpenAI Codex

Config file location: `%USERPROFILE%\.codex\agents.toml` or `.codex\agents.toml` in your project root.

> Create the file and folder if they don't exist.

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

### OpenCode

Config file location: `opencode.json` in your project root.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Zed

Config file location: `~/.config/zed/settings.json`

> Add via **Settings** > **MCP Servers** in Zed:

```json
{
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
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

### AntiGravity

Config file location: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> Also accessible via agent panel **...** → **Manage MCP Servers** → **View raw config**.

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
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Save the config, then click **Refresh** in AntiGravity.

---

## Step 3: Install Skills (Optional)

Skills are AI execution blueprints — verified pipelines with safety gates that turn raw MCP tools into reliable workflows. 4 skills across 3 categories.

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# Or with uvx (no install needed)
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

> **On the pip path (Step 1b), call the module instead** — `servicenow-mcp-skills` is the same kind of unsigned pip-generated `.exe` shim that Smart App Control blocks:
>
> ```powershell
> python -m servicenow_mcp.setup_skills claude
> python -m servicenow_mcp.setup_skills codex
> python -m servicenow_mcp.setup_skills opencode
> ```

| Client | Install Path | Auto-Discovery |
|--------|-------------|----------------|
| Claude Code | `.claude\commands\servicenow\` | `/servicenow` slash commands appear on next startup |
| OpenAI Codex | `.codex\skills\servicenow\` | Skills loaded on next agent session |
| OpenCode | `.opencode\skills\servicenow\` | Skills loaded on next session |

| Category | Skills | Purpose |
|----------|--------|---------|
| `analyze/` | 6 | Widget analysis, portal diagnosis, dependency mapping, code detection |
| `fix/` | 3 | Widget patching (staged safety gates), debugging, code review |
| `manage/` | 8 | Page layout, script includes, source export, app source download, changeset workflow, local sync, workflow management, skill management |
| `deploy/` | 2 | Change request lifecycle, incident triage |
| `explore/` | 5 | Health check, schema discovery, route tracing, flow trigger tracing, ESC catalog flow |

**Update:** Re-run the same install command to replace all existing skill files.
**Remove skills only:** delete the skill directory manually (for example `Remove-Item -Recurse .claude\commands\servicenow\`).

---

## Step 4: Verify

1. **Fully quit and restart** your MCP client (close the tray icon too).
2. The browser window opens on the first tool call (not on server start).
3. Complete MFA authentication via Okta/Microsoft Authenticator/etc.
4. After authentication, the browser closes automatically and the session persists.

Test: call the `sn_health` tool from your client.

> If the browser doesn't open, check that Chromium was installed. You can force-install it with: `uvx --with playwright playwright install chromium`

---

## Session Management

Authenticated sessions are saved to disk automatically — no need to log in every time.

- **Session file location**: `%USERPROFILE%\.servicenow_mcp\session_*.json`
- **Default session TTL**: 30 minutes (keepalive thread extends every 15 minutes)
- **On session expiry**: browser window opens automatically for re-authentication

To change the TTL, use the `--browser-session-ttl` option (in minutes):
```
--browser-session-ttl 60
```

To persist the browser profile, add the `--browser-user-data-dir` option:
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
This stores cookies and login state in the directory for longer session persistence.

---

## Tool Packages

Set `MCP_TOOL_PACKAGE` to choose a tool set. Default: `standard` (read-only).

| Package | Tools | Description |
|---------|:-----:|-------------|
| `core` | 12 | Minimal read-only essentials for health, schema, discovery, and key lookups |
| `standard` | 27 | **(Default)** Read-only package across incidents, changes, portal, logs, and source analysis |
| `service_desk` | 29 | standard + incident and change operational writes |
| `portal_developer` | 38 | standard + portal, changeset, script include, and local-sync delivery workflows |
| `platform_developer` | 43 | standard + workflow, Flow Designer, UI policy, incident/change, and script writes |
| `full` | 57 | Broadest packaged surface: all `manage_*` workflows plus advanced operations |

To change, update the `MCP_TOOL_PACKAGE` value:

JSON clients (Claude Desktop, AntiGravity):
```json
"env": {
  "MCP_TOOL_PACKAGE": "standard"
}
```

TOML clients (Codex) — add inside the `args` array:
```toml
"--tool-package", "standard",
```

---

## Troubleshooting

### "uvx not found"
→ Make sure you **closed and reopened** PowerShell after Step 1. If still failing:
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### uvx is found, but nothing runs / "blocked by your administrator" / broke after a Windows update
→ This is **Smart App Control**, not a broken install. uvx unpacks an unsigned temporary executable on every run and SAC refuses to run it. Switch to the pip path in [Step 1b](#step-1b-smart-app-control-blocks-uvx--install-with-pip). Don't disable SAC — that's a one-way switch you can only undo by reinstalling Windows.

### The pip install worked, but `servicenow-mcp` still won't launch
→ You're hitting the pip-generated `servicenow-mcp.exe` shim, which is unsigned and blocked by SAC just like uvx was. Call the module instead: `python -m servicenow_mcp`. Update your MCP client config to `"command": "python"`, `"args": ["-m", "servicenow_mcp"]` too.

### "Python is not installed"
→ On the **uvx** path, `uv` automatically downloads Python 3.11+ — no manual install needed. If there's a conflict with system Python, uninstall and reinstall `uv`.
→ On the **pip** path you supply Python yourself: install 3.10+ from the [python.org installer](https://www.python.org/downloads/) (signed, so it passes Smart App Control) and tick **"Add python.exe to PATH"**. Microsoft Store Python works as well.

### "Browser won't open"
→ Chromium must be installed before MCP startup:
```powershell
uvx --with playwright playwright install chromium   # uvx
python -m playwright install chromium               # pip
```

### "MCP server won't connect"
→ Check config file syntax:
  - JSON: commas, quotes, matching braces
  - TOML: brackets, quotes, commas
→ Verify `instance-url` starts with `https://`.
→ Claude Desktop requires a **full quit and restart** after config changes (close tray icon too).

### "PowerShell script execution is blocked"
→ Allow execution for the current user:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Reset Session
If login issues persist, delete the session cache and retry:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### Version Update
`uvx` reuses the last cached version it downloaded. It does **not** automatically refresh to a newer release on every run. To pull the latest published version into cache:
```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

On the pip path:
```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Chromium is refreshed alongside in both cases, because a newer Playwright expects a newer Chromium build.

After refreshing, fully restart your MCP client so it launches the new version.
