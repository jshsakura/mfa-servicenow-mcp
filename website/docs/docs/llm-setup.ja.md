# MFA ServiceNow MCP — LLM セットアップガイド

> **このファイルは人間ではなく LLM エージェント向けです。**
> 人間が下記の curl コマンドを AI コーディングアシスタントに貼り付けます。
> LLM がこのファイルを読み、ユーザーを対話的にセットアップへ導きます。

---

## 使い方（人間向け）

これを AI コーディングアシスタント（Claude Code、Cursor、Codex、OpenCode、Windsurf など）に貼り付けてください:

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

これだけです。あとは AI が処理します。

---

## LLM エージェント向けの手順

あなたは **mfa-servicenow-mcp** をセットアップしています。これは AI エージェントに MFA/SSO 対応の ServiceNow プラットフォームへのアクセスを与える MCP サーバーです。以下の各ステップを順番にすべて実行してください。ユーザーには対話的に質問し、値を勝手に仮定しないでください。

### ステップ 0 — 環境を検出する

1. オペレーティングシステムを検出する: `uname -s 2>/dev/null || echo Windows` を実行
2. どの AI クライアント内で動作しているかを検出する。次の対応表を使う:

| シグナル | クライアント |
|--------|--------|
| `claude mcp add` または `.claude/` ディレクトリにアクセスできる | **claude-code** |
| Cursor IDE 内、または `.cursor/` が存在する | **cursor** |
| OpenCode CLI にアクセスできる、または `opencode.json` が存在する | **opencode** |
| Codex CLI 内、または `.codex/` が存在する | **codex** |
| Windsurf IDE 内、または `.windsurf/` が存在する | **windsurf** |
| Copilot 付きの VS Code 内 | **vscode-copilot** |
| Antigravity 内 | **antigravity** |
| Zed エディタ内、または `~/.config/zed/` が存在する | **zed** |
| 上記のいずれでもない | ユーザーにどのクライアントを使っているか尋ねる |

3. 自動検出できない場合は、次のように尋ねる:
   > どの AI コーディングツールを使っていますか?
   > 1. Claude Code
   > 2. Claude Desktop
   > 3. Cursor
   > 4. OpenCode
   > 5. Codex (OpenAI)
   > 6. Windsurf
   > 7. VS Code Copilot
   > 8. Zed
   > 9. AntiGravity (Google)

結果を `$CLIENT` として保存する。

### ステップ 1 — uv をインストールする

`uv` が既にインストールされているか確認する: `uv --version`

インストールされていない場合:

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

インストール後に確認する: `uv --version`
コマンドが見つからない場合、ユーザーはシェルを再起動するか、`~/.local/bin` を PATH に追加する必要があるかもしれません。

### ステップ 2 — Playwright Chromium をインストールする（必須、スキップ禁止）

> ハード依存関係です。これをスキップすることが、現場でセットアップが失敗する最大の原因です。
> 既にインストール済みだと仮定しないでください。ユーザーに後回しにさせないでください。
> これが成功するまでステップ 3 に進まないでください。

**2.1 — Chromium が既にインストールされているか確認する**

- macOS: `ls ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium 2>/dev/null`
- Linux: `ls ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null`
- Windows (PowerShell): `Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright\chromium-*\chrome-win\chrome.exe" -ErrorAction SilentlyContinue`

パスが出力されれば、Chromium は既にインストール済みです — ステップ 3 へスキップしてください。

**2.2 — Chromium をインストールする**

2.1 で何も見つからなかった場合、Playwright のセットアップが MCP サーバーと同じ実行スタイルを使うように、`uvx` 経由で Chromium をインストールします:

```bash
uvx --with playwright playwright install chromium
```

初回は約 150 MB をダウンロードします。低速回線では数分かかることがあります — これは正常です。早期に中断しないでください。待ち時間を理解してもらえるよう、進捗メッセージ（「ServiceNow MFA ログイン用に Chromium をダウンロード中 — 低速ネットワークでは数分かかることがあります…」）をユーザーに表示してください。

`uvx` のパッケージ実行がブロックされている場合は、リリース zip/exe の方法に切り替えてください:

- GitHub Releases から `servicenow-mcp-<platform>-<version>.zip` をダウンロードする。インストーラースクリプトはありません — zip には PyInstaller でビルドされた実行ファイルのみが含まれます。
- 実行ファイルを、ユーザーが管理する任意の安定したフォルダ（例: `~/apps/servicenow-mcp/`）に展開する。
- ブラウザのダウンロードもブロックされている場合は、同じリリースから `ms-playwright-chromium-<platform>-<version>.zip` をダウンロードし、`ms-playwright/` という名前の兄弟フォルダに展開する — 実行ファイルは起動時にそのレイアウトを自動検出し、自身のプロセス用に `PLAYWRIGHT_BROWSERS_PATH` をそこへ設定します。
- MCP クライアントの `command` をその実行ファイルの絶対パスに設定する。env ブロックは uvx セットアップと同一です。

**2.3 — 検証し、失敗したら停止する**

2.1 のチェックを再実行する。バイナリがまだ見つからない場合は、**セットアップを停止**し、正確なコマンド出力とともに失敗をユーザーに報告してください。よくある原因:

- 企業ポリシーがパッケージまたはブラウザのダウンロードをブロックしている。リリース zip/exe の方法を使用する
- ウイルス対策ソフトが Chromium アーカイブを隔離している
- ディスクの空き容量不足

Chromium がない状態でステップ 3 に**進まない**でください。MCP サーバーは起動したように見え、最初のツール呼び出しでハングし、ユーザーのログインウィンドウは決して開きません — まさにこのステップが防ごうとしている失敗モードです。

