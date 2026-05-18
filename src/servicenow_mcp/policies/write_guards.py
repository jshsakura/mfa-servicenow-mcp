"""Write guards — block unsafe writes before they reach ServiceNow.

Guards enforced (v1.12.28):
  G1 — Active update set whitelist (env-configured)
  G2 — Update set name denylist (hard block on suspicious names)
  G5 — Update set size threshold (warn/hard-block on bloated sets)
  G6 — Flow Designer raw write block (sys_hub_* via sn_write denied)
  G7 — Publish-class extra confirmation

Deferred to v1.12.29:
  G3 — Concurrent-edit detection
  G4 — Optimistic locking

Each guard is independent. Failures raise PolicyViolation with a
LLM-readable message describing what was blocked and how to proceed.
"""

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env vars)
# ---------------------------------------------------------------------------

ENV_WRITE_GUARDS = "SERVICENOW_WRITE_GUARDS"  # master toggle: "off" disables all
ENV_ACTIVE_US = "SERVICENOW_ACTIVE_UPDATE_SET"
ENV_ACTIVE_US_NAME = "SERVICENOW_ACTIVE_UPDATE_SET_NAME"
ENV_US_WARN = "SERVICENOW_US_WARN_THRESHOLD"
ENV_US_BLOCK = "SERVICENOW_US_BLOCK_THRESHOLD"

DEFAULT_US_WARN = 1000
DEFAULT_US_BLOCK = 5000

# G2 denylist — case-insensitive substring match on update set name.
UPDATE_SET_NAME_DENYLIST = (
    "[not use]",
    "[notuse]",
    "[no use]",
    "default",
    "ignore",
    "stash",
    "preview",
    "backup",
    "deprecated",
    "archive",
)

# G6 — tables that must only be written via scaffold tools (manage_flow_designer).
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
_MANAGE_READ_ACTIONS: Dict[str, frozenset[str]] = {
    "manage_incident": frozenset({"get"}),
    "manage_change": frozenset({"get"}),
    "manage_changeset": frozenset({"get"}),
    "manage_user": frozenset({"get", "list"}),
    "manage_group": frozenset({"list"}),
    "manage_workflow": frozenset({"list", "get", "list_versions", "get_activities"}),
    "manage_script_include": frozenset({"list", "get"}),
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
    """Raised when a write guard blocks an action.

    Inherits ValueError so the existing call_tool error-handling path
    (returns the message back to the LLM) Just Works.
    """

    def __init__(self, guard: str, message: str):
        self.guard = guard
        super().__init__(f"[{guard}] {message}")


class WriteGuardContext:
    """Per-call context passed to each guard.

    Holds a reference to the running server (for auth/config) plus the
    tool name and arguments. Caches lookups so guards can share work
    (e.g. fetching the current update set once even if multiple guards
    need it).
    """

    def __init__(self, server: Any, tool_name: str, arguments: Dict[str, Any]):
        self.server = server
        self.tool_name = tool_name
        self.arguments = arguments
        self._current_us_cache: Optional[Dict[str, str]] = None
        self._us_size_cache: Optional[int] = None


# Cache the user's current update set for ~30s to avoid hammering sn_query
# during a burst of write attempts. Keyed by user sys_id.
_us_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}
_US_CACHE_TTL_SEC = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guards_enabled() -> bool:
    return os.getenv(ENV_WRITE_GUARDS, "on").lower() not in ("off", "false", "0", "no")


