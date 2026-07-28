"""One MFA challenge per account, not one per Chromium profile.

The problem, measured rather than assumed
-----------------------------------------
"Do not challenge for MFA on this browser for the next 16 hours" is a single
cookie on the INSTANCE host:

    glide_mfa_remembered_browser   <instance>   expires ~16h out

It is not a session cookie and it carries no session: alongside it in the same
jar sit ``JSESSIONID``, ``glide_session_store``, ``glide_user_activity`` — those
ARE the session, and they are exactly what session.py refuses to share between
the API's browser profile and the debug window (impersonating or logging out in
a shared session would land on the object the MCP tools depend on).

So the two profiles each had to earn the remembered-browser cookie separately,
and the person paid for that with an MFA code every time a debug window opened.
The fix is to share the ONE cookie that is about the device and none of the ones
that are about the session.

The store
---------
A small file next to the window state, keyed by instance+account exactly like
everything else in this layer, holding that single cookie. Every profile that
faces a login reads it; every attached window contributes back to it. Two debug
profiles for the same account (a named-instance alias and a legacy key produce
different directories) now share one challenge instead of two.

The value is a device-trust token. It is written 0600 and never logged — the
same handling the session cache gives cookies, because it is the same kind of
secret.

Both directions, because a jar is a jar
--------------------------------------
A challenge answered in the debug window does NOT appear in the login profile on
its own — they are two cookie stores on disk. So the trust moves both ways: read
out of whichever profile earned it, and written into the other one when the
shared value actually changes (roughly once per remembered-browser lifetime).
The auth layer's CODE is untouched — auth_manager is FROZEN and stays that way;
what happens here is one cookie being placed in a profile directory, headless,
skipped entirely if anything is holding that profile's lock.

The intended shape of a day: pass MFA once, anywhere — the API's login browser
or the debug window — and every window for that account on that machine rides it
until the platform's own expiry. On a production instance, where the code comes
from a phone call to whoever holds the authenticator, that is the difference
between one call and one call per window.

Measured, on a live instance, three throwaway profiles
-----------------------------------------------------
=========  ======  ==============================
window     cookie  outcome
=========  ======  ==============================
headless   seeded  challenged
headed     seeded  logged in, no challenge
headed     none    challenged
=========  ======  ==============================

Two things follow, and the second one is the surprise. The cookie IS what skips
the challenge (rows 2 vs 3). And it only counts in a HEADED browser (rows 1 vs
2) — the instance weighs the client, not just the token, and a
``HeadlessChrome`` user agent is not the browser that was remembered. The cookie
was verified to reach the server in both cases, so this is the instance's
judgement rather than a transport problem.

That is a good fit and not a lucky one: the debug window is headed by contract
(``DEBUG_WINDOW_ALWAYS_HEADED``) because a shared screen cannot be invisible.
The headless launches in THIS module only read and write a cookie jar — they
never log in, so the same limit does not apply to them.

What is deliberately NOT here
-----------------------------
The session. ``JSESSIONID`` and friends stay where they are; see session.py for
why a shared session would put impersonation, logout and the update-set picker
on top of the object the MCP tools depend on. This module moves device trust,
which grants nothing on its own — a stolen copy still faces the password, and
(per the table) still has to look like the same browser.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Sequence

from ._offload import require_playwright, run_off_loop

logger = logging.getLogger(__name__)

# Measured on a live instance (v1.21.29). One name, not a guessed family: an
# invented pattern would silently match a session cookie some day, and this
# module's whole safety story is that it moves exactly one known cookie.
MFA_COOKIE_NAME = "glide_mfa_remembered_browser"

# A cookie this close to expiry is not worth carrying: the login it would serve
# has not happened yet, and a challenge is better than a broken-looking one.
MIN_REMAINING_S = 120.0

# Reading another profile means starting a browser on it. Short leash: this is
# an optimisation, and a slow one that blocks a window from opening is worse
# than an MFA prompt.
HARVEST_TIMEOUT_S = 45.0


def store_path(cache_root: str, instance_url: str, username: str = "") -> str:
    """Where the shared cookie lives: keyed by ACCOUNT, not by profile.

    Deliberately not the window/session suffix every other file in this layer
    uses. That suffix encodes the *configuration* — a named-instance alias
    ("dev") and a legacy host+user key produce different directories for the
    same human on the same instance, which is precisely how one account ends up
    being challenged twice. The device trust belongs to the account and the
    machine, so the key is host + account and nothing else.
    """
    from urllib.parse import urlparse

    host = (urlparse(instance_url).hostname or "default").replace(".", "_")
    user = re.sub(r"[^A-Za-z0-9]+", "_", (username or "").strip().lower()).strip("_")
    name = f"mfa_trust_{host}{f'_{user}' if user else ''}.json"
    return os.path.join(cache_root, name)


def _fresh(cookie: Optional[Dict[str, Any]], now: Optional[float] = None) -> bool:
    """Is this cookie worth carrying? Session cookies (no expiry) never are."""
    if not cookie or cookie.get("name") != MFA_COOKIE_NAME or not cookie.get("value"):
        return False
    try:
        expires = float(cookie.get("expires") or 0)
    except (TypeError, ValueError):
        return False
    if expires <= 0:
        # A cookie that dies with the browser cannot help a future window.
        return False
    return expires - (now if now is not None else time.time()) > MIN_REMAINING_S


def pick(cookies: Sequence[Dict[str, Any]], instance_host: str) -> Optional[Dict[str, Any]]:
    """The one cookie we move, or None. Everything else is left where it is.

    Matched by NAME and by host, so a jar full of session cookies contributes
    nothing — which is the point of the whole module.
    """
    host = (instance_host or "").lower().lstrip(".")
    for cookie in cookies or []:
        if cookie.get("name") != MFA_COOKIE_NAME:
            continue
        domain = str(cookie.get("domain") or "").lower().lstrip(".")
        if host and domain and domain not in host and host not in domain:
            continue
        if _fresh(dict(cookie)):
            return {
                "name": MFA_COOKIE_NAME,
                "value": str(cookie.get("value") or ""),
                "domain": str(cookie.get("domain") or instance_host),
                "path": str(cookie.get("path") or "/"),
                "expires": float(cookie.get("expires") or 0),
                "httpOnly": bool(cookie.get("httpOnly")),
                "secure": bool(cookie.get("secure", True)),
            }
    return None


# ---------------------------------------------------------------------------
# The shared store
# ---------------------------------------------------------------------------


def read_store(path: str) -> Optional[Dict[str, Any]]:
    """The shared cookie, or None when there is none worth using."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            recorded = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable MFA trust store at %s: %s", path, exc)
        return None
    cookie = recorded.get("cookie") if isinstance(recorded, dict) else None
    return cookie if _fresh(cookie) else None


