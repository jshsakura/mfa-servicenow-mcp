"""get_record_context: one read-only call for "what is going on with INC0012345".

Replaces a chain of sn_query calls (record, links, approvals, variables, child
tasks, SLAs, flow contexts, journal counts) with one bounded answer.

Every section states what it PROVED. A section that could not be read comes back
as ``{checked: false, because}`` -- never an empty list -- and a section that was
read and is genuinely empty is named in ``empty_sections`` instead of silently
dropped. A record that did not come back is ``undetermined``, not "not found":
an ACL-denied read answers exactly like a missing one.
"""

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import (
    _read_failure_verdict,
    sn_count_by_group,
    sn_query_page,
)
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

SECTION_NAMES = ("links", "approvals", "variables", "tasks", "sla", "flows", "journal")
INCOMING_CAP = 20
_ROW_CAP = 50
_SECTION_WORKERS = 4
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_NUMBER = re.compile(r"^([A-Za-z]+)\d+$")

# Outgoing reference fields -> (target table, or None when only the label is kept).
_OUTGOING_TARGETS: Dict[str, Optional[str]] = {
    "parent": "task",
    "universal_request": "task",
    "rfc": "change_request",
    "caused_by": "change_request",
    "problem_id": "problem",
    "parent_incident": "incident",
    "request": "sc_request",
    "request_item": "sc_req_item",
    "cat_item": None,
}

# Link fields per table, beyond the task base ones.
_LINK_FIELDS: Dict[str, Tuple[str, ...]] = {
    "incident": ("rfc", "caused_by", "problem_id", "parent_incident"),
    "problem": ("rfc",),
    "sc_req_item": ("request", "cat_item"),
    "sc_task": ("request_item", "request"),
}
_BASE_LINK_FIELDS = ("parent", "universal_request")
# Read with the record but not links: who requested a change (self-approval check).
_EXTRA_FIELDS: Dict[str, Tuple[str, ...]] = {"change_request": ("requested_by",)}
_CORE_FIELDS = (
    "sys_class_name",
    "number",
    "short_description",
    "state",
    "priority",
    "assignment_group",
    "assigned_to",
    "opened_at",
    "active",
)

# (list name, table, field, applies to tables or None for every table).
_INCOMING: Tuple[Tuple[str, str, str, Optional[Tuple[str, ...]]], ...] = (
    ("incident_parent_incident", "incident", "parent_incident", ("incident",)),
    ("incident_problem_id", "incident", "problem_id", ("problem",)),
    ("incident_rfc", "incident", "rfc", ("change_request",)),
    ("incident_caused_by", "incident", "caused_by", ("change_request",)),
    ("problem_rfc", "problem", "rfc", ("change_request",)),
    ("change_parent", "change_request", "parent", None),
    ("req_item_request", "sc_req_item", "request", ("sc_request",)),
    ("task_universal_request", "task", "universal_request", None),
)

# Child task table and the field that points back at the parent.
_CHILD_TASKS: Dict[str, Tuple[str, str]] = {
    "sc_req_item": ("sc_task", "request_item"),
    "change_request": ("change_task", "change_request"),
    "problem": ("problem_task", "problem"),
}

# Variable types (item_option_new.type values).
# question.type values measured on a live sys_choice: 8 Reference, 18 Lookup Select
# Box, 21 List Collector, 22 Lookup Multiple Choice, 31 Requested For.
_REFERENCE_TYPES = {"8", "18", "21", "22", "31"}
_REF_LABEL_COLUMNS = ("name", "number", "user_name", "title", "short_description", "label")

_sys_number_cache: Dict[str, Dict[str, str]] = {}
_sys_number_lock = threading.Lock()


class RecordContextParams(BaseModel):
    number: str = Field(description="Record number, e.g. INC0012345 or RITM0010002 (REQUIRED).")
    sections: Optional[List[str]] = Field(
        default=None,
        description="Subset of links,approvals,variables,tasks,sla,flows,journal. Default all.",
    )


