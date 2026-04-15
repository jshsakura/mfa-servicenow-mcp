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
| Safety | LLM decides (운빨) | Gates enforced (snapshot→preview→apply) |
| Tokens | Source dumps in context | Delegate to sub-agent, summary only |
| Accuracy | LLM guesses tool order | Verified pipeline |
| Rollback | Might forget | Snapshot mandatory |

## Skill Metadata

```yaml
context_cost: low|medium|high    # Token budget hint
safety_level: none|confirm|staged # Gate enforcement level
delegatable: true|false           # Can run in sub-agent
required_input: what user must provide
output: summary|report|diff|data|status|files|action
```

## Skill Index

### analyze/ — Understand before you touch

| Skill | Cost | Delegatable | Trigger Examples |
|-------|------|-------------|-----------------|
| [widget-analysis](analyze/widget-analysis.md) | medium | yes | "위젯 분석", "what does this widget do" |
| [portal-diagnosis](analyze/portal-diagnosis.md) | high | yes | "포탈 진단", "portal health check" |
| [provider-audit](analyze/provider-audit.md) | medium | yes | "프로바이더 감사", "find unused providers" |
| [dependency-analysis](analyze/dependency-analysis.md) | medium | yes | "지워도 돼?", "what depends on this" |
| [code-detection](analyze/code-detection.md) | medium | yes | "누락된 조건", "missing branches" |
| [local-source-audit](analyze/local-source-audit.md) | low | yes | "로컬 검수", "dead code", "cross reference" |
| [esc-page-audit](analyze/esc-page-audit.md) | high | yes | "ESC 구조", "audit ESC" |

### fix/ — Modify with safety gates

| Skill | Cost | Safety | Trigger Examples |
|-------|------|--------|-----------------|
| [widget-patching](fix/widget-patching.md) | medium | **staged** | "코드 수정", "fix widget" |
| [widget-debugging](fix/widget-debugging.md) | high | none | "위젯이 안 돼", "debug widget" |
| [code-review](fix/code-review.md) | medium | none | "보안 검사", "code review" |

### manage/ — CRUD and operations

| Skill | Cost | Safety | Trigger Examples |
|-------|------|--------|-----------------|
| [page-management](manage/page-management.md) | low | confirm | "위젯 배치", "page layout", "페이지 생성", "scaffold page" |
| [script-include-management](manage/script-include-management.md) | low | confirm | "SI 보여줘", "execute GlideAjax" |
| [source-download](manage/source-download.md) | high | none | "소스 내보내기", "download sources" |
| [changeset-workflow](manage/changeset-workflow.md) | low | **staged** | "체인지셋 커밋", "publish" |
| [app-source-download](manage/app-source-download.md) | high | yes | "앱 소스 다운로드", "전체 소스 받아" |
| [skill-management](manage/skill-management.md) | low | confirm | "스킬 업데이트", "update skill" |
| [local-sync](manage/local-sync.md) | low | **staged** | "로컬 동기화", "push local changes" |
| [workflow-management](manage/workflow-management.md) | low | **staged** | "워크플로우 수정", "edit workflow" |

### deploy/ — Release and operations

| Skill | Cost | Safety | Trigger Examples |
|-------|------|--------|-----------------|
| [change-lifecycle](deploy/change-lifecycle.md) | low | **staged** | "변경 요청", "approve change" |
| [incident-triage](deploy/incident-triage.md) | low | confirm | "인시던트 분류", "triage" |

### explore/ — Discover and navigate

| Skill | Cost | Delegatable | Trigger Examples |
|-------|------|-------------|-----------------|
| [health-check](explore/health-check.md) | low | no | "연결 확인", "health check" |
| [schema-discovery](explore/schema-discovery.md) | low | yes | "테이블 찾기", "show fields" |
| [route-tracing](explore/route-tracing.md) | medium | yes | "어디로 이동", "find dead links" |
| [esc-catalog-flow](explore/esc-catalog-flow.md) | high | yes | "ESC 카탈로그", "catalog flow" |
| [flow-trigger-tracing](explore/flow-trigger-tracing.md) | medium | yes | "트리거 추적", "what runs on this table" |

## Workflow Chains

### Bug Fix Pipeline
`explore/health-check` → `fix/widget-debugging` → `analyze/widget-analysis` → `fix/widget-patching` → `manage/changeset-workflow`

### Code Audit Pipeline
`analyze/portal-diagnosis` → `analyze/provider-audit` → `analyze/code-detection` → `fix/code-review`

### New Feature Pipeline
`analyze/widget-analysis` → `analyze/dependency-analysis` → `fix/widget-patching` → `manage/changeset-workflow` → `deploy/change-lifecycle`

### Full App Audit Pipeline
`manage/app-source-download` → `analyze/local-source-audit` → *(review HTML report)* → `fix/code-review`

### Local Edit Pipeline
`manage/source-download` → *(edit locally)* → `manage/local-sync` → `manage/changeset-workflow` → `deploy/change-lifecycle`

### ESC Customization Pipeline
`analyze/esc-page-audit` → `explore/esc-catalog-flow` → `analyze/widget-analysis` → `fix/widget-patching`
