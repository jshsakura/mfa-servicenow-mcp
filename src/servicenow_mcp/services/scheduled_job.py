"""Scheduled Script Execution (sysauto_script) — the schedule, not the script.

The script body already has a write path (download → edit →
update_remote_from_local, or manage_portal_component update_code), behind the
sync gate. What had none was everything else on the form: active, run type,
time, day, interval, run-as. This owns those and never writes ``script``.

Two facts measured on a live instance shape the time handling:

* the form's "Time" is stored twice — ``entered_time`` as typed, in the job's
  ``time_zone``, and ``run_time`` in UTC (09:00 America/Phoenix is
  ``entered_time 1970-01-01 09:00:00`` / ``run_time 1970-01-01 16:00:00``).
  Writing one without the other leaves the form and the scheduler disagreeing,
  so a time is taken in the job's zone and both are written.
* durations are stored as an offset from the epoch: one day is
  ``1970-01-02 00:00:00``.

Every write is read back. A field the server did not keep is reported as
``not_applied`` — a 200 on the PATCH is not proof the schedule changed.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import count_response, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

JOB_TABLE = "sysauto_script"
TRIGGER_TABLE = "sys_trigger"
_JOB_FIELDS = (
    "sys_id,name,active,run_type,run_time,entered_time,time_zone,run_dayofweek,"
    "run_dayofmonth,run_period,run_start,conditional,condition,run_as,script,"
    "sys_scope,sys_mod_count,sys_updated_on"
)
_LIST_FIELDS = "sys_id,name,active,run_type,entered_time,time_zone,sys_scope,sys_updated_on"
_DAYS = {
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
    "7": "Sunday",
}
_EPOCH = datetime(1970, 1, 1)
_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_DURATION = re.compile(r"^(?:(\d+)\s*d?\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def _v(row: Dict[str, Any], field: str) -> str:
    val = row.get(field)
    if isinstance(val, dict):
        return str(val.get("value") or "")
    return str(val or "")


def _d(row: Dict[str, Any], field: str) -> str:
    val = row.get(field)
    if isinstance(val, dict):
        return str(val.get("display_value") or val.get("value") or "")
    return str(val or "")


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    *,
    limit: int = 1,
    offset: int = 0,
    orderby: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        display_value="all",
        orderby=orderby,
        fail_silently=False,
    )
    return rows


def _clock(raw: str) -> str:
    """'1970-01-01 09:00:00' -> '09:00:00'."""
    return raw.split(" ", 1)[1] if " " in raw else raw


def _duration_text(raw: str) -> str:
    """'1970-01-02 01:00:00' -> '1d 01:00:00' (offset from the epoch)."""
    try:
        delta = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S") - _EPOCH
    except ValueError:
        return raw
    hours, rem = divmod(delta.seconds, 3600)
    clock = f"{hours:02d}:{rem // 60:02d}:{rem % 60:02d}"
    return f"{delta.days}d {clock}" if delta.days else clock


def parse_clock(text: str) -> Optional[timedelta]:
    m = _TIME.match(text.strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59 or s > 59:
        return None
    return timedelta(hours=h, minutes=mi, seconds=s)


def parse_duration(text: str) -> Optional[str]:
    """'1:00' / '01:00:00' / '1d 00:00:00' / '2 06:00' -> epoch-offset raw value."""
    m = _DURATION.match(text.strip())
    if not m:
        return None
    days = int(m.group(1) or 0)
    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
    if mi > 59 or s > 59:
        return None
    return (_EPOCH + timedelta(days=days, hours=h, minutes=mi, seconds=s)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def utc_clock(local: timedelta, time_zone: str, when: Optional[datetime] = None) -> str:
    """Wall-clock time in *time_zone* -> the UTC wall-clock ServiceNow stores.

    Uses the zone's offset today (so a DST zone gets today's offset — what the
    form itself does when you save it). Raises ValueError for an unknown zone.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown time zone '{time_zone}'") from exc
    offset = (when or datetime.now(zone)).astimezone(zone).utcoffset() or timedelta(0)
    seconds = int((local - offset).total_seconds()) % 86400
    return f"1970-01-01 {seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _next_run(config: ServerConfig, auth_manager: AuthManager, sys_id: str) -> Dict[str, Any]:
    """The scheduler's own answer (sys_trigger), not one computed from the form."""
    try:
        rows = _read(
            config,
            auth_manager,
            TRIGGER_TABLE,
            f"document=sysauto_script^document_key={sys_id}",
            "next_action,state",
            limit=5,
            orderby="next_action",
        )
    except Exception as exc:
        return {"checked": False, "note": f"Could not read sys_trigger: {exc}"}
    if not rows:
        return {
            "checked": True,
            "scheduled": False,
            "note": "No sys_trigger row: the job is inactive, on demand, or not registered.",
        }
    first = rows[0]
    return {
        "checked": True,
        "scheduled": True,
        "next_action_utc": _v(first, "next_action"),
        "next_action_display": _d(first, "next_action"),
        "trigger_rows": len(rows),
    }


