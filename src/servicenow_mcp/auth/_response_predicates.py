"""HTTP response classification: authenticated vs login-redirect vs logout vs
ACL-block, plus BIG-IP routing-hint extraction and the stale-profile cookie set.

Extracted verbatim from auth_manager.py (v1.18.25). These encode hard-won
server-behavior knowledge (issues #37/#40 and the phantom-session saga); the
docstrings travel with the code so the "why" is never separated from it.
auth_manager re-imports every symbol so its namespace stays byte-identical.
"""

from typing import Optional

import requests

from ._url_predicates import _is_login_page_url


def _extract_bigip_routing_hint(response: requests.Response) -> Optional[tuple]:
    """v1.12.18: pull BIGipServerpool_<host>=<value> from a response's
    Set-Cookie if present. Returns ``(name, value)`` or ``None``.

    F5 BIG-IP uses BIGipServerpool to bind a client to a specific backend.
    When the client's existing BIG-IP cookie sticks it to backend A but
    the session was minted on backend B (because Playwright Chromium
    connected at a different time and got round-robined elsewhere), F5
    responds 302 with a Set-Cookie redirecting future requests to B.
    Absorbing that hint and retrying with the new BIG-IP cookie lets the
    same captured session work without a re-auth round.

    ``requests`` parses Set-Cookie into ``response.cookies`` correctly
    even when multiple cookies are comma-merged in the raw header
    (which Python's stdlib SimpleCookie chokes on). Only values that
    are non-empty and aren't being expired (no Max-Age=0 + past Expires)
    are returned.
    """
    try:
        for cookie in response.cookies:
            if not cookie.name or not cookie.name.startswith("BIGipServerpool"):
                continue
            if not cookie.value:
                continue  # an empty / revocation Set-Cookie — not a routing hint
            return (cookie.name, cookie.value)
    except Exception:  # noqa: BLE001
        return None
    return None


def _response_indicates_login_redirect(response: requests.Response) -> bool:
    location = (response.headers.get("Location") or "").lower()
    response_url = str(response.url or "").lower()
    return (
        "login.do" in location
        or "sysparm_type=login" in location
        or _is_login_page_url(response_url)
    )


# Cookies that bind a Chromium persistent profile to a specific server-side
# session. When the server has invalidated that session, leaving any of these
# in the profile causes the next ``login.do`` submission to be treated as a
# logout flow — the symptom is the user seeing the login window reopen on
# every tool call.
#
# Evolution of ``glide_mfa_remembered_browser`` handling:
#   v1.11.12 — preserved (didn't help, kept the phantom-session loop)
#   v1.11.14 — purged with everything else (broke the loop, but cost the
#              user one MFA prompt per session expiry)
#   v1.11.20 — back to preserved. The v1.11.18 server-side ``/logout.do``
#              flush is what actually breaks the phantom loop, so this
#              cookie can stay and let the user skip MFA on re-auth.
_STALE_PROFILE_COOKIE_NAMES: tuple[str, ...] = (
    "glide_session_store",
    "JSESSIONID",
    "glide_user",
    "glide_user_route",
    "glide_user_activity",
    "glide_node_id_for_js",
    "factor",
    "UX-Token",
    "__CJ_g_startTime",
)


def _response_indicates_authenticated_session(response: requests.Response) -> bool:
    if _response_indicates_login_redirect(response):
        return False

    # Defence-in-depth: ``requests`` silently follows 302 → /logout_success.do
    # and returns the logout-success HTML body with a 200 status, which
    # makes status-only checks misclassify the call as authenticated.
    # Inspect the redirect chain — any hop through a logout endpoint means
    # the original request was unauthenticated, regardless of the final
    # status. The body-marker check below catches some of these via
    # localized copy, but not all instances ship English / not all
    # logout pages contain the markers we look for.
    try:
        for hop in response.history or ():
            location = (hop.headers.get("Location") or "").lower()
            if (
                "logout_success" in location
                or "/logout.do" in location
                or location.startswith("/logout?")
            ):
                return False
    except Exception:
        pass

    try:
        body = (response.text or "")[:2000].lower()
    except Exception:
        body = ""

    unauthenticated_markers = [
        # Match both "user not authenticated" and "User is not authenticated"
        # (the literal ServiceNow REST 401 body). The earlier "user not
        # authenticated" form missed the "is" variant, so a dead session whose
        # probe returns 401+JSON was misread as authenticated and adopted.
        "not authenticated",
        "required to provide auth",
        "login with sso",
        "forgot password ?",
        "forgot password?",
        "log in | servicenow",
        "<title>log in",
    ]
    return not any(marker in body for marker in unauthenticated_markers)


