---
hide:
  - navigation
  - toc
---

<div class="hero-section">
  <div class="hero-badge">
    <span class="badge-dot"></span>
    Open Source &middot; Enterprise Ready
  </div>

  <h1 class="hero-title">
    Secure ServiceNow<br>
    for <span class="gradient-text">AI Agents</span>
  </h1>
  <p class="hero-subtitle">
    The MFA-first MCP server that gives your AI agents secure,
    high-performance access to ServiceNow — no credentials shared.
  </p>

  <div class="hero-buttons">
    <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
      Get Started
    </a>
    <a href="https://github.com/jshsakura/mfa-servicenow-mcp" class="md-button">
      View on GitHub
    </a>
  </div>

  <div class="hero-banner">
    <img src="assets/images/banner.jpg" alt="MFA ServiceNow MCP — The Guardian of Your ServiceNow Access">
    <div class="hero-banner-overlay">
      <span class="hero-banner-tag">You shall not pass... without MFA</span>
    </div>
  </div>

  <div class="hero-terminal">
    <div class="hero-terminal-header">
      <div class="hero-terminal-dot red"></div>
      <div class="hero-terminal-dot yellow"></div>
      <div class="hero-terminal-dot green"></div>
      <span class="hero-terminal-title">mfa-servicenow-mcp</span>
    </div>
    <div class="hero-terminal-body" id="hero-typed-terminal">
      <!-- Lines will be injected by JS animation -->
    </div>
  </div>

  <div class="hero-stats">
    <div class="hero-stat">
      <span class="hero-stat-value">89+</span>
      <span class="hero-stat-label">MCP Tools</span>
    </div>
    <div class="hero-stat">
      <span class="hero-stat-value">MFA</span>
      <span class="hero-stat-label">Native Support</span>
    </div>
    <div class="hero-stat">
      <span class="hero-stat-value">6</span>
      <span class="hero-stat-label">Skill Packages</span>
    </div>
    <div class="hero-stat">
      <span class="hero-stat-value">0</span>
      <span class="hero-stat-label">Credentials Shared</span>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="how-section">
  <div class="how-section-inner">
    <span class="section-label">How it works</span>
    <h2 class="section-title">From install to production<br>in three steps</h2>
    <p class="section-desc">
      No API keys to configure, no passwords to paste into config files.
      Authenticate once through your browser, and your AI agent inherits a live session.
    </p>
    <div class="steps-grid">
      <div class="step-card">
        <div class="step-number">1</div>
        <h3>Install</h3>
        <p>
          One command sets everything up. Works with <code>uvx</code>, <code>pip</code>,
          or clone-and-run for development.
        </p>
      </div>
      <div class="step-card">
        <div class="step-number">2</div>
        <h3>Authenticate</h3>
        <p>
          A real Chromium browser opens for you to log in — MFA, SSO, SAML, whatever
          your org requires. No passwords stored.
        </p>
      </div>
      <div class="step-card">
        <div class="step-number">3</div>
        <h3>Connect</h3>
        <p>
          Point Claude, Cursor, or any MCP-compatible client at the server.
          Your AI agent gets 89+ ServiceNow tools instantly.
        </p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="install-section">
  <div class="install-section-inner">
    <span class="section-label">Quick install</span>
    <h2 class="section-title">Copy, paste, run</h2>
    <p class="section-desc">
      Pick your OS. One command installs the server and opens a browser for MFA login.
    </p>
    <div class="install-tabs">
      <button class="install-tab active" data-target="install-mac">macOS / Linux</button>
      <button class="install-tab" data-target="install-win">Windows</button>
      <button class="install-tab" data-target="install-pip">pip</button>
      <button class="install-tab" data-target="install-dev">Dev (source)</button>
    </div>
    <div class="install-panels">
      <div class="install-panel active" id="install-mac">
        <div class="install-code-block">
          <div class="install-code-header">
            <span class="install-code-label">Terminal</span>
            <button class="install-copy-btn" aria-label="Copy">Copy</button>
          </div>
          <pre class="install-code"><code><span class="install-comment"># Install uv (if not already installed)</span>
