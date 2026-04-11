---
name: changeset-workflow
version: 1.0.0
description: End-to-end changeset lifecycle — create, add files, review, commit, and publish update sets
author: jshsakura
tags: [development, changeset, update-set, commit, publish, deployment]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - list_changesets
    - create_changeset
    - get_changeset_details
    - add_file_to_changeset
    - update_changeset
    - commit_changeset
    - publish_changeset
complexity: intermediate
estimated_time: 5-15 minutes
---

# Changeset Workflow

## Overview

Manage the full update set lifecycle — create a changeset, add configuration files, review contents, commit, and publish for deployment.

**When to use:**
- "Create an update set for my changes"
- "What's in this changeset?"
- "Commit and publish this update set"
- "Move changes from dev to test"

## Prerequisites

- **Roles:** `admin` or update set manager role
- **MCP Package:** `portal_developer` or higher

## Procedure

### Step 1: List Existing Changesets

```
Tool: list_changesets
Parameters:
  state: "in progress"
  limit: 10
```

### Step 2: Create New Changeset

```
Tool: create_changeset
Parameters:
  name: "FEAT-1234 Add company code branch"
  description: "Adds 2J00 company code handling to benefits widget"
  confirm: "approve"
```

### Step 3: Make Changes

Use other tools to modify widgets, script includes, etc. ServiceNow automatically tracks changes in the current update set.

### Step 4: Review Contents

```
Tool: get_changeset_details
Parameters:
  changeset_id: "<changeset sys_id>"
```

Review the list of included configuration records.

### Step 5: Commit

```
Tool: commit_changeset
Parameters:
  changeset_id: "<changeset sys_id>"
  confirm: "approve"
```

### Step 6: Publish (Optional)

Push to remote instance or make available for retrieval.

```
Tool: publish_changeset
Parameters:
  changeset_id: "<changeset sys_id>"
  confirm: "approve"
```

## Tips

- Always review changeset contents before committing (Step 4)
- Name changesets with ticket IDs for traceability
- One logical change per changeset — avoid mixing unrelated modifications
- Combine with the `widget-patching` skill: create changeset → patch widget → commit
