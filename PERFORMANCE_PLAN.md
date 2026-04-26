# Performance Status and Follow-Ups

This document used to be a forward-looking optimization plan. Those core items are now shipped, so it has been rewritten as a status record to avoid roadmap drift.

## Current Shipped State

### 1. Resource modules use pooled HTTP sessions

The resource layer now routes requests through `auth_manager.make_request(...)` instead of standalone `requests.get(...)` calls.

- `src/servicenow_mcp/resources/catalog.py`
- `src/servicenow_mcp/resources/changesets.py`
- `src/servicenow_mcp/resources/script_includes.py`

This means resource requests now benefit from the shared session configuration already present in `AuthManager`: connection pooling, keep-alive reuse, and consistent request handling.

### 2. Script Include candidate resolution is batched

`src/servicenow_mcp/tools/source_tools.py` now includes `_batch_resolve_script_includes(...)` and uses it in the widget dependency path.

That replaced the earlier N+1 lookup shape with batched resolution, which cuts repeated round-trips when a widget references multiple Script Includes.

### 3. Flow Designer querying is materially consolidated

`src/servicenow_mcp/tools/flow_designer_tools.py` now uses `display_value="all"` in the key subflow/snapshot path and reduces duplicate raw/display fetches.

The most important consolidation lives in `_fetch_subflow_bindings(...)`, which now retrieves both raw and display-oriented data with fewer sequential queries.

### 4. Startup still leans on lazy discovery

The lazy tool-discovery path remains intact, backed by the generated module index in:

- `src/servicenow_mcp/tools/_module_index.py`
- `scripts/regenerate_tool_module_index.py`

This keeps startup overhead lower by avoiding full imports when only a subset of tools is needed.

## Why this matters

These changes are the reason the current server shape already reflects the performance strengths called out in recent review:

- lower repeated-call latency through pooled sessions
- fewer unnecessary API round-trips in dependency analysis
- less duplicated Flow Designer querying
- lower startup/import cost through lazy discovery

In other words, the original plan is no longer pending work; it is part of the shipped baseline.

## Remaining Follow-Ups

The high-value performance work that was once planned is now done. Remaining work is mostly about keeping that state visible and preventing regression.

### Regression prevention

- keep generated artifacts in sync (`_module_index.py`, `docs/TOOL_INVENTORY.md`)
- keep package/docs counts aligned with the real packaged surface
- keep tests covering package inheritance and generated-file drift

### Future performance work, if new hotspots appear

These are optional follow-ups, not currently-blocking gaps:

1. add more targeted benchmark-style tests around high-volume read paths
2. measure cache-hit behavior on repeated Flow Designer/detail calls under realistic workloads
3. profile large local-source audit runs and repo-analysis helpers if latency becomes noticeable

## Out of Scope for this document

- breaking package-surface changes
- legacy-wrapper removal sequencing; see `CONSOLIDATION_PLAN.md` for the v1.11 public-surface cleanup
- speculative rewrites without measured hotspots

For compatibility and consolidation sequencing, see `CONSOLIDATION_PLAN.md`.
