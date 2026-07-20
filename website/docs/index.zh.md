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
      不要给你的 AI 写脚本。<span class="gradient-text">为它装备武器。</span>
    </h1>
    <p class="hero-subtitle">
      用平实的语言告诉你的 AI 你需要什么。
      剩下的交给 MCP Skills。
    </p>
    <div class="hero-buttons">
      <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
        开始使用
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
    <span class="section-label">快速开始</span>
    <h2 class="section-title">只需粘贴这一行。就这么简单。</h2>
    <p class="section-desc">
      把下面这行复制到任意 AI 编码助手中。<br>
      它会自动安装一切 —— uv、Playwright、MCP 配置和技能。
    </p>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="quick-ai">粘贴到你的 AI 中</button>
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
      适用于 Claude Code、Cursor、Codex、OpenCode、Windsurf、VS Code Copilot、Antigravity、Zed 等等。<br>
      你的 AI 会检测客户端和操作系统，然后以交互方式引导你完成安装。<br>
      安装后，<strong>重启你的 AI 客户端</strong>以加载 MCP 服务器。
    </p>

    <p class="section-desc" style="margin-top:16px; font-size:0.9rem;">
      如果 <code>uvx</code> 被企业安全工具阻止，请跳到下方的
      <a href="#local-install">当 uvx 被阻止时（pip）</a>一节。
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">手动 — 安装 + 配置</span>
      <h2 class="section-title">先安装，再添加到客户端配置</h2>
      <p class="section-desc">
        更喜欢用终端？安装 uv + Chromium，然后将服务器添加到你的 MCP 客户端配置文件（片段见下）。无需安装命令，无需各客户端专属标志。
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
      <span class="section-label">当 uvx 被阻止时</span>
      <h2 class="section-title">改用 pip 安装</h2>
      <p class="section-desc">
        Windows 的 <a href="https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0" target="_blank" rel="noopener">Smart App Control</a> 会阻止 <code>uvx</code>，因为 uvx 每次运行都要解压一个未签名的临时可执行文件。如果 uvx 一直用得好好的，却在某次 Windows 更新之后突然失效，原因就在这里。改用 pip 安装，并以模块方式启动服务器 —— <code>servicenow-mcp</code> 控制台脚本是 pip 生成的未签名 <code>.exe</code> 包装器，会因为同样的原因被阻止。
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
            <pre class="install-code"><code><span class="c"># Homebrew 和发行版自带的 Python 会拒绝全局 pip 安装（PEP 668）。</span>
<span class="c"># 请改用 python.org 的 Python，或者干脆继续用上面的 uvx。</span>
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium

<span class="c"># 验证：</span>
python -m servicenow_mcp --version

<span class="c"># 以后升级：</span>
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium</code></pre>
          </div>
        </div>
        <div class="install-panel" id="local-win">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># python.org 的 Python 3.10+ 已签名，可以通过 Smart App Control。</span>
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium

<span class="c"># 验证：</span>
python -m servicenow_mcp --version

<span class="c"># 以后升级：</span>
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium</code></pre>
          </div>
        </div>
      </div>
    </div>
    <p class="section-desc" style="margin-top:16px; font-size:0.9rem; opacity:0.8;">
      无论用哪种方式，<code>env</code> 块都完全相同 —— 只有 <code>command</code> 和 <code>args</code> 不同。粘贴下方<a href="#mcp-tabs">手动回退</a>一节中的片段，然后把 <code>command</code> 设为 <code>python</code>，<code>args</code> 设为 <code>["-m", "servicenow_mcp"]</code>。
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">手动回退</span>
      <h2 class="section-title">手动修复或检查客户端配置</h2>
      <p class="section-desc">
        安装程序是推荐路径。仅当你需要手动检查或修复客户端配置时，才使用下面的原始配置示例。
      </p>
    </div>
    <p class="section-desc" style="margin-top:8px;font-size:0.9rem;opacity:0.8;">
      四种不同的形态涵盖了所有受支持的客户端。<code>env</code> 块在各处完全相同 —— 只有外层包装不同。
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
      只读的 <code>standard</code> 包默认加载 —— 无需 <code>MCP_TOOL_PACKAGE</code>。
      若需写入权限，请将其设为高级包（<code>service_desk</code>、<code>portal_developer</code>、
      <code>platform_developer</code> 或 <code>full</code>）—— 见
      <a href="docs/TOOL_PACKAGES/">工具包（高级）指南</a>。
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">手动 — 第 3 步</span>
      <h2 class="section-title">添加为 LLM 优化的技能</h2>
      <p class="section-desc">
        仅有工具只是原始的 API 调用。技能才是让你的 LLM 真正有用的东西 ——
        带安全门控、回滚和上下文感知委派的经验证流水线。
        如今有 4 个技能，每次发布都会有更多。
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
        <p>5 个技能 —— widget 分析、门户诊断、本地源码审计、provider 审计、ESC 页面审计</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>🔧 fix/</h3>
        <p>3 个技能 —— 带分阶段安全门控的 widget 修补、调试、代码审查</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>📦 manage/</h3>
        <p>5 个技能 —— 应用源码下载、变更集工作流、本地同步、工作流管理、技能管理</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🚀 deploy/</h3>
        <p>1 个技能 —— 变更请求生命周期</p>
      </div>
      <div class="step-card" style="--i:5">
        <h3>🧭 explore/</h3>
        <p>2 个技能 —— flow 触发器追踪、ESC 目录流程</p>
      </div>
    </div>
  </div>
