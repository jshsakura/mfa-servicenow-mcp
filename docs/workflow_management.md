# Workflow Management in ServiceNow MCP

This document covers two workflow engines exposed by the MCP server:

1. **Legacy Workflow** (`wf_workflow`) — driven by the `manage_workflow` action router below.
2. **Flow Designer** (`sys_hub_flow`) — unified `manage_flow_designer` tool with action dispatch. Standard package exposes read actions (`list` / `get_detail` / `get_executions` / `compare`); higher packages unlock writes (`update` / `checkout` / `set_*` / `save` / `discard`). Action/SubFlow/Playbook tables are documented in the [Flow Designer table map](#flow-designer-table-map).

If you are not sure which engine a process uses, start with `manage_flow_designer(action="list")` (modern instances) and fall back to `manage_workflow(action="list")` for legacy `wf_workflow` records.

## Overview

ServiceNow workflows are a powerful automation feature that allows you to define and automate business processes. The workflow management tools in the ServiceNow MCP server enable you to view, create, and modify workflows in your ServiceNow instance.

## Available Tools

### Viewing Workflows

1. **manage_workflow(action="list")** - List workflows from ServiceNow
   - Parameters:
     - `limit` (optional): Maximum number of records to return (default: 10)
     - `offset` (optional): Offset to start from (default: 0)
     - `active` (optional): Filter by active status (true/false)
     - `name` (optional): Filter by name (contains)
     - `query` (optional): Additional query string

2. **manage_workflow(action="get")** - Get detailed information about a specific workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id

3. **manage_workflow(action="list_versions")** - List all versions of a specific workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id
     - `limit` (optional): Maximum number of records to return (default: 10)
     - `offset` (optional): Offset to start from (default: 0)

4. **manage_workflow(action="get_activities")** - Get all activities in a workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id
     - `version` (optional): Specific version to get activities for (if not provided, the latest published version will be used)

### Modifying Workflows

5. **manage_workflow** (action="create") - Create a new workflow in ServiceNow
   - Parameters:
     - `name` (required): Name of the workflow
     - `description` (optional): Description of the workflow
     - `table` (optional): Table the workflow applies to
     - `active` (optional): Whether the workflow is active (default: true)
     - `attributes` (optional): Additional attributes for the workflow

6. **manage_workflow** (action="update") - Update an existing workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id
     - `name` (optional): Name of the workflow
     - `description` (optional): Description of the workflow
     - `table` (optional): Table the workflow applies to
     - `active` (optional): Whether the workflow is active
     - `attributes` (optional): Additional attributes for the workflow

7. **manage_workflow** (action="activate") - Activate a workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id

8. **manage_workflow** (action="deactivate") - Deactivate a workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id

### Managing Workflow Activities

9. **manage_workflow** (action="add_activity") - Add a new activity to a workflow
   - Parameters:
     - `workflow_id` (required): Workflow ID or sys_id
     - `name` (required): Name of the activity
     - `description` (optional): Description of the activity
     - `activity_type` (required): Type of activity (e.g., 'approval', 'task', 'notification')
     - `attributes` (optional): Additional attributes for the activity
     - `position` (optional): Position in the workflow (if not provided, the activity will be added at the end)

10. **manage_workflow** (action="update_activity") - Update an existing activity in a workflow
    - Parameters:
      - `activity_id` (required): Activity ID or sys_id
      - `name` (optional): Name of the activity
      - `description` (optional): Description of the activity
      - `attributes` (optional): Additional attributes for the activity

11. **manage_workflow** (action="delete_activity") - Delete an activity from a workflow
    - Parameters:
      - `activity_id` (required): Activity ID or sys_id

12. **manage_workflow** (action="reorder_activities") - Change the order of activities in a workflow
    - Parameters:
      - `workflow_id` (required): Workflow ID or sys_id
      - `activity_ids` (required): List of activity IDs in the desired order

## Usage Examples

### Viewing Workflows

#### List all active workflows

```python
result = list_workflows({
    "active": True,
    "limit": 20
})
```

#### Get details about a specific workflow

```python
result = get_workflow_details({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### List all versions of a workflow

```python
result = list_workflow_versions({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### Get all activities in a workflow

```python
result = get_workflow_activities({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### Modifying Workflows

#### Create a new workflow

```python
result = manage_workflow({"action": "create",
    "name": "Software License Request",
    "description": "Workflow for handling software license requests",
    "table": "sc_request"
})
```

#### Update an existing workflow

```python
result = manage_workflow({"action": "update",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "description": "Updated workflow description",
    "active": True
})
```

#### Activate a workflow

```python
result = manage_workflow({"action": "activate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### Deactivate a workflow

```python
result = manage_workflow({"action": "deactivate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### Managing Workflow Activities

#### Add a new activity to a workflow

```python
result = manage_workflow({"action": "add_activity",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "name": "Manager Approval",
    "description": "Approval step for the manager",
    "activity_type": "approval"
})
```

#### Update an existing activity

```python
result = manage_workflow({"action": "update_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591",
    "name": "Updated Activity Name",
    "description": "Updated activity description"
})
```

#### Delete an activity

```python
result = manage_workflow({"action": "delete_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591"
})
```

#### Reorder activities in a workflow

```python
result = manage_workflow({"action": "reorder_activities",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "activity_ids": [
        "3cda7cda87a9c150e0b0df23cebb3591",
        "4cda7cda87a9c150e0b0df23cebb3592",
        "5cda7cda87a9c150e0b0df23cebb3593"
    ]
})
```

## Flow Designer Tools

Flow Designer (`sys_hub_flow`) is the modern successor to legacy workflows. The MCP server exposes it as a read-mostly surface — full CRUD requires the undocumented processflow API and is intentionally not surfaced through Table API tools.

### `manage_flow_designer` (unified)
Single composite tool with action dispatch. Replaces the previous 6 standalone flow tools (`list_flow_designers`, `get_flow_designer_detail`, `get_flow_designer_executions`, `compare_flows`, `update_flow_designer`, `manage_flow_edit`). Action enum is narrowed to read-only in `standard` and unlocked in `portal_developer` / `platform_developer` / `full`.

Read actions (available in `standard`):
- `action="list"` — search flows/subflows. Key params: `limit`, `offset`, `include_inactive`, `flow_status`, `scope`, `name_filter`.
- `action="get_detail"` — flow metadata + optional heavy sections. Key params: `flow_id` (required), `include_structure`, `include_triggers`, `include_executions_summary`, `trace_pill`, `include_subflow_tree`, `summary_format`.
- `action="get_executions"` — runtime history (filters) or single execution detail. Key params: `context_id` (single mode), `flow_id`, `flow_name`, `exec_state`, `source_record`, `errors_only`, `limit`/`offset`.
- `action="compare"` — diff two flows by `flow_id_a`/`flow_id_b` or `name_a`/`name_b`. Reports structural diff, subflow bindings, trigger differences. Preferred over calling `get_detail` twice.

Write actions (only in `portal_developer` / `platform_developer` / `full`):
- `action="update"` — metadata only (`new_name` / `description` / `active`). Anything structural (steps, triggers, publish) requires the edit workflow below or the Workflow Studio UI.
- `action="checkout"` — start a local edit session (browser auth required, uses processflow API).
- `action="set_action_input"` — patch action input value. Requires `node_id`, `input_name`, `value`.
- `action="set_branch_condition"` — patch flow logic branch condition. Requires `node_id`, `value`; optional `condition_label`.
- `action="set_trigger_condition"` — patch trigger condition. Requires `value`; `node_id` optional (first trigger if omitted).
- `action="save"` — persist edits via processflow API. Optional `publish=true` to publish after save.
- `action="discard"` — drop the local edit session.
- `action="edit_status"` — inspect current local checkout state.

### Flow Designer Table Map

| Workflow Studio Tab | Table |
| --- | --- |
| Flows / SubFlows | `sys_hub_flow` |
| Actions | `sys_hub_action_type_definition` |
| Playbooks | `sys_pd_process_definition` |
| Decision Tables | `sys_decision` |

### Read-only Bias

Flow modifications carry the highest risk in this codebase — corrupting a published flow can break automation across the instance. Default to read actions, gate writes behind explicit user confirmation, and prefer `manage_flow_designer(action="compare")` + `manage_flow_designer(action="get_executions")` to verify behavior before any change.

## Common Activity Types

ServiceNow provides several activity types that can be used when adding activities to a workflow:

1. **approval** - An approval activity that requires user action
2. **task** - A task that needs to be completed
3. **notification** - Sends a notification to users
4. **timer** - Waits for a specified amount of time
5. **condition** - Evaluates a condition and branches the workflow
6. **script** - Executes a script
7. **wait_for_condition** - Waits until a condition is met
8. **end** - Ends the workflow

## Best Practices

1. **Version Control**: Always create a new version of a workflow before making significant changes.
2. **Testing**: Test workflows in a non-production environment before deploying to production.
3. **Documentation**: Document the purpose and behavior of each workflow and activity.
4. **Error Handling**: Include error handling in your workflows to handle unexpected situations.
5. **Notifications**: Use notification activities to keep stakeholders informed about the workflow progress.

## Troubleshooting

### Common Issues

1. **Error: "No published versions found for this workflow"**
   - This error occurs when trying to get activities for a workflow that has no published versions.
   - Solution: Publish a version of the workflow before trying to get its activities.

2. **Error: "Activity type is required"**
   - This error occurs when trying to add an activity without specifying its type.
   - Solution: Provide a valid activity type when adding an activity.

3. **Error: "Cannot modify a published workflow version"**
   - This error occurs when trying to modify a published workflow version.
   - Solution: Create a new draft version of the workflow before making changes.

4. **Error: "Workflow ID is required"**
   - This error occurs when not providing a workflow ID for operations that require it.
   - Solution: Make sure to include the workflow ID in your request.

## Additional Resources

- [ServiceNow Workflow Documentation](https://docs.servicenow.com/bundle/tokyo-platform-administration/page/administer/workflow-administration/concept/c_WorkflowAdministration.html)
- [ServiceNow Workflow API Reference](https://developer.servicenow.com/dev.do#!/reference/api/tokyo/rest/c_WorkflowAPI) 