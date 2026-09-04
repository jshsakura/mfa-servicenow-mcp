"""Attach to the live window, take what is asked for, detach.

Nothing here stays connected between tool calls, and nothing here clicks —
driving the page is actions.py, deliberately a different module behind a
different (write-classified) tool. The page does its own recording (probe.py),
so a call attaches, drains whatever accumulated since last time, optionally
captures a screenshot or a few computed styles, and lets go.

Defaults are all "off": no screenshot, no styles, only events newer than the
caller's high-water mark. Everything this module returns had to be asked for.
"""

import io
import logging
import os
import time
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import image_budget, scroll_shot
from ._offload import cdp_browser, require_playwright, run_off_loop
from .badge import (
    badge_activity_script,
    badge_init_script,
    hide_badge_script,
    instance_labels,
    show_badge_script,
)
from .evaluate import run_in_page
from .probe import PROBE_SCRIPT, dirty_script, drain_script, presence_script
from .session import read_effective_user
from .tab_owner import claimed_by_others, drop_pin, write_pin
from .window import WindowState

logger = logging.getLogger(__name__)

# Watching is a human-paced activity ("I'll click through the form"), but an
# unbounded wait would pin an MCP request open indefinitely.
MAX_WATCH_SECONDS = 300.0

# When a new tab pushes the window past this, the oldest EMPTY tabs are closed.
# Generous: a real debugging session legitimately keeps a form, a list, a portal
# page and the record they are about side by side. See _trim_tabs.
MAX_TABS = 8

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


def _write_image(raw: bytes, destination: str) -> Tuple[str, Dict[str, str]]:
    """Write a screenshot, downscaled and lossless-WebP. Returns (path, size).

    Two different savings, and only one of them is about tokens.

    BYTES: measured on a real ServiceNow screenshot (1502x779), the PNG
    Playwright hands over is 64KB and the same pixels as lossless WebP are
    26KB — 59% fewer bytes at a maximum per-channel difference of ZERO. The
    alternatives were measured too and both lose: re-saving the PNG with
    optimize=True came out BIGGER (66KB), and JPEG q85 was bigger still (69KB)
    while visibly chewing the anti-aliased text. That is a disk saving.

    PIXELS: a model is billed for the pixel count, so none of the above saved a
    single token — the same 1729x847 arrived either way, at roughly two
    thousand of them. `image_budget.fit` caps the width first; see that module
    for why width and not the longer side.

    Without Pillow the bytes are written as they came, PNG and all, and the
    returned size says nothing rather than claiming a resize that never ran: a
    smaller file is not worth a screenshot that does not exist, and neither is
    an accurate-sounding number.
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        with open(destination, "wb") as handle:
            handle.write(raw)
        return destination, image_budget.uncapped(raw)

    target = os.path.splitext(destination)[0] + ".webp"
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            fitted, size = image_budget.fit(image)
            try:
                fitted.save(target, "WEBP", lossless=True, method=6)
            finally:
                if fitted is not image:
                    fitted.close()
        return target, size
    except Exception as exc:  # noqa: BLE001 - an unwritten screenshot is the worse outcome
        logger.info("Could not re-encode the screenshot, keeping it as PNG: %s", exc)
        with open(destination, "wb") as handle:
            handle.write(raw)
        return destination, image_budget.uncapped(raw)


def _why_one_screen(page: Any) -> str:
    """Why 'full' came back as one screen — the reason that actually applied.

    This was one fixed sentence, and it named a cause nobody had checked:
    "install the 'browser' extra for stitching". Measured on a live instance
    against a Next Experience analytics page, with Pillow installed and working
    (every other screenshot that session came back as WebP, which needs it), the
    note still told the reader to install it. A shorter image that looks
    complete is the failure this path exists to stop; a note that misnames the
    cause sends the reader to fix something that is not broken, which is the
    same failure with an extra errand attached.

    So the branches are separated and each says only what it established.
    """
    tail = " — this is one screen, not the whole page"
    try:
        from PIL import Image  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return (
            "this page does not scroll in its top document, and stitching needs Pillow, "
            "which is not installed (pip install 'mfa-servicenow-mcp[browser]')" + tail
        )
    if scroll_shot.find_scrolling_frame(page) is None:
        return (
            "this page does not scroll in its top document, and no same-origin FRAME "
            "scrolls either — on Next Experience the scroller is often a component "
            "inside a shadow root rather than an iframe, and this cannot drive that" + tail
        )
    return (
        "this page does not scroll in its top document, and the frame that does "
        "scroll could not be captured (it stopped answering, or its box could not "
        "be measured)" + tail
    )


class NoPageFound(RuntimeError):
    """The window is open but has no inspectable page."""


def _on_instance(page: Any, instance_host: str) -> bool:
    """Is this tab on the instance the call is about?

    An empty host means the question cannot be asked (an unconfigured instance
    URL), and an unaskable question is not a negative answer: everything the
    window has is then the only thing it has.
    """
    if not instance_host:
        return True
    return instance_host in str(getattr(page, "url", ""))


def _foreign_instance(page: Any, instance_host: str) -> bool:
    """Is this tab on a DIFFERENT configured instance?

    The fallback below — "no tab on the instance, so take the first real one" —
    was written when a window held one instance, so the only thing it could fall
    back to was a page the person had wandered off to. Since v1.24.7 one window
    holds every instance the account can reach, and the same line would hand a
    dev question a test tab, then report the answer under the dev label.

    This is not guessed from the URL's shape: the configured instances are a
    list this process has (``instance_labels``), so a known host is PROVEN to be
    someone else's session rather than suspected of it. An unconfigured host is
    left alone — falling back to somebody's intranet tab is the behaviour the
    shared window is supposed to have.
    """
    if _on_instance(page, instance_host):
        return False
    try:
        host = (urlparse(str(getattr(page, "url", ""))).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    return bool(host) and host in instance_labels()


def _usable(pages: Sequence[Any], instance_host: str) -> List[Any]:
    """Tabs this call may read or drive: real, and not another instance's."""
    return [
        page
        for page in pages
        if not str(page.url).startswith("devtools://")
        and not _foreign_instance(page, instance_host)
    ]


