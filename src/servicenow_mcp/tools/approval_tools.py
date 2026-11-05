"""manage_approval — list / approve / reject sysapproval_approver rows for any record.

The caller is verified server-side BEFORE any write: an approval is a decision
made by (or lawfully for) a named person, and the Table API will happily let any
session with the right ACL write someone else's row. Three bases are accepted,
and the response always names the one used:

- ``approver``: the session user IS the approver.
- ``delegate``: a live sys_user_delegate row (approvals=true, inside starts/ends).
- ``on_behalf``: neither proven (or identity unknown) and the caller passed
  ``confirm_on_behalf`` equal to the approver's user_name — a named second
  approval, recorded in the approval comment.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .record_context_tools import resolve_table
from .sn_api import _authenticated_user, invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_APPROVAL_FIELDS = "sys_id,approver,state,document_id,sysapproval,source_table,comments"
_FLOW_HINT = (
    "Downstream progression (flow/workflow) is asynchronous; check sys_flow_context "
    "for the record if the parent has not moved."
)


def _raw(value: Any) -> str:
    """Raw value of a Table-API field that may be {value, display_value}."""
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(value or "")


def _disp(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("display_value") or value.get("value") or "")
    return str(value or "")


def _q(config, auth_manager, table, query, fields, limit=50, display="all"):
    """Strict read: raises on failure so an unread answer is never an empty one."""
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        display_value=display,
        fail_silently=False,
    )
    return rows


def _refuse(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message, **extra}


def _parse_dt(text: str) -> Optional[Tuple[datetime, bool]]:
    """``(utc datetime, date_only)`` or None when the text is neither format."""
    text = (text or "").strip()
    for fmt, date_only in (("%Y-%m-%d %H:%M:%S", False), ("%Y-%m-%d", True)):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc), date_only
        except ValueError:
            continue
    return None


def _delegation_live(row: Dict[str, Any], now: datetime) -> bool:
    """starts empty or <= now, ends empty or >= now. An unparseable bound is NOT live."""
    starts, ends = _raw(row.get("starts")), _raw(row.get("ends"))
    if starts:
        parsed = _parse_dt(starts)
        if parsed is None or parsed[0] > now:
            return False
    if ends:
        parsed = _parse_dt(ends)
        if parsed is None:
            return False
        end, date_only = parsed
        if date_only:  # a date-only end is inclusive of that whole day
            end = end.replace(hour=23, minute=59, second=59)
        if end < now:
            return False
    return True


def _user_by_name(config, auth_manager, user_name: str) -> Optional[Dict[str, str]]:
    rows = _q(
        config, auth_manager, "sys_user", f"user_name={user_name}", "sys_id,user_name,name", 2
    )
    if not rows:
        return None
    return {
        "sys_id": _raw(rows[0].get("sys_id")),
        "user_name": _raw(rows[0].get("user_name")),
        "name": _disp(rows[0].get("name")),
    }


def _user_by_id(config, auth_manager, sys_id: str) -> Optional[Dict[str, str]]:
    rows = _q(config, auth_manager, "sys_user", f"sys_id={sys_id}", "sys_id,user_name,name", 1)
    if not rows:
        return None
    return {
        "sys_id": sys_id,
        "user_name": _raw(rows[0].get("user_name")),
        "name": _disp(rows[0].get("name")),
    }


def _caller(config, auth_manager) -> Optional[str]:
    try:
        return _authenticated_user(config, auth_manager, allow_live=True) or None
    except Exception as exc:  # identity unknown, never a crash
        logger.debug("caller identity lookup failed: %s", exc)
        return None


def verify_caller(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    approver: Dict[str, str],
    confirm_on_behalf: Optional[str],
) -> Dict[str, Any]:
    """Decide whether this session may decide for ``approver``.

    Returns ``{"allowed": bool, "basis": approver|delegate|on_behalf, "caller": ...}``
    or, when not allowed, a refusal dict (``allowed`` False, ``success`` False).
    Every failure to PROVE degrades to the named-approval path, never to allowed.
    """
    caller = _caller(config, auth_manager)
    approver_name = approver.get("user_name", "")
    notes: List[str] = []
    if caller and approver_name and caller.casefold() == approver_name.casefold():
        return {"allowed": True, "basis": "approver", "caller": caller}
    if caller:
        try:
            me = _user_by_name(config, auth_manager, caller)
            if me and approver.get("sys_id"):
                rows = _q(
                    config,
                    auth_manager,
                    "sys_user_delegate",
                    f"user={approver['sys_id']}^delegate={me['sys_id']}^approvals=true",
                    "sys_id,user,delegate,approvals,starts,ends",
                    20,
                )
                now = datetime.now(timezone.utc)
                if any(_delegation_live(r, now) for r in rows):
                    return {"allowed": True, "basis": "delegate", "caller": caller}
                notes.append(
                    "no live sys_user_delegate (approvals=true) from the approver to the caller"
                    if not rows
                    else "delegation exists but is outside its starts/ends window"
                )
            else:
                notes.append("caller's sys_user row could not be resolved")
        except Exception as exc:
            notes.append(f"delegate check could not be read ({exc})")
    else:
        notes.append("session identity could not be determined")
    if approver_name and confirm_on_behalf == approver_name:
        return {
            "allowed": True,
            "basis": "on_behalf",
            "caller": caller or "unidentified session",
            "identity_known": bool(caller),
        }
    return {
        "allowed": False,
        "success": False,
        "error": "caller_not_approver",
        "caller": caller,
        "approver": approver_name or approver.get("sys_id"),
        "because": "; ".join(notes),
        "message": (
            f"Session user '{caller or 'unidentified'}' is not approver '{approver_name}' "
            "and not a valid delegate. To decide for them, pass "
            f"confirm_on_behalf='{approver_name}' (recorded in the approval comment)."
        ),
    }


def _read_parent_approval(
    config, auth_manager, row: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str]]:
    """``(approval value, note)``; a failed read is None plus why, not a guess."""
    table, doc = _raw(row.get("source_table")), _raw(row.get("document_id"))
    if not table or not doc:
        return None, "parent table/sys_id not on the approval row"
    try:
        rows = _q(config, auth_manager, table, f"sys_id={doc}", "sys_id,approval", 1, "false")
    except Exception as exc:
        return None, f"parent read failed: {exc}"
    if not rows:
        return None, f"{table} {doc} not readable"
    return _raw(rows[0].get("approval")), None


def decide_approval(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    approval_id: str,
    decision: Literal["approved", "rejected"],
    comments: Optional[str] = None,
    confirm_on_behalf: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Verify the caller, write the decision, re-read to prove it. Shared by manage_change."""
    if decision == "rejected" and not (comments or "").strip():
        return _refuse("comments_required", "comments are required to reject.")
    try:
        rows = _q(
            config,
            auth_manager,
            "sysapproval_approver",
            f"sys_id={approval_id}",
            _APPROVAL_FIELDS,
            1,
        )
    except Exception as exc:
        return _refuse("approval_unreadable", f"Could not read approval {approval_id}: {exc}")
    if not rows:
        return _refuse("approval_not_found", f"No sysapproval_approver {approval_id}.")
    row = rows[0]
    state = _raw(row.get("state"))
    if state != "requested":
        return _refuse(
            "not_actionable",
            f"Approval is in state '{state}'; only 'requested' can be decided.",
            current_state=state,
        )
    approver_id = _raw(row.get("approver"))
    try:
        approver = _user_by_id(config, auth_manager, approver_id) if approver_id else None
    except Exception as exc:
        return _refuse("approver_unreadable", f"Could not read the approver: {exc}")
    if not approver or not approver["user_name"]:
        return _refuse(
            "approver_unresolved",
            "The approver is not a readable sys_user (group approval?); refusing to decide for it.",
        )

    check = verify_caller(
        config, auth_manager, approver=approver, confirm_on_behalf=confirm_on_behalf
    )
    if not check["allowed"]:
        return {k: v for k, v in check.items() if k != "allowed"}
    basis, caller = check["basis"], check["caller"]

    verb = "Approved" if decision == "approved" else "Rejected"
    body: Dict[str, Any] = {"state": decision}
    text = (comments or "").strip()
    if basis == "on_behalf":
        note = f"{verb} via MCP by {caller} on behalf of {approver['user_name']}"
        text = f"{text}\n{note}" if text else note
    if text:
        body["comments"] = text

    result: Dict[str, Any] = {
        "approval_id": approval_id,
        "decision": decision,
        "caller": caller,
        "approver": approver["user_name"],
        "basis": basis,
    }
    if dry_run:
        return {"success": True, "dry_run": True, "would_write": body, **result}

    resp = auth_manager.make_request(
        "PATCH",
        f"{config.api_url}/table/sysapproval_approver/{approval_id}",
        json=body,
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    invalidate_query_cache(table="sysapproval_approver")
    parent_table = _raw(row.get("source_table"))
    if parent_table:
        invalidate_query_cache(table=parent_table)

    try:
        after = _q(
            config,
            auth_manager,
            "sysapproval_approver",
            f"sys_id={approval_id}",
            _APPROVAL_FIELDS,
            1,
        )
    except Exception as exc:
        return {
            "success": False,
            "applied": None,
            "message": f"Write sent but the re-read failed ({exc}); state unverified.",
            **result,
        }
    state_after = _raw(after[0].get("state")) if after else None
    parent_approval, parent_note = _read_parent_approval(
        config, auth_manager, after[0] if after else row
    )
    applied = state_after == decision
    out: Dict[str, Any] = {
        "success": applied,
        "applied": applied,
        "state_after": state_after,
        "parent_approval": parent_approval,
        "message": (
            f"{verb} (basis: {basis})."
            if applied
            else f"Write returned OK but the row is still '{state_after}' — a business rule "
            "may have aborted it."
        ),
        "note": _FLOW_HINT,
        **result,
    }
    if parent_note:
        out["parent_note"] = parent_note
    return out


# ---------------------------------------------------------------------------
# manage_approval
# ---------------------------------------------------------------------------


_DECIDE_FIELDS = frozenset(
    {"approval_id", "record", "table", "approver", "comments", "confirm_on_behalf", "dry_run"}
)


class ManageApprovalParams(BaseModel):
    """Approvals (sysapproval_approver) on any record."""

    action: Literal["list", "approve", "reject"] = Field(...)
    approval_id: Optional[str] = Field(default=None, description="sysapproval_approver sys_id")
    record: Optional[str] = Field(default=None, description="Record number (INC...) or sys_id")
    table: Optional[str] = Field(default=None, description="Table when record is a sys_id")
    approver: Optional[str] = Field(default=None, description="Approver user_name or sys_id")
    state: str = Field(default="requested", description="list filter: a state or 'any'")
    comments: Optional[str] = Field(default=None, description="Required for reject")
    confirm_on_behalf: Optional[str] = Field(
        default=None,
        description="Required to decide for another user: that approver's user_name.",
    )
    limit: int = Field(default=20, description="Max rows (list)")
    dry_run: bool = Field(default=False, description="Verify and preview, no write")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"record", "table", "approver", "state", "limit"}),
        "approve": _DECIDE_FIELDS,
        "reject": _DECIDE_FIELDS,
    }

    @model_validator(mode="after")
    def _validate(self) -> "ManageApprovalParams":
        if self.action == "reject" and not (self.comments or "").strip():
            raise ValueError("comments are required for action='reject'")
        if self.action != "list" and not (self.approval_id or self.record):
            raise ValueError(f"approval_id or record is required for action='{self.action}'")
        return self


