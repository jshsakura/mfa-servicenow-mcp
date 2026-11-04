# 変更管理

1 つのツール `manage_change` で、変更リクエスト（`change_request`）、変更タスク、承認ステップを扱います。

| パッケージ | アクション |
|---|---|
| `platform_developer`, `full` | すべてのアクション |

書き込みアクションには、このサーバーの他の書き込みと同じく `confirm='approve'` が必要です。長い一覧や条件付きの一覧には、`table=change_request` を指定した `sn_query` も使えます。

## アクション

| アクション | 必須 | 任意 |
|---|---|---|
| `action="get"` | 1 件なら `change_id`、一覧なら不要 | `limit`, `offset`, `timeframe`, `query`, `state`, `type`, `category`, `assignment_group`, `count_only` |
| `action="create"` | `short_description`, `type` | `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date` |
| `action="update"` | `change_id` と 1 つ以上のフィールド | `short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes` |
| `action="add_task"` | `change_id`, `task_short_description` | `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date` |
| `action="submit"` | `change_id` | `state`（既定 Assess）、`work_notes`（承認依頼のコメント） |
| `action="approve"` | `change_id` | `approver_id`、`state`（既定 Implement）、`work_notes`（コメント） |
| `action="reject"` | `change_id`、`work_notes`（却下理由） | `approver_id`、`state`（既定 Canceled） |

## 承認

- `action="submit"` は変更を目標の状態に移し、requested 状態の承認レコードを作成します。
- `action="approve"` と `action="reject"` は `approver_id`（sys_id または名前）の承認レコードに適用します。指定がなければ、まだ保留中の最初のレコードに適用します。その後、変更を目標の状態に移します。
- submit と approve は他の人が引き継ぐ変更を動かすため、`confirm_publish='approve'` も必要です。

## 選択肢の値

`state`、`type`、`risk`、`impact` に保存されるのは単語ではなくコードです。たとえば `state` の -4 は Assess、-1 は Implement です。コードかラベルのどちらかを渡してください。書き込む前にそのインスタンス自身の選択肢一覧（`sys_choice`）と照合し、一覧にない値は拒否して、有効な値をすべて示します。

approve と reject は、承認レコードに触れる前に目標の状態を確認します。そのため、誤った状態が原因で承認だけが処理され、変更が元のまま残ることはありません。

## プレビュー

どの書き込みアクションにも `dry_run=true` を渡せます。

- `action="update"` はフィールドごとの差分を返します。
- `action="approve"` と `action="reject"` は、変更される承認レコードと変更の状態を返します。
- それ以外の書き込みアクションは、送信するはずのリクエストをそのまま `would_send` として返します。

どちらの場合も何も書き込みません。

## プロンプト例

- 「明日の夜にセキュリティパッチを適用するサーバーメンテナンスの変更リクエストを作成して。」
- 「サーバーメンテナンスの変更に事前チェックのタスクを追加して。」
- 「サーバーメンテナンスの変更を承認依頼して。」
- 「DB アップグレードの変更を承認して。コメント：実装計画が丁寧。」
- 「ネットワーク変更を却下して。理由：テスト不足。」
- 「今週予定されている緊急変更をすべて見せて。」
