"""manage_data_update — bulk data updates the tool itself can prove before it writes.

The Background Script it replaces carried its own ``DRY_RUN`` flag, which only
the script could vouch for. Here ``preview`` is read-only by construction (it
is a read action, so it runs on read-only instances too), and ``apply`` writes
exactly the rows the preview showed or nothing. Every gate lives in
services/data_update.py and runs again on apply.
"""

from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import data_update as svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool


def _fit(config: ServerConfig, out: Dict[str, Any], name: str, rows: Any) -> Dict[str, Any]:
    """Bound what returns; when it had to be shortened, hand the user the whole list."""
    out = svc.fit(out)
    if "trimmed_note" in out:
        if rows is None and out.get("snapshot"):
            snap, _ = svc.load_snapshot(config.instance_url, out["snapshot"])
            rows = (snap or {}).get("rows")
        if rows:
            out.update(svc.write_review(config.instance_url, name, rows))
    return out


class ManageDataUpdateParams(BaseModel):
    action: Literal["preview", "apply", "list_snapshots", "preview_revert", "revert"] = Field(...)
    table: Optional[str] = Field(default=None, description="Data table (not sys_*, not config)")
    query: Optional[str] = Field(
        default=None, description="Encoded query selecting the rows; every field is checked"
    )
    set: Optional[Dict[str, Any]] = Field(
        default=None, description="field→value applied to every matched row (choice label ok)"
    )
    rows: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Per-row values instead of query+set: [{sys_id, field: value}]"
    )
    max_rows: int = Field(default=100, description="Refuse above this many rows (hard cap 1000)")
    confirm_whole_table: Optional[str] = Field(
        default=None, description="Table name, only when the condition really matches every row"
    )
    preview_token: Optional[str] = Field(
        default=None, description="apply/revert: preview_token from the preview you reviewed"
    )
    confirm_count: Optional[int] = Field(
        default=None, description="apply/revert: will_change from that preview"
    )
    snapshot: Optional[str] = Field(default=None, description="Snapshot id (preview_revert/revert)")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "preview": frozenset({"table", "query", "set", "rows", "max_rows", "confirm_whole_table"}),
        "apply": frozenset(
            {
                "table",
                "query",
                "set",
                "rows",
                "max_rows",
                "confirm_whole_table",
                "preview_token",
                "confirm_count",
            }
        ),
        "list_snapshots": frozenset(),
        "preview_revert": frozenset({"snapshot"}),
        "revert": frozenset({"snapshot", "preview_token", "confirm_count"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageDataUpdateParams":
        if self.action in ("preview", "apply"):
            if not self.table:
                raise ValueError(f"table is required for action='{self.action}'")
            if self.rows is None and not (self.query and self.set):
                raise ValueError("pass query+set, or rows")
        if self.action in ("preview_revert", "revert") and not self.snapshot:
            raise ValueError(f"snapshot is required for action='{self.action}'")
        if self.action in ("apply", "revert") and (
            not self.preview_token or self.confirm_count is None
        ):
            raise ValueError(
                f"{self.action} needs preview_token and confirm_count from the preview — "
                "run the preview first and show it to the user"
            )
        return self


def _gate_apply(
    plan: Dict[str, Any], params: ManageDataUpdateParams, preview_call: str
) -> Optional[Dict[str, Any]]:
    """The plan recomputed now must be the plan that was reviewed."""
    if plan["token"] != params.preview_token or len(plan["plan"]) != params.confirm_count:
        return {
            "success": False,
            "error": "PREVIEW_STALE",
            "message": (
                "The rows or their values are not what the preview showed (now "
                f"{len(plan['plan'])} row(s) would change, confirm_count was "
                f"{params.confirm_count}). Nothing was written. Preview again and show the "
                "user the new result."
            ),
            "preview_again": preview_call,
        }
    if not plan["plan"]:
        return {
            "success": False,
            "error": "NOTHING_TO_CHANGE",
            "message": "Every row already has the value. Nothing was written.",
        }
    return None


@register_tool(
    name="manage_data_update",
    params=ManageDataUpdateParams,
    description=(
        "Bulk-update data rows instead of a BG script: preview (read-only) → apply with its "
        "token+count; snapshot and revert."
    ),
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_data_update(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageDataUpdateParams,
) -> Dict[str, Any]:
    if params.action == "list_snapshots":
        return {"success": True, "snapshots": svc.list_snapshots(config.instance_url)}

    if params.action in ("preview", "apply"):
        assert params.table is not None
        plan = svc.build_plan(
            config,
            auth_manager,
            table=params.table,
            query=params.query if params.rows is None else None,
            set_values=params.set if params.rows is None else None,
            rows=params.rows,
            max_rows=params.max_rows,
            confirm_whole_table=params.confirm_whole_table,
        )
        if not plan.get("success"):
            return plan
        if params.action == "preview":
            view = svc.preview_view(plan)
            view["side_effects"] = svc.side_effects(
                config, auth_manager, plan["table"], plan["ancestry"]
            )
            view["not_predicted"] = (
                "Fields business rules change on save are not shown here — nothing was saved. "
                "apply reports them as also_changed; to see them first, apply one row via rows."
            )
            view["next"] = (
                "Show this to the user. Only on their go-ahead: manage_data_update("
                "action='apply', <same table/query/set or rows>, preview_token="
                f"'{plan['token']}', confirm_count={len(plan['plan'])}, confirm='approve')."
            )
            return _fit(config, view, f"preview-{plan['token']}", plan["plan"])
        refusal = _gate_apply(
            plan, params, "manage_data_update(action='preview', <same arguments>)"
        )
        if refusal:
            return refusal
        result = svc.execute(config, auth_manager, plan)
        return _fit(config, result, f"applied-{result.get('snapshot') or plan['token']}", None)

    assert params.snapshot is not None
    snap, refusal = svc.load_snapshot(config.instance_url, params.snapshot)
    if refusal:
        return refusal
    assert snap is not None
    plan = svc.build_revert_plan(config, auth_manager, snap)
    if not plan.get("success"):
        return plan
    if params.action == "preview_revert":
        view = svc.preview_view(plan)
        view["operation"] = "revert"
        view["snapshot"] = params.snapshot
        if plan["conflicts"]:
            view["changed_since"] = svc.brief(plan["conflicts"][:20])
            view["changed_since_count"] = len(plan["conflicts"])
            view["changed_since_note"] = (
                "Someone changed these rows after the update; they are NOT reverted (that "
                "would overwrite their change). Decide them one by one."
            )
        if plan["missing"]:
            view["missing"] = plan["missing"][:20]
        side = sorted({f for p in plan["plan"] for f in p.get("restore_side") or {}})
        if side:
            view["side_fields"] = side
            view["side_fields_note"] = (
                "The update also changed these through the server. A revert writes back only the "
                "sent fields; whether these return depends on the business rules, and the result "
                "says which did not."
            )
        view["next"] = (
            "Show this to the user. Only on their go-ahead: manage_data_update(action='revert', "
            f"snapshot='{params.snapshot}', preview_token='{plan['token']}', "
            f"confirm_count={len(plan['plan'])}, confirm='approve')."
        )
        return _fit(config, view, f"revert-preview-{plan['token']}", plan["plan"])
    refusal = _gate_apply(
        plan, params, f"manage_data_update(action='preview_revert', snapshot='{params.snapshot}')"
    )
    if refusal:
        return refusal
    result = svc.execute(config, auth_manager, plan, reverts=params.snapshot)
    if plan["conflicts"]:
        result["not_reverted_changed_since"] = len(plan["conflicts"])
    return _fit(config, result, f"reverted-{result.get('snapshot') or plan['token']}", None)
