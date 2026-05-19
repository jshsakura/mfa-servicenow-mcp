"""One-shot measurement: how many tokens do the active tool schemas cost?

Usage:
    uv run python scripts/measure_tool_tokens.py [package_name]

Default package = "standard" (the user's everyday surface).
Tries tiktoken (cl100k_base) for the token count; falls back to chars/4.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List

# Configure a minimal dummy config BEFORE importing the server so AuthManager
# doesn't try to do anything live.
os.environ.setdefault("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")

from servicenow_mcp.server import ServiceNowMCP  # noqa: E402
from servicenow_mcp.utils.config import (  # noqa: E402
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    ServerConfig,
)


def build_dummy_config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.API_KEY, api_key=ApiKeyConfig(api_key="dummy")),
    )


def count_tokens(text: str) -> int:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Rough fallback: ~4 chars per token for English/JSON.
        return len(text) // 4


def tools_payload(server: ServiceNowMCP) -> List[Dict[str, Any]]:
    tools = asyncio.run(server._list_tools_impl())  # type: ignore[attr-defined]
    out: List[Dict[str, Any]] = []
    for t in tools:
        out.append(
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
        )
    return out


def main() -> int:
    pkg = sys.argv[1] if len(sys.argv) > 1 else "standard"
    os.environ["MCP_TOOL_PACKAGE"] = pkg

    server = ServiceNowMCP(build_dummy_config())
    payload = tools_payload(server)

    if not payload:
        print(f"No tools enabled for package '{pkg}'", file=sys.stderr)
        return 1

    full_json = json.dumps(payload, ensure_ascii=False)
    total_tokens = count_tokens(full_json)

    # Per-tool breakdown for hot spots.
    rows = []
    for tool in payload:
        tjson = json.dumps(tool, ensure_ascii=False)
        rows.append((tool["name"], count_tokens(tjson), len(tjson)))

    rows.sort(key=lambda r: r[1], reverse=True)

    print(f"Package: {pkg}")
    print(f"Tools enabled: {len(payload)}")
    print(f"Total payload bytes: {len(full_json):,}")
    print(f"Total tokens (cl100k_base): {total_tokens:,}")
    print()
    print("Top 15 tools by token cost:")
    print(f"  {'tool':<40} {'tokens':>8} {'chars':>8}")
    for name, tokens, chars in rows[:15]:
        print(f"  {name:<40} {tokens:>8} {chars:>8}")

    print()
    print("Bottom 5 (smallest):")
    for name, tokens, chars in rows[-5:]:
        print(f"  {name:<40} {tokens:>8} {chars:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
