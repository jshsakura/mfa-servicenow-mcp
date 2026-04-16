# Performance Optimization Plan

## Goals

1. Reduce per-request latency on repeated queries to the same table/query/field combination.
2. Eliminate N+1 API round-trips where batch resolution is possible.
3. Adopt the pooled HTTP session (`auth_manager.make_request`) across all resource modules, replacing bare `requests.get` calls.
4. Improve startup time by keeping lazy tool discovery tight and deferring non-essential imports.
5. Widen the existing `sn_query_page` / `sn_query_all` cache hit rate.

## Priorities (Highest ROI First)

| Priority | Area | Expected Impact | Effort |
|----------|------|----------------|--------|
| P0 | Resource modules: adopt pooled session | Every MCP resource call bypasses connection pooling today | Medium |
| P1 | `source_tools.py`: batch SI candidate resolution | Up to N sequential lookups reduced to 1 batch query | Medium |
| P2 | `flow_designer_tools.py`: reduce duplicate display_value queries | `_fetch_subflow_bindings` issues 4-6 sequential queries per call | Medium |

---

## Phase 1: Resource Module Session Adoption (P0)

### Problem

All three resource modules (`catalog.py`, `changesets.py`, `script_includes.py`) use bare `requests.get()` directly. Each call opens a new TCP connection, negotiates TLS, and closes it. The `AuthManager` already holds a pooled `requests.Session` with 20-connection pool, TCP keep-alive, and TLS session resumption.

### Work Items

#### `src/servicenow_mcp/resources/catalog.py`

