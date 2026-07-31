"""Session context tools — read/switch the caller's current application + update set.

ServiceNow assigns a NEW record's scope from the session's *current application*,
and captures changes into the session's *current update set*. Neither is settable
via the Table API insert body (an explicit sys_scope there triggers a 403
cross-scope guard). The platform UI switches both through the "concourse picker"
session endpoints; this tool drives the same endpoints so the MCP can own its own
write context instead of forcing a manual trip through the ServiceNow UI.

These are session-only endpoints, so the whole tool is gated behind browser auth
(see CLAUDE.md "Auth Separation"). Every set_* action reads the context back and
only reports success when the read-back matches — so a rejected/!=expected switch
surfaces as a clear failure rather than a false positive.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from ..auth.auth_manager import AuthManager
from ..utils.config import AuthType, ServerConfig
from ..utils.registry import register_tool
from .sn_api import sn_query_page

logger = logging.getLogger(__name__)


def _is_browser_auth(config: ServerConfig) -> bool:
    """Return True when the active auth type is browser-based.

    Mirrors flow_designer_tools._is_browser_auth; defined locally to avoid a
    heavy cross-module import just for this gate.
    """
    return config.auth.type == AuthType.BROWSER


_APP_ENDPOINT = "/api/now/ui/concoursepicker/application"
_UPDATESET_ENDPOINT = "/api/now/ui/concoursepicker/updateset"


class ManageSessionContextParams(BaseModel):
    """Read or switch the current application / update set for this session."""

    action: str = Field(
        ...,
        description="get | set_app | set_update_set",
    )
    app_id: Optional[str] = Field(
        default=None, description="sys_scope sys_id (required for set_app)"
    )
    update_set_id: Optional[str] = Field(
        default=None,
        description="sys_update_set sys_id (set_update_set, or pass with set_app to set both)",
    )
    update_set_name: Optional[str] = Field(
        default=None,
        description="Update set name, resolved among in-progress sets (set_update_set or set_app)",
    )

    @model_validator(mode="after")
    def _validate(self) -> "ManageSessionContextParams":
        if self.action not in ("get", "set_app", "set_update_set"):
            raise ValueError("action must be one of: get, set_app, set_update_set")
        if self.action == "set_app" and not self.app_id:
            raise ValueError("app_id is required for action='set_app'")
        if self.action == "set_update_set" and not (self.update_set_id or self.update_set_name):
            raise ValueError(
                "update_set_id or update_set_name is required for action='set_update_set'"
            )
        return self


# Concoursepicker response shapes vary widely across releases/endpoints: the
# current selection may be a {current: {...}} object, a bare sys_id string, a
# top-level {sysId/value}, or an item flagged in a (possibly nested) list. The
# application picker on dev returned a shape the old parser read as empty —
# making a *successful* switch look like not_applied. These keys cover the
# known variants; the resolver tries them most-authoritative-first.
_ID_KEYS = ("sysId", "sys_id", "value", "id")
_NAME_KEYS = ("name", "displayValue", "display_value", "label")
_SELECTED_FLAGS = ("selected", "current", "isCurrent", "is_current")


def _selection_from_obj(obj: Any) -> Optional[Dict[str, str]]:
    """{sys_id, name} from a selection object, or a bare sys_id string."""
    if isinstance(obj, str):
        return {"sys_id": obj, "name": ""} if obj.strip() else None
    if not isinstance(obj, dict):
        return None
    sid = next((obj[k] for k in _ID_KEYS if obj.get(k)), None)
    if not sid:
        return None
    name = next((obj[k] for k in _NAME_KEYS if obj.get(k)), "")
    return {"sys_id": str(sid), "name": str(name)}


def _name_for_sys_id(container: Any, sys_id: str) -> str:
    """Look up a selection's display name in the picker's option list.

    The application picker returns ``current`` as a bare sys_id with the names
    living in ``result.list``; resolve the name so the success message reads
    'BPM' rather than a raw sys_id.
    """
    items = container.get("list") if isinstance(container, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("sysId") or item.get("sys_id") or "") == sys_id:
                return str(item.get("name") or item.get("displayValue") or "")
    return ""


# The update-set picker labels every entry with its application: "Pilot [My App]".
# That label is NOT the name. sys_update_set.name holds "Pilot", every reference
# display value shows "Pilot", and update_set_name resolves against "Pilot" — so
# handing the label back to the caller produced a name that could not be fed into
# the very tool that accepts one, and made one set look like two.
_PICKER_LABEL_RE = re.compile(r"^(?P<name>.+?)\s*\[(?P<app>[^\[\]]+)\]$")


def split_picker_label(label: str) -> Tuple[str, str]:
    """('Pilot [My App]') -> ('Pilot', 'My App'). No suffix -> (label, '').

    Deliberately conservative: only a bracketed group at the very END is a
    suffix. A set genuinely named "Release [Q3]" keeps its name, because the
    application it belongs to is read from the record, never from the string.
    """
    match = _PICKER_LABEL_RE.match((label or "").strip())
    if not match:
        return (label or "").strip(), ""
    return match.group("name").strip(), match.group("app").strip()


def _normalize_update_set_selection(selection: Dict[str, str]) -> Dict[str, str]:
    """Split a picker label into the name and the application it was tagged with.

    Applied at the READ boundary rather than at each call site: every consumer
    of "the current update set" wants the name that round-trips, and one that
    has to remember to normalize is one that will forget.
    """
    name, application = split_picker_label(str(selection.get("name") or ""))
    normalized = {**selection, "name": name}
    if application:
        normalized["application"] = application
    return normalized


def _find_flagged_selection(node: Any) -> Optional[Dict[str, str]]:
    """Depth-first search for the object flagged as the active selection."""
    if isinstance(node, dict):
        if any(node.get(flag) for flag in _SELECTED_FLAGS):
            sel = _selection_from_obj(node)
            if sel:
                return sel
        for value in node.values():
            sel = _find_flagged_selection(value)
            if sel:
                return sel
    elif isinstance(node, list):
        for item in node:
            sel = _find_flagged_selection(item)
            if sel:
                return sel
    return None


def _picker_value(payload: Dict[str, Any]) -> Dict[str, str]:
    """Extract {sys_id, name} of the current selection from a concoursepicker body.

    Tolerant of every observed shape: an explicit ``current`` (object or bare
    sys_id), selection fields directly on ``result``, or a flagged item nested
    anywhere in the structure. Falls back to empty strings so callers always get
    a stable shape.
    """
    result = payload.get("result", payload) if isinstance(payload, dict) else payload

    # 1) Explicit current — most authoritative (dict or bare sys_id string).
    if isinstance(result, dict) and result.get("current") is not None:
        sel = _selection_from_obj(result["current"])
        if sel:
            if not sel["name"]:
                sel["name"] = _name_for_sys_id(result, sel["sys_id"])
            return sel

    # 2) Selection fields directly on the result object.
    if isinstance(result, dict):
        sel = _selection_from_obj(result)
        if sel:
            return sel

    # 3) A flagged item anywhere (top-level list, or a list nested under result).
    sel = _find_flagged_selection(result)
    if sel:
        return sel

    return {"sys_id": "", "name": ""}


def _resolve_update_set_by_name(
    config: ServerConfig, auth_manager: AuthManager, name: str
) -> Dict[str, Any]:
    """Resolve an update set *name* to a sys_id, preferring in-progress sets.

    Only in-progress sets are selectable, so the name is matched against those
    first; an exact match wins over a substring. Returns {"sys_id", "name",
    "application"} on a unique hit, or {"error", "message", "candidates"?} when
    none/ambiguous.

    A caller may pass back a picker label ("Pilot [My App]") because that is
    what an earlier response showed them. The suffix is stripped before the
    query and used as a tie-breaker afterwards, so the round-trip works instead
    of returning not_found for a set that plainly exists.
    """
    requested_name, requested_app = split_picker_label(name)
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_set",
            query=f"state=in progress^nameLIKE{requested_name}^ORDERBYname",
            fields="sys_id,name,state,application",
            limit=20,
            offset=0,
            display_value=True,
        )
    except Exception as exc:
        logger.warning("Failed to resolve update set name '%s': %s", name, exc)
        return {"error": "resolve_failed", "message": f"Could not look up update set: {exc}"}

    if not rows:
        return {
            "error": "not_found",
            "message": (
                f"No in-progress update set matching '{requested_name}'. Only in-progress "
                "sets can be selected — check the name or create one first."
            ),
        }

    exact = [
        r for r in rows if str(r.get("name", "")).strip().lower() == requested_name.strip().lower()
    ]
    chosen = exact if exact else rows

    # An application given in the label narrows a same-name collision without a
    # second round trip — it is exactly the information that tells them apart.
    if len(chosen) > 1 and requested_app:
        by_app = [r for r in chosen if _display(r.get("application")).strip() == requested_app]
        if len(by_app) == 1:
            chosen = by_app

    if len(chosen) > 1:
        candidates: List[Dict[str, str]] = [
            {
                "sys_id": str(r.get("sys_id") or ""),
                "name": str(r.get("name") or ""),
                # Without this the list is N visually identical rows, which is
                # how a same-name pair became impossible to tell apart.
                "application": _display(r.get("application")) or "unknown",
            }
            for r in chosen
        ]
        same_name = len({c["name"].strip().lower() for c in candidates}) == 1
        detail = (
            f"{len(chosen)} in-progress update sets share the name '{requested_name}', "
            f"differing only by application ({', '.join(c['application'] for c in candidates)})"
            if same_name
            else f"'{requested_name}' matches {len(chosen)} in-progress update sets"
        )
        return {
            "error": "ambiguous",
            "message": (
                f"{detail}. The name cannot identify one of them — pass "
                "update_set_id=<sys_id> from the candidates below."
            ),
            "candidates": candidates,
        }
    row = chosen[0]
    return {
        "sys_id": str(row.get("sys_id") or ""),
        "name": str(row.get("name") or ""),
        "application": _display(row.get("application")),
    }


def _ui_context_headers(config: ServerConfig) -> Dict[str, str]:
    """Headers that make a request look UI-driven to ServiceNow.

    The concoursepicker lives under ``/api/now/ui`` — a session-mutating UI
    endpoint that enforces same-origin (Referer/Origin) on top of the
    X-UserToken the Table API already accepts. Without them the PUT is rejected
    403 and the GET reads an empty current app, even for an admin whose token
    works fine for Table API writes. We attach these ONLY to the concoursepicker
    calls (not the global request path, which dropped Referer for unrelated
    reasons — see auth_manager) so the supported scope switch actually applies.
    """
    base = config.instance_url.rstrip("/")
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
    return {
        "Referer": f"{base}/",
        "Origin": origin,
        "X-WantSessionNotificationMessages": "true",
    }


def _response_debug(response: Any) -> Dict[str, Any]:
    """Compact, paste-safe snapshot of a raw HTTP response for diagnostics.

    When a switch is accepted (no 403) yet the read-back still shows no current
    selection, the cause is a request/response *shape* mismatch with this
    instance's concoursepicker — which only the raw payload reveals. Surfacing
    it lets us fix the parser/body for that instance instead of guessing.
    """
    status = getattr(response, "status_code", 0)
    body = ""
    try:
        body = (response.text or "")[:600]
    except Exception:
        body = ""
    ctype = ""
    try:
        ctype = str((getattr(response, "headers", {}) or {}).get("Content-Type", ""))
    except Exception:
        ctype = ""
    return {"status": status, "content_type": ctype, "body": body}


def _get_current_raw(
    config: ServerConfig,
    auth_manager: AuthManager,
    endpoint: str,
    *,
    raise_on_error: bool = False,
) -> tuple[Dict[str, str], Dict[str, Any]]:
    """Read the current selection; return (parsed, raw-response-debug)."""
    url = f"{config.instance_url.rstrip('/')}{endpoint}"
    response = auth_manager.make_request(
        "GET", url, timeout=config.timeout, headers=_ui_context_headers(config)
    )
    if raise_on_error:
        response.raise_for_status()
    try:
        payload = response.json()
    except Exception:
        payload = {}
    parsed = _picker_value(payload if isinstance(payload, dict) else {})
    if endpoint == _UPDATESET_ENDPOINT:
        # ONE place, so no caller can forget: everything downstream — the
        # Default check, the push confirmation, the awareness stamp on writes —
        # sees the name sys_update_set actually stores.
        parsed = _normalize_update_set_selection(parsed)
    dbg = _response_debug(response)
    # Log the raw shape so a parser/shape issue is diagnosable from the log file
    # alone (the body is otherwise only in the tool response's diagnostics).
    logger.debug(
        "concoursepicker GET %s -> status=%s parsed_sys_id=%r body=%s",
        endpoint,
        dbg["status"],
        parsed.get("sys_id"),
        dbg["body"],
    )
    return parsed, dbg


def _get_current(config: ServerConfig, auth_manager: AuthManager, endpoint: str) -> Dict[str, str]:
    parsed, _ = _get_current_raw(config, auth_manager, endpoint, raise_on_error=True)
    return parsed


def _put_current(
    config: ServerConfig, auth_manager: AuthManager, endpoint: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    """PUT a selection; return raw-response-debug (status/content_type/body).

    Does not raise on HTTP error — the caller inspects the status so it can both
    surface the server's reason and attach the payload for diagnosis.
    """
    url = f"{config.instance_url.rstrip('/')}{endpoint}"
    response = auth_manager.make_request(
        "PUT", url, json=body, timeout=config.timeout, headers=_ui_context_headers(config)
    )
    dbg = _response_debug(response)
    logger.debug(
        "concoursepicker PUT %s body=%r -> status=%s resp_body=%s",
        endpoint,
        body,
        dbg["status"],
        dbg["body"],
    )
    return dbg


def _browser_only_error() -> Dict[str, Any]:
    return {
        "success": False,
        "error": "browser_auth_required",
        "message": (
            "Switching the current application / update set uses session-only "
            "endpoints, available with browser auth only. With basic/OAuth/API-key "
            "auth, set the context in the ServiceNow UI (Developer picker) instead."
        ),
    }


def _set_and_verify(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    endpoint: str,
    body: Dict[str, Any],
    expected_id: str,
    label: str,
) -> Dict[str, Any]:
    """PUT a new selection, then read it back. Success only if read-back matches.

    On any failure the raw concoursepicker GET/PUT payloads are attached under
    ``diagnostics`` so a shape mismatch on a specific instance can be fixed from
    evidence rather than guessed at.
    """
    try:
        put_dbg = _put_current(config, auth_manager, endpoint, body)
    except Exception as exc:  # network only — HTTP errors come back as a status
        logger.warning("Failed to set %s: %s", label, exc)
        return {"success": False, "error": "set_failed", "message": f"Set {label} failed: {exc}"}

    if put_dbg["status"] >= 400:
        detail = f" — {put_dbg['body'][:200]}" if put_dbg.get("body") else ""
        return {
            "success": False,
            "error": "set_failed",
            "message": f"Set {label} failed: HTTP {put_dbg['status']} from {endpoint}{detail}",
            "diagnostics": {"put": put_dbg},
        }

    try:
        current, read_dbg = _get_current_raw(config, auth_manager, endpoint)
    except Exception as exc:
        logger.warning("Set %s but read-back failed: %s", label, exc)
        return {
            "success": False,
            "error": "verify_failed",
            "message": f"Set {label} sent but could not confirm: {exc}",
            "diagnostics": {"put": put_dbg},
        }

    if current.get("sys_id") != expected_id:
        return {
            "success": False,
            "error": "not_applied",
            "message": (
                f"{label} did not switch — requested '{expected_id}', current is "
                f"'{current.get('sys_id')}'. The PUT was accepted (HTTP {put_dbg['status']}) "
                "but the read-back shows no/different current — likely a request- or "
                "response-shape mismatch with this instance's concoursepicker. The raw "
                "GET/PUT payloads are under 'diagnostics' — share them to pin the exact shape."
            ),
            "current": current,
            "diagnostics": {"put": put_dbg, "readback": read_dbg},
        }
    return {
        "success": True,
        "message": f"Current {label} is now {current.get('name') or expected_id}",
        "current": current,
    }


def set_application_scope(
    config: ServerConfig, auth_manager: AuthManager, app_sys_id: str
) -> Dict[str, Any]:
    """Set the session's current application scope to *app_sys_id* (a sys_scope
    sys_id), verifying the switch. Browser auth only; never raises.

    Used by the push flow to align the session scope to the component's scope
    BEFORE writing: ServiceNow rejects a REST write to a scoped record when the
    session's current app is a different scope, even though the same user can
    save it in the in-scope UI.
    """
    if not _is_browser_auth(config) or not app_sys_id:
        return {"success": False, "error": "unavailable"}
    try:
        return _set_and_verify(
            config,
            auth_manager,
            endpoint=_APP_ENDPOINT,
            body={"value": app_sys_id, "appId": app_sys_id, "app_id": app_sys_id},
            expected_id=app_sys_id,
            label="application",
        )
    except Exception as exc:  # never let a scope-switch attempt break the caller
        logger.warning("set_application_scope failed: %s", exc)
        return {"success": False, "error": "exception", "message": str(exc)}


def _apply_update_set(
    config: ServerConfig,
    auth_manager: AuthManager,
    update_set_id: Optional[str],
    update_set_name: Optional[str],
) -> Dict[str, Any]:
    """Resolve (by name if needed) and switch the session's current update set."""
    if not update_set_id:
        if not update_set_name:
            return {
                "success": False,
                "error": "missing_update_set",
                "message": "update_set_id or update_set_name is required.",
            }
        resolved = _resolve_update_set_by_name(config, auth_manager, update_set_name)
        if resolved.get("error"):
            return {"success": False, **resolved}
        update_set_id = resolved["sys_id"]
    assert update_set_id  # narrowed: set by param or resolved above
    return _set_and_verify(
        config,
        auth_manager,
        endpoint=_UPDATESET_ENDPOINT,
        body={"value": update_set_id, "sysId": update_set_id, "sys_id": update_set_id},
        expected_id=update_set_id,
        label="update set",
    )


