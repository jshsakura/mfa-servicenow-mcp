"""Asset records (alm_asset and its classes): look up, create, update, transfer.

Built to run on an instance this code has never seen, so nothing about the
schema is assumed — every write is checked against the instance first, and a
check that cannot be completed refuses rather than guesses:

* the class must descend from alm_asset (read from sys_db_object);
* every column written must exist on that class (sys_dictionary, inherited
  columns included) — an unknown column is accepted and dropped by the Table
  API, and the write still answers 200;
* install_status and substatus resolve against the live sys_choice list, and a
  substatus must belong to its install_status (``dependent_value``);
* every reference (model, stockroom, user, location) is read before it is
  written: a sys_id that points at nothing is stored without complaint.

After a write the record the server returns is compared with what was sent.
Business rules on alm_asset can rewrite a field (state/substatus, stockroom,
the CI link); a field the server changed is reported, never presented as done.

Only base asset management is covered. Purchase-order receiving, audits and
disposal are plugin flows (Hardware Asset Management) and are not written here.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.query_fields import table_ancestry, table_columns

logger = logging.getLogger(__name__)

ASSET_TABLE = "alm_asset"
DEFAULT_CLASS = "alm_hardware"
MAX_TRANSFER_ASSETS = 50
ASSET_FIELDS = (
    "sys_id,sys_class_name,display_name,asset_tag,serial_number,model,model_category,"
    "install_status,substatus,stockroom,assigned_to,location,quantity,ci,sys_updated_on"
)
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")

# Reference columns written by this module → the table each must point into.
_REFERENCES = {
    "model": "cmdb_model",
    "model_category": "cmdb_model_category",
    "stockroom": "alm_stockroom",
    "assigned_to": "sys_user",
    "location": "cmn_location",
}


def _refuse(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message, **extra}


def _ref(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value") or ""
    return str(value or "").strip()


def _flat(row: Dict[str, Any]) -> Dict[str, Any]:
    """display_value=all rows → one value per field: "Label (raw)" when they differ."""
    out: Dict[str, Any] = {}
    for key, cell in row.items():
        if isinstance(cell, dict):
            raw, shown = str(cell.get("value") or ""), str(cell.get("display_value") or "")
            out[key] = shown if not raw or raw == shown else f"{shown} ({raw})"
        else:
            out[key] = cell
    return out


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = 2,
    display_value: Any = False,
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        display_value=display_value,
        no_count=True,
        fail_silently=False,
    )
    return rows


def find_assets(
    config: ServerConfig,
    auth_manager: AuthManager,
    identifier: str,
    *,
    fields: str = ASSET_FIELDS,
    display_value: Any = False,
) -> List[Dict[str, Any]]:
    """Rows matching a sys_id, asset_tag or serial_number (at most 2: enough to see a clash)."""
    ident = str(identifier).strip()
    if _SYS_ID.match(ident):
        query = f"sys_id={ident}"
    else:
        value = safe_value(ident).value
        query = f"asset_tag={value}^ORserial_number={value}"
    return _read(config, auth_manager, ASSET_TABLE, query, fields, 2, display_value)


def _resolve_one(
    config: ServerConfig, auth_manager: AuthManager, identifier: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    try:
        rows = find_assets(config, auth_manager, identifier)
    except Exception as e:
        return None, _refuse("ASSET_UNREADABLE", f"Could not read alm_asset: {e}")
    if not rows:
        return None, _refuse(
            "ASSET_NOT_FOUND", f"No asset with sys_id, tag or serial {identifier!r}."
        )
    if len(rows) > 1:
        return None, _refuse(
            "ASSET_AMBIGUOUS",
            f"{identifier!r} matches more than one asset (tag and serial). Pass the sys_id.",
            candidates=[r.get("sys_id") for r in rows],
        )
    return rows[0], None


def _check_columns(
    config: ServerConfig, auth_manager: AuthManager, table: str, names: List[str]
) -> Optional[Dict[str, Any]]:
    columns = table_columns(config, auth_manager, table)
    if columns is None:
        return _refuse(
            "SCHEMA_UNVERIFIED",
            f"Could not read the columns of {table}, so the write cannot be checked. "
            "Nothing was written.",
        )
    missing = sorted(n for n in names if n not in columns)
    if missing:
        return _refuse(
            "UNKNOWN_COLUMN",
            f"{table} on this instance has no column {', '.join(missing)}; the server would "
            "drop it silently. Nothing was written.",
        )
    return None


def _check_references(
    config: ServerConfig, auth_manager: AuthManager, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    for column, table in _REFERENCES.items():
        sys_id = data.get(column)
        if not sys_id:
            continue
        try:
            found = _read(
                config, auth_manager, table, f"sys_id={safe_value(sys_id).value}", "sys_id", 1
            )
        except Exception as e:
            return _refuse("REFERENCE_UNVERIFIED", f"Could not read {table} to check {column}: {e}")
        if not found:
            return _refuse(
                "REFERENCE_NOT_FOUND",
                f"{column}={sys_id} is not a {table} record on this instance. Nothing was written.",
            )
    return None


def _resolve_status(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    data: Dict[str, Any],
    current_status: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Resolve install_status, then substatus within it. Mutates ``data``."""
    if data.get("install_status") not in (None, ""):
        code, refusal = resolve_choice(
            config,
            auth_manager,
            table=table,
            element="install_status",
            requested=str(data["install_status"]),
        )
        if refusal is not None:
            return refusal
        data["install_status"] = code
    if data.get("substatus") not in (None, ""):
        parent = data.get("install_status") or current_status
        if not parent:
            return _refuse(
                "SUBSTATUS_NEEDS_STATUS",
                "substatus is only valid under an install_status; pass install_status too.",
            )
        code, refusal = resolve_choice(
            config,
            auth_manager,
            table=table,
            element="substatus",
            requested=str(data["substatus"]),
            depends_on=str(parent),
        )
        if refusal is not None:
            return refusal
        data["substatus"] = code
    return None


