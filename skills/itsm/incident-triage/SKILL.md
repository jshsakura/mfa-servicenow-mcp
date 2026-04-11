---
name: incident-triage
version: 1.0.0
description: Triage incidents by priority, category, and assignment — query unassigned tickets, analyze, and route to the correct group
author: jshsakura
tags: [itsm, incident, triage, priority, assignment]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - list_incidents
    - get_incident_by_number
    - update_incident
    - add_comment
    - sn_aggregate
    - sn_query
complexity: beginner
estimated_time: 3-10 minutes
---

# Incident Triage

## Overview

Triage ServiceNow incidents — find unassigned or new tickets, analyze priority/category, and route to the appropriate assignment group.

**When to use:**
- "Show me unassigned high-priority incidents"
- "Triage this incident"
- "How many open P1s are there?"
- "Route this incident to the network team"

## Prerequisites

- **Roles:** `itil` or `incident_manager`
- **MCP Package:** `service_desk` or higher for write; `standard` for read

## Procedure

### Step 1: Find Incidents Needing Triage

```
Tool: list_incidents
Parameters:
  query: "active=true^assigned_toISEMPTY^priority<=2"
  limit: 20
```

Or get a quick count first:

```
Tool: sn_aggregate
Parameters:
  table: "incident"
  aggregate: "COUNT"
  query: "active=true^assigned_toISEMPTY"
```

### Step 2: Analyze a Specific Incident

```
Tool: get_incident_by_number
Parameters:
  number: "INC0010001"
```

Check:
- **Priority**: Is impact/urgency correctly set?
- **Category**: Does the short description match the assigned category?
- **Assignment group**: Is it blank or incorrect?

### Priority Matrix Reference

| Impact / Urgency | High (1) | Medium (2) | Low (3) |
|-------------------|----------|------------|---------|
| **High (1)** | P1 | P2 | P3 |
| **Medium (2)** | P2 | P3 | P4 |
| **Low (3)** | P3 | P4 | P5 |

### Step 3: Update and Route

```
Tool: update_incident
Parameters:
  incident_id: "<sys_id>"
  assignment_group: "Network Operations"
  category: "Network"
  priority: "2"
  confirm: "approve"
```

### Step 4: Add Triage Notes

```
Tool: add_comment
Parameters:
  incident_id: "<sys_id>"
  comment: "Triaged: Assigned to Network Operations based on VPN connectivity symptoms. Priority adjusted to P2 (High impact, Medium urgency)."
  comment_type: "work_note"
  confirm: "approve"
```

## Tips

- Start with `sn_aggregate` for a quick overview before diving into individual incidents
- Always add a work note explaining triage decisions — it helps the next person
- For bulk triage, use `list_incidents` with specific queries to batch similar tickets
