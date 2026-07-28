"""The two tools behind the shared debug window.

Exactly two, and the split is by side effect rather than by verb:

``open_debug_window``   the only tool that can put a window on the user's screen
``inspect_debug_window`` reads whatever window is already there, or reports none

That asymmetry is the design. A read tool that opens windows on demand means a
window appears every time the model wants to check something, so inspecting
uses ``find_window`` (never launches) while opening uses ``ensure_window``
(idempotent, rate-capped). Everything else — session isolation, the launch
claim, the unsaved-input guard — lives in servicenow_mcp.browser as
deterministic code rather than as instructions the model is asked to follow.

Closing is not a tool: the user closes the window with the mouse, and a closed
window is simply reopened on the next explicit request.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..browser._launch_lock import LaunchBusy
from ..browser._offload import PlaywrightUnavailable
from ..browser.capture import MAX_WATCH_SECONDS, NoPageFound, arm, capture, navigate
from ..browser.cursor import resolve_after_seq, write_cursor
from ..browser.launch_budget import LaunchBudgetExceeded, budget_status
from ..browser.report import compact
from ..browser.session import api_username, describe_window_user
from ..browser.window import (
    ensure_window,
    find_window,
    window_artifacts_dir,
    window_cursor_path,
    window_history_path,
)
from ..utils.config import ServerConfig
from ..utils.registry import register_tool

logger = logging.getLogger(__name__)

SCREENSHOT_MODES = ("none", "viewport", "full", "element")

# Enough selectors to compare a broken element against its parent and a sibling
# without turning the response into a stylesheet.
MAX_STYLE_SELECTORS = 5


class OpenDebugWindowParams(BaseModel):
    url: Optional[str] = Field(
        default=None, description="Page to open. Relative paths resolve against the instance."
    )
    width: int = Field(default=1440, description="Window width in pixels.")
    height: int = Field(default=900, description="Window height in pixels.")
    discard_unsaved_input: bool = Field(
        default=False,
        description="Allow navigating away from a form with unsaved input.",
    )


class InspectDebugWindowParams(BaseModel):
    watch_seconds: float = Field(
        default=0,
        description="Record while the user clicks. 0 reads what already happened.",
    )
    screenshot: str = Field(
        default="none", description="none | viewport | full | element (needs selector)."
    )
    selector: Optional[str] = Field(
        default=None, description="CSS selector for screenshot='element'."
    )
    styles: List[str] = Field(
        default_factory=list,
        description="Selectors to report computed layout styles and box for.",
    )
    since_last: bool = Field(default=True, description="Only events newer than the last inspect.")
    after_seq: Optional[int] = Field(
        default=None, description="Read from this event sequence instead of the cursor."
    )


def _resolve_url(config: ServerConfig, url: Optional[str]) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    base = str(config.instance_url or "").rstrip("/")
    return f"{base}/{url.lstrip('/')}" if base else url


def _window_identity(state: Any, config: ServerConfig) -> Dict[str, Any]:
    """Always echo which window this is.

    Two instances mean two windows, and acting on the wrong one is the failure
    this repo guards against everywhere else. The on-screen badge answers it for
    the user; this answers it for the model.
    """
    return {"instance_target": state.instance_host or str(config.instance_url or "")}


@register_tool(
    name="open_debug_window",
    params=OpenDebugWindowParams,
    description="Open a visible browser window on the user's screen for shared debugging. Reuses an open one.",
    serialization="raw_dict",
    return_type=dict,
)
def open_debug_window(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: OpenDebugWindowParams,
) -> Dict[str, Any]:
    target_url = _resolve_url(config, params.url)

    try:
        state, opened = ensure_window(
            auth_manager,
            url=target_url,
            viewport=(max(320, params.width), max(240, params.height)),
        )
    except (LaunchBudgetExceeded, LaunchBusy) as exc:
        return {"success": False, "error": str(exc)}
    except PlaywrightUnavailable as exc:
        return {"success": False, "error": str(exc)}
    except (RuntimeError, TimeoutError, OSError) as exc:
        logger.warning("Could not open the debug window: %s", exc)
        return {"success": False, "error": str(exc)}

    result: Dict[str, Any] = {
        "success": True,
        "opened": opened,
        "reused": not opened,
        **_window_identity(state, config),
    }

    profile = str(config.instance_url or "")

    # A brand new window navigates via the command line; an existing one has to
    # be told, and that is where unsaved input can be destroyed.
    if target_url and not opened:
        try:
            moved = navigate(
                state,
                url=target_url,
                profile=profile,
                allow_discard=params.discard_unsaved_input,
            )
        except (NoPageFound, RuntimeError, TimeoutError) as exc:
            return {**result, "success": False, "error": str(exc)}
        if not moved.get("navigated"):
            return {
                **result,
                "navigated": False,
                "url": moved.get("url"),
                "blocked_by_unsaved_input": moved.get("blocked_by_unsaved_input"),
                "hint": "Fields have unsaved input. Re-run with discard_unsaved_input=true to navigate anyway.",
            }
        result["url"] = moved.get("url")
    elif target_url:
        result["url"] = target_url

    # Arm the collector NOW, not on the first inspect. Otherwise the submit
    # that caused the bug happens before anything is watching it.
    try:
        armed = arm(state, profile=profile)
        result["recording"] = bool(armed.get("armed"))
        if not armed.get("armed"):
            result["recording_note"] = (
                f"Not recording yet ({armed.get('reason')}). Open a page in the window; "
                "inspect_debug_window will arm it on the next call."
            )
    except (PlaywrightUnavailable, RuntimeError, TimeoutError, OSError) as exc:
        logger.info("Could not arm the debug collector yet: %s", exc)
        result["recording"] = False

    used, allowance = budget_status(window_history_path(auth_manager))
    if used >= allowance - 1:
        result["launch_budget"] = f"{used}/{allowance} recent launches"

    if opened:
        result["hint"] = (
            "This window has its own ServiceNow session, so it may ask for login once. "
            "Sign in there; impersonating or logging out here cannot affect MCP API calls."
        )
    return result


@register_tool(
    name="inspect_debug_window",
    params=InspectDebugWindowParams,
    description="Read the shared debug window: console errors, XHR, duplicate calls, screenshot, CSS. Never opens one.",
    serialization="raw_dict",
    return_type=dict,
)
def inspect_debug_window(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: InspectDebugWindowParams,
) -> Dict[str, Any]:
    if params.screenshot not in SCREENSHOT_MODES:
        return {
            "success": False,
            "error": f"screenshot must be one of: {', '.join(SCREENSHOT_MODES)}.",
        }
    if params.screenshot == "element" and not params.selector:
        return {"success": False, "error": "screenshot='element' requires a selector."}

    state = find_window(auth_manager)
    if state is None:
        # Deliberately does NOT open one. See the module docstring.
        return {
            "success": False,
            "window_open": False,
            "error": "No debug window is open. Call open_debug_window first.",
        }

    cursor_path = window_cursor_path(auth_manager)
    after_seq = resolve_after_seq(
        cursor_path, since_last=params.since_last, explicit=params.after_seq
    )
    artifacts_dir = window_artifacts_dir(auth_manager)
    shot_path = (
        os.path.join(artifacts_dir, f"shot-{int(time.time() * 1000)}.png")
        if params.screenshot != "none"
        else ""
    )

    try:
        raw = capture(
            state,
            profile=str(config.instance_url or ""),
            after_seq=after_seq,
            watch_seconds=min(float(params.watch_seconds), MAX_WATCH_SECONDS),
            screenshot=params.screenshot,
            selector=params.selector,
            style_selectors=params.styles[:MAX_STYLE_SELECTORS],
            screenshot_path=shot_path,
        )
    except (NoPageFound, PlaywrightUnavailable) as exc:
        return {"success": False, "window_open": True, "error": str(exc)}
    except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("Debug window inspection failed: %s", exc)
        return {"success": False, "window_open": True, "error": str(exc)}

    report = compact(raw, artifacts_dir=artifacts_dir)
    write_cursor(cursor_path, report.get("next_seq", 0))

    identity = describe_window_user(raw.get("effective_user"), api_username(config))
    result: Dict[str, Any] = {
        "success": True,
        "window_open": True,
        **_window_identity(state, config),
        **report,
    }
    if identity.get("window_user"):
        result["window_user"] = identity["window_user"]
    if identity.get("note"):
        result["session_note"] = identity["note"]
    elif not identity.get("window_user"):
        result["session_note"] = (
            "Could not read a signed-in user from the page — the window may still "
            "need a login, or the page is not a ServiceNow UI."
        )

    if len(params.styles) > MAX_STYLE_SELECTORS:
        result["styles_omitted"] = len(params.styles) - MAX_STYLE_SELECTORS
    return result


__all__ = [
    "InspectDebugWindowParams",
    "MAX_STYLE_SELECTORS",
    "OpenDebugWindowParams",
    "SCREENSHOT_MODES",
    "inspect_debug_window",
    "open_debug_window",
]