def no_page_message(pages: Sequence[Any], instance_host: str) -> str:
    """Why there is nothing to work with. "No tab" and "not YOUR tab" differ.

    Told apart because the fix differs: one is "open a page", the other is "this
    window is busy with another instance and you need a tab on yours". A single
    message for both would send someone looking for a window that is right in
    front of them, full of tabs.
    """
    others = sum(1 for page in pages if _foreign_instance(page, instance_host))
    if others:
        return (
            f"This window has no tab on {instance_host}. Its {others} other tab(s) are on "
            "different configured instances, and driving one of those would act on "
            "somebody else's session. Call open_debug_window with a url to get a tab here."
        )
    return "The debug window has no open tab. Open a page in it and retry."


def _instance_page(pages: Sequence[Any], instance_host: str) -> Optional[Any]:
    """Prefer a tab actually on the instance; fall back to the first usable tab.

    With several tabs open, guessing wrong means reporting another page's
    errors — worse than reporting none. Another configured instance's tab is
    never the fallback at all; see :func:`_foreign_instance`.
    """
    real_pages = _usable(pages, instance_host)
    if not real_pages:
        return None
    if instance_host:
        for page in real_pages:
            if instance_host in str(page.url):
                return page
    return real_pages[0]


class TabPick(NamedTuple):
    """The tab a call landed on, and what is actually known about it.

    ``mine`` is proven, never assumed: it is True only when this session had a
    pin AND a tab answered with that exact id. A tab that could not be asked
    (no probe, an unarmed document) is not mine — an unread signal is not a
    match, and callers branch on this to decide whether to displace somebody.

    ``tab_id`` is "" for the same reason: the probe did not say.
    """

    page: Any
    tab_id: str
    mine: bool
    # Another LIVE session's pinned tab. Separate from ``not mine`` on purpose:
    # "not mine" is the ordinary case (a single terminal has no pin until it
    # opens something, and the person's own tab has none ever), while this one
    # names a session that said it is working here. Only the second is a reason
    # to step aside — treating the first as one would open a tab on every
    # navigate for everybody. Proven, never assumed: an unknown tab id matches
    # no claim, so it is not claimed.
    claimed_by_other: bool = False


def _tab_readings(pages: Sequence[Any]) -> Dict[int, Tuple[str, float]]:
    """``id(page) -> (tabId, lastHuman)`` for every tab that answers.

    Best effort by design: a tab with no probe simply has no say, and is left
    out rather than represented by a default that would compete on equal terms
    with a real reading.
    """
    readings: Dict[int, Tuple[str, float]] = {}
    for page in pages:
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
            stamp = 0.0
        readings[id(page)] = (str(reading.get("tabId") or ""), stamp)
    return readings


