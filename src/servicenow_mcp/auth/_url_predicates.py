"""URL classification for ServiceNow login/MFA flow detection, plus the
browser-close error markers.

Extracted verbatim from auth_manager.py (v1.18.25). Pure string predicates.
auth_manager re-imports every symbol so its namespace stays byte-identical.
"""

from urllib.parse import urlparse

# Substrings (lowercase) that indicate the persistent Chromium context was
# closed before login completed OR that the user simply walked away without
# completing MFA before the polling-loop budget expired. Both shapes carry the
# same intent — the user did not authenticate this session — so they share the
# same path: short fixed cooldown, no exponential backoff. Without this the
# walk-away timeout would feed the regular failure counter and inflate the
# cooldown to 30/60/120s, making the next legitimate retry feel "stuck".
USER_CLOSE_ERROR_MARKERS = (
    "target closed",
    "browser closed",
    "browser was closed",
    "browser has been closed",
    "target page, context or browser has been closed",
    "connection closed",
    "login_cancelled_by_user",
    "timed out waiting for manual browser login/mfa completion",
)


def _looks_like_user_close(error_text: str) -> bool:
    """Return True if `error_text` (lowercased exception message) contains
    a marker indicating the browser/login window was closed before auth
    completed."""
    return any(marker in error_text for marker in USER_CLOSE_ERROR_MARKERS)


def _login_poll_should_keep_waiting(
    *,
    elapsed_ms: float,
    wait_budget_ms: int,
    use_headless: bool,
    on_auth_flow_page: bool,
    hard_cap_ms: int,
) -> bool:
    """Decide whether the login polling loop keeps waiting past its budget.

    Within budget: always keep waiting. Past budget: a VISIBLE window whose
    last-polled URL is still in the login/MFA family means the user is
    mid-authentication (typing a TOTP code, riding an SSO bounce) — closing
    the window there rips it away mid-entry, misfires the walk-away cooldown,
    and fails the tool call (observed 2026-07-05: poll.timeout while sitting
    on validate_multifactor_auth_code.do). Keep waiting, bounded by
    ``hard_cap_ms`` so a genuinely abandoned window still times out.
    Headless windows never extend — no human is typing into them.
    """
    if elapsed_ms < wait_budget_ms:
        return True
    if use_headless or not on_auth_flow_page:
        return False
    return elapsed_ms < hard_cap_ms


def _visible_window_mid_auth(*, on_login_url: bool, current_host: str, instance_host: str) -> bool:
    """True when a visible login window is still mid-authentication.

    Two shapes: (a) the URL is a ServiceNow login/MFA page (``on_login_url``),
    or (b) the window is parked on a FOREIGN host — an external SSO IdP such as
    Okta or ``login.microsoftonline.com`` — that is not the instance host.
    Both mean a human is still typing/authenticating, so the poll loop should
    extend past budget instead of ripping the window away (the 2026-07-05
    failure, which recurs on SSO-federated instances whose MFA happens on the
    IdP page, not a ServiceNow ``*.do`` URL). An empty/unknown current host
    (about:blank) is NOT treated as mid-auth, so it can never hold the loop
    open to its hard cap for no reason.
    """
    if on_login_url:
        return True
    ch = (current_host or "").strip().lower()
    ih = (instance_host or "").strip().lower()
    return bool(ch) and ch != ih


def _is_login_page_url(url: str) -> bool:
    """Return True when the URL still indicates ServiceNow login or MFA flow.

    Covers initial /login.do, the various MFA challenge / setup pages
    (including `validate_multifactor_auth_code.do` — the prompt the user
    actually sees while entering their code), SSO redirect bouncers, and
    sysparm hints that indicate auth is still mid-flight. The browser-
    state success gate keys off this — false negatives here cause us to
    declare login complete while the user is still typing an MFA code.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    # Explicit login/logout page markers
    login_markers = [
        "/login.do",
        "/login_redirect.do",
        "/auth_redirect.do",
        "/external_logout_complete.do",
        "/multi_factor_auth_view.do",
        "/multi_factor_auth_setup.do",
        "/validate_multifactor_auth_code.do",
        "/external_login_complete.do",
        "/sys_auth_info.do",
        "/mfa.do",
        "/mfa_setup.do",
    ]
    # Generic substring guards — catch instance- or version-specific
    # variants we have not seen explicitly. "/login_" covers ServiceNow's
    # post-MFA bounce pages like login_redirect.do and any future
    # login_* variants; "multifactor" / "mfa_" are narrow enough not to
    # false-positive on dashboard URLs.
    generic_substrings = ("multifactor", "/mfa_", "/mfa/", "/login_")
    return (
        any(marker in path for marker in login_markers)
        or any(sub in path for sub in generic_substrings)
        or "sysparm_type=login" in query
        or "sysparm_reauth=true" in query
        or "sysparm_mfa_needed=true" in query
        or "sysparm_direct=true" in query
        or path == "/login"
        or path == "/auth"
    )


def _is_mfa_challenge_url(url: str) -> bool:
    """Return True only for ServiceNow's MFA/TOTP *challenge* pages.

    A headless browser can never satisfy these — there is no human to type
    the code into the invisible window — so the login flow aborts fast and
    falls back to a visible window the moment it lands here.

    Deliberately NARROWER than ``_is_login_page_url``: it must NOT match the
    plain ``/login.do`` the success path transits for a beat before the
    remembered-browser cookie redirects to the dashboard, or we would kill a
    login that was about to succeed. Only the explicit multi-factor endpoints.
    """
    path = urlparse(url or "").path.lower()
    mfa_markers = (
        "/validate_multifactor_auth_code.do",
        "/multi_factor_auth_view.do",
        "/multi_factor_auth_setup.do",
        "/mfa.do",
        "/mfa_setup.do",
    )
    return any(marker in path for marker in mfa_markers) or "multifactor" in path
