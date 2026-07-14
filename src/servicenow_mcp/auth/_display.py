"""Can this host actually show a browser window?

Stateless sibling helper (see CLAUDE.md: the AuthManager class is frozen, its
stateless helpers are not).

The browser auth path falls back to a VISIBLE Chromium window whenever the
headless attempt reports "MFA required" — a human has to type the TOTP. On a
headless Linux box (SSH session, container, systemd unit) there is no display
server, so that fallback launches a window nobody can see, burns the login
budget, and finally fails with a Chromium error about a missing X server.

The fix is to fail *early* and *actionably*: browser auth needs a human at a
screen. On a display-less host the right answer is a non-interactive auth type
(basic / oauth / api_key), not a longer timeout.

macOS and Windows always have a window server, so the check is Linux-only.
"""

import os
import sys
from typing import Optional

# X11 and Wayland respectively. Either one means a window can be shown.
_DISPLAY_ENV_VARS = ("DISPLAY", "WAYLAND_DISPLAY")

VISIBLE_BROWSER_UNAVAILABLE = (
    "Browser auth needs a visible browser window for MFA/SSO, but this host has "
    "no display server (no DISPLAY or WAYLAND_DISPLAY). Run the MCP server on the "
    "machine where you log in, or switch to a non-interactive auth type "
    "(SERVICENOW_AUTH_TYPE=basic | oauth | api_key)."
)


def _visible_browser_unavailable_reason() -> Optional[str]:
    """Return why a visible browser can't be shown here, or None if it can."""
    if not sys.platform.startswith("linux"):
        return None  # macOS / Windows always have a window server
    if any(os.environ.get(var) for var in _DISPLAY_ENV_VARS):
        return None
    return VISIBLE_BROWSER_UNAVAILABLE