| Line(s) | Current | Change |
|---------|---------|--------|
| 92-97 | `requests.get(url, headers=self.auth_manager.get_headers(), ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |
| 118-120 | `requests.get(url, headers=self.auth_manager.get_headers())` | `self.auth_manager.make_request("GET", url)` |
| 139-144 | `requests.get(url, headers=self.auth_manager.get_headers(), ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |
| 176-180 | `requests.get(url, headers=self.auth_manager.get_headers(), ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |

After: remove `import requests` from `catalog.py`. Parse `response.json()` consistently.

#### `src/servicenow_mcp/resources/changesets.py`

| Line(s) | Current | Change |
|---------|---------|--------|
| 43-48 | `requests.get(url, headers=self.auth_manager.get_headers(), ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |
| 56-59 | `requests.get(url, headers=headers)` | `self.auth_manager.make_request("GET", url)` |
| 63-67 | `requests.get(url, headers=headers, ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |

After: remove `import requests`. Use `json_fast.loads(response.content)` for deserialization consistency with the rest of the codebase.

#### `src/servicenow_mcp/resources/script_includes.py`

| Line(s) | Current | Change |
|---------|---------|--------|
| 43-48 | `requests.get(url, headers=self.auth_manager.get_headers(), ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |
| 58-60 | `requests.get(url, headers=headers)` | `self.auth_manager.make_request("GET", url)` |
| 63-66 | `requests.get(url, headers=headers, ...)` | `self.auth_manager.make_request("GET", url, params=request_params)` |

After: remove `import requests`.

### Validation

- `python -m pytest tests/test_resources_*.py -x` passes.
- Manual: call `catalog://items`, `catalog://categories`, and script include resource. Confirm 200 responses.

---

## Phase 2: Batch Script Include Resolution in `source_tools.py` (P1)

### Problem

`_find_script_include_by_candidate` (line 773) is called inside a loop for each SI candidate extracted from a widget script (line 1372-1388). If a widget references 10 script includes, that is 10 sequential API round-trips. Each call queries `sys_script_include` with a different candidate name.

### Work Items

#### New helper: `_batch_resolve_script_includes`

Create a function that takes a list of candidate names and resolves them in a single `sys_script_include` query using `sysparm_query=nameINc1,c2,c3...^ORapi_nameINc1,c2,c3...`. Return a dict mapping candidate name to the matching row.

Key details from current code:
- Query template: `name={candidate}^ORapi_name={candidate}^ORapi_nameENDSWITH.{candidate}`
- Fields: `["sys_id", "name", "api_name", "script"]`
- Scope and active filters applied per call

The batch version should:
1. Collect all unique candidates.
2. Build a single query: `nameINc1,c2,...^ORapi_nameINc1,c2,...^ORapi_nameENDSWITH.c1^ORapi_nameENDSWITH.c2...`
   - Chunk at 50 candidates per query to stay within URL length limits (using existing `_chunked` helper at line 802).
3. Apply scope and active filters once.
4. Return `{candidate_name: row}` mapping.

#### Refactor call site (~line 1372)

Replace the sequential loop:

```python
# Current (N+1):
for candidate in si_candidates:
    si_row = _find_script_include_by_candidate(config, auth_manager, ...)
```

With:

```python
# Batch (1-2 queries regardless of candidate count):
si_map = _batch_resolve_script_includes(
    config, auth_manager,
    candidates=si_candidates,
    scope=params.scope,
    only_active=params.only_active,
)
for candidate in si_candidates:
    si_row = si_map.get(candidate)
    ...
```

Keep `_find_script_include_by_candidate` as a single-record fallback for callers that need exactly one match.

### Validation

- Existing test suite covers `get_widget_table_references` which triggers this path. Verify tests pass.
- Add a test: mock `sn_query_page`, call with 5 candidates, assert only 1 (or at most 2 chunked) queries made.

---

## Phase 3: Reduce Duplicate Queries in `flow_designer_tools.py` (P2)

### Problem

`_fetch_subflow_bindings` (line 533) makes 4-6 sequential queries:
1. Subflow instances (raw) from `sys_hub_sub_flow_instance_v2` (line 548)
2. Subflow instances (display) from the same table (line 566)
3. Snapshots (raw) from `sys_hub_flow_snapshot` (line 584)
4. Snapshots (display) from the same table (line 600)
5. Master flows (display) from `sys_hub_flow` (line 627)

Queries 1+2 and 3+4 are the same table with different `display_value` settings, returning the same rows. The display values could be extracted from a single `display_value=True` query.

`_fetch_flow_structure` (line 710) also calls `_get_snapshot_id` (line 736), which queries `sys_hub_flow_snapshot` separately. When `_fetch_subflow_bindings` is called right after, the snapshot query is repeated.

### Work Items

#### Merge dual display_value queries in `_fetch_subflow_bindings`

Replace the two-query pattern (raw + display) with a single `display_value=True` query. Parse display values from the response directly. The raw sys_id values needed for reference resolution can be extracted from display value responses (they remain as sys_id strings in non-reference fields).

Affected: lines 548-576 (subflow instances) and lines 584-613 (snapshots).

Expected reduction: 4-6 queries down to 2-3 per `_fetch_subflow_bindings` call.

#### Cache `_get_snapshot_id` result per flow_id

The `_get_snapshot_id` function is called by both `_fetch_flow_structure` (line 736) and `_fetch_flow_triggers` (line 941). When `get_flow_details` with `include_structure=true` and `include_triggers=true` is called, the same snapshot lookup runs twice.

Add a simple per-call snapshot cache:
- Option A: Thread-local dict keyed by `flow_id`, cleared at the start of each tool invocation.
- Option B: Extend the existing `sn_query_page` cache (which already caches by query key). Since `_get_snapshot_id` uses the same query params each time, the existing cache should already handle this. Verify cache TTL (30 seconds) covers the typical multi-tool-call window.

Verify: check if the existing `sn_query_page` cache already deduplicates the `_get_snapshot_id` call. If it does, no code change is needed here. If the query params differ slightly (e.g., different `fields` lists), align the field lists to enable cache hits.

### Validation

- `python -m pytest tests/test_flow_designer_tools.py tests/test_flow_designer_crud.py -x`
- Add a test for `_fetch_subflow_bindings` that counts mock calls: assert 2-3 queries instead of 4-6.

---

## Execution Order

```
Phase 1 (P0): Resource module session adoption
  ├── catalog.py
  ├── changesets.py
  └── script_includes.py
  → Eliminates bare requests.get across all resource modules

Phase 2 (P1): Batch SI resolution in source_tools.py
  ├── New _batch_resolve_script_includes helper
  └── Refactor call site at ~line 1372
  → N+1 reduced to 1-2 batch queries

Phase 3 (P2): Flow Designer query dedup
  ├── Merge dual display_value queries
  └── Verify snapshot cache hit rate
  → 4-6 queries per subflow binding reduced to 2-3
```

## Risks

| Risk | Mitigation |
|------|-----------|
| `make_request` behavior differs from bare `requests.get` (e.g., retry logic, timeout handling) | `make_request` wraps the same underlying session. Review its signature to confirm `params` passthrough and response object compatibility. Test each resource endpoint. |
| Batch SI query URL length exceeds ServiceNow limits | Use `_chunked` helper (already exists) to split at 50 candidates. URL-safe encoded queries stay well within the 2000-character practical limit. |
| Merging display_value=True/False queries changes response structure for non-reference fields | Verify that `sys_id` fields return raw sys_id strings regardless of `display_value` setting (they do per ServiceNow Table API spec). |

## Out of Scope

- Database/ServiceNow server-side query optimization (outside this codebase).
- Async HTTP migration (would require broader architectural change).
- New tool development or feature additions.
- Changes to auth_manager session lifecycle or cookie handling.
