# Tool Consolidation Plan

## Status

| Phase | Description | Status | Released |
|---|---|---|---|
| 1 | New primitives — `sn_write`, `sn_resolve_url` | ✅ done | v1.9.11 |
| 2 | First 3 manage_X (incident, change, kb_article) | ✅ done | v1.9.12 |
| 3a-d | manage_changeset / script_include / workflow / user / group | ✅ done | v1.9.13 |
| 3e-g | manage_catalog / portal_layout / portal_component / ui_policy | ✅ done | v1.9.14 |
| — | manage_agile | 🚫 deferred (orphan domain) | — |
| 4.0 | Remove duplicate wrappers + extract services (165 → 106) | ⏳ planned | per-domain, v1.10.x |
| 4.5 | Fold read tools into existing manage_X (opt-in per domain, 106 → up to ~70) | ⏳ planned | per-domain, v1.10.x → v1.11.x |
| 4.7 | New manage_X for loose domains (opt-in per domain, ~70 → up to ~50) | ⏳ planned | v1.11.x → v1.12.x |
| 5 | Skills overhaul | ⏳ planned | after Phase 4.7 |

Tests at v1.9.14: **2017 passed, 5 skipped**. No regressions.

## Goal

The real problem is **duplicates**, not raw tool count. 165 tools today contains ~59 wrappers that are 1:1 redundant with `manage_X` — that's the noise the LLM picks through on every request. Kill that noise and the surface is already healthy at ~106.

Sub-phase targets:
- **Phase 4.0 (mandatory)**: 165 → 106 — remove duplicate wrappers + extract services. **This is the binding goal.**
- **Phase 4.5 (opt-in per domain)**: 106 → up to ~70 — fold read tools into `manage_X` only where the NL benchmark shows zero regression. If a domain's reads are fine as standalones, leave them.
- **Phase 4.7 (opt-in per domain)**: ~70 → up to ~50 — new `manage_X` for currently-loose domains only when the bundle clearly improves LLM selection. If forcing a domain into a bundle muddies the LLM's choice, keep the standalones.

Domain knowledge (table names, mandatory fields, valid actions) stays baked into each `manage_X` tool — the LLM never has to call `sn_schema` first to discover what to send.

Strategy in one line: push the `manage_X` pattern only as far as it clearly helps LLM selection — never collapse across domains, never consolidate past the point of diminishing return. Verb-style routers (`sn_create(target=...)`) are explicitly out of scope (see below).

Constraints (non-negotiable):
- **NL latency must not regress.** Each common action stays at 1 MCP round-trip.
- **Standard package stays safe by default.** No new write capability leaks into standard via consolidation.
- **Confirm-on-write gate stays intact.** Every write action requires `confirm='approve'`.
- **Live-safe rollout.** Staged per domain (one minor release per domain), not big-bang. Each PR ships behavior-preserving response-shape snapshots so live LLM consumers see no diff.
- **Read-action consolidation never bundled with write-wrapper removal in the same PR.** Different blast radii, different release cadence.

## Absolute rules (LLM-clarity-preserving)

These are gates, not aspirations. Any consolidation that violates one is rolled back, regardless of token savings.

1. **Domain boundaries are sacred.** `manage_X` always covers exactly one domain. No `manage_record(target=...)`, no `manage_itsm`, no cross-domain dispatch.
2. **Bundle names point at the domain directly.** `manage_incident` ✅. `manage_workflow_things` ❌. The name is the LLM's primary signal for tool selection.
3. **Action count per bundle ≤ ~10.** If a domain naturally needs more, that domain is too big and should be split, not crammed.
4. **Read and write actions can coexist in one `manage_X`,** but `MANAGE_READ_ACTIONS` must list every read action exactly so the confirm gate routes correctly.
5. **Every consolidation step gates on an NL benchmark.** Per domain, 5-10 representative prompts. Pass criteria: LLM picks the right action on first try, completes in 1 round-trip. Fail → revert that step.
6. **When in doubt, keep the tool.** Tool count reduction is a side effect of removing duplicates, not a goal in itself. An extra tool that helps the LLM choose correctly is cheaper than a "cleaner" surface where the LLM hesitates. The "~50" number is a ceiling we'd accept if everything works — never a number to chase past clarity.

