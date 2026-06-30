# MCP クライアント設定

各 MCP クライアントの詳細なセットアップ。すべてのクライアントは同じ MCP サーバーを使用します — 設定フォーマットだけが異なります。

> **まず推奨:** 下記の `uvx` セットアップコマンドを使用してください。企業のセキュリティツールによって `uvx` がブロックされている場合は、リリース zip/exe のセクションを使用してください。

---

## はじめる前に

デフォルトでは `uvx` を使用してください。macOS、Linux、Windows 全体でインストールとクライアント設定の一貫性を保ちます。

### 1. uv をインストールする

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. サーバーを取得し、Chromium をインストールする

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # サーバーの取得と検証
uvx --with playwright playwright install chromium                                   # MFA/SSO ログイン用の Chromium
```

最初のコマンドは、クライアントが使用するのとまったく同じ `--with playwright` 環境でサーバーを事前取得・検証するため、初回起動が即座になります。2 番目のコマンドは Chromium をダウンロードします。`uvx` は標準キャッシュ内に一致する Chromium が既にあれば再利用します。

### 3. サーバーを MCP クライアント設定に追加する

クライアントの設定ファイルにエントリを追加します（インストーラーコマンドは不要）:

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

クライアントごとのファイルパスとフォーマット（Codex TOML など）は下記にあります。設定後はクライアントを再起動してください。

### ローカルインストール（リリース zip/exe）

`uvx` または PyPI がブロックされている場合に使用します。リリース zip は単一の PyInstaller ビルド実行ファイルです — **インストーラースクリプト不要、Python 不要、システムキャッシュを汚しません**。実行ファイルは、自身の隣にある `ms-playwright/` ディレクトリを自動検出します。

**1. ダウンロード。** 実行ファイルは [最新リリース](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest) から、任意の Chromium バンドル（ネットワークが Playwright の Chromium ダウンロードもブロックしている場合のみ）は長期保持されている [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) リリースから取得します。

| プラットフォーム | 必須（最新リリース） | Chromium ダウンロードがブロックされている場合に追加（chromium-bundle リリース） |
|----------|---------------------------|----------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. 配置する。** ユーザーが管理する任意の安定したディレクトリに配置します。**両方の zip を先に展開してください** — `.zip` ファイルを実行ファイルの隣に残さないでください。Chromium zip を展開したフォルダは、名前が `ms-play` で始まり `chromium-*` サブディレクトリを含んでいればよいだけです:

```
~/apps/servicenow-mcp/                                  (任意のディレクトリ)
├── servicenow-mcp                                      ← プラットフォーム zip から（Windows では .exe）
└── ms-playwright-chromium-linux-x64-<ver>/             ← デフォルトの展開名で動作
    └── chromium-1185/
        └── …
```

（よりすっきりした名前にしたい場合は `ms-playwright/` にリネームできます — どちらでも動作します。）起動時、実行ファイルは隣接する `ms-play*` ディレクトリを glob で探し、その中に `chromium-*` サブディレクトリを見つけると、現在のプロセスに限り `PLAYWRIGHT_BROWSERS_PATH` 経由で Playwright をそこへ向けます。システムの Playwright キャッシュには**触れず**、MCP クライアント設定も**変更せず**、ディスク上のどこにも**書き込みません**。

**3. 検証してから、MCP クライアントを接続する:**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

下記の [設定ガイド](#configuration-guide) の MCP 設定スニペットをクライアントの設定ファイルに貼り付け、`command` を実行ファイルの絶対パスに設定します。`env` ブロックは uvx セットアップと同じです — `command` だけが変わります。Chromium を実行ファイルの隣以外の場所に置いた場合は、`env` ブロックに `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` を追加してください。

Chromium zip をスキップし、Playwright の自動ダウンロードがブロックされている場合は、Python のあるマシンでディレクトリを事前準備します:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

自動検出は追加設定なしでそれを拾います。

> Windows ユーザー: ステップごとの詳細とプロキシ/ウイルス対策に関する注意は [Windows インストールガイド](WINDOWS_INSTALL.md) を参照してください。

### クイックテスト

クライアントを設定する前に、サーバーが起動することを確認します:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

サーバーが起動してログイン用のブラウザウィンドウが開けば、下記でクライアントを設定する準備ができています。

---

## 設定ガイド

> **`args` はパッケージ用のみ** — インスタンス URL、認証、クレデンシャルはすべて `env`（または `environment`）に入れます。これにより args がクリーンに保たれ、プロジェクトごとにインスタンスを簡単に切り替えられます。

> **プロジェクトローカル推奨**: 各プロジェクトが異なる ServiceNow インスタンスに接続できるよう、プロジェクトスコープの設定を使用してください。

> **設計上、アクティブなインスタンスは 1 つ**: 通常のツールは 1 つのアクティブな ServiceNow インスタンスにのみルーティングされます。これはリクエスト時の書き込み切り替えを意図的に避けるためで、dev/test/prod 間を移動する際に本番環境への誤った書き込みを引き起こす可能性があるからです。

---

## Streamable HTTP

デフォルトのトランスポートは `stdio` です。リモート MCP クライアントやローカル HTTP ブリッジの場合は、Streamable HTTP でサーバーを起動します:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP エンドポイントは `http://127.0.0.1:8000/mcp` です。`/health` は軽量なステータスレスポンスを返します。サーバーが信頼できるネットワーク制御下にない限り、デフォルトのループバックホストのままにしてください。

