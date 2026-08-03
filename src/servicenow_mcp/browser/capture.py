"""Attach to the live window, take what is asked for, detach.

Nothing here stays connected between tool calls, and nothing here clicks —
driving the page is actions.py, deliberately a different module behind a
different (write-classified) tool. The page does its own recording (probe.py),
so a call attaches, drains whatever accumulated since last time, optionally
captures a screenshot or a few computed styles, and lets go.

Defaults are all "off": no screenshot, no styles, only events newer than the
caller's high-water mark. Everything this module returns had to be asked for.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ._offload import require_playwright, run_off_loop
from .badge import badge_activity_script, badge_init_script, hide_badge_script, show_badge_script
from .evaluate import run_in_page
from .probe import PROBE_SCRIPT, dirty_script, drain_script, presence_script
from .session import EFFECTIVE_USER_SCRIPT
from .window import WindowState

logger = logging.getLogger(__name__)

# Watching is a human-paced activity ("I'll click through the form"), but an
# unbounded wait would pin an MCP request open indefinitely.
MAX_WATCH_SECONDS = 300.0

# Curated instead of exhaustive. getComputedStyle exposes 300+ properties; the
# handful that explain "why is this element in the wrong place" is small, and
# dumping the rest would cost more tokens than the answer is worth.
LAYOUT_PROPERTIES: Tuple[str, ...] = (
    "display",
    "position",
    "top",
    "right",
    "bottom",
    "left",
    "width",
    "height",
    "margin",
    "padding",
    "border",
    "box-sizing",
    "overflow",
    "z-index",
    "float",
    "flex",
    "flex-direction",
    "align-items",
    "justify-content",
    "grid-template-columns",
    "font-size",
    "line-height",
    "color",
    "background-color",
    "visibility",
    "opacity",
    "transform",
)


class NoPageFound(RuntimeError):
    """The window is open but has no inspectable page."""


def _instance_page(pages: Sequence[Any], instance_host: str) -> Optional[Any]:
    """Prefer a tab actually on the instance; fall back to the first real tab.

    With several tabs open, guessing wrong means reporting another page's
    errors — worse than reporting none.
    """
    real_pages = [page for page in pages if not str(page.url).startswith("devtools://")]
    if not real_pages:
        return None
    if instance_host:
        for page in real_pages:
            if instance_host in str(page.url):
                return page
    return real_pages[0]


def _active_instance_page(pages: Sequence[Any], instance_host: str) -> Optional[Any]:
    """The instance tab someone was last working in — not merely the first one.

    With one tab this is :func:`_instance_page` and costs nothing. With several
    it matters a great deal: a new tab opened beside a form (see ``navigate``)
    would otherwise leave the model reading the OLD tab while the person looks
    at the new one, and "let's look at this together" quietly becomes two people
    describing different pages.

    Focus is not available: measured on the live window, every tab reports
    ``document.visibilityState === 'visible'`` and ``hasFocus() === true`` once
    CDP is attached, because attaching lifts background throttling. What IS
    available is the probe's ``lastHuman`` stamp, kept per tab in sessionStorage
    for the reaper. Whoever touched a tab most recently — the person or the
    model's own clicks, which arrive through the same input pipeline — is
    working there, and that is the tab to continue in.

    Falls back to the first instance tab whenever the probe cannot answer: an
    unarmed document is not a reason to pick the wrong page.
    """
    candidates = [page for page in pages if not str(page.url).startswith("devtools://")]
    if instance_host:
        on_instance = [page for page in candidates if instance_host in str(page.url)]
        candidates = on_instance or candidates
    if len(candidates) <= 1:
        return candidates[0] if candidates else None

    best: Optional[Any] = None
    best_stamp = -1.0
    for page in candidates:
        try:
            reading = page.evaluate(presence_script())
        except Exception as exc:  # noqa: BLE001 - an unarmed tab simply has no say
            logger.debug("Could not read presence from a tab: %s", exc)
            continue
        if not isinstance(reading, dict):
            continue
        try:
            stamp = float(reading.get("lastHuman") or 0.0)
        except (TypeError, ValueError):
            continue
        if stamp > best_stamp:
            best, best_stamp = page, stamp

    if best is not None and best_stamp > 0:
        return best
    return _instance_page(pages, instance_host)


def _probe_scripts(state: WindowState, profile: str, account: str = "") -> Tuple[str, ...]:
    # The profile dir IS the window: one directory, one Chromium. That is what
    # the badge colours itself by, so every tab in a window wears one colour
    # while each names its own instance.
    return (PROBE_SCRIPT, badge_init_script(profile, account, window_id=state.profile_dir))


def _install_probe_scripts(
    context: Any, state: WindowState, profile: str, account: str = ""
) -> None:
    """Register the init scripts on the CONTEXT — for documents not yet created.

    Split out because a new tab has no page to inject into yet, and registering
    first is what makes that tab instrumented from its first byte. The probe's
    unsaved-input record is only trustworthy when it was there from the start.
    """
    for script in _probe_scripts(state, profile, account):
        try:
            context.add_init_script(script)
        except Exception as exc:  # noqa: BLE001 - instrumentation is best effort
            logger.debug("Could not register debug init script: %s", exc)


def _install_probe(
    context: Any, page: Any, state: WindowState, profile: str, account: str = ""
) -> None:
    """Make sure the collector and the badge are present, now and after navigation.

    Registered on EVERY attach, deliberately. Playwright registers init scripts
    over CDP, and whether those survive a disconnect is not something to bet the
    feature on: if they do, the second registration is a no-op because both
    scripts guard on their own global; if they do not, skipping the re-register
    would leave the next navigation uninstrumented and the user's clicks would
    go unrecorded. Re-registering is correct either way, so it is not cached.
    """
    _install_probe_scripts(context, state, profile, account)

    # add_init_script only affects documents created from now on, so the page
    # already loaded needs a direct injection. Both scripts no-op if present.
    for script in _probe_scripts(state, profile, account):
        try:
            page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 - a hostile page must not break the read
            logger.debug("Could not inject debug script into the current document: %s", exc)


def _arm_tabs(pages: Sequence[Any], state: WindowState, profile: str, account: str = "") -> int:
    """Put the probe in EVERY instance tab, not just the one we are about to use.

    Otherwise the tab choice above cannot work: a tab the user opened by hand —
    or one opened beside a form — has no probe, so it cannot report that the
    person is working in it, so it is never chosen, so it never gets a probe.
    Arming every tab breaks that circle.

    A tab armed on this attach still starts at ``lastHuman = 0``; it earns a say
    from the next thing done in it. One call to catch up is the cost of a tab
    that appeared without us.

    Returns how many tabs were armed, for the tests. Never raises: a tab that
    refuses the script simply stays silent.
    """
    armed = 0
    scripts = _probe_scripts(state, profile, account)
    for page in pages:
        url = str(getattr(page, "url", ""))
        if url.startswith("devtools://"):
            continue
        if state.instance_host and state.instance_host not in url:
            continue
        for script in scripts:
            try:
                page.evaluate(script)
            except Exception as exc:  # noqa: BLE001 - a torn-down tab is not an error
                logger.debug("Could not arm a tab: %s", exc)
                break
        else:
            armed += 1
    return armed


def _set_activity(page: Any, active: bool) -> None:
    """Light the badge dot while the MCP is attached to this page.

    Best-effort by design: the light is a courtesy to the human watching, and
    a page that refuses the script must not fail the operation it is reporting.
    """
    try:
        page.evaluate(badge_activity_script(active))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not update the activity dot: %s", exc)


def _computed_styles(page: Any, selectors: Sequence[str]) -> Dict[str, Any]:
    """Layout-relevant computed styles plus the box, per selector."""
    if not selectors:
        return {}
    script = """
    ([selectors, props]) => {
      const out = {};
      for (const sel of selectors) {
        let el = null;
        try { el = document.querySelector(sel); } catch (e) { out[sel] = { error: 'invalid selector' }; continue; }
        if (!el) { out[sel] = { found: false }; continue; }
        const cs = getComputedStyle(el);
        const style = {};
        for (const p of props) style[p] = cs.getPropertyValue(p);
        const r = el.getBoundingClientRect();
        out[sel] = {
          found: true,
          tag: el.tagName.toLowerCase(),
          classes: String(el.className || '').slice(0, 200),
          box: { x: Math.round(r.x), y: Math.round(r.y),
                 w: Math.round(r.width), h: Math.round(r.height) },
          style
        };
      }
      return out;
    }
    """
    try:
        return dict(page.evaluate(script, [list(selectors), list(LAYOUT_PROPERTIES)]))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Computed-style read failed: %s", exc)
        return {"_error": str(exc)[:200]}


def _screenshot(
    page: Any, *, mode: str, selector: Optional[str], destination: str
) -> Optional[str]:
    """Capture to disk and return the path. The badge is hidden for the shot.

    Element mode exists because a full-page screenshot of a ServiceNow portal
    rarely shows what broke — the interesting box is 200px tall somewhere in
    the middle.
    """
    if mode == "none":
        return None

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    try:
        page.evaluate(hide_badge_script())
    except Exception:  # noqa: BLE001 - badge may not be injected yet
        pass

    try:
        if mode == "element":
            if not selector:
                raise ValueError("screenshot='element' needs a selector.")
            page.locator(selector).first.screenshot(path=destination)
        else:
            page.screenshot(path=destination, full_page=(mode == "full"))
        return destination
    finally:
        try:
            page.evaluate(show_badge_script())
        except Exception:  # noqa: BLE001
            pass


def _effective_user(page: Any) -> Optional[Dict[str, Any]]:
    try:
        result = page.evaluate(EFFECTIVE_USER_SCRIPT)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Effective-user read failed: %s", exc)
        return None
    return dict(result) if isinstance(result, dict) else None


def capture(
    state: WindowState,
    *,
    profile: str,
    account: str = "",
    after_seq: int = 0,
    watch_seconds: float = 0.0,
    screenshot: str = "none",
    selector: Optional[str] = None,
    style_selectors: Sequence[str] = (),
    screenshot_path: str = "",
    evaluate_expression: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach, collect, detach. Returns raw material for report.py to compact."""
    require_playwright()
    wait_s = max(0.0, min(float(watch_seconds), MAX_WATCH_SECONDS))

    def _work() -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                contexts = browser.contexts
                if not contexts:
                    raise NoPageFound("The debug window has no browser context.")
                context = contexts[0]
                # Arm first, choose second: an unarmed tab has no say in which
                # tab is being worked in, and staying unarmed is how it keeps
                # not having one.
                _arm_tabs(context.pages, state, profile, account)
                page = _active_instance_page(context.pages, state.instance_host)
                if page is None:
                    raise NoPageFound(
                        "The debug window has no open tab. Open a page in it and retry."
                    )

                _install_probe(context, page, state, profile, account)
                _set_activity(page, True)

                if wait_s:
                    # The page records on its own; this is just the agreed
                    # window during which the user drives.
                    time.sleep(wait_s)

                drained = page.evaluate(drain_script(after_seq)) or {}
                # Evaluated AFTER the drain so a question about the page's
                # state is answered from the same moment the events describe,
                # and before the screenshot so the picture matches the answer.
                evaluation = (
                    run_in_page(page, expression=evaluate_expression)
                    if evaluate_expression
                    else None
                )
                shot = _screenshot(
                    page,
                    mode=screenshot,
                    selector=selector,
                    destination=screenshot_path,
                )
                return {
                    "evaluation": evaluation,
                    "url": str(page.url),
                    "title": str(drained.get("title") or page.title()),
                    "seq": int(drained.get("seq") or 0),
                    "dropped": int(drained.get("dropped") or 0),
                    "events": list(drained.get("events") or []),
                    "styles": _computed_styles(page, style_selectors),
                    "screenshot": shot,
                    "effective_user": _effective_user(page),
                    "watched_seconds": wait_s,
                }
            finally:
                # Cleared before detaching, so the dot never outlives the
                # attachment it is reporting.
                try:
                    _set_activity(page, False)
                except Exception:  # noqa: BLE001 - page may be gone
                    pass
                browser.close()

    # The offload budget has to outlast the watch itself, plus attach/capture.
    return run_off_loop(_work, timeout_s=wait_s + 90.0)


