"""Become another user in the shared debug window — the avatar menu, automated.

Why this belongs to the window and not to the API
-------------------------------------------------
Impersonation is server-side SESSION state: the cookie does not change, the
server re-points the session at another user. That is precisely why session.py
gives the window its own session — and precisely why impersonating *in the
window* is safe to automate. Nothing here can reach the API session the MCP
tools run on.

One window, one session, everybody
----------------------------------
There is one debug window per instance+user profile, and every MCP session
shares it. So an impersonation started by one conversation is what the next
conversation — and the person watching the screen — will be looking at. Three
things follow, and all three are implemented rather than documented:

- the "who were we before" note lives on DISK next to the window state, keyed to
  the window's ``started_at``, so any session can end an impersonation another
  one started, and a marker from a closed window never claims a fresh one;
- every impersonation is verified by re-reading the user off the page, so the
  answer is what the session actually became, not what was requested;
- the on-screen badge reads the user live (badge.py), so the human sees the
  switch without being told.

Mechanism
---------
``POST /api/now/ui/impersonate/<user_name-or-sys_id>`` — the same endpoint the
platform's own impersonate dialog and the OOB portal header widget call, issued
from inside the window so it carries that window's cookies and its ``g_ck``.
Ending an impersonation is the same call aimed back at the original user, which
is how the OOB widget does it too.

Because it is an HTTP call and not a menu, it works from wherever the window
already is — a portal page, a workspace, a classic form, a list — and the page
comes back on the SAME url, re-rendered for the new user. No navigating to a
dialog and no clicking through a localized menu ('가장' / 'Impersonate'), which
would be a different DOM on every one of those screens.

What guards it
--------------
- ``act_in_debug_window`` is already write-classified (write_guards), so the
  confirm gate and ``allow_writes=false`` cover this like any other write. There
  is deliberately no second approval on top: unlike ``eval``, this cannot run
  arbitrary code, cannot exceed what the instance already grants the account
  (the endpoint refuses without the impersonator/admin role), cannot touch the
  API session, and is undone by one step. Making it loud and reversible beats
  making it ceremonial.
- The switch RELOADS the page, so it refuses when the user has unsaved input,
  exactly as navigation does (capture.navigate). Losing someone's half-typed
  form to a background session change is the one damaging thing here.
- It refuses on a page that is not on the instance, rather than firing a
  cross-origin POST that would silently carry no session at all.

The POST is fixed source built here, not caller-supplied JavaScript: the target
is JSON-encoded into a string literal and passed through ``encodeURIComponent``,
so there is nothing for a caller to inject.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .capture import _dirty_fields
from .evaluate import run_in_page
from .session import EFFECTIVE_USER_SCRIPT

logger = logging.getLogger(__name__)

IMPERSONATE_ACTION = "impersonate"
END_IMPERSONATION_ACTION = "end_impersonation"

# The globals that carry the user name (NOW.user, g_user) land well after the
# document does, especially on Next Experience and the portal — the badge polls
# for the same reason. So the verification read polls too instead of declaring
# failure against a page that simply has not booted yet.
_VERIFY_POLL_S = 0.4
_MIN_VERIFY_S = 3.0


# ---------------------------------------------------------------------------
# The marker — one window's impersonation, readable by every MCP session
# ---------------------------------------------------------------------------


def read_marker(path: str, started_at: float) -> Optional[Dict[str, Any]]:
    """What this window is impersonating, or None.

    Keyed on the window's ``started_at``: a marker left behind by a window the
    user closed must not be reported as a live impersonation of the new one,
    which starts signed in as itself.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            recorded = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable impersonation marker at %s: %s", path, exc)
        return None
    try:
        if abs(float(recorded.get("started_at", -1.0)) - float(started_at)) >= 0.001:
            return None
    except (TypeError, ValueError):
        return None
    return recorded if recorded.get("as") else None


def write_marker(path: str, *, started_at: float, original: str, impersonated: str) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    payload = {
        "started_at": float(started_at),
        "original": original,
        "as": impersonated,
        "at": time.time(),
    }
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not record the impersonation: %s", exc)


