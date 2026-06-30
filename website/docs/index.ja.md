---
hide:
  - navigation
  - toc
social:
  cards: false
---

<div class="landing-page">
<div class="hero-section">
  <div class="hero-bg-img"></div>
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <h1 class="hero-title">
      AI をスクリプトで縛るな。<span class="gradient-text">武器を持たせろ。</span>
    </h1>
    <p class="hero-subtitle">
      必要なことを普通の言葉で AI に伝えるだけ。
      あとは MCP Skills が処理します。
    </p>
    <div class="hero-buttons">
      <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
        はじめる
      </a>
      <a href="https://github.com/jshsakura/mfa-servicenow-mcp" class="md-button md-button--ghost">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
        GitHub
      </a>
    </div>
  </div>
</div>

<div class="content-wrap">

<div class="hero-terminal reveal">
  <div class="hero-terminal-header">
    <div class="hero-terminal-dots">
      <span class="dot red"></span>
      <span class="dot yellow"></span>
      <span class="dot green"></span>
    </div>
    <span class="hero-terminal-title">mfa-servicenow-mcp</span>
    <div class="hero-terminal-spacer"></div>
  </div>
  <div class="hero-terminal-body" id="hero-typed-terminal"></div>
</div>

<div class="section reveal" id="install" style="padding-top:48px;">
  <div class="section-inner">
    <span class="section-label">クイックスタート</span>
    <h2 class="section-title">これを貼り付けるだけ。それで完了。</h2>
    <p class="section-desc">
      下の行を任意の AI コーディングアシスタントにコピーしてください。<br>
      uv、Playwright、MCP 設定、スキルまで — すべて自動でインストールします。
    </p>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="quick-ai">AI に貼り付ける</button>
      </div>
      <div class="install-panels">
        <div class="install-panel active" id="quick-ai">
          <div class="install-code-block">
            <pre class="install-code"><code>Install and configure mfa-servicenow-mcp by following the instructions here:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md</code></pre>
          </div>
        </div>
      </div>
    </div>
    <p class="section-desc" style="margin-top:16px; font-size:0.9rem; opacity:0.7;">
      Claude Code、Cursor、Codex、OpenCode、Windsurf、VS Code Copilot、Antigravity、Zed などで動作します。<br>
      AI がクライアントと OS を検出し、対話的にセットアップへ導きます。<br>
      セットアップ後は、<strong>AI クライアントを再起動</strong> して MCP サーバーを読み込んでください。
    </p>

    <p class="section-desc" style="margin-top:16px; font-size:0.9rem;">
      企業のセキュリティツールによって <code>uvx</code> がブロックされている場合は、下記の
      <a href="#local-install">ローカルインストール（リリース zip）</a> セクションへ進んでください。
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">手動 — インストール + 設定</span>
      <h2 class="section-title">インストールしてから、クライアント設定に追加する</h2>
      <p class="section-desc">
        ターミナル派ですか? uv + Chromium をインストールしてから、サーバーを MCP クライアントの設定ファイルに追加してください（下記スニペット）。インストーラーコマンドも、クライアントごとのフラグも不要です。
      </p>
    </div>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="install-mac">macOS / Linux</button>
        <button class="install-tab" data-target="install-win">Windows</button>
      </div>
      <div class="install-panels">
        <div class="install-panel active" id="install-mac">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># 1. Install uv (if not already installed)</span>
curl -LsSf https://astral.sh/uv/install.sh | sh

<span class="c"># 2. Fetch the server + Chromium up front (so the first browser-auth call</span>
<span class="c">#    doesn't download ~150 MB and time out)</span>
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium

<span class="c"># 3. Add the server to your MCP client config — copy a snippet below</span></code></pre>
          </div>
        </div>
        <div class="install-panel" id="install-win">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># 1. Install uv (if not already installed)</span>
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

<span class="c"># 2. Fetch the server + Chromium up front (so the first browser-auth call</span>
<span class="c">#    doesn't download ~150 MB and time out)</span>
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium

