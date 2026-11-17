"""manage_portal_action — Employee Center actions (the OOTB action-widget's data).

The action widget renders buttons from five records: an action TYPE (server /
client script and the parameter names it reads), an ACTION (label, icon, table,
type), the action's PARAMETERS (fixed strings or a field of the ticket), a GROUP
and the GROUP LINKS that place an action in a group with a visibility script.

There was no tool for any of them, so every new button arrived as a hand-run
Background Script. Each call here writes ONE record (an action may carry its
parameters), goes through the normal confirm / update-set gates, and reads the
record back: a field the server dropped or truncated is reported, never
assumed to have landed.
"""

import logging
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.registry import register_tool

from .portal_crud_tools import align_session_for_create
from .sn_api import invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")


class _Kind:
    def __init__(
        self,
        table: str,
        fields: Tuple[str, ...],
        required: Tuple[str, ...],
        refs: Dict[str, Tuple[str, str]],
        unique: Tuple[str, ...],
    ):
        self.table = table
        self.fields = frozenset(fields)
        self.required = required
        self.refs = refs  # field -> (referenced table, column a non-sys_id value names)
        self.unique = unique  # fields that identify a duplicate


KINDS: Dict[str, _Kind] = {
    "type": _Kind(
        "sn_ex_sp_action_type",
        (
            "name",
            "active",
            "server_script",
            "server_parameters",
            "client_script",
            "client_parameters",
            "reverse_execution",
        ),
        ("name",),
        {},
        ("name",),
    ),
    "action": _Kind(
        "sn_ex_sp_action",
        ("name", "table", "action_type", "icon", "active"),
        ("name", "action_type"),
        {"action_type": ("sn_ex_sp_action_type", "name")},
        ("name", "table", "action_type"),
    ),
    "parameter": _Kind(
        "sn_ex_sp_action_parameter",
        (
            "action",
            "name",
            "parameter_type",
            "text",
            "field",
            "table",
            "json",
            "is_client",
            "is_display_value",
        ),
        ("action", "name", "parameter_type"),
        {"action": ("sn_ex_sp_action", "name")},
        ("action", "name"),
    ),
    "group": _Kind("sn_ex_sp_action_group", ("name", "active"), ("name",), {}, ("name",)),
    "link": _Kind(
        "sn_ex_sp_m2m_action_group",
        ("group", "action", "order", "action_visibility", "primary", "script", "user_criteria"),
        ("group", "action", "order", "action_visibility"),
        {
            "group": ("sn_ex_sp_action_group", "name"),
            "action": ("sn_ex_sp_action", "name"),
            "user_criteria": ("user_criteria", "name"),
        },
        ("group", "action"),
    ),
}


class ManagePortalActionParams(BaseModel):
    """Employee Center actions."""

    action: Literal["create", "update"] = Field(..., description="create one record, or update one")
    kind: Literal["type", "action", "parameter", "group", "link"] = Field(
        ..., description="type | action | parameter | group | link (action in a group)"
    )
    fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Column values. References take a sys_id or the record's name",
    )
    parameters: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="create kind=action: parameter rows created with it (name, parameter_type, ...)",
    )
    record_id: Optional[str] = Field(default=None, description="update: sys_id of the record")
    scope: Optional[str] = Field(
        default=None, description="create: sys_scope sys_id the record must land in"
    )
    update_set: Optional[str] = Field(
        default=None, description="create: update set name or sys_id to capture into"
    )
    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "create": frozenset({"kind", "fields", "parameters", "scope", "update_set", "dry_run"}),
        "update": frozenset({"kind", "fields", "record_id", "dry_run"}),
    }

    @model_validator(mode="after")
    def _validate(self) -> "ManagePortalActionParams":
        kind = KINDS[self.kind]
        unknown = sorted(set(self.fields) - kind.fields)
        if unknown:
            # ServiceNow drops an unknown column from a write without complaint,
            # so a typo would report success with the value missing.
            raise ValueError(
                f"unknown field(s) {unknown} for kind='{self.kind}'; allowed: {sorted(kind.fields)}"
            )
        if self.action == "create":
            missing = [f for f in kind.required if self.fields.get(f) in (None, "")]
            if missing:
                raise ValueError(f"create kind='{self.kind}' needs fields {missing}")
            if not self.scope:
                raise ValueError("scope is required for action='create'")
        else:
            if not self.record_id:
                raise ValueError("record_id is required for action='update'")
            if not self.fields:
                raise ValueError("update needs at least one field")
        if self.parameters is not None and not (self.action == "create" and self.kind == "action"):
            raise ValueError("parameters only go with action='create' kind='action'")
        for row in self.parameters or []:
            bad = sorted(set(row) - (KINDS["parameter"].fields - {"action"}))
            if bad:
                raise ValueError(f"unknown parameter field(s) {bad}")
            if not row.get("name") or not row.get("parameter_type"):
                raise ValueError("every parameter needs name and parameter_type")
        return self


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _raw(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _norm(value: Any) -> str:
    """Compare form: booleans as true/false, scripts without CR / trailing space."""
    text = _raw(value).replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _read(config, auth_manager, table: str, query: str, fields: str, limit: int):
    """Raises on failure — an unread row must never look like a missing one."""
    invalidate_query_cache(table=table)
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        fail_silently=False,
    )
    return rows or []


