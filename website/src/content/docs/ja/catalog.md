---
title: "サービスカタログ"
description: "ServiceNow Service Catalog integration tools and workflows."
slug: ja/catalog
---

1 つのツール `manage_catalog` で、サービスカタログのカテゴリ（`sc_category`）、アイテム（`sc_cat_item`）、アイテム変数（`item_option_new`）を扱います。

| パッケージ | アクション |
|---|---|
| `service_desk` | 読み取りアクション 4 つ |
| `portal_developer`, `full` | すべてのアクション |

書き込みアクションには、このサーバーの他の書き込みと同じく `confirm='approve'` が必要です。

## 読み取りアクション

| アクション | 引数 | 戻り値 |
|---|---|---|
| `action="list_categories"` | `limit`, `offset`, `query`, `active`, `count_only` | カテゴリ一覧 |
| `action="list_items"` | `limit`, `offset`, `query`, `category`, `active`, `count_only` | アイテム一覧 |
| `action="get_item"` | `item_id` | アイテムとその変数 |
| `action="list_item_variables"` | `catalog_item_id` | 変数一覧：名前、ラベル、タイプコード、必須、既定値、順序 |

2 つの一覧アクションは次の値を返します。

- `count`：このページの件数。
- `total`：サーバー上で条件に一致する件数。
- `more`：次のページがあるときだけ返り、次に指定する offset も示します。

サーバーが件数を返さない場合は推測せず、`total_unknown` と示します。`count_only=true` を指定すると件数だけを返します。

## 書き込みアクション

| アクション | 必須 | 任意 |
|---|---|---|
| `action="create_category"` | `title` | `description`, `parent`, `icon`, `active`, `order` |
| `action="update_category"` | `category_id` と 1 つ以上のフィールド | create と同じフィールド |
| `action="update_item"` | `item_id` と 1 つ以上のフィールド | `name`, `short_description`, `description`, `category`, `price`, `active`, `order` |
| `action="move_items"` | `item_ids`, `target_category_id` | |
| `action="create_variable"` | `catalog_item_id`, `variable_name`, `variable_type`, `label` | `mandatory`, `help_text`, `default_value`, `description`, `order`, `reference_table`, `reference_qualifier`, `max_length`, `min`, `max` |
| `action="update_variable"` | `variable_id` と 1 つ以上のフィールド | `variable_name`, `variable_type`, `reference_table`、create の任意フィールド |

### 変数タイプ

`item_option_new.type` に保存されるのは単語ではなく数値コードです。コードかラベルのどちらかを渡してください。

| コード | ラベル |
|---|---|
| `6` | Single Line Text |
| `2` | Multi Line Text |
| `5` | Select Box |
| `3` | Multiple Choice |
| `7` | CheckBox |
| `8` | Reference |
| `9` | Date |
| `10` | Date/Time |

書き込む前に、そのインスタンス自身の選択肢一覧（`sys_choice`）と照合するため、インスタンスで追加した選択肢も受け付けます。一覧にない値は拒否し、有効なコードをすべて示します。選択肢一覧を読めない場合は何も書き込みません。

### 長さと範囲

- `item_option_new` には `max_length` 列がありません。`max_length` はプラットフォームと同じ方法で、変数の `attributes` に `max_length=N` として保存されます。
- `min` と `max` は評価スケール（rating scale）の範囲である `scale_min`、`scale_max` を設定します。

## プレビュー

どの書き込みアクションにも `dry_run=true` を渡せます。

- `action="update_category"` と `action="update_item"` はフィールドごとの差分を返します。
- それ以外の書き込みアクションは、送信するはずのリクエストをそのまま `would_send` として返します。

どちらの場合も何も書き込みません。このルールはサーバーがすべてのツールに強制しているため、プレビューが実際の書き込みに変わることはありません。

## プロンプト例

- 「カタログのカテゴリと、カテゴリごとのアイテム数を見せて。」
- 「'New Laptop' アイテムの変数を見せて。」
- 「そのアイテムに必須の Single Line Text 変数 'asset_tag' を追加して。まずプレビューで。」
- 「この 3 つのアイテムを Hardware カテゴリに移して。」
