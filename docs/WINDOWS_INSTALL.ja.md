# Windows インストールガイド

デフォルトでは `uvx` を使用してください。エンドポイントセキュリティ/Zscaler が `uvx` やパッケージのダウンロードをブロックする場合は、下記のリリース zip/exe のセクションを使用してください。

---

## ステップ 1: デフォルトの uvx インストール

管理者権限なしで PowerShell を開きます:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

これで `uv` がインストールされ、サーバーが取得・検証され、Chromium がダウンロードされます。その後、サーバーを MCP クライアントの設定ファイルに追加します（インストーラーコマンド不要）:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

`uvx` は標準の Playwright キャッシュ内に一致する Chromium が既にあれば再利用します。Chromium がない場合は、まず上記のインストールコマンドを実行してください。

---

## ステップ 2: リリース zip/exe インストール

`uvx` がブロックされている場合に使用します。GitHub Releases から `servicenow-mcp-windows-x64-<version>.zip` をダウンロードします。これには PyInstaller でビルドされた単一の `servicenow-mcp.exe` と `LICENSE` が含まれます。インストーラースクリプトは不要です — 実行ファイルが Chromium の検出を自身で行います。管理する安定したフォルダ（例: `C:\Users\you\apps\servicenow-mcp\`）を選び、`servicenow-mcp.exe` をそこに展開し、Chromium zip がある場合は **先に展開** して同じフォルダに入れます。`.zip` を放置しないでください。展開したフォルダ名は Windows が生成したままでも `ms-playwright\` にリネームしてもかまいません。実行ファイルは起動時に隣接する `ms-play*` ディレクトリを glob で探します:

```
C:\Users\you\apps\servicenow-mcp\
├── servicenow-mcp.exe
└── ms-playwright-chromium-windows-x64-<ver>\   (デフォルトの展開名で動作)
    └── chromium-1185\
        └── …
```

起動時、実行ファイルは隣接する `ms-play*\chromium-*` ディレクトリを探し、現在のプロセスに限り `PLAYWRIGHT_BROWSERS_PATH` 経由で Playwright をそこへ向けます。システム標準の Playwright キャッシュ（`%LOCALAPPDATA%\ms-playwright`）には触れず、MCP クライアント設定も変更せず、ディスク上のどこにも書き込みません。

その後、これをクライアント設定ファイルに貼り付けます（Claude Code / Claude Desktop の例）:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe",
      "args": [],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

`SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` は任意の MFA ログイン事前入力です。Chromium を隣接する `ms-playwright\` ディレクトリ以外の場所に置いた場合は、`env` ブロックに `"PLAYWRIGHT_BROWSERS_PATH": "C:/abs/path/to/ms-playwright"` を追加してください。Codex（`config.toml`）/ OpenCode（`opencode.json`）/ Cursor / Antigravity / Zed 用のスニペットは [クライアントセットアップガイド](CLIENT_SETUP.md) にあります。

これにより `uvx` をランタイムから完全に排除できます。

Chromium がバンドルされておらず、ダウンロードが許可されている場合は、<https://www.python.org/downloads/> から Python をインストールしてから次を実行します:

```powershell
py -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = "$HOME\apps\servicenow-mcp\ms-playwright"
py -m playwright install chromium
```

Playwright のブラウザダウンロードもブロックされている場合は、chromium-bundle リリース（https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle）から `ms-playwright-chromium-windows-x64.zip` をダウンロードし、その内容を次の場所に展開します:

```text
%LOCALAPPDATA%\ms-playwright
```

Playwright ブラウザのドキュメント: <https://playwright.dev/python/docs/browsers>

---

## ステップ 3: リリースアセットをビルドする

メンテナーは Windows でリリース zip をビルドします:

```powershell
py scripts\build_desktop_release.py --browser-zip
```

これにより、実行ファイルの zip と、ブロックされたネットワーク用の任意の Playwright Chromium キャッシュ zip が作成されます。

---

## ステップ 4: MCP クライアントを設定する

下記からお使いの MCP クライアント用の設定をコピーします。
`your-instance` を実際の ServiceNow インスタンスアドレスに置き換えてください。

### Claude Desktop

設定ファイルの場所: `%APPDATA%\Claude\claude_desktop_config.json`

> ファイルが存在しない場合は作成してください。フォルダがない場合は、Claude Desktop を一度起動して作成させてください。

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Claude Code

CLI で登録 — 設定ファイル不要:

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

確認:
```powershell
claude mcp list
```

### OpenAI Codex

設定ファイルの場所: `%USERPROFILE%\.codex\agents.toml` またはプロジェクトルートの `.codex\agents.toml`。

> ファイルとフォルダが存在しない場合は作成してください。

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://your-instance.service-now.com",
  "--auth-type", "browser",
  "--browser-headless", "false",
  "--tool-package", "standard",
]
```

### OpenCode

設定ファイルの場所: プロジェクトルートの `opencode.json`。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Zed

設定ファイルの場所: `~/.config/zed/settings.json`