</div>

<div class="install-block reveal" style="margin-top:40px;">
  <span class="section-label">保持更新</span>
  <h2 class="section-title">始终运行最新版本</h2>
  <p class="section-desc" style="margin-bottom:16px;">
    <code>uvx</code> 会缓存上次下载的版本 —— 它<strong>不会</strong>自动更新。<br>
    通过 <code>uv</code> 升级以获取最新发布版：
  </p>
  <div class="install-tabs"><button class="install-tab active">终端</button></div>
  <div class="install-code-block">
    <pre class="install-code"><code>uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version</code></pre>
  </div>
  <p class="section-desc" style="margin-top:12px;font-size:0.9em;">
    然后重启你的 MCP 客户端（Claude Code、Cursor 等）以加载新版本。
  </p>
</div>

<div class="hero-stats reveal">
  <div class="hero-stat">
    <span class="hero-stat-value">70</span>
    <span class="hero-stat-label">已注册工具</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">MFA</span>
    <span class="hero-stat-label">原生支持</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">5</span>
    <span class="hero-stat-label">技能类别</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">0</span>
    <span class="hero-stat-label">凭据共享</span>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">工作原理</span>
    <h2 class="section-title">三步即可投入生产</h2>
    <p class="section-desc">
      无需配置 API 密钥，配置文件中也没有密码。
      通过浏览器认证一次，你的 AI 代理便继承一个实时会话。
    </p>
    <div class="steps-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <div class="step-number">1</div>
        <h3>安装</h3>
        <p>用 <code>uvx</code> 一条命令搞定一切。零配置。</p>
      </div>
      <div class="step-card" style="--i:2">
        <div class="step-number">2</div>
        <h3>认证</h3>
        <p>会打开一个真实浏览器用于 MFA、SSO、SAML —— 无论你的组织要求什么。</p>
      </div>
      <div class="step-card" style="--i:3">
        <div class="step-number">3</div>
        <h3>连接</h3>
        <p>指向 Claude、Cursor、Zed 或任意 MCP 客户端。70 个已注册工具通过活动包配置加载。</p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">特性</span>
    <h2 class="section-title">为企业打造</h2>
    <p class="section-desc">
      在规模化场景下安全地连接 AI 代理与 ServiceNow，你所需的一切尽在于此。
    </p>

    <div class="feature-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔒 零信任安全</h3>
        <p>基于浏览器的认证意味着凭据永不离开你的机器。支持 MFA、SSO、SAML 以及你组织使用的任意登录流程。</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>⚡ token 高效的性能</h3>
        <p>惰性工具发现、按包限定的 schema、紧凑 JSON、响应缓存和批量读取，将启动开销和 LLM 上下文成本控制在可控范围内。</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>🧩 安全的数据比对</h3>
        <p>可选的命名实例被限制为只读的 dev/test 漂移检查。普通工具始终固定在一个活动实例上。</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🤖 广泛的客户端支持</h3>
        <p>适用于 Claude、Codex、Cursor、Zed、Antigravity、OpenCode、Windsurf、VS Code Copilot，以及通过 stdio 或 Streamable HTTP 通信的 MCP 客户端。</p>
      </div>
    </div>

  </div>
</div>

<hr class="section-divider">

<div class="cta-banner reveal">
  <h2>准备好把你的 AI 连接到 ServiceNow 了吗？</h2>
  <p>跟随我们的分步指南，五分钟内即可完成设置。</p>
  <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">阅读安装指南</a>
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