def arm(state: WindowState, *, profile: str, account: str = "") -> Dict[str, Any]:
    """Install the collector now, before the user does anything worth recording.

    Without this the probe would first appear on the initial inspect call — and
    by then the submit that caused the double-save has already happened and was
    never seen. Arming at open time is what makes "open the page, click around,
    then ask me what happened" work at all.
    """
    require_playwright()

    def _work() -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                contexts = browser.contexts
                if not contexts:
                    return {"armed": False, "reason": "no browser context"}
                context = contexts[0]
                # Arm first, choose second: an unarmed tab has no say in which
                # tab is being worked in, and staying unarmed is how it keeps
                # not having one.
                _arm_tabs(context.pages, state, profile, account)
                page = _active_instance_page(context.pages, state.instance_host)
                if page is None:
                    return {"armed": False, "reason": "no open tab"}
                _install_probe(context, page, state, profile, account)
                return {"armed": True, "url": str(page.url)}
            finally:
                # Disconnects from the browser; it does NOT terminate the
                # window (Playwright: a connected browser is disconnected, a
                # launched one is closed).
                browser.close()

    return run_off_loop(_work, timeout_s=60.0)


def navigate(
    state: WindowState,
    *,
    url: str,
    profile: str = "",
    account: str = "",
    allow_discard: bool = False,
    new_tab: bool = False,
) -> Dict[str, Any]:
    """Point the window's active tab at ``url``, or open ``url`` in a new one.

    Refuses when the current page holds edited-but-unsaved form input, unless
    ``allow_discard``. Navigating away from a half-filled form is the most
    damaging thing this feature could do to the person using it — and that
    person is mid-task by definition, since they are the one filling it in.

    ``new_tab`` is the answer to that refusal rather than a way around it: the
    form stays open and untouched in its tab while the new page loads beside
    it, which is what a person does when they need to look at something else
    without losing their place. It never triggers the unsaved-input check,
    because there is nothing to lose.

    A GUESS does not refuse — it steps aside. When no keystroke was ever
    observed (``basis == "guessed"``: the probe was not on that document, and
    the fields merely differ from their HTML defaults, which every widget that
    initialises itself produces) this opens the new tab by itself instead of
    returning "no". Refusing on that evidence is how a shared window stops being
    usable: the portal landing page reports eight dirty fields nobody touched,
    every navigation is denied, and the person ends up closing the window to get
    a working one. Both people are supposed to be able to type in this window —
    protecting that must not cost the ability to use it.

    Observed input (``typed``/``partial``) still refuses, because there the
    evidence is a real person's keystrokes.
    """
    require_playwright()

    def _work() -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                contexts = browser.contexts
                if not contexts:
                    raise NoPageFound("The debug window has no browser context.")
                context = contexts[0]
                _arm_tabs(context.pages, state, profile, account)
                existing = _active_instance_page(context.pages, state.instance_host)

                # Decided before anything moves: a guess steps aside into a new
                # tab, observed input still refuses. See the docstring.
                stepped_aside: Dict[str, Any] = {}
                use_new_tab = new_tab
                if existing is not None and not use_new_tab and not allow_discard:
                    dirty, basis = _dirty_fields(existing)
                    if dirty and basis == "guessed":
                        use_new_tab = True
                        stepped_aside = {"kept_input": dirty, "input_basis": basis}
                    elif dirty:
                        return {
                            "navigated": False,
                            "url": str(existing.url),
                            "blocked_by_unsaved_input": dirty,
                            "input_basis": basis,
                        }

                if use_new_tab or existing is None:
                    # Register the init scripts BEFORE the tab exists, so the
                    # new document is instrumented from its first byte — which
                    # is also what makes its unsaved-input record trustworthy
                    # later (see _dirty_fields).
                    _install_probe_scripts(context, state, profile, account)
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded")
                    page.bring_to_front()
                    return {
                        "navigated": True,
                        "url": str(page.url),
                        "new_tab": True,
                        "previous_url": (str(existing.url) if existing else None),
                        "tabs": len(context.pages),
                        **stepped_aside,
                    }

                page = existing
                previous_url = str(page.url)

                # Register BEFORE navigating: add_init_script only reaches
                # documents created after it lands, so arming after goto would
                # miss everything the page does while loading.
                _install_probe(context, page, state, profile, account)
                page.goto(url, wait_until="domcontentloaded")
                return {
                    "navigated": True,
                    "url": str(page.url),
                    "new_tab": False,
                    "previous_url": previous_url,
                }
            finally:
                browser.close()

    return run_off_loop(_work, timeout_s=120.0)