<span class="c"># 3. Add the server to your MCP client config — copy a snippet below</span></code></pre>
          </div>
        </div>
      </div>
    </div>

    <div id="local-install" style="margin-top:56px;" class="reveal">
      <span class="section-label">ローカルインストール — オフラインに優しい</span>
      <h2 class="section-title">リリース zip からインストールする</h2>
      <p class="section-desc">
        <code>uvx</code> または PyPI がブロックされている場合に使用します。リリース zip には PyInstaller でビルドされた単一ファイルの実行ファイルが付属します — Python 不要、インストーラースクリプト不要。<a href="https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest" target="_blank" rel="noopener">GitHub Releases</a> からプラットフォーム zip（および Chromium のダウンロードもブロックされている場合は任意で対応する <code>ms-playwright-chromium</code> zip）を取得し、展開して、MCP クライアントの <code>command</code> を実行ファイルに向けてください。
      </p>
    </div>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="local-mac">macOS / Linux</button>
        <button class="install-tab" data-target="local-win">Windows</button>
      </div>
      <div class="install-panels">
        <div class="install-panel active" id="local-mac">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># 1. Pick a stable folder you control. Extract both zips UP FRONT —</span>
<span class="c">#    don't leave .zip files alongside the executable. The Chromium</span>
<span class="c">#    folder name just has to start with ms-play and hold chromium-*:</span>
<span class="c">#</span>
<span class="c">#    ~/apps/servicenow-mcp/                              (any directory)</span>
<span class="c">#    ├── servicenow-mcp                                  ← executable</span>
<span class="c">#    └── ms-playwright-chromium-linux-x64-&lt;ver&gt;/         ← default name works</span>
<span class="c">#        └── chromium-1185/</span>
<span class="c">#</span>
<span class="c"># 2. At startup the executable globs for a sibling ms-play* directory</span>
<span class="c">#    with a chromium-* inside and points Playwright at it. The system</span>
<span class="c">#    standard cache (~/.cache/ms-playwright) and your MCP client config</span>
<span class="c">#    stay untouched.</span>
<span class="c"># 3. Verify the binary runs:</span>
~/apps/servicenow-mcp/servicenow-mcp --version

<span class="c"># 4. Paste the MCP config snippet from "Manual fallback" below into</span>
<span class="c">#    your client config and set 'command' to:</span>
<span class="c">#       ~/apps/servicenow-mcp/servicenow-mcp</span>
<span class="c"># Then restart your MCP client.</span></code></pre>
          </div>
        </div>
        <div class="install-panel" id="local-win">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># 1. Pick a stable folder you control. Extract both zips UP FRONT —</span>
<span class="c">#    don't leave .zip files alongside the executable. The Chromium</span>
<span class="c">#    folder name just has to start with ms-play and hold chromium-*:</span>
<span class="c">#</span>
<span class="c">#    C:\Users\you\apps\servicenow-mcp\</span>
<span class="c">#    ├── servicenow-mcp.exe                              ← executable</span>
<span class="c">#    └── ms-playwright-chromium-windows-x64-&lt;ver&gt;\       ← default name works</span>
<span class="c">#        └── chromium-1185\</span>
<span class="c">#</span>
<span class="c"># 2. At startup the executable globs for a sibling ms-play* directory</span>
<span class="c">#    with a chromium-* inside and points Playwright at it. The system</span>
<span class="c">#    standard cache (%LOCALAPPDATA%\ms-playwright) and your MCP client</span>
<span class="c">#    config stay untouched.</span>
<span class="c"># 3. Verify the binary runs:</span>
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version

