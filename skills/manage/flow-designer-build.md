---
name: flow-designer-build
description: Build or edit a Flow Designer flow yourself by driving Workflow Studio in the debug browser, verifying every save on the server
context_cost: medium
safety_level: confirm
delegatable: false
required_input: what the flow must do (trigger, steps, run-as) and the update set it belongs in
output: status
tools:
  - manage_flow_designer
  - open_debug_window
  - act_in_debug_window
  - inspect_debug_window
  - sn_query
  - manage_changeset
triggers:
  - "플로우 만들어"
  - "플로우 수정"
  - "플로우 디자이너"
  - "트리거 추가"
  - "build the flow"
  - "edit the flow"
  - "add a trigger"
---

# Instructions

Flow Designer has no write API, so YOU build the flow: drive Workflow Studio in
the debug browser and read the result back from the server after every save.
Do not hand the editing to the user — the window exists so the agent can do it.
The user only answers questions: which update set, and whether to activate.

The window is its own ServiceNow session. What it saves is captured into the
window's update set, not the one `manage_session_context` reports for the API.
So the capture target is proven from the server after the first save, never
assumed from either picker.

## Pipeline

1. READ what exists: `manage_flow_designer(action="get_detail", flow_id=...)` for
   an existing flow, or the spec the user gave. ASK once which update set this
   belongs in when it is not stated — a set named for other work is a question,
   not a match.

2. OPEN the window: `open_debug_window(url="/now/workflow-studio/home")`.
   `CHOOSE_WINDOW` means several windows are open after a restart: pick by the
   tabs (the Workflow Studio tab holding this flow) and call again with
   `window=<n>`; ask the user only when the tabs do not settle it.

3. SET the window's capture target in the window itself: the app/update set
   picker in the header, to the set from step 1. Read it back as text
   (`inspect_debug_window(evaluate=...)`) — never from a screenshot.

4. BUILD in small batches: `act_in_debug_window(actions=[...])`, a few steps per
   call, by visible text (`text=Add a trigger`) or aria label. Read the outcome
   as text after each batch. SAVE after each logical block (trigger, each action,
   each branch).

5. VERIFY each save on the server, both:
   - structure: `manage_flow_designer(action="get_detail", flow_id=...)` — the
     trigger/steps/conditions just built are there
   - capture: `sn_query(table="sys_update_xml", query="nameLIKE<flow sys_id>^ORDERBYDESCsys_updated_on", fields="name,update_set.name,sys_updated_on")`
     — the newest entry is in the set from step 1. A wrong set: STOP, tell the
     user, move it with `manage_changeset(action="move_file", changeset_id, entry_ids, target_changeset_id)` on their OK.

6. ACTIVATE only on the user's explicit OK: activation makes the flow run on
   real records.

7. REPORT: what was built, the get_detail summary, the update set it is in,
   active or draft.

## Workflow Studio recipes (measured on a live instance)

Read the outcome of every batch from `page_state` in the act reply — focused
field, `near_focus` (the items of a menu that just opened), `dialogs` (title +
its buttons), `alerts` (the editor announces moves there). Take a screenshot
only for a layout question; one per step is what made a session slow.

- **Edit mode**: a published flow opens Read-only (status bar). Click
  `text=Edit flow` first; Undo/Redo appear once it took.
- **Update set moves under you**: the current update set is a USER preference,
  shared by the window and every API session of the account. Editing a flow of
  a scoped app switches it to that app's last set. Any write's
  `update_set_context.changed_from` says it happened — switch back before the
  next save, and never "fix" it by asking the user about another session.
- **Autosave**: in edit mode EVERY change is saved to the server as a draft
  (History shows "Autosaved") and captured into the window's update set. There
  is no "try it without saving" — undo a change with History → Restore.
- **Move a step** (also into / out of an If): never delete and recreate it.
  `press` Enter on `[aria-label^="Hit enter to move action N,"]`, then ArrowUp /
  ArrowDown (each one is announced in `alerts`), then Enter. A dialog "Are you
  sure you want to make this change?" may follow → `[role=dialog] button:has-text("OK")`.
  Moving can drop data-pill references the dialog names; a red asterisk on a
  step afterwards is a broken pill — fix it before the next block.
- **Step rows**: `.section-item[data-position-order="N"]` (N = the number shown).
- **More actions menu**: `[aria-label="More Actions menu"]` — items arrive in `near_focus`.
- **History / restore**: `button[data-tooltip="History"]` → click the version
  (e.g. `text=Deployed`) → `button:has-text("Restore")` → `[role=dialog] button:has-text("Restore")`.
- Icon buttons are named only by `aria-label` / `data-tooltip`. On a miss, the
  step's `near_matches` gives the selector to use (`[data-tooltip="History"]`).
- Batch several steps per call; wait with `wait_for` on the next element, not
  a fixed `wait`.

## ON ERROR

- Element not found → use the step's `near_matches` (text and label-attribute
  candidates) and retry once; then say which step failed
- `WINDOW_NOT_AVAILABLE` → another terminal holds that window; pick another or ask
- The window shows a login or MFA page → the user signs in; wait, do not retry
  a login yourself
- get_detail does not show a step the window showed as saved → the save did not
  land; redo that block, do not move on
- Captured into the wrong update set → step 5; never leave it for later

## DELEGATE hint

Not delegatable: the debug browser is the user's window, and set/activation
choices are theirs. Only the get_detail summary and the update set go into the
conversation.
