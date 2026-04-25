# Tool Consolidation Plan

## Goal

Cut 151 tools → ~60 by **bundling CRUD wrappers per domain** while **preserving every multi-query orchestrator**. Domain knowledge (table names, mandatory fields, valid actions) stays baked into each `manage_X` tool — the LLM never has to call `sn_schema` first to discover what to send.

Constraints (non-negotiable):
- **NL latency must not regress.** Each common action stays at 1 MCP round-trip.
- **Standard package stays safe by default.** No new write capability leaks into standard via consolidation.
- **Confirm-on-write gate stays intact.** Every write action requires `confirm='approve'`.
- **Backward compatibility for one minor version.** Old wrapper names alias to new manage_X for 1.10.x; removed in 1.11.0.

## Tool Classification

The 151 current tools fall into four buckets:

### A. Primitives (KEEP, 6)
The generic table API surface. The LLM uses these whenever no domain tool fits.

```
sn_query, sn_aggregate, sn_schema, sn_discover, sn_health, sn_nl
```

### B. Orchestrators (KEEP, ~40)
Multi-query, joins, state machines, bulk loops, pipelines. Dropping these would force the LLM into 3-10× round-trips for the same answer.

| Domain | Orchestrators (kept as-is) |
|---|---|
| Change | `get_change_request_details` (record+tasks+approvals), `approve_change`, `reject_change`, `submit_change_for_approval` |
| Changeset | `get_changeset_details` (set+entries) |
| Incident | `get_incident_by_number` (number→record fallback) |
| Workflow | `get_workflow_details`, `get_workflow_activities`, `list_workflow_versions`, `reorder_workflow_activities` |
| Flow Designer | `list_flow_designers`, `get_flow_designer_detail`, `get_flow_designer_executions`, `compare_flows` |
| Portal | `get_widget_bundle`, `resolve_widget_chain`, `resolve_page_dependencies`, `search_portal_regex_matches`, `trace_portal_route_targets`, `analyze_widget_performance`, `get_provider_dependency_map`, `extract_widget_table_dependencies`, `detect_angular_implicit_globals`, `download_portal_sources`, `scaffold_page`, the 5-tool portal-edit pipeline (`route_*`, `analyze_*`, `preview_*`, `create_*_snapshot`, `update_*_from_snapshot`) |
| Source / audit | `search_server_code`, `get_metadata_source`, `extract_table_dependencies`, `download_app_sources` + `download_*` per-domain bundles, `audit_local_sources`, `audit_pending_changes` |
| Dev productivity | `get_developer_changes`, `get_developer_daily_summary`, `get_uncommitted_changes`, `get_repo_change_report`, `get_repo_recent_commits`, `get_repo_file_last_modifier`, `get_repo_working_tree_status` |
| Catalog | `get_optimization_recommendations` |
| User / group | `add_group_members`, `remove_group_members` (loop-bulk) |
| Sync | `diff_local_component`, `update_remote_from_local` |
| Logs | `get_logs` |

### C. CRUD wrappers → BUNDLE into `manage_X` (~70 tools collapse to 12 tools)

