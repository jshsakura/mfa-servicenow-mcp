"""Shared debug browser — a Chromium window the user and the LLM look at together.

The window is a plain OS process (Chromium launched with a remote debugging
port), NOT a Playwright-managed browser held open across tool calls. That
choice is deliberate:

- It survives between MCP tool calls, so the user can keep clicking while the
  LLM inspects the same live page.
- It uses its OWN profile directory, so it never contends for the login
  profile's Chromium ``SingletonLock`` (see ``auth/_browser_dom.py``). The auth
  path stays untouched — ``auth_manager.py`` is FROZEN.
- It signs in with its OWN ServiceNow session (see ``session.py``), so
  impersonating or logging out in the window cannot reach the API session the
  MCP tools use.
- Each tool call attaches over CDP, reads, and detaches. No Playwright object
  outlives a call, so there is no cross-call state to corrupt. History is not
  lost in the gaps because the page collects its own events (``probe.py``).

Read-only by design: navigate, observe, capture. Nothing here clicks or types.
An authenticated session is on the other side of that window, and driving it
from a tool would bypass every write guard in this repo.
"""

from ._launch_lock import LaunchBusy, launch_claim
from ._offload import PlaywrightUnavailable, run_off_loop
from .badge import badge_init_script, badge_label
from .launch_budget import LaunchBudgetExceeded, budget_status
from .probe import PROBE_SCRIPT, drain_script
from .session import EFFECTIVE_USER_SCRIPT, api_username, describe_window_user
from .window import (
    DEBUG_WINDOW_ALWAYS_HEADED,
    DEFAULT_VIEWPORT,
    WindowState,
    ensure_window,
    find_window,
    is_window_alive,
    launch_window,
    read_window_state,
    stop_window,
    window_profile_dir,
    window_state_path,
)

__all__ = [
    "DEBUG_WINDOW_ALWAYS_HEADED",
    "DEFAULT_VIEWPORT",
    "EFFECTIVE_USER_SCRIPT",
    "LaunchBudgetExceeded",
    "LaunchBusy",
    "PROBE_SCRIPT",
    "PlaywrightUnavailable",
    "WindowState",
    "api_username",
    "badge_init_script",
    "badge_label",
    "budget_status",
    "describe_window_user",
    "drain_script",
    "ensure_window",
    "find_window",
    "is_window_alive",
    "launch_claim",
    "launch_window",
    "read_window_state",
    "run_off_loop",
    "stop_window",
    "window_profile_dir",
    "window_state_path",
]
