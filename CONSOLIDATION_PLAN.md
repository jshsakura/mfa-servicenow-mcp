# Tool Consolidation Plan

## Status

| Phase | Description | Status | Released |
|---|---|---|---|
| 1 | New primitives — `sn_write`, `sn_resolve_url` | ✅ done | v1.9.11 |
| 2 | First 3 manage_X (incident, change, kb_article) | ✅ done | v1.9.12 |
| 3a-d | manage_changeset / script_include / workflow / user / group | ✅ done | v1.9.13 |
| 3e-g | manage_catalog / portal_layout / portal_component / ui_policy | ✅ done | v1.9.14 |
| — | manage_agile | 🚫 deferred (orphan domain) | — |
| 4 | Drop deprecated wrappers | ⏳ planned | v1.11.0 target |
| 5 | Skills overhaul | ⏳ planned | post-Phase 4 |

Tests at v1.9.14: **2017 passed, 5 skipped**. No regressions.

## Goal

Cut 151 tools → ~60 by **bundling CRUD wrappers per domain** while **preserving every multi-query orchestrator**. Domain knowledge (table names, mandatory fields, valid actions) stays baked into each `manage_X` tool — the LLM never has to call `sn_schema` first to discover what to send.

Constraints (non-negotiable):
- **NL latency must not regress.** Each common action stays at 1 MCP round-trip.
- **Standard package stays safe by default.** No new write capability leaks into standard via consolidation.
- **Confirm-on-write gate stays intact.** Every write action requires `confirm='approve'`.
- **Backward compatibility for one minor version.** Legacy wrappers stay registered alongside `manage_X` until 1.11.0.

## Tool surface today (v1.9.14)

12 `manage_X` bundles + 2 new primitives + all original orchestrators + legacy wrappers (deprecated, scheduled for removal in Phase 4).

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

## Phase 4 — Drop deprecated wrappers (target: v1.11.0)

After at least one minor release cycle on 1.10.x with both surfaces coexisting.

### Wrappers to remove (~70 tools)

```
# Bundled into manage_incident
create_incident, update_incident, add_comment, resolve_incident

# Bundled into manage_change
create_change_request, update_change_request, add_change_task

# Bundled into manage_kb_article / manage_kb_taxonomy (TODO: kb_taxonomy bundle)
create_article, update_article, publish_article
create_knowledge_base, create_category

# Bundled into manage_changeset
create_changeset, update_changeset, add_file_to_changeset,
commit_changeset, publish_changeset

# Bundled into manage_script_include
create_script_include, update_script_include,
delete_script_include, execute_script_include

# Bundled into manage_workflow
create_workflow, update_workflow, activate_workflow, deactivate_workflow,
delete_workflow, add_workflow_activity, update_workflow_activity,
delete_workflow_activity

# Bundled into manage_user / manage_group
create_user, update_user, get_user, list_users,
create_group, update_group, list_groups

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

### List/get wrappers also removable
`get_catalog_item`, `list_catalog_items`, `list_catalog_categories`, `list_catalog_item_variables`, `list_workflows`, `get_script_include`, `list_script_includes` — covered by `manage_X.list`/`.get` action OR `sn_query`.

### Phase 4 work items
1. Delete the wrapper functions and their `@register_tool` decorators.
2. Delete the legacy params classes if no longer referenced internally.
3. Delete legacy wrapper test files (or rewrite the few that test logic not covered by `manage_X` tests).
4. Remove old names from all `tool_packages.yaml` package definitions.
5. Regenerate `_module_index.py` via `scripts/regenerate_tool_module_index.py`.
6. Update skills (see Phase 5).
7. Update READMEs / website docs to reference `manage_X` instead.
8. Verify `manage_X` impl no longer relies on legacy function — copy core logic in if needed (Phase 2-3 dispatched to legacy wrappers; Phase 4 must inline that logic before deleting them).

### Deletion safety checklist
- [ ] Each `manage_X` action still works after the corresponding wrapper is removed (run `pytest tests/test_manage_*.py`).
- [ ] No `from servicenow_mcp.tools.X import legacy_function` remaining anywhere (grep).
- [ ] No skill / docs / README / changelog mentions a deleted name.
- [ ] Tool count down from 165 → ~95 (target).
- [ ] Full-package schema bytes ≤ 10K tokens (currently ~10K already after Phase 3).

## Phase 5 — Skills overhaul (post-Phase 4)

Mechanical rewrite + reorg. The deletion in Phase 4 will break any skill referencing legacy names; Phase 5 fixes that and improves the skill model.

### Layer reorganization

| Layer | Purpose | Examples |
|---|---|---|
| `skill://workflow/*` | end-to-end scenarios | mfa-request-handling, change-approval-flow |
| `skill://domain/*` | per-domain manage_X usage | incident-ops, portal-edit-pipeline, flow-designer-analysis |
| `skill://custom-tables/*` | customer-fork-only (empty in upstream) | e.g. `x_acme_request.md` |
| `skill://debugging/*` | troubleshooting | mfa-login-stuck, processflow-fails |

### Phase 5 work items
1. Tool-name rewrite pass across all `skills/*` files (scriptable: `update_incident` → `manage_incident action='update'`).
2. Reorg files into the 4-layer directory structure.
3. Add `suggested_skill` URI to `sn_resolve_url` output. URL → table → suggested skill → LLM auto-pulls.
4. Document the **private-fork pattern** for `custom-tables/*`: customers add their own `x_<co>_*.md` skills in their fork; upstream stays empty.
5. CI check: every legacy tool name in skills/ must also appear in deprecation warnings (Phase 4) — no orphan references.

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
| LLM trained on old tool names breaks after Phase 4 | One full minor cycle (1.10.x) with both surfaces; deprecation in changelog; `sn_resolve_url` rewrites |
| Per-action required-field validation gets ugly | Pydantic `model_validator(mode='after')` with one validator per action — already in place across all 12 bundles |
| Confirm gate misses manage_X with read action | `MANAGE_READ_ACTIONS` map already declared in `server.py`; tested for `manage_user`/`manage_group` |
| sn_write abused on dangerous tables | Hard-coded `SN_WRITE_DENY_TABLES` (no env override); test asserts denylist intact |
| Token budget regression on tool description | Each manage_X description capped at 120 chars; per-action `Literal[...]` replaces prose |
| Existing skills/docs reference old names | Phase 5 mechanical rewrite + CI check for orphan refs |

## Out of scope

- URL routing intelligence beyond regex parsing — defer to LLM (sn_resolve_url returns suggestion, LLM dispatches)
- Field-level allowlists per role — rejected as over-engineering in earlier discussion
- Audit log to ServiceNow side — relies on existing `sys_audit`
- Junior/lead package split — `standard` (read-only) vs `full` (everything) is the clean line
- `manage_agile` — orphan domain, no tools currently in any package, zero LLM-token win from bundling

## Acceptance (final, post-Phase 4 + 5)

- All tests pass (currently 2017 at v1.9.14)
- Full-package schema bytes ≤ 50% of pre-consolidation baseline (target: 10K tokens; achieved at v1.9.14)
- NL benchmark: each representative prompt (create incident, find change by number, publish KB, scaffold portal page, get widget bundle) completes in ≤ 1 extra MCP round-trip vs. baseline
- `manage_X` tools have ≥ 90% test coverage (per-action happy path + invalid-action + missing-required) — already met at v1.9.14
- No tool description exceeds 120 chars; no param description exceeds 80 chars
- No skill or doc references a deleted legacy tool name
- Tool count down to ~95 from 165 at v1.9.14 (or 151 pre-consolidation)