| New tool | Replaces | Actions |
|---|---|---|
| `manage_incident` | `create_incident`, `update_incident`, `add_comment`, `resolve_incident` | create, update, comment, resolve |
| `manage_change` | `create_change_request`, `update_change_request`, `add_change_task` | create, update, add_task |
| `manage_changeset` | `create_changeset`, `update_changeset`, `add_file_to_changeset`, `commit_changeset`, `publish_changeset` | create, update, add_file, commit, publish |
| `manage_kb_article` | `create_article`, `update_article`, `publish_article` | create, update, publish |
| `manage_kb_taxonomy` | `create_knowledge_base`, `create_category` | create_kb, create_category |
| `manage_script_include` | `create_script_include`, `update_script_include`, `delete_script_include`, `execute_script_include` | create, update, delete, execute |
| `manage_workflow` | `create_workflow`, `update_workflow`, `activate_workflow`, `deactivate_workflow`, `delete_workflow`, `add_workflow_activity`, `update_workflow_activity`, `delete_workflow_activity` | create, update, activate, deactivate, delete, add_activity, update_activity, delete_activity |
| `manage_user` | `create_user`, `update_user`, `get_user`, `list_users` | create, update, get, list |
| `manage_group` | `create_group`, `update_group`, `list_groups` | create, update, list |
| `manage_catalog` | `create_catalog_category`, `update_catalog_category`, `update_catalog_item`, `move_catalog_items`, `create_catalog_item_variable`, `update_catalog_item_variable` | create_category, update_category, update_item, move_items, create_variable, update_variable |
| `manage_portal_layout` | `create_widget_instance`, `update_widget_instance`, `update_page`, `create_page`, `create_container`, `create_row`, `create_column` | place_widget, move_widget, update_page, create_page, add_container, add_row, add_column |
| `manage_portal_component` | `create_widget`, `create_angular_provider`, `create_header_footer`, `create_css_theme`, `create_ng_template`, `create_ui_page`, `update_portal_component` | create_widget, create_provider, create_header_footer, create_theme, create_ng_template, create_ui_page, update_code |
| `manage_ui_policy` | `create_ui_policy`, `create_ui_policy_action` | create, add_action |
| `manage_agile` (orphan) | `create_epic`, `update_epic`, `list_epics`, `create_story`, `update_story`, `list_stories`, `create_story_dependency`, `delete_story_dependency`, `list_story_dependencies`, `create_scrum_task`, `update_scrum_task`, `list_scrum_tasks`, `create_project`, `update_project`, `list_projects` | epic_*, story_*, story_dep_*, scrum_*, project_* |

(15 new manage_X tools replacing ~70 wrappers.)

### D. List/Get wrappers → FOLD into orchestrators or sn_query (~12 tools removed)

These do nothing sn_query can't do. They were thin convenience wrappers:

```
get_catalog_item, list_catalog_items, list_catalog_categories,
list_catalog_item_variables, list_workflows, get_script_include,
list_script_includes
```

Each kept their info via the parent `manage_X.list` / `manage_X.get` action OR documented sn_query usage in the orchestrator descriptions.

## New Primitives (2)

### `sn_write(table, action, sys_id?, fields?, confirm)`
Generic Table-API CRUD for the long tail (tables without a `manage_X`). **Hard-coded denylist** in code (not config):

```python
DENY_TABLES = {
    "sys_user", "sys_user_group", "sys_security_acl",
    "sys_app", "sys_scope", "sys_dictionary", "sys_db_object",
    "sys_remote_update_set",
}
DENY_ACTIONS_ON_SYS = {"delete"}  # delete blocked on any sys_* table
```

Parameters:
- `table: str` — target table
- `action: Literal["create","update","delete"]`
- `sys_id: Optional[str]` — required for update/delete
- `fields: Optional[Dict[str, Any]]` — required for create/update
- `confirm: Literal["approve"]` — gate (existing pattern)
- `dry_run: bool = False` — preview field changes before commit

### `sn_resolve_url(url)`
Parse any ServiceNow URL → table + sys_id + scope + suggested next tool.

Patterns to handle:
- `nav_to.do?uri={table}.do?sys_id={id}` → record-form
- `$sp.do?id={page_id}&sys_id={id}` → portal-page
- `sys_app_studio.do#/...` → Studio (extract scope)
- `kb_view.do?sysparm_article={number}` → KB article
- `esc?id={page}` → Employee Center
- Plain `incident.do?sys_id=...`, `change_request.do?...`

Returns:
```json
{"table": "...", "sys_id": "...", "scope": "...",
 "suggested_tool": "manage_incident", "suggested_action": "get",
 "context": {...}}
```

## Tool count: before / after

| Bucket | Before | After |
|---|---|---|
| Primitives | 6 | 6 |
| Orchestrators | 40 | 40 |
| CRUD wrappers | 70 | 0 |
| List/Get wrappers | 12 | 0 |
| `manage_X` bundles | 0 | 15 |
| New primitives | 0 | 2 (`sn_write`, `sn_resolve_url`) |
| Misc (analyze, audit, sync) | 23 | 23 |
| **Total** | **151** | **~86** |

