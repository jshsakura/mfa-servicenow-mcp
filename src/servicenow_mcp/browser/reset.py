"""Put the debug window back to a blank state — for ONE instance, never all.

Why this exists
---------------
A shared window accumulates: a session signed in hours ago, a half-tested
impersonation, cookies from a form that set them, six tabs. "Start this test
from nothing" was previously done by closing the window by hand and opening a
new one — which is a whole Chromium launch (a launch-budget slot, a profile
warm-up, and about 200MB) to throw away a cookie jar.

Why it is scoped to one instance
--------------------------------
Since v1.24.7 one window holds every instance the account can reach, as tabs.
So "clear the cookies" without a scope would sign the person out of the two
instances they did not mention — including one they might be mid-task in. This
clears exactly one session:

- cookies whose domain belongs to this instance host, and no others. Read,
  filtered, and written back rather than cleared with a ``domain=`` predicate,
  because what that predicate matches (exact host? parent domain? leading dot?)
  varies with the Playwright version, and a filter that matched nothing would
  clear nothing while reporting a reset — the failure this repo keeps finding.
  Filtering in Python is the same work and the match is ours to prove.
- localStorage/sessionStorage on that origin, cleared from a tab standing on it.
- the tabs on that host, closed. Other instances' tabs are left exactly alone.
- the impersonation marker for that session (host-scoped already).

What it deliberately does NOT clear
-----------------------------------
**The auto-login budget.** It is spent by a credential the server REFUSED
(login.py), and resetting a browser does not make a rejected password correct —
giving the shot back here would turn "reset and retry" into the retry loop the
budget exists to prevent. So a window whose login was refused comes back from a
reset signed out and stays that way until a person types the password. Said out
loud in the result rather than left to be discovered.

What it clears wider than one instance
--------------------------------------
**The HTTP cache.** Chromium's cache API is per-browser, not per origin, so
emptying it reaches every instance in the window. That is not a scoping failure
being tolerated quietly — the cache holds no session state, so the whole cost is
a slower first load on another tab, and a "blank state" that silently kept a
stale bundle is the more expensive kind of wrong. Reported as what it is.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence

from ._offload import require_playwright, run_off_loop
from .capture import _dirty_fields, _on_instance
from .window import WindowState

logger = logging.getLogger(__name__)

# Long enough for tab closes plus a storage wipe, short enough that a wedged
# window fails the call rather than pinning the MCP request open.
_RESET_TIMEOUT_S = 90.0


def _cookie_host(cookie: Dict[str, Any]) -> str:
    """The host a cookie belongs to, with the leading dot browsers use dropped."""
    return str(cookie.get("domain") or "").lstrip(".").lower()


def belongs_to(cookie: Dict[str, Any], instance_host: str) -> bool:
    """Is this cookie part of the session for ``instance_host``?

    A cookie set on ``.service-now.com`` is sent to the instance too, so it is
    part of that session — but it is part of every OTHER instance's session on
    that domain as well, and clearing it would sign them out. So only cookies
    whose own domain IS this host are taken: over-keeping leaves a stale cookie
    the server will replace, over-clearing ends a session nobody mentioned.
    """
    host = (instance_host or "").lower()
    if not host:
        return False
    return _cookie_host(cookie) == host


def _clear_cookies(context: Any, instance_host: str) -> Dict[str, Any]:
    """Drop this instance's cookies, keep every other instance's. Exact counts."""
    try:
        before: List[Dict[str, Any]] = list(context.cookies())
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        logger.debug("Could not read cookies to reset: %s", exc)
        return {"cookies_cleared": None, "cookies_note": f"Could not read cookies ({exc})."}

    kept = [cookie for cookie in before if not belongs_to(cookie, instance_host)]
    dropped = len(before) - len(kept)
    if not dropped:
        return {"cookies_cleared": 0}

    try:
        context.clear_cookies()
        if kept:
            context.add_cookies(kept)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not rewrite the cookie jar: %s", exc)
        return {
            "cookies_cleared": None,
            "cookies_note": (
                f"The cookie jar could not be rewritten ({exc}). Some sessions in this "
                "window may have been signed out; check the other instances' tabs."
            ),
        }
    return {"cookies_cleared": dropped, "cookies_kept": len(kept)}


_STORAGE_SCRIPT = """
(() => {
  const done = [];
  try { window.localStorage.clear(); done.push('localStorage'); } catch (e) {}
  try { window.sessionStorage.clear(); done.push('sessionStorage'); } catch (e) {}
  return done;
})()
"""


def _clear_storage(page: Any) -> List[str]:
    """Wipe web storage for the origin this tab is standing on."""
    try:
        cleared = page.evaluate(_STORAGE_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - a hostile document is not a failed reset
        logger.debug("Could not clear web storage: %s", exc)
        return []
    return [str(item) for item in (cleared or [])]


def _clear_cache(page: Any) -> Optional[bool]:
    """Empty Chromium's HTTP cache. None when the request never got through."""
    try:
        session = page.context.new_cdp_session(page)
    except Exception as exc:  # noqa: BLE001
        logger.debug("No CDP session for a cache clear: %s", exc)
        return None
    try:
        session.send("Network.clearBrowserCache")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not clear the browser cache: %s", exc)
        return None
    finally:
        try:
            session.detach()
        except Exception:  # noqa: BLE001 - already gone
            pass


