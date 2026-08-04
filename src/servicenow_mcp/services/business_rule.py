"""Business rule (sys_script) service layer.

Reusable API logic for list / get / create / update / delete on the ServiceNow
``sys_script`` table, mirroring ``services.script_include``. Creating one is the
same single POST as a script include — the table and the field set are the only
real differences — but two of those fields decide whether the rule ever runs,
which is why this module refuses to write a rule that cannot fire (see
:func:`_execution_is_reachable`).

``sys_script`` was already wired for reading (``search_server_code``,
``download_server_sources``) and for pushing a body onto an EXISTING record
(``sync_tools``). Nothing could create one, and ``update_remote_from_local``
deliberately never will: it PATCHes a record proven to descend from a version
the server held, so a component with no anchor is refused rather than invented.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

_BR_FIELDS = (
    "sys_id,name,collection,when,order,active,advanced,action_insert,action_update,action_delete"
)

_BR_UPDATE_FIELDS = (
    "script",
    "condition",
    "filter_condition",
    "description",
    "collection",
    "when",
    "order",
    "active",
    "advanced",
    "action_insert",
    "action_update",
    "action_delete",
)

_SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

# A rule fires on at least one DML action, at one of these points.
WHEN_VALUES = ("before", "after", "async", "display")


class BusinessRuleResponse(BaseModel):
    """Response from business rule operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    business_rule_id: Optional[str] = Field(
        default=None, description="sys_id of the affected business rule"
    )
    business_rule_name: Optional[str] = Field(
        default=None, description="Name of the affected business rule"
    )
    table: Optional[str] = Field(default=None, description="Table the rule is attached to")
    candidates: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Matching rules when a name identifies more than one"
    )