Tool surface in `full` package:
- before: 110 tools, schema ~20K LLM tokens
- after: ~70 tools, schema **~10K tokens** (50% reduction)

`standard` package stays read-only — gets `sn_resolve_url` only, no `sn_write` or `manage_X` writes.

## Per-domain manage_X spec (representative example)

```python
class ManageIncidentParams(BaseModel):
    """Manage incidents — table: incident.

    Required fields per action:
      create:  short_description
      update:  sys_id, fields
      comment: sys_id, comment, comment_type ('work_notes' | 'comments')
      resolve: sys_id, resolution_code, close_notes
    """

    action: Literal["create", "update", "comment", "resolve"] = Field(
        ..., description="Operation to perform."
    )
    sys_id: Optional[str] = Field(default=None, description="Target incident sys_id (update/comment/resolve).")
    incident_number: Optional[str] = Field(default=None, description="INC number alternative to sys_id.")
    short_description: Optional[str] = Field(default=None, description="Required for create.")
    fields: Optional[Dict[str, Any]] = Field(default=None, description="Field updates for update action.")
    comment: Optional[str] = Field(default=None, description="Comment text for comment action.")
    comment_type: Optional[Literal["work_notes", "comments"]] = Field(default="work_notes")
    resolution_code: Optional[str] = Field(default=None, description="Resolution code for resolve action.")
    close_notes: Optional[str] = Field(default=None, description="Required for resolve action.")
    dry_run: bool = Field(default=False)
```

LLM-facing tool description (≤120 chars):
```
"Create/update/comment/resolve an incident (table: incident). One call, no schema lookup needed."
```

Validation: per-action required-field check via Pydantic `model_validator(mode='after')`. Emit clear error when missing.

## Confirm gate continuity

Current gate matches `MUTATING_TOOL_PREFIXES = ("create_","update_","delete_",...)`. After consolidation, every `manage_X` is a write tool — extend the gate:

```python
MUTATING_TOOL_PREFIXES = (
    "manage_",     # NEW — every manage_X requires confirm
    "create_", "update_", "delete_",
    # ... existing prefixes (reduced over time)
)
MUTATING_TOOL_NAMES |= {"sn_write"}
```

`manage_X` with read-only actions (`list`, `get` on `manage_user`/`manage_group`) — exempt via per-action check rather than tool-name. Implementation: check `arguments["action"]` in `_call_tool_impl` for tools starting with `manage_`. Read actions skip the confirm requirement.

## Migration phases

### Phase 1: New primitives — sn_write, sn_resolve_url
Standalone work. No tool removal yet. **Adds 2 tools, removes 0.**

- Implement `sn_write` with denylist + confirm + dry_run
- Implement `sn_resolve_url` with regex-based URL parsing
- Add to `standard` (sn_resolve_url only) and `full` (both)
- Tests: denylist enforcement, dry_run output, URL parsing for each pattern

### Phase 2: First 3 manage_X (incident, change, kb_article)
Lowest-risk domains, well-tested. **Adds 3 tools, deprecates 10.**

- Implement bundle tools
- Old wrappers stay registered but log `DeprecationWarning` and delegate to manage_X
- Update YAML packages: `manage_incident` replaces `create_incident`+`update_incident`+`add_comment`+`resolve_incident`
- Add aliases in `_module_index.py` so old names route to new module

### Phase 3: Remaining manage_X (12 more)
Bulk migration. **Adds 12 tools, deprecates ~60.**

### Phase 4: Drop deprecated wrappers (in 1.11.0)
After 1 minor cycle — remove old wrappers entirely.

### Phase 5: Skills overhaul
After all manage_X are stable. **Mechanical rewrite + reorg.**

- Replace legacy tool names in `skills/*` (scriptable, low-risk)
- Reorganize into 4-layer structure (workflow/domain/custom/debugging)
- Add `suggested_skill` to `sn_resolve_url` output — LLM auto-pulls when given a URL
- Document private-fork pattern for `custom-tables/*` skills

