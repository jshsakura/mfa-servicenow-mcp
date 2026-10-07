"""One-shot measurement: how many tokens do the active tool schemas cost?

Usage:
    uv run python scripts/measure_tool_tokens.py [package_name]

Default package = "standard" (the user's everyday surface).
Uses tiktoken (cl100k_base) when installed; otherwise prints a chars/4 ESTIMATE
and says so. Published figures must come from a tiktoken run.
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


def _encoder() -> Any:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


_ENC = _encoder()
# Say which counter produced the number. The fallback used to print under a
# "cl100k_base" label, so a chars/4 estimate was published as a measurement.
COUNTER = "cl100k_base" if _ENC is not None else "ESTIMATE chars/4 (tiktoken not installed)"


def count_tokens(text: str) -> int:
    if _ENC is not None:
        return len(_ENC.encode(text))
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
    print(f"Total tokens ({COUNTER}): {total_tokens:,}")
    if _ENC is None:
        print("  -> not a measurement; for published figures run with tiktoken:")
        print("     uv run --no-sync --with tiktoken python scripts/measure_tool_tokens.py <pkg>")
    print()
    print("All tools by token cost:")
    print(f"  {'tool':<40} {'tokens':>8} {'chars':>8}")
    for name, tokens, chars in rows:
        print(f"  {name:<40} {tokens:>8} {chars:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
