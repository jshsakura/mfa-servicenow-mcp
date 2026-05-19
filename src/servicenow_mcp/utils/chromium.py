"""Chromium presence probe for browser auth.

Centralizes the "is Playwright Chromium installed?" check so the MCP server,
the auth manager, and the sn_health tool all answer the same question without
duplicating logic. Returns user-facing instructions (with the exact install
command) — the caller decides where to surface them.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def check_chromium_install_hint() -> Optional[str]:
    """Return an LLM-facing instructions string if Chromium needs installing.

    Browser auth requires a Playwright Chromium binary. When it's missing or
    version-mismatched we surface the exact install command through every
    user-visible channel (MCP `instructions` + sn_health) so the LLM can guide
    the user immediately instead of letting them discover it via a cryptic
    handshake timeout on the first tool call.

    Returns:
        Multi-line instructions string when remediation is needed, else None.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        return (
            "Playwright Python package is missing. Run the server with "
            "`uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp …` "
            "or install it manually (`pip install playwright`)."
        )

    try:
        with sync_playwright() as pw:
            _ = pw.chromium.executable_path
    except Exception as exc:
        msg = str(exc).lower()
        if "executable" in msg or "browser" in msg or "doesn't exist" in msg:
            return (
                "Playwright Chromium browser is not installed (browser auth will fail "
                "on the next tool call). Run this once:\n"
                "  uvx --with playwright playwright install chromium\n"
                "Then retry. To prevent this from recurring after a Playwright release, "
                "pin both packages in your MCP client config:\n"
                '  args = ["--with", "playwright==<version>", '
                '"--from", "mfa-servicenow-mcp==<version>", "servicenow-mcp"]'
            )
        # Non-binary error — let it surface elsewhere; don't pollute instructions.
        logger.debug("Chromium probe raised non-binary error: %s", exc)
    return None
