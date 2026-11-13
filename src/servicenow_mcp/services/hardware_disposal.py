"""Hardware disposal orders (HAM Pro): create, add assets, run each stage, close tasks.

Measured end to end on a live instance (order → completed, asset → Retired /
Disposed, flow COMPLETE), not taken from docs:

* Inserting ``sn_hamp_hardware_disposal`` starts the "Hardware Asset Disposal
  flow", which opens one task at a time — verify, schedule, depart, confirm,
  documentation — and waits for each to close. Assets are rows of
  ``sn_hamp_m2m_hw_asset_disposal`` (stage draft → verified → in_transit →
  pending_certificate → completed). Orders, asset rows, order fields and task
  closing are plain records; their business rules and the flow do the rest.
* Verify / Depart / Dispose are Workspace declarative actions whose server
  script (``AssetAutomationAPI.completeAssetDisposalTask``) also moves the ASSET
  (Retired/pending disposal, In transit, Retired/disposed). That script is only
  reachable through the session endpoint the Workspace posts to,
  ``/api/now/ui/declarative_action/<assignment>``, so those three need browser
  auth. Writing the row's ``stage`` directly would skip the asset update.
* Closing a task the platform does not accept is NOT an error: the before rule
  (``HampHWDisposalUtils.checkTaskCompletion``) puts the state back and the
  Table API still answers 200. So the requirements are read before the close
  and the task is read again after it; a close is reported only when it held.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.asset import find_assets
from servicenow_mcp.tools.sn_api import _authenticated_user, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import AuthType, ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value

logger = logging.getLogger(__name__)

ORDER_TABLE = "sn_hamp_hardware_disposal"
ASSET_ROW_TABLE = "sn_hamp_m2m_hw_asset_disposal"
TASK_TABLE = "sn_hamp_hw_asset_disposal_task"
ACTION_TABLE = "sys_declarative_action_assignment"
TASK_ORDER = ("verify", "schedule", "depart", "confirm", "documentation")
MAX_ASSETS_PER_CALL = 50
MAX_ASSET_ROWS = 500
MAX_CERTIFICATE_BYTES = 20 * 1024 * 1024
NEXT_TASK_WAIT_S = 20.0
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_OPEN_TASK = ("1", "2")
# Stages from which the Workspace can still add or remove assets (its Add action).
_ADD_STAGES = ("draft", "scheduled", "in_transit")
# step → (declarative action_name, task that must be open, row stages it acts on, stage after)
STEPS: Dict[str, Tuple[str, str, Tuple[str, ...], Tuple[str, ...]]] = {
    "verify": ("verify", "verify", ("draft",), ("verified",)),
    "depart": ("depart", "depart", ("draft", "verified"), ("in_transit", "already_disposed")),
    "dispose": ("dispose", "documentation", ("pending_certificate",), ("completed",)),
}
ORDER_FIELDS = (
    "scheduled_date",
    "vendor",
    "vendor_order_id",
    "pickup_contact",
    "pickup_details",
    "carrier",
    "tracking_number",
    "shipped_to",
    "additional_info",
    "assigned_to",
)
_REFERENCES = {
    "vendor": "core_company",
    "carrier": "sn_itam_common_shipping_carrier",
    "shipped_to": "cmn_location",
    "assigned_to": "sys_user",
    "stockroom": "alm_stockroom",
    "location": "cmn_location",
}
_ORDER_FIELDS_READ = (
    "sys_id,number,stage,stockroom,location,assigned_to,scheduled_date,vendor,"
    "vendor_order_id,pickup_contact,certificate_of_disposal,tracking_number,carrier"
)


def _refuse(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message, **extra}


def _ref(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value") or ""
    return str(value or "").strip()


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = 100,
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


def _request(
    config: ServerConfig, auth_manager: AuthManager, method: str, path: str, **kw: Any
) -> Dict[str, Any]:
    headers = dict(auth_manager.get_headers())
    headers.update(kw.pop("headers", {}))
    response = auth_manager.make_request(
        method, f"{config.instance_url}{path}", headers=headers, timeout=config.timeout, **kw
    )
    response.raise_for_status()
    return response.json().get("result", {}) or {}


def _invalidate() -> None:
    for table in (ORDER_TABLE, ASSET_ROW_TABLE, TASK_TABLE, "alm_asset", "alm_hardware"):
        invalidate_query_cache(table=table)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _find_order(
    config: ServerConfig, auth_manager: AuthManager, order: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    ident = order.strip()
    column = "sys_id" if _SYS_ID.match(ident) else "number"
    try:
        rows = _read(
            config,
            auth_manager,
            ORDER_TABLE,
            f"{column}={safe_value(ident).value}",
            _ORDER_FIELDS_READ,
            2,
        )
    except Exception as e:
        return None, _refuse("ORDER_UNREADABLE", f"Could not read {ORDER_TABLE}: {e}")
    if not rows:
        return None, _refuse("ORDER_NOT_FOUND", f"No hardware disposal order {order!r}.")
    if len(rows) > 1:
        return None, _refuse("ORDER_AMBIGUOUS", f"{order!r} matches more than one order.")
    return rows[0], None


def _tasks(config: ServerConfig, auth_manager: AuthManager, order_id: str) -> List[Dict[str, Any]]:
    return _read(
        config,
        auth_manager,
        TASK_TABLE,
        f"hardware_disposal={order_id}^ORDERBYsys_created_on",
        "sys_id,number,task_name,state",
        20,
    )


def _asset_rows(
    config: ServerConfig, auth_manager: AuthManager, order_id: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """(rows, complete). A capped read must not be counted as the whole order."""
    rows = _read(
        config,
        auth_manager,
        ASSET_ROW_TABLE,
        f"hardware_disposal={order_id}^ORDERBYsys_created_on",
        "sys_id,stage,hardware,hardware.asset_tag,hardware.serial_number",
        MAX_ASSET_ROWS + 1,
    )
    return rows[:MAX_ASSET_ROWS], len(rows) <= MAX_ASSET_ROWS


def _open_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    open_tasks = [t for t in tasks if _ref(t.get("state")) in _OPEN_TASK]
    return open_tasks[-1] if open_tasks else None


def _stage_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        stage = _ref(row.get("stage"))
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _has_attachment(config: ServerConfig, auth_manager: AuthManager, task_id: str) -> bool:
    rows = _read(
        config,
        auth_manager,
        "sys_attachment",
        f"table_name={TASK_TABLE}^table_sys_id={task_id}",
        "sys_id",
        1,
    )
    return bool(rows)


def requirements(
    config: ServerConfig,
    auth_manager: AuthManager,
    order_row: Dict[str, Any],
    task: Dict[str, Any],
    rows: List[Dict[str, Any]],
    complete: bool,
) -> Dict[str, Any]:
    """What closing ``task`` needs, as HampHWDisposalUtils.checkTaskCompletion checks it.

    ``determined`` is False when the asset rows were capped: counting a partial
    list would answer a question about the whole order from part of it.
    """
    if not complete:
        return {
            "determined": False,
            "missing": [],
            "reason": f"over {MAX_ASSET_ROWS} asset rows; counts not complete",
        }
    counts = _stage_counts(rows)
    planned = sum(n for stage, n in counts.items() if stage != "cancelled")
    name = _ref(task.get("task_name"))
    missing: List[str] = []

    def need_fields(*fields: str) -> None:
        for field in fields:
            if not _ref(order_row.get(field)):
                missing.append(f"order field {field}")

    if planned == 0:
        missing.append("planned assets (add_assets)")
    elif name == "verify":
        if counts.get("verified", 0) == 0:
            missing.append("at least one verified asset (action=verify)")
    elif name == "schedule":
        need_fields("scheduled_date", "vendor")
    elif name == "depart":
        need_fields("scheduled_date", "vendor", "vendor_order_id", "pickup_contact")
        if counts.get("in_transit", 0) == 0:
            missing.append("at least one departed asset (action=depart)")
        if counts.get("verified", 0):
            missing.append(
                f"{counts['verified']} verified asset(s) still to depart or cancel (action=depart)"
            )
    elif name == "documentation":
        if not _has_attachment(config, auth_manager, _ref(task.get("sys_id"))):
            missing.append(
                "a disposal certificate attached to the task (action=attach_certificate)"
            )
        if _ref(order_row.get("certificate_of_disposal")) == "N":
            missing.append("certificate_of_disposal = Yes (action=attach_certificate)")
        if counts.get("completed", 0) == 0:
            missing.append("at least one disposed asset (action=dispose)")
        if counts.get("pending_certificate", 0):
            missing.append(
                f"{counts['pending_certificate']} asset(s) still to dispose (action=dispose)"
            )
    return {"determined": True, "task": name, "missing": missing}


def status(config: ServerConfig, auth_manager: AuthManager, *, order: str) -> Dict[str, Any]:
    row, refusal = _find_order(config, auth_manager, order)
    if refusal is not None:
        return refusal
    assert row is not None
    order_id = _ref(row.get("sys_id"))
    try:
        tasks = _tasks(config, auth_manager, order_id)
        rows, complete = _asset_rows(config, auth_manager, order_id)
    except Exception as e:
        return _refuse("ORDER_UNREADABLE", f"Could not read the order's tasks or assets: {e}")
    answer: Dict[str, Any] = {
        "success": True,
        "order": {k: _ref(v) for k, v in row.items()},
        "tasks": [
            {
                "number": _ref(t.get("number")),
                "task": _ref(t.get("task_name")),
                "state": _ref(t.get("state")),
            }
            for t in tasks
        ],
        "asset_stages": _stage_counts(rows),
        "assets": [
            {
                "row_id": _ref(r.get("sys_id")),
                "asset": _ref(r.get("hardware")),
                "asset_tag": _ref(r.get("hardware.asset_tag")),
                "serial_number": _ref(r.get("hardware.serial_number")),
                "stage": _ref(r.get("stage")),
            }
            for r in rows
        ],
        "assets_complete": complete,
    }
    task = _open_task(tasks)
    if task is None:
        stage = _ref(row.get("stage"))
        answer["open_task"] = None
        answer["note"] = (
            "No open task: the order is finished."
            if stage in ("completed", "cancelled")
            else "No open task yet; the disposal flow may not have created the next one. "
            "Read again shortly."
        )
        return answer
    answer["open_task"] = {"number": _ref(task.get("number")), "task": _ref(task.get("task_name"))}
    try:
        answer["to_close"] = requirements(config, auth_manager, row, task, rows, complete)
    except Exception as e:
        answer["to_close"] = {"determined": False, "missing": [], "reason": str(e)}
    return answer


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _check_reference(
    config: ServerConfig, auth_manager: AuthManager, column: str, value: str
) -> Optional[Dict[str, Any]]:
    table = _REFERENCES[column]
    try:
        found = _read(config, auth_manager, table, f"sys_id={safe_value(value).value}", "sys_id", 1)
    except Exception as e:
        return _refuse("REFERENCE_UNVERIFIED", f"Could not read {table} to check {column}: {e}")
    if not found:
        return _refuse("REFERENCE_NOT_FOUND", f"{column}={value} is not a {table} record.")
    return None


def _session_user(config: ServerConfig, auth_manager: AuthManager) -> str:
    name = _authenticated_user(config, auth_manager, allow_live=True)
    if not name:
        return ""
    try:
        rows = _read(
            config, auth_manager, "sys_user", f"user_name={safe_value(name).value}", "sys_id", 2
        )
    except Exception:
        return ""
    return _ref(rows[0].get("sys_id")) if len(rows) == 1 else ""


def _resolve_assets(
    config: ServerConfig, auth_manager: AuthManager, identifiers: List[str]
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if len(identifiers) > MAX_ASSETS_PER_CALL:
        return [], _refuse("TOO_MANY_ASSETS", f"At most {MAX_ASSETS_PER_CALL} assets per call.")
    resolved = []
    for ident in identifiers:
        try:
            rows = find_assets(config, auth_manager, ident)
        except Exception as e:
            return [], _refuse("ASSET_UNREADABLE", f"Could not read alm_asset: {e}")
        if len(rows) != 1:
            return [], _refuse(
                "ASSET_NOT_FOUND" if not rows else "ASSET_AMBIGUOUS",
                f"{ident!r} matches {len(rows)} assets; pass the sys_id. Nothing was written.",
            )
        resolved.append(rows[0])
    return resolved, None


def _add_rows(
    config: ServerConfig,
    auth_manager: AuthManager,
    order_id: str,
    assets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert one row per asset; the rules may refuse one (excluded, duplicate)."""
    results = []
    for asset in assets:
        asset_id = _ref(asset.get("sys_id"))
        entry = {"asset": asset_id, "asset_tag": _ref(asset.get("asset_tag"))}
        try:
            created = _request(
                config,
                auth_manager,
                "POST",
                f"/api/now/table/{ASSET_ROW_TABLE}",
                json={"hardware_disposal": order_id, "hardware": asset_id},
            )
            entry["row_id"] = _ref(created.get("sys_id"))
        except Exception as e:
            entry["error"] = str(e)
        results.append(entry)
    return results


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    stockroom: str,
    asset_ids: List[str],
    location: Optional[str] = None,
    assigned_to: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if not asset_ids:
        return _refuse(
            "NO_ASSETS", "Pass asset_ids: an order without assets cannot pass its first task."
        )
    refusal = _check_reference(config, auth_manager, "stockroom", stockroom)
    if refusal is not None:
        return refusal
    if not location:
        try:
            rooms = _read(
                config, auth_manager, "alm_stockroom", f"sys_id={stockroom}", "location", 1
            )
        except Exception as e:
            return _refuse("STOCKROOM_UNREADABLE", f"Could not read the stockroom: {e}")
        location = _ref(rooms[0].get("location")) if rooms else ""
        if not location:
            return _refuse("LOCATION_REQUIRED", "The stockroom has no location; pass location.")
    else:
        refusal = _check_reference(config, auth_manager, "location", location)
        if refusal is not None:
            return refusal
    owner = assigned_to or _session_user(config, auth_manager)
    if not owner:
        return _refuse(
            "ASSIGNED_TO_REQUIRED",
            "assigned_to is mandatory and the session user could not be resolved; pass it.",
        )
    if assigned_to:
        refusal = _check_reference(config, auth_manager, "assigned_to", assigned_to)
        if refusal is not None:
            return refusal
    assets, refusal = _resolve_assets(config, auth_manager, asset_ids)
    if refusal is not None:
        return refusal
    body = {"stockroom": stockroom, "location": location, "assigned_to": owner}
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_create": {
                ORDER_TABLE: body,
                ASSET_ROW_TABLE: [
                    _ref(a.get("asset_tag")) or _ref(a.get("sys_id")) for a in assets
                ],
            },
        }
    try:
        created = _request(config, auth_manager, "POST", f"/api/now/table/{ORDER_TABLE}", json=body)
    except Exception as e:
        return _refuse("CREATE_FAILED", f"Creating the disposal order failed: {e}")
    order_id = _ref(created.get("sys_id"))
    added = _add_rows(config, auth_manager, order_id, assets)
    _invalidate()
    answer = status(config, auth_manager, order=order_id)
    answer["added"] = added
    if any("error" in a for a in added):
        answer["success"] = False
        answer["message"] = "The order exists, but some assets were refused; see added."
    return answer


