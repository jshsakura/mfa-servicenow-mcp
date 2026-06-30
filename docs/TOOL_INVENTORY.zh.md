# ServiceNow MCP - 工具清单

由 `scripts/regenerate_tool_inventory.py` 自动生成。请勿手动编辑。

实时注册表中已注册的工具数：**65**
`full` 中打包的工具数：**54**
已注册但当前未打包的工具数：**11**

`list_tool_packages` 在运行时被注入到除 `none` 以外的每个启用包中。
本文件对其有说明，但本文件中的包计数反映的是 YAML 定义的工具面。

## 包概览

| 包 | 工具数 | 描述 |
|---------|------:|-------------|
| `none` | 0 | 用于有意关闭工具的禁用配置。 |
| `core` | 12 | 用于快速健康检查/schema/表操作的极简只读基础工具。 |
| `standard` | 28 | 覆盖 incident、change、门户、日志和源码分析的默认只读包。 |
| `service_desk` | 30 | standard 加上用于运营支持的事件与变更写入工作流。 |
| `portal_developer` | 40 | standard 加上门户、变更集、script include 和本地同步交付工作流。 |
| `platform_developer` | 40 | standard 加上工作流、Flow Designer、UI policy、incident/change 和脚本写入。 |
| `full` | 54 | 最广泛的打包功能面：所有 manage_* 工作流加上高级操作。 |

## 运行时注入的辅助工具

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `list_tool_packages` | R | 列出可用的工具包以及当前活动的包。 | `core`、`standard`、`service_desk`、`portal_developer`、`platform_developer`、`full` |
| `list_instances` | R | 列出只读数据比对模式中已配置的别名。 | 运行时比对辅助工具 |
| `compare_instances` | R | 跨已配置别名的只读记录比对；不是写入路由机制。 | 运行时比对辅助工具 |

## 已注册但未打包的工具

这些工具在代码中已注册，但被有意排除在打包的 YAML 功能面之外。它们仍可用于自定义构建、测试或将来的打包决策。

`create_category`、`create_knowledge_base`、`get_developer_daily_summary`、`get_repo_file_last_modifier`、`get_repo_recent_commits`、`get_repo_working_tree_status`、`get_uncommitted_changes`、`manage_epic`、`manage_project`、`manage_scrum_task`、`manage_story`

## 按模块划分的工具

**读/写**列是工具在不受限时的完整能力。显示为 `pkg (actions…)` 的包仅暴露该工具的那些操作 —— 例如 `manage_script_include` 注册为 `R/W`，但只读包（`core`、`standard`）将其暴露为 `standard (get, list)`。未带括号列出的包以工具的完整读/写能力暴露该工具。

### Attachment Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `download_attachment` | R | 按 attachment_sys_id 或 表+记录 将 ServiceNow 附件文件下载到磁盘。从 saved_path 读取。 | standard, portal_developer, platform_developer, service_desk, full |

### Audit Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | 审计待处理的 update set 更改 —— 按类型、风险模式、克隆和交叉引用编制清单。 | full |

### Catalog Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_catalog` | R/W | 目录 类别/项目/变量 的 CRUD（表：sc_category、sc_cat_item、item_option_new）。 | portal_developer, service_desk (get_item, list_categories, list_item_variables, list_items), full |

### Change Tools (4)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `approve_change` | W | 批准变更的审批记录（按 approver_id）；推进 change_request（默认：implement）。 | full |
| `manage_change` | R/W | 获取/创建/更新变更请求，或为其添加变更任务（表：change_request）。 | platform_developer, full |
| `reject_change` | W | 以原因拒绝变更的审批记录（按 approver_id）；推进 change_request（默认：canceled）。 | full |
| `submit_change_for_approval` | W | 将变更请求转入 assess 状态并创建审批记录。需要 change_id。 | platform_developer, full |

### Changeset Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_changeset` | R/W | 对 update set 执行 get/create/update/commit/publish/add_file（表：sys_update_set）。 | portal_developer, platform_developer, full |

### Epic Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_epic` | R/W | Epic CRUD（表：rm_epic）。list 跳过确认。 | — |

### Flow Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_flow_designer` | R/W | Flow Designer 读取/检查。编辑仅限于 action 输入 + 触发器/分支条件；无结构性更改（请用 UI）。 | core (list), standard (get_action_source, get_detail, get_executions, list), portal_developer, platform_developer, service_desk (get_action_source, get_detail, get_executions, list), full |

### Incident Management (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_incident` | R/W | 获取/创建/更新/评论/解决一个事件（表：incident）。一次调用，无需 schema 查询。 | platform_developer, service_desk, full |

