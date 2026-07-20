# Windows इंस्टॉलेशन गाइड

बाकी सभी प्लेटफ़ॉर्म की तरह Windows पर भी डिफ़ॉल्ट `uvx` ही है। सिर्फ़ एक Windows-विशिष्ट वजह आपको उससे हटा सकती है:

- **Smart App Control `uvx` को ब्लॉक कर देता है** → **pip** पर स्विच करें (Step 1b)। Windows पर यही अब तक की सबसे आम खराबी है, और आम तौर पर यह Windows अपडेट के ठीक बाद अचानक सामने आती है।

अगर **PyPI तक ही पहुंच नहीं है** — यानी कॉर्पोरेट नेटवर्क पैकेज इंडेक्स को पूरी तरह ब्लॉक कर देता है — तो दोनों में से कोई भी रास्ता पैकेज नहीं ला पाएगा। अपनी IT टीम से `pypi.org` और `files.pythonhosted.org` को allowlist में डलवाएं, या पैकेज को किसी आंतरिक इंडेक्स पर मिरर करवाएं जिसे आप `pip install --index-url` से इस्तेमाल कर सकें।

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

**अपडेट करना:** `uvx` जिस वर्शन को डाउनलोड करता है उसे कैश करके बार-बार उसी का उपयोग करता रहता है, इसलिए किसी नए रिलीज़ को स्पष्ट रूप से मंगाना पड़ता है:

