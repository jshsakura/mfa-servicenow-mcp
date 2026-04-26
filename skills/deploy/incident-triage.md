---
name: incident-triage
description: Triage incidents — find unassigned, analyze priority, route to correct group
context_cost: low
safety_level: confirm
delegatable: false
required_input: incident number or query
output: action
tools:
  - manage_incident
  - sn_aggregate
triggers:
  - "인시던트 분류"
  - "미배정 인시던트"
  - "P1 몇 개"
  - "triage incident"
  - "unassigned incidents"
  - "how many P1s"
---

# Instructions

You are triaging ServiceNow incidents.

## Pipeline

IF "몇 개" or "count":
  CALL sn_aggregate(table="incident", aggregate="COUNT", query="active=true^assigned_toISEMPTY")
  → RETURN count

IF "목록" or "list unassigned":
  CALL manage_incident(action="get", query="active=true^assigned_toISEMPTY^priority<=2", limit=20)
  → RETURN list sorted by priority

IF "분석" or "analyze specific":
  CALL manage_incident(action="get", incident_id=INPUT)
  → CHECK: priority correct per impact/urgency matrix?
  → CHECK: category matches short_description keywords?
  → CHECK: assignment group appropriate?
  → RETURN: analysis with recommendations

IF "배정" or "route":
  CALL manage_incident(action="update", ...)
    - incident_id, assignment_group, category, priority
    - confirm = "approve"
  CALL manage_incident(action="comment", ...)
    - incident_id, comment = triage justification, is_work_note = True
    - confirm = "approve"

## Priority Matrix

| Impact / Urgency | High (1) | Medium (2) | Low (3) |
|-------------------|----------|------------|---------|
| High (1) | P1 | P2 | P3 |
| Medium (2) | P2 | P3 | P4 |
| Low (3) | P3 | P4 | P5 |

## ON ERROR

- "Incident not found" → check number format (INC0010001)
- No unassigned → queue is clean

## DELEGATE hint

DO NOT delegate. Routing requires user judgment and confirmation.
