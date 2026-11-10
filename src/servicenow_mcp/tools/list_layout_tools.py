"""manage_list_layout — which columns a table's list view shows, in which order.

A list layout is one ``sys_ui_list`` row (table + view; no parent, relationship
or user — those are related lists and personal layouts, out of scope) and its
``sys_ui_list_element`` rows by ``position``.

Like a form section, the list is captured in the update set as a whole
(``sys_ui_list_<table>_null`` for the Default view), so importing it replaces
the target's columns for that view. ``sys_ui_list`` is ``update_synch_custom``:
the platform captures it only when its own code saves it, and a Table API write
does not, so a write reports ``captured`` from a before/after diff of the update
set and is never ``success`` without a new entry. Every write previews
first and only ``confirm_list='<table>:<view>'`` changes it. A table with no
list row of its own shows its parent's list; this tool never creates one —
that would silently fork the list for one table.
"""

import logging
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .form_layout_tools import (
    _NAME,
    _call,
    _captures,
    _fail,
    _read,
    _s,
    _settle_capture,
    _snapshot,
    _unknown_fields,
    _view_id,
)
from .sn_api import invalidate_query_cache

logger = logging.getLogger(__name__)

_DEFAULT_VIEW = "Default view"


class ManageListLayoutParams(BaseModel):
    """List columns (sys_ui_list / sys_ui_list_element)."""

    action: Literal["get", "add_columns", "remove_columns"] = Field(...)
    table: str = Field(..., description="Table whose list it is, e.g. sc_req_item")
    view: str = Field(default=_DEFAULT_VIEW, description="List view name")
    columns: Optional[List[str]] = Field(
        default=None, description="Column names in order; dot-walk allowed (caller_id.email)"
    )
    after: Optional[str] = Field(
        default=None, description="add_columns: insert after this column (default: last)"
    )
    confirm_list: Optional[str] = Field(
        default=None, description="'<table>:<view>' after reading the preview; approves it"
    )

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset({"table", "view"}),
        "add_columns": frozenset({"table", "view", "columns", "after", "confirm_list"}),
        "remove_columns": frozenset({"table", "view", "columns", "confirm_list"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageListLayoutParams":
        if not _NAME.match(self.table):
            raise ValueError("table must be a table name")
        if self.action == "get":
            return self
        cols = self.columns or []
        if not cols:
            raise ValueError(f"{self.action} needs columns")
        if any(not all(_NAME.match(part) for part in c.split(".")) for c in cols):
            raise ValueError("columns are column names, optionally dot-walked")
        if len(set(cols)) != len(cols):
            raise ValueError("columns lists a column twice")
        return self


def _fresh() -> None:
    for t in ("sys_ui_list", "sys_ui_list_element", "sys_update_xml"):
        invalidate_query_cache(table=t)


def _list(config, auth_manager, table: str, view: str) -> Dict[str, Any]:
    """The table's own base list for the view and its columns in order. Raises."""
    _fresh()
    view_id = _view_id(config, auth_manager, view)
    if view_id is None:
        raise LookupError(f"view {view!r} is not one sys_ui_view row on this instance")
    lists = _read(
        config,
        auth_manager,
        "sys_ui_list",
        f"name={table}^view={view_id}^parentISEMPTY^relationshipISEMPTY^sys_userISEMPTY",
        "sys_id",
        5,
    )
    if len(lists) != 1:
        raise LookupError(
            f"{table} has {len(lists)} base list rows for view {view!r}. With none, it shows "
            "its parent's list and a new row would fork it for this table only — set the list "
            "once in the UI (List Layout). More than one is ambiguous."
        )
    list_id = _s(lists[0].get("sys_id"))
    rows = _read(
        config,
        auth_manager,
        "sys_ui_list_element",
        f"list_id={list_id}",
        "sys_id,element,position",
    )
    rows.sort(key=lambda r: int(_s(r.get("position")) or 0))
    return {
        "list_id": list_id,
        "columns": [
            {
                "sys_id": _s(r.get("sys_id")),
                "element": _s(r.get("element")),
                "position": int(_s(r.get("position")) or 0),
            }
            for r in rows
        ],
    }


def _names(lst: Dict[str, Any]) -> List[str]:
    return [c["element"] for c in lst["columns"]]


def _capture_name(p: "ManageListLayoutParams") -> str:
    """The update-set name of a base list: ``sys_ui_list_<table>_<view>``, Default view as
    ``null`` (read off live sys_update_version rows; other views' spelling is unverified, and
    a wrong name can only read as NOT captured, never as captured)."""
    view = "null" if p.view == _DEFAULT_VIEW else p.view
    return f"sys_ui_list_{p.table}_{view}"


def _gate(p: ManageListLayoutParams, preview: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    want = f"{p.table}:{p.view}"
    if (p.confirm_list or "").strip().lower() == want.lower():
        return None
    wrong = f" ({p.confirm_list!r} does not name it)" if p.confirm_list else ""
    return {
        "success": False,
        "approval_required": True,
        "message": f"Nothing written{wrong}. Review before/after, then re-send the same call with "
        f"confirm_list={want!r}.",
        "note": "The list is captured as a whole; importing it replaces the target's columns "
        "for this view.",
        **preview,
    }


def _verify(
    config, auth_manager, p, expect: List[str], out: Dict[str, Any], before_capture
) -> Dict[str, Any]:
    try:
        after = _list(config, auth_manager, p.table, p.view)
    except Exception as e:
        out.update(success=False, verified=False, message=f"Re-read failed ({e}); UNVERIFIED.")
        return out
    out["columns"] = _names(after)
    if out["columns"] != expect:
        mismatch = "The list does not match the columns this call meant to produce."
        out["message"] = f"{out['message']} {mismatch}" if out.get("message") else mismatch
        out["success"] = False
        out["expected"] = expect
    return _settle_capture(
        config,
        auth_manager,
        [_capture_name(p)],
        before_capture,
        out,
        f"Configure > List Layout for {p.table} ({p.view})",
    )


def _context(config, auth_manager, p: ManageListLayoutParams, check: bool):
    try:
        lst = _list(config, auth_manager, p.table, p.view)
        unknown = (
            _unknown_fields(
                config, auth_manager, p.table, sorted({c.split(".")[0] for c in p.columns or []})
            )
            if check
            else []
        )
    except Exception as e:
        return None, _fail(f"Could not read the list or its fields: {e}. Nothing written.")
    if unknown:
        return None, _fail(
            f"Not columns of {p.table} or the tables it extends: {unknown}. Nothing written.",
            unknown=unknown,
        )
    return lst, None


def _get(config, auth_manager, p: ManageListLayoutParams) -> Dict[str, Any]:
    try:
        lst = _list(config, auth_manager, p.table, p.view)
    except Exception as e:
        return _fail(f"Could not read the {p.table} list ({p.view}): {e}", determined=False)
    return {
        "success": True,
        "table": p.table,
        "view": p.view,
        "columns": _names(lst),
        "update_set_capture": _captures(config, auth_manager, [_capture_name(p)]),
    }


def _add_columns(config, auth_manager, p: ManageListLayoutParams) -> Dict[str, Any]:
    lst, refusal = _context(config, auth_manager, p, check=True)
    if refusal:
        return refusal
    names = _names(lst)
    dup = [c for c in p.columns or [] if c in names]
    if dup:
        return _fail(f"Already in the list: {dup}. Nothing written.", already_in_list=dup)
    if p.after is not None and p.after not in names:
        return _fail(f"{p.after!r} is not a column of this list. Nothing written.")
    at = names.index(p.after) + 1 if p.after is not None else len(names)
    expect = names[:at] + list(p.columns or []) + names[at:]
    gate = _gate(p, {"before": names, "after": expect})
    if gate:
        return gate
    snap = _snapshot(config, auth_manager, [_capture_name(p)])
    out: Dict[str, Any] = {"success": True, "done": []}
    try:
        shift = len(p.columns or [])
        for c in reversed(lst["columns"][at:]):
            _call(
                config,
                auth_manager,
                "PATCH",
                "sys_ui_list_element",
                c["sys_id"],
                {"position": c["position"] + shift},
            )
        base = lst["columns"][at - 1]["position"] + 1 if at else 0
        for i, col in enumerate(p.columns or []):
            _call(
                config,
                auth_manager,
                "POST",
                "sys_ui_list_element",
                data={"list_id": lst["list_id"], "element": col, "position": base + i},
            )
            out["done"].append(col)
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and columns.")
    return _verify(config, auth_manager, p, expect, out, snap)


def _remove_columns(config, auth_manager, p: ManageListLayoutParams) -> Dict[str, Any]:
    lst, refusal = _context(config, auth_manager, p, check=False)
    if refusal:
        return refusal
    present = {c["element"]: c for c in lst["columns"]}
    missing = [c for c in p.columns or [] if c not in present]
    if missing:
        return _fail(f"Not in the list: {missing}. Nothing written.", missing=missing)
    names = _names(lst)
    expect = [n for n in names if n not in set(p.columns or [])]
    if not expect:
        return _fail("That would leave the list with no columns. Nothing written.")
    gate = _gate(
        p,
        {
            "before": names,
            "after": expect,
            "data_note": "Only the list column goes; the field and its values stay.",
        },
    )
    if gate:
        return gate
    snap = _snapshot(config, auth_manager, [_capture_name(p)])
    out: Dict[str, Any] = {"success": True, "done": []}
    try:
        for col in p.columns or []:
            _call(config, auth_manager, "DELETE", "sys_ui_list_element", present[col]["sys_id"])
            out["done"].append(col)
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and columns.")
    return _verify(config, auth_manager, p, expect, out, snap)


@register_tool(
    "manage_list_layout",
    params=ManageListLayoutParams,
    description="List columns of a table's list view: get, add_columns, remove_columns. Previews first; never forks an inherited list.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_list_layout(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageListLayoutParams,
) -> Dict[str, Any]:
    return {"get": _get, "add_columns": _add_columns, "remove_columns": _remove_columns}[
        params.action
    ](config, auth_manager, params)
