"""Service layer for portal component creation (widget, provider, header/footer, theme, template, ui_page)."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers (mirror portal_crud_tools._check_duplicate / _create_record)
# ---------------------------------------------------------------------------


def _check_duplicate(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    field: str,
    value: str,
    scope: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    query = f"{field}={value}"
    if scope:
        query += f"^sys_scope={scope}"
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=f"sys_id,{field},sys_scope",
            limit=1,
            offset=0,
            display_value=True,
        )
        return rows[0] if rows else None
    except Exception:
        return None


def _scope_id(value: Any) -> str:
    """Normalize a sys_scope reference (dict {value,link} or raw string) to a sys_id."""
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(value or "")


def _scope_info(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extra keys to merge into a create response: where the record actually landed."""
    info: Dict[str, Any] = {}
    if result.get("created_scope"):
        info["created_scope"] = result["created_scope"]
    if result.get("scope_warning"):
        info["scope_warning"] = result["scope_warning"]
    return info


def _create_record(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    body: Dict[str, Any],
    timeout: int = 30,
) -> Dict[str, Any]:
    # ServiceNow rejects an explicit sys_scope in the insert body as a privileged
    # cross-scope write (HTTP 403) even when it matches the caller's current app.
    # A new record's scope is assigned from the session's current application
    # instead — callers align that via manage_session_context before creating.
    # So strip sys_scope here, then report where the record actually landed so a
    # context mismatch is visible rather than silently writing to the wrong scope.
    requested_scope = _scope_id(body.pop("sys_scope", None))
    url = f"{config.instance_url}/api/now/table/{table}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=body,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return {"success": False, "message": f"No result in response for {table}"}
        invalidate_query_cache(table=table)
        record = data["result"]
        created_scope = _scope_id(record.get("sys_scope"))
        out: Dict[str, Any] = {"success": True, "result": record}
        if created_scope:
            out["created_scope"] = created_scope
        if requested_scope and created_scope and requested_scope != created_scope:
            out["scope_warning"] = (
                f"Requested scope '{requested_scope}' but the record landed in "
                f"'{created_scope}' (your current application). Set the target app "
                "first via manage_session_context (action=set_app), then retry."
            )
            logger.warning(
                "Created %s in scope %s, requested %s", table, created_scope, requested_scope
            )
        return out
    except Exception as e:
        logger.error("Error creating record in %s: %s", table, e)
        return {"success": False, "message": f"Error creating record in {table}: {e}"}


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def create_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    widget_id: Optional[str] = None,
    template: Optional[str] = None,
    css: Optional[str] = None,
    script: Optional[str] = None,
    client_script: Optional[str] = None,
    link: Optional[str] = None,
    internal: bool = False,
    data_table: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_widget", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"Widget with name '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
            "existing_scope": existing.get("sys_scope"),
        }
    if widget_id:
        existing_id = _check_duplicate(config, auth_manager, "sp_widget", "id", widget_id)
        if existing_id:
            return {
                "success": False,
                "message": f"Widget with id '{widget_id}' already exists.",
                "existing_sys_id": existing_id.get("sys_id"),
                "existing_scope": existing_id.get("sys_scope"),
            }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if widget_id:
        body["id"] = widget_id
    if template is not None:
        body["template"] = template
    if css is not None:
        body["css"] = css
    if script is not None:
        body["script"] = script
    if client_script is not None:
        body["client_script"] = client_script
    if link is not None:
        body["link"] = link
    if internal:
        body["internal"] = "true"
    if data_table:
        body["data_table"] = data_table
    if description:
        body["description"] = description

    result = _create_record(config, auth_manager, "sp_widget", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created widget: {record.get('name')}",
        **_scope_info(result),
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
        "name": record.get("name"),
    }


def create_angular_provider(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    script: str,
    scope: str,
    provider_type: str = "factory",
    description: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_angular_provider", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"Angular provider '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {
        "name": name,
        "script": script,
        "type": provider_type,
        "sys_scope": scope,
    }
    if description:
        body["description"] = description

    result = _create_record(config, auth_manager, "sp_angular_provider", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created angular provider: {record.get('name')}",
        **_scope_info(result),
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
        "type": record.get("type"),
    }


