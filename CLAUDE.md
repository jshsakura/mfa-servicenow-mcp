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

## TLS Impersonation (curl_cffi, default-ON)

Default-ON is a deliberate policy: JA3-hardened instances silently reject stock
`requests` even with valid cookies (issue #37), and the failure is invisible
until hit. Keep it default-ON; flip `SERVICENOW_TLS_IMPERSONATE=off` only when
curl_cffi itself regresses on an instance. Semantics live in
`_build_http_session` and its tests.

## Auth Separation

- **Basic/OAuth/API Key**: Table API only. Never call undocumented APIs.
- **Browser auth**: Can use processflow API and other session-only endpoints.
- Gate browser-only calls behind `_is_browser_auth(config)`.
- Never silently try browser-only APIs with basic auth — it wastes a network round-trip.

## auth_manager.py is FROZEN — bug fixes only

Exempt from the file-size rule; its behavior is coupled to real servers, real
browsers, and timing that mock tests cannot fully verify — refactors here break
in production, not in CI (probe-path saga: 8 patch versions; headless-first:
shipped→broken→reverted→re-shipped).

- **Do NOT refactor, split, reorder, or "clean up" this file.** Structural change
  only on explicit maintainer request, gated on the invariant tests below.
- Bug fixes = minimal diffs. If a change breaks one of these tests, the change
  is wrong — fix the change, not the test.
- Adding NEW invariant-pinning tests is always welcome; that is the sanctioned
  way to make this file safer.

The behavioral invariants are pinned in tests, not documented here:

| Invariant area | Pinned by |
|---|---|
| Headless-first login: cookie gate, MFA fast-detect, cooldown-clock restore on every headless bail, `force_interactive=True` ⇒ visible, window closed on every raise path, `LOGIN_COOLDOWN` | `test_auth_manager_final.py::TestLoginWithBrowserSync` |
| Sliding session TTL (`_mark_browser_session_recently_valid` on every 200) | `test_auth_manager_browser.py` |
| User-close = cancellation (15s cooldown, `LOGIN_CANCELLED_BY_USER`) | `test_auth_manager.py::TestBrowserLoginErrorHandling` |
| Probe default `sys_user_preference`, NEVER `sys_user` | `test_cli.py` |
| Playwright startup non-fatal + background daemon self-heal (`sys.frozen` skip, `SERVICENOW_AUTO_INSTALL_CHROMIUM=off` opt-out); never inline/blocking install, never a startup raise | `test_auth_manager.py::TestStartupNonFatalChromium`, `::TestAutoInstallChromium` |

Design history and the "why": issues #37 (TLS), #45 (headless-first), #62
(Playwright bump), and git log on `auth_manager.py`.

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
