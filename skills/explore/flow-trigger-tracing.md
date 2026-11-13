---
name: flow-trigger-tracing
description: What runs when a table changes, and what sets one field — rules, flows, workflows, notifications — proven on live records
context_cost: medium
safety_level: none
delegatable: yes
required_input: table name; optionally the field (state, stage, approval...) or the operation
output: report
tools:
  - get_table_automation
  - search_server_code
  - manage_flow_designer
  - manage_workflow
  - sn_query
  - sn_aggregate
triggers:
  - "이 테이블 바뀌면 뭐가 실행돼"
  - "트리거 추적"
  - "플로우 트리거"
  - "상태 바꿔주는 놈"
  - "누가 이 값을 바꿔"
  - "영향도"
  - "승인하면 뭐가 돌아"
  - "what runs when this table changes"
  - "what sets this field"
  - "impact of this change"
---

# Instructions

The judge is the live instance, never a document or a name. A rule's name says
what someone meant; its script and a real record's history say what happens.

## Pipeline — run in this order, do not skip

1. **Inventory — one call, narrowed.**
   CALL `get_table_automation(table=T, operation="update", categories=["business_rules","flow_triggers","legacy_workflows"])`
   - Insert-time question → `operation="insert"`. Email question → add `"notifications"`.
   - Never `operation="any"` with no categories: it returned 18KB for one table.
   - Parent tables are included (task for sc_req_item); keep them, they run too.

2. **Who writes the field — search the code, not the names** (only with a field F).
   CALL `search_server_code(query="F", source_type="business_rule")`, then `"script_include"`.
   Look for `current.F =`, `setValue('F'`, `.F =`. A rule that only READS F is not a writer.

3. **Flows and workflows that write it.** For each flow from step 1:
   `manage_flow_designer(action="get_detail", flow_id=<id>, include_structure=true)` —
   find Update Record steps that set F. Legacy: `manage_workflow(action="get", workflow_id=<id>, include_activities=true)`.
   Call get_detail ONCE per flow. A repeat returns `unchanged: true` — use the answer you have.

4. **Prove it on a real record (live evidence).** Pick one recent record of T
   whose F has the value in question (`sn_query(table=T, query="F=<value>", fields="sys_id,number,sys_updated_on", orderby="-sys_updated_on", limit=3)`),
   then read its history by sys_id — sys_audit is huge, always filter by `documentkey`:
   `sn_query(table="sys_audit", query="documentkey=<SYS_ID>^fieldname=F^ORDERBYsys_created_on", fields="oldvalue,newvalue,user,sys_created_on")`
   Match each change's time to a flow run
   (`manage_flow_designer(action="get_executions", source_record=<SYS_ID>, source_table=T)`)
   or to the rule from step 2. Unmatched change = "writer not identified", never a guess.

## Report — fixed format

```
## T.F — <one-line answer: who sets it, when>
| Writer | Kind | When (condition / order) | Proven on a record? |
|---|---|---|---|
| <name> | BR before/after #order / flow step / workflow activity | <condition as written> | yes: <number + time> / no: code only |
Not checked: <categories or tables you did not read — never leave this out>
```

"Nothing else writes F" is allowed only when steps 1–3 all ran over every
category and step 4 found no unmatched change. Otherwise list what was not read.

## ON ERROR

- `table_undetermined` / no rows → name the table as unread, not as "no automation"
- A row cap or `withheld` category → ask for that category alone; never report the
  first page as the whole list
- sys_audit empty → the table may not be audited; say "no audit trail", not "never changed"

## DELEGATE hint

Delegatable, read-only. Return only the report table.
