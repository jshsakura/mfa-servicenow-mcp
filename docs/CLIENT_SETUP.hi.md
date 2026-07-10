# MCP क्लाइंट कॉन्फ़िगरेशन

प्रत्येक MCP क्लाइंट के लिए विस्तृत सेटअप। सभी क्लाइंट एक ही MCP सर्वर का उपयोग करते हैं — केवल कॉन्फ़िग प्रारूप भिन्न होता है।

> **पहले अनुशंसित:** नीचे दिए गए `uvx` सेटअप कमांड का उपयोग करें। यदि `uvx` को कॉर्पोरेट सुरक्षा टूलिंग द्वारा अवरुद्ध किया गया हो, तो release zip/exe अनुभाग का उपयोग करें।

---

## शुरू करने से पहले

डिफ़ॉल्ट रूप से `uvx` का उपयोग करें। यह macOS, Linux और Windows पर इंस्टॉल और क्लाइंट कॉन्फ़िग को एक समान रखता है।

### 1. uv इंस्टॉल करें

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. सर्वर फ़ेच करें + Chromium इंस्टॉल करें

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

पहला कमांड सर्वर को ठीक उसी `--with playwright` एनवायरनमेंट में पहले से फ़ेच और सत्यापित करता है जिसका क्लाइंट उपयोग करता है, ताकि पहली शुरुआत तत्काल हो। दूसरा कमांड Chromium डाउनलोड करता है; `uvx` मानक कैश में पहले से मौजूद किसी मेल खाते Chromium का पुनः उपयोग करता है।

### 3. अपने MCP क्लाइंट कॉन्फ़िग में सर्वर जोड़ें

अपने क्लाइंट की कॉन्फ़िग फ़ाइल में एक प्रविष्टि जोड़ें (किसी इंस्टॉलर कमांड की आवश्यकता नहीं):

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

प्रति-क्लाइंट फ़ाइल पथ और प्रारूप (Codex TOML, आदि) नीचे दिए गए हैं; उसके बाद क्लाइंट को पुनः आरंभ करें।

### स्थानीय इंस्टॉल (release zip/exe)

इसका उपयोग तब करें जब `uvx` या PyPI अवरुद्ध हो। release zip एक एकल PyInstaller-निर्मित निष्पादन योग्य फ़ाइल है — **कोई इंस्टॉलर स्क्रिप्ट नहीं, कोई Python आवश्यक नहीं, कोई सिस्टम-कैश प्रदूषण नहीं**। निष्पादन योग्य फ़ाइल अपने बगल में स्थित `ms-playwright/` डायरेक्टरी को स्वतः पहचान लेती है।

**1. डाउनलोड करें।** निष्पादन योग्य फ़ाइल [latest release](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest) से; वैकल्पिक Chromium बंडल (केवल तभी जब नेटवर्क Playwright के Chromium डाउनलोड को भी अवरुद्ध करता हो) दीर्घकालिक [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) release से।

| प्लेटफ़ॉर्म | आवश्यक (latest release) | यदि Chromium डाउनलोड अवरुद्ध हो तो जोड़ें (chromium-bundle release) |
|----------|---------------------------|----------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. इसे व्यवस्थित करें** किसी भी स्थिर डायरेक्टरी में जिस पर आपका नियंत्रण हो। **दोनों zip को पहले ही एक्सट्रैक्ट कर लें** — `.zip` फ़ाइलों को निष्पादन योग्य फ़ाइल के बगल में न छोड़ें। Chromium zip के एक्सट्रैक्ट किए गए फ़ोल्डर को बस `ms-play` से शुरू होना चाहिए और उसमें एक `chromium-*` सबडायरेक्टरी होनी चाहिए:

```
~/apps/servicenow-mcp/                                  (any directory you choose)
├── servicenow-mcp                                      ← from the platform zip (.exe on Windows)
└── ms-playwright-chromium-linux-x64-<ver>/             ← default extracted name works
    └── chromium-1185/
        └── …
```

(यदि आप अधिक साफ-सुथरा नाम चाहते हैं तो `ms-playwright/` नाम बदल दें — दोनों काम करते हैं।) स्टार्टअप पर निष्पादन योग्य फ़ाइल किसी भी सहोदर (sibling) `ms-play*` डायरेक्टरी के लिए glob करती है और, उसके अंदर एक `chromium-*` सबडायरेक्टरी मिलने पर, केवल वर्तमान प्रोसेस के लिए `PLAYWRIGHT_BROWSERS_PATH` के माध्यम से Playwright को उसकी ओर इंगित करती है। यह सिस्टम Playwright कैश को **छूती नहीं**, किसी MCP क्लाइंट कॉन्फ़िग को **संशोधित नहीं करती**, डिस्क पर कहीं भी **लिखती नहीं**।

