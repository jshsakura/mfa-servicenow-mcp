"""manage_task_rule — assignment rules and approval rules, configured without scripts.

``kind`` picks the table: ``assignment`` -> sysrule_assignment, ``approval`` ->
sysrule_approvals. A rule is set up by condition + group/user (+ set_state for
approvals); this tool has no script parameter and never writes the ``script``
field. A rule that genuinely needs a script is a customization for a human.

Every write is re-read and answered with ``applied`` (what the record holds
now), never with what was asked for. Existing rules that are OOTB / protected
are refused through the same check the catalog tools use.
"""

import logging
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.catalog import _is_customer_package, _writable_target
from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.query_fields import near_matches, table_columns, unknown_query_fields
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

_TABLES = {"assignment": "sysrule_assignment", "approval": "sysrule_approvals"}
_BASE_FIELDS = ("name", "table", "condition", "group", "user", "order", "active", "description")
_APPROVAL_ONLY = ("optional_group", "set_state", "run_rule_before")
_REF_FIELDS = ("group", "user", "optional_group")
_BOOL_FIELDS = ("active", "run_rule_before")
_WRITE_FIELDS = _BASE_FIELDS + _APPROVAL_ONLY
_READ_FIELDS = (
    "sys_id,name,table,condition,group,user,order,active,description,match_conditions,"
    "script,sys_policy,sys_package,sys_scope,sys_updated_on"
)
_APPROVAL_READ = ",optional_group,set_state,run_rule_before"


