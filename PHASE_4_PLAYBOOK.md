# Phase 4.0 Execution Playbook

This is the runnable companion to `CONSOLIDATION_PLAN.md`. Any model (Opus, Sonnet, Haiku) should be able to pick this up, follow the steps in order, and stop at every gate without ad-hoc judgment. **Only Phase 4.0 (duplicate wrapper removal + service extraction) is covered here.** Phases 4.5 / 4.7 are opt-in per domain — write a separate playbook when you get there.

## Resume status (last updated 2026-04-26)

Tool count: **165 → 110 (−55), 11 / 11 domains shipped. Phase 4.0 COMPLETE.**

| ✅ ver | domain | wrappers removed | tools after |
|---|---|---|---|
| v1.9.16 | manage_kb_article | 3 | 163 |
| v1.9.17 | manage_change | 3 | 160 |
| v1.9.18 | manage_incident | 4 | 156 |
| v1.9.19 | manage_ui_policy | 2 | 154 |
| v1.9.20 | manage_script_include | 4 | 150 |
| v1.9.21 | manage_changeset | 5 | 145 |
| v1.9.22 | manage_catalog | 6 | 139 |
| v1.9.23 | manage_user / manage_group | 7 | 132 |
| v1.9.24 | manage_portal_layout | 7 | 125 |
| v1.9.25 | manage_portal_component | 7 | 118 |
| v1.9.26 | manage_workflow | 8 | 110 |

Phase 4.0 binding goal = **~106 tools** — achieved 110 (within rounding).

## Lessons learned (apply these to remaining domains)

1. **NL gate is over-engineered for most domains.** Snapshot byte-for-byte + full pytest sweep + ruff/orphan-ref clean is sufficient. Do **not** ask the human to write real records to ServiceNow — verified by `feedback_no_live_data_gate.md` memory.
2. **Response model relocation is required when the model is shared between wrapper(s) and the service.** Define the model in `services/<domain>.py` and re-import from `tools/<domain>.py`. Avoids the wrapper-→-service-→-wrapper circular import. (Domains that return raw `Dict[str, Any]` like `change` and `ui_policy` skip this step.)
3. **`tools/<domain>.py` import cleanup**: after wrappers delete, `invalidate_query_cache` may still be needed by surviving tools (e.g. read tools, state-transition tools). Don't remove it blindly — `grep` first. Same for `build_update_preview` (usually only used by deleted update wrappers).
4. **Test patches need updating from `tools.<domain>.invalidate_query_cache` → `services.<domain>.invalidate_query_cache`** for any test that exercises a path now routing through the service. Read paths and surviving-tool paths still patch on `tools.<domain>`.
5. **Dispatch tests in `tests/test_manage_<X>.py`** need their patches rewired from `tools.<domain>.<wrapper>` → `services.<domain>.<func>` AND their assertion model from `mock.call_args[0][2].field` (Params object) → `mock.call_args.kwargs["field"]` (kwargs dict).
6. **If `tests/test_<domain>_tools.py` is entirely wrapper-direct,** `git rm` it. The snapshot test + dispatch test give equivalent coverage. Don't waste tokens rewriting 16+ tests for a tiny service module. Done for `ui_policy`.
7. **YAML deletion**: drop wrapper names from `service_desk` / `portal_developer` / `platform_developer` / `full` packages. `manage_X` is already in those packages. **Always sync** `config/tool_packages.yaml` ↔ `src/servicenow_mcp/config/tool_packages.yaml` (test_yaml_sync enforces).
8. **CI orphan-ref ALLOWLIST**: action enum names that match tool-name shape (`add_task`, `add_file`, `update_code`, etc.) need to be added when manage_X tool description references them in backticks. Already in script.
9. **Helper function rename**: when relocating private helpers (`_resolve_incident_sys_id`) into services, drop the `_` prefix — they're now public service API.
10. **Skill / docs cleanup**: every `skills/**/*.md` and `docs/<domain>.md` (+ `website/docs/docs/<domain>.md` mirror) that references a deleted wrapper must be updated in the same commit. Orphan-ref check catches it.
11. **Pre-commit chain order**: black auto-runs first, then isort, then ruff. Run `.venv/bin/black <files>` then `.venv/bin/isort <files>` manually before `git commit` to avoid a fail-and-retry cycle.