def add_assets(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    order: str,
    asset_ids: List[str],
    dry_run: bool = False,
) -> Dict[str, Any]:
    row, refusal = _find_order(config, auth_manager, order)
    if refusal is not None:
        return refusal
    assert row is not None
    stage = _ref(row.get("stage"))
    if stage not in _ADD_STAGES:
        return _refuse(
            "ORDER_CLOSED_TO_ASSETS", f"Assets can be added up to Transit; the order is {stage!r}."
        )
    if not asset_ids:
        return _refuse("NO_ASSETS", "Pass asset_ids.")
    assets, refusal = _resolve_assets(config, auth_manager, asset_ids)
    if refusal is not None:
        return refusal
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_add": [_ref(a.get("asset_tag")) or _ref(a.get("sys_id")) for a in assets],
        }
    added = _add_rows(config, auth_manager, _ref(row.get("sys_id")), assets)
    _invalidate()
    answer = status(config, auth_manager, order=_ref(row.get("sys_id")))
    answer["added"] = added
    if any("error" in a for a in added):
        answer["success"] = False
        answer["message"] = "Some assets were refused by the platform; see added."
    return answer


def _action_assignment(config: ServerConfig, auth_manager: AuthManager, action_name: str) -> str:
    rows = _read(
        config,
        auth_manager,
        ACTION_TABLE,
        f"active=true^table={ASSET_ROW_TABLE}^action_name={action_name}",
        "sys_id",
        3,
    )
    if len(rows) != 1:
        raise RuntimeError(f"{len(rows)} active '{action_name}' actions on {ASSET_ROW_TABLE}")
    return _ref(rows[0].get("sys_id"))


