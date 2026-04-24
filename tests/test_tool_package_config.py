from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "tool_packages.yaml"


def _load_packages():
    """Load tool_packages.yaml and resolve _extends inheritance."""
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    resolved: dict[str, set[str]] = {}

    def resolve(name: str) -> set[str]:
        if name in resolved:
            return resolved[name]
        val = raw.get(name, [])
        if isinstance(val, list):
            resolved[name] = set(val)
            return resolved[name]
        base = resolve(val["_extends"]) if "_extends" in val else set()
        resolved[name] = base | set(val.get("_tools", []))
        return resolved[name]

    for key in raw:
        resolve(key)
    return resolved


def test_portal_developer_includes_changeset_commit_and_workflow_read_tools():
    pkgs = _load_packages()
    portal_tools = pkgs["portal_developer"]

    assert "get_logs" in portal_tools
    assert "search_server_code" in portal_tools
    assert "get_metadata_source" in portal_tools
    assert "trace_portal_route_targets" in portal_tools
    assert "commit_changeset" in portal_tools
    assert "publish_changeset" in portal_tools
    assert "list_workflows" in portal_tools
    assert "get_workflow_details" in portal_tools
    assert "route_portal_component_edit" in portal_tools
    assert "analyze_portal_component_update" in portal_tools
    assert "create_portal_component_snapshot" in portal_tools
    assert "preview_portal_component_update" in portal_tools
    assert "update_portal_component" in portal_tools
    assert "update_portal_component_from_snapshot" in portal_tools


def test_full_package_includes_portal_edit_pipeline_tools():
    pkgs = _load_packages()
    full_tools = pkgs["full"]

    assert "route_portal_component_edit" in full_tools
    assert "analyze_portal_component_update" in full_tools
    assert "create_portal_component_snapshot" in full_tools
    assert "preview_portal_component_update" in full_tools
    assert "update_portal_component" in full_tools
    assert "update_portal_component_from_snapshot" in full_tools


def test_local_sync_tools_in_correct_packages():
    pkgs = _load_packages()

    for pkg in ["standard", "service_desk", "portal_developer", "platform_developer", "full"]:
        assert "diff_local_component" in pkgs[pkg], f"diff_local_component missing from {pkg}"

    for pkg in ["portal_developer", "platform_developer", "full"]:
        assert (
            "update_remote_from_local" in pkgs[pkg]
        ), f"update_remote_from_local missing from {pkg}"

    assert "update_remote_from_local" not in pkgs["standard"]
    assert "update_remote_from_local" not in pkgs["service_desk"]


def test_full_package_tool_count():
    pkgs = _load_packages()
    count = len(pkgs["full"])
    assert count <= 130, f"full package should be under 130 tools, got {count}"


def test_download_and_audit_tools_in_all_packages():
    pkgs = _load_packages()

    # Common download tools shared by portal_developer, platform_developer, full
    common_downloads = [
        "download_app_sources",
        "download_script_includes",
        "download_server_scripts",
        "download_ui_components",
        "download_api_sources",
        "download_security_sources",
        "download_admin_scripts",
        "download_table_schema",
    ]
    for pkg in ["portal_developer", "platform_developer", "full"]:
        for tool in common_downloads:
            assert tool in pkgs[pkg], f"'{tool}' missing from '{pkg}' package"

    # Portal-specific downloads
    assert "download_portal_sources" in pkgs["portal_developer"]
    assert "download_portal_sources" in pkgs["full"]


def test_consolidated_tools_replaced_old_ones():
    pkgs = _load_packages()
    full_tools = pkgs["full"]

    assert "get_flow_designer_detail" in full_tools
    assert "get_flow_designer_executions" in full_tools
    assert "get_workflow_details" in full_tools

    removed = [
        "get_flow_designer_structure",
        "get_flow_designer_triggers",
        "get_flow_designer_execution_detail",
        "list_portals",
        "list_pages",
        "list_widget_instances",
        "list_incidents",
        "list_change_requests",
        "list_changesets",
    ]
    for tool in removed:
        for pkg_name, pkg_tools in pkgs.items():
            assert tool not in pkg_tools, f"Removed tool '{tool}' still in package '{pkg_name}'"


def test_consolidated_flow_designer_tools_in_standard():
    pkgs = _load_packages()
    standard = pkgs["standard"]

    for tool in [
        "list_flow_designers",
        "get_flow_designer_detail",
        "get_flow_designer_executions",
        "compare_flows",
    ]:
        assert tool in standard, f"'{tool}' missing from standard package"

    removed = [
        "get_flow_full_detail",
        "list_flow_triggers_by_table",
        "activate_flow_designer",
        "deactivate_flow_designer",
        "list_actions",
        "get_action_detail",
        "list_playbooks",
        "get_playbook_detail",
        "list_decision_tables",
        "get_decision_table_detail",
    ]
    for tool in removed:
        assert tool not in standard, f"'{tool}' should not be in standard package"