# ---------------------------------------------------------------------------
# Row helpers (sysparm_display_value=all gives {value, display_value} dicts)
# ---------------------------------------------------------------------------


def _val(row: Dict[str, Any], field: str) -> str:
    cell = row.get(field)
    if isinstance(cell, dict):
        cell = cell.get("value")
    return "" if cell is None else str(cell)


def _lab(row: Dict[str, Any], field: str) -> str:
    cell = row.get(field)
    if isinstance(cell, dict):
        shown = cell.get("display_value")
        return str(shown) if shown not in (None, "") else _val(row, field)
    return "" if cell is None else str(cell)


def _short(row: Dict[str, Any], table: str = "") -> Dict[str, Any]:
    return {
        "table": _val(row, "sys_class_name") or table,
        "number": _val(row, "number"),
        "state": _lab(row, "state"),
        "short_description": _val(row, "short_description"),
    }


def _unread(err: Dict[str, Any]) -> Dict[str, Any]:
    return {"checked": False, **err}


def _page(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = _ROW_CAP,
    *,
    display: "bool | str" = "all",
    orderby: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[Dict[str, Any]]]:
    """``(rows, total, error)``. ``error`` is ``{because, availability?}`` -- never an empty page."""
    try:
        rows, total = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=fields,
            limit=limit,
            offset=0,
            display_value=display,
            orderby=orderby,
            fail_silently=False,
        )
        return rows, total, None
    except Exception as exc:  # noqa: BLE001 - reported, never rendered as empty
        status = getattr(getattr(exc, "response", None), "status_code", None)
        verdict = None
        try:
            # fields_clean=False: the sysparm_fields list was not dictionary-checked,
            # so a 403 is not proven to be an ACL answer.
            verdict = _read_failure_verdict(config, auth_manager, table, exc, fields_clean=False)
        except Exception:  # noqa: BLE001 - the verdict read is itself best effort
            verdict = None
        if verdict:
            return (
                [],
                None,
                {
                    "table": table,
                    "availability": verdict.get("availability", "undetermined"),
                    "because": verdict.get("because") or verdict.get("message") or "read rejected",
                },
            )
        why = f"HTTP {status}" if status else f"{type(exc).__name__}: {str(exc)[:120]}"
        return (
            [],
            None,
            {"table": table, "availability": "undetermined", "because": f"read failed ({why})"},
        )


def _provably_empty(rows: List[Dict[str, Any]], total: Optional[int]) -> bool:
    """Empty is a claim: only a server count of 0 backs it."""
    return not rows and total == 0


def _complete(rows: List[Dict[str, Any]], total: Optional[int], limit: int) -> bool:
    if total is None:
        return len(rows) < limit
    return len(rows) >= total


def _in(ids: List[str]) -> str:
    return "sys_idIN" + ",".join(ids)


# ---------------------------------------------------------------------------
# Number -> table
# ---------------------------------------------------------------------------


def _prefix_map(
    config: ServerConfig, auth_manager: AuthManager
) -> Tuple[Dict[str, str], bool, Optional[Dict[str, Any]]]:
    """``(prefix -> table, complete, error)``. Only a successful, complete read is memoised."""
    key = config.instance_url
    with _sys_number_lock:
        cached = _sys_number_cache.get(key)
    if cached is not None:
        return cached, True, None
    limit = 1000
    rows, total, err = _page(
        config, auth_manager, "sys_number", "", "prefix,category", limit, display=False
    )
    if err:
        return {}, False, err
    mapping: Dict[str, str] = {}
    for row in rows:
        prefix, table = _val(row, "prefix").upper(), _val(row, "category")
        if prefix and table and prefix not in mapping:
            mapping[prefix] = table
    complete = _complete(rows, total, limit)
    if complete:
        with _sys_number_lock:
            _sys_number_cache[key] = mapping
    return mapping, complete, None


