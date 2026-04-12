---
hide:
  - navigation
  - toc
---

<script>document.body.classList.add("landing");</script>

<div class="hero-section">
  <div class="hero-bg-img"></div>
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <h1 class="hero-title">
      Stop giving your LLM a script.<br>
      <span class="gradient-text">Give it a gun.</span>
    </h1>
    <p class="hero-subtitle">
      Equip your LLM with high-caliber MCP Skills<br>
      to hunt down bottlenecks, execute with surgical precision,<br>
      and turn manual toil into strategic fire.
    </p>
    <div class="hero-buttons">
      <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
        Get Started
      </a>
      <a href="https://github.com/jshsakura/mfa-servicenow-mcp" class="md-button md-button--ghost">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
        GitHub
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

<div class="section" id="install" style="padding-top:48px;">
  <div class="section-inner">
    <span class="section-label">Step 1 — Server</span>
    <h2 class="section-title">Install and connect</h2>
    <p class="section-desc">
      Pick your OS. A real Chromium browser opens for MFA/SSO login — Okta, Entra ID, SAML all work out of the box.
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
            <pre class="install-code"><code><span class="c"># Install uv (if not already installed)</span>
curl -LsSf https://astral.sh/uv/install.sh | sh

<span class="c"># Run with MFA browser login (Okta, Entra ID, SAML supported)</span>
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://YOUR_INSTANCE.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"</code></pre>
          </div>
        </div>
        <div class="install-panel" id="install-win">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Install uv (if not already installed)</span>
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

<span class="c"># Run with MFA browser login (Okta, Entra ID, SAML supported)</span>
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp `
  --instance-url "https://YOUR_INSTANCE.service-now.com" `
  --auth-type "browser" `
  --browser-headless "false"</code></pre>
          </div>
        </div>
        <div class="install-panel" id="install-pip">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Install with pip + browser auth support</span>
pip install "mfa-servicenow-mcp[browser]"
playwright install chromium

<span class="c"># Run with MFA browser login</span>
servicenow-mcp \
  --instance-url "https://YOUR_INSTANCE.service-now.com" \
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
  --instance-url "https://YOUR_INSTANCE.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"</code></pre>
          </div>
        </div>
      </div>
    </div>

    <div style="margin-top:56px;">
      <span class="section-label">Client config</span>
      <h2 class="section-title">Paste into your AI client</h2>
      <p class="section-desc">
        Paste the config for your client. All use the same MCP server — only the format differs.
      </p>
    </div>
    <div class="install-block">
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
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://YOUR_INSTANCE.service-now.com",
        "--auth-type", "browser"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-claude-code">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c">// Option A: CLI one-liner</span>
claude mcp add servicenow -- \
  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://YOUR_INSTANCE.service-now.com" \
  --auth-type "browser"

<span class="c">// Option B: .mcp.json in project root</span>
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://YOUR_INSTANCE.service-now.com",
        "--auth-type", "browser"
      ],
      "env": { "MCP_TOOL_PACKAGE": "standard" }
    }
  }
}</code></pre>
          </div>
        </div>
        <div class="install-panel" id="mcp-codex">
          <div class="install-code-block">
            <pre class="install-code"><code>[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://YOUR_INSTANCE.service-now.com",
  "--auth-type", "browser",
  "--tool-package", "standard",
]</code></pre>
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
        "SERVICENOW_INSTANCE_URL": "https://YOUR_INSTANCE.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
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
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://YOUR_INSTANCE.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
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
        "SERVICENOW_INSTANCE_URL": "https://YOUR_INSTANCE.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}</code></pre>
          </div>
        </div>
      </div>
    </div>

    <div style="margin-top:56px;">
      <span class="section-label">Step 2 — Skills</span>
      <h2 class="section-title">Add LLM-optimized skills</h2>
      <p class="section-desc">
        Tools alone are raw API calls. Skills are what make your LLM actually useful —
        verified pipelines with safety gates, rollback, and context-aware delegation.
        20 skills today, more coming with every release.
      </p>
    </div>
    <div class="install-block">
      <div class="install-tabs" id="skill-tabs">
        <button class="install-tab active" data-target="skill-claude">Claude Code</button>
        <button class="install-tab" data-target="skill-codex">Codex</button>
        <button class="install-tab" data-target="skill-opencode">OpenCode</button>
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
      </div>
    </div>
    <div class="skill-categories">
      <div class="step-card">
        <h3>analyze/</h3>
        <p>6 skills — widget analysis, portal diagnosis, dependency mapping, code detection</p>
      </div>
      <div class="step-card">
        <h3>fix/</h3>
        <p>3 skills — widget patching with staged safety gates, debugging, code review</p>
      </div>
      <div class="step-card">
        <h3>manage/</h3>
        <p>5 skills — page layout, script includes, source export, changeset workflow</p>
      </div>
      <div class="step-card">
        <h3>deploy/</h3>
        <p>2 skills — change request lifecycle, incident triage</p>
      </div>
      <div class="step-card">
        <h3>explore/</h3>
        <p>4 skills — health check, schema discovery, route tracing, ESC catalog flow</p>
      </div>
    </div>
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
</script>
