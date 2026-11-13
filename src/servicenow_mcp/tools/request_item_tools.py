"""manage_request_item -- order catalog items and drive RITM / SCTASK fulfilment.

Ordering goes through the documented Service Catalog API (order_now). Every
write is re-read afterwards: ServiceNow accepts what it does not understand
(unknown variable names are dropped, a business rule may refuse a state change
without an error), so a write is only reported as applied once the record
shows it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_create_preview, build_update_preview
from servicenow_mcp.tools.record_context_tools import _lab, _val, resolve_table
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_RITM = "sc_req_item"
_TASK = "sc_task"

# Measured task.state choices (sc_req_item and sc_task inherit them).
_STATE_VALUES = {"1": "Open", "2": "Work in Progress", "-5": "Pending"}
_STATE_VALUES.update({"3": "Closed Complete", "4": "Closed Incomplete", "7": "Closed Skipped"})
_STATE_ALIASES = {
    "open": "1",
    "work in progress": "2",
    "in progress": "2",
    "wip": "2",
    "pending": "-5",
    "closed complete": "3",
    "complete": "3",
    "closed incomplete": "4",
    "incomplete": "4",
    "closed skipped": "7",
    "skipped": "7",
}

_UPDATE_FIELDS = (
    "assignment_group",
    "assigned_to",
    "work_notes",
    "comments",
    "short_description",
    "due_date",
)


class ManageRequestItemParams(BaseModel):
    """Order a catalog item and fulfil RITM / SCTASK records."""

    action: Literal["order", "get", "update", "set_state", "add_task"] = Field(
        ..., description="order | get | update | set_state | add_task"
    )
    item_id: Optional[str] = Field(default=None, description="Catalog item sys_id (order)")
    quantity: int = Field(default=1, description="Quantity (order)")
    variables: Optional[Dict[str, Any]] = Field(
        default=None, description="Variable name -> value; names are checked (order)"
    )
    requested_for: Optional[str] = Field(default=None, description="sys_user sys_id (order)")
    record_id: Optional[str] = Field(
        default=None, description="RITM/SCTASK number or sys_id (add_task: the RITM)"
    )
    short_description: Optional[str] = Field(default=None)
    assignment_group: Optional[str] = Field(default=None, description="Group sys_id or name")
    assigned_to: Optional[str] = Field(default=None, description="User sys_id or user_name")
    work_notes: Optional[str] = Field(default=None)
    comments: Optional[str] = Field(default=None)
    due_date: Optional[str] = Field(default=None)
    state: Optional[str] = Field(
        default=None,
        description="Name or value: Open, Work in Progress, Pending, Closed Complete, "
        "Closed Incomplete, Closed Skipped",
    )
    close_notes: Optional[str] = Field(default=None, description="Sent with set_state if given")
    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "order": frozenset({"item_id", "quantity", "variables", "requested_for", "dry_run"}),
        "get": frozenset({"record_id"}),
        "update": frozenset({"record_id", *_UPDATE_FIELDS, "dry_run"}),
        "set_state": frozenset({"record_id", "state", "close_notes", "dry_run"}),
        "add_task": frozenset({"record_id", "short_description", "assignment_group", "dry_run"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageRequestItemParams":
        a = self.action
        if a == "order":
            if not self.item_id or not _SYS_ID.match(self.item_id):
                raise ValueError("item_id (32-char sys_id) is required for action='order'")
            if self.quantity < 1:
                raise ValueError("quantity must be >= 1")
        elif not self.record_id:
            raise ValueError(f"record_id is required for action='{a}'")
        if a == "update" and not any(getattr(self, f) is not None for f in _UPDATE_FIELDS):
            raise ValueError("at least one field must be provided for action='update'")
        if a == "set_state" and not self.state:
            raise ValueError("state is required for action='set_state'")
        if a == "add_task" and not self.short_description:
            raise ValueError("short_description is required for action='add_task'")
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    *,
    display: "bool | str" = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Rows or raise. An unreadable table is never rendered as an empty one."""
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        display_value=display,
        no_count=True,
        fail_silently=False,
    )
    return rows


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1")


def _fail(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message, **extra}


