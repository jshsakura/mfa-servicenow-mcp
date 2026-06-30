# ServiceNow MCP - ツールインベントリ

`scripts/regenerate_tool_inventory.py` によって自動生成されます。手作業で編集しないでください。

ライブレジストリに登録されているツール: **65**
`full` にパッケージ化されたツール数: **54**
登録済みだが現在パッケージ化されていないツール: **11**

`list_tool_packages` は、`none` を除くすべての有効なパッケージに実行時に注入されます。
本ファイルでは下記に記載していますが、本ファイル内のパッケージ数は YAML で定義されたツールサーフェスを反映しています。

## パッケージ概要

| パッケージ | ツール数 | 説明 |
|---------|------:|-------------|
| `none` | 0 | 意図的にツールをオフにするための無効化プロファイル。 |
| `core` | 12 | 素早いヘルス/スキーマ/テーブル作業のための最小限の読み取り専用エッセンシャル。 |
| `standard` | 28 | インシデント、変更、ポータル、ログ、ソース分析にわたるデフォルトの読み取り専用パッケージ。 |
| `service_desk` | 30 | standard に加え、運用サポート向けのインシデントと変更の書き込みワークフロー。 |
| `portal_developer` | 40 | standard に加え、ポータル、チェンジセット、スクリプトインクルード、ローカル同期デリバリーワークフロー。 |
| `platform_developer` | 40 | standard に加え、ワークフロー、Flow Designer、UI ポリシー、インシデント/変更、スクリプトの書き込み。 |
| `full` | 54 | 最も広いパッケージ化サーフェス: すべての manage_* ワークフローに加えて高度な操作。 |

## 実行時に注入されるヘルパー

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `list_tool_packages` | R | 利用可能なツールパッケージと現在アクティブなものを一覧表示する。 | `core`, `standard`, `service_desk`, `portal_developer`, `platform_developer`, `full` |
| `list_instances` | R | 読み取り専用データ比較モード用に設定されたエイリアスを一覧表示する。 | 実行時比較ヘルパー |
| `compare_instances` | R | 設定済みエイリアス間の読み取り専用レコード比較。書き込みルーティングの仕組みではない。 | 実行時比較ヘルパー |

## 登録済みだがパッケージ化されていないツール

これらのツールはコードに登録されていますが、パッケージ化された YAML サーフェスからは意図的に除外されています。カスタムビルド、テスト、または将来のパッケージ化の判断のために引き続き到達可能です。

`create_category`, `create_knowledge_base`, `get_developer_daily_summary`, `get_repo_file_last_modifier`, `get_repo_recent_commits`, `get_repo_working_tree_status`, `get_uncommitted_changes`, `manage_epic`, `manage_project`, `manage_scrum_task`, `manage_story`

## モジュール別ツール

**R/W** 列は、制限がない場合のツールの完全な機能です。`pkg (actions…)` として示されるパッケージは、そのツールの当該アクションのみを公開します — 例えば `manage_script_include` は `R/W` として登録されていますが、読み取り専用パッケージ（`core`、`standard`）はそれを `standard (get, list)` として公開します。括弧なしで記載されているパッケージは、そのツールを完全な R/W 機能で公開します。

### 添付ファイルツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `download_attachment` | R | ServiceNow の添付ファイルを attachment_sys_id、またはテーブル + レコードでディスクにダウンロードする。saved_path から読み込む。 | standard, portal_developer, platform_developer, service_desk, full |

### 監査ツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | 保留中のアップデートセット変更を監査する — タイプ別インベントリ、リスクパターン、クローン、相互参照。 | full |

### カタログツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_catalog` | R/W | カタログのカテゴリ/アイテム/変数の CRUD（テーブル: sc_category, sc_cat_item, item_option_new）。 | portal_developer, service_desk (get_item, list_categories, list_item_variables, list_items), full |