def _active_instance_page(pages: Sequence[Any], state: WindowState) -> Optional[TabPick]:
    """The tab this call should work in: this session's, else the live one.

    **This session's pinned tab wins.** Several MCP hosts share one window
    (see tab_owner.py), and until v1.24.8 they shared one TAB with it: the rule
    below picks the most recently touched tab, and Playwright's own clicks are
    trusted input, so whichever host acted last owned the tab for every host.
    Two terminals on one instance silently drove the same page, and a form one
    of them was typing into came back to the other as ``blocked_by_unsaved_input``
    — a window that looked locked, by a lock that never existed.

    A pin that no longer matches any open tab is dropped here rather than left
    to fail the same way on every future call. It is NOT replaced by a guess:
    the returned ``mine`` says the tab is not this session's, and the caller
    decides what that is worth (``navigate`` opens its own; a read says so).

    Without a pin the old rule stands, and its reasoning is unchanged. Focus is
    not available — measured on the live window, every tab reports
    ``visibilityState === 'visible'`` and ``hasFocus() === true`` once CDP is
    attached, because attaching lifts background throttling. What IS available
    is the probe's ``lastHuman`` stamp. Whoever touched a tab most recently is
    working there, and that is the tab to continue in.

    Falls back to the first instance tab whenever no tab can answer: an unarmed
    document is not a reason to pick the wrong page.
    """
    instance_host = state.instance_host
    candidates = _usable(pages, instance_host)
    if instance_host:
        on_instance = [page for page in candidates if instance_host in str(page.url)]
        candidates = on_instance or candidates
    if not candidates:
        return None

    # Read FIRST, and cheaply: a local file, no round trip. It has to come
    # before the decision below because the collision this fixes happens in the
    # one-tab case above all — two sessions, one tab, no pin yet. Skipping the
    # probe read there ("nothing to decide") would leave the tab id blank, match
    # no claim, and hand the tab straight over, which is the bug.
    claims = claimed_by_others(state.owners_path, instance_host) if state.owners_path else set()

    # The round trip is still skipped when nothing can turn on it: one tab, no
    # pin of ours, and nobody else claiming anything here. That is the ordinary
    # single-terminal call, and it costs exactly what it did before.
    readings = (
        _tab_readings(candidates) if state.owner_tab_id or claims or len(candidates) > 1 else {}
    )

    if state.owner_tab_id:
        for page in candidates:
            if readings.get(id(page), ("", 0.0))[0] == state.owner_tab_id:
                return TabPick(page, state.owner_tab_id, True)
        # Only once every candidate has ANSWERED can "not here" be distinguished
        # from "not asked". A tab that failed to report its id may well be the
        # pinned one, and dropping the pin on that evidence would hand this
        # session a new tab every call while its own sat there unrecognised.
        if len(readings) == len(candidates):
            logger.debug("Dropping a debug-window tab pin whose tab is gone")
            drop_pin(state.owners_path, instance_host)

    best: Optional[Any] = None
    best_stamp = -1.0
    for page in candidates:
        stamp = readings.get(id(page), ("", -1.0))[1]
        if stamp > best_stamp:
            best, best_stamp = page, stamp

    if best is None or best_stamp <= 0:
        best = _instance_page(pages, instance_host)
        if best is None:
            return None
        # The fallback is chosen from `pages`, which `readings` may not cover
        # when it was never read (the cheap path). Ask now rather than report a
        # blank id: the id is what the claim check below is judged on, and an
        # absent one would read as "nobody claims this".
        if id(best) not in readings and (state.owner_tab_id or claims or len(candidates) > 1):
            readings.update(_tab_readings([best]))

    tab_id = readings.get(id(best), ("", 0.0))[0]
    # `mine` was ruled out above, so the only remaining question is whether
    # somebody else said this tab is theirs. With no tab id there is nothing to
    # match — not a clean answer, but the only one available, and it is reached
    # solely when nobody claims anything on this host anyway.
    return TabPick(best, tab_id, False, bool(tab_id) and tab_id in claims)


def _tab_id(page: Any) -> str:
    """This tab's probe id, or "" when it cannot say.

    Called only where a pin is about to be written, so the read paths keep the
    round trip they had. "" is not an error: an unarmed tab has no id yet, and a
    pin nobody can match later is worse than no pin at all.
    """
    try:
        reading = page.evaluate(presence_script())
    except Exception as exc:  # noqa: BLE001 - an unarmed tab simply has no id
        logger.debug("Could not read a tab id: %s", exc)
        return ""
    return str(reading.get("tabId") or "") if isinstance(reading, dict) else ""


