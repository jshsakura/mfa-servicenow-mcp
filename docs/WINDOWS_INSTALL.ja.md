# Windows インストールガイド

Windows でも他の環境と同じく `uvx` がデフォルトです。ただし Windows 固有の事情が 1 つあり、これに当たった場合は別の方法に切り替える必要があります:

- **Smart App Control が `uvx` をブロックする** → **pip**（ステップ 1b）に切り替えます。Windows で起きるトラブルとしては圧倒的にこれが多く、たいていは Windows Update の直後に何の前触れもなく発生します。

**PyPI 自体に到達できない**場合（社内ネットワークがパッケージインデックスごと遮断しているケース）は、どちらの方法でもパッケージを取得できません。情報システム部門に `pypi.org` と `files.pythonhosted.org` の許可を依頼するか、社内インデックスにミラーしてもらい、`pip install --index-url` でそこを指定してインストールしてください。

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

**更新:** `uvx` はダウンロード済みのバージョンをキャッシュして使い続けるため、新しいリリースを取り込むには明示的な操作が必要です:

```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

---

## ステップ 1b: Smart App Control が uvx をブロックする場合は pip でインストールする

### 症状

`uvx` が有用なエラーを一切出さずに動かなくなります。MCP クライアントは「サーバーの起動に失敗した」と報告し、PowerShell では「管理者によってブロックされました」「システムポリシーによりブロックされました」といったメッセージが出ます。設定は何も変えていません。これは **Windows Update の直後** に始まることが非常に多く、そのためランチャーではなくサーバー側が壊れたように見えてしまいます。

### 原因

[Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0)（SAC）は、**署名済み、または安全性が確認済み**の実行ファイルだけを実行させる Windows 11 の機能です。`uvx` は恒久的にインストールされたプログラムを実行するのではなく、**実行のたびに署名のない一時実行ファイルを新しく展開して**起動します。これはまさに SAC が防ぐために存在する挙動そのものなので、毎回ブロックされます。リトライしても `uv` を再インストールしても変わりません — 仕様上、ファイルは実行のたびに新規かつ未署名だからです。

SAC は新しい Windows 11 マシンでは評価モードで動作しており、後から**自動的にオン**に切り替わることがあります。何か月も問題なく動いていたマシンで、ある日突然この現象が起きるのはこのためです。

確認方法: **Windows セキュリティ → アプリとブラウザーの制御 → スマート アプリ コントロールの設定**。

> **これを回避するために Smart App Control をオフにしないでください。** オフにする操作は **一方通行** です — 一度無効にすると、Windows は二度と有効に戻させてくれません。元に戻すには **Windows の再インストール** が必要です。パッケージランチャーひとつのために OS のセキュリティを恒久的に下げるのは割に合いません。代わりに pip を使ってください。SAC をオンにしたまま問題を完全に解決できます。

### pip での導入手順

pip でインストールした場合、サーバーは **署名済み** の Python インタープリタが実行する通常の Python ファイルになるため、SAC が問題視する要素がなくなります。

[python.org のインストーラー](https://www.python.org/downloads/) から Python **3.10 以降** をインストールしてください。このビルドは署名済みで、そのまま SAC を通過します。（Microsoft Store 版の Python でも動作します。）インストール時に **「Add python.exe to PATH」** にチェックを入れてください。その後:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**更新:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Chromium は上記のように先にインストールしておいてください。最初のツール呼び出しまで先送りすると、約 150 MB のダウンロードが MCP クライアントのハンドシェイクのタイムアウトと競合し、`connection closed` として表面化します。

### 必ずモジュールとして起動し、コンソールスクリプトは使わない

pip は Scripts フォルダに `servicenow-mcp.exe` というシムも配置します。**このシムは pip がマシン上で生成する未署名の `.exe` なので、uvx とまったく同じ理由で SAC にブロックされます。** モジュールを直接呼び出して、シムを完全に迂回してください:

| 使わないコマンド | 代わりに使うコマンド |
|---|---|
| `servicenow-mcp` | `python -m servicenow_mcp` |
| `servicenow-mcp setup` | `python -m servicenow_mcp setup` |
| `servicenow-mcp --version` | `python -m servicenow_mcp --version` |
| `servicenow-mcp-skills claude` | `python -m servicenow_mcp.setup_skills claude` |

インストールの確認:

```powershell
python -m servicenow_mcp --version
```

### pip 版でのクライアント設定

変更が必要なのは `command` と `args` だけです。**`env` ブロックは uvx 版とまったく同じ**なので、ステップ 2 の設定をそのままコピーして、先頭の 2 行だけ差し替えてください:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Codex の TOML では `command = "python"` / `args = ["-m", "servicenow_mcp"]` が同等の記述です。

> MCP クライアントが `python` を見つけられない場合は、絶対パスを指定してください（例: `C:/Users/you/AppData/Local/Programs/Python/Python312/python.exe`）。MCP クライアントはシェルの PATH を必ずしも引き継ぎません。

---

## ステップ 2: MCP クライアントを設定する

下記からお使いの MCP クライアント用の設定をコピーします。
`your-instance` を実際の ServiceNow インスタンスアドレスに置き換えてください。

> 以下の例はデフォルトの `uvx` インストールを前提としています。**pip 版（ステップ 1b）では、`command` を `python` に、`args` を `["-m", "servicenow_mcp"]` に置き換えてください** — 後続の `--instance-url` / `--auth-type` などのフラグはそのまま残し、`env` ブロックも記載どおりのままにします。

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

## ステップ 3: スキルをインストールする（任意）

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

> **pip 版（ステップ 1b）ではモジュールとして呼び出してください** — `servicenow-mcp-skills` も、Smart App Control にブロックされる pip 生成の未署名 `.exe` シムです:
>
> ```powershell
> python -m servicenow_mcp.setup_skills claude
> python -m servicenow_mcp.setup_skills codex
> python -m servicenow_mcp.setup_skills opencode
> ```

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

## ステップ 4: 検証する

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

### uvx は見つかるのに何も起動しない / 「blocked by your administrator」 / Windows Update 後に壊れた
→ これはインストールの破損ではなく **Smart App Control** です。uvx は実行のたびに未署名の一時実行ファイルを展開するため、SAC がその実行を拒否します。[ステップ 1b](#ステップ-1b-smart-app-control-が-uvx-をブロックする場合は-pip-でインストールする) の pip 版に切り替えてください。SAC を無効化してはいけません — 一方通行の操作で、元に戻すには Windows の再インストールが必要になります。

### pip インストールは成功したのに `servicenow-mcp` が起動しない
→ pip が生成した `servicenow-mcp.exe` シムを実行しています。これは未署名で、uvx と同様に SAC にブロックされます。代わりにモジュールを呼び出してください: `python -m servicenow_mcp`。MCP クライアント設定も `"command": "python"`、`"args": ["-m", "servicenow_mcp"]` に更新してください。

### 「Python is not installed」
→ **uvx** 版では `uv` が Python 3.11+ を自動的にダウンロードするため、手動インストールは不要です。システムの Python と競合する場合は、`uv` をアンインストールして再インストールしてください。
→ **pip** 版では Python は自分で用意します。[python.org のインストーラー](https://www.python.org/downloads/) から 3.10 以降をインストールし（署名済みなので Smart App Control を通過します）、**「Add python.exe to PATH」** にチェックを入れてください。Microsoft Store 版の Python でも動作します。

### 「Browser won't open」
→ MCP 起動前に Chromium がインストールされている必要があります:
```powershell
uvx --with playwright playwright install chromium   # uvx
python -m playwright install chromium               # pip
```

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
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

pip 版の場合:
```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

いずれの場合も Chromium を同時に更新します。新しい Playwright は新しい Chromium ビルドを前提とするためです。

リフレッシュ後、MCP クライアントを完全に再起動して、新しいバージョンを起動させてください。