### 変更ツール (4)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `approve_change` | W | 変更の承認レコードを承認する（approver_id で）。change_request を進める（デフォルト: implement）。 | full |
| `manage_change` | R/W | 変更要求の取得/作成/更新、または変更タスクの追加（テーブル: change_request）。 | platform_developer, full |
| `reject_change` | W | 変更の承認レコードを理由付きで却下する（approver_id で）。change_request を進める（デフォルト: canceled）。 | full |
| `submit_change_for_approval` | W | 変更要求を assess 状態に遷移させ、承認レコードを作成する。change_id が必要。 | platform_developer, full |

### チェンジセットツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_changeset` | R/W | アップデートセットの get/create/update/commit/publish/add_file（テーブル: sys_update_set）。 | portal_developer, platform_developer, full |

### エピックツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_epic` | R/W | エピックの CRUD（テーブル: rm_epic）。list は確認をスキップする。 | — |

### フローツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_flow_designer` | R/W | Flow Designer の読み取り/検査。編集はアクション入力 + トリガー/ブランチ条件に限定。構造的変更は不可（UI を使用）。 | core (list), standard (get_action_source, get_detail, get_executions, list), portal_developer, platform_developer, service_desk (get_action_source, get_detail, get_executions, list), full |

### インシデント管理 (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_incident` | R/W | インシデントの取得/作成/更新/コメント/解決（テーブル: incident）。1 回の呼び出しで、スキーマ検索不要。 | platform_developer, service_desk, full |

### ナレッジベース (3)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `create_category` | W | ナレッジベース配下に KB カテゴリを作成する。kb_id と label が必要。 | — |
| `create_knowledge_base` | W | ナレッジベースを作成する（kb_knowledge_base）。title が必要。sys_id を返す。 | — |
| `manage_kb_article` | R/W | ナレッジ記事の作成/更新/公開（テーブル: kb_knowledge）。 | full |

### ローカルグラフツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `query_local_graph` | R | 監査グラフファイルからのオフライン依存関係/影響の回答（API 0 回）。uses|used_by|page|impact。 | standard, portal_developer, platform_developer, service_desk, full |

### ログ (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `get_logs` | R | ServiceNow のログをクエリする。log_type: system/journal/transaction/background。最大 20 行。 | core, standard, portal_developer, platform_developer, service_desk, full |

### パフォーマンスツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | ウィジェットのパフォーマンスを分析する — コードパターン、トランザクションログ、プロバイダー使用状況。重大度付きの所見を返す。 | standard, portal_developer, platform_developer, service_desk, full |

### ポータル CRUD (3)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_portal_component` | W | ポータルコンポーネントを作成する。または sys_id で任意のコードレコードを編集する — BR、通知、SI、ACL、UI など。action=update_code。 | portal_developer, platform_developer, full |
| `manage_portal_layout` | W | ポータルレイアウト: ページ CRUD + コンテナ/行/列 + ウィジェットインスタンスの配置。 | portal_developer, platform_developer, full |
| `scaffold_page` | W | レイアウト（コンテナ/行/列）とウィジェット配置を含む完全なポータルページを 1 回の呼び出しで作成する。Scope は必須。 | portal_developer, platform_developer, full |

### ポータル開発ツール (3)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `get_developer_changes` | R | 開発者のポータルテーブル全体にわたる最近の変更を一覧表示する。メタデータのみ。まず count_only を使う。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_developer_daily_summary` | R | 開発者の日次作業サマリーを生成する。jira/plain/structured の出力形式に対応。 | — |
| `get_uncommitted_changes` | R | 開発者の未コミットのアップデートセットエントリを一覧表示する。エントリのタイプとターゲットを返す。まず count_only=true を使う。 | — |

