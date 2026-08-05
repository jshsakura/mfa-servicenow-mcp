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

Because it is an HTTP call and not a menu, it is made from wherever the window
already is — a portal page, a workspace, a classic form, a list — and the page
comes back on the SAME url, re-rendered for the new user. No navigating to a
dialog and no clicking through a localized menu ('가장' / 'Impersonate'), which
would be a different DOM on every one of those screens.

Where the window is still decides three things, all of them measured on a live
instance rather than reasoned about:

- **off the instance entirely** (the window is a shared screen; somebody's
  intranet tab is a normal thing to find it on) — a relative POST would go to
  THAT site. The tab is driven to the instance, the switch is made and verified
  there, and the tab goes back where it was. It used to just hand back a
  sentence saying to open an instance page.
- **signed out** — the login page carries a ``g_ck`` of its own, because the
  guest session has one. So a signed-out window did not trip the "no token"
  branch; it POSTed, got a 401, and was told the account needs the impersonator
  role. Asked explicitly now, and it stops rather than relocating: no page on
  the instance can carry a session that does not exist.
- **Next Experience** (``/now/nav/ui/...``) — the shell has the token but names
  no user at all; the classic UI it wraps is an iframe inside a shadow root, and
  ``g_user`` is in there. The POST always worked here. The read after it did
  not, so a switch that HAD happened came back as "the page never reported a
  signed-in user" — see :func:`current_identity`.

And what the page becomes afterwards is nobody's to predict: the same url is a
different experience for every user, and a redirect away from it is the instance
saying this one may not see it. Reported (``landing_note``) rather than left for
the caller to notice.

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
from .session import read_effective_user

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
    """Source for the impersonate POST, run inside the window's own session.

    Takes whatever the caller has. Measured against a live instance: the
    endpoint accepts a ``user_name`` and a ``sys_id`` and answers 201 with
    ``{"result": {"user": ..., "impersonatedUser": ...}}``. It does NOT accept a
    display name — so rather than telling the caller to go and look up an id,
    a miss falls back to asking sys_user who that is and retries with the sys_id.
    Finding the user is the tool's job, not the caller's.
    """
    return """
    const target = %(target)s;
    const token = (window.g_ck || (window.NOW && window.NOW.g_ck) || '');
    const headers = {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'X-UserToken': token
    };

    const attempt = async (who) => {
      let response;
      try {
        response = await fetch('/api/now/ui/impersonate/' + encodeURIComponent(who), {
          method: 'POST', credentials: 'same-origin', headers: headers, body: '{}'
        });
      } catch (e) {
        return { sent: false, error: String((e && e.message) || e) };
      }
      let text = '';
      try { text = await response.text(); } catch (e) {}
      let became = '';
      try { became = String((JSON.parse(text).result || {}).impersonatedUser || ''); } catch (e) {}
      return {
        sent: true,
        ok: response.ok,
        status: response.status,
        became: became,
        body: text.slice(0, 200)
      };
    };

    // '^' separates ServiceNow query clauses; letting one through would let a
    // name append conditions to the lookup.
    const lookup = async (name) => {
      const safe = String(name).split('^').join(' ').trim();
      if (!safe) return [];
      const query = 'active=true^user_name=' + safe + '^ORemail=' + safe + '^ORname=' + safe;
      try {
        const r = await fetch(
          '/api/now/table/sys_user?sysparm_query=' + encodeURIComponent(query) +
          '&sysparm_fields=sys_id,user_name,name&sysparm_limit=6',
          { credentials: 'same-origin', headers: headers }
        );
        if (!r.ok) return [];
        return ((await r.json()).result) || [];
      } catch (e) {
        return [];
      }
    };

    let outcome = await attempt(target);
    if (outcome.sent && !outcome.ok && (outcome.status === 404 || outcome.status === 400)) {
      const matches = await lookup(target);
      if (matches.length === 1) {
        const resolved = matches[0];
        outcome = await attempt(resolved.sys_id);
        outcome.resolved = { from: target, user_name: resolved.user_name, name: resolved.name };
      } else if (matches.length > 1) {
        outcome.candidates = matches.map((m) => m.user_name + ' (' + m.name + ')');
      }
    }
    outcome.had_token = token ? true : false;
    return outcome;
    """ % {
        "target": json.dumps(str(target)),
    }


