"""
Tests for workflow tool registration via @register_tool decorator system.
"""

from servicenow_mcp.utils.registry import discover_tools


def test_workflow_tools_are_discovered_by_registry():
    """Verify registered workflow tools appear in the global @register_tool registry."""
    registry = discover_tools()

    assert "manage_workflow" in registry, "Expected 'manage_workflow' in discover_tools() registry"

    # These were absorbed into manage_workflow (Phase 4.5)
    removed = [
        "list_workflows",
        "get_workflow_details",
        "create_workflow",
        "update_workflow",
        "activate_workflow",
        "deactivate_workflow",
        "add_workflow_activity",
        "update_workflow_activity",
        "delete_workflow_activity",
        "reorder_workflow_activities",
    ]
    for tool_name in removed:
        assert tool_name not in registry, f"'{tool_name}' should not be a standalone tool"


def test_workflow_tools_have_valid_params_and_description():
    """Verify manage_workflow has a Pydantic params model and non-empty description."""
    registry = discover_tools()

    impl_func, params_cls, ret_type, description, serialization = registry["manage_workflow"]
    assert callable(impl_func), "manage_workflow: impl must be callable"
    assert hasattr(
        params_cls, "model_json_schema"
    ), "manage_workflow: params must be Pydantic model"
    assert len(description) > 10, "manage_workflow: description too short"