def _resolve_refs(config, auth_manager, kind: _Kind, values: Dict[str, Any]) -> Dict[str, Any]:
    """Names → sys_ids for reference fields; exactly one match or ValueError."""
    out = dict(values)
    for field, (table, column) in kind.refs.items():
        value = _raw(out.get(field))
        if not value or _SYS_ID.match(value):
            continue
        rows = _read(
            config, auth_manager, table, f"{column}={safe_value(value)}", "sys_id," + column, 5
        )
        if len(rows) != 1:
            raise ValueError(
                f"No {table} named '{value}'."
                if not rows
                else f"{len(rows)} {table} rows are named '{value}'; pass the sys_id."
            )
        out[field] = _raw(rows[0].get("sys_id"))
    return out


def _find_duplicate(config, auth_manager, kind: _Kind, values: Dict[str, Any]) -> List[str]:
    clauses = [f"{f}={safe_value(_raw(values.get(f)))}" for f in kind.unique]
    rows = _read(config, auth_manager, kind.table, "^".join(clauses), "sys_id", 5)
    return [_raw(r.get("sys_id")) for r in rows]


def _verify(config, auth_manager, table: str, sys_id: str, expected: Dict[str, Any]) -> List[str]:
    """Read back and list every field that did not land as written."""
    cols = sorted(set(expected) | {"sys_id"})
    try:
        rows = _read(config, auth_manager, table, f"sys_id={sys_id}", ",".join(cols), 1)
    except Exception as e:
        return [f"could not read back ({e})"]
    if not rows:
        return ["record not found on read-back"]
    problems = []
    for field, want in expected.items():
        have = rows[0].get(field)
        if _norm(have) != _norm(want):
            shown = _raw(have)
            shown = shown if len(shown) <= 60 else f"{len(shown)} chars"
            problems.append(f"{field} is '{shown}', not what was written")
    return problems


def _body(values: Dict[str, Any]) -> Dict[str, str]:
    return {k: _raw(v) for k, v in values.items()}