def _locate(
    config: ServerConfig, auth_manager: AuthManager, record_id: str
) -> Tuple[Optional[Tuple[str, Dict[str, Any]]], Optional[Dict[str, Any]]]:
    """``((table, row), None)`` or ``(None, refusal)`` for a RITM/SCTASK number or sys_id."""
    fields = "sys_id,number,state,stage,request,request_item,cat_item,short_description"
    rid = record_id.strip()
    try:
        if _SYS_ID.match(rid):
            for table in (_RITM, _TASK):
                rows = _read(config, auth_manager, table, f"sys_id={rid}", fields, limit=1)
                if rows:
                    return (table, rows[0]), None
            return None, _fail("NOT_FOUND", f"No sc_req_item or sc_task with sys_id {rid}")
        upper = rid.upper()
        if upper.startswith("SCTASK"):
            table = _TASK
        elif upper.startswith("RITM"):
            table = _RITM
        else:
            found, refusal = resolve_table(config, auth_manager, rid)
            if refusal is not None:
                return None, refusal
            table = found or ""
            if table not in (_RITM, _TASK):
                return None, _fail(
                    "WRONG_TABLE", f"{rid} is a {table} record; expected a RITM or SCTASK"
                )
        rows = _read(config, auth_manager, table, f"number={upper}", fields, limit=1)
    except Exception as exc:  # noqa: BLE001 - reported, never read as "not found"
        return None, _fail("READ_FAILED", f"Could not read {rid}: {exc}")
    if not rows:
        return None, _fail("NOT_FOUND", f"{rid} not found in {table}")
    return (table, rows[0]), None


