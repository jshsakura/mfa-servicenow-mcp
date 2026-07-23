# MFA ServiceNow MCP

🌐 [English](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md) | 🇰🇷 [한국어](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md) | 🇯🇵 [日本語](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ja.md) | 🇮🇳 [हिन्दी](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.hi.md) | 🇨🇳 [简体中文](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.zh.md) | 🇪🇸 [Español](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.es.md) | 🚀 [**GitHub Pages**](https://jshsakura.github.io/mfa-servicenow-mcp/)

MFA を最優先する ServiceNow MCP サーバー。実際のブラウザ（Playwright）経由で認証するため、Okta、Entra ID、SAML、その他あらゆる MFA/SSO ログインがそのまま動作します。ヘッドレス/Docker 環境向けに API Key もサポートします。

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-live-blue?logo=github)](https://jshsakura.github.io/mfa-servicenow-mcp/)

> [!WARNING]
> **個人利用を目的に構築されています — 自己責任でご利用ください。** 本プロジェクトは主に作者自身のワークフローのために作成されました。リスクは積極的に最小化されています（読み取り専用のデフォルト、書き込みガード、ドライラン・プレビュー、すべての書き込みに対する `confirm='approve'` ゲート）が、それでも **稼働中の ServiceNow インスタンス** に対して動作します。あなたのインスタンス上での挙動については、あなた自身が全責任を負います。**いかなる種類の保証もなく「現状のまま」** 提供されます（Apache-2.0、[LICENSE](LICENSE) を参照）。ツールを承認する前に、それが何をするのかを確認してください。

---

## 目次

- [Features](https://github.com/jshsakura/mfa-servicenow-mcp#features)
- [Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup)
- [MCP Client Configuration](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration)
- [Authentication](https://github.com/jshsakura/mfa-servicenow-mcp#authentication)
- [Tool Packages](https://github.com/jshsakura/mfa-servicenow-mcp#tool-packages)
- [CLI Reference](https://github.com/jshsakura/mfa-servicenow-mcp#cli-reference)
- [Keeping Up to Date](https://github.com/jshsakura/mfa-servicenow-mcp#keeping-up-to-date)
- [Safety Policy](https://github.com/jshsakura/mfa-servicenow-mcp#safety-policy)
- [Performance Optimizations](https://github.com/jshsakura/mfa-servicenow-mcp#performance-optimizations)
- [Local Source Audit](https://github.com/jshsakura/mfa-servicenow-mcp#local-source-audit)
- [Skills](https://github.com/jshsakura/mfa-servicenow-mcp#skills)
- [Docker](https://github.com/jshsakura/mfa-servicenow-mcp#docker)
- [Developer Setup](https://github.com/jshsakura/mfa-servicenow-mcp#developer-setup)
- [Documentation](https://github.com/jshsakura/mfa-servicenow-mcp#documentation)
- [Related Projects](https://github.com/jshsakura/mfa-servicenow-mcp#related-projects-and-acknowledgements)
- [License](https://github.com/jshsakura/mfa-servicenow-mcp#license)

---

## Setup

2 ステップです。**インストール** し、次に **MCP クライアントの設定にサーバーを追加** します。インストーラーコマンドも、クライアントごとのフラグも不要です。

### 1. インストール

デフォルトは **`uvx`** です。別途インストール手順は不要で、そのまま実行できます。ほとんどの方はこれで話が終わります。

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

**更新するとき** — uvx は最後にダウンロードしたバージョンをキャッシュして再利用し続けるため、新しいリリースは `--refresh` で明示的に引き寄せる必要があります:

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium     # Playwright が上がると新しい Chromium ビルドが必要になります
```

#### uvx がブロックされる場合 — `pip`

Windows の Smart App Control が有効だと、uvx はそもそも起動できません。uvx は実行のたびに署名のない一時実行ファイルを展開するため、SAC がそれをブロックします。Windows Update の直後に突然 uvx が動かなくなった場合、原因はほぼこれです。そのときは pip を使ってください:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**更新するとき:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

[python.org のインストーラー](https://www.python.org/downloads/)（署名済み、3.10 以上）で入れた Python なら、そのまま SAC を通過します。起動には `servicenow-mcp` コンソールスクリプトではなく `python -m servicenow_mcp` を使ってください — コンソールスクリプトは pip が生成する署名のない `.exe` ラッパーで、これも SAC にブロックされます。

> mac/Linux で pip を使う場合の唯一の注意点は、Homebrew やディストリビューション付属の Python が [PEP 668](https://peps.python.org/pep-0668/) によりグローバルインストールを拒否すること（`externally-managed-environment`）です。python.org のインストーラーを使うか、素直に uvx にとどまってください。

どちらの経路でも、Chromium を **先に** インストールしておくことが重要です。最初のツール呼び出しまで先送りすると、約 150 MB のダウンロードが MCP ホストのハンドシェイク期限と競合し、`connection closed` として表面化します。

> **ガイド付きセットアップ。** フラグなしで `servicenow-mcp setup`（pip の場合は `python -m servicenow_mcp setup`）を実行すると、番号付きメニューでガイドされます（クライアントと認証タイプを番号または名前で選択 — 自由入力の推測は不要）。英語または韓国語に対応します（ロケールから自動検出。`SERVICENOW_MCP_LANG=ko|en` で強制可能）。

### 2. MCP クライアントの設定

クライアントの設定ファイルにサーバーを追加します。**`env` ブロックはインストール方法によらず同一** で、上で選んだ経路に合わせるのは `command` / `args` だけです:

| インストール | `command` | `args` |
|---|---|---|
| uvx（デフォルト） | `uvx` | `["--with","playwright","--from","mfa-servicenow-mcp","servicenow-mcp"]` |
| pip | `python` | `["-m","servicenow_mcp"]` |

必須の環境変数は 2 つだけです。`MCP_TOOL_PACKAGE` はデフォルトで `standard` になるため、別のパッケージが必要でない限り省略してください。

#### 単一インスタンス

インスタンスが 1 つだけなら、これで完了です。

**Claude Code** — `.mcp.json`（プロジェクトルート）/ `~/.claude.json`（グローバル）:

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

pip でインストールした場合は `command` / `args` をこう差し替えるだけです — 残りはそのままです:

```json
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
```

**Codex** — `.codex/config.toml`（プロジェクト）/ `~/.codex/config.toml`（グローバル）:

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
# pip: command = "python"  /  args = ["-m", "servicenow_mcp"]

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
```

**OpenCode** — `opencode.json`（プロジェクトルート）:

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
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

その他のクライアント（Cursor、VS Code、Antigravity、Zed など）と完全な環境変数オプション（認証タイプ、ツールパッケージ）は [MCP Client Configuration](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration) にあります。

その後、クライアントを再起動してください。最初のブラウザツール呼び出しで、Okta/Entra ID/SAML/MFA ログイン用のウィンドウが開きます。セッションは永続化されます — 毎回再ログインする必要はありません。

#### マルチインスタンス（dev / test / prod）

dev / test / prod をまとめて扱うなら、**サーバーを複数立ち上げないでください。** `env` を変えるだけで、1 つの接続からすべて操作できます:

```json
      "env": {
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"prod\": { \"url\": \"https://acme.service-now.com\", \"auth_type\": \"browser\" } }"
      }
```

`SERVICENOW_INSTANCE_URL` の位置に alias のリストが入るだけで、`command` / `args` はそのままです。これにより:

- **本番の保護がデフォルト** — `allow_writes` を与えていない alias は読み取り専用です。上の例の `prod` には一切書き込めません。
- **再起動なしで別インスタンスを参照** — `sn_query(instance="prod", ...)` のように、読み取り系ツールに `instance` を渡すだけです。
- **インスタンス間の比較** — `compare_instances` で dev と prod の同じコンポーネントを直接突き合わせられます。
- **ログインは 1 回** — ブラウザセッションを alias 間で共有します。

完全なルール（書き込みルーティング、ゲート、`${ENV}` 参照）は [複数のインスタンス（dev / test / prod）— 2 つのアプローチ](#プロファイル-vs-マルチプロセス) にあります。クライアントの画面上で接続を見た目から分けたい場合にだけ、そこの **B. マルチプロセス** を参照してください。

> AI に任せたいですか？ Claude Code / Cursor / Codex などに以下を貼り付けてください:
> `Install and configure mfa-servicenow-mcp following https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md`

### 企業ネットワークにインストールを阻まれる場合

TLS インスペクションを行うプロキシ（Zscaler など）や PyPI 自体がブロックされている環境には別の経路があります — [Install (offline / corporate)](#install-offline--corporate) を参照してください。

---

## Features

- MFA/SSO 環境向けの **ブラウザ認証**（Okta、Entra ID、SAML、MFA）
- **4 つの認証モード**: Browser、Basic、OAuth、API Key
- **66 個の登録済みツール** と **6 つのアクティブなパッケージプロファイル**、加えて無効化用の `none` — 最小限の読み取り専用から幅広いバンドル CRUD まで
- 安全ゲート、サブエージェント委譲、検証済みパイプラインを備えた **4 個のワークフロースキル**
- **Streamable HTTP トランスポート** — デフォルトとして stdio を維持しつつ、HTTP 対応クライアントやブリッジ向けに `/mcp` を公開可能
- HTML レポート、相互参照グラフ、デッドコード検出、自動生成されるドメイン知識を備えた **ローカルソース監査**
- **ディスク上の信頼できる関係グラフ** — `_graph.json`（widget→Angular Provider、ライブ M2M 由来）と `_page_graph.json`（page→widget、`sp_instance` 由来）により、LLM はインスタンスへ再クエリすることなくオフラインで依存関係の質問に答えられます
- **増分同期**（`incremental=True`）— 前回の同期以降に変更されたレコードのみを再ダウンロード（`sys_updated_on` ウォーターマーク）。`git pull` のように動作します。`reconcile_deletions=True` はインスタンス上で削除されたレコードをフラグ付けします
- `download_app_sources` における **スコープ横断の依存関係自動解決** — アプリが参照する global スコープの Script Include、Widget、Angular Provider、UI Macro を取得し、ローカルバンドルを分析用に自己完結させます
- **添付ファイルのダウンロード**（`download_attachment`）— レコードの添付ファイル（xlsx、PDF、Word など）を、添付ファイルの sys_id または親の `table`+`record` 指定でローカルディスクに取得します。レコードの添付ファイルを自動的に解決してバイト列をディスクに書き込むため、LLM は `saved_path` から読み取れます
- すべての書き込みツールでの **ドライラン・プレビュー**（`dry_run=True`）— 副作用が発生する前に、フィールド単位の差分、依存関係の数、精度に関する注記を返します。読み取り専用 API を使用し、すべての認証モードで動作します。
- `confirm='approve'` による安全な書き込み確認
- ペイロードの安全上限、フィールド単位の切り詰め、レスポンス全体の予算（200K 文字）
- 一時的なネットワークエラーに対するバックオフ付きリトライ
- core、standard、service desk、portal developer、platform developer 向けのツールパッケージ — 上級ユーザー向けに `full` も利用可能（[warning](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md) を参照）
- 開発者の生産性ツール: アクティビティ追跡、未コミットの変更、依存関係マッピング、日次サマリー
- ServiceNow のコアなアーティファクトテーブルの完全なカバレッジ（[Supported Tables](https://github.com/jshsakura/mfa-servicenow-mcp#supported-servicenow-tables) を参照）
- 自動タグ付け、PyPI への公開、Docker マルチプラットフォームビルドを備えた CI/CD

### Supported ServiceNow Tables

| Artifact Type | Table Name | Source Search | Developer Tracking | Safety (Heavy Table) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_script_client` | ✅ | ✅ | 🛡️ |
| Catalog Client Script | `catalog_script_client` | ✅ | ⬜ | ⬜ |
| UI Action | `sys_ui_action` | ✅ | ✅ | 🛡️ |
| UI Script | `sys_ui_script` | ✅ | ✅ | 🛡️ |
| UI Page | `sys_ui_page` | ✅ | ✅ | 🛡️ |
| UI Macro | `sys_ui_macro` | ✅ | ⬜ | 🛡️ |
| Scripted REST API | `sys_ws_operation` | ✅ | ✅ | 🛡️ |
| Fix Script | `sys_script_fix` | ✅ | ✅ | 🛡️ |
| Scheduled Job | `sysauto_script` | ✅ | ⬜ | ⬜ |
| Script Action | `sysevent_script_action` | ✅ | ⬜ | ⬜ |
| Email Notification | `sysevent_email_action` | ✅ | ⬜ | ⬜ |
| ACL | `sys_security_acl` | ✅ | ⬜ | ⬜ |
| Transform Script | `sys_transform_script` | ✅ | ⬜ | ⬜ |
| Processor | `sys_processor` | ✅ | ⬜ | ⬜ |
| Service Portal Widget | `sp_widget` | ✅ | ✅ | 🛡️ |
| Angular Provider | `sp_angular_provider` | ✅ | ✅ | ⬜ |
| Portal Header/Footer | `sp_header_footer` | ✅ | ⬜ | ⬜ |
| Portal CSS | `sp_css` | ✅ | ⬜ | ⬜ |
| Angular Template | `sp_ng_template` | ✅ | ⬜ | ⬜ |
| Metadata / XML Definitions | `sys_metadata` | ✅ | ⬜ | 🛡️ |
| Update XML | `sys_update_xml` | ✅ | ⬜ | ⬜ |

---

## Install (offline / corporate)

ほとんどのユーザーにとって、上記の [Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) だけで十分です。企業ネットワークで押さえておきたいケースが 2 つあります。

よくあるのは **PyPI には到達できるが、HTTPS が TLS インスペクションされている**（Zscaler / Netskope / 企業 MITM）ケースで、すぐ下のセクションがこれを扱います。

PyPI 自体が完全にブロックされている場合、uvx も pip もパッケージに到達できません。情報システム部門に `pypi.org` と `files.pythonhosted.org` の許可リスト登録を依頼するか、`pip install --index-url` で指定できる社内インデックスにパッケージをミラーしてもらってください。

### TLS インスペクションを行うプロキシ配下でのインストール（Zscaler など）

PyPI には **到達できる** ものの、TLS インスペクションを行うプロキシが HTTPS を再署名するためインストールやランタイム呼び出しが `SSL: CERTIFICATE_VERIFY_FAILED` で失敗する場合に、これを使用します。プロキシのルート CA を **OS のトラストストアに登録するだけでは不十分** です — Python（`pip`、`requests`、`httpx`）、`curl_cffi`、Playwright はそれぞれ独自の CA バンドル（certifi / libcurl / node）を同梱しており、環境変数で証明書を指し示さない限り OS ストアを無視します。

**1. プロキシのルート CA を PEM ファイルとして入手** します（IT に依頼するか、OS のキーチェーンからエクスポート）。`/etc/ssl/zscaler-root.pem`（Windows: `C:\certs\zscaler-root.pem`）に配置されると仮定します。

**2. インストール** — インストーラーに証明書を指定します:

```bash
pip install --cert /etc/ssl/zscaler-root.pem mfa-servicenow-mcp
python -m playwright install chromium     # NODE_EXTRA_CA_CERTS (step 3) covers its download
```

uvx を好みますか？ `uv` は OS のトラストストア（プロキシ CA が既に登録済みの場所）を直接使用できます:

```bash
UV_NATIVE_TLS=1 uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
```

**3. ランタイム — MCP クライアントの `env` に CA パスを設定します。** わかりにくい点: 稼働中の ServiceNow 呼び出しは **curl_cffi（libcurl）** を経由し、これは `REQUESTS_CA_BUNDLE` *ではなく* `CURL_CA_BUNDLE` を読み取ります。すべてのレイヤーがプロキシを信頼するよう、これらをすべて設定してください:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "CURL_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "REQUESTS_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "SSL_CERT_FILE": "/etc/ssl/zscaler-root.pem",
        "NODE_EXTRA_CA_CERTS": "/etc/ssl/zscaler-root.pem"
      }
    }
  }
}
```

| Env var | Layer it fixes |
|---------|----------------|
| `CURL_CA_BUNDLE` | **curl_cffi / libcurl — 実際の ServiceNow API + ブラウザログインのプローブ呼び出し** |
| `REQUESTS_CA_BUNDLE` | `requests`（OAuth / API キーのトークン呼び出し、フォールバック HTTP パス） |
| `SSL_CERT_FILE` | Python 標準ライブラリの `ssl` / `httpx` / `uv` |
| `NODE_EXTRA_CA_CERTS` | Playwright の Chromium ダウンロード |
| `PIP_CERT`（インストール時のみ） | PyPI から取得する `pip`（`--cert` と同じ） |

完全にインスペクションされたネットワークでは、プロキシがすべてのホストを再署名するため、単一のプロキシルート PEM ですべての HTTPS をカバーできます。一部のホストがプロキシを **バイパス** する場合は、プロキシルートと certifi のバンドル（`python -m certifi` がパスを表示します）を 1 つの PEM に連結し、環境変数をそれに向けてください。

> どうしても PEM を入手できない場合の最終手段: `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org mfa-servicenow-mcp` は **インストールのみ** で検証をスキップします — ランタイムの ServiceNow 呼び出しには何の効果もなく、それらは依然として `CURL_CA_BUNDLE` を必要とします。証明書パスを優先してください。`--trusted-host` はセキュリティ制御を無効化します。

## MCP Client Configuration

> 推奨: 上記の [Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) を使用してください。クライアント設定ファイルを確認、修復、または手動管理する必要がある場合に、下記のコピー＆ペースト設定を使用してください。

各プロジェクトは異なる ServiceNow インスタンスに接続できます。各プロジェクトが独自のインスタンス URL と認証情報を持てるよう、設定は **プロジェクトディレクトリ** に置いてください。

| Client | Project Config | Global Config | Format |
|--------|---------------|--------------|--------|
| Claude Code | `.mcp.json` | `~/.claude.json` | JSON |
| Cursor | `.cursor/mcp.json` | *Project only* | JSON |
| VS Code (Copilot) | `.vscode/mcp.json` | *Project only* | JSON |
| Zed | *Global only* | `~/.config/zed/settings.json` | JSON |
| OpenAI Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML |
| OpenCode | `opencode.json` | *Project only* | JSON |
| Windsurf | *Global only* | `~/.codeium/windsurf/mcp_config.json` | JSON |
| Claude Desktop | *Global only* | `claude_desktop_config.json` | JSON |
| AntiGravity | *Global only* | `~/.gemini/antigravity/mcp_config.json` | JSON |
| Docker | *Env vars only* | *Env vars only* | Env vars |

各クライアントのコピー＆ペースト設定: **[Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` は任意です — MFA ログインフォームを事前入力します。Windows では、これらをシステム環境変数として設定してください。

#### プロファイル vs マルチプロセス

上記の例は単一インスタンスです — それがデフォルトのままです。インスタンスが 2 つ以上ある場合は進め方が 2 通りあり、**設定を書き始める前にどちらかを決めておく価値があります:**

| | **A. プロファイル**（推奨） | **B. マルチプロセス** |
|---|---|---|
| サーバープロセス | 1 つ | インスタンスごとに 1 つ |
| クライアントから見える接続 | 1 つ | 3 つ |
| インスタンスの選択 | 呼び出しごとに `instance="test"` | プロセスに固定 |
| インスタンス間の比較 | **可能**（`compare_instances`） | 不可 — プロセス同士は互いを知りません |
| ブラウザログイン | 1 つのセッションを共有 | プロセスごとに 1 回ログイン |
| 書き込みの制御 | エイリアスごとの `allow_writes` | プロセスごとの設定 |

**ほとんどの方には A が向いています。** 書き込みの安全性は A で既に解決済みです — prod のエイリアスで `allow_writes` を省けば読み取り専用になり、非アクティブなインスタンスへの書き込みは `confirm_instance` ゲートを通過する必要があります。さらに、インスタンス間の比較とログイン 1 回で済むのは A だけです。

**B を選ぶのは、クライアントの UI 上で接続が目に見えて分かれている必要がある場合だけです。** ツール名が `mcp_snow-prd_*` として現れるため、人間が一目で見分けられます。その代償はログイン 3 回、比較不可、設定 3 つ分です。詳細: [複数の接続を見分ける](#複数の接続を見分ける--server-name)。

##### A. プロファイル

1 つのクライアントから複数のインスタンスを切り替えるには、`SERVICENOW_INSTANCE_CONFIG`（エイリアス → 設定）にそれらを列挙し、`SERVICENOW_ACTIVE_INSTANCE` でアクティブなものを選びます。各エイリアスは **独自の認証情報**（`username` / `password` / `auth_type` / `api_key`）を持てます。`${ENV}` 参照によってシークレットを JSON の外に保てます。単一インスタンスの `SERVICENOW_INSTANCE_URL` 形式も引き続きフォールバックとして動作します。

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

`SERVICENOW_ACTIVE_INSTANCE` は書き込みのデフォルト先です。読み取りツールは `instance="test"` で他のインスタンスを覗け、単一の書き込みは `instance="test" confirm_instance="test" confirm="approve"` で非アクティブなインスタンスにルーティングできます（ガード付きで、反映後に検証されます）。完全なルール（書き込みルーティング、ゲーティング、比較、`${ENV}`）: [マルチインスタンスモード](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ja.md#マルチインスタンスモード比較--ガード付き単一呼び出し書き込み)。

##### B. マルチプロセス

クライアントの UI 上で接続を分けて見せたい場合にのみ意味があります。各エントリが **インスタンスを 1 つ固定** し、`--server-name` で独自の名前を持ちます:

```json
{
  "mcpServers": {
    "snow-dev": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-dev"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme-dev.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    },
    "snow-prd": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-prd"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

これでツール名が `mcp_snow-dev_*` / `mcp_snow-prd_*` に固定されます。`--server-name` を外すと双方が `ServiceNow` として名乗るため、クライアントはロード順で番号を振ります（`mcp_servicenow`、`mcp_servicenow2`）— そしてこの番号は再起動のたびに入れ替わりうるので、どちらが本番なのかを決して信用できません。

本番の接続を読み取り専用に保つには、読み取り専用の `MCP_TOOL_PACKAGE` を与えてください。A とは違い、ここには `allow_writes` によるエイリアスのゲートがありません — **書き込みを止めているのはツールパッケージだけです。**

> ログインのプロンプトはプロセスごとに立ち上がり、`compare_instances` のようなインスタンス横断ツールは使えません — 各プロセスは自分のインスタンスしか知らないためです。それが問題になるなら A を選んでください。

---

## Authentication

ServiceNow 環境に応じて認証モードを選択してください。

### Browser Auth (MFA/SSO) — Default

[Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) コマンドはデフォルトでブラウザ認証を使用します。任意のフラグ:

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | ログインフォームのユーザー名を事前入力 |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | ログインフォームのパスワードを事前入力 |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | GUI なしでブラウザを実行 |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | ログインのタイムアウト（秒） |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | セッションの TTL（分） |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Chromium プロファイルのパスを上書きします。ほとんど不要 — 設定する前に下記のサンドボックスに関する注記を参照してください。 |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | ユーザー名が判明している場合はユーザー固有の `sys_user` ルックアップ、そうでない場合は `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | セッション検証エンドポイント（非管理者セッションでの 401 を回避） |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | カスタムログインページの URL |

#### ホストとインスタンスをまたいだログイン共有 — 実際の仕組み

サーバーは `~/.mfa_servicenow_mcp/` 配下に 2 つのものをキャッシュします: Playwright プロファイル（Chromium の SSO クッキー）と、セッション JSON（次回起動時に再利用される解析済みクッキー）です。どちらも **インスタンス + ユーザー名ごとにスコープ** されており、ファイルは `profile_<host>_<user>` および `session_<host>_<user>.json` という名前になります。

このスコープ付けにより、**設定なしで** 自動的に 2 つのことが実現されます:

- **複数のホストが 1 つのログインを共有する。** 同じマシン上の Claude Code と Codex はどちらも `~/.mfa_servicenow_mcp/` を解決するため、先にログインした方がセッションを書き込み、もう一方がそれを再利用します — 2 度目の MFA プロンプトはありません。
- **異なるインスタンス / 異なる認証情報は分離されたまま。** 各インスタンス + ユーザーは独自のプロファイルとセッションファイルを持つため、dev と test（または 2 つのアカウント）が衝突することはありません。複数のインスタンスの場合は `SERVICENOW_INSTANCE_CONFIG`（JSON）で設定してください — 各エイリアスが独自のスコープ付きキャッシュを持ち、プロファイルパスで管理する必要は **ありません**。

**ログインを「共有」するために `SERVICENOW_BROWSER_USER_DATA_DIR` を設定しないでください。** これはプロファイルパスをそのまま上書きします — インスタンスごとのスコープ付けがバイパスされ、実行するすべてのインスタンスが 1 つの Chromium プロファイルに強制され、それらのクッキーが衝突します。唯一の正当な用途は限定的なものです: `HOME` をコンテナパスに再マップする **サンドボックス化された** ホスト（例: macOS の Claude Desktop）で、その `~/.mfa_servicenow_mcp/` がターミナルのものと一致しなくなる場合です。その単一インスタンスのケースでは、サンドボックス化されたホストを実際のホームパスに向けてください:

```bash
# Only when a sandbox remapped HOME, and only for a single-instance host
export SERVICENOW_BROWSER_USER_DATA_DIR="/Users/you/.mfa_servicenow_mcp/profile_acme"
```

複数のインスタンスを実行する場合は、これを未設定のままにして、インスタンスごとのスコープ付けに仕事をさせてください。

### Basic Auth

PDI や MFA のないインスタンスに使用します。

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth

現在の CLI サポートは OAuth password grant の入力を想定しています。

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

`--token-url` を省略すると、サーバーはデフォルトで `https://<instance>/oauth_token.do` を使用します。

### API Key

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

デフォルトヘッダー: `X-ServiceNow-API-Key`（`--api-key-header` でカスタマイズ可能）。

---

## Tool Packages

`MCP_TOOL_PACKAGE` は、サーバーが公開するツールを制御します。**デフォルト: `standard`** — ほとんどのユーザーは設定不要です。

> [!WARNING]
> **`standard` より上のパッケージはいずれも書き込みアクセスを付与する上級者向けオプションです。** `service_desk`、`portal_developer`、`platform_developer`、`full` はすべて、AI エージェントがレコードを作成・更新・削除できるようにします — `full` はすべてのドメインに対して一度にそれを行います。ほとんどのユーザーは読み取り専用のデフォルト `standard` にとどまり、タスクが実際に必要とする最も狭い書き込みパッケージにのみ引き上げるべきです。

読み取り専用（安全なデフォルト）:

| Package | Tools | ~トークン | Description |
| :--- | :---: | :---: | :--- |
| `none` | 0 | 0 | 意図的にツールをオフにするための無効化プロファイル |
| `core` | 12 | ~3.0K | ヘルス、スキーマ、ディスカバリ、主要アーティファクトのルックアップ向けの最小限の読み取り専用エッセンシャル |
| `standard` | 29 | ~7.3K | **（デフォルト）** インシデント、変更、ポータル、ログ、ソース分析にまたがる読み取り専用 |

⚠️ 書き込み可能（上級者向け — 作成/更新/削除を付与）:

| Package | Tools | ~トークン | Description |
| :--- | :---: | :---: | :--- |
| `service_desk` | 31 | ~8.2K | ⚠️ standard + インシデントと変更の運用書き込み |
| `portal_developer` | 41 | ~10.6K | ⚠️ standard + ポータル、changeset、script include、ローカル同期配信の書き込み |
| `platform_developer` | 41 | ~10.8K | ⚠️ standard + ワークフロー、Flow Designer、UI policy、インシデント/変更、スクリプトの書き込み |
| `full` | 55 | ~13.8K | ⚠️ **最も高度** — すべてのドメインにまたがるすべての書き込みツールを一度に |

> **~トークン** = リクエストごとに各パッケージのツールスキーマがモデルのコンテキストに追加する概算トークン数（tiktoken cl100k_base 基準、実際の Claude のトークン数は多少異なる）。狭いパッケージほどコンテキストとコストを節約。

各サーバープロセスは、通常のツールに対しては 1 つのアクティブな ServiceNow インスタンスにバインドされます。*別の* 設定済みインスタンスへの書き込みは呼び出しごとに可能ですが、明示的でガード付きの承認（下記）を通じてのみ行われます — 決して黙って切り替わることはありません。

### マルチインスタンスモード（比較 + ガード付き単一呼び出し書き込み）

dev/test/prod を比較したり、選んだインスタンスにデプロイしたりする必要がある場合、`SERVICENOW_INSTANCE_CONFIG` で名前付きインスタンスをオプトインします。`SERVICENOW_ACTIVE_INSTANCE` は引き続き必須です。

2 つはグローバル、1 つはインスタンスごとです:

- **ツールの面はグローバル** — `MCP_TOOL_PACKAGE` で一度設定します。サーバープロセスごとにアクティブなインスタンスは常に 1 つだけなので、インスタンスごとのツールパッケージはありません。
- **書き込み権限はインスタンスごと** — 各エイリアスが `allow_writes` を持ちます。これは呼び出し時にアクティブなインスタンスに対して強制されます: 書き込みツールはロードできても、アクティブなインスタンスが `allow_writes: false` であれば拒否されます。書き込みはオプトインです: `allow_writes` を省略するとインスタンスは読み取り専用になります。
- **認証情報はインスタンスごと、グローバルフォールバックあり** — エイリアスに `username` / `password` / `api_key`（および `auth_type`）を付けて上書きします。省略すると、エイリアスはグローバルな `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` などを継承します。したがって、すべてのインスタンスが 1 つのログインを共有する場合は、グローバルに一度設定し、エイリアスのエントリは認証情報なしのままにしてください。

その他のルール:

- **読み取りツールは `instance` 引数を受け付け**、非アクティブなインスタンスに対して 1 回の読み取りを実行します — 例: `dev` がアクティブなまま `sn_query(instance="test", table="incident", ...)` や `sn_health(instance="test")`。パッケージ内のすべての読み取りツールがそのスキーマでこれを公開します（設定済みエイリアスの列挙）。これが、再起動せずに別のインスタンスのデータを覗く方法です。
- **単一の書き込みも非アクティブなインスタンスにルーティングできます**が、決して黙ってではありません。`instance="test" confirm_instance="test" confirm="approve"`（意図と承認としてターゲットを 2 回指定）を渡し、ターゲットが `allow_writes=true` である必要があります。その 1 回の書き込みだけがそこへ向かい、直後にアクティブなインスタンスが復元されます。ターゲット/confirm の不一致や読み取り専用ターゲットは明示的なメッセージで拒否されるため、dev/test/prod が入り混じっても誤ったインスタンスに書き込まれることはありません。その後、ターゲット上で書き込みを再読み取りし、`landed`（または `WRITE_NOT_LANDED`）として報告し、`target_instance` をエコーします — 「成功」とは 200 が返ったことではなく、**意図したインスタンスに内容が実在することが確認された**という意味です。
- `list_instances` は設定済みエイリアスとアクティブなもの、そして各インスタンスの書き込みフラグを報告します。`compare_instances` はエイリアスをまたいだ読み取り専用のテーブル比較を実行します。
- *デフォルトの* アクティブなインスタンスの切り替えには MCP クライアントの再起動が必要です — サーバー起動時に一度読み込まれ、ライブでは更新されません。（上記の呼び出しごとの `instance=` ルーティングには再起動は不要です。）

例 — 共有グローバルログイン、インスタンスごとの書き込みゲーティング:

```bash
export MCP_TOOL_PACKAGE=standard
export SERVICENOW_USERNAME=svc_account
export SERVICENOW_PASSWORD='...'
export SERVICENOW_ACTIVE_INSTANCE=dev
export SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "allow_writes": false }
}'
```

インスタンスに独自のログインを持たせるには、そのエイリアスにフィールドを追加してください（`${ENV}` 参照は解決されるため、シークレットを JSON の外に保てます）:

```json
"prod": { "url": "https://acme.service-now.com", "username": "prod_user", "password": "${SERVICENOW_PROD_PASSWORD}" }
```

dev/test のドリフトチェックには `compare_instances` を使用してください。**多数の** レコードを昇格させる場合（特に Service Portal / scoped テーブル）は、レコードごとのインスタンス横断書き込みよりも Update Set（ソースで commit → ターゲットの UI で retrieve + commit）を推奨します — 単一の Table-API 書き込みが引っかかる per-table/SP ACL を回避できます。

現在のパッケージでツールが利用できない場合、サーバーはどのパッケージにそれが含まれているかを教えてくれます。

完全なリファレンス（すべてのパッケージ、継承の詳細、設定構文）: [Tool Packages Advanced Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md)。

---

## CLI Reference

### Server Options

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *required* | ServiceNow インスタンス URL |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | 認証モード: `basic`、`oauth`、`api_key`、`browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | ロードするツールパッケージ |
| `--server-name` | `SERVICENOW_MCP_SERVER_NAME` | `ServiceNow` | クライアントに公表する MCP サーバー名 |
| `--transport` | `SERVICENOW_MCP_TRANSPORT` | `stdio` | MCP トランスポート: `stdio` または `http` |
| `--http-host` | `SERVICENOW_MCP_HTTP_HOST` | `127.0.0.1` | `--transport http` 用のホスト |
| `--http-port` | `SERVICENOW_MCP_HTTP_PORT` | `8000` | `--transport http` 用のポート |
| `--http-path` | `SERVICENOW_MCP_HTTP_PATH` | `/mcp` | Streamable HTTP エンドポイントのパス |
| `--http-allowed-hosts` | `SERVICENOW_MCP_HTTP_ALLOWED_HOSTS` | loopback hosts | DNS リバインディング保護用のカンマ区切り Host 許可リスト |
| `--http-disable-dns-rebinding-protection` | `SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | 信頼できるネットワーク制御下で DNS リバインディング保護を無効化 |
| `--http-json-response` | `SERVICENOW_MCP_HTTP_JSON_RESPONSE` | `false` | SSE ストリームの代わりに JSON レスポンスを返す |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP リクエストのタイムアウト（秒） |
| `--debug` | `SERVICENOW_DEBUG` | `false` | デバッグログを有効化 |

HTTP トランスポートの例:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP エンドポイントは `http://127.0.0.1:8000/mcp` です。`/health` は軽量なヘルスレスポンスを返します。

#### 複数の接続を見分ける（`--server-name`）

1 つのクライアントに **複数のサーバーエントリ** を登録する場合（dev / stg / prd を別々のプロセスとして）、すべてがデフォルトで `ServiceNow` という名前になるため、クライアントはロード順で区別します — `mcp_servicenow`、`mcp_servicenow2`、`mcp_servicenow3`。この番号は再起動のたびに変わりうるので、**どれが本番かを判断する材料としては信用できません。** 接続ごとに名前を付けてください:

```bash
servicenow-mcp --server-name snow-prd          # uvx / コンソールスクリプト
python -m servicenow_mcp --server-name snow-prd # pip
```

これでツールの名前空間が `mcp_snow-prd_*` に固定されます。環境変数 `SERVICENOW_MCP_SERVER_NAME` でも同じことができ、両方指定した場合はフラグが優先します。未設定なら `ServiceNow` のままなので、既存の設定はそのまま動作します。

> **1 つの** サーバーの中でインスタンスを切り替えたい場合は、これではなく [マルチインスタンスモード](#マルチインスタンスモード比較--ガード付き単一呼び出し書き込み) です。両者は無関係です — `--server-name` はクライアントから見える名前であり、マルチインスタンスのエイリアスは 1 つのプロセス内でインスタンスを指す名前です。

### Basic Auth

| Flag | Env Variable |
|------|-------------|
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### OAuth

| Flag | Env Variable |
|------|-------------|
| `--client-id` | `SERVICENOW_CLIENT_ID` |
| `--client-secret` | `SERVICENOW_CLIENT_SECRET` |
| `--token-url` | `SERVICENOW_TOKEN_URL` |
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### API Key

| Flag | Env Variable | Default |
|------|-------------|---------|
| `--api-key` | `SERVICENOW_API_KEY` | — |
| `--api-key-header` | `SERVICENOW_API_KEY_HEADER` | `X-ServiceNow-API-Key` |

### Script Execution

| Flag | Env Variable |
|------|-------------|
| `--script-execution-api-resource-path` | `SCRIPT_EXECUTION_API_RESOURCE_PATH` |

---

## Keeping Up to Date

インストールした方法に合うものを選んでください（同じコマンドは [インストールのセクション](#1-インストール) にもあります）:

```bash
# uvx — 最後にダウンロードしたバージョンをキャッシュするため、新しいものは --refresh で引き寄せます
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

```powershell
# pip
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

どちらの場合も Chromium を併せて更新するのは、Playwright が上がると異なる Chromium ビルドを要求するためです（下記参照）。

リフレッシュ後、新しいバージョンを読み込むために **MCP クライアント**（Claude Code、Cursor など）を再起動してください。

現在のバージョンの確認:

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp --version   # uvx
python -m servicenow_mcp --version                       # pip
```

### なぜ Chromium を先にインストールする必要があるのか

新しい Playwright リリースは異なる Chromium ビルドを要求します。放置すると *最初の* ブラウザツール呼び出しで約 150 MB のブラウザバイナリを取得することになり、低速な回線では MCP ホストのハンドシェイクタイムアウトを超えて、次のように表面化します:

```text
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

上記のアップグレードコマンドが毎回 `playwright install chromium` を実行しているのはそのためです。

> **なぜ MCP サーバー内で Chromium を自動インストールしなくなったのか:** そのダウンロードは以前、最初のツール呼び出し中に実行されていました。低速な回線ではサブプロセスがホストのハンドシェイク期限を超え、クライアントが「connection closed」と報告していました。v1.13.1 でこれが変更されました — MCP サーバーは Chromium がない場合に *警告するだけ* になりました。事前にインストールしてください（帯域外、ハンドシェイクタイマーなし）。

---

## Safety Policy

すべての変更系ツールは明示的な確認によって保護されています。

ルール:
1. `create_`、`update_`、`delete_`、`remove_`、`add_`、`move_`、`activate_`、`deactivate_`、`commit_`、`publish_`、`submit_`、`approve_`、`reject_`、`resolve_`、`reorder_`、`execute_` などの接頭辞を持つ変更系ツールには確認が必要です。
2. `confirm='approve'` を渡す必要があります。
3. そのパラメータがなければ、サーバーは実行前にリクエストを拒否します。

このポリシーは、選択されたツールパッケージに関係なく適用されます。

### Write Guards

confirm ゲートに加えて、すべての書き込みは決定論的なガードを通過し、安全でない書き込みが ServiceNow に到達する *前* にブロックします。同時編集と重複作成のチェックは confirm ゲートの **後** に実行されるため、未確認の書き込みがネットワークに触れることは決してありません。各ガードは、拒否/失敗した事前読み取りに対して **フェイルオープン** します — 先に確認できなかったというだけで正当な書き込みをブロックすることはありません。意図はシンプルです: **チームメイトの変更を黙って上書きできてはならない** — 他の誰かがレコードに触れていた場合、書き込みは停止してそれを通知し、上書きして進むことはありません。

| Guard | Protects against | Override / toggle |
|---|---|---|
| 同時編集 (G3/G8) | 直近 10 分以内に **別のユーザー** が編集したレコードを盲目的に上書きすること。`sn_write`、`manage_portal_component`、および `manage_*` 更新ツール — `manage_script_include`、`manage_flow_designer`、`manage_workflow`、`manage_kb_article`、`manage_portal_layout`、`manage_widget_dependency` を含む — をカバーします。`sys_updated_by`/`sys_updated_on` の **ライブリモート読み取り** によって判定されます — ローカルコピーは決して使いません。 | `SERVICENOW_CONCURRENT_EDIT_GUARD=off`。ウィンドウは `SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN` で指定（デフォルト `10`） |
| ソースプッシュのドリフト（ライブアンカー + update-set HOLD） | 編集したソースを `update_remote_from_local` で書き戻す際、時間ウィンドウでは捕捉できない 2 つのチェックを追加します: リモートの現在の `sys_updated_on` を、ダウンロード時に記録された値と **時間に依存せず** 比較すること（数時間後、あるいは数 **日** 後の上書きを捕捉）、およびそのレコードが **別ユーザーの未コミット update set に保持されている** かのライブチェック。 | 検出されたドリフトを押し通すには `force=true` |
| 重複作成 (G9) | ServiceNow が一意性を保証しないテーブル（`sys_update_set`、`wf_workflow`、`sys_user_group`、`sys_user`）で、既に存在する名前の 2 つ目のレコードを黙って作成すること。 | それでも作成するには `allow_duplicate='true'` を渡す |
| Flow Designer の生書き込み (G6) | フロースナップショットを破損させる `sys_hub_*` テーブルへの生の `sn_write` — `manage_flow_designer` を強制します。 | — |
| Publish 系 (G7) | 偶発的な publish/commit/push — 2 つ目の `confirm_publish='approve'` が必要です。 | — |
| インスタンス横断プッシュ | インスタンス A からダウンロードしたローカルソースをインスタンス B にプッシュすること（origin は `_settings.json` / `_manifest.json` から読み取り）。 | 正しいインスタンスから再ダウンロードする |

レイヤー全体を無効化するには `SERVICENOW_WRITE_GUARDS=off` を使用します。マルチインスタンスモードでは、すべての書き込みレスポンスに `instance_target` フィールドも付属し（他所にルーティングされた読み取りには `instance_source`）、呼び出しが当たったインスタンスが常に可視になります。

### Portal Investigation Safety

ポータル調査ツールはデフォルトで保守的です:

- `search_portal_regex_matches` は widget のみのスキャン、リンク展開オフ、小さなデフォルト上限で開始します。
- `trace_portal_route_targets` は、コンパクトな Widget -> Provider -> ルートターゲットの証跡を得るための推奨フォローアップです。
- `download_portal_sources` は、明示的に要求されない限りリンクされた Script Include や Angular Provider を取得しません。
- 大規模なポータルスキャンはサーバー側で上限が設けられ、リクエストが安全なデフォルトを超えると警告を返します。

パターンマッチングモード:

| Mode | Behavior |
|------|----------|
| `auto`（デフォルト） | プレーン文字列はリテラルとして扱い、正規表現に見えるパターンは正規表現のまま |
| `literal` | 常にパターンを先にエスケープ。ルート/トークン文字列に最も安全 |
| `regex` | 正規表現演算子を意図的に必要とする場合にのみ使用 |

---

## Performance Optimizations

サーバーには、レイテンシとトークン使用量を最小化するための複数層のパフォーマンス最適化が含まれています。

### Serialization

- **orjson バックエンド**: すべての JSON シリアライズは `json_fast`（利用可能なら orjson、なければ標準ライブラリにフォールバック）を使用します。loads と dumps の両方で標準ライブラリの `json` より 2〜4 倍高速です。
- **コンパクト出力**: ツールのレスポンスはインデントや余分な空白なしでシリアライズされ、レスポンスごとに 20〜30% のトークンを節約します。
- **二重パース回避**: `serialize_tool_output` は既にコンパクトな JSON 文字列を検出し、再シリアライズをスキップします。

### Caching

- **OrderedDict LRU キャッシュ**: クエリ結果は `OrderedDict.popitem()` を使った O(1) のエビクションでキャッシュされます。最大 256 エントリ、30 秒 TTL（安定したメタデータ — schema/scope/choice テーブル — は 600 秒）、スレッドセーフ。
- **ツールスキーマキャッシュ**: Pydantic の `model_json_schema()` 出力はモデルタイプごとにキャッシュされ、スキーマ生成の繰り返しを回避します。
- **遅延ツールディスカバリ**: アクティブな `MCP_TOOL_PACKAGE` が必要とするツールモジュールのみが起動時にインポートされます。未使用のモジュールは完全にスキップされます。

### Network

- **デフォルトでブラウザ相当の TLS**: HTTP レイヤーは Chrome のインパーソネーションプロファイル（デフォルト `chrome120`）を備えた `curl_cffi` を経由するため、TLS ハンドシェイクは実際のブラウザとバイト単位で同一になります — Cloudflare/Akamai や JA3 ボット検出の背後にあり、標準の Python `requests` を拒否するインスタンスでも追加設定なしで動作します。`SERVICENOW_TLS_IMPERSONATE=off` でオプトアウトします。
- **HTTP セッションプーリング**: TCP keep-alive と gzip/deflate 圧縮を備えた永続セッション（大きな JSON でペイロードを 60〜80% 削減）。標準 `requests` のオプトアウトパスは 20 接続の `HTTPAdapter` をマウントします。
- **並列ページネーション**: `sn_query_all` は合計件数のために最初のページを逐次的に取得し、残りのページを `ThreadPoolExecutor`（最大 4 ワーカー）で並行取得します。
- **動的ページサイズ調整**: 残りのレコードが 1 ページ（<=100）に収まる場合、余分なラウンドトリップを避けるためにページサイズが拡大されます。
- **バッチ API**: `sn_batch` は複数の REST サブリクエストを単一の `/api/now/batch` POST にまとめ、150 リクエストの上限で自動的にチャンク化します。
- **並列チャンク化 M2M クエリ**: 100 ID チャンクに分割された Widget-to-provider の M2M ルックアップは、逐次ではなく並行に実行されます。

### Schema & Startup

- **浅いコピーによるスキーマ注入**: 確認スキーマ（`confirm='approve'`）は `copy.deepcopy` ではなく軽量な dict コピーで注入され、`list_tools` のオーバーヘッドを削減します。
- **ノーカウント最適化**: 後続のページネーションページは `sysparm_no_count=true` を使用してサーバー側の合計件数計算をスキップします。
- **ペイロードの安全性**: 重いテーブル（`sp_widget`、`sys_script` など）には、コンテキストウィンドウのオーバーフローを防ぐための自動的なフィールドクランプと limit 制限があります。

## Local Source Audit

ServiceNow アプリケーション全体をローカルにダウンロードして分析します — API 呼び出しの繰り返しなし、コンテキストの浪費なし。

```
Step 1: download_app_sources(scope="x_company_app")    → All server-side code + cross-scope deps to disk
Step 2: audit_local_sources(source_root="temp/...")     → Analysis + HTML report
```

Step 1 はデフォルトで `auto_resolve_deps=True` を実行します: スコープ内のダウンロード後、すべての
`.js/.html/.xml` ファイルをスキャンし、バンドルにまだ含まれていない参照済みの `sys_script_include`、`sp_widget`、
`sp_angular_provider`、`sys_ui_macro` レコードを、それらがどのスコープに存在するかに関係なく取得します。
取得された依存関係は `_metadata.json` に `"is_dependency": true` を付けて同じツリーに保存されるため、
Step 2 の監査は完全なコールグラフを把握できます。スコープ内のレコードのみが欲しい場合は
`auto_resolve_deps=False` を設定してください。

> **ヒント — `global` を含むスコープ全体を取得する:** すべての global スコープのレコードをダンプするには
> `scope="global"` を渡すか、アプリのスコープを維持しつつ `auto_resolve_deps` に、実際に参照している
> レコードのために `global` へ手を伸ばさせてください。いずれの方法でもローカルバンドルは自己完結するため、
> 分析は完全にオフラインでディスクに対して実行されます。

### Incremental Sync

実行のたびに大きなアプリを再ダウンロードするのは遅く、タイムアウトのリスクがあります。`incremental=True` を渡すと、
**前回のダウンロード以降に変更されたものだけ** を取得します — 新規 `clone` ではなく `git pull` のようにです。
`download_app_sources` と `download_portal_sources` の両方で動作します。

```
download_app_sources(scope="x_company_app")                      # 1st run: full download
download_app_sources(scope="x_company_app", incremental=True)    # later: changed records only
```

- **仕組み:** 最初のダウンロードで各レコードの `sys_updated_on` を `_sync_meta.json` に記録します。増分実行では、
  すべてのソースファミリーが `sys_updated_on >= <latest seen>`（サーバー側タイムスタンプ、クロックスキューなし）を
  クエリし、それらのレコードだけを再ダウンロードし、変更されていないローカルファイルはそのままにします。
- **削除:** タイムスタンプの差分では削除されたレコードを認識できません。`reconcile_deletions=True` を追加すると、
  ローカルには存在するがインスタンス上では消えているレコードを列挙します — `deletion_candidates` の下に警告として
  報告され、**自動的に削除されることはありません**。
- **初回実行 / 過去データなし:** 自動的に完全ダウンロードにフォールバックします。
- 完全に同期した状態を保つため、定期的に完全（非増分）ダウンロードを実行してください。

### Download Safety & Completeness

ダウンロードはオフライン分析の信頼できる情報源であるため、決定論的であり、完全でないのに完全に *見える* ことが決してないように構築されています:

- **スコープの自動解決。** アプリの **ネームスペース**（`x_company_app`）、その **表示名**（"My App"）、または `sys_scope` の sys_id を渡してください — すべて正規のネームスペースに解決されるため、ローカルフォルダ（`temp/<instance>/<namespace>/`）とすべてのクエリは毎回同一になります。解決された値は `scope_resolution` としてエコーされます。
- **黙ったキャップなし。** ソースファミリーが `max_records_per_type` に達した場合、それは目立つようにフラグ付けされます: `source_types` 内のファミリーごとの `capped: true`、`incomplete_types` 内のそのファミリー、トップレベルの `complete: false`。切り詰められたダウンロードが完全なものになりすますことは決してありません。
- **インスタンス横断 / 古さに対するガード。** 書き戻し（`update_remote_from_local`）は、ローカルツリーに記録された origin を接続中のインスタンスと照合します。古いローカルコピーを保持する再開ダウンロードは、実際の同期ウォーターマークを保持し、ドリフトを隠すのではなく警告します。
- **ダウンロード時の関係メタデータ。** Widget→Angular-Provider エッジ（`_graph.json`）と widget→CSS/JS-dependency エッジ（`_dependency_graph.json`）は、ポータルダウンロード中にライブ M2M テーブルから取得されます — 分析はコードから推測する代わりに実際のグラフを読みます。
- **推移的依存関係の深さ。** スコープ横断の依存関係はデフォルトで `2` パスの深さまで解決します（保守的）。`SERVICENOW_DEP_MAX_DEPTH`（`1–6` にクランプ）で引き上げて、より長い A→B→C→D チェーンを追えます。
- **ワンコールでのグラフ構築。** `download_app_sources` に `build_graph=True` を渡すと、ダウンロード直後にオフラインの関係監査を実行します — 追加の API コストなし。
- **作成 → ローカル同期のうながし。** インスタンス上で widget/page を作成 *かつ* そのスコープのローカルツリーが存在する場合、作成レスポンスに `local_out_of_sync` メッセージが追加され、新しいレコードをローカルに取得するための正確な `download_portal_sources(...)` コマンドが示されます。ローカルファイルを勝手に書き込むことはありません。

### What Gets Generated

| File | Purpose |
|------|---------|
| `_audit_report.html` | 自己完結型のダークテーマ HTML レポート — ブラウザで開く |
| `_cross_references.json` | 誰が誰を呼ぶか — Script Include チェーン、GlideRecord のテーブル参照 |
| `_graph.json` | ライブ M2M 由来の信頼できる widget→Angular Provider エッジ（テキスト推測ではない） |
| `_dependency_graph.json` | `m2m_sp_widget_dependency` 由来の信頼できる widget→CSS/JS 依存エッジ |
| `_page_graph.json` | `sp_instance` からローカルに導出した Page→widget 配置（API 呼び出しなし） |
| `_orphans.json` | デッドコード候補 — 参照されない SI、未使用の widget |
| `_execution_order.json` | テーブルごとの BR/CS/ACL 実行シーケンス（順序番号付き） |
| `_domain_knowledge.md` | 自動生成されたアプリプロファイル — テーブルマップ、ハブスクリプト、警告 |
| `_schema/*.json` | 参照されるすべてのテーブルのフィールド定義 |
| `_sync_meta.json` | 増分同期を支えるファミリーごとの `sys_updated_on` ウォーターマーク |

### Individual Download Tools

完全なダンプにはオーケストレーターを、対象を絞った単一ファミリーのリフレッシュには `download_server_sources` を使用してください:

| Tool | Sources |
|------|---------|
| `download_app_sources` | アプリの完全ダンプ（すべてのファミリー + portal + schema + スコープ横断の依存関係） |
| `download_portal_sources` | Widget、Angular Provider、リンクされた Script Include |
| `download_server_sources` (`families=`) | 対象を絞ったリフレッシュ — `script_includes`、`server_scripts`（BR/Client/Catalog Client）、`ui`（Actions/Scripts/Pages/Macros）、`api`（Scripted REST/Processors）、`security`（ACL、デフォルトでスクリプトのみ）、`admin`（Fix Scripts/Scheduled Jobs/Script Actions/Notifications/Transforms） |
| `download_table_schema` | sys_dictionary のフィールド定義 |

すべてのダウンロードは完全なソースを切り詰めなしでディスクに書き込みます。LLM のコンテキストにはサマリーのみが返されます。

---

## Skills

ツールは生の API 呼び出しです。スキルこそが、あなたの LLM を実際に役立つものにします — 安全ゲート、ロールバック、コンテキスト認識のサブエージェント委譲を備えた検証済みパイプラインです。**MCP サーバー + スキルが、** LLM 駆動の ServiceNow 自動化のための **完全なセットアップ** です。

現在 4 スキル、リリースごとに増えていきます。

| | Tools Only | Tools + Skills |
|---|---|---|
| 安全性 | LLM が判断 | ゲートが強制（diff → preview → confirm → apply） |
| トークン | コンテキスト内にソースダンプ | サブエージェントに委譲、サマリーのみ |
| 正確性 | LLM がツール順序を推測 | 検証済みパイプライン |
| ロールバック | 忘れる可能性 | サーバー側のバージョン履歴（ServiceNow Versions タブ / 更新セット） |

### Install Skills

```bash
# Claude Code
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude

# OpenAI Codex
uvx --from mfa-servicenow-mcp servicenow-mcp-skills codex

# OpenCode
uvx --from mfa-servicenow-mcp servicenow-mcp-skills opencode

# Antigravity
uvx --from mfa-servicenow-mcp servicenow-mcp-skills antigravity
```

インストーラーはこのリポジトリの `skills/` ディレクトリからスキルファイルをダウンロードし、プロジェクトローカルの LLM ディレクトリに配置します。認証や設定は不要です。

> Windows で `servicenow-mcp-skills` がセキュリティポリシーにブロックされる場合は、モジュールとして呼び出してください — 動作は同じです:
>
> ```bash
> python -m servicenow_mcp.setup_skills claude
> ```

| Client | Install Path | Auto-Discovery |
|--------|-------------|----------------|
| Claude Code | `.claude/commands/servicenow/` | 次回起動時に `/servicenow` スラッシュコマンドが表示される |
| OpenAI Codex | `.codex/skills/servicenow/` | 次回のエージェントセッションでスキルが読み込まれる |
| OpenCode | `.opencode/skills/servicenow/` | 次回のセッションでスキルが読み込まれる |
| Antigravity | `.gemini/antigravity/skills/servicenow/` | 次回のセッションでスキルが有効化される |

**仕組み:** 各スキルは、YAML フロントマター（メタデータ）とパイプライン手順を持つ独立した Markdown ファイルです。LLM クライアントはこれらのファイルをインストールパスから読み取り、呼び出し可能なコマンドまたはスキルトリガーとして公開します。

**更新:** 同じインストールコマンドを再実行してください — 既存のスキルファイルをすべて置き換えます（クリーンインストール、マージなし）。

**スキルのみ削除:** スキルのインストールディレクトリを手動で削除してください（例: `rm -rf .claude/commands/servicenow/`）。

### Skill Categories

| Category | Skills | Purpose |
|----------|--------|---------|
| `analyze/` | 1 | **ローカルソース監査** — 相互参照、デッドコード、実行順序、HTML レポート |
| `explore/` | 1 | **フロートリガートレース** — テーブル変更時にどのワークフロー/フローが発火するか |
| `manage/` | 2 | **アプリソースダウンロード**、**ローカル同期**（diff → 競合検出付きプッシュ） |

### Skill Metadata

各スキルには、LLM が実行を最適化するのに役立つメタデータが含まれています:

```yaml
context_cost: low|medium|high    # → high = delegate to sub-agent
safety_level: none|confirm|staged # → staged = mandatory diff/preview/apply
delegatable: true|false           # → can run in sub-agent to save context
triggers: ["위젯 분석", "analyze widget"]  # → LLM trigger matching
```

完全なスキルリファレンスについては、[skills/SKILL.md](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/skills/SKILL.md) を参照してください。

### MCP Resources (Built-in Skill Guides)

スキルはサーバーから直接 **MCP リソース** としても公開されます — クライアント側のインストールは不要です。MCP 準拠の任意のクライアントが、オンデマンドでそれらを発見して読み取れます。

```
# List available skill guides
list_resources → skill://manage/local-sync, skill://manage/app-source-download, ...

# Read a specific guide
read_resource("skill://manage/local-sync") → full pipeline with safety gates
```

対応するスキルガイドを持つツールは、その説明に `→ skill://...` のヒントを表示します。ガイドの内容は **プルベース** です — クライアントが実際に読み取るまでトークンコストはゼロです。

| Feature | Client-side Skills | MCP Resources |
|---------|-------------------|---------------|
| 利用可能性 | インストールコマンドが必要 | 組み込み、任意のクライアント |
| トークンコスト | クライアントがロード | オンデマンドでプル（読み取るまで 0） |
| ディスカバリ | スラッシュコマンド / トリガー | `list_resources` |
| 最適な用途 | パワーユーザー、スラッシュコマンド | 汎用ガイダンス |

## Docker

API Key 認証のみ（MFA ブラウザ認証は GUI を必要とし、コンテナでは利用できません）。

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

ローカルビルドのオプションについては [Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md#docker-api-key-only) を参照してください。

## Developer Setup

ソースをローカルで変更したい場合:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uvx --with playwright playwright install chromium
```

### Running Tests

```bash
uv run pytest
```

### Linting & Formatting

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

### Building

```bash
uv build
```

> Windows: [Windows Installation Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md) を参照してください

---

## Documentation

- [LLM Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/llm-setup.md) — AI ガイド付きのワンライン・インストールフロー
- [Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md) — インストーラー優先のセットアップとフォールバックのクライアント設定
- [Tool Inventory](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_INVENTORY.md) — カテゴリとパッケージ別の完全なツールリスト
- [Windows Installation Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)
- [Catalog Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/catalog.md) — サービスカタログの CRUD と最適化
- [Change Management](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/change_management.md) — 変更要求のライフサイクルと承認
- [Workflow Management](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/workflow_management.md) — Workflow（wf_workflow エンジン）と Flow Designer のツール
- [Korean README](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md)

---

## Related Projects and Acknowledgements

- このリポジトリには、以前の内部 / レガシーな ServiceNow MCP 実装から統合・リファクタリングされたツールが含まれています。現在の面はバンドルされた `manage_*` ツールを中心に構成されています（[tool_utils.py](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/src/servicenow_mcp/utils/tool_utils.py) を参照）。
- 本プロジェクトは、安全で差分優先の MCP サーバーのユースケースに焦点を当てています: すべての書き込みは confirm + write-guards（同時編集、重複作成、publish、Flow Designer）を通過し、ソースの編集はプッシュ前にライブのリモートと差分が取られます。

---

## License

Apache License 2.0
