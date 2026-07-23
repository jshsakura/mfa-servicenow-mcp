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
      No programes tu IA. <span class="gradient-text">Ármala.</span>
    </h1>
    <p class="hero-subtitle">
      Dile a tu IA lo que necesitas en lenguaje natural.
      Las Skills de MCP se encargan del resto.
    </p>
    <div class="hero-buttons">
      <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
        Comenzar
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
    <span class="section-label">Inicio rápido</span>
    <h2 class="section-title">Solo pega esto. Eso es todo.</h2>
    <p class="section-desc">
      Copia la línea de abajo en cualquier asistente de programación con IA.<br>
      Instala todo — uv, Playwright, configuración de MCP y skills — automáticamente.
    </p>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="quick-ai">Pega esto en tu IA</button>
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
      Funciona con Claude Code, Cursor, Codex, OpenCode, Windsurf, VS Code Copilot, Antigravity, Zed y más.<br>
      Tu IA detecta el cliente y el sistema operativo, y luego te guía por la configuración de forma interactiva.<br>
      Tras la configuración, <strong>reinicia tu cliente de IA</strong> para cargar el servidor MCP.
    </p>

    <p class="section-desc" style="margin-top:16px; font-size:0.9rem;">
      Si <code>uvx</code> está bloqueado por las herramientas de seguridad corporativas, salta a la sección
      <a href="#local-install">Si uvx está bloqueado (pip)</a> más abajo.
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">Manual — instalar + configurar</span>
      <h2 class="section-title">Instala y luego añádelo a la configuración de tu cliente</h2>
      <p class="section-desc">
        ¿Prefieres la terminal? Instala uv + Chromium y luego añade el servidor al archivo de configuración de tu cliente MCP (fragmentos abajo). Sin comando de instalación, sin opciones específicas por cliente.
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
      <span class="section-label">Si uvx está bloqueado</span>
      <h2 class="section-title">Instala con pip en su lugar</h2>
      <p class="section-desc">
        El Smart App Control de Windows bloquea <code>uvx</code>, porque uvx descomprime un ejecutable temporal sin firmar en cada ejecución. Si uvx te funcionaba hasta hace poco y dejó de hacerlo justo después de una actualización de Windows, esta es la razón. Instala con pip y arranca el servidor como módulo — el script de consola <code>servicenow-mcp</code> es un envoltorio <code>.exe</code> sin firmar generado por pip, y queda bloqueado por el mismo motivo.
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
            <pre class="install-code"><code><span class="c"># Homebrew y los Python de distribución rechazan las instalaciones globales de pip (PEP 668).</span>
<span class="c"># Usa un Python de python.org, o simplemente quédate con uvx de arriba.</span>
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium

<span class="c"># Verifica:</span>
python -m servicenow_mcp --version

<span class="c"># Para actualizar más adelante:</span>
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium</code></pre>
          </div>
        </div>
        <div class="install-panel" id="local-win">
          <div class="install-code-block">
            <pre class="install-code"><code><span class="c"># Python 3.10+ de python.org está firmado y pasa Smart App Control.</span>
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium

<span class="c"># Verifica:</span>
python -m servicenow_mcp --version

<span class="c"># Para actualizar más adelante:</span>
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium</code></pre>
          </div>
        </div>
      </div>
    </div>
    <p class="section-desc" style="margin-top:16px; font-size:0.9rem; opacity:0.8;">
      El bloque <code>env</code> es idéntico en ambos casos — solo cambian <code>command</code> y <code>args</code>. Pega el fragmento de la sección <a href="#mcp-tabs">Manual de respaldo</a> de abajo y luego establece <code>command</code> en <code>python</code> y <code>args</code> en <code>["-m", "servicenow_mcp"]</code>.
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">Manual de respaldo</span>
      <h2 class="section-title">Repara o inspecciona la configuración del cliente manualmente</h2>
      <p class="section-desc">
        El instalador es la vía recomendada. Usa los ejemplos de configuración en bruto de abajo solo si necesitas inspeccionar o reparar la configuración de un cliente a mano.
      </p>
    </div>
    <p class="section-desc" style="margin-top:8px;font-size:0.9rem;opacity:0.8;">
      Cuatro formas distintas cubren todos los clientes compatibles. El bloque <code>env</code> es idéntico en todas partes — solo difiere el contenedor externo.
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
      El paquete de solo lectura <code>standard</code> se carga por defecto — no se necesita <code>MCP_TOOL_PACKAGE</code>.
      Para acceso de escritura, configúralo con un paquete avanzado (<code>service_desk</code>, <code>portal_developer</code>,
      <code>platform_developer</code> o <code>full</code>) — consulta la
      <a href="docs/TOOL_PACKAGES/">guía de Paquetes de herramientas (Avanzado)</a>.
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">Manual — Paso 3</span>
      <h2 class="section-title">Añade skills optimizadas para LLM</h2>
      <p class="section-desc">
        Las herramientas por sí solas son llamadas API en bruto. Las skills son lo que hace que tu LLM sea realmente útil —
        pipelines verificados con controles de seguridad, reversión y delegación contextual.
        4 skills hoy, y más con cada release.
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
        <p>1 skill — auditoría de fuentes locales: referencias cruzadas, código muerto, orden de ejecución, informe HTML</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>🧭 explore/</h3>
        <p>1 skill — trazado de triggers de flujo: qué workflows/flujos se activan cuando cambia una tabla</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>📦 manage/</h3>
        <p>2 skills — descarga de fuentes de la app, sincronización local (diff → push con detección de conflictos)</p>
      </div>
    </div>
  </div>
