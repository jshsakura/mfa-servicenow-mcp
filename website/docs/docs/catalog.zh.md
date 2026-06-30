# ServiceNow Service Catalog 集成

本文档介绍 ServiceNow MCP 服务器中的 ServiceNow Service Catalog 集成。

## 概述

ServiceNow Service Catalog 集成让你能够：

- 列出服务目录类别
- 列出服务目录项
- 获取特定目录项的详细信息，包括其变量
- 按类别或搜索查询过滤目录项

## 工具

以下工具可用于与 ServiceNow Service Catalog 交互：

### `manage_catalog(action="list_categories")`

列出可用的服务目录类别。

**参数：**
- `limit`（int，默认值：10）：要返回的最大类别数量
- `offset`（int，默认值：0）：用于分页的偏移量
- `query`（string，可选）：类别的搜索查询
- `active`（boolean，默认值：true）：是否仅返回活动类别

**示例：**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogCategoriesParams, list_catalog_categories

params = ListCatalogCategoriesParams(
    limit=5,
    query="hardware"
)
result = list_catalog_categories(config, auth_manager, params)
```

### `manage_catalog(action="list_items")`

列出可用的服务目录项。

**参数：**
- `limit`（int，默认值：10）：要返回的最大项目数量
- `offset`（int，默认值：0）：用于分页的偏移量
- `category`（string，可选）：按类别过滤
- `query`（string，可选）：项目的搜索查询
- `active`（boolean，默认值：true）：是否仅返回活动项目

**示例：**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogItemsParams, list_catalog_items

params = ListCatalogItemsParams(
    limit=5,
    category="hardware",
    query="laptop"
)
result = list_catalog_items(config, auth_manager, params)
```

### `manage_catalog(action="get_item")`

获取特定目录项的详细信息。

**参数：**
- `item_id`（string，必填）：目录项 ID 或 sys_id

**示例：**
```python
from servicenow_mcp.tools.catalog_tools import GetCatalogItemParams, get_catalog_item

params = GetCatalogItemParams(
    item_id="item123"
)
result = get_catalog_item(config, auth_manager, params)
```

## 资源

以下资源可用于访问 ServiceNow Service Catalog：

### `catalog://items`

列出服务目录项。

**示例：**
```
catalog://items
```

### `catalog://categories`

列出服务目录类别。

**示例：**
```
catalog://categories
```

### `catalog://{item_id}`

按 ID 获取特定目录项。

**示例：**
```
catalog://item123
```

## 与 Claude Desktop 集成

要在 Claude Desktop 中使用 ServiceNow Service Catalog：

1. 在 Claude Desktop 中配置 ServiceNow MCP 服务器
2. 向 Claude 提出关于服务目录的问题

**示例提示：**
- "你能列出 ServiceNow 中可用的服务目录类别吗？"
- "你能给我看看 ServiceNow 服务目录中可用的项目吗？"
- "你能列出 Hardware 类别中的目录项吗？"
- "你能给我看看 'New Laptop' 目录项的详细信息吗？"
- "你能在 ServiceNow 中找到与 'software' 相关的目录项吗？"
- "你能在服务目录中创建一个名为 'Cloud Services' 的新类别吗？"
- "你能把 'Hardware' 类别重命名为 'IT Equipment' 吗？"
- "你能把 'Virtual Machine' 目录项移动到 'Cloud Services' 类别吗？"
- "你能在 'IT Equipment' 类别下创建一个名为 'Monitors' 的子类别吗？"
- "你能把所有软件项目移到 'Software' 类别来重新整理我们的目录吗？"

## 示例脚本

### 集成测试

`examples/catalog_integration_test.py` 脚本演示了如何直接使用目录工具：

```bash
python examples/catalog_integration_test.py
```

### Claude Desktop 演示

`examples/claude_catalog_demo.py` 脚本演示了如何在 Claude Desktop 中使用目录功能：

```bash
python examples/claude_catalog_demo.py
```

## 数据模型

### CatalogItemModel

表示一个 ServiceNow 目录项。

**字段：**
- `sys_id`（string）：目录项的唯一标识符
- `name`（string）：目录项名称
- `short_description`（string，可选）：目录项的简短描述
- `description`（string，可选）：目录项的详细描述
- `category`（string，可选）：目录项的类别
- `price`（string，可选）：目录项的价格
- `picture`（string，可选）：目录项的图片 URL
- `active`（boolean，可选）：目录项是否活动
- `order`（integer，可选）：目录项在其类别中的顺序

### CatalogCategoryModel

表示一个 ServiceNow 目录类别。

**字段：**
- `sys_id`（string）：类别的唯一标识符
- `title`（string）：类别的标题
- `description`（string，可选）：类别的描述
- `parent`（string，可选）：父类别 ID
- `icon`（string，可选）：类别的图标
- `active`（boolean，可选）：类别是否活动
- `order`（integer，可选）：类别的顺序

### CatalogItemVariableModel

表示一个 ServiceNow 目录项变量。

**字段：**
- `sys_id`（string）：变量的唯一标识符
- `name`（string）：变量名称
- `label`（string）：变量的标签
- `type`（string）：变量的类型
- `mandatory`（boolean，可选）：变量是否必填
- `default_value`（string，可选）：变量的默认值
- `help_text`（string，可选）：变量的帮助文本
- `order`（integer，可选）：变量的顺序
