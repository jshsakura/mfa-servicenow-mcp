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

import hashlib
import json
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

    action: Literal["create", "update", "preview_update", "preview_delete", "delete"] = Field(
        ...,
        description=(
            "create one; update one; update many or delete: preview_* first (read-only), "
            "then run with its token"
        ),
    )
    kind: Optional[Literal["type", "action", "parameter", "group", "link"]] = Field(
        default=None, description="type | action | parameter | group | link (action in a group)"
    )
    fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Column values. References take a sys_id or the record's name",
    )
    parameters: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="create kind=action: parameter rows created with it (name, parameter_type, ...)",
    )
    record_id: Optional[str] = Field(default=None, description="sys_id of one record")
    record_ids: Optional[List[str]] = Field(
        default=None, description="update many: sys_ids of one kind, all get the same fields"
    )
    records: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="delete many: [{kind, record_id}]; deleted dependents-first in one plan",
    )
    preview_token: Optional[str] = Field(
        default=None, description="delete / update many: token from the preview the user approved"
    )
    confirm_count: Optional[int] = Field(
        default=None, description="delete / update many: record count from that preview"
    )
    scope: Optional[str] = Field(
        default=None, description="create: sys_scope sys_id the record must land in"
    )
    update_set: Optional[str] = Field(
        default=None, description="create: update set name or sys_id to capture into"
    )
    dry_run: bool = Field(default=False, description="create / update one: show, write nothing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "create": frozenset({"kind", "fields", "parameters", "scope", "update_set", "dry_run"}),
        "update": frozenset(
            {
                "kind",
                "fields",
                "record_id",
                "record_ids",
                "preview_token",
                "confirm_count",
                "dry_run",
            }
        ),
        "preview_update": frozenset({"kind", "fields", "record_ids"}),
        "preview_delete": frozenset({"kind", "record_id", "records"}),
        "delete": frozenset({"kind", "record_id", "records", "preview_token", "confirm_count"}),
    }

    @model_validator(mode="after")
    def _validate(self) -> "ManagePortalActionParams":
        a = self.action
        if a in ("preview_delete", "delete"):
            self._validate_delete_targets()
            if a == "delete" and (not self.preview_token or self.confirm_count is None):
                raise ValueError(
                    "delete needs preview_token and confirm_count from preview_delete — "
                    "preview first, show the user the plan, delete only on their go-ahead"
                )
            return self
        if not self.kind:
            raise ValueError("kind is required")
        kind = KINDS[self.kind]
        unknown = sorted(set(self.fields) - kind.fields)
        if unknown:
            # ServiceNow drops an unknown column from a write without complaint,
            # so a typo would report success with the value missing.
            raise ValueError(
                f"unknown field(s) {unknown} for kind='{self.kind}'; allowed: {sorted(kind.fields)}"
            )
        if a == "create":
            missing = [f for f in kind.required if self.fields.get(f) in (None, "")]
            if missing:
                raise ValueError(f"create kind='{self.kind}' needs fields {missing}")
            if not self.scope:
                raise ValueError("scope is required for action='create'")
        else:
            if self.record_id and self.record_ids:
                raise ValueError("pass record_id or record_ids, not both")
            if a == "preview_update" and not self.record_ids:
                raise ValueError("preview_update takes record_ids (one record: update dry_run)")
            if not self.record_id and not self.record_ids:
                raise ValueError(f"record_id or record_ids is required for action='{a}'")
            ids = list(self.record_ids or [])
            if len(set(ids)) != len(ids):
                raise ValueError("record_ids lists the same sys_id twice")
            if not self.fields:
                raise ValueError(f"{a} needs at least one field")
            if (
                a == "update"
                and self.record_ids
                and (not self.preview_token or self.confirm_count is None)
            ):
                raise ValueError(
                    "update with record_ids needs preview_token and confirm_count from "
                    "preview_update — preview first, apply only on the user's go-ahead"
                )
        if self.parameters is not None and not (a == "create" and self.kind == "action"):
            raise ValueError("parameters only go with action='create' kind='action'")
        for row in self.parameters or []:
            bad = sorted(set(row) - (KINDS["parameter"].fields - {"action"}))
            if bad:
                raise ValueError(f"unknown parameter field(s) {bad}")
            if not row.get("name") or not row.get("parameter_type"):
                raise ValueError("every parameter needs name and parameter_type")
        return self

    def _validate_delete_targets(self) -> None:
        if self.fields or self.record_ids:
            raise ValueError("delete takes record_id+kind or records, nothing else")
        if self.records:
            if self.kind or self.record_id:
                raise ValueError("pass records, or kind+record_id — not both")
            for r in self.records:
                if r.get("kind") not in KINDS or not r.get("record_id"):
                    raise ValueError(
                        f"every record needs kind (one of {sorted(KINDS)}) and record_id"
                    )
            if len({r["record_id"] for r in self.records}) != len(self.records):
                raise ValueError("records lists the same record_id twice")
        elif not (self.kind and self.record_id):
            raise ValueError("delete needs kind and record_id, or records")


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