def current_identity(page: Any) -> Dict[str, Any]:
    """Who the page says it is, and whether it admits to impersonating.

    Reads the document AND its frames (``session.read_effective_user``), which
    is what makes this work on Next Experience: the shell names nobody, and a
    main-frame-only read turned a switch that HAD happened into "the page never
    reported a signed-in user" — a false failure on a state-changing action, and
    worse than a false success, because the next step is someone retrying a
    switch that already took effect.

    ``impersonating`` is None when nothing exposes the flag (an older UI, a
    document that has not booted) — which is not the same as False and must not
    be read as "this is definitely the real account".
    """
    reading = read_effective_user(page)
    if not reading:
        return {"user": "", "impersonating": None}
    identity = {"user": str(reading["user"]), "impersonating": reading.get("impersonating")}
    if reading.get("frame"):
        identity["frame"] = reading["frame"]
    return identity


def current_user(page: Any) -> str:
    """Who the page says it is, or '' when nothing readable is there yet."""
    return str(current_identity(page).get("user") or "")


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
    candidates = outcome.get("candidates") or []
    if candidates:
        # Several people answer to that name. Picking one for the caller is the
        # one thing worse than asking: the whole test would run as the wrong user.
        return f"'{target}' matches {len(candidates)} users — say which one: " + "; ".join(
            str(entry) for entry in candidates[:6]
        )
    if status == 404:
        return (
            f"No active user matched '{target}' ({status}) — not as a user_name, an "
            "email, a display name, or a sys_id."
        )
    if not outcome.get("had_token", True):
        return (
            f"The impersonate call was rejected ({status}) and the page carried no "
            "g_ck — the window is probably still on a login or SSO page."
        )
    body = str(outcome.get("body") or "").strip()
    return f"The impersonate call failed ({status}){f': {body}' if body else '.'}"


# Whether this document is a signed-out one. Deliberately separate from
# EFFECTIVE_USER_SCRIPT, which answers "who are we" and is used by the badge and
# every read: a signed-out page answers that with nothing, and "nothing" is also
# what an unbooted page answers.
_GUEST_SCRIPT = """
(() => {
  try {
    const name =
      (window.NOW && NOW.user && (NOW.user.userName || NOW.user.name)) ||
      (window.g_user && g_user.userName) ||
      (window.NOW && NOW.user_name) || null;
    if (!name) return null;
    return String(name).trim().toLowerCase() === 'guest';
  } catch (e) {
    return null;
  }
})()
"""