---

## 読み取り専用データ比較モード

dev/test のドリフト分析のため、`SERVICENOW_INSTANCE_CONFIG` で名前付きインスタンスを設定できます。このモードは意図的にデータ比較に限定されています:

- 通常のツールは引き続き `SERVICENOW_ACTIVE_INSTANCE` にのみルーティングされます。
- 書き込み可能なツールはインスタンスセレクターを公開しません。
- `compare_instances` は読み取り専用で、エイリアス間でレコードを比較します。
- `list_instances` は設定済みのエイリアスのみを報告します。
- 比較エイリアスは読み取り専用パッケージと `allow_writes=false` で設定してください。
- このモードを環境をまたぐ書き込み作業に使用しないでください。

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev": {
    "url": "https://acme-dev.service-now.com",
    "tool_package": "standard",
    "allow_writes": false
  },
  "test": {
    "url": "https://acme-test.service-now.com",
    "tool_package": "standard",
    "allow_writes": false
  }
}'
```

インスタンスごとのクレデンシャルは、MCP クライアントの `env` ブロック内に記述します（各エイリアスは自身の `username` / `password` / `auth_type` / `api_key` を持てます。`${ENV}` でシークレットを JSON の外に保ちます。単一インスタンスの `SERVICENOW_INSTANCE_URL` 形式も引き続きフォールバックとして機能します）:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mfa-servicenow-mcp@latest"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

比較の例:

```json
{
  "source": "dev",
  "target": "test",
  "table": "sys_script_include",
  "key_field": "api_name",
  "fields": "api_name,name,active,script",
  "query": "sys_scope.scope=x_company_app"
}
```

別のインスタンスに対する実際の作業には、別々のプロジェクト/クライアント設定を使用してください。

---

## Claude Desktop

| スコープ | パス |
|-------|------|
| グローバル | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| グローバル | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

> Claude Desktop はプロジェクトローカル設定をサポートしていません。プロジェクトごとのセットアップには Claude Code を使用してください。

---

## Claude Code

| スコープ | パス |
|-------|------|
| グローバル | `~/.claude.json` |
| プロジェクト | プロジェクトルートの `.mcp.json` |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

---

## Zed

| スコープ | パス |
|-------|------|
| グローバル | `~/.config/zed/settings.json` |

Zed の **Settings** > **MCP Servers** から追加します:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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
```

---

## OpenAI Codex (CLI & App)

**Codex CLI**（`codex` コマンド）と **Codex App**（chatgpt.com/codex）はどちらも同じ `config.toml` から読み込みます。

| スコープ | パス | 備考 |
|-------|------|------|
| グローバル | `~/.codex/config.toml` | 全プロジェクトで共有 |
| プロジェクト | `.codex/config.toml` | グローバルを上書き（信頼できるプロジェクトのみ） |

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
# ログインはホスト間で自動的に共有されます（~/.mfa_servicenow_mcp 配下で
# インスタンス + ユーザーごとにスコープされます）。サンドボックス化された
# ホストが HOME を再マッピングした場合のみ SERVICENOW_BROWSER_USER_DATA_DIR を
# 設定してください — README の「Login sharing」の注記を参照。複数インスタンスを
# 実行する場合は設定しないでください。1 つの Chromium プロファイルにまとめてしまいます。
```

---

## OpenCode

| スコープ | パス |
|-------|------|
| プロジェクト | プロジェクトルートの `opencode.json` |

> OpenCode は `env` ではなく `environment` を使用します。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "enabled": true,
      "environment": {
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

---

## AntiGravity

| スコープ | パス |
|-------|------|
| グローバル | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| グローバル | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> エージェントパネルから編集: **...** > **Manage MCP Servers** > **View raw config**。保存後に **Refresh** をクリックします。

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

---

## Docker (API キーのみ)

> browser 認証（MFA/SSO）には GUI ブラウザが必要で、コンテナ内では動作しません。

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
