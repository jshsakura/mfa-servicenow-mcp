# MFA ServiceNow MCP — LLM Setup Guide

> **This file is for LLM agents, not humans.**
> A human pastes the curl command below into their AI coding assistant.
> The LLM reads this file and walks the user through setup interactively.

---

## How to use (for humans)

Paste this into your AI coding assistant (Claude Code, Cursor, Codex, OpenCode, Windsurf, etc.):

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

That's it. Your AI handles the rest.

---

## Instructions for the LLM agent

You are setting up **mfa-servicenow-mcp** — an MCP server that gives AI agents access to ServiceNow platforms with MFA/SSO support. Follow every step below in order. Ask the user questions interactively; do NOT assume values.

### Step 0 — Detect environment

1. Detect the operating system: run `uname -s 2>/dev/null || echo Windows`
2. Detect which AI client you are running inside. Use this mapping:

| Signal | Client |
|--------|--------|
| You have access to `claude mcp add` or `.claude/` directory | **claude-code** |
| You are inside Cursor IDE or `.cursor/` exists | **cursor** |
| You have access to OpenCode CLI or `opencode.json` exists | **opencode** |
| You are inside Codex CLI or `.codex/` exists | **codex** |
| You are inside Windsurf IDE or `.windsurf/` exists | **windsurf** |
| You are inside VS Code with Copilot | **vscode-copilot** |
| You are inside Antigravity | **antigravity** |
| You are inside Zed editor or `~/.config/zed/` exists | **zed** |
| None of the above | Ask the user which client they use |

3. If you cannot auto-detect, ask:
   > Which AI coding tool are you using?
   > 1. Claude Code
   > 2. Claude Desktop
   > 3. Cursor
   > 4. OpenCode
   > 5. Codex (OpenAI)
   > 6. Windsurf
   > 7. VS Code Copilot
   > 8. Zed
   > 9. AntiGravity (Google)

Store the result as `$CLIENT`.

### Step 1 — Install the runtime

There are three install methods. **Try them strictly in this order and stop at the first one that works:**

1. **uvx** — the default. Use it unless it is actually blocked.
2. **pip** — the fallback when uvx cannot execute (Windows Smart App Control).
3. **Release zip/exe** — last resort, only when PyPI itself is unreachable.

Store the winner as `$INSTALL_METHOD` (`uvx`, `pip`, or `zip`). **Every later step branches on this value**, so do not skip recording it.

**1.1 — uvx (default, try first)**

Check if `uv` is already installed: `uv --version`

If NOT installed:

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

After install, verify: `uv --version`
If the command is not found, the user may need to restart their shell or add `~/.local/bin` to PATH.

Then confirm that uvx can actually *execute* a package — installing `uv` successfully is not proof of this:

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
```

If a version number prints, set `$INSTALL_METHOD=uvx` and go to Step 2.
If the command is killed, refuses to run, or reports a policy/permission block, go to 1.2.

**1.2 — pip (fallback when uvx is blocked)**

Use this when `uv` installs fine but the `uvx …` command above will not run, or when `uv` itself is blocked from running.

On Windows the usual cause is **Smart App Control**: uvx unpacks an unsigned temporary executable on every run, and SAC blocks it. A strong tell is that uvx worked until recently and stopped right after a Windows update.

Requires Python 3.10+. On Windows, a Python from the python.org installer is signed and passes SAC as-is.

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Set `$INSTALL_METHOD=pip`.

> **Critical rule for the pip path — never use the `servicenow-mcp` console script.** Always invoke the server as `python -m servicenow_mcp`. The console script is an unsigned `.exe` shim that pip generates, and Smart App Control blocks it for exactly the same reason it blocks uvx. This applies to the installer command in Step 4 **and** to the `command`/`args` written into the MCP client config.

> On macOS/Linux, Homebrew and distro-packaged Pythons refuse global pip installs under [PEP 668](https://peps.python.org/pep-0668/) (`externally-managed-environment`). Use a python.org Python, or a virtualenv, or simply stay on uvx — pip is a Windows-driven fallback, not a general recommendation.

**1.3 — Release zip/exe (last resort)**

Use this **only when PyPI itself is unreachable** (corporate network blocks the package index outright), so neither 1.1 nor 1.2 can download anything. Do not jump here just because uvx was blocked — that case is 1.2.

- Download `servicenow-mcp-<platform>-<version>.zip` from GitHub Releases. There is no installer script — the zip contains the PyInstaller-built executable only.
- Extract the executable into any stable folder the user controls (e.g. `~/apps/servicenow-mcp/`).
- If the browser download is blocked too, download `ms-playwright-chromium-<platform>-<version>.zip` from the same release and extract it to a sibling folder named `ms-playwright/` — the executable auto-detects that layout at startup and sets `PLAYWRIGHT_BROWSERS_PATH` to it for its own process.
- The MCP client `command` becomes the absolute path of that executable and `args` becomes `[]`. The env block is identical to the uvx setup.

Set `$INSTALL_METHOD=zip`.

### Step 2 — Install Playwright Chromium (MANDATORY, do NOT skip)

> Hard dependency. Skipping this is the #1 reason setups fail in the field.
> Do not assume it's already installed. Do not let the user defer it.
> Do not proceed to Step 3 until this succeeds.

**2.1 — Check whether Chromium is already installed**

- macOS: `ls ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium 2>/dev/null`
- Linux: `ls ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null`
- Windows (PowerShell): `Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright\chromium-*\chrome-win\chrome.exe" -ErrorAction SilentlyContinue`

If a path is printed, Chromium is already installed — skip to Step 3.

**2.2 — Install Chromium**

If 2.1 found nothing, install Chromium using the same execution style as `$INSTALL_METHOD`, so Playwright resolves the same way the MCP server will:

- **`$INSTALL_METHOD=uvx`:**
  ```bash
  uvx --with playwright playwright install chromium
  ```
- **`$INSTALL_METHOD=pip`:**
  ```powershell
  python -m playwright install chromium
  ```
  (Step 1.2 already ran this. Run it again only if 2.1 found nothing.)
- **`$INSTALL_METHOD=zip`:** there is nothing to download — the `ms-playwright/` folder extracted next to the executable in Step 1.3 *is* the Chromium install. Verify that folder exists instead of running a command.

This downloads ~150 MB the first time. On a slow link it can take several minutes — that is normal. Do not abort early. Show the user a progress message ("Downloading Chromium for ServiceNow MFA login — this can take a few minutes on slow networks…") so they understand the wait.

If the install command is blocked rather than merely slow, do not improvise here — go back to Step 1 and move down the ordered list (uvx → pip → zip/exe), then return.

**2.3 — Verify and stop on failure**

Re-run the check from 2.1. If the binary is still missing, **STOP the setup** and report the failure to the user with the exact command output. Common causes:

- Corporate policy blocking package or browser downloads; move down the Step 1 list (uvx → pip → zip/exe)
- Windows Smart App Control blocking the unsigned executable uvx unpacks; switch to the pip path (Step 1.2)
- Antivirus quarantining the Chromium archive
- Disk full

Do **not** continue to Step 3 with Chromium missing. The MCP server will appear to start, the first tool call will hang, and the user's login window will never open — exactly the failure mode this step exists to prevent.

**Why this matters (context for the agent — do not surface to the user unless asked):** the runtime tries to fall back to "install on demand" when Chromium is absent, but on slow connections that download exceeds the MCP host's tool-call timeout. The user sees no login window, no error UI, and assumes the server is broken. Pre-installing here makes the first tool call subsecond.

### Step 3 — Collect user configuration

Ask the user these questions one by one. Provide defaults in brackets.

1. **ServiceNow instance URL**
   > What is your ServiceNow instance URL?
   > Example: `https://your-company.service-now.com`

   Store as `$INSTANCE_URL`. Validate it looks like a URL.

2. **Authentication type**
   > How do you authenticate to ServiceNow?
   > 1. browser — MFA/SSO via real browser (recommended)
   > 2. basic — Username + password
   > 3. oauth — OAuth 2.0 client credentials
   > 4. api_key — REST API key

   Store as `$AUTH_TYPE`. Default: `browser`

3. **Credentials** (optional, for form pre-fill with browser auth)
   > (Optional) Enter your ServiceNow username to pre-fill the login form.
   > Leave blank to type it manually each time.

   Store as `$USERNAME` (may be empty).
   If provided, also ask for `$PASSWORD`.

4. **Tool package**
   > Which tool package do you need?
   > 1. standard — Core tools (incidents, changes, catalog) [default]
   > 2. service_desk — Standard + assignment, SLA, escalation
   > 3. portal_developer — Standard + portal widgets, pages, themes
   > 4. platform_developer — Standard + scripts, flows, update sets
   > 5. full — Broadest packaged surface with bundled workflows (53 tools)

   Store as `$TOOL_PACKAGE`. Default: `standard`

5. **Headless browser**
   > Run browser in headless mode? (no visible window)
   > Recommended: No (so you can see and complete MFA prompts)

   Store as `$HEADLESS`. Default: `false`

### Step 4 — Run the installer command

**IMPORTANT: Always default to project-local installation when the client supports it.** Use `--scope global` only if the user explicitly asks for a global install.

Build a single installer command and run it from the current project root. The installer now owns:
- client-specific config file paths
- merge/update behavior for existing config files
- optional skills installation for supported clients

Base command — **pick the form matching `$INSTALL_METHOD` from Step 1:**

```bash
# $INSTALL_METHOD=uvx
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS"
```

