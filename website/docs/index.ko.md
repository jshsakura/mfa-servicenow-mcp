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
      Don't script your AI. <span class="gradient-text">Arm it.</span>
    </h1>
    <p class="hero-subtitle">
      자연스럽게 AI에게 물어보세요.<br>
      나머지는 MCP 스킬이 알아서 처리합니다.
    </p>
    <div class="hero-buttons">
      <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
        시작하기
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
    <span class="section-label">빠른 시작</span>
    <h2 class="section-title">이 한 줄만 복사하세요. 끝입니다.</h2>
    <p class="section-desc">
      아래 명령어를 AI 코딩 어시스턴트에 붙여넣으세요.<br>
      uv, Playwright, MCP 설정, 스킬 설치까지 한 번에 자동으로 설정됩니다.
    </p>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="quick-ai">AI에 붙여넣기</button>
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
      Claude Code, Cursor, Codex, OpenCode, Windsurf, VS Code Copilot, Gemini CLI 등과 호환됩니다.<br>
      AI가 클라이언트와 OS를 감지한 뒤, 대화형으로 설정을 진행해 줍니다.<br>
      설정이 완료되면 <strong>AI 클라이언트를 재시작</strong>하여 MCP 서버를 로드하세요.
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">수동 설치 — 한 번에</span>
      <h2 class="section-title">클라이언트용 setup 실행</h2>
      <p class="section-desc">
        터미널에서 직접 설치하고 싶다면 아래 installer를 사용하세요.<br>
        클라이언트에 맞는 MCP 설정을 써 주고, 기존 설정은 보존하며, 지원되는 경우 스킬도 함께 설치합니다.
      </p>
    </div>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="install-mac">macOS / Linux</button>
        <button class="install-tab" data-target="install-win">Windows</button>
        <button class="install-tab" data-target="install-pip">pip</button>
        <button class="install-tab" data-target="install-dev">Dev</button>
      </div>
      <div class="install-panels">
        <div class="install-panel active" id="install-mac">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Install uv (if not already installed)</span>
curl -LsSf https://astral.sh/uv/install.sh | sh

<span class="c"># 클라이언트 설정과 선택 스킬 설치</span>
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"</code></pre>
          </div>
        </div>
        <div class="install-panel" id="install-win">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Install uv (if not already installed)</span>
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

<span class="c"># 클라이언트 설정과 선택 스킬 설치</span>
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser"</code></pre>
          </div>
        </div>
        <div class="install-panel" id="install-pip">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Install with pip + browser auth support</span>
pip install "mfa-servicenow-mcp[browser]"
playwright install chromium

<span class="c"># Run with MFA browser login</span>
servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"</code></pre>
          </div>
        </div>
        <div class="install-panel" id="install-dev">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Clone and install in development mode</span>
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp
uv pip install -e ".[browser]"
playwright install chromium

<span class="c"># Run with MFA browser login</span>
servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"</code></pre>
          </div>
        </div>
      </div>
    </div>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">수동 복구용</span>
      <h2 class="section-title">클라이언트 설정을 직접 점검하거나 복구하기</h2>
      <p class="section-desc">
        installer가 권장 경로입니다. 아래 원시 설정 예시는 설정 파일을 직접 점검하거나 복구해야 할 때만 사용하세요.
      </p>
    </div>
    <div class="install-block reveal">
      <div class="install-tabs" id="mcp-tabs">
        <button class="install-tab active" data-target="mcp-claude-desktop">Claude Desktop</button>
        <button class="install-tab" data-target="mcp-claude-code">Claude Code</button>
        <button class="install-tab" data-target="mcp-codex">Codex</button>
        <button class="install-tab" data-target="mcp-opencode">OpenCode</button>
        <button class="install-tab" data-target="mcp-gemini">Gemini</button>
        <button class="install-tab" data-target="mcp-antigravity">AntiGravity</button>
      </div>
      <div class="install-panels" id="mcp-panels">
        <div class="install-panel active" id="mcp-claude-desktop">
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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-claude-code">
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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
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
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"</code></pre>
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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-gemini">
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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-antigravity">
          <div class="install-code-block">
            <pre class="install-code"><code>{
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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}</code></pre>
          </div>
        </div>
      </div>
    </div>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">수동 설치 — 3단계</span>
      <h2 class="section-title">LLM 최적화 스킬 추가하기</h2>
      <p class="section-desc">
        도구(Tool)만으로는 단순한 API 호출일 뿐입니다.<br>
        안전 장치, 롤백, 문맥 인식을 통한 위임 파이프라인이 포함된 스킬(Skill)들이 결합되었을 때<br>
        LLM은 진정으로 유용해집니다. 현재 16개 스킬을 지원하며 릴리스마다 더 추가되고 있습니다.
      </p>
    </div>
    <div class="install-block reveal">
      <div class="install-tabs" id="skill-tabs">
        <button class="install-tab active" data-target="skill-claude">Claude Code</button>
        <button class="install-tab" data-target="skill-codex">Codex</button>
        <button class="install-tab" data-target="skill-opencode">OpenCode</button>
        <button class="install-tab" data-target="skill-gemini">Gemini CLI</button>
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
        <div class="install-panel" id="skill-gemini">
          <div class="install-code-block">
            <pre class="install-code"><code>uvx --from mfa-servicenow-mcp servicenow-mcp-skills gemini</code></pre>
          </div>
        </div>
      </div>
    </div>
    <div class="skill-categories reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔍 analyze/</h3>
        <p>6개 스킬 — 위젯 분석, 포털 진단, 의존성 매핑, 코드 감지</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>🔧 fix/</h3>
        <p>3개 스킬 — 안전망이 있는 위젯 패치, 디버깅, 코드 리뷰</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>📦 manage/</h3>
        <p>8개 스킬 — 페이지 레이아웃, 스크립트 인클루드, 소스 내보내기, 앱 소스 다운로드, 변경 집합(Changeset) 워크플로우, 로컬 동기화, 워크플로우 관리, 스킬 관리</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🚀 deploy/</h3>
        <p>2개 스킬 — 변경 요청(CR) 수명주기, 인시던트 분류</p>
      </div>
      <div class="step-card" style="--i:5">
        <h3>🧭 explore/</h3>
        <p>5개 스킬 — 상태 점검(Health check), 스키마 탐색, 라우트 추적, 플로우 트리거 추적, ESC 카탈로그 흐름</p>
      </div>
    </div>
  </div>