def _response_redirected_through_logout(response: requests.Response) -> bool:
    """Return True if the response chain passed through ServiceNow logout.

    ``requests`` follows 302→/logout_success.do silently and surfaces the
    logout HTML with status 200, masking a torn-down session. v1.11.44 uses
    this signal as the runtime self-heal trigger: treat the response as a
    session-died 401 instead of a success.
    """
    try:
        for hop in response.history or ():
            location = (hop.headers.get("Location") or "").lower()
            if (
                "logout_success" in location
                or "/logout.do" in location
                or location.startswith("/logout?")
            ):
                return True
    except Exception:  # noqa: BLE001
        pass
    try:
        final_url = (getattr(response, "url", "") or "").lower()
        if "logout_success" in final_url:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _response_confirms_browser_probe_session(response: requests.Response) -> bool:
    """Confirm a reusable session only on POSITIVE evidence of authentication.

    Structural rule: a session is trusted only when the probe returns a positive
    authenticated signal — NOT merely the absence of a failure marker. Absence-of-
    failure was brittle: when an instance changed how it signals an unauthenticated
    REST call (e.g. 302->logout flipped to a bare 401+JSON after a clone), a dead
    session slipped through and was adopted. See issue #40.

      - 2xx   -> authenticated (still guard against a 200 logout-HTML body).
      - 403   -> authenticated but unauthorized for the probe path (an
                 authorization failure necessarily implies authentication passed).
      - 401   -> unauthenticated BY DEFAULT. Trusted only when the body POSITIVELY
                 indicates an ACL/permission block (some instances answer 401
                 instead of 403 for a probe-path ACL deny). A plain or
                 "not authenticated" 401 is rejected -> caller re-authenticates.
      - else  -> rejected.
    """
    status = response.status_code
    if 200 <= status < 300:
        return _response_indicates_authenticated_session(response)
    if status == 403:
        return not _response_indicates_login_redirect(response)
    if status == 401:
        return _response_indicates_acl_block(response)
    return False


def _response_indicates_acl_block(response: requests.Response) -> bool:
    """Return True only when a 401 JSON body clearly indicates an ACL/permission block
    (not a session/token expiry).

    ServiceNow returns 401 + JSON for both stale X-UserToken AND ACL denials, so we
    must inspect the body to tell them apart. When uncertain, return False so the
    caller treats it as a session issue and re-authenticates.
    """
    if response.status_code != 401:
        return False
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" not in content_type:
        return False
    if _response_indicates_login_redirect(response):
        return False
    try:
        body = (response.text or "")[:2000].lower()
    except Exception:
        return False
    # Strong session-expiry signals — definitively NOT ACL.
    # "not authenticated" matches both "user not authenticated" and the literal
    # "User is not authenticated" REST 401 body; "required to provide auth" is
    # ServiceNow's detail string for an unauthenticated REST call.
    session_expiry_markers = (
        "not authenticated",
        "required to provide auth",
        "session has expired",
        "session expired",
        "invalid session",
        "x-usertoken",
    )
    if any(marker in body for marker in session_expiry_markers):
        return False
    # Strong ACL signals
    acl_markers = (
        "insufficient rights",
        "access denied",
        "acl ",
        "operation against the requested object is not allowed",
        "no permission",
        "not authorized to",
    )
    return any(marker in body for marker in acl_markers)
