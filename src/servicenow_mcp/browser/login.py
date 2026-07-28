"""Sign the debug window in with the credentials the server already has.

The window keeps its own ServiceNow session (see session.py), and the price of
that isolation is a login. Asking the user to type a password they already
configured — into a window a tool just opened for them — is the kind of chore
this repo removes, so if the config carries a username and a password the form
is filled and submitted automatically.

Two things are load-bearing here.

**One attempt per window.** A wrong password retried on every open_debug_window
call is how an account gets locked out, and the second attempt would be no more
likely to succeed than the first: nothing changed between them. So the attempt
is claimed on disk against the window's ``started_at`` BEFORE the submit, not
after — a crash mid-login must not come back as a retry loop either. Closing
the window and opening a new one is the deliberate way to try again, and it is
also exactly what a person does after fixing a typo in their config.

**MFA is the user's.** The submit is where automation stops. Everything past it
— the code, the push prompt, the remembered-device checkbox — happens in a
window the user is already looking at, which is the whole premise of the
feature. Nothing here waits for it: the tool returns and says so.

Credentials come from ``auth.browser`` first, then ``auth.basic``. The second
is not a fallback so much as a convenience for the common setup where the same
account is used both ways; on an OAuth or API-key profile there is simply
nothing to fill and the window asks for a login as before.
"""

import json
import logging
import os
from typing import Any, Dict, Optional, Sequence, Tuple

from ..auth._browser_dom import (
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    _click_first_matching,
    _fill_first_matching,
    _selector_exists,
    _target_label,
)
from ._offload import require_playwright, run_off_loop
from .window import WindowState

logger = logging.getLogger(__name__)

# A window that just opened is usually still redirecting through the IdP, so
# the form is not in the DOM on the first look. Short, because this wait is
# also paid by an already-signed-in window, where it will always time out.
LOGIN_FORM_WAIT_S = 5.0

# Attaching, filling, submitting. Deliberately does NOT cover MFA.
LOGIN_TIMEOUT_S = 90.0

# CSS unions of the shared selector tuples — one wait_for_selector instead of
# one per candidate, which would multiply the timeout above by six.
_PASSWORD_UNION = ", ".join(PASSWORD_SELECTORS)


def saved_credentials(config: Any) -> Optional[Tuple[str, str]]:
    """Username and password from the server config, or None.

    Both must be present: half a credential fills half a form and submits
    nothing useful, which is worse than not trying.
    """
    for holder in ("browser", "basic"):
        section = getattr(getattr(config, "auth", None), holder, None)
        username = getattr(section, "username", None)
        password = getattr(section, "password", None)
        if username and password:
            return str(username), str(password)
    return None


# ---------------------------------------------------------------------------
# The one-attempt claim
# ---------------------------------------------------------------------------


def already_attempted(marker_path: str, state: WindowState) -> bool:
    """True when this exact window has already been auto-filled once.

    Keyed on ``started_at`` rather than on the file merely existing, so a new
    window — the user's way of saying "try again" — starts with a fresh shot
    even though the marker file from the previous one is still on disk.
    """
    try:
        with open(marker_path, "r", encoding="utf-8") as handle:
            recorded = json.load(handle)
    except FileNotFoundError:
        return False
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable auto-login marker at %s: %s", marker_path, exc)
        return False
    try:
        return abs(float(recorded.get("started_at", -1.0)) - float(state.started_at)) < 0.001
    except (TypeError, ValueError):
        return False


def record_attempt(marker_path: str, state: WindowState) -> None:
    """Spend this window's single auto-login attempt."""
    os.makedirs(os.path.dirname(marker_path), exist_ok=True)
    tmp_path = f"{marker_path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"started_at": float(state.started_at)}, handle)
        os.replace(tmp_path, marker_path)
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not record the auto-login attempt: %s", exc)


# ---------------------------------------------------------------------------
# Filling the form
# ---------------------------------------------------------------------------


def _login_targets(page: Any) -> Sequence[Any]:
    """The page plus its frames — SSO forms are routinely in an iframe."""
    targets = [page]
    try:
        for frame in page.frames:
            if frame is not page.main_frame:
                targets.append(frame)
    except Exception as exc:  # noqa: BLE001 - a detached frame must not abort login
        logger.debug("Could not enumerate frames for login: %s", exc)
    return targets