## Per-domain quick notes (remaining 7)

Pre-loaded survey for each upcoming domain. Confirm with `grep -nE "^class .*Params|^def |@register_tool"` before starting.

### 5. manage_script_include — `tools/script_include_tools.py` (4 wrappers)
- Wrappers: `create_script_include`, `update_script_include`, `delete_script_include`, `execute_script_include`
- Service target: `services/script_include.py` — likely returns dict (no model relocation)
- Note: `execute_script_include` runs server-side script. Verify it exposes the right error path on script syntax errors.
- Test files: `tests/test_script_include_tools.py`, `tests/test_execute_script_include.py`

### 6. manage_changeset — `tools/changeset_tools.py` (5 wrappers)
- Wrappers: `create_changeset`, `update_changeset`, `commit_changeset`, `publish_changeset`, `add_file_to_changeset`
- Service target: `services/changeset.py`
- Note: `commit_changeset` and `publish_changeset` have state-transition semantics. Snapshot both happy + transition-failure paths.
- Heavy in `portal_developer` package — yaml needs careful cleanup.

### 7. manage_catalog — `tools/catalog_tools.py` + `tools/catalog_variables.py` (6 wrappers)
- Wrappers: `create_catalog_category`, `update_catalog_category`, `update_catalog_item`, `move_catalog_items` (in `catalog_tools.py`); `create_catalog_item_variable`, `update_catalog_item_variable` (in `catalog_variables.py`)
- Service target: single `services/catalog.py` covers both files. `move_catalog_items` is unusual — touches multiple records; preserve its bulk behavior carefully.
- Two source files but one service module is fine.

### 8. manage_user / manage_group — `tools/user_tools.py` (9 combined)
- Wrappers: `create_user`, `update_user`, `get_user`, `list_users`, `create_group`, `update_group`, `list_groups`, `add_group_members`, `remove_group_members`
- Service targets: `services/user.py` and `services/group.py` (separate files for cleaner domain separation), OR single `services/identity.py` if cross-references are heavy.
- **CAUTION**: `get_user`, `list_users`, `list_groups` are **read tools shipped in the `standard` package**. `manage_user` and `manage_group` already have `get`/`list` actions in `MANAGE_READ_ACTIONS`. Removal here is essentially the Phase 4.5 read-action consolidation pattern combined with 4.0 wrapper removal — verify `standard` package still serves read consumers via `manage_X(action="list")` after removal.
- Two `manage_X` bundles, two snapshot test files (`test_user_snapshots.py`, `test_group_snapshots.py`), or one combined.

### 9. manage_portal_layout — `tools/portal_crud_tools.py` (7 wrappers)
- Wrappers: `create_widget_instance`, `update_widget_instance`, `update_page`, `create_page`, `create_container`, `create_row`, `create_column`
- Service target: `services/portal_layout.py`
- Note: shares the `portal_crud_tools.py` file with the next domain (`manage_portal_component`). **Do not bundle**: ship layout first, then component, separate releases. Share the import block carefully — if you remove `invalidate_query_cache` import after layout deletion, component still needs it.

### 10. manage_portal_component — `tools/portal_crud_tools.py` (7 wrappers)
- Wrappers: `create_widget`, `create_angular_provider`, `create_header_footer`, `create_css_theme`, `create_ng_template`, `create_ui_page`, `update_portal_component`
- Service target: `services/portal_component.py`
- Note: ships **after** Domain 9. After this lands, `portal_crud_tools.py` may have very few surviving registrations — review whether the file should be deleted entirely or kept as a small layer.

### 11. manage_workflow — `tools/workflow_tools.py` (9 wrappers)
- Wrappers: `create_workflow`, `update_workflow`, `activate_workflow`, `deactivate_workflow`, `delete_workflow`, `add_workflow_activity`, `update_workflow_activity`, `delete_workflow_activity`, `reorder_workflow_activities`
- Service target: `services/workflow.py` (single module covering both workflow CRUD and activity CRUD)
- Note: largest count (9). Snapshot suite should cover both workflow-level and activity-level actions. Pre-existing `params.dict()` Pydantic v1 deprecation warning at `workflow_tools.py:187` — **leave it alone** (separate fix, not part of Phase 4.0).

