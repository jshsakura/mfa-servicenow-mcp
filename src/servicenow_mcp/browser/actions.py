"""Drive the shared window: click, type, wait — a batch per attach.

Why a batch rather than one action per call
-------------------------------------------
"Fill the description, save, wait for the toast" is one intention. Sending it
as three tool calls costs three CDP attaches, three round-trips through the
model, and — worse — leaves the page half-driven if the model gets distracted
between steps. A list of steps executes in one attach, stops at the first
failure, and reports what got done.

The batch is also what makes the answer worth reading: the events the actions
caused are drained in the same attach, so a call returns "clicked Save; that
POST went out twice, 23ms apart" rather than a bare ok. Acting and observing
were always the same question.

Fail-fast, not best-effort
--------------------------
A step that fails stops the batch. Continuing would run "click Save" against a
page that never got the value it was supposed to save, and the report would
show a successful save of the wrong thing — the failure mode this feature
exists to catch, manufactured by the tool itself.

Frames
------
ServiceNow puts real forms inside ``gsft_main``, and login pages inside IdP
iframes. Every selector is resolved against the page AND its frames, in order,
so a caller never has to know which document an element lives in. Resolution is
polled rather than instant: after a click that navigates, the next element does
not exist yet, and waiting is what a person does.

Session steps
-------------
``impersonate`` and ``end_impersonation`` are steps rather than a separate tool
because becoming a user is never the point on its own — "be that user, open
this page, click Save, see whether the ACL bites" is one intention, and running
it as several tool calls is how the wrong user ends up being tested. They change
the whole window's session, which every MCP session shares; impersonate.py has
the details and holds the marker that lets any session end what another started.

Running server-side code
------------------------
A handful of pages in ServiceNow turn a click into arbitrary server-side
execution, and ``fill`` + ``click`` reaches them. Doing that is allowed — it is
just not something to arrive at sideways, so an unapproved batch stops rather
than runs: before the first step when the window is already sitting on such a
page, and again before each activating step, because a click can navigate onto
one mid-batch. Both checks read the LIVE ``page.url``, which is why they live
here and not in the tool layer: a pre-flight can only see where the window was.
``allow_server_script`` is the caller's approval arriving from there. See
server_scripts.py.

Dialogs
-------
A native ``confirm()`` blocks the page and would hang the batch. Playwright's
default is to dismiss it, which would silently cancel the very action that was
just requested — so dialogs are ACCEPTED and reported. The window is on the
user's screen and the click was explicit; pretending it did not happen is the
one option that helps nobody.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from ._offload import cdp_browser, require_playwright, run_off_loop
from .capture import (
    NoPageFound,
    _active_instance_page,
    _arm_tabs,
    _dirty_fields,
    _drain,
    _effective_user,
    _install_probe,
    _on_instance,
    _page_title,
    _screenshot,
    _set_activity,
    no_page_message,
)
from .evaluate import run_in_page
from .impersonate import END_IMPERSONATION_ACTION, IMPERSONATE_ACTION, become, restore
from .page_state import read_page_state
from .server_scripts import ACTIVATING_ACTIONS, ServerScriptBlocked
from .server_scripts import rejection as script_rejection
from .server_scripts import surface_for_url
from .snapshot import REF_PREFIX, as_selector
from .snapshot import take as take_snapshot
from .window import WindowState

logger = logging.getLogger(__name__)

# What one batch may contain. Long enough for a real form, short enough that a
# runaway plan cannot drive the user's browser for a minute unattended.
MAX_ACTIONS = 25

# Per-step budget: how long to wait for the element, and for the action itself.
# 5s, not 10: in one live Workflow Studio session ten misses each burned the full
# 10s (100s of 375s). An element that is coming shows up well inside 5s; one
# that is not gets the near matches below sooner. timeout_ms raises it per step.
DEFAULT_STEP_TIMEOUT_MS = 5_000
MAX_STEP_TIMEOUT_MS = 60_000

# An explicit pause between steps ("give the form a second to react"). Capped
# because sleeping is the one thing a step can do that nothing can interrupt.
MAX_WAIT_MS = 30_000

# Actions that need an element, mapped to the argument they additionally need.
ACTIONS_NEEDING_SELECTOR = frozenset(
    {
        "click",
        "double_click",
        "fill",
        "select",
        "check",
        "uncheck",
        "hover",
        "scroll_to",
        "wait_for",
        "drag",
    }
)
ACTIONS_NEEDING_VALUE = frozenset({"fill", "select", "type", "goto", "eval", IMPERSONATE_ACTION})

# Page-level moves. A document load outlasts the element budget, and doing it with
# eval (`location.href=...`, 215 times in one week of logs) tears down the context
# the eval is running in, which then reports a navigation that worked as a failure.
NAVIGATION_ACTIONS = frozenset({"goto", "reload"})
MIN_NAVIGATION_TIMEOUT_MS = 30_000

# Runs arbitrary JavaScript in the signed-in window. Gated by a second explicit
# approval at the tool layer (see browser_debug_tools.py) — the tool-level
# confirm covers "you are driving the page", this covers "you are running code".
EVAL_ACTION = "eval"

# The two steps that change WHO the window is rather than what the page shows.
# They are ordinary steps on purpose: "become this user, open that page, click
# Save, see the ACL error" is one intention, and splitting it across tool calls
# is how the model ends up testing the wrong user. See impersonate.py.
SESSION_ACTIONS = frozenset({IMPERSONATE_ACTION, END_IMPERSONATION_ACTION})

SUPPORTED_ACTIONS: Tuple[str, ...] = (
    "click",
    "double_click",
    "fill",
    "select",
    "check",
    "uncheck",
    "hover",
    "press",
    "type",
    "scroll_to",
    "drag",
    "wait_for",
    "wait",
    "goto",
    "reload",
    EVAL_ACTION,
    IMPERSONATE_ACTION,
    END_IMPERSONATION_ACTION,
)

_RESOLVE_POLL_S = 0.15


class _OnlyHidden(LookupError):
    """The selector matched, but no match is visible. Carries how many it matched."""

    def __init__(self, matched: int) -> None:
        super().__init__(str(matched))
        self.matched = matched


class _StaleRef(LookupError):
    """An ``aria-ref=`` the page no longer has: the snapshot it came from is older than the page."""


def _resolve_ref(page: Any, selector: str) -> Any:
    """The one element a ref names, looked up once.

    A ref is a pointer into a snapshot, not a description that a later page could
    come to match, so waiting for it only delays the answer. Asked of the page,
    never per frame: the `f1` in `f1e2` already says which frame.
    """
    try:
        matches = page.locator(selector)
        if matches.count():
            return matches.first
    except Exception as exc:  # noqa: BLE001 - "Invalid frame in aria-ref" and kin
        raise _StaleRef(selector) from exc
    raise _StaleRef(selector)


class ActionError(RuntimeError):
    """A step could not be carried out. Carries the step index for the report."""

    def __init__(
        self, message: str, *, index: int, near: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        super().__init__(message)
        self.index = index
        self.near = near or []


def _targets(page: Any) -> Sequence[Any]:
    targets: List[Any] = [page]
    try:
        for frame in page.frames:
            if frame is not page.main_frame:
                targets.append(frame)
    except Exception as exc:  # noqa: BLE001 - a detached frame is not fatal
        logger.debug("Could not enumerate frames: %s", exc)
    return targets


def _has(target: Any, selector: str) -> bool:
    try:
        return target.locator(selector).count() > 0
    except Exception:  # noqa: BLE001 - invalid selector for this engine, or torn-down frame
        return False


def _first_visible(target: Any, selector: str) -> Any:
    """The first VISIBLE match in this document, ``None`` if every match is hidden.

    Raises when visibility could not be read, which is not the same as hidden:
    the caller falls back to the plain first match rather than claim anything.
    Asked of Playwright as one filter rather than element by element, so no number
    of hidden copies in front of the visible one can hide it.
    """
    visible = target.locator(f"{selector} >> visible=true")
    return visible.first if visible.count() else None


def _any_visible(page: Any, selector: str, *, unreadable: bool) -> bool:
    """Whether a match is visible now.

    ``unreadable`` is the answer when visibility could not be read. A wait for
    visible passes False, so it keeps waiting and times out rather than report
    something it never saw; a wait for hidden passes True, for the same reason.
    """
    for target in _targets(page):
        if not _has(target, selector):
            continue
        try:
            if _first_visible(target, selector) is not None:
                return True
        except Exception:  # noqa: BLE001 - torn-down frame, or a selector engine quirk
            if unreadable:
                return True
    return False


def _resolve_locator(page: Any, selector: str, timeout_ms: int, *, need_visible: bool) -> Any:
    """The element a step should act on, waiting for it across page and frames.

    Portal pages keep hidden copies of the same markup (modals, inactive tabs), so
    "the first match" is routinely an element nobody can click. Taking it meant the
    step waited out its whole timeout on a hidden node while a visible one sat right
    there: 187 calls in one week of logs carried ``>> visible=true`` to get round it.

    Polling instead of ``wait_for_selector`` because that call is per-document:
    running it on every frame would multiply the timeout by the frame count,
    and running it only on the main frame would miss ``gsft_main`` entirely.

    Raises ``LookupError`` when nothing matches and :class:`_OnlyHidden` when
    everything that matches is hidden, because those need different fixes.
    """
    if selector.startswith(REF_PREFIX):
        return _resolve_ref(page, selector)
    deadline = time.time() + max(0.0, timeout_ms / 1000.0)
    hidden = 0
    while True:
        hidden = 0
        for target in _targets(page):
            if not _has(target, selector):
                continue
            matches = target.locator(selector)
            if not need_visible:
                return matches.first
            try:
                visible = _first_visible(target, selector)
            except Exception as exc:  # noqa: BLE001 - unknown is not hidden; do not guess
                logger.debug("Could not read visibility of %s: %s", selector, exc)
                return matches.first
            if visible is not None:
                return visible
            hidden += matches.count()
        if time.time() >= deadline:
            if hidden:
                raise _OnlyHidden(hidden)
            raise LookupError(selector)
        time.sleep(_RESOLVE_POLL_S)


# Actions that need the element to accept input; a disabled one never will.
_NEEDS_ENABLED = frozenset({"click", "double_click", "fill", "select", "check", "uncheck"})
# How long a found-but-disabled element gets to enable itself (a button that
# enables a beat after the last field is filled) before the step says why.
_ENABLE_GRACE_S = 1.5
_TEXT_IN_SELECTOR = re.compile(
    r"""(?:text(?:-is)?\s*=\s*|has-text\(\s*|text-is\(\s*)['"]?/?\^?\\?s?\*?([^'")/$>]+)"""
)
# `[aria-label*="History" i]` — an icon button's only name is often an attribute.
_ATTR_IN_SELECTOR = re.compile(r"""\[[\w-]+\s*[*^$~|]?=\s*['"]([^'"]+)['"]""")
# Where an icon button keeps its name. Text probes cannot see these.
_LABEL_ATTRS = ("aria-label", "title", "data-tooltip", "data-tooltip-content")
# Playwright's own reason, from the call log a failed action raises with.
_ACTION_REASONS = (
    ("not enabled", "it is disabled"),
    ("intercepts pointer events", "another element covers it"),
    ("not stable", "it is still moving (animating)"),
    ("outside of the viewport", "it is outside the viewport"),
    ("not visible", "it is not visible"),
)


def _stale_ref_message(selector: str) -> str:
    return (
        f"'{selector}' is not on the page any more: refs belong to the last snapshot, "
        "and the page has changed (or another session snapshotted) since. Nothing was done. "
        "Take inspect_debug_window(snapshot=...) again and use the new ref."
    )


def _reason_of(message: str) -> str:
    low = message.lower()
    for needle, said in _ACTION_REASONS:
        if needle in low:
            return said
    return ""


def _text_of_selector(selector: str) -> str:
    found = _TEXT_IN_SELECTOR.search(selector or "") or _ATTR_IN_SELECTOR.search(selector or "")
    if not found:
        return ""
    # A regex selector (/^\s*\[sc_request\]\s*$/) keeps only its literal text.
    text = re.sub(r"\\[sSdDwWb][*+?]?", " ", found.group(1)).replace("\\", "")
    return " ".join(text.split())


def near_matches(page: Any, selector: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Visible elements whose text resembles the selector's — what to click instead.

    A miss used to come back as "no element matched", and the next call was a
    DOM-walking evaluate to find out what WAS there. The page already knows.
    Never raises; [] when the selector carries no text or nothing resembles it.
    """
    text = _text_of_selector(selector)
    if not text:
        return []
    words = [w for w in re.split(r"\s+", text) if len(w) >= 2]
    probes = [text] + sorted(set(words) - {text}, key=len, reverse=True)[:2]
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for probe in probes:
        quoted = probe.replace('"', '\\"')
        by_attr = ", ".join(f'[{a}*="{quoted}" i]' for a in _LABEL_ATTRS)
        for target in _targets(page):
            for kind in ("text", "attr"):
                try:
                    found = target.get_by_text(probe) if kind == "text" else target.locator(by_attr)
                    count = min(found.count(), 20)
                except Exception:  # noqa: BLE001 - a detached frame is simply skipped
                    continue
                for i in range(count):
                    item = _near_item(found.nth(i))
                    if not item or item["text"] in seen:
                        continue
                    seen.add(item["text"])
                    out.append(item)
                    if len(out) >= limit:
                        return out
        if out:
            return out
    return out


def _near_item(el: Any) -> Optional[Dict[str, Any]]:
    """One visible candidate as {text, tag, enabled}, named the way a selector can reach it."""
    try:
        if not el.is_visible():
            return None
        text = " ".join(el.inner_text(timeout=300).split())[:60]
        attr = ""
        for name in _LABEL_ATTRS:
            value = el.get_attribute(name, timeout=300)
            if value:
                attr = f'[{name}="{" ".join(value.split())[:60]}"]'
                break
        if not text and not attr:
            return None
        item: Dict[str, Any] = {
            "text": text or attr,
            "tag": str(el.evaluate("e => e.tagName.toLowerCase()")),
            "enabled": bool(el.is_enabled()),
        }
        if text and attr:
            item["attr"] = attr
        return item
    except Exception:  # noqa: BLE001
        return None


def _wait_enabled(locator: Any) -> bool:
    deadline = time.time() + _ENABLE_GRACE_S
    while True:
        try:
            if locator.is_enabled():
                return True
        except Exception:  # noqa: BLE001 - unreadable is not "disabled"; let the action try
            return True
        if time.time() >= deadline:
            return False
        time.sleep(_RESOLVE_POLL_S)


# Where on the drop target the pointer is released, as a fraction of its height.
# Editors that insert by position (a step list) read above/below from the pointer.
_DROP_AT = {"top": 0.15, "center": 0.5, "bottom": 0.85}
# Moves between press and release. Drag libraries start a drag only after the
# pointer has travelled a few pixels, and some track pointermove rather than
# the end point, so one jump from source to target never registers.
_DRAG_MOVES = 12


def _drag(page: Any, source: Any, target: Any, at: str, timeout_ms: int) -> Dict[str, Any]:
    """Press on ``source``, move in steps, release on ``target``: a person's drag.

    Raw mouse events rather than ``drag_to``: they are what a person produces, so
    HTML5 drag-and-drop and pointer-driven editors both see a real drag.
    """
    source.scroll_into_view_if_needed(timeout=timeout_ms)
    src = source.bounding_box()
    dst = target.bounding_box()
    if not src or not dst:
        raise RuntimeError("element is not visible (no bounding box)")
    sx, sy = src["x"] + src["width"] / 2, src["y"] + src["height"] / 2
    tx, ty = dst["x"] + dst["width"] / 2, dst["y"] + dst["height"] * _DROP_AT[at]
    mouse = page.mouse
    mouse.move(sx, sy)
    mouse.down()
    mouse.move(sx + 6, sy + 6, steps=3)
    mouse.move(tx, ty, steps=_DRAG_MOVES)
    time.sleep(0.2)  # the drop zone highlights on hover; release onto it, not before
    mouse.move(tx, ty + 1)
    mouse.up()
    return {"dropped_at": at}


def _same_instance_url(page: Any, destination: str, instance_host: str) -> str:
    """Resolve a goto target. It stays on this instance; other hosts have their own tab."""
    # Python reads `https://evil.example\\@host/` as host; a browser reads `\\` as `/`,
    # which makes it evil.example. Refused rather than resolved one way.
    if "\\" in destination or any(ord(char) < 32 for char in destination):
        raise ValueError(f"goto cannot use {destination!r}: backslash or control character.")
    base = _page_url(page)
    if not urlparse(base).hostname and instance_host:
        base = f"https://{instance_host}/"
    resolved = urljoin(base, destination)
    parsed = urlparse(resolved)
    current = (instance_host or urlparse(base).hostname or "").lower()
    # With no host to compare against, "matches" would mean nothing: refused.
    if (
        not current
        or parsed.scheme not in ("http", "https")
        or (parsed.hostname or "").lower() != current
    ):
        raise ValueError(
            f"goto stays on {current or 'this instance'}, and '{destination}' does not. "
            "Use open_debug_window for a page on another instance."
        )
    return resolved


def normalize(raw_actions: Sequence[Any]) -> List[Dict[str, Any]]:
    """Validate the batch before touching the browser.

    Every rejection here is one the model can fix without having driven the
    page halfway first, which is why validation is a separate pass rather than
    a check inside the loop.
    """
    if not raw_actions:
        raise ValueError("No actions given. Pass at least one action.")
    if len(raw_actions) > MAX_ACTIONS:
        raise ValueError(f"Too many actions ({len(raw_actions)}). The limit is {MAX_ACTIONS}.")

    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_actions, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Action {index} must be an object, got {type(raw).__name__}.")
        name = str(raw.get("action") or "").strip().lower()
        if name not in SUPPORTED_ACTIONS:
            raise ValueError(
                f"Action {index}: unknown action '{name or '(missing)'}'. "
                f"Supported: {', '.join(SUPPORTED_ACTIONS)}."
            )
        selector = raw.get("selector")
        if name in ACTIONS_NEEDING_SELECTOR and not selector:
            raise ValueError(f"Action {index} ('{name}') needs a selector.")
        if name in ACTIONS_NEEDING_VALUE and raw.get("value") is None:
            raise ValueError(f"Action {index} ('{name}') needs a value.")
        if name == "press" and not raw.get("key"):
            raise ValueError(f"Action {index} ('press') needs a key, e.g. 'Enter'.")
        if name == "drag" and not raw.get("to"):
            raise ValueError(f"Action {index} ('drag') needs `to`: the selector to drop on.")
        if name == "drag" and str(raw.get("value") or "center") not in _DROP_AT:
            raise ValueError(
                f"Action {index} ('drag'): value is where on `to` to drop — "
                f"{', '.join(_DROP_AT)}."
            )

        timeout_ms = int(raw.get("timeout_ms") or DEFAULT_STEP_TIMEOUT_MS)
        normalized.append(
            {
                "action": name,
                "selector": (as_selector(str(selector)) if selector else None),
                "value": (None if raw.get("value") is None else str(raw.get("value"))),
                "key": (str(raw["key"]) if raw.get("key") else None),
                "ms": max(0, min(int(raw.get("ms") or 0), MAX_WAIT_MS)),
                "timeout_ms": max(100, min(timeout_ms, MAX_STEP_TIMEOUT_MS)),
                "state": str(raw.get("state") or "visible"),
                "to": (as_selector(str(raw["to"])) if raw.get("to") else None),
            }
        )
    return normalized


def budget_seconds(actions: Sequence[Dict[str, Any]]) -> float:
    """Wall-clock the whole batch may take, for the offload timeout.

    A session step is counted twice: it reloads the page AND then waits for the
    globals to report the new user, so one timeout does not cover it.
    """
    total = sum(step["timeout_ms"] + step["ms"] for step in actions)
    total += sum(step["timeout_ms"] for step in actions if step["action"] in SESSION_ACTIONS)
    total += sum(
        MIN_NAVIGATION_TIMEOUT_MS for step in actions if step["action"] in NAVIGATION_ACTIONS
    )
    return total / 1000.0 + 60.0


def _page_url(page: Any) -> str:
    """The window's current address, or '' if it cannot be read.

    Never raises: an unreadable URL must not turn a legitimate click into an
    error. It only means this half of the script-runner check abstains — the
    verb half, checked at the tool layer, still applies.
    """
    try:
        return str(page.url)
    except Exception as exc:  # noqa: BLE001 - a torn-down page has no url
        logger.debug("Could not read the page URL: %s", exc)
        return ""


def _run_step(
    page: Any,
    step: Dict[str, Any],
    index: int,
    session: Optional[Dict[str, Any]] = None,
    allow_server_script: bool = False,
) -> Dict[str, Any]:
    """Execute one step. Raises :class:`ActionError` with a usable message.

    ``session`` carries what the impersonation steps need and nothing else: the
    marker path, the window's ``started_at`` that keys it, and the account the
    window signed in as. Absent (the default) those steps report that they were
    not wired up rather than guessing at a path.

    ``allow_server_script`` is the second approval, already checked at the tool
    layer. Without it, an activating step on a script-runner page fails HERE
    rather than in a pre-flight, because only here is the URL the real one.
    """
    name = step["action"]
    selector = step["selector"]
    timeout_ms = step["timeout_ms"]
    context = session or {}

    if not allow_server_script and name in ACTIVATING_ACTIONS:
        surface = surface_for_url(_page_url(page))
        if surface:
            raise ActionError(script_rejection(surface, steps=index), index=index)

    if name == "wait":
        time.sleep(step["ms"] / 1000.0)
        return {"waited_ms": step["ms"]}

    if name in SESSION_ACTIONS:
        common = {
            "marker_path": str(context.get("marker_path") or ""),
            "started_at": float(context.get("started_at") or 0.0),
            "instance_host": str(context.get("instance_host") or ""),
            "allow_discard": bool(context.get("allow_discard")),
            "carrier_url": str(context.get("carrier_url") or ""),
            "timeout_ms": timeout_ms,
        }
        login_user = str(context.get("login_user") or "")
        if name == IMPERSONATE_ACTION:
            outcome = become(page, target=step["value"] or "", login_user=login_user, **common)
        else:
            outcome = restore(page, fallback_user=login_user, **common)
        if not outcome.get("ok"):
            raise ActionError(str(outcome.get("error")), index=index)
        if name == IMPERSONATE_ACTION:
            entry = {"impersonating": outcome.get("now"), "was": outcome.get("before")}
            # Only when the caller's word was not the account's — mapping the
            # display name the caller typed to the account it resolved to is the
            # answer to the next question.
            if outcome.get("resolved"):
                entry["resolved"] = outcome["resolved"]
            return entry
        return {"restored_to": outcome.get("now")}

    if name == EVAL_ACTION:
        # Runs on the main frame. A script that needs a frame reaches it the
        # way a script does — through `frames`/`contentWindow` — rather than
        # through a selector this layer would have to guess at.
        outcome = run_in_page(page, body=step["value"] or "")
        if not outcome.get("ok"):
            error = str(outcome.get("error"))
            if "context was destroyed" in error:
                error += (
                    " The page navigated while this ran, so the navigation itself probably "
                    "worked. Use the goto or reload action to navigate."
                )
            raise ActionError(f"eval failed: {error}", index=index)
        return {"result": outcome}

    if name == "press" and not selector:
        try:
            page.keyboard.press(step["key"])
        except Exception as exc:  # noqa: BLE001
            raise ActionError(f"Could not press '{step['key']}': {exc}", index=index) from exc
        return {"key": step["key"]}

    if name == "goto" and not allow_server_script:
        try:
            surface = surface_for_url(
                _same_instance_url(
                    page, step["value"] or "", str(context.get("instance_host") or "")
                )
            )
        except ValueError as exc:
            raise ActionError(str(exc), index=index) from exc
        if surface:
            raise ActionError(script_rejection(surface, steps=index), index=index)

    if name in NAVIGATION_ACTIONS:
        # The same refusal open_debug_window and impersonate give: this is the
        # most expensive thing a step can throw away.
        if not context.get("allow_discard"):
            dirty, _ = _dirty_fields(page)
            if dirty:
                raise ActionError(
                    f"{name} would discard unsaved input in {', '.join(dirty[:5])}. "
                    "Pass discard_unsaved_input=true to go ahead.",
                    index=index,
                )
        limit = max(timeout_ms, MIN_NAVIGATION_TIMEOUT_MS)
        destination = ""
        try:
            if name == "goto":
                host = str(context.get("instance_host") or "")
                destination = _same_instance_url(page, step["value"] or "", host)
                page.goto(destination, wait_until="domcontentloaded", timeout=limit)
            else:
                page.reload(wait_until="domcontentloaded", timeout=limit)
        except Exception as exc:  # noqa: BLE001 - Playwright raises a wide family here
            raise ActionError(f"{name} failed: {str(exc)[:300]}", index=index) from exc
        landed = _page_url(page)
        # An expired session answers a goto with its login page, and the load itself
        # still succeeds. The step is reported, but it must not read as "you are there".
        if destination and urlparse(landed).path != urlparse(destination).path:
            return {"url": landed, "redirected_from": destination}
        return {"url": landed}

    if name == "type" and not selector:
        try:
            page.keyboard.type(step["value"] or "")
        except Exception as exc:  # noqa: BLE001
            raise ActionError(f"Could not type: {exc}", index=index) from exc
        return {}

    if name == "wait_for":
        deadline = time.time() + timeout_ms / 1000.0
        # hidden/visible ask about what the user can see, so a node that is in the
        # DOM but display:none is hidden. It used to count as visible, which made
        # "wait for the spinner to go" time out and "wait for the dialog" return
        # before anything was on screen. detached/attached ask about the DOM.
        by_dom = step["state"] in ("attached", "detached")
        want_hidden = step["state"] in ("hidden", "detached")
        while True:
            if by_dom:
                present = any(_has(target, selector) for target in _targets(page))
            else:
                # Unreadable never ends the wait: it counts as present for hidden and
                # as absent for visible, so neither reports what it did not see.
                present = _any_visible(page, selector, unreadable=want_hidden)
            if present != want_hidden:
                return {"state": step["state"]}
            if time.time() >= deadline:
                raise ActionError(
                    f"Timed out after {timeout_ms}ms waiting for '{selector}' "
                    f"to be {step['state']}.",
                    index=index,
                )
            time.sleep(_RESOLVE_POLL_S)

    try:
        # A key can go to a focused element nobody can see; the rest need one in view.
        locator = _resolve_locator(page, selector, timeout_ms, need_visible=name != "press")
    except _StaleRef as exc:
        raise ActionError(_stale_ref_message(selector), index=index) from exc
    except _OnlyHidden as exc:
        raise ActionError(
            f"'{selector}' matched {exc.matched} element(s) but none became visible within "
            f"{timeout_ms}ms (searched the page and every frame). Open what reveals it first "
            "(tab, modal, section).",
            index=index,
        ) from exc
    except LookupError as exc:
        raise ActionError(
            f"No element matched '{selector}' within {timeout_ms}ms "
            "(searched the page and every frame). snapshot='page' lists what is there, "
            "with refs to act on.",
            index=index,
            near=near_matches(page, selector),
        ) from exc

    if name in _NEEDS_ENABLED and not _wait_enabled(locator):
        # Found and visible but disabled: waiting out the timeout cannot help,
        # and the bare Playwright log hid the reason (cut at "enabled and st...").
        raise ActionError(
            f"'{selector}' is on the page but disabled — it enables when the page is "
            "ready for it (e.g. required fields filled). Nothing was clicked.",
            index=index,
        )

    if name == "drag":
        try:
            target = _resolve_locator(page, step["to"], timeout_ms, need_visible=True)
        except _StaleRef as exc:
            raise ActionError(_stale_ref_message(step["to"]), index=index) from exc
        except LookupError as exc:
            raise ActionError(
                f"drag: no drop target matched '{step['to']}' within {timeout_ms}ms. "
                "Nothing was moved.",
                index=index,
                near=near_matches(page, step["to"]),
            ) from exc
        try:
            return _drag(page, locator, target, step["value"] or "center", timeout_ms)
        except Exception as exc:  # noqa: BLE001
            raise ActionError(
                f"drag '{selector}' -> '{step['to']}' failed: {str(exc)[:200]}", index=index
            ) from exc

    try:
        if name == "click":
            locator.click(timeout=timeout_ms)
        elif name == "double_click":
            locator.dblclick(timeout=timeout_ms)
        elif name == "fill":
            locator.fill(step["value"], timeout=timeout_ms)
        elif name == "select":
            locator.select_option(step["value"], timeout=timeout_ms)
        elif name == "check":
            locator.check(timeout=timeout_ms)
        elif name == "uncheck":
            locator.uncheck(timeout=timeout_ms)
        elif name == "hover":
            locator.hover(timeout=timeout_ms)
        elif name == "press":
            locator.press(step["key"], timeout=timeout_ms)
        elif name == "type":
            locator.press_sequentially(step["value"], timeout=timeout_ms)
        elif name == "scroll_to":
            locator.scroll_into_view_if_needed(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - Playwright raises a wide family here
        reason = _reason_of(str(exc))
        raise ActionError(
            f"{name} on '{selector}' failed"
            + (f": {reason}" if reason else "")
            + f". {str(exc)[:200]}",
            index=index,
            near=near_matches(page, selector) if reason else None,
        ) from exc

    return {}


def act(
    state: WindowState,
    *,
    profile: str,
    account: str = "",
    actions: Sequence[Dict[str, Any]] = (),
    marks: Any = 0,
    settle_ms: int = 0,
    screenshot: str = "none",
    selector: Optional[str] = None,
    screenshot_path: str = "",
    session: Optional[Dict[str, Any]] = None,
    allow_server_script: bool = False,
    snapshot: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the batch, then drain what it caused. Same raw shape as capture().

    ``allow_server_script`` carries the caller's second approval for running
    server-side code; without it a batch that would do so is refused with
    :class:`ServerScriptBlocked` before any step runs.
    """
    require_playwright()
    steps = list(actions)
    settle_s = max(0, min(int(settle_ms), MAX_WAIT_MS)) / 1000.0

    def _work() -> Dict[str, Any]:
        with cdp_browser(state.cdp_endpoint) as browser:
            page = None
            try:
                contexts = browser.contexts
                if not contexts:
                    raise NoPageFound("The debug window has no browser context.")
                context = contexts[0]
                _arm_tabs(context.pages, state, profile, account)
                pick = _active_instance_page(context.pages, state)
                if pick is None:
                    raise NoPageFound(no_page_message(context.pages, state.instance_host))
                page = pick.page

                # open_debug_window opens a new tab in these two cases rather than take
                # the tab over. A batch has no second tab to go to, so it asks for one.
                if any(step["action"] in NAVIGATION_ACTIONS for step in steps) and (
                    pick.claimed_by_other or not _on_instance(page, state.instance_host)
                ):
                    raise NoPageFound(
                        "goto and reload would take over a tab that is not this session's. "
                        "Call open_debug_window with new_tab=true and a url, then retry."
                    )

                # The window may already be sitting on Background Scripts, in
                # which case the whole batch is refused rather than half-run:
                # nothing typed, nothing clicked, page left as the user had it.
                if not allow_server_script:
                    surface = surface_for_url(_page_url(page))
                    if surface and any(step["action"] in ACTIVATING_ACTIONS for step in steps):
                        raise ServerScriptBlocked(script_rejection(surface), surface=surface)

                # Re-arm first: a click that navigates must land on an
                # instrumented document, and add_init_script only affects
                # documents created after it is registered.
                _install_probe(context, page, state, profile, account)
                # Lit for the whole batch: this is the case where "was that me
                # or the model?" is asked most, because the page is moving.
                _set_activity(page, True)

                dialogs: List[Dict[str, Any]] = []

                def _on_dialog(dialog: Any) -> None:
                    entry: Dict[str, Any] = {
                        "type": str(dialog.type),
                        "message": str(dialog.message)[:200],
                    }
                    try:
                        dialog.accept()
                        entry["accepted"] = True
                    except Exception as exc:  # noqa: BLE001
                        entry["accepted"] = False
                        logger.debug("Could not accept dialog: %s", exc)
                    dialogs.append(entry)

                page.on("dialog", _on_dialog)

                results: List[Dict[str, Any]] = []
                failure: Optional[Dict[str, Any]] = None
                for index, step in enumerate(steps, start=1):
                    started = time.time()
                    entry: Dict[str, Any] = {
                        "step": index,
                        "action": step["action"],
                        "selector": step["selector"],
                    }
                    try:
                        entry.update(_run_step(page, step, index, session, allow_server_script))
                        entry["ok"] = True
                    except ActionError as exc:
                        entry["ok"] = False
                        entry["error"] = str(exc)
                        if exc.near:
                            entry["near_matches"] = exc.near
                        failure = entry
                    entry["ms"] = int((time.time() - started) * 1000)
                    results.append(entry)
                    if failure is not None:
                        break

                if settle_s:
                    # Let the page finish reacting before we read it — a save
                    # that fires its XHR 300ms later is the common case.
                    time.sleep(settle_s)

                try:
                    page.remove_listener("dialog", _on_dialog)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not detach the dialog listener: %s", exc)

                drained = _drain(page, marks)
                page_state = read_page_state(page)
                # The page as the steps left it, so the next batch can point at
                # what is there now without another round trip.
                outline = take_snapshot(page, snapshot) if snapshot else None
                shot, shot_note = _screenshot(
                    page, mode=screenshot, selector=selector, destination=screenshot_path
                )
                return {
                    "url": str(page.url),
                    "title": str(drained.get("title") or _page_title(page)),
                    "seq": int(drained.get("seq") or 0),
                    "tab_id": str(drained.get("tabId") or ""),
                    # Deliberately NOT pinned here. Driving a tab does not make
                    # it this session's: pinning one we merely landed on would
                    # turn a single collision into a standing claim on a page
                    # somebody else is working in. A tab becomes ours by being
                    # opened for us (capture.navigate) — this only reports.
                    "tab_is_mine": pick.mine,
                    "tab_claimed_by_other": pick.claimed_by_other,
                    "dropped": int(drained.get("dropped") or 0),
                    "events": list(drained.get("events") or []),
                    "styles": {},
                    "screenshot": shot,
                    "screenshot_note": shot_note,
                    "effective_user": _effective_user(page),
                    "watched_seconds": settle_s,
                    "events_unread": bool(drained.get("events_unread")),
                    "events_note": drained.get("events_note"),
                    "steps": results,
                    "page_state": page_state,
                    "snapshot": outline,
                    "dialogs": dialogs,
                    "failed_step": (failure["step"] if failure else None),
                    "skipped": max(0, len(steps) - len(results)),
                }
            finally:
                try:
                    if page is not None:
                        _set_activity(page, False)
                except Exception:  # noqa: BLE001 - page may be gone
                    pass

    return run_off_loop(_work, timeout_s=budget_seconds(steps) + settle_s)


__all__ = [
    "ACTIONS_NEEDING_SELECTOR",
    "ACTIONS_NEEDING_VALUE",
    "ACTIVATING_ACTIONS",
    "END_IMPERSONATION_ACTION",
    "EVAL_ACTION",
    "IMPERSONATE_ACTION",
    "SESSION_ACTIONS",
    "ActionError",
    "DEFAULT_STEP_TIMEOUT_MS",
    "MAX_ACTIONS",
    "MAX_STEP_TIMEOUT_MS",
    "MAX_WAIT_MS",
    "SUPPORTED_ACTIONS",
    "ServerScriptBlocked",
    "act",
    "budget_seconds",
    "normalize",
]