def _is_read_only(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Return True if this tool call doesn't mutate ServiceNow data.

    Mirrors server._is_blocked_mutating_tool but is action-aware for
    manage_X composite tools.
    """
    # Explicit writers
    if tool_name in {"sn_write", "sn_batch"}:
        return False
    # sn_nl is read unless execute=true
    if tool_name == "sn_nl":
        return not bool(arguments.get("execute", False))
    # manage_X tools: action determines read/write
    if tool_name.startswith("manage_"):
        read_actions = _MANAGE_READ_ACTIONS.get(tool_name)
        if read_actions is not None:
            return arguments.get("action") in read_actions
        return False  # manage_X without read-action listing → assume write
    # Other mutation prefixes
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
    # Default: read-only (most tools are get_/list_/search_/download_/audit_/...)
    return True


def _is_publish_class(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """G7 — does this call publish/commit changes (extra-risky)?"""
    cond = _PUBLISH_CLASS_TOOLS.get(tool_name, "__nope__")
    if cond == "__nope__":
        return False
    if cond is None:
        return True  # always publish-class
    # dict match: every key in cond must match arguments
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


def _current_user_sys_id(server: Any) -> Optional[str]:
    """Best-effort: look up the auth user's sys_user.sys_id."""
    try:
        username = getattr(server.config.auth, "username", None) or getattr(
            server.auth_manager, "username", None
        )
        if not username:
            return None
        from servicenow_mcp.tools.sn_api import sn_query_page

        records, _ = sn_query_page(
            server.config,
            server.auth_manager,
            table="sys_user",
            query=f"user_name={username}",
            fields="sys_id",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=True,
        )
        if records:
            return records[0].get("sys_id")
    except Exception:
        logger.debug("Could not resolve current user sys_id", exc_info=True)
    return None


def _fetch_current_update_set(ctx: WriteGuardContext) -> Optional[Dict[str, str]]:
    """Read the user's currently-selected update set.

    Returns dict {"sys_id": ..., "name": ...} or None if it can't be
    determined (in which case G1/G2/G5 will skip — guard-failing-open is
    safer than blocking everything when the lookup is broken).
    """
    if ctx._current_us_cache is not None:
        return ctx._current_us_cache

    user_sys_id = _current_user_sys_id(ctx.server)
    if not user_sys_id:
        return None

    now = time.monotonic()
    cached = _us_cache.get(user_sys_id)
    if cached and (now - cached[0]) < _US_CACHE_TTL_SEC:
        ctx._current_us_cache = cached[1]
        return cached[1]

    try:
        from servicenow_mcp.tools.sn_api import sn_query_page

        records, _ = sn_query_page(
            ctx.server.config,
            ctx.server.auth_manager,
            table="sys_user_preference",
            query=f"user={user_sys_id}^name=sys_update_set",
            fields="value",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=True,
        )
        if not records:
            return None
        us_sys_id = records[0].get("value")
        if not us_sys_id:
            return None

        us_records, _ = sn_query_page(
            ctx.server.config,
            ctx.server.auth_manager,
            table="sys_update_set",
            query=f"sys_id={us_sys_id}",
            fields="sys_id,name,state",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=True,
        )
        if not us_records:
            return None
        info = {
            "sys_id": us_records[0].get("sys_id", us_sys_id),
            "name": us_records[0].get("name", ""),
            "state": us_records[0].get("state", ""),
        }
        _us_cache[user_sys_id] = (now, info)
        ctx._current_us_cache = info
        return info
    except Exception:
        logger.debug("Failed to fetch current update set", exc_info=True)
        return None


def _fetch_update_set_size(ctx: WriteGuardContext, us_sys_id: str) -> Optional[int]:
    if ctx._us_size_cache is not None:
        return ctx._us_size_cache
    try:
        from servicenow_mcp.tools.sn_api import sn_count

        count = sn_count(
            ctx.server.config,
            ctx.server.auth_manager,
            table="sys_update_xml",
            query=f"update_set={us_sys_id}",
        )
        ctx._us_size_cache = count
        return count
    except Exception:
        logger.debug("Failed to count sys_update_xml", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _g6_flow_designer_raw_write(ctx: WriteGuardContext) -> None:
    """G6 — block raw writes to sys_hub_* tables via sn_write."""
    if ctx.tool_name != "sn_write":
        return
    table = (ctx.arguments.get("table") or "").lower()
    if not table:
        return
    if table not in FLOW_DESIGNER_INTERNAL_TABLES:
        # Special case: sys_variable_value only blocked when document=sys_hub_*
        return

    # Some sys_hub_* targets are permitted IF the row keys to a non-flow
    # document (handled by sys_variable_value; but that table is not in the
    # frozenset above so we don't reach here for it).
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


def _g1_active_update_set(ctx: WriteGuardContext) -> None:
    """G1 — only allow writes when the user's current update set matches
    the env-configured one."""
    expected = os.getenv(ENV_ACTIVE_US)
    if not expected:
        # Guard not configured → skip with a debug log.
        logger.debug("G1 skipped: %s not set", ENV_ACTIVE_US)
        return
    current = _fetch_current_update_set(ctx)
    if current is None:
        logger.debug("G1 skipped: could not determine current update set")
        return
    if current["sys_id"] == expected:
        return
    expected_name = os.getenv(ENV_ACTIVE_US_NAME, "<not set>")
    raise PolicyViolation(
        "G1",
        f"Active update set mismatch — write blocked.\n"
        f"  Expected: {expected_name} ({expected})\n"
        f"  Current:  {current['name']} ({current['sys_id']})\n"
        f"To fix: switch via switch_update_set(target_sys_id='{expected}') "
        f"or update SERVICENOW_ACTIVE_UPDATE_SET env var.",
    )


def _g2_update_set_denylist(ctx: WriteGuardContext) -> None:
    """G2 — refuse to write when current update set name looks unsafe."""
    current = _fetch_current_update_set(ctx)
    if current is None:
        return
    name = (current.get("name") or "").lower()
    if not name:
        return
    for pattern in UPDATE_SET_NAME_DENYLIST:
        if pattern in name:
            raise PolicyViolation(
                "G2",
                f"Current update set '{current['name']}' matches "
                f"denylist pattern '{pattern}' — write blocked.\n"
                f"This is a hard block (no override). "
                f"Switch to a proper working update set first.",
            )


def _g5_update_set_size(ctx: WriteGuardContext) -> None:
    """G5 — bloated update set → require strong confirm or hard block."""
    current = _fetch_current_update_set(ctx)
    if current is None:
        return
    size = _fetch_update_set_size(ctx, current["sys_id"])
    if size is None:
        return
    block_threshold = int(os.getenv(ENV_US_BLOCK, DEFAULT_US_BLOCK))
    warn_threshold = int(os.getenv(ENV_US_WARN, DEFAULT_US_WARN))
    if size >= block_threshold:
        raise PolicyViolation(
            "G5",
            f"Active update set '{current['name']}' has {size} entries "
            f"(>= {block_threshold} hard block). "
            f"Split into a new update set before writing.",
        )
    if size >= warn_threshold:
        if ctx.arguments.get("confirm_large_update_set") != "approve":
            raise PolicyViolation(
                "G5",
                f"Active update set '{current['name']}' has {size} entries "
                f"(>= {warn_threshold} warning). "
                f"Add confirm_large_update_set='approve' to proceed.",
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_write_guards(server: Any, tool_name: str, arguments: Dict[str, Any]) -> None:
    """Run all write guards. Raises PolicyViolation on first failure.

    Called from server._call_tool_impl between the action-allowlist check
    and the confirm gate.
    """
    if not _guards_enabled():
        return
    if _is_read_only(tool_name, arguments):
        return

    ctx = WriteGuardContext(server, tool_name, arguments)

    # Order: cheap/local checks first, then guards that need an API call.
    _g6_flow_designer_raw_write(ctx)
    _g6_variable_value_for_flow(ctx)
    _g7_publish_extra_confirm(ctx)
    _g2_update_set_denylist(ctx)
    _g1_active_update_set(ctx)
    _g5_update_set_size(ctx)


# Strip publish/large-set confirm fields after guards so tool impls don't
# see them in their params.
def strip_guard_fields(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v
        for k, v in arguments.items()
        if k not in (CONFIRM_PUBLISH_FIELD, "confirm_large_update_set")
    }
