"""get_table_automation: what runs when a record on table X is inserted/updated.

Replaces a hand-chained set of reads (business rules, flow triggers, legacy
workflows, client scripts, UI/data policies, notifications, SLAs, assignment and
approval rules, UI actions) with one bounded answer. No script bodies are read.

Every category states what it PROVED: a category that could not be read is
``{checked: false, because}`` -- never an empty list -- and a capped one says
``complete: false`` with the server total. A table that is not there answers
with the ``unknown_table`` / ``feature_not_installed`` / ``undetermined`` verdict
of the shared read-failure path, not an empty result.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.record_context_tools import _complete, _lab, _page, _val
from servicenow_mcp.tools.sn_api import _read_failure_verdict
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_ROW_CAP = 50
_MAX_LEVELS = 6
_WORKERS = 4
_OPERATIONS = ("insert", "update", "delete", "query", "any")
_ORIGIN = ("sys_scope", "sys_package", "sys_policy")
_WHEN_RANK = {"before": 0, "after": 1, "async": 2, "async_always": 2, "display": -1}


class TableAutomationParams(BaseModel):
    table: str = Field(description="Table name, e.g. incident (REQUIRED).")
    operation: Optional[str] = Field(
        default="any", description="insert, update, delete, query or any (default)."
    )
    include_inherited: bool = Field(
        default=True, description="Also report automation on parent tables (task for incident)."
    )
    include_inactive: bool = Field(default=False, description="Include inactive records.")
    categories: Optional[List[str]] = Field(
        default=None,
        description="Only these categories (summary keys). Default: all for the operation.",
    )


def _flag(row: Dict[str, Any], field: str) -> bool:
    return _val(row, field).lower() == "true"


def _origin(row: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for field in _ORIGIN:
        text = _lab(row, field)
        if text:
            out[field.replace("sys_", "")] = text
    return out


def _order(row: Dict[str, Any]) -> int:
    try:
        return int(_val(row, "order") or 0)
    except ValueError:
        return 0


def _put(entry: Dict[str, Any], row: Dict[str, Any], *fields: str) -> None:
    """Add non-empty fields verbatim (conditions are shown as written)."""
    for field in fields:
        text = _val(row, field)
        if text:
            entry[field] = text


# ---------------------------------------------------------------------------
# Parent chain
# ---------------------------------------------------------------------------


def _unknown_table(
    config: ServerConfig, auth_manager: AuthManager, table: str
) -> Optional[Dict[str, Any]]:
    """The shared verdict for a table whose catalog row did not come back."""
    resp = requests.Response()
    resp.status_code = 404
    exc = requests.exceptions.HTTPError("HTTP 404")
    exc.response = resp
    try:
        verdict = _read_failure_verdict(config, auth_manager, table, exc)
    except Exception:  # noqa: BLE001 - the verdict read is itself best effort
        verdict = None
    if verdict and "error" in verdict:
        return verdict
    return {
        "success": False,
        "error": "table_undetermined",
        "table": table,
        "availability": (verdict or {}).get("availability", "undetermined"),
        "because": (verdict or {}).get("because")
        or "sys_db_object returned no row for this name; it may be absent or unreadable",
    }


def _parent_chain(
    config: ServerConfig, auth_manager: AuthManager, table: str
) -> Tuple[List[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """``(parents nearest-first, refusal, chain_note)``.

    ``refusal`` is set when ``table`` itself is not in sys_db_object. ``chain_note``
    says why the chain stopped early (unreadable level, level cap).
    """
    rows, total, err = _page(
        config, auth_manager, "sys_db_object", f"name={table}", "name,super_class", 1, display=False
    )
    if err:
        return [], {"success": False, "error": "table_undetermined", **err}, None
    if not rows:
        return [], _unknown_table(config, auth_manager, table), None
    parents: List[str] = []
    nxt = _val(rows[0], "super_class")
    while nxt:
        if len(parents) >= _MAX_LEVELS:
            return (
                parents,
                None,
                {
                    "complete": False,
                    "because": f"parent chain cut at {_MAX_LEVELS} levels",
                },
            )
        prow, _t, perr = _page(
            config, auth_manager, "sys_db_object", f"sys_id={nxt}", "name,super_class", 1,
            display=False,
        )  # fmt: skip
        if perr or not prow:
            return (
                parents,
                None,
                {
                    "complete": False,
                    "because": (perr or {}).get("because", "parent class row not returned"),
                },
            )
        name = _val(prow[0], "name")
        if not name or name in parents:
            break
        parents.append(name)
        nxt = _val(prow[0], "super_class")
    return parents, None, None


# ---------------------------------------------------------------------------
# Categories: (table, column holding the target table, fields, extra query, builder)
# ---------------------------------------------------------------------------


def _fires_on(row: Dict[str, Any], flags: Dict[str, str]) -> List[str]:
    return [op for op, col in flags.items() if _flag(row, col)]


def _br_entry(row: Dict[str, Any], flags: Dict[str, str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": _val(row, "name"),
        "when": _val(row, "when"),
        "order": _order(row),
        "active": _flag(row, "active"),
        "fires_on": _fires_on(row, {**flags, "query": "action_query"}),
        "origin": _origin(row),
    }
    if _flag(row, "abort_action"):
        entry["abort_action"] = True
    _put(entry, row, "condition", "filter_condition")
    return entry


def _br_sort(e: Dict[str, Any]) -> Tuple[int, int]:
    return _WHEN_RANK.get(e["when"], 3), e["order"]


def _notif_entry(row: Dict[str, Any], flags: Dict[str, str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": _val(row, "name"),
        "active": _flag(row, "active"),
        "fires_on": _fires_on(row, flags),
        "origin": _origin(row),
    }
    _put(entry, row, "event_name", "type", "condition")
    return entry


def _wf_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry = {"name": _val(row, "name"), "order": _order(row), "origin": _origin(row)}
    _put(entry, row, "condition", "condition_type")
    return entry


def _csc_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry = {
        "name": _val(row, "name"),
        "type": _val(row, "type"),
        "order": _order(row),
        "active": _flag(row, "active"),
        "origin": _origin(row),
    }
    _put(entry, row, "ui_type", "condition")
    return entry


def _uip_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry = {
        "name": _val(row, "short_description"),
        "order": _order(row),
        "active": _flag(row, "active"),
        "origin": _origin(row),
    }
    _put(entry, row, "ui_type", "conditions")
    return entry


def _dp_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"name": _val(row, "short_description") or _val(row, "sys_id")}
    entry["active"] = _flag(row, "active")
    entry["origin"] = _origin(row)
    _put(entry, row, "conditions")
    return entry


def _sla_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": _val(row, "name"),
        "active": _flag(row, "active"),
        "origin": _origin(row),
    }
    _put(entry, row, "type", "start_condition", "stop_condition", "pause_condition")
    if _lab(row, "flow"):
        entry["flow"] = _lab(row, "flow")
    return entry


def _rule_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": _lab(row, "group") or _val(row, "sys_id"),
        "origin": _origin(row),
    }
    entry["active"] = _flag(row, "active")
    _put(entry, row, "condition")
    return entry


def _action_entry(row: Dict[str, Any], _f: Dict[str, str]) -> Dict[str, Any]:
    entry = {
        "name": _val(row, "name"),
        "order": _order(row),
        "active": _flag(row, "active"),
        "origin": _origin(row),
    }
    _put(entry, row, "action_name", "condition")
    if _flag(row, "client"):
        entry["client"] = True
    if _flag(row, "form_button"):
        entry["form_button"] = True
    return entry


# name -> (sn table, column naming the target table, fields, extra query, builder, order column,
#          flag columns usable as an operation filter or None)
_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "business_rules": {
        "table": "sys_script",
        "col": "collection",
        "fields": "name,when,order,active,condition,filter_condition,action_insert,"
        "action_update,action_delete,action_query,abort_action,collection",
        "flags": {
            "insert": "action_insert",
            "update": "action_update",
            "delete": "action_delete",
            "query": "action_query",
        },
        "build": _br_entry,
        "sort": _br_sort,
    },
    "legacy_workflows": {
        "table": "wf_workflow_version",
        "col": "table",
        "extra": "published=true",
        "fields": "name,table,condition,condition_type,order",
        "build": _wf_entry,
    },
    "client_scripts": {
        "table": "sys_script_client",
        "col": "table",
        "fields": "name,table,type,active,order,ui_type,condition",
        "build": _csc_entry,
    },
    "ui_policies": {
        "table": "sys_ui_policy",
        "col": "table",
        "extra": "sys_class_name=sys_ui_policy",  # catalog policies are another class
        "fields": "short_description,table,conditions,active,order,ui_type",
        "build": _uip_entry,
    },
    "data_policies": {
        "table": "sys_data_policy2",
        "col": "model_table",
        "fields": "short_description,model_table,conditions,active",
        "build": _dp_entry,
    },
    "notifications": {
        "table": "sysevent_email_action",
        "col": "collection",
        "fields": "name,collection,active,action_insert,action_update,event_name,condition,type",
        "flags": {"insert": "action_insert", "update": "action_update"},
        "build": _notif_entry,
    },
    "sla_definitions": {
        "table": "contract_sla",
        "col": "collection",
        "fields": "name,collection,active,type,start_condition,stop_condition,"
        "pause_condition,flow",
        "build": _sla_entry,
    },
    "assignment_rules": {
        "table": "sysrule_assignment",
        "col": "table",
        "fields": "table,condition,group,active",
        "build": _rule_entry,
    },
    "approval_rules": {
        "table": "sysrule_approvals",
        "col": "table",
        "fields": "table,condition,group,active",
        "build": _rule_entry,
    },
    "ui_actions": {
        "table": "sys_ui_action",
        "col": "table",
        "fields": "name,table,action_name,active,order,client,form_button,condition",
        "build": _action_entry,
    },
}
# Whether a row on a PARENT table runs for this table's records. Measured columns
# decide it where they exist; business rules and UI actions inherit by platform
# design; for the rest inheritance is not proven, so it is said, not assumed.
_INHERIT_FLAG = {
    "client_scripts": "applies_extended",
    "ui_policies": "inherit",
    "data_policies": "inherit",
}
_INHERITS_ALWAYS = {"business_rules", "ui_actions"}

_CATEGORY_ORDER = ("business_rules", "flow_triggers") + tuple(
    c for c in _CATEGORIES if c != "business_rules"
)


def _target(row: Dict[str, Any], col: str) -> str:
    return _val(row, col)


def _generic(
    config: ServerConfig,
    auth_manager: AuthManager,
    name: str,
    tables: List[str],
    operation: str,
    include_inactive: bool,
) -> Dict[str, Any]:
    spec = _CATEGORIES[name]
    col = spec["col"]
    flags: Dict[str, str] = spec.get("flags", {})
    parts = [f"{col}IN{','.join(tables)}"]
    if spec.get("extra"):
        parts.append(spec["extra"])
    if name == "legacy_workflows":
        parts.append("active=true")  # published AND active, per the measured shape
    elif not include_inactive:
        parts.append("active=true")
    if operation != "any" and flags:
        if operation not in flags:
            return {
                "checked": True,
                "not_applicable": f"{name} do not fire on {operation}",
                "total": 0,
                "complete": True,
                "rows": [],
            }
        parts.append(f"{flags[operation]}=true")
    extra_fields = [_INHERIT_FLAG[name]] if name in _INHERIT_FLAG else []
    fields = ",".join(dict.fromkeys(spec["fields"].split(",") + extra_fields + list(_ORIGIN)))
    rows, total, err = _page(
        config, auth_manager, spec["table"], "^".join(parts), fields, _ROW_CAP, orderby="order"
    )
    if err:
        return {"checked": False, "availability": err["availability"], "because": err["because"]}
    items = []
    not_inherited = 0
    for r in rows:
        entry = spec["build"](r, flags)
        src = _target(r, col)
        if src and src != tables[0]:
            entry["inherited_from"] = src
            if name in _INHERIT_FLAG:
                if not _flag(r, _INHERIT_FLAG[name]):
                    not_inherited += 1  # defined on a parent, but off for children
                    continue
            elif name not in _INHERITS_ALWAYS:
                entry["applies_here"] = "not_verified"
        items.append(entry)
    if "sort" in spec:
        items.sort(key=spec["sort"])
    out = {
        "checked": True,
        "total": total if total is not None else len(items),
        "complete": _complete(rows, total, _ROW_CAP),
        "rows": items,
    }
    if not_inherited:
        out["parent_rows_not_inherited"] = not_inherited
    return out


def _flow_triggers(
    config: ServerConfig,
    auth_manager: AuthManager,
    tables: List[str],
    operation: str,
    include_inactive: bool,
) -> Dict[str, Any]:
    parts = [f"tableIN{','.join(tables)}"]
    if operation in ("delete", "query"):
        return {
            "checked": True,
            "not_applicable": f"record-triggered flows fire on insert/update, not {operation}",
            "total": 0,
            "complete": True,
            "rows": [],
        }
    if operation == "insert":
        parts.append("on_insert=true")
    elif operation == "update":
        parts.append("on_update=true")
    rows, total, err = _page(
        config,
        auth_manager,
        "sys_flow_record_trigger",
        "^".join(parts),
        "sys_id,table,condition,on_insert,on_update,run_on_extended,run_flow_in",
        _ROW_CAP,
    )
    if err:
        return {"checked": False, "availability": err["availability"], "because": err["because"]}
    flows: Dict[str, Dict[str, Any]] = {}
    flow_err = None
    ids = sorted({_val(r, "sys_id") for r in rows if _val(r, "sys_id")})
    if ids:
        frows, _ft, flow_err = _page(
            config,
            auth_manager,
            "sys_hub_flow",
            "remote_trigger_idIN" + ",".join(ids),
            "sys_id,name,active,status,remote_trigger_id,sys_scope,sys_package",
            200,
        )
        for f in frows:
            flows[_val(f, "remote_trigger_id")] = f
    items = []
    not_inherited = 0
    for r in rows:
        flow = flows.get(_val(r, "sys_id"))
        if _val(r, "table") not in ("", tables[0]) and not _flag(r, "run_on_extended"):
            not_inherited += 1  # a parent-table trigger that does not run for child tables
            continue
        entry: Dict[str, Any] = {
            "fires_on": _fires_on(r, {"insert": "on_insert", "update": "on_update"}),
            "run_on_extended": _flag(r, "run_on_extended"),
        }
        src = _val(r, "table")
        if src and src != tables[0]:
            entry["inherited_from"] = src
        _put(entry, r, "condition", "run_flow_in")
        if flow is not None:
            if not include_inactive and not _flag(flow, "active"):
                continue
            entry["flow"] = {
                "name": _val(flow, "name"),
                "active": _flag(flow, "active"),
                "status": _val(flow, "status"),
            }
            entry["origin"] = _origin(flow)
        elif flow_err:
            entry["flow"] = {"checked": False, "because": flow_err["because"]}
        else:
            entry["flow"] = None  # trigger with no flow row pointing at it
        items.append(entry)
    out = {
        "checked": True,
        "total": total if total is not None else len(items),
        "complete": _complete(rows, total, _ROW_CAP),
        "rows": items,
    }
    if not_inherited:
        out["parent_rows_not_inherited"] = not_inherited
    return out


# ---------------------------------------------------------------------------
# Change management (only asked for on change_request and its children)
# ---------------------------------------------------------------------------

_CHANGE_TABLE = "change_request"
_CHANGE_ONLY = ("change_models", "approval_policies")
_POLICY_LINK_UNVERIFIED = (
    "chg_policy_approval has no table, model or condition column; which change a policy "
    "applies to is decided by its decision-table inputs (not read here) and recorded per "
    "change in chg_policy_applied. Treat 'applies_to' as unknown."
)


def _read_failed(err: Dict[str, Any]) -> Dict[str, Any]:
    return {"checked": False, "availability": err["availability"], "because": err["because"]}


def _change_models(
    config: ServerConfig, auth_manager: AuthManager, tables: List[str], include_inactive: bool
) -> Dict[str, Any]:
    parts = [f"table_nameIN{','.join(tables)}"]
    if not include_inactive:
        parts.append("active=true")
    fields = ",".join(
        dict.fromkeys(
            ["name", "table_name", "active", "default_change_model", "state_field", *_ORIGIN]
        )
    )
    rows, total, err = _page(
        config, auth_manager, "chg_model", "^".join(parts), fields, _ROW_CAP, orderby="name"
    )
    if err:
        return _read_failed(err)
    items = []
    for r in rows:
        entry: Dict[str, Any] = {
            "name": _val(r, "name"),
            "active": _flag(r, "active"),
            "default_change_model": _flag(r, "default_change_model"),
            "origin": _origin(r),
        }
        _put(entry, r, "state_field")
        if _val(r, "table_name") != tables[0]:
            entry["inherited_from"] = _val(r, "table_name")
        items.append(entry)
    return {
        "checked": True,
        "total": total if total is not None else len(items),
        "complete": _complete(rows, total, _ROW_CAP),
        "rows": items,
    }


def _approval_policies(
    config: ServerConfig, auth_manager: AuthManager, include_inactive: bool
) -> Dict[str, Any]:
    fields = ",".join(
        dict.fromkeys(["name", "label", "active", "execution", "answer_table", *_ORIGIN])
    )
    rows, total, err = _page(
        config,
        auth_manager,
        "chg_policy_approval",
        "" if include_inactive else "active=true",
        fields,
        _ROW_CAP,
        orderby="name",
    )
    if err:
        return _read_failed(err)
    items = []
    for r in rows:
        entry: Dict[str, Any] = {
            "name": _val(r, "name"),
            "active": _flag(r, "active"),
            "origin": _origin(r),
            "applies_to": "not_verified",
        }
        if _lab(r, "execution"):
            entry["execution"] = _lab(r, "execution")
        _put(entry, r, "label", "answer_table")
        items.append(entry)
    return {
        "checked": True,
        "total": total if total is not None else len(items),
        "complete": _complete(rows, total, _ROW_CAP),
        "not_verified": _POLICY_LINK_UNVERIFIED,
        "rows": items,
    }


# Form-side: they run in the browser on a form, not on the server's insert or
# update. A REQ inserted by the cart never meets them, and on one live table they
# were 22KB of a 54KB answer to "what runs on insert". Read for operation="any"
# or when named in categories.
_FORM_SIDE = ("client_scripts", "ui_policies", "ui_actions")
# Measured: 54KB for one table at operation=insert (44 BRs, 28 SLAs, 46 UI
# actions). Above this the largest categories give their rows up first —
# business rules last, they are the usual answer — and say how to ask for them.
_BUDGET = 24_000


def _size(obj: Any) -> int:
    import json

    return len(json.dumps(obj, ensure_ascii=False, default=str))


def _fit(out: Dict[str, Any], names: Tuple[str, ...], ask: str) -> None:
    """Withhold the rows of the biggest categories until the answer fits."""
    if _size(out) <= _BUDGET:
        return
    order = sorted(
        (n for n in names if isinstance(out.get(n), dict) and out[n].get("rows")),
        key=lambda n: (n == "business_rules", -_size(out[n]["rows"])),
    )
    for name in order:
        rows = out[name].pop("rows")
        out[name]["rows_withheld"] = {
            "count": len(rows),
            "bytes": _size(rows),
            "ask": f"{ask}, categories=['{name}'])",
        }
        if _size(out) <= _BUDGET:
            return


@register_tool(
    "get_table_automation",
    params=TableAutomationParams,
    description="What runs on a table's insert/update: rules, flows, workflows, policies, "
    "notifications, SLAs; change models and approval policies for change_request.",
    serialization="raw_dict",
    return_type=dict,
)
def get_table_automation(
    config: ServerConfig, auth_manager: AuthManager, params: TableAutomationParams
) -> Dict[str, Any]:
    table = (params.table or "").strip()
    operation = (params.operation or "any").strip().lower()
    if not table:
        return {"success": False, "error": "missing_table", "message": "table is required."}
    if operation not in _OPERATIONS:
        return {
            "success": False,
            "error": "bad_operation",
            "message": f"Unknown operation '{operation}'.",
            "valid_operations": list(_OPERATIONS),
        }

    parents: List[str] = []
    chain_note: Optional[Dict[str, Any]] = None
    if params.include_inherited:
        parents, refusal, chain_note = _parent_chain(config, auth_manager, table)
        if refusal:
            return refusal
    else:
        rows, _t, err = _page(
            config, auth_manager, "sys_db_object", f"name={table}", "name", 1, display=False
        )
        if err:
            return {"success": False, "error": "table_undetermined", **err}
        if not rows:
            return _unknown_table(config, auth_manager, table) or {}
    tables = [table] + parents
    names = _CATEGORY_ORDER + (_CHANGE_ONLY if _CHANGE_TABLE in tables else ())
    skipped: Dict[str, Dict[str, Any]] = {}
    if params.categories:
        wanted = {c.strip() for c in params.categories if c and c.strip()}
        unknown = sorted(wanted - set(names))
        if unknown:
            return {
                "success": False,
                "error": "unknown_categories",
                "unknown": unknown,
                "valid_categories": list(names),
            }
        names = tuple(n for n in names if n in wanted)
    elif operation != "any":
        for name in _FORM_SIDE:
            skipped[name] = {
                "checked": False,
                "not_read": f"form-side: runs in the browser, not on the server's {operation}",
            }
        names = tuple(n for n in names if n not in _FORM_SIDE)

    def run(name: str) -> Tuple[str, Dict[str, Any]]:
        try:
            if name == "change_models":
                out = _change_models(config, auth_manager, tables, params.include_inactive)
            elif name == "approval_policies":
                out = _approval_policies(config, auth_manager, params.include_inactive)
            elif name == "flow_triggers":
                out = _flow_triggers(
                    config, auth_manager, tables, operation, params.include_inactive
                )
            else:
                out = _generic(
                    config, auth_manager, name, tables, operation, params.include_inactive
                )
            return name, out
        except Exception as exc:  # noqa: BLE001 - a category never takes the call down
            logger.warning("get_table_automation %s failed: %s", name, exc)
            return name, {
                "checked": False,
                "availability": "undetermined",
                "because": f"{type(exc).__name__}: {str(exc)[:120]}",
            }

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = dict(pool.map(run, names))

    results.update(skipped)
    names = names + tuple(skipped)
    summary: Dict[str, Any] = {}
    for name in names:
        res = results[name]
        if name in skipped:
            summary[name] = "not_read"
        else:
            summary[name] = res["total"] if res.get("checked") else "unread"
    out: Dict[str, Any] = {
        "success": True,
        "table": table,
        "operation": operation,
        "tables_covered": tables,
        "summary": summary,
    }
    if chain_note:
        out["parent_chain"] = chain_note
    out.update({name: results[name] for name in names})
    if skipped:
        out["form_side_not_read"] = (
            f"client scripts, UI policies and UI actions act on a form, not on the server's "
            f"{operation}. For them: get_table_automation(table='{table}', operation="
            f"'{operation}', categories=[...])"
        )
    _fit(out, names, f"get_table_automation(table='{table}', operation='{operation}'")
    return out