> Zed の **Settings** > **MCP Servers** から追加します:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": [
      "--with", "playwright",
      "--from", "mfa-servicenow-mcp",
      "servicenow-mcp"
    ],
    "env": {
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

### AntiGravity

設定ファイルの場所: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> エージェントパネルの **...** → **Manage MCP Servers** → **View raw config** からもアクセスできます。

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> 設定を保存してから、AntiGravity で **Refresh** をクリックします。

---

## ステップ 5: スキルをインストールする（任意）

スキルは AI の実行ブループリントです — 安全ゲートを備えた検証済みパイプラインで、生の MCP ツールを信頼できるワークフローに変えます。3 カテゴリにわたる 4 スキル。

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# または uvx で（インストール不要）
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

| クライアント | インストールパス | 自動検出 |
|--------|-------------|----------------|
| Claude Code | `.claude\commands\servicenow\` | 次回起動時に `/servicenow` スラッシュコマンドが表示される |
| OpenAI Codex | `.codex\skills\servicenow\` | 次回エージェントセッションでスキルが読み込まれる |
| OpenCode | `.opencode\skills\servicenow\` | 次回セッションでスキルが読み込まれる |

| カテゴリ | スキル | 目的 |
|----------|--------|------|
| `analyze/` | 6 | ウィジェット分析、ポータル診断、依存関係マッピング、コード検出 |
| `fix/` | 3 | ウィジェットのパッチ適用（段階的な安全ゲート）、デバッグ、コードレビュー |
| `manage/` | 8 | ページレイアウト、スクリプトインクルード、ソースエクスポート、アプリソースダウンロード、チェンジセットワークフロー、ローカル同期、ワークフロー管理、スキル管理 |
| `deploy/` | 2 | 変更要求のライフサイクル、インシデントトリアージ |
| `explore/` | 5 | ヘルスチェック、スキーマ検出、ルートトレース、フロートリガートレース、ESC カタログフロー |

**更新:** 同じインストールコマンドを再実行すると、既存のすべてのスキルファイルが置き換えられます。
**スキルのみ削除:** スキルディレクトリを手動で削除します（例: `Remove-Item -Recurse .claude\commands\servicenow\`）。

---

## ステップ 6: 検証する

1. MCP クライアントを **完全に終了して再起動** します（トレイアイコンも閉じる）。
2. ブラウザウィンドウは最初のツール呼び出し時に開きます（サーバー起動時ではありません）。
3. Okta/Microsoft Authenticator などで MFA 認証を完了します。
4. 認証後、ブラウザは自動的に閉じ、セッションは保持されます。

テスト: クライアントから `sn_health` ツールを呼び出します。

> ブラウザが開かない場合は、Chromium がインストールされているか確認してください。次のコマンドで強制インストールできます: `uvx --with playwright playwright install chromium`

---

## セッション管理

認証済みセッションは自動的にディスクに保存されます — 毎回ログインする必要はありません。

- **セッションファイルの場所**: `%USERPROFILE%\.servicenow_mcp\session_*.json`
- **デフォルトのセッション TTL**: 30 分（キープアライブスレッドが 15 分ごとに延長）
- **セッション失効時**: 再認証のためにブラウザウィンドウが自動的に開きます

TTL を変更するには、`--browser-session-ttl` オプション（分単位）を使用します:
```
--browser-session-ttl 60
```

ブラウザプロファイルを永続化するには、`--browser-user-data-dir` オプションを追加します:
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
これにより、Cookie とログイン状態がディレクトリに保存され、セッションの永続性が長くなります。

---

## ツールパッケージ

ツールセットを選ぶには `MCP_TOOL_PACKAGE` を設定します。デフォルト: `standard`（読み取り専用）。

| パッケージ | ツール数 | 説明 |
|---------|:-----:|-------------|
| `core` | 12 | ヘルス、スキーマ、検出、キー検索のための最小限の読み取り専用エッセンシャル |
| `standard` | 27 | **（デフォルト）** インシデント、変更、ポータル、ログ、ソース分析にわたる読み取り専用パッケージ |
| `service_desk` | 29 | standard + インシデントと変更の運用書き込み |
| `portal_developer` | 38 | standard + ポータル、チェンジセット、スクリプトインクルード、ローカル同期デリバリーワークフロー |
| `platform_developer` | 43 | standard + ワークフロー、Flow Designer、UI ポリシー、インシデント/変更、スクリプト書き込み |
| `full` | 57 | 最も広いパッケージ化サーフェス: すべての `manage_*` ワークフローに加えて高度な操作 |

変更するには、`MCP_TOOL_PACKAGE` の値を更新します:

JSON クライアント（Claude Desktop、AntiGravity）:
```json
"env": {
  "MCP_TOOL_PACKAGE": "standard"
}
```

TOML クライアント（Codex）— `args` 配列の中に追加します:
```toml
"--tool-package", "standard",
```

---

## トラブルシューティング

### 「uvx not found」
→ ステップ 1 の後に PowerShell を **閉じて再度開いた** か確認してください。それでも失敗する場合:
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### 「Python is not installed」
→ `uv` は Python 3.11+ を自動的にダウンロードします。手動インストールは不要です。
システムの Python と競合する場合は、`uv` をアンインストールして再インストールしてください。

### 「Browser won't open」
→ MCP 起動前に Chromium がインストールされている必要があります:
```powershell
uvx --with playwright playwright install chromium
```
→ ブラウザのダウンロードがブロックされている場合は、chromium-bundle リリースの `ms-playwright-chromium-windows-x64.zip` を使用し、`%LOCALAPPDATA%\ms-playwright` に展開してください。

### 「MCP server won't connect」
→ 設定ファイルの構文を確認してください:
  - JSON: カンマ、引用符、対応する波括弧
  - TOML: 角括弧、引用符、カンマ
→ `instance-url` が `https://` で始まっているか確認してください。
→ Claude Desktop は設定変更後に **完全な終了と再起動** が必要です（トレイアイコンも閉じる）。

### 「PowerShell script execution is blocked」
→ 現在のユーザーに対して実行を許可します:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### セッションのリセット
ログインの問題が続く場合は、セッションキャッシュを削除して再試行します:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### バージョン更新
`uvx` は最後にダウンロードしたキャッシュ済みバージョンを再利用します。実行のたびに新しいリリースへ自動的に更新する**わけではありません**。最新の公開バージョンをキャッシュに取り込むには:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

リフレッシュ後、MCP クライアントを完全に再起動して、新しいキャッシュ済みバージョンを起動させてください。