def _holding_input(pages: Sequence[Any]) -> List[Dict[str, Any]]:
    """Tabs with something typed in them, observed or guessed.

    Unlike navigation, a guess is NOT stepped around here: a reset closes tabs
    and clears the session behind them, and there is no "open it beside" version
    of that. The evidence that would only move a tab has to be enough to stop
    one being closed.
    """
    holding: List[Dict[str, Any]] = []
    for page in pages:
        try:
            dirty, basis = _dirty_fields(page)
        except Exception as exc:  # noqa: BLE001 - an unreadable tab is not an empty one
            logger.debug("Could not read a tab's input before reset: %s", exc)
            holding.append({"url": str(getattr(page, "url", "")), "fields": None, "basis": None})
            continue
        if dirty:
            holding.append({"url": str(page.url), "fields": dirty, "basis": basis})
    return holding


def reset_session(
    state: WindowState,
    *,
    landing_url: str,
    allow_discard: bool = False,
    clear_cache: bool = True,
) -> Dict[str, Any]:
    """Sign this instance out of the window and leave one blank tab on it.

    Returns what it actually did, item by item. Never guesses a success: a step
    that could not be carried out comes back as ``None`` with a note, because
    "reset" is a claim a caller will build a test on.
    """
    require_playwright()
    host = state.instance_host

    def _work() -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        browser = None
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                contexts = browser.contexts
                if not contexts:
                    return {"reset": False, "error": "The debug window has no browser context."}
                context = contexts[0]

                pages = [
                    page
                    for page in context.pages
                    if not str(page.url).startswith("devtools://") and _on_instance(page, host)
                    # With no host to scope by there is nothing to scope: an
                    # unconfigured instance URL makes every tab "ours", and
                    # clearing everything is not a scoped reset. Refused above.
                ]

                if not allow_discard:
                    holding = _holding_input(pages)
                    if holding:
                        return {
                            "reset": False,
                            "blocked_by_unsaved_input": holding,
                            "error": (
                                f"{len(holding)} tab(s) on this instance hold input. A reset "
                                "closes them and clears the session behind them — pass "
                                "discard_unsaved_input=true to do it anyway."
                            ),
                        }

                # A tab on the origin has to outlive the cookie clear to wipe
                # storage, so the blank one is opened FIRST and everything else
                # closed around it.
                landing = context.new_page()
                try:
                    landing.goto(landing_url, wait_until="domcontentloaded")
                except Exception as exc:  # noqa: BLE001 - a signed-out redirect is normal
                    logger.debug("Reset landing page did not settle: %s", exc)

                closed = 0
                for page in pages:
                    try:
                        page.close()
                        closed += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Could not close a tab during reset: %s", exc)

                result: Dict[str, Any] = {"reset": True, "closed_tabs": closed}
                result.update(_clear_cookies(context, host))
                result["storage_cleared"] = _clear_storage(landing)
                if clear_cache:
                    result["cache_cleared"] = _clear_cache(landing)

                # Reloaded after the jar was emptied: until it is, the tab is
                # still showing the signed-in page and "blank state" would be a
                # screenshot away from being contradicted.
                try:
                    landing.goto(landing_url, wait_until="domcontentloaded")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not reload the landing tab after reset: %s", exc)
                try:
                    landing.bring_to_front()
                except Exception:  # noqa: BLE001 - cosmetic
                    pass
                result["url"] = str(landing.url)
                return result
            finally:
                if browser is not None:
                    browser.close()

    return run_off_loop(_work, timeout_s=_RESET_TIMEOUT_S)


__all__ = ["belongs_to", "reset_session"]
