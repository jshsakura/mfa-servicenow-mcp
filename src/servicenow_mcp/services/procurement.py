"""Receive against a purchase order line through the Receive page's own server path.

Measured on a live instance. The Table API cannot do this: the field ACLs on
``proc_rec_slip_item.purchase_line`` / ``quantity`` and
``proc_rec_slip.purchase_order`` allow a write only while the field is empty and
do not let admin override, so an insert answers 200 with those fields DROPPED —
an empty receiving line, no assets, quantities unmoved. The Receive page avoids
that by running server script: it posts to ``/procurement_processor.do``
(``sysparm_processor=POReceiveManager``), which calls
``processPOReceiveWithParams`` with GlideRecord. This module calls the same two
processor functions the page does, so the platform does the receiving:

1. ``getPOItems`` — the receivable lines of the order as the page sees them,
   including the server's OWN verdict on mandatory identifiers
   (``is_serial_number_mandatory`` …, from ``AssetCMDBUtil``), the model type and
   any pre-created assets. Nothing about that is re-derived here.
2. ``processPOReceive`` — the line object from (1) with the quantity, stockroom,
   cost and per-unit details filled in the way ``ProcurementMobileHandler`` does.

Cost is the line's REFERENCE currency and amount (``fx_currency_instance``), as
``getReferenceCurrencyCode()``/``getReferenceValue()`` give the platform. The
Table API's ``cost`` is converted into the session's currency and would record a
different amount.

The processor is a session endpoint, so this needs browser auth. The answer is
what the server holds afterwards — the new receiving line(s), their assets, the
line's quantities — read back, never the request echoed.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import AuthType, ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value

logger = logging.getLogger(__name__)

PROCESSOR_PATH = "/procurement_processor.do"
MAX_RECEIVE_UNITS = 50
# Receiving lines already on a PO line, read before the receive so the new ones
# are told apart by set difference (no clock comparison between two machines).
MAX_PRIOR_LINES = 500
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_ASSET_FIELDS = (
    "sys_id,sys_class_name,asset_tag,serial_number,install_status,substatus,stockroom,"
    "reserved_for,receiving_line"
)
# Keys the page itself strips before sending (POReceiveManager.getBatchConfig).
_UNSENT_KEYS = (
    "discount",
    "errors",
    "ordered",
    "received_quantity",
    "remaining_quantity",
    "sys_created_by",
    "sys_created_on",
    "sys_domain",
    "sys_mod_count",
    "sys_updated_by",
    "sys_updated_on",
    "short_description",
)


def _refuse(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message, **extra}


def _ref(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value") or value.get("sys_id") or ""
    return str(value or "").strip()


def _int(value: Any) -> Optional[int]:
    try:
        return int(float(_ref(value)))
    except (TypeError, ValueError):
        return None


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int,
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        display_value=False,
        no_count=True,
        fail_silently=False,
    )
    return rows


def _processor(
    config: ServerConfig, auth_manager: AuthManager, name: str, params: Dict[str, str]
) -> Any:
    """Call POReceiveManager.<name> the way the page does.

    GET, measured: the same call as a form POST answers 200 with an EMPTY body
    and does nothing, so a POST "success" would be a read of nothing.
    """
    response = auth_manager.make_request(
        "GET",
        f"{config.instance_url}{PROCESSOR_PATH}",
        params={"sysparm_processor": "POReceiveManager", "sysparm_name": name, **params},
        headers=auth_manager.get_headers(),
        timeout=config.timeout,
    )
    response.raise_for_status()
    return json.loads(response.text)


def _find_line(
    config: ServerConfig, auth_manager: AuthManager, po_line: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    ident = po_line.strip()
    column = "sys_id" if _SYS_ID.match(ident) else "number"
    try:
        rows = _read(
            config,
            auth_manager,
            "proc_po_item",
            f"{column}={safe_value(ident).value}",
            "sys_id,number,status,remaining_quantity,purchase_order",
            2,
        )
    except Exception as e:
        return None, _refuse("PO_LINE_UNREADABLE", f"Could not read proc_po_item: {e}")
    if not rows:
        return None, _refuse("PO_LINE_NOT_FOUND", f"No purchase order line {po_line!r}.")
    if len(rows) > 1:
        return None, _refuse(
            "PO_LINE_AMBIGUOUS", f"{po_line!r} matches more than one line; pass the sys_id."
        )
    return rows[0], None


def _reference_cost(
    config: ServerConfig, auth_manager: AuthManager, line_id: str
) -> Tuple[Optional[str], Optional[str]]:
    """'CODE;amount' in the line's reference currency, or (None, why)."""
    try:
        rows = _read(
            config,
            auth_manager,
            "fx_currency_instance",
            f"table=proc_po_item^field=cost^id={line_id}",
            "reference_amount,reference_currency.code",
            2,
        )
    except Exception as e:
        return None, f"fx_currency_instance unreadable: {e}"
    if len(rows) != 1:
        return None, f"{len(rows)} currency rows for the line's cost"
    code = _ref(rows[0].get("reference_currency.code"))
    amount = _ref(rows[0].get("reference_amount"))
    if not code or not amount:
        return None, "the line's cost has no reference currency or amount"
    return f"{code};{amount}", None


