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

  G9 — Duplicate-name create block
       Creating a record whose name already exists, for tables where a duplicate
       name is a real clash (sys_update_set, wf_workflow, sys_user_group,
       sys_user). Override with allow_duplicate='true'. Runs post-confirm; a
       failed/denied existence read fails open (never blocks a create on a
       missing read).

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
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EditTarget:
    """How to find the record a manage_* tool writes to, for the audit fetch."""

    table: Optional[str]  # static target table, or None when table_fn resolves it
    id_arg: str  # argument key holding the record identifier
    update_actions: frozenset  # action values that edit an EXISTING record
    id_columns: Tuple[str, ...] = ("sys_id",)  # OR-matched columns for the id
    # When a tool writes to one of several tables depending on its args (e.g.
    # manage_widget_dependency target=provider|dependency), derive the table from
    # the arguments. Returns None when it can't be resolved → guard fails open.
    table_fn: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None


# Registry of manage_* write tools that identify their target by a tool-specific
# id arg (not a generic table+sys_id). Only single-record update/delete actions
# on one known table are listed; ambiguous junction/multi-record actions (link,
# add_members, reorder_activities) and creates are deliberately omitted →
# fail-open. Tools whose actions span a SECOND table get an extra entry in
# _CONCURRENT_EDIT_REGISTRY_SECONDARY below.
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
    "manage_kb_article": _EditTarget(
        "kb_knowledge", "article_id", frozenset({"update", "publish"}), ("sys_id", "number")
    ),
    "manage_portal_layout": _EditTarget("sp_page", "sys_id", frozenset({"update_page"})),
    # target=provider|dependency selects the record table; link/unlink touch m2m
    # junctions (ambiguous) and stay fail-open, so they're not listed here.
    "manage_widget_dependency": _EditTarget(
        None,
        "record_id",
        frozenset({"update", "delete"}),
        table_fn=lambda args: {
            "provider": "sp_angular_provider",
            "dependency": "sp_dependency",
        }.get(str(args.get("target") or "provider").strip().lower()),
    ),
}

# Additional per-tool targets for bundles whose actions write MORE than one
# table (each action set must be disjoint from the primary entry's). Checked by
# _g8_registry_concurrent_edit alongside the primary registry.
_CONCURRENT_EDIT_REGISTRY_SECONDARY: Dict[str, Tuple[_EditTarget, ...]] = {
    # Activity-level edits target wf_activity by activity_id; without this a
    # blind overwrite of another user's concurrent activity edit went undetected.
    "manage_workflow": (
        _EditTarget(
            "wf_activity",
            "activity_id",
            frozenset({"update_activity", "delete_activity"}),
        ),
    ),
}


@dataclass(frozen=True)
class _CreateDupTarget:
    """How to detect a same-name record before a create (G9)."""

    table: str
    name_arg: str  # argument key holding the new record's name
    name_column: str  # ServiceNow column to match on


# G9 — block CREATE of a record whose name already exists, ONLY for tables where
# a duplicate name is a genuine problem (functional ambiguity / silent
# duplicate). Deliberately excludes things like rm_story/rm_epic where two items
# legitimately share a short_description — blocking those would be false
# positives. Override per call with allow_duplicate='true'.
_CREATE_DUP_REGISTRY: Dict[str, _CreateDupTarget] = {
    "manage_changeset": _CreateDupTarget("sys_update_set", "name", "name"),
    "manage_workflow": _CreateDupTarget("wf_workflow", "name", "name"),
    "manage_group": _CreateDupTarget("sys_user_group", "name", "name"),
    "manage_user": _CreateDupTarget("sys_user", "user_name", "user_name"),
}

