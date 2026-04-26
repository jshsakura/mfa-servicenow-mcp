---
name: skill-management
description: Create, update, list, and validate skill pipeline definitions
context_cost: low
safety_level: confirm
delegatable: false
required_input: action (list, read, create, update, validate)
output: action
tools: []
triggers:
  - "스킬 목록"
  - "스킬 업데이트"
  - "스킬 만들어"
  - "파이프라인 수정"
  - "list skills"
  - "update skill"
  - "create skill"
  - "fix skill pipeline"
---

# Instructions

You are managing the skill pipeline definitions that guide LLM behavior.
Skills are markdown files in `skills/<category>/` — no MCP tools needed, only file read/write.

## Skill Location

```
skills/
  SKILL.md              ← Master index (MUST stay in sync)
  analyze/              ← Understand before you touch
  fix/                  ← Modify with safety gates
  manage/               ← CRUD and operations
  deploy/               ← Release and operations
  explore/              ← Discover and navigate
```

## Mode Selection

| Action | Trigger | Steps |
|--------|---------|-------|
| List | "스킬 목록", "list skills" | Read SKILL.md, display index table |
| Read | "스킬 보여줘 <name>" | Read the skill file, show pipeline |
| Create | "스킬 만들어" | Template → fill → validate → write → update index |
| Update | "스킬 수정" | Read current → modify → validate → write → update index |
| Validate | "스킬 검증" | Check all skills for format compliance |

## Pipeline: List

1. READ `skills/SKILL.md`
2. RETURN: formatted skill index table

## Pipeline: Read

1. IDENTIFY target skill from user input
2. READ `skills/<category>/<name>.md`
3. RETURN: frontmatter metadata + pipeline summary

## Pipeline: Create

1. ASK: skill name, category, description, triggers
2. IDENTIFY which MCP tools the skill will use
3. GENERATE skill file using the template below
4. VALIDATE format
5. WRITE to `skills/<category>/<name>.md`
6. UPDATE `skills/SKILL.md` index table
7. CONFIRM with user

## Pipeline: Update

1. READ the target skill file
2. SHOW current content to user
3. ASK what to change (pipeline, triggers, tools, description)
4. APPLY changes preserving frontmatter structure
5. VALIDATE format
6. WRITE updated file
7. UPDATE `skills/SKILL.md` if description or triggers changed
8. CONFIRM with user

## Pipeline: Validate

1. SCAN all `skills/**/*.md` files (exclude SKILL.md, _*)
2. FOR EACH skill file:
   - CHECK frontmatter has: name, description, context_cost, safety_level, delegatable, required_input, output, tools, triggers
   - CHECK context_cost is one of: low, medium, high
   - CHECK safety_level is one of: none, confirm, staged
   - CHECK delegatable is true or false
   - CHECK output is one of: summary, report, diff, data, status, files, action, diagnosis
   - CHECK tools list contains only registered MCP tool names
   - CHECK body has: # Instructions, ## Pipeline (or ## Mode Selection)
   - CHECK SKILL.md index contains this skill
3. RETURN: validation report with pass/fail per skill

## Skill File Template

```markdown
---
name: <kebab-case-name>
description: <one-line description>
context_cost: low|medium|high
safety_level: none|confirm|staged
delegatable: true|false
required_input: <what user provides>
output: summary|report|diff|data|status|files|action|diagnosis
tools:
  - <tool_name_1>
  - <tool_name_2>
triggers:
  - "<korean trigger>"
  - "<english trigger>"
---

# Instructions

You are <concise role statement>.

## Pipeline

<step-by-step pipeline with CALL, IF, RETURN blocks>

## ON ERROR

<error handling guidance>

## DELEGATE hint

<delegation guidance>
```

## Frontmatter Field Rules

| Field | Type | Values | Required |
|-------|------|--------|----------|
| name | string | kebab-case, matches filename | yes |
| description | string | one-line, max 100 chars | yes |
| context_cost | enum | low, medium, high | yes |
| safety_level | enum | none, confirm, staged | yes |
| delegatable | boolean | true, false | yes |
| required_input | string | what user must provide | yes |
| output | enum | summary, report, diff, data, status, files, action, diagnosis | yes |
| tools | list | registered MCP tool names | yes (can be empty) |
| triggers | list | Korean + English trigger phrases | yes |

## SKILL.md Index Format

Each skill appears in the category table:

```markdown
| [skill-name](category/skill-name.md) | cost | delegatable/safety | "trigger1", "trigger2" |
```

## ON ERROR

- Frontmatter parse error → check for tab/space inconsistency
- Missing tool in tools list → verify tool exists in tool_packages.yaml
- SKILL.md out of sync → regenerate the category table row

## DELEGATE hint

NOT delegatable. Skill management requires human confirmation for changes.