def clear_marker(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not clear the impersonation marker: %s", exc)


# ---------------------------------------------------------------------------
# The switch itself
# ---------------------------------------------------------------------------


def post_script(target: str) -> str:
    """Source for the impersonate POST, run inside the window's own session."""
    return """
    const target = %(target)s;
    const token = (window.g_ck || (window.NOW && window.NOW.g_ck) || '');
    let response;
    try {
      response = await fetch('/api/now/ui/impersonate/' + encodeURIComponent(target), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-UserToken': token
        },
        body: '{}'
      });
    } catch (e) {
      return { sent: false, error: String((e && e.message) || e) };
    }
    let body = '';
    try { body = (await response.text()).slice(0, 200); } catch (e) {}
    return {
      sent: true,
      ok: response.ok,
      status: response.status,
      had_token: token ? true : false,
      body: body
    };
    """ % {
        "target": json.dumps(str(target)),
    }


def current_user(page: Any) -> str:
    """Who the page says it is, or '' when nothing readable is there yet."""
    try:
        result = page.evaluate(EFFECTIVE_USER_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - an unbooted page is not an error here
        logger.debug("Effective-user read failed during impersonation: %s", exc)
        return ""
    if isinstance(result, dict) and result.get("user"):
        return str(result["user"])
    return ""


def _url(page: Any) -> str:
    try:
        return str(page.url)
    except AttributeError:  # pragma: no cover - defensive
        return ""


def _same(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


def _explain(outcome: Dict[str, Any], target: str) -> str:
    """Turn an HTTP answer into the sentence that says what to do about it."""
    status = int(outcome.get("status") or 0)
    if status in (401, 403):
        return (
            f"The instance refused to impersonate '{target}' ({status}). The account the "
            "window is signed in as needs the impersonator or admin role."
        )
    if status == 404:
        return (
            f"No user '{target}' ({status}). Pass the user_name or the sys_id from "
            "sys_user — a display name will not resolve."
        )
    if not outcome.get("had_token", True):
        return (
            f"The impersonate call was rejected ({status}) and the page carried no "
            "g_ck — the window is probably still on a login or SSO page."
        )
    body = str(outcome.get("body") or "").strip()
    return f"The impersonate call failed ({status}){f': {body}' if body else '.'}"


def _wrong_origin(page: Any, instance_host: str) -> Optional[str]:
    """Why this page cannot carry the call, or None when it can.

    A relative POST from some other site would go to that site — no session, no
    cookies, and a 404 that reads like the endpoint is missing. Saying so beats
    firing it.
    """
    if not instance_host:
        return None
    try:
        host = (urlparse(str(page.url)).hostname or "").lower()
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        return None
    if not host:
        return (
            "The window has no page loaded yet. Open an instance page first "
            "(open_debug_window url=...)."
        )
    if host != instance_host.lower():
        return (
            f"The window is on '{host}', not on the instance ('{instance_host}'). "
            "Impersonation runs in the instance's own session — open an instance "
            "page in the window first."
        )
    return None


def _switch(
    page: Any,
    *,
    target: str,
    timeout_ms: int,
    instance_host: str = "",
    allow_discard: bool = False,
) -> Dict[str, Any]:
    """POST, reload, and read back who the session actually became."""
    before = current_user(page)
    if not target.strip():
        return {"ok": False, "error": "No user given to impersonate.", "before": before}

    misplaced = _wrong_origin(page, instance_host)
    if misplaced:
        return {"ok": False, "error": misplaced, "before": before}

    # The switch reloads the page, so it destroys unsaved input exactly like a
    # navigation does — and gets the same refusal. The user is mid-task by
    # definition when there is something to lose.
    if not allow_discard:
        dirty, basis = _dirty_fields(page)
        if dirty:
            return {
                "ok": False,
                "before": before,
                "blocked_by_unsaved_input": dirty,
                "input_basis": basis,
                "error": (
                    f"Switching user reloads this page and would discard input in "
                    f"{', '.join(dirty[:5])}. Pass discard_unsaved_input=true to go "
                    "ahead"
                    + (
                        ", though no keystroke was actually observed here — these "
                        "fields merely differ from their HTML defaults, which a "
                        "widget initializing itself also does."
                        if basis == "guessed"
                        else "."
                    )
                ),
            }

    sent = run_in_page(page, body=post_script(target))
    if not sent.get("ok"):
        return {
            "ok": False,
            "error": f"The page refused to run the impersonate call: {sent.get('error')}",
            "before": before,
        }
    outcome = sent.get("value")
    if not isinstance(outcome, dict):
        return {
            "ok": False,
            "error": "The impersonate call returned nothing usable.",
            "before": before,
        }
    if not outcome.get("sent"):
        return {
            "ok": False,
            "error": f"The impersonate request never left the page: {outcome.get('error')}",
            "before": before,
        }
    if not outcome.get("ok"):
        return {
            "ok": False,
            "error": _explain(outcome, target),
            "before": before,
            "status": outcome.get("status"),
        }

    # The session changed under the open document: everything on screen — the
    # globals, the ACLs the page was rendered with, the badge — is now stale.
    # A reload rather than a navigation, so whatever screen this is comes back
    # as itself, rendered for the new user. Nothing to navigate back from.
    try:
        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - a slow reload is not a failed switch
        logger.debug("Reload after impersonation did not settle: %s", exc)

    deadline = time.time() + max(_MIN_VERIFY_S, timeout_ms / 1000.0)
    now = ""
    while True:
        now = current_user(page)
        # Changed, or already the requested user: either way the read is final.
        if now and (not _same(now, before) or _same(now, target)):
            break
        if time.time() >= deadline:
            break
        time.sleep(_VERIFY_POLL_S)

    if not now:
        return {
            "ok": False,
            "before": before,
            "error": (
                f"The instance accepted the impersonation of '{target}' but the page "
                "never reported a signed-in user. Look at the window."
            ),
        }
    if _same(now, before) and not _same(now, target):
        return {
            "ok": False,
            "before": before,
            "now": now,
            "error": (
                f"The instance answered 200 but the session is still '{now}'. "
                f"Check that '{target}' is an active user_name."
            ),
        }
    return {"ok": True, "before": before, "now": now, "url": _url(page)}


def become(
    page: Any,
    *,
    target: str,
    marker_path: str,
    started_at: float,
    timeout_ms: int = 10_000,
    instance_host: str = "",
    allow_discard: bool = False,
) -> Dict[str, Any]:
    """Impersonate ``target`` in the window, and record who to go back to.

    The original is whoever the window was BEFORE the first impersonation —
    switching from one impersonated user to another keeps the first answer, so
    ``end_impersonation`` always lands back on the real account rather than on
    the previous stop along the way.
    """
    existing = read_marker(marker_path, started_at) if marker_path else None
    result = _switch(
        page,
        target=target,
        timeout_ms=timeout_ms,
        instance_host=instance_host,
        allow_discard=allow_discard,
    )
    if not result.get("ok"):
        return result

    original = str((existing or {}).get("original") or result.get("before") or "")
    if marker_path:
        write_marker(
            marker_path,
            started_at=started_at,
            original=original,
            impersonated=str(result.get("now") or target),
        )
    result["original"] = original
    return result


def restore(
    page: Any,
    *,
    marker_path: str,
    started_at: float,
    fallback_user: str = "",
    timeout_ms: int = 10_000,
    instance_host: str = "",
    allow_discard: bool = False,
) -> Dict[str, Any]:
    """End the impersonation and go back to the account the window signed in as.

    The marker is the first source, so any MCP session can end what another one
    started. The saved login username is the second: a user who impersonated by
    hand through the avatar menu left no marker, and going back is still the
    thing they want.
    """
    marker = read_marker(marker_path, started_at) if marker_path else None
    target = str((marker or {}).get("original") or fallback_user or "").strip()
    if not target:
        return {
            "ok": False,
            "error": (
                "Nothing records who this window was before. Impersonate your own "
                "user_name to get back, or use the avatar menu in the window."
            ),
        }

    current = current_user(page)
    if current and _same(current, target):
        clear_marker(marker_path)
        return {"ok": True, "now": current, "already": True}

    result = _switch(
        page,
        target=target,
        timeout_ms=timeout_ms,
        instance_host=instance_host,
        allow_discard=allow_discard,
    )
    if result.get("ok"):
        clear_marker(marker_path)
    return result


def describe(marker: Optional[Dict[str, Any]], window_user: str) -> Optional[Dict[str, Any]]:
    """The impersonation to report on a read, or None.

    The PAGE is the authority: a marker whose user no longer matches what the
    window shows is stale — the impersonation was ended in the window by hand —
    and reporting it would send an investigation after the wrong session.
    """
    if not marker or not window_user:
        return None
    if not _same(str(marker.get("as") or ""), window_user):
        return None
    return {"as": window_user, "original": str(marker.get("original") or "") or None}


__all__ = [
    "END_IMPERSONATION_ACTION",
    "IMPERSONATE_ACTION",
    "become",
    "clear_marker",
    "current_user",
    "describe",
    "post_script",
    "read_marker",
    "restore",
    "write_marker",
]