def _job_row(r: Dict[str, Any]) -> Dict[str, Any]:
    script = _v(r, "script")
    tz = _v(r, "time_zone")
    return {
        "sys_id": _v(r, "sys_id"),
        "name": _v(r, "name"),
        "active": _v(r, "active") == "true",
        "run_type": _v(r, "run_type"),
        "time": _clock(_v(r, "entered_time")) if tz and tz != "floating" else "",
        "time_zone": tz or "floating",
        "run_time_utc": _clock(_v(r, "run_time")),
        "run_dayofweek": _DAYS.get(_v(r, "run_dayofweek"), _v(r, "run_dayofweek")),
        "run_dayofmonth": _v(r, "run_dayofmonth"),
        "run_period": _duration_text(_v(r, "run_period")) if _v(r, "run_period") else "",
        "run_start_utc": _v(r, "run_start"),
        "conditional": _v(r, "conditional") == "true",
        "condition": _v(r, "condition"),
        "run_as": {"sys_id": _v(r, "run_as"), "name": _d(r, "run_as")},
        "scope": {"sys_id": _v(r, "sys_scope"), "name": _d(r, "sys_scope")},
        "script_chars": len(script),
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest() if script else "",
        "sys_mod_count": _v(r, "sys_mod_count"),
        "sys_updated_on": _v(r, "sys_updated_on"),
    }


