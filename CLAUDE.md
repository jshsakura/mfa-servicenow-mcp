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
3. **Headless gate** (`use_headless=True` only): if the profile has no
   non-expired `glide_mfa_remembered_browser` cookie, raise `MFA_REQUIRED`
   immediately. The wrapper catches that marker and re-runs with
   `force_interactive=True`, opening a visible window for MFA/SSO.
4. If the gate passes, headless attempt has 30s to confirm a probe-200.
   If it times out, the wrapper also falls back to interactive (90s).
5. Interactive mode opens a visible window with credentials prefilled and
   waits up to 90s for the user to complete MFA.

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