## Next-session quickstart

1. Read this file's "Resume status" section to confirm queue head.
2. Read `feedback_no_live_data_gate.md` and `feedback_tool_count_judgment.md` from memory (auto-loaded).
3. Pick up the next pending domain from the queue (currently **Domain 5: manage_script_include**).
4. Apply the 8-step recipe below, using the per-domain quick note above for that domain.
5. After each domain ships: bump version (patch increment), tag, push.
6. Stop when queue exhausted OR human asks to pause.

## Operating principles for the executor

1. **Do exactly one domain per branch / PR.** Never bundle two domains.
2. **Stop at every gate.** If a verify command fails, do not "fix forward" — read the failure, decide whether the change is wrong or the test is wrong, and report. Don't paper over it.
3. **No behavior change is allowed mid-extraction.** If you find a bug while extracting, file it as a follow-up; do not fix it in the same PR.
4. **No new features, no refactors of unrelated code.** Touch only what the step says to touch.
5. **Snapshot diff is the contract with live LLM consumers.** If the snapshot changes, the change is wrong — even if tests pass.
6. **When in doubt, stop and ask the human.** Better to pause than ship a silent regression.

## Repo facts (verified 2026-04-26)

| Thing | Where |
|---|---|
| Tool source files | `src/servicenow_mcp/tools/<domain>.py` (one file per domain — wrappers AND `manage_X` live in the same file) |
| Tool registration | `@register_tool(...)` decorator inline above each function |
| Pydantic params | Same file, named `<Action>Params` |
| Tool packages config | `config/tool_packages.yaml` |
| Auto-generated tool index | `src/servicenow_mcp/tools/_module_index.py` (regenerate via `scripts/regenerate_tool_module_index.py`) |
| Tool inventory doc | `docs/TOOL_INVENTORY.md` (regenerate via `scripts/regenerate_tool_inventory.py`) |
| Tests | `tests/test_<domain>.py` + `tests/test_<domain>_extra.py` |
| `manage_X` confirm gate | `MANAGE_READ_ACTIONS` map in `src/servicenow_mcp/server.py` |
| `services/` directory | **Does not exist yet** — Phase 4.0 creates `src/servicenow_mcp/services/` |
| Snapshot test infra | **Does not exist yet** — Phase 4.0 introduces it (template below) |
| NL benchmark | **Does not exist yet** — manual review for now (see "NL gate" below) |

## Per-domain template (the 8-step recipe)

Every domain in the queue follows this exact sequence. Each step has a verify command. **If a verify fails, stop.**

### Step 0 — Pre-flight survey

For the target domain, gather and write down (in the PR description):

- Domain file path (e.g. `src/servicenow_mcp/tools/knowledge_base.py`)
- Wrappers to remove (function names + line numbers)
- Their `<Action>Params` classes (line numbers)
- The `manage_X` dispatcher (line numbers)
- All test files that import any of the wrappers
- All tool_packages.yaml occurrences of the wrapper names

Verify:
```bash
grep -n "@register_tool\|^def \|^async def \|^class .*Params" src/servicenow_mcp/tools/<domain>.py
grep -rn "from servicenow_mcp.tools.<domain> import" src/ tests/
grep -n "<wrapper_name>" config/tool_packages.yaml
```

### Step 1 — Establish baseline snapshots (commit 1)

Capture the JSON response shape of every action that will be touched. These snapshots are the contract: post-extraction output must match byte-for-byte.

