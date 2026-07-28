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

Dialogs
-------
A native ``confirm()`` blocks the page and would hang the batch. Playwright's
default is to dismiss it, which would silently cancel the very action that was
just requested — so dialogs are ACCEPTED and reported. The window is on the
user's screen and the click was explicit; pretending it did not happen is the
one option that helps nobody.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ._offload import require_playwright, run_off_loop
from .capture import NoPageFound, _effective_user, _install_probe, _instance_page, _screenshot
from .probe import drain_script
from .window import WindowState

logger = logging.getLogger(__name__)

# What one batch may contain. Long enough for a real form, short enough that a
# runaway plan cannot drive the user's browser for a minute unattended.
MAX_ACTIONS = 25

# Per-step budget: how long to wait for the element, and for the action itself.
DEFAULT_STEP_TIMEOUT_MS = 10_000
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
    }
)
ACTIONS_NEEDING_VALUE = frozenset({"fill", "select"})

SUPPORTED_ACTIONS: Tuple[str, ...] = (
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
)

_RESOLVE_POLL_S = 0.15


class ActionError(RuntimeError):
    """A step could not be carried out. Carries the step index for the report."""

    def __init__(self, message: str, *, index: int) -> None:
        super().__init__(message)
        self.index = index


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


def _resolve_target(page: Any, selector: str, timeout_ms: int) -> Any:
    """The page or frame that contains ``selector``, waiting for it to appear.

    Polling instead of ``wait_for_selector`` because that call is per-document:
    running it on every frame would multiply the timeout by the frame count,
    and running it only on the main frame would miss ``gsft_main`` entirely.
    """
    deadline = time.time() + max(0.0, timeout_ms / 1000.0)
    while True:
        for target in _targets(page):
            if _has(target, selector):
                return target
        if time.time() >= deadline:
            raise LookupError(selector)
        time.sleep(_RESOLVE_POLL_S)


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

        timeout_ms = int(raw.get("timeout_ms") or DEFAULT_STEP_TIMEOUT_MS)
        normalized.append(
            {
                "action": name,
                "selector": (str(selector) if selector else None),
                "value": (None if raw.get("value") is None else str(raw.get("value"))),
                "key": (str(raw["key"]) if raw.get("key") else None),
                "ms": max(0, min(int(raw.get("ms") or 0), MAX_WAIT_MS)),
                "timeout_ms": max(100, min(timeout_ms, MAX_STEP_TIMEOUT_MS)),
                "state": str(raw.get("state") or "visible"),
            }
        )
    return normalized


def budget_seconds(actions: Sequence[Dict[str, Any]]) -> float:
    """Wall-clock the whole batch may take, for the offload timeout."""
    total = sum(step["timeout_ms"] + step["ms"] for step in actions) / 1000.0
    return total + 60.0


def _run_step(page: Any, step: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Execute one step. Raises :class:`ActionError` with a usable message."""
    name = step["action"]
    selector = step["selector"]
    timeout_ms = step["timeout_ms"]

    if name == "wait":
        time.sleep(step["ms"] / 1000.0)
        return {"waited_ms": step["ms"]}

    if name == "press" and not selector:
        try:
            page.keyboard.press(step["key"])
        except Exception as exc:  # noqa: BLE001
            raise ActionError(f"Could not press '{step['key']}': {exc}", index=index) from exc
        return {"key": step["key"]}

    if name == "wait_for":
        deadline = time.time() + timeout_ms / 1000.0
        want_hidden = step["state"] in ("hidden", "detached")
        while True:
            present = any(_has(target, selector) for target in _targets(page))
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
        target = _resolve_target(page, selector, timeout_ms)
    except LookupError as exc:
        raise ActionError(
            f"No element matched '{selector}' within {timeout_ms}ms "
            "(searched the page and every frame).",
            index=index,
        ) from exc

    locator = target.locator(selector).first
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
        elif name == "scroll_to":
            locator.scroll_into_view_if_needed(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - Playwright raises a wide family here
        raise ActionError(f"{name} on '{selector}' failed: {str(exc)[:300]}", index=index) from exc

    return {}


def act(
    state: WindowState,
    *,
    profile: str,
    actions: Sequence[Dict[str, Any]],
    after_seq: int = 0,
    settle_ms: int = 0,
    screenshot: str = "none",
    selector: Optional[str] = None,
    screenshot_path: str = "",
) -> Dict[str, Any]:
    """Run the batch, then drain what it caused. Same raw shape as capture()."""
    require_playwright()
    steps = list(actions)
    settle_s = max(0, min(int(settle_ms), MAX_WAIT_MS)) / 1000.0

    def _work() -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                contexts = browser.contexts
                if not contexts:
                    raise NoPageFound("The debug window has no browser context.")
                context = contexts[0]
                page = _instance_page(context.pages, state.instance_host)
                if page is None:
                    raise NoPageFound(
                        "The debug window has no open tab. Open a page in it and retry."
                    )

                # Re-arm first: a click that navigates must land on an
                # instrumented document, and add_init_script only affects
                # documents created after it is registered.
                _install_probe(context, page, state, profile)

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
                        entry.update(_run_step(page, step, index))
                        entry["ok"] = True
                    except ActionError as exc:
                        entry["ok"] = False
                        entry["error"] = str(exc)
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

                drained = page.evaluate(drain_script(after_seq)) or {}
                shot = _screenshot(
                    page, mode=screenshot, selector=selector, destination=screenshot_path
                )
                return {
                    "url": str(page.url),
                    "title": str(drained.get("title") or page.title()),
                    "seq": int(drained.get("seq") or 0),
                    "dropped": int(drained.get("dropped") or 0),
                    "events": list(drained.get("events") or []),
                    "styles": {},
                    "screenshot": shot,
                    "effective_user": _effective_user(page),
                    "watched_seconds": settle_s,
                    "steps": results,
                    "dialogs": dialogs,
                    "failed_step": (failure["step"] if failure else None),
                    "skipped": max(0, len(steps) - len(results)),
                }
            finally:
                browser.close()

    return run_off_loop(_work, timeout_s=budget_seconds(steps) + settle_s)


__all__ = [
    "ACTIONS_NEEDING_SELECTOR",
    "ACTIONS_NEEDING_VALUE",
    "ActionError",
    "DEFAULT_STEP_TIMEOUT_MS",
    "MAX_ACTIONS",
    "MAX_STEP_TIMEOUT_MS",
    "MAX_WAIT_MS",
    "SUPPORTED_ACTIONS",
    "act",
    "budget_seconds",
    "normalize",
]
