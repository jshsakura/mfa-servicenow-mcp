"""The three tools behind the shared debug window.

The split is by side effect rather than by verb:

``open_debug_window``   the only tool that can put a window on the user's screen
``inspect_debug_window`` reads whatever window is already there, or reports none
``act_in_debug_window``  drives that window — clicks, types, waits

That asymmetry is the design. A read tool that opens windows on demand means a
window appears every time the model wants to check something, so inspecting and
acting both use ``find_window`` (never launches) while opening uses
``ensure_window`` (idempotent, rate-capped). Everything else — session
isolation, the launch claim, the unsaved-input guard, the single auto-login
attempt — lives in servicenow_mcp.browser as deterministic code rather than as
instructions the model is asked to follow.

Acting is classified as a WRITE (write_guards.MUTATING_TOOL_NAMES), because a
click on Save in an authenticated session creates a record just as surely as
the Table API would. The window's session is its own, so that write is
attributed to whoever the window is signed in as — which is exactly why
inspect reports that user back.

Running JavaScript is graded in two, because "read a value off the page" and
"run a script in someone's session" are not the same request:

``inspect_debug_window(evaluate=...)``  one EXPRESSION, value returned. A
    statement body is a parse error, not a silent success. It cannot be
    promised side-effect-free (``fetch(...)`` is an expression), so the
    argument itself flips the call to a write for the allow_writes gate —
    see write_guards.ARG_TRIGGERED_WRITE_ARGS.
``act_in_debug_window`` action ``eval``  arbitrary source, and therefore
    confirm='approve' AND confirm_eval='approve'.

Running SERVER-side code is not graded above both — it is off, and it is the one
capability in this repo that is refused rather than priced. ``open_debug_window``
will not point the window at Background Scripts, a Fix Script, a scheduled job or
an ATF run at all, and there is no approval argument that changes it
(_script_surface_refusal). The platform keeps those pages for a person who
genuinely needs one; whether a tool may steer there is a different question.

The older gates stay behind that block, for the window a person navigated by
hand: confirm_script_exec='approve' on the verb a step names, checked here before
the browser is touched, and in actions.py against the window's live URL — the
only place a click that lands on a runner mid-batch can be caught.

Impersonation is a step, not a tool, for the same reason: testing "what does
this user see" is never one call. It changes the whole window's session — which
every MCP session and the person watching the screen share — so both tools
report who the window is afterwards, and open_debug_window says so on the way in
when it reuses a window someone left impersonating. See browser/impersonate.py.

One window per ACCOUNT, and every instance that account can reach lives in it as
a tab (window.py::_window_key). So three things this module does are about
whose tab is whose rather than about the window: a tab on another configured
instance is never read, driven or navigated away from; a reused window with no
tab on this instance gets one opened beside the others; and ``reset`` clears one
instance's session out of the shared jar, never the window's.

Closing is not a tool: the user closes the window with the mouse, and a closed
window is simply reopened on the next explicit request.
"""

import logging
import os
import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..browser import server_scripts
from ..browser._launch_lock import LaunchBusy
from ..browser._offload import PlaywrightUnavailable
from ..browser.actions import EVAL_ACTION, MAX_ACTIONS, act, normalize
from ..browser.artifacts import prune as prune_artifacts
from ..browser.badge import profile_label
from ..browser.capture import MAX_WATCH_SECONDS, NoPageFound, arm, capture, navigate
from ..browser.cursor import resolve_marks, write_mark
from ..browser.impersonate import END_IMPERSONATION_ACTION, IMPERSONATE_ACTION, clear_marker
from ..browser.impersonate import describe_detected as describe_impersonation
from ..browser.impersonate import read_marker
from ..browser.launch_budget import LaunchBudgetExceeded, budget_status
from ..browser.login import auto_login
from ..browser.login import describe as describe_login
from ..browser.login import saved_credentials
from ..browser.reaper import reap_idle_windows
from ..browser.report import compact
from ..browser.reset import reset_session
from ..browser.server_scripts import ServerScriptBlocked, navigation_rejection, surface_for_url
from ..browser.session import api_username, describe_window_user
from ..browser.window import (
    ensure_window,
    find_window,
    window_artifacts_dir,
    window_cursor_path,
    window_history_path,
    window_impersonation_path,
    window_login_path,
)
from ..utils.config import ServerConfig
from ..utils.registry import register_tool

