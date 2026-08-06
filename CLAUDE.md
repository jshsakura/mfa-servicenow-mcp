# MFA ServiceNow MCP — Development Rules

## Tool Description Rules (LLM Context Budget)

Tool definitions are sent to the LLM on every request. Every character costs tokens.

### Description Limits — a target, with a floor underneath it

- Tool `description`: aim for 120 chars. State what it does + one usage hint.
- Parameter `description`: aim for 80 chars. No examples unless critical.
- Good: `"List Flow Designer custom action definitions. Use list_actions to find sys_ids."`
- Bad: `"This tool allows you to list all of the custom action definitions that have been created in the Flow Designer interface of ServiceNow, returning their names, statuses, and other metadata."`

**These are budgets to write against, not a limit to retrofit.** Descriptions
have a FLOOR: cut below it and tool selection gets worse, so trimming is not a
pure saving — it is a token-vs-accuracy trade, and past the floor it loses. This
was measured, not assumed: truncating param descriptions dropped routing hints
("use portal tracing/search tools when …") and changed meaning (dropped "or
sys_id of the parent table"), and the model mis-routed calls. That is why the
schema compactor forwards them verbatim (`server.py::_get_tool_schema`) and
truncates defaults instead.

So: **do not open a PR that compresses existing descriptions to hit the number.**
An automated length sweep will find ~28 params over 80 chars. Those are known,
and shortening them is not the win — every one was written long because the short
version routed worse.

Nothing enforces the number, deliberately. A hard check would have exactly one
effect: descriptions written to satisfy a linter rather than a reader.

**Where the real savings are**, in order — all functional, none of them string
length:

1. **Package layering.** `standard` is the no-config base every package
   `_extends`, so a specialist cluster added there is paid for by every session
   that will never call it (~2-3k tokens/request for the portal/source-analysis
   set alone). Move clusters out to opt-in read layers.
2. **Action multiplex + `_FIELDS_BY_ACTION`.** One `manage_*` tool with narrowed
   per-action fields beats N tools. Applied to 7 tools; a `manage_*` tool without
   the map exposes every field on every action. Merging user-facing *getters* is
   NOT safe — it degrades selection; internal resolver merges are.
3. **Output projection.** Read tools defaulting to `fields=""` return whole
   records. This is the largest remaining win and it costs no accuracy.

Never save tokens by under-fetching a field a caller needs — a re-query costs far
more than the projection saved.

### Parameter Model Rules
- `Optional[str]` is fine — the schema compactor strips `anyOf` noise automatically.
- Never put long default values (>60 chars) in `Field(default=...)`. Move to docstring or omit.
- Don't duplicate the tool description in the Pydantic model docstring — the compactor strips it.
- Use `Field(description=...)` on every parameter. Undocumented params waste LLM reasoning.

### Adding New Tools Checklist
1. Follow existing patterns in the same file — don't invent new structures.
2. Register in `config/tool_packages.yaml` under the correct package(s).
3. Read-only tools go in `standard`. Write tools go in domain packages only.
4. Add `"Use <list_tool> first to find the sys_id."` to get-detail tool descriptions.
5. Add tests: happy path, error, not-found (for detail), count_only (for list), filters.
6. Run `python -m pytest tests/ -x` before committing.

## Download / Sync Flow (LLM must follow)

Source downloads write full bodies to disk; only summaries return to context.
Picking the wrong tool wastes round-trips and tokens. Default decision tree:

0. **Unfinished local work surfaces automatically** — `sn_health` carries a
   `workspace` summary (unpushed edits, unresolved `.remote` conflicts) when
   any exist; silent otherwise. There is deliberately NO separate brief tool:
   automation the LLM must remember to invoke is not automation. Drill down
   with `diff_local_component(path=<tree>, verdict=True)`.

   A conflict is a QUESTION, not a notice — you and the server both changed the
   same body and which wins is not the tool's call. `sn_health` carries
   `decision_required` with the three options as calls (keep both / take theirs /
   keep mine) and **every** conflicting path, not a sample; it keeps coming back
   until the sidecar is gone, and nothing is overwritten meanwhile. The scan
   budget bounds file HASHING only — spotting a conflict is one `exists()`, so a
   speed guard must never be why one goes unlisted.

1. **Reading one widget/SI body** → `get_widget_bundle` (widget only) or
   `get_portal_component_code` with `fetch_complete=True`. Do NOT loop on
   `script_offset` unless the field is genuinely >12KB and you only need a slice.
2. **Bulk source dump for analysis** → `download_app_sources(scope=...)` (Step 1).
   Then `audit_local_sources(source_root=...)` (Step 2). Do NOT chain 7
   individual `download_*` sub-tools — they exist for targeted refreshes only.
3. **Targeted refresh** (portal slice or server-side families) → the specific
   `download_portal_sources(widget_ids=...)` (portal) or
   `download_server_sources(families=[...])` (SIs/BRs/UI/api/security/admin).
4. **Already downloaded before** → `diff_local_component(path=...)` first.
   Re-download only if diff reports drift, or if `_manifest.json` is missing.
   A `.remote` mirror is the SERVER's copy, so it is only worth anything while it
   still IS the server's copy. Every surface that points at one holds the live
   record and brings it up to date first (`sync_anchor.refresh_mirror`) — merging
   from a frozen sidecar produces a body nobody has and a push the gate rejects.
   Two hard rules: only an **untruncated** read may write a mirror (the bulk/Batch
   path clips large fields, and a clipped mirror is worse than a stale one, so
   `_component_field_verdicts` takes `remote_is_complete`); and an **offline**
   surface may report a conflict as unresolved but never call the sidecar current.
   For "is any of this stale?" over a folder/scope, use `verdict=True` —
   per-component verdicts + line counts, zero source bodies in context.
   Cross-instance comparison → `compare_instances` (live, both sides).
5. **Push back to ServiceNow** → `diff_local_component` → `update_remote_from_local`.
   **No anchor means no push.** A component with no `_sync_meta` entry cannot be
   proven to descend from any version the server ever held, so the gate returns
   `CONFLICT_NO_ANCHOR`. It used to pass: with no entry, the counter, the sha and
   the timestamp are all empty, drift read as "nothing moved", and an arbitrarily
   old local body overwrote another developer's current work at `risk_level:
   none` — absence of evidence scored as evidence of absence. The fix is to
   re-download (it anchors the record and keeps your edits; a real divergence
   lands as a `.remote` sidecar), not to reach for `force`.

   **A server fact is read from the server, never from `_sync_meta`.** The anchor
   records what YOU last received; it is not a cache of the record's state. The
   gate used to answer "did someone take this over" by comparing the editor name
   cached at download against the live `sys_updated_by` — a stale copy of a server
   fact on one side, and on the other a field that names only the LAST editor. So
   `download v1 → bob edits v2 → you push anything` left bob in neither value, and
   reverting him scored as your own safe edit. WHO changed a record is now asked
   of its `sys_update_version` history over the range since your anchor
   (`_editors_since`), on the conflict path only.

   That read is bounded, so what it PROVES is carried with it and every limit is
   a stop: `checked` (an unread history is never a clearance), `complete` (the
   read is capped newest-first — a full page that never reaches back to your
   anchor can hide a coworker's edit behind your own later versions), and
   `attributable` (with an unresolved session every author trivially "is not
   you", so unconfirmed identity names NOBODY — it must hedge, never accuse).
   "Clean fast-forward" is printed only when all three hold; otherwise the
   response says which limit was hit. The range is cut client-side on
   `sys_created_on`, never by an encoded date filter: a wrong or unsupported
   filter form fails by returning no rows, which would read as "no other editor"
   — a broken query silently becoming a safety claim.

   **`force=true` alone remains the approval, not a re-gate.** The history guard
   makes the rejection accurate and the audit log name the right person; it is
   deliberately not a second wall in front of force, so do not describe it as
   protecting forced pushes.
6. **Incremental download is REMOTE-FIRST, per record** (`download_map.stale_sys_ids`).
   Never gate the fetch on a local aggregate. It used to query
   `sys_updated_on >= max(local anchors)`: a record whose own anchor had lagged
   (conflict, kept local edits, legacy tree, folder deleted) sat below a MAX any
   freshly-synced sibling had already raised, so the query never returned it —
   the download truthfully reported "0 changed" while the local copy stayed
   stale, forever, because a max watermark only rises. Now every download reads a
   live ledger (`sys_id,sys_updated_on,sys_mod_count`, no bodies) and compares
   each record to ITS OWN anchor. Fetch more rather than miss one: an unreadable
   ledger falls back to a full download, and a ledger that hits its record cap
   says `INCOMPLETE CHANGE LIST` instead of implying everything is current.

   **An anchor may only veto a fetch while it still describes the files on disk**
   (`sync_anchor.anchor_matches_disk`). `_sync_meta` is a local CLAIM, not proof:
   "the server matches my anchor" says nothing about the copy you would be left
   reading if that copy is not what the anchor describes. Deleted, edited, or
   never sha-recorded ⇒ the claim is dropped and the record is fetched and
   reconciled against real content. The anchor's real job is telling YOUR edit
   from THEIR change (3-way) — that needs a local record; deciding what to
   download does not.
7. **Re-download is live-anchored (`utils/sync_anchor.py`)**: drift decisions use
   the live `sys_mod_count` (authority) plus a per-field content sha recorded in
   `_sync_meta` — there is NO frozen `_baseline/` snapshot anymore. Locally edited
   files are never overwritten; a true conflict keeps your working file and writes
   an always-fresh `<field>.remote.<ext>` mirror of the CURRENT server body next to
   it. Merge into the main file, push; the mirror auto-clears. NEVER edit or push
   `*.remote.*` files — they are the server's copy, not the component (push rejects
   them). Legacy `_baseline/` dirs are swept automatically on the next download.

Standard download root: `temp/<instance>/<scope>/_manifest.json`. Treat its
presence as "already fetched"; check `downloaded_at` for freshness.

## Deployment XML (LLM must follow)

An `<unload>` file is just text, so a hand-assembled one is indistinguishable
from a real export by inspection. That is not hypothetical: a set of day-old
XMLs was built from local copies, shipped as current, never imported, and
recorded as deployed — and importing them would have reverted two other
developers' same-day work. The push gate (`update_remote_from_local`) never
applied, because that path was never taken.

**NEVER hand-write or hand-edit a deploy XML.** The only legal source is
`export_record_xml`, which reads the live `sys_update_version` and has no
local-file path. It issues an origin certificate (`<file>.xml.meta.json`,
`utils/deploy_ledger.py`) recording the source instance and each record's live
version stamp — that certificate is what makes "came from the live server"
provable rather than claimed.

Sequence, all three steps:

1. `export_record_xml` — build from live. Never assemble by hand.
2. `verify_deployment_xml(mode='preflight')` — **before** import. Run it against
   the SOURCE to test the file's freshness (`live_newer` = someone edited after
   your export; the import would revert them, so re-export). Against the TARGET
   it previews what the import changes. `deployable: false` means stop.
3. Import, then `verify_deployment_xml(mode='postflight')` against the TARGET —
   `not_applied` means it never landed. Do not record a deployment as done on
   anything else. Confirmation is written into the certificate.

An XML with no certificate returns `unanchored` and is refused before any
network call; `allow_unanchored=true` is a deliberate second approval, not a
default. Unconfirmed exports surface on `sn_health` under `deployments` — same
reason as step 0 above: nobody has to remember to ask.

## TLS Impersonation (curl_cffi, default-ON)

Default-ON is a deliberate policy: JA3-hardened instances silently reject stock
`requests` even with valid cookies (issue #37), and the failure is invisible
until hit. Keep it default-ON; flip `SERVICENOW_TLS_IMPERSONATE=off` only when
curl_cffi itself regresses on an instance. Semantics live in
`_build_http_session` and its tests.

## Auth Separation

- **Basic/OAuth/API Key**: Table API only. Never call undocumented APIs.
- **Browser auth**: Can use processflow API and other session-only endpoints.
- Gate browser-only calls behind `_is_browser_auth(config)`.
- Never silently try browser-only APIs with basic auth — it wastes a network round-trip.

## auth_manager.py is FROZEN — bug fixes only

The FROZEN scope is the **`AuthManager` class core** (the browser/network/timing-
coupled methods — especially `_login_with_browser_sync`, `make_request`,
`get_headers`). Its behavior is coupled to real servers, real browsers, and
timing that mock tests cannot fully verify — refactors here break in production,
not in CI (probe-path saga: 8 patch versions; headless-first:
shipped→broken→reverted→re-shipped).

Stateless module-level helpers (cookie parsing, URL/response predicates, log
redaction, HTTP-session factory, DOM helpers) were extracted to sibling modules
(`_http_session.py`, `_cookies.py`, `_url_predicates.py`, `_response_predicates.py`,
`_diagnostics.py`, `_browser_dom.py`) in v1.18.25 and re-exported byte-identically;
those are normal code under the usual rules. The freeze is about the coupled class.

- **Do NOT refactor, split, reorder, or "clean up" the AuthManager class.** Structural
  change only on explicit maintainer request, gated on the invariant tests below.
- Bug fixes = minimal diffs. If a change breaks one of these tests, the change
  is wrong — fix the change, not the test.
- Adding NEW invariant-pinning tests is always welcome; that is the sanctioned
  way to make this file safer.

The behavioral invariants are pinned in tests, not documented here:

| Invariant area | Pinned by |
|---|---|
| Headless-first login: cookie gate, MFA fast-detect, cooldown-clock restore on every headless bail, `force_interactive=True` ⇒ visible, window closed on every raise path, `LOGIN_COOLDOWN` | `test_auth_manager_final.py::TestLoginWithBrowserSync` |
| Sliding session TTL (`_mark_browser_session_recently_valid` on every 200) | `test_auth_manager_browser.py` |
| User-close = cancellation (15s cooldown, `LOGIN_CANCELLED_BY_USER`) | `test_auth_manager.py::TestBrowserLoginErrorHandling` |
| Probe default `sys_user_preference`, NEVER `sys_user` | `test_cli.py` |
| Playwright startup non-fatal + background daemon self-heal (`sys.frozen` skip, `SERVICENOW_AUTO_INSTALL_CHROMIUM=off` opt-out); never inline/blocking install, never a startup raise | `test_auth_manager.py::TestStartupNonFatalChromium`, `::TestAutoInstallChromium` |

Design history and the "why": issues #37 (TLS), #45 (headless-first), #62
(Playwright bump), and git log on `auth_manager.py`.

## Version Bumps & Git Tags

- Always patch increment: `x.y.z` → `x.y.(z+1)`.
- Never jump minor/major unless explicitly asked.
- **After every version bump commit, immediately create and push the git tag:**
  ```
  git tag v{version} && git push origin main v{version}
  ```
- Never push a version bump commit without its corresponding tag.

## Schema Optimization

`server.py::_get_tool_schema()` automatically compacts all Pydantic schemas:
- Strips `title` fields (redundant with `description`)
- Flattens `anyOf` nullable unions to simple types
- Removes top-level model `description` (docstring)
- Truncates long `default` string values (>60 chars)

This saves ~25% context tokens across all tools. Don't bypass this.

## A Guard May Only Claim What It Actually Read

Every safety bug in this repo has been the same shape, found eleven times in
three days: **a signal that was never read, rendered as a signal that came back
clean.**

- `max(local anchors)` decided nothing changed → a lagging record was never fetched
- no `_sync_meta` entry → "no drift" → an ancient body overwrote current work
- a cached `sys_updated_by` → "nobody else touched it" while their edit sat live
- a 20-row history page → "no other editor since your copy"
- an empty history (untracked table) → the cleanest possible answer
- a `.remote` written once → "the server's CURRENT body"
- six different `None`s from the hold check → "no one is holding this record"
- two `complete` sets in another app → "two in-progress sets, your change is split"
- a badge reading the ACTIVE instance env → "this window is dev" on a prod window
- a PyPI JSON cache minutes behind the upload → "1.22.24 is not published"
- a live pid and an answering CDP port → "a window you can use", tabs never asked
- a `sysparm_orderby` the Table API does not have → 21 "newest first" reads, unordered
- a filter on a column that does not exist → the condition is DROPPED, 808 rows
  come back, and one of them is returned as *this* flow's structure

None of these were wrong logic. Each was an **absence** — unread, unanchored,
capped, stale, closed — scored as **evidence of safety**, and every one of them
printed a confident sentence on top of it.

So, for anything a caller could act on:

1. **Return what you PROVED, not just what you found.** A bounded or best-effort
   read carries its limits with it: `checked` / `complete` / `attributable` /
   `determined`. `_editors_since` and `_record_update_set_hold` are the pattern.
2. **Never collapse "we could not find out" into "there is nothing."** If one
   function returns `None` for six reasons, the caller cannot tell them apart —
   and it will pick the reassuring one. Split the return.
3. **The reassuring branch is the one that needs the guard.** Print "safe",
   "clean fast-forward", "up to date", "no other editor" ONLY when every input
   backing it came back and covered the whole question. Otherwise say which limit
   was hit — a bare "could not confirm" reads as "fine".
4. **Describe the other thing by reading it.** If you hold its sys_id, look it
   up. Inferring its state from a name match is what turned closed sets into a
   live conflict.
5. **A failure must degrade toward the expensive answer**, never the quiet one:
   fetch more, block, ask. Over-fetching is recoverable; a silent miss is not.
6. **A slow answer is not a negative answer, and a dead end is not a report.**
   A source that lags — a CDN cache, an index written minutes after the thing it
   indexes, a queue — can only say "not visible yet", never "not there". Ask the
   AUTHORITATIVE source before you report: the install index rather than the JSON
   API, the publishing JOB rather than the workflow that contains it. If it still
   does not resolve, fall back, keep going, and warn — do not hand back a bare
   failure. Rule 5 is about what to DO (block, ask); this is about what to SAY.
   "Could not confirm, so I used X, treat Y as unverified" is actionable;
   "failed" leaves the caller with nothing but the work of asking again.
7. **A mock cannot tell you what the server does with your request.** ServiceNow
   accepts what it does not understand and moves on: an unknown `sysparm_*` is
   ignored, an unknown field in an encoded query has its **condition dropped**
   (so the read returns the WHOLE TABLE), and an unknown field in
   `sysparm_fields` is simply absent from the payload. None of these raise, and
   a fixture answers with whatever key it was written with — so every one of
   them passes a full green suite. Field and parameter names are only ever
   proven against a live instance. `scripts/audit_query_fields.py` sweeps every
   literal field name in the package against a real schema; run it after
   touching a query, and treat a table it could not read as **unchecked**, not
   as passed.

## No Real Identities in Code — HARD STOP, NO EXCEPTIONS

This is a **public open-source** repo. A commit is permanent: once pushed, the
string is in the public history forever and stays reachable by SHA even after the
file is "fixed" in a later commit. Deleting it later does NOT undo it — the only
real remedy is a full history rewrite, a force-push, and asking GitHub to purge
cached objects, which breaks every clone and every tag.

**NEVER write any of these into source, tests, fixtures, docstrings, comments,
commit messages, issues, or docs:**

- a real person's name, user_name, login, or email (`jane.doe`, `Jane Doe`,
  `jane.doe@<their-employer>.com`)
- a real company name, domain, instance URL, scope namespace, or company code
- anything else that identifies a real customer, colleague, or system

This has already happened three times in this repo — a colleague's full name + login
sat in a test fixture across ~150 commits, a real work email sat in a source
comment, and a second colleague's login sat in two more fixtures. All three came
from pasting real debug output into code. **That is the failure mode: real data
arrives by copy-paste from a live session.** `scripts/check_real_identities.py`
now blocks it at commit time — the rule below is why, not the enforcement.

Rules that follow from it:

1. **Placeholders only**, always: `alice` / `bob` / `other.dev`, `my_app`,
   `x_myapp`, `example.com`, `Sprint 12 fixes`, `https://test.service-now.com`.
2. **Anything pasted from a live instance is contaminated until proven clean.**
   Real logs, real records, real screenshots — rename every identifier before it
   goes anywhere near a file.
3. **Before every commit, grep the diff.** Names, `@`-emails, real domains. If
   you are touching a file that already contains such a string, you are about to
   commit it again in your tree — fix it in that same commit, do not "leave it
   for later".
4. **Never announce it in a commit message or issue.** "Removes a real name from
   a fixture" is a public signpost to exactly what to look for in the history.
   Scrub it silently and report the fix to the maintainer directly.
5. If you find one, tell the maintainer **immediately and privately** — it is a
   disclosure incident, not a cleanup chore.

## Pre-commit

- `isort` + `black` + `ruff` run on commit. Format before committing.
- Run `python -m pytest tests/ -x` to verify all tests pass.