## Tool surface today (v1.9.15)

12 `manage_X` bundles + 2 new primitives + all original orchestrators + duplicate legacy wrappers scheduled for removal from the public MCP registry in Phase 4.

| Bundle | Actions | Read-actions (no confirm) |
|---|---|---|
| `manage_incident` | create / update / comment / resolve | — |
| `manage_change` | create / update / add_task | — |
| `manage_kb_article` | create / update / publish | — |
| `manage_changeset` | create / update / commit / publish / add_file | — |
| `manage_script_include` | create / update / delete / execute | — |
| `manage_workflow` | workflow + activity CRUD (9 actions) | — |
| `manage_user` | create / update / get / list | get, list |
| `manage_group` | create / update / list / add_members / remove_members | list |
| `manage_catalog` | category/item/variable CRUD + move (6 actions) | — |
| `manage_portal_layout` | page CRUD + container/row/column + widget instance (7 actions) | — |
| `manage_portal_component` | widget/provider/header_footer/theme/ng_template/ui_page + update_code (7 actions) | — |
| `manage_ui_policy` | create / add_action | — |

**Primitives** (`sn_query`, `sn_aggregate`, `sn_schema`, `sn_discover`, `sn_health`, `sn_nl`, `sn_write`, `sn_resolve_url`) — 8 tools.

**Orchestrators preserved** (multi-query, joins, state machines, bulk loops, pipelines): change-detail/approve/reject/submit-for-approval, changeset-detail, incident-by-number, workflow detail/versions/activities/reorder, all flow-designer tools, all portal analysis/dependency/scaffold/edit-pipeline tools, all source/audit/download tools, dev-productivity tools, sync tools, logs.

## Phase 4 — Three-stage tool-surface compression (165 → ~50)

Phase 4 splits into three sub-phases (4.0 / 4.5 / 4.7) that each ship independently, **one domain per minor release**. No big-bang. Each sub-phase has its own blast radius, its own validation gate, and its own release cadence.

| Sub-phase | Goal | Tool count | Risk | Release cadence |
|---|---|---|---|---|
| 4.0 | Remove duplicate wrappers + extract services | 165 → 106 | low (1:1 redundant w/ manage_X) | per-domain, v1.10.x |
| 4.5 | Fold read tools (`get_X`, `list_X`, search) into existing `manage_X` | 106 → ~70 | medium (touches `standard` package surface) | per-domain, v1.10.x → v1.11.x |
| 4.7 | New `manage_X` for currently-loose domains | ~70 → ~50 | medium-high (orchestrator semantics) | v1.11.x → v1.12.x |

### Phase 4.0 — Duplicate wrapper removal + service extraction

Most `manage_X` dispatchers currently call legacy wrapper functions for their real API logic. Phase 4.0 moves that logic into domain services, then deletes the public wrapper functions:

1. Create small domain service modules/classes for reusable API logic, for example `incident_service.create(...)`, `catalog_service.update_item(...)`, and `portal_layout_service.create_page(...)`.
2. Move implementation bodies from duplicate legacy wrappers into those services with behavior-preserving tests **including response-shape snapshots** so live LLM consumers see no diff.
3. Update `manage_X` dispatchers and internal cross-module callers to call service functions directly.
4. Delete duplicate legacy wrapper functions, their `@register_tool` decorators, and no-longer-needed per-wrapper params classes.
5. Remove old public names from package YAML and regenerated tool indexes.
6. Rewrite skills/docs/README/website examples in **the same PR as the deletion** so docs are never out of sync with the registered surface.

Temporary `_..._impl` helpers are acceptable only as a short-lived checkpoint inside a domain migration. They are not the desired end state.

#### Duplicate registered wrappers to remove (59 tools)