def _write(
    config: ServerConfig,
    auth_manager: AuthManager,
    method: str,
    url: str,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    response = auth_manager.make_request(
        method,
        url,
        json=body,
        headers=auth_manager.get_headers(),
        timeout=config.timeout,
    )
    response.raise_for_status()
    return response.json().get("result", {}) or {}


class _Variables:
    """An item's variables as the order API sees them.

    ``single``: names sent as plain values — the item's own variables plus those
    of single-row sets. ``multi``: multi-row variable sets by internal name, each
    with its column variables; the API takes such a set as ONE variable whose
    value is a JSON array of row objects, so its columns are never top-level.
    """

    def __init__(self) -> None:
        self.single: List[Dict[str, Any]] = []
        self.multi: Dict[str, List[Dict[str, Any]]] = {}

    def __len__(self) -> int:
        return len(self.single) + sum(len(cols) for cols in self.multi.values())


def _item_variables(config: ServerConfig, auth_manager: AuthManager, item_id: str) -> _Variables:
    """Active variables of an item: its own plus those of attached variable sets.

    A set's type is read, never assumed: treating a multi-row set's columns as
    plain variables demands them at the top level and refuses the set's own
    name, so an item built on one could not be ordered at all. A linked set
    whose record cannot be read raises — its shape is unknown.
    """
    cols = "name,mandatory,active,type,default_value"
    out = _Variables()
    out.single = [
        r
        for r in _read(
            config, auth_manager, "item_option_new", f"cat_item={item_id}^active=true", cols
        )
        if _val(r, "name")
    ]
    links = _read(config, auth_manager, "io_set_item", f"sc_cat_item={item_id}", "variable_set")
    sets = sorted({_val(r, "variable_set") for r in links if _val(r, "variable_set")})
    if not sets:
        return out
    set_rows = _read(
        config,
        auth_manager,
        "item_option_new_set",
        f"sys_idIN{','.join(sets)}",
        "sys_id,internal_name,type",
        limit=len(sets) + 1,
    )
    by_id = {_val(r, "sys_id"): r for r in set_rows}
    unread = [s for s in sets if s not in by_id]
    if unread:
        raise RuntimeError(f"variable set(s) {', '.join(unread)} could not be read")
    rows = _read(
        config,
        auth_manager,
        "item_option_new",
        f"variable_setIN{','.join(sets)}^active=true",
        cols + ",variable_set",
    )
    for row in rows:
        if not _val(row, "name"):
            continue
        owner = by_id.get(_val(row, "variable_set"))
        if owner is not None and _val(owner, "type") == "one_to_many":
            out.multi.setdefault(_val(owner, "internal_name"), []).append(row)
        else:
            out.single.append(row)
    for set_id in sets:
        owner = by_id[set_id]
        if _val(owner, "type") == "one_to_many":
            out.multi.setdefault(_val(owner, "internal_name"), [])
    return out


def _missing_mandatory(rows: List[Dict[str, Any]], given: Dict[str, Any]) -> List[str]:
    return sorted(
        _val(r, "name")
        for r in rows
        if _truthy(_val(r, "mandatory"))
        and not _val(r, "default_value")
        and given.get(_val(r, "name")) in (None, "")
    )


def _multi_rows(name: str, value: Any) -> Tuple[Optional[List[Any]], Optional[str]]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else []
        except ValueError:
            return None, f"{name} is a multi-row set: pass a list of row objects"
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        return None, f"{name} is a multi-row set: pass a list of row objects"
    return value, None


def _validate_variables(
    declared: _Variables, given: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """(refusal, payload variables). Multi-row sets go out as a JSON array string."""
    by_name = {_val(r, "name"): r for r in declared.single}
    known = set(by_name) | set(declared.multi)
    unknown = sorted(n for n in given if n not in known)
    if unknown:
        hint = {
            col: set_name
            for set_name, cols in declared.multi.items()
            for col in (_val(c, "name") for c in cols)
            if col in unknown
        }
        return (
            _fail(
                "UNKNOWN_VARIABLES",
                "Not variables of this item (the server would drop them silently): "
                + ", ".join(unknown)
                + ". Nothing was ordered."
                + (
                    " Columns of a multi-row set go inside it: "
                    + ", ".join(f"{c} -> {s}" for c, s in sorted(hint.items()))
                    + "."
                    if hint
                    else ""
                ),
                unknown=unknown,
                known=sorted(known),
            ),
            {},
        )
    missing = _missing_mandatory(declared.single, given)
    if missing:
        return (
            _fail(
                "MISSING_MANDATORY",
                "Mandatory variables with no value or default: "
                + ", ".join(missing)
                + ". Nothing was ordered.",
                missing=missing,
            ),
            {},
        )
    payload = dict(given)
    for set_name, cols in declared.multi.items():
        if set_name not in given:
            continue
        rows, error = _multi_rows(set_name, given[set_name])
        if error is not None:
            return _fail("BAD_MULTI_ROW_SET", error + ". Nothing was ordered."), {}
        assert rows is not None
        columns = {_val(c, "name") for c in cols}
        for index, row in enumerate(rows, 1):
            stray = sorted(k for k in row if k not in columns)
            if stray:
                return (
                    _fail(
                        "UNKNOWN_VARIABLES",
                        f"{set_name} row {index} has columns the set does not: "
                        f"{', '.join(stray)} (known: {', '.join(sorted(columns))}). "
                        "Nothing was ordered.",
                        unknown=stray,
                        known=sorted(columns),
                    ),
                    {},
                )
            lacking = _missing_mandatory(cols, row)
            if lacking:
                return (
                    _fail(
                        "MISSING_MANDATORY",
                        f"{set_name} row {index} lacks mandatory {', '.join(lacking)}. "
                        "Nothing was ordered.",
                        missing=lacking,
                    ),
                    {},
                )
        payload[set_name] = json.dumps(
            [{k: "" if v is None else str(v) for k, v in row.items()} for row in rows]
        )
    return None, payload


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _submit_producer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageRequestItemParams,
    given: Dict[str, Any],
    producer: Dict[str, Any],
    checked: int,
) -> Dict[str, Any]:
    """Submit a record producer and re-read the record it created."""
    payload: Dict[str, Any] = {"variables": given}
    if params.dry_run:
        return {
            "dry_run": True,
            "operation": "order",
            "route": "submit_producer",
            "target": {"item_id": params.item_id, "table": _val(producer, "table_name")},
            "payload": payload,
            "variables_checked": checked,
            "warnings": [],
        }
    url = f"{config.instance_url}/api/sn_sc/servicecatalog/items/{params.item_id}/submit_producer"
    try:
        result = _write(config, auth_manager, "POST", url, payload)
    except Exception as exc:  # noqa: BLE001
        return _fail("ORDER_FAILED", f"Producer submit failed: {exc}")
    sys_id = str(result.get("sys_id") or "")
    table = str(result.get("table") or _val(producer, "table_name") or "")
    number = result.get("number")
    out: Dict[str, Any] = {
        "success": True,
        "route": "submit_producer",
        "table": table or None,
        "number": number,
        "sys_id": sys_id or None,
    }
    if not _SYS_ID.match(sys_id) or not _TABLE_NAME.match(table):
        out.update(
            success=False,
            applied=False,
            message="Submitted, but the response carried no usable sys_id/table, so the "
            "created record could not be confirmed. Look it up before assuming it exists.",
        )
        return out
    invalidate_query_cache(table=table)
    try:
        rows = _read(config, auth_manager, table, f"sys_id={sys_id}", "sys_id,number", limit=1)
    except Exception as exc:  # noqa: BLE001
        out.update(
            applied=False, message=f"Submitted, but the re-read failed ({exc}): unconfirmed."
        )
        return out
    if not rows:
        out.update(
            applied=False,
            message=f"Submitted, but no {table} record {sys_id} could be read back: unconfirmed.",
        )
        return out
    out.update(applied=True, number=_val(rows[0], "number") or number)
    return out


def _order(
    config: ServerConfig, auth_manager: AuthManager, params: ManageRequestItemParams
) -> Dict[str, Any]:
    assert params.item_id is not None
    given = dict(params.variables or {})
    try:
        declared = _item_variables(config, auth_manager, params.item_id)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "VARIABLES_UNVERIFIED",
            f"Could not read the item's variables, so the order cannot be checked: {exc}. "
            "Nothing was ordered.",
        )
    refusal, given = _validate_variables(declared, given)
    if refusal is not None:
        return refusal

    # A record producer creates a record directly; order_now would not. Reading the
    # producer table by sys_id covers the class and every child of it. An unreadable
    # answer is a refusal: guessing the route would order the wrong thing.
    try:
        producers = _read(
            config,
            auth_manager,
            "sc_cat_item_producer",
            f"sys_id={params.item_id}",
            "sys_id,table_name,sys_class_name",
            limit=1,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "ITEM_CLASS_UNVERIFIED",
            f"Could not tell whether the item is a record producer: {exc}. Nothing was ordered.",
        )
    if producers:
        return _submit_producer(config, auth_manager, params, given, producers[0], len(declared))

    payload: Dict[str, Any] = {"sysparm_quantity": str(params.quantity), "variables": given}
    if params.requested_for:
        payload["sysparm_requested_for"] = params.requested_for
    if params.dry_run:
        return {
            "dry_run": True,
            "operation": "order",
            "target": {"item_id": params.item_id},
            "payload": payload,
            "variables_checked": len(declared),
            "warnings": [],
        }

    url = f"{config.instance_url}/api/sn_sc/servicecatalog/items/{params.item_id}/order_now"
    try:
        result = _write(config, auth_manager, "POST", url, payload)
    except Exception as exc:  # noqa: BLE001
        return _fail("ORDER_FAILED", f"Order failed: {exc}")
    invalidate_query_cache(table="sc_request")
    invalidate_query_cache(table=_RITM)

    request_id = result.get("request_id") or ""
    out: Dict[str, Any] = {
        "success": True,
        "request_number": result.get("request_number"),
        "request_id": request_id or None,
        "number": result.get("number"),
        "sys_id": result.get("sys_id"),
        "table": result.get("table"),
    }
    if not request_id:
        out.update(
            confirmed=False,
            message="Order was posted but the response carried no request_id: unconfirmed. "
            "Look the request up by number before assuming it exists.",
        )
        return out
    try:
        reqs = _read(
            config,
            auth_manager,
            "sc_request",
            f"sys_id={request_id}",
            "sys_id,number,stage,state",
            display="all",
            limit=1,
        )
        ritms = _read(
            config,
            auth_manager,
            _RITM,
            f"request={request_id}",
            "sys_id,number,state,stage,cat_item",
            display="all",
        )
    except Exception as exc:  # noqa: BLE001
        out.update(
            confirmed=False, message=f"Ordered, but the re-read failed ({exc}): unconfirmed."
        )
        return out
    if not reqs or not ritms:
        out.update(
            confirmed=False,
            message="Ordered, but the re-read found "
            + ("no sc_request" if not reqs else "no sc_req_item")
            + ": unconfirmed.",
        )
        return out
    out["confirmed"] = True
    out["request"] = {
        "number": _val(reqs[0], "number"),
        "stage": _lab(reqs[0], "stage"),
        "state": _lab(reqs[0], "state"),
    }
    out["items"] = [
        {
            "number": _val(r, "number"),
            "sys_id": _val(r, "sys_id"),
            "state": _lab(r, "state"),
            "stage": _lab(r, "stage"),
            "cat_item_ok": _val(r, "cat_item") == params.item_id,
        }
        for r in ritms
    ]
    return out


