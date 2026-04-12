from pathlib import Path

import yaml


def test_portal_developer_includes_changeset_commit_and_workflow_read_tools():
    config_path = Path(__file__).resolve().parents[1] / "config" / "tool_packages.yaml"
    config = yaml.safe_load(config_path.read_text())

    portal_tools = set(config["portal_developer"])

    assert "get_system_logs" in portal_tools
    assert "get_journal_entries" in portal_tools
    assert "get_transaction_logs" in portal_tools
    assert "get_background_script_logs" in portal_tools
    assert "search_server_code" in portal_tools
    assert "get_metadata_source" in portal_tools
    assert "trace_portal_route_targets" in portal_tools
    assert "commit_changeset" in portal_tools
    assert "publish_changeset" in portal_tools
    assert "list_legacy_workflows" in portal_tools
    assert "get_legacy_workflow_details" in portal_tools
    assert "list_legacy_workflow_versions" in portal_tools
    assert "get_legacy_workflow_activities" in portal_tools
    assert "route_portal_component_edit" in portal_tools
    assert "analyze_portal_component_update" in portal_tools
    assert "create_portal_component_snapshot" in portal_tools
    assert "preview_portal_component_update" in portal_tools
    assert "update_portal_component" in portal_tools
    assert "update_portal_component_from_snapshot" in portal_tools


def test_full_package_includes_portal_edit_pipeline_tools():
    config_path = Path(__file__).resolve().parents[1] / "config" / "tool_packages.yaml"
    config = yaml.safe_load(config_path.read_text())

    full_tools = set(config["full"])

    assert "route_portal_component_edit" in full_tools
    assert "analyze_portal_component_update" in full_tools
    assert "create_portal_component_snapshot" in full_tools
    assert "preview_portal_component_update" in full_tools
    assert "update_portal_component" in full_tools
    assert "update_portal_component_from_snapshot" in full_tools


def test_local_sync_tools_in_correct_packages():
    config_path = Path(__file__).resolve().parents[1] / "config" / "tool_packages.yaml"
    config = yaml.safe_load(config_path.read_text())

    # diff_local_component is read-only — should be in all packages
    for pkg in ["standard", "service_desk", "portal_developer", "platform_developer", "full"]:
        assert "diff_local_component" in config[pkg], f"diff_local_component missing from {pkg}"

    # update_remote_from_local is write — only in portal_developer, platform_developer, full
    for pkg in ["portal_developer", "platform_developer", "full"]:
        assert "update_remote_from_local" in config[pkg], f"update_remote_from_local missing from {pkg}"

    # should NOT be in standard or service_desk
    assert "update_remote_from_local" not in config["standard"]
    assert "update_remote_from_local" not in config["service_desk"]


def test_full_package_is_100_tools():
    config_path = Path(__file__).resolve().parents[1] / "config" / "tool_packages.yaml"
    config = yaml.safe_load(config_path.read_text())

    assert len(config["full"]) == 100, f"full package should have exactly 100 tools, got {len(config['full'])}"
