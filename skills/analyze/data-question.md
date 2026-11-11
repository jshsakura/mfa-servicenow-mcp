---
name: data-question
description: Answer a question about instance data, or change data in bulk, with the right tool instead of a Background Script
context_cost: low
safety_level: confirm
delegatable: yes
required_input: the question (how many / which / list / fix these rows) and the table, if known
output: data
tools:
  - sn_aggregate
  - sn_query
  - sn_schema
  - manage_data_update
  - manage_workbook
triggers:
  - "몇 건이야"
  - "건수"
  - "통계"
  - "데이터 뽑아"
  - "일괄 수정"
  - "데이터 보정"
  - "BG로 돌려"
  - "백그라운드 스크립트"
  - "how many"
  - "count by"
  - "bulk update"
  - "data fix"
  - "background script"
---

# Instructions

A Background Script is the reflex for "how many", "list these", and "fix these
rows". Each is a tool call here, and the tool proves what a script only claims:
the read is read-only by construction, and the write shows its exact rows first.
**Do not write a BG script and do not hand one to the user.** If no tool below
fits, say which capability is missing — that is a tool to build, not a script
to paste.

## Pipeline

1. IDENTIFY what the user wants, then CALL the tool from this table.

### Route by question

| The user wants | Call | Not |
|---|---|---|
| a number, or numbers per group | `sn_aggregate(table, query, group_by=...)` | reading rows to count them |
| a sum / average / min / max | `sn_aggregate(aggregate="SUM", field=...)` | a GlideAggregate script |
| some rows | `sn_query(table, query, fields=..., limit=...)` | `fields` left empty |
| a value on a related record | dot-walk in `fields` / `query`: `caller_id.department` | a second query per row |
| to change field values on many rows | `manage_data_update` (below) | a BG update loop |
| to create/close/assign one ITSM record | the domain tool (`manage_incident`, `manage_change`, …) | `manage_data_update` |
| a spreadsheet, or many rows to analyse | `manage_workbook(action="write", spec={sheets:[{title, source:{table, query, fields}}]})` | reading the rows into context, or openpyxl in a script |
| one record's history | skill `explore/record-forensics` | — |

## Reading — three traps

1. **A field name you did not verify can return the whole table.** ServiceNow
   DROPS a condition on a field that does not exist — no error, every row comes
   back. Verify names first with `sn_schema(table=...)` when they were not read
   from the instance in this session. This holds for every hop of a dot-walk.
2. **Count before you list.** `sn_aggregate` first; read rows only when the
   count is what you expected and small. `sn_query` returns at most 100 per call.
3. **Values are codes.** `state=2`, not `state=In Progress`. Use
   `display_value=true` to show labels; query on the stored value.

## Many rows — never through the conversation

Reading rows into context to analyse or re-type them costs every value twice
and can silently change one. Instead:

1. `sn_aggregate` answers counts, groups and sums on the server — try it first.
2. When rows are needed, export them: a `source` sheet in `manage_workbook`
   write. The server reads into the file; the response is `matched`, `rows`,
   `complete`, and a per-column profile (empties, distinct, common values).
3. To look at particular rows: `manage_workbook(action="find", path=<file>, query=<regex>)`
   or `action="read"` with `min_row`/`limit` — a bounded slice, not the file.

`complete: false` means the server counted more rows than it returned (ACL):
say so; the file is not the full set.

## Changing data — `manage_data_update`

1. `manage_data_update(action="preview", table=..., query=..., set={...})` —
   read-only, safe on any instance. Or `rows=[{sys_id, field: value}, ...]` when
   each row gets its own value.
2. **Show the preview to the user**: `matched`, `will_change`,
   `changes_by_field`, `side_effects` (business rules / notifications per row).
   If it says `full_list`, give them the path — do not read the file back.
3. Only on their go-ahead: `manage_data_update(action="apply", <same arguments>,
   preview_token=..., confirm_count=..., confirm="approve")` — the token and count
   come from that preview.
4. Report `updated`, `also_changed` (fields business rules changed on their
   own) and the `snapshot` id. To undo: `action="preview_revert"` → user →
   `action="revert"`.

A refusal is the answer, not an obstacle: `UNKNOWN_QUERY_FIELDS`,
`WHOLE_TABLE`, `OVER_CAP`, `COUNT_MISMATCH` mean the scope is not proven. Fix
the condition; never work around it.

Business rules changing other fields cannot be seen before saving. For a
large change, apply ONE row first (`rows=[...]`), show its `also_changed`, then
the rest.

## ON ERROR

- `UNKNOWN_QUERY_FIELDS` / `WHOLE_TABLE` / `OVER_CAP` / `COUNT_MISMATCH` → the
  scope is not proven; fix the condition (check names with `sn_schema`), never
  work around it
- `PREVIEW_STALE` → the data moved since the preview; preview again and show the
  user the new result
- `STOPPED_AT_FAILURE` → report how many were updated, the failing row and its
  error; the snapshot covers what was written
- Insert, delete, per-row computed logic → not covered by these tools; name the
  gap to the user. Do not fall back to a script.

## DELEGATE hint

Reads are delegatable; a sub-agent returns counts and a small sample only.
`apply` / `revert` are NOT delegatable — the user must see the preview and
approve in the main conversation.