def get_current_update_set(
    config: ServerConfig, auth_manager: AuthManager
) -> Optional[Dict[str, str]]:
    """Read the session's current update set, or None if unavailable.

    Browser auth only; never raises. Used to detect a *silent* update-set change
    that ServiceNow performs as a side effect of switching the current app — so a
    create can warn instead of capturing into the wrong (often "Default") set.
    """
    if not _is_browser_auth(config):
        return None
    try:
        return _get_current(config, auth_manager, _UPDATESET_ENDPOINT)
    except Exception as exc:
        logger.warning("Could not read current update set: %s", exc)
        return None


def is_default_update_set(update_set: Optional[Dict[str, str]]) -> bool:
    """True if the selection looks like a system 'Default' update set.

    Capturing app changes into Default is almost always an accident, so create
    paths flag it. Matched by name (case-insensitive) since the sys_id differs
    per application.

    The picker labels it "Default [Global]", and an exact match against that
    string is False — which would have silently dropped the one warning that
    costs a deploy. The label is split here as well as at the read boundary, so
    a caller holding a raw picker value still gets the right answer.
    """
    if not update_set:
        return False
    name, _ = split_picker_label(str(update_set.get("name", "")))
    return name.strip().lower() == "default"


# sys_update_set states that provably cannot RECEIVE a capture any more. Only a
# state on THIS list silences the warning.
#
# The inverse list ("open == 'in progress', everything else is closed") was the
# wrong way round: an unrecognised value — a state this vocabulary does not know,
# a localized or customized choice — would be read as closed and the warning
# dropped. That fails toward the quiet answer, which is the one failure direction
# this codebase does not accept. Unknown now keeps warning.
_CLOSED_UPDATE_SET_STATES = {"complete", "committed", "closed", "ignore", "released"}