### ポータル管理 (9)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | R | 提案されたポータルコンポーネント編集を分析し、限定的なリスクとフィールド変更のサマリーを返す | portal_developer, full |
| `detect_angular_implicit_globals` | R | Angular プロバイダースクリプトで実行時 'not defined' エラーを引き起こす未宣言の変数代入を検出する。 | portal_developer, full |
| `download_portal_sources` | R | 対象を絞ったポータルウィジェット/プロバイダー。アプリ全体: download_app_sources。widget_ids=1 つのウィジェット。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_portal_component_code` | R | ウィジェット/プロバイダー/SI のフィールドを取得する。デフォルトで本文全体を返す。分析のためにチャンク分割しない。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_widget_bundle` | R | 完全なウィジェットバンドル（HTML、スクリプト、プロバイダー、CSS/JS 依存関係）を 1 回の呼び出しで取得する。分析の出発点。 | standard, portal_developer, platform_developer, service_desk, full |
| `preview_portal_component_update` | R | 提案されたポータルコンポーネント編集について、限定的な前後スニペットと差分をプレビューする | portal_developer, full |
| `route_portal_component_edit` | R | ポータル編集の指示を適切な analyze/preview/apply ツールにルーティングする。 | portal_developer, full |
| `search_portal_regex_matches` | R | ポータルコード（widget/provider/SI）に対する真の正規表現、オフセット + コンテキスト。サーバーテーブルのキーワード検索: search_server_code。 | standard, portal_developer, platform_developer, service_desk, full |
| `trace_portal_route_targets` | R | widget→provider→route の関係をマッピングする。メタデータのみ、スクリプト本文なし。 | standard, portal_developer, platform_developer, service_desk, full |

### ポータル管理ツール (3)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `get_page` | R | URL パス、タイトル、または sys_id でポータルページを取得または一覧表示する。ウィジェット配置を含むレイアウトツリーを返す。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `get_portal` | R | 名前、URL サフィックス、または sys_id でサービスポータルを取得または一覧表示する。設定、ホームページ、テーマ、ページを返す。 | full |
| `get_widget_instance` | R | ページ上のウィジェットインスタンス配置を取得する。列、順序、設定を返す。ページまたはウィジェットでフィルタする。 | standard, portal_developer, platform_developer, service_desk, full |

### プロジェクトツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_project` | R/W | プロジェクトの CRUD（テーブル: pm_project）。list は確認をスキップする。 | — |

### リポジトリ (4)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | 統合された git レポート: ワーキングツリーの状態 + 最近のコミット + ファイルごとの最終更新者を 1 回の呼び出しで。 | full |
| `get_repo_file_last_modifier` | R | ファイルごとの最終更新者とコミットメタデータを検索する（任意で未コミットの状態も）。 | — |
| `get_repo_recent_commits` | R | 作者と任意の変更ファイル一覧を含む最近のコミットを一覧表示する。 | — |
| `get_repo_working_tree_status` | R | ステージ済み、未ステージ、未追跡のファイルを含むワーキングツリーの状態を検査する。 | — |

### スクリプトインクルード (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_script_include` | R/W | スクリプトインクルードの list/get/create/update/delete/execute（テーブル: sys_script_include）。 | core (get, list), standard (get, list), portal_developer, platform_developer, service_desk (get, list), full |

### スクラムタスクツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_scrum_task` | R/W | スクラムタスクの CRUD（テーブル: rm_scrum_task）。list は確認をスキップする。 | — |

### セッションコンテキストツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_session_context` | W | 現在のアプリケーション + アップデートセットの取得/切り替え（browser 認証）。set_* は読み戻しで検証する。 | portal_developer, platform_developer, full |

### Sn Api (7)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `sn_aggregate` | R | 任意のテーブルで COUNT/SUM/AVG/MIN/MAX を任意の group_by 付きで実行する。レコードを取得せずに統計を返す。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_discover` | R | 名前またはラベルのキーワードでテーブルを検索する。テーブル名、ラベル、スコープ、親クラスを返す。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_health` | R | ServiceNow API の接続性、認証状態、Chromium のインストール状態（browser 認証）、MCP サーバーのバージョンを確認する。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_query` | R | 汎用テーブルクエリ — 最終手段。ドメインツールを優先: search_server_code、manage_workflow、manage_flow_designer。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_resolve_url` | R | ServiceNow URL を解析 → テーブル、sys_id、スコープ、推奨される次のツール。読み取り専用。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_schema` | R | 指定テーブルについて、sys_dictionary からフィールド名、型、ラベル、制約を取得する。 | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_write` | W | 最終手段の CRUD（専用ツールがない場合）。manage_*/update_* を優先。ACL/user/group/scope はブロック。confirm='approve'。 | full |

