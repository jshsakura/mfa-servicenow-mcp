"""Write guards — block unsafe writes before they reach ServiceNow.

Design philosophy (v1.12.28.1): keep this lean.
Most "write safety" concerns are handled by:
  - ServiceNow session/ACL (user identity, update set selection)
  - The user's own discipline (which update set is current)
  - Existing confirm='approve' gate (action-level intent)

This layer adds only what the above can't catch:

  G3 — Concurrent-edit warning
       sn_write(update|delete) on a record edited by someone else within
       a configurable window. Blocks with a specific, actionable message.

  G8 — Concurrent-edit warning (generalized)
       Same protection for any other write tool that names its target via
       table + sys_id (update_portal_component, manage_portal_component, …) so
       a blind write can't silently overwrite someone else's concurrent edit.
       Conservative: fires only when table + sys_id are explicit. Both G3 and
       G8 share one window and can be disabled together via
       SERVICENOW_CONCURRENT_EDIT_GUARD=off.

  G6 — Flow Designer raw-write block
       sn_write to sys_hub_* tables (or sys_variable_value where
       document=sys_hub_*) corrupts flow snapshots. Force use of
       manage_flow_designer (checkout/save).

  G7 — Publish-class extra confirmation
       publish/commit/push tools require a separate confirm_publish='approve'
       beyond the regular confirm. Prevents accidental rollouts.

Removed (delegated to ServiceNow / session):
  G1, G2, G5 — Update set membership/size policing. Each user's session
               writes only to their own current update set. Self-management.

Deferred:
  G4 — Optimistic locking via sys_mod_count.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EditTarget:
    """How to find the record a manage_* tool writes to, for the audit fetch."""

    table: str
    id_arg: str  # argument key holding the record identifier
    update_actions: frozenset  # action values that edit an EXISTING record
    id_columns: Tuple[str, ...] = ("sys_id",)  # OR-matched columns for the id


# Registry of manage_* write tools that identify their target by a tool-specific
# id arg (not a generic table+sys_id). Only single-record update/delete actions
# on one known table are listed; ambiguous junction/multi-table actions (link,
# add_members, update_activity) and creates are deliberately omitted → fail-open.
_CONCURRENT_EDIT_REGISTRY: Dict[str, _EditTarget] = {
    "manage_incident": _EditTarget(
        "incident", "incident_id", frozenset({"update", "comment", "resolve"}), ("sys_id", "number")
    ),
    "manage_change": _EditTarget(
        "change_request", "change_id", frozenset({"update"}), ("sys_id", "number")
    ),
    "manage_changeset": _EditTarget("sys_update_set", "changeset_id", frozenset({"update"})),
    "manage_workflow": _EditTarget(
        "wf_workflow",
        "workflow_id",
        frozenset({"update", "activate", "deactivate", "delete"}),
    ),
    "manage_script_include": _EditTarget(
        "sys_script_include",
        "script_include_id",
        frozenset({"update", "delete"}),
        ("sys_id", "name"),
    ),
    "manage_user": _EditTarget("sys_user", "user_id", frozenset({"update"})),
    "manage_group": _EditTarget("sys_user_group", "group_id", frozenset({"update"})),
    "manage_flow_designer": _EditTarget("sys_hub_flow", "flow_id", frozenset({"update"})),
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_WRITE_GUARDS = "SERVICENOW_WRITE_GUARDS"  # master toggle ("off" disables all)
ENV_CONCURRENT_WINDOW_MIN = "SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN"
ENV_CONCURRENT_GUARD = "SERVICENOW_CONCURRENT_EDIT_GUARD"  # disables G3+G8 only
DEFAULT_CONCURRENT_WINDOW_MIN = 10

# G6 — tables that must only be written via scaffold tools.
FLOW_DESIGNER_INTERNAL_TABLES = frozenset(
    {
        "sys_hub_flow",
        "sys_hub_flow_base",
        "sys_hub_flow_snapshot",
        "sys_hub_flow_component",
        "sys_hub_flow_block",
        "sys_hub_action_instance",
        "sys_hub_action_instance_v2",
        "sys_hub_flow_logic",
        "sys_hub_flow_logic_instance_v2",
        "sys_hub_trigger_instance",
        "sys_hub_trigger_instance_v2",
        "sys_hub_sub_flow_instance",
        "sys_hub_sub_flow_instance_v2",
        "sys_hub_pill_compound",
        "sys_hub_snapshot",
        "sys_hub_snapshot_chunk",
        "sys_hub_action_plan",
        "sys_hub_action_plan_chunk",
    }
)

# G7 — publish-class tools requiring extra confirmation.
CONFIRM_PUBLISH_FIELD = "confirm_publish"
CONFIRM_PUBLISH_VALUE = "approve"

# tool_name → publish-class trigger condition. None=always publish-class.
# Otherwise dict of arg matches (all must match).
_PUBLISH_CLASS_TOOLS: Dict[str, Optional[Dict[str, Any]]] = {
    "publish_changeset": None,
    "commit_changeset": None,
    "update_remote_from_local": None,
    "approve_change": None,
    "submit_change_for_approval": None,
    "manage_changeset": {"action": ("publish", "commit")},
    "manage_flow_designer": {"action": ("save",), "publish": True},
}


# Read-only manage_X sub-actions (mirror of server.MANAGE_READ_ACTIONS).
# Duplicated here to avoid circular import; keep in sync.
_MANAGE_READ_ACTIONS: Dict[str, frozenset] = {
    "manage_incident": frozenset({"get"}),
    "manage_change": frozenset({"get"}),
    "manage_changeset": frozenset({"get"}),
    "manage_user": frozenset({"get", "list"}),
    "manage_group": frozenset({"list"}),
    "manage_workflow": frozenset({"list", "get", "list_versions", "get_activities"}),
    "manage_script_include": frozenset({"list", "get"}),
    "manage_widget_dependency": frozenset({"list", "get"}),
    "manage_catalog": frozenset(
        {"list_items", "get_item", "list_categories", "list_item_variables"}
    ),
    "manage_kb_article": frozenset({"list_kbs", "list_articles", "get_article", "list_categories"}),
    "manage_flow_designer": frozenset(
        {"list", "get_detail", "get_executions", "compare", "edit_status"}
    ),
    "manage_project": frozenset({"list"}),
    "manage_epic": frozenset({"list"}),
    "manage_scrum_task": frozenset({"list"}),
    "manage_story": frozenset({"list", "list_dependencies"}),
}


# ---------------------------------------------------------------------------
# Exception + context
# ---------------------------------------------------------------------------


class PolicyViolation(ValueError):
    """Raised when a write guard blocks an action."""

    def __init__(self, guard: str, message: str):
        self.guard = guard
        super().__init__(f"[{guard}] {message}")


class WriteGuardContext:
    """Per-call context — holds server, tool, args; caches lookups."""

    def __init__(self, server: Any, tool_name: str, arguments: Dict[str, Any]):
        self.server = server
        self.tool_name = tool_name
        self.arguments = arguments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guards_enabled() -> bool:
    return os.getenv(ENV_WRITE_GUARDS, "on").lower() not in ("off", "false", "0", "no")


def _concurrent_guard_enabled() -> bool:
    """Targeted off-switch for concurrent-edit detection (G3 + G8), leaving the
    flow-designer (G6) and publish (G7) guards intact."""
    return os.getenv(ENV_CONCURRENT_GUARD, "on").lower() not in ("off", "false", "0", "no")


def _is_read_only(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """True if this call doesn't mutate ServiceNow data."""
    if tool_name in {"sn_write", "sn_batch"}:
        return False
    if tool_name.startswith("manage_"):
        read_actions = _MANAGE_READ_ACTIONS.get(tool_name)
        if read_actions is not None:
            return arguments.get("action") in read_actions
        return False
    mutation_prefixes = (
        "create_",
        "update_",
        "delete_",
        "remove_",
        "add_",
        "move_",
        "activate_",
        "deactivate_",
        "commit_",
        "publish_",
        "submit_",
        "approve_",
        "reject_",
        "resolve_",
        "reorder_",
        "execute_",
        "assign_",
    )
    if tool_name.startswith(mutation_prefixes):
        return False
    return True