```powershell
# $INSTALL_METHOD=pip — module invocation, NOT the servicenow-mcp console script
python -m servicenow_mcp setup "$CLIENT" `
  --instance-url "$INSTANCE_URL" `
  --auth-type "$AUTH_TYPE" `
  --tool-package "$TOOL_PACKAGE" `
  --browser-headless "$HEADLESS"
```

```bash
# $INSTALL_METHOD=zip — run the extracted executable, and point it at the bundled browsers
/absolute/path/to/servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS" \
  --server-command "/absolute/path/to/servicenow-mcp" \
  --playwright-browsers-path "/absolute/path/to/ms-playwright"
```

Add flags only when needed:

- If the user provided username: `--username "$USERNAME"`
- If the user provided password: `--password "$PASSWORD"`
- For OAuth: add `--client-id`, `--client-secret`, and optionally `--token-url`
- For API key: add `--api-key` and optionally `--api-key-header`
- If the user wants global install: add `--scope global`
- If the user does **not** want skills: add `--skip-skills`

Examples (shown in the `uvx` form — on the pip path replace the leading `uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp` with `python -m servicenow_mcp`):

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup codex \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type basic \
  --username "your-username" \
  --password "your-password"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup claude-code \
  --instance-url "https://your-instance.service-now.com" \
  --scope global \
  --skip-skills
```

**If `$INSTALL_METHOD=pip`, you MUST correct `command`/`args` afterwards.** The installer always writes the uvx form, and it has no flag that produces the pip form (`--server-command` sets `command` but forces `args` to `[]`, which is right for the zip/exe path and wrong for pip). So run the installer, then open the config file it reported and change exactly these two keys — **leave the `env` block completely untouched, it is identical for every install method:**

```json
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
```

For Codex (`config.toml`) the same correction is:

```toml
command = "python"
args = ["-m", "servicenow_mcp"]
```

This is the one sanctioned hand-edit of the config. Do not rewrite anything else.

For reference, the two valid `command`/`args` pairs are:

| `$INSTALL_METHOD` | `command` | `args` |
|---|---|---|
| `uvx` | `uvx` | `["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]` |
| `pip` | `python` | `["-m", "servicenow_mcp"]` |
| `zip` | absolute path to the executable | `[]` |

### Step 5 — Verify installation

1. Confirm the installer exited successfully
2. Read the config file path reported by the installer summary
3. If `$INSTALL_METHOD=pip`, confirm `command` is `python` and `args` is `["-m", "servicenow_mcp"]` — if the installer left `uvx` there, apply the correction from Step 4 now
4. If skills were installed, confirm the installed skills directory exists
5. Do **not** manually rewrite the config beyond the `command`/`args` correction above, unless the installer failed and you are explicitly repairing it

### Step 6 — Tell the user what happens next

After installation, tell the user:

> **Installation is complete!**
> Restart your AI client (or reload MCP servers) so it picks up the new configuration.
>
> On the first browser-authenticated tool call, a browser window will open for MFA/SSO login.
> After login, try: `Run a health check on my ServiceNow instance`
> Full docs: https://jshsakura.github.io/mfa-servicenow-mcp/

Do **not** attempt to call ServiceNow MCP tools in the current session after setup. The client must restart first.

### Important notes for the LLM

- **Never hardcode credentials** in config files without asking. If the user skips credentials, omit them entirely from the config.
- The installer merges into existing config files. Do not hand-roll config merges unless recovery is needed — the `command`/`args` correction for the pip path (Step 4) is the sole exception.
- **The `env` block never depends on the install method.** Only `command`/`args` change between uvx, pip, and zip/exe. If you find yourself changing env vars because of how the server was installed, you have made a mistake.
- **If the user has more than one instance (dev / test / prod):** the recommended setup is still a *single* server entry using profiles — list the instances in `SERVICENOW_INSTANCE_CONFIG` (alias → settings) and pick the default with `SERVICENOW_ACTIVE_INSTANCE`. One process, one login, and cross-instance comparison works. Do not reach for multiple entries by default.
  Only if the user explicitly wants the connections shown **separately in the client UI**, register one entry per instance and give each its own name with `--server-name` (env: `SERVICENOW_MCP_SERVER_NAME`, default `ServiceNow`), so tool namespaces stay stable as `mcp_snow-dev_*` / `mcp_snow-prd_*`. Without it every entry advertises itself as `ServiceNow` and the client disambiguates by load order (`mcp_servicenow`, `mcp_servicenow2`), which can shift between restarts — meaning nobody can tell which connection is production. The installer has no `--server-name` flag, so add these extra entries by hand:
  ```json
  "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-prd"]
  ```
  On the pip path the equivalent is `"args": ["-m", "servicenow_mcp", "--server-name", "snow-prd"]`.
- **Windows paths** use backslashes. Use the correct path separator for the OS.
- If any step fails, diagnose the error and help the user fix it before moving on.
- Keep the conversation friendly and concise. Don't dump walls of text.
- After installation, do NOT try to test MCP tools. Just tell the user to restart and they're good to go.