### Knowledge Base (3)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `create_category` | W | 在某个知识库下创建一个 KB 类别。需要 kb_id 和 label。 | — |
| `create_knowledge_base` | W | 创建一个知识库（kb_knowledge_base）。需要 title。返回 sys_id。 | — |
| `manage_kb_article` | R/W | 创建/更新/发布一篇知识文章（表：kb_knowledge）。 | full |

### Local Graph Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `query_local_graph` | R | 从审计图文件中给出离线依赖/影响答案（0 次 API 调用）。uses|used_by|page|impact。 | standard, portal_developer, platform_developer, service_desk, full |

### Logs (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `get_logs` | R | 查询 ServiceNow 日志。log_type：system/journal/transaction/background。最多 20 行。 | core, standard, portal_developer, platform_developer, service_desk, full |

### Performance Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | 分析 widget 性能 —— 代码模式、事务日志、provider 使用情况。返回带严重级别的发现项。 | standard, portal_developer, platform_developer, service_desk, full |

### Portal CRUD (3)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_portal_component` | W | 创建门户组件；或按 sys_id 编辑任意代码记录 —— BR、notification、SI、ACL、UI 等。action=update_code。 | portal_developer, platform_developer, full |
| `manage_portal_layout` | W | 门户布局：page CRUD + container/row/column + widget 实例放置。 | portal_developer, platform_developer, full |
| `scaffold_page` | W | 一次调用创建带布局（container/rows/columns）和 widget 放置的完整门户页面。Scope 为必填。 | portal_developer, platform_developer, full |

### Portal Dev Tools (3)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `get_developer_changes` | R | 跨门户表列出开发者的近期更改。仅元数据，请先用 count_only。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_developer_daily_summary` | R | 生成开发者每日工作摘要。支持 jira/plain/structured 输出格式。 | — |
| `get_uncommitted_changes` | R | 列出某开发者未提交的 update set 条目。返回条目类型和目标。请先用 count_only=true。 | — |

### Portal Management (9)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | R | 分析拟议的门户组件编辑，返回有界的风险与字段变更摘要 | portal_developer, full |
| `detect_angular_implicit_globals` | R | 检测 Angular provider 脚本中导致运行时 'not defined' 错误的未声明变量赋值。 | portal_developer, full |
| `download_portal_sources` | R | 有针对性的门户 widget/provider。整个应用：download_app_sources。widget_ids=单个 widget。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_portal_component_code` | R | 获取 widget/provider/SI 字段。默认返回完整正文。分析时切勿分块。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_widget_bundle` | R | 一次调用获取完整的 widget 包（HTML、脚本、provider、CSS/JS 依赖）。分析的起点。 | standard, portal_developer, platform_developer, service_desk, full |
| `preview_portal_component_update` | R | 为拟议的门户组件编辑预览有界的前后片段及 diff | portal_developer, full |
| `route_portal_component_edit` | R | 将门户编辑指令路由到正确的 analyze/preview/apply 工具。 | portal_developer, full |
| `search_portal_regex_matches` | R | 对门户代码（widget/provider/SI）执行真正的正则匹配，返回偏移量+上下文。服务端表关键字搜索：search_server_code。 | standard, portal_developer, platform_developer, service_desk, full |
| `trace_portal_route_targets` | R | 映射 widget→provider→route 关系。仅元数据，无脚本正文。 | standard, portal_developer, platform_developer, service_desk, full |

### Portal Management Tools (3)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `get_page` | R | 按 URL 路径、标题或 sys_id 获取或列出门户页面。返回带 widget 放置的布局树。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `get_portal` | R | 按名称、URL 后缀或 sys_id 获取或列出 Service Portal。返回配置、主页、主题和页面。 | full |
| `get_widget_instance` | R | 获取页面上的 widget 实例放置。返回列、顺序和配置。可按 page 或 widget 过滤。 | standard, portal_developer, platform_developer, service_desk, full |

### Project Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_project` | R/W | Project CRUD（表：pm_project）。list 跳过确认。 | — |

### Repository (4)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | 组合式 git 报告：一次调用获取工作树状态 + 近期提交 + 每个文件的最后修改者。 | full |
| `get_repo_file_last_modifier` | R | 查询每个文件的最后修改者和提交元数据，可选附带未提交状态 | — |
| `get_repo_recent_commits` | R | 列出近期提交，含作者和可选的变更文件列表 | — |
| `get_repo_working_tree_status` | R | 检查工作树状态，包括已暂存、未暂存和未跟踪的文件 | — |

