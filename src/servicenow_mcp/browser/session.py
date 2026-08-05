"""The debug window keeps its OWN ServiceNow session. Nothing is shared.

Why there is no "share the API session" mode
--------------------------------------------
ServiceNow impersonation is server-side session state: the cookie does not
change, the server re-points that session at another user. So a window carrying
the API's session cookie would not merely *show* the API's session — it would
BE it, and everything done in the window would land on the object the MCP tools
depend on:

    impersonate         -> every later MCP call runs as that user; ACLs and
                           sys_updated_by attribution both contaminated
    logout              -> the API session dies
    switch update set   -> subsequent MCP writes silently land somewhere else

That last one is the worst: this repo works hard to keep the active scope and
update set deterministic (manage_session_context, the write guards), and a
human clicking the picker would override all of it without a trace.

The mode was considered and deliberately not built. Guarding a shared session
with warnings still leaves the failure reachable; giving the window its own
session removes it. Impersonating, logging out, and switching scope in the
window are now ordinary things to do, because they cannot reach the API.

The cost is one interactive login the first time. The window has a persistent
Chromium profile, so the IdP's remembered-device cookie makes later refreshes
silent — the same mechanism the login profile already relies on.

A useful side effect: with no cookie to inject, this works on basic/OAuth/
API-key profiles too. The window logs itself in and does not care how the API
authenticates.
"""

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def instance_host(instance_url: str) -> str:
    return (urlparse(instance_url).hostname or "").lower()


# ---------------------------------------------------------------------------
# Who is this window logged in as?
# ---------------------------------------------------------------------------

# Deliberately layered and best-effort: ServiceNow exposes the current user
# under different globals depending on the UI (classic vs Next Experience vs
# Service Portal). Returning `source` lets the caller judge how far to trust
# the answer instead of pretending one global is authoritative — the same
# stance the repo takes on attribution generally.
EFFECTIVE_USER_SCRIPT = """
(() => {
  // NOW.user_impersonating is the platform's own answer to "is this session
  // pretending to be someone?" — measured on a live instance, where it reads
  // true while impersonating and is absent otherwise. It does NOT name the real
  // account; it only says that the name below is not it.
  let impersonating = null;
  try {
    if (window.NOW && typeof NOW.user_impersonating !== 'undefined') {
      impersonating = NOW.user_impersonating === true || NOW.user_impersonating === 'true';
    }
  } catch (e) {}
  const pick = (source, user) =>
    (user ? { user: String(user), source, impersonating } : null);
  try {
    if (window.NOW && NOW.user && NOW.user.userName) return pick('NOW.user', NOW.user.userName);
  } catch (e) {}
  try {
    if (window.g_user && g_user.userName) return pick('g_user', g_user.userName);
  } catch (e) {}
  try {
    if (window.NOW && NOW.user_name) return pick('NOW.user_name', NOW.user_name);
  } catch (e) {}
  return null;
})()
"""


def _read_user_in(target: Any) -> Optional[Dict[str, Any]]:
    """Run the reader against one document. None when it does not say."""
    try:
        result = target.evaluate(EFFECTIVE_USER_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - an unbooted document is not an error
        logger.debug("Effective-user read failed: %s", exc)
        return None
    return dict(result) if isinstance(result, dict) and result.get("user") else None


def read_effective_user(page: Any) -> Optional[Dict[str, Any]]:
    """Who this page says it is — its own document first, then its frames.

    The frame half is not a nicety, and it is measured rather than reasoned
    about: on Next Experience (``/now/nav/ui/...``) the shell document carries
    ``g_ck`` but names NO user, because the classic UI it wraps sits in an
    iframe **inside a shadow root** and ``g_user`` lives in there. Playwright
    lists that frame even though a DOM query on the light document finds nothing.

    Reading only the main document is why three different surfaces reported the
    same absence as a fact: the badge showed a blank user, ``inspect`` said
    "could not read a signed-in user — the window may still need a login", and
    impersonation turned a switch that HAD happened into "the page never
    reported a signed-in user". One document was read; the window was described.

    Frames on another host are skipped — a third-party widget's globals are not
    this session's and must not get to answer who we are. The answering frame's
    url is returned under ``frame`` so a caller can see where it came from.
    """
    own = _read_user_in(page)
    if own:
        return own

    try:
        main_host = (urlparse(str(page.url)).hostname or "").lower()
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        main_host = ""
    try:
        frames = list(page.frames)
        main = page.main_frame
    except Exception as exc:  # noqa: BLE001 - a page without frames is normal
        logger.debug("Could not enumerate frames for the user read: %s", exc)
        return None

    for frame in frames:
        if frame is main:
            continue
        try:
            frame_url = str(frame.url)
        except Exception:  # noqa: BLE001 - a detached frame does not answer
            continue
        if main_host and (urlparse(frame_url).hostname or "").lower() != main_host:
            continue
        reading = _read_user_in(frame)
        if reading:
            return {**reading, "frame": frame_url}
    return None


def describe_window_user(
    detected: Optional[Dict[str, Any]], api_user: Optional[str]
) -> Dict[str, Any]:
    """Report who the window is, and whether that differs from the API user.

    This is information, not a warning: the window has its own session, so a
    different user there is expected and harmless — while impersonating, it is
    the whole point. It is reported because confusing "what the window sees"
    with "what the API sees" would send an investigation down the wrong path.
    """
    window_user = str(detected.get("user")) if detected and detected.get("user") else None
    result: Dict[str, Any] = {
        "window_user": window_user,
        "detected_via": (detected or {}).get("source"),
        "api_user": api_user,
    }
    if window_user and api_user and window_user.strip().lower() != api_user.strip().lower():
        result["note"] = (
            f"The window is signed in as '{window_user}'; MCP API calls still run as "
            f"'{api_user}'. Separate sessions — what you see here is not what the "
            "API tools see."
        )
    return result


def api_username(config: Any) -> Optional[str]:
    """Best-effort username behind the API session, for the comparison above."""
    for holder in ("browser", "basic"):
        section = getattr(getattr(config, "auth", None), holder, None)
        username = getattr(section, "username", None)
        if username:
            return str(username)
    return None


__all__ = [
    "EFFECTIVE_USER_SCRIPT",
    "api_username",
    "describe_window_user",
    "instance_host",
    "read_effective_user",
]
