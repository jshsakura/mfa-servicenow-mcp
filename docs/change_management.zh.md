# ServiceNow MCP 变更管理工具

本文档介绍 ServiceNow MCP 服务器中可用的变更管理工具。

## 概述

变更管理工具让 Claude 能够与 ServiceNow 的变更管理功能交互，使用户能够通过自然语言对话来创建、更新和管理变更请求。

## 可用工具

ServiceNow MCP 服务器提供以下变更管理工具：

### 核心变更请求管理

1. **`manage_change`** - 变更请求的捆绑式 CRUD（表：`change_request`）
   - `action`（必填）：`create` / `update` / `add_task` 之一
   - 对于 `action="create"`：`short_description`、`type`（`normal`/`standard`/`emergency`），以及可选的 `description`、`risk`、`impact`、`category`、`requested_by`、`assignment_group`、`start_date`、`end_date`
   - 对于 `action="update"`：`change_id` 加上至少一个可更新字段（`short_description`、`description`、`state`、`risk`、`impact`、`category`、`assignment_group`、`start_date`、`end_date`、`work_notes`）；支持 `dry_run=True` 以进行预览
   - 对于 `action="add_task"`：`change_id`、`task_short_description`，以及可选的 `task_description`、`task_assigned_to`、`task_planned_start_date`、`task_planned_end_date`

2. **`sn_query`**（搭配 `table=change_request`）- 用任意过滤器列出变更请求
   - 使用通用的表查询原语来列出变更请求。`sn_query` 的参数见[工具清单](TOOL_INVENTORY.md)。

3. **`manage_change(action="get")`** - 获取特定变更请求的详细信息
   - 参数：
     - `change_id`（必填）：变更请求 ID 或 sys_id

### 变更审批工作流

1. **submit_change_for_approval** - 提交变更请求以供审批
   - 参数：
     - `change_id`（必填）：变更请求 ID 或 sys_id
     - `approval_comments`：审批请求的备注

2. **approve_change** - 批准变更请求
   - 参数：
     - `change_id`（必填）：变更请求 ID 或 sys_id
     - `approver_id`：审批人的 ID
     - `approval_comments`：审批的备注

3. **reject_change** - 拒绝变更请求
   - 参数：
     - `change_id`（必填）：变更请求 ID 或 sys_id
     - `approver_id`：审批人的 ID
     - `rejection_reason`（必填）：拒绝的原因

## 与 Claude 的使用示例

一旦 ServiceNow MCP 服务器在 Claude Desktop 中配置完成，你就可以让 Claude 执行如下操作：

### 创建和管理变更请求

- "创建一个变更请求，用于明天晚上对服务器进行维护以应用安全补丁"
- "为下周二凌晨 2 点到 4 点安排一次数据库升级"
- "创建一个紧急变更，以修复我们 Web 应用中的严重安全漏洞"

### 添加任务和实施细节

- "为服务器维护变更添加一个用于实施前检查的任务"
- "添加一个在开始数据库升级前验证系统备份的任务"
- "更新网络变更的实施计划，加入回滚流程"

### 审批工作流

- "提交服务器维护变更以供审批"
- "给我看看所有等待我审批的变更"
- "批准数据库升级变更，备注：实施计划看起来很周密"
- "由于测试不足，拒绝该网络变更"

### 查询变更信息

- "给我看看本周安排的所有紧急变更"
- "数据库升级变更的状态如何？"
- "列出所有指派给 Network 团队的变更"
- "给我看看变更 CHG0010001 的详细信息"

## 示例代码

以下示例展示如何以编程方式使用变更管理工具：

```python
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.utils.config import ServerConfig

# 创建服务器配置
server_config = ServerConfig(
    instance_url="https://your-instance.service-now.com",
)

# 创建认证管理器
auth_manager = AuthManager(
    auth_type="basic",
    username="your-username",
    password="your-password",
    instance_url="https://your-instance.service-now.com",
)

# 通过捆绑式 manage_change 工具创建一个变更请求
params = ManageChangeParams(
    action="create",
    short_description="Server maintenance - Apply security patches",
    description="Apply the latest security patches to the application servers.",
    type="normal",
    risk="moderate",
    impact="medium",
    category="Hardware",
    start_date="2023-12-15 01:00:00",
    end_date="2023-12-15 03:00:00",
)

result = manage_change(server_config, auth_manager, params)
print(result)
```

上面的示例展示了编程式请求的形态，以及将变更管理集成到你自己的自动化中所需的关键导入。

## 与 Claude Desktop 集成

要在 Claude Desktop 中配置带变更管理工具的 ServiceNow MCP 服务器：

1. 编辑位于 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或你操作系统对应路径的 Claude Desktop 配置文件：

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/Users/yourusername/dev/servicenow-mcp/.venv/bin/python",
      "args": [
        "-m",
        "servicenow_mcp.cli"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "SERVICENOW_AUTH_TYPE": "basic"
      }
    }
  }
}
```

2. 重启 Claude Desktop 以应用更改

## 自定义

变更管理工具可以定制以匹配你组织特定的 ServiceNow 配置：

- 状态值可能需要根据你的 ServiceNow 实例配置进行调整
- 如有需要，可向参数模型添加额外字段
- 审批工作流可能需要修改以匹配你组织的审批流程

要定制这些工具，请修改 `src/servicenow_mcp/tools` 目录下的 `change_tools.py` 文件。
