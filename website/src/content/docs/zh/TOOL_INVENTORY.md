---
title: "ServiceNow MCP - 工具清单"
description: "Full list of registered ServiceNow MCP tools, grouped by package."
slug: zh/TOOL_INVENTORY
---

为避免逐行翻译清单的维护成本，本文件是快速了解当前公开工具面的**摘要版**。其中的数字由 `scripts/regenerate_doc_counts.py` 自动更新。

实时注册表中已注册的工具数：**75**
`full` 中打包的工具数：**61**
已注册但当前未打包的工具数：**11**

- 逐个工具的完整清单：[英文版 TOOL_INVENTORY.md](./TOOL_INVENTORY.md)

`list_tool_packages` 在运行时被注入到除 `none` 以外的每个启用包中。
本文件对其有说明，但本文件中的包计数反映的是 YAML 定义的工具面。

## 包概览

| 包 | 工具数 | 描述 |
|---------|------:|-------------|
| `none` | 0 | 用于有意关闭工具的禁用配置。 |
| `core` | 12 | 用于快速健康检查/schema/表操作的极简只读基础工具。 |
| `standard` | 31 | 覆盖 incident、change、门户、日志和源码分析的默认只读包。 |
| `service_desk` | 33 | standard 加上用于运营支持的事件与变更写入工作流。 |
| `portal_developer` | 50 | standard 加上门户、变更集、script include 和本地同步交付工作流。 |
| `platform_developer` | 44 | standard 加上工作流、Flow Designer、UI policy、incident/change 和脚本写入。 |
| `full` | 61 | 最广泛的打包功能面：所有 manage_* 工作流加上高级操作。 |

## 运行时注入的辅助工具

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `list_tool_packages` | R | 列出可用的工具包以及当前活动的包。 | `core`、`standard`、`service_desk`、`portal_developer`、`platform_developer`、`full` |
| `list_instances` | R | 列出只读数据比对模式中已配置的别名。 | 运行时比对辅助工具 |
| `compare_instances` | R | 跨已配置别名的只读记录比对；不是写入路由机制。 | 运行时比对辅助工具 |

## 本文档的维护原则

- **逐个工具的完整清单以英文版 `docs/TOOL_INVENTORY.md` 为准。** 该文件由实时注册表
  自动生成，因此始终是最新的。
- 本文件仅作为快速了解包选择与当前工具面的摘要。并行维护逐行翻译的结果是落后了
  4 个版本（缺失 10 个工具），因此统一采用韩文版率先确立的方针。
- 上述数字与包表格由脚本自动更新，请勿手工修改。
