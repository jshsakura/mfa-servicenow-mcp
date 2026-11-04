# 服务目录

一个工具 `manage_catalog` 即可处理服务目录的分类（`sc_category`）、目录项（`sc_cat_item`）和目录项变量（`item_option_new`）。

| 工具包 | 操作 |
|---|---|
| `service_desk` | 4 个读取操作 |
| `portal_developer`、`full` | 全部操作 |

与本服务器的其他写入一样，写入操作需要 `confirm='approve'`。

## 读取操作

| 操作 | 参数 | 返回 |
|---|---|---|
| `action="list_categories"` | `limit`、`offset`、`query`、`active`、`count_only` | 分类列表 |
| `action="list_items"` | `limit`、`offset`、`query`、`category`、`active`、`count_only` | 目录项列表 |
| `action="get_item"` | `item_id` | 目录项及其变量 |
| `action="list_item_variables"` | `catalog_item_id` | 变量列表：名称、标签、类型代码、是否必填、默认值、顺序 |

两个列表操作返回以下字段：

- `count`：本页的行数。
- `total`：服务器上符合条件的总数。
- `more`：只在还有下一页时出现，并给出下一次请求要用的 offset。

服务器没有返回总数时，响应会标出 `total_unknown`，不会自行猜测。`count_only=true` 只返回数量。

## 写入操作

| 操作 | 必填 | 可选 |
|---|---|---|
| `action="create_category"` | `title` | `description`、`parent`、`icon`、`active`、`order` |
| `action="update_category"` | `category_id` 及至少一个字段 | 与 create 相同的字段 |
| `action="update_item"` | `item_id` 及至少一个字段 | `name`、`short_description`、`description`、`category`、`price`、`active`、`order` |
| `action="move_items"` | `item_ids`、`target_category_id` | |
| `action="create_variable"` | `catalog_item_id`、`variable_name`、`variable_type`、`label` | `mandatory`、`help_text`、`default_value`、`description`、`order`、`reference_table`、`reference_qualifier`、`max_length`、`min`、`max` |
| `action="update_variable"` | `variable_id` 及至少一个字段 | `variable_name`、`variable_type`、`reference_table`，以及 create 的可选字段 |

### 变量类型

`item_option_new.type` 存储的是数字代码，而不是单词。传入代码或其标签都可以：

| 代码 | 标签 |
|---|---|
| `6` | Single Line Text |
| `2` | Multi Line Text |
| `5` | Select Box |
| `3` | Multiple Choice |
| `7` | CheckBox |
| `8` | Reference |
| `9` | Date |
| `10` | Date/Time |

写入前会与该实例自己的选项列表（`sys_choice`）核对，因此实例中新增的选项同样可用。不在列表中的值会被拒绝，并列出所有有效代码。如果选项列表无法读取，则不写入任何内容。

### 长度与范围

- `item_option_new` 没有 `max_length` 列。`max_length` 会按平台自身的方式，以 `max_length=N` 的形式保存在变量的 `attributes` 中。
- `min` 和 `max` 设置的是评分量表（rating scale）的范围 `scale_min` 和 `scale_max`。

## 预览

任何写入操作都可以传 `dry_run=true`：

- `action="update_category"` 和 `action="update_item"` 返回逐字段的差异。
- 其他写入操作原样返回将要发送的请求，字段名为 `would_send`。

两种情况都不会写入任何内容。服务器对所有工具强制执行这一规则，预览不可能变成真正的写入。

## 提示示例

- "列出目录分类，以及每个分类下有多少目录项。"
- "显示 'New Laptop' 目录项的变量。"
- "给该目录项添加一个必填的 Single Line Text 变量 'asset_tag'，先预览。"
- "把这三个目录项移到 Hardware 分类。"