```
# Bundled into manage_incident
create_incident, update_incident, add_comment, resolve_incident

# Bundled into manage_change
create_change_request, update_change_request, add_change_task

# Bundled into manage_kb_article
create_article, update_article, publish_article

# Bundled into manage_changeset
create_changeset, update_changeset, add_file_to_changeset,
commit_changeset, publish_changeset

# Bundled into manage_script_include
create_script_include, update_script_include,
delete_script_include, execute_script_include

# Bundled into manage_workflow
create_workflow, update_workflow, activate_workflow, deactivate_workflow,
delete_workflow, add_workflow_activity, update_workflow_activity,
delete_workflow_activity, reorder_workflow_activities

# Bundled into manage_user / manage_group
create_user, update_user, get_user, list_users,
create_group, update_group, list_groups, add_group_members, remove_group_members

# Bundled into manage_catalog
create_catalog_category, update_catalog_category, update_catalog_item,
move_catalog_items, create_catalog_item_variable, update_catalog_item_variable

# Bundled into manage_portal_layout
create_widget_instance, update_widget_instance, update_page,
create_page, create_container, create_row, create_column

# Bundled into manage_portal_component
create_widget, create_angular_provider, create_header_footer,
create_css_theme, create_ng_template, create_ui_page,
update_portal_component

# Bundled into manage_ui_policy
create_ui_policy, create_ui_policy_action
```

#### Standalone tools to preserve (Phase 4.0 — Phase 4.5/4.7 may revisit)

Do **not** remove tools that are not 1:1 duplicates of a `manage_X` action. These stay registered through Phase 4.0:

- Change lifecycle: `submit_change_for_approval`, `approve_change`, `reject_change` — multi-query state transitions; revisit as `manage_change` actions in Phase 4.5 only if NL benchmark confirms 1 round-trip.
- Flow Designer: `update_flow_designer` — revisit in Phase 4.7 under `manage_flow_designer`.
- Knowledge taxonomy: `create_knowledge_base`, KB `create_category`.
- Portal orchestration/safety: `scaffold_page`, `route_portal_component_edit`, `analyze_portal_component_update`, `create_portal_component_snapshot`, `preview_portal_component_update`, `update_portal_component_from_snapshot` — entire pipeline becomes `manage_portal_pipeline` in Phase 4.7.
- Local sync: `update_remote_from_local` — revisit in Phase 4.7 under `manage_sync`.
- Generic primitives: `sn_write` and read/search/detail tools that are not directly represented by `manage_X` actions.

#### Phase 4.0 acceptance
- [ ] Each `manage_X` action still works after the corresponding wrapper function is deleted (`pytest tests/test_manage_*.py`).
- [ ] No internal import points at the old public wrapper name; cross-module imports use domain service functions.
- [ ] Service-layer tests cover the extracted behavior formerly tested through wrapper functions.
- [ ] Response-shape snapshots match pre-extraction output (no silent JSON-key renames).
- [ ] No skill / docs / README / changelog mentions a deleted name.
- [ ] **CI gate added**: scan skills/docs for any tool name not in the live registry; fail the build on orphan refs. (Moved here from Phase 5 — must exist before any deletion ships.)
- [ ] Tool count = 106 after Phase 4.0 completes across all 12 domains.

### Phase 4.5 — Read-action consolidation (opt-in per domain, 106 → up to ~70)

Fold per-domain read tools (`get_X`, `list_X`, search) into the existing `manage_X` as read actions, **but only where it clearly helps LLM selection**. Pattern already proven on `manage_user` / `manage_group`. For each domain, decide *before* starting:

- ✅ **Consolidate** if standalone reads have generic names that compete with `manage_X` for LLM attention (multiple ways to "get incident X").
- ❌ **Skip** if standalone reads have unique purposes the LLM already routes to correctly (e.g. orchestrators that join across tables, `_by_number` shortcuts).

If you skip a domain, log the reason in the per-domain release notes. Don't force consolidation just to hit ~70.

Per-domain process — **always two PRs, never one**:

