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
      अपने AI को स्क्रिप्ट मत कीजिए। <span class="gradient-text">उसे सशक्त बनाइए।</span>
    </h1>
    <p class="hero-subtitle">
      अपने AI को सरल भाषा में बताइए कि आपको क्या चाहिए।
      बाकी सब MCP स्किल्स संभाल लेंगी।
    </p>
    <div class="hero-buttons">
      <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">
        शुरू करें
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
    <span class="section-label">त्वरित शुरुआत</span>
    <h2 class="section-title">बस इसे पेस्ट कीजिए। बस इतना ही।</h2>
    <p class="section-desc">
      नीचे दी गई पंक्ति को किसी भी AI कोडिंग असिस्टेंट में कॉपी कीजिए।<br>
      यह सब कुछ स्वतः इंस्टॉल कर देता है — uv, Playwright, MCP कॉन्फ़िग, और स्किल्स।
    </p>
    <div class="install-block reveal">
      <div class="install-tabs">
        <button class="install-tab active" data-target="quick-ai">अपने AI में पेस्ट करें</button>
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
      Claude Code, Cursor, Codex, OpenCode, Windsurf, VS Code Copilot, Antigravity, Zed, और अन्य के साथ काम करता है।<br>
      आपका AI क्लाइंट और OS का पता लगाता है, फिर इंटरैक्टिव रूप से सेटअप में आपका मार्गदर्शन करता है।<br>
      सेटअप के बाद, MCP सर्वर लोड करने के लिए <strong>अपने AI क्लाइंट को पुनः आरंभ करें</strong>।
    </p>

    <p class="section-desc" style="margin-top:16px; font-size:0.9rem;">
      यदि <code>uvx</code> को कॉर्पोरेट सुरक्षा टूलिंग द्वारा अवरुद्ध किया गया है, तो नीचे दिए गए
      <a href="#local-install">लोकल इंस्टॉल (रिलीज़ ज़िप)</a> सेक्शन पर जाएँ।
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">मैनुअल — इंस्टॉल + कॉन्फ़िगर</span>
      <h2 class="section-title">इंस्टॉल करें, फिर अपने क्लाइंट कॉन्फ़िग में जोड़ें</h2>
      <p class="section-desc">
        टर्मिनल पसंद है? uv + Chromium इंस्टॉल करें, फिर सर्वर को अपनी MCP क्लाइंट कॉन्फ़िग फ़ाइल में जोड़ें (नीचे स्निपेट दिए गए हैं)। कोई इंस्टॉलर कमांड नहीं, कोई प्रति-क्लाइंट फ़्लैग नहीं।
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
      <span class="section-label">लोकल इंस्टॉल — ऑफ़लाइन-अनुकूल</span>
      <h2 class="section-title">रिलीज़ ज़िप से इंस्टॉल करें</h2>
      <p class="section-desc">
        इसका उपयोग तब करें जब <code>uvx</code> या PyPI अवरुद्ध हो। रिलीज़ ज़िप में एक PyInstaller से बना सिंगल-फ़ाइल एक्ज़ीक्यूटेबल आता है — Python की आवश्यकता नहीं, कोई इंस्टॉलर स्क्रिप्ट नहीं। प्लेटफ़ॉर्म ज़िप (और यदि Chromium डाउनलोड भी अवरुद्ध हो तो वैकल्पिक रूप से मिलान वाला <code>ms-playwright-chromium</code> ज़िप) <a href="https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest" target="_blank" rel="noopener">GitHub Releases</a> से लें, उसे एक्सट्रैक्ट करें, और अपने MCP क्लाइंट के <code>command</code> को एक्ज़ीक्यूटेबल पर इंगित करें।
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
      कोई इंस्टॉलर स्क्रिप्ट नहीं। आप एक्ज़ीक्यूटेबल को अपने नियंत्रण वाले किसी भी स्थिर फ़ोल्डर में अनज़िप करते हैं, Chromium ज़िप को <code>ms-playwright</code> नाम के एक सिबलिंग फ़ोल्डर में एक्सट्रैक्ट करते हैं, और एक्ज़ीक्यूटेबल स्टार्टअप पर उस लेआउट का स्वतः पता लगा लेता है — केवल वर्तमान प्रक्रिया के लिए <code>PLAYWRIGHT_BROWSERS_PATH</code> के माध्यम से Playwright को उस पर इंगित करता है। सिस्टम का मानक Playwright कैश (<code>~/.cache/ms-playwright</code>, <code>%LOCALAPPDATA%\ms-playwright</code>) अछूता रहता है, और आपकी MCP क्लाइंट कॉन्फ़िग आपके संपादन के लिए आपकी है — नीचे दिए गए <a href="#mcp-tabs">मैनुअल फ़ॉलबैक</a> सेक्शन से स्निपेट पेस्ट करें और <code>command</code> को एक्ज़ीक्यूटेबल के निरपेक्ष पथ पर सेट करें।
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">मैनुअल फ़ॉलबैक</span>
      <h2 class="section-title">क्लाइंट कॉन्फ़िग को मैन्युअल रूप से ठीक करें या जाँचें</h2>
      <p class="section-desc">
        इंस्टॉलर अनुशंसित रास्ता है। नीचे दिए गए रॉ कॉन्फ़िग उदाहरणों का उपयोग केवल तभी करें जब आपको किसी क्लाइंट कॉन्फ़िग को हाथ से जाँचना या ठीक करना हो।
      </p>
    </div>
    <p class="section-desc" style="margin-top:8px;font-size:0.9rem;opacity:0.8;">
      चार अलग-अलग आकार हर समर्थित क्लाइंट को कवर करते हैं। <code>env</code> ब्लॉक हर जगह समान है — केवल बाहरी रैपर अलग होता है।
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
      केवल-पढ़ने वाला <code>standard</code> पैकेज डिफ़ॉल्ट रूप से लोड होता है — किसी <code>MCP_TOOL_PACKAGE</code> की आवश्यकता नहीं।
      लिखने की पहुँच के लिए, इसे एक उन्नत पैकेज पर सेट करें (<code>service_desk</code>, <code>portal_developer</code>,
      <code>platform_developer</code>, या <code>full</code>) — देखें
      <a href="docs/TOOL_PACKAGES/">टूल पैकेज (उन्नत) गाइड</a>।
    </p>

    <div style="margin-top:56px;" class="reveal">
      <span class="section-label">मैनुअल — चरण 3</span>
      <h2 class="section-title">LLM-अनुकूलित स्किल्स जोड़ें</h2>
      <p class="section-desc">
        अकेले टूल्स केवल कच्चे API कॉल हैं। स्किल्स ही आपके LLM को वास्तव में उपयोगी बनाती हैं —
        सुरक्षा गेट्स, रोलबैक, और संदर्भ-जागरूक प्रत्यायोजन के साथ सत्यापित पाइपलाइनें।
        आज 4 स्किल्स, हर रिलीज़ के साथ और भी आ रही हैं।
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
        <p>5 स्किल्स — विजेट विश्लेषण, पोर्टल निदान, लोकल सोर्स ऑडिट, प्रोवाइडर ऑडिट, ESC पेज ऑडिट</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>🔧 fix/</h3>
        <p>3 स्किल्स — चरणबद्ध सुरक्षा गेट्स के साथ विजेट पैचिंग, डिबगिंग, कोड समीक्षा</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>📦 manage/</h3>
        <p>5 स्किल्स — ऐप सोर्स डाउनलोड, चेंजसेट वर्कफ़्लो, लोकल सिंक, वर्कफ़्लो प्रबंधन, स्किल प्रबंधन</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🚀 deploy/</h3>
        <p>1 स्किल — चेंज रिक्वेस्ट जीवनचक्र</p>
      </div>
      <div class="step-card" style="--i:5">
        <h3>🧭 explore/</h3>
        <p>2 स्किल्स — फ़्लो ट्रिगर ट्रेसिंग, ESC कैटलॉग फ़्लो</p>
      </div>
    </div>
  </div>
