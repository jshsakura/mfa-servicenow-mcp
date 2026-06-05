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
3. **Targeted refresh** (one widget or one source family) → the specific
   `download_portal_sources(widget_ids=...)` or `download_<family>` sub-tool.
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

## Browser Login Flow (headless-first)

The browser auth flow is "try headless, fall back to interactive on demand" —
NOT "always open a visible window". Future maintainers must understand this
before touching `auth_manager.py`:

1. `get_auth_headers` calls `_login_with_browser(force_interactive=False)`.
2. `_login_with_browser_sync` launches a persistent Chromium context.
3. **The FIRST attempt is headless by default** (v1.15.8+) when BOTH
   preconditions hold: (a) credentials present (`browser_config.username` AND
   `password` — so a headless attempt can fill an expired-SSO login form
   instead of stalling 30s), and (b) MFA bypass possible (the gate in step 4).
   Then `use_headless = not force_interactive`, regardless of
   `SERVICENOW_BROWSER_HEADLESS`, and a valid remembered-MFA cookie replays
   silently — no window the user watches auto-fill. No creds → visible-first.
   Escape hatch: `SERVICENOW_BROWSER_HEADLESS_FIRST=off` reverts to the old
   `browser_config.headless and not force_interactive`.
4. **Headless gate** (`use_headless=True`): if the profile has no non-expired
   `glide_mfa_remembered_browser` cookie, raise `MFA_REQUIRED` immediately. The
   wrapper catches that marker and re-runs with `force_interactive=True`,
   opening a visible window for MFA/SSO.
5. If the gate passes, headless attempt has 30s to confirm a probe-200. On
   timeout it raises "...browser login/MFA in headless mode" — the wrapper
   matches that too and falls back to interactive (90s). So **1st attempt
   invisible, 2nd+ visible for diagnosis**.
6. Interactive mode opens a visible window with credentials prefilled and
   waits up to 90s for the user to complete MFA.

**Critical safety (do NOT regress):** `_last_login_started_at` is set AFTER the
headless gate passes (just before login.do), NOT before launch. A gate-rejected
first attempt submits no login.do, so it must not burn the 60s
`_MIN_LOGIN_INTERVAL_SECONDS` — otherwise the visible fallback is blocked by
`LOGIN_COOLDOWN` and re-auth dies. See `test_gate_rejection_does_not_burn_min_login_interval`.

Why this matters:
- Reverting to "always interactive" wastes the persistent profile and
  re-prompts MFA every session. The only legitimate trigger for forcing
  interactive is `force_interactive=True` from the wrapper's fallback.
- Hardcoding `force_interactive=True` at call sites kills the headless
  attempt — which is the entire point of the persistent profile.
- The probe path default is `sys_user_preference` (NOT `sys_user`).
  See `cli.py:325-363` for the full history of why.

Don't break this without reading `auth_manager.py` and the related tests
end-to-end.

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