curl -LsSf https://astral.sh/uv/install.sh | sh

<span class="install-comment"># Run the MCP server (auto-installs dependencies)</span>
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url https://YOUR_INSTANCE.service-now.com</code></pre>
        </div>
      </div>
      <div class="install-panel" id="install-win">
        <div class="install-code-block">
          <div class="install-code-header">
            <span class="install-code-label">PowerShell</span>
            <button class="install-copy-btn" aria-label="Copy">Copy</button>
          </div>
          <pre class="install-code"><code><span class="install-comment"># Install uv (if not already installed)</span>
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

<span class="install-comment"># Run the MCP server (auto-installs dependencies)</span>
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp `
  --instance-url https://YOUR_INSTANCE.service-now.com</code></pre>
        </div>
      </div>
      <div class="install-panel" id="install-pip">
        <div class="install-code-block">
          <div class="install-code-header">
            <span class="install-code-label">Terminal</span>
            <button class="install-copy-btn" aria-label="Copy">Copy</button>
          </div>
          <pre class="install-code"><code><span class="install-comment"># Install with pip + browser support</span>
pip install "mfa-servicenow-mcp[browser]"
playwright install chromium

<span class="install-comment"># Run the MCP server</span>
servicenow-mcp \
  --instance-url https://YOUR_INSTANCE.service-now.com</code></pre>
        </div>
      </div>
      <div class="install-panel" id="install-dev">
        <div class="install-code-block">
          <div class="install-code-header">
            <span class="install-code-label">Terminal</span>
            <button class="install-copy-btn" aria-label="Copy">Copy</button>
          </div>
          <pre class="install-code"><code><span class="install-comment"># Clone and install in development mode</span>
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp
uv pip install -e ".[browser]"
playwright install chromium

<span class="install-comment"># Run the MCP server</span>
servicenow-mcp \
  --instance-url https://YOUR_INSTANCE.service-now.com</code></pre>
        </div>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="features-section">
  <div class="features-section-inner">
    <span class="section-label">Features</span>
    <h2 class="section-title">Built for the enterprise</h2>
    <p class="section-desc">
      Everything you need to bridge AI agents and ServiceNow securely at scale.
    </p>

<div class="grid cards" markdown>

-   :material-shield-lock:{ .lg .middle } __Zero-Trust Security__

    Browser-based auth means credentials never leave your machine. Supports MFA, SSO, SAML, and any login flow your org uses.

-   :material-lightning-bolt:{ .lg .middle } __Optimized Performance__

    Batch queries, connection pooling, response caching, and token-efficient JSON keep latency and API costs to a minimum.

-   :material-puzzle:{ .lg .middle } __Modular Skill Packages__

    Incidents, Changes, Catalog, Portals, Workflows, and Scripts — load only what you need or run the full suite.

-   :material-robot:{ .lg .middle } __Multi-LLM Compatible__

    Works with Claude, ChatGPT, Gemini, Cursor, and any client that speaks the Model Context Protocol.

</div>

  </div>
</div>

<hr class="section-divider">

<div class="cta-banner">
  <h2>Ready to connect your AI to ServiceNow?</h2>
  <p>Get set up in under five minutes with our step-by-step guide.</p>
  <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">Read the Setup Guide</a>
</div>

<script>
(function(){
  var lines = [
    { type: "prompt", prompt: "$ ", text: "uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp", speed: 28 },
    { type: "pause", ms: 600 },
    { type: "success", text: "\u2713 Authenticated with ServiceNow (MFA verified)", speed: 12 },
    { type: "pause", ms: 800 },
    { type: "prompt", prompt: "Claude \u203a ", text: "\"Trace the route for /hr?id=onboarding\"", speed: 32 },
    { type: "pause", ms: 500 },
    { type: "thinking", text: "Analyzing portal route and widget layout\u2026", speed: 18 },
    { type: "pause", ms: 300 },
    { type: "tool", text: "\u2699 servicenow_get_portal", dim: " portal_id=hr", speed: 8 },
    { type: "tool", text: "\u2699 servicenow_get_page", dim: " page_id=onboarding", speed: 8 },
    { type: "tool", text: "\u2699 servicenow_trace_portal_route_targets", dim: " match=onboarding", speed: 8 },
    { type: "pause", ms: 600 },
    { type: "success", text: "\u2713 Route resolved \u2014 4 widgets found, upstream: newEmployeeRequestWd", speed: 14 }
  ];

  var container = document.getElementById("hero-typed-terminal");
  if (!container) return;

  var classMap = {
    prompt: "hero-terminal-command",
    success: "hero-terminal-success",
    thinking: "hero-terminal-thinking",
    tool: "hero-terminal-tool"
  };

  function createLine(cfg) {
    var div = document.createElement("div");
    div.className = "hero-terminal-line";
    if (cfg.type === "prompt") {
      var ps = document.createElement("span");
      ps.className = "hero-terminal-prompt";
      ps.textContent = cfg.prompt;
      div.appendChild(ps);
    }
    var span = document.createElement("span");
    span.className = classMap[cfg.type] || "";
    div.appendChild(span);
    if (cfg.dim) {
      var ds = document.createElement("span");
      ds.className = "hero-terminal-dim";
      div.appendChild(ds);
    }
    return { el: div, span: span, dimSpan: cfg.dim ? div.lastChild : null, text: cfg.text, dim: cfg.dim || "", speed: cfg.speed };
  }

  function typeLine(info, cb) {
    container.appendChild(info.el);
    container.scrollTop = container.scrollHeight;
    var i = 0, full = info.text;
    function tick() {
      if (i <= full.length) {
        info.span.textContent = full.slice(0, i);
        i++;
        setTimeout(tick, info.speed);
      } else {
        if (info.dimSpan && info.dim) {
          info.dimSpan.textContent = info.dim;
        }
        cb();
      }
    }
    tick();
  }

  function run(idx) {
    if (idx >= lines.length) {
      // add blinking cursor then restart after a delay
      var cursor = document.createElement("div");
      cursor.className = "hero-terminal-line";
      var cp = document.createElement("span");
      cp.className = "hero-terminal-prompt";
      cp.textContent = "$ ";
      cursor.appendChild(cp);
      var cc = document.createElement("span");
      cc.className = "hero-terminal-cursor";
      cursor.appendChild(cc);
      container.appendChild(cursor);
      setTimeout(function() {
        container.innerHTML = "";
        run(0);
      }, 4000);
      return;
    }
    var cfg = lines[idx];
    if (cfg.type === "pause") {
      setTimeout(function() { run(idx + 1); }, cfg.ms);
    } else {
      typeLine(createLine(cfg), function() { run(idx + 1); });
    }
  }

  // start when visible
  if ("IntersectionObserver" in window) {
    var obs = new IntersectionObserver(function(entries) {
      if (entries[0].isIntersecting) { obs.disconnect(); run(0); }
    }, { threshold: 0.3 });
    obs.observe(container);
  } else {
    run(0);
  }
})();

// --- Install tabs ---
(function(){
  var tabs = document.querySelectorAll(".install-tab");
  tabs.forEach(function(tab) {
    tab.addEventListener("click", function() {
      tabs.forEach(function(t) { t.classList.remove("active"); });
      tab.classList.add("active");
      document.querySelectorAll(".install-panel").forEach(function(p) {
        p.classList.remove("active");
      });
      var target = document.getElementById(tab.getAttribute("data-target"));
      if (target) target.classList.add("active");
    });
  });

  // --- Copy buttons ---
  document.querySelectorAll(".install-copy-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var code = btn.closest(".install-code-block").querySelector("code");
      var text = code.textContent.replace(/^#.*$/gm, "").replace(/\n{2,}/g, "\n").trim();
      navigator.clipboard.writeText(text).then(function() {
        btn.textContent = "Copied!";
        setTimeout(function() { btn.textContent = "Copy"; }, 2000);
      });
    });
  });
})();
</script>
