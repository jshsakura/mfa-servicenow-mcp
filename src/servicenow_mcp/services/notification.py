"""Notification (Email Action) + Email Template service layer.

``sysevent_email_action`` decides WHEN an email fires (event, condition,
recipients) and CAN embed the body directly or point at a shared
``sysevent_email_template`` via its ``template`` reference. Bundled as one
tool for the same reason ``manage_scripted_rest`` bundles service + resource:
a notification and the template it uses are edited together in practice, and
a caller resolving that reference by hand hits the exact trap
``services/ux_list.py`` already documents — write the display name into a
reference field and the platform stores it silently wrong.

Kept separate from ``sn_write`` and from ``manage_portal_component`` (which
only ever exposed a notification's subject/message_html/message_text — the
source-sync path, not full record CRUD) for the same reason as ux_list: no
existing surface covered condition/recipients/event/category/template.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_create_preview, build_update_preview
from servicenow_mcp.tools.sn_api import count_response, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

NOTIF_TABLE = "sysevent_email_action"
TEMPLATE_TABLE = "sysevent_email_template"
CATEGORY_TABLE = "sys_notification_category"

_NOTIF_META = (
    "sys_id,name,subject,collection,event_name,condition,category,template,active,weight,"
    "action_insert,action_update,send_self,"
    "recipient_users,recipient_groups,recipient_fields,message_html,message_text,"
    "from,reply_to,sys_scope,sys_updated_on"
)
_TEMPLATE_META = "sys_id,name,subject,collection,message_html,message_text,sys_scope,sys_updated_on"

# Python kwarg -> ServiceNow field name, where they differ ("from" is reserved).
_NOTIF_UPDATE_FIELDS = (
    "name",
    "collection",
    "event_name",
    "condition",
    "category",
    "template",
    "active",
    "action_insert",
    "action_update",
    "send_self",
    "weight",
    "recipient_users",
    "recipient_groups",
    "recipient_fields",
    "subject",
    "message_html",
    "message_text",
    "from_address",
    "reply_to",
)
_NOTIF_FIELD_NAME = {"from_address": "from"}
_NOTIF_REF_FIELDS = {"category": (CATEGORY_TABLE, "name"), "template": (TEMPLATE_TABLE, "name")}

_TEMPLATE_UPDATE_FIELDS = ("name", "subject", "collection", "message_html", "message_text")


def _dv(v: Any) -> Any:
    """Unwrap a display-value dict to its value; pass scalars through."""
    return v.get("display_value") if isinstance(v, dict) else v


def _is_sys_id(value: str) -> bool:
    return len(value) == 32 and all(c in "0123456789abcdefABCDEF" for c in value)


def _resolve_ref(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    name_field: str,
    ident: str,
) -> Optional[str]:
    """A sys_id for `ident` (already a sys_id, ``sys_id:<id>``, or a display
    name), or None when a name was given and nothing matched — never a guess
    written into a reference field."""
    if ident.startswith("sys_id:"):
        return ident[len("sys_id:") :]
    if _is_sys_id(ident):
        return ident
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=f"{name_field}={ident}",
        fields=f"sys_id,{name_field}",
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return records[0]["sys_id"] if records else None


def _notif_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sys_id": r.get("sys_id"),
        "name": r.get("name"),
        "subject": r.get("subject"),
        "collection": r.get("collection"),
        "event_name": r.get("event_name"),
        "condition": r.get("condition"),
        "category": _dv(r.get("category")),
        "template": _dv(r.get("template")),
        "active": _dv(r.get("active")) == "true",
        "action_insert": _dv(r.get("action_insert")) == "true",
        "action_update": _dv(r.get("action_update")) == "true",
        "send_self": _dv(r.get("send_self")) == "true",
        "weight": r.get("weight"),
        "recipient_users": r.get("recipient_users"),
        "recipient_groups": r.get("recipient_groups"),
        "recipient_fields": r.get("recipient_fields"),
        "message_html": r.get("message_html"),
        "message_text": r.get("message_text"),
        "from": r.get("from"),
        "reply_to": r.get("reply_to"),
        "scope": _dv(r.get("sys_scope")),
        "updated_on": r.get("sys_updated_on"),
    }


def _template_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sys_id": r.get("sys_id"),
        "name": r.get("name"),
        "subject": r.get("subject"),
        "collection": r.get("collection"),
        "message_html": r.get("message_html"),
        "message_text": r.get("message_text"),
        "scope": _dv(r.get("sys_scope")),
        "updated_on": r.get("sys_updated_on"),
    }


def _build_body(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    update_fields: tuple,
    ref_fields: Dict[str, tuple],
    field_name: Dict[str, str],
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Proposed-write body: reference fields resolved by name, booleans
    lowercased, everything else passed through. Raises _RefNotFound (via a
    dict sentinel the caller checks) rather than write a guess."""
    body: Dict[str, Any] = {}
    for f in update_fields:
        v = fields.get(f)
        if v is None:
            continue
        target = field_name.get(f, f)
        if f in ref_fields:
            table, name_field = ref_fields[f]
            resolved = _resolve_ref(
                config, auth_manager, table=table, name_field=name_field, ident=v
            )
            if resolved is None:
                return {
                    "__error__": f"{table} not found: {v!r} — check the name, or pass sys_id:<id>"
                }
            body[target] = resolved
        elif isinstance(v, bool):
            body[target] = str(v).lower()
        else:
            body[target] = v
    return body


