---
name: workflow-management
description: Manage workflows and Flow Designer flows — list, inspect, activate, deactivate, modify
context_cost: low
safety_level: staged
delegatable: false
required_input: workflow name, sys_id, or table name
output: action
tools:
  - list_workflows
  - get_workflow_details
  - create_workflow
  - update_workflow
  - activate_workflow
  - deactivate_workflow
  - add_workflow_activity
  - update_workflow_activity
  - delete_workflow_activity
  - reorder_workflow_activities
  - list_flow_designers
  - get_flow_designer_detail
  - update_flow_designer
  - get_flow_designer_executions
triggers:
  - "워크플로우 목록"
  - "워크플로우 수정"
  - "워크플로우 활성화"
  - "워크플로우 비활성화"
  - "플로우 디자이너"
  - "플로우 수정"
  - "list workflows"
  - "edit workflow"
  - "activate workflow"
  - "deactivate workflow"
  - "flow designer"
  - "update flow"
---

# Instructions

You are managing ServiceNow workflows. Two engines exist — identify which one first.

## Engine Detection

| Engine | Table | How to tell |
|--------|-------|-------------|
| Workflow Engine | `wf_workflow` | Classic workflows, activity-based |
| Flow Designer | `sys_hub_flow` | Modern flows, action/subflow-based |

When user says "workflow" without specifying, check BOTH engines:
1. CALL list_workflows(name=INPUT)
2. CALL list_flow_designers(name=INPUT)
3. SHOW results from both, ask which one

## Pipeline: List

IF "목록" or "list":
  CALL list_workflows(name=FILTER, table=FILTER) for Workflow Engine
  CALL list_flow_designers(name=FILTER, scope=FILTER) for Flow Designer
  RETURN combined results with engine labels

## Pipeline: Inspect

IF "상세" or "details":
  IF wf_workflow:
    CALL get_workflow_details(workflow_id=INPUT, include_activities=true)
  IF sys_hub_flow:
    CALL get_flow_designer_detail(flow_id=INPUT, include_structure=true, include_triggers=true)

## Pipeline: Activate / Deactivate

IF "활성화" or "activate":
  IF wf_workflow: CALL activate_workflow(workflow_id=INPUT, confirm="approve")
  IF sys_hub_flow: CALL update_flow_designer(flow_id=INPUT, active=true, confirm="approve")

IF "비활성화" or "deactivate":
  IF wf_workflow: CALL deactivate_workflow(workflow_id=INPUT, confirm="approve")
  IF sys_hub_flow: CALL update_flow_designer(flow_id=INPUT, active=false, confirm="approve")

## Pipeline: Modify

IF "수정" or "update":
  # 1. Preview — no side effects, shows field-level diff
  IF wf_workflow: CALL update_workflow(workflow_id=INPUT, <fields>, dry_run=True)
  # 2. Show user `proposed_changes` + `no_op_fields`, then apply
  IF wf_workflow: CALL update_workflow(workflow_id=INPUT, <fields>, confirm="approve")
  IF sys_hub_flow: CALL update_flow_designer(flow_id=INPUT, name/description/active, confirm="approve")

> Flow Designer note: action/subflow structure changes require the Flow Designer UI + Publish. MCP can modify metadata and state only.

## Pipeline: Activity Management (Workflow Engine only)

IF "액티비티 추가" or "add activity":
  CALL add_workflow_activity(workflow_version_id=INPUT, activity_name=INPUT, confirm="approve")

IF "액티비티 수정" or "update activity":
  CALL update_workflow_activity(activity_id=INPUT, confirm="approve")

IF "액티비티 삭제" or "delete activity":
  CALL delete_workflow_activity(activity_id=INPUT, confirm="approve")

IF "액티비티 순서" or "reorder":
  CALL reorder_workflow_activities(workflow_id=INPUT, activity_ids=[...], confirm="approve")

## Pipeline: Execution History (Flow Designer only)

IF "실행 이력" or "executions":
  CALL get_flow_designer_executions(flow_id=INPUT, errors_only=true/false)

## ON ERROR

- "not found" → check the other engine (user may have the wrong one)
- Flow Designer structure change fails → must use Flow Designer UI + Publish
- Permission denied → check ACL or scope

## DELEGATE hint

DO NOT delegate. All write operations need user confirmation.
