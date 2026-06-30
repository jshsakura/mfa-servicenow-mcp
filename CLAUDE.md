# MFA ServiceNow MCP — Development Rules

## Tool Description Rules (LLM Context Budget)

Tool definitions are sent to the LLM on every request. Every character costs tokens.

### Description Limits
- Tool `description`: max 120 chars. State what it does + one usage hint.
- Parameter `description`: max 80 chars. No examples unless critical.
- Good: `"List Flow Designer custom action definitions. Use list_actions to find sys_ids."`
- Bad: `"This tool allows you to list all of the custom action definitions that have been created in the Flow Designer interface of ServiceNow, returning their names, statuses, and other metadata."`

### Parameter Model Rules
- `Optional[str]` is fine — the schema compactor strips `anyOf` noise automatically.
- Never put long default values (>60 chars) in `Field(default=...)`. Move to docstring or omit.
- Don't duplicate the tool description in the Pydantic model docstring — the compactor strips it.
- Use `Field(description=...)` on every parameter. Undocumented params waste LLM reasoning.

### Adding New Tools Checklist
1. Follow existing patterns in the same file — don't invent new structures.
2. Register in `config/tool_packages.yaml` under the correct package(s).
3. Read-only tools go in `standard`. Write tools go in domain packages only.
4. Add `"Use <list_tool> first to find the sys_id."` to get-detail tool descriptions.
5. Add tests: happy path, error, not-found (for detail), count_only (for list), filters.
6. Run `python -m pytest tests/ -x` before committing.

## Download / Sync Flow (LLM must follow)

Source downloads write full bodies to disk; only summaries return to context.
Picking the wrong tool wastes round-trips and tokens. Default decision tree:

1. **Reading one widget/SI body** → `get_widget_bundle` (widget only) or
   `get_portal_component_code` with `fetch_complete=True`. Do NOT loop on
   `script_offset` unless the field is genuinely >12KB and you only need a slice.
2. **Bulk source dump for analysis** → `download_app_sources(scope=...)` (Step 1).
   Then `audit_local_sources(source_root=...)` (Step 2). Do NOT chain 7
   individual `download_*` sub-tools — they exist for targeted refreshes only.
3. **Targeted refresh** (portal slice or server-side families) → the specific
   `download_portal_sources(widget_ids=...)` (portal) or
   `download_server_sources(families=[...])` (SIs/BRs/UI/api/security/admin).
4. **Already downloaded before** → `diff_local_component(path=...)` first.
   Re-download only if diff reports drift, or if `_manifest.json` is missing.
5. **Push back to ServiceNow** → `diff_local_component` → `update_remote_from_local`.

Standard download root: `temp/<instance>/<scope>/_manifest.json`. Treat its
presence as "already fetched"; check `downloaded_at` for freshness.

## TLS Impersonation (curl_cffi, default-ON as of v1.12.21)

Some ServiceNow instances (especially those fronted by Cloudflare/Akamai
or running internal JA3-based bot detection) reject Python's stock
`requests` library regardless of cookie validity — the same captured
session works fine in a real browser but 302→/logout_success.do when
sent from `requests`. Symptom: web login works, `sn_health` produces
"born dead" sessions repeatedly. See issue #37 for the full post-mortem
of the 2026-05-13 saga.

`_build_http_session` uses `curl_cffi.requests.Session(impersonate=...)`
to make the TLS handshake byte-for-byte identical to a real browser
(cipher order, TLS extensions, GREASE, HTTP/2 SETTINGS, ALPN). The
`SERVICENOW_TLS_IMPERSONATE` environment variable controls which
profile via a tri-state:

| env value | result |
|---|---|
| (unset) | `chrome120` — default since v1.12.21 |
| `off` / `false` / `0` / `disable` / `no` / `none` | stock `requests.Session`, explicit opt-out |
| anything else | use the value as the curl_cffi profile (e.g. `chrome131`, `chrome120_arm64`, `safari17_0`) |