def _is_publish_class(tool_name: str, arguments: Dict[str, Any]) -> bool:
    cond = _PUBLISH_CLASS_TOOLS.get(tool_name, "__nope__")
    if cond == "__nope__":
        return False
    if cond is None:
        return True
    if not isinstance(cond, dict):
        return False
    for key, expected in cond.items():
        actual = arguments.get(key)
        if isinstance(expected, tuple):
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


def _current_username(server: Any) -> Optional[str]:
    """Best-effort: return the auth user's user_name."""
    try:
        return getattr(server.config.auth, "username", None) or getattr(
            server.auth_manager, "username", None
        )
    except Exception:
        return None


def _fetch_record_audit(ctx: WriteGuardContext, table: str, query: str) -> Optional[Dict[str, str]]:
    """LIVE fetch of the record's CURRENT sys_updated_by / sys_updated_on from
    ServiceNow — NOT local cache, NOT the downloaded copy. This is a fresh remote
    table-API read at write time (encoded `query`, e.g. ``sys_id=...`` or
    ``sys_id=...^ORnumber=...``), so the concurrent-edit decision is made against
    the record's real present state. Returns None on any failure (fail-open)."""
    try:
        from servicenow_mcp.tools.sn_api import sn_query_page

        records, _ = sn_query_page(
            ctx.server.config,
            ctx.server.auth_manager,
            table=table,
            query=query,
            fields="sys_updated_by,sys_updated_on",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=True,
        )
        if records:
            return records[0]
    except Exception:
        logger.debug("Audit fetch failed for %s (%s)", table, query, exc_info=True)
    return None