def run_step(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    step: str,
    order: str,
    asset_ids: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if config.auth.type != AuthType.BROWSER:
        return _refuse(
            "BROWSER_AUTH_REQUIRED",
            f"{step} runs the Workspace action's server script through a session endpoint; "
            "it needs browser auth. Writing the stage directly would skip the asset update.",
        )
    action_name, task_name, from_stages, to_stages = STEPS[step]
    row, refusal = _find_order(config, auth_manager, order)
    if refusal is not None:
        return refusal
    assert row is not None
    order_id = _ref(row.get("sys_id"))
    try:
        tasks = _tasks(config, auth_manager, order_id)
        rows, _ = _asset_rows(config, auth_manager, order_id)
    except Exception as e:
        return _refuse("ORDER_UNREADABLE", f"Could not read the order's tasks or assets: {e}")
    task = _open_task(tasks)
    if task is None or _ref(task.get("task_name")) != task_name:
        current = _ref(task.get("task_name")) if task else "none"
        return _refuse(
            "WRONG_TASK",
            f"{step} needs the '{task_name}' task open; the open task is {current!r}. "
            "Read the order (action=get) for the next step.",
        )
    wanted = None
    if asset_ids:
        assets, refusal = _resolve_assets(config, auth_manager, asset_ids)
        if refusal is not None:
            return refusal
        wanted = {_ref(a.get("sys_id")) for a in assets}
        absent = wanted - {_ref(r.get("hardware")) for r in rows}
        if absent:
            return _refuse("NOT_ON_ORDER", f"Not on this order: {', '.join(sorted(absent))}.")
    targets = [
        r
        for r in rows
        if _ref(r.get("stage")) in from_stages
        and (wanted is None or _ref(r.get("hardware")) in wanted)
    ]
    if not targets:
        return _refuse(
            "NOTHING_TO_DO",
            f"No asset on the order is in {', '.join(from_stages)}; {step} has nothing to act on.",
            asset_stages=_stage_counts(rows),
        )
    target_ids = [_ref(r.get("sys_id")) for r in targets]
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_act_on": [
                _ref(r.get("hardware.asset_tag")) or _ref(r.get("hardware")) for r in targets
            ],
        }
    try:
        assignment = _action_assignment(config, auth_manager, action_name)
    except Exception as e:
        return _refuse(
            "ACTION_UNRESOLVED", f"Could not find the Workspace '{action_name}' action: {e}"
        )
    body = {
        "sysIds": ",".join(target_ids),
        "query": f"hardware_disposal={order_id}",
        "selectionQuery": "sys_idIN" + ",".join(target_ids),
        "parentTable": TASK_TABLE,
        "parentRecordSysId": _ref(task.get("sys_id")),
    }
    try:
        _request(
            config,
            auth_manager,
            "POST",
            f"/api/now/ui/declarative_action/{assignment}",
            params={"sysparm_table": ASSET_ROW_TABLE},
            json=body,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        _invalidate()
        return _refuse(
            "STEP_UNCONFIRMED",
            f"The {step} call failed or answered unreadably ({e}); it may still have run. "
            "Read the order (action=get) before retrying.",
        )
    _invalidate()
    answer = status(config, auth_manager, order=order_id)
    after = {a["row_id"]: a for a in answer.get("assets", [])}
    moved: List[Dict[str, Any]] = []
    stuck: List[Dict[str, Any]] = []
    for row_id in target_ids:
        stage = (after.get(row_id) or {}).get("stage")
        (moved if stage in to_stages else stuck).append(
            {
                "row_id": row_id,
                "asset_tag": (after.get(row_id) or {}).get("asset_tag"),
                "stage": stage,
            }
        )
    answer["moved"] = moved
    if stuck:
        answer["success"] = False
        answer["not_moved"] = stuck
        answer["message"] = f"{len(stuck)} asset(s) did not reach {'/'.join(to_stages)}."
    return answer


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    order: str,
    fields: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    data = {k: v for k, v in fields.items() if v not in (None, "")}
    if not data:
        return _refuse("NOTHING_TO_UPDATE", "Pass at least one order field.")
    row, refusal = _find_order(config, auth_manager, order)
    if refusal is not None:
        return refusal
    assert row is not None
    for column, value in data.items():
        if column in _REFERENCES:
            refusal = _check_reference(config, auth_manager, column, str(value))
            if refusal is not None:
                return refusal
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_set": data,
        }
    order_id = _ref(row.get("sys_id"))
    try:
        result = _request(
            config, auth_manager, "PATCH", f"/api/now/table/{ORDER_TABLE}/{order_id}", json=data
        )
    except Exception as e:
        return _refuse("UPDATE_FAILED", f"Updating the order failed: {e}")
    _invalidate()
    changed = {
        k: {"sent": v, "stored": _ref(result.get(k))}
        for k, v in data.items()
        if k in result and _ref(result.get(k)) != str(v)
    }
    answer: Dict[str, Any] = {
        "success": not changed,
        "order": _ref(row.get("number")),
        "updated": sorted(data),
    }
    if changed:
        answer["server_changed"] = changed
        answer["message"] = "The instance stored different values for these fields."
    return answer