ALLOW_DUPLICATE_FIELD = "allow_duplicate"
_ALLOW_DUPLICATE_TRUE = {"true", "yes", "approve", "1"}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_WRITE_GUARDS = "SERVICENOW_WRITE_GUARDS"  # master toggle ("off" disables all)
ENV_CONCURRENT_WINDOW_MIN = "SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN"
ENV_CONCURRENT_GUARD = "SERVICENOW_CONCURRENT_EDIT_GUARD"  # disables G3+G8 only
DEFAULT_CONCURRENT_WINDOW_MIN = 10

# Opt-in fail-CLOSED for the concurrent-edit guard. Default is fail-open: if the
# pre-write audit read cannot run (network error, ACL denial, 5xx), the guard
# lets the write through rather than blocking a legitimate write on missing data.
# Security-sensitive callers can flip this to "closed" so a guard that *could not
# verify* blocks instead of silently passing — trading availability for the
# guarantee that a lost-update check never silently no-ops. Scoped to the
# read-FAILED case only; a read that succeeds and finds no conflict still passes.
ENV_WRITE_GUARDS_FAIL = "SERVICENOW_WRITE_GUARDS_FAIL"  # "closed" ⇒ fail-closed
_FAIL_CLOSED_VALUES = ("closed", "close", "strict", "1", "true", "yes")

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
_PUBLISH_CLASS_TOOLS: Dict[str, Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]] = {
    "publish_changeset": None,
    "commit_changeset": None,
    "update_remote_from_local": None,
    "approve_change": None,
    "submit_change_for_approval": None,
    "manage_changeset": {"action": ("publish", "commit")},
    # A list means OR: publish-class if ANY match-dict matches. Flow Designer
    # publishes two ways — save-then-publish (action='save', publish=True) AND
    # the direct action='publish' snapshot recompile — both must demand the
    # extra confirm_publish approval, so both are listed.
    "manage_flow_designer": [
        {"action": ("save",), "publish": True},
        {"action": ("publish",)},
    ],
}


# tool_name → a read-only way to PREVIEW the pending change, so a confirm/publish
# rejection is never a dead-end: it tells the caller exactly how to see what would
# happen, then retry. Empty for tools with no obvious read-only preview.
_PREVIEW_HINTS: Dict[str, str] = {
    "update_remote_from_local": (
        "Preview first with diff_local_component(path=...): it shows the exact line "
        "diff, whether the remote drifted, and who last edited it — then retry."
    ),
    "manage_flow_designer": (
        "Preview first with action='get_detail' (what will be recompiled) and check "
        "the current application/update set — then retry publish with "
        "confirm='approve' AND confirm_publish='approve'."
    ),
}


def preview_hint(tool_name: str) -> str:
    """Read-only-preview guidance for *tool_name*, or '' if none. Appended to
    confirm/publish rejections so they hand back the next actionable step."""
    return _PREVIEW_HINTS.get(tool_name, "")


# ---------------------------------------------------------------------------
# Write classification — SINGLE SOURCE OF TRUTH.
#
# server.py imports these (module-level import is safe: this module only
# imports stdlib at module level). History: this table used to be a hand
# mirror of server.MANAGE_READ_ACTIONS "to avoid circular import" — and it
# drifted (get_action_source was read-only in server but a write here, so a
# pure read ran the concurrent-edit guards). Never fork these tables again;
# tests/test_write_classification.py pins identity.
# ---------------------------------------------------------------------------

# Tool-name prefixes that mean "this call mutates ServiceNow data".
# manage_* is a write bundle by default; read-only sub-actions are exempted
# via MANAGE_READ_ACTIONS below.
MUTATING_TOOL_PREFIXES = (
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
    "manage_",
)

# Mutating tools whose NAME matches no prefix above. Any new tool that writes
# but doesn't match a prefix MUST be listed here, or it silently bypasses the
# confirm gate AND the allow_writes read-only guard (the scaffold_page bug).
MUTATING_TOOL_NAMES = frozenset({"sn_batch", "sn_write", "scaffold_page"})

