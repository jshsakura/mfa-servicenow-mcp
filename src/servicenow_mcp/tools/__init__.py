"""
Tools module for the ServiceNow MCP server.
"""

# Import tools as they are implemented
from servicenow_mcp.tools.catalog_optimization import (
    get_optimization_recommendations,
    update_catalog_item,
)
from servicenow_mcp.tools.catalog_tools import (
    create_catalog_category,
    get_catalog_item,
    list_catalog_categories,
    list_catalog_items,
    move_catalog_items,
    update_catalog_category,
)
from servicenow_mcp.tools.catalog_variables import (
    create_catalog_item_variable,
    list_catalog_item_variables,
    update_catalog_item_variable,
)
from servicenow_mcp.tools.change_tools import (
    add_change_task,
    approve_change,
    create_change_request,
    get_change_request_details,
    reject_change,
    submit_change_for_approval,
    update_change_request,
)
from servicenow_mcp.tools.changeset_tools import (
    add_file_to_changeset,
    commit_changeset,
    create_changeset,
    get_changeset_details,
    publish_changeset,
    update_changeset,
)
from servicenow_mcp.tools.epic_tools import create_epic, list_epics, update_epic
from servicenow_mcp.tools.flow_designer_tools import (
    activate_flow_designer,
    deactivate_flow_designer,
)
from servicenow_mcp.tools.flow_designer_tools import get_flow_details as get_flow_designer_detail
from servicenow_mcp.tools.flow_designer_tools import (
    get_flow_executions as get_flow_designer_executions,
)
from servicenow_mcp.tools.flow_designer_tools import list_flow_triggers_by_table
from servicenow_mcp.tools.flow_designer_tools import list_flows as list_flow_designers
from servicenow_mcp.tools.flow_designer_tools import update_flow_designer
from servicenow_mcp.tools.incident_tools import (
    add_comment,
    create_incident,
    get_incident_by_number,
    resolve_incident,
    update_incident,
)
from servicenow_mcp.tools.knowledge_base import (
    create_article,
    create_category,
    create_knowledge_base,
    get_article,
    list_articles,
    list_categories,
    list_knowledge_bases,
    publish_article,
    update_article,
)
from servicenow_mcp.tools.log_tools import get_logs
from servicenow_mcp.tools.performance_tools import analyze_widget_performance
from servicenow_mcp.tools.portal_tools import (
    analyze_portal_component_update,
    create_portal_component_snapshot,
    detect_angular_implicit_globals,
    preview_portal_component_update,
    route_portal_component_edit,
    search_portal_regex_matches,
    update_portal_component_from_snapshot,
)

__all__ = [
    # Incident tools
    "create_incident",
    "update_incident",
    "add_comment",
    "resolve_incident",
    "get_incident_by_number",
    # Log tools
    "get_logs",
    # Source tools
    "search_server_code",
    "get_metadata_source",
    # Catalog tools
    "list_catalog_items",
    "get_catalog_item",
    "list_catalog_categories",
    "create_catalog_category",
    "update_catalog_category",
    "move_catalog_items",
    "get_optimization_recommendations",
    "update_catalog_item",
    "create_catalog_item_variable",
    "list_catalog_item_variables",
    "update_catalog_item_variable",
    # Change management tools
    "create_change_request",
    "update_change_request",
    "get_change_request_details",
    "add_change_task",
    "submit_change_for_approval",
    "approve_change",
    "reject_change",
    # Workflow (wf_workflow engine) management tools
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
    # Changeset tools
    "get_changeset_details",
    "create_changeset",
    "update_changeset",
    "commit_changeset",
    "publish_changeset",
    "add_file_to_changeset",
    # Script Include tools
    "list_script_includes",
    "get_script_include",
    "create_script_include",
    "update_script_include",
    "delete_script_include",
    # Knowledge Base tools
    "create_knowledge_base",
    "list_knowledge_bases",
    "create_category",
    "list_categories",
    "create_article",
    "update_article",
    "publish_article",
    "list_articles",
    "get_article",
    # User management tools
    "create_user",
    "update_user",
    "get_user",
    "list_users",
    "create_group",
    "update_group",
    "add_group_members",
    "remove_group_members",
    "list_groups",
    # Story tools
    "create_story",
    "update_story",
    "list_stories",
    "list_story_dependencies",
    "create_story_dependency",
    "delete_story_dependency",
    # Epic tools
    "create_epic",
    "update_epic",
    "list_epics",
    # Scrum Task tools
    "create_scrum_task",
    "update_scrum_task",
    "list_scrum_tasks",
    # Project tools
    "create_project",
    "update_project",
    "list_projects",
    "search_portal_regex_matches",
    "detect_angular_implicit_globals",
    "analyze_portal_component_update",
    "create_portal_component_snapshot",
    "preview_portal_component_update",
    "route_portal_component_edit",
    "update_portal_component_from_snapshot",
    "analyze_widget_performance",
    # Portal CRUD tools (Phase 1-3)
    "create_widget",
    "create_angular_provider",
    "create_header_footer",
    "create_css_theme",
    "create_ng_template",
    "create_ui_page",
    "create_page",
    "update_page",
    "create_container",
    "create_row",
    "create_column",
    "scaffold_page",
    # Flow Designer tools
    "list_flow_designers",
    "get_flow_designer_detail",
    "get_flow_designer_structure",
    "get_flow_designer_executions",
    "get_flow_designer_execution_detail",
    "get_flow_designer_triggers",
    "update_flow_designer",
    "activate_flow_designer",
    "deactivate_flow_designer",
    "list_flow_triggers_by_table",
    # Future tools
    # "create_problem",
    # "update_problem",
    # "create_request",
    # "update_request",
]