def _elapsed_minutes(timestamp_str: Optional[str]) -> Optional[float]:
    """ServiceNow datetimes are UTC, "YYYY-MM-DD HH:MM:SS"."""
    if not timestamp_str:
        return None
    try:
        ts = datetime.fromisoformat(timestamp_str.replace(" ", "T"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 60.0
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _g6_flow_designer_raw_write(ctx: WriteGuardContext) -> None:
    """G6 — block raw writes to sys_hub_* tables via sn_write."""
    if ctx.tool_name != "sn_write":
        return
    table = (ctx.arguments.get("table") or "").lower()
    if not table or table not in FLOW_DESIGNER_INTERNAL_TABLES:
        return
    raise PolicyViolation(
        "G6",
        f"Direct write to Flow Designer internal table '{table}' is blocked.\n"
        f"Use manage_flow_designer with the appropriate action instead.\n"
        f"Reason: raw INSERTs to sys_hub_* leave the flow in an inconsistent state.",
    )


def _g6_variable_value_for_flow(ctx: WriteGuardContext) -> None:
    """G6 extension — block sn_write to sys_variable_value when its
    document is a sys_hub_* table (Flow Designer input value)."""
    if ctx.tool_name != "sn_write":
        return
    table = (ctx.arguments.get("table") or "").lower()
    if table != "sys_variable_value":
        return
    fields = ctx.arguments.get("fields") or {}
    document = (fields.get("document") or "").lower()
    if not document.startswith("sys_hub_"):
        return
    raise PolicyViolation(
        "G6",
        f"Direct write to sys_variable_value with document='{document}' is blocked.\n"
        f"Flow Designer input values must be set via manage_flow_designer "
        f"(checkout → set_* → save) to keep snapshots consistent.",
    )


def _g7_publish_extra_confirm(ctx: WriteGuardContext) -> None:
    """G7 — publish/commit/push class needs separate confirm field."""
    if not _is_publish_class(ctx.tool_name, ctx.arguments):
        return
    val = ctx.arguments.get(CONFIRM_PUBLISH_FIELD)
    if str(val).lower().strip() == CONFIRM_PUBLISH_VALUE:
        return
    raise PolicyViolation(
        "G7",
        f"Publish-class action '{ctx.tool_name}' requires BOTH "
        f"confirm='approve' AND {CONFIRM_PUBLISH_FIELD}='{CONFIRM_PUBLISH_VALUE}'. "
        f"This prevents accidental publish/commit/push. "
        f"Review what will be published before adding these flags.",
    )


def _check_concurrent_edit(
    ctx: WriteGuardContext, table: str, query: str, label: str, *, guard: str
) -> None:
    """Shared concurrent-edit core: fetch the record's FRESH remote audit (via
    `query`) and block if a DIFFERENT user edited it within the window. Fail-open
    on any uncertainty (audit fetch failed, no editor, unparseable timestamp) —
    a guard must never block a legitimate write on missing data, only on a
    confirmed clash. `label` (e.g. "incident/INC001") is for the message only."""
    target = _fetch_record_audit(ctx, table, query)
    if target is None:
        return  # fail-open if audit fetch fails

    other = (target.get("sys_updated_by") or "").strip()
    me = (_current_username(ctx.server) or "").strip()
    if not other or other == me:
        return  # same user (or unknown) — never block your own work

    elapsed = _elapsed_minutes(target.get("sys_updated_on"))
    if elapsed is None:
        return

    try:
        window = int(os.getenv(ENV_CONCURRENT_WINDOW_MIN, str(DEFAULT_CONCURRENT_WINDOW_MIN)))
    except ValueError:
        window = DEFAULT_CONCURRENT_WINDOW_MIN

    if elapsed > window:
        return

    raise PolicyViolation(
        guard,
        f"Concurrent edit detected on {label}.\n"
        f"  Last edited by '{other}' ~{int(elapsed)} min ago "
        f"(window: {window} min, current user: '{me}').\n"
        f"Someone else's change would be overwritten. Re-fetch the record, "
        f"reapply your change, then retry — or wait out the window.",
    )


def _g3_concurrent_edit(ctx: WriteGuardContext) -> None:
    """G3 — block sn_write(update|delete) when the target was recently edited
    by someone else."""
    if not _concurrent_guard_enabled():
        return
    if ctx.tool_name != "sn_write":
        return
    action = (ctx.arguments.get("action") or "").lower()
    if action not in ("update", "delete"):
        return
    table = ctx.arguments.get("table")
    sys_id = ctx.arguments.get("sys_id")
    if not (table and sys_id):
        # Missing required args — let sn_write itself reject; guard skips.
        return
    _check_concurrent_edit(ctx, str(table), f"sys_id={sys_id}", f"{table}/{sys_id}", guard="G3")


def _g8_generic_concurrent_edit(ctx: WriteGuardContext) -> None:
    """G8 — extend concurrent-edit protection beyond sn_write to ANY write tool
    that names its target explicitly via `table` + `sys_id` args (e.g.
    update_portal_component, manage_portal_component update actions).

    Deliberately conservative: fires ONLY when both `table` and `sys_id` are
    present and non-empty, so the audited record is exactly the one being
    written — no risk of blocking the wrong record. Tools that identify records
    another way (e.g. by `number`) are covered by the registry guard instead.
    sn_write is handled by G3; registry tools by _g8_registry — skip both here
    to avoid a duplicate audit fetch."""
    if not _concurrent_guard_enabled():
        return
    if ctx.tool_name == "sn_write" or ctx.tool_name in _CONCURRENT_EDIT_REGISTRY:
        return
    table = str(ctx.arguments.get("table") or "").strip()
    sys_id = str(ctx.arguments.get("sys_id") or "").strip()
    if not (table and sys_id):
        return
    _check_concurrent_edit(ctx, table, f"sys_id={sys_id}", f"{table}/{sys_id}", guard="G8")


def _g8_registry_concurrent_edit(ctx: WriteGuardContext) -> None:
    """G8 (registry) — concurrent-edit protection for the manage_* write tools
    that identify their target by a tool-specific id arg (incident_id, change_id,
    workflow_id, …) rather than a generic `table`+`sys_id`.

    Only single-record update/delete actions on a known table are registered;
    ambiguous junction / multi-table actions (link, add_members, …) and create
    actions are intentionally left out → they fail-open (pass through). The audit
    query ORs the id across its possible columns (sys_id / number / name) so it
    matches the exact record regardless of which identifier form was passed."""
    if not _concurrent_guard_enabled():
        return
    target = _CONCURRENT_EDIT_REGISTRY.get(ctx.tool_name)
    if target is None:
        return
    action = str(ctx.arguments.get("action") or "").lower()
    if action not in target.update_actions:
        return
    value = str(ctx.arguments.get(target.id_arg) or "").strip()
    if not value:
        return
    query = "^OR".join(f"{col}={value}" for col in target.id_columns)
    _check_concurrent_edit(ctx, target.table, query, f"{target.table}/{value}", guard="G8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_write_guards(server: Any, tool_name: str, arguments: Dict[str, Any]) -> None:
    """Local pre-confirm guards (G6, G7) — NO network. Raises PolicyViolation on
    first failure. Called from server._call_tool_impl BEFORE the confirm gate so
    structural violations fail with a specific message.

    Concurrent-edit detection (G3/G8) is intentionally NOT here: it makes a live
    audit fetch, so it must run only AFTER the confirm gate passes — see
    run_concurrent_edit_guards. This keeps the invariant "an unconfirmed mutation
    touches the network zero times".
    """
    if not _guards_enabled():
        return
    if _is_read_only(tool_name, arguments):
        return

    ctx = WriteGuardContext(server, tool_name, arguments)
    _g6_flow_designer_raw_write(ctx)
    _g6_variable_value_for_flow(ctx)
    _g7_publish_extra_confirm(ctx)


def run_concurrent_edit_guards(server: Any, tool_name: str, arguments: Dict[str, Any]) -> None:
    """Concurrent-edit guards (G3 + G8). Each makes ONE live audit fetch of the
    target's current sys_updated_by/on, so this runs AFTER the confirm gate — an
    unconfirmed write is rejected first and never reaches the network. Only
    update/delete of an existing record is checked; creates pass through (nothing
    to clash with). Raises PolicyViolation on a confirmed concurrent clash."""
    if not _guards_enabled():
        return
    if _is_read_only(tool_name, arguments):
        return

    ctx = WriteGuardContext(server, tool_name, arguments)
    _g3_concurrent_edit(ctx)
    _g8_generic_concurrent_edit(ctx)
    _g8_registry_concurrent_edit(ctx)


def strip_guard_fields(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Remove guard-specific fields before passing to tool impl."""
    return {k: v for k, v in arguments.items() if k != CONFIRM_PUBLISH_FIELD}