def _identifiers_in_use(
    config: ServerConfig, auth_manager: AuthManager, column: str, values: List[str]
) -> Tuple[Optional[List[str]], Optional[str]]:
    if not values:
        return [], None
    query = f"{column}IN" + ",".join(safe_value(v).value for v in values)
    try:
        rows = _read(config, auth_manager, "alm_asset", query, column, len(values) + 1)
    except Exception as e:
        return None, str(e)
    return sorted({_ref(r.get(column)) for r in rows}), None


def _receiving_lines(config: ServerConfig, auth_manager: AuthManager, line_id: str) -> List[str]:
    rows = _read(
        config,
        auth_manager,
        "proc_rec_slip_item",
        f"purchase_line={line_id}",
        "sys_id",
        MAX_PRIOR_LINES + 1,
    )
    return [_ref(r.get("sys_id")) for r in rows]


def _clean_list(values: Optional[List[str]]) -> List[str]:
    return [str(v).strip() for v in (values or [])]


def receive(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    po_line: str,
    quantity: int,
    stockroom: Optional[str] = None,
    serial_numbers: Optional[List[str]] = None,
    asset_tags: Optional[List[str]] = None,
    requested_for: Optional[str] = None,
    reserve: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if config.auth.type != AuthType.BROWSER:
        return _refuse(
            "BROWSER_AUTH_REQUIRED",
            "Receiving runs through the Receive page's session endpoint; the Table API "
            "drops the line's fields by ACL. Use browser auth, or receive on the PO's "
            "Receive page.",
        )
    if quantity < 1 or quantity > MAX_RECEIVE_UNITS:
        return _refuse("BAD_QUANTITY", f"quantity must be 1..{MAX_RECEIVE_UNITS}.")
    serials = _clean_list(serial_numbers)
    tags = _clean_list(asset_tags)
    for label, values in (("serial_numbers", serials), ("asset_tags", tags)):
        if len(values) > quantity:
            return _refuse("TOO_MANY_IDENTIFIERS", f"{len(values)} {label} for {quantity} units.")
        given = [v for v in values if v]
        if len(given) != len(set(given)):
            return _refuse("DUPLICATE_IDENTIFIER", f"{label} repeats a value.")

    line, refusal = _find_line(config, auth_manager, po_line)
    if refusal is not None:
        return refusal
    assert line is not None
    line_id = _ref(line.get("sys_id"))
    line_number = _ref(line.get("number"))
    po_id = _ref(line.get("purchase_order"))
    if not po_id:
        return _refuse("NO_PURCHASE_ORDER", f"{line_number} is not on a purchase order.")

    # The page's own view of the line: receivable or not, and what it requires.
    try:
        items = _processor(config, auth_manager, "getPOItems", {"sysparm_po_sysid": po_id})
    except Exception as e:
        return _refuse(
            "RECEIVE_PAGE_UNREADABLE",
            f"Could not read the order through the Receive page's processor: {e}. "
            "Nothing was written.",
        )
    if not isinstance(items, list):
        return _refuse(
            "RECEIVE_PAGE_UNREADABLE",
            "The Receive page's processor did not answer with a line list (session expired, "
            "or a release that changed it). Nothing was written.",
        )
    item = next(
        (i for i in items if isinstance(i, dict) and _ref(i.get("sys_id")) == line_id), None
    )
    if item is None:
        return _refuse(
            "NOT_RECEIVABLE",
            f"The Receive page does not offer {line_number} (status {_ref(line.get('status'))!r}, "
            f"remaining {_ref(line.get('remaining_quantity')) or '?'}); it lists only open "
            "lines with something left to receive.",
        )
    model_type = _ref(item.get("item_model_type"))
    if model_type != "asset":
        return _refuse(
            "UNSUPPORTED_LINE_TYPE",
            f"{line_number} is a {model_type or 'unknown'} line. Only hardware (asset) lines "
            "are received here; software, consumable and bundle lines take inputs this tool "
            "does not send — use the Receive page.",
        )
    remaining = _int(item.get("remaining_quantity"))
    if remaining is None:
        return _refuse("REMAINING_UNKNOWN", f"No remaining quantity for {line_number}.")
    if quantity > remaining:
        return _refuse(
            "OVER_RECEIVE", f"{line_number} has {remaining} left to receive; asked {quantity}."
        )
    tracked = _ref((item.get("model") or {}).get("asset_tracking_strategy")) != "do_not_track"
    if not tracked and (serials or tags or reserve):
        return _refuse(
            "NOT_TRACKED",
            "The model is 'do not track': no asset is created, so serials, tags or a "
            "reservation have nothing to land on.",
        )
    if item.get("is_mac_address_mandatory") is True:
        return _refuse(
            "MAC_REQUIRED",
            "This instance requires a MAC address per unit for this model; receive it on "
            "the Receive page.",
        )
    required = [
        column
        for column, flag in (
            ("serial_number", "is_serial_number_mandatory"),
            ("asset_tag", "is_asset_tag_mandatory"),
        )
        if item.get(flag) is True
    ]
    supplied = {
        "serial_number": sum(1 for s in serials if s),
        "asset_tag": sum(1 for t in tags if t),
    }
    short = [c for c in required if supplied[c] < quantity]
    if short:
        return _refuse(
            "IDENTIFIER_REQUIRED",
            f"The Receive page requires {', '.join(short)} for every unit of {line_number}; "
            "pass one per unit. Nothing was written.",
        )
    precreated = item.get("pre_created_assets") or []
    if precreated and (serials or tags):
        return _refuse(
            "PRECREATED_ASSETS",
            f"{line_number} has {len(precreated)} pre-created asset(s); the Receive page "
            "picks among them for tagged units. Receive without serials/tags (the platform "
            "uses them in order), or use the page.",
        )
    for column, values in (("serial_number", serials), ("asset_tag", tags)):
        clash, error = _identifiers_in_use(config, auth_manager, column, [v for v in values if v])
        if error is not None:
            return _refuse("IDENTIFIER_CHECK_FAILED", f"Could not check {column}: {error}")
        if clash:
            return _refuse(
                "IDENTIFIER_IN_USE",
                f"{column} already on another asset: {', '.join(clash)}. Nothing was written.",
            )

    cost, why = _reference_cost(config, auth_manager, line_id)
    if cost is None:
        return _refuse(
            "COST_UNVERIFIED",
            f"Could not read the line's cost in its own currency ({why}); the receipt would "
            "record a wrong amount. Nothing was written.",
        )
    ship_to = (item.get("purchase_order") or {}).get("ship_to") or {}
    target_stockroom = (stockroom or _ref(ship_to)).strip()
    if not target_stockroom:
        return _refuse("STOCKROOM_REQUIRED", "The order has no ship-to; pass stockroom.")
    if stockroom:
        try:
            found = _read(
                config,
                auth_manager,
                "alm_stockroom",
                f"sys_id={safe_value(stockroom).value}",
                "sys_id",
                1,
            )
        except Exception as e:
            return _refuse("STOCKROOM_UNREADABLE", f"Could not read alm_stockroom: {e}")
        if not found:
            return _refuse("STOCKROOM_NOT_FOUND", f"Stockroom {stockroom} does not exist.")
    reserved_for = requested_for or _ref(item.get("requested_for"))

    pol = {k: v for k, v in item.items() if k not in _UNSENT_KEYS}
    pol.update(
        {
            "receive": True,
            "receiving_quantity": str(quantity),
            "reserved": bool(reserve),
            "cost_with_currency": cost,
            "ship_to": {"value": target_stockroom},
            "reserved_for": {"value": reserved_for or ""},
        }
    )
    if serials or tags:
        pol["assetTags"] = [
            {
                "asset_tag": tags[i] if i < len(tags) else "",
                "serial_number": serials[i] if i < len(serials) else "",
            }
            for i in range(quantity)
        ]
    plan = {
        "po_line": line_number,
        "purchase_order": _ref((item.get("purchase_order") or {}).get("number")),
        "quantity": quantity,
        "remaining_before": remaining,
        "stockroom": target_stockroom,
        "cost": cost,
        "reserved_for": reserved_for or None,
        "reserve": reserve,
        "required_by_page": required,
        "tracked": tracked,
    }
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "plan": plan,
        }

    try:
        before = set(_receiving_lines(config, auth_manager, line_id))
    except Exception as e:
        return _refuse("PRIOR_LINES_UNREADABLE", f"Could not read existing receipts: {e}")
    if len(before) > MAX_PRIOR_LINES:
        return _refuse(
            "TOO_MANY_PRIOR_RECEIPTS",
            f"{line_number} already has over {MAX_PRIOR_LINES} receiving lines, so the new "
            "one could not be told apart. Use the Receive page.",
        )
    try:
        response = _processor(
            config,
            auth_manager,
            "processPOReceive",
            {
                "sysparm_po_sysid": po_id,
                "sysparm_receivedata": json.dumps([pol]),
                "sysparm_batching": "none",
            },
        )
    except Exception as e:
        _invalidate()
        return _refuse(
            "RECEIVE_UNCONFIRMED",
            f"The receive call failed or its answer was unreadable ({e}). It may still have "
            f"run: read proc_rec_slip_item for purchase_line={line_id} before retrying.",
        )
    _invalidate()
    return _proof(config, auth_manager, line_id, before, quantity, remaining, plan, response)


