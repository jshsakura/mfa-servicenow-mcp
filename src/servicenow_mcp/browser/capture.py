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
from .badge import badge_init_script, hide_badge_script, show_badge_script
from .evaluate import run_in_page
from .probe import PROBE_SCRIPT, drain_script
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


def _install_probe(context: Any, page: Any, state: WindowState, profile: str) -> None:
    """Make sure the collector and the badge are present, now and after navigation.

    Registered on EVERY attach, deliberately. Playwright registers init scripts
    over CDP, and whether those survive a disconnect is not something to bet the
    feature on: if they do, the second registration is a no-op because both
    scripts guard on their own global; if they do not, skipping the re-register
    would leave the next navigation uninstrumented and the user's clicks would
    go unrecorded. Re-registering is correct either way, so it is not cached.
    """
    scripts = (PROBE_SCRIPT, badge_init_script(state.instance_host, profile))

    for script in scripts:
        try:
            context.add_init_script(script)
        except Exception as exc:  # noqa: BLE001 - instrumentation is best effort
            logger.debug("Could not register debug init script: %s", exc)

    # add_init_script only affects documents created from now on, so the page
    # already loaded needs a direct injection. Both scripts no-op if present.
    for script in scripts:
        try:
            page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 - a hostile page must not break the read
            logger.debug("Could not inject debug script into the current document: %s", exc)


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
                page = _instance_page(context.pages, state.instance_host)
                if page is None:
                    raise NoPageFound(
                        "The debug window has no open tab. Open a page in it and retry."
                    )

                _install_probe(context, page, state, profile)

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
                browser.close()

    # The offload budget has to outlast the watch itself, plus attach/capture.
    return run_off_loop(_work, timeout_s=wait_s + 90.0)


def arm(state: WindowState, *, profile: str) -> Dict[str, Any]:
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
                page = _instance_page(context.pages, state.instance_host)
                if page is None:
                    return {"armed": False, "reason": "no open tab"}
                _install_probe(context, page, state, profile)
                return {"armed": True, "url": str(page.url)}
            finally:
                # Disconnects from the browser; it does NOT terminate the
                # window (Playwright: a connected browser is disconnected, a
                # launched one is closed).
                browser.close()

    return run_off_loop(_work, timeout_s=60.0)


def navigate(
    state: WindowState, *, url: str, profile: str = "", allow_discard: bool = False
) -> Dict[str, Any]:
    """Point the window's active tab at ``url``.

    Refuses when the current page holds edited-but-unsaved form input, unless
    ``allow_discard``. Navigating away from a half-filled form is the most
    damaging thing this read-only feature could do to the person using it — and
    that person is mid-task by definition, since they are the one filling it in.
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
                page = _instance_page(context.pages, state.instance_host)
                if page is None:
                    page = context.new_page()

                previous_url = str(page.url)
                if not allow_discard:
                    dirty = _dirty_fields(page)
                    if dirty:
                        return {
                            "navigated": False,
                            "url": previous_url,
                            "blocked_by_unsaved_input": dirty,
                        }

                # Register BEFORE navigating: add_init_script only reaches
                # documents created after it lands, so arming after goto would
                # miss everything the page does while loading.
                _install_probe(context, page, state, profile)
                page.goto(url, wait_until="domcontentloaded")
                return {"navigated": True, "url": str(page.url), "previous_url": previous_url}
            finally:
                browser.close()

    return run_off_loop(_work, timeout_s=120.0)


_DIRTY_FIELDS_SCRIPT = """
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


def _dirty_fields(page: Any) -> List[str]:
    try:
        result = page.evaluate(_DIRTY_FIELDS_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - never block navigation on a probe failure
        logger.debug("Unsaved-input check failed: %s", exc)
        return []
    return [str(name) for name in result or []]


__all__ = [
    "LAYOUT_PROPERTIES",
    "MAX_WATCH_SECONDS",
    "NoPageFound",
    "arm",
    "capture",
    "navigate",
]
