"""Sign the debug window in with the credentials the server already has.

The window keeps its own ServiceNow session (see session.py), and the price of
that isolation is a login. Asking the user to type a password they already
configured — into a window a tool just opened for them — is the kind of chore
this repo removes, so if the config carries a username and a password the form
is filled and submitted automatically.

Two things are load-bearing here.

**One REJECTED attempt per window.** A wrong password retried on every
open_debug_window call is how an account gets locked out, and the second attempt
would be no more likely to succeed than the first: nothing changed between them.
So the attempt is claimed on disk against the window's ``started_at`` BEFORE the
submit — a crash mid-login must not come back as a retry loop either — and then
GIVEN BACK when the instance turns out not to have rejected it.

That second half was missing until v1.24.1, and its absence was the bug: the
marker recorded "we tried" and every later call read it as "trying again would
be a retry loop", without anything ever reading whether the login had worked. A
window that signed in perfectly at 09:00 and whose session expired at 14:00 had
no attempt left, and the tool told the user to close their window and reopen it
— for a login that never failed. What the lockout guard is actually protecting
against is a credential the server REFUSES, so that is what now spends the shot.

The verdict is read from the login form itself: gone means the server did not
refuse (it either signed us in or moved on to an MFA challenge, and replaying an
accepted credential cannot lock anything), still standing means refused. An
unreadable page proves neither and leaves the attempt spent — the expensive
answer, per the repo's guard rule. Nothing here spams a challenge either: while
MFA is pending there is no password field on the page, so the next call finds no
form to fill and does nothing.

**The password only ever goes into a tab we drove.** This used to fill
``pages[0]`` — whatever tab happened to be first — and there was no origin check
anywhere in this module. The window is shared with the person using it, so tab 0
is routinely one of *their* pages; if it held a password field belonging to some
other site, the instance credentials were typed into that form and submitted.
Wasting the one attempt was the mild version of that bug.

So the tab is chosen, not assumed (:func:`_login_page`): a tab on the instance
host, or else the tab this very call pointed at the instance (``driven_url``,
which is why a single freshly-launched tab still qualifies after it redirects).
When neither can be identified, auto-login declines rather than guessing —
saying so, because a silent no-op is what let this go unnoticed. SSO is
unaffected: the IdP lives on a foreign host, but it is reached by driving OUR
tab there, and a form inside that tab's frames is still that tab's.

**MFA is the user's.** The submit is where automation stops. Everything past it
— the code, the push prompt, the remembered-device checkbox — happens in a
window the user is already looking at, which is the whole premise of the
feature. Nothing here waits for it: the tool returns and says so.

Do not try to carry the "remembered browser" over from the login profile. It
was tried (v1.22.1, reverted in v1.22.2) and the instance does not accept it.
Measured, not reasoned about:

- "do not challenge for 16 hours" is one cookie on the instance host,
  ``glide_mfa_remembered_browser``, sitting beside the session cookies;
- copied into another Chromium profile it reaches the server — verified in the
  request headers — and the server challenges anyway;
- so does copying every non-session cookie the profile holds
  (``glide_user_route``, ``glide_node_id_for_js``, ``BIGipServerpool_*``, …);
- and a fresh token, taken seconds after a successful challenge, behaves the
  same way in a second profile.

The instance identifies the BROWSER, not just the token. One profile, one
challenge — the debug window's own persistent profile is what makes the second
open silent, and that already works. The only thing sharing would have bought
is what session.py refuses to share for much better reasons.

**SSO (``auth_type: "sso"``) types a user ID and nothing else.** Some
instances sign people in through a multi-provider SSO page,
``login_locate_sso.do``: a single "User ID" field whose Submit asks the instance
which identity provider that user belongs to, then redirects there. The local
login form on such an instance is the wrong door — its password is not the one
the user has — so in this mode nothing is ever typed into a password field.
When the tab is on the instance's login page, it is sent to the locator, the ID
goes into ``#sso_selector_id``, Submit is clicked, and the rest (the IdP's own
password, MFA) is the user's. The mode is an explicit config value rather than
"no password configured", because that already means "sign in by hand".

Credentials come from ``auth.browser`` first, then ``auth.basic``. The second
is not a fallback so much as a convenience for the common setup where the same
account is used both ways; on an OAuth or API-key profile there is simply
nothing to fill and the window asks for a login as before.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from ..auth._browser_dom import (
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    _click_first_matching,
    _fill_first_matching,
    _selector_exists,
    _target_label,
)
from ..utils.instances import SSO_LOCATOR_PATH
from ._offload import cdp_browser, require_playwright, run_off_loop
from .window import WindowState

logger = logging.getLogger(__name__)

# A window that just opened is usually still redirecting through the IdP, so
# the form is not in the DOM on the first look. Short, because this wait is
# also paid by an already-signed-in window, where it will always time out.
LOGIN_FORM_WAIT_S = 5.0

# Attaching, filling, submitting. Deliberately does NOT cover MFA.
LOGIN_TIMEOUT_S = 90.0

# How long to watch the form for the instance's answer to the credentials, and
# how long it has to stay gone before that counts. A submit navigates, and a
# page mid-navigation briefly has no fields at all — reading that single frame
# as "accepted" would hand the attempt back to a password the server refused.
CREDENTIAL_VERDICT_S = 8.0
_VERDICT_POLL_S = 0.5
_VERDICT_STABLE_READS = 3

# CSS unions of the shared selector tuples — one wait_for_selector instead of
# one per candidate, which would multiply the timeout above by six.
_PASSWORD_UNION = ", ".join(PASSWORD_SELECTORS)

# The multi-provider SSO locator page (login_locate_sso.do). Read from the page
# itself: one text input, and a Submit button whose onclick runs locateSSO().
SSO_USER_FIELD = "input#sso_selector_id"
SSO_SUBMIT_SELECTORS = (
    "button[onclick*='locateSSO']",
    "button[type='submit']",
    "input[type='submit']",
)
# An unknown user ID is answered in place, as a GlideUI error message.
SSO_ERROR_SELECTOR = ".outputmsg_error"
SSO_VERDICT_S = 10.0
_SIGN_IN_UNION = f"{_PASSWORD_UNION}, {SSO_USER_FIELD}"


def saved_credentials(config: Any) -> Optional[Tuple[str, str]]:
    """Username and password from the server config, or None.

    Both must be present: half a credential fills half a form and submits
    nothing useful, which is worse than not trying.
    """
    if sso_login(config):
        # Nothing is ever typed into a password field in SSO mode — not even a
        # password that happens to sit in the basic section.
        return None
    for holder in ("browser", "basic"):
        section = getattr(getattr(config, "auth", None), holder, None)
        username = getattr(section, "username", None)
        password = getattr(section, "password", None)
        if username and password:
            return str(username), str(password)
    return None


def sso_login(config: Any) -> Optional[Tuple[str, str]]:
    """``(user ID, locator URL)`` when the config says ``auth_type: "sso"``.

    The URL may be empty: the window then uses its own instance's locator page.
    """
    browser = getattr(getattr(config, "auth", None), "browser", None)
    if getattr(browser, "login", None) != "sso":
        return None
    username = getattr(browser, "username", None)
    if not username:
        return None
    return str(username), str(getattr(browser, "login_url", None) or "")


def configured_username(config: Any) -> str:
    """The account this config signs in as, whichever way it signs in."""
    sso = sso_login(config)
    if sso:
        return sso[0]
    return (saved_credentials(config) or ("", ""))[0]


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


def release_attempt(marker_path: str) -> None:
    """Give the attempt back — the instance did not refuse these credentials.

    Called only on a proven non-refusal. Every other outcome, including one that
    could not be read, leaves the shot spent: the guard exists for a credential
    the server rejects, and "we could not tell" is not evidence it did not.
    """
    try:
        os.remove(marker_path)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not release the auto-login attempt at %s: %s", marker_path, exc)


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


def _real_pages(pages: Sequence[Any]) -> List[Any]:
    return [page for page in pages if not str(page.url).startswith("devtools://")]


def _login_page(
    pages: Sequence[Any], *, instance_host: str = "", driven_url: str = ""
) -> Tuple[Optional[Any], str]:
    """The one tab this may type a password into, or (None, why not).

    In order: a tab on the instance host; else the tab this call just pointed at
    the instance. The second is what keeps SSO working — the redirect lands the
    tab on the IdP's host, so there is nothing on the instance host to find, but
    it is still the tab we drove and a freshly launched window has only that one.

    A tab nobody here navigated is never a candidate, however convincing its
    login form looks. See the module docstring.
    """
    real = _real_pages(pages)
    if not real:
        return None, "no_page"

    host = (instance_host or "").lower()
    if host:
        for page in real:
            if host in str(page.url).lower():
                return page, ""

    if driven_url:
        exact = [page for page in real if str(page.url) == driven_url]
        if len(exact) == 1:
            return exact[0], ""
        # The launch case: the URL was handed to Chromium rather than to a goto,
        # so what came back after the redirect was never seen here. One tab means
        # there is nothing to confuse it with.
        if len(real) == 1:
            return real[0], ""

    return None, "no_instance_page"


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


def _credentials_accepted(page: Any) -> Optional[bool]:
    """Did the instance refuse what we submitted? True=no, False=yes, None=unread.

    The login form is the answer. Gone means accepted — signed in, or standing at
    an MFA challenge, and a credential the server already accepted cannot lock
    the account by being replayed. Still standing after the wait means refused.

    ``_selector_exists`` answers False for a page it could not read at all, which
    is the same shape as "the form is gone" and would hand the attempt back on no
    evidence. So each poll first proves the document still answers, and a page
    that stops answering returns None rather than the reassuring one.
    """
    deadline = time.time() + CREDENTIAL_VERDICT_S
    clear_reads = 0
    while True:
        try:
            page.evaluate("1")
        except Exception as exc:  # noqa: BLE001 - an unreadable page proves nothing
            logger.debug("Could not read the page after submitting the login: %s", exc)
            return None
        standing = any(_selector_exists(target, _PASSWORD_UNION) for target in _login_targets(page))
        clear_reads = 0 if standing else clear_reads + 1
        if clear_reads >= _VERDICT_STABLE_READS:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(_VERDICT_POLL_S)


# ---------------------------------------------------------------------------
# SSO: the user ID goes to the locator page, nothing else is typed
# ---------------------------------------------------------------------------


def _on_host(page: Any, host: str) -> bool:
    return bool(host) and (urlparse(str(page.url)).hostname or "").lower() == host.lower()


def _sso_field(page: Any) -> Optional[Any]:
    """The page or frame holding the SSO user-ID field, if one does."""
    for target in _login_targets(page):
        if _selector_exists(target, SSO_USER_FIELD):
            return target
    return None


def _wait_for_sign_in(page: Any) -> bool:
    """Is the tab asking anyone to sign in — a password form or the SSO field?"""
    for target in _login_targets(page):
        if _selector_exists(target, _SIGN_IN_UNION):
            return True
    try:
        page.wait_for_selector(_SIGN_IN_UNION, timeout=int(LOGIN_FORM_WAIT_S * 1000))
        return True
    except Exception:  # noqa: BLE001 - not a login page, or already signed in
        return False


def _locator_url(configured: str, instance_host: str) -> str:
    """The configured locator page — but only on this window's own instance.

    A login_url that points at another host (inherited from another profile, or
    simply wrong) is not somewhere to send this window's sign-in.
    """
    if configured and _host_of(configured) == instance_host.lower():
        return configured
    return f"https://{instance_host}{SSO_LOCATOR_PATH}"


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _sso_verdict(page: Any, locator_url: str) -> Optional[bool]:
    """Did the locator move on? True=redirected, False=user not found, None=unread.

    ``page.url`` is read rather than evaluated: a redirect tears the document
    down, and an evaluate that fails mid-navigation is exactly the success case.
    """
    locator_path = urlparse(locator_url).path or SSO_LOCATOR_PATH
    deadline = time.time() + SSO_VERDICT_S
    while True:
        try:
            current = urlparse(str(page.url))
        except Exception as exc:  # noqa: BLE001 - a closed tab proves nothing
            logger.debug("Could not read the tab after the SSO submit: %s", exc)
            return None
        if current.path != locator_path:
            return True
        if any(_selector_exists(t, SSO_ERROR_SELECTOR) for t in _login_targets(page)):
            return False
        if time.time() >= deadline:
            return None
        time.sleep(_VERDICT_POLL_S)


def fill_sso_user_id(page: Any, user: str, *, wait_ms: int) -> str:
    """Type the user ID into the SSO locator page and submit it — nothing else.

    For the MCP's own login window (``AuthManager``), where SSO has no password
    by design. Never raises; returns what happened. Not on the locator (already
    at the identity provider, or a custom login_url) is ``no_sso_field``: the
    window stays open for the user, and no password field is ever touched.
    """
    target = _sso_field(page)
    if target is None:
        try:
            page.wait_for_selector(SSO_USER_FIELD, timeout=wait_ms, state="visible")
        except Exception:  # noqa: BLE001 - not the locator page
            return "no_sso_field"
        target = _sso_field(page)
        if target is None:
            return "no_sso_field"
    try:
        target.fill(SSO_USER_FIELD, user)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not type into the SSO user ID field: %s", exc)
        return "fill_failed"
    if _click_first_matching(target, SSO_SUBMIT_SELECTORS):
        return "submitted"
    try:
        target.locator(SSO_USER_FIELD).press("Enter")
        return "submitted"
    except Exception:  # noqa: BLE001 - filled; the user can press Submit
        return "filled"


def _sso_sign_in(
    page: Any, state: WindowState, *, user: str, locator: str, marker_path: str
) -> Dict[str, Any]:
    if not _wait_for_sign_in(page):
        return {"status": "no_login_form", "url": str(page.url)}

    target = _sso_field(page)
    if target is None:
        if not _on_host(page, state.instance_host):
            # Already at the identity provider. Its password is the user's to
            # type — this mode never fills one.
            return {"status": "sso_at_idp", "user": user, "url": str(page.url)}
        # The instance's own login form: the wrong door in SSO mode.
        locator = _locator_url(locator, state.instance_host)
        try:
            page.goto(locator, wait_until="load", timeout=int(LOGIN_TIMEOUT_S * 1000 / 3))
            page.wait_for_selector(SSO_USER_FIELD, timeout=int(LOGIN_FORM_WAIT_S * 1000))
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            logger.info("SSO locator page did not show its user ID field: %s", exc)
            return {"status": "sso_no_locator", "url": locator}
        target = _sso_field(page)
        if target is None:
            return {"status": "sso_no_locator", "url": locator}
    locator = str(page.url)

    # Claimed BEFORE the submit, as for a password: a crash mid-submit must
    # not come back as a loop that keeps driving the user's tab.
    record_attempt(marker_path, state)
    try:
        target.fill(SSO_USER_FIELD, user)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not type into the SSO user ID field: %s", exc)
        return {"status": "fields_not_found", "url": locator}
    via = _click_first_matching(target, SSO_SUBMIT_SELECTORS)
    if via:
        via = f"click {via}"
    else:
        try:
            target.locator(SSO_USER_FIELD).press("Enter")
            via = "Enter"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not submit the SSO page with Enter: %s", exc)
            return {"status": "filled", "user": user, "mode": "sso"}

    moved = _sso_verdict(page, locator)
    if moved is None:
        return {"status": "sso_unverified", "user": user, "via": via}
    if not moved:
        return {"status": "sso_not_located", "user": user, "url": locator}
    # The locator found a provider; whatever happens at the IdP is the user's,
    # and a session that expires later deserves a fresh hand-off.
    release_attempt(marker_path)
    return {"status": "sso_redirected", "user": user, "via": via, "url": str(page.url)}


def auto_login(
    state: WindowState,
    *,
    credentials: Optional[Tuple[str, str]],
    marker_path: str,
    driven_url: str = "",
    sso: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    """Fill and submit the login form in the window, at most once per window.

    With ``sso`` (user ID, locator URL) the window is signed in through the SSO
    locator page instead, and ``credentials`` is not consulted.

    Never raises: a window that opened is a success even if signing it in was
    not, and the user can always type the password themselves. Every outcome is
    reported under ``status`` so the caller can say which one happened.
    """
    if sso:
        return _auto_login_sso(state, sso=sso, marker_path=marker_path, driven_url=driven_url)
    if not credentials:
        return {"status": "no_credentials"}
    if already_attempted(marker_path, state):
        return {"status": "already_attempted"}

    username, password = credentials
    require_playwright()

    def _work() -> Dict[str, Any]:
        with cdp_browser(state.cdp_endpoint) as browser:
            contexts = browser.contexts
            if not contexts:
                return {"status": "no_page"}
            page, refusal = _login_page(
                contexts[0].pages,
                instance_host=state.instance_host,
                driven_url=driven_url,
            )
            if page is None:
                return {"status": refusal}

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

            accepted = _credentials_accepted(page)
            if accepted is None:
                return {"status": "unverified", "user": username, "via": outcome["via"]}
            if not accepted:
                return {"status": "rejected", "user": username, "url": str(page.url)}
            release_attempt(marker_path)
            return {"status": "submitted", "user": username, "via": outcome["via"]}

    try:
        return run_off_loop(_work, timeout_s=LOGIN_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a failed login never fails the open
        logger.info("Debug window auto-login did not complete: %s", exc)
        return {"status": "error", "error": str(exc)[:200]}


def _auto_login_sso(
    state: WindowState, *, sso: Tuple[str, str], marker_path: str, driven_url: str
) -> Dict[str, Any]:
    if already_attempted(marker_path, state):
        return {"status": "already_attempted", "mode": "sso"}
    user, locator = sso
    require_playwright()

    def _work() -> Dict[str, Any]:
        with cdp_browser(state.cdp_endpoint) as browser:
            contexts = browser.contexts
            if not contexts:
                return {"status": "no_page"}
            page, refusal = _login_page(
                contexts[0].pages,
                instance_host=state.instance_host,
                driven_url=driven_url,
            )
            if page is None:
                return {"status": refusal}
            return _sso_sign_in(page, state, user=user, locator=locator, marker_path=marker_path)

    try:
        return run_off_loop(_work, timeout_s=LOGIN_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a failed login never fails the open
        logger.info("Debug window SSO sign-in did not complete: %s", exc)
        return {"status": "error", "error": str(exc)[:200]}


def describe(result: Dict[str, Any]) -> Optional[str]:
    """One line for the caller to pass on, or None when there is nothing to say."""
    status = result.get("status")
    if status == "sso_redirected":
        return (
            f"Sent user ID '{result.get('user')}' to the SSO page and it handed the window "
            "to the identity provider — finish signing in there (password, MFA)."
        )
    if status == "sso_at_idp":
        return (
            "The window is on the identity provider's sign-in page — sign in there. "
            "SSO mode never types a password."
        )
    if status == "sso_not_located":
        return (
            f"The SSO page did not accept user ID '{result.get('user')}' — check the "
            "username in the config, or sign in in the window. Not retried for this window."
        )
    if status == "sso_unverified":
        return (
            f"Submitted user ID '{result.get('user')}' on the SSO page but could not tell "
            "whether it moved on — look at the window."
        )
    if status == "sso_no_locator":
        return (
            f"Could not open the SSO page ({result.get('url')}) — sign in in the window. "
            "If this instance's SSO entry page is somewhere else, set login_url."
        )
    if status == "already_attempted" and result.get("mode") == "sso":
        return (
            "The SSO page already ran for this window and did not hand it on. Sign in in "
            "the window, or close it and open it again to try once more."
        )
    if status == "filled" and result.get("mode") == "sso":
        return (
            f"Typed user ID '{result.get('user')}' on the SSO page but found no Submit "
            "button — press it in the window."
        )
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
    if status == "rejected":
        return (
            f"The instance did not accept the saved credentials for '{result.get('user')}' — "
            "the login form is still showing. Fix the password in the config, then close "
            "the window and open it again."
        )
    if status == "unverified":
        return (
            f"Submitted the credentials for '{result.get('user')}' but could not read whether "
            "the instance accepted them — look at the window. The attempt is held as spent "
            "until a new window; closing this one and reopening frees it."
        )
    if status == "fields_not_found":
        return "A login form is showing but its fields were not recognized — sign in manually."
    if status == "no_instance_page":
        return (
            "Auto-login did not run: no tab in this window is on the instance, and it will "
            "not type the instance password into a form on some other site. Open an "
            "instance page (open_debug_window url=...) and it will sign in there."
        )
    if status == "already_attempted":
        return (
            "Auto-login already ran for this window and the login was not accepted. Close "
            "the window and open it again to try once more (a refused password is not "
            "retried, to avoid locking the account)."
        )
    if status == "error":
        return f"Auto-login could not run ({result.get('error')}) — sign in manually."
    if status == "no_login_form":
        # This used to be silent, on the reading that no form means the window is
        # already signed in. A COLD profile says otherwise: the first launch on a
        # fresh profile dir is slow, the tab was still on its way to the login
        # page when this looked, and "no password field" got reported as nothing
        # to report. A source that lags can only say NOT VISIBLE YET.
        return (
            "Auto-login found no password field, so it did nothing. If the window is "
            "showing a login page it had not finished loading yet — call "
            "open_debug_window again and it will sign in. If it is already signed in, "
            "this is the expected answer. The one attempt has NOT been spent either way."
        )
    if status == "no_page":
        return (
            "Auto-login had no tab to look at, so it did nothing. Open a page "
            "(open_debug_window url=...) and it will sign in there."
        )
    # no_credentials: nothing to fill, and nothing is wrong.
    return None


__all__ = [
    "CREDENTIAL_VERDICT_S",
    "LOGIN_FORM_WAIT_S",
    "LOGIN_TIMEOUT_S",
    "SSO_USER_FIELD",
    "already_attempted",
    "auto_login",
    "configured_username",
    "describe",
    "record_attempt",
    "release_attempt",
    "saved_credentials",
    "sso_login",
]
