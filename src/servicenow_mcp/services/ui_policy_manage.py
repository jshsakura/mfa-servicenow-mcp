"""UI policy read/update/remove and catalog UI policies (catalog_ui_policy*).

Two kinds share one shape: ``form`` (sys_ui_policy / sys_ui_policy_action) and
``catalog`` (catalog_ui_policy / catalog_ui_policy_action, which inherits the
form tables). A catalog policy names variables as ``IO:<item_option_new sys_id>``
in ``catalog_conditions`` and ``catalog_variable``; callers speak variable NAMES
and this module translates, refusing any name it cannot resolve to exactly one
variable of the item (own variables plus attached sets via io_set_item).

Every refusal carries its reason. A read that could not complete is never
reported as "nothing found".
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import (
    build_create_preview,
    build_delete_preview,
    build_update_preview,
)
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

TABLES = {
    "form": ("sys_ui_policy", "sys_ui_policy_action"),
    "catalog": ("catalog_ui_policy", "catalog_ui_policy_action"),
}
TRISTATE = ("true", "false", "ignore")
_PAGE = 500
_PROTECTED_POLICIES = ("read", "protected")

_POLICY_FIELDS = {
    "form": "sys_id,short_description,table,conditions,active,order,on_load,reverse_if_false",
    "catalog": (
        "sys_id,short_description,catalog_item,variable_set,catalog_conditions,active,order,"
        "on_load,reverse_if_false,applies_catalog,applies_req_item,applies_sc_task,"
        "applies_target_record"
    ),
}
_ACTION_FIELDS = {
    "form": "sys_id,ui_policy,table,field,visible,mandatory,disabled,cleared",
    "catalog": (
        "sys_id,ui_policy,catalog_variable,variable,catalog_item,variable_set,order,"
        "mandatory,visible,disabled"
    ),
}
_ORIGIN = "sys_policy,sys_package,sys_scope"

# Segment: optional OR/NQ, then a lowercase variable name, then an operator.
_TERM = re.compile(
    r"^(?P<pre>OR|NQ)?(?P<name>[a-z][a-z0-9_]*?)"
    r"(?P<op>ISNOTEMPTY|ISEMPTY|NOTIN|IN|NOTLIKE|LIKE|STARTSWITH|ENDSWITH|BETWEEN|NSAMEAS|SAMEAS"
    r"|ANYTHING|VALCHANGES|CHANGES|DYNAMIC|ON|!=|>=|<=|=|>|<)(?P<rest>.*)$",
    re.S,
)


def _rv(v: Any) -> Any:
    return v.get("value") if isinstance(v, dict) else v


def _dv(v: Any) -> Any:
    return v.get("display_value") if isinstance(v, dict) else v


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _read(
    config: ServerConfig,
    auth: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = _PAGE,
    offset: int = 0,
    display: Any = False,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    return sn_query_page(
        config,
        auth,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        display_value=display,
        fail_silently=False,
    )


def tristate(value: Any) -> Optional[str]:
    """bool or 'true'/'false'/'ignore' -> platform string; None stays None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value).strip().lower()
    if s not in TRISTATE:
        raise ValueError(f"expected true, false or ignore — got {value!r}")
    return s


def _flag(value: Any) -> str:
    return str(bool(value)).lower() if isinstance(value, bool) else str(value)


# ---------------------------------------------------------------------------
# Protection
# ---------------------------------------------------------------------------