# manage_<X>: per-tool set of action values that are read-only (no confirm).
# Bundles whose actions are all writes don't appear here — the prefix gate
# applies.
MANAGE_READ_ACTIONS: Dict[str, frozenset] = {
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
        {
            "list",
            "get_detail",
            "get_executions",
            "compare",
            "edit_status",
            "get_action_source",
            "read_action",
        }
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


def _fail_closed() -> bool:
    """True when the operator opted the concurrent-edit guard into fail-CLOSED —
    an audit read that could not run blocks the write instead of passing."""
    return os.getenv(ENV_WRITE_GUARDS_FAIL, "").strip().lower() in _FAIL_CLOSED_VALUES


def _is_read_only(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """True if this call doesn't mutate ServiceNow data."""
    if tool_name in MUTATING_TOOL_NAMES:
        return False
    if tool_name.startswith("manage_"):
        read_actions = MANAGE_READ_ACTIONS.get(tool_name)
        if read_actions is not None:
            return arguments.get("action") in read_actions
        return False
    if tool_name.startswith(MUTATING_TOOL_PREFIXES):
        return False
    return True


def _matches_publish_cond(cond: Dict[str, Any], arguments: Dict[str, Any]) -> bool:
    """True when every (key, expected) in *cond* matches *arguments* (AND).
    A tuple expected value matches membership; a scalar matches equality."""
    for key, expected in cond.items():
        actual = arguments.get(key)
        if isinstance(expected, tuple):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _is_publish_class(tool_name: str, arguments: Dict[str, Any]) -> bool:
    cond = _PUBLISH_CLASS_TOOLS.get(tool_name, "__nope__")
    if cond == "__nope__":
        return False
    if cond is None:
        return True
    # A list of match-dicts is OR: publish-class if ANY matches.
    if isinstance(cond, list):
        return any(_matches_publish_cond(c, arguments) for c in cond)
    if isinstance(cond, dict):
        return _matches_publish_cond(cond, arguments)
    return False


def _current_username(server: Any) -> Optional[str]:
    """Best-effort: return the auth user's user_name.

    Must resolve the SAME identity ServiceNow stamps into sys_updated_by, or the
    G3/G8 same-user exemption never matches and every post-push retouch inside
    the window blocks on your own edit. basic/oauth read the configured
    username (no network); browser asks the live session (TTL-cached)."""
    try:
        from servicenow_mcp.tools.sn_api import _authenticated_user

        return _authenticated_user(server.config, server.auth_manager, allow_live=True)
    except Exception:
        return None


def _parse_http_date(date_header: Optional[str]) -> Optional[datetime]:
    """Parse an HTTP ``Date`` response header (RFC 7231, GMT) into an aware UTC
    datetime, or None if absent/unparseable. This is ServiceNow's OWN clock at
    the moment it answered — used as the reference 'now' so the concurrent-edit
    window never depends on the local machine clock (which may have drifted)."""
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _fetch_record_audit(
    ctx: WriteGuardContext, table: str, query: str
) -> Tuple[Optional[Dict[str, str]], Optional[datetime]]:
    """LIVE fetch of the record's CURRENT sys_updated_by / sys_updated_on from
    ServiceNow — NOT local cache, NOT the downloaded copy. A fresh remote
    table-API read at write time (encoded `query`, e.g. ``sys_id=...`` or
    ``sys_id=...^ORnumber=...``), so the concurrent-edit decision is made against
    the record's real present state.

    Returns ``(record, server_now)`` where ``server_now`` is parsed from the
    response ``Date`` header — ServiceNow's own clock. Both ``sys_updated_on``
    (raw UTC, display_value=false) and ``server_now`` come from the SAME response,
    so the elapsed-time calc is server-vs-server and immune to local clock drift.
    Both ``None`` on any failure (fail-open). No extra round-trip — the Date
    header rides on the audit fetch we already make."""
    try:
        url = f"{ctx.server.config.instance_url}/api/now/table/{table}"
        params: Dict[str, Any] = {
            "sysparm_limit": 1,
            "sysparm_offset": 0,
            "sysparm_display_value": "false",  # sys_updated_on stays raw UTC
            "sysparm_exclude_reference_link": "true",
            "sysparm_fields": "sys_updated_by,sys_updated_on",
        }
        if query:
            params["sysparm_query"] = query

        response = ctx.server.auth_manager.make_request(
            "GET", url, params=params, timeout=ctx.server.config.request_timeout
        )
        response.raise_for_status()
        server_now = _parse_http_date(response.headers.get("Date"))
        rows = (response.json() or {}).get("result", [])
        record = rows[0] if rows else None
        return record, server_now
    except Exception:
        logger.debug("Audit fetch failed for %s (%s)", table, query, exc_info=True)
        return None, None


def _elapsed_minutes(
    timestamp_str: Optional[str], now: Optional[datetime] = None
) -> Optional[float]:
    """Minutes between ``sys_updated_on`` and *now*.

    ServiceNow datetimes are UTC ("YYYY-MM-DD HH:MM:SS"). Pass the SERVER's time
    (from the audit response ``Date`` header) as *now* so the result is
    server-vs-server and never depends on the local machine clock; falls back to
    local UTC only when the server time is unavailable."""
    if not timestamp_str:
        return None
    try:
        ts = datetime.fromisoformat(timestamp_str.replace(" ", "T"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        return (reference - ts).total_seconds() / 60.0
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
    hint = preview_hint(ctx.tool_name)
    raise PolicyViolation(
        "G7",
        f"Publish-class action '{ctx.tool_name}' requires BOTH "
        f"confirm='approve' AND {CONFIRM_PUBLISH_FIELD}='{CONFIRM_PUBLISH_VALUE}'. "
        f"This prevents accidental publish/commit/push. "
        f"Review what will be published before adding these flags." + (f" {hint}" if hint else ""),
    )


def _check_concurrent_edit(
    ctx: WriteGuardContext, table: str, query: str, label: str, *, guard: str
) -> None:
    """Shared concurrent-edit core: fetch the record's FRESH remote audit (via
    `query`) and block if a DIFFERENT user edited it within the window. Fail-open
    on any uncertainty (audit fetch failed, no editor, unparseable timestamp) —
    a guard must never block a legitimate write on missing data, only on a
    confirmed clash. `label` (e.g. "incident/INC001") is for the message only."""
    target, server_now = _fetch_record_audit(ctx, table, query)
    if target is None:
        # Distinguish "read FAILED" from "record legitimately absent":
        # _fetch_record_audit returns (None, None) only when the request itself
        # raised; a successful read with no matching row still parses the Date
        # header, so server_now is set. Fail-closed applies ONLY to the former —
        # a genuine record-not-found has nothing to conflict with.
        if server_now is None and _fail_closed():
            raise PolicyViolation(
                guard,
                f"Concurrent-edit guard could not verify {label}: the pre-write "
                f"audit read failed (network, ACL, or 5xx). Fail-closed mode "
                f"({ENV_WRITE_GUARDS_FAIL}=closed) blocks rather than risk a "
                f"silent lost update. Retry, or set {ENV_WRITE_GUARDS_FAIL} back "
                f"to its default (fail-open) if this instance denies audit reads.",
            )
        return  # fail-open (default): audit fetch failed or record absent

    other = (target.get("sys_updated_by") or "").strip()
    me = (_current_username(ctx.server) or "").strip()
    if not other or not me or other.lower() == me.lower():
        # Same user — never block your own work. Unknown identity (either side)
        # is uncertainty, and this guard fails open on uncertainty: it may only
        # block a CONFIRMED clash with someone else.
        return

    # server_now is ServiceNow's clock from the same response — drift-proof.
    elapsed = _elapsed_minutes(target.get("sys_updated_on"), now=server_now)
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
    primary = _CONCURRENT_EDIT_REGISTRY.get(ctx.tool_name)
    targets = ([primary] if primary else []) + list(
        _CONCURRENT_EDIT_REGISTRY_SECONDARY.get(ctx.tool_name, ())
    )
    action = str(ctx.arguments.get("action") or "").lower()
    for target in targets:
        if action not in target.update_actions:
            continue
        value = str(ctx.arguments.get(target.id_arg) or "").strip()
        if not value:
            continue
        # Resolve the target table — static, or derived from args for multi-table
        # tools. An unresolvable table fails open (skip) rather than guessing.
        table = target.table_fn(ctx.arguments) if target.table_fn else target.table
        if not table:
            continue
        query = "^OR".join(f"{col}={value}" for col in target.id_columns)
        _check_concurrent_edit(ctx, table, query, f"{table}/{value}", guard="G8")


def _fetch_existing_by_name(
    ctx: WriteGuardContext, table: str, column: str, name: str
) -> Optional[Dict[str, str]]:
    """LIVE remote check for an existing record with this name. Returns the first
    match (sys_id + name) or None. None ALSO on any failure — including a read
    denied by ACL — so the guard is permission-flexible: it never blocks a create
    just because it couldn't look first."""
    try:
        from servicenow_mcp.tools.sn_api import sn_query_page

        # name values shouldn't contain encoded-query operators; strip to be safe.
        safe = name.replace("^", "").replace("=", "")
        records, _ = sn_query_page(
            ctx.server.config,
            ctx.server.auth_manager,
            table=table,
            query=f"{column}={safe}",
            fields=f"sys_id,{column}",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=True,
        )
        if records:
            return records[0]
    except Exception:
        logger.debug("Duplicate-name check failed for %s.%s=%s", table, column, name, exc_info=True)
    return None


def _g9_duplicate_create(ctx: WriteGuardContext) -> None:
    """G9 — block creating a record whose name already exists, for the registered
    tables where a duplicate name is a real problem (sys_update_set, wf_workflow,
    sys_user_group, sys_user). Override with allow_duplicate='true'. Fail-open if
    the existence check can't run (no read access, transient error)."""
    target = _CREATE_DUP_REGISTRY.get(ctx.tool_name)
    if target is None:
        return
    if str(ctx.arguments.get("action") or "").lower() != "create":
        return
    name = str(ctx.arguments.get(target.name_arg) or "").strip()
    if not name:
        return
    if str(ctx.arguments.get(ALLOW_DUPLICATE_FIELD) or "").lower().strip() in _ALLOW_DUPLICATE_TRUE:
        return  # explicit, deliberate duplicate

    existing = _fetch_existing_by_name(ctx, target.table, target.name_column, name)
    if existing is None:
        return  # none found, or check couldn't run — fail-open

    raise PolicyViolation(
        "G9",
        f"A {target.table} with {target.name_column}='{name}' already exists "
        f"(sys_id={existing.get('sys_id')}). Creating another would make a silent "
        f"duplicate. If that is intended, add {ALLOW_DUPLICATE_FIELD}='true'; "
        f"otherwise update the existing record instead.",
    )


def _g10_session_identity(ctx: WriteGuardContext) -> None:
    """G10 — the live session user must match the profile's declared owner.

    Multi-user setups run each instance under a known person (declared via the
    browser auth ``username``). Browser SSO sessions are adopted from a shared
    per-instance disk cache, so after a reconnect the live session can silently
    belong to a DIFFERENT user — every write would then be recorded under that
    user and captured into THEIR active update set. One identity read (TTL-
    cached, ~free); only runs for browser auth with a declared username.

    Fail-open on an unresolvable identity (transient blip — the write itself
    would 401 on a truly dead session); SERVICENOW_WRITE_GUARDS_FAIL=closed
    blocks instead.
    """
    try:
        auth = ctx.server.config.auth
        if auth.type.value != "browser" or not auth.browser:
            return
        declared = str(auth.browser.username or "").strip()
    except Exception:
        return
    if not declared:
        return

    from servicenow_mcp.tools.sn_api import resolve_live_username

    try:
        actual = str(resolve_live_username(ctx.server.config, ctx.server.auth_manager) or "")
    except Exception:
        actual = ""
    actual = actual.strip()

    if not actual:
        if _fail_closed():
            raise PolicyViolation(
                "G10",
                f"Could not verify who this session is logged in as, and "
                f"{ENV_WRITE_GUARDS_FAIL}=closed blocks unverified writes. This "
                f"instance is declared for user '{declared}'. Run sn_health, "
                f"re-login if needed, then retry.",
            )
        return

    if actual.lower() == declared.lower():
        return

    raise PolicyViolation(
        "G10",
        f"Blocked: this session is logged in as '{actual}', but this instance is "
        f"declared for user '{declared}'. The write would be recorded as "
        f"'{actual}' and captured into their active update set. Log in again as "
        f"'{declared}' (or correct the declared username in the instance config), "
        f"then retry.",
    )


# ---------------------------------------------------------------------------
# Update-set awareness (NON-blocking)
# ---------------------------------------------------------------------------
# Surface WHERE a write is captured (which update set + scope) so the user is
# fully aware — especially when another session changed the current update set,
# or it points at a different app / Default. We never block: the ServiceNow UI
# lets the user do the same, so we inform rather than prevent. Fail-open: any
# read failure / basic auth → no field, write proceeds unchanged.


def _ref_pair(value: Any) -> Tuple[str, str]:
    """(sys_id, display) from a Table API reference field (dict or bare string)."""
    if isinstance(value, dict):
        return str(value.get("value") or ""), str(value.get("display_value") or "")
    s = str(value or "")
    return s, s


def _fetch_one(server: Any, table: str, query: str, fields: str) -> Optional[Dict[str, Any]]:
    try:
        from servicenow_mcp.tools.sn_api import sn_query_page

        rows, _ = sn_query_page(
            server.config,
            server.auth_manager,
            table=table,
            query=query,
            fields=fields,
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=True,
        )
        return rows[0] if rows else None
    except Exception:
        return None


def _resolve_write_record(
    tool_name: str, arguments: Dict[str, Any], result: Any
) -> Optional[Tuple[str, str]]:
    """Best-effort (table, sys_id) of the record a write targeted, for the scope
    comparison. None when it can't be determined → base awareness only."""
    target = _CONCURRENT_EDIT_REGISTRY.get(tool_name)
    table = target.table if target else ""
    table = table or str(arguments.get("table") or "").strip()
    sys_id = ""
    if isinstance(result, dict):
        sys_id = str(result.get("sys_id") or "").strip()
        comp = result.get("component")
        if isinstance(comp, dict):
            table = table or str(comp.get("table") or "").strip()
            sys_id = sys_id or str(comp.get("sys_id") or "").strip()
    sys_id = sys_id or str(arguments.get("sys_id") or "").strip()
    return (table, sys_id) if (table and sys_id) else None


def update_set_context(
    server: Any, tool_name: str, arguments: Dict[str, Any], result: Any
) -> Optional[Dict[str, Any]]:
    """Awareness stamp merged into a write's result: which update set (+ scope)
    the change is captured into, and whether that scope matches the record.

    Browser auth only (the current update set is session state). Never raises —
    returns None to skip on any uncertainty so a write is never affected.
    """
    try:
        from servicenow_mcp.utils.config import AuthType

        if getattr(getattr(server.config, "auth", None), "type", None) != AuthType.BROWSER:
            return None

        from servicenow_mcp.tools.session_context_tools import (
            get_current_update_set,
            is_default_update_set,
        )

        us = get_current_update_set(server.config, server.auth_manager)
        if not us or not us.get("sys_id"):
            return None

        usrec = _fetch_one(
            server, "sys_update_set", f"sys_id={us['sys_id']}", "sys_id,name,application"
        )
        us_scope_id, us_scope_name = _ref_pair(usrec.get("application")) if usrec else ("", "")

        ctx: Dict[str, Any] = {
            "update_set": us.get("name") or us.get("sys_id"),
            "update_set_scope": us_scope_name or us_scope_id or "unknown",
        }

        # Opportunistic scope comparison when the record is resolvable.
        aligned: Optional[bool] = None
        record = _resolve_write_record(tool_name, arguments, result)
        if record:
            rec = _fetch_one(server, record[0], f"sys_id={record[1]}", "sys_id,sys_scope")
            if rec is not None:
                rec_scope_id, rec_scope_name = _ref_pair(rec.get("sys_scope"))
                if rec_scope_id and us_scope_id:
                    aligned = rec_scope_id == us_scope_id
                    ctx["record_scope"] = rec_scope_name or rec_scope_id

        if is_default_update_set(us):
            ctx["aligned"] = False
            ctx["note"] = (
                "⚠ Current update set is 'Default' — changes are usually captured here by "
                "accident. Verify this is where you want them before relying on it."
            )
        elif aligned is False:
            ctx["aligned"] = False
            ctx["note"] = (
                f"⚠ Captured into update set '{ctx['update_set']}' (scope "
                f"{ctx['update_set_scope']}), but the record is in scope "
                f"{ctx.get('record_scope')}. Another session may have changed your current "
                "update set — verify this is the intended target."
            )
        elif aligned is True:
            ctx["aligned"] = True
        # No note in the benign case: it only ever restated update_set and
        # update_set_scope, which are right here. A note in this stamp MEANS
        # "something is off" — spending it on "everything is fine" both costs
        # every single write and dulls the two cases above, which are the ones
        # that must read as alarming.
        return ctx
    except Exception:
        logger.debug("update_set_context computation failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_write_guards(server: Any, tool_name: str, arguments: Dict[str, Any]) -> None:
    """Local pre-confirm guards (G6, G7) — NO network. Raises PolicyViolation on
    first failure. Called from server._call_tool_impl BEFORE the confirm gate so
    structural violations fail with a specific message.

    Concurrent-edit detection (G3/G8) is intentionally NOT here: it makes a live
    audit fetch, so it must run only AFTER the confirm gate passes — see
    run_post_confirm_guards. This keeps the invariant "an unconfirmed mutation
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


def run_post_confirm_guards(server: Any, tool_name: str, arguments: Dict[str, Any]) -> None:
    """Post-confirm network guards. Each makes ONE live remote read, so they run
    AFTER the confirm gate — an unconfirmed write is rejected first and never
    reaches the network. Covers:
      • G10 — session identity: block writes when the live session user differs
        from the profile's declared owner (browser auth with username set).
      • G3/G8 — concurrent edit: block overwriting a DIFFERENT user's recent edit
        on an update/delete (creates pass through).
      • G9 — duplicate create: block creating a same-name record where that is a
        real clash (override with allow_duplicate='true').
    Raises PolicyViolation on a confirmed violation."""
    if not _guards_enabled():
        return
    if _is_read_only(tool_name, arguments):
        return

    ctx = WriteGuardContext(server, tool_name, arguments)
    # Identity first: with the wrong user logged in, the concurrent-edit and
    # duplicate reads below would themselves run (and reason) as that user.
    _g10_session_identity(ctx)
    _g3_concurrent_edit(ctx)
    _g8_generic_concurrent_edit(ctx)
    _g8_registry_concurrent_edit(ctx)
    _g9_duplicate_create(ctx)


def strip_guard_fields(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Remove pre-confirm guard fields before the confirm gate. (allow_duplicate
    is consumed by the POST-confirm G9 guard, so it is stripped later, alongside
    the confirm field.)"""
    return {k: v for k, v in arguments.items() if k != CONFIRM_PUBLISH_FIELD}


def strip_post_confirm_fields(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Remove post-confirm guard fields (allow_duplicate) before the tool runs."""
    return {k: v for k, v in arguments.items() if k != ALLOW_DUPLICATE_FIELD}