def _wait_for_login_form(page: Any) -> bool:
    """Is there a password field to fill, now or within a few seconds?

    A password input is the signal, not the URL: instances redirect to wildly
    different IdPs, and every one of them ends at a field of this shape.
    """
    for target in _login_targets(page):
        if _selector_exists(target, _PASSWORD_UNION):
            return True
    try:
        page.wait_for_selector(_PASSWORD_UNION, timeout=int(LOGIN_FORM_WAIT_S * 1000))
        return True
    except Exception:  # noqa: BLE001 - not a login page, or already signed in
        return False


def _fill_and_submit(page: Any, username: str, password: str) -> Dict[str, Any]:
    """Fill the first frame that has the fields, then submit it.

    Selectors are logged; values never are. The password reaches Playwright and
    the DOM and goes nowhere else — see probe.py for the matching redaction on
    the network side, where a fetch-based IdP would otherwise buffer it.
    """
    for index, target in enumerate(_login_targets(page)):
        label = _target_label(target, index)
        filled_user = _fill_first_matching(target, USERNAME_SELECTORS, username)
        filled_password = _fill_first_matching(target, PASSWORD_SELECTORS, password)
        if not (filled_user or filled_password):
            continue

        logger.info(
            "Debug window auto-login filled %s (user=%s pass=%s)",
            label,
            filled_user,
            filled_password,
        )

        clicked = _click_first_matching(target, SUBMIT_SELECTORS)
        if clicked:
            return {"filled": True, "submitted": True, "via": f"click {clicked}"}

        # No recognizable submit button. Enter in the password field is what a
        # person would do next, and most login forms honor it.
        if filled_password:
            try:
                target.locator(filled_password).press("Enter")
                return {"filled": True, "submitted": True, "via": "Enter"}
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not submit the login form with Enter: %s", exc)

        return {"filled": True, "submitted": False, "via": None}

    return {"filled": False, "submitted": False, "via": None}


def auto_login(
    state: WindowState,
    *,
    credentials: Optional[Tuple[str, str]],
    marker_path: str,
) -> Dict[str, Any]:
    """Fill and submit the login form in the window, at most once per window.

    Never raises: a window that opened is a success even if signing it in was
    not, and the user can always type the password themselves. Every outcome is
    reported under ``status`` so the caller can say which one happened.
    """
    if not credentials:
        return {"status": "no_credentials"}
    if already_attempted(marker_path, state):
        return {"status": "already_attempted"}

    username, password = credentials
    require_playwright()

    def _work() -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                contexts = browser.contexts
                if not contexts:
                    return {"status": "no_page"}
                pages = [
                    page
                    for page in contexts[0].pages
                    if not str(page.url).startswith("devtools://")
                ]
                if not pages:
                    return {"status": "no_page"}
                page = pages[0]

                if not _wait_for_login_form(page):
                    return {"status": "no_login_form", "url": str(page.url)}

                # Claimed BEFORE the submit: if this call dies between the
                # click and the response, the next one must not try again.
                record_attempt(marker_path, state)

                outcome = _fill_and_submit(page, username, password)
                if not outcome["filled"]:
                    return {"status": "fields_not_found", "url": str(page.url)}
                if not outcome["submitted"]:
                    return {"status": "filled", "user": username}
                return {"status": "submitted", "user": username, "via": outcome["via"]}
            finally:
                # Disconnects from the window; does not close it.
                browser.close()

    try:
        return run_off_loop(_work, timeout_s=LOGIN_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a failed login never fails the open
        logger.info("Debug window auto-login did not complete: %s", exc)
        return {"status": "error", "error": str(exc)[:200]}


def describe(result: Dict[str, Any]) -> Optional[str]:
    """One line for the caller to pass on, or None when there is nothing to say."""
    status = result.get("status")
    if status == "submitted":
        return (
            f"Signed in as '{result.get('user')}' automatically. "
            "If the instance asks for MFA, complete it in the window."
        )
    if status == "filled":
        return (
            f"Filled the credentials for '{result.get('user')}' but found no submit "
            "button — press Enter in the window."
        )
    if status == "fields_not_found":
        return "A login form is showing but its fields were not recognized — sign in manually."
    if status == "already_attempted":
        return (
            "Auto-login already ran once for this window. If it failed, close the window "
            "and open it again (one attempt per window avoids locking the account)."
        )
    if status == "error":
        return f"Auto-login could not run ({result.get('error')}) — sign in manually."
    # no_credentials / no_login_form / no_page: nothing happened and nothing is wrong.
    return None


__all__ = [
    "LOGIN_FORM_WAIT_S",
    "LOGIN_TIMEOUT_S",
    "already_attempted",
    "auto_login",
    "describe",
    "record_attempt",
    "saved_credentials",
]