def _patch(config, auth_manager, table: str, sys_id: str, body: Dict[str, str]) -> None:
    url = f"{config.instance_url}/api/now/table/{table}/{sys_id}"
    response = auth_manager.make_request(
        "PATCH", url, json=body, headers=auth_manager.get_headers(), timeout=30
    )
    response.raise_for_status()
    invalidate_query_cache(table=table)


def _align_to_scope(config, auth_manager, scopes: Dict[str, str]) -> Dict[str, Any]:
    """Point the session at the one scope the records live in before changing them.

    A record in a scoped app answers a write from another current app with 403
    (measured: Employee Center records, session on Global). *scopes* maps
    record sys_id -> its sys_scope. Returns {"error": ...} or what was switched.
    """
    distinct = sorted(set(scopes.values()))
    if len(distinct) != 1 or not distinct[0]:
        return {
            "error": {
                "success": False,
                "message": (
                    "The records live in more than one scope; change one scope per call."
                    if len(distinct) > 1
                    else "Could not read the records' scope; nothing was changed."
                ),
                "scopes": scopes,
            }
        }
    return align_session_for_create(config, auth_manager, scope=distinct[0])


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
    assert params.kind  # validator guarantees it for create
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

    p_table = KINDS["parameter"].table
    added_by_platform: List[Dict[str, Any]] = []
    if params.kind == "action":
        # An Employee Center business rule ("Inserting and updating action
        # parameters") adds a blank string parameter for every name in the
        # type's server/client parameter lists the moment an action is
        # inserted. A requested parameter with the same name and side fills
        # that row; inserting another would leave two, one of them blank.
        try:
            stubs = _read(
                config, auth_manager, p_table, f"action={sys_id}", "sys_id,name,is_client", 50
            )
        except Exception as e:
            stubs = []
            problems.append(f"could not read parameters the platform adds ({e})")
        by_key = {
            (_raw(r.get("name")), _norm(r.get("is_client")) == "true"): _raw(r.get("sys_id"))
            for r in stubs
        }
        used: set = set()
        for row in params.parameters or []:
            p_body = _body({**row, "action": sys_id})
            key = (row["name"], _norm(row.get("is_client", False)) == "true")
            try:
                if key in by_key:
                    p_id = by_key[key]
                    _patch(config, auth_manager, p_table, p_id, p_body)
                else:
                    p_id = _raw(_insert(config, auth_manager, p_table, p_body).get("sys_id"))
            except Exception as e:
                problems.append(f"parameter '{row['name']}' not written ({e}); stopped here")
                break
            used.add(p_id)
            created.append({"table": p_table, "sys_id": p_id, "name": row["name"]})
            problems += [
                f"parameter '{row['name']}': {p}"
                for p in _verify(config, auth_manager, p_table, p_id, p_body)
            ]
        for (name, is_client), p_id in by_key.items():
            if p_id not in used:
                added_by_platform.append({"sys_id": p_id, "name": name, "is_client": is_client})
                created.append({"table": p_table, "sys_id": p_id, "name": name})

    if len(created) > 1:
        targets = [
            {
                "kind": "parameter" if c["table"] != kind.table else params.kind,
                "record_id": c["sys_id"],
            }
            for c in created
        ]
        undo = f"manage_portal_action action='preview_delete' records={targets}"
    else:
        undo = f"manage_portal_action action='preview_delete' kind='{params.kind}' record_id='{sys_id}'"
    undo += " — then delete with its token once the user approves"
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
        **(
            {
                "added_by_platform": added_by_platform,
                "added_by_platform_note": (
                    "Blank parameters the platform created from the type's parameter "
                    "lists; set their value with action='update' kind='parameter'."
                ),
            }
            if added_by_platform
            else {}
        ),
        "missing": problems,
        "undo": undo,
        **extras,
    }


