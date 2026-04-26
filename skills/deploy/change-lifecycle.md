---
name: change-lifecycle
description: Change request full lifecycle — create, tasks, submit, approve/reject
context_cost: low
safety_level: staged
delegatable: false
required_input: change details or change_id
output: status
tools:
  - manage_change
  - submit_change_for_approval
  - approve_change
  - reject_change
triggers:
  - "변경 요청"
  - "승인"
  - "거부"
  - "change request"
  - "approve change"
  - "reject change"
  - "create CR"
---

# Instructions

You are managing a change request lifecycle.

## Pipeline

IF "만들기" or "create":
  CALL manage_change(action="create", ...)
    - short_description, type (normal/standard/emergency), description, risk, impact
    - confirm = "approve"

IF "작업 추가" or "add task":
  # Preview first (field diff + dependency counts)
  CALL manage_change(action="update", change_id=..., dry_run=True) for scope-changing edits
  CALL manage_change(action="add_task", ...)
    - change_id, task_short_description, task_assigned_to
    - confirm = "approve"

IF "승인 요청" or "submit":
  CALL submit_change_for_approval(change_id=INPUT, confirm="approve")

IF "승인" or "approve":
  CALL approve_change
    - change_id = INPUT
    - approval_comments = USER_REASON
    - confirm = "approve"

IF "거부" or "reject":
  CALL reject_change
    - change_id = INPUT
    - rejection_reason = USER_REASON
    - confirm = "approve"

IF "상태" or "check status":
  CALL manage_change(action="get", change_id=INPUT)

IF "목록" or "list":
  CALL manage_change(action="get", state=INPUT_STATE, limit=20)

## ON ERROR

- "No approval record" → change not submitted for approval yet
- "already approved" → change already processed

## DELEGATE hint

DO NOT delegate. All operations need user confirmation.