def _read_update_set(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str
) -> Optional[Dict[str, str]]:
    """State + application for one update set, by sys_id. None when unreadable.

    The push check used to describe the OTHER set — "two in-progress sets share
    this name" — without ever looking it up. It had the sys_id in hand the whole
    time and inferred the rest from a name match, so a pair of COMPLETED sets in
    a DIFFERENT application got reported as a live split of the current work.
    Raw values (display_value=False) so the state compares deterministically
    against a fixed vocabulary rather than a localized label.
    """
    if not sys_id:
        return None
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_set",
            query=f"sys_id={sys_id}",
            fields="sys_id,name,state,application",
            limit=1,
            offset=0,
            display_value=False,
        )
    except Exception as exc:
        logger.warning("Could not read update set %s: %s", sys_id, exc)
        return None
    if not rows:
        return None
    row = rows[0]
    return {
        "sys_id": str(row.get("sys_id") or ""),
        "name": str(row.get("name") or ""),
        "state": str(row.get("state") or "").strip().lower(),
        "application": _display(row.get("application")),
    }


def check_update_set_for_push(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str = "",
    sys_id: str = "",
) -> Optional[Dict[str, str]]:
    """Non-blocking pre-write check on WHERE this change is about to be captured.

    Everything here is read from state we already hold: the current update set is
    live session state, and ``get_last_update_set_for_record`` reads THIS
    instance's ``sys_update_xml`` for THIS record. Both are inherently
    instance-/session-scoped, so across a prod/dev/test multi-session each push
    compares its own instance's last-capture set against its own session's current
    set — no cross-instance bookkeeping needed.

    Returns None (silence — a correctly-targeted push pays no tokens to say so)
    when the set cannot be read at all (basic/OAuth auth — the picker is
    session-only), and for the common good case. It speaks up for two situations:

    1. **Default** — changes captured into 'Default' are not retrievable and never
       promote, so the push lands on this instance only and silently fails to ship.
       This is a warning: it costs you the deploy.
    2. **Set switched since you last worked this record** — the current session set
       differs from the one this record was last captured into. This is a
       confirmation, not a warning: switching is often deliberate (a new feature
       set), but doing it unintentionally splits one logical change across two
       sets. Silent when they match, or when the record has no prior capture (first
       edit) — there is nothing to have switched away from.

    Deliberately does NOT create or switch a set. Creating a sys_update_set as a
    side effect of a push writes a record nobody asked for, and a wrong guess
    splits one logical change across two sets — a worse failure than the note.
    Must be called AFTER any scope alignment: switching the current application
    switches the update set with it, so the set we are about to capture into is
    only knowable once the session is in its final state.
    """
    us = get_current_update_set(config, auth_manager)
    if us is None:
        return None  # unreadable (basic/OAuth) — stay silent, never guess

    # 1. Default — the change won't ship. Highest-severity, reported first.
    if is_default_update_set(us):
        return {
            "update_set": us.get("name") or "Default",
            "warning": (
                "The session's current update set is 'Default'. Changes captured there are NOT "
                "retrievable and never promote to another instance — this push lands on this "
                "instance only and will be missing from any release built from an update set."
            ),
            "recommended_action": (
                "Switch to a real update set — manage_changeset(action='create', name=..., "
                "application=<scope>) then manage_session_context(action='set_update_set', "
                "update_set_name=...) — and then re-SAVE this record so it is captured there. "
                "A plain re-push will NOT recapture it: local now equals remote, so there is "
                "nothing left to write."
            ),
        }

    # 2. Named set, but not the one this record was last worked in — confirm intent.
    if not (table and sys_id):
        return None
    current_id = (us.get("sys_id") or "").strip()
    last = get_last_update_set_for_record(config, auth_manager, table, sys_id)
    last_id = (last or {}).get("sys_id", "").strip()
    if not last_id or last_id == current_id:
        return None  # first edit, or still in the same set — nothing to confirm
    # The read boundary already split the picker's label, so `application` is
    # normally right here; the split is kept as a fallback for a caller holding
    # a raw picker value.
    current_name, split_app = split_picker_label(us.get("name") or current_id)
    current_app = us.get("application") or split_app
    last_name, last_app = split_picker_label((last or {}).get("name") or last_id)
    last_app = (last or {}).get("application") or last_app

    # Look the OTHER set up. We have had its sys_id all along; describing it from
    # a name match instead is what turned two COMPLETED sets in a different
    # application into "two in-progress sets are both named X, your change is
    # split". Worse, the advice that followed — switch back and re-save — cannot
    # be carried out on a closed set, so it sent the caller at an impossible fix.
    last_record = _read_update_set(config, auth_manager, last_id)
    last_state = (last_record or {}).get("state", "")
    if last_record:
        last_name = last_record.get("name") or last_name
        last_app = last_record.get("application") or last_app
        if last_state in _CLOSED_UPDATE_SET_STATES:
            # Closed: it cannot receive this change, so nothing is being split
            # that anyone could rejoin. Sequential work across releases is the
            # normal case and stays silent.
            return None
    by = (last or {}).get("by") or ""
    at = (last or {}).get("at") or ""
    # Attribute the earlier capture. A bare "the set differs" reads as "you
    # switched", so a push after someone else's edit sends the developer hunting
    # for a mistake they never made.
    who = f" by {by}" if by else ""
    when = f" on {at}" if at else ""

    a, b = current_name.strip().lower(), last_name.strip().lower()
    collides = bool(a) and a == b

    # How to switch back. With two sets sharing a name, a name cannot say which
    # one — recommending it would send the caller into an ambiguity error, or
    # worse, into the other set.
    switch_by = f"update_set_id='{last_id}'" if collides else f"update_set_name='{last_name}'"
    out = {
        "current_update_set": current_name,
        "current_update_set_id": current_id,
        "last_worked_update_set": last_name,
        "last_worked_update_set_id": last_id,
        "last_worked_by": by,
        "last_worked_at": at,
        "confirm": (
            f"This record was last captured into update set '{last_name}'{who}{when}; this "
            f"session's set is '{current_name}'. Nothing was created or switched — this is a "
            f"read of where the two captures land. If that earlier capture was someone else's "
            f"session or an intentional new feature set, push as-is. Otherwise switch with "
            f"manage_session_context(action='set_update_set', {switch_by}) "
            f"and re-SAVE, so one logical change is not split across two sets."
        ),
    }
    if current_app:
        out["current_update_set_application"] = current_app
    if last_app:
        out["last_worked_update_set_application"] = last_app

    if last_state:
        out["last_worked_update_set_state"] = last_state
    if collides:
        # The nastiest shape: two sets, one name. Everything that identifies a
        # set by name — this confirmation, the picker label, a human reading a
        # release note — points at both, so the sys_id has to lead.
        #
        # "in progress" is only claimed for a set we actually read as such. The
        # state is the whole difference between "your change is split across two
        # live sets" and "a set with the same name shipped last month".
        apps = f" ('{current_app}' vs '{last_app}')" if current_app and last_app else ""
        both_open = bool(last_state) and last_state not in _CLOSED_UPDATE_SET_STATES
        which = "in-progress " if both_open else ""
        out["note"] = (
            f"Two DIFFERENT {which}update sets are both named '{current_name}'{apps} — "
            f"current is {current_id}, the earlier capture went to {last_id}"
            + (f" (state '{last_state}')" if last_state and not both_open else "")
            + f". Identify them by sys_id, not by name: update_set_name='{current_name}' "
            f"cannot pick one."
        )
    elif a and b and (a.startswith(b) or b.startswith(a)):
        # Near-identical names (a suffixed variant) read as one set, so a split
        # into two is easy to miss exactly where it matters most.
        out["note"] = (
            f"'{current_name}' and '{last_name}' are two DIFFERENT update sets whose names "
            f"only differ by a suffix — promoting one will not carry the other."
        )
    return out