def create_header_footer(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    template: Optional[str] = None,
    css: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_header_footer", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"Header/footer '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if template is not None:
        body["template"] = template
    if css is not None:
        body["css"] = css

    result = _create_record(config, auth_manager, "sp_header_footer", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created header/footer: {record.get('name')}",
        **_scope_info(result),
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }


def create_css_theme(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    css: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_css", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"CSS theme '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if css is not None:
        body["css"] = css

    result = _create_record(config, auth_manager, "sp_css", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created CSS theme: {record.get('name')}",
        **_scope_info(result),
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }


def create_ng_template(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    template_id: str,
    template: str,
    scope: str,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_ng_template", "id", template_id, scope)
    if existing:
        return {
            "success": False,
            "message": f"ng-template with id '{template_id}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {
        "id": template_id,
        "template": template,
        "sys_scope": scope,
    }

    result = _create_record(config, auth_manager, "sp_ng_template", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created ng-template: {record.get('id')}",
        **_scope_info(result),
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
    }


def create_ui_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    html: Optional[str] = None,
    client_script: Optional[str] = None,
    processing_script: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sys_ui_page", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"UI page '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if html is not None:
        body["html"] = html
    if client_script is not None:
        body["client_script"] = client_script
    if processing_script is not None:
        body["processing_script"] = processing_script
    if description:
        body["description"] = description
    if category:
        body["category"] = category

    result = _create_record(config, auth_manager, "sys_ui_page", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created UI page: {record.get('name')}",
        **_scope_info(result),
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }


# ---------------------------------------------------------------------------
# Clone (widget / header-footer) — copy the code, reference the same relations
# ---------------------------------------------------------------------------

_SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Columns measured live on sp_widget / sp_header_footer. Copied: every code and
# config field. NOT copied: id/name (the caller picks them), sys_* (record
# identity), `servicenow` (the platform's own "shipped by ServiceNow" flag — a
# clone is not), and `docs` (a reference to the ORIGINAL's documentation record).
_CLONE_FIELDS = (
    "template",
    "script",
    "client_script",
    "link",
    "css",
    "option_schema",
    "demo_data",
    "data_table",
    "field_list",
    "controller_as",
    "public",
    "roles",
    "has_preview",
    "description",
    "category",
    "internal",
)
_CLONE_TABLES: Dict[str, Dict[str, Any]] = {
    "sp_widget": {"fields": _CLONE_FIELDS, "label": "widget"},
    "sp_header_footer": {"fields": _CLONE_FIELDS + ("static",), "label": "header/footer"},
}
# Relations a widget carries by reference. The clone points at the SAME
# dependency / provider records; it never copies them.
_DEPENDENCY_M2M = "m2m_sp_widget_dependency"
_DEPENDENCY_REF = "sp_dependency"
_PROVIDER_REF = "sp_angular_provider"
_M2M_PAGE = 500


def _norm(field: str, value: Any) -> Any:
    """Comparable form of a raw field value (CRLF, bool case, list order)."""
    if isinstance(value, dict):
        value = value.get("value", "")
    text = "" if value is None else str(value).replace("\r\n", "\n")
    if field in ("roles", "field_list"):
        return sorted(p for p in text.split(",") if p)
    if text in ("true", "false"):
        return text
    return text


def _read_all(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Read every matching row. Returns (rows, complete); raises when unreadable.

    ``complete`` is False when the page cap was hit with more rows behind it, so
    a caller never mistakes a capped list for the whole relation.
    """
    invalidate_query_cache(table=table)
    rows, total = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=_M2M_PAGE,
        offset=0,
        fail_silently=False,
    )
    if total is not None:
        return rows, len(rows) >= total
    return rows, len(rows) < _M2M_PAGE


def _ref_value(value: Any) -> str:
    return _scope_id(value)


def _resolve_clone_source(
    config: ServerConfig, auth_manager: AuthManager, table: str, source: str, fields: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(row, None) when exactly one record matches; (None, refusal) otherwise."""
    column = "sys_id" if _SYS_ID_RE.match(source) else "id"
    try:
        invalidate_query_cache(table=table)
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"{column}={source}",
            fields=f"sys_id,id,name,sys_scope,{fields}",
            limit=5,
            offset=0,
            fail_silently=False,
        )
    except Exception as e:
        return None, {"success": False, "message": f"Could not read the source {table}: {e}"}
    if len(rows) == 1:
        return rows[0], None
    candidates = [
        {
            "sys_id": r.get("sys_id"),
            "id": r.get("id"),
            "name": r.get("name"),
            "scope": _scope_id(r.get("sys_scope")),
        }
        for r in rows
    ]
    msg = (
        f"No {table} record with {column}='{source}'."
        if not rows
        else f"{len(rows)} {table} records match {column}='{source}'; pass the sys_id."
    )
    return None, {"success": False, "message": msg, "candidates": candidates}


def _relations(
    config: ServerConfig, auth_manager: AuthManager, widget_sys_id: str
) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[str]]:
    """Dependency + provider links of a widget: {kind: {table, ref, ids}}.

    Returns (None, reason) when either relation could not be read in full — a
    clone made from half-read relations would silently lack some.
    """
    from servicenow_mcp.tools.portal_dev_tools import resolve_angular_provider_m2m

    try:
        provider_table = resolve_angular_provider_m2m(config, auth_manager)
    except Exception as e:
        return None, f"Could not resolve the angular-provider link table: {e}"
    out: Dict[str, Dict[str, Any]] = {}
    for kind, table, ref in (
        ("dependency", _DEPENDENCY_M2M, _DEPENDENCY_REF),
        ("provider", provider_table, _PROVIDER_REF),
    ):
        try:
            rows, complete = _read_all(
                config, auth_manager, table, f"sp_widget={widget_sys_id}", ref
            )
        except Exception as e:
            return None, f"Could not read {table}: {e}"
        if not complete:
            return None, f"{table} has more than {_M2M_PAGE} rows for this widget; not cloning."
        ids = sorted({_ref_value(r.get(ref)) for r in rows} - {""})
        out[kind] = {"table": table, "ref": ref, "ids": ids}
    return out, None


def clone_component(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    source: str,
    new_id: str,
    name: str,
    scope: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    spec = _CLONE_TABLES[table]
    label = spec["label"]
    fields = ",".join(spec["fields"])

    row, refusal = _resolve_clone_source(config, auth_manager, table, source, fields)
    if refusal:
        return refusal
    assert row is not None
    source_sys_id = str(row.get("sys_id"))

    # The new id and name must be free. An unreadable check is a refusal: a
    # silent "nothing found" is how a duplicate id gets written.
    for column, value in (("id", new_id), ("name", name)):
        try:
            invalidate_query_cache(table=table)
            clash, _ = sn_query_page(
                config,
                auth_manager,
                table=table,
                query=f"{column}={value}" + (f"^sys_scope={scope}" if column == "name" else ""),
                fields="sys_id,id,name",
                limit=1,
                offset=0,
                fail_silently=False,
            )
        except Exception as e:
            return {"success": False, "message": f"Could not check {column} '{value}': {e}"}
        if clash:
            return {
                "success": False,
                "message": f"A {label} with {column} '{value}' already exists.",
                "existing_sys_id": clash[0].get("sys_id"),
            }

    relations: Dict[str, Dict[str, Any]] = {}
    if table == "sp_widget":
        found, why = _relations(config, auth_manager, source_sys_id)
        if found is None:
            return {"success": False, "message": why}
        relations = found

    body: Dict[str, Any] = {"id": new_id, "name": name, "sys_scope": scope}
    copied: List[str] = []
    empty: List[str] = []
    for f in spec["fields"]:
        v = row.get(f)
        v = v.get("value") if isinstance(v, dict) else v
        if v in (None, ""):
            empty.append(f)
            continue
        body[f] = v
        copied.append(f)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "operation": f"clone_{label.replace('/', '_')}",
            "source": {
                "sys_id": source_sys_id,
                "id": row.get("id"),
                "name": row.get("name"),
                "scope": _scope_id(row.get("sys_scope")),
            },
            "target": {"id": new_id, "name": name, "scope": scope},
            "would_copy_fields": copied,
            "empty_in_source": empty,
            "not_copied": ["docs", "servicenow", "sys_*"] if table == "sp_widget" else ["sys_*"],
            "would_create_m2m": {
                k: {"table": v["table"], "rows": len(v["ids"])} for k, v in relations.items()
            },
        }

    created = _create_record(config, auth_manager, table, body)
    if not created["success"]:
        return created
    record = created["result"]
    clone_sys_id = str(record.get("sys_id"))

    m2m_report: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for kind, rel in relations.items():
        errors: List[str] = []
        for ref_id in rel["ids"]:
            made = _create_record(
                config,
                auth_manager,
                rel["table"],
                {"sp_widget": clone_sys_id, rel["ref"]: ref_id},
            )
            if not made["success"]:
                errors.append(str(made.get("message")))
        # Prove by reading back, not by counting our own successful POSTs.
        try:
            rows, complete = _read_all(
                config, auth_manager, rel["table"], f"sp_widget={clone_sys_id}", rel["ref"]
            )
            have = {_ref_value(r.get(rel["ref"])) for r in rows} - {""}
            absent = sorted(set(rel["ids"]) - have)
            entry: Dict[str, Any] = {
                "table": rel["table"],
                "expected": len(rel["ids"]),
                "created": len(have & set(rel["ids"])),
                "missing_ids": absent,
                "verified": complete,
            }
            if not complete:
                missing.append(f"{kind}: read-back capped, links unverified")
        except Exception as e:
            entry = {
                "table": rel["table"],
                "expected": len(rel["ids"]),
                "created": None,
                "missing_ids": rel["ids"],
                "verified": False,
                "read_error": str(e),
            }
            missing.append(f"{kind}: could not read back ({e})")
        if errors:
            entry["errors"] = errors[:3]
        if entry["missing_ids"] and entry.get("verified"):
            missing.append(f"{kind}: {len(entry['missing_ids'])} of {entry['expected']} not linked")
        m2m_report[kind] = entry

    applied: Dict[str, bool] = {}
    try:
        invalidate_query_cache(table=table)
        back, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"sys_id={clone_sys_id}",
            fields=",".join(["id", "name", *copied]),
            limit=1,
            offset=0,
            fail_silently=False,
        )
        if not back:
            raise RuntimeError("clone not found on read-back")
        got = back[0]
        for f in ("id", "name"):
            expected = body[f]
            applied[f] = _norm(f, got.get(f)) == _norm(f, expected)
        for f in copied:
            applied[f] = _norm(f, got.get(f)) == _norm(f, body[f])
        not_applied = sorted(f for f, ok in applied.items() if not ok)
        if not_applied:
            missing.append(f"fields not applied: {', '.join(not_applied)}")
    except Exception as e:
        not_applied = []
        missing.append(f"clone could not be read back ({e}); fields unverified")

    if created.get("scope_warning"):
        missing.append("scope: " + str(created["scope_warning"]))

    complete = not missing
    return {
        "success": True,
        "complete": complete,
        "message": (
            f"Cloned {label} '{row.get('name')}' -> '{name}'"
            if complete
            else f"Cloned {label} but INCOMPLETE: " + "; ".join(missing)
        ),
        **_scope_info(created),
        "sys_id": clone_sys_id,
        "id": record.get("id"),
        "name": record.get("name"),
        "source_sys_id": source_sys_id,
        "applied": applied,
        "m2m": m2m_report,
        "missing": missing,
    }
