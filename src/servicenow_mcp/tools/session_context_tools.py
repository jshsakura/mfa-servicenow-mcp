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
from typing import Any, Dict, List, Optional

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
        default=None, description="sys_update_set sys_id (set_update_set; or pass update_set_name)"
    )
    update_set_name: Optional[str] = Field(
        default=None,
        description="Update set name — resolved to sys_id among in-progress sets (set_update_set)",
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


def _picker_value(payload: Dict[str, Any]) -> Dict[str, str]:
    """Extract {sys_id, name} of the current selection from a concoursepicker body.

    The picker response shape varies across releases; check the documented keys in
    order and fall back to empty strings so callers always get a stable shape.
    """
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(result, dict):
        return {"sys_id": "", "name": ""}
    current = result.get("current")
    if isinstance(current, dict):
        return {
            "sys_id": str(
                current.get("sysId") or current.get("sys_id") or current.get("value") or ""
            ),
            "name": str(current.get("name") or current.get("displayValue") or ""),
        }
    return {
        "sys_id": str(result.get("sysId") or result.get("sys_id") or result.get("value") or ""),
        "name": str(result.get("name") or result.get("displayValue") or ""),
    }


def _resolve_update_set_by_name(
    config: ServerConfig, auth_manager: AuthManager, name: str
) -> Dict[str, Any]:
    """Resolve an update set *name* to a sys_id, preferring in-progress sets.

    Only in-progress sets are selectable, so the name is matched against those
    first; an exact match wins over a substring. Returns {"sys_id", "name"} on a
    unique hit, or {"error", "message", "candidates"?} when none/ambiguous.
    """
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_set",
            query=f"state=in progress^nameLIKE{name}^ORDERBYname",
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
                f"No in-progress update set matching '{name}'. Only in-progress "
                "sets can be selected — check the name or create one first."
            ),
        }

    exact = [r for r in rows if str(r.get("name", "")).strip().lower() == name.strip().lower()]
    chosen = exact if exact else rows
    if len(chosen) > 1:
        candidates: List[Dict[str, str]] = [
            {"sys_id": str(r.get("sys_id") or ""), "name": str(r.get("name") or "")} for r in chosen
        ]
        return {
            "error": "ambiguous",
            "message": (
                f"'{name}' matches {len(chosen)} in-progress update sets. "
                "Pass update_set_id to disambiguate."
            ),
            "candidates": candidates,
        }
    row = chosen[0]
    return {"sys_id": str(row.get("sys_id") or ""), "name": str(row.get("name") or "")}


def _get_current(config: ServerConfig, auth_manager: AuthManager, endpoint: str) -> Dict[str, str]:
    url = f"{config.instance_url.rstrip('/')}{endpoint}"
    response = auth_manager.make_request("GET", url, timeout=config.timeout)
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception:
        payload = {}
    return _picker_value(payload if isinstance(payload, dict) else {})


def _put_current(
    config: ServerConfig, auth_manager: AuthManager, endpoint: str, body: Dict[str, Any]
) -> None:
    url = f"{config.instance_url.rstrip('/')}{endpoint}"
    response = auth_manager.make_request("PUT", url, json=body, timeout=config.timeout)
    response.raise_for_status()


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
    """PUT a new selection, then read it back. Success only if read-back matches."""
    try:
        _put_current(config, auth_manager, endpoint, body)
    except Exception as exc:  # network / HTTP / endpoint-shape rejection
        logger.warning("Failed to set %s: %s", label, exc)
        return {"success": False, "error": "set_failed", "message": f"Set {label} failed: {exc}"}

    try:
        current = _get_current(config, auth_manager, endpoint)
    except Exception as exc:
        logger.warning("Set %s but read-back failed: %s", label, exc)
        return {
            "success": False,
            "error": "verify_failed",
            "message": f"Set {label} sent but could not confirm: {exc}",
        }

    if current.get("sys_id") != expected_id:
        return {
            "success": False,
            "error": "not_applied",
            "message": (
                f"{label} did not switch — requested '{expected_id}', "
                f"current is '{current.get('sys_id')}'. Check the sys_id and that "
                "your account may select it."
            ),
            "current": current,
        }
    return {
        "success": True,
        "message": f"Current {label} is now {current.get('name') or expected_id}",
        "current": current,
    }


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
    """
    if not update_set:
        return False
    return str(update_set.get("name", "")).strip().lower() == "default"


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
            fields="sys_id,name,update_set,sys_updated_on",
            limit=1,
            offset=0,
            display_value=True,
        )
    except Exception as exc:
        logger.warning("Could not read last update set for %s/%s: %s", table, sys_id, exc)
        return None
    if not rows:
        return None
    us = rows[0].get("update_set")
    if isinstance(us, dict):
        return {"sys_id": str(us.get("value") or ""), "name": str(us.get("display_value") or "")}
    return {"sys_id": str(us or ""), "name": ""}


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
        body={"appId": scope_id, "app_id": scope_id},
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
        body={"sysId": target_id, "sys_id": target_id},
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
        return _set_and_verify(
            config,
            auth_manager,
            endpoint=_APP_ENDPOINT,
            body={"appId": params.app_id, "app_id": params.app_id},
            expected_id=params.app_id,
            label="application",
        )

    # set_update_set — resolve by name when no explicit sys_id was given.
    update_set_id = params.update_set_id
    if not update_set_id:
        assert params.update_set_name is not None
        resolved = _resolve_update_set_by_name(config, auth_manager, params.update_set_name)
        if resolved.get("error"):
            return {"success": False, **resolved}
        update_set_id = resolved["sys_id"]

    assert update_set_id  # narrowed: set by param or resolved above
    return _set_and_verify(
        config,
        auth_manager,
        endpoint=_UPDATESET_ENDPOINT,
        body={"sysId": update_set_id, "sys_id": update_set_id},
        expected_id=update_set_id,
        label="update set",
    )