def _token(instance: str, action: str, rows: List[Any]) -> str:
    """Fingerprint of a reviewed plan, including each record's sys_mod_count —
    any edit to a record after the preview changes it."""
    canon = json.dumps(
        {"instance": instance, "action": action, "rows": rows}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _stale(plan_token: str, count: int, params: ManagePortalActionParams, preview: str) -> Any:
    """The plan recomputed now must be the plan that was approved. Refusal or None."""
    if plan_token == params.preview_token and count == params.confirm_count:
        return None
    return {
        "success": False,
        "error": "PREVIEW_STALE",
        "message": (
            f"This is not the plan that was previewed (now {count} record(s), confirm_count "
            f"was {params.confirm_count}; a record or the request changed since). Nothing was "
            "changed. Preview again and show the user the new plan."
        ),
        "preview_again": preview,
    }


def _update_plan(config, auth_manager, params: ManagePortalActionParams) -> Dict[str, Any]:
    """Read every target and work out the change. Never writes."""
    assert params.kind
    kind = KINDS[params.kind]
    ids = [params.record_id] if params.record_id else list(params.record_ids or [])
    try:
        values = _resolve_refs(config, auth_manager, kind, params.fields)
        cols = ",".join(sorted(set(values) | {"sys_id", "sys_scope", "sys_mod_count", "name"}))
        before: Dict[str, Dict[str, Any]] = {}
        for rid in ids:
            rows = _read(config, auth_manager, kind.table, f"sys_id={rid}", cols, 1)
            if not rows:
                return {"success": False, "message": f"No {kind.table} {rid}; nothing was changed."}
            before[rid] = rows[0]
    except Exception as e:
        return {"success": False, "message": f"Could not read the records: {e}"}
    body = _body(values)
    changes = {
        rid: {
            k: {"from": _raw(row.get(k)), "to": v}
            for k, v in body.items()
            if _norm(row.get(k)) != _norm(v)
        }
        for rid, row in before.items()
    }
    changes = {rid: ch for rid, ch in changes.items() if ch}
    token = _token(
        config.instance_url,
        "update",
        [
            [rid, _raw(before[rid].get("sys_mod_count")), sorted(body.items())]
            for rid in sorted(changes)
        ],
    )
    return {
        "success": True,
        "kind": kind,
        "ids": ids,
        "body": body,
        "before": before,
        "changes": changes,
        "token": token,
    }


def _update(config, auth_manager, params: ManagePortalActionParams) -> Dict[str, Any]:
    p = _update_plan(config, auth_manager, params)
    if not p.get("success"):
        return p
    kind, ids, body, changes = p["kind"], p["ids"], p["body"], p["changes"]
    if not changes:
        return {"success": True, "message": "Nothing to change", "record_ids": ids}
    shown = {
        "table": kind.table,
        "count": len(changes),
        "changes": [
            {"record_id": rid, "name": _raw(p["before"][rid].get("name")), "changes": ch}
            for rid, ch in changes.items()
        ],
    }
    if params.action == "preview_update":
        return {
            "success": True,
            "preview": True,
            "operation": "update",
            **shown,
            "preview_token": p["token"],
            "next": (
                "Nothing was changed. Show the user every record above. Only on their explicit "
                "go-ahead: manage_portal_action(action='update', <same kind/record_ids/fields>, "
                f"preview_token='{p['token']}', confirm_count={len(changes)}, confirm='approve')."
            ),
        }
    if params.dry_run:
        return {"success": True, "dry_run": True, "operation": "update", **shown}
    if params.record_ids:
        refused = _stale(
            p["token"],
            len(changes),
            params,
            "manage_portal_action(action='preview_update', <same kind/record_ids/fields>)",
        )
        if refused:
            return refused
    aligned = _align_to_scope(
        config, auth_manager, {rid: _raw(p["before"][rid].get("sys_scope")) for rid in changes}
    )
    if aligned.get("error"):
        return aligned["error"]

    done: List[str] = []
    problems: List[str] = []
    for rid in changes:
        try:
            _patch(config, auth_manager, kind.table, rid, body)
        except Exception as e:
            logger.error("Error updating %s %s: %s", kind.table, rid, e)
            problems.append(f"{rid}: update failed ({e}); stopped here")
            break
        done.append(rid)
        problems += [f"{rid}: {pr}" for pr in _verify(config, auth_manager, kind.table, rid, body)]
    not_done = [rid for rid in changes if rid not in done]
    return {
        "success": bool(done),
        "complete": not problems and not not_done,
        "message": (
            f"Updated {len(done)} {kind.table} record(s)"
            if not problems and not not_done
            else f"Updated {len(done)} of {len(changes)}; NOT confirmed: " + "; ".join(problems)
        ),
        **shown,
        "updated": done,
        "not_updated": not_done,
        "missing": problems,
        **{k: v for k, v in aligned.items() if v},
    }


# Rows that point at a record of each kind. Deleting a record they still point
# at leaves a button with no type, an empty link, or an override of nothing.
_DEPENDENTS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "type": (("action", "action_type"), ("type", "sys_overrides")),
    "action": (("parameter", "action"), ("link", "action"), ("action", "sys_overrides")),
    "group": (("link", "group"), ("group", "sys_overrides")),
    "parameter": (),
    "link": (("link", "sys_overrides"),),
}
# Children before parents, so a whole button set can go in one plan.
_DELETE_ORDER = ("link", "parameter", "action", "group", "type")
_DEPENDENT_CAP = 50


