"""manage_problem — problem records (table: problem), links and state.

Writes go through the Table API only. A state write is NOT the form's UI
action: business rules may refuse or revert it, so every write is re-read and
the response says what the record holds now, not what was asked for.
"""

import logging
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.choices import resolve_choice, resolve_payload_choices
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_NUMBER = re.compile(r"^([A-Za-z]{3,})\d+$")
_NUMBER_TABLES = {"INC": "incident", "PRB": "problem", "CHG": "change_request"}

_PROBLEM_COMMON_FIELDS = (
    "short_description",
    "description",
    "category",
    "subcategory",
    "impact",
    "urgency",
    "assignment_group",
    "assigned_to",
    "cmdb_ci",
    "first_reported_by_task",
)
_PROBLEM_UPDATE_FIELDS = _PROBLEM_COMMON_FIELDS + (
    "workaround",
    "cause_notes",
    "fix_notes",
    "resolution_code",
    "close_notes",
    "duplicate_of",
)
_PROBLEM_CHOICE_FIELDS = ("impact", "urgency", "resolution_code")
_NOTE_FIELDS = ("workaround", "cause_notes", "fix_notes")
_GET_FIELDS = (
    "sys_id,number,state,short_description,assignment_group,assigned_to,known_error,rfc,"
    "first_reported_by_task,related_incidents,major_problem,duplicate_of,resolution_code,"
    "workaround,cause_notes,fix_notes,sys_updated_on"
)

_STATE_HINT = (
    "The Table API write is not the form's UI action; the OOTB path for this "
    "transition is the problem form's UI actions."
)