def protection_refusal(
    config: ServerConfig, auth: AuthManager, row: Dict[str, Any], label: str
) -> Optional[str]:
    """Reason a write to this record must be refused, or None when it is customer-owned.

    Heuristic for "customer": no package, or a package whose source is a scope
    ("x_...") or global. An unreadable package refuses (cannot prove ownership).
    """
    policy = str(_rv(row.get("sys_policy")) or "").strip().lower()
    if policy in _PROTECTED_POLICIES:
        return f"{label} is protected (sys_policy='{policy}') — an out-of-box record; not modified."
    pkg = _rv(row.get("sys_package"))
    if not pkg:
        return None
    try:
        rows, _ = _read(config, auth, "sys_package", f"sys_id={pkg}", "sys_id,name,source", 1)
    except Exception as exc:  # noqa: BLE001
        return (
            f"{label} belongs to package {pkg} but the package could not be read ({exc}); "
            "ownership unproven, so not modified."
        )
    if not rows:
        return f"{label} belongs to package {pkg} which could not be found; not modified."
    src = str(_rv(rows[0].get("source")) or "").strip().lower()
    name = str(_rv(rows[0].get("name")) or "").strip().lower()
    if src in ("", "global") or src.startswith("x_") or name == "global":
        return None
    return (
        f"{label} belongs to non-customer package '{_rv(rows[0].get('name'))}' "
        f"(source '{src}') — an out-of-box record; not modified."
    )


# ---------------------------------------------------------------------------
# Variables <-> IO:<sys_id>
# ---------------------------------------------------------------------------


def load_variables(
    config: ServerConfig,
    auth: AuthManager,
    *,
    catalog_item: Optional[str],
    variable_set: Optional[str],
) -> Tuple[List[Dict[str, Any]], bool]:
    """(variables, truncated) visible to a policy on this item / variable set. Raises on read failure."""
    truncated = False
    out: List[Dict[str, Any]] = []

    def pull(query: str, source: str) -> None:
        nonlocal truncated
        rows, _ = _read(config, auth, "item_option_new", query, "sys_id,name,question_text", _PAGE)
        if len(rows) >= _PAGE:
            truncated = True
        for r in rows:
            if _rv(r.get("name")):
                out.append(
                    {
                        "sys_id": _rv(r.get("sys_id")),
                        "name": _rv(r.get("name")),
                        "label": _rv(r.get("question_text")),
                        "source": source,
                    }
                )

    if catalog_item:
        pull(f"cat_item={catalog_item}", "item")
        links, _ = _read(
            config, auth, "io_set_item", f"sc_cat_item={catalog_item}", "variable_set", _PAGE
        )
        if len(links) >= _PAGE:
            truncated = True
        sets = sorted(
            {str(_rv(r.get("variable_set"))) for r in links if _rv(r.get("variable_set"))}
        )
        if sets:
            pull(f"variable_setIN{','.join(sets)}", "variable_set")
    elif variable_set:
        pull(f"variable_set={variable_set}", "variable_set")
    return out, truncated


def resolve_variable(
    name: str, variables: List[Dict[str, Any]], truncated: bool
) -> Tuple[Optional[str], Optional[str]]:
    """(sys_id, None) or (None, refusal). Exactly one variable may match."""
    ref = name[3:] if name.startswith("IO:") else name
    if re.fullmatch(r"[0-9a-f]{32}", ref):
        if any(v["sys_id"] == ref for v in variables):
            return ref, None
        return None, f"variable id {ref} is not a variable of this item/set."
    hits = {v["sys_id"]: v for v in variables if v["name"] == name}
    if len(hits) == 1:
        return next(iter(hits)), None
    note = (
        " (variable list was truncated at 500 — the name may exist beyond it)" if truncated else ""
    )
    if len(hits) > 1:
        cands = "; ".join(f"{k} ({v['source']})" for k, v in hits.items())
        return None, f"variable name '{name}' is ambiguous: {cands}. Pass the sys_id."
    known = ", ".join(sorted({v["name"] for v in variables})[:25]) or "none"
    return None, f"unknown variable '{name}'{note}. Known names: {known}."


def translate_conditions(
    cond: str, variables: List[Dict[str, Any]], truncated: bool
) -> Tuple[Optional[str], Optional[str]]:
    """Variable NAMES in an encoded query -> IO:<sys_id>. Refuses unknown names."""
    out: List[str] = []
    for seg in cond.split("^"):
        pre = re.match(r"(OR|NQ)?", seg).group(0)  # type: ignore[union-attr]
        rest = seg[len(pre) :]
        if (
            seg == ""
            or rest.startswith("IO:")
            or rest in ("EQ", "")
            or seg.startswith(("ORDERBY", "GROUPBY"))
        ):
            out.append(seg)
            continue
        m = _TERM.match(seg)
        if not m:
            return (
                None,
                f"cannot parse condition term '{seg}'; expected <variable name><operator><value>.",
            )
        sid, err = resolve_variable(m.group("name"), variables, truncated)
        if err:
            return None, err
        out.append(f"{m.group('pre') or ''}IO:{sid}{m.group('op')}{m.group('rest')}")
    return "^".join(out), None


