---
name: mfa-servicenow-skills
version: 2.0.0
author: jshsakura
description: Portal-specialized ServiceNow skills — LLM execution blueprints with safety gates, sub-agent delegation, and context optimization
---

# MFA ServiceNow Skills

Execution blueprints for AI agents working with ServiceNow portals. Not documentation — these are **pipelines** with mandatory safety gates, sub-agent delegation hints, and exact tool calls.

## Why Skills (vs raw tools)

| | Tools Only | Skills + Tools |
|---|---|---|
| Safety | LLM decides (운빨) | Gates enforced (diff→preview→confirm→apply) |
| Tokens | Source dumps in context | Delegate to sub-agent, summary only |
| Accuracy | LLM guesses tool order | Verified pipeline |
| Recovery | Might forget | diff_local_component before push + server-side version history |

## Skill Metadata

```yaml
context_cost: low|medium|high    # Token budget hint
safety_level: none|confirm|staged # Gate enforcement level
delegatable: true|false           # Can run in sub-agent
required_input: what user must provide
output: summary|report|diff|data|status|files|action|diagnosis
```

## Dry-Run Preview (write tools, v1.8.22+)

All mutating tools (update_*, delete_*, add_*, remove_*, reorder_*) accept
`dry_run=True`. When set, the tool issues only read-only Table/Aggregate API
calls and returns a structured preview — no side effects. Shape:

```
{
  "dry_run": true,
  "operation": "update"|"delete"|...,
  "target": {"table": "...", "sys_id": "..."},
  "target_found": bool,
  "proposed_changes": {"field": {"before": x, "after": y}},  # update
  "no_op_fields": [...],                                      # update
  "dependencies": {"activities": N, "versions": N},           # delete
  "warnings": [...],
  "precision_notes": {"count_source": "table_api", ...}
}
```

Recommended flow for any write: **dry_run=True → show diff → confirm=approve**.
Works under every auth type (basic/OAuth/API key/browser) — read-only APIs only.

## Cross-Scope Dep Auto-Resolve (v1.8.21+)

`download_app_sources(auto_resolve_deps=True)` (default) scans downloaded
sources and pulls referenced cross-scope records from global/other scopes:

- Script Includes — `new X()`, `gs.include('X')`, `new GlideAjax('X')`
- Widgets — `<sp-widget id="X">`, `$sp.getWidget('X')`
- Angular Providers — `$inject`, `angular.module(..., [...])`
- UI Macros — `<g:macro>` / `<g2:macro>` Jelly tags (excl. builtins)

Pulled records are saved into the same scope tree with `is_dependency: true`
in `_metadata.json`. Business rules / client scripts / UI actions are **not**
auto-resolved (table-bound, not referenced by name from code).

## Skill Index

Kept deliberately lean: only general, cross-tool playbooks remain. Single-tool
wrappers and feature-specific pipelines were dropped — tool descriptions and the
tools' own built-in safety gates cover those. **Enforcement lives in the tools,
not in skills** (skills are advisory; they can't be forced).

### analyze/ — Understand before you touch

| Skill | Cost | Delegatable | Trigger Examples |
|-------|------|-------------|-----------------|
| [local-source-audit](analyze/local-source-audit.md) | low | yes | "로컬 검수", "dead code", "cross reference" |

### manage/ — CRUD and operations

| Skill | Cost | Safety | Trigger Examples |
|-------|------|--------|-----------------|
| [app-source-download](manage/app-source-download.md) | high | yes | "앱 소스 다운로드", "전체 소스 받아", "포털 소스 백업" |
| [local-sync](manage/local-sync.md) | low | **staged** | "로컬 동기화", "push local changes" |

### explore/ — Discover and navigate

| Skill | Cost | Delegatable | Trigger Examples |
|-------|------|-------------|-----------------|
| [flow-trigger-tracing](explore/flow-trigger-tracing.md) | medium | yes | "트리거 추적", "what runs on this table" |

## Workflow Chains

### Offline Analysis Pipeline
`manage/app-source-download` → `analyze/local-source-audit` → *(review HTML report)*

### Local Edit Pipeline
`manage/app-source-download` → *(edit locally)* → `manage/local-sync`