def _invalidate() -> None:
    for table in ("proc_rec_slip", "proc_rec_slip_item", "proc_po_item", "proc_po", "alm_asset"):
        invalidate_query_cache(table=table)


def _proof(
    config: ServerConfig,
    auth_manager: AuthManager,
    line_id: str,
    before: set,
    quantity: int,
    remaining_before: int,
    plan: Dict[str, Any],
    response: Any,
) -> Dict[str, Any]:
    """Read back what the server holds now; the answer is this, not the request."""
    answer: Dict[str, Any] = {"plan": plan}
    warnings: List[str] = []
    failed = (response or {}).get("failedAssets") if isinstance(response, dict) else None
    if failed:
        answer["failed_assets"] = failed
        warnings.append("The platform rejected some units; see failed_assets.")
    try:
        new_lines = [s for s in _receiving_lines(config, auth_manager, line_id) if s not in before]
    except Exception as e:
        new_lines = None
        warnings.append(f"Receiving lines not re-read: {e}")
    answer["receiving_lines"] = new_lines
    assets: Optional[List[Dict[str, Any]]] = None
    if new_lines is not None and not new_lines:
        assets = []
    if new_lines:
        try:
            rows = _read(
                config,
                auth_manager,
                "alm_asset",
                "receiving_lineIN" + ",".join(new_lines) + "^ORDERBYsys_created_on",
                _ASSET_FIELDS,
                quantity + 1,
            )
            assets = [{k: _ref(v) for k, v in a.items()} for a in rows]
        except Exception as e:
            warnings.append(f"Assets not re-read: {e}")
    answer["assets"] = assets
    try:
        rows = _read(
            config,
            auth_manager,
            "proc_po_item",
            f"sys_id={line_id}",
            "status,received_quantity,remaining_quantity",
            1,
        )
        if rows:
            answer["po_line_after"] = {k: _ref(v) for k, v in rows[0].items()}
    except Exception as e:
        warnings.append(f"PO line not re-read: {e}")

    remaining_after = _int((answer.get("po_line_after") or {}).get("remaining_quantity"))
    received = new_lines is not None and len(new_lines) > 0
    if new_lines is not None and not new_lines:
        warnings.append("No new receiving line exists: nothing was received.")
    if remaining_after is not None and remaining_after != remaining_before - quantity:
        warnings.append(
            f"remaining_quantity is {remaining_after}, expected {remaining_before - quantity}."
        )
    expected_assets = quantity if plan.get("tracked", True) else 0
    if assets is not None and len(assets) != expected_assets:
        warnings.append(
            f"{len(assets)} asset(s) on the new receiving line(s) for {quantity} unit(s)."
        )
    answer["success"] = bool(received and not warnings)
    if warnings:
        answer["warnings"] = warnings
    return answer