def get_last_update_set_for_record(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str
) -> Optional[Dict[str, str]]:
    """Return the update set a record was most recently captured into, or None.

    Every captured change writes a sys_update_xml row whose ``name`` is
    ``<table>_<sys_id>``; the newest one's ``update_set`` is where the last edit
    landed. Used to warn before an edit goes into a *different* set than the one
    the record was last modified in. Browser-agnostic (Table API read); never
    raises — returns None when unknown so callers stay non-blocking on failure.
    """
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_xml",
            query=f"name={table}_{sys_id}^ORDERBYDESCsys_updated_on",
            fields="sys_id,name,update_set,sys_updated_on,sys_updated_by",
            limit=1,
            offset=0,
            display_value=True,
        )
    except Exception as exc:
        logger.warning("Could not read last update set for %s/%s: %s", table, sys_id, exc)
        return None
    if not rows:
        return None
    row = rows[0]
    us = row.get("update_set")
    if isinstance(us, dict):
        out = {"sys_id": str(us.get("value") or ""), "name": str(us.get("display_value") or "")}
    else:
        out = {"sys_id": str(us or ""), "name": ""}
    # WHO/WHEN: without these the caller can only say "the set differs", which
    # reads as "you switched" even when another person/session captured it.
    out["by"] = _display(row.get("sys_updated_by"))
    out["at"] = _display(row.get("sys_updated_on"))
    return out