</div>

<div class="install-block reveal" style="margin-top:40px;">
  <span class="section-label">अद्यतन बनाए रखना</span>
  <h2 class="section-title">हमेशा नवीनतम संस्करण चलाएँ</h2>
  <p class="section-desc" style="margin-bottom:16px;">
    <code>uvx</code> अंतिम डाउनलोड किए गए संस्करण को कैश करता है — यह स्वतः अपडेट <strong>नहीं</strong> होता।<br>
    नवीनतम रिलीज़ पाने के लिए <code>uv</code> के माध्यम से अपग्रेड करें:
  </p>
  <div class="install-tabs"><button class="install-tab active">Terminal</button></div>
  <div class="install-code-block">
    <pre class="install-code"><code>uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version</code></pre>
  </div>
  <p class="section-desc" style="margin-top:12px;font-size:0.9em;">
    फिर नया संस्करण लोड करने के लिए अपने MCP क्लाइंट (Claude Code, Cursor, आदि) को पुनः आरंभ करें।
  </p>
</div>

<div class="hero-stats reveal">
  <div class="hero-stat">
    <span class="hero-stat-value">70</span>
    <span class="hero-stat-label">पंजीकृत टूल्स</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">MFA</span>
    <span class="hero-stat-label">मूल समर्थन</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">5</span>
    <span class="hero-stat-label">स्किल श्रेणियाँ</span>
  </div>
  <div class="hero-stat">
    <span class="hero-stat-value">0</span>
    <span class="hero-stat-label">साझा किए गए क्रेडेंशियल्स</span>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">यह कैसे काम करता है</span>
    <h2 class="section-title">प्रोडक्शन तक तीन चरण</h2>
    <p class="section-desc">
      कॉन्फ़िगर करने के लिए कोई API कुंजी नहीं, कॉन्फ़िग फ़ाइलों में कोई पासवर्ड नहीं।
      अपने ब्राउज़र के माध्यम से एक बार प्रमाणित करें, और आपका AI एजेंट एक लाइव सत्र विरासत में पा लेता है।
    </p>
    <div class="steps-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <div class="step-number">1</div>
        <h3>इंस्टॉल करें</h3>
        <p><code>uvx</code> के साथ एक कमांड सब कुछ सेट कर देती है। शून्य कॉन्फ़िग।</p>
      </div>
      <div class="step-card" style="--i:2">
        <div class="step-number">2</div>
        <h3>प्रमाणित करें</h3>
        <p>MFA, SSO, SAML के लिए एक वास्तविक ब्राउज़र खुलता है — जो भी आपका संगठन माँगता है।</p>
      </div>
      <div class="step-card" style="--i:3">
        <div class="step-number">3</div>
        <h3>कनेक्ट करें</h3>
        <p>Claude, Cursor, Zed, या किसी भी MCP क्लाइंट को इंगित करें। सक्रिय पैकेज प्रोफ़ाइल के माध्यम से 70 पंजीकृत टूल्स लोड होते हैं।</p>
      </div>
    </div>
  </div>