def _dependents(config, auth_manager, kind_name: str, sys_id: str) -> List[Dict[str, Any]]:
    """Every row still pointing at the record. Raises when a table cannot be read."""
    found: List[Dict[str, Any]] = []
    for dep_kind, column in _DEPENDENTS[kind_name]:
        table = KINDS[dep_kind].table
        rows = _read(
            config, auth_manager, table, f"{column}={sys_id}", "sys_id,name", _DEPENDENT_CAP
        )
        for r in rows:
            found.append(
                {
                    "kind": dep_kind,
                    "record_id": _raw(r.get("sys_id")),
                    "name": _raw(r.get("name")),
                    "points_at": sys_id,
                    "via": column,
                }
            )
    return found


def _delete_plan(config, auth_manager, params: ManagePortalActionParams) -> Dict[str, Any]:
    """Read every target and everything pointing at it. Never writes."""
    if params.records:
        targets = [(r["kind"], r["record_id"]) for r in params.records]
    else:
        assert params.kind and params.record_id
        targets = [(params.kind, params.record_id)]
    targets.sort(key=lambda t: _DELETE_ORDER.index(t[0]))
    in_plan = {rid for _, rid in targets}

    plan: List[Dict[str, Any]] = []
    blocking: List[Dict[str, Any]] = []
    scopes: Dict[str, str] = {}
    try:
        for kind_name, rid in targets:
            table = KINDS[kind_name].table
            rows = _read(
                config,
                auth_manager,
                table,
                f"sys_id={rid}",
                "sys_id,name,sys_scope,sys_mod_count,sys_updated_on,sys_updated_by",
                1,
            )
            if not rows:
                return {
                    "success": False,
                    "message": f"No {table} {rid} (kind='{kind_name}'); nothing was deleted.",
                }
            row = rows[0]
            scopes[rid] = _raw(row.get("sys_scope"))
            plan.append(
                {
                    "kind": kind_name,
                    "table": table,
                    "record_id": rid,
                    "name": _raw(row.get("name")),
                    "last_updated": f"{_raw(row.get('sys_updated_on'))} by "
                    f"{_raw(row.get('sys_updated_by'))}",
                    "_mod": _raw(row.get("sys_mod_count")),
                }
            )
            blocking += [
                d
                for d in _dependents(config, auth_manager, kind_name, rid)
                if d["record_id"] not in in_plan
            ]
    except Exception as e:
        return {"success": False, "message": f"Could not check the records before delete: {e}"}
    token = _token(
        config.instance_url, "delete", [[i["record_id"], i["kind"], i["_mod"]] for i in plan]
    )
    for item in plan:
        item.pop("_mod")
    return {
        "success": True,
        "plan": plan,
        "blocking": blocking,
        "scopes": scopes,
        "token": token,
    }