```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

---

## Step 1b: Smart App Control uvx को ब्लॉक करता है — pip से इंस्टॉल करें

### आपको क्या दिखेगा

`uvx` बिना किसी काम की एरर दिए काम करना बंद कर देता है। MCP क्लाइंट बताता है कि सर्वर शुरू नहीं हो सका, या PowerShell कहता है कि प्रोग्राम को आपके एडमिनिस्ट्रेटर / सिस्टम पॉलिसी ने ब्लॉक कर दिया। आपकी कॉन्फ़िग में कुछ भी नहीं बदला होता। बहुत बार यह **Windows अपडेट के ठीक बाद** शुरू होता है, जिससे लगता है कि सर्वर खराब हो गया, जबकि असल में मामला लॉन्चर का है।

### ऐसा क्यों होता है

[Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0) (SAC) एक Windows 11 फ़ीचर है जो केवल **साइन किए हुए या अन्यथा भरोसेमंद माने गए** एक्ज़ीक्यूटेबल्स को ही चलने देता है। `uvx` कोई स्थायी रूप से इंस्टॉल किया गया प्रोग्राम नहीं चलाता — हर एक रन पर वह एक **नया, बिना साइन किया हुआ अस्थायी एक्ज़ीक्यूटेबल** अनपैक करके लॉन्च करता है। ठीक यही चीज़ रोकने के लिए SAC बना है, इसलिए वह हर बार इसे ब्लॉक करता है। बार-बार कोशिश करने या `uv` को दोबारा इंस्टॉल करने से कुछ नहीं बदलता: डिज़ाइन के हिसाब से ही फ़ाइल हर रन पर नई और बिना साइन की होती है।

नई Windows 11 मशीनों पर SAC मूल्यांकन (evaluation) मोड में आता है और बाद में अपने आप **on** हो सकता है। इसीलिए ऐसी मशीन पर भी यह अचानक सामने आ जाता है जहां `uvx` महीनों से ठीक चल रहा था।

जांचने के लिए: **Windows Security → App & browser control → Smart App Control settings**।

> **इसे ठीक करने के लिए Smart App Control को बंद न करें।** इसे बंद करना एक **एकतरफ़ा स्विच** है — एक बार बंद करने के बाद Windows आपको इसे दोबारा चालू नहीं करने देगा। इसे वापस पाने के लिए **Windows दोबारा इंस्टॉल** करना पड़ेगा। एक पैकेज लॉन्चर के बदले OS की सुरक्षा को स्थायी रूप से कमज़ोर करना समझदारी नहीं है। इसके बजाय pip का उपयोग करें; यह समस्या को पूरी तरह हल कर देता है और SAC चालू रहने देता है।

### pip वाला रास्ता

pip सर्वर को सामान्य Python फ़ाइलों के रूप में इंस्टॉल करता है जिन्हें एक **साइन किया हुआ** Python इंटरप्रेटर चलाता है, इसलिए SAC को आपत्ति करने लायक कुछ मिलता ही नहीं।

[python.org इंस्टॉलर](https://www.python.org/downloads/) से Python **3.10 या उससे नया** इंस्टॉल करें — वह बिल्ड साइन किया हुआ है और SAC से जस का तस पास हो जाता है। (Microsoft Store वाला Python भी काम करता है।) इंस्टॉल के दौरान **"Add python.exe to PATH"** पर टिक करें। फिर:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**अपडेट करना:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Chromium को ऊपर दिखाए अनुसार पहले ही इंस्टॉल कर लें। इसे पहले टूल कॉल तक टालने का मतलब है ~150 MB का डाउनलोड आपके MCP क्लाइंट की हैंडशेक डेडलाइन से होड़ करेगा, जो `connection closed` के रूप में सामने आता है।

### इसे हमेशा मॉड्यूल के रूप में लॉन्च करें, कंसोल स्क्रिप्ट से कभी नहीं

pip आपके Scripts फ़ोल्डर में एक `servicenow-mcp.exe` शिम भी रख देता है। **वह शिम बिना साइन किया हुआ `.exe` है जिसे pip आपकी मशीन पर ही बनाता है, इसलिए SAC उसे ठीक वैसे ही ब्लॉक करता है जैसे उसने uvx को किया था।** मॉड्यूल को सीधे कॉल करके उसे पूरी तरह किनारे कर दें:

| इसकी जगह | यह उपयोग करें |
|---|---|
| `servicenow-mcp` | `python -m servicenow_mcp` |
| `servicenow-mcp setup` | `python -m servicenow_mcp setup` |
| `servicenow-mcp --version` | `python -m servicenow_mcp --version` |
| `servicenow-mcp-skills claude` | `python -m servicenow_mcp.setup_skills claude` |

इंस्टॉल सत्यापित करें:

```powershell
python -m servicenow_mcp --version
```

### pip वाले रास्ते पर क्लाइंट कॉन्फ़िग

सिर्फ़ `command` और `args` बदलते हैं। **`env` ब्लॉक uvx वाले रूप के बिल्कुल समान रहता है** — Step 2 की कोई भी कॉन्फ़िग कॉपी करें और ऊपर की दो लाइनें बदल दें:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Codex के TOML में इसका समकक्ष है `command = "python"` / `args = ["-m", "servicenow_mcp"]`।

> अगर आपके MCP क्लाइंट को `python` नहीं मिलता, तो उसकी जगह पूरा पाथ दें (उदाहरण के लिए `C:/Users/you/AppData/Local/Programs/Python/Python312/python.exe`)। MCP क्लाइंट्स को हमेशा वह PATH नहीं मिलता जो आपके शेल के पास होता है।

---

## Step 2: अपना MCP क्लाइंट कॉन्फ़िगर करें

नीचे अपने MCP क्लाइंट के लिए कॉन्फ़िगरेशन कॉपी करें।
`your-instance` को अपने वास्तविक ServiceNow इंस्टेंस एड्रेस से बदलें।

> ये उदाहरण डिफ़ॉल्ट `uvx` इंस्टॉल मानकर दिए गए हैं। **pip वाले रास्ते पर (Step 1b), `command` को `python` से और `args` को `["-m", "servicenow_mcp"]` से बदलें** — उसके बाद आने वाले `--instance-url` / `--auth-type` फ़्लैग यथावत रखें, और `env` ब्लॉक को बिल्कुल वैसा ही रहने दें जैसा लिखा है।

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

## Step 3: स्किल्स इंस्टॉल करें (वैकल्पिक)

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

> **pip वाले रास्ते पर (Step 1b), इसके बजाय मॉड्यूल को कॉल करें** — `servicenow-mcp-skills` भी pip से बना वैसा ही बिना साइन किया हुआ `.exe` शिम है जिसे Smart App Control ब्लॉक करता है:
>
> ```powershell
> python -m servicenow_mcp.setup_skills claude
> python -m servicenow_mcp.setup_skills codex
> python -m servicenow_mcp.setup_skills opencode
> ```

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

## Step 4: सत्यापित करें

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

### uvx मिल तो जाता है, पर कुछ चलता नहीं / "blocked by your administrator" / Windows अपडेट के बाद खराब हो गया
→ यह **Smart App Control** है, खराब इंस्टॉल नहीं। uvx हर रन पर एक बिना साइन किया हुआ अस्थायी एक्ज़ीक्यूटेबल अनपैक करता है और SAC उसे चलाने से मना कर देता है। [Step 1b](#step-1b-smart-app-control-uvx-को-ब्लॉक-करता-है--pip-से-इंस्टॉल-करें) वाले pip रास्ते पर स्विच करें। SAC को बंद न करें — वह एकतरफ़ा स्विच है जिसे केवल Windows दोबारा इंस्टॉल करके ही पलटा जा सकता है।

### pip इंस्टॉल तो हो गया, पर `servicenow-mcp` फिर भी लॉन्च नहीं होता
→ आप pip से बने `servicenow-mcp.exe` शिम से टकरा रहे हैं, जो बिना साइन किया हुआ है और SAC उसे ठीक वैसे ही ब्लॉक करता है जैसे uvx को करता था। इसके बजाय मॉड्यूल को कॉल करें: `python -m servicenow_mcp`। अपने MCP क्लाइंट कॉन्फ़िग को भी `"command": "python"`, `"args": ["-m", "servicenow_mcp"]` पर अपडेट करें।

### "Python is not installed"
→ **uvx** वाले रास्ते पर `uv` स्वतः Python 3.11+ डाउनलोड करता है — किसी मैन्युअल इंस्टॉल की ज़रूरत नहीं। अगर सिस्टम Python के साथ टकराव है, तो `uv` को अनइंस्टॉल करके पुनः इंस्टॉल करें।
→ **pip** वाले रास्ते पर Python आपको खुद देना होता है: [python.org इंस्टॉलर](https://www.python.org/downloads/) से 3.10+ इंस्टॉल करें (साइन किया हुआ है, इसलिए Smart App Control से पास हो जाता है) और **"Add python.exe to PATH"** पर टिक करें। Microsoft Store वाला Python भी काम करता है।

### "Browser won't open"
→ MCP स्टार्टअप से पहले Chromium इंस्टॉल होना चाहिए:
```powershell
uvx --with playwright playwright install chromium   # uvx
python -m playwright install chromium               # pip
```

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
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

pip वाले रास्ते पर:
```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

दोनों ही मामलों में Chromium साथ में रिफ़्रेश किया जाता है, क्योंकि नया Playwright नए Chromium बिल्ड की अपेक्षा करता है।

रिफ़्रेश करने के बाद, अपने MCP क्लाइंट को पूरी तरह पुनः आरंभ करें ताकि वह नया वर्शन लॉन्च करे।