# The fallback, used only when the probe was never installed. It compares each
# field against its HTML value attribute, which on a framework-rendered page
# says almost nothing: Angular/ng-model assigns `.value` from JS and leaves
# `defaultValue` empty, so every widget that initialized itself reads as
# half-typed. Kept because "no evidence either way" must fail toward keeping
# the user's work, not toward discarding it — but it is labelled as a guess so
# the caller can weigh it accordingly.
_DIRTY_FIELDS_FALLBACK_SCRIPT = """
(() => {
  const dirty = [];
  const named = (el) => el.name || el.id || el.getAttribute('ng-model') || el.tagName.toLowerCase();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (el.type === 'hidden' || el.disabled || el.readOnly) continue;
    let changed = false;
    if (el.tagName === 'SELECT') changed = el.selectedIndex !== el.querySelector('option[selected]')?.index;
    else if (el.type === 'checkbox' || el.type === 'radio') changed = el.checked !== el.defaultChecked;
    else changed = (el.value || '') !== (el.defaultValue || '');
    if (changed && String(el.value || '').length) dirty.push(named(el));
    if (dirty.length >= 10) break;
  }
  return dirty;
})()
"""


def _dirty_fields(page: Any) -> Tuple[List[str], str]:
    """Fields that would lose input on navigation, and how confidently we know.

    Returns (names, basis) where basis is one of:

    ``typed``     the probe watched this document from its first byte and these
                  fields received TRUSTED input events — a human typed in them.
    ``partial``   the probe is present but was injected into an already-loaded
                  document, so anything typed before it arrived went unseen.
                  What it reports is real; what it omits is not proof.
    ``guessed``   no probe. Values differ from the HTML defaults, which a widget
                  initializing itself also produces. Frequently a false alarm.
    """
    try:
        record = page.evaluate(dirty_script())
    except Exception as exc:  # noqa: BLE001 - never block navigation on a probe failure
        logger.debug("Unsaved-input check failed: %s", exc)
        return [], "guessed"

    if isinstance(record, dict):
        fields = [str(name) for name in record.get("fields") or []]
        return fields, ("typed" if record.get("observedFromStart") else "partial")

    try:
        legacy = page.evaluate(_DIRTY_FIELDS_FALLBACK_SCRIPT)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Fallback unsaved-input check failed: %s", exc)
        return [], "guessed"
    return [str(name) for name in legacy or []], "guessed"


__all__ = [
    "LAYOUT_PROPERTIES",
    "MAX_WATCH_SECONDS",
    "NoPageFound",
    "arm",
    "capture",
    "navigate",
]
