# AGENTS.md

ServiceNow MCP Server — Python 3.11+ / MCP SDK / Pydantic v2 / Playwright (optional)

## Commands

```bash
uv sync                    # install
uv run pytest              # test (must pass before PR)
uv run black src/ && uv run isort src/ && uv run ruff check src/  # lint
uv build                   # package
```

## Structure

```
src/servicenow_mcp/
  cli.py            # CLI entrypoint
  server.py         # stdio MCP server, tool dispatch, mutating-tool confirm guard
  server_sse.py     # SSE MCP server (Starlette/Uvicorn)
  auth/auth_manager.py   # session/cookie/MFA auth
  config/tool_packages.yaml  # role-based tool package definitions
  utils/registry.py      # @register_tool decorator + auto-discovery
  utils/config.py        # ServerConfig (Pydantic)
  tools/                 # one module per domain
```

## Adding a Tool

1. Create or edit a module in `src/servicenow_mcp/tools/`
2. Use `@register_tool` decorator (auto-discovered, no manual import needed):

```python
@register_tool("verb_noun", params=MyParams, description="Keep to 1-2 sentences", serialization="str")
def verb_noun(config: ServerConfig, auth_manager: AuthManager, params: MyParams):
    ...
```

3. Register in `config/tool_packages.yaml` — must be in `full` package; add to role packages selectively. **Unregistered tools are invisible to clients.**
4. Add test file in `tests/` (`test_<module>.py`) — required for every new tool.

## Rules

- **Tool name**: snake_case `verb_noun`. Mutating tools must start with a prefix in `MUTATING_TOOL_PREFIXES` (`create_`, `update_`, `delete_`, etc.) to trigger the automatic confirm guard.
- **Params**: Pydantic v2 BaseModel. Every Field must have a `description` — this is the only information LLMs use to understand parameters.
- **Short descriptions**: MCP clients include all tool schemas in context every turn. Verbose descriptions waste tokens.
- **Minimize payload**: Exclude large fields (script body, etc.) in list queries. Use `sysparm_fields` to request only needed fields. Always paginate.
- **API calls**: Always go through `auth_manager` (handles session/cookie/MFA automatically).
- **Package separation**: Using role packages (`portal_developer`, `platform_developer`, etc.) instead of `full` reduces tool count and saves context.
- **Tests**: Every new feature or change must include tests. `uv run pytest` must pass before PR.
- **Commits**: Conventional style (`feat:`, `fix:`, `docs:`, `chore:`). PRs should focus on a single domain.
- **Version**: Bump `pyproject.toml` version on release.