# ---------------------------------------------------------------------------
# Notifications (sysevent_email_action)
# ---------------------------------------------------------------------------


def list_notifications(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    collection: Optional[str] = None,
    query: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    """List notifications (sysevent_email_action), optionally by target table."""
    parts: List[str] = []
    if collection:
        parts.append(f"collection={collection}")
    if active is not None:
        parts.append(f"active={str(active).lower()}")
    if query:
        parts.append(f"nameLIKE{query}^ORsubjectLIKE{query}")
    query_string = "^".join(parts)

    if count_only:
        return count_response(config, auth_manager, NOTIF_TABLE, query_string, what="notifications")

    records, _ = sn_query_page(
        config,
        auth_manager,
        table=NOTIF_TABLE,
        query=query_string,
        fields=_NOTIF_META,
        limit=min(limit, 50),
        offset=offset,
        display_value=True,
        fail_silently=False,
    )
    notifications = [_notif_row(r) for r in records]
    return {
        "success": True,
        "message": f"Found {len(notifications)} notifications",
        "notifications": notifications,
        "total": len(notifications),
        "limit": limit,
        "offset": offset,
    }


def get_notification(
    config: ServerConfig, auth_manager: AuthManager, *, sys_id: str
) -> Dict[str, Any]:
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=NOTIF_TABLE,
        query=f"sys_id={sys_id}",
        fields=_NOTIF_META,
        limit=1,
        offset=0,
        display_value=True,
        fail_silently=False,
    )
    if not records:
        return {"success": False, "message": f"Notification not found: {sys_id}"}
    return {"success": True, "notification": _notif_row(records[0])}


def create_notification(
    config: ServerConfig, auth_manager: AuthManager, *, dry_run: bool = False, **fields: Any
) -> Dict[str, Any]:
    """Create a notification. `category` is mandatory on the platform's own
    dictionary; omitting it is passed through rather than defaulted here —
    what happens then is the platform's rule to enforce, not this tool's to
    guess.

    ``dry_run`` was already accepted here — it is declared on the tool's params
    model, so every action takes it — and then dropped: `manage_notification`
    simply did not pass it on. `_FIELDS_BY_ACTION` leaving it off `create` did
    not reject it either, because that map narrows the ADVERTISED SCHEMA
    (`server.py` -> `_narrow_action_schema`) and validates nothing at runtime.
    A caller asking for a preview got a real record.

    A create preview is thinner than an update's by nature and that is not a
    defect: `build_update_preview` fetches the record and diffs it, and a create
    has nothing to diff against. `build_create_preview` is the repo's answer for
    that, already used by workflow_tools — used here rather than hand-rolled, so
    every preview in this server keeps the same shape (`warnings`,
    `precision_notes`) and a caller cannot tell them apart by accident.
    """
    body = _build_body(
        config,
        auth_manager,
        update_fields=_NOTIF_UPDATE_FIELDS,
        ref_fields=_NOTIF_REF_FIELDS,
        field_name=_NOTIF_FIELD_NAME,
        fields=fields,
    )
    if "__error__" in body:
        return {"success": False, "message": body["__error__"]}

    if dry_run:
        # After _build_body, so the preview shows the record the SERVER would
        # receive — references already resolved to sys_ids, not the names typed.
        return build_create_preview(table=NOTIF_TABLE, proposed=body)

    url = f"{config.instance_url}/api/now/table/{NOTIF_TABLE}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": "Failed to create notification"}
        invalidate_query_cache(table=NOTIF_TABLE)
        return {
            "success": True,
            "message": f"Created notification: {result.get('name') or result.get('subject') or result.get('sys_id')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
            "subject": result.get("subject"),
        }
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        return {"success": False, "message": f"Error creating notification: {str(e)}"}