**3. सत्यापित करें, फिर अपने MCP क्लाइंट को कनेक्ट करें:**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

नीचे दिए गए [Configuration Guide](#configuration-guide) से MCP कॉन्फ़िग स्निपेट को अपने क्लाइंट की कॉन्फ़िग फ़ाइल में पेस्ट करें, `command` को अपनी निष्पादन योग्य फ़ाइल के पूर्ण पथ पर सेट करें। `env` ब्लॉक uvx सेटअप के समान ही है — केवल `command` बदलता है। यदि आपने Chromium को निष्पादन योग्य फ़ाइल के बगल के अलावा कहीं और रखा है, तो `env` ब्लॉक में `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` जोड़ें।

यदि आपने Chromium zip को छोड़ दिया और Playwright का स्वतः-डाउनलोड अवरुद्ध है, तो Python वाली मशीन पर डायरेक्टरी को पहले से तैयार करें:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

स्वतः-पहचान इसे बिना किसी अतिरिक्त कॉन्फ़िग के उठा लेती है।

> Windows उपयोगकर्ता: चरण-दर-चरण विवरण और proxy/antivirus नोट्स के लिए [Windows Installation Guide](WINDOWS_INSTALL.md) देखें।

### त्वरित परीक्षण

अपने क्लाइंट को कॉन्फ़िगर करने से पहले सत्यापित करें कि सर्वर शुरू होता है:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

यदि सर्वर शुरू होता है और लॉगिन के लिए एक ब्राउज़र विंडो खुलती है, तो आप नीचे अपने क्लाइंट को कॉन्फ़िगर करने के लिए तैयार हैं।

---

## Configuration Guide

> **`args` केवल पैकेज के लिए है** — instance URL, auth, credentials सब कुछ `env` (या `environment`) में जाता है। यह args को साफ़ रखता है और प्रति प्रोजेक्ट इंस्टेंस बदलना आसान बनाता है।

> **प्रोजेक्ट-लोकल अनुशंसित**: प्रोजेक्ट-स्कोप्ड कॉन्फ़िग का उपयोग करें ताकि प्रत्येक प्रोजेक्ट एक भिन्न ServiceNow इंस्टेंस से कनेक्ट हो सके।

> **सुविचारित write टार्गेटिंग**: सामान्य टूल सक्रिय इंस्टेंस (`SERVICENOW_ACTIVE_INSTANCE`) की ओर रूट करते हैं। किसी *भिन्न* कॉन्फ़िगर किए गए इंस्टेंस में write करना भी संभव है लेकिन कभी चुपचाप नहीं — उसी कॉल में टार्गेट को नाम देकर उसे मंज़ूरी देनी होती है ([मल्टी-इंस्टेंस मोड](#मल्टी-इंस्टेंस-मोड-तुलना--गार्डेड-सिंगल-कॉल-राइट्स) देखें)। इसलिए dev/test/prod के बीच आते-जाते समय production में आकस्मिक राइट नहीं हो सकती।

---

## Streamable HTTP

डिफ़ॉल्ट transport `stdio` है। रिमोट MCP क्लाइंट या स्थानीय HTTP ब्रिज के लिए, Streamable HTTP के साथ सर्वर शुरू करें:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP endpoint `http://127.0.0.1:8000/mcp` है; `/health` एक हल्की स्थिति प्रतिक्रिया लौटाता है। जब तक सर्वर विश्वसनीय नेटवर्क नियंत्रणों के पीछे न हो, डिफ़ॉल्ट loopback host को बनाए रखें।

---

## मल्टी-इंस्टेंस मोड (तुलना + गार्डेड सिंगल-कॉल राइट्स)

`SERVICENOW_INSTANCE_CONFIG` के साथ नामित इंस्टेंस (जैसे `dev` / `test` / `prod` aliases) कॉन्फ़िगर करें ताकि एक ही सत्र में आप वातावरणों के बीच तुलना भी कर सकें और किसी चुने हुए इंस्टेंस पर **deploy** भी — सक्रिय इंस्टेंस बदले या सर्वर पुनः आरंभ किए बिना। किसी एकल कॉल को `instance=<alias>` argument के साथ रूट करें:

- **केवल-पठन** कॉल स्वतंत्र रूप से रूट होती हैं: `instance=test` `test` को पढ़ता है जबकि `dev` सक्रिय रहता है।
- किसी non-active इंस्टेंस पर **writes** की अनुमति है लेकिन कभी चुपचाप नहीं। उस एक कॉल को *टार्गेट को नाम देकर उसे मंज़ूरी देनी* होती है — `instance=test confirm_instance=test confirm=approve` — और टार्गेट के पास `allow_writes=true` होना चाहिए। केवल वही एक write वहाँ रूट होती है; सक्रिय इंस्टेंस तुरंत बाद बहाल हो जाता है। टार्गेट/confirm बेमेल या read-only टार्गेट को एक स्पष्ट संदेश के साथ अस्वीकार कर दिया जाता है, इसलिए dev/test/prod का घालमेल गलत इंस्टेंस पर नहीं लग सकता।
- **write को टार्गेट पर सत्यापित किया जाता है।** परिणाम में `target_instance` और एक `landed` निर्णय echo होता है: टूल push किए गए fields को टार्गेट पर फिर से पढ़ता है और यदि सामग्री टिकी नहीं (जैसे कोई `sp_*` Service Portal field चुपचाप drop हो गया) तो `WRITE_NOT_LANDED` लौटाता है। "Success" का अर्थ है कि सामग्री इच्छित इंस्टेंस पर मौजूद होने की पुष्टि हुई — न कि केवल यह कि अनुरोध ने 200 लौटाया।
- `compare_instances` aliases के पार रिकॉर्ड्स की तुलना (read-only) करता है; `list_instances` कॉन्फ़िगर किए गए aliases और प्रत्येक का write flag रिपोर्ट करता है।
- `prod` को `allow_writes=false` पर रखें जब तक आप जानबूझकर production writes न करना चाहें — तब कोई भूला हुआ flag कभी उसे सक्षम नहीं कर सकता।

> **बहुत सारे** रिकॉर्ड्स को promote करने के लिए (विशेषकर Service Portal / scoped तालिकाएँ), प्रति-रिकॉर्ड cross-instance writes के बजाय एक Update Set को प्राथमिकता दें — source पर commit, target UI में retrieve + commit — यह उन per-table/SP ACLs को bypass करता है जिनसे single Table-API writes टकराती हैं।

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "auth_type": "browser", "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "auth_type": "browser", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "auth_type": "browser", "allow_writes": false }
}'
```

प्रति-इंस्टेंस credentials, MCP क्लाइंट `env` ब्लॉक में (प्रत्येक alias अपना स्वयं का `username` / `password` / `auth_type` / `api_key` रख सकता है; `${ENV}` secrets को JSON से बाहर रखता है; एकल-इंस्टेंस `SERVICENOW_INSTANCE_URL` रूप अभी भी एक fallback के रूप में काम करता है):

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

उदाहरण तुलना:

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

किसी non-active इंस्टेंस पर एकल write के लिए, ऊपर दी गई guarded `instance=<alias> confirm_instance=<alias> confirm=approve` routing का उपयोग करें। **कई** records को promote करने के लिए, per-record cross-instance writes के बजाय Update Set को प्राथमिकता दें।

---

## Claude Desktop

| स्कोप | पथ |
|-------|------|
| Global | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Global | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

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

> Claude Desktop प्रोजेक्ट-लोकल कॉन्फ़िग का समर्थन नहीं करता। प्रति-प्रोजेक्ट सेटअप के लिए Claude Code का उपयोग करें।

---

## Claude Code

| स्कोप | पथ |
|-------|------|
| Global | `~/.claude.json` |
| Project | प्रोजेक्ट रूट में `.mcp.json` |

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

| स्कोप | पथ |
|-------|------|
| Global | `~/.config/zed/settings.json` |

Zed में **Settings** > **MCP Servers** के माध्यम से जोड़ें:

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

दोनों **Codex CLI** (`codex` कमांड) और **Codex App** (chatgpt.com/codex) एक ही `config.toml` से पढ़ते हैं।

| स्कोप | पथ | टिप्पणी |
|-------|------|------|
| Global | `~/.codex/config.toml` | सभी प्रोजेक्ट्स में साझा |
| Project | `.codex/config.toml` | global को ओवरराइड करता है (केवल विश्वसनीय प्रोजेक्ट्स) |

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
# Login is shared across hosts automatically (scoped per instance + user under
# ~/.mfa_servicenow_mcp). Only set SERVICENOW_BROWSER_USER_DATA_DIR if a sandboxed
# host remapped HOME — see the README "Login sharing" note. Do NOT set it when you
# run multiple instances; it collapses them into one Chromium profile.
```

---

## OpenCode

| स्कोप | पथ |
|-------|------|
| Project | प्रोजेक्ट रूट में `opencode.json` |

> OpenCode `environment` का उपयोग करता है (`env` का नहीं)।

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

| स्कोप | पथ |
|-------|------|
| Global | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| Global | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> एजेंट पैनल के माध्यम से संपादित करें: **...** > **Manage MCP Servers** > **View raw config**। सहेजने के बाद **Refresh** पर क्लिक करें।

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

## Docker (केवल API Key)

> Browser auth (MFA/SSO) के लिए एक GUI ब्राउज़र की आवश्यकता होती है और यह कंटेनरों के अंदर काम नहीं करता।

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
