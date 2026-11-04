---
title: "变更管理"
description: "Change management tools available in the ServiceNow MCP server."
slug: zh/change_management
---

一个工具 `manage_change` 即可处理变更请求（`change_request`）、变更任务和审批步骤。

| 工具包 | 操作 |
|---|---|
| `platform_developer` | 除批准（approve）和拒绝（reject）以外的全部操作 |
| `full` | 全部操作 |

与本服务器的其他写入一样，写入操作需要 `confirm='approve'`。较长或带筛选条件的列表也可以用 `sn_query` 并指定 `table=change_request`。

## 操作

| 操作 | 必填 | 可选 |
|---|---|---|
| `action="get"` | 单条记录传 `change_id`，列表无需传 | `limit`、`offset`、`timeframe`、`query`、`state`、`type`、`category`、`assignment_group`、`count_only` |
| `action="create"` | `short_description`、`type` | `description`、`risk`、`impact`、`category`、`requested_by`、`assignment_group`、`start_date`、`end_date` |
| `action="update"` | `change_id` 及至少一个字段 | `short_description`、`description`、`state`、`risk`、`impact`、`category`、`assignment_group`、`start_date`、`end_date`、`work_notes` |
| `action="add_task"` | `change_id`、`task_short_description` | `task_description`、`task_assigned_to`、`task_planned_start_date`、`task_planned_end_date` |
| `action="submit"` | `change_id` | `state`（默认 Assess）、`work_notes`（审批请求备注） |
| `action="approve"` | `change_id` | `approver_id`、`state`（默认 Implement）、`work_notes`（备注） |
| `action="reject"` | `change_id`、`work_notes`（拒绝理由） | `approver_id`、`state`（默认 Canceled） |

## 审批

- `action="submit"` 把变更移到目标状态，并创建一条 requested 状态的审批记录。
- `action="approve"` 和 `action="reject"` 作用于 `approver_id`（sys_id 或名称）对应的审批记录；未指定时，作用于第一条仍在等待的记录。之后把变更移到目标状态。
- submit 和 approve 会推动其他人接手的变更，因此还需要 `confirm_publish='approve'`。

## 选项值

`state`、`type`、`risk`、`impact` 存储的是代码，而不是单词：例如 `state` 的 -4 是 Assess，-1 是 Implement。传入代码或其标签都可以。写入前会与该实例自己的选项列表（`sys_choice`）核对；不在列表中的值会被拒绝，并列出所有有效值。

approve 和 reject 在改动审批记录之前就先检查目标状态，因此不会因为状态错误而出现审批已处理、变更却原地不动的情况。

## 预览

任何写入操作都可以传 `dry_run=true`：

- `action="update"` 返回逐字段的差异。
- `action="approve"` 和 `action="reject"` 返回将要设置的审批记录和变更状态。
- 其他写入操作原样返回将要发送的请求，字段名为 `would_send`。

两种情况都不会写入任何内容。

## 提示示例

- "创建一个变更请求：明晚为服务器打安全补丁。"
- "给服务器维护变更添加一个实施前检查任务。"
- "把服务器维护变更提交审批。"
- "批准数据库升级变更，备注：实施计划很周全。"
- "拒绝网络变更，理由：测试不足。"
- "列出本周计划的所有紧急变更。"