</div>

<hr class="section-divider">

<div class="section reveal">
  <div class="section-inner">
    <span class="section-label">विशेषताएँ</span>
    <h2 class="section-title">एंटरप्राइज़ के लिए निर्मित</h2>
    <p class="section-desc">
      AI एजेंट्स और ServiceNow को बड़े पैमाने पर सुरक्षित रूप से जोड़ने के लिए आवश्यक सब कुछ।
    </p>

    <div class="feature-grid reveal-stagger">
      <div class="step-card" style="--i:1">
        <h3>🔒 ज़ीरो-ट्रस्ट सुरक्षा</h3>
        <p>ब्राउज़र-आधारित प्रमाणीकरण का अर्थ है कि क्रेडेंशियल्स कभी आपकी मशीन से बाहर नहीं जाते। MFA, SSO, SAML, और आपके संगठन द्वारा उपयोग किए जाने वाले किसी भी लॉगिन फ़्लो का समर्थन करता है।</p>
      </div>
      <div class="step-card" style="--i:2">
        <h3>⚡ टोकन-कुशल प्रदर्शन</h3>
        <p>लेज़ी टूल खोज, पैकेज-स्कोप्ड स्कीमा, कॉम्पैक्ट JSON, रिस्पॉन्स कैशिंग, और बैच्ड रीड्स स्टार्टअप और LLM संदर्भ लागत को नियंत्रण में रखते हैं।</p>
      </div>
      <div class="step-card" style="--i:3">
        <h3>🧩 सुरक्षित डेटा तुलना</h3>
        <p>वैकल्पिक नामित इंस्टेंसेस केवल-पढ़ने वाली dev/test ड्रिफ़्ट जाँच तक सीमित हैं। सामान्य टूल्स एक सक्रिय इंस्टेंस पर ही पिन रहते हैं।</p>
      </div>
      <div class="step-card" style="--i:4">
        <h3>🤖 व्यापक क्लाइंट समर्थन</h3>
        <p>Claude, Codex, Cursor, Zed, Antigravity, OpenCode, Windsurf, VS Code Copilot, और stdio या Streamable HTTP पर MCP क्लाइंट्स के साथ काम करता है।</p>
      </div>
    </div>

  </div>
</div>

<hr class="section-divider">

<div class="cta-banner reveal">
  <h2>अपने AI को ServiceNow से जोड़ने के लिए तैयार हैं?</h2>
  <p>हमारी चरण-दर-चरण गाइड के साथ पाँच मिनट से भी कम समय में सेटअप करें।</p>
  <a href="docs/CLIENT_SETUP/" class="md-button md-button--primary">सेटअप गाइड पढ़ें</a>
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