Each phase ends with: tests pass, schema bytes measured, NL benchmark on 5 representative prompts.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM trained on old tool names breaks | Aliases in registry — old names route to manage_X for 1 minor version |
| Per-action required-field validation gets ugly | Pydantic `model_validator(mode='after')` with one validator per action; tested per action |
| Confirm gate misses manage_X with read action | Read-action exemption in `_call_tool_impl` checks `arguments["action"]` against per-tool read list |
| sn_write abused on dangerous tables | Hard-coded `DENY_TABLES` (no env override); separate test asserts denylist intact |
| Token budget regression on tool description | Each manage_X description capped at 120 chars; per-action enums replace prose |
| Existing skills/docs reference old names | grep + automated rewrite in `skills/*` and `docs/*` during phase 4 |

## Custom tables

`manage_X` covers OOTB tables only. Customer-specific tables (`x_<vendor>_<scope>_<name>`, `u_*`) won't have a domain bundle — instead:

```
LLM intent: "create a record in x_acme_request"
  → sn_schema("x_acme_request")     # one-time discovery (sn_query_page cache, 30s TTL)
  → sn_write(table="x_acme_request", action="create", fields={...})
```

First call pays one extra `sn_schema` round-trip. Subsequent calls hit the schema cache and execute in one round-trip — same as a manage_X. The LLM's general ServiceNow knowledge (naming conventions, sys_id semantics, dictionary field types) handles the rest.

For org-specific data models that change LLM behavior at scale, customers add private skill resources (see Skills migration below).

## Documentation strategy

Two layers, with strict cost-discipline on the always-loaded surface:

1. **Always-loaded (= every request, billed every time)**: tool descriptions + JSON schemas only. Capped: tool ≤ 120 chars, param ≤ 80 chars. No tutorials, no domain primers, no enum-as-prose.
2. **On-demand (= pulled by LLM when needed)**:
   - `sn_schema(table)` — live field metadata
   - `sn_discover(keyword)` — table-name fuzzy search
   - MCP `resources` (skills) — workflow guides, custom-table primers

Off-limits: baking comprehensive ServiceNow knowledge into tool descriptions. The LLM already knows OOTB tables and GlideRecord patterns from training; reproducing that is pure waste.

## Skills migration

Existing skills reference legacy tool names (`create_incident`, `update_change_request`, etc.). After consolidation, every skill needs a tool-name pass. We also restructure for the new tool surface:

**Before** (tool-centric): "use `update_incident` with state=Resolved"
**After** (workflow-centric): "to resolve an MFA reset request: 1) `sn_resolve_url` on the screen → 2) `manage_incident` action='comment' to log progress → 3) `manage_incident` action='resolve'..."

Layer reorganization:

| Layer | Purpose | Examples |
|---|---|---|
| `skill://workflow/*` | end-to-end scenarios | mfa-request-handling, change-approval-flow |
| `skill://domain/*` | per-domain manage_X usage | incident-ops, portal-edit-pipeline, flow-designer-analysis |
| `skill://custom-tables/*` | customer-fork-only (empty in upstream) | (e.g. `x_acme_request.md`) |
| `skill://debugging/*` | troubleshooting | mfa-login-stuck, processflow-fails |

`sn_resolve_url` returns a `suggested_tool` and (in Phase 5) a `suggested_skill` URI — the LLM auto-pulls the right skill for the URL it's looking at. URL → skill → action.

## Out of scope

- URL routing intelligence beyond regex parsing — defer to LLM (sn_resolve_url returns suggestion, LLM dispatches)
- Field-level allowlists per role — rejected as over-engineering in earlier discussion
- Audit log to ServiceNow side — relies on existing `sys_audit`
- Junior/lead package split — `standard` (read-only) vs `full` (everything) is the clean line

## Acceptance

- All 1842+ tests pass
- Full-package schema bytes ≤ 50% of current (target: 10K tokens)
- NL benchmark: each of 5 representative prompts (create incident, find change by number, publish KB, scaffold portal page, get widget bundle) completes in ≤ 1 extra MCP round-trip vs. baseline
- `manage_X` tools have ≥ 90% test coverage (per-action happy path + invalid-action + missing-required)
- No tool description exceeds 120 chars; no param description exceeds 80 chars