### Script Include (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_script_include` | R/W | 对 script include 执行 列出/获取/创建/更新/删除/执行（表：sys_script_include）。 | core (get, list), standard (get, list), portal_developer, platform_developer, service_desk (get, list), full |

### Scrum Task Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_scrum_task` | R/W | Scrum task CRUD（表：rm_scrum_task）。list 跳过确认。 | — |

### Session Context Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_session_context` | W | 获取/切换当前应用 + update set（浏览器认证）。set_* 通过回读进行验证。 | portal_developer, platform_developer, full |

### Sn Api (7)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `sn_aggregate` | R | 在任意表上运行 COUNT/SUM/AVG/MIN/MAX，可选 group_by。返回统计而不获取记录。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_discover` | R | 按名称或标签关键字查找表。返回表名、标签、scope 和父类。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_health` | R | 检查 ServiceNow API 连通性、认证状态、Chromium 安装状态（浏览器认证）和 MCP 服务器版本。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_query` | R | 通用表查询 —— 最后手段。优先用领域工具：search_server_code、manage_workflow、manage_flow_designer。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_resolve_url` | R | 解析 ServiceNow URL → 表、sys_id、scope、建议的下一个工具。只读。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_schema` | R | 从 sys_dictionary 获取给定表的字段名、类型、标签和约束。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_write` | W | 最后手段的 CRUD（无专用工具时）。优先用 manage_*/update_*。ACL/用户/组/scope 被阻止。confirm='approve'。 | full |

### Source Analysis (6)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `download_app_sources` | R | 将某应用 scope 的完整/全部源码下载到磁盘（所有组+依赖）。scope 必填 —— 询问用户。第 1 步，不是门户。 | standard, portal_developer, platform_developer, service_desk, full |
| `download_server_sources` | R | 有针对性的服务端源码族（SI/BR/UI/api/security/admin）。整个应用：download_app_sources。 | platform_developer, full |
| `download_table_schema` | R | 下载 sys_dictionary 字段定义。指定表或从本地源码自动检测。 | platform_developer, full |
| `extract_table_dependencies` | R | 从服务端脚本（SI/BR/widget）提取 GlideRecord 表依赖图。传 widget_id 表示单个 widget。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_metadata_source` | R | 按名称/sys_id 获取一条源码记录（SI/BR/widget）。返回正文；'complete' 标记预览是否被截断。 | standard, portal_developer, platform_developer, service_desk, full |
| `search_server_code` | R | 跨 22 种服务端代码类型（SI/BR/ACL）的快速关键字搜索。门户正则+片段：search_portal_regex_matches。 | core, standard, portal_developer, platform_developer, service_desk, full |

### Source Audit Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `audit_local_sources` | R | 在本地分析已下载的源码（无 API）。生成交叉引用图、死代码、HTML 报告。 | standard, portal_developer, platform_developer, service_desk, full |

### Story Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_story` | R/W | Story CRUD + 依赖操作（rm_story/m2m_story_dependencies）。list/list_dependencies 跳过确认。 | — |

### Sync Tools (2)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `diff_local_component` | R | 将本地编辑与远程比对（或通过 compare_to 与第二个下载根比对，例如 dev-vs-test）。 | standard, portal_developer, platform_developer, service_desk, full |
| `update_remote_from_local` | W | 将一处本地编辑推回 ServiceNow（先执行 diff_local_component）。有针对性的刷新，而非批量的 dev→test 提升。 | portal_developer, platform_developer, full |

### UI Policy (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_ui_policy` | W | UI Policy 创建 + 添加字段操作（表：sys_ui_policy / sys_ui_policy_action）。 | portal_developer, platform_developer, full |

### User Tools (2)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_group` | R/W | Group CRUD + 成员操作（表：sys_user_group）。list 跳过确认。 | full |
| `manage_user` | R/W | User CRUD + 查询（表：sys_user）。读操作跳过确认。 | full |

### Widget Dependency Tools (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_widget_dependency` | R/W | 对 widget 的 Angular provider 及 CSS/JS 依赖执行 CRUD + link/unlink。请先用 action=list 获取 sys_id。 | standard (get, list), portal_developer, platform_developer (get, list), service_desk (get, list), full |

### Workflow (1)

| 工具 | 读/写 | 描述 | 包 |
|------|-----|-------------|----------|
| `manage_workflow` | R/W | 仅限旧版 Workflow 引擎（wf_workflow/wf_activity）。大多数流程是 Flow Designer -> 请用 manage_flow_designer。 | core (get_activities, list), standard (get_activities, list), portal_developer, platform_developer, service_desk (get_activities, list), full |
