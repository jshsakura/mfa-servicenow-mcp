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
- Verification result (fields verified vs mismatched)
- Updated `_sync_meta.json` status

> Recovery: ServiceNow versions every record server-side (Versions tab / update sets),
> so no local snapshot is taken — roll back through the platform's version history if needed.

After all pushes, suggest: `git add . && git commit` to create a local checkpoint.

## ON ERROR

| Error | Action |
|-------|--------|
| `CONFLICT` | Remote changed since download (by you/unattributed). Re-download, or `force=true` with explicit user approval |
| `CONFLICT_OTHER_USER` | A DIFFERENT user (`remote_updated_by`) edited it after your download. Show the user WHO + WHEN; recommend coordinating or re-downloading and re-applying. If the user still wants to overwrite that person's change, pass `force=true` |
| `403 Forbidden` | Record may be locked to another user's open update set — check ACLs, update set scope, or API permissions |
| `Component not found` | `_map.json` may be stale — re-download sources |
| `CROSS_INSTANCE` | Local source is from a DIFFERENT instance than the target (e.g. dev→test). To deploy without re-downloading, re-run with `cross_instance_deploy=true` — the target record is re-resolved BY NAME on the target (its own sys_id), safe whether or not the instances share sys_ids |
| `TARGET_NOT_FOUND` | Cross-instance deploy: no record of that name on the target. It updates an existing record only — never creates. Create it on the target first if intended |
| `TARGET_AMBIGUOUS` | Cross-instance deploy: multiple records share the name on the target — disambiguate before deploying |

## Cross-instance deploy (dev → test)

To promote a change you edited against `dev` onto `test` WITHOUT re-downloading test's source:

```
update_remote_from_local(path=DEV_COMPONENT_PATH, cross_instance_deploy=true)
```

The target record is matched **by name** on the target instance and pushed to ITS own sys_id, so it works whether or not dev/test share sys_ids and never touches the wrong record (0 matches → `TARGET_NOT_FOUND`, >1 → `TARGET_AMBIGUOUS`).

To just **compare** the same record across two instances (no push), use `compare_instances(source=dev, target=test, table=..., key_field=..., fields="script,css,template,...")` — read-only, by business key.

## DELEGATE hint

DO NOT delegate. This pipeline requires user confirmation at each gate.
Context cost is low — only diffs are shown, never full source.
