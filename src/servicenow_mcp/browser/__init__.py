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

Observing and driving are separate modules, and that separation is the safety
story rather than a filing convention. ``capture.py`` reads and never clicks, so
the tool that inspects cannot change anything by accident. ``actions.py`` is the
only module that touches the page, ``login.py`` the only one that types a
credential — and the tool in front of actions.py is classified as a WRITE
(``write_guards.MUTATING_TOOL_NAMES``), because clicking Save in an
authenticated session creates a record exactly like the Table API would.

``evaluate.py`` is called by both and imports neither: an expression for the
read door, a script body for the write door. It is honest about being a size
cap and a parser, not a sandbox — read its docstring before extending it.
"""

from ._launch_lock import LaunchBusy, launch_claim
from ._offload import PlaywrightUnavailable, run_off_loop
from .actions import EVAL_ACTION, MAX_ACTIONS, SUPPORTED_ACTIONS, act, normalize
from .badge import badge_init_script, badge_label
from .evaluate import MAX_RESULT_CHARS, body_script, expression_script, run_in_page
from .launch_budget import LaunchBudgetExceeded, budget_status
from .login import auto_login, saved_credentials
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
    window_login_path,
    window_profile_dir,
    window_state_path,
)

__all__ = [
    "DEBUG_WINDOW_ALWAYS_HEADED",
    "DEFAULT_VIEWPORT",
    "EFFECTIVE_USER_SCRIPT",
    "EVAL_ACTION",
    "MAX_ACTIONS",
    "MAX_RESULT_CHARS",
    "LaunchBudgetExceeded",
    "LaunchBusy",
    "PROBE_SCRIPT",
    "PlaywrightUnavailable",
    "SUPPORTED_ACTIONS",
    "WindowState",
    "act",
    "api_username",
    "auto_login",
    "badge_init_script",
    "badge_label",
    "body_script",
    "budget_status",
    "expression_script",
    "describe_window_user",
    "drain_script",
    "ensure_window",
    "find_window",
    "is_window_alive",
    "launch_claim",
    "launch_window",
    "normalize",
    "read_window_state",
    "run_in_page",
    "run_off_loop",
    "saved_credentials",
    "stop_window",
    "window_login_path",
    "window_profile_dir",
    "window_state_path",
]