def attach_certificate(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    order: str,
    file_path: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    row, refusal = _find_order(config, auth_manager, order)
    if refusal is not None:
        return refusal
    assert row is not None
    order_id = _ref(row.get("sys_id"))
    try:
        task = _open_task(_tasks(config, auth_manager, order_id))
    except Exception as e:
        return _refuse("ORDER_UNREADABLE", f"Could not read the order's tasks: {e}")
    if task is None or _ref(task.get("task_name")) != "documentation":
        return _refuse(
            "WRONG_TASK",
            "The certificate goes on the open Disposal Documentation task; it is not open.",
        )
    path = os.path.expanduser(file_path)
    if not os.path.isfile(path):
        return _refuse("FILE_NOT_FOUND", f"No file at {file_path}.")
    size = os.path.getsize(path)
    if size == 0 or size > MAX_CERTIFICATE_BYTES:
        return _refuse(
            "BAD_FILE_SIZE", f"The file is {size} bytes; it must be 1..{MAX_CERTIFICATE_BYTES}."
        )
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_attach": {
                "task": _ref(task.get("number")),
                "file": os.path.basename(path),
                "bytes": size,
            },
            "would_set": {"certificate_of_disposal": "Y"},
        }
    with open(path, "rb") as handle:
        content = handle.read()
    try:
        attachment = _request(
            config,
            auth_manager,
            "POST",
            "/api/now/attachment/file",
            params={
                "table_name": TASK_TABLE,
                "table_sys_id": _ref(task.get("sys_id")),
                "file_name": os.path.basename(path),
            },
            data=content,
            headers={"Content-Type": "application/octet-stream"},
        )
    except Exception as e:
        return _refuse("ATTACH_FAILED", f"Uploading the certificate failed: {e}")
    result = update(config, auth_manager, order=order_id, fields={"certificate_of_disposal": "Y"})
    result["attachment_id"] = _ref(attachment.get("sys_id"))
    return result


