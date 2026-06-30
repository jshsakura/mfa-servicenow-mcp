# Windows इंस्टॉलेशन गाइड

डिफ़ॉल्ट रूप से `uvx` का उपयोग करें। अगर एंडपॉइंट सिक्योरिटी/Zscaler `uvx` या पैकेज डाउनलोड को ब्लॉक करता है, तो नीचे दिए गए रिलीज़ zip/exe सेक्शन का उपयोग करें।

---

## Step 1: डिफ़ॉल्ट uvx इंस्टॉल

बिना एडमिन विशेषाधिकार के PowerShell खोलें:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

यह `uv` इंस्टॉल करता है, सर्वर को फ़ेच+वेरिफ़ाई करता है, और Chromium डाउनलोड करता है। फिर सर्वर को अपनी MCP क्लाइंट कॉन्फ़िग फ़ाइल में जोड़ें (कोई इंस्टॉलर कमांड नहीं):

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

`uvx` मानक Playwright कैश में पहले से मौजूद किसी मिलते-जुलते Chromium का पुनः उपयोग करता है; अगर Chromium गायब है, तो पहले ऊपर दी गई इंस्टॉल कमांड चलाएं।

---

## Step 2: रिलीज़ zip/exe इंस्टॉल

इसका उपयोग तब करें जब `uvx` ब्लॉक हो। GitHub Releases से `servicenow-mcp-windows-x64-<version>.zip` डाउनलोड करें। इसमें एक ही PyInstaller-निर्मित `servicenow-mcp.exe` के साथ `LICENSE` होता है। किसी इंस्टॉलर स्क्रिप्ट की ज़रूरत नहीं है — एक्ज़ीक्यूटेबल खुद Chromium खोज को संभालता है। अपने नियंत्रण वाला एक स्थिर फ़ोल्डर चुनें (उदाहरण के लिए `C:\Users\you\apps\servicenow-mcp\`), उसमें `servicenow-mcp.exe` एक्सट्रैक्ट करें, और — अगर आपके पास Chromium zip है — तो **उसे पहले ही** उसी फ़ोल्डर में एक्सट्रैक्ट कर दें। `.zip` को यूं ही पड़ा न छोड़ें। एक्सट्रैक्ट किए गए फ़ोल्डर का नाम वैसा ही रह सकता है जैसा Windows ने बनाया हो या उसे `ms-playwright\` में बदला जा सकता है; एक्ज़ीक्यूटेबल स्टार्टअप पर किसी भी सिबलिंग `ms-play*` डायरेक्टरी के लिए glob करता है:

```
C:\Users\you\apps\servicenow-mcp\
├── servicenow-mcp.exe
└── ms-playwright-chromium-windows-x64-<ver>\   (default extracted name works)
    └── chromium-1185\
        └── …
```

स्टार्टअप पर एक्ज़ीक्यूटेबल किसी भी सिबलिंग `ms-play*\chromium-*` डायरेक्टरी की तलाश करता है और केवल वर्तमान प्रोसेस के लिए `PLAYWRIGHT_BROWSERS_PATH` के माध्यम से Playwright को उसकी ओर इंगित करता है। यह सिस्टम के मानक Playwright कैश (`%LOCALAPPDATA%\ms-playwright`) को नहीं छूता, किसी भी MCP क्लाइंट कॉन्फ़िग को संशोधित नहीं करता, और डिस्क पर कहीं भी कुछ नहीं लिखता।

फिर इसे अपनी क्लाइंट कॉन्फ़िग फ़ाइल में पेस्ट करें (Claude Code / Claude Desktop उदाहरण):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe",
      "args": [],
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

`SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` वैकल्पिक MFA लॉगिन प्री-फ़िल हैं। अगर आप Chromium को सिबलिंग `ms-playwright\` डायरेक्टरी के अलावा कहीं और रखते हैं, तो `env` ब्लॉक में `"PLAYWRIGHT_BROWSERS_PATH": "C:/abs/path/to/ms-playwright"` जोड़ें। Codex (`config.toml`) / OpenCode (`opencode.json`) / Cursor / Antigravity / Zed के लिए स्निपेट [Client Setup Guide](CLIENT_SETUP.md) में मौजूद हैं।

यह `uvx` को रनटाइम से पूरी तरह बाहर रखता है।

अगर Chromium बंडल नहीं है और डाउनलोड की अनुमति है, तो <https://www.python.org/downloads/> से Python इंस्टॉल करें, फिर चलाएं:

```powershell
py -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = "$HOME\apps\servicenow-mcp\ms-playwright"
py -m playwright install chromium
```

अगर Playwright ब्राउज़र डाउनलोड भी ब्लॉक है, तो chromium-bundle रिलीज़ (https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) से `ms-playwright-chromium-windows-x64.zip` डाउनलोड करें और उसकी सामग्री को यहां एक्सट्रैक्ट करें:

```text
%LOCALAPPDATA%\ms-playwright
```

Playwright ब्राउज़र दस्तावेज़: <https://playwright.dev/python/docs/browsers>

---

## Step 3: रिलीज़ एसेट्स बनाएं

मेंटेनर Windows पर रिलीज़ zip बनाते हैं:

```powershell
py scripts\build_desktop_release.py --browser-zip
```

यह एक्ज़ीक्यूटेबल zip और ब्लॉक किए गए नेटवर्क के लिए वैकल्पिक Playwright Chromium कैश zip बनाता है।

---

## Step 4: अपना MCP क्लाइंट कॉन्फ़िगर करें

नीचे अपने MCP क्लाइंट के लिए कॉन्फ़िगरेशन कॉपी करें।
`your-instance` को अपने वास्तविक ServiceNow इंस्टेंस एड्रेस से बदलें।

### Claude Desktop

कॉन्फ़िग फ़ाइल का स्थान: `%APPDATA%\Claude\claude_desktop_config.json`

> अगर फ़ाइल मौजूद नहीं है तो उसे बनाएं। अगर फ़ोल्डर गायब है, तो उसे बनाने के लिए Claude Desktop को एक बार लॉन्च करें।

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Claude Code

CLI के माध्यम से रजिस्टर करें — किसी कॉन्फ़िग फ़ाइल की ज़रूरत नहीं:

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

सत्यापित करें:
```powershell
claude mcp list
```

### OpenAI Codex

कॉन्फ़िग फ़ाइल का स्थान: `%USERPROFILE%\.codex\agents.toml` या आपके प्रोजेक्ट रूट में `.codex\agents.toml`।

> अगर फ़ाइल और फ़ोल्डर मौजूद नहीं हैं तो उन्हें बनाएं।

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://your-instance.service-now.com",
  "--auth-type", "browser",
  "--browser-headless", "false",
  "--tool-package", "standard",
]
```

### OpenCode

कॉन्फ़िग फ़ाइल का स्थान: आपके प्रोजेक्ट रूट में `opencode.json`।

```json
{
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
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Zed

कॉन्फ़िग फ़ाइल का स्थान: `~/.config/zed/settings.json`

> Zed में **Settings** > **MCP Servers** के माध्यम से जोड़ें:

```json
{
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
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

### AntiGravity

कॉन्फ़िग फ़ाइल का स्थान: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> एजेंट पैनल **...** → **Manage MCP Servers** → **View raw config** के माध्यम से भी पहुंचा जा सकता है।

```json
{
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
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> कॉन्फ़िग सहेजें, फिर AntiGravity में **Refresh** पर क्लिक करें।

---

## Step 5: स्किल्स इंस्टॉल करें (वैकल्पिक)

स्किल्स AI एक्ज़ीक्यूशन ब्लूप्रिंट हैं — सुरक्षा गेट्स वाली सत्यापित पाइपलाइन जो कच्चे MCP टूल्स को विश्वसनीय वर्कफ़्लो में बदल देती हैं। 3 श्रेणियों में 4 स्किल्स।

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# Or with uvx (no install needed)
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

| क्लाइंट | इंस्टॉल पाथ | ऑटो-डिस्कवरी |
|--------|-------------|----------------|
| Claude Code | `.claude\commands\servicenow\` | अगली स्टार्टअप पर `/servicenow` स्लैश कमांड दिखाई देते हैं |
| OpenAI Codex | `.codex\skills\servicenow\` | अगले एजेंट सेशन पर स्किल्स लोड होती हैं |
| OpenCode | `.opencode\skills\servicenow\` | अगले सेशन पर स्किल्स लोड होती हैं |

| श्रेणी | स्किल्स | उद्देश्य |
|----------|--------|---------|
| `analyze/` | 6 | विजेट विश्लेषण, पोर्टल डायग्नोसिस, डिपेंडेंसी मैपिंग, कोड डिटेक्शन |
| `fix/` | 3 | विजेट पैचिंग (चरणबद्ध सुरक्षा गेट्स), डीबगिंग, कोड रिव्यू |
| `manage/` | 8 | पेज लेआउट, स्क्रिप्ट इंक्लूड, सोर्स एक्सपोर्ट, ऐप सोर्स डाउनलोड, चेंजसेट वर्कफ़्लो, लोकल सिंक, वर्कफ़्लो प्रबंधन, स्किल प्रबंधन |
| `deploy/` | 2 | चेंज रिक्वेस्ट लाइफ़साइकल, इंसिडेंट ट्राएज |
| `explore/` | 5 | हेल्थ चेक, स्कीमा डिस्कवरी, रूट ट्रेसिंग, फ़्लो ट्रिगर ट्रेसिंग, ESC कैटलॉग फ़्लो |

**अपडेट:** सभी मौजूदा स्किल फ़ाइलों को बदलने के लिए वही इंस्टॉल कमांड दोबारा चलाएं।
**केवल स्किल्स हटाएं:** स्किल डायरेक्टरी को मैन्युअल रूप से हटाएं (उदाहरण के लिए `Remove-Item -Recurse .claude\commands\servicenow\`)।

---

## Step 6: सत्यापित करें

1. अपने MCP क्लाइंट को **पूरी तरह बंद करें और पुनः आरंभ करें** (ट्रे आइकन भी बंद करें)।
2. ब्राउज़र विंडो पहले टूल कॉल पर खुलती है (सर्वर स्टार्ट पर नहीं)।
3. Okta/Microsoft Authenticator/आदि के माध्यम से MFA प्रमाणीकरण पूरा करें।
4. प्रमाणीकरण के बाद, ब्राउज़र स्वतः बंद हो जाता है और सेशन बना रहता है।

टेस्ट: अपने क्लाइंट से `sn_health` टूल कॉल करें।

> अगर ब्राउज़र नहीं खुलता, तो जांचें कि Chromium इंस्टॉल था या नहीं। आप इसे ज़बरदस्ती इंस्टॉल कर सकते हैं: `uvx --with playwright playwright install chromium`

---

## सेशन प्रबंधन

प्रमाणित सेशन स्वतः डिस्क पर सहेजे जाते हैं — हर बार लॉग इन करने की ज़रूरत नहीं।

- **सेशन फ़ाइल का स्थान**: `%USERPROFILE%\.servicenow_mcp\session_*.json`
- **डिफ़ॉल्ट सेशन TTL**: 30 मिनट (keepalive थ्रेड हर 15 मिनट में बढ़ाता है)
- **सेशन समाप्ति पर**: पुनः प्रमाणीकरण के लिए ब्राउज़र विंडो स्वतः खुलती है

TTL बदलने के लिए, `--browser-session-ttl` विकल्प का उपयोग करें (मिनटों में):
```
--browser-session-ttl 60
```

ब्राउज़र प्रोफ़ाइल को बनाए रखने के लिए, `--browser-user-data-dir` विकल्प जोड़ें:
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
यह लंबे सेशन प्रतिधारण के लिए कुकीज़ और लॉगिन स्टेट को डायरेक्टरी में संग्रहीत करता है।

---

## टूल पैकेज

टूल सेट चुनने के लिए `MCP_TOOL_PACKAGE` सेट करें। डिफ़ॉल्ट: `standard` (केवल-पढ़ने योग्य)।

| पैकेज | टूल्स | विवरण |
|---------|:-----:|-------------|
| `core` | 12 | हेल्थ, स्कीमा, डिस्कवरी, और मुख्य लुकअप के लिए न्यूनतम केवल-पढ़ने योग्य आवश्यक चीज़ें |
| `standard` | 27 | **(डिफ़ॉल्ट)** इंसिडेंट, चेंज, पोर्टल, लॉग, और सोर्स विश्लेषण में केवल-पढ़ने योग्य पैकेज |
| `service_desk` | 29 | standard + इंसिडेंट और चेंज ऑपरेशनल राइट्स |
| `portal_developer` | 38 | standard + पोर्टल, चेंजसेट, स्क्रिप्ट इंक्लूड, और लोकल-सिंक डिलीवरी वर्कफ़्लो |
| `platform_developer` | 43 | standard + वर्कफ़्लो, Flow Designer, UI पॉलिसी, इंसिडेंट/चेंज, और स्क्रिप्ट राइट्स |
| `full` | 57 | सबसे व्यापक पैकेज्ड सतह: सभी `manage_*` वर्कफ़्लो के साथ एडवांस्ड ऑपरेशन्स |

बदलने के लिए, `MCP_TOOL_PACKAGE` मान अपडेट करें:

JSON क्लाइंट (Claude Desktop, AntiGravity):
```json
"env": {
  "MCP_TOOL_PACKAGE": "standard"
}
```

TOML क्लाइंट (Codex) — `args` एरे के अंदर जोड़ें:
```toml
"--tool-package", "standard",
```

---

## समस्या निवारण

### "uvx not found"
→ सुनिश्चित करें कि आपने Step 1 के बाद PowerShell को **बंद करके फिर से खोला** है। अगर अब भी विफल हो रहा है:
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### "Python is not installed"
→ `uv` स्वतः Python 3.11+ डाउनलोड करता है। किसी मैन्युअल इंस्टॉल की ज़रूरत नहीं।
अगर सिस्टम Python के साथ टकराव है, तो `uv` को अनइंस्टॉल करके पुनः इंस्टॉल करें।

### "Browser won't open"
→ MCP स्टार्टअप से पहले Chromium इंस्टॉल होना चाहिए:
```powershell
uvx --with playwright playwright install chromium
```
→ अगर ब्राउज़र डाउनलोड ब्लॉक है, तो chromium-bundle रिलीज़ से `ms-playwright-chromium-windows-x64.zip` का उपयोग करें और उसे `%LOCALAPPDATA%\ms-playwright` में एक्सट्रैक्ट करें।

### "MCP server won't connect"
→ कॉन्फ़िग फ़ाइल सिंटैक्स जांचें:
  - JSON: कॉमा, कोट्स, मिलते हुए ब्रेसेस
  - TOML: ब्रैकेट, कोट्स, कॉमा
→ सत्यापित करें कि `instance-url` `https://` से शुरू होता है।
→ Claude Desktop को कॉन्फ़िग बदलावों के बाद **पूर्ण क्विट और रीस्टार्ट** चाहिए (ट्रे आइकन भी बंद करें)।

### "PowerShell script execution is blocked"
→ वर्तमान उपयोगकर्ता के लिए एक्ज़ीक्यूशन की अनुमति दें:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### सेशन रीसेट करें
अगर लॉगिन समस्याएं बनी रहती हैं, तो सेशन कैश हटाएं और पुनः प्रयास करें:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### वर्शन अपडेट
`uvx` अपने द्वारा डाउनलोड किए गए अंतिम कैश्ड वर्शन का पुनः उपयोग करता है। यह हर रन पर स्वतः किसी नए रिलीज़ में रिफ़्रेश **नहीं** होता। नवीनतम प्रकाशित वर्शन को कैश में लाने के लिए:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

रिफ़्रेश करने के बाद, अपने MCP क्लाइंट को पूरी तरह पुनः आरंभ करें ताकि वह नया कैश्ड वर्शन लॉन्च करे।
