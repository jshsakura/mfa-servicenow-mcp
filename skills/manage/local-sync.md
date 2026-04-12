---
name: local-sync
description: Scan, diff, and push local portal source changes to ServiceNow with conflict detection
context_cost: low
safety_level: staged
delegatable: false
required_input: directory path (from download_portal_sources output)
output: status
tools:
  - diff_local_component
  - update_remote_from_local
triggers:
  - "로컬 동기화"
  - "로컬 푸시"
  - "변경 사항 확인"
  - "로컬 소스 올려"
  - "sync local"
  - "push local changes"
  - "local diff"
  - "what changed locally"
  - "upload local sources"
---

# Instructions

Synchronize locally edited portal source files back to ServiceNow.
This is a **STAGED** pipeline — never push without showing diffs first.

## GATE RULES

- **GATE 1**: Scan before diffing — know what changed
- **GATE 2**: Show diffs before pushing — review every change
- **GATE 3**: User confirms each push — no silent overwrites

## Pipeline

### Step 1 — Scan

```
CALL diff_local_component(path=INPUT_DIR)
```

Give the download root directory. Returns compact summary: which components have local edits, remote changes, or conflicts.

- If **no changes**: RETURN "All local files match remote. Nothing to push."
- If **remote_newer** items: WARN user — "These were updated on ServiceNow since download. Re-download or use force."
- If **conflict** items: WARN user — "Both local and remote changed. Review carefully."

### Step 2 — Diff (each modified component)

```
FOR EACH component with status = local_modified or conflict:
  CALL diff_local_component(path=COMPONENT_FILE_OR_DIR)
```

Show unified diff (compact, never full source).

- If `conflict_warning` is present, display it prominently
- Let user decide: push, skip, or re-download

### Step 3 — Push (user must confirm)

ASK: "Push these N changes to ServiceNow?"

```
ONLY after explicit confirmation:
FOR EACH approved component:
  CALL update_remote_from_local(path=COMPONENT_PATH)
```

Show for each push:
- Snapshot path (for rollback)
- Verification result (fields verified vs mismatched)
- Updated `_sync_meta.json` status

After all pushes, suggest: `git add . && git commit` to create a local checkpoint.

## ON ERROR

| Error | Action |
|-------|--------|
| `CONFLICT` | Suggest re-download or `force=true` with explicit user approval |
| `403 Forbidden` | Check ACLs, update set scope, or API permissions |
| `Component not found` | `_map.json` may be stale — re-download sources |
| `Instance mismatch` | Local files are from a different instance — re-download |

## DELEGATE hint

DO NOT delegate. This pipeline requires user confirmation at each gate.
Context cost is low — only diffs are shown, never full source.
