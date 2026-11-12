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
  - manage_portal_component
  - manage_portal_layout
  - sn_aggregate
  - sn_query
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
- If the result lists a `.remote` sidecar for the component, a conflict mirror
  exists on disk — see "Conflict resolution" below
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

## ServiceNow-owned record (`SERVICENOW_OWNED`)

A push to a record ServiceNow delivers (a baseline widget, an Employee Center
header) is stopped with `decision_required`. Editing it in place makes it a
customization: the next upgrade skips it and ServiceNow's fixes stop reaching
it. That is the user's call — ASK, showing both options from the response.

- **Edit in place** — the user accepts the upgrade cost:
  `update_remote_from_local(path=..., confirm_servicenow_edit="approve")`.
- **Clone and edit the copy** — the original stays upgradeable:
  1. CALL the clone from the response:
     `manage_portal_component(action="clone_widget"|"clone_header_footer", source=<sys_id>, new_id=..., name=..., scope=...)`.
     Unapplied fields come back named (e.g. a category value the target does
     not have) — report them.
  2. Point the pages at the copy — ONLY the pages the user means. Pages are
     shared between portals, so "every placement of the original" can include
     other portals' pages, and swapping those changes screens nobody asked about.
     - Which pages: `download_portal_sources(portal=...)` or `(page_ids=[...])`
       lists each widget with the page it sits on (`widget_source`).
     - Count first: `sn_aggregate(table="sp_instance", query="sp_widget=<original sys_id>")`
       — `sn_query` returns at most 100 rows, so a list without the count can be partial.
     - Read the placements: `sn_query(table="sp_instance", query="sp_widget=<original sys_id>", fields="sys_id,sp_column")`.
     - SHOW the user the instances on THEIR pages and get a go-ahead, then for each:
       `manage_portal_layout(action="replace_widget", instance_id=<sys_id>, sp_widget=<new_id>)`
       (parameters and CSS on the instance are kept).
  3. A header/footer lives on the THEME (`sp_theme.header` / `footer`), not on a
     page: `manage_portal_component(action="update_code", table="sp_theme", sys_id=<theme>, update_data={"header": <clone sys_id>})`.
     Check the THEME's own origin first: changing a ServiceNow-delivered theme
     is itself a customization — the same upgrade trade-off as editing the
     original header. Tell the user before doing it; a theme used by several
     portals changes all of them.
  4. `download_portal_sources(widget_ids=["<new_id>"])`, move the edits into the
     copy, then the normal Step 2–3 diff → push.

`download_portal_sources(portal=...)` / `(page_ids=[...])` marks every record
with its `origin`, so this choice can be made before editing, not at push time.

## Conflict resolution (`.remote` mirror)

When both local and remote changed, re-download does NOT overwrite your edits.
It keeps your working file and writes a `<field>.remote.<ext>` sidecar holding the
CURRENT server body next to it (an always-fresh mirror, refreshed every download).

Resolve a conflict like this:
1. Open both `<field>.<ext>` (your edits) and `<field>.remote.<ext>` (server body).
2. Merge the server's changes INTO your working file — never the other way.
3. Push the working file with `update_remote_from_local`. The mirror auto-clears
   on the next successful reconcile.

**NEVER edit or push a `*.remote.*` file** — it is the server's copy, not the
component. `update_remote_from_local` hard-rejects it (it is a sidecar, not a field).

## ON ERROR

| Error | Action |
|-------|--------|
| `CONFLICT` | Remote changed since download (by you/unattributed). Re-download to get a fresh `.remote` mirror and merge (see "Conflict resolution"), or `force=true` with explicit user approval |
| `CONFLICT_OTHER_USER` | A DIFFERENT user (`remote_updated_by`) edited it after your download. Show the user WHO + WHEN; recommend coordinating or re-downloading and re-applying. If the user still wants to overwrite that person's change, pass `force=true` |
| `403 Forbidden` | Record may be locked to another user's open update set — check ACLs, update set scope, or API permissions |
| `Component not found` | `_map.json` may be stale — re-download sources |
| `CROSS_INSTANCE` | Local source is from a DIFFERENT instance than the target (e.g. dev→test). To deploy without re-downloading, re-run with `cross_instance_deploy=true` — the target record is re-resolved BY NAME on the target (its own sys_id), safe whether or not the instances share sys_ids |
| `TARGET_NOT_FOUND` | Cross-instance deploy: no record of that name on the target. It updates an existing record only — never creates. Create it on the target first if intended |
| `SERVICENOW_OWNED` | Baseline record — see "ServiceNow-owned record": ask edit-in-place vs clone |
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