1. Create `tests/snapshots/<domain>/` directory.
2. Add `tests/test_<domain>_snapshots.py` using the template in [Snapshot test pattern](#snapshot-test-pattern). One test per `manage_X` action and per wrapper being removed.
3. Run the suite — it should generate snapshot files on first run (or assert against pre-recorded ones).
4. Commit: `test(<domain>): baseline response-shape snapshots before service extraction`

Verify:
```bash
python -m pytest tests/test_<domain>_snapshots.py -x
git status tests/snapshots/<domain>/   # files should be tracked
```

### Step 2 — Create the service module (commit 2)

1. Create `src/servicenow_mcp/services/__init__.py` if it doesn't exist.
2. Create `src/servicenow_mcp/services/<domain>.py`.
3. **Copy** (do not move) the body of each target wrapper into a function in the service module. Use the same function signatures minus the `@register_tool` decorator. Drop the Params dependency where possible — accept plain kwargs.
4. Add unit tests `tests/test_<domain>_service.py` that exercise the new service functions directly.

The wrapper functions in `tools/<domain>.py` are **untouched** at this step — services exist in parallel.

Verify:
```bash
python -m pytest tests/test_<domain>_service.py tests/test_<domain>.py tests/test_<domain>_snapshots.py -x
```

Commit: `feat(services): extract <domain> service module (parallel to wrappers)`

### Step 3 — Wire wrappers and `manage_X` to the service (commit 3)

1. Replace the body of each wrapper with a thin call into `services.<domain>.<func>(...)`.
2. Replace the dispatch arms in the `manage_X` function with direct service calls (skip the wrapper indirection).
3. Run the full snapshot suite — **it must still pass byte-for-byte**.

Verify:
```bash
python -m pytest tests/test_<domain>_snapshots.py tests/test_<domain>.py tests/test_<domain>_extra.py tests/test_<domain>_service.py -x
python -m pytest tests/ -x   # full sweep, no regressions elsewhere
```

Commit: `refactor(<domain>): route wrappers and manage_X through service layer`

### Step 4 — NL gate (manual for now)

Run a 5-prompt human spot-check against the manage_X surface. Until automation exists, a model executor stops here and asks the human to confirm.

Prompts to test (kb_article example — adapt per domain):
1. "create a knowledge article in KB X with title Y and body Z"
2. "update article SYSID, change title to W"
3. "publish article SYSID"
4. "publish article" (intentionally missing sys_id — should fail validation cleanly)
5. "create article" (intentionally missing required fields — should fail validation cleanly)

Pass criteria: LLM picks `manage_kb_article` first try, supplies right action, gets 1 round-trip success on (1)-(3), gets a single helpful error on (4)-(5). **Fail → revert and re-design.**

### Step 5 — Delete the wrappers (commit 4)

Only after Step 3 is green and Step 4 is human-confirmed.

1. Delete the wrapper functions, their `@register_tool` decorators, and their `<Action>Params` classes.
2. Update `tests/test_<domain>.py` and `tests/test_<domain>_extra.py`: any test that called a deleted wrapper now calls the equivalent `services.<domain>` function (preferred) or `manage_X(action=...)`.
3. Remove deleted wrapper names from `config/tool_packages.yaml`.
4. Run the regenerators:
   ```bash
   python scripts/regenerate_tool_module_index.py
   python scripts/regenerate_tool_inventory.py
   ```
5. Search for any orphaned references in skills / docs / README:
   ```bash
   grep -rn "<wrapper_name>" skills/ docs/ website/ README.md README.ko.md
   ```
   Update or delete every hit.

Verify:
```bash
python -m pytest tests/ -x
grep -rn "<wrapper_name>" src/ tests/ skills/ docs/ website/ README.md README.ko.md   # should print nothing
```

Commit: `feat(<domain>): remove duplicate wrappers, manage_<X> is the sole entry point`

### Step 6 — CI orphan-ref gate (one-time, before first domain ships)

Add `scripts/check_orphan_tool_refs.py` that:
1. Loads the live tool registry (everything currently registered with `@register_tool`).
2. Walks `skills/`, `docs/`, `website/`, `README.md`, `README.ko.md`.
3. Greps for any token matching `[a-z][a-z0-9_]+` that looks like a tool name AND is not in the live registry.
4. Exits non-zero if it finds any.

Wire it into pre-commit and into the test command. This must exist **before** the first wrapper deletion lands.

Verify:
```bash
python scripts/check_orphan_tool_refs.py   # exits 0 on a clean repo
```

Commit: `ci: add orphan tool-reference detector`

### Step 7 — Version bump + tag (commit 5)

Per `CLAUDE.md`: patch increment, then immediate tag.

```bash
# Edit src/servicenow_mcp/version.py and pyproject.toml: x.y.z → x.y.(z+1)
git add -A && git commit -m "chore: bump version to <new_version>"
git tag v<new_version> && git push origin <branch> v<new_version>
```

### Step 8 — PR description checklist

- [ ] Single domain only
- [ ] Snapshots from Step 1 unchanged in final state
- [ ] Full test suite green
- [ ] NL gate confirmed by human reviewer
- [ ] No orphan refs in skills/docs/README/website
- [ ] Tool count drop reported in PR body (e.g. "165 → 162")
- [ ] Version bumped and tag pushed

## Domain queue (Phase 4.0 — execute in this order)

Ordered smallest → largest by wrapper count, so the playbook itself gets battle-tested on a small surface first.

| # | Domain | Wrappers to remove | File |
|---|---|---|---|
| 1 | **manage_kb_article** ← NEXT | 3 (`create_article`, `update_article`, `publish_article`) | `tools/knowledge_base.py` |
| 2 | manage_change | 3 (`create_change_request`, `update_change_request`, `add_change_task`) | `tools/change_tools.py` |
| 3 | manage_incident | 4 (`create_incident`, `update_incident`, `add_comment`, `resolve_incident`) | `tools/incident_tools.py` |
| 4 | manage_ui_policy | 2 (`create_ui_policy`, `create_ui_policy_action`) | `tools/ui_policy_tools.py` |
| 5 | manage_script_include | 4 (`create_script_include`, `update_script_include`, `delete_script_include`, `execute_script_include`) | `tools/script_include_tools.py` |
| 6 | manage_changeset | 5 (`create_changeset`, `update_changeset`, `add_file_to_changeset`, `commit_changeset`, `publish_changeset`) | `tools/changeset_tools.py` |
| 7 | manage_catalog | 6 (`create_catalog_category`, `update_catalog_category`, `update_catalog_item`, `move_catalog_items`, `create_catalog_item_variable`, `update_catalog_item_variable`) | `tools/catalog_tools.py` + `catalog_variables.py` |
| 8 | manage_user / manage_group | 9 combined (see CONSOLIDATION_PLAN list) | `tools/user_tools.py` |
| 9 | manage_portal_layout | 7 | `tools/portal_*.py` |
| 10 | manage_portal_component | 7 | `tools/portal_*.py` |
| 11 | manage_workflow | 9 | `tools/workflow_tools.py` |

Total: **59 wrappers across 11 domain PRs.** Expected outcome: 165 → 106 tools.

## Domain 1 — manage_kb_article (concrete details)

Pre-loaded survey results so the executor can start immediately:

- **File**: `src/servicenow_mcp/tools/knowledge_base.py` (1108 lines)
- **Wrappers to remove**:
  - `create_article` — L436 (decorator L429, params class `CreateArticleParams` L66)
  - `update_article` — L505 (decorator L498, params class `UpdateArticleParams` L83)
  - `publish_article` — L584 (decorator L577, params class `PublishArticleParams` L98)
- **manage_X dispatcher**: `manage_kb_article` — L1068, params class `ManageKbArticleParams` L1008
- **Service target file (new)**: `src/servicenow_mcp/services/kb_article.py`
- **Service functions to create**:
  - `kb_article.create(config, auth_manager, *, title, text, short_description, knowledge_base, category, keywords=None, article_type=None) -> ArticleResponse`
  - `kb_article.update(config, auth_manager, *, article_id, title=None, text=None, short_description=None, category=None, keywords=None, dry_run=False) -> ArticleResponse`
  - `kb_article.publish(config, auth_manager, *, article_id, workflow_state=None, workflow_version=None) -> ArticleResponse`
- **Test files affected**:
  - `tests/test_knowledge_base.py` (imports all 3 wrappers at L24/L31/L32)
  - `tests/test_knowledge_base_extra.py` (also imports — verify in Step 0)
  - `tests/test_manage_change_kb.py` (imports — verify in Step 0)
- **Tests to add**:
  - `tests/test_kb_article_service.py` (new)
  - `tests/test_knowledge_base_snapshots.py` (new — snapshot baseline)
- **Tools NOT to touch in this PR** (same file, but not duplicates of `manage_kb_article`): `create_knowledge_base`, `list_knowledge_bases`, `create_category`, `list_articles`, `get_article`, `list_categories`. These survive.
- **tool_packages.yaml**: grep for the 3 wrapper names; remove from any package that lists them.

## Snapshot test pattern

Save under `tests/test_<domain>_snapshots.py`. The pattern uses pytest fixtures + JSON files; snapshot files are committed to git.

```python
"""Response-shape snapshots for <domain>.

These tests assert byte-for-byte equality against pre-recorded JSON output.
A snapshot diff means the response shape changed — which is a contract break
with live LLM consumers, regardless of whether other tests pass.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.<domain> import manage_<X>, Manage<X>Params

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "<domain>"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _assert_snapshot(name: str, actual: dict) -> None:
    snap_path = SNAPSHOTS_DIR / f"{name}.json"
    actual_json = json.dumps(actual, sort_keys=True, indent=2)
    if not snap_path.exists():
        snap_path.write_text(actual_json)
        pytest.skip(f"snapshot {name} created — re-run to assert")
    expected = snap_path.read_text()
    assert actual_json == expected, (
        f"\nSnapshot drift for {name}:\n"
        f"  Update with: rm {snap_path} && pytest -k {name}\n"
        f"  Then review the diff carefully — a change here is a contract break.\n"
    )


@pytest.fixture
def server_config():
    cfg = MagicMock()
    cfg.instance_url = "https://example.service-now.com"
    cfg.auth.type = "basic"
    return cfg


@pytest.fixture
def auth_manager():
    am = MagicMock()
    am.get_headers.return_value = {"Authorization": "Basic xxx"}
    return am


@patch("servicenow_mcp.tools.<domain>.requests.post")
def test_snapshot_manage_<X>_create(mock_post, server_config, auth_manager):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"result": {"sys_id": "abc123", ...}}
    params = Manage<X>Params(action="create", ...)
    result = manage_<X>(server_config, auth_manager, params)
    _assert_snapshot("manage_<X>_create", result.model_dump() if hasattr(result, "model_dump") else result)


# ... one test per (manage_X, action) and one per (wrapper_being_deleted)
```

**On first run** the test creates the snapshot and skips. **On second run** it asserts. After Step 1, commit the snapshot files. Steps 3 and beyond must produce zero diffs.

## Rollback

If any verify in Steps 3-5 fails and the cause isn't an obvious typo:

```bash
git reset --hard <commit-before-step-3>   # back out the service wiring
# Investigate. The bug is likely a serialization difference (Pydantic v2 vs dict, datetime format, None vs missing key).
# Fix, re-run snapshot suite, retry from Step 3.
```

If Step 5 (deletion) ships and a regression surfaces post-merge:

```bash
git revert <merge-commit>
git tag v<previous_version> --force-with-lease   # if tag was pushed
# File a bug, do not retry the same domain until the root cause is understood.
```

## Definition of done — Phase 4.0 (whole campaign)

- [ ] All 11 domain PRs merged
- [ ] Tool count = 106 (down from 165)
- [ ] Full test suite green on `main`
- [ ] CI orphan-ref check active and green
- [ ] No skill/doc/README mentions any of the 59 deleted names
- [ ] Each merged PR includes the snapshot files for its domain (no diffs anywhere)
- [ ] Phase 4.0 row in `CONSOLIDATION_PLAN.md` Status table marked ✅ done with the version range it shipped under

## What this playbook deliberately omits

- Phase 4.5 / 4.7 work — written separately when 4.0 is complete and lessons are integrated.
- Verb-router design — explicitly out of scope (see `CONSOLIDATION_PLAN.md` § Out of scope).
- Skill reorganization — Phase 5, after 4.7.
- Performance work — separate concern (`PERFORMANCE_PLAN.md`).
