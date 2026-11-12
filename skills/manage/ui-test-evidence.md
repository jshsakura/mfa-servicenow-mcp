---
name: ui-test-evidence
description: Run UI test cases in the debug browser and put screenshots + results into a workbook — without ever loading an image into context
context_cost: low
safety_level: confirm
delegatable: false
required_input: the test cases (steps + expected result), the page/user to test as, and the evidence form (.xlsx) or a new file name
output: files
tools:
  - act_in_debug_window
  - inspect_debug_window
  - manage_workbook
triggers:
  - "테스트 증빙"
  - "스크린샷 붙여"
  - "단위테스트 결과서"
  - "캡처해서 엑셀"
  - "test evidence"
  - "screenshot into excel"
---

# Instructions

Evidence screenshots are for PEOPLE. The model never needs to see them, so they
cost nothing: a screenshot is written to disk and only its path comes back.
**Never open a screenshot file.** That is the only step that spends image tokens
(about one token per 750 pixels), and nothing here needs it. Pass/fail is read
as TEXT from the page.

The debug browser is user-initiated: run this only when the user asked for test
evidence. It is for looking — the test steps are what a person would click, and
any data set-up goes through the API tools first.

## Pipeline

1. VALIDATE the inputs: each case has steps and an expected result; the form
   (or a new output file) is named. ASK for what is missing — do not invent
   expected results.

2. For each case:
   a. CALL `act_in_debug_window(actions=[...steps...], screenshot="viewport")`
      (`"element"` + `selector` for one component, `"full"` for a long page).
      Keep the returned `screenshot` path. Do NOT read the file.
   b. CALL `inspect_debug_window(evaluate="<JS expression>")` to read the
      outcome as text — a field value, a message, a row count — and compare it
      to the expected result. That is the pass/fail, at a few dozen tokens.
   c. Record: case id, result (pass/fail + the value read), screenshot path.

3. Every 10 cases or so — not only at the end — WRITE what you have:
   `manage_workbook(action="fill", path=<form>, output_file=<out>, rows_at={start_row, rows:[[id, result, ...]]}, images=[{path, cell}])`
   or, with no form, `manage_workbook(action="write", output_file=<out>, spec={sheets:[{title, rows, images:[{path, cell}]}]})`.
   The debug window prunes old captures (it keeps the newest 40 and anything
   from the last 30 minutes), so a long run that embeds only at the end can
   lose its first screenshots.

4. SHOW the user: the output file path, pass/fail counts, the failing cases with
   the value read. Not the images.

## Resolution

Captures are capped at 1024px wide (`SERVICENOW_SCREENSHOT_MAX_WIDTH`). That
cap is about what a model pays if it LOOKS; evidence is never looked at by the
model, so lowering it saves nothing here and makes the evidence harder for a
person to read. Leave it.

## ON ERROR

- `screenshot_note` says `only_viewport` / `truncated` for a `full` capture → the
  page did not scroll as one; capture the parts with `element` shots and say so
- A step fails → the reply names the step; record the case as "not run" with
  that reason — not as a fail of the feature
- An image does not embed (the workbook reply has `image_notes`) → report the
  path beside the case so the user can attach it by hand
- Window closed / signed out → stop and tell the user; do not open a new one
  unasked

## DELEGATE hint

Not delegatable: the debug browser is the user's shared window, and the run
needs their go-ahead. Only the final workbook path and counts go into the
conversation.