1. **PR-A (additive)**: Add `get` / `list` / (optionally `search`) actions to the relevant `manage_X` Pydantic action enum.
2. **PR-A**: Extend `MANAGE_READ_ACTIONS` map in `server.py` so the confirm gate skips `confirm='approve'` for read actions.
3. **PR-A**: Wire the read action body to the same data layer the standalone `get_X` / `list_X` already use (no new query code).
4. **PR-A**: Run NL benchmark for the domain (5-10 prompts including pure-read prompts). Merge.
5. **PR-B (subtractive, separate release)**: Remove the standalone `get_X` / `list_X` tools and update `tool_packages.yaml` / `_module_index.py`.

The split is mandatory because read tools live in the `standard` package — removing them changes the read-only consumer surface, which is a separate blast radius from PR-A.

#### Phase 4.5 acceptance
- [ ] Every `manage_X` covers all reads its domain previously exposed via standalone tools.
- [ ] `MANAGE_READ_ACTIONS` lists every read action; confirm-gate test passes for each.
- [ ] `standard` package YAML still serves read-only consumers via `manage_X` (no write actions leaked).
- [ ] NL benchmark per domain shows no round-trip regression on read prompts.
- [ ] Tool count = ~70 after Phase 4.5 completes.

### Phase 4.7 — New `manage_X` for currently-loose domains (opt-in per domain, ~70 → up to ~50)

Domains currently spread across many standalone tools **may** become new `manage_X` bundles — only when the bundle clearly improves LLM selection. Each candidate is a hypothesis, not a commitment.

Candidates to evaluate:
- `manage_flow_designer` — Flow Designer CRUD + activate/publish/version actions
- `manage_portal_pipeline` — scaffold/route/analyze/snapshot/preview/update (already a clear pipeline)
- `manage_source` — source/download tools
- `manage_audit` — audit tools
- `manage_sync` — local sync tools

Per candidate: extract service → add `manage_X` dispatcher → snapshot tests → NL benchmark. **Only if the benchmark passes** do you ship the bundle and remove standalones. If the LLM gets lost choosing between actions, abandon the bundle and keep standalones registered. Landing at 60 tools with high accuracy beats 50 with confusion.

#### Phase 4.7 acceptance
- [ ] Each new `manage_X` passes all five absolute rules.
- [ ] No multi-query orchestrator silently changes round-trip count (snapshot + NL benchmark verify).
- [ ] Tool count ≈ 50 after Phase 4.7 completes.

## Phase 5 — Skills overhaul (post-Phase 4.7)

Phase 4 sub-phases each include the mechanical tool-name rewrite for any skill that references a removed wrapper (and the CI gate from Phase 4.0 enforces this). Phase 5 is the deeper skill-model cleanup after the public tool surface is already minimal.

### Layer reorganization

| Layer | Purpose | Examples |
|---|---|---|
| `skill://workflow/*` | end-to-end scenarios | mfa-request-handling, change-approval-flow |
| `skill://domain/*` | per-domain manage_X usage | incident-ops, portal-edit-pipeline, flow-designer-analysis |
| `skill://custom-tables/*` | customer-fork-only (empty in upstream) | e.g. `x_acme_request.md` |
| `skill://debugging/*` | troubleshooting | mfa-login-stuck, processflow-fails |

### Phase 5 work items
1. Reorg files into the 4-layer directory structure.
2. Add `suggested_skill` URI to `sn_resolve_url` output. URL → table → suggested skill → LLM auto-pulls.
3. Document the **private-fork pattern** for `custom-tables/*`: customers add their own `x_<co>_*.md` skills in their fork; upstream stays empty.

## Custom tables

`manage_X` covers OOTB tables only. Customer-specific tables (`x_<vendor>_<scope>_<name>`, `u_*`) use:

```
LLM intent: "create a record in x_acme_request"
  → sn_schema("x_acme_request")     # one-time discovery (sn_query_page cache, 30s TTL)
  → sn_write(table="x_acme_request", action="create", fields={...})
```