Default-ON because the failure mode is invisible to users until they
hit it (and then they don't know to look for an env var). The cost is
~10MB extra wheel and a tiny per-request overhead from libcurl; the
benefit is "uvx mfa-servicenow-mcp@latest just works on hardened
instances". Verify the active wire layer by looking for
`HTTP session: curl_cffi impersonate=...` at startup or the
`http_client=curl_cffi:<profile>` field on any `auth_event=` line.

Flip to `off` only if curl_cffi causes a regression on an instance —
the diagnostic infrastructure (v1.12.14+ auth_event channel) will say
so clearly when something breaks.

## Auth Separation

- **Basic/OAuth/API Key**: Table API only. Never call undocumented APIs.
- **Browser auth**: Can use processflow API and other session-only endpoints.
- Gate browser-only calls behind `_is_browser_auth(config)`.
- Never silently try browser-only APIs with basic auth — it wastes a network round-trip.

## Browser Login Flow (safe headless-first, v1.15.15)

The flow is "try headless silently, fall back to a visible window ONLY when the
server actually demands MFA". The whole point: while the 16h
`glide_mfa_remembered_browser` cookie is valid the session refreshes invisibly
(no window stealing the user's cursor/focus); a window appears only when a human
must type a TOTP code. Read this before touching `auth_manager.py`:

1. `get_auth_headers` calls `_login_with_browser(force_interactive=False)`.
2. `_login_with_browser_sync`: `use_headless = not force_interactive`. So the
   FIRST attempt is always headless (regardless of `SERVICENOW_BROWSER_HEADLESS`);
   the interactive fallback (`force_interactive=True`) is always visible.
3. **Cookie gate** (headless, non-debug): no non-expired
   `glide_mfa_remembered_browser` cookie → raise `MFA_REQUIRED` immediately,
   BEFORE any login.do. Wrapper re-runs `force_interactive=True` → visible window.
4. **MFA-page fast-detect**: if the headless wait loop lands on an MFA challenge
   (`_is_mfa_challenge_url` — narrow, MFA pages only, NOT the plain `login.do` the
   success path transits), abort in ~1s → visible fallback. Without this it would
   burn the full 30s headless budget.
5. Headless success: a valid cookie makes the server skip MFA → confirmed in ~3s,
   silent. Visible fallback: window with creds prefilled, 90s for the user.

**Why the v1.15.8-9 "headless-first" experiment failed and how v1.15.15 fixes it.**
That version trapped re-auth: cookie present → gate passed → login.do submitted →
server still demanded TOTP → 30s timeout that ALSO burned the 60s
`_MIN_LOGIN_INTERVAL_SECONDS`, so the visible fallback hit `LOGIN_COOLDOWN` and
re-auth FAILED. It was reverted to visible-only in v1.15.14. v1.15.15 reintroduces
headless-first WITH the three fixes that close exactly that hole:
- **Cooldown clock restore.** `_last_login_started_at` is snapshotted at entry
  (`prev_last_login_started_at`). Every headless bail path — gate-reject, MFA
  fast-detect, headless timeout — restores it before raising, so the immediate
  visible fallback is NEVER refused by `LOGIN_COOLDOWN`. (Do NOT move the set
  back to "before launch unconditionally"; that is what re-broke it.)
- **MFA fast-detect** (step 4) so the fallback is snappy, not 30s late.
- **`force_interactive=True` ⇒ visible, always.** It is the "a human must act
  now" path; never let the headless config flag keep it invisible.

## Sliding session TTL (v1.15.15)

`_browser_cookie_expires_at` is a SLIDING window, not a fixed login+TTL one.
`_mark_browser_session_recently_valid()` (called on every authenticated 200)
pushes the expiry to `now + session_ttl_minutes` — mirroring ServiceNow's
sliding inactivity timeout. Before this, an actively-used session was torn down
and re-logged-in every ~30 min from login even under continuous traffic (the
"login window every 30 min" complaint). If the server has genuinely ended the
session, the next request 401s and normal self-heal re-logs-in — so sliding
never keeps a dead session alive, it only stops us giving up on a live one early.

Other invariants (still true):
- The only legitimate trigger for forcing interactive is `force_interactive=True`
  from the wrapper's fallback. Hardcoding it at call sites kills the silent path.
- The probe path default is `sys_user_preference` (NOT `sys_user`).
  See `cli.py:325-363` for the full history of why.

Don't break this without reading `auth_manager.py` and the related tests
(`test_auth_manager_final.py::TestLoginWithBrowserSync`,
`test_auth_manager_browser.py`) end-to-end.

## Playwright/Chromium — the only external runtime dep; NEVER hard-fail on a bump (v1.18.5)

Playwright is the single heavy external dependency, and its npm/PyPI package
version is welded to a specific Chromium browser *revision*. The standard launch
is `uvx --with playwright …`, which is UNPINNED: every launch resolves the
LATEST Playwright, but the shared `~/.cache/ms-playwright` only holds the
revision that was last `playwright install`ed. So a Playwright release silently
makes the cached binary "missing or version-mismatched". This broke the whole
MCP **twice** before v1.18.5 — see issue #62 for the post-mortem.

**Why it was catastrophic, not merely degraded.** `_ensure_playwright_ready()`
ran in `AuthManager.__init__` (startup) and RAISED on a mismatch →
`ServiceNowMCP.__init__` raised → the MCP "failed to load" with the only helpful
message buried in stderr. Even a session that needed no browser (valid cached
cookie → Table API only) was killed.

**The v1.18.5 recurrence-prevention design (do NOT regress any of these):**
- **Startup is non-fatal.** The probe failure is caught, stored on
  `self._browser_setup_error`, and the server boots anyway. A valid cached
  session keeps serving Table API requests with no browser at all.
- **Background self-heal.** `_start_background_chromium_install()` runs
  `[sys.executable, -m, playwright, install, chromium]` in a DAEMON thread —
  fetching exactly the revision the *resolved* Playwright expects. It MUST stay
  background: a blocking inline install inside the handshake is what caused the
  historical Codex "connection closed: initialize response" timeout (which is
  why prior devs refused inline auto-install). Clears the flag on success;
  keeps the manual remediation on failure.
  - Opt out: `SERVICENOW_AUTO_INSTALL_CHROMIUM=off` (metered/locked-down nets).
  - Skipped when `sys.frozen` (PyInstaller exe: `sys.executable` is the app, not
    a Python — running it `-m playwright` would re-launch the app). The frozen
    build bundles Chromium anyway.
- **First login re-probes** when startup flagged a problem, surfacing the precise
  `playwright install chromium` remediation as the tool-call error (not a raw
  Playwright stack or silent timeout). `server.py` prefers the captured message
  for the MCP `instructions`.

Net effect: a Playwright bump now self-heals invisibly; if it can't, the user
gets a clear actionable notice instead of a dead server. Don't reintroduce a
startup raise, don't move the install inline/blocking, and don't "fix" it
per-machine by swapping the client config to a local install (rejected — the
product itself must self-heal + warn). Tests:
`test_auth_manager.py::TestStartupNonFatalChromium`,
`::TestAutoInstallChromium`.

## Version Bumps & Git Tags

- Always patch increment: `x.y.z` → `x.y.(z+1)`.
- Never jump minor/major unless explicitly asked.
- **After every version bump commit, immediately create and push the git tag:**
  ```
  git tag v{version} && git push origin main v{version}
  ```
- Never push a version bump commit without its corresponding tag.

## Schema Optimization

`server.py::_get_tool_schema()` automatically compacts all Pydantic schemas:
- Strips `title` fields (redundant with `description`)
- Flattens `anyOf` nullable unions to simple types
- Removes top-level model `description` (docstring)
- Truncates long `default` string values (>60 chars)

This saves ~25% context tokens across all tools. Don't bypass this.

## No Company-Specific Data in Code

This is a **public open-source** repo. Never put real company names, scope namespaces, company codes, or any customer-identifiable information in source code, tests, examples, descriptions, or comments. Use generic placeholders instead (e.g. "my_app", "Old Flow", "New Flow").

## Pre-commit

- `isort` + `black` + `ruff` run on commit. Format before committing.
- Run `python -m pytest tests/ -x` to verify all tests pass.