logger = logging.getLogger(__name__)

SCREENSHOT_MODES = ("none", "viewport", "full", "element")

# The second approval for the eval action. Same shape as the publish-class
# double confirm in write_guards: one flag for "this is a write", a separate
# one for "this specific write is the dangerous kind".
CONFIRM_EVAL_VALUE = "approve"

# Enough selectors to compare a broken element against its parent and a sibling
# without turning the response into a stylesheet.
MAX_STYLE_SELECTORS = 5


def _numbered(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Steps with their 1-based position, so a rejection can name which one."""
    return [{**step, "step": index} for index, step in enumerate(steps, start=1)]


def _script_surface_refusal(target_url: str) -> Optional[Dict[str, Any]]:
    """Refuse to point the window at a server-script runner. No approval argument.

    A wall, not a door, and that is deliberate here — the one place in this
    repo where the usual "gate it, never block it" rule does not apply, on the
    maintainer's instruction. The rule buys something specific: the person
    watching the screen sees the thing before it happens, in cases where they
    might reasonably say yes. Here they would not. Background Scripts via MCP is
    off, not expensive; the platform keeps the page for a human who really needs
    it, which is a different question from whether a tool may drive there.

    So there is no approval field to fill in. A gate whose answer is always no
    is just a prompt the model learns to answer for itself, and meanwhile the
    window has already moved onto the runner.

    Checked before anything opens or moves. This does not touch the window a
    person is driving by hand: they can navigate wherever they like.
    """
    if not target_url:
        return None
    surface = surface_for_url(target_url)
    if not surface:
        return None
    return {
        "success": False,
        "error": navigation_rejection(surface, url=target_url),
        "script_exec_surface": surface,
    }


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
    new_tab: bool = Field(
        default=False,
        description="Open in a new tab, leaving the current page untouched.",
    )
    reset: bool = Field(
        default=False,
        description="Sign this instance out first: cookies, storage, tabs. Needs confirm_reset.",
    )
    confirm_reset: Optional[str] = Field(
        default=None, description="Required ('approve') when reset=true."
    )


class DebugAction(BaseModel):
    """One step. The enum below is the whole vocabulary.

    ``eval`` is in it, and it is the only member that is not a thing a person
    could do with a mouse — which is why it costs a second approval
    (``confirm_eval``) on top of the tool's own confirm.

    ``impersonate`` / ``end_impersonation`` are things a person does with the
    mouse (the avatar menu), and they are steps for the same reason the rest
    are: "be that user, open the page, click Save" is one intention. They reload
    the current page in place — see browser/impersonate.py.
    """

    action: Literal[
        "click",
        "double_click",
        "fill",
        "select",
        "check",
        "uncheck",
        "hover",
        "press",
        "scroll_to",
        "wait_for",
        "wait",
        "eval",
        "impersonate",
        "end_impersonation",
    ]
    selector: Optional[str] = Field(
        default=None, description="CSS, text=..., or xpath=... Frames are searched too."
    )
    value: Optional[str] = Field(
        default=None,
        description="fill text, select option, eval JS, or who to impersonate (name works).",
    )
    key: Optional[str] = Field(default=None, description="Key for press, e.g. Enter.")
    ms: Optional[int] = Field(default=None, description="Pause length for action='wait'.")
    timeout_ms: Optional[int] = Field(default=None, description="Per-step timeout. Default 10000.")
    state: Optional[str] = Field(
        default=None, description="For wait_for: visible (default) or hidden."
    )


class ActInDebugWindowParams(BaseModel):
    actions: List[DebugAction] = Field(
        description="Steps in order. Stops at the first failure and reports it."
    )
    settle_ms: int = Field(
        default=500, description="Pause after the last step so the page can react."
    )
    screenshot: str = Field(
        default="none",
        description=(
            "none | viewport | full | element. full can come back as one screen — "
            "the reply says why."
        ),
    )
    selector: Optional[str] = Field(
        default=None, description="CSS selector for screenshot='element'."
    )
    since_last: bool = Field(default=True, description="Only events newer than the last read.")
    confirm_eval: Optional[str] = Field(
        default=None, description="Required ('approve') when any step is action='eval'."
    )
    confirm_script_exec: Optional[str] = Field(
        default=None,
        description="Required ('approve') to run a server-side script (Background/Fix/ATF).",
    )
    discard_unsaved_input: bool = Field(
        default=False,
        description="Allow impersonate/end_impersonation to reload a form holding input.",
    )


class InspectDebugWindowParams(BaseModel):
    watch_seconds: float = Field(
        default=0,
        description="Record while the user clicks. 0 reads what already happened.",
    )
    screenshot: str = Field(
        default="none",
        # Over the 80-char target on purpose. `full` is the one value here that
        # can quietly not do what its name says: the page's scroller is often a
        # component in a shadow root, which cannot be driven, so the capture
        # falls back to one screen. The reply carries the reason (`only_viewport`
        # / `truncated`) — this is the line that stops it being a surprise.
        description=(
            "none | viewport | full | element (needs selector). "
            "full can come back as one screen — the reply says why."
        ),
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
    evaluate: Optional[str] = Field(
        default=None,
        description="A JS expression to read from the page. Statements need act's eval.",
    )
    confirm_script_exec: Optional[str] = Field(
        default=None,
        description="Required ('approve') when evaluate posts to a server-script endpoint.",
    )


def _resolve_url(config: ServerConfig, url: Optional[str]) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    base = str(config.instance_url or "").rstrip("/")
    return f"{base}/{url.lstrip('/')}" if base else url


def _window_account(config: ServerConfig, auth_manager: AuthManager, state: Any) -> str:
    """The user this window SIGNED IN as — not necessarily who it is right now.

    The badge draws anyone else as an impersonation, so this has to be the real
    account: while impersonating, the page itself no longer knows it. The marker
    holds the answer it read before the switch; the configured browser login is
    the answer for a window nobody has impersonated in. An OAuth or API-key
    profile has neither, and the badge simply names whoever is signed in.
    """
    marker = read_marker(window_impersonation_path(auth_manager), state.started_at)
    if marker and marker.get("original"):
        return str(marker["original"])
    return (saved_credentials(config) or ("", ""))[0]


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

    # Checked before the window is opened or moved. See _script_surface_refusal:
    # this one is a block rather than a gate, and it is the only one.
    landing = _script_surface_refusal(target_url)
    if landing:
        return landing

    # A gate, not a wall: resetting is a thing people legitimately want before a
    # test, and it is also the one option here that destroys somebody else's
    # signed-in session in a window they are looking at. So it costs a second
    # approval and nothing more. Checked before the window is touched.
    if params.reset and str(params.confirm_reset or "").strip().lower() != CONFIRM_EVAL_VALUE:
        return {
            "success": False,
            "error": (
                "reset=true signs this instance out of the shared window — its cookies, "
                "web storage and tabs — and the person watching loses their session with "
                f"it. That needs confirm_reset='{CONFIRM_EVAL_VALUE}'. Other instances' "
                "tabs in the same window are not touched."
            ),
        }
    if params.reset and not str(config.instance_url or "").strip():
        return {
            "success": False,
            "error": (
                "reset=true needs a configured instance_url: with no host to scope by, "
                "the only reset available would clear every session in the window."
            ),
        }

    # Before the population grows, retire whatever is provably unused. Never
    # fatal: an unusable reaper must not stand between the user and a window.
    try:
        retired = reap_idle_windows(auth_manager)
    except Exception as exc:  # noqa: BLE001 - housekeeping, not the job
        logger.debug("Could not reap idle debug windows: %s", exc)
        retired = []

    # Reported on EVERY path, including the failures: a window that vanished
    # from the user's screen has to be accounted for even when the call that
    # retired it then went on to fail.
    housekeeping: Dict[str, Any] = {"closed_idle_windows": retired} if retired else {}

    try:
        state, opened = ensure_window(
            auth_manager,
            url=target_url,
            viewport=(max(320, params.width), max(240, params.height)),
        )
    except (LaunchBudgetExceeded, LaunchBusy) as exc:
        return {"success": False, "error": str(exc), **housekeeping}
    except PlaywrightUnavailable as exc:
        return {"success": False, "error": str(exc), **housekeeping}
    except (RuntimeError, TimeoutError, OSError) as exc:
        logger.warning("Could not open the debug window: %s", exc)
        return {"success": False, "error": str(exc), **housekeeping}

    result: Dict[str, Any] = {
        "success": True,
        "opened": opened,
        "reused": not opened,
        **_window_identity(state, config),
        **housekeeping,
    }

    # The badge shows the PROFILE and the account, not the address — the
    # address bar is directly above it. See browser/badge.py.
    profile = profile_label(config)
    account = _window_account(config, auth_manager, state)

    # Before anything is navigated or armed: the point of a reset is that what
    # comes after it starts from nothing.
    if params.reset and not opened:
        try:
            wiped = reset_session(
                state,
                landing_url=str(config.instance_url or "").rstrip("/") + "/",
                allow_discard=params.discard_unsaved_input,
            )
        except (PlaywrightUnavailable, RuntimeError, TimeoutError, OSError) as exc:
            # A reset that did not happen must never be reported as one — the
            # caller is about to run a test on the state it claims to have made.
            return {
                **result,
                "success": False,
                "reset": False,
                "error": f"The reset failed: {exc}",
            }
        if not wiped.get("reset"):
            return {**result, "success": False, **wiped}
        # The marker describes a session that no longer exists. Cleared here
        # rather than inside reset_session, which knows about pages and cookies
        # and deliberately not about where this window keeps its files.
        clear_marker(window_impersonation_path(auth_manager))
        # The badge compares against the account this window signed in as, and
        # the marker it was reading a moment ago is now describing a session
        # that was just cleared.
        account = (saved_credentials(config) or ("", ""))[0]
        result["reset"] = {
            key: wiped[key]
            for key in (
                "closed_tabs",
                "cookies_cleared",
                "cookies_kept",
                "cookies_note",
                "storage_cleared",
                "cache_cleared",
            )
            if key in wiped
        }
        result["url"] = wiped.get("url")
        result["reset_note"] = (
            "This instance is signed out; other instances' tabs in this window kept "
            "their sessions. The HTTP cache is per-browser and was emptied for all of "
            "them. The one auto-login attempt is NOT given back — it is only ever spent "
            "by a password the server refused, and a reset does not make one correct."
        )
    elif params.reset:
        # A window that did not exist a moment ago has nothing to reset, and
        # saying "reset" about a fresh profile would be a claim nobody verified.
        result["reset"] = {"skipped": "the window was just opened, so it was already blank"}

    # A brand new window navigates via the command line; an existing one has to
    # be told, and that is where unsaved input can be destroyed.
    if target_url and not opened:
        try:
            moved = navigate(
                state,
                url=target_url,
                profile=profile,
                account=account,
                allow_discard=params.discard_unsaved_input,
                new_tab=params.new_tab,
            )
        except (NoPageFound, RuntimeError, TimeoutError) as exc:
            return {**result, "success": False, "error": str(exc)}
        if not moved.get("navigated"):
            # Only reachable now when a real keystroke was observed — a guess
            # opens a new tab instead of refusing (see capture.navigate).
            return {
                **result,
                "navigated": False,
                "url": moved.get("url"),
                "blocked_by_unsaved_input": moved.get("blocked_by_unsaved_input"),
                "input_basis": moved.get("input_basis"),
                "hint": (
                    "Someone typed in these fields. Use new_tab=true to open this "
                    "alongside without touching them, or discard_unsaved_input=true "
                    "to navigate anyway."
                ),
            }
        result["url"] = moved.get("url")
        if moved.get("new_tab"):
            result["new_tab"] = True
            result["tabs"] = moved.get("tabs")
        if moved.get("opened_beside_url"):
            # One window holds every instance this account can reach, so the tab
            # that was active is routinely another instance's — or the person's
            # own page. Never navigated away from; said, not silent.
            result["opened_beside"] = (
                f"Opened in a new tab: the active one was on {moved['opened_beside_url']}, "
                "not on this instance, and taking it over would end a session nobody "
                "asked to end."
            )
        # Said, never silent: a tab disappearing from the user's screen is
        # their tab, and a cap that gave up must not look like one that worked.
        for key in ("closed_tabs_note", "tabs_note"):
            if moved.get(key):
                result[key] = moved[key]
        if moved.get("kept_input"):
            # Said, not silent: a tab appeared that the caller did not ask for,
            # and the reason is fields that merely look edited.
            result["opened_beside"] = (
                f"Opened in a new tab rather than disturbing {len(moved['kept_input'])} "
                "field(s) that look filled in. No keystroke was observed in them, so "
                "this is probably a widget's own defaults — pass discard_unsaved_input="
                "true to reuse the tab instead."
            )
    elif target_url:
        result["url"] = target_url

    # Arm the collector NOW, not on the first inspect. Otherwise the submit
    # that caused the bug happens before anything is watching it.
    try:
        armed = arm(state, profile=profile, account=account)
        if not armed.get("armed") and not target_url and not opened and config.instance_url:
            # A reused window is shared across instances now, so "open the debug
            # window" for one of them can land on a window that has no tab HERE —
            # the person would be looking at another instance and nothing would
            # have happened. Give this instance a tab of its own, beside the
            # others rather than instead of them. Only when no url was asked for:
            # with one, the navigation above has already put a tab here.
            home = str(config.instance_url or "").rstrip("/") + "/"
            try:
                moved = navigate(state, url=home, profile=profile, account=account, new_tab=True)
                result["url"] = moved.get("url")
                result["opened_tab"] = (
                    "This window had no tab on this instance, so one was opened beside "
                    "the tabs already in it."
                )
                armed = arm(state, profile=profile, account=account)
            except (NoPageFound, RuntimeError, TimeoutError) as exc:
                logger.info("Could not give this instance a tab in the shared window: %s", exc)
        result["recording"] = bool(armed.get("armed"))
        if not armed.get("armed"):
            result["recording_note"] = (
                f"Not recording yet ({armed.get('reason')}). Open a page in the window; "
                "inspect_debug_window will arm it on the next call."
            )
    except (PlaywrightUnavailable, RuntimeError, TimeoutError, OSError) as exc:
        logger.info("Could not arm the debug collector yet: %s", exc)
        result["recording"] = False

    # Sign the window in with what the server already knows, once per window.
    # Runs after arming so the login round-trip is itself recorded, and after
    # navigation so the form it looks at is the one on the target page.
    #
    # ``driven_url`` is which tab that was. The window is shared with the person
    # using it, and their tabs are not places to type an instance password —
    # login.py fills the tab we pointed at the instance, or none at all.
    login = auto_login(
        state,
        credentials=saved_credentials(config),
        marker_path=window_login_path(auth_manager),
        driven_url=str(result.get("url") or ""),
    )
    # Only "no credentials configured" stays out of the response. The other two
    # quiet statuses — no form, no tab — used to be suppressed as "nothing
    # happened and nothing is wrong", which is what made a window that came up
    # signed out with no auto_login field at all impossible to diagnose: the
    # absence of the key read as "it did not need to run".
    if login.get("status") not in (None, "no_credentials"):
        result["auto_login"] = login.get("status")
    login_note = describe_login(login)

    used, allowance = budget_status(window_history_path(auth_manager))
    if used >= allowance - 1:
        result["launch_budget"] = f"{used}/{allowance} recent launches"

    # Reusing a window that someone left impersonating is the surprise this
    # feature could most easily cause — the page looks normal and every ACL is
    # somebody else's. Say it on the way in, not after the confusing result.
    marker = read_marker(window_impersonation_path(auth_manager), state.started_at)
    if marker:
        result["impersonating"] = {
            "as": marker.get("as"),
            "original": marker.get("original") or None,
        }
        result["impersonation_note"] = (
            f"This window is impersonating '{marker.get('as')}'. Use "
            "act_in_debug_window action='end_impersonation' to go back to "
            f"'{marker.get('original') or 'the signed-in account'}'."
        )

    if login_note:
        result["hint"] = login_note
    elif opened:
        result["hint"] = (
            "This window has its own ServiceNow session, so it may ask for login once. "
            "Sign in there; impersonating or logging out here cannot affect MCP API calls."
        )
    return result


@register_tool(
    name="inspect_debug_window",
    params=InspectDebugWindowParams,
    description="Read the shared debug window: console errors, XHR, duplicates, screenshot, CSS, JS expression. Never opens one.",
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

    # `fetch('/sys.scripts.do', {method:'POST'})` is an expression, so the read
    # tool can run a background script without ever loading its page. Same
    # approval as the act path — one gate, whichever door it comes through.
    if params.evaluate and not server_scripts.approved(params.confirm_script_exec):
        surface = server_scripts.surface_in_source(params.evaluate)
        if surface:
            return {
                "success": False,
                "error": server_scripts.rejection(surface),
                "script_exec_surface": surface,
            }

    state = find_window(auth_manager)
    if state is None:
        # Deliberately does NOT open one. See the module docstring.
        return {
            "success": False,
            "window_open": False,
            "error": "No debug window is open. Call open_debug_window first.",
        }

    cursor_path = window_cursor_path(auth_manager)
    marks = resolve_marks(cursor_path, since_last=params.since_last, explicit=params.after_seq)
    artifacts_dir = window_artifacts_dir(auth_manager)
    shot_path = (
        os.path.join(artifacts_dir, f"shot-{int(time.time() * 1000)}.png")
        if params.screenshot != "none"
        else ""
    )

    try:
        raw = capture(
            state,
            profile=profile_label(config),
            account=_window_account(config, auth_manager, state),
            marks=marks,
            watch_seconds=min(float(params.watch_seconds), MAX_WATCH_SECONDS),
            screenshot=params.screenshot,
            selector=params.selector,
            style_selectors=params.styles[:MAX_STYLE_SELECTORS],
            screenshot_path=shot_path,
            evaluate_expression=params.evaluate,
        )
    except (NoPageFound, PlaywrightUnavailable) as exc:
        return {"success": False, "window_open": True, "error": str(exc)}
    except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("Debug window inspection failed: %s", exc)
        return {"success": False, "window_open": True, "error": str(exc)}

    report = compact(raw, artifacts_dir=artifacts_dir)
    # After the write, so this call's own artifact is the newest and can never
    # be the one removed. Housekeeping — never fatal, and silent unless it did
    # something (see browser/artifacts.py).
    report.update(prune_artifacts(artifacts_dir))
    write_mark(cursor_path, report.get("tab_id", ""), report.get("next_seq", 0))

    identity = describe_window_user(raw.get("effective_user"), api_username(config))
    result: Dict[str, Any] = {
        "success": True,
        "window_open": True,
        **_window_identity(state, config),
        **report,
    }
    if identity.get("window_user"):
        result["window_user"] = identity["window_user"]

    # Someone else's impersonation is still this window's session: the batch
    # that started it may have run in another MCP session entirely, so a read
    # has to say so rather than let "why is this user denied?" be investigated
    # against the wrong account.
    impersonation = describe_impersonation(
        raw.get("effective_user"),
        read_marker(window_impersonation_path(auth_manager), state.started_at),
    )
    if impersonation:
        result["impersonating"] = impersonation

    if identity.get("note"):
        result["session_note"] = identity["note"]
    elif not identity.get("window_user"):
        result["session_note"] = (
            "Could not read a signed-in user from the page — the window may still "
            "need a login, or the page is not a ServiceNow UI."
        )

    if raw.get("evaluation"):
        result["evaluation"] = raw["evaluation"]

    if len(params.styles) > MAX_STYLE_SELECTORS:
        result["styles_omitted"] = len(params.styles) - MAX_STYLE_SELECTORS
    return result


@register_tool(
    name="act_in_debug_window",
    params=ActInDebugWindowParams,
    description="Drive the open debug window: click, fill, select, wait, eval, impersonate. Reports what steps caused.",
    serialization="raw_dict",
    return_type=dict,
)
def act_in_debug_window(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ActInDebugWindowParams,
) -> Dict[str, Any]:
    if params.screenshot not in SCREENSHOT_MODES:
        return {
            "success": False,
            "error": f"screenshot must be one of: {', '.join(SCREENSHOT_MODES)}.",
        }
    if params.screenshot == "element" and not params.selector:
        return {"success": False, "error": "screenshot='element' requires a selector."}

    try:
        steps = normalize([action.model_dump() for action in params.actions])
    except ValueError as exc:
        # Rejected before the browser is touched: a batch that would fail
        # halfway leaves the page in a state nobody planned.
        return {"success": False, "error": str(exc), "max_actions": MAX_ACTIONS}

    # Running code is a bigger ask than clicking, so it takes its own approval
    # on top of the tool's. The tool-level confirm means "drive the page"; this
    # one means "run this source, which can do anything the signed-in user can".
    eval_steps = [step["step"] for step in _numbered(steps) if step["action"] == EVAL_ACTION]
    if eval_steps and str(params.confirm_eval or "").strip().lower() != CONFIRM_EVAL_VALUE:
        return {
            "success": False,
            "error": (
                f"Step(s) {eval_steps} run arbitrary JavaScript in the signed-in window. "
                f"That needs confirm_eval='{CONFIRM_EVAL_VALUE}' in addition to confirm. "
                "Show the user the source first — it can do anything they can."
            ),
            "eval_steps": eval_steps,
        }

    # A click on Run in Background Scripts is not the same request as a click on
    # Save, and until now it cost the same. Caught here by the verb the step
    # names — which is the half that works when the run is invoked from a list
    # view and no script-runner page is ever loaded. The other half, the live
    # URL, is checked in actions.py where the URL is real.
    allow_server_script = server_scripts.approved(params.confirm_script_exec)
    if not allow_server_script:
        script_steps: List[int] = []
        surface = ""
        for step in _numbered(steps):
            hit = server_scripts.surface_for_step(step)
            if not hit and step["action"] == EVAL_ACTION:
                # An eval never loads the page: it posts to it.
                hit = server_scripts.surface_in_source(step["value"])
            if hit:
                script_steps.append(step["step"])
                surface = surface or hit
        if script_steps:
            return {
                "success": False,
                "error": server_scripts.rejection(surface, steps=script_steps),
                "script_exec_steps": script_steps,
            }

    state = find_window(auth_manager)
    if state is None:
        return {
            "success": False,
            "window_open": False,
            "error": "No debug window is open. Call open_debug_window first.",
        }

    cursor_path = window_cursor_path(auth_manager)
    marks = resolve_marks(cursor_path, since_last=params.since_last)
    artifacts_dir = window_artifacts_dir(auth_manager)
    shot_path = (
        os.path.join(artifacts_dir, f"shot-{int(time.time() * 1000)}.png")
        if params.screenshot != "none"
        else ""
    )

    try:
        raw = act(
            state,
            profile=profile_label(config),
            account=_window_account(config, auth_manager, state),
            actions=steps,
            marks=marks,
            settle_ms=params.settle_ms,
            screenshot=params.screenshot,
            selector=params.selector,
            screenshot_path=shot_path,
            session={
                # Everything the impersonation steps need, resolved here where
                # the config and the auth manager are — actions.py stays a page
                # driver that knows nothing about profiles.
                "marker_path": window_impersonation_path(auth_manager),
                "started_at": state.started_at,
                "instance_host": state.instance_host,
                "login_user": (saved_credentials(config) or ("", ""))[0],
                "allow_discard": params.discard_unsaved_input,
                # Where to make the switch from when the tab is off the instance
                # and a relative POST would go to somebody else's site. The
                # instance root, because it is the one URL every instance has —
                # a deeper page would be a guess about this customer's menu.
                "carrier_url": str(config.instance_url or "").rstrip("/") + "/",
            },
            allow_server_script=allow_server_script,
        )
    except ServerScriptBlocked as exc:
        # The window was already sitting on a script runner, so nothing ran —
        # not even the fill that would have typed the script in.
        return {
            "success": False,
            "window_open": True,
            "error": str(exc),
            "script_exec_surface": exc.surface,
        }
    except (NoPageFound, PlaywrightUnavailable) as exc:
        return {"success": False, "window_open": True, "error": str(exc)}
    except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("Driving the debug window failed: %s", exc)
        return {"success": False, "window_open": True, "error": str(exc)}

    report = compact(raw, artifacts_dir=artifacts_dir)
    # After the write, so this call's own artifact is the newest and can never
    # be the one removed. Housekeeping — never fatal, and silent unless it did
    # something (see browser/artifacts.py).
    report.update(prune_artifacts(artifacts_dir))
    write_mark(cursor_path, report.get("tab_id", ""), report.get("next_seq", 0))

    failed_step = raw.get("failed_step")
    result: Dict[str, Any] = {
        # A failed step is not a failed call: the report below is how the
        # caller finds out WHY the click missed.
        "success": failed_step is None,
        "window_open": True,
        **_window_identity(state, config),
        "steps": raw.get("steps", []),
        **report,
    }
    if failed_step is not None:
        result["failed_step"] = failed_step
        result["skipped_steps"] = raw.get("skipped", 0)
    if raw.get("dialogs"):
        # Accepted, not dismissed — see browser/actions.py. Always reported,
        # because "a confirm box appeared and was answered" changes what the
        # click actually did.
        result["dialogs"] = raw["dialogs"]

    # A session step changed WHO the window is, and one window is shared by
    # every MCP session and by the person watching it. Never let that be a
    # silent side effect of a batch.
    if any(step["action"] in (IMPERSONATE_ACTION, END_IMPERSONATION_ACTION) for step in steps):
        result["window_user"] = (raw.get("effective_user") or {}).get("user")
        # Short on purpose: window_user above already names the user, so this
        # only has to carry what the name alone does not say.
        result["session_note"] = (
            "Whole window, every MCP session, until end_impersonation. API calls unaffected."
        )
    return result


__all__ = [
    "ActInDebugWindowParams",
    "DebugAction",
    "InspectDebugWindowParams",
    "MAX_STYLE_SELECTORS",
    "OpenDebugWindowParams",
    "SCREENSHOT_MODES",
    "act_in_debug_window",
    "inspect_debug_window",
    "open_debug_window",
]
