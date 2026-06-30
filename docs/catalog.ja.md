# ServiceNow サービスカタログ統合

このドキュメントは、ServiceNow MCP サーバーにおける ServiceNow サービスカタログ統合に関する情報を提供します。

## 概要

ServiceNow サービスカタログ統合により、以下が可能になります:

- サービスカタログのカテゴリを一覧表示する
- サービスカタログのアイテムを一覧表示する
- 特定のカタログアイテムの詳細情報（変数を含む）を取得する
- カテゴリまたは検索クエリでカタログアイテムをフィルタする

## ツール

ServiceNow サービスカタログを操作するために、以下のツールが利用できます:

### `manage_catalog(action="list_categories")`

利用可能なサービスカタログのカテゴリを一覧表示します。

**パラメータ:**
- `limit` (int, デフォルト: 10): 返すカテゴリの最大数
- `offset` (int, デフォルト: 0): ページネーション用のオフセット
- `query` (string, 任意): カテゴリの検索クエリ
- `active` (boolean, デフォルト: true): アクティブなカテゴリのみを返すかどうか

**例:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogCategoriesParams, list_catalog_categories

params = ListCatalogCategoriesParams(
    limit=5,
    query="hardware"
)
result = list_catalog_categories(config, auth_manager, params)
```

### `manage_catalog(action="list_items")`

利用可能なサービスカタログのアイテムを一覧表示します。

**パラメータ:**
- `limit` (int, デフォルト: 10): 返すアイテムの最大数
- `offset` (int, デフォルト: 0): ページネーション用のオフセット
- `category` (string, 任意): カテゴリでフィルタ
- `query` (string, 任意): アイテムの検索クエリ
- `active` (boolean, デフォルト: true): アクティブなアイテムのみを返すかどうか

**例:**
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

特定のカタログアイテムの詳細情報を取得します。

**パラメータ:**
- `item_id` (string, 必須): カタログアイテム ID または sys_id

**例:**
```python
from servicenow_mcp.tools.catalog_tools import GetCatalogItemParams, get_catalog_item

params = GetCatalogItemParams(
    item_id="item123"
)
result = get_catalog_item(config, auth_manager, params)
```

## リソース

ServiceNow サービスカタログにアクセスするために、以下のリソースが利用できます:

### `catalog://items`

サービスカタログのアイテムを一覧表示します。

**例:**
```
catalog://items
```

### `catalog://categories`

サービスカタログのカテゴリを一覧表示します。

**例:**
```
catalog://categories
```

### `catalog://{item_id}`

ID で特定のカタログアイテムを取得します。

**例:**
```
catalog://item123
```

## Claude Desktop との統合

Claude Desktop で ServiceNow サービスカタログを使用するには:

1. Claude Desktop で ServiceNow MCP サーバーを設定する
2. サービスカタログについて Claude に質問する

**プロンプト例:**
- "Can you list the available service catalog categories in ServiceNow?"
- "Can you show me the available items in the ServiceNow service catalog?"
- "Can you list the catalog items in the Hardware category?"
- "Can you show me the details of the 'New Laptop' catalog item?"
- "Can you find catalog items related to 'software' in ServiceNow?"
- "Can you create a new category called 'Cloud Services' in the service catalog?"
- "Can you update the 'Hardware' category to rename it to 'IT Equipment'?"
- "Can you move the 'Virtual Machine' catalog item to the 'Cloud Services' category?"
- "Can you create a subcategory called 'Monitors' under the 'IT Equipment' category?"
- "Can you reorganize our catalog by moving all software items to the 'Software' category?"

## サンプルスクリプト

### 統合テスト

`examples/catalog_integration_test.py` スクリプトは、カタログツールを直接使用する方法を示します:

```bash
python examples/catalog_integration_test.py
```

### Claude Desktop デモ

`examples/claude_catalog_demo.py` スクリプトは、Claude Desktop でカタログ機能を使用する方法を示します:

```bash
python examples/claude_catalog_demo.py
```

## データモデル

### CatalogItemModel

ServiceNow のカタログアイテムを表します。

**フィールド:**
- `sys_id` (string): カタログアイテムの一意の識別子
- `name` (string): カタログアイテムの名前
- `short_description` (string, 任意): カタログアイテムの短い説明
- `description` (string, 任意): カタログアイテムの詳細な説明
- `category` (string, 任意): カタログアイテムのカテゴリ
- `price` (string, 任意): カタログアイテムの価格
- `picture` (string, 任意): カタログアイテムの画像 URL
- `active` (boolean, 任意): カタログアイテムがアクティブかどうか
- `order` (integer, 任意): カテゴリ内でのカタログアイテムの順序

### CatalogCategoryModel

ServiceNow のカタログカテゴリを表します。

**フィールド:**
- `sys_id` (string): カテゴリの一意の識別子
- `title` (string): カテゴリのタイトル
- `description` (string, 任意): カテゴリの説明
- `parent` (string, 任意): 親カテゴリの ID
- `icon` (string, 任意): カテゴリのアイコン
- `active` (boolean, 任意): カテゴリがアクティブかどうか
- `order` (integer, 任意): カテゴリの順序

### CatalogItemVariableModel

ServiceNow のカタログアイテム変数を表します。

**フィールド:**
- `sys_id` (string): 変数の一意の識別子
- `name` (string): 変数の名前
- `label` (string): 変数のラベル
- `type` (string): 変数の型
- `mandatory` (boolean, 任意): 変数が必須かどうか
- `default_value` (string, 任意): 変数のデフォルト値
- `help_text` (string, 任意): 変数のヘルプテキスト
- `order` (integer, 任意): 変数の順序