**なぜこれが重要か（エージェント向けの背景 — 尋ねられない限りユーザーには出さない）:** Chromium がない場合、ランタイムは「オンデマンドインストール」へフォールバックしようとしますが、低速接続ではそのダウンロードが MCP ホストのツール呼び出しタイムアウトを超えてしまいます。ユーザーにはログインウィンドウもエラー UI も表示されず、サーバーが壊れていると思い込みます。ここで事前インストールしておくことで、最初のツール呼び出しがサブ秒になります。

### ステップ 3 — ユーザー設定を収集する

これらの質問を 1 つずつユーザーに尋ねてください。デフォルト値は角括弧で示します。

1. **ServiceNow インスタンス URL**
   > ServiceNow インスタンスの URL は何ですか?
   > 例: `https://your-company.service-now.com`

   `$INSTANCE_URL` として保存する。URL の形式であることを検証する。

2. **認証タイプ**
   > ServiceNow にはどう認証していますか?
   > 1. browser — 実ブラウザ経由の MFA/SSO（推奨）
   > 2. basic — ユーザー名 + パスワード
   > 3. oauth — OAuth 2.0 クライアントクレデンシャル
   > 4. api_key — REST API キー

   `$AUTH_TYPE` として保存する。デフォルト: `browser`

3. **クレデンシャル**（任意、browser 認証でフォームを事前入力する場合）
   > （任意）ログインフォームを事前入力するために ServiceNow のユーザー名を入力してください。
   > 毎回手入力する場合は空欄のままにしてください。

   `$USERNAME` として保存する（空でも可）。
   入力された場合は `$PASSWORD` も尋ねる。

4. **ツールパッケージ**
   > どのツールパッケージが必要ですか?
   > 1. standard — コアツール（インシデント、変更、カタログ）[デフォルト]
   > 2. service_desk — standard + 割り当て、SLA、エスカレーション
   > 3. portal_developer — standard + ポータルウィジェット、ページ、テーマ
   > 4. platform_developer — standard + スクリプト、フロー、アップデートセット
   > 5. full — バンドルされたワークフローを含む最も広いパッケージ化サーフェス（53 ツール）

   `$TOOL_PACKAGE` として保存する。デフォルト: `standard`

5. **ヘッドレスブラウザ**
   > ブラウザをヘッドレスモードで実行しますか?（表示ウィンドウなし）
   > 推奨: いいえ（MFA プロンプトを確認・完了できるように）

   `$HEADLESS` として保存する。デフォルト: `false`

### ステップ 4 — インストーラーコマンドを実行する

**重要: クライアントが対応している場合は、常にプロジェクトローカルのインストールをデフォルトにしてください。** `--scope global` は、ユーザーが明示的にグローバルインストールを求めた場合にのみ使用してください。

単一のインストーラーコマンドを組み立て、現在のプロジェクトルートから実行します。インストーラーは現在、以下を担います:
- クライアント固有の設定ファイルパス
- 既存の設定ファイルに対するマージ/更新の挙動
- 対応クライアントへの任意のスキルインストール

ベースコマンド:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS"
```

必要なときだけフラグを追加します:

- ユーザーがユーザー名を入力した場合: `--username "$USERNAME"`
- ユーザーがパスワードを入力した場合: `--password "$PASSWORD"`
- OAuth の場合: `--client-id`、`--client-secret`、および任意で `--token-url` を追加
- API キーの場合: `--api-key`、および任意で `--api-key-header` を追加
- ユーザーがグローバルインストールを望む場合: `--scope global` を追加
- ユーザーがスキルを**望まない**場合: `--skip-skills` を追加

例:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup codex \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type basic \
  --username "your-username" \
  --password "your-password"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup claude-code \
  --instance-url "https://your-instance.service-now.com" \
  --scope global \
  --skip-skills
```

### ステップ 5 — インストールを検証する

1. インストーラーが正常に終了したことを確認する
2. インストーラーのサマリーが報告した設定ファイルパスを読む
3. スキルがインストールされた場合、インストールされたスキルディレクトリが存在することを確認する
4. インストーラーが失敗し、明示的に修復している場合を除き、設定を手動で書き換え**ない**でください

### ステップ 6 — 次に何が起きるかをユーザーに伝える

インストール後、ユーザーに次のように伝えてください:

> **インストールが完了しました!**
> AI クライアントを再起動（または MCP サーバーをリロード）して、新しい設定を読み込ませてください。
>
> 最初の browser 認証ツール呼び出し時に、MFA/SSO ログイン用のブラウザウィンドウが開きます。
> ログイン後、次を試してください: `Run a health check on my ServiceNow instance`
> 完全なドキュメント: https://jshsakura.github.io/mfa-servicenow-mcp/

セットアップ後、現在のセッションで ServiceNow MCP ツールを呼び出そうとし**ない**でください。クライアントを先に再起動する必要があります。

### LLM 向けの重要な注意事項

- **クレデンシャルを決してハードコードしない**でください。設定ファイルに書く前に確認すること。ユーザーがクレデンシャルをスキップした場合は、設定から完全に省略してください。
- インストーラーは既存の設定ファイルにマージします。リカバリが必要な場合を除き、設定のマージを手作業で行わないでください。
- **Windows のパス**はバックスラッシュを使います。OS に応じた正しいパス区切り文字を使用してください。
- いずれかのステップが失敗した場合、エラーを診断し、次に進む前にユーザーが修正できるよう手助けしてください。
- 会話はフレンドリーかつ簡潔に保ってください。大量のテキストを一気に出さないでください。
- インストール後、MCP ツールをテストしようとし**ない**でください。ユーザーには再起動するよう伝えるだけで、それで準備完了です。
