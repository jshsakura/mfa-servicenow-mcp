"""Shared dry-run preview helpers for write tools.

Purpose: when a tool is called with dry_run=True, disclose the EXACT scope the
operation would touch before any side effect. Uses only Table API + Aggregate
API (read-only), so works under every auth type (basic/OAuth/API key/browser).

The returned dict follows a fixed schema so every tool's dry-run response has
the same shape and callers can reason about it uniformly:

    {
      "dry_run": true,
      "operation": "delete" | "update" | ...,
      "target": {"table": "...", "sys_id": "..."},
      "target_found": true|false,
      "target_record": { ...filtered fields... },       # delete: current state
      "proposed_changes": { "field": {"before": x, "after": y}, ... },  # update
      "no_op_fields": ["..."],                          # update: new == old
      "dependencies": {"activities": 12, "versions": 3},
      "warnings": ["..."],
      "precision_notes": {
        "count_source": "table_api",
        "dependency_check": true|false,
        "acl_checked": false
      }
    }

`precision_notes` is the integrity contract: it tells the user what this
preview actually verified vs. what it could not. Never omit it.
"""

from typing import Any, Dict, List, Mapping, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig


def _empty_precision_notes() -> Dict[str, Any]:
    return {
        "count_source": "table_api",
        "dependency_check": False,
        "acl_checked": False,
    }


def _fetch_target(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    sys_id: str,
    fields: List[str],
) -> Optional[Dict[str, Any]]:
    """Fetch single record by sys_id. Returns None if not found or error."""
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"sys_id={sys_id}",
            fields=",".join(fields),
            limit=1,
            offset=0,
            display_value=False,
            no_count=True,
        )
    except Exception:
        return None
    return rows[0] if rows else None


def build_delete_preview(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    sys_id: str,
    identifier_fields: Optional[List[str]] = None,
    dependency_checks: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Scope-disclosure preview for a delete operation.

    Args:
        table: target table (e.g. "wf_workflow").
        sys_id: target record sys_id.
        identifier_fields: extra fields to return (display-friendly identifiers).
        dependency_checks: each entry = {"table": ..., "field": ..., "label": ...}.
            A count-only query `{field}={sys_id}` is issued per entry so the
            user sees how many dependent rows will be cascade-deleted or orphaned.
    """
    preview: Dict[str, Any] = {
        "dry_run": True,
        "operation": "delete",
        "target": {"table": table, "sys_id": sys_id},
        "dependencies": {},
        "warnings": [],
        "precision_notes": _empty_precision_notes(),
    }
    preview["precision_notes"]["dependency_check"] = bool(dependency_checks)

    fetch_fields = ["sys_id", "sys_scope"] + list(identifier_fields or [])
    row = _fetch_target(config, auth_manager, table=table, sys_id=sys_id, fields=fetch_fields)
    if row is None:
        preview["target_found"] = False
        preview["warnings"].append(f"record not found in {table} (sys_id={sys_id})")
        return preview

    preview["target_found"] = True
    preview["target_record"] = {k: v for k, v in row.items() if v not in (None, "")}

    if dependency_checks:
        for dep in dependency_checks:
            dep_table = dep["table"]
            dep_field = dep["field"]
            label = dep.get("label", dep_table)
            try:
                count = sn_count(
                    config,
                    auth_manager,
                    table=dep_table,
                    query=f"{dep_field}={sys_id}",
                )
            except Exception as exc:
                preview["dependencies"][label] = None
                preview["warnings"].append(f"{label} count failed: {exc}")
                continue
            preview["dependencies"][label] = count
            if count > 0:
                preview["warnings"].append(
                    f"{count} {label} will be affected (cascade or orphaned)"
                )

    return preview


def build_update_preview(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    sys_id: str,
    proposed: Mapping[str, Any],
    identifier_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Scope-disclosure preview for an update operation.

    Fetches the current record and diffs each proposed field. Splits into
    `proposed_changes` (real diff) and `no_op_fields` (new == old).
    """
    preview: Dict[str, Any] = {
        "dry_run": True,
        "operation": "update",
        "target": {"table": table, "sys_id": sys_id},
        "proposed_changes": {},
        "no_op_fields": [],
        "warnings": [],
        "precision_notes": _empty_precision_notes(),
    }

    # Fetch enough fields to diff against
    diff_fields = list(proposed.keys())
    fetch_fields = ["sys_id", "sys_scope"] + list(identifier_fields or []) + diff_fields
    # dedupe while preserving order
    seen: set = set()
    fetch_fields = [f for f in fetch_fields if not (f in seen or seen.add(f))]

    row = _fetch_target(config, auth_manager, table=table, sys_id=sys_id, fields=fetch_fields)
    if row is None:
        preview["target_found"] = False
        preview["warnings"].append(f"record not found in {table} (sys_id={sys_id})")
        return preview

    preview["target_found"] = True
    preview["target_record"] = {
        k: row.get(k) for k in (identifier_fields or []) if row.get(k) not in (None, "")
    }

    for field, new_val in proposed.items():
        old_val = row.get(field)
        # Normalize to strings for comparison (SN API returns strings for most fields)
        old_str = "" if old_val is None else str(old_val)
        new_str = "" if new_val is None else str(new_val)
        if old_str == new_str:
            preview["no_op_fields"].append(field)
        else:
            preview["proposed_changes"][field] = {"before": old_val, "after": new_val}

    if preview["no_op_fields"]:
        preview["warnings"].append(
            f"{len(preview['no_op_fields'])} field(s) already match target value (no-op)"
        )
    if not preview["proposed_changes"]:
        preview["warnings"].append("no effective changes — all proposed values match current state")

    return preview
