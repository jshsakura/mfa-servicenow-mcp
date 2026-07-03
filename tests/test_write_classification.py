"""Write-classification single-source tests (security batch).

Guards two past failure modes:
1. A mutating tool whose name matches no mutating prefix (scaffold_page)
   silently classified read-only → bypassed confirm + allow_writes.
2. Hand-mirrored classification tables (server vs write_guards) drifting —
   get_action_source was read-only in one copy and a write in the other.
"""

import servicenow_mcp.server as server_module
from servicenow_mcp.policies import write_guards
from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.tools._module_index import TOOL_MODULE_INDEX
from servicenow_mcp.tools.source_tools import SOURCE_CONFIG
from servicenow_mcp.tools.sync_tools import _target_qualifier_fields


class TestScaffoldPageIsMutating:
    def test_server_classifies_scaffold_page_as_write(self):
        assert "scaffold_page" in server_module.MUTATING_TOOL_NAMES

    def test_write_guards_classify_scaffold_page_as_write(self):
        assert write_guards._is_read_only("scaffold_page", {}) is False


class TestClassificationSingleSource:
    def test_manage_read_actions_is_one_object(self):
        # Identity, not equality: the tables must be THE SAME object so a new
        # entry can never land in only one copy again.
        assert server_module.MANAGE_READ_ACTIONS is write_guards.MANAGE_READ_ACTIONS

    def test_mutating_names_is_one_object(self):
        assert server_module.MUTATING_TOOL_NAMES is write_guards.MUTATING_TOOL_NAMES

    def test_get_action_source_is_read_only_in_guards(self):
        # The drift this catches: read action ran the concurrent-edit guards.
        assert (
            write_guards._is_read_only("manage_flow_designer", {"action": "get_action_source"})
            is True
        )

    def test_unknown_manage_action_still_write(self):
        assert write_guards._is_read_only("manage_flow_designer", {"action": "save"}) is False


class TestQualifierMapDerived:
    def test_target_qualifier_derived_from_source_config(self):
        # The push-side qualifier map must be BUILT from SOURCE_CONFIG, so adding
        # folder_qualifier_field to a new type can't silently miss push routing.
        expected = {
            cfg["table"]: cfg["folder_qualifier_field"]
            for cfg in SOURCE_CONFIG.values()
            if cfg.get("folder_qualifier_field")
        }
        assert _target_qualifier_fields() == expected
        assert _target_qualifier_fields()["sys_ws_operation"] == "web_service_definition.name"


# Every registered tool that classifies READ-ONLY at name level. This is the
# deep fix for the scaffold_page class of bug: a NEW tool that writes but
# matches no mutating prefix lands in this set, fails this test, and forces a
# conscious decision at PR time — either rename it / add it to
# MUTATING_TOOL_NAMES (it writes), or extend this snapshot (it truly reads).
# Never extend the snapshot without checking the tool does not mutate
# ServiceNow data.
_READ_ONLY_TOOL_SNAPSHOT = frozenset(
    {
        "analyze_portal_component_update",
        "analyze_widget_performance",
        "audit_local_sources",
        "audit_pending_changes",
        "detect_angular_implicit_globals",
        "diff_local_component",
        "download_app_sources",
        "download_attachment",
        "download_portal_sources",
        "download_server_sources",
        "download_table_schema",
        "extract_table_dependencies",
        "get_developer_changes",
        "get_developer_daily_summary",
        "get_logs",
        "get_metadata_source",
        "get_page",
        "get_portal",
        "get_portal_component_code",
        "get_repo_change_report",
        "get_repo_file_last_modifier",
        "get_repo_recent_commits",
        "get_repo_working_tree_status",
        "get_uncommitted_changes",
        "get_widget_bundle",
        "get_widget_instance",
        "preview_portal_component_update",
        "query_local_graph",
        "route_portal_component_edit",
        "search_portal_regex_matches",
        "search_server_code",
        "sn_aggregate",
        "sn_discover",
        "sn_health",
        "sn_query",
        "sn_resolve_url",
        "sn_schema",
        "trace_portal_route_targets",
        # Session brief: disk reads + timestamp count queries only.
        "workspace_brief",
    }
)


class TestEveryToolIsClassified:
    def test_read_only_classification_matches_snapshot(self):
        # TOOL_MODULE_INDEX is the CI-verified complete tool list. Any tool the
        # gate treats as read-only MUST be in the audited snapshot above.
        read_only = {
            name for name in TOOL_MODULE_INDEX if not ServiceNowMCP._is_blocked_mutating_tool(name)
        }
        unexpected = read_only - _READ_ONLY_TOOL_SNAPSHOT
        assert not unexpected, (
            f"New tool(s) classified READ-ONLY at name level: {sorted(unexpected)}. "
            "If any of them mutates ServiceNow data, add it to write_guards."
            "MUTATING_TOOL_NAMES (or use a mutating prefix). Only extend "
            "_READ_ONLY_TOOL_SNAPSHOT after confirming it is a pure read."
        )
        stale = _READ_ONLY_TOOL_SNAPSHOT - read_only
        assert (
            not stale
        ), f"Snapshot lists tools that no longer exist/classify read-only: {sorted(stale)}"