def complete_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    order: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    row, refusal = _find_order(config, auth_manager, order)
    if refusal is not None:
        return refusal
    assert row is not None
    order_id = _ref(row.get("sys_id"))
    try:
        tasks = _tasks(config, auth_manager, order_id)
        rows, complete = _asset_rows(config, auth_manager, order_id)
    except Exception as e:
        return _refuse("ORDER_UNREADABLE", f"Could not read the order's tasks or assets: {e}")
    task = _open_task(tasks)
    if task is None:
        return _refuse("NO_OPEN_TASK", "The order has no open task.", stage=_ref(row.get("stage")))
    try:
        needs = requirements(config, auth_manager, row, task, rows, complete)
    except Exception as e:
        return _refuse("REQUIREMENTS_UNREAD", f"Could not read what closing the task needs: {e}")
    if not needs["determined"]:
        return _refuse("REQUIREMENTS_UNDETERMINED", needs.get("reason", ""), to_close=needs)
    if needs["missing"]:
        return _refuse(
            "TASK_NOT_READY",
            f"The '{needs['task']}' task cannot close yet: " + "; ".join(needs["missing"]) + ".",
            to_close=needs,
        )
    task_id = _ref(task.get("sys_id"))
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": "dry_run: nothing was written.",
            "would_close": _ref(task.get("number")),
        }
    known = {_ref(t.get("number")) for t in tasks}
    try:
        _request(
            config,
            auth_manager,
            "PATCH",
            f"/api/now/table/{TASK_TABLE}/{task_id}",
            json={"state": "3"},
        )
    except Exception as e:
        return _refuse("CLOSE_FAILED", f"Closing the task failed: {e}")
    _invalidate()
    try:
        after = _read(config, auth_manager, TASK_TABLE, f"sys_id={task_id}", "state", 1)
    except Exception as e:
        return _refuse("CLOSE_UNCONFIRMED", f"Closed, but the task could not be read back: {e}")
    if not after or _ref(after[0].get("state")) != "3":
        return _refuse(
            "TASK_NOT_CLOSED",
            "The platform put the task back (its completion rule refused the close). "
            "Read the order (action=get) for what it still needs.",
        )
    # The flow opens the next task in the background: a missing one is "not yet".
    deadline = time.monotonic() + NEXT_TASK_WAIT_S
    answer: Dict[str, Any] = {}
    while True:
        answer = status(config, auth_manager, order=order_id)
        new = [t for t in answer.get("tasks", []) if t.get("number") not in known]
        if new or answer.get("order", {}).get("stage") in ("completed", "cancelled"):
            break
        if time.monotonic() >= deadline:
            answer["note"] = (
                f"Closed. The next task was not visible after {NEXT_TASK_WAIT_S:.0f}s; the "
                "flow runs in the background, so read the order again before assuming it stopped."
            )
            break
        time.sleep(2)
    answer["closed"] = _ref(task.get("number"))
    return answer