def resolve_table(
    config: ServerConfig, auth_manager: AuthManager, number: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """``(table, None)`` or ``(None, refusal)``."""
    match = _NUMBER.match(number)
    if not match:
        return None, {
            "success": False,
            "error": "bad_number",
            "message": f"'{number}' is not <PREFIX><digits> (e.g. INC0012345).",
        }
    prefix = match.group(1).upper()
    mapping, complete, err = _prefix_map(config, auth_manager)
    if err:
        return None, {
            "success": False,
            "error": "prefix_map_unreadable",
            "availability": err["availability"],
            "because": f"sys_number could not be read: {err['because']}",
        }
    if prefix in mapping:
        return mapping[prefix], None
    if not complete:
        rows, _total, err = _page(
            config,
            auth_manager,
            "sys_number",
            f"prefix={prefix}",
            "prefix,category",
            5,
            display=False,
        )
        if err is None:
            for row in rows:
                if _val(row, "category"):
                    return _val(row, "category"), None
        return None, {
            "success": False,
            "error": "prefix_undetermined",
            "availability": "undetermined",
            "because": "sys_number has more rows than one page and this prefix was not found in it",
        }
    return None, {
        "success": False,
        "error": "unknown_number_prefix",
        "message": f"No number prefix '{prefix}' in sys_number.",
        "known_prefixes": sorted(mapping),
    }


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

Section = Callable[[ServerConfig, AuthManager, Dict[str, Any]], Tuple[Dict[str, Any], bool]]


def _outgoing_links(config, auth_manager, ctx) -> Tuple[List[Dict[str, Any]], bool]:
    """``(entries, all_read)`` for the reference fields this record holds."""
    row, table = ctx["row"], ctx["table"]
    fields = _BASE_LINK_FIELDS + _LINK_FIELDS.get(table, ())
    by_target: Dict[str, List[Tuple[str, str]]] = {}
    out: List[Dict[str, Any]] = []
    for field in fields:
        value = _val(row, field)
        if not value:
            continue
        target = _OUTGOING_TARGETS.get(field)
        if target is None:
            out.append({"field": field, "label": _lab(row, field)})
        else:
            by_target.setdefault(target, []).append((field, value))
    all_read = True
    for target, pairs in by_target.items():
        ids = sorted({v for _f, v in pairs})
        rows, _total, err = _page(
            config,
            auth_manager,
            target,
            _in(ids),
            "sys_id,sys_class_name,number,state,short_description",
        )
        found = {_val(r, "sys_id"): r for r in rows}
        for field, value in pairs:
            if err:
                all_read = False
                out.append({"field": field, "label": _lab(row, field), **_unread(err)})
            elif value in found:
                out.append({"field": field, **_short(found[value], target)})
            else:
                out.append(
                    {
                        "field": field,
                        "label": _lab(row, field),
                        "unread": "not returned (gone or ACL)",
                    }
                )
    return out, all_read and all("unread" not in e for e in out)


def _rel_links(config, auth_manager, ctx) -> Dict[str, Any]:
    sid = ctx["sys_id"]
    rows, total, err = _page(
        config,
        auth_manager,
        "task_rel_task",
        f"parent={sid}^ORchild={sid}",
        "parent,child,type",
        INCOMING_CAP,
    )
    if err:
        return _unread(err)
    others: List[Tuple[str, str]] = []
    for r in rows:
        side = "child" if _val(r, "parent") == sid else "parent"
        others.append((_val(r, side), _lab(r, "type")))
    ids = sorted({o for o, _t in others if o})
    detail: Dict[str, Dict[str, Any]] = {}
    detail_err = None
    if ids:
        drows, _t, detail_err = _page(
            config,
            auth_manager,
            "task",
            _in(ids),
            "sys_id,sys_class_name,number,state,short_description",
        )
        detail = {_val(r, "sys_id"): r for r in drows}
    items = []
    for other, rel_type in others:
        entry = {"relation": rel_type}
        entry.update(_short(detail[other]) if other in detail else {"unread": "task not returned"})
        items.append(entry)
    out: Dict[str, Any] = {
        "rows": items,
        "total": total,
        "complete": _complete(rows, total, INCOMING_CAP),
    }
    if detail_err:
        out["detail_unread"] = detail_err["because"]
    return out


def _section_links(config, auth_manager, ctx):
    table, sid = ctx["table"], ctx["sys_id"]
    outgoing, outgoing_ok = _outgoing_links(config, auth_manager, ctx)
    incoming: Dict[str, Any] = {}
    all_empty = outgoing_ok
    for name, in_table, field, applies in _INCOMING:
        if applies is not None and table not in applies:
            continue
        rows, total, err = _page(
            config,
            auth_manager,
            in_table,
            f"{field}={sid}",
            "sys_id,sys_class_name,number,state,short_description",
            INCOMING_CAP,
        )
        if err:
            incoming[name] = _unread(err)
            all_empty = False
            continue
        incoming[name] = {
            "rows": [_short(r, in_table) for r in rows],
            "total": total,
            "complete": _complete(rows, total, INCOMING_CAP),
        }
        all_empty = all_empty and _provably_empty(rows, total)
    incoming["task_rel_task"] = _rel_links(config, auth_manager, ctx)
    rel = incoming["task_rel_task"]
    all_empty = all_empty and rel.get("total") == 0 and not rel.get("rows")
    payload = {"outgoing": outgoing, "incoming": incoming}
    return payload, bool(all_empty and not outgoing)


def _self_approval_check(ctx, rows) -> Dict[str, Any]:
    """Approvers who are also the record's implementer (assigned_to) or requester (change).

    Compared by sys_id, never by display value. A person field that was not read is
    reported as unchecked: its absence is not a clearance.
    """
    row = ctx["row"]
    roles = [("assigned_to", "assigned_to")]
    if ctx["table"] == "change_request":
        roles.append(("requested_by", "requested_by"))
    people: Dict[str, str] = {}
    unchecked: List[str] = []
    for field, role in roles:
        if field not in row:
            unchecked.append(field)
            continue
        value = _val(row, field)
        if value:
            people[role] = value
    warnings: List[Dict[str, Any]] = []
    for r in rows:
        approver = _val(r, "approver")
        if not approver:
            continue
        for role, person in people.items():
            if approver == person:
                warnings.append(
                    {
                        "code": "SELF_APPROVAL",
                        "approver": _lab(r, "approver"),
                        "state": _lab(r, "state"),
                        "is": role,
                        "message": f"The approver is the record's {role}; the implementer "
                        "may not approve their own change.",
                    }
                )
    out: Dict[str, Any] = {"checked": not unchecked, "warnings": warnings}
    if unchecked:
        out["unchecked_fields"] = unchecked
        out["because"] = "not read from the record: " + ", ".join(unchecked)
    return out


def _section_approvals(config, auth_manager, ctx):
    sid = ctx["sys_id"]
    payload: Dict[str, Any] = {}
    rows, total, err = _page(
        config,
        auth_manager,
        "sysapproval_approver",
        f"document_id={sid}^ORsysapproval={sid}",
        "approver,state,group,order,source_table",
        _ROW_CAP,
        orderby="order",
    )
    approvers_empty = False
    pending: List[Tuple[str, str]] = []
    if err:
        payload["approvers"] = _unread(err)
    else:
        payload["approvers"] = {
            "rows": [
                {
                    "approver": _lab(r, "approver"),
                    "state": _lab(r, "state"),
                    "group": _lab(r, "group"),
                    "order": _val(r, "order"),
                }
                for r in rows
            ],
            "total": total,
            "complete": _complete(rows, total, _ROW_CAP),
        }
        approvers_empty = _provably_empty(rows, total)
        pending = [
            (_val(r, "approver"), _lab(r, "approver"))
            for r in rows
            if _val(r, "state") == "requested"
        ]
        check = _self_approval_check(ctx, rows)
        payload["self_approval_check"] = check
        if check["warnings"]:
            payload["warnings"] = check["warnings"]
    grows, gtotal, gerr = _page(
        config,
        auth_manager,
        "sysapproval_group",
        f"parent={sid}",
        "assignment_group,approval,approval_user,wait_for",
        _ROW_CAP,
    )
    groups_empty = False
    if gerr:
        payload["group_approvals"] = _unread(gerr)
    else:
        payload["group_approvals"] = {
            "rows": [
                {
                    "group": _lab(r, "assignment_group"),
                    "approval": _lab(r, "approval"),
                    "approval_user": _lab(r, "approval_user"),
                    "wait_for": _lab(r, "wait_for"),
                }
                for r in grows
            ],
            "total": gtotal,
            "complete": _complete(grows, gtotal, _ROW_CAP),
        }
        groups_empty = _provably_empty(grows, gtotal)
    delegates_ok = True
    if pending:
        ids = sorted({p for p, _l in pending if p})
        now = "javascript:gs.nowDateTime()"
        drows, _dt, derr = _page(
            config,
            auth_manager,
            "sys_user_delegate",
            f"userIN{','.join(ids)}^approvals=true^startsISEMPTY^ORstarts<={now}"
            f"^endsISEMPTY^ORends>={now}",
            "user,delegate,starts,ends",
            _ROW_CAP,
        )
        if derr:
            payload["valid_delegates"] = _unread(derr)
            delegates_ok = False
        else:
            payload["valid_delegates"] = {
                "rows": [
                    {
                        "approver": _lab(r, "user"),
                        "delegate": _lab(r, "delegate"),
                        "ends": _val(r, "ends"),
                    }
                    for r in drows
                ],
                "checked_for": [label for _p, label in pending],
            }
    return payload, bool(approvers_empty and groups_empty and delegates_ok and not pending)


def _section_variables(config, auth_manager, ctx):
    table = ctx["table"]
    if table == "sc_req_item":
        item = ctx["sys_id"]
    elif table == "sc_task":
        item = _val(ctx["row"], "request_item")
        if not item:
            return {"checked": False, "because": "sc_task row carries no request_item"}, False
    else:
        return {"not_applicable": f"variables exist on sc_req_item / sc_task, not {table}"}, False
    mrows, mtotal, err = _page(
        config,
        auth_manager,
        "sc_item_option_mtom",
        f"request_item={item}",
        "sc_item_option",
        200,
        display=False,
    )
    if err:
        return _unread(err), False
    if _provably_empty(mrows, mtotal):
        return {}, True
    option_ids = sorted({_val(r, "sc_item_option") for r in mrows if _val(r, "sc_item_option")})
    orows, _ot, err = _page(
        config,
        auth_manager,
        "sc_item_option",
        _in(option_ids),
        "sys_id,item_option_new,value,order",
        200,
        display=False,
    )
    if err:
        return _unread(err), False
    qids = sorted({_val(r, "item_option_new") for r in orows if _val(r, "item_option_new")})
    qrows, _qt, err = _page(
        config,
        auth_manager,
        "item_option_new",
        _in(qids),
        "sys_id,name,question_text,type,reference,list_table,lookup_table,lookup_value",
        200,
    )
    if err:
        return _unread(err), False
    questions = {_val(r, "sys_id"): r for r in qrows}

    # Every non-reference question is asked: guessing choice types by number would
    # silently skip one that carries question_choice rows.
    choice_qids = sorted(q for q, r in questions.items() if _val(r, "type") not in _REFERENCE_TYPES)
    choices: Dict[Tuple[str, str], str] = {}
    choice_err = None
    if choice_qids:
        crows, _ct, choice_err = _page(
            config,
            auth_manager,
            "question_choice",
            f"questionIN{','.join(choice_qids)}",
            "question,value,text",
            500,
            display=False,
        )
        choices = {(_val(r, "question"), _val(r, "value")): _val(r, "text") for r in crows}

    # One batched read per referenced table.
    wanted: Dict[str, set] = {}
    for orow in orows:
        q = questions.get(_val(orow, "item_option_new"))
        ref_table = _ref_target(q)[0] if q and _val(q, "type") in _REFERENCE_TYPES else ""
        if ref_table:
            wanted.setdefault(ref_table, set()).update(
                v for v in _val(orow, "value").split(",") if v
            )
    labels: Dict[Tuple[str, str], str] = {}
    ref_err: Dict[str, str] = {}
    for ref_table, ids in wanted.items():
        rrows, _rt, rerr = _page(
            config,
            auth_manager,
            ref_table,
            _in(sorted(ids)),
            "sys_id," + ",".join(_REF_LABEL_COLUMNS),
            200,
            display=False,
        )
        if rerr:
            ref_err[ref_table] = rerr["because"]
            continue
        for r in rrows:
            text = next((_val(r, c) for c in _REF_LABEL_COLUMNS if _val(r, c)), "")
            if text:
                labels[(ref_table, _val(r, "sys_id"))] = text

    items = []
    blank = 0
    for orow in sorted(
        orows, key=lambda r: (_val(r, "order").zfill(8), _val(r, "item_option_new"))
    ):
        raw = _val(orow, "value")
        qid = _val(orow, "item_option_new")
        q = questions.get(qid)
        if not raw:
            blank += 1
            continue
        if q is None:
            items.append(
                {
                    "name": "",
                    "label": "",
                    "type": "",
                    "value": raw,
                    "unresolved": "question not returned",
                }
            )
            continue
        qtype = _val(q, "type")
        item_out: Dict[str, Any] = {
            "name": _val(q, "name"),
            "label": _val(q, "question_text"),
            "type": _lab(q, "type"),
            "value": raw,
        }
        if qtype in _REFERENCE_TYPES:
            ref_table, why = _ref_target(q)
            if not ref_table:
                item_out["unresolved"] = why
            elif ref_table in ref_err:
                item_out["unresolved"] = ref_err[ref_table]
            else:
                shown = [labels.get((ref_table, v)) for v in raw.split(",") if v]
                if all(shown):
                    item_out["display"] = ", ".join(shown)  # type: ignore[arg-type]
                else:
                    item_out["unresolved"] = "referenced record not returned (gone or ACL)"
        elif (qid, raw) in choices:
            item_out["display"] = choices[(qid, raw)]
        elif choice_err and qid in choice_qids:
            item_out["unresolved"] = choice_err["because"]
        items.append(item_out)
    payload: Dict[str, Any] = {"variables": items, "blank": blank}
    if mtotal is not None and mtotal > len(mrows):
        payload["complete"] = False
        payload["total"] = mtotal
    return payload, False


def _ref_target(q: Dict[str, Any]) -> Tuple[str, str]:
    """(table whose sys_ids the value holds, reason when there is none)."""
    qtype = _val(q, "type")
    if qtype == "21":
        table = _val(q, "list_table")
    elif qtype in ("18", "22"):
        lookup_value = _val(q, "lookup_value")
        if lookup_value and lookup_value != "sys_id":
            return "", f"lookup stores column '{lookup_value}', not a sys_id; raw value shown"
        table = _val(q, "lookup_table") or _val(q, "reference")
    else:
        table = _val(q, "reference") or ("sys_user" if qtype == "31" else "")
    return table, "" if table else "question names no reference table"


def _section_tasks(config, auth_manager, ctx):
    spec = _CHILD_TASKS.get(ctx["table"])
    if spec is None:
        return {"not_applicable": f"no child-task table for {ctx['table']}"}, False
    child, field = spec
    rows, total, err = _page(
        config,
        auth_manager,
        child,
        f"{field}={ctx['sys_id']}",
        "number,state,assignment_group,assigned_to",
        _ROW_CAP,
    )
    if err:
        return _unread(err), False
    if _provably_empty(rows, total):
        return {}, True
    return {
        "table": child,
        "rows": [
            {
                "number": _val(r, "number"),
                "state": _lab(r, "state"),
                "assignment_group": _lab(r, "assignment_group"),
                "assigned_to": _lab(r, "assigned_to"),
            }
            for r in rows
        ],
        "total": total,
        "complete": _complete(rows, total, _ROW_CAP),
    }, False


def _section_sla(config, auth_manager, ctx):
    rows, total, err = _page(
        config,
        auth_manager,
        "task_sla",
        f"task={ctx['sys_id']}",
        "sla,stage,has_breached,business_percentage,planned_end_time,active",
        _ROW_CAP,
    )
    if err:
        return _unread(err), False
    if _provably_empty(rows, total):
        return {}, True
    return {
        "rows": [
            {
                "sla": _lab(r, "sla"),
                "stage": _lab(r, "stage"),
                "has_breached": _val(r, "has_breached"),
                "business_percentage": _val(r, "business_percentage"),
                "planned_end_time": _val(r, "planned_end_time"),
                "active": _val(r, "active"),
            }
            for r in rows
        ],
        "total": total,
        "complete": _complete(rows, total, _ROW_CAP),
    }, False


def _section_flows(config, auth_manager, ctx):
    rows, total, err = _page(
        config,
        auth_manager,
        "sys_flow_context",
        f"source_record={ctx['sys_id']}",
        "name,state,flow,snapshot,sys_created_on",
        _ROW_CAP,
        orderby="-sys_created_on",
    )
    if err:
        return _unread(err), False
    if _provably_empty(rows, total):
        return {}, True
    flow_ids = sorted({_val(r, "flow") for r in rows if _val(r, "flow")})
    latest: Dict[str, str] = {}
    latest_err = None
    if flow_ids:
        frows, _ft, latest_err = _page(
            config,
            auth_manager,
            "sys_hub_flow",
            _in(flow_ids),
            "sys_id,latest_snapshot",
            200,
            display=False,
        )
        latest = {_val(r, "sys_id"): _val(r, "latest_snapshot") for r in frows}
    contexts = []
    counts: Dict[str, int] = {}
    for r in rows:
        state = _lab(r, "state")
        counts[state] = counts.get(state, 0) + 1
        flow = _val(r, "flow")
        entry: Dict[str, Any] = {
            "name": _val(r, "name"),
            "state": state,
            "created": _val(r, "sys_created_on"),
        }
        if latest_err:
            entry["on_latest_snapshot"] = None
        elif flow in latest and latest[flow]:
            entry["on_latest_snapshot"] = _val(r, "snapshot") == latest[flow]
        else:
            entry["on_latest_snapshot"] = None  # flow or its latest_snapshot not returned
        contexts.append(entry)
    payload: Dict[str, Any] = {
        "contexts": contexts,
        "by_state": counts,
        "total": total,
        "complete": _complete(rows, total, _ROW_CAP),
    }
    if latest_err:
        payload["snapshot_unread"] = latest_err["because"]
    return payload, False


def _section_journal(config, auth_manager, ctx):
    counts = sn_count_by_group(
        config, auth_manager, "sys_journal_field", f"element_id={ctx['sys_id']}", "element"
    )
    if counts is None:
        return {
            "checked": False,
            "availability": "undetermined",
            "because": "aggregate read on sys_journal_field failed",
        }, False
    if not counts:
        return {}, True
    return {"counts": dict(sorted(counts.items()))}, False


_SECTION_FUNCS: Dict[str, Section] = {
    "links": _section_links,
    "approvals": _section_approvals,
    "variables": _section_variables,
    "tasks": _section_tasks,
    "sla": _section_sla,
    "flows": _section_flows,
    "journal": _section_journal,
}


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


def _record_fields(row: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for field in fields:
        if field not in row:
            continue
        value, label = _val(row, field), _lab(row, field)
        if value == "" and label == "":
            continue
        if _SYS_ID.match(value):
            out[field] = label or value  # reference: the label, not the sys_id
        elif label and label != value:
            out[field] = {"value": value, "label": label}
        else:
            out[field] = value
    return out


@register_tool(
    "get_record_context",
    params=RecordContextParams,
    description="Context for one ITSM record by number: links, approvals, variables, tasks, SLA, flows, journal.",
    serialization="raw_dict",
    return_type=dict,
)
def get_record_context(
    config: ServerConfig, auth_manager: AuthManager, params: RecordContextParams
) -> Dict[str, Any]:
    number = (params.number or "").strip()
    wanted = list(params.sections) if params.sections else list(SECTION_NAMES)
    bad = [s for s in wanted if s not in SECTION_NAMES]
    if bad:
        return {
            "success": False,
            "error": "unknown_section",
            "message": f"Unknown section(s) {bad}.",
            "valid_sections": list(SECTION_NAMES),
        }

    table, refusal = resolve_table(config, auth_manager, number)
    if refusal:
        return refusal
    assert table is not None

    link_fields = list(_BASE_LINK_FIELDS + _LINK_FIELDS.get(table, ()))
    fields = list(_CORE_FIELDS) + link_fields + list(_EXTRA_FIELDS.get(table, ()))
    rows, total, err = _page(
        config, auth_manager, table, f"number={number}", "sys_id," + ",".join(fields), 2
    )
    if err:
        return {
            "success": False,
            "error": "record_not_determined",
            "number": number,
            "table": table,
            **err,
        }
    if not rows:
        return {
            "success": False,
            "error": "record_not_determined",
            "number": number,
            "table": table,
            "availability": "undetermined",
            "because": (
                "the read returned no row: the number may not exist, or this session may "
                "not be allowed to read it (an ACL-denied record answers the same way)"
            ),
        }
    row = rows[0]
    ctx = {"table": table, "sys_id": _val(row, "sys_id"), "row": row}

    results: Dict[str, Tuple[Dict[str, Any], bool]] = {}

    def run(name: str) -> Tuple[str, Tuple[Dict[str, Any], bool]]:
        try:
            return name, _SECTION_FUNCS[name](config, auth_manager, ctx)
        except Exception as exc:  # noqa: BLE001 - a section never takes the call down
            logger.warning("get_record_context section %s failed: %s", name, exc)
            return name, (
                {
                    "checked": False,
                    "availability": "undetermined",
                    "because": f"{type(exc).__name__}: {str(exc)[:120]}",
                },
                False,
            )

    with ThreadPoolExecutor(max_workers=_SECTION_WORKERS) as pool:
        for name, outcome in pool.map(run, wanted):
            results[name] = outcome

    out: Dict[str, Any] = {
        "success": True,
        "number": number,
        "table": table,
        "sys_id": ctx["sys_id"],
        "record": _record_fields(row, [f for f in fields if f != "sys_class_name"]),
    }
    empty: List[str] = []
    not_applicable: Dict[str, str] = {}
    for name in SECTION_NAMES:
        if name not in results:
            continue
        payload, is_empty = results[name]
        if is_empty:
            empty.append(name)
        elif "not_applicable" in payload:
            not_applicable[name] = payload["not_applicable"]
        else:
            out[name] = payload
    if empty:
        out["empty_sections"] = empty
    if not_applicable:
        out["not_applicable"] = not_applicable
    return out
