# ServiceNow MCP のワークフロー管理

このドキュメントは、MCP サーバーが公開する 2 つのワークフローエンジンを取り上げます:

1. **レガシーワークフロー**（`wf_workflow`）— 下記の `manage_workflow` アクションルーターで駆動されます。
2. **Flow Designer**（`sys_hub_flow`）— アクションディスパッチを備えた統合 `manage_flow_designer` ツール。standard パッケージは読み取りアクション（`list` / `get_detail` / `get_executions` / `compare`）を公開し、上位パッケージは書き込み（`update` / `checkout` / `set_*` / `save` / `discard`）をアンロックします。Action/SubFlow/Playbook のテーブルは [Flow Designer テーブルマップ](#flow-designer-テーブルマップ) に記載されています。

プロセスがどちらのエンジンを使うか分からない場合は、まず `manage_flow_designer(action="list")`（モダンなインスタンス）から始め、レガシーの `wf_workflow` レコードには `manage_workflow(action="list")` にフォールバックしてください。

## 概要

ServiceNow のワークフローは、ビジネスプロセスを定義・自動化できる強力な自動化機能です。ServiceNow MCP サーバーのワークフロー管理ツールにより、ServiceNow インスタンス内のワークフローを表示、作成、変更できます。

## 利用可能なツール

### ワークフローの表示

1. **manage_workflow(action="list")** - ServiceNow からワークフローを一覧表示する
   - パラメータ:
     - `limit`（任意）: 返すレコードの最大数（デフォルト: 10）
     - `offset`（任意）: 開始オフセット（デフォルト: 0）
     - `active`（任意）: アクティブ状態でフィルタ（true/false）
     - `name`（任意）: 名前でフィルタ（部分一致）
     - `query`（任意）: 追加のクエリ文字列

2. **manage_workflow(action="get")** - 特定のワークフローの詳細情報を取得する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id

3. **manage_workflow(action="list_versions")** - 特定のワークフローのすべてのバージョンを一覧表示する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id
     - `limit`（任意）: 返すレコードの最大数（デフォルト: 10）
     - `offset`（任意）: 開始オフセット（デフォルト: 0）

4. **manage_workflow(action="get_activities")** - ワークフロー内のすべてのアクティビティを取得する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id
     - `version`（任意）: アクティビティを取得する特定のバージョン（指定しない場合、最新の公開バージョンが使用される）

### ワークフローの変更

5. **manage_workflow**（action="create"）- ServiceNow に新しいワークフローを作成する
   - パラメータ:
     - `name`（必須）: ワークフローの名前
     - `description`（任意）: ワークフローの説明
     - `table`（任意）: ワークフローが適用されるテーブル
     - `active`（任意）: ワークフローがアクティブかどうか（デフォルト: true）
     - `attributes`（任意）: ワークフローの追加属性

6. **manage_workflow**（action="update"）- 既存のワークフローを更新する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id
     - `name`（任意）: ワークフローの名前
     - `description`（任意）: ワークフローの説明
     - `table`（任意）: ワークフローが適用されるテーブル
     - `active`（任意）: ワークフローがアクティブかどうか
     - `attributes`（任意）: ワークフローの追加属性

7. **manage_workflow**（action="activate"）- ワークフローをアクティブ化する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id

8. **manage_workflow**（action="deactivate"）- ワークフローを非アクティブ化する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id

### ワークフローアクティビティの管理

9. **manage_workflow**（action="add_activity"）- ワークフローに新しいアクティビティを追加する
   - パラメータ:
     - `workflow_id`（必須）: ワークフロー ID または sys_id
     - `name`（必須）: アクティビティの名前
     - `description`（任意）: アクティビティの説明
     - `activity_type`（必須）: アクティビティのタイプ（例: 'approval'、'task'、'notification'）
     - `attributes`（任意）: アクティビティの追加属性
     - `position`（任意）: ワークフロー内の位置（指定しない場合、アクティビティは末尾に追加される）

10. **manage_workflow**（action="update_activity"）- ワークフロー内の既存のアクティビティを更新する
    - パラメータ:
      - `activity_id`（必須）: アクティビティ ID または sys_id
      - `name`（任意）: アクティビティの名前
      - `description`（任意）: アクティビティの説明
      - `attributes`（任意）: アクティビティの追加属性

11. **manage_workflow**（action="delete_activity"）- ワークフローからアクティビティを削除する
    - パラメータ:
      - `activity_id`（必須）: アクティビティ ID または sys_id

12. **manage_workflow**（action="reorder_activities"）- ワークフロー内のアクティビティの順序を変更する
    - パラメータ:
      - `workflow_id`（必須）: ワークフロー ID または sys_id
      - `activity_ids`（必須）: 希望する順序のアクティビティ ID のリスト

## 使用例

### ワークフローの表示

#### すべてのアクティブなワークフローを一覧表示する

```python
result = list_workflows({
    "active": True,
    "limit": 20
})
```

#### 特定のワークフローの詳細を取得する

```python
result = get_workflow_details({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### ワークフローのすべてのバージョンを一覧表示する

```python
result = list_workflow_versions({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### ワークフロー内のすべてのアクティビティを取得する

```python
result = get_workflow_activities({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### ワークフローの変更

#### 新しいワークフローを作成する

```python
result = manage_workflow({"action": "create",
    "name": "Software License Request",
    "description": "Workflow for handling software license requests",
    "table": "sc_request"
})
```

#### 既存のワークフローを更新する

```python
result = manage_workflow({"action": "update",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "description": "Updated workflow description",
    "active": True
})
```

#### ワークフローをアクティブ化する

```python
result = manage_workflow({"action": "activate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### ワークフローを非アクティブ化する

```python
result = manage_workflow({"action": "deactivate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### ワークフローアクティビティの管理

#### ワークフローに新しいアクティビティを追加する

```python
result = manage_workflow({"action": "add_activity",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "name": "Manager Approval",
    "description": "Approval step for the manager",
    "activity_type": "approval"
})
```

#### 既存のアクティビティを更新する

```python
result = manage_workflow({"action": "update_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591",
    "name": "Updated Activity Name",
    "description": "Updated activity description"
})
```

#### アクティビティを削除する

```python
result = manage_workflow({"action": "delete_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591"
})
```

#### ワークフロー内のアクティビティを並べ替える

```python
result = manage_workflow({"action": "reorder_activities",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "activity_ids": [
        "3cda7cda87a9c150e0b0df23cebb3591",
        "4cda7cda87a9c150e0b0df23cebb3592",
        "5cda7cda87a9c150e0b0df23cebb3593"
    ]
})
```

## Flow Designer ツール

Flow Designer（`sys_hub_flow`）は、レガシーワークフローのモダンな後継です。MCP サーバーは、processflow API を介して、画面忠実度の高い読み取りと、検証済みの編集サーフェス（条件、アクション入力、プロパティ、コピー、アクティブ化）を、ツールパッケージでゲートして公開します。唯一フェイクしないのは publish です: スナップショットの再コンパイルはエディタでゲートされているため、ツールは誤った成功ではなく手動公開の指示を返します。`sys_hub_*` への生の Table API 書き込みは、フロースナップショットを破損させるためブロックされます（ガード G6）。

### `manage_flow_designer`（統合）
アクションディスパッチを備えた単一の複合ツール。以前の 6 つの独立したフローツール（`list_flow_designers`、`get_flow_designer_detail`、`get_flow_designer_executions`、`compare_flows`、`update_flow_designer`、`manage_flow_edit`）を置き換えます。アクション列挙は `standard` では読み取り専用に絞られ、`portal_developer` / `platform_developer` / `full` でアンロックされます。

読み取りアクション（`standard` で利用可能）:
- `action="read"`（v1.18.6）— **画面忠実度の高い** 読み取り: 1 つの順序付けされた If/Else ネストのステップツリー（アクション + ロジック + サブフローを実行順にマージ）、条件を **人間が読めるテキストにデコード**、データピルを生成元ステップのラベルに解決、カスタム Action タイプとそのスクリプト本文を含む。サイクル/欠落 uid をガード。142 ノードのフローで約 18K トークン（以前は約 130K）— フローを理解するにはここから始める。
- `action="read_action"` — 単一のカスタム Action 定義のスクリプト本文を読む。
- `action="list"` — フロー/サブフローを検索する。主なパラメータ: `limit`、`offset`、`include_inactive`、`flow_status`、`scope`、`name_filter`。
- `action="get_detail"` — フローのメタデータ + 任意の重いセクション。主なパラメータ: `flow_id`（必須）、`include_structure`、`include_triggers`、`include_executions_summary`、`trace_pill`、`include_subflow_tree`、`summary_format`。
- `action="get_executions"` — 実行履歴（フィルタ）または単一実行の詳細。主なパラメータ: `context_id`（単一モード）、`flow_id`、`flow_name`、`exec_state`、`source_record`、`errors_only`、`limit`/`offset`。
- `action="compare"` — `flow_id_a`/`flow_id_b` または `name_a`/`name_b` で 2 つのフローを差分する。構造差分、サブフローバインディング、トリガーの差異を報告する。`get_detail` を 2 回呼び出すより優先される。

書き込みアクション（`portal_developer` / `platform_developer` / `full` のみ）。すべての編集は **ライブで検証** され（保存後に再読み取り）、`dry_run` をサポートします:
- `action="update"` — メタデータのみ（`new_name` / `description` / `active`）。
- `action="checkout"` — ローカル編集セッションを開始する（browser 認証が必要、processflow API を使用）。`action="status"` でそれを検査し、`action="discard"` で破棄する。
- `action="set_action_input"` — アクション入力値をパッチする。`node_id`、`input_name`、`value` が必要。
- `action="set_branch_condition"` / `action="set_trigger_condition"` — ロジックブランチまたはトリガー条件をパッチする。構造化された行 `[{field, operator, value}]` **または** 生のエンコード済みクエリを渡す。レスポンスは `condition_readable` をエコーするため、エンコーダが意図したものを生成したか確認できる（演算子には CHANGES ファミリー、AND/OR/NQ が含まれる）。
- `action="set_property"` / `action="save_properties"` — フロープロパティ: Run As、Protection、Priority、`active`。
- `action="copy"` — ネイティブのフロー/サブフロークローン（Workflow Studio の "Copy flow" が行うのと同じ呼び出し）。
- `action="activate"` / `action="deactivate"` — フローのアクティブ状態を切り替える。
- `action="save"` — processflow API を介して編集を永続化する（スコープ正しい PUT で、新しいフローバージョンも書き込む — サイレントなトリガーリバートの修正）。
- `action="publish"` — **エディタでゲート。** スナップショットの再コンパイルは対話的な Workflow Studio エディタからのみ到達可能で、すべての API パスは即座に失敗する。ツールは成功を装わず — `manual_publish_required` と、手動で公開を完了するための正確な UI URL を返す。

### Flow Designer テーブルマップ

| Workflow Studio タブ | テーブル |
| --- | --- |
| Flows / SubFlows | `sys_hub_flow` |
| Actions | `sys_hub_action_type_definition` |
| Playbooks | `sys_pd_process_definition` |
| Decision Tables | `sys_decision` |

### 読み取り専用バイアス

フローの変更は、このコードベースで最も高いリスクを伴います — 公開済みのフローを破損させると、インスタンス全体の自動化が壊れる可能性があります。デフォルトで読み取りアクションを使い、書き込みは明示的なユーザー確認の背後にゲートし、変更の前に挙動を検証するために `manage_flow_designer(action="compare")` + `manage_flow_designer(action="get_executions")` を優先してください。

## 一般的なアクティビティタイプ

ServiceNow は、ワークフローにアクティビティを追加する際に使用できるいくつかのアクティビティタイプを提供します:

1. **approval** - ユーザーのアクションを必要とする承認アクティビティ
2. **task** - 完了が必要なタスク
3. **notification** - ユーザーに通知を送信する
4. **timer** - 指定した時間だけ待機する
5. **condition** - 条件を評価し、ワークフローを分岐させる
6. **script** - スクリプトを実行する
7. **wait_for_condition** - 条件が満たされるまで待機する
8. **end** - ワークフローを終了する

## ベストプラクティス

1. **バージョン管理**: 重要な変更を加える前に、必ずワークフローの新しいバージョンを作成してください。
2. **テスト**: 本番にデプロイする前に、非本番環境でワークフローをテストしてください。
3. **ドキュメント化**: 各ワークフローとアクティビティの目的と挙動をドキュメント化してください。
4. **エラー処理**: 予期しない状況に対処するため、ワークフローにエラー処理を含めてください。
5. **通知**: 通知アクティビティを使用して、関係者にワークフローの進捗を知らせてください。

## トラブルシューティング

### よくある問題

1. **エラー: "No published versions found for this workflow"**
   - このエラーは、公開バージョンのないワークフローのアクティビティを取得しようとしたときに発生します。
   - 解決策: アクティビティを取得する前に、ワークフローのバージョンを公開してください。

2. **エラー: "Activity type is required"**
   - このエラーは、タイプを指定せずにアクティビティを追加しようとしたときに発生します。
   - 解決策: アクティビティを追加する際に有効なアクティビティタイプを指定してください。

3. **エラー: "Cannot modify a published workflow version"**
   - このエラーは、公開済みのワークフローバージョンを変更しようとしたときに発生します。
   - 解決策: 変更を加える前に、ワークフローの新しいドラフトバージョンを作成してください。

4. **エラー: "Workflow ID is required"**
   - このエラーは、ワークフロー ID を必要とする操作でそれを指定しなかったときに発生します。
   - 解決策: リクエストにワークフロー ID を含めるようにしてください。

## 追加リソース

- [ServiceNow ワークフロードキュメント](https://docs.servicenow.com/bundle/tokyo-platform-administration/page/administer/workflow-administration/concept/c_WorkflowAdministration.html)
- [ServiceNow ワークフロー API リファレンス](https://developer.servicenow.com/dev.do#!/reference/api/tokyo/rest/c_WorkflowAPI)