def _display(value: Any) -> str:
    """Flatten a display_value Table API field ({value, display_value} or str)."""
    if isinstance(value, dict):
        return str(value.get("display_value") or value.get("value") or "")
    return str(value or "")


def ensure_current_app(
    config: ServerConfig, auth_manager: AuthManager, scope_id: str
) -> Dict[str, Any]:
    """Best-effort: make scope_id the current application (browser auth only).

    Returns {"switched": bool, "skipped"?: reason, ...}. Used by create paths to
    align the session before an insert so the record lands in the intended scope.
    Never raises — a failure is reported so the caller can surface guidance.
    """
    if not _is_browser_auth(config):
        return {"switched": False, "skipped": "not_browser_auth"}
    try:
        current = _get_current(config, auth_manager, _APP_ENDPOINT)
    except Exception as exc:
        logger.warning("Could not read current app before create: %s", exc)
        return {"switched": False, "skipped": "read_failed", "detail": str(exc)}
    if current.get("sys_id") == scope_id:
        return {"switched": False, "already_current": True}
    res = _set_and_verify(
        config,
        auth_manager,
        endpoint=_APP_ENDPOINT,
        body={"value": scope_id, "appId": scope_id, "app_id": scope_id},
        expected_id=scope_id,
        label="application",
    )
    return {"switched": bool(res.get("success")), **res}