class ManageTaskRuleParams(BaseModel):
    """Assignment and approval rules."""

    action: Literal["list", "get", "create", "update"] = Field(..., description="Operation")
    kind: Literal["assignment", "approval"] = Field(
        ..., description="assignment = sysrule_assignment, approval = sysrule_approvals"
    )

    rule_id: Optional[str] = Field(default=None, description="Rule sys_id or exact name")
    full: bool = Field(default=False, description="get: include the script body")
    active_only: Optional[bool] = Field(
        default=None, description="list: true = active only, false = inactive only"
    )
    limit: int = Field(default=50, ge=1, le=200, description="list: max rows")
    offset: int = Field(default=0, ge=0, description="list: rows to skip")

    name: Optional[str] = Field(default=None)
    table: Optional[str] = Field(default=None, description="Table the rule runs on (also a filter)")
    condition: Optional[str] = Field(default=None, description="Encoded query, e.g. category=hw^EQ")
    group: Optional[str] = Field(default=None, description="Group name or sys_id; '' clears")
    user: Optional[str] = Field(default=None, description="user_name or sys_id; '' clears")
    order: Optional[int] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    description: Optional[str] = Field(default=None)
    optional_group: Optional[str] = Field(
        default=None, description="approval: group name or sys_id; '' clears"
    )
    set_state: Optional[str] = Field(
        default=None, description="approval: approval state to set (value or label); '' clears"
    )
    run_rule_before: Optional[bool] = Field(default=None, description="approval: run before")

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"kind", "table", "active_only", "limit", "offset"}),
        "get": frozenset({"kind", "rule_id", "full"}),
        "create": frozenset({"kind", "dry_run", *_WRITE_FIELDS}),
        "update": frozenset({"kind", "rule_id", "dry_run", *_WRITE_FIELDS}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageTaskRuleParams":
        a = self.action
        if a == "list":
            return self
        if a in ("get", "update") and not self.rule_id:
            raise ValueError(f"rule_id is required for action='{a}'")
        if self.kind == "assignment":
            stray = [f for f in _APPROVAL_ONLY if getattr(self, f) is not None]
            if stray:
                raise ValueError(f"{', '.join(stray)} only apply to kind='approval'")
        if a == "create":
            if not self.name or not self.table:
                raise ValueError("name and table are required for action='create'")
            if self.kind == "assignment" and not (self.group or self.user):
                raise ValueError("an assignment rule needs a group or a user")
            if self.kind == "approval" and not (
                self.group or self.user or self.optional_group or self.set_state
            ):
                raise ValueError(
                    "an approval rule needs a group, user, optional_group or set_state"
                )
        if a == "update" and not any(getattr(self, f) is not None for f in _WRITE_FIELDS):
            raise ValueError("at least one field must be provided for action='update'")
        return self


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _raw(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def _disp(value: Any) -> Any:
    return value.get("display_value") if isinstance(value, dict) else value


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int,
    offset: int = 0,
    orderby: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    return sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        display_value="all",
        orderby=orderby,
        fail_silently=False,
    )


def readable_condition(condition: str) -> str:
    """Encoded query as one line a person can read. Display only, never written back."""
    text = (condition or "").strip()
    if not text:
        return "(always)"
    text = re.sub(r"\^EQ$", "", text)
    text = text.replace("^NQ", " OR-GROUP ").replace("^OR", " OR ").replace("^", " AND ")
    return re.sub(r"\s+", " ", text).strip()


def _flat(row: Dict[str, Any], kind: str) -> Dict[str, Any]:
    pkg_v, pkg_l = str(_raw(row.get("sys_package")) or ""), str(_disp(row.get("sys_package")) or "")
    scope_l = str(_disp(row.get("sys_scope")) or "")
    policy = str(_raw(row.get("sys_policy")) or "").strip().lower()
    editable = policy not in ("read", "protected") and _is_customer_package(pkg_v, pkg_l, scope_l)
    cond = str(_raw(row.get("condition")) or "")
    out: Dict[str, Any] = {
        "sys_id": _raw(row.get("sys_id")),
        "name": _raw(row.get("name")),
        "table": _raw(row.get("table")),
        "active": str(_raw(row.get("active"))).lower() == "true",
        "order": _raw(row.get("order")),
        "condition": cond.strip(),
        "condition_readable": readable_condition(cond),
        "group": _disp(row.get("group")) or None,
        "user": _disp(row.get("user")) or None,
        "has_script": bool(str(_raw(row.get("script")) or "").strip()),
        "editable": editable,
    }
    if not editable:
        out["package"] = pkg_l or scope_l or policy
    if kind == "approval":
        out["optional_group"] = _disp(row.get("optional_group")) or None
        out["set_state"] = _raw(row.get("set_state")) or None
        out["run_rule_before"] = str(_raw(row.get("run_rule_before"))).lower() == "true"
    return out


def _fields_for(kind: str) -> str:
    return _READ_FIELDS + (_APPROVAL_READ if kind == "approval" else "")


def _find_rule(
    config: ServerConfig, auth_manager: AuthManager, kind: str, ident: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(row, None) or (None, refusal). 0 rows is 'absent or hidden', never 'does not exist'."""
    table = _TABLES[kind]
    ident = ident.strip()
    query = f"sys_id={ident}" if _SYS_ID.match(ident) else f"name={safe_value(ident).value}"
    try:
        rows, _ = _read(config, auth_manager, table, query, _fields_for(kind), 10)
    except Exception as e:
        return None, _fail(f"Failed to read {table}: {e}. Nothing was written.", determined=False)
    if not rows:
        return None, _fail(
            f"{table} {ident!r} was not returned: absent, or hidden from this account by ACL "
            "(the two look the same). Nothing was written.",
            determined=False,
        )
    if len(rows) > 1:
        return None, _fail(
            f"{len(rows)} {table} rules are named {ident!r}; pass the sys_id.",
            candidates=[
                {"sys_id": _raw(r.get("sys_id")), "table": _raw(r.get("table"))} for r in rows
            ],
        )
    return rows[0], None


def _resolve_party(
    config: ServerConfig, auth_manager: AuthManager, field: str, value: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Group/user name -> sys_id. '' clears. 0 or >1 matches refuse, with candidates."""
    value = value.strip()
    if value == "":
        return "", None
    is_user = field == "user"
    table = "sys_user" if is_user else "sys_user_group"
    shown = "sys_id,user_name,name" if is_user else "sys_id,name"
    if _SYS_ID.match(value):
        queries = [f"sys_id={value}"]
    elif is_user:
        queries = [f"user_name={safe_value(value).value}", f"name={safe_value(value).value}"]
    else:
        queries = [f"name={safe_value(value).value}"]
    rows: List[Dict[str, Any]] = []
    try:
        for q in queries:
            rows, _ = _read(config, auth_manager, table, q + "^active=true", shown, 6)
            if rows:
                break
    except Exception as e:
        return None, _fail(f"Could not resolve {field} {value!r}: {e}. Nothing was written.")
    if len(rows) == 1:
        return str(_raw(rows[0].get("sys_id"))), None
    if not rows:
        close: List[str] = []
        try:
            like, _ = _read(
                config,
                auth_manager,
                table,
                f"nameLIKE{safe_value(value).value}^active=true",
                shown,
                5,
            )
            close = [str(_disp(r.get("name"))) for r in like]
        except Exception:
            pass
        return None, _fail(
            f"No active {table} row matches {field} {value!r} (absent, or hidden from this "
            "account by ACL). Nothing was written.",
            field=field,
            candidates=close,
        )
    return None, _fail(
        f"{len(rows)} active {table} rows match {field} {value!r}; pass a sys_id. "
        "Nothing was written.",
        field=field,
        candidates=[
            {
                "sys_id": _raw(r.get("sys_id")),
                "name": _disp(r.get("name")),
                **({"user_name": _raw(r.get("user_name"))} if is_user else {}),
            }
            for r in rows
        ],
    )


def _check_table(
    config: ServerConfig, auth_manager: AuthManager, table: str
) -> Optional[Dict[str, Any]]:
    if not _TABLE_NAME.match(table):
        return _fail(f"{table!r} is not a table name. Nothing was written.", field="table")
    try:
        rows, _ = _read(config, auth_manager, "sys_db_object", f"name={table}", "name", 1)
    except Exception as e:
        return _fail(f"Could not verify table {table!r}: {e}. Nothing was written.", field="table")
    if not rows:
        return _fail(
            f"Table {table!r} was not returned by sys_db_object: absent, or hidden from this "
            "account. Nothing was written.",
            field="table",
        )
    return None


def _check_condition(
    config: ServerConfig, auth_manager: AuthManager, table: str, condition: str
) -> Optional[Dict[str, Any]]:
    """A condition naming a column the table lacks has that term DROPPED by the server."""
    if not condition.strip():
        return None
    missing = unknown_query_fields(config, auth_manager, table, condition)
    if missing is None:
        return _fail(
            f"Could not read the columns of {table}, so the condition cannot be checked "
            "(an unknown field is silently dropped by ServiceNow). Nothing was written.",
            field="condition",
        )
    if missing:
        cols = table_columns(config, auth_manager, table) or set()
        return _fail(
            f"The condition names fields {table} does not have: {missing}. ServiceNow would "
            "drop those terms and the rule would match far more than intended. Nothing was written.",
            field="condition",
            did_you_mean={m: near_matches(m, sorted(cols)) for m in missing},
        )
    return None


def _build_payload(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageTaskRuleParams,
    effective_table: str,
    effective_condition: Optional[str],
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    data: Dict[str, Any] = {}
    for f in _WRITE_FIELDS:
        v = getattr(params, f)
        if v is None:
            continue
        data[f] = v
    if "table" in data:
        refusal = _check_table(config, auth_manager, data["table"])
        if refusal:
            return data, refusal
    if "condition" in data or "table" in data:
        refusal = _check_condition(config, auth_manager, effective_table, effective_condition or "")
        if refusal:
            return data, refusal
    for f in _REF_FIELDS:
        if f in data:
            sys_id, refusal = _resolve_party(config, auth_manager, f, str(data[f]))
            if refusal:
                return data, refusal
            data[f] = sys_id
    if data.get("set_state"):
        value, refusal = resolve_choice(
            config,
            auth_manager,
            table=_TABLES["approval"],
            element="set_state",
            requested=str(data["set_state"]),
        )
        if refusal:
            return data, refusal
        data["set_state"] = value
    for f in _BOOL_FIELDS:
        if f in data:
            data[f] = "true" if data[f] else "false"
    if "order" in data:
        data["order"] = str(data["order"])
    return data, None


def _same(wanted: Any, got: Any) -> bool:
    w, g = str(wanted).strip(), str(_raw(got) if _raw(got) is not None else "").strip()
    if w in ("true", "false"):
        return w == g.lower()
    return w == g


def _reread(
    config: ServerConfig, auth_manager: AuthManager, kind: str, sys_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Re-read the rule and report which written fields it actually holds."""
    table = _TABLES[kind]
    base = {"sys_id": sys_id, "kind": kind}
    try:
        rows, _ = _read(config, auth_manager, table, f"sys_id={sys_id}", _fields_for(kind), 1)
    except Exception as e:
        return {
            "success": True,
            **base,
            "verified": False,
            "applied": None,
            "message": f"Write sent but the re-read failed ({e}); the result is UNVERIFIED.",
        }
    if not rows:
        return {
            "success": True,
            **base,
            "verified": False,
            "applied": None,
            "message": "Write sent but the rule was not returned on re-read; UNVERIFIED.",
        }
    row = rows[0]
    not_applied = {
        f: {"requested": v, "actual": _raw(row.get(f))}
        for f, v in data.items()
        if not _same(v, row.get(f))
    }
    out: Dict[str, Any] = {
        "success": not not_applied,
        **base,
        "verified": True,
        "applied": not not_applied,
        "rule": _flat(row, kind),
    }
    if not_applied:
        out["not_applied"] = not_applied
        out["message"] = "The write was accepted but these fields do not hold the requested value."
    else:
        out["message"] = "Rule saved and confirmed by re-read."
    return out


def _approval_note(kind: str, flat: Dict[str, Any]) -> Optional[str]:
    if kind == "approval" and not flat.get("set_state") and not flat.get("has_script"):
        return (
            "This rule has no set_state and no script, so it resolves approvers but never moves "
            "the record's approval state."
        )
    return None


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _list(config, auth_manager, params: ManageTaskRuleParams) -> Dict[str, Any]:
    kind = params.kind
    table = _TABLES[kind]
    parts: List[str] = []
    if params.table:
        if not _TABLE_NAME.match(params.table):
            return _fail(f"{params.table!r} is not a table name.", field="table")
        parts.append(f"table={params.table}")
    if params.active_only is not None:
        parts.append(f"active={'true' if params.active_only else 'false'}")
    try:
        rows, total = _read(
            config,
            auth_manager,
            table,
            "^".join(parts),
            _fields_for(kind),
            params.limit,
            params.offset,
            orderby="table",
        )
    except Exception as e:
        return _fail(f"Failed to read {table}: {e}", determined=False)
    out: Dict[str, Any] = {
        "success": True,
        "kind": kind,
        "count": len(rows),
        "total": total,
        "rules": [_flat(r, kind) for r in rows],
    }
    if total is not None and params.offset + len(rows) < total:
        out["truncated"] = True
        out["note"] = (
            f"{total - params.offset - len(rows)} more; pass offset={params.offset + len(rows)}."
        )
    if not rows:
        out["note"] = (
            "No rows returned: none match, or this account cannot read them (the two look the same)."
        )
    return out


def _get(config, auth_manager, params: ManageTaskRuleParams) -> Dict[str, Any]:
    assert params.rule_id
    row, refusal = _find_rule(config, auth_manager, params.kind, params.rule_id)
    if refusal:
        return refusal
    assert row
    flat = _flat(row, params.kind)
    out: Dict[str, Any] = {"success": True, "kind": params.kind, "rule": flat}
    if params.full and flat["has_script"]:
        out["script"] = _raw(row.get("script"))
    elif flat["has_script"]:
        out["note"] = "Has a script (body withheld); get with full=true to read it."
    return out


def _create(config, auth_manager, params: ManageTaskRuleParams) -> Dict[str, Any]:
    assert params.table
    try:
        data, refusal = _build_payload(config, auth_manager, params, params.table, params.condition)
    except Exception as e:
        return _fail(f"Could not resolve create fields: {e}. Nothing was written.")
    if refusal:
        return refusal
    if params.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "operation": "create",
            "kind": params.kind,
            "would_write": data,
        }
    table = _TABLES[params.kind]
    try:
        resp = auth_manager.make_request(
            "POST",
            f"{config.api_url}/table/{table}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        resp.raise_for_status()
        sys_id = str(_raw(resp.json().get("result", {}).get("sys_id")) or "")
        invalidate_query_cache(table=table)
    except Exception as e:
        logger.error(f"Failed to create {table} rule: {e}")
        return _fail(f"Failed to create rule: {e}")
    if not sys_id:
        return _fail("The create was accepted but returned no sys_id; UNVERIFIED.", applied=None)
    out = _reread(config, auth_manager, params.kind, sys_id, data)
    note = _approval_note(params.kind, out.get("rule", {}))
    if note:
        out["warning"] = note
    return out


def _update(config, auth_manager, params: ManageTaskRuleParams) -> Dict[str, Any]:
    assert params.rule_id
    row, refusal = _find_rule(config, auth_manager, params.kind, params.rule_id)
    if refusal:
        return refusal
    assert row
    sys_id = str(_raw(row.get("sys_id")))
    table = _TABLES[params.kind]
    guard = _writable_target(config, auth_manager, table, sys_id)
    if guard:
        return guard
    eff_table = params.table or str(_raw(row.get("table")) or "")
    eff_cond = (
        params.condition if params.condition is not None else str(_raw(row.get("condition")) or "")
    )
    try:
        data, refusal = _build_payload(config, auth_manager, params, eff_table, eff_cond)
    except Exception as e:
        return _fail(f"Could not resolve update fields: {e}. Nothing was written.")
    if refusal:
        return refusal
    if params.dry_run:
        changes = {
            f: {"from": _raw(row.get(f)), "to": v}
            for f, v in data.items()
            if not _same(v, row.get(f))
        }
        return {
            "success": True,
            "dry_run": True,
            "operation": "update",
            "kind": params.kind,
            "sys_id": sys_id,
            "proposed_changes": changes,
            "no_op_fields": [f for f in data if f not in changes],
        }
    try:
        resp = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/{table}/{sys_id}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        resp.raise_for_status()
        invalidate_query_cache(table=table)
    except Exception as e:
        logger.error(f"Failed to update {table} rule: {e}")
        return _fail(f"Failed to update rule: {e}", sys_id=sys_id)
    out = _reread(config, auth_manager, params.kind, sys_id, data)
    note = _approval_note(params.kind, out.get("rule", {}))
    if note:
        out["warning"] = note
    return out


@register_tool(
    "manage_task_rule",
    params=ManageTaskRuleParams,
    description="Assignment/approval rules: list, get, create, update by condition + group/user. No scripts, no delete.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_task_rule(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageTaskRuleParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "list":
        return _list(config, auth_manager, params)
    if a == "get":
        return _get(config, auth_manager, params)
    if a == "create":
        return _create(config, auth_manager, params)
    return _update(config, auth_manager, params)