def signed_out(page: Any) -> Optional[bool]:
    """True when this page is a signed-out one, None when it does not say.

    Measured on a live instance and the reason this exists: **the login page
    carries a g_ck.** The guest session has a token like any other, so the
    "page carried no g_ck" branch in :func:`_explain` never fires on the one
    page it was written for, and a signed-out window came back as
    "the account needs the impersonator or admin role" — sending whoever read
    it to an admin to fix a permission that was never the problem.

    Only an explicit ``guest`` blocks. None means the page did not say, which is
    not evidence of being signed in and must not be reported as such.
    """
    try:
        result = page.evaluate(_GUEST_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - an unbooted page is not a verdict
        logger.debug("Signed-out read failed: %s", exc)
        return None
    return bool(result) if isinstance(result, bool) else None


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


def _goto(page: Any, url: str, timeout_ms: int) -> Optional[str]:
    """Point the tab at ``url``. Returns why it could not, or None."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return None
    except Exception as exc:  # noqa: BLE001 - reported, never raised at the caller
        return f"Could not open {url} in the window: {str(exc)[:160]}"


def _switch(
    page: Any,
    *,
    target: str,
    timeout_ms: int,
    instance_host: str = "",
    allow_discard: bool = False,
    carrier_url: str = "",
) -> Dict[str, Any]:
    """POST, reload, and read back who the session actually became.

    When the tab is not on the instance at all, the call cannot be carried from
    there — a relative POST would go to whatever site the window is on. Rather
    than handing back a sentence and stopping, the tab is driven to
    ``carrier_url`` on the instance, the switch is made and VERIFIED there, and
    then the tab goes back to where it was. The window is a shared screen, so it
    is put back the way it was found.

    Relocating is not offered as a way around the unsaved-input refusal: moving
    the tab destroys input exactly like the reload does, which is why that check
    now runs first, before anything moves.
    """
    before = current_user(page)
    if not target.strip():
        return {"ok": False, "error": "No user given to impersonate.", "before": before}

    # The switch reloads the page — and relocating moves it — so either way this
    # destroys unsaved input exactly like a navigation does, and gets the same
    # refusal. The user is mid-task by definition when there is something to lose.
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

    return_url = ""
    misplaced = _wrong_origin(page, instance_host)
    if misplaced:
        if not carrier_url:
            return {"ok": False, "error": misplaced, "before": before}
        return_url = _url(page)
        problem = _goto(page, carrier_url, timeout_ms)
        if problem:
            return {"ok": False, "error": f"{misplaced} {problem}", "before": before}
        still_misplaced = _wrong_origin(page, instance_host)
        if still_misplaced:
            return {"ok": False, "error": still_misplaced, "before": before}
        # Read on a page that can actually answer; the foreign one never could.
        before = current_user(page)

    # A signed-out window has a g_ck all the same (the guest session carries
    # one), so this cannot be left to the HTTP status to explain — see
    # :func:`signed_out`. Moving the tab does not fix it, so it is a stop.
    if signed_out(page) is True:
        return {
            "ok": False,
            "before": before,
            "error": (
                "The debug window is not signed in — the page is running as 'guest'. "
                "Impersonation runs in the window's own session, so sign in there "
                "first (the window has its own login, separate from the API's)."
            ),
            **({"relocated_to": _url(page)} if return_url else {}),
        }

    result = _switch_here(page, target=target, timeout_ms=timeout_ms, before=before)
    if return_url:
        result = _come_back(page, result, return_url=return_url, timeout_ms=timeout_ms)
    return result


def _come_back(
    page: Any, result: Dict[str, Any], *, return_url: str, timeout_ms: int
) -> Dict[str, Any]:
    """Put the tab back where it was, and say what the new user got there.

    The switch was made and verified on the carrier, so this cannot turn a
    successful switch into a failure — it is reported alongside, never instead.

    What the page becomes here is the part nobody can predict: the same URL is a
    different experience for every user, and a redirect away from it is the
    instance saying this one may not see it. That is worth reporting on its own,
    because a caller who asked to look at a screen as somebody else is now
    looking at a different screen.
    """
    returned = dict(result)
    returned["switched_on"] = _url(page)
    problem = _goto(page, return_url, timeout_ms)
    if problem:
        returned["return_failed"] = problem
        return returned
    landed = _url(page)
    returned["returned_to"] = landed
    if landed.split("#")[0] != return_url.split("#")[0]:
        returned["landing_note"] = (
            f"Going back to {return_url} as this user ended up at {landed} — the "
            "instance redirected it, so that page is probably not one they may see."
        )
    return returned


def _switch_here(page: Any, *, target: str, timeout_ms: int, before: str) -> Dict[str, Any]:
    """The switch itself, on a page already established as able to carry it."""
    url_before = _url(page)
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

    # The server names who the session became ("impersonatedUser" in the 201
    # body). That is the authority on the session; the page read below is the
    # authority on what is now on screen. Both are reported when they disagree,
    # because a session that switched under a document that did not is exactly
    # the state that makes a debugging session go sideways.
    became = str(outcome.get("became") or "")
    resolved = outcome.get("resolved") or None
    expected = became or target

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
        if now and (not _same(now, before) or _same(now, expected)):
            break
        if time.time() >= deadline:
            break
        time.sleep(_VERIFY_POLL_S)

    landed = _url(page)
    result: Dict[str, Any] = {
        "ok": True,
        "before": before,
        "now": now or became,
        "url": landed,
    }
    if resolved:
        result["resolved"] = resolved
    # The reload is meant to bring this screen back as itself, rendered for the
    # new user. When it comes back as a DIFFERENT url, the instance sent them
    # somewhere else — the same page is a different experience for every user,
    # and this one may not be theirs to see. Said, because the caller asked to
    # look at a specific screen as somebody else and is no longer on it.
    if url_before and landed.split("#")[0] != url_before.split("#")[0]:
        result["landing_note"] = (
            f"Reloading {url_before} as this user ended up at {landed} — the instance "
            "redirected it, so that page is probably not one they may see."
        )

    if not now:
        # The server said it switched and the page has not said anything yet:
        # a portal that boots its globals slowly, not a failure. Reported as
        # what it is rather than dressed up as either outcome.
        if became:
            result["unverified_on_page"] = (
                f"The instance switched the session to '{became}'; the page had not "
                "reported a user yet when this returned."
            )
            return result
        return {
            "ok": False,
            "before": before,
            "error": (
                f"The instance accepted the impersonation of '{target}' but the page "
                "never reported a signed-in user. Look at the window."
            ),
        }
    if _same(now, before) and not _same(now, expected):
        return {
            "ok": False,
            "before": before,
            "now": now,
            "error": (
                f"The instance answered {outcome.get('status')} but the session is "
                f"still '{now}'. Check that '{target}' is an active account."
            ),
        }
    return result


def home_user(page: Any, *, marker: Optional[Dict[str, Any]], login_user: str) -> str:
    """The account to go back to — never a user we are merely pretending to be.

    Learned from a live run that got this wrong: "whoever the page said we were
    before the switch" is only the account when the page was NOT already
    impersonating, and a user who used the avatar menu first makes it not be.
    So, in order:

    1. an existing marker's ``original`` — the start of the chain, recorded when
       the first switch happened;
    2. the configured login account, when the page admits to impersonating —
       the window signs itself in with those credentials, so that IS the account;
    3. the page's current user, when nothing says it is an impersonation.

    Returns '' when none of the three can answer, which the caller must report
    rather than paper over: sending the session "back" to the wrong user is
    worse than saying it does not know.
    """
    if marker and marker.get("original"):
        return str(marker["original"])
    identity = current_identity(page)
    if identity.get("impersonating"):
        return login_user
    return str(identity.get("user") or "") or login_user


def become(
    page: Any,
    *,
    target: str,
    marker_path: str,
    started_at: float,
    timeout_ms: int = 10_000,
    instance_host: str = "",
    allow_discard: bool = False,
    login_user: str = "",
    carrier_url: str = "",
) -> Dict[str, Any]:
    """Impersonate ``target`` in the window, and record who to go back to.

    The recorded original is the account, not the previous stop: switching from
    one impersonated user to another — or impersonating on top of one the user
    started by hand in the avatar menu — still ends up back at the real account.
    See :func:`home_user`.
    """
    existing = read_marker(marker_path, started_at) if marker_path else None
    home = home_user(page, marker=existing, login_user=login_user)
    result = _switch(
        page,
        target=target,
        timeout_ms=timeout_ms,
        instance_host=instance_host,
        allow_discard=allow_discard,
        carrier_url=carrier_url,
    )
    if not result.get("ok"):
        return result

    # Resolved BEFORE the switch, while the page could still be asked whether it
    # was impersonating — afterwards it always is, and the answer would be lost.
    original = home or str(result.get("before") or "")
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
    carrier_url: str = "",
) -> Dict[str, Any]:
    """End the impersonation and go back to the account the window signed in as.

    The marker is the first source, so any MCP session can end what another one
    started. The saved login username is the second: a user who impersonated by
    hand through the avatar menu left no marker, and going back is still the
    thing they want.
    """
    marker = read_marker(marker_path, started_at) if marker_path else None
    identity = current_identity(page)
    target = str((marker or {}).get("original") or fallback_user or "").strip()
    if not target:
        if identity.get("impersonating") is False:
            # The page is explicit: this session is the real one. Nothing to end.
            return {"ok": True, "now": identity.get("user") or "", "already": True}
        # Impersonating, or a page that does not say — either way this cannot be
        # answered, and guessing would send the session to the wrong user.
        return {
            "ok": False,
            "error": (
                f"The window shows '{identity.get('user') or 'nobody'}' and nothing "
                "records the account it signed in as. Impersonate that account by "
                "name to get back, or use the avatar menu in the window."
            ),
        }

    current = str(identity.get("user") or "")
    if current and _same(current, target) and not identity.get("impersonating"):
        clear_marker(marker_path)
        return {"ok": True, "now": current, "already": True}

    result = _switch(
        page,
        target=target,
        timeout_ms=timeout_ms,
        instance_host=instance_host,
        allow_discard=allow_discard,
        carrier_url=carrier_url,
    )
    if result.get("ok"):
        clear_marker(marker_path)
    return result


def describe_detected(
    detected: Optional[Dict[str, Any]], marker: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """The impersonation to report on a read, page-first.

    The page's own ``user_impersonating`` flag catches what a marker cannot: an
    impersonation started from the avatar menu, or one left by an MCP session
    whose marker was cleaned up. The marker only adds the account to go back to.
    Falls back to marker-only agreement for pages that do not expose the flag.
    """
    user = str((detected or {}).get("user") or "")
    if not user:
        return None
    flag = (detected or {}).get("impersonating")
    if flag:
        return {"as": user, "original": str((marker or {}).get("original") or "") or None}
    if flag is False:
        # The page says this is the real account; a marker claiming otherwise is
        # stale and reporting it would send the next question to the wrong user.
        return None
    return describe(marker, user)


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
    "current_identity",
    "describe_detected",
    "home_user",
    "clear_marker",
    "current_user",
    "describe",
    "post_script",
    "read_marker",
    "restore",
    "write_marker",
]