def _insert(config, auth_manager, table: str, body: Dict[str, str]) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{table}"
    response = auth_manager.make_request(
        "POST", url, json=body, headers=auth_manager.get_headers(), timeout=30
    )
    response.raise_for_status()
    invalidate_query_cache(table=table)
    return response.json().get("result") or {}


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _create(config, auth_manager, params: ManagePortalActionParams) -> Dict[str, Any]:
    kind = KINDS[params.kind]
    values = dict(params.fields)
    if params.kind in ("type", "action", "group") and "active" not in values:
        values["active"] = True
    try:
        values = _resolve_refs(config, auth_manager, kind, values)
        dupes = _find_duplicate(config, auth_manager, kind, values)
    except Exception as e:
        return {"success": False, "message": f"Could not check the target: {e}"}
    if dupes:
        return {
            "success": False,
            "message": (
                f"A {kind.table} row with the same {', '.join(kind.unique)} already exists. "
                "Change it with action='update' record_id=<sys_id>."
            ),
            "existing_sys_ids": dupes,
        }
    plan: Dict[str, Any] = {"table": kind.table, "fields": _body(values)}
    if params.parameters:
        plan["parameters"] = [_body(p) for p in params.parameters]
    if params.dry_run:
        return {"success": True, "dry_run": True, "operation": "create", **plan}

    aligned = align_session_for_create(
        config, auth_manager, scope=params.scope, update_set=params.update_set
    )
    if aligned.get("error"):
        return aligned["error"]
    extras = {k: v for k, v in aligned.items() if v}

    body = _body(values)
    try:
        sys_id = _raw(_insert(config, auth_manager, kind.table, body).get("sys_id"))
    except Exception as e:
        logger.error("Error creating %s: %s", kind.table, e)
        return {"success": False, "message": f"Error creating {kind.table}: {e}", **extras}
    # The scope comes from the session's current app, not the body: a record
    # that landed in another scope must not report as done.
    problems = _verify(
        config, auth_manager, kind.table, sys_id, {**body, "sys_scope": params.scope}
    )
    created = [{"table": kind.table, "sys_id": sys_id}]

    for row in params.parameters or []:
        p_body = _body({**row, "action": sys_id})
        try:
            p_id = _raw(
                _insert(config, auth_manager, KINDS["parameter"].table, p_body).get("sys_id")
            )
        except Exception as e:
            problems.append(f"parameter '{row.get('name')}' not created ({e}); stopped here")
            break
        created.append({"table": KINDS["parameter"].table, "sys_id": p_id, "name": row["name"]})
        problems += [
            f"parameter '{row['name']}': {p}"
            for p in _verify(config, auth_manager, KINDS["parameter"].table, p_id, p_body)
        ]

    undo = (
        f"manage_portal_action action='update' kind='{params.kind}' record_id='{sys_id}' "
        "fields={'active': false}"
        if "active" in kind.fields
        else "delete the created rows in the UI"
    )
    return {
        "success": True,
        "complete": not problems,
        "message": (
            f"Created {kind.table} {sys_id}"
            if not problems
            else "Created but NOT confirmed: " + "; ".join(problems)
        ),
        "sys_id": sys_id,
        "created": created,
        "missing": problems,
        "undo": undo,
        **extras,
    }


def _update(config, auth_manager, params: ManagePortalActionParams) -> Dict[str, Any]:
    kind = KINDS[params.kind]
    try:
        values = _resolve_refs(config, auth_manager, kind, params.fields)
        cols = ",".join(sorted(set(values) | {"sys_id"}))
        rows = _read(config, auth_manager, kind.table, f"sys_id={params.record_id}", cols, 1)
    except Exception as e:
        return {"success": False, "message": f"Could not read the record: {e}"}
    if not rows:
        return {"success": False, "message": f"No {kind.table} {params.record_id}."}
    body = _body(values)
    changes = {
        k: {"from": _raw(rows[0].get(k)), "to": v}
        for k, v in body.items()
        if _norm(rows[0].get(k)) != _norm(v)
    }
    if not changes:
        return {"success": True, "message": "Nothing to change", "record_id": params.record_id}
    if params.dry_run:
        return {"success": True, "dry_run": True, "operation": "update", "changes": changes}

    url = f"{config.instance_url}/api/now/table/{kind.table}/{params.record_id}"
    try:
        response = auth_manager.make_request(
            "PATCH", url, json=body, headers=auth_manager.get_headers(), timeout=30
        )
        response.raise_for_status()
    except Exception as e:
        logger.error("Error updating %s: %s", kind.table, e)
        return {"success": False, "message": f"Error updating {kind.table}: {e}"}
    assert params.record_id  # validator guarantees it for update
    problems = _verify(config, auth_manager, kind.table, params.record_id, body)
    return {
        "success": True,
        "complete": not problems,
        "message": (
            f"Updated {kind.table} {params.record_id}"
            if not problems
            else "Update sent but NOT confirmed: " + "; ".join(problems)
        ),
        "record_id": params.record_id,
        "changes": changes,
        "missing": problems,
    }


@register_tool(
    name="manage_portal_action",
    params=ManagePortalActionParams,
    description=(
        "Employee Center action-widget buttons: create/update action types, actions (+parameters), "
        "groups, group links."
    ),
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_portal_action(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManagePortalActionParams,
) -> Dict[str, Any]:
    if params.action == "create":
        return _create(config, auth_manager, params)
    return _update(config, auth_manager, params)
