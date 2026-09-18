# ServiceNow MCP 中的工作流管理

本文档涵盖 MCP 服务器暴露的两个工作流引擎：

1. **旧版 Workflow**（`wf_workflow`）—— 由下方的 `manage_workflow` 操作路由器驱动。
2. **Flow Designer**（`sys_hub_flow`）—— 带操作分派的统一 `manage_flow_designer` 工具。在所有包中均为只读（`list` / `get_detail` / `get_executions` / `compare` 以及操作源读取）；写入操作已撤销。Action/SubFlow/Playbook 表记录在 [Flow Designer 表对照](#flow-designer-表对照)中。

如果你不确定某个流程使用哪个引擎，从 `manage_flow_designer(action="list")`（现代实例）开始，并回退到 `manage_workflow(action="list")` 以查找旧版 `wf_workflow` 记录。

## 概述

ServiceNow 工作流是一项强大的自动化功能，让你能够定义并自动化业务流程。ServiceNow MCP 服务器中的工作流管理工具让你能够查看、创建和修改 ServiceNow 实例中的工作流。

## 可用工具

### 查看工作流

1. **manage_workflow(action="list")** - 从 ServiceNow 列出工作流
   - 参数：
     - `limit`（可选）：要返回的最大记录数（默认值：10）
     - `offset`（可选）：起始偏移量（默认值：0）
     - `active`（可选）：按活动状态过滤（true/false）
     - `name`（可选）：按名称过滤（包含）
     - `query`（可选）：附加的查询字符串

2. **manage_workflow(action="get")** - 获取特定工作流的详细信息
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id

3. **manage_workflow(action="list_versions")** - 列出特定工作流的所有版本
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id
     - `limit`（可选）：要返回的最大记录数（默认值：10）
     - `offset`（可选）：起始偏移量（默认值：0）

4. **manage_workflow(action="get_activities")** - 获取工作流中的所有活动
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id
     - `version`（可选）：要获取活动的特定版本（如果未提供，将使用最新发布的版本）

### 修改工作流

5. **manage_workflow**（action="create"）- 在 ServiceNow 中创建新工作流
   - 参数：
     - `name`（必填）：工作流的名称
     - `description`（可选）：工作流的描述
     - `table`（可选）：工作流适用的表
     - `active`（可选）：工作流是否活动（默认值：true）
     - `attributes`（可选）：工作流的附加属性

6. **manage_workflow**（action="update"）- 更新现有工作流
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id
     - `name`（可选）：工作流的名称
     - `description`（可选）：工作流的描述
     - `table`（可选）：工作流适用的表
     - `active`（可选）：工作流是否活动
     - `attributes`（可选）：工作流的附加属性

7. **manage_workflow**（action="activate"）- 激活工作流
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id

8. **manage_workflow**（action="deactivate"）- 停用工作流
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id

### 管理工作流活动

9. **manage_workflow**（action="add_activity"）- 向工作流添加新活动
   - 参数：
     - `workflow_id`（必填）：工作流 ID 或 sys_id
     - `name`（必填）：活动的名称
     - `description`（可选）：活动的描述
     - `activity_type`（必填）：活动类型（例如 'approval'、'task'、'notification'）
     - `attributes`（可选）：活动的附加属性
     - `position`（可选）：在工作流中的位置（如果未提供，活动将添加到末尾）

10. **manage_workflow**（action="update_activity"）- 更新工作流中的现有活动
    - 参数：
      - `activity_id`（必填）：活动 ID 或 sys_id
      - `name`（可选）：活动的名称
      - `description`（可选）：活动的描述
      - `attributes`（可选）：活动的附加属性

11. **manage_workflow**（action="delete_activity"）- 从工作流中删除活动
    - 参数：
      - `activity_id`（必填）：活动 ID 或 sys_id

12. **manage_workflow**（action="reorder_activities"）- 更改工作流中活动的顺序
    - 参数：
      - `workflow_id`（必填）：工作流 ID 或 sys_id
      - `activity_ids`（必填）：按期望顺序排列的活动 ID 列表

## 使用示例

### 查看工作流

#### 列出所有活动的工作流

```python
result = list_workflows({
    "active": True,
    "limit": 20
})
```

#### 获取特定工作流的详情

```python
result = get_workflow_details({
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001"
})
```

#### 列出工作流的所有版本

```python
result = list_workflow_versions({
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001"
})
```

#### 获取工作流中的所有活动

```python
result = get_workflow_activities({
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001"
})
```

### 修改工作流

#### 创建新工作流

```python
result = manage_workflow({"action": "create",
    "name": "Software License Request",
    "description": "Workflow for handling software license requests",
    "table": "sc_request"
})
```

#### 更新现有工作流

```python
result = manage_workflow({"action": "update",
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001",
    "description": "Updated workflow description",
    "active": True
})
```

#### 激活工作流

```python
result = manage_workflow({"action": "activate",
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001"
})
```

#### 停用工作流

```python
result = manage_workflow({"action": "deactivate",
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001"
})
```

### 管理工作流活动

#### 向工作流添加新活动

```python
result = manage_workflow({"action": "add_activity",
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001",
    "name": "Manager Approval",
    "description": "Approval step for the manager",
    "activity_type": "approval"
})
```

#### 更新现有活动

```python
result = manage_workflow({"action": "update_activity",
    "activity_id": "aaaa1111bbbb2222cccc3333dddd0002",
    "name": "Updated Activity Name",
    "description": "Updated activity description"
})
```

#### 删除活动

```python
result = manage_workflow({"action": "delete_activity",
    "activity_id": "aaaa1111bbbb2222cccc3333dddd0002"
})
```

#### 重新排序工作流中的活动

```python
result = manage_workflow({"action": "reorder_activities",
    "workflow_id": "aaaa1111bbbb2222cccc3333dddd0001",
    "activity_ids": [
        "aaaa1111bbbb2222cccc3333dddd0002",
        "aaaa1111bbbb2222cccc3333dddd0003",
        "aaaa1111bbbb2222cccc3333dddd0004"
    ]
})
```

## Flow Designer 工具

Flow Designer（`sys_hub_flow`）是旧版工作流的现代继任者。MCP 服务器通过 processflow API 暴露了一个屏幕保真级的读取，加上一个经验证的编辑面（条件、action 输入、属性、复制、激活），并按工具包进行门控。它唯一**不会**伪造的是发布：快照重编译受编辑器门控，因此该工具会返回一条手动发布指令，而非伪造的成功。对 `sys_hub_*` 的原始 Table-API 写入被阻止（守卫 G6），因为它们会损坏 flow 快照。

### `manage_flow_designer`（统一）
带操作分派的单个复合工具。取代了此前 6 个独立的 flow 工具（`list_flow_designers`、`get_flow_designer_detail`、`get_flow_designer_executions`、`compare_flows`、`update_flow_designer`、`manage_flow_edit`）。action 枚举在所有包中均为只读——写操作已移除；请在 Flow Designer UI 中编辑流程。

读取操作（在 `standard` 中可用）：
- `action="read"`（v1.18.6）—— **屏幕保真**级的读取：一棵有序的、If/Else 嵌套的步骤树（action + 逻辑 + subflow 按执行顺序合并），条件**解码为人类可读文本**，data pill 解析到其生成步骤的标签，并附带自定义 Action 类型及其 Script 正文。已对环路/缺失 uid 加守卫。一个 142 节点的 flow 约 18K token（此前约 130K）—— 从这里开始理解一个 flow。
- `action="read_action"` —— 读取单个自定义 Action 定义的 Script 正文。
- `action="list"` —— 搜索 flow/subflow。关键参数：`limit`、`offset`、`include_inactive`、`flow_status`、`scope`、`name_filter`。
- `action="get_detail"` —— flow 元数据 + 可选的重型区段。关键参数：`flow_id`（必填）、`include_structure`、`include_triggers`、`include_executions_summary`、`trace_pill`、`include_subflow_tree`、`summary_format`。
- `action="get_executions"` —— 运行时历史（过滤器）或单次执行详情。关键参数：`context_id`（单次模式）、`flow_id`、`flow_name`、`exec_state`、`source_record`、`errors_only`、`limit`/`offset`。
- `action="compare"` —— 按 `flow_id_a`/`flow_id_b` 或 `name_a`/`name_b` 比对两个 flow。报告结构差异、subflow 绑定、触发器差异。优于两次调用 `get_detail`。

写入操作已撤销。`manage_flow_designer` 只读取和分析流程，不会修改它们 — 请在 Flow Designer 界面中编辑。流程编辑会将整个 processflow 负载 PUT 回去，而本工具只是部分建模了该内部格式：`label_cache` 中缺失的一个 pill 会产生通过 API 读取正常、**在界面上为空**的条件，并且每次保存都会成为随之发布的更新集条目。处理函数也一并删除；原因记录在 `flow_tools.py` 的 `git log` 中。

### Flow Designer 表对照

| Workflow Studio 标签页 | 表 |
| --- | --- |
| Flows / SubFlows | `sys_hub_flow` |
| Actions | `sys_hub_action_type_definition` |
| Playbooks | `sys_pd_process_definition` |
| Decision Tables | `sys_decision` |

### 只读偏向

在本代码库中，修改 flow 风险最高 —— 损坏一个已发布的 flow 可能破坏整个实例的自动化。默认使用读取操作，把写入门控在明确的用户确认之后，并在任何更改之前优先用 `manage_flow_designer(action="compare")` + `manage_flow_designer(action="get_executions")` 来验证行为。

## 常见活动类型

ServiceNow 提供了若干在向工作流添加活动时可用的活动类型：

1. **approval** - 需要用户操作的审批活动
2. **task** - 需要完成的任务
3. **notification** - 向用户发送通知
4. **timer** - 等待指定时长
5. **condition** - 评估条件并对工作流分支
6. **script** - 执行脚本
7. **wait_for_condition** - 等待直到某个条件满足
8. **end** - 结束工作流

## 最佳实践

1. **版本控制**：在做出重大更改之前，始终创建工作流的新版本。
2. **测试**：在部署到生产之前，先在非生产环境中测试工作流。
3. **文档**：记录每个工作流和活动的目的与行为。
4. **错误处理**：在工作流中包含错误处理，以应对意外情况。
5. **通知**：使用通知活动让相关方了解工作流进度。

## 故障排查

### 常见问题

1. **错误："No published versions found for this workflow"**
   - 此错误发生在尝试获取一个没有已发布版本的工作流的活动时。
   - 解决方法：在尝试获取其活动之前，先发布该工作流的一个版本。

2. **错误："Activity type is required"**
   - 此错误发生在尝试添加活动时未指定其类型。
   - 解决方法：添加活动时提供有效的活动类型。

3. **错误："Cannot modify a published workflow version"**
   - 此错误发生在尝试修改一个已发布的工作流版本时。
   - 解决方法：在做出更改之前，先创建工作流的新草稿版本。

4. **错误："Workflow ID is required"**
   - 此错误发生在未为需要工作流 ID 的操作提供该 ID 时。
   - 解决方法：确保在请求中包含工作流 ID。

## 其他资源

- [ServiceNow 工作流文档](https://docs.servicenow.com/bundle/tokyo-platform-administration/page/administer/workflow-administration/concept/c_WorkflowAdministration.html)
- [ServiceNow 工作流 API 参考](https://developer.servicenow.com/dev.do#!/reference/api/tokyo/rest/c_WorkflowAPI)
