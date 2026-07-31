# Adversarial Review: sync history guard draft

Context: current uncommitted diff in `src/servicenow_mcp/tools/sync_tools.py` adds
`_editors_since()` and uses `sys_update_version` history to decide whether a
drifted push involves another editor.

## Verdict

The v1.22.11 anchor/fetch model is directionally cautious:

- `_sync_meta` is no longer allowed to veto fetch by itself.
- `anchor_matches_disk()` forces the anchor to prove it still describes local
  files before skipping.
- If that proof fails, the code fetches and reconciles against real server
  content.
- Divergence keeps the working file and writes a `.remote` mirror, so local edits
  are not silently overwritten.

The risky part is the new history-based patch on top of it. It is trying to fix a
real problem, but it currently overclaims what a bounded/best-effort history read
proves.

## Finding 1: unconfirmed identity becomes false `CONFLICT_OTHER_USER`

Location: `src/servicenow_mcp/tools/sync_tools.py`, `_editors_since()`

Problem:

```py
if who and who != me and who not in others:
    others.append(who)
```

If `me == ""` because identity could not be resolved, every history row becomes
"other". Then the caller does:

```py
if editors["others"]:
    confirmed_other = True
```

That reintroduces the exact class of bug the existing push safety code was built
to avoid: unconfirmed identity must hedge, not accuse. A user with unresolved
SSO/browser identity can now get `CONFLICT_OTHER_USER` based solely on history
rows that might be their own.

Expected behavior:

- If `me` is unconfirmed/blank, history can say `other_editors_since_your_copy`
  is unknown or suspicious.
- It must not set `confirmed_other = True`.
- It must not return `CONFLICT_OTHER_USER`.

## Finding 2: `limit=20` makes a false "no other editor" claim

Location: `_EDITOR_HISTORY_LIMIT = 20`, `_editors_since()`, conflict message.

Problem:

The code queries at most 20 `sys_update_version` rows and then says:

> version history shows no other editor since your copy was taken

That is not proven when there are more than 20 versions after the anchor. A
coworker edit can exist at version 21, followed by 20 self-edits. The query sees
only self-edits and the tool tells the user this is a clean fast-forward.

This is a safety regression because the message converts incomplete evidence into
a positive safety claim.

Expected behavior:

- Either page until the history range is exhausted, or
- Treat a full page as inconclusive: "first 20 versions show no other editor" is
  not enough to say nobody else edited it.
- Never print "history shows no other editor since your copy was taken" unless the
  queried range is complete.

## Finding 3: ServiceNow date query is unproven and possibly malformed

Location:

```py
query += f"^sys_recorded_at>javascript:gs.dateGenerate('{since}')"
```

Problem:

`since` is a full timestamp string such as `2025-01-10 10:00:00`. ServiceNow
`gs.dateGenerate()` commonly expects separate date/time arguments. If this query
silently returns no rows, or errors on some instances, the code can misclassify
history as readable-but-empty or unreadable in inconsistent ways.

Expected behavior:

- Add a unit test pinning the exact query generated from a timestamp.
- Prefer a query form already known to work elsewhere in the repo.
- If the filter cannot be proven portable, do not use empty history as positive
  evidence.

## Finding 4: history check is skipped on bare `force=true`

Location: `update_remote_from_local()`, drift gate.

Problem:

`_editors_since()` only runs inside:

```py
if drifted:
    if not params.force:
        ...
```

So a bare forced push does not get the new history-based attribution. Maybe this
is intentional backward compatibility, but then the feature does not actually
protect forced overwrites. It only enriches the rejection path.

Expected behavior:

- Decide explicitly whether bare `force=true` should remain backward compatible.
- If yes, do not describe the history guard as covering forced pushes.
- If no, require `confirm_overwrite_updated_on` or run the same history check
  before force succeeds.

## Finding 5: docs/comments overstate "server history covers recovery"

Location: conflict/force comments and messages around `sys_update_version`.

Problem:

The comments imply the overwritten body stays recoverable in server version
history. That is likely true for tracked update-set records, but not a universal
guarantee for every table/ACL/configuration path this tool may touch.

Expected behavior:

- Soften wording to "may be recoverable" unless the table is known to have a
  current version row.
- Do not use server history as a reason to skip local backup unless that guarantee
  is validated for the specific record family.

## What is safe in v1.22.11

The anchor side is much better than the old local-watermark behavior:

- Clean tree + server equals anchor: skip is safe because the local file still
  matches the anchor.
- File differs from anchor: fetch.
- File deleted: fetch.
- Anchor has no SHA: fetch.
- After fetch, true divergence writes `.remote` and preserves the working file.

That is not "trusting local too much"; it is using local state only as a
provable common ancestor for 3-way comparison.

## Required tests before accepting the history patch

- Unconfirmed identity + history rows by current-looking user does not produce
  `CONFLICT_OTHER_USER`.
- More than 20 versions since anchor does not produce "no other editor" language.
- Full-page history result is marked inconclusive unless pagination completes.
- `sys_recorded_at` query string is pinned for a normal timestamp.
- History read failure leaves the conflict conservative but does not upgrade to
  confirmed other-user.
- Bare `force=true` behavior is explicitly tested and documented.