<span class="c"># 4. Paste the MCP config snippet from "Manual fallback" below into</span>
<span class="c">#    your client config and set 'command' to:</span>
<span class="c">#       C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe</span>
<span class="c"># Then restart your MCP client.</span></code></pre>
          </div>
        </div>
      </div>
    </div>
    <p class="section-desc" style="margin-top:16px; font-size:0.9rem; opacity:0.8;">
      インストーラースクリプトはありません。実行ファイルを、管理する任意の安定したフォルダに解凍し、Chromium zip を <code>ms-playwright</code> という名前の兄弟フォルダに展開すると、実行ファイルが起動時にそのレイアウトを自動検出します — 現在のプロセスに限り <code>PLAYWRIGHT_BROWSERS_PATH</code> を介して Playwright をそこへ向けます。システム標準の Playwright キャッシュ（<code>~/.cache/ms-playwright</code>、<code>%LOCALAPPDATA%\ms-playwright</code>）には触れず、MCP クライアント設定はあなたが編集するものです — 下記の <a href="#mcp-tabs">手動フォールバック</a> セクションのスニペットを貼り付け、<code>command</code> を実行ファイルの絶対パスに設定してください。
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">手動フォールバック</span>
      <h2 class="section-title">クライアント設定を手動で修復または検査する</h2>
      <p class="section-desc">
        インストーラーが推奨される方法です。下記の生の設定例は、クライアント設定を手作業で検査または修復する必要がある場合にのみ使用してください。
      </p>
    </div>
    <p class="section-desc" style="margin-top:8px;font-size:0.9rem;opacity:0.8;">
      4 つの異なる形が、サポートされているすべてのクライアントをカバーします。<code>env</code> ブロックはどこでも同一です — 外側のラッパーだけが異なります。
    </p>
    <div class="install-block reveal">
      <div class="install-tabs" id="mcp-tabs">
        <button class="install-tab active" data-target="mcp-standard">Claude Desktop / Claude Code / AntiGravity / Cursor</button>
        <button class="install-tab" data-target="mcp-zed">Zed</button>
        <button class="install-tab" data-target="mcp-codex">Codex (TOML)</button>
        <button class="install-tab" data-target="mcp-opencode">OpenCode</button>
      </div>
      <div class="install-panels" id="mcp-panels">
        <div class="install-panel active" id="mcp-standard">
          <div class="install-code-block">
            <pre class="install-code"><code>{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-zed">
          <div class="install-code-block">
            <pre class="install-code"><code>{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
    "env": {
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "SERVICENOW_USERNAME": "your-username",
      "SERVICENOW_PASSWORD": "your-password"
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-codex">
          <div class="install-code-block">
            <pre class="install-code"><code>[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-opencode">
          <div class="install-code-block">
            <pre class="install-code"><code>{
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
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}</code></pre>
          </div>
        </div>
      </div>
    </div>

    <p class="section-desc reveal" style="max-width:760px;margin-top:20px;">
      読み取り専用の <code>standard</code> パッケージがデフォルトで読み込まれます — <code>MCP_TOOL_PACKAGE</code> は不要です。
      書き込みアクセスには、高度なパッケージ（<code>service_desk</code>、<code>portal_developer</code>、
      <code>platform_developer</code>、または <code>full</code>）に設定してください — 
      <a href="docs/TOOL_PACKAGES/">ツールパッケージ（高度）ガイド</a> を参照。
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">手動 — ステップ 3</span>
      <h2 class="section-title">LLM 最適化スキルを追加する</h2>
      <p class="section-desc">
        ツールだけでは生の API 呼び出しにすぎません。スキルこそが LLM を実際に役立つものにします —
        安全ゲート、ロールバック、コンテキスト対応の委譲を備えた検証済みパイプライン。
        今日は 4 スキル、リリースのたびに増えていきます。
      </p>
    </div>
    <div class="install-block reveal">
      <div class="install-tabs" id="skill-tabs">
        <button class="install-tab active" data-target="skill-claude">Claude Code</button>
        <button class="install-tab" data-target="skill-codex">Codex</button>
        <button class="install-tab" data-target="skill-opencode">OpenCode</button>
        <button class="install-tab" data-target="skill-antigravity">Antigravity</button>
      </div>
      <div class="install-panels" id="skill-panels">
        <div class="install-panel active" id="skill-claude">
          <div class="install-code-block">
            <pre class="install-code"><code>uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude</code></pre>
          </div>
        </div>
        <div class="install-panel" id="skill-codex">
          <div class="install-code-block">
            <pre class="install-code"><code>uvx --from mfa-servicenow-mcp servicenow-mcp-skills codex</code></pre>
          </div>
        </div>
        <div class="install-panel" id="skill-opencode">
          <div class="install-code-block">
            <pre class="install-code"><code>uvx --from mfa-servicenow-mcp servicenow-mcp-skills opencode</code></pre>
          </div>
        </div>
        <div class="install-panel" id="skill-antigravity">
          <div class="install-code-block">
            <pre class="install-code"><code>uvx --from mfa-servicenow-mcp servicenow-mcp-skills antigravity</code></pre>
          </div>
        </div>
      </div>
    </div>
    <div class="skill-categories reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔍 analyze/</h3>
        <p>5 スキル — ウィジェット分析、ポータル診断、ローカルソース監査、プロバイダー監査、ESC ページ監査</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>🔧 fix/</h3>
        <p>3 スキル — 段階的な安全ゲート付きウィジェットパッチ適用、デバッグ、コードレビュー</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>📦 manage/</h3>
        <p>5 スキル — アプリソースダウンロード、チェンジセットワークフロー、ローカル同期、ワークフロー管理、スキル管理</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🚀 deploy/</h3>
        <p>1 スキル — 変更要求のライフサイクル</p>
      </div>
      <div class="step-card" style="--i:5">
        <h3>🧭 explore/</h3>
        <p>2 スキル — フロートリガートレース、ESC カタログフロー</p>
      </div>
    </div>
  </div>
</div>

<div class="install-block reveal" style="margin-top:40px;">
  <span class="section-label">最新の状態を保つ</span>
  <h2 class="section-title">常に最新バージョンを実行する</h2>
  <p class="section-desc" style="margin-bottom:16px;">
    <code>uvx</code> は最後にダウンロードしたバージョンをキャッシュします — 自動更新は <strong>されません</strong>。<br>
    <code>uv</code> 経由でアップグレードして最新リリースを取得してください:
  </p>
  <div class="install-tabs"><button class="install-tab active">ターミナル</button></div>
  <div class="install-code-block">
    <pre class="install-code"><code>uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version</code></pre>
  </div>
  <p class="section-desc" style="margin-top:12px;font-size:0.9em;">
    その後、MCP クライアント（Claude Code、Cursor など）を再起動して新しいバージョンを読み込んでください。
  </p>
</div>

<div class="hero-stats reveal">
  <div class="hero-stat">
    <span class="hero-stat-value">70</span>
    <span class="hero-stat-label">登録済みツール</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">MFA</span>
    <span class="hero-stat-label">ネイティブ対応</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">5</span>
    <span class="hero-stat-label">スキルカテゴリ</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">0</span>
    <span class="hero-stat-label">共有されたクレデンシャル</span>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">仕組み</span>
    <h2 class="section-title">本番までの 3 ステップ</h2>
    <p class="section-desc">
      設定する API キーも、設定ファイル内のパスワードもありません。
      ブラウザで一度認証すれば、AI エージェントがライブセッションを引き継ぎます。
    </p>
    <div class="steps-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <div class="step-number">1</div>
        <h3>インストール</h3>
        <p><code>uvx</code> による 1 コマンドですべてをセットアップ。設定ゼロ。</p>
      </div>
      <div class="step-card" style="--i:2">
        <div class="step-number">2</div>
        <h3>認証</h3>
        <p>MFA、SSO、SAML — 組織が要求するものは何でも、実ブラウザが開きます。</p>
      </div>
      <div class="step-card" style="--i:3">
        <div class="step-number">3</div>
        <h3>接続</h3>
        <p>Claude、Cursor、Zed、または任意の MCP クライアントを向けるだけ。70 個の登録済みツールがアクティブなパッケージプロファイルを通じて読み込まれます。</p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">機能</span>
    <h2 class="section-title">エンタープライズ向けに構築</h2>
    <p class="section-desc">
      AI エージェントと ServiceNow を、安全かつ大規模に橋渡しするために必要なすべて。
    </p>

    <div class="feature-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔒 ゼロトラストセキュリティ</h3>
        <p>ブラウザベースの認証により、クレデンシャルがマシンから出ることはありません。MFA、SSO、SAML、そして組織が使う任意のログインフローに対応します。</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>⚡ トークン効率の高いパフォーマンス</h3>
        <p>遅延ツール検出、パッケージスコープのスキーマ、コンパクトな JSON、レスポンスキャッシュ、バッチ読み取りにより、起動と LLM のコンテキストコストを抑えます。</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>🧩 安全なデータ比較</h3>
        <p>任意の名前付きインスタンスは、読み取り専用の dev/test ドリフトチェックに限定されます。通常のツールは 1 つのアクティブなインスタンスに固定されたままです。</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🤖 幅広いクライアント対応</h3>
        <p>Claude、Codex、Cursor、Zed、Antigravity、OpenCode、Windsurf、VS Code Copilot、そして stdio または Streamable HTTP 経由の MCP クライアントで動作します。</p>
      </div>
    </div>

  </div>
</div>

<hr class="section-divider">

<div class="cta-banner reveal">
  <h2>AI を ServiceNow に接続する準備はできましたか?</h2>
  <p>ステップバイステップのガイドで、5 分以内にセットアップできます。</p>
  <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">セットアップガイドを読む</a>
</div>

</div>

<script>
(function(){
  // Intersection Observer for Reveal Animations
  var obsOptions = { threshold: 0.1 };
  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('active');
      }
    });
  }, obsOptions);

  document.querySelectorAll('.reveal, .reveal-stagger, .reveal-left, .reveal-right').forEach(function(el) {
    observer.observe(el);
  });

  var lines = [
    { type:"prompt", prompt:"$ ", text:"uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp", speed:22 },
    { type:"pause", ms:500 },
    { type:"success", text:"\u2713 Authenticated with ServiceNow (MFA verified)", speed:10 },
    { type:"pause", ms:700 },
    { type:"prompt", prompt:"Claude \u203a ", text:"\"Trace the route for /hr?id=onboarding\"", speed:26 },
    { type:"pause", ms:400 },
    { type:"thinking", text:"Analyzing portal route and widget layout\u2026", speed:14 },
    { type:"pause", ms:250 },
    { type:"tool", text:"\u2699 servicenow_get_portal", dim:" portal_id=hr", speed:6 },
    { type:"tool", text:"\u2699 servicenow_get_page", dim:" page_id=onboarding", speed:6 },
    { type:"tool", text:"\u2699 servicenow_trace_portal_route_targets", dim:" match=onboarding", speed:6 },
    { type:"pause", ms:500 },
    { type:"success", text:"\u2713 Route resolved \u2014 4 widgets found, upstream: onboardingHeroWd", speed:10 }
  ];
  var el=document.getElementById("hero-typed-terminal");
  if(!el) return;
  var map={prompt:"hero-terminal-command",success:"hero-terminal-success",thinking:"hero-terminal-thinking",tool:"hero-terminal-tool"};
  function mk(c){
    var d=document.createElement("div");d.className="hero-terminal-line";
    if(c.type==="prompt"){var p=document.createElement("span");p.className="hero-terminal-prompt";p.textContent=c.prompt;d.appendChild(p);}
    var s=document.createElement("span");s.className=map[c.type]||"";d.appendChild(s);
    var ds=null;if(c.dim){ds=document.createElement("span");ds.className="hero-terminal-dim";d.appendChild(ds);}
    return{el:d,s:s,ds:ds,t:c.text,dm:c.dim||"",sp:c.speed};
  }
  function ty(info,cb){
    el.appendChild(info.el);var i=0,f=info.t;
    (function tk(){if(i<=f.length){info.s.textContent=f.slice(0,i);i++;setTimeout(tk,info.sp);}else{if(info.ds)info.ds.textContent=info.dm;cb();}}());
  }
  function run(i){
    if(i>=lines.length){
      var cur=document.createElement("div");cur.className="hero-terminal-line";
      var cp=document.createElement("span");cp.className="hero-terminal-prompt";cp.textContent="$ ";cur.appendChild(cp);
      var cc=document.createElement("span");cc.className="hero-terminal-cursor";cur.appendChild(cc);
      el.appendChild(cur);
      setTimeout(function(){el.innerHTML="";run(0);},3500);return;
    }
    var c=lines[i];
    if(c.type==="pause") setTimeout(function(){run(i+1);},c.ms);
    else ty(mk(c),function(){run(i+1);});
  }
  if("IntersectionObserver" in window){
    var ob=new IntersectionObserver(function(e){if(e[0].isIntersecting){ob.disconnect();run(0);}},{threshold:0.2});
    ob.observe(el);
  }else run(0);
})();


// --- Tabs: scoped per .install-block so multiple tab groups work independently ---
(function(){
  document.querySelectorAll(".install-block").forEach(function(block){
    var tabs=block.querySelectorAll(".install-tab");
    var panels=block.querySelectorAll(".install-panel");
    tabs.forEach(function(tab){
      tab.addEventListener("click",function(){
        tabs.forEach(function(t){t.classList.remove("active");});
        tab.classList.add("active");
        panels.forEach(function(p){p.classList.remove("active");});
        var t=document.getElementById(tab.getAttribute("data-target"));
        if(t) t.classList.add("active");
      });
    });
  });
})();

// --- Hover Tracking for Cards ---
(function(){
  document.querySelectorAll('.step-card').forEach(function(card){
    card.addEventListener('mousemove', function(e) {
      var rect = card.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var y = e.clientY - rect.top;
      card.style.setProperty('--mouse-x', x + 'px');
      card.style.setProperty('--mouse-y', y + 'px');
    });
  });
})();
</script>
</div>