def update_notification(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sys_id: str,
    dry_run: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    existing = get_notification(config, auth_manager, sys_id=sys_id)
    if not existing.get("success"):
        return existing

    body = _build_body(
        config,
        auth_manager,
        update_fields=_NOTIF_UPDATE_FIELDS,
        ref_fields=_NOTIF_REF_FIELDS,
        field_name=_NOTIF_FIELD_NAME,
        fields=fields,
    )
    if "__error__" in body:
        return {"success": False, "message": body["__error__"]}

    if not body:
        return {
            "success": True,
            "message": f"No changes to update for notification: {existing['notification'].get('name') or existing['notification'].get('subject')}",
            "sys_id": sys_id,
        }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=NOTIF_TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "subject", "collection", "event_name"],
        )

    url = f"{config.instance_url}/api/now/table/{NOTIF_TABLE}/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": f"Failed to update notification: {sys_id}"}
        invalidate_query_cache(table=NOTIF_TABLE)
        return {
            "success": True,
            "message": f"Updated notification: {result.get('name') or result.get('subject') or sys_id}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
            "subject": result.get("subject"),
        }
    except Exception as e:
        logger.error(f"Error updating notification: {e}")
        return {"success": False, "message": f"Error updating notification: {str(e)}"}


# ---------------------------------------------------------------------------
# Email templates (sysevent_email_template)
# ---------------------------------------------------------------------------


def list_templates(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    collection: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    parts: List[str] = []
    if collection:
        parts.append(f"collection={collection}")
    if query:
        parts.append(f"nameLIKE{query}")
    query_string = "^".join(parts)

    if count_only:
        return count_response(
            config, auth_manager, TEMPLATE_TABLE, query_string, what="email templates"
        )

    records, _ = sn_query_page(
        config,
        auth_manager,
        table=TEMPLATE_TABLE,
        query=query_string,
        fields=_TEMPLATE_META,
        limit=min(limit, 50),
        offset=offset,
        display_value=True,
        fail_silently=False,
    )
    templates = [_template_row(r) for r in records]
    return {
        "success": True,
        "message": f"Found {len(templates)} email templates",
        "templates": templates,
        "total": len(templates),
        "limit": limit,
        "offset": offset,
    }


def get_template(config: ServerConfig, auth_manager: AuthManager, *, sys_id: str) -> Dict[str, Any]:
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=TEMPLATE_TABLE,
        query=f"sys_id={sys_id}",
        fields=_TEMPLATE_META,
        limit=1,
        offset=0,
        display_value=True,
        fail_silently=False,
    )
    if not records:
        return {"success": False, "message": f"Email template not found: {sys_id}"}
    return {"success": True, "template": _template_row(records[0])}


def create_template(
    config: ServerConfig, auth_manager: AuthManager, *, dry_run: bool = False, **fields: Any
) -> Dict[str, Any]:
    """Create an email template. See `create_notification` for why `dry_run`
    had to be threaded here rather than merely accepted."""
    body = _build_body(
        config,
        auth_manager,
        update_fields=_TEMPLATE_UPDATE_FIELDS,
        ref_fields={},
        field_name={},
        fields=fields,
    )
    if not body.get("name"):
        return {"success": False, "message": "name is required to create an email template"}

    if dry_run:
        return build_create_preview(table=TEMPLATE_TABLE, proposed=body)

    url = f"{config.instance_url}/api/now/table/{TEMPLATE_TABLE}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": "Failed to create email template"}
        invalidate_query_cache(table=TEMPLATE_TABLE)
        return {
            "success": True,
            "message": f"Created email template: {result.get('name')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
        }
    except Exception as e:
        logger.error(f"Error creating email template: {e}")
        return {"success": False, "message": f"Error creating email template: {str(e)}"}


def update_template(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sys_id: str,
    dry_run: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    existing = get_template(config, auth_manager, sys_id=sys_id)
    if not existing.get("success"):
        return existing

    body = _build_body(
        config,
        auth_manager,
        update_fields=_TEMPLATE_UPDATE_FIELDS,
        ref_fields={},
        field_name={},
        fields=fields,
    )
    if not body:
        return {
            "success": True,
            "message": f"No changes to update for email template: {existing['template'].get('name')}",
            "sys_id": sys_id,
        }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=TEMPLATE_TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "subject", "collection"],
        )

    url = f"{config.instance_url}/api/now/table/{TEMPLATE_TABLE}/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": f"Failed to update email template: {sys_id}"}
        invalidate_query_cache(table=TEMPLATE_TABLE)
        return {
            "success": True,
            "message": f"Updated email template: {result.get('name')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
        }
    except Exception as e:
        logger.error(f"Error updating email template: {e}")
        return {"success": False, "message": f"Error updating email template: {str(e)}"}
