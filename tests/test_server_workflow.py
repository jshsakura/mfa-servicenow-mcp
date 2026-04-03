"""
Tests for workflow tool registration via @register_tool decorator system.
"""

from servicenow_mcp.utils.registry import discover_tools


def test_workflow_tools_are_discovered_by_registry():
    """Verify all workflow tools appear in the global @register_tool registry."""
    registry = discover_tools()

    workflow_tools = [
        "list_workflows",
        "get_workflow_details",
        "list_workflow_versions",
        "get_workflow_activities",
        "create_workflow",
        "update_workflow",
        "activate_workflow",
        "deactivate_workflow",
        "add_workflow_activity",
        "update_workflow_activity",
        "delete_workflow_activity",
        "reorder_workflow_activities",
    ]

    for tool_name in workflow_tools:
        assert tool_name in registry, f"Expected '{tool_name}' in discover_tools() registry"


def test_workflow_tools_have_valid_params_and_description():
    """Verify each workflow tool has a Pydantic params model and non-empty description."""
    registry = discover_tools()

    workflow_tools = [
        "list_workflows",
        "get_workflow_details",
        "create_workflow",
        "update_workflow",
    ]

    for tool_name in workflow_tools:
        impl_func, params_cls, ret_type, description, serialization = registry[tool_name]
        assert callable(impl_func), f"{tool_name}: impl must be callable"
        assert hasattr(
            params_cls, "model_json_schema"
        ), f"{tool_name}: params must be Pydantic model"
        assert len(description) > 10, f"{tool_name}: description too short"