### ソース分析 (6)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `download_app_sources` | R | アプリスコープの全/完全ソースをディスクへ（全グループ + 依存関係）。scope 必須 — ユーザーに尋ねる。Step 1、ポータルではない。 | standard, portal_developer, platform_developer, service_desk, full |
| `download_server_sources` | R | 対象を絞ったサーバーサイドソースファミリー（SI/BR/UI/api/security/admin）。アプリ全体: download_app_sources。 | platform_developer, full |
| `download_table_schema` | R | sys_dictionary のフィールド定義をダウンロードする。テーブルを指定するか、ローカルソースから自動検出する。 | platform_developer, full |
| `extract_table_dependencies` | R | サーバースクリプト（SI/BR/widgets）からの GlideRecord テーブル依存関係グラフ。1 つのウィジェットには widget_id を渡す。 | standard, portal_developer, platform_developer, service_desk, full |
| `get_metadata_source` | R | 名前/sys_id で 1 つのソースレコード（SI/BR/widget）を取得する。本文を返す。'complete' は切り詰められたプレビューかどうかを示す。 | standard, portal_developer, platform_developer, service_desk, full |
| `search_server_code` | R | 22 種類のサーバーサイドコードタイプ（SI/BR/ACL）にわたる高速キーワード検索。ポータルの正規表現 + スニペット: search_portal_regex_matches。 | core, standard, portal_developer, platform_developer, service_desk, full |

### ソース監査ツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `audit_local_sources` | R | ダウンロードしたソースをローカルで分析する（API なし）。相互参照グラフ、デッドコード、HTML レポートを生成する。 | standard, portal_developer, platform_developer, service_desk, full |

### ストーリーツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_story` | R/W | ストーリーの CRUD + 依存関係操作（rm_story/m2m_story_dependencies）。list/list_dependencies は確認をスキップする。 | — |

### 同期ツール (2)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `diff_local_component` | R | ローカル編集とリモート（または compare_to 経由で 2 つ目のダウンロードルート、例: dev-vs-test）との差分。 | standard, portal_developer, platform_developer, service_desk, full |
| `update_remote_from_local` | W | 1 つのローカル編集を ServiceNow へプッシュバックする（まず diff_local_component）。対象を絞ったリフレッシュであり、一括の dev→test 昇格ではない。 | portal_developer, platform_developer, full |

### UI ポリシー (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_ui_policy` | W | UI ポリシーの作成 + フィールドアクションの追加（テーブル: sys_ui_policy / sys_ui_policy_action）。 | portal_developer, platform_developer, full |

### ユーザーツール (2)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_group` | R/W | グループの CRUD + メンバーシップ操作（テーブル: sys_user_group）。list は確認をスキップする。 | full |
| `manage_user` | R/W | ユーザーの CRUD + 検索（テーブル: sys_user）。読み取りアクションは確認をスキップする。 | full |

### ウィジェット依存関係ツール (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_widget_dependency` | R/W | ウィジェットの Angular プロバイダーと CSS/JS 依存関係の CRUD + link/unlink。sys_id にはまず action=list を使う。 | standard (get, list), portal_developer, platform_developer (get, list), service_desk (get, list), full |

### ワークフロー (1)

| ツール | R/W | 説明 | パッケージ |
|------|-----|-------------|----------|
| `manage_workflow` | R/W | レガシーワークフローエンジン専用（wf_workflow/wf_activity）。ほとんどのフローは Flow Designer -> manage_flow_designer を使用。 | core (get_activities, list), standard (get_activities, list), portal_developer, platform_developer, service_desk (get_activities, list), full |