def render_conditions(cond: str, variables: List[Dict[str, Any]]) -> str:
    names = {v["sys_id"]: v["name"] for v in variables}
    return re.sub(r"IO:([0-9a-f]{32})", lambda m: names.get(m.group(1), m.group(0)), cond or "")


# ---------------------------------------------------------------------------
# Record access
# ---------------------------------------------------------------------------


def _policy_row(
    config: ServerConfig, auth: AuthManager, kind: str, sys_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(row, failure). Fields come back raw; origin fields ride the same read."""
    table = TABLES[kind][0]
    try:
        rows, _ = _read(
            config, auth, table, f"sys_id={sys_id}", f"{_POLICY_FIELDS[kind]},{_ORIGIN}", 1
        )
    except Exception as exc:  # noqa: BLE001
        return None, _fail(f"Could not read {table} {sys_id}: {exc}")
    if not rows:
        return None, _fail(f"{table} not found: {sys_id}")
    return rows[0], None


def _action_row(
    config: ServerConfig, auth: AuthManager, kind: str, sys_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    table = TABLES[kind][1]
    try:
        rows, _ = _read(
            config, auth, table, f"sys_id={sys_id}", f"{_ACTION_FIELDS[kind]},{_ORIGIN}", 1
        )
    except Exception as exc:  # noqa: BLE001
        return None, _fail(f"Could not read {table} {sys_id}: {exc}")
    if not rows:
        return None, _fail(f"{table} not found: {sys_id}")
    return rows[0], None


def _vars_for_policy(
    config: ServerConfig, auth: AuthManager, policy: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], bool]:
    return load_variables(
        config,
        auth,
        catalog_item=_rv(policy.get("catalog_item")) or None,
        variable_set=_rv(policy.get("variable_set")) or None,
    )


def _send(
    config: ServerConfig,
    auth: AuthManager,
    method: str,
    table: str,
    sys_id: Optional[str],
    body: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{table}" + (f"/{sys_id}" if sys_id else "")
    try:
        kwargs: Dict[str, Any] = {"headers": auth.get_headers(), "timeout": 30}
        if body is not None:
            kwargs["json"] = body
        resp = auth.make_request(method, url, **kwargs)
        resp.raise_for_status()
        invalidate_query_cache(table=table)
        if method == "DELETE":
            return {"success": True}
        data = resp.json()
        if not isinstance(data, dict) or "result" not in data:
            return _fail(
                f"{method} {table} returned no record — the session may have expired; retry."
            )
        return {"success": True, "result": data["result"]}
    except Exception as exc:  # noqa: BLE001
        logger.error(f"{method} {table} failed: {exc}")
        return _fail(f"Error on {method} {table}: {exc}")


# ---------------------------------------------------------------------------
# list / get
# ---------------------------------------------------------------------------


def list_policies(
    config: ServerConfig, auth: AuthManager, kind: str, p: Dict[str, Any]
) -> Dict[str, Any]:
    table = TABLES[kind][0]
    parts: List[str] = []
    if kind == "form" and p.get("table"):
        parts.append(f"table={p['table']}")
    if kind == "catalog":
        for f in ("catalog_item", "variable_set"):
            if p.get(f):
                parts.append(f"{f}={p[f]}")
    if p.get("query"):
        parts.append(f"short_descriptionLIKE{p['query']}")
    if p.get("active") is not None:
        parts.append(f"active={str(bool(p['active'])).lower()}")
    query = "^".join(parts) + ("^" if parts else "") + "ORDERBYorder"
    limit = 1 if p.get("count_only") else max(1, min(int(p.get("limit") or 20), 100))
    try:
        rows, total = _read(
            config,
            auth,
            table,
            query,
            _POLICY_FIELDS[kind],
            limit,
            int(p.get("offset") or 0),
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"Could not list {table}: {exc}")
    if p.get("count_only"):
        return {"success": True, "kind": kind, "count": total if total is not None else len(rows)}
    out = [{k: _rv(v) for k, v in r.items()} for r in rows]
    result: Dict[str, Any] = {"success": True, "kind": kind, "count": len(out), "policies": out}
    if total is not None:
        result["total"] = total
    if kind == "catalog" and (p.get("catalog_item") or p.get("variable_set")):
        try:
            variables, _ = load_variables(
                config,
                auth,
                catalog_item=p.get("catalog_item"),
                variable_set=p.get("variable_set"),
            )
            for pol in out:
                readable = render_conditions(pol.get("catalog_conditions") or "", variables)
                if readable != (pol.get("catalog_conditions") or ""):
                    pol["conditions_readable"] = readable
        except Exception as exc:  # noqa: BLE001
            result["conditions_readable_error"] = f"variables not read, ids left as IO:<id>: {exc}"
    return result


def get_policy(
    config: ServerConfig, auth: AuthManager, kind: str, p: Dict[str, Any]
) -> Dict[str, Any]:
    row, fail = _policy_row(config, auth, kind, p["ui_policy"])
    if fail:
        return fail
    assert row is not None
    policy = {
        k: _rv(v) for k, v in row.items() if k not in ("sys_policy", "sys_package", "sys_scope")
    }
    policy["sys_policy"] = _rv(row.get("sys_policy"))
    action_table = TABLES[kind][1]
    try:
        acts, _ = _read(
            config,
            auth,
            action_table,
            (
                f"ui_policy={p['ui_policy']}^ORDERBYorder"
                if kind == "catalog"
                else f"ui_policy={p['ui_policy']}"
            ),
            _ACTION_FIELDS[kind],
            _PAGE,
            display="all" if kind == "catalog" else False,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"Policy read, but its actions could not be read: {exc}", policy=policy)
    result: Dict[str, Any] = {"success": True, "kind": kind, "policy": policy}
    if kind == "form":
        result["actions"] = [{k: _rv(v) for k, v in a.items()} for a in acts]
        return result
    actions = [
        {
            **{k: _rv(v) for k, v in a.items()},
            "variable_label": _dv(a.get("variable")) or _dv(a.get("catalog_variable")),
        }
        for a in acts
    ]
    try:
        variables, _ = _vars_for_policy(config, auth, row)
        names = {v["sys_id"]: v["name"] for v in variables}
        cond = policy.get("catalog_conditions") or ""
        readable = render_conditions(cond, variables)
        if readable != cond:
            policy["conditions_readable"] = readable
        for a in actions:
            ref = str(a.get("catalog_variable") or "")
            if ref.startswith("IO:") and ref[3:] in names:
                a["variable_name"] = names[ref[3:]]
    except Exception as exc:  # noqa: BLE001
        result["readable_error"] = f"variables not read, ids left as IO:<id>: {exc}"
    result["actions"] = actions
    return result


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def _policy_body(
    kind: str, p: Dict[str, Any], variables: Optional[List[Dict[str, Any]]], truncated: bool
) -> Tuple[Dict[str, Any], Optional[str]]:
    body: Dict[str, Any] = {}
    plain = [
        "short_description",
        "active",
        "order",
        "on_load",
        "reverse_if_false",
        "script_true",
        "script_false",
    ]
    if kind == "form":
        plain += ["conditions"]
        if p.get("global_policy") is not None:
            body["global"] = _flag(p["global_policy"])
        if p.get("view_name") is not None:
            body["view"] = p["view_name"]
    else:
        plain += ["applies_catalog", "applies_req_item", "applies_sc_task", "applies_target_record"]
        cond = p.get("catalog_conditions")
        if cond is not None:
            if cond.strip() == "":
                body["catalog_conditions"] = ""
            else:
                translated, err = translate_conditions(cond, variables or [], truncated)
                if err:
                    return {}, err
                body["catalog_conditions"] = translated
    for f in plain:
        if p.get(f) is not None:
            body[f] = _flag(p[f])
    return body, None


def create_catalog_policy(
    config: ServerConfig, auth: AuthManager, p: Dict[str, Any]
) -> Dict[str, Any]:
    item, vset = p.get("catalog_item"), p.get("variable_set")
    variables: List[Dict[str, Any]] = []
    truncated = False
    if p.get("catalog_conditions"):
        try:
            variables, truncated = load_variables(
                config, auth, catalog_item=item, variable_set=vset
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not read the variables to resolve conditions: {exc}")
    q = {**p, "active": True if p.get("active") is None else p["active"]}
    q["order"] = 100 if p.get("order") is None else p["order"]
    body, err = _policy_body("catalog", q, variables, truncated)
    if err:
        return _fail(f"Refused: {err}")
    body["catalog_item" if item else "variable_set"] = item or vset
    if p.get("dry_run"):
        return build_create_preview(table=TABLES["catalog"][0], proposed=body)
    sent = _send(config, auth, "POST", TABLES["catalog"][0], None, body)
    if not sent["success"]:
        return sent
    res = sent["result"]
    return {
        "success": True,
        "message": f"Created catalog UI policy: {res.get('short_description')}",
        "ui_policy_id": res.get("sys_id"),
        "catalog_conditions": body.get("catalog_conditions"),
    }


def _action_body(
    kind: str, p: Dict[str, Any], variables: List[Dict[str, Any]], truncated: bool
) -> Tuple[Dict[str, Any], Optional[str]]:
    body: Dict[str, Any] = {}
    for f in ("visible", "mandatory", "disabled"):
        v = tristate(p.get(f))
        if v is not None:
            body[f] = v
    if kind == "form":
        if p.get("cleared") is not None:
            body["cleared"] = _flag(p["cleared"])
    else:
        if p.get("order") is not None:
            body["order"] = str(p["order"])
        if p.get("variable"):
            sid, err = resolve_variable(p["variable"], variables, truncated)
            if err:
                return {}, err
            body["catalog_variable"] = f"IO:{sid}"
    return body, None


def add_catalog_action(
    config: ServerConfig, auth: AuthManager, p: Dict[str, Any]
) -> Dict[str, Any]:
    row, fail = _policy_row(config, auth, "catalog", p["ui_policy"])
    if fail:
        return fail
    assert row is not None
    refusal = protection_refusal(config, auth, row, f"catalog UI policy {p['ui_policy']}")
    if refusal:
        return _fail(f"Refused: {refusal}")
    try:
        variables, truncated = _vars_for_policy(config, auth, row)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"Could not read the policy's variables to resolve the name: {exc}")
    body, err = _action_body("catalog", p, variables, truncated)
    if err:
        return _fail(f"Refused: {err}")
    body["ui_policy"] = p["ui_policy"]
    for f in ("catalog_item", "variable_set"):
        if _rv(row.get(f)):
            body[f] = _rv(row.get(f))
    if p.get("dry_run"):
        return build_create_preview(table=TABLES["catalog"][1], proposed=body)
    sent = _send(config, auth, "POST", TABLES["catalog"][1], None, body)
    if not sent["success"]:
        return sent
    res = sent["result"]
    return {
        "success": True,
        "message": f"Created catalog UI policy action for variable '{p['variable']}'",
        "action_id": res.get("sys_id"),
        "ui_policy": p["ui_policy"],
        "catalog_variable": body["catalog_variable"],
    }


def update_policy(
    config: ServerConfig, auth: AuthManager, kind: str, p: Dict[str, Any]
) -> Dict[str, Any]:
    row, fail = _policy_row(config, auth, kind, p["ui_policy"])
    if fail:
        return fail
    assert row is not None
    refusal = protection_refusal(config, auth, row, f"UI policy {p['ui_policy']}")
    if refusal:
        return _fail(f"Refused: {refusal}")
    variables: List[Dict[str, Any]] = []
    truncated = False
    if kind == "catalog" and p.get("catalog_conditions"):
        try:
            variables, truncated = _vars_for_policy(config, auth, row)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not read the variables to resolve conditions: {exc}")
    body, err = _policy_body(kind, p, variables, truncated)
    if err:
        return _fail(f"Refused: {err}")
    if not body:
        return _fail("No fields to update.")
    table = TABLES[kind][0]
    if p.get("dry_run"):
        return build_update_preview(
            config,
            auth,
            table=table,
            sys_id=p["ui_policy"],
            proposed=body,
            identifier_fields=["short_description", "active"],
        )
    sent = _send(config, auth, "PATCH", table, p["ui_policy"], body)
    if not sent["success"]:
        return sent
    return {
        "success": True,
        "message": f"Updated UI policy: {sent['result'].get('short_description')}",
        "ui_policy_id": p["ui_policy"],
        "updated_fields": sorted(body),
    }


def _action_context(
    config: ServerConfig, auth: AuthManager, kind: str, action_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(action_row, parent_policy_row, failure) with protection already enforced."""
    arow, fail = _action_row(config, auth, kind, action_id)
    if fail:
        return None, None, fail
    assert arow is not None
    parent_id = _rv(arow.get("ui_policy"))
    prow, fail = _policy_row(config, auth, kind, str(parent_id))
    if fail:
        return None, None, fail
    assert prow is not None
    for label, rec in (
        (f"UI policy action {action_id}", arow),
        (f"its policy {parent_id}", prow),
    ):
        refusal = protection_refusal(config, auth, rec, label)
        if refusal:
            return None, None, _fail(f"Refused: {refusal}")
    return arow, prow, None


def update_action(
    config: ServerConfig, auth: AuthManager, kind: str, p: Dict[str, Any]
) -> Dict[str, Any]:
    arow, prow, fail = _action_context(config, auth, kind, p["action_id"])
    if fail:
        return fail
    assert prow is not None
    variables: List[Dict[str, Any]] = []
    truncated = False
    if kind == "catalog" and p.get("variable"):
        try:
            variables, truncated = _vars_for_policy(config, auth, prow)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not read the policy's variables to resolve the name: {exc}")
    body, err = _action_body(kind, p, variables, truncated)
    if err:
        return _fail(f"Refused: {err}")
    if not body:
        return _fail("No fields to update.")
    table = TABLES[kind][1]
    if p.get("dry_run"):
        return build_update_preview(
            config,
            auth,
            table=table,
            sys_id=p["action_id"],
            proposed=body,
            identifier_fields=["ui_policy", "field" if kind == "form" else "catalog_variable"],
        )
    sent = _send(config, auth, "PATCH", table, p["action_id"], body)
    if not sent["success"]:
        return sent
    return {
        "success": True,
        "message": "Updated UI policy action",
        "action_id": p["action_id"],
        "updated_fields": sorted(body),
    }


def remove_action(
    config: ServerConfig, auth: AuthManager, kind: str, p: Dict[str, Any]
) -> Dict[str, Any]:
    arow, _prow, fail = _action_context(config, auth, kind, p["action_id"])
    if fail:
        return fail
    assert arow is not None
    if p.get("ui_policy") and str(_rv(arow.get("ui_policy"))) != p["ui_policy"]:
        return _fail(
            f"Refused: action {p['action_id']} belongs to policy {_rv(arow.get('ui_policy'))}, "
            f"not {p['ui_policy']}."
        )
    table = TABLES[kind][1]
    if p.get("dry_run"):
        return build_delete_preview(
            config,
            auth,
            table=table,
            sys_id=p["action_id"],
            identifier_fields=["ui_policy", "field" if kind == "form" else "catalog_variable"],
        )
    sent = _send(config, auth, "DELETE", table, p["action_id"], None)
    if not sent["success"]:
        return sent
    return {
        "success": True,
        "message": f"Removed UI policy action {p['action_id']} (the policy itself is untouched)",
        "action_id": p["action_id"],
        "ui_policy": _rv(arow.get("ui_policy")),
    }
