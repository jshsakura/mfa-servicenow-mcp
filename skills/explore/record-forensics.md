---
name: record-forensics
description: Reconstruct what happened to one record — who changed which field when, what approvals, flows, emails and errors followed
context_cost: medium
safety_level: none
delegatable: yes
required_input: a record number (INC0012345, RITM0010001, ...); optionally the field or time in question
output: report
tools:
  - get_record_context
  - sn_aggregate
  - sn_query
  - get_logs
  - get_table_automation
triggers:
  - "왜 이렇게 됐어"
  - "누가 바꿨어"
  - "이력 추적"
  - "이 티켓 무슨 일"
  - "메일 나갔어"
  - "승인 어디서 멈췄어"
  - "who changed this"
  - "what happened to this record"
  - "why did this ticket"
  - "was the email sent"
---

# Instructions

The question is about ONE record's past: who, when, what followed. Every answer
here is a read. Do not write a Background Script for it, and do not open the
debug browser to read a history list — the tables below are the same data.

## Rules

- **Count before you read.** History tables are large. `sn_aggregate` (COUNT) on
  the exact condition first; read rows only when the count is small or after
  narrowing by time or field.
- **Project fields.** Always pass `fields=`. A history row without projection is
  mostly noise.
- **Say what you did not read.** A table you could not read (ACL, plugin absent)
  is "not checked", never "nothing happened". Auditing can be off for a table or
  field — an empty `sys_audit` means "not recorded", not "never changed".

## Pipeline

1. **Overview — one call.**
   CALL `get_record_context(number=<NUMBER>)` → the record, approvals, flows, child
   tasks, SLAs, journal counts. Note its `sys_id`, table, and the time window the
   question is about. Many questions end here. It takes a number only; with a
   bare sys_id, read the record with `sn_query` and continue from step 2.

2. **Field history — who changed what, when.**
   Count first:
   CALL `sn_aggregate(table="sys_audit", query="documentkey=<SYS_ID>^tablename=<TABLE>", aggregate="COUNT", group_by="fieldname")`
   Then READ only the fields in question:
   CALL `sn_query(table="sys_audit", query="documentkey=<SYS_ID>^fieldname=<FIELD>^ORDERBYsys_created_on", fields="fieldname,oldvalue,newvalue,user,sys_created_on")`
   Reference values are sys_ids — resolve the few that matter, not all.

3. **Comments / work notes** (only if the question is about what was said).
   `get_logs(log_type="journal", table=<TABLE>, record_sys_id=<SYS_ID>, field_name="comments"|"work_notes")`

4. **Approvals** — `get_record_context` already lists them. For the full trail
   of one approval: `sn_query(table="sysapproval_approver", query="sysapproval=<SYS_ID>", fields="approver,state,comments,sys_updated_on")`.

5. **Emails — was it sent, to whom.**
   `sn_query(table="sys_email", query="instance=<SYS_ID>^ORDERBYDESCsys_created_on", fields="subject,type,state,recipients,error_string,sys_created_on")`
   `type` is the outcome: `sent`, `send-ready` (queued, not out yet),
   `send-ignored` (a rule or setting suppressed it), `send-failed` (see
   `error_string`). No row means no email record exists — no notification
   fired, or old email rows were cleaned up; say which you could tell, and check
   the notification's conditions before suspecting the mail server.

6. **Flows — did one fail.**
   `sn_query(table="sys_flow_context", query="source_record=<SYS_ID>", fields="name,state,error_message,sys_created_on")`
   For what SHOULD run on the table at all: `get_table_automation(table=<TABLE>)`.

7. **Errors around the moment** (only with a time from steps 2–6).
   `get_logs(log_type="system", level="error", timeframe=..., contains=<NUMBER or a script name>)`
   Logs are shared by the whole instance: match on the record number, a script
   name, or a narrow time — never report an unrelated error as the cause.

## Report

```
## <NUMBER> — <one-line answer to the question>

### Timeline
| When | Who | What |
|------|-----|------|
| ...  | ... | state 2 → 3 (sys_audit) |
| ...  | system | approval requested from <approver> |
| ...  | system | email "<subject>" sent / ignored (<reason>) |

### Not checked
- <table>: <why> (ACL / plugin absent / audit off for this field)
```

The answer is the first line. The timeline is the evidence. "Not checked" is
mandatory when anything was not read.

## ON ERROR

- `get_record_context` returns `undetermined` → the record did not come back
  (missing OR ACL-denied — they look the same); say so, do not report "no such record"
- A history table read fails or is denied → list it under "Not checked", keep going
- `sys_audit` is empty for a field that clearly changed → auditing is off for it;
  fall back to `sys_journal_field` / `sys_email` / flow contexts and say the
  field history is not recorded
- Count in the thousands → narrow by `fieldname` or `sys_created_on` before reading

## DELEGATE hint

Delegatable. Read-only. A sub-agent can run the reads and return only the
timeline table and the "Not checked" list — never raw history rows.
