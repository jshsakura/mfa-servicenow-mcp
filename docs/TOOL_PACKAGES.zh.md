# 工具包 — 高级参考

> **大多数用户不需要本页。** 默认包是 `standard` —— 只读，对任何环境都安全。
> 仅当你需要 `standard` 之外的写入工具时才继续阅读。

---

## 选择一个包

从能覆盖你工作的最窄的包开始。每往上一级，就为更多领域增加写入权限：

只读 —— 对任何环境都安全，无写入工具：

| 包 | 工具数 | ~令牌 | 何时使用 |
| :--- | :---: | :---: | :--- |
| `core` | 12 | ~3.0K | 极简只读：仅健康检查、schema、发现、关键工件查询 |
| `standard` | 30 | ~7.3K | **（默认）** 覆盖 incident、change、门户、日志和源码分析的只读 |
| `none` | 0 | 0 | 有意禁用所有工具（测试、锁定环境） |

⚠️ 具备写入能力 —— 授予创建/更新/删除权限的**高级选项**：

| 包 | 工具数 | ~令牌 | 何时使用 |
| :--- | :---: | :---: | :--- |
| `service_desk` | 32 | ~8.2K | ⚠️ 需要更新/关闭 incident 和 change 的服务台坐席 |
| `portal_developer` | 42 | ~10.6K | ⚠️ 部署 widget、变更集和 script include 的门户开发者 |
| `platform_developer` | 42 | ~10.8K | ⚠️ 管理工作流、Flow Designer 和脚本的平台工程师 |
| `full` | 56 | ~13.8K | ⚠️ 最高级 —— 同时启用所有领域的所有写入工具（见下方警告） |

> **~令牌** = 每次请求该包的工具 schema 向模型上下文增加的大致 token 数（基于 tiktoken cl100k_base，实际 Claude token 数略有差异）。使用更窄的包可节省上下文与成本。

除 `core` 和 `none` 外的所有包都通过 `_extends` 继承 `standard` 的只读工具。完整的继承树见 `config/tool_packages.yaml`。

---

!!! danger "⚠️  任何高于 `standard` 的包都是高级的、具备写入能力的选项"
    `service_desk`、`portal_developer`、`platform_developer` 和 `full` 都会激活写入工具 —— 在它们之下运行的 AI
    代理可以创建、更新和删除 ServiceNow 记录。`full` 会**在每个领域同时**这样做
    （incident、change、门户、Flow Designer、工作流、脚本等），因此一个被误解的提示
    或一次幻觉就可能在多个领域同时触发破坏性更改。

    **不要从 `standard` 向上切换，除非：**
    - 你了解该包激活的每一个写入工具（见[工具清单](TOOL_INVENTORY.md)）
    - 你在**非生产**或**沙箱化**实例中工作，或已设置 `allow_writes` 门控
    - 你是经验丰富的 ServiceNow 开发者，知道如何从意外更改中恢复

    如果不确定，请保持只读的默认包 `standard`，仅当某项任务确实需要时才选择最窄的写入包。

---

## 设置包

通过环境变量（推荐）：

```bash
MCP_TOOL_PACKAGE=standard
```

通过 CLI 标志：

```bash
servicenow-mcp --tool-package standard --instance-url ...
```

在你的 MCP 客户端配置中：

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "standard"
  }
}
```

---

## 当某个工具不在你的包中会发生什么

如果你调用了一个在当前包中未激活的工具，服务器会返回一条清晰的错误：

```
Tool 'manage_widget' is not available in package 'standard'.
Enable package 'portal_developer' or higher to use this tool.
```

没有静默失败 —— LLM 确切知道该请求哪个包。

---

## 完整工具列表

按类别和包归属列出全部 73 个工具的完整清单，请见[工具清单](TOOL_INVENTORY.md)。
