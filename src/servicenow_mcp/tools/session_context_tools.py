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
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator

from ..auth.auth_manager import AuthManager
from ..utils.config import AuthType, ServerConfig
from ..utils.registry import register_tool

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
        default=None, description="sys_update_set sys_id (required for set_update_set)"
    )

    @model_validator(mode="after")
    def _validate(self) -> "ManageSessionContextParams":
        if self.action not in ("get", "set_app", "set_update_set"):
            raise ValueError("action must be one of: get, set_app, set_update_set")
        if self.action == "set_app" and not self.app_id:
            raise ValueError("app_id is required for action='set_app'")
        if self.action == "set_update_set" and not self.update_set_id:
            raise ValueError("update_set_id is required for action='set_update_set'")
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

    # set_update_set
    assert params.update_set_id is not None
    return _set_and_verify(
        config,
        auth_manager,
        endpoint=_UPDATESET_ENDPOINT,
        body={"sysId": params.update_set_id, "sys_id": params.update_set_id},
        expected_id=params.update_set_id,
        label="update set",
    )
