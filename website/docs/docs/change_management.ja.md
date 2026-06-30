# ServiceNow MCP 変更管理ツール

このドキュメントは、ServiceNow MCP サーバーで利用可能な変更管理ツールに関する情報を提供します。

## 概要

変更管理ツールにより、Claude は ServiceNow の変更管理機能と連携でき、自然言語の会話を通じてユーザーが変更要求を作成、更新、管理できるようになります。

## 利用可能なツール

ServiceNow MCP サーバーは、以下の変更管理ツールを提供します:

### コア変更要求管理

1. **`manage_change`** - 変更要求のバンドルされた CRUD（テーブル: `change_request`）
   - `action`（必須）: `create` / `update` / `add_task` のいずれか
   - `action="create"` の場合: `short_description`、`type`（`normal`/`standard`/`emergency`）、加えて任意で `description`、`risk`、`impact`、`category`、`requested_by`、`assignment_group`、`start_date`、`end_date`
   - `action="update"` の場合: `change_id` に加えて、少なくとも 1 つの更新可能なフィールド（`short_description`、`description`、`state`、`risk`、`impact`、`category`、`assignment_group`、`start_date`、`end_date`、`work_notes`）。プレビュー用に `dry_run=True` をサポート
   - `action="add_task"` の場合: `change_id`、`task_short_description`、加えて任意で `task_description`、`task_assigned_to`、`task_planned_start_date`、`task_planned_end_date`

2. **`sn_query`**（`table=change_request` 付き）- 任意のフィルタで変更要求を一覧表示する
   - 変更要求の一覧表示には汎用テーブルクエリプリミティブを使用します。`sn_query` のパラメータは [ツールインベントリ](TOOL_INVENTORY.md) を参照してください。

3. **`manage_change(action="get")`** - 特定の変更要求の詳細情報を取得する
   - パラメータ:
     - `change_id`（必須）: 変更要求 ID または sys_id

### 変更承認ワークフロー

1. **submit_change_for_approval** - 変更要求を承認に提出する
   - パラメータ:
     - `change_id`（必須）: 変更要求 ID または sys_id
     - `approval_comments`: 承認要求のコメント

2. **approve_change** - 変更要求を承認する
   - パラメータ:
     - `change_id`（必須）: 変更要求 ID または sys_id
     - `approver_id`: 承認者の ID
     - `approval_comments`: 承認のコメント

3. **reject_change** - 変更要求を却下する
   - パラメータ:
     - `change_id`（必須）: 変更要求 ID または sys_id
     - `approver_id`: 承認者の ID
     - `rejection_reason`（必須）: 却下の理由

## Claude での使用例

ServiceNow MCP サーバーが Claude Desktop で設定されると、Claude に次のようなアクションを依頼できます:

### 変更要求の作成と管理

- "Create a change request for server maintenance to apply security patches tomorrow night"
- "Schedule a database upgrade for next Tuesday from 2 AM to 4 AM"
- "Create an emergency change to fix the critical security vulnerability in our web application"

### タスクと実装詳細の追加

- "Add a task to the server maintenance change for pre-implementation checks"
- "Add a task to verify system backups before starting the database upgrade"
- "Update the implementation plan for the network change to include rollback procedures"

### 承認ワークフロー

- "Submit the server maintenance change for approval"
- "Show me all changes waiting for my approval"
- "Approve the database upgrade change with comment: implementation plan looks thorough"
- "Reject the network change due to insufficient testing"

### 変更情報のクエリ

- "Show me all emergency changes scheduled for this week"
- "What's the status of the database upgrade change?"
- "List all changes assigned to the Network team"
- "Show me the details of change CHG0010001"

## サンプルコード

変更管理ツールをプログラムで使用する方法の例を以下に示します:

```python
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.utils.config import ServerConfig

# サーバー設定を作成
server_config = ServerConfig(
    instance_url="https://your-instance.service-now.com",
)

# 認証マネージャーを作成
auth_manager = AuthManager(
    auth_type="basic",
    username="your-username",
    password="your-password",
    instance_url="https://your-instance.service-now.com",
)

# バンドルされた manage_change ツールで変更要求を作成
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

上記のサンプルは、プログラムによるリクエストの形と、変更管理を独自の自動化に統合するために必要な主要なインポートを示しています。

## Claude Desktop との統合

Claude Desktop で変更管理ツール付きの ServiceNow MCP サーバーを設定するには:

1. macOS では `~/Library/Application Support/Claude/claude_desktop_config.json` の Claude Desktop 設定ファイル、または OS に応じた適切なパスを編集します:

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

2. 変更を適用するために Claude Desktop を再起動します

## カスタマイズ

変更管理ツールは、組織固有の ServiceNow 設定に合わせてカスタマイズできます:

- 状態の値は、ServiceNow インスタンスの設定に応じて調整が必要な場合があります
- 必要に応じてパラメータモデルにフィールドを追加できます
- 承認ワークフローは、組織の承認プロセスに合わせて変更が必要な場合があります

ツールをカスタマイズするには、`src/servicenow_mcp/tools` ディレクトリ内の `change_tools.py` ファイルを変更します。