</div>

<div class="install-block reveal" style="margin-top:40px;">
  <span class="section-label">최신 버전 유지</span>
  <h2 class="section-title">항상 최신 버전으로 업데이트하기</h2>
  <p class="section-desc" style="margin-bottom:16px;">
    <code>uvx</code>는 마지막으로 다운로드한 버전을 캐시하여 계속 재사용합니다 — <strong>자동 업데이트되지 않습니다.</strong><br>
    <code>uv</code>를 통해 업그레이드하세요:
  </p>
  <div class="install-tabs"><button class="install-tab active">Terminal</button></div>
  <div class="install-code-block">
    <pre class="install-code"><code>uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version</code></pre>
  </div>
  <p class="section-desc" style="margin-top:12px;font-size:0.9em;">
    업그레이드 후 MCP 클라이언트를 재시작해야 새 버전이 적용됩니다 (Claude Code, Cursor 등).
  </p>
</div>

<div class="hero-stats reveal">
  <div class="hero-stat">
    <span class="hero-stat-value">77</span>
    <span class="hero-stat-label">MCP 도구(Tools)</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">MFA</span>
    <span class="hero-stat-label">네이티브 지원</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">5</span>
    <span class="hero-stat-label">스킬 패키지</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">0</span>
    <span class="hero-stat-label">외부 공유되는 자격 증명</span>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">작동 방식</span>
    <h2 class="section-title">운영 환경까지 단 3단계</h2>
    <p class="section-desc">
      설정할 API 키나 구성 파일에 넣을 비밀번호가 없습니다.<br>
      브라우저를 통해 한 번만 인증하면 AI 에이전트가 실시간 세션을 상속받습니다.
    </p>
    <div class="steps-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <div class="step-number">1</div>
        <h3>설치</h3>
        <p><code>uvx</code>를 사용한 명령 한 줄로 모든 설정이 끝납니다. 제로 구성(Zero config).</p>
      </div>
      <div class="step-card" style="--i:2">
        <div class="step-number">2</div>
        <h3>인증</h3>
        <p>실제 브라우저가 열려 조직에서 요구하는 MFA, SSO, SAML을 처리합니다.</p>
      </div>
      <div class="step-card" style="--i:3">
        <div class="step-number">3</div>
        <h3>연결</h3>
        <p>Claude, Cursor 또는 모든 MCP 클라이언트에 연결하세요. 77개의 등록된 도구가 활성 패키지 프로필을 통해 즉시 준비됩니다.</p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">주요 기능</span>
    <h2 class="section-title">엔터프라이즈 환경에 맞게 구축됨</h2>
    <p class="section-desc">
      AI 에이전트와 ServiceNow를<br>
      대규모로 안전하게 연결하는 데 필요한 모든 것을 제공합니다.
    </p>

    <div class="feature-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔒 제로 트러스트 보안</h3>
        <p>브라우저 기반 인증은 자격 증명이 절대 로컬 장치를 벗어나지 않음을 의미합니다. MFA, SSO, SAML 및 조직에서 사용하는 모든 로그인 흐름을 지원합니다.</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>⚡ 최적화된 성능</h3>
        <p>배치 쿼리, 연결 풀링, 응답 캐싱 및 토큰 효율적인 JSON은 지연 시간과 API 비용을 최소화합니다.</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>🧩 모듈식 스킬 패키지</h3>
        <p>인시던트, 변경 관리, 카탈로그, 포털, 워크플로우 및 스크립트 등 — 필요한 기능만 로드하거나 전체 제품군을 실행할 수 있습니다.</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🤖 다중 LLM 호환</h3>
        <p>Claude, ChatGPT, Gemini, Cursor 및 모델 컨텍스트 프로토콜(MCP)을 사용하는 모든 클라이언트에서 작동합니다.</p>
      </div>
    </div>

  </div>
</div>

<hr class="section-divider">

<div class="cta-banner reveal">
  <h2>AI를 ServiceNow에 연결할 준비 되셨나요?</h2>
  <p>단계별 가이드로 5분 안에 설정을 완료하세요.</p>
  <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">설정 가이드 보기</a>
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
