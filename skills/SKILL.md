---
name: mfa-servicenow-skills
version: 1.0.0
author: jshsakura
description: MFA-first ServiceNow skills — portal-specialized workflow recipes for AI agents, built on 98 MCP tools
tags:
  - servicenow
  - mfa
  - portal
  - skills
  - mcp
---

# MFA ServiceNow Skills

Workflow recipes that teach AI agents how to perform multi-step ServiceNow tasks. Each skill combines multiple MCP tools into a structured procedure.

**MCP = Tools (what you can do). Skills = Recipes (how to do it well).**

## Skill Format

Each skill is a `SKILL.md` file with YAML frontmatter and markdown body:

```yaml
---
name: skill-name
version: 1.0.0
description: One-line description
author: jshsakura
tags: [category, relevant, tags]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - tool_name_1
    - tool_name_2
complexity: beginner | intermediate | advanced
estimated_time: X-Y minutes
---

# Skill Title
## Overview — when to use
## Prerequisites — roles, packages
## Procedure — step-by-step with tool calls
## Tips — practical advice
```

## Available Skills

### Portal (6 skills)

| Skill | Description | Complexity |
|-------|-------------|------------|
| [widget-analysis](portal/widget-analysis/SKILL.md) | Analyze widget dependency tree | Beginner |
| [widget-patching](portal/widget-patching/SKILL.md) | Safe snapshot-preview-apply edit workflow | Intermediate |
| [portal-diagnosis](portal/portal-diagnosis/SKILL.md) | Full portal health check | Intermediate |
| [route-tracing](portal/route-tracing/SKILL.md) | Map navigation routes, find dead links | Beginner |
| [source-download](portal/source-download/SKILL.md) | Export sources to local files | Beginner |
| [code-detection](portal/code-detection/SKILL.md) | Find missing conditional branches | Intermediate |

### Development (4 skills)

| Skill | Description | Complexity |
|-------|-------------|------------|
| [script-include-management](development/script-include-management/SKILL.md) | Script include CRUD + GlideAjax execution | Beginner |
| [code-review](development/code-review/SKILL.md) | Search and audit server-side code | Intermediate |
| [changeset-workflow](development/changeset-workflow/SKILL.md) | Update set create → commit → publish | Intermediate |
| [dependency-analysis](development/dependency-analysis/SKILL.md) | Map artifact dependencies | Intermediate |

### ITSM (3 skills)

| Skill | Description | Complexity |
|-------|-------------|------------|
| [incident-triage](itsm/incident-triage/SKILL.md) | Classify, prioritize, and route incidents | Beginner |
| [change-lifecycle](itsm/change-lifecycle/SKILL.md) | Change request full lifecycle | Intermediate |
| [knowledge-authoring](itsm/knowledge-authoring/SKILL.md) | Create and publish KB articles | Beginner |

### Admin (3 skills)

| Skill | Description | Complexity |
|-------|-------------|------------|
| [health-check](admin/health-check/SKILL.md) | Instance connectivity and auth verification | Beginner |
| [schema-discovery](admin/schema-discovery/SKILL.md) | Explore tables and field definitions | Beginner |
| [developer-activity](admin/developer-activity/SKILL.md) | Track developer changes and uncommitted work | Beginner |

## Differences from Other Skill Libraries

This library is designed specifically for the `mfa-servicenow-mcp` tool set:

- **MFA-first**: Skills assume browser-based MFA authentication as the primary auth mode
- **Portal-specialized**: 6 out of 16 skills focus on Service Portal development — the deepest coverage available
- **Real tool references**: Every `Tool:` block uses actual MCP tool names and parameters, not generic placeholders
- **End-to-end workflows**: Skills chain tools together (e.g., detect → snapshot → patch → verify → commit)
- **Safety built-in**: Write operations always include `confirm: "approve"` and snapshot/rollback guidance
