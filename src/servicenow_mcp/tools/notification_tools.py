"""Notification (Email Action) + Email Template tools for the ServiceNow MCP
server.

Bundled CRUD over ``sysevent_email_action`` (when/who an email fires for) and
``sysevent_email_template`` (a reusable body a notification can point at),
the same two-level shape ``manage_scripted_rest`` uses for service + resource
— a notification and its template are edited together in practice.

Deliberately a dedicated tool rather than ``sn_write`` or
``manage_portal_component``: ``category``/``template`` are references, and a
raw write with the display name in them stores an invalid sys_id silently.
``manage_portal_component`` already edits an existing notification's
subject/message_html/message_text (the source-sync path); this tool owns
everything else — condition, recipients, event, category, template — plus
creation, for both tables.
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import notification as _svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_NOTIF_WRITE_FIELDS = frozenset(
    {
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
    }
)
_TEMPLATE_WRITE_FIELDS = frozenset(
    {"name", "subject", "collection", "email_layout", "message_html", "message_text"}
)
_MAIL_SCRIPT_WRITE_FIELDS = frozenset({"name", "script", "new_lines_to_html"})
_LAYOUT_WRITE_FIELDS = frozenset({"name", "description", "layout", "advanced", "advanced_layout"})
# action -> (service kind, write fields) for the flat mail script / layout records
_SIMPLE_ACTIONS: Dict[str, tuple] = {
    "list_mail_scripts": ("mail_script", None),
    "get_mail_script": ("mail_script", None),
    "create_mail_script": ("mail_script", _MAIL_SCRIPT_WRITE_FIELDS),
    "update_mail_script": ("mail_script", _MAIL_SCRIPT_WRITE_FIELDS),
    "list_layouts": ("layout", None),
    "get_layout": ("layout", None),
    "create_layout": ("layout", _LAYOUT_WRITE_FIELDS),
    "update_layout": ("layout", _LAYOUT_WRITE_FIELDS),
}


class ManageNotificationParams(BaseModel):
    """Manage notifications, email templates, mail scripts and email layouts —
    tables: sysevent_email_action, sysevent_email_template, sys_script_email,
    sys_email_layout.

    Required per action:
      list / list_templates / list_mail_scripts / list_layouts:  (none)
      get / get_template / get_mail_script / get_layout:         sys_id
      create:                 category, at least one other field
      create_template / create_mail_script / create_layout:      name
      update / update_template / update_mail_script / update_layout:
                              sys_id, at least one field
    """

    action: Literal[
        "list",
        "get",
        "create",
        "update",
        "list_templates",
        "get_template",
        "create_template",
        "update_template",
        "list_mail_scripts",
        "get_mail_script",
        "create_mail_script",
        "update_mail_script",
        "list_layouts",
        "get_layout",
        "create_layout",
        "update_layout",
    ] = Field(...)

    sys_id: Optional[str] = Field(default=None, description="Target record sys_id (get/update)")

    # list / list_templates
    collection: Optional[str] = Field(
        default=None, description="Filter by target table name (list)"
    )
    query: Optional[str] = Field(default=None, description="Subject/name search (list*)")
    active: Optional[bool] = Field(
        default=None, description="Active flag (filter on list, set on write)"
    )
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    count_only: bool = Field(default=False, description="Return count only")

    # create/update notification
    event_name: Optional[str] = Field(default=None, description="System event this fires on")
    condition: Optional[str] = Field(default=None, description="Encoded query gating delivery")
    category: Optional[str] = Field(
        default=None, description="Notification category name or sys_id:<id> (required on create)"
    )
    template: Optional[str] = Field(default=None, description="Email template name or sys_id:<id>")
    recipient_users: Optional[str] = Field(
        default=None, description="Comma-separated sys_user sys_ids"
    )
    recipient_groups: Optional[str] = Field(
        default=None, description="Comma-separated sys_user_group sys_ids"
    )
    recipient_fields: Optional[str] = Field(
        default=None,
        description="Comma-separated field names on the target record (e.g. assignment_group)",
    )
    action_insert: Optional[bool] = Field(
        default=None, description="Trigger on record insert ('Inserted' checkbox)"
    )
    action_update: Optional[bool] = Field(
        default=None, description="Trigger on record update ('Updated' checkbox)"
    )
    send_self: Optional[bool] = Field(
        default=None, description="Also email the user whose change fired it"
    )
    weight: Optional[int] = Field(default=None, description="Delivery priority weight")
    subject: Optional[str] = Field(default=None, description="Email subject")
    message_html: Optional[str] = Field(default=None, description="HTML body")
    message_text: Optional[str] = Field(default=None, description="Plain-text body")
    from_address: Optional[str] = Field(default=None, description="From address override")
    reply_to: Optional[str] = Field(default=None, description="Reply-to address override")

    # notification name / create_template/update_template
    name: Optional[str] = Field(
        default=None,
        description="Record name — notification or template (required on create_template)",
    )

    # template -> layout link
    email_layout: Optional[str] = Field(
        default=None, description="Email layout name or sys_id:<id> (template)"
    )

    # mail script (sys_script_email)
    script: Optional[str] = Field(
        default=None, description="Mail script body; called as ${mail_script:<name>}"
    )
    new_lines_to_html: Optional[bool] = Field(
        default=None, description="Convert newlines in script output to <br/>"
    )

    # email layout (sys_email_layout)
    layout: Optional[str] = Field(
        default=None, description="Layout HTML; must contain ${notification:body}"
    )
    description: Optional[str] = Field(default=None, description="Layout description")
    advanced: Optional[bool] = Field(
        default=None, description="Use advanced_layout (XML) instead of layout"
    )
    advanced_layout: Optional[str] = Field(default=None, description="Advanced layout XML")

    dry_run: bool = Field(default=False, description="Preview the write without committing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"collection", "query", "active", "limit", "offset", "count_only"}),
        "get": frozenset({"sys_id"}),
        "create": _NOTIF_WRITE_FIELDS | {"dry_run"},
        "update": _NOTIF_WRITE_FIELDS | {"sys_id", "dry_run"},
        "list_templates": frozenset({"collection", "query", "limit", "offset", "count_only"}),
        "get_template": frozenset({"sys_id"}),
        "create_template": _TEMPLATE_WRITE_FIELDS | {"dry_run"},
        "update_template": _TEMPLATE_WRITE_FIELDS | {"sys_id", "dry_run"},
        "list_mail_scripts": frozenset({"query", "limit", "offset", "count_only"}),
        "get_mail_script": frozenset({"sys_id"}),
        "create_mail_script": _MAIL_SCRIPT_WRITE_FIELDS | {"dry_run"},
        "update_mail_script": _MAIL_SCRIPT_WRITE_FIELDS | {"sys_id", "dry_run"},
        "list_layouts": frozenset({"query", "limit", "offset", "count_only"}),
        "get_layout": frozenset({"sys_id"}),
        "create_layout": _LAYOUT_WRITE_FIELDS | {"dry_run"},
        "update_layout": _LAYOUT_WRITE_FIELDS | {"sys_id", "dry_run"},
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageNotificationParams":
        a = self.action
        if a in _SIMPLE_ACTIONS:
            _, fields = _SIMPLE_ACTIONS[a]
            if a.startswith(("get_", "update_")) and not self.sys_id:
                raise ValueError(f"sys_id is required for action='{a}'")
            if a.startswith("create_") and not self.name:
                raise ValueError(f"name is required for action='{a}'")
            if a.startswith("update_") and not any(getattr(self, f) is not None for f in fields):
                raise ValueError(f"at least one field is required for action='{a}'")
            return self
        if a in ("get", "get_template"):
            if not self.sys_id:
                raise ValueError(f"sys_id is required for action='{a}'")
        elif a == "create":
            if not self.category:
                raise ValueError("category is required for action='create'")
        elif a == "create_template":
            if not self.name:
                raise ValueError("name is required for action='create_template'")
        elif a in ("update", "update_template"):
            if not self.sys_id:
                raise ValueError(f"sys_id is required for action='{a}'")
            fields = _NOTIF_WRITE_FIELDS if a == "update" else _TEMPLATE_WRITE_FIELDS
            if not any(getattr(self, f) is not None for f in fields):
                raise ValueError(f"at least one field is required for action='{a}'")
        return self


@register_tool(
    name="manage_notification",
    params=ManageNotificationParams,
    description="Notification, email template, mail script, email layout CRUD. Use list* to find sys_id.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_notification(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageNotificationParams,
) -> Dict[str, Any]:
    if params.action in _SIMPLE_ACTIONS:
        return _run_simple(config, auth_manager, params)
    if params.action == "list":
        return _svc.list_notifications(
            config,
            auth_manager,
            collection=params.collection,
            query=params.query,
            active=params.active,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if params.action == "get":
        assert params.sys_id is not None
        return _svc.get_notification(config, auth_manager, sys_id=params.sys_id)
    if params.action == "list_templates":
        return _svc.list_templates(
            config,
            auth_manager,
            collection=params.collection,
            query=params.query,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if params.action == "get_template":
        assert params.sys_id is not None
        return _svc.get_template(config, auth_manager, sys_id=params.sys_id)

    notif_kwargs: Dict[str, Any] = {
        "name": params.name,
        "collection": params.collection,
        "event_name": params.event_name,
        "condition": params.condition,
        "category": params.category,
        "template": params.template,
        "active": params.active,
        "weight": params.weight,
        "recipient_users": params.recipient_users,
        "recipient_groups": params.recipient_groups,
        "recipient_fields": params.recipient_fields,
        "subject": params.subject,
        "message_html": params.message_html,
        "message_text": params.message_text,
        "from_address": params.from_address,
        "reply_to": params.reply_to,
        "action_insert": params.action_insert,
        "action_update": params.action_update,
        "send_self": params.send_self,
    }
    if params.action == "create":
        return _svc.create_notification(
            config, auth_manager, dry_run=params.dry_run, **notif_kwargs
        )
    if params.action == "update":
        assert params.sys_id is not None
        return _svc.update_notification(
            config, auth_manager, sys_id=params.sys_id, dry_run=params.dry_run, **notif_kwargs
        )

    template_kwargs: Dict[str, Any] = {
        "name": params.name,
        "subject": params.subject,
        "collection": params.collection,
        "email_layout": params.email_layout,
        "message_html": params.message_html,
        "message_text": params.message_text,
    }
    if params.action == "create_template":
        return _svc.create_template(config, auth_manager, dry_run=params.dry_run, **template_kwargs)
    # update_template
    assert params.sys_id is not None
    return _svc.update_template(
        config, auth_manager, sys_id=params.sys_id, dry_run=params.dry_run, **template_kwargs
    )


def _run_simple(
    config: ServerConfig, auth_manager: AuthManager, params: ManageNotificationParams
) -> Dict[str, Any]:
    kind, fields = _SIMPLE_ACTIONS[params.action]
    verb = params.action.split("_", 1)[0]
    if verb == "list":
        return _svc.list_simple(
            config,
            auth_manager,
            kind=kind,
            query=params.query,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if verb == "get":
        assert params.sys_id is not None
        return _svc.get_simple(config, auth_manager, kind=kind, sys_id=params.sys_id)
    kwargs = {f: getattr(params, f) for f in fields}
    if verb == "create":
        return _svc.create_simple(config, auth_manager, kind=kind, dry_run=params.dry_run, **kwargs)
    assert params.sys_id is not None
    return _svc.update_simple(
        config, auth_manager, kind=kind, sys_id=params.sys_id, dry_run=params.dry_run, **kwargs
    )