def _record_sys_id(
    config, auth_manager, record: str, table: Optional[str]
) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """``(sys_id, table, refusal)``."""
    if _SYS_ID.match(record):
        return record, table, None
    resolved, err = resolve_table(config, auth_manager, record)
    if err or not resolved:
        return None, None, err or _refuse("unresolved_number", f"Cannot resolve '{record}'.")
    try:
        rows = _q(config, auth_manager, resolved, f"number={record}", "sys_id", 1, "false")
    except Exception as exc:
        return None, None, _refuse("record_unreadable", f"Could not read {record}: {exc}")
    if not rows:
        return (
            None,
            None,
            _refuse(
                "record_not_determined",
                f"No row for {record} in {resolved} — absent, or hidden from this account by ACL.",
            ),
        )
    return _raw(rows[0].get("sys_id")), resolved, None


def _approver_sys_id(config, auth_manager, who: str) -> str:
    if _SYS_ID.match(who):
        return who
    user = _user_by_name(config, auth_manager, who)
    if not user:
        raise LookupError(f"approver '{who}' is not a sys_user user_name")
    return user["sys_id"]


def _list_rows(config, auth_manager, params: ManageApprovalParams) -> Dict[str, Any]:
    parts: List[str] = []
    try:
        if params.record:
            sid, _tbl, err = _record_sys_id(config, auth_manager, params.record, params.table)
            if err:
                return err
            parts.append(f"document_id={sid}^ORsysapproval={sid}")
        if params.approver or not params.record:
            who = params.approver
            if not who:
                who = _caller(config, auth_manager)
                if not who:
                    return _refuse(
                        "identity_unknown",
                        "Session identity unknown: pass record or approver to list.",
                    )
            parts.append(f"approver={_approver_sys_id(config, auth_manager, who)}")
        if params.state != "any":
            parts.append(f"state={params.state}")
        rows = _q(
            config,
            auth_manager,
            "sysapproval_approver",
            "^".join(parts),
            _APPROVAL_FIELDS,
            max(1, min(params.limit, 100)),
        )
    except Exception as exc:
        return _refuse("approvals_unreadable", f"Could not list approvals: {exc}")
    items = [
        {
            "sys_id": _raw(r.get("sys_id")),
            "approver": _disp(r.get("approver")),
            "state": _raw(r.get("state")),
            "document_id": _raw(r.get("document_id")),
            "source_table": _raw(r.get("source_table")),
            "comments": _raw(r.get("comments"))[:200],
        }
        for r in rows
    ]
    return {"success": True, "count": len(items), "approvals": items}


