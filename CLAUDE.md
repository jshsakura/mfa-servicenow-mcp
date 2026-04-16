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

## Version Bumps

- Always patch increment: `x.y.z` → `x.y.(z+1)`.
- Never jump minor/major unless explicitly asked.

## Schema Optimization

`server.py::_get_tool_schema()` automatically compacts all Pydantic schemas:
- Strips `title` fields (redundant with `description`)
- Flattens `anyOf` nullable unions to simple types
- Removes top-level model `description` (docstring)
- Truncates long `default` string values (>60 chars)

This saves ~25% context tokens across all tools. Don't bypass this.

## Pre-commit

- `isort` + `black` + `ruff` run on commit. Format before committing.
- Run `python -m pytest tests/ -x` to verify all tests pass.
