---
name: changeset-workflow
description: Update set lifecycle — create, review, commit, publish
context_cost: low
safety_level: staged
delegatable: false
required_input: changeset name or sys_id
output: status
tools:
  - list_changesets
  - create_changeset
  - get_changeset_details
  - commit_changeset
  - publish_changeset
triggers:
  - "체인지셋"
  - "업데이트 셋"
  - "커밋"
  - "퍼블리시"
  - "changeset"
  - "update set"
  - "commit"
  - "publish"
---

# Instructions

You are managing an update set. This is a STAGED pipeline.

## GATE RULES

- GATE 1: Review contents before commit
- GATE 2: User confirms commit
- GATE 3: User confirms publish (optional)

## Pipeline

IF "만들기" or "create":
  CALL create_changeset(name=INPUT, description=INPUT_DESC, confirm="approve")
  → RETURN sys_id

IF "내용 확인" or "review":
  CALL get_changeset_details(changeset_id=INPUT)
  → SHOW included configuration records

IF "커밋" or "commit":
  GATE 1: CALL get_changeset_details(changeset_id=INPUT)
  → SHOW contents to user
  GATE 2: ASK "Commit this changeset?"
  → ONLY on confirm: CALL commit_changeset(changeset_id=INPUT, confirm="approve")

IF "퍼블리시" or "publish":
  GATE 3: ASK "Publish to remote?"
  → ONLY on confirm: CALL publish_changeset(changeset_id=INPUT, confirm="approve")

IF "목록" or "list":
  CALL list_changesets(state="in progress", limit=10)

## ON ERROR

- "already committed" → create new changeset
- Empty changeset → no configuration changes were made yet

## DELEGATE hint

DO NOT delegate. Requires user confirmation at gates.