def list_jobs(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    query: Optional[str] = None,
    scope: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    parts: List[str] = []
    if scope:
        parts.append(f"sys_scope.scope={scope}")
    if active is not None:
        parts.append(f"active={str(active).lower()}")
    if query:
        parts.append(f"nameLIKE{query}")
    query_string = "^".join(parts)
    if count_only:
        return count_response(config, auth_manager, JOB_TABLE, query_string, what="scheduled jobs")
    rows = _read(
        config,
        auth_manager,
        JOB_TABLE,
        query_string,
        _LIST_FIELDS,
        limit=min(limit, 50),
        offset=offset,
        orderby="name",
    )
    jobs = [
        {
            "sys_id": _v(r, "sys_id"),
            "name": _v(r, "name"),
            "active": _v(r, "active") == "true",
            "run_type": _v(r, "run_type"),
            "time": _clock(_v(r, "entered_time")),
            "time_zone": _v(r, "time_zone") or "floating",
            "scope": _d(r, "sys_scope"),
        }
        for r in rows
    ]
    return {"success": True, "jobs": jobs, "count": len(jobs), "limit": limit, "offset": offset}


def get_job(config: ServerConfig, auth_manager: AuthManager, *, sys_id: str) -> Dict[str, Any]:
    rows = _read(config, auth_manager, JOB_TABLE, f"sys_id={sys_id}", _JOB_FIELDS)
    if not rows:
        return {
            "success": False,
            "error": "not_found",
            "message": f"Scheduled job not found: {sys_id}",
        }
    return {
        "success": True,
        "job": _job_row(rows[0]),
        "next_run": _next_run(config, auth_manager, sys_id),
        "script_hint": (
            "The script body is edited through the sync path: download_server_sources"
            "(families=['admin']) → edit → update_remote_from_local, or "
            "manage_portal_component(action='update_code', table='sysauto_script', "
            "sys_id=..., update_data={'script': ...})."
        ),
    }


def _resolve_user(config: ServerConfig, auth_manager: AuthManager, user: str) -> Optional[str]:
    if len(user) == 32 and all(c in "0123456789abcdef" for c in user.lower()):
        return user
    rows = _read(config, auth_manager, "sys_user", f"user_name={user}", "sys_id")
    return _v(rows[0], "sys_id") if rows else None


def update_job(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sys_id: str,
    fields: Dict[str, Any],
    expected_updated_on: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    rows = _read(config, auth_manager, JOB_TABLE, f"sys_id={sys_id}", _JOB_FIELDS)
    if not rows:
        return {
            "success": False,
            "error": "not_found",
            "message": f"Scheduled job not found: {sys_id}",
        }
    current = rows[0]
    server_updated = _v(current, "sys_updated_on")
    if expected_updated_on and expected_updated_on.strip() != server_updated:
        return {
            "success": False,
            "error": "record_changed",
            "message": (
                f"The job changed after you read it (expected sys_updated_on "
                f"{expected_updated_on.strip()}, server now has {server_updated}). "
                "Nothing was written. Read it again first."
            ),
            "server_updated_on": server_updated,
        }

    body: Dict[str, Any] = {}
    for key in ("name", "active", "run_type", "conditional", "condition", "run_dayofmonth"):
        if fields.get(key) is not None:
            val = fields[key]
            body[key] = str(val).lower() if isinstance(val, bool) else val
    if fields.get("run_dayofweek") is not None:
        body["run_dayofweek"] = str(fields["run_dayofweek"])
    if fields.get("run_period") is not None:
        raw = parse_duration(str(fields["run_period"]))
        if raw is None:
            return {
                "success": False,
                "error": "invalid_run_period",
                "message": "run_period must look like 'HH:MM[:SS]' or '<days>d HH:MM[:SS]'.",
            }
        body["run_period"] = raw
    if fields.get("run_as") is not None:
        user_id = _resolve_user(config, auth_manager, str(fields["run_as"]))
        if not user_id:
            return {
                "success": False,
                "error": "unknown_user",
                "message": f"No sys_user with user_name '{fields['run_as']}'.",
            }
        body["run_as"] = user_id

    new_tz = fields.get("time_zone")
    if new_tz is not None:
        body["time_zone"] = new_tz
    if fields.get("run_time") is not None or new_tz is not None:
        tz = new_tz if new_tz is not None else (_v(current, "time_zone") or "floating")
        clock_text = fields.get("run_time") or _clock(_v(current, "entered_time"))
        local = parse_clock(str(clock_text))
        if local is None:
            return {
                "success": False,
                "error": "invalid_run_time",
                "message": "run_time must look like 'HH:MM' or 'HH:MM:SS' (24h).",
            }
        if tz == "floating":
            return {
                "success": False,
                "error": "time_zone_required",
                "message": (
                    "This job's time zone is 'floating', so a time cannot be converted to the "
                    "UTC value the scheduler runs on. Pass time_zone too (e.g. 'Europe/Berlin')."
                ),
            }
        try:
            body["run_time"] = utc_clock(local, tz)
        except ValueError as exc:
            return {"success": False, "error": "invalid_time_zone", "message": str(exc)}
        secs = int(local.total_seconds())
        body["entered_time"] = (
            f"1970-01-01 {secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
        )

    if not body:
        return {"success": True, "message": "No changes requested.", "sys_id": sys_id}

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=JOB_TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "run_type", "active"],
        )

    before = _job_row(current)
    url = f"{config.instance_url}/api/now/table/{JOB_TABLE}/{sys_id}"
    try:
        response = auth_manager.make_request(
            "PATCH", url, json=body, headers=auth_manager.get_headers(), timeout=30
        )
        response.raise_for_status()
    except Exception as e:
        logger.error("Error updating scheduled job %s: %s", sys_id, e)
        return {"success": False, "message": f"Error updating scheduled job: {e}"}
    invalidate_query_cache(table=JOB_TABLE)

    after_rows = _read(config, auth_manager, JOB_TABLE, f"sys_id={sys_id}", _JOB_FIELDS)
    if not after_rows:
        return {
            "success": False,
            "error": "not_verified",
            "message": "The update was sent but the job could not be read back.",
        }
    after = after_rows[0]
    not_applied = {
        k: {"sent": str(v), "server": _v(after, k)}
        for k, v in body.items()
        if str(v) != _v(after, k)
    }
    out: Dict[str, Any] = {
        "success": not not_applied,
        "message": (
            f"Updated scheduled job: {_v(after, 'name')}"
            if not not_applied
            else f"The server did not keep {len(not_applied)} field(s); see not_applied."
        ),
        "sys_id": sys_id,
        "before": before,
        "after": _job_row(after),
        "next_run": _next_run(config, auth_manager, sys_id),
    }
    if not_applied:
        out["error"] = "not_applied"
        out["not_applied"] = not_applied
    return out