class ManageProblemParams(BaseModel):
    """Manage problems — table: problem."""

    action: Literal[
        "get",
        "create",
        "update",
        "link_incidents",
        "unlink_incidents",
        "link_change",
        "mark_known_error",
        "set_state",
        "add_task",
    ] = Field(..., description="Operation to perform")

    problem_id: Optional[str] = Field(
        default=None, description="PRB number or sys_id (all actions but create)"
    )
    full: bool = Field(default=False, description="get: include workaround/cause/fix bodies")

    short_description: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    subcategory: Optional[str] = Field(default=None)
    impact: Optional[str] = Field(default=None)
    urgency: Optional[str] = Field(default=None)
    assignment_group: Optional[str] = Field(default=None)
    assigned_to: Optional[str] = Field(default=None)
    cmdb_ci: Optional[str] = Field(default=None)
    first_reported_by_task: Optional[str] = Field(
        default=None, description="Task sys_id or number (INC/CHG/PRB)"
    )
    workaround: Optional[str] = Field(default=None)
    cause_notes: Optional[str] = Field(default=None)
    fix_notes: Optional[str] = Field(default=None)
    resolution_code: Optional[str] = Field(default=None)
    close_notes: Optional[str] = Field(default=None)
    duplicate_of: Optional[str] = Field(default=None, description="PRB number or sys_id")

    incidents: Optional[List[str]] = Field(
        default=None, description="INC numbers (link_incidents/unlink_incidents)"
    )
    force_relink: bool = Field(
        default=False, description="link_incidents: take incidents linked to another problem"
    )
    change: Optional[str] = Field(default=None, description="CHG number or sys_id (link_change)")
    state: Optional[str] = Field(default=None, description="set_state: value or label")
    problem_task_type: Optional[str] = Field(
        default=None, description="add_task: type value or label (General, Root Cause Analysis)"
    )

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset({"problem_id", "full"}),
        "create": frozenset({"dry_run", *_PROBLEM_COMMON_FIELDS}),
        "update": frozenset({"problem_id", "dry_run", *_PROBLEM_UPDATE_FIELDS}),
        "link_incidents": frozenset({"problem_id", "dry_run", "incidents", "force_relink"}),
        "unlink_incidents": frozenset({"problem_id", "dry_run", "incidents"}),
        "link_change": frozenset({"problem_id", "dry_run", "change"}),
        "mark_known_error": frozenset({"problem_id", "dry_run", "workaround"}),
        "set_state": frozenset({"problem_id", "dry_run", "state"}),
        "add_task": frozenset(
            {
                "problem_id",
                "dry_run",
                "short_description",
                "description",
                "assignment_group",
                "assigned_to",
                "problem_task_type",
            }
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageProblemParams":
        a = self.action
        if a == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
            return self
        if not self.problem_id:
            raise ValueError(f"problem_id is required for action='{a}'")
        if a == "add_task" and not self.short_description:
            raise ValueError("short_description is required for action='add_task'")
        if a == "update" and not any(getattr(self, f) is not None for f in _PROBLEM_UPDATE_FIELDS):
            raise ValueError("at least one field must be provided for action='update'")
        if a in ("link_incidents", "unlink_incidents") and not self.incidents:
            raise ValueError(f"incidents (INC numbers) is required for action='{a}'")
        if a == "link_change" and not self.change:
            raise ValueError("change is required for action='link_change'")
        if a == "set_state" and not self.state:
            raise ValueError("state is required for action='set_state'")
        return self


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _raw(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def _disp(value: Any) -> Any:
    return value.get("display_value") if isinstance(value, dict) else value


def _read(
    config: ServerConfig, auth_manager: AuthManager, table: str, query: str, fields: str, limit: int
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        display_value="all",
        fail_silently=False,
    )
    return rows


def _resolve_record(
    config: ServerConfig,
    auth_manager: AuthManager,
    ident: str,
    table: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (sys_id, table, None) or (None, table, reason).

    A sys_id is taken as given (it is checked when the record is read). A number
    is looked up; 0 rows means unreadable-or-absent, never "does not exist".
    """
    ident = ident.strip()
    if _SYS_ID.match(ident):
        return ident, table, None
    m = _NUMBER.match(ident)
    if not m:
        return None, table, f"{ident!r} is neither a sys_id nor a record number"
    tbl = table or _NUMBER_TABLES.get(m.group(1).upper(), "task")
    rows = _read(config, auth_manager, tbl, f"number={safe_value(ident).value}", "sys_id", 1)
    if not rows:
        return (
            None,
            tbl,
            f"{ident} was not returned by {tbl}: it is absent or not readable by this "
            "user (the two look the same). Nothing was written.",
        )
    return _raw(rows[0].get("sys_id")), tbl, None


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _patch(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str, data: Dict[str, Any]
) -> None:
    resp = auth_manager.make_request(
        "PATCH",
        f"{config.api_url}/table/{table}/{sys_id}",
        json=data,
        headers=auth_manager.get_headers(),
        timeout=config.timeout,
    )
    resp.raise_for_status()
    invalidate_query_cache(table=table)


def _write_verified(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """PATCH the problem, re-read it, and report which fields actually hold."""
    try:
        _patch(config, auth_manager, "problem", sys_id, data)
    except Exception as e:
        logger.error(f"Failed to update problem: {e}")
        return _fail(f"Failed to update problem: {e}", sys_id=sys_id)
    try:
        rows = _read(
            config, auth_manager, "problem", f"sys_id={sys_id}", "number," + ",".join(data), 1
        )
    except Exception as e:
        return {
            "success": True,
            "sys_id": sys_id,
            "verified": False,
            "message": f"Write sent but the re-read failed ({e}); the result is UNVERIFIED.",
        }
    if not rows:
        return {
            "success": True,
            "sys_id": sys_id,
            "verified": False,
            "message": "Write sent but the record was not returned on re-read; UNVERIFIED.",
        }
    row = rows[0]
    not_applied = {}
    for field, wanted in data.items():
        got = row.get(field)
        if str(wanted) not in (str(_raw(got)), str(_disp(got))):
            not_applied[field] = {"requested": wanted, "actual": _raw(got), "label": _disp(got)}
    out: Dict[str, Any] = {
        "success": not not_applied,
        "sys_id": sys_id,
        "number": _raw(row.get("number")),
        "verified": True,
        "applied": not not_applied,
    }
    if not_applied:
        out["not_applied"] = not_applied
        out["message"] = "The write was accepted but these fields do not hold the requested value."
    else:
        out["message"] = "Problem updated and confirmed by re-read."
    return out


def _preview(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    return build_update_preview(
        config,
        auth_manager,
        table="problem",
        sys_id=sys_id,
        proposed=data,
        identifier_fields=["number", "short_description", "state"],
    )


def _payload(
    config: ServerConfig, auth_manager: AuthManager, params: ManageProblemParams, fields: tuple
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    data = {f: getattr(params, f) for f in fields if getattr(params, f) is not None}
    for field, table in (("first_reported_by_task", None), ("duplicate_of", "problem")):
        if field in data:
            sys_id, _, reason = _resolve_record(config, auth_manager, data[field], table)
            if reason:
                return data, _fail(reason, field=field)
            data[field] = sys_id
    refusal = resolve_payload_choices(
        config, auth_manager, table="problem", data=data, elements=_PROBLEM_CHOICE_FIELDS
    )
    return data, refusal


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _get(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    assert params.problem_id
    ident = params.problem_id.strip()
    query = f"sys_id={ident}" if _SYS_ID.match(ident) else f"number={safe_value(ident).value}"
    try:
        rows = _read(config, auth_manager, "problem", query, _GET_FIELDS, 1)
    except Exception as e:
        return _fail(f"Failed to read problem: {e}")
    if not rows:
        return _fail(
            f"Problem {ident} was not returned: absent or not readable by this user.",
            determined=False,
        )
    r = rows[0]
    out: Dict[str, Any] = {
        "success": True,
        "sys_id": _raw(r.get("sys_id")),
        "number": _raw(r.get("number")),
        "state": _disp(r.get("state")),
        "state_value": _raw(r.get("state")),
        "short_description": _raw(r.get("short_description")),
        "assignment_group": _disp(r.get("assignment_group")),
        "assigned_to": _disp(r.get("assigned_to")),
        "known_error": str(_raw(r.get("known_error"))).lower() == "true",
        "major_problem": str(_raw(r.get("major_problem"))).lower() == "true",
        "rfc": _disp(r.get("rfc")),
        "first_reported_by_task": _disp(r.get("first_reported_by_task")),
        "duplicate_of": _disp(r.get("duplicate_of")),
        "resolution_code": _disp(r.get("resolution_code")),
        "related_incidents": _raw(r.get("related_incidents")),
    }
    for f in _NOTE_FIELDS:
        body = _raw(r.get(f)) or ""
        if params.full:
            out[f] = body
        else:
            out[f"{f}_length"] = len(body)
    if not params.full and any(out[f"{f}_length"] for f in _NOTE_FIELDS):
        out["note"] = "Bodies withheld; call get with full=true for workaround/cause/fix text."
    return out


def _create(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    try:
        data, refusal = _payload(config, auth_manager, params, _PROBLEM_COMMON_FIELDS)
    except Exception as e:
        return _fail(f"Could not resolve create fields: {e}. Nothing was written.")
    if refusal is not None:
        return refusal
    if params.dry_run:
        return {"success": True, "dry_run": True, "operation": "create", "would_write": data}
    try:
        resp = auth_manager.make_request(
            "POST",
            f"{config.api_url}/table/problem",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        invalidate_query_cache(table="problem")
    except Exception as e:
        logger.error(f"Failed to create problem: {e}")
        return _fail(f"Failed to create problem: {e}")
    return {
        "success": True,
        "message": "Problem created",
        "sys_id": _raw(result.get("sys_id")),
        "number": _raw(result.get("number")),
    }


def _problem_sys_id(config, auth_manager, params) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    try:
        sys_id, _, reason = _resolve_record(config, auth_manager, params.problem_id, "problem")
    except Exception as e:
        return None, _fail(f"Could not resolve {params.problem_id}: {e}. Nothing was written.")
    if reason:
        return None, _fail(reason, determined=False)
    return sys_id, None


def _apply(config, auth_manager, params, sys_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if params.dry_run:
        return _preview(config, auth_manager, sys_id, data)
    return _write_verified(config, auth_manager, sys_id, data)


def _update(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    sys_id, err = _problem_sys_id(config, auth_manager, params)
    if err:
        return err
    assert sys_id
    try:
        data, refusal = _payload(config, auth_manager, params, _PROBLEM_UPDATE_FIELDS)
    except Exception as e:
        return _fail(f"Could not resolve update fields: {e}. Nothing was written.")
    if refusal is not None:
        return refusal
    return _apply(config, auth_manager, params, sys_id, data)


def _incident_rows(config, auth_manager, numbers: List[str]) -> Dict[str, Dict[str, Any]]:
    clean = [safe_value(n).value.strip() for n in numbers]
    rows = _read(
        config,
        auth_manager,
        "incident",
        "numberIN" + ",".join(clean),
        "sys_id,number,problem_id",
        200,
    )
    return {str(_raw(r.get("number"))): r for r in rows}


def _link_incidents(
    config, auth_manager, params: ManageProblemParams, link: bool
) -> Dict[str, Any]:
    sys_id, err = _problem_sys_id(config, auth_manager, params)
    if err:
        return err
    assert sys_id and params.incidents
    try:
        found = _incident_rows(config, auth_manager, params.incidents)
    except Exception as e:
        return _fail(f"Could not read incidents: {e}. Nothing was written.", determined=False)

    results: List[Dict[str, Any]] = []
    todo: List[Tuple[str, str]] = []  # (number, incident sys_id)
    for num in params.incidents:
        row = found.get(num)
        if row is None:
            results.append(
                {
                    "number": num,
                    "status": "not_readable",
                    "note": "absent or not readable by this user",
                }
            )
            continue
        current = _raw(row.get("problem_id")) or ""
        inc_id = _raw(row.get("sys_id"))
        if link:
            if current == sys_id:
                results.append({"number": num, "status": "already_linked_here"})
            elif current and not params.force_relink:
                results.append(
                    {
                        "number": num,
                        "status": "linked_elsewhere",
                        "problem": _disp(row.get("problem_id")),
                        "note": "refused; pass force_relink=true to move it",
                    }
                )
            else:
                todo.append((num, inc_id))
                results.append(
                    {
                        "number": num,
                        "status": "linked",
                        "relinked_from": _disp(row.get("problem_id")),
                    }
                    if current
                    else {"number": num, "status": "linked"}
                )
        else:
            if current == sys_id:
                todo.append((num, inc_id))
                results.append({"number": num, "status": "unlinked"})
            else:
                results.append(
                    {
                        "number": num,
                        "status": "not_linked_here",
                        "problem": _disp(row.get("problem_id")) or None,
                    }
                )

    by_num = {r["number"]: r for r in results}
    if params.dry_run:
        for r in results:
            if r["number"] in {n for n, _ in todo}:
                r["status"] = "would_" + r["status"]
        return {"success": True, "dry_run": True, "problem": sys_id, "incidents": results}

    target = sys_id if link else ""
    for num, inc_id in todo:
        try:
            _patch(config, auth_manager, "incident", inc_id, {"problem_id": target})
        except Exception as e:
            by_num[num].update(status="failed", note=str(e))
    # Re-read: only report a link that the incident really holds.
    if todo:
        try:
            after = _incident_rows(config, auth_manager, [n for n, _ in todo])
        except Exception:
            after = {}
        for num, _ in todo:
            r = by_num[num]
            if r["status"] == "failed":
                continue
            row = after.get(num)
            if row is None:
                r.update(status="unverified", note="re-read did not return the incident")
            elif (_raw(row.get("problem_id")) or "") != target:
                r.update(status="not_applied", note="write accepted but problem_id did not change")
    ok = all(
        r["status"] in ("linked", "unlinked", "already_linked_here", "not_linked_here")
        for r in results
    )
    return {"success": ok, "problem": sys_id, "incidents": results}


def _link_change(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    sys_id, err = _problem_sys_id(config, auth_manager, params)
    if err:
        return err
    assert sys_id and params.change
    try:
        chg, _, reason = _resolve_record(config, auth_manager, params.change, "change_request")
    except Exception as e:
        return _fail(f"Could not resolve {params.change}: {e}. Nothing was written.")
    if reason:
        return _fail(reason, determined=False)
    return _apply(config, auth_manager, params, sys_id, {"rfc": chg})


def _mark_known_error(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    sys_id, err = _problem_sys_id(config, auth_manager, params)
    if err:
        return err
    assert sys_id
    data: Dict[str, Any] = {"known_error": "true"}
    if params.workaround is not None:
        data["workaround"] = params.workaround
    return _apply(config, auth_manager, params, sys_id, data)


def _set_state(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    sys_id, err = _problem_sys_id(config, auth_manager, params)
    if err:
        return err
    assert sys_id and params.state
    value, refusal = resolve_choice(
        config, auth_manager, table="problem", element="state", requested=params.state
    )
    if refusal is not None:
        return refusal
    if params.dry_run:
        return _preview(config, auth_manager, sys_id, {"state": value})
    out = _write_verified(config, auth_manager, sys_id, {"state": value})
    if out.get("verified") is False:
        out.update(applied=None, requested_state=value)
    elif out.get("not_applied"):
        miss = out["not_applied"]["state"]
        out.update(
            applied=False,
            requested_state=value,
            actual_state=miss["actual"],
            actual_state_label=miss["label"],
            message=(
                f"State was NOT changed to {value}; the record is in state "
                f"{miss['actual']} ({miss['label']}). " + _STATE_HINT
            ),
        )
        out.pop("not_applied", None)
    elif out.get("success"):
        out.update(applied=True, requested_state=value, message=f"State is now {value}.")
    return out


_TASK_FIELDS = ("short_description", "description", "assignment_group", "assigned_to")


def _add_task(config, auth_manager, params: ManageProblemParams) -> Dict[str, Any]:
    """Create a problem_task (PTASK) under the problem and prove it by re-read."""
    sys_id, err = _problem_sys_id(config, auth_manager, params)
    if err:
        return err
    assert sys_id
    data: Dict[str, Any] = {"problem": sys_id}
    data.update({f: getattr(params, f) for f in _TASK_FIELDS if getattr(params, f) is not None})
    if params.problem_task_type:
        value, refusal = resolve_choice(
            config,
            auth_manager,
            table="problem_task",
            element="problem_task_type",
            requested=params.problem_task_type,
        )
        if refusal is not None:
            return refusal
        data["problem_task_type"] = value
    if params.dry_run:
        return {"success": True, "dry_run": True, "operation": "add_task", "would_write": data}
    try:
        resp = auth_manager.make_request(
            "POST",
            f"{config.api_url}/table/problem_task",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        invalidate_query_cache(table="problem_task")
    except Exception as e:
        logger.error(f"Failed to create problem task: {e}")
        return _fail(f"Failed to create problem task: {e}", problem=sys_id)
    task_id = _raw(result.get("sys_id"))
    out: Dict[str, Any] = {
        "success": True,
        "problem": sys_id,
        "sys_id": task_id,
        "number": _raw(result.get("number")),
    }
    try:
        rows = (
            _read(
                config,
                auth_manager,
                "problem_task",
                f"sys_id={task_id}",
                "number," + ",".join(data),
                1,
            )
            if task_id
            else []
        )
    except Exception as e:
        rows = []
        out["message"] = f"Task created but the re-read failed ({e}); UNVERIFIED."
    if not rows:
        out.update(verified=False, applied=None)
        out.setdefault("message", "Task created but not returned on re-read; UNVERIFIED.")
        return out
    row = rows[0]
    out["number"] = _raw(row.get("number")) or out["number"]
    not_applied = {}
    for field, wanted in data.items():
        got = row.get(field)
        if str(wanted) not in (str(_raw(got)), str(_disp(got))):
            not_applied[field] = {"requested": wanted, "actual": _raw(got), "label": _disp(got)}
    out.update(verified=True, applied=not not_applied)
    if not_applied:
        out["success"] = False
        out["not_applied"] = not_applied
        out["message"] = "Task created but these fields do not hold the requested value."
    else:
        out["message"] = "Problem task created and confirmed by re-read."
    return out


@register_tool(
    "manage_problem",
    params=ManageProblemParams,
    description="Problems: get/create/update, link incidents or a change, mark known error, set state, add task (re-read verified).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_problem(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageProblemParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "get":
        return _get(config, auth_manager, params)
    if a == "create":
        return _create(config, auth_manager, params)
    if a == "update":
        return _update(config, auth_manager, params)
    if a == "link_incidents":
        return _link_incidents(config, auth_manager, params, True)
    if a == "unlink_incidents":
        return _link_incidents(config, auth_manager, params, False)
    if a == "link_change":
        return _link_change(config, auth_manager, params)
    if a == "mark_known_error":
        return _mark_known_error(config, auth_manager, params)
    if a == "add_task":
        return _add_task(config, auth_manager, params)
    return _set_state(config, auth_manager, params)
