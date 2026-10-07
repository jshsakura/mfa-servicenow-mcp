"""Scheduled Script Execution tools — the schedule of a sysauto_script job.

The script body already had a write path behind the sync gate; the schedule
around it (active, run type, time, day, interval, run-as) had none, so a
caller could change what a job does but not when it runs. ``get`` also reports
the scheduler's own next run (sys_trigger), so "did my change take?" is read,
not inferred from the form.
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import scheduled_job as _svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_SCHEDULE_FIELDS = frozenset(
    {
        "name",
        "active",
        "run_type",
        "run_time",
        "time_zone",
        "run_dayofweek",
        "run_dayofmonth",
        "run_period",
        "conditional",
        "condition",
        "run_as",
    }
)

# sys_choice for sysauto.run_type, read from a live instance.
RunType = Literal[
    "daily",
    "weekly",
    "monthly",
    "periodically",
    "once",
    "on_demand",
    "week_in_month",
    "day_and_month_in_year",
    "day_week_month_year",
    "business_calendar_start",
    "business_calendar_end",
]


class ManageScheduledJobParams(BaseModel):
    """Manage the schedule of Scheduled Script Executions — table: sysauto_script.

    Required per action:
      list:   (none)
      get:    sys_id
      update: sys_id, at least one schedule field
    """

    action: Literal["list", "get", "update"] = Field(...)

    sys_id: Optional[str] = Field(default=None, description="Scheduled job record (get/update)")
    query: Optional[str] = Field(default=None, description="Name search (list)")
    scope: Optional[str] = Field(default=None, description="App scope namespace filter (list)")
    active: Optional[bool] = Field(
        default=None, description="Active flag (filter on list, set on update)"
    )
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    count_only: bool = Field(default=False, description="Return count only")

    name: Optional[str] = Field(default=None, description="Job name")
    run_type: Optional[RunType] = Field(default=None, description="When it runs")
    run_time: Optional[str] = Field(
        default=None, description="HH:MM[:SS] in the job's time zone (as shown on the form)"
    )
    time_zone: Optional[str] = Field(default=None, description="IANA zone, e.g. Europe/Berlin")
    run_dayofweek: Optional[int] = Field(
        default=None, ge=1, le=7, description="1=Monday … 7=Sunday (weekly)"
    )
    run_dayofmonth: Optional[int] = Field(
        default=None, ge=1, le=31, description="Day of month (monthly)"
    )
    run_period: Optional[str] = Field(
        default=None, description="Repeat interval: HH:MM[:SS] or '<days>d HH:MM' (periodically)"
    )
    conditional: Optional[bool] = Field(default=None, description="Run only when condition passes")
    condition: Optional[str] = Field(default=None, description="Condition script")
    run_as: Optional[str] = Field(default=None, description="sys_user user_name or sys_id")
    expected_updated_on: Optional[str] = Field(
        default=None, description="sys_updated_on you read; blocks the write if the server moved"
    )
    dry_run: bool = Field(default=False, description="Preview the write without committing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"query", "scope", "active", "limit", "offset", "count_only"}),
        "get": frozenset({"sys_id"}),
        "update": _SCHEDULE_FIELDS | {"sys_id", "expected_updated_on", "dry_run"},
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageScheduledJobParams":
        if self.action in ("get", "update") and not self.sys_id:
            raise ValueError(f"sys_id is required for action='{self.action}'")
        if self.action == "update" and all(getattr(self, f) is None for f in _SCHEDULE_FIELDS):
            raise ValueError("at least one schedule field is required for action='update'")
        return self


@register_tool(
    name="manage_scheduled_job",
    params=ManageScheduledJobParams,
    description="Scheduled job schedule (sysauto_script): active, run type/time/day/interval, run-as + next run. Not the script.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_scheduled_job(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageScheduledJobParams,
) -> Dict[str, Any]:
    if params.action == "list":
        return _svc.list_jobs(
            config,
            auth_manager,
            query=params.query,
            scope=params.scope,
            active=params.active,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    assert params.sys_id is not None
    if params.action == "get":
        return _svc.get_job(config, auth_manager, sys_id=params.sys_id)
    return _svc.update_job(
        config,
        auth_manager,
        sys_id=params.sys_id,
        fields={f: getattr(params, f) for f in _SCHEDULE_FIELDS},
        expected_updated_on=params.expected_updated_on,
        dry_run=params.dry_run,
    )
