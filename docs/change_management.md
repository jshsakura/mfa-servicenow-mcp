# Change Management

One tool, `manage_change`, covers change requests (`change_request`), their
tasks, and the approval steps.

| Package | Actions |
|---|---|
| `platform_developer`, `full` | every action |

Write actions need `confirm='approve'`, like every write in this server. For
long or filtered lists, `sn_query` with `table=change_request` also works.

## Actions

| Action | Required | Optional |
|---|---|---|
| `action="get"` | `change_id` for one record; nothing for a list | `limit`, `offset`, `timeframe`, `query`, `state`, `type`, `category`, `assignment_group`, `count_only` |
| `action="create"` | `short_description`, `type` | `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date` |
| `action="update"` | `change_id` and one field or more | `short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes` |
| `action="add_task"` | `change_id`, `task_short_description` | `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date` |
| `action="submit"` | `change_id` | `state` (default Assess), `work_notes` (approval comment) |
| `action="approve"` | `change_id` | `approver_id`, `state` (default Implement), `work_notes` (comment) |
| `action="reject"` | `change_id`, `work_notes` (the reason) | `approver_id`, `state` (default Canceled) |

## Approvals

- `action="submit"` moves the change to the target state and creates an
  approval record in the requested state.
- `action="approve"` and `action="reject"` act on the approval record of
  `approver_id` (a sys_id or a name). Without it, they act on the first record
  still pending. Then they move the change to the target state.
- Submit and approve also need `confirm_publish='approve'`, because they move a
  change other people act on.

## Choice values

`state`, `type`, `risk` and `impact` store codes, not words: `state` -4 is
Assess and -1 is Implement. Pass the code or its label. Before writing, the
tool checks the value against the instance's own choice list (`sys_choice`). A
value that is not on the list is refused, and the refusal lists every valid
value.

For approve and reject, the target state is checked before the approval record
is touched. A bad state cannot leave the approval decided and the change where
it was.

## Previews

Pass `dry_run=true` on any write action:

- `action="update"` returns a field-by-field diff.
- `action="approve"` and `action="reject"` return the approval record and the
  change state they would set.
- Every other write action returns `would_send`: the exact request the call
  would make.

Either way, nothing is written.

## Example prompts

- "Create a change request for server maintenance to apply security patches tomorrow night."
- "Add a task to the server maintenance change for pre-implementation checks."
- "Submit the server maintenance change for approval."
- "Approve the database upgrade change with the comment: the implementation plan looks thorough."
- "Reject the network change: not enough testing."
- "Show me all emergency changes scheduled for this week."