def ensure_current_update_set(
    config: ServerConfig, auth_manager: AuthManager, update_set: str
) -> Dict[str, Any]:
    """Best-effort: make *update_set* the current update set (browser auth only).

    Accepts a sys_id or a name (names resolve among in-progress sets). Mirrors
    ``ensure_current_app`` — used by create paths so changes land in the intended
    set. Never raises; reports a failure for the caller to surface.
    """
    if not _is_browser_auth(config):
        return {"switched": False, "skipped": "not_browser_auth"}

    target_id = update_set
    target_name = ""
    # A 32-char hex string is a sys_id; anything else is treated as a name.
    is_sys_id = len(update_set) == 32 and all(c in "0123456789abcdef" for c in update_set.lower())
    if not is_sys_id:
        resolved = _resolve_update_set_by_name(config, auth_manager, update_set)
        if resolved.get("error"):
            return {"switched": False, "skipped": "resolve_failed", **resolved}
        target_id = resolved["sys_id"]
        target_name = resolved.get("name", "")

    try:
        current = _get_current(config, auth_manager, _UPDATESET_ENDPOINT)
    except Exception as exc:
        logger.warning("Could not read current update set before create: %s", exc)
        return {"switched": False, "skipped": "read_failed", "detail": str(exc)}
    if current.get("sys_id") == target_id:
        return {"switched": False, "already_current": True, "name": current.get("name", "")}

    res = _set_and_verify(
        config,
        auth_manager,
        endpoint=_UPDATESET_ENDPOINT,
        body={"value": target_id, "sysId": target_id, "sys_id": target_id},
        expected_id=target_id,
        label="update set",
    )
    out = {"switched": bool(res.get("success")), **res}
    if target_name and "name" not in out:
        out["name"] = target_name
    return out


