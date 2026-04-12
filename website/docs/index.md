---
hide:
  - navigation
  - toc
---

<div class="hero-section">
  <div class="hero-bg-img"></div>
  <div class="hero-overlay"></div>
  <div class="hero-content">
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
      <a href="https://github.com/jshsakura/mfa-servicenow-mcp" class="md-button md-button--ghost">
        View on GitHub
      </a>
    </div>
  </div>
</div>

<div class="content-wrap">

<div class="hero-terminal">
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

<hr class="section-divider">

<div class="section" id="install">
  <div class="section-inner">
    <span class="section-label">Quick install</span>
    <h2 class="section-title">Copy, paste, run</h2>
    <p class="section-desc">
      Pick your OS. One command installs the server and opens a browser for MFA login.
    </p>
    <div class="install-block">
      <div class="install-tabs">
        <button class="install-tab active" data-target="install-mac">macOS / Linux</button>
        <button class="install-tab" data-target="install-win">Windows</button>
        <button class="install-tab" data-target="install-pip">pip</button>
        <button class="install-tab" data-target="install-dev">Dev</button>
      </div>
      <div class="install-panels">
        <div class="install-panel active" id="install-mac">
          <div class="install-code-block">
            <div class="install-code-header">
              <span class="install-code-label">Terminal</span>
              <button class="install-copy-btn" aria-label="Copy">Copy</button>
            </div>
            <pre class="install-code"><code><span class="c"># Install uv (if not already installed)</span>
curl -LsSf https://astral.sh/uv/install.sh | sh

<span class="c"># Run the MCP server (auto-installs dependencies)</span>
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
            <pre class="install-code"><code><span class="c"># Install uv (if not already installed)</span>
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

<span class="c"># Run the MCP server (auto-installs dependencies)</span>
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
            <pre class="install-code"><code><span class="c"># Install with pip + browser support</span>
pip install "mfa-servicenow-mcp[browser]"
playwright install chromium

<span class="c"># Run the MCP server</span>
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
            <pre class="install-code"><code><span class="c"># Clone and install in development mode</span>
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp
uv pip install -e ".[browser]"
playwright install chromium

<span class="c"># Run the MCP server</span>
servicenow-mcp \
  --instance-url https://YOUR_INSTANCE.service-now.com</code></pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section">
  <div class="section-inner">
    <span class="section-label">How it works</span>
    <h2 class="section-title">Three steps to production</h2>
    <p class="section-desc">
      No API keys to configure, no passwords in config files.
      Authenticate once through your browser, and your AI agent inherits a live session.
    </p>
    <div class="steps-grid">
      <div class="step-card">
        <div class="step-number">1</div>
        <h3>Install</h3>
        <p>One command with <code>uvx</code> sets everything up. Zero config.</p>
      </div>
      <div class="step-card">
        <div class="step-number">2</div>
        <h3>Authenticate</h3>
        <p>A real browser opens for MFA, SSO, SAML — whatever your org requires.</p>
      </div>
      <div class="step-card">
        <div class="step-number">3</div>
        <h3>Connect</h3>
        <p>Point Claude, Cursor, or any MCP client. 89+ tools ready instantly.</p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section">
  <div class="section-inner">
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

</div>

<script>
(function(){
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
    { type:"success", text:"\u2713 Route resolved \u2014 4 widgets found, upstream: newEmployeeRequestWd", speed:10 }
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

(function(){
  document.querySelectorAll(".install-tab").forEach(function(tab){
    tab.addEventListener("click",function(){
      document.querySelectorAll(".install-tab").forEach(function(t){t.classList.remove("active");});
      tab.classList.add("active");
      document.querySelectorAll(".install-panel").forEach(function(p){p.classList.remove("active");});
      var t=document.getElementById(tab.getAttribute("data-target"));
      if(t) t.classList.add("active");
    });
  });
  document.querySelectorAll(".install-copy-btn").forEach(function(btn){
    btn.addEventListener("click",function(){
      var code=btn.closest(".install-code-block").querySelector("code");
      var text=code.textContent.replace(/^#.*$/gm,"").replace(/\n{2,}/g,"\n").trim();
      navigator.clipboard.writeText(text).then(function(){
        btn.textContent="Copied!";setTimeout(function(){btn.textContent="Copy";},2000);
      });
    });
  });
})();
</script>
