"""Where per-process local state files live (download roots, xml dirs, write journal).

Mirrors AuthManager._get_cache_dir so two projects with separate
``SERVICENOW_BROWSER_USER_DATA_DIR`` values never see each other's state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_registered: Optional[str] = None


def register_state_dir(user_data_dir: Optional[str]) -> None:
    """Record the resolved BASE ``browser.user_data_dir`` (None clears it)."""
    global _registered
    _registered = os.path.abspath(os.path.expanduser(user_data_dir)) if user_data_dir else None


def state_dir() -> Path:
    """Registered base dir, else env SERVICENOW_BROWSER_USER_DATA_DIR, else the home default."""
    if _registered:
        return Path(_registered)
    env = os.getenv("SERVICENOW_BROWSER_USER_DATA_DIR")
    if env:
        return Path(os.path.abspath(os.path.expanduser(env)))
    return Path.home() / ".mfa_servicenow_mcp"