def pin_tab(state: WindowState, tab_id: str) -> None:
    """Remember ``tab_id`` as this session's tab on the caller's instance.

    Called with whatever tab id the operation already had in hand, so it costs
    no round trip. Never raises: a pin is an optimization, and losing one costs
    a single re-pick on the next call.
    """
    if not tab_id or not state.owners_path:
        return
    try:
        write_pin(state.owners_path, state.instance_host, tab_id)
    except Exception as exc:  # noqa: BLE001 - never fail a call over a pin
        logger.debug("Could not pin a debug-window tab: %s", exc)


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
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Capture to disk and return (path, note).

    Element mode exists because a full-page screenshot of a ServiceNow portal
    rarely shows what broke — the interesting box is 200px tall somewhere in
    the middle.

    ``full`` used to hand ``full_page=True`` to Playwright and be done. That
    grows the TOP document, which is right on a portal page and a no-op on Next
    Experience, where the shell never scrolls and the classic UI scrolls inside
    a frame — so ``full`` returned one viewport and called itself full. The
    scroller is checked now, and when it is a frame the shot is stitched from
    real scrolling (scroll_shot). Nothing on the page is changed either way.

    **The badge is hidden for EVERY capture.** It is ``position: fixed`` and
    sits over the page, so in a screenshot it is not information — it is an
    occlusion, covering whatever is under the bottom-right corner, which on a
    list is a row and on a form is a field.

    v1.24.3 made the single shot an exception, on the argument that a screenshot
    OF the debug window should say which window it is. That was answered
    elsewhere all along: every response carries ``instance_target``, and the
    badge is on screen for the person watching, which is its actual job. The
    exception traded page pixels the caller asked for against a fact they
    already had — and it contradicted this module's own stated constraint, that
    screenshots are used to judge visual breakage so the badge must not appear
    in them.
    """
    if mode == "none":
        return None, None

    os.makedirs(os.path.dirname(destination), exist_ok=True)

    hidden = _hide_badge(page)
    try:
        if mode == "element":
            if not selector:
                raise ValueError("screenshot='element' needs a selector.")
            path, size = _write_image(page.locator(selector).first.screenshot(), destination)
            return path, (size or None)

        if mode == "full" and not scroll_shot.page_scrolls(page):
            stitched = scroll_shot.capture(page, destination=destination)
            if stitched:
                return stitched.pop("path", destination), stitched
            # Nothing better was possible here (no inner scroller, no Pillow, a
            # frame that would not answer). The ordinary shot is taken, and it is
            # NOT described as a full-page capture.
            path, size = _write_image(page.screenshot(full_page=False), destination)
            return path, {"only_viewport": _why_one_screen(page), **size}

        path, size = _write_image(page.screenshot(full_page=(mode == "full")), destination)
        return path, (size or None)
    finally:
        if hidden:
            _show_badge(page)


def _hide_badge(page: Any) -> bool:
    try:
        page.evaluate(hide_badge_script())
        return True
    except Exception:  # noqa: BLE001 - badge may not be injected yet
        return False


def _show_badge(page: Any) -> None:
    try:
        page.evaluate(show_badge_script())
    except Exception:  # noqa: BLE001
        pass


def _effective_user(page: Any) -> Optional[Dict[str, Any]]:
    # Frame-aware: the Next Experience shell names nobody, and reporting that as
    # "could not read a signed-in user — the window may still need a login" sent
    # people to look for a login problem on a signed-in window. See
    # session.read_effective_user.
    return read_effective_user(page)


def capture(
    state: WindowState,
    *,
    profile: str,
    account: str = "",
    marks: Any = 0,
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
        with cdp_browser(state.cdp_endpoint) as browser:
            page = None
            try:
                contexts = browser.contexts
                if not contexts:
                    raise NoPageFound("The debug window has no browser context.")
                context = contexts[0]
                # Arm first, choose second: an unarmed tab has no say in which
                # tab is being worked in, and staying unarmed is how it keeps
                # not having one.
                _arm_tabs(context.pages, state, profile, account)
                pick = _active_instance_page(context.pages, state)
                if pick is None:
                    raise NoPageFound(no_page_message(context.pages, state.instance_host))
                page = pick.page

                _install_probe(context, page, state, profile, account)
                _set_activity(page, True)

                if wait_s:
                    # The page records on its own; this is just the agreed
                    # window during which the user drives.
                    time.sleep(wait_s)

                drained = page.evaluate(drain_script(marks)) or {}
                # Evaluated AFTER the drain so a question about the page's
                # state is answered from the same moment the events describe,
                # and before the screenshot so the picture matches the answer.
                evaluation = (
                    run_in_page(page, expression=evaluate_expression)
                    if evaluate_expression
                    else None
                )
                shot, shot_note = _screenshot(
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
                    "tab_id": str(drained.get("tabId") or ""),
                    # Reported, never claimed: reading a tab does not make it
                    # this session's. See actions.py for the same note.
                    "tab_is_mine": pick.mine,
                    "tab_claimed_by_other": pick.claimed_by_other,
                    "dropped": int(drained.get("dropped") or 0),
                    "events": list(drained.get("events") or []),
                    "styles": _computed_styles(page, style_selectors),
                    "screenshot": shot,
                    "screenshot_note": shot_note,
                    "effective_user": _effective_user(page),
                    "watched_seconds": wait_s,
                }
            finally:
                # Cleared before returning, so the dot never outlives the
                # attachment it is reporting.
                try:
                    if page is not None:
                        _set_activity(page, False)
                except Exception:  # noqa: BLE001 - page may be gone
                    pass

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
        with cdp_browser(state.cdp_endpoint) as browser:
            contexts = browser.contexts
            if not contexts:
                return {"armed": False, "reason": "no browser context"}
            context = contexts[0]
            # Arm first, choose second: an unarmed tab has no say in which
            # tab is being worked in, and staying unarmed is how it keeps
            # not having one.
            _arm_tabs(context.pages, state, profile, account)
            pick = _active_instance_page(context.pages, state)
            if pick is None:
                return {
                    "armed": False,
                    "reason": no_page_message(context.pages, state.instance_host),
                }
            page = pick.page
            _install_probe(context, page, state, profile, account)
            # Read while attached: the landed url and signed-in user answer the
            # "did the open land where I asked, as whom?" question the caller
            # used to spend a follow-up inspect on. ``tab_id`` rides along for
            # the pin (tab_owner.py) — read after _install_probe, because a tab
            # armed a moment ago is exactly the one that had no id before.
            return {
                "armed": True,
                "url": str(page.url),
                "user": _effective_user(page),
                "tab_id": pick.tab_id or _tab_id(page),
                "tab_is_mine": pick.mine,
            }

    return run_off_loop(_work, timeout_s=60.0)


def _trim_tabs(context: Any, *, keep: Any, instance_host: str = "") -> Dict[str, Any]:
    """Close the oldest tabs holding nothing, once the window has too many.

    Tabs accumulate and nothing used to remove them: ``navigate`` opens one on
    request and one more whenever it steps aside from a page whose dirty fields
    are only a guess (a portal landing page reports eight nobody typed in), and
    the reaper retires idle WINDOWS, not tabs. A long session ends up with a
    window nobody can find anything in.

    Destructive, so it is deliberately timid:

    - a tab with ANY unsaved input is never closed, guessed or observed. The
      "a guess only steps aside" rule elsewhere is about opening a tab, which
      costs nothing; this closes one, and the same evidence is not good enough
      for that.
    - oldest first (``context.pages`` is creation order), never the tab just
      opened.
    - THIS instance's tabs first. One window holds every instance the account
      can reach, and the duplicates that made the window hard to work in are the
      ones piling up on the instance being driven. Another instance's single tab
      is the last thing to take, not the first thing older than ours.
    - when nothing qualifies, nothing is closed and the count is REPORTED. A
      cap that silently gives up looks identical to a cap that worked.
    """
    try:
        pages = [page for page in context.pages if not str(page.url).startswith("devtools://")]
    except Exception as exc:  # noqa: BLE001 - housekeeping must not fail a navigation
        logger.debug("Could not list tabs to trim: %s", exc)
        return {}
    excess = len(pages) - MAX_TABS
    if excess <= 0:
        return {}

    # Stable within each group, so "oldest first" still holds inside them.
    ordered = [page for page in pages if _on_instance(page, instance_host)]
    ordered += [page for page in pages if not _on_instance(page, instance_host)]

    closed: List[str] = []
    for page in ordered:
        if len(closed) >= excess:
            break
        if page is keep:
            continue
        try:
            dirty, _basis = _dirty_fields(page)
            if dirty:
                continue
            was = str(page.url)
            page.close()
            closed.append(was)
        except Exception as exc:  # noqa: BLE001 - a tab that will not close is not fatal
            logger.debug("Could not close a tab while trimming: %s", exc)

    if closed:
        return {
            "closed_tabs": closed,
            "closed_tabs_note": (
                f"{len(closed)} empty tab(s) closed — the window was over {MAX_TABS}. "
                "Anything holding input was left alone."
            ),
        }
    return {
        "tabs_note": (
            f"{len(pages)} tabs open, over the {MAX_TABS} this trims at, and none could "
            "be closed — they all hold input. Close some by hand if the window is "
            "getting hard to work in."
        )
    }


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

    A tab that is not on this instance is never taken over at all — new tab,
    every time, no dirty check needed because nothing of ours is being
    displaced. One window holds every instance the account can reach (see
    window.py), so the tab that happens to be active is routinely another
    instance's work or the person's own page, and navigating it away would end
    a session nobody asked to end.
    """
    require_playwright()

    def _work() -> Dict[str, Any]:
        with cdp_browser(state.cdp_endpoint) as browser:
            contexts = browser.contexts
            if not contexts:
                raise NoPageFound("The debug window has no browser context.")
            context = contexts[0]
            _arm_tabs(context.pages, state, profile, account)
            pick = _active_instance_page(context.pages, state)
            existing = pick.page if pick else None

            # Decided before anything moves: a guess steps aside into a new
            # tab, observed input still refuses. See the docstring.
            stepped_aside: Dict[str, Any] = {}
            use_new_tab = new_tab
            if existing is not None and pick is not None and pick.claimed_by_other:
                # Another LIVE MCP session said it is working in this tab. Taking
                # it over is the whole reported problem: several hosts share this
                # window, tab choice went by "most recently touched", and
                # Playwright's own input is trusted, so whoever navigated last
                # won the tab for everybody — the other one's half-filled form
                # then came back to them as `blocked_by_unsaved_input`, looking
                # like a lock that never existed. Open a tab instead of taking
                # one. Deliberately NOT triggered by "not mine": an unclaimed tab
                # is still reused in place, or a single terminal would open a new
                # tab on every navigate.
                use_new_tab = True
                stepped_aside = {"claimed_by_other_url": str(existing.url)}
            if existing is not None and not _on_instance(existing, state.instance_host):
                # The window holds every instance this account can reach, so
                # the tab we would otherwise take over is routinely ANOTHER
                # instance's — or the person's own page. Taking it would end
                # a session nobody asked to end. Instances are tabs: open one.
                use_new_tab = True
                stepped_aside = {"opened_beside_url": str(existing.url)}
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
                # This tab exists because this session asked for it, so it is
                # this session's from here on. Pinned only on tabs we created or
                # already held: pinning a tab we merely landed on would turn a
                # one-call collision into a permanent claim on somebody's page.
                pin_tab(state, _tab_id(page))
                return {
                    "navigated": True,
                    "url": str(page.url),
                    "new_tab": True,
                    "tab_is_mine": True,
                    "previous_url": (str(existing.url) if existing else None),
                    "tabs": len(context.pages),
                    **stepped_aside,
                    **_trim_tabs(context, keep=page, instance_host=state.instance_host),
                }

            page = existing
            previous_url = str(page.url)

            # Register BEFORE navigating: add_init_script only reaches
            # documents created after it lands, so arming after goto would
            # miss everything the page does while loading.
            _install_probe(context, page, state, profile, account)
            page.goto(url, wait_until="domcontentloaded")
            # Ours, or proven unclaimed a moment ago and now navigated by this
            # session — either way this is the tab we are working in. Pinning a
            # tab we merely READ would be a claim on somebody's page; pinning the
            # one we just pointed somewhere is a record of what we did.
            #
            # The id is asked for when the selection never needed it (one tab,
            # no pin, no claims): that path is precisely the one where this
            # session is about to acquire its first tab, so it is the one call
            # that must not go unrecorded.
            pin_tab(state, (pick.tab_id if pick else "") or _tab_id(page))
            return {
                "navigated": True,
                "url": str(page.url),
                "new_tab": False,
                "tab_is_mine": True,
                "previous_url": previous_url,
            }

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
