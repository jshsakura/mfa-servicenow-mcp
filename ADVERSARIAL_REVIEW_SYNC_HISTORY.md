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


---

# Resolution (v1.22.13)

Checked each finding against the code rather than accepting or rejecting it on
the description. Four of five were real; one was already stale.

## Finding 1 — unconfirmed identity becomes false `CONFLICT_OTHER_USER` — CONFIRMED, fixed

Real, and worse than described: `_resolve_push_actor()` returns `("", False)` by
design when neither the configured username nor a live lookup resolves, so `who
!= me` was true for **every** history row and the whole history read as other
people. It re-entered the exact bug class `TestOwnEditIsNotAnAlarm` exists to
prevent, through a side door that bypassed the `confirmed and ...` guard the rest
of the gate uses.

Fixed at the source: `_editors_since()` takes `me_confirmed` and reports
`attributable`. Unattributable history names nobody, so `ownership_changed` stays
False and `CONFLICT_OTHER_USER` cannot fire on it. The response says identity
could not be confirmed instead.

Pinned by `TestEditorHistoryLimits::test_unconfirmed_identity_names_nobody`.

## Finding 2 — `limit=20` makes a false "no other editor" claim — CONFIRMED, fixed

Real. The message asserted a positive safety claim from a capped read — the same
"no silent caps" rule already applied to the download ledger, violated here.

`complete` now travels with the result: True only when the page came back short,
or when a version at/older than the anchor was reached (so the range is covered
however many rows follow). "Clean fast-forward" prints only when `checked and
complete and attributable`; otherwise the response names which limit was hit.

Pinned by `test_a_full_page_that_never_reaches_the_anchor_is_incomplete`,
`test_reaching_past_the_anchor_completes_the_range`,
`test_inconclusive_history_never_prints_a_clean_fast_forward`.

## Finding 3 — date query unproven / possibly malformed — CONFIRMED, removed

Real. `sys_recorded_at>javascript:gs.dateGenerate('<full timestamp>')` appears
nowhere else in this repo (the established idiom for a datetime field is the
plain `sys_updated_on>=<value>` form, 10+ sites), and the field's type was never
verified. The failure mode is the dangerous direction: a wrong filter returns no
rows, which reads as "no other editor" — a broken query turning into a safety
claim.

Not "fixed" — deleted. The query carries no date filter at all; the range is cut
client-side on `sys_created_on`, a plain datetime present on every table. Cutting
locally cannot fail toward a false clearance.

Pinned by `test_the_range_is_cut_locally_not_by_an_encoded_date_query`, which
asserts the exact generated query.

## Finding 4 — history check skipped on bare `force=true` — STALE, then decided

The quoted code (`if drifted: if not params.force:`) no longer existed at review
time: the call had been moved ahead of risk scoring, so it runs on forced pushes
too. The substantive question stands and is now answered explicitly.

Decision: **bare `force=true` remains an approval, not a re-gate.** Per this
repo's "gate, don't block" rule, force is how a human says "yes, overwrite that";
making it a wall pushes people to a cruder tool. The guard's job is to make the
rejection accurate and the audit log truthful — the force-path warning now names
the editors the *history* implicates, not `sys_updated_by`, which can be you while
the work at stake is someone else's. Documented in CLAUDE.md as NOT covering
forced pushes.

Pinned by `TestBareForceIsStillTheApproval`.

## Finding 5 — "server history covers recovery" overstated — CONFIRMED, softened

Real. Reworded to "for a record tracked in an update set the overwritten body is
normally recoverable from the server's version history, which is not guaranteed
for every table". No local backup was ever skipped on the strength of that claim,
so nothing else changed.

## Note on the review's read of v1.22.11

Its summary of the anchor model matches the code: local state is used only as a
provable common ancestor, and every way that proof can fail (content differs,
file missing, no recorded sha) falls to fetch.
