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
    assert "commit_changeset" in portal_tools
    assert "publish_changeset" in portal_tools
    assert "list_workflows" in portal_tools
    assert "get_workflow_details" in portal_tools
    assert "list_workflow_versions" in portal_tools
    assert "get_workflow_activities" in portal_tools