First call pays one extra `sn_schema` round-trip. Subsequent calls hit the schema cache and execute in one round-trip — same as a manage_X. LLM general knowledge (sys_id, dictionary types, naming conventions) handles the rest.

For org-specific data models that need LLM-side guidance, customers add private `skill://custom-tables/*` resources in their fork.

## Documentation strategy

Two layers with strict cost-discipline on the always-loaded surface:

1. **Always-loaded (every request, billed every time)**: tool descriptions + JSON schemas only. Capped: tool ≤ 120 chars, param ≤ 80 chars. No tutorials, no domain primers, no enum-as-prose.
2. **On-demand (LLM pulls when needed)**:
   - `sn_schema(table)` — live field metadata
   - `sn_discover(keyword)` — table-name fuzzy search
   - MCP `resources` (skills) — workflow guides, custom-table primers

Off-limits: baking comprehensive ServiceNow knowledge into tool descriptions. The LLM already knows OOTB tables and GlideRecord patterns from training; reproducing that is pure waste.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Service extraction silently changes response shape (JSON-key renames, error-message format drift) | Behavior-preserving snapshot tests captured pre-extraction, asserted post-extraction. Required in every Phase 4.0 PR. |
| Removed-tool name still called by live LLM consumer | CI gate scans skills/docs for orphan refs before any deletion ships; runtime returns a structured error pointing at the `manage_X(action=...)` replacement. |
| Per-action required-field validation gets ugly | Pydantic `model_validator(mode='after')` with one validator per action — already in place across all 12 bundles. |
| Confirm gate misses manage_X with read action | `MANAGE_READ_ACTIONS` map already declared in `server.py`; tested for `manage_user`/`manage_group`; Phase 4.5 extends to all bundles. |
| `sn_write` abused on dangerous tables | Hard-coded `SN_WRITE_DENY_TABLES` (no env override); test asserts denylist intact. |
| Token budget regression on tool description | Each manage_X description capped at 120 chars; per-action `Literal[...]` replaces prose. |
| Read-tool removal breaks `standard` package consumers | Read-action consolidation (PR-A) ships and bakes for one release before removal (PR-B). |
| Cross-domain service circular imports during extraction | Services live in `services/<domain>.py`; cross-domain calls go through a thin facade or are refactored as data-only handoffs. |

## Out of scope

- URL routing intelligence beyond regex parsing — defer to LLM (sn_resolve_url returns suggestion, LLM dispatches)
- Field-level allowlists per role — rejected as over-engineering in earlier discussion
- Audit log to ServiceNow side — relies on existing `sys_audit`
- Junior/lead package split — `standard` (read-only) vs `full` (everything) is the clean line
- `manage_agile` — orphan domain, no tools currently in any package, zero LLM-token win from bundling
- **Verb-style routers** (e.g. `sn_create(target=...)`, `sn_do(intent=...)`) — collapsing across domain boundaries breaks the LLM's strongest tool-selection signal (the bundle name itself). Token savings don't justify the accuracy regression on a live system. Revisit only if a non-live migration window opens AND a NL benchmark proves the current `manage_X` surface is the binding constraint.

## Acceptance (final, post-Phase 4.0/4.5/4.7 + 5)

- All tests pass (currently 2017 at v1.9.14)
- Full-package schema bytes ≤ 50% of pre-consolidation baseline (target: 10K tokens; achieved at v1.9.14)
- NL benchmark: each representative prompt (create incident, find change by number, publish KB, scaffold portal page, get widget bundle) completes in ≤ 1 extra MCP round-trip vs. baseline
- `manage_X` tools have ≥ 90% test coverage (per-action happy path + invalid-action + missing-required) — already met at v1.9.14
- No tool description exceeds 120 chars; no param description exceeds 80 chars
- No skill or doc references a deleted legacy tool name (CI-enforced from Phase 4.0)
- Tool count: 165 → 106 (Phase 4.0, mandatory) → 70-90 (Phase 4.5, opt-in per domain) → 50-70 (Phase 4.7, opt-in per domain). Final landing point is wherever LLM accuracy is highest, not a fixed number.