def _get(
    config: ServerConfig, auth_manager: AuthManager, params: ManageRequestItemParams
) -> Dict[str, Any]:
    assert params.record_id is not None
    found, refusal = _locate(config, auth_manager, params.record_id)
    if refusal is not None:
        return refusal
    assert found is not None
    table, base = found
    if table == _RITM:
        fields = (
            "sys_id,number,short_description,state,stage,approval,request,cat_item,"
            "assigned_to,assignment_group,due_date,parent,universal_request"
        )
    else:
        fields = (
            "sys_id,number,short_description,state,request_item,request,cat_item,"
            "assigned_to,assignment_group,due_date"
        )
    try:
        rows = _read(
            config,
            auth_manager,
            table,
            f"sys_id={_val(base, 'sys_id')}",
            fields,
            display="all",
            limit=1,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail("READ_FAILED", f"Could not read {params.record_id}: {exc}")
    if not rows:
        return _fail("NOT_FOUND", f"{params.record_id} vanished between reads")
    record: Dict[str, Any] = {"table": table}
    for f in fields.split(","):
        shown = _lab(rows[0], f)
        if shown != "":
            record[f] = shown
    record["sys_id"] = _val(rows[0], "sys_id")
    return {"success": True, "record": record}


def _update(
    config: ServerConfig, auth_manager: AuthManager, params: ManageRequestItemParams
) -> Dict[str, Any]:
    assert params.record_id is not None
    found, refusal = _locate(config, auth_manager, params.record_id)
    if refusal is not None:
        return refusal
    assert found is not None
    table, base = found
    sys_id = _val(base, "sys_id")
    data = {f: getattr(params, f) for f in _UPDATE_FIELDS if getattr(params, f) is not None}
    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=table,
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )
    try:
        _write(config, auth_manager, "PUT", f"{config.api_url}/table/{table}/{sys_id}", data)
    except Exception as exc:  # noqa: BLE001
        return _fail("UPDATE_FAILED", f"Update failed: {exc}")
    invalidate_query_cache(table=table)
    return {
        "success": True,
        "table": table,
        "number": _val(base, "number"),
        "updated": sorted(data),
    }