</div>

<div class="install-block reveal" style="margin-top:40px;">
  <span class="section-label">Mantente actualizado</span>
  <h2 class="section-title">Ejecuta siempre la última versión</h2>
  <p class="section-desc" style="margin-bottom:16px;">
    <code>uvx</code> almacena en caché la última versión descargada — <strong>no</strong> se actualiza automáticamente.<br>
    Actualiza mediante <code>uv</code> para obtener el último release:
  </p>
  <div class="install-tabs"><button class="install-tab active">Terminal</button></div>
  <div class="install-code-block">
    <pre class="install-code"><code>uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version</code></pre>
  </div>
  <p class="section-desc" style="margin-top:12px;font-size:0.9em;">
    Luego reinicia tu cliente MCP (Claude Code, Cursor, etc.) para cargar la nueva versión.
  </p>
</div>

<div class="hero-stats reveal">
  <div class="hero-stat">
    <span class="hero-stat-value">66</span>
    <span class="hero-stat-label">Herramientas registradas</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">MFA</span>
    <span class="hero-stat-label">Soporte nativo</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">3</span>
    <span class="hero-stat-label">Categorías de skills</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">0</span>
    <span class="hero-stat-label">Credenciales compartidas</span>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">Cómo funciona</span>
    <h2 class="section-title">Tres pasos a producción</h2>
    <p class="section-desc">
      Sin claves API que configurar, sin contraseñas en archivos de configuración.
      Autentícate una vez a través de tu navegador, y tu agente de IA hereda una sesión activa.
    </p>
    <div class="steps-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <div class="step-number">1</div>
        <h3>Instalar</h3>
        <p>Un solo comando con <code>uvx</code> configura todo. Cero configuración.</p>
      </div>
      <div class="step-card" style="--i:2">
        <div class="step-number">2</div>
        <h3>Autenticar</h3>
        <p>Se abre un navegador real para MFA, SSO, SAML — lo que sea que requiera tu organización.</p>
      </div>
      <div class="step-card" style="--i:3">
        <div class="step-number">3</div>
        <h3>Conectar</h3>
        <p>Apunta Claude, Cursor, Zed o cualquier cliente MCP. 66 herramientas registradas se cargan mediante perfiles de paquete activos.</p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">Características</span>
    <h2 class="section-title">Diseñado para la empresa</h2>
    <p class="section-desc">
      Todo lo que necesitas para conectar agentes de IA y ServiceNow de forma segura a escala.
    </p>

    <div class="feature-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔒 Seguridad Zero-Trust</h3>
        <p>La autenticación basada en navegador significa que las credenciales nunca salen de tu máquina. Compatible con MFA, SSO, SAML y cualquier flujo de inicio de sesión que use tu organización.</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>⚡ Rendimiento eficiente en tokens</h3>
        <p>El descubrimiento perezoso de herramientas, los esquemas acotados por paquete, el JSON compacto, el almacenamiento en caché de respuestas y las lecturas por lotes mantienen bajo control el arranque y el coste de contexto del LLM.</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>🧩 Comparación segura de datos</h3>
        <p>Las instancias nombradas opcionales se limitan a comprobaciones de deriva de solo lectura entre dev/test. Las herramientas ordinarias permanecen ancladas a una única instancia activa.</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🤖 Amplio soporte de clientes</h3>
        <p>Funciona con Claude, Codex, Cursor, Zed, Antigravity, OpenCode, Windsurf, VS Code Copilot y clientes MCP sobre stdio o Streamable HTTP.</p>
      </div>
    </div>

  </div>
</div>

<hr class="section-divider">

<div class="cta-banner reveal">
  <h2>¿Listo para conectar tu IA a ServiceNow?</h2>
  <p>Configúralo en menos de cinco minutos con nuestra guía paso a paso.</p>
  <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">Leer la guía de configuración</a>
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
    { type:"success", text:"✓ Authenticated with ServiceNow (MFA verified)", speed:10 },
    { type:"pause", ms:700 },
    { type:"prompt", prompt:"Claude › ", text:"\"Trace the route for /hr?id=onboarding\"", speed:26 },
    { type:"pause", ms:400 },
    { type:"thinking", text:"Analyzing portal route and widget layout…", speed:14 },
    { type:"pause", ms:250 },
    { type:"tool", text:"⚙ servicenow_get_portal", dim:" portal_id=hr", speed:6 },
    { type:"tool", text:"⚙ servicenow_get_page", dim:" page_id=onboarding", speed:6 },
    { type:"tool", text:"⚙ servicenow_trace_portal_route_targets", dim:" match=onboarding", speed:6 },
    { type:"pause", ms:500 },
    { type:"success", text:"✓ Route resolved — 4 widgets found, upstream: onboardingHeroWd", speed:10 }
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