def write_store(path: str, cookie: Optional[Dict[str, Any]]) -> bool:
    """Record the cookie for every profile of this account. 0600, never logged."""
    if not path or not _fresh(cookie):
        return False
    existing = read_store(path)
    if existing and existing.get("value") == (cookie or {}).get("value"):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"cookie": cookie, "at": time.time()}, handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not record the MFA trust cookie: %s", exc)
        return False
    logger.info("Recorded the MFA remembered-browser cookie for reuse (value not logged).")
    return True


# ---------------------------------------------------------------------------
# Moving it in and out of browsers
# ---------------------------------------------------------------------------


def harvest_from_context(context: Any, instance_host: str) -> Optional[Dict[str, Any]]:
    """Read the cookie off an already-attached context. No launch, no cost."""
    try:
        return pick(context.cookies(), instance_host)
    except Exception as exc:  # noqa: BLE001 - a jar we cannot read is not an error
        logger.debug("Could not read cookies for the MFA trust store: %s", exc)
        return None


def seed_context(context: Any, cookie: Optional[Dict[str, Any]]) -> bool:
    """Put the shared cookie into a window that is about to log in."""
    if not _fresh(cookie):
        return False
    try:
        context.add_cookies([dict(cookie or {})])
    except Exception as exc:  # noqa: BLE001 - seeding is an optimisation
        logger.debug("Could not seed the MFA trust cookie: %s", exc)
        return False
    logger.info("Seeded the MFA remembered-browser cookie into the debug window.")
    return True


def _on_profile(profile_dir: str, executable_path: str, work: Any) -> Any:
    """Run ``work(context)`` on a headless persistent context, or return None.

    Refuses rather than waits when the profile is in use: this runs while
    someone is waiting for a window, and a profile lock is held for as long as
    the browser holding it is open. Never raises — every caller here is an
    optimisation whose failure costs at most one MFA prompt.
    """
    if not profile_dir or not os.path.isdir(profile_dir):
        return None

    from ..auth._browser_dom import _singleton_holder_pid

    holder = _singleton_holder_pid(profile_dir)
    if holder is not None:
        logger.debug(
            "Profile %s is in use (pid %s); skipping MFA cookie work.", profile_dir, holder
        )
        return None

    require_playwright()

    def _work() -> Any:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            launch: Dict[str, Any] = {"headless": True}
            if executable_path:
                launch["executable_path"] = executable_path
            context = pw.chromium.launch_persistent_context(profile_dir, **launch)
            try:
                return work(context)
            finally:
                context.close()

    try:
        return run_off_loop(_work, timeout_s=HARVEST_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - never fail a window over this
        logger.info("MFA cookie work on %s did not complete: %s", profile_dir, exc)
        return None


def seed_profile(
    profile_dir: str, cookie: Optional[Dict[str, Any]], *, executable_path: str = ""
) -> bool:
    """Put the shared cookie INTO another profile — the way back.

    Two Chromium profiles are two cookie jars: a challenge answered in the debug
    window does not reach the login profile on its own, so the next API re-login
    would ask again. This closes that loop, and it is the only write this module
    makes outside its own store. Called only when the shared value actually
    changed — roughly once per remembered-browser lifetime, not per window.
    """
    if not _fresh(cookie):
        return False
    seeded = _on_profile(
        profile_dir, executable_path, lambda context: seed_context(context, cookie)
    )
    return bool(seeded)


def harvest_from_profile(
    profile_dir: str, instance_host: str, *, executable_path: str = ""
) -> Optional[Dict[str, Any]]:
    """Read the cookie out of another Chromium profile, headless and read-only.

    Used once, to seed a debug profile that has never been challenged, from the
    login profile that already has been — read-only, so the auth layer is not
    changed by this at all.
    """
    return _on_profile(
        profile_dir, executable_path, lambda context: harvest_from_context(context, instance_host)
    )


__all__ = [
    "HARVEST_TIMEOUT_S",
    "MFA_COOKIE_NAME",
    "MIN_REMAINING_S",
    "harvest_from_context",
    "harvest_from_profile",
    "pick",
    "read_store",
    "seed_context",
    "seed_profile",
    "store_path",
    "write_store",
]