def _select_row(
    config, auth_manager, params: ManageApprovalParams
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Pick the approval to decide: explicit id, else the one unambiguous requested row."""
    if params.approval_id:
        return params.approval_id, None
    assert params.record
    try:
        sid, _tbl, err = _record_sys_id(config, auth_manager, params.record, params.table)
        if err:
            return None, err
        query = f"(document_id={sid}^ORsysapproval={sid})^state=requested"
        if params.approver:
            query += f"^approver={_approver_sys_id(config, auth_manager, params.approver)}"
        rows = _q(config, auth_manager, "sysapproval_approver", query, _APPROVAL_FIELDS, 50)
    except Exception as exc:
        return None, _refuse("approvals_unreadable", f"Could not read approvals: {exc}")
    if not rows:
        return None, _refuse("no_requested_approval", "No approval in state 'requested' matches.")
    if len(rows) > 1 and not params.approver:
        me = _caller(config, auth_manager)
        try:
            me_row = _user_by_name(config, auth_manager, me) if me else None
        except Exception:
            me_row = None
        mine = [r for r in rows if me_row and _raw(r.get("approver")) == me_row["sys_id"]]
        if len(mine) != 1:
            return None, _refuse(
                "ambiguous_approval",
                "Several requested approvals match; pass approval_id or approver.",
                candidates=[
                    {"sys_id": _raw(r.get("sys_id")), "approver": _disp(r.get("approver"))}
                    for r in rows
                ],
            )
        rows = mine
    return _raw(rows[0].get("sys_id")), None


@register_tool(
    name="manage_approval",
    params=ManageApprovalParams,
    description="Approvals on any record: list pending, approve/reject. Caller is verified as the approver or delegate.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_approval(
    config: ServerConfig, auth_manager: AuthManager, params: ManageApprovalParams
) -> Dict[str, Any]:
    if params.action == "list":
        return _list_rows(config, auth_manager, params)
    approval_id, err = _select_row(config, auth_manager, params)
    if err:
        return err
    assert approval_id
    try:
        return decide_approval(
            config,
            auth_manager,
            approval_id=approval_id,
            decision="approved" if params.action == "approve" else "rejected",
            comments=params.comments,
            confirm_on_behalf=params.confirm_on_behalf,
            dry_run=params.dry_run,
        )
    except Exception as exc:
        logger.error("manage_approval %s failed: %s", params.action, exc)
        return _refuse("write_failed", f"Error during {params.action}: {exc}")