def _server_changes(sent: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Fields whose stored value is not what was sent (a business rule rewrote them)."""
    changed = {}
    for key, value in sent.items():
        if key not in result:
            continue
        stored = _ref(result.get(key))
        if stored != str(value):
            changed[key] = {"sent": value, "stored": stored}
    return changed


def get(config: ServerConfig, auth_manager: AuthManager, *, asset_id: str) -> Dict[str, Any]:
    try:
        rows = find_assets(config, auth_manager, asset_id, display_value="all")
    except Exception as e:
        return _refuse("ASSET_UNREADABLE", f"Could not read alm_asset: {e}")
    if not rows:
        return _refuse("ASSET_NOT_FOUND", f"No asset with sys_id, tag or serial {asset_id!r}.")
    assets = [_flat(r) for r in rows]
    if len(assets) > 1:
        return _refuse(
            "ASSET_AMBIGUOUS",
            f"{asset_id!r} matches more than one asset (tag and serial). Pass the sys_id.",
            candidates=assets,
        )
    return {"success": True, "asset": assets[0]}


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    model: str,
    asset_class: Optional[str] = None,
    model_category: Optional[str] = None,
    **fields: Any,
) -> Dict[str, Any]:
    table = asset_class or DEFAULT_CLASS
    ancestry = table_ancestry(config, auth_manager, table)
    if ancestry is None:
        return _refuse("SCHEMA_UNVERIFIED", f"Could not read the table hierarchy of {table}.")
    if ASSET_TABLE not in ancestry:
        return _refuse("NOT_AN_ASSET_CLASS", f"{table} does not extend alm_asset on this instance.")

    try:
        models = _read(
            config,
            auth_manager,
            "cmdb_model",
            f"sys_id={safe_value(model).value}",
            "sys_id,display_name,cmdb_model_category",
            1,
        )
    except Exception as e:
        return _refuse("REFERENCE_UNVERIFIED", f"Could not read cmdb_model: {e}")
    if not models:
        return _refuse("REFERENCE_NOT_FOUND", f"model={model} is not a cmdb_model record.")
    categories = [c for c in _ref(models[0].get("cmdb_model_category")).split(",") if c]
    if model_category:
        if categories and model_category not in categories:
            return _refuse(
                "MODEL_CATEGORY_MISMATCH",
                f"model_category {model_category} is not one of this model's categories: "
                f"{', '.join(categories)}.",
            )
    elif len(categories) == 1:
        model_category = categories[0]
    else:
        return _refuse(
            "MODEL_CATEGORY_REQUIRED",
            "alm_asset.model_category is mandatory and this model has "
            f"{len(categories) or 'no'} categories"
            + (f" ({', '.join(categories)})" if categories else "")
            + "; pass model_category.",
        )

    data: Dict[str, Any] = {"model": model, "model_category": model_category}
    data.update({k: v for k, v in fields.items() if v not in (None, "")})
    refusal = (
        _check_columns(config, auth_manager, table, list(data))
        or _resolve_status(config, auth_manager, table, data, None)
        or _check_references(config, auth_manager, data)
    )
    if refusal is not None:
        return refusal

    try:
        response = auth_manager.make_request(
            "POST",
            f"{config.instance_url}/api/now/table/{table}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {}) or {}
    except Exception as e:
        return _refuse("CREATE_FAILED", f"Creating the asset failed: {e}")
    invalidate_query_cache(table=ASSET_TABLE)
    invalidate_query_cache(table=table)
    answer: Dict[str, Any] = {
        "success": True,
        "asset_id": _ref(result.get("sys_id")),
        "table": table,
        "asset_tag": _ref(result.get("asset_tag")),
    }
    changed = _server_changes(data, result)
    if changed:
        answer["server_changed"] = changed
        answer["note"] = "The instance stored different values for these fields."
    return answer


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    asset_id: str,
    dry_run: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    row, refusal = _resolve_one(config, auth_manager, asset_id)
    if refusal is not None:
        return refusal
    assert row is not None
    sys_id = _ref(row.get("sys_id"))
    table = _ref(row.get("sys_class_name")) or ASSET_TABLE
    data = {k: v for k, v in fields.items() if v not in (None, "")}
    if not data:
        return _refuse("NOTHING_TO_UPDATE", "Pass at least one field to change.")
    refusal = (
        _check_columns(config, auth_manager, table, list(data))
        or _resolve_status(config, auth_manager, table, data, _ref(row.get("install_status")))
        or _check_references(config, auth_manager, data)
    )
    if refusal is not None:
        return refusal

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=table,
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["asset_tag", "display_name", "install_status"],
        )
    try:
        response = auth_manager.make_request(
            "PATCH",
            f"{config.instance_url}/api/now/table/{table}/{sys_id}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {}) or {}
    except Exception as e:
        return _refuse("UPDATE_FAILED", f"Updating the asset failed: {e}")
    invalidate_query_cache(table=ASSET_TABLE)
    invalidate_query_cache(table=table)
    answer: Dict[str, Any] = {"success": True, "asset_id": sys_id, "updated": sorted(data)}
    changed = _server_changes(data, result)
    if changed:
        answer["server_changed"] = changed
        answer["note"] = "The instance stored different values for these fields."
    return answer


def transfer(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    from_stockroom: str,
    to_stockroom: str,
    asset_ids: Optional[List[str]] = None,
    model: Optional[str] = None,
    quantity: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create a transfer order (alm_transfer_order) with one line per asset or one model line.

    The order's stages after this are the platform's own workflow; this only
    creates it, the way the form's Submit does.
    """
    if from_stockroom == to_stockroom:
        return _refuse("SAME_STOCKROOM", "Source and destination stockroom are the same.")
    refusal = _check_references(config, auth_manager, {"stockroom": from_stockroom}) or (
        _check_references(config, auth_manager, {"stockroom": to_stockroom})
    )
    if refusal is not None:
        return refusal

    lines: List[Dict[str, Any]] = []
    if asset_ids:
        if len(asset_ids) > MAX_TRANSFER_ASSETS:
            return _refuse("TOO_MANY_ASSETS", f"At most {MAX_TRANSFER_ASSETS} assets per call.")
        elsewhere = []
        for identifier in asset_ids:
            row, refusal = _resolve_one(config, auth_manager, identifier)
            if refusal is not None:
                return refusal
            assert row is not None
            if _ref(row.get("stockroom")) != from_stockroom:
                elsewhere.append(_ref(row.get("asset_tag")) or _ref(row.get("sys_id")))
                continue
            lines.append(
                {
                    "model": _ref(row.get("model")),
                    "asset": _ref(row.get("sys_id")),
                    "quantity_requested": 1,
                }
            )
        if elsewhere:
            return _refuse(
                "NOT_IN_SOURCE_STOCKROOM",
                f"Not in stockroom {from_stockroom}: {', '.join(elsewhere)}. Nothing was written.",
            )
    elif model and quantity and quantity > 0:
        refusal = _check_references(config, auth_manager, {"model": model})
        if refusal is not None:
            return refusal
        lines.append({"model": model, "quantity_requested": quantity})
    else:
        return _refuse("NOTHING_TO_TRANSFER", "Pass asset_ids, or model with a quantity above 0.")

    order = {
        "from_stockroom": from_stockroom,
        "to_stockroom": to_stockroom,
        "requested_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    for line in lines:
        line.update({"from_stockroom": from_stockroom, "to_stockroom": to_stockroom})
    refusal = _check_columns(config, auth_manager, "alm_transfer_order", list(order)) or (
        _check_columns(
            config,
            auth_manager,
            "alm_transfer_order_line",
            sorted({k for line in lines for k in line} | {"transfer_order"}),
        )
    )
    if refusal is not None:
        return refusal
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_create": {"alm_transfer_order": order, "alm_transfer_order_line": lines},
        }

    def _post(table: str, body: Dict[str, Any]) -> Dict[str, Any]:
        response = auth_manager.make_request(
            "POST",
            f"{config.instance_url}/api/now/table/{table}",
            json=body,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        return response.json().get("result", {}) or {}

    try:
        created = _post("alm_transfer_order", order)
    except Exception as e:
        return _refuse("CREATE_FAILED", f"Creating the transfer order failed: {e}")
    order_id = _ref(created.get("sys_id"))
    done: List[str] = []
    for index, line in enumerate(lines):
        try:
            result = _post("alm_transfer_order_line", {**line, "transfer_order": order_id})
        except Exception as e:
            invalidate_query_cache(table="alm_transfer_order")
            invalidate_query_cache(table="alm_transfer_order_line")
            return _refuse(
                "PARTIAL_TRANSFER",
                f"Transfer order {_ref(created.get('number'))} was created, but line "
                f"{index + 1} of {len(lines)} failed: {e}. {len(done)} line(s) exist; "
                "finish or cancel the order on the instance.",
                transfer_order_id=order_id,
                lines_created=done,
            )
        done.append(_ref(result.get("sys_id")))
    invalidate_query_cache(table="alm_transfer_order")
    invalidate_query_cache(table="alm_transfer_order_line")
    return {
        "success": True,
        "transfer_order_id": order_id,
        "number": _ref(created.get("number")),
        "stage": _ref(created.get("stage")),
        "lines_created": len(done),
    }