def _recovery(config, auth_manager, record_id: str) -> Dict[str, Any]:
    """Whether the platform kept a restorable copy (Deleted Records, sys_audit_delete)."""
    try:
        rows = _read(
            config, auth_manager, "sys_audit_delete", f"documentkey={record_id}", "sys_id", 1
        )
    except Exception as e:
        return {"recoverable": None, "why": f"could not read sys_audit_delete ({e})"}
    if not rows:
        return {
            "recoverable": False,
            "why": "no Deleted Records entry — Undelete Record cannot bring it back",
        }
    return {"recoverable": True, "audit_delete_id": _raw(rows[0].get("sys_id"))}


def _delete(config, auth_manager, params: ManagePortalActionParams) -> Dict[str, Any]:
    p = _delete_plan(config, auth_manager, params)
    if not p.get("success"):
        return p
    plan = p["plan"]
    if p["blocking"]:
        return {
            "success": False,
            "message": (
                f"{len(p['blocking'])} row(s) outside this request still point at it; nothing "
                "was deleted. Add them to records, or leave the record they point at."
            ),
            "plan": plan,
            "dependents": p["blocking"],
        }
    if params.action == "preview_delete":
        return {
            "success": True,
            "preview": True,
            "operation": "delete",
            "count": len(plan),
            "plan": plan,
            "preview_token": p["token"],
            "next": (
                "Nothing was deleted. Show the user every record above (kind, name, last "
                "updated). Only on their explicit go-ahead: manage_portal_action("
                "action='delete', <same records or kind/record_id>, preview_token="
                f"'{p['token']}', confirm_count={len(plan)}, confirm='approve')."
            ),
        }
    refused = _stale(
        p["token"],
        len(plan),
        params,
        "manage_portal_action(action='preview_delete', <same records or kind/record_id>)",
    )
    if refused:
        return refused
    aligned = _align_to_scope(config, auth_manager, p["scopes"])
    if aligned.get("error"):
        return aligned["error"]

    deleted: List[Dict[str, Any]] = []
    problems: List[str] = []
    for item in plan:
        url = f"{config.instance_url}/api/now/table/{item['table']}/{item['record_id']}"
        try:
            response = auth_manager.make_request(
                "DELETE", url, headers=auth_manager.get_headers(), timeout=30
            )
            response.raise_for_status()
        except Exception as e:
            logger.error("Error deleting %s %s: %s", item["table"], item["record_id"], e)
            problems.append(f"{item['record_id']}: delete failed ({e}); stopped here")
            break
        invalidate_query_cache(table=item["table"])
        deleted.append({**item, **_recovery(config, auth_manager, item["record_id"])})
        try:
            still = _read(
                config, auth_manager, item["table"], f"sys_id={item['record_id']}", "sys_id", 1
            )
            if still:
                problems.append(f"{item['record_id']}: still exists after delete; stopped here")
                break
        except Exception as e:
            problems.append(f"{item['record_id']}: could not read back ({e}); stopped here")
            break
    gone = {d["record_id"] for d in deleted}
    remaining = [i for i in plan if i["record_id"] not in gone]
    unrecoverable = [d["record_id"] for d in deleted if d.get("recoverable") is not True]
    return {
        "success": bool(deleted),
        "complete": not problems and not remaining,
        "message": (
            f"Deleted {len(deleted)} record(s)"
            if not problems and not remaining
            else f"Deleted {len(deleted)} of {len(plan)}; NOT confirmed: " + "; ".join(problems)
        ),
        "deleted": deleted,
        "not_deleted": remaining,
        "missing": problems,
        "restore": (
            "Each deleted record is in Deleted Records (sys_audit_delete); an admin restores "
            "it there with Undelete Record."
            if deleted and not unrecoverable
            else f"NOT confirmed restorable: {unrecoverable}" if unrecoverable else ""
        ),
        **{k: v for k, v in aligned.items() if v},
    }


@register_tool(
    name="manage_portal_action",
    params=ManagePortalActionParams,
    description=(
        "Employee Center action-widget buttons: create/update/delete action types, actions "
        "(+parameters), groups, links. Delete and bulk update: preview first."
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
    if params.action in ("preview_delete", "delete"):
        return _delete(config, auth_manager, params)
    return _update(config, auth_manager, params)