def _as_bool(value: Any) -> bool:
    """ServiceNow returns booleans as 'true'/'false' strings on the Table API."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1")


def _execution_is_reachable(
    *,
    script: Optional[str],
    advanced: Optional[bool],
    insert: Optional[bool],
    update: Optional[bool],
    delete: Optional[bool],
    when: Optional[str],
) -> Optional[str]:
    """Why this rule would never run, or None when it can.

    A business rule that saves cleanly and then does nothing is the worst
    outcome this tool can produce: the record exists, the UI shows the script,
    and nothing anywhere reports that it is inert. Two fields cause it, and
    neither announces itself.

    - ``advanced`` off means the ``script`` field is not executed at all. The
      form hides the script tab, so a rule written by API with advanced unset
      looks complete and runs nothing.
    - every ``action_*`` off means there is no DML event to fire on. ``display``
      rules are the exception — they run when a form is loaded, not on insert,
      update or delete.

    Returning the reason rather than a bool so the caller can say which one.
    """
    if script and advanced is False:
        return (
            "this rule has a script but advanced=false, and a non-advanced rule never "
            "executes its script. Pass advanced=true (the default when a script is given)."
        )
    if when != "display" and not any((insert, update, delete)):
        return (
            "no trigger is set: action_insert, action_update and action_delete are all off, "
            f"so a when='{when}' rule has no event to fire on. Turn on at least one."
        )
    return None


def _fetch_br(
    config: ServerConfig,
    auth_manager: AuthManager,
    business_rule_id: str,
    collection: Optional[str] = None,
) -> Union[Dict[str, Any], BusinessRuleResponse]:
    """Resolve a business rule by sys_id, or by name within a table.

    Business rule names are NOT unique, and duplication across tables is the
    normal way a family of rules is written — five rules called "Update Group
    Count", one per interface table, is a deliberate pattern, not a mistake. So
    a name alone may identify several records, and picking the first would edit
    an arbitrary one of them.

    An ambiguous name returns every candidate instead of a guess. Pass
    ``collection`` to disambiguate, or the sys_id to be exact.
    """
    if _SYS_ID_RE.match(business_rule_id.replace("sys_id:", "").strip()):
        query = f"sys_id={business_rule_id.replace('sys_id:', '').strip()}"
    else:
        query = f"name={business_rule_id}"
        if collection:
            query += f"^collection={collection}"

    records, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_script",
        query=query,
        fields=_BR_FIELDS,
        limit=10,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    if not records:
        where = f" on table '{collection}'" if collection else ""
        return BusinessRuleResponse(
            success=False,
            message=f"Business rule not found: {business_rule_id}{where}",
        )
    if len(records) > 1:
        return BusinessRuleResponse(
            success=False,
            message=(
                f"'{business_rule_id}' matches {len(records)} business rules — a rule name is "
                "not unique across tables. Pass collection=<table> or the sys_id."
            ),
            candidates=[
                {
                    "sys_id": row.get("sys_id"),
                    "name": row.get("name"),
                    "collection": row.get("collection"),
                    "when": row.get("when"),
                }
                for row in records
            ],
        )
    return records[0]


def list_br(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    collection: Optional[str] = None,
    query: Optional[str] = None,
    when: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = 20,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    """List business rules, newest-relevant filters first."""
    parts: List[str] = []
    if collection:
        parts.append(f"collection={collection}")
    if when:
        parts.append(f"when={when}")
    if active is not None:
        parts.append(f"active={str(active).lower()}")
    if query:
        parts.append(f"nameLIKE{query}")
    encoded = "^".join(parts)

    if count_only:
        total = sn_count(config, auth_manager, table="sys_script", query=encoded)
        return {"success": True, "count": total, "table": "sys_script"}

    try:
        records, total = sn_query_page(
            config,
            auth_manager,
            table="sys_script",
            query=encoded,
            fields=_BR_FIELDS,
            limit=limit,
            offset=offset,
            display_value=False,
            fail_silently=False,
            orderby="collection",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a message
        logger.error(f"Error listing business rules: {exc}")
        return {"success": False, "message": f"Error listing business rules: {exc}"}

    return {
        "success": True,
        "count": len(records),
        "total": total,
        "business_rules": records,
    }


def get_br(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    business_rule_id: str,
    collection: Optional[str] = None,
) -> Dict[str, Any]:
    """Read one business rule including its script and condition."""
    found = _fetch_br(config, auth_manager, business_rule_id, collection)
    if isinstance(found, BusinessRuleResponse):
        return found.model_dump(exclude_none=True)

    records, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_script",
        query=f"sys_id={found['sys_id']}",
        fields=f"{_BR_FIELDS},script,condition,filter_condition,description",
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    if not records:
        return {"success": False, "message": f"Business rule not found: {business_rule_id}"}
    return {"success": True, "business_rule": records[0]}


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    collection: str,
    when: str = "before",
    script: Optional[str] = None,
    condition: Optional[str] = None,
    filter_condition: Optional[str] = None,
    description: Optional[str] = None,
    order: int = 100,
    active: bool = True,
    advanced: Optional[bool] = None,
    action_insert: bool = False,
    action_update: bool = False,
    action_delete: bool = False,
) -> BusinessRuleResponse:
    """Create a business rule. Refuses to create one that could never run."""
    # A script implies an advanced rule; that is the only combination in which
    # the script field means anything, so it is the default rather than a trap.
    resolved_advanced = advanced if advanced is not None else bool(script)

    unreachable = _execution_is_reachable(
        script=script,
        advanced=resolved_advanced,
        insert=action_insert,
        update=action_update,
        delete=action_delete,
        when=when,
    )
    if unreachable:
        return BusinessRuleResponse(
            success=False,
            message=f"Refusing to create a business rule that would never run: {unreachable}",
        )

    url = f"{config.instance_url}/api/now/table/sys_script"
    body: Dict[str, Any] = {
        "name": name,
        "collection": collection,
        "when": when,
        "order": str(order),
        "active": str(active).lower(),
        "advanced": str(resolved_advanced).lower(),
        "action_insert": str(action_insert).lower(),
        "action_update": str(action_update).lower(),
        "action_delete": str(action_delete).lower(),
    }
    if script:
        body["script"] = script
    if condition:
        body["condition"] = condition
    if filter_condition:
        body["filter_condition"] = filter_condition
    if description:
        body["description"] = description

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or "result" not in data:
            # A dead or redirected session answers with an HTML login page, and
            # .get() on that string dies with an unhelpful AttributeError.
            return BusinessRuleResponse(
                success=False,
                message=(
                    "Create returned no record. The response was not the expected JSON — "
                    "the session may have expired; re-authenticate and retry."
                ),
            )
        result = data["result"]
        invalidate_query_cache(table="sys_script")
        return BusinessRuleResponse(
            success=True,
            message=f"Created business rule '{result.get('name')}' on {result.get('collection')}",
            business_rule_id=result.get("sys_id"),
            business_rule_name=result.get("name"),
            table=result.get("collection"),
        )
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        logger.error(f"Error creating business rule: {exc}")
        return BusinessRuleResponse(success=False, message=f"Error creating business rule: {exc}")


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    business_rule_id: str,
    collection_filter: Optional[str] = None,
    dry_run: bool = False,
    **fields: Any,
) -> Union[BusinessRuleResponse, Dict[str, Any]]:
    """Update an existing business rule. Supports dry-run preview."""
    found = _fetch_br(config, auth_manager, business_rule_id, collection_filter)
    if isinstance(found, BusinessRuleResponse):
        return found

    sys_id = found["sys_id"]
    br_name = found.get("name")

    body: Dict[str, Any] = {}
    for key in _BR_UPDATE_FIELDS:
        value = fields.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            body[key] = str(value).lower()
        elif key == "order":
            body[key] = str(value)
        else:
            body[key] = value

    if not body:
        return BusinessRuleResponse(
            success=True,
            message=f"No changes to update for business rule: {br_name}",
            business_rule_id=sys_id,
            business_rule_name=br_name,
            table=found.get("collection"),
        )

    # The same two fields that make a NEW rule inert make an existing one inert.
    # Anything not being changed is read from the record rather than assumed —
    # inferring the current state from the absence of a parameter is how a rule
    # gets switched off by an edit that never mentioned it.
    merged_script = body.get("script", None)
    unreachable = _execution_is_reachable(
        script=merged_script if merged_script is not None else None,
        advanced=(
            fields.get("advanced")
            if fields.get("advanced") is not None
            else _as_bool(found.get("advanced"))
        ),
        insert=(
            fields.get("action_insert")
            if fields.get("action_insert") is not None
            else _as_bool(found.get("action_insert"))
        ),
        update=(
            fields.get("action_update")
            if fields.get("action_update") is not None
            else _as_bool(found.get("action_update"))
        ),
        delete=(
            fields.get("action_delete")
            if fields.get("action_delete") is not None
            else _as_bool(found.get("action_delete"))
        ),
        when=fields.get("when") or found.get("when"),
    )
    if unreachable:
        return BusinessRuleResponse(
            success=False,
            message=f"Refusing an update that would leave the rule unable to run: {unreachable}",
            business_rule_id=sys_id,
            business_rule_name=br_name,
            table=found.get("collection"),
        )

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sys_script",
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "collection", "when", "active"],
        )

    url = f"{config.instance_url}/api/now/table/sys_script/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or "result" not in data:
            return BusinessRuleResponse(
                success=False,
                message=(
                    f"Update of '{br_name}' returned no record. The response was not the "
                    "expected JSON — the session may have expired; re-authenticate and retry."
                ),
            )
        result = data["result"]
        invalidate_query_cache(table="sys_script")
        return BusinessRuleResponse(
            success=True,
            message=f"Updated business rule: {result.get('name')}",
            business_rule_id=result.get("sys_id"),
            business_rule_name=result.get("name"),
            table=result.get("collection"),
        )
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        logger.error(f"Error updating business rule: {exc}")
        return BusinessRuleResponse(success=False, message=f"Error updating business rule: {exc}")


def delete(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    business_rule_id: str,
    collection_filter: Optional[str] = None,
) -> BusinessRuleResponse:
    """Permanently delete a business rule."""
    found = _fetch_br(config, auth_manager, business_rule_id, collection_filter)
    if isinstance(found, BusinessRuleResponse):
        return found

    sys_id = found["sys_id"]
    name = found.get("name")
    url = f"{config.instance_url}/api/now/table/sys_script/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("DELETE", url, headers=headers, timeout=30)
        response.raise_for_status()
        invalidate_query_cache(table="sys_script")
        return BusinessRuleResponse(
            success=True,
            message=f"Deleted business rule: {name}",
            business_rule_id=sys_id,
            business_rule_name=name,
            table=found.get("collection"),
        )
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        logger.error(f"Error deleting business rule: {exc}")
        return BusinessRuleResponse(success=False, message=f"Error deleting business rule: {exc}")
