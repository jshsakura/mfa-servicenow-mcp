---
name: flow-trigger-tracing
description: Trace which workflows and flows fire when a table record changes
context_cost: medium
safety_level: none
delegatable: yes
required_input: table name (e.g. incident, sc_req_item)
output: report
tools:
  - sn_query
  - manage_workflow
  - list_flow_designers
  - get_flow_designer_detail
triggers:
  - "이 테이블 바뀌면 뭐가 실행돼"
  - "트리거 추적"
  - "플로우 트리거"
  - "워크플로우 트리거"
  - "what runs when this table changes"
  - "trace triggers"
  - "flow triggers"
  - "which workflows fire on"
---

# Instructions

You are tracing all automation (workflows + flows) that fire when a specific table's records change.

## Pipeline

1. IDENTIFY target table from user input
   - User may say "incident", "sc_req_item", "change_request", etc.
   - If user gives a record number (e.g. INC0012345), resolve the table first

2. TRACE Flow Designer triggers
   CALL sn_query(table="sys_flow_record_trigger", query="table=TARGET_TABLE^scope filter if provided", fields="sys_id,table,remote_trigger_id,condition,sys_scope,sys_name")
   → Returns trigger records from `sys_flow_record_trigger`; use `remote_trigger_id` to identify linked flows

3. TRACE Workflow Engine
   CALL manage_workflow(action="list", table=TARGET_TABLE, active=true)
   → Returns workflows from `wf_workflow` that are bound to this table

4. COMPILE report:
   ```
   ## Automation on [table_name]

   ### Flow Designer (sys_hub_flow)
    | Flow Name | Trigger Condition | Active | Scope |
   |-----------|-------------------|--------|-------|
   | ...       | ...               | ...    | ...   |

   ### Workflow Engine (wf_workflow)
   | Workflow Name | Active | Description |
   |---------------|--------|-------------|
   | ...           | ...    | ...         |

   ### Summary
   - X Flow Designer flows
   - Y Workflow Engine workflows
   - Total: X+Y automations on this table
   ```

5. IF user wants details on a specific flow/workflow:
   - Flow Designer: CALL get_flow_designer_detail(flow_id=ID, include_structure=true, include_triggers=true)
   - Workflow Engine: CALL manage_workflow(action="get", workflow_id=ID, include_activities=true)

## ON ERROR

- 0 results for both → table may not have automation, or scope filter too narrow
- Flow trigger has no linked flow → orphaned trigger record, report it
- Permission denied → ACL restriction on sys_flow_record_trigger table

## DELEGATE hint

Delegatable. No write operations. Sub-agent can compile the full report and return summary.