def _resolve_state(requested: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    key = requested.strip()
    if key in _STATE_VALUES:
        return key, None
    value = _STATE_ALIASES.get(key.lower())
    if value is not None:
        return value, None
    return None, _fail(
        "UNKNOWN_CHOICE",
        f"{requested!r} is not a task.state choice. Nothing was written.",
        choices=_STATE_VALUES,
    )


def _set_state(
    config: ServerConfig, auth_manager: AuthManager, params: ManageRequestItemParams
) -> Dict[str, Any]:
    assert params.record_id is not None and params.state is not None
    wanted, refusal = _resolve_state(params.state)
    if refusal is not None:
        return refusal
    assert wanted is not None
    found, refusal = _locate(config, auth_manager, params.record_id)
    if refusal is not None:
        return refusal
    assert found is not None
    table, base = found
    sys_id = _val(base, "sys_id")
    data: Dict[str, Any] = {"state": wanted}
    if params.close_notes is not None:
        data["close_notes"] = params.close_notes
    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=table,
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )
    try:
        _write(config, auth_manager, "PUT", f"{config.api_url}/table/{table}/{sys_id}", data)
    except Exception as exc:  # noqa: BLE001
        return _fail("UPDATE_FAILED", f"State change failed: {exc}")
    invalidate_query_cache(table=table)
    fields = "sys_id,number,state,stage" if table == _RITM else "sys_id,number,state"
    out: Dict[str, Any] = {
        "table": table,
        "number": _val(base, "number"),
        "requested": {"value": wanted, "label": _STATE_VALUES[wanted]},
    }
    try:
        rows = _read(
            config, auth_manager, table, f"sys_id={sys_id}", fields, display="all", limit=1
        )
    except Exception as exc:  # noqa: BLE001
        return {
            **out,
            "success": True,
            "applied": None,
            "message": f"Written, but the re-read failed ({exc}): not confirmed.",
        }
    if not rows:
        return {
            **out,
            "success": True,
            "applied": None,
            "message": "Written, but the record could not be re-read: not confirmed.",
        }
    actual = rows[0].get("state")
    actual_value = _val(rows[0], "state")
    applied = actual_value == wanted
    out.update(
        success=applied,
        applied=applied,
        state={"value": actual_value, "label": _lab(rows[0], "state")},
    )
    if table == _RITM:
        out["stage"] = _lab(rows[0], "stage")
    if not applied:
        out["message"] = (
            f"The platform did not take state {wanted}: the record is at "
            f"{_lab(rows[0], 'state') or actual}. A business rule or state model refused it."
        )
    return out


def _add_task(
    config: ServerConfig, auth_manager: AuthManager, params: ManageRequestItemParams
) -> Dict[str, Any]:
    assert params.record_id is not None and params.short_description is not None
    found, refusal = _locate(config, auth_manager, params.record_id)
    if refusal is not None:
        return refusal
    assert found is not None
    table, base = found
    if table != _RITM:
        return _fail("WRONG_TABLE", "add_task needs a RITM; record_id is a task.")
    ritm_id = _val(base, "sys_id")
    request_id = _val(base, "request")
    if not request_id:
        return _fail("NO_REQUEST", "The RITM has no request reference; nothing was created.")
    data: Dict[str, Any] = {
        "request_item": ritm_id,
        "request": request_id,
        "short_description": params.short_description,
    }
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.dry_run:
        return build_create_preview(table=_TASK, proposed=data)
    try:
        result = _write(config, auth_manager, "POST", f"{config.api_url}/table/{_TASK}", data)
    except Exception as exc:  # noqa: BLE001
        return _fail("CREATE_FAILED", f"Task creation failed: {exc}")
    invalidate_query_cache(table=_TASK)
    out: Dict[str, Any] = {
        "success": True,
        "number": result.get("number"),
        "sys_id": result.get("sys_id"),
        "table": _TASK,
    }
    try:
        rows = _read(
            config,
            auth_manager,
            _TASK,
            f"sys_id={result.get('sys_id')}",
            "sys_id,number,state,request_item,request",
            display="all",
            limit=1,
        )
    except Exception as exc:  # noqa: BLE001
        out.update(confirmed=False, message=f"Created, but the re-read failed ({exc}).")
        return out
    if not rows:
        out.update(confirmed=False, message="Created, but the task could not be re-read.")
        return out
    out.update(
        confirmed=True,
        state=_lab(rows[0], "state"),
        wired=_val(rows[0], "request_item") == ritm_id and _val(rows[0], "request") == request_id,
    )
    return out


@register_tool(
    "manage_request_item",
    params=ManageRequestItemParams,
    description="Order a catalog item, get/update/set_state a RITM or SCTASK, add_task. Writes are re-read.",
    serialization="raw_dict",
    return_type=dict,
)
def manage_request_item(
    config: ServerConfig, auth_manager: AuthManager, params: ManageRequestItemParams
) -> Dict[str, Any]:
    if params.action == "order":
        return _order(config, auth_manager, params)
    if params.action == "get":
        return _get(config, auth_manager, params)
    if params.action == "update":
        return _update(config, auth_manager, params)
    if params.action == "set_state":
        return _set_state(config, auth_manager, params)
    return _add_task(config, auth_manager, params)