@register_tool(
    name="manage_session_context",
    params=ManageSessionContextParams,
    description="Get/switch current application + update set (browser auth). set_* verifies via read-back.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_session_context(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageSessionContextParams,
) -> Dict[str, Any]:
    if not _is_browser_auth(config):
        return _browser_only_error()

    if params.action == "get":
        try:
            app = _get_current(config, auth_manager, _APP_ENDPOINT)
            update_set = _get_current(config, auth_manager, _UPDATESET_ENDPOINT)
        except Exception as exc:
            logger.warning("Failed to read session context: %s", exc)
            return {"success": False, "error": "read_failed", "message": str(exc)}
        return {"success": True, "application": app, "update_set": update_set}

    if params.action == "set_app":
        assert params.app_id is not None
        app_result = _set_and_verify(
            config,
            auth_manager,
            endpoint=_APP_ENDPOINT,
            body={"value": params.app_id, "appId": params.app_id, "app_id": params.app_id},
            expected_id=params.app_id,
            label="application",
        )
        # Scope + update set are managed together: switching the app already
        # changes the update set as a side effect, so when the caller names an
        # update set, set it in the SAME call — "put me in scope X with update
        # set Y" is one step, not two (and a scoped write then lands correctly).
        if app_result.get("success") and (params.update_set_id or params.update_set_name):
            us_result = _apply_update_set(
                config, auth_manager, params.update_set_id, params.update_set_name
            )
            return {
                "success": bool(us_result.get("success")),
                "application": app_result.get("current"),
                "update_set": us_result.get("current"),
                "message": f"{app_result.get('message', '')} | "
                f"{us_result.get('message') or us_result.get('error', '')}",
                **({"update_set_error": us_result} if not us_result.get("success") else {}),
            }
        return app_result

    # set_update_set — change only the update set (within the current scope).
    return _apply_update_set(config, auth_manager, params.update_set_id, params.update_set_name)
