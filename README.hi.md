# MFA ServiceNow MCP

🌐 [English](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md) | 🇰🇷 [한국어](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md) | 🇯🇵 [日本語](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ja.md) | 🇮🇳 [हिन्दी](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.hi.md) | 🇨🇳 [简体中文](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.zh.md) | 🇪🇸 [Español](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.es.md) | 🚀 [**GitHub Pages**](https://jshsakura.github.io/mfa-servicenow-mcp/)

MFA-first ServiceNow MCP सर्वर। एक असली ब्राउज़र (Playwright) के ज़रिए प्रमाणीकरण करता है ताकि Okta, Entra ID, SAML, और कोई भी MFA/SSO लॉगिन बिना किसी झंझट के काम करे। headless/Docker वातावरणों के लिए API Key का भी समर्थन करता है।

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-live-blue?logo=github)](https://jshsakura.github.io/mfa-servicenow-mcp/)

> [!WARNING]
> **व्यक्तिगत उपयोग के लिए बनाया गया — अपने जोखिम पर उपयोग करें।** यह परियोजना मुख्य रूप से लेखक के अपने वर्कफ़्लो के लिए बनाई गई थी। जोखिम को सक्रिय रूप से कम किया गया है (read-only डिफ़ॉल्ट, write गार्ड, dry-run पूर्वावलोकन, और हर write पर `confirm='approve'` गेट), लेकिन यह **लाइव ServiceNow इंस्टेंस** के विरुद्ध काम करता है। यह आपके इंस्टेंस पर जो कुछ करता है उसके लिए आप पूरी तरह से ज़िम्मेदार हैं। **"जैसा है" वैसा ही प्रदान किया गया, किसी भी प्रकार की वारंटी के बिना** (Apache-2.0, देखें [LICENSE](LICENSE))। किसी टूल को मंज़ूरी देने से पहले समीक्षा करें कि वह क्या करेगा।

---

## विषय-सूची

- [Features](https://github.com/jshsakura/mfa-servicenow-mcp#features)
- [Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup)
- [Prerequisites](https://github.com/jshsakura/mfa-servicenow-mcp#prerequisites)
- [MCP Client Configuration](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration)
- [Authentication](https://github.com/jshsakura/mfa-servicenow-mcp#authentication)
- [Tool Packages](https://github.com/jshsakura/mfa-servicenow-mcp#tool-packages)
- [CLI Reference](https://github.com/jshsakura/mfa-servicenow-mcp#cli-reference)
- [Keeping Up to Date](https://github.com/jshsakura/mfa-servicenow-mcp#keeping-up-to-date)
- [Safety Policy](https://github.com/jshsakura/mfa-servicenow-mcp#safety-policy)
- [Performance Optimizations](https://github.com/jshsakura/mfa-servicenow-mcp#performance-optimizations)
- [Local Source Audit](https://github.com/jshsakura/mfa-servicenow-mcp#local-source-audit)
- [Skills](https://github.com/jshsakura/mfa-servicenow-mcp#skills)
- [Docker](https://github.com/jshsakura/mfa-servicenow-mcp#docker)
- [Developer Setup](https://github.com/jshsakura/mfa-servicenow-mcp#developer-setup)
- [Documentation](https://github.com/jshsakura/mfa-servicenow-mcp#documentation)
- [Related Projects](https://github.com/jshsakura/mfa-servicenow-mcp#related-projects-and-acknowledgements)
- [License](https://github.com/jshsakura/mfa-servicenow-mcp#license)

---

## Setup

दो चरण: **install**, फिर **अपने MCP क्लाइंट कॉन्फ़िग में सर्वर जोड़ें**। कोई installer कमांड नहीं, कोई प्रति-क्लाइंट फ़्लैग नहीं।

### 1. Install

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

यह `uv` को install करता है, सर्वर को fetch+verify करता है, और Chromium डाउनलोड करता है — एक बार। fetch पर लगा `--with playwright` नीचे दिए गए रनटाइम कॉन्फ़िग से मेल खाता है, इसलिए uvx ठीक उसी env को कैश करता है और पहला क्लाइंट स्टार्ट तुरंत होता है।

> **निर्देशित सेटअप।** बिना किसी फ़्लैग के `servicenow-mcp setup` चलाने पर यह आपको क्रमांकित मेनू के ज़रिए ले जाता है (क्लाइंट और auth प्रकार को नंबर या नाम से चुनें — कोई free-text अनुमान नहीं), अंग्रेज़ी या कोरियाई में (आपकी locale से स्वतः-पहचाना जाता है; `SERVICENOW_MCP_LANG=ko|en` से बाध्य करें)।

### 2. अपना MCP क्लाइंट कॉन्फ़िगर करें

सर्वर को अपने क्लाइंट की कॉन्फ़िग फ़ाइल में जोड़ें — नीचे अपना चुनें। केवल दो env vars आवश्यक हैं; `MCP_TOOL_PACKAGE` डिफ़ॉल्ट रूप से `standard` होता है, इसलिए जब तक आपको कोई भिन्न पैकेज न चाहिए, इसे छोड़ दें।

**Claude Code** — `.mcp.json` (project root) / `~/.claude.json` (global):

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

**Codex** — `.codex/config.toml` (project) / `~/.codex/config.toml` (global):

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
```

**OpenCode** — `opencode.json` (project root):

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
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

अन्य क्लाइंट (Cursor, VS Code, Antigravity, Zed, …) और पूर्ण env विकल्प (auth प्रकार, tool पैकेज) [MCP Client Configuration](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration) में हैं।

फिर क्लाइंट को पुनः आरंभ करें। पहला ब्राउज़र टूल कॉल Okta/Entra ID/SAML/MFA लॉगिन के लिए एक विंडो खोलता है। सत्र बने रहते हैं — हर बार पुनः-लॉगिन की ज़रूरत नहीं।

> क्या आप चाहते हैं कि कोई AI इसे करे? Claude Code / Cursor / Codex / आदि में पेस्ट करें:
> `Install and configure mfa-servicenow-mcp following https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md`
> कॉर्पोरेट नेटवर्क uvx/PyPI को ब्लॉक कर रहा है? [release zip/exe](https://github.com/jshsakura/mfa-servicenow-mcp#install-offline--corporate) का उपयोग करें।

---

## Features

- MFA/SSO वातावरणों (Okta, Entra ID, SAML, MFA) के लिए **ब्राउज़र प्रमाणीकरण**
- **4 auth मोड**: Browser, Basic, OAuth, API Key
- **65 पंजीकृत टूल** के साथ **6 सक्रिय पैकेज प्रोफ़ाइल** और साथ ही disabled `none` — न्यूनतम read-only से लेकर व्यापक bundled CRUD तक
- **16 वर्कफ़्लो skills** सुरक्षा गेट, sub-agent डेलिगेशन, और सत्यापित पाइपलाइनों के साथ
- **Streamable HTTP transport** — डिफ़ॉल्ट के रूप में stdio रखें, या HTTP-सक्षम क्लाइंट और ब्रिज के लिए `/mcp` एक्सपोज़ करें
- HTML रिपोर्ट, क्रॉस-रेफ़रेंस ग्राफ़, dead code पहचान, और स्वतः-जनित डोमेन ज्ञान के साथ **लोकल सोर्स ऑडिट**
- **डिस्क पर आधिकारिक संबंध ग्राफ़** — `_graph.json` (widget→Angular Provider, लाइव M2M से) और `_page_graph.json` (page→widget, `sp_instance` से) LLM को इंस्टेंस को फिर से query किए बिना ऑफ़लाइन निर्भरता प्रश्नों के उत्तर देने देते हैं
- **इंक्रीमेंटल sync** (`incremental=True`) — केवल उन रिकॉर्ड्स को फिर से डाउनलोड करें जो पिछले sync के बाद बदले हैं (`sys_updated_on` watermark), `git pull` की तरह; `reconcile_deletions=True` इंस्टेंस पर डिलीट किए गए रिकॉर्ड्स को फ़्लैग करता है
- `download_app_sources` में **क्रॉस-स्कोप dep स्वतः-समाधान** — global-scope Script Includes, Widgets, Angular Providers, और UI Macros को खींचता है जिन्हें ऐप संदर्भित करता है, ताकि लोकल bundle विश्लेषण के लिए स्व-निहित हो
- **अटैचमेंट डाउनलोड** (`download_attachment`) — किसी रिकॉर्ड की अटैचमेंट फ़ाइल(फ़ाइलों) (xlsx, PDF, Word, …) को अटैचमेंट sys_id द्वारा या parent `table`+`record` द्वारा लोकल डिस्क पर fetch करें; किसी रिकॉर्ड के अटैचमेंट को स्वतः हल करता है और bytes को डिस्क पर लिखता है ताकि LLM उन्हें `saved_path` से पढ़े
- हर write टूल पर **dry-run पूर्वावलोकन** (`dry_run=True`) — किसी भी side effect से पहले field-level diff, निर्भरता गणना, और परिशुद्धता नोट्स लौटाता है। read-only APIs का उपयोग करता है, सभी auth मोड के अंतर्गत काम करता है।
- `confirm='approve'` के साथ सुरक्षित write पुष्टिकरण
- Payload सुरक्षा सीमाएँ, प्रति-field truncation, और कुल प्रतिक्रिया बजट (200K वर्ण)
- backoff के साथ क्षणिक नेटवर्क त्रुटि पुनः प्रयास
- core, standard, service desk, portal डेवलपर्स, और platform डेवलपर्स के लिए tool पैकेज — उन्नत उपयोगकर्ताओं के लिए `full` उपलब्ध (देखें [warning](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md))
- डेवलपर उत्पादकता टूल: गतिविधि ट्रैकिंग, अप्रतिबद्ध परिवर्तन, निर्भरता मैपिंग, दैनिक सारांश
- core ServiceNow artifact तालिकाओं की पूर्ण कवरेज (देखें [Supported Tables](https://github.com/jshsakura/mfa-servicenow-mcp#supported-servicenow-tables))
- auto-tagging, PyPI publishing, और Docker multi-platform builds के साथ CI/CD

### समर्थित ServiceNow तालिकाएँ

| Artifact Type | Table Name | Source Search | Developer Tracking | Safety (Heavy Table) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_script_client` | ✅ | ✅ | 🛡️ |
| Catalog Client Script | `catalog_script_client` | ✅ | ⬜ | ⬜ |
| UI Action | `sys_ui_action` | ✅ | ✅ | 🛡️ |
| UI Script | `sys_ui_script` | ✅ | ✅ | 🛡️ |
| UI Page | `sys_ui_page` | ✅ | ✅ | 🛡️ |
| UI Macro | `sys_ui_macro` | ✅ | ⬜ | 🛡️ |
| Scripted REST API | `sys_ws_operation` | ✅ | ✅ | 🛡️ |
| Fix Script | `sys_script_fix` | ✅ | ✅ | 🛡️ |
| Scheduled Job | `sysauto_script` | ✅ | ⬜ | ⬜ |
| Script Action | `sysevent_script_action` | ✅ | ⬜ | ⬜ |
| Email Notification | `sysevent_email_action` | ✅ | ⬜ | ⬜ |
| ACL | `sys_security_acl` | ✅ | ⬜ | ⬜ |
| Transform Script | `sys_transform_script` | ✅ | ⬜ | ⬜ |
| Processor | `sys_processor` | ✅ | ⬜ | ⬜ |
| Service Portal Widget | `sp_widget` | ✅ | ✅ | 🛡️ |
| Angular Provider | `sp_angular_provider` | ✅ | ✅ | ⬜ |
| Portal Header/Footer | `sp_header_footer` | ✅ | ⬜ | ⬜ |
| Portal CSS | `sp_css` | ✅ | ⬜ | ⬜ |
| Angular Template | `sp_ng_template` | ✅ | ⬜ | ⬜ |
| Metadata / XML Definitions | `sys_metadata` | ✅ | ⬜ | 🛡️ |
| Update XML | `sys_update_xml` | ✅ | ⬜ | ⬜ |

---

## Install (ऑफ़लाइन / कॉर्पोरेट)

अधिकांश उपयोगकर्ताओं के लिए ऊपर दिया गया [Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) (uvx) ही पर्याप्त है। दो कॉर्पोरेट-नेटवर्क विकल्प:

- **PyPI पहुँच योग्य है, लेकिन HTTPS TLS-निरीक्षित है** (Zscaler / Netskope / कॉर्पोरेट MITM) → ठीक नीचे **pip install (internal network behind TLS inspection)** देखें।
- **PyPI / uvx पूरी तरह ब्लॉक है** → और नीचे **Release zip/exe (local install)** देखें।

### pip install (TLS निरीक्षण के पीछे आंतरिक नेटवर्क — Zscaler आदि)

इसका उपयोग तब करें जब PyPI पहुँच योग्य **है** लेकिन एक TLS-निरीक्षण करने वाला proxy HTTPS को फिर से साइन करता है, जिससे installs और रनटाइम कॉल `SSL: CERTIFICATE_VERIFY_FAILED` के साथ विफल हो जाते हैं। proxy के root CA को **OS trust store** में पंजीकृत करना **पर्याप्त नहीं है** — Python (`pip`, `requests`, `httpx`), `curl_cffi`, और Playwright प्रत्येक अपना स्वयं का CA bundle (certifi / libcurl / node) रखते हैं और जब तक आप उन्हें env के ज़रिए cert की ओर इंगित न करें, OS store को अनदेखा करते हैं।

**1. proxy root CA प्राप्त करें** एक PEM फ़ाइल के रूप में (IT से पूछें, या इसे OS keychain से export करें)। मान लें यह `/etc/ssl/zscaler-root.pem` पर पहुँचती है (Windows: `C:\certs\zscaler-root.pem`)।

**2. Install** — installer को cert की ओर इंगित करें:

```bash
pip install --cert /etc/ssl/zscaler-root.pem mfa-servicenow-mcp
python -m playwright install chromium     # NODE_EXTRA_CA_CERTS (step 3) covers its download
```

uvx पसंद है? `uv` सीधे OS trust store का उपयोग कर सकता है (जहाँ proxy CA पहले से पंजीकृत है):

```bash
UV_NATIVE_TLS=1 uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
```

**3. रनटाइम — अपने MCP क्लाइंट `env` में CA path सेट करें।** जो स्पष्ट नहीं है: लाइव ServiceNow कॉल **curl_cffi (libcurl)** के माध्यम से जाती हैं, जो `CURL_CA_BUNDLE` पढ़ता है — *न कि* `REQUESTS_CA_BUNDLE`। इन सभी को सेट करें ताकि हर परत proxy पर भरोसा करे:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "servicenow-mcp",
      "args": [],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "CURL_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "REQUESTS_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "SSL_CERT_FILE": "/etc/ssl/zscaler-root.pem",
        "NODE_EXTRA_CA_CERTS": "/etc/ssl/zscaler-root.pem"
      }
    }
  }
}
```

| Env var | यह जिस परत को ठीक करता है |
|---------|----------------|
| `CURL_CA_BUNDLE` | **curl_cffi / libcurl — असली ServiceNow API + browser-login probe कॉल** |
| `REQUESTS_CA_BUNDLE` | `requests` (OAuth / API-key token कॉल, fallback HTTP path) |
| `SSL_CERT_FILE` | Python stdlib `ssl` / `httpx` / `uv` |
| `NODE_EXTRA_CA_CERTS` | Playwright का Chromium डाउनलोड |
| `PIP_CERT` (केवल install) | PyPI से fetch करता `pip` (`--cert` के समान) |

पूरी तरह-निरीक्षित नेटवर्क में proxy हर host को फिर से साइन करता है, इसलिए एकल proxy-root PEM सभी HTTPS को कवर करता है। यदि कुछ hosts proxy को **bypass** करते हैं, तो proxy root को certifi के bundle के साथ जोड़ें (`python -m certifi` इसका path प्रिंट करता है) एक PEM में और env vars को उसकी ओर इंगित करें।

> अंतिम उपाय यदि आप वास्तव में PEM प्राप्त नहीं कर सकते: `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org mfa-servicenow-mcp` केवल **install के लिए** सत्यापन को छोड़ देता है — यह रनटाइम ServiceNow कॉल के लिए कुछ नहीं करता, जिन्हें अभी भी `CURL_CA_BUNDLE` की ज़रूरत होती है। cert path को प्राथमिकता दें; `--trusted-host` एक सुरक्षा नियंत्रण को अक्षम करता है।

### Release zip/exe (local install)

इस path का उपयोग तब करें जब `uvx` या PyPI को कॉर्पोरेट सुरक्षा द्वारा ब्लॉक किया गया हो। release zip एक **PyInstaller-निर्मित single-file executable** भेजता है — कोई Python आवश्यक नहीं, कोई installer script नहीं, कोई system-cache प्रदूषण नहीं। executable अपने बगल में रखी `ms-playwright/` डायरेक्टरी को स्वतः-पहचानता है, इसलिए पूरा install "unzip करें और अपने MCP क्लाइंट को इसकी ओर इंगित करें" है।

#### 1. डाउनलोड

executable [latest release](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest) पर है। Chromium bundle — केवल तब आवश्यक जब नेटवर्क Playwright के स्वयं के Chromium डाउनलोड को भी ब्लॉक करता है — हर release पर फिर से संलग्न **नहीं** किया जाता (यह ~150 MB का है और केवल Playwright के साथ बदलता है); इसे दीर्घकालिक [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) release से प्राप्त करें।

| Platform | आवश्यक (latest release) | Chromium डाउनलोड ब्लॉक होने पर यह भी जोड़ें (chromium-bundle release) |
|----------|---------------------------|------------------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

#### 2. यह फ़ोल्डर लेआउट बनाएँ

कोई भी डायरेक्टरी चुनें जिस पर आपका नियंत्रण हो (`~/apps/servicenow-mcp/`, `D:\Tools\servicenow-mcp\`, आदि — बस इसे स्थिर रखें)। **दोनों zips को पहले से extract करें** — `.zip` फ़ाइलों को executable के बगल में पड़ा न रहने दें। Chromium zip की extracted डायरेक्टरी को बस `ms-play` से शुरू होना चाहिए और एक `chromium-*` उप-डायरेक्टरी रखनी चाहिए; आपका unzip टूल जो भी नाम उत्पन्न करता है, ठीक है:

```
~/apps/servicenow-mcp/                                  (any directory you choose)
├── servicenow-mcp                                      ← from the platform zip (.exe on Windows)
└── ms-playwright-chromium-linux-x64-1.13.7/            ← default extracted name works
    └── chromium-1185/                                  (one of these is enough)
        └── …
```

या, यदि आप एक साफ़ नाम चाहते हैं, तो इसे केवल `ms-playwright/` नामक फ़ोल्डर में extract करें। दोनों काम करते हैं — executable स्टार्टअप पर किसी भी sibling `ms-play*` डायरेक्टरी के लिए glob करता है और, अंदर एक `chromium-*` उप-डायरेक्टरी पाने पर, `PLAYWRIGHT_BROWSERS_PATH` को उस path पर सेट करता है **केवल वर्तमान प्रक्रिया के लिए**। यह डिस्क पर कहीं नहीं लिखता, आपके MCP क्लाइंट कॉन्फ़िग को संपादित नहीं करता, और सिस्टम-व्यापी Playwright cache (`~/.cache/ms-playwright`, `%LOCALAPPDATA%\ms-playwright`, …) को नहीं छूता। यदि Chromium bundled नहीं है, तो Playwright अपनी स्वयं की खोज पर वापस आ जाता है — अपने MCP env में `PLAYWRIGHT_BROWSERS_PATH` स्वयं सेट करें या किसी पहुँच योग्य स्थान पर `playwright install chromium` चलाएँ।

#### 3. बाइनरी की sanity-check करें

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

यदि version प्रिंट होता है, तो आपका बाइनरी आधा हिस्सा पूरा हो गया — शेष हर चरण केवल कॉन्फ़िग है।

#### 4. इसे अपने MCP क्लाइंट में wire करें (copy-paste)

[Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) में `uvx` path के समान क्लाइंट कॉन्फ़िग का पुनः उपयोग करें — केवल `command` आपके executable के absolute path में बदलता है, `env` block समान रहता है। Claude Code उदाहरण:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "/home/you/apps/servicenow-mcp/servicenow-mcp",
      "args": [],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}
```

Windows पर `"command"` को `"C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe"` से बदलें।

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` वैकल्पिक हैं (MFA लॉगिन pre-fill)। यदि Chromium executable के बगल के बजाय कहीं और रहता है, तो env block में `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` जोड़ें। Codex (TOML), OpenCode, Cursor, VS Code Copilot, Antigravity, Zed स्निपेट: [Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md)।

#### Chromium fallback (वैकल्पिक)

यदि आपने Chromium zip छोड़ दिया और Playwright का auto-download ब्लॉक है, तो किसी भी Python वाली मशीन पर डायरेक्टरी को pre-stage करें:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

परिणाम वही `ms-playwright/chromium-*/…` लेआउट है जो bundled zip उत्पन्न करता है, इसलिए auto-detect बिना किसी अतिरिक्त कॉन्फ़िग के इसे उठा लेता है।

> Windows उपयोगकर्ता: PATH और antivirus नोट्स के लिए [Windows Installation Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md) देखें।

---

## MCP Client Configuration

> अनुशंसित: ऊपर दिए गए [Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) का उपयोग करें। नीचे दिए गए copy-paste कॉन्फ़िग का उपयोग तब करें जब आपको किसी क्लाइंट कॉन्फ़िग फ़ाइल का निरीक्षण, मरम्मत, या हाथ से-प्रबंधन करना हो।

प्रत्येक प्रोजेक्ट एक अलग ServiceNow इंस्टेंस से कनेक्ट हो सकता है। कॉन्फ़िग को अपनी **प्रोजेक्ट डायरेक्टरी** में सेट करें ताकि हर प्रोजेक्ट का अपना इंस्टेंस URL और क्रेडेंशियल हो।

| Client | Project Config | Global Config | Format |
|--------|---------------|--------------|--------|
| Claude Code | `.mcp.json` | `~/.claude.json` | JSON |
| Cursor | `.cursor/mcp.json` | *केवल प्रोजेक्ट* | JSON |
| VS Code (Copilot) | `.vscode/mcp.json` | *केवल प्रोजेक्ट* | JSON |
| Zed | *केवल Global* | `~/.config/zed/settings.json` | JSON |
| OpenAI Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML |
| OpenCode | `opencode.json` | *केवल प्रोजेक्ट* | JSON |
| Windsurf | *केवल Global* | `~/.codeium/windsurf/mcp_config.json` | JSON |
| Claude Desktop | *केवल Global* | `claude_desktop_config.json` | JSON |
| AntiGravity | *केवल Global* | `~/.gemini/antigravity/mcp_config.json` | JSON |
| Docker | *केवल Env vars* | *केवल Env vars* | Env vars |

प्रत्येक क्लाइंट के लिए copy-paste कॉन्फ़िग: **[Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` वैकल्पिक हैं — ये MFA लॉगिन फ़ॉर्म को prefill करते हैं। Windows पर, इन्हें सिस्टम environment variables के रूप में सेट करें।

#### एक क्लाइंट में कई इंस्टेंस (dev / test / prod)

ऊपर दिए गए उदाहरण single-instance हैं — यही डिफ़ॉल्ट रहता है। एक क्लाइंट से कई इंस्टेंस के बीच स्विच करने के लिए, उन्हें `SERVICENOW_INSTANCE_CONFIG` (alias → settings) में सूचीबद्ध करें और सक्रिय वाले को `SERVICENOW_ACTIVE_INSTANCE` से चुनें। प्रत्येक alias अपने **स्वयं के क्रेडेंशियल** (`username` / `password` / `auth_type` / `api_key`) रख सकता है; `${ENV}` संदर्भ secrets को JSON से बाहर रखते हैं। single-instance `SERVICENOW_INSTANCE_URL` रूप अभी भी fallback के रूप में काम करता है।

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

`SERVICENOW_ACTIVE_INSTANCE` वह इंस्टेंस है जहाँ writes डिफ़ॉल्ट रूप से जाते हैं; read टूल `instance="test"` के साथ अन्य में झाँक सकते हैं, और `instance="test" confirm_instance="test" confirm="approve"` के साथ एक single write को किसी non-active इंस्टेंस पर route किया जा सकता है (गार्डेड, और land होने के बाद सत्यापित)। पूर्ण नियम (write routing, gating, तुलना, `${ENV}`): [Multi-Instance Mode](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md#multi-instance-mode-comparison--guarded-single-call-writes)।

---

## Authentication

अपने ServiceNow वातावरण के आधार पर auth मोड चुनें।

### Browser Auth (MFA/SSO) — Default

[Setup](https://github.com/jshsakura/mfa-servicenow-mcp#setup) कमांड डिफ़ॉल्ट रूप से browser auth का उपयोग करता है। वैकल्पिक फ़्लैग:

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | लॉगिन फ़ॉर्म username को prefill करें |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | लॉगिन फ़ॉर्म password को prefill करें |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | ब्राउज़र को GUI के बिना चलाएँ |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | सेकंड में लॉगिन timeout |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | मिनटों में सत्र TTL |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Chromium प्रोफ़ाइल path को override करें। शायद ही कभी आवश्यक — इसे सेट करने से पहले नीचे sandbox नोट देखें। |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | जब username ज्ञात हो तो उपयोगकर्ता-विशिष्ट `sys_user` lookup, अन्यथा `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | सत्र सत्यापन endpoint (non-admin सत्रों पर 401 से बचता है) |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | कस्टम लॉगिन पेज URL |

#### hosts और instances के बीच लॉगिन साझाकरण — यह वास्तव में कैसे काम करता है

सर्वर `~/.mfa_servicenow_mcp/` के अंतर्गत दो चीज़ें cache करता है: Playwright प्रोफ़ाइल (Chromium SSO cookies) और एक session JSON (अगले स्टार्ट पर पुनः उपयोग किए गए parsed cookies)। दोनों **प्रति instance + username स्कोप किए गए हैं** — फ़ाइलों के नाम `profile_<host>_<user>` और `session_<host>_<user>.json` हैं।

वह स्कोपिंग आपके लिए स्वतः दो चीज़ें करती है, **बिना किसी कॉन्फ़िगरेशन** के:

- **कई hosts एक लॉगिन साझा करते हैं।** एक ही मशीन पर Claude Code और Codex दोनों `~/.mfa_servicenow_mcp/` को resolve करते हैं, इसलिए जो भी पहले लॉगिन करता है वह session लिखता है और दूसरा उसका पुनः उपयोग करता है — कोई दूसरा MFA प्रॉम्प्ट नहीं।
- **विभिन्न instances / विभिन्न क्रेडेंशियल अलग रहते हैं।** प्रत्येक instance+user को अपनी प्रोफ़ाइल और session फ़ाइल मिलती है, इसलिए dev और test (या दो खाते) कभी टकराते नहीं। कई instances के लिए, उन्हें `SERVICENOW_INSTANCE_CONFIG` (JSON) में कॉन्फ़िगर करें — प्रत्येक alias को अपना स्कोप किया गया cache मिलता है; आप इसे प्रोफ़ाइल path से प्रबंधित **नहीं** करते।

**logins को "साझा" करने के लिए `SERVICENOW_BROWSER_USER_DATA_DIR` सेट न करें।** यह प्रोफ़ाइल path को हू-ब-हू override करता है — प्रति-instance स्कोपिंग bypass हो जाती है, इसलिए आप जो भी instance चलाते हैं उसे एक Chromium प्रोफ़ाइल में बाध्य कर दिया जाता है और उनके cookies टकराते हैं। एकमात्र वैध उपयोग एक संकीर्ण है: एक **sandboxed** host (जैसे macOS पर Claude Desktop) जो `HOME` को एक कंटेनर path पर remap करता है, इसलिए इसका `~/.mfa_servicenow_mcp/` अब टर्मिनल के साथ मेल नहीं खाता। उस single-instance स्थिति में, sandboxed host को असली home path की ओर इंगित करें:

```bash
# Only when a sandbox remapped HOME, and only for a single-instance host
export SERVICENOW_BROWSER_USER_DATA_DIR="/Users/you/.mfa_servicenow_mcp/profile_acme"
```

यदि आप एक से अधिक instance चलाते हैं, तो इसे unset छोड़ दें और प्रति-instance स्कोपिंग को अपना काम करने दें।

### Basic Auth

इसका उपयोग PDIs या MFA के बिना instances के लिए करें।

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth

वर्तमान CLI समर्थन OAuth password grant inputs की अपेक्षा करता है।

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

यदि `--token-url` छोड़ दिया जाता है, तो सर्वर डिफ़ॉल्ट रूप से `https://<instance>/oauth_token.do` पर जाता है।

### API Key

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

डिफ़ॉल्ट header: `X-ServiceNow-API-Key` (`--api-key-header` के साथ अनुकूलन योग्य)।

---

## Tool Packages

`MCP_TOOL_PACKAGE` नियंत्रित करता है कि सर्वर कौन से टूल एक्सपोज़ करता है। **डिफ़ॉल्ट: `standard`** — अधिकांश उपयोगकर्ताओं के लिए कोई कॉन्फ़िग आवश्यक नहीं।

> [!WARNING]
> **`standard` से ऊपर कोई भी पैकेज write पहुँच देता है और एक उन्नत विकल्प है।** `service_desk`, `portal_developer`, `platform_developer`, और `full` सभी एक AI agent को रिकॉर्ड्स बनाने, अपडेट करने, और डिलीट करने देते हैं — `full` ऐसा हर डोमेन में एक साथ करता है। अधिकांश उपयोगकर्ताओं को read-only डिफ़ॉल्ट `standard` पर बने रहना चाहिए और केवल उतने ही संकीर्ण write पैकेज तक opt up करना चाहिए जितना उनका कार्य वास्तव में आवश्यक करता है।

Read-only (सुरक्षित डिफ़ॉल्ट):

| Package | Tools | Description |
| :--- | :---: | :--- |
| `none` | 0 | जानबूझकर टूल बंद करने के लिए Disabled प्रोफ़ाइल |
| `core` | 12 | health, schema, discovery, और प्रमुख artifact lookups के लिए न्यूनतम read-only आवश्यक चीज़ें |
| `standard` | 27 | **(Default)** incidents, changes, portal, logs, और source विश्लेषण के पार read-only |

⚠️ Write-capable (उन्नत — create/update/delete देता है):

| Package | Tools | Description |
| :--- | :---: | :--- |
| `service_desk` | 29 | ⚠️ standard + incident और change ऑपरेशनल writes |
| `portal_developer` | 38 | ⚠️ standard + portal, changeset, script include, और local-sync डिलीवरी writes |
| `platform_developer` | 43 | ⚠️ standard + workflow, Flow Designer, UI policy, incident/change, और script writes |
| `full` | 57 | ⚠️ **सबसे उन्नत** — सभी डोमेन में सभी write टूल एक साथ |

प्रत्येक सर्वर प्रक्रिया सामान्य टूल के लिए एक सक्रिय ServiceNow instance से बंधती है। किसी *भिन्न* कॉन्फ़िगर किए गए instance पर write प्रति-कॉल संभव है, लेकिन केवल एक स्पष्ट, गार्डेड स्वीकृति (नीचे) के माध्यम से — कभी कोई चुपचाप स्विच नहीं।

### Multi-Instance Mode (comparison + guarded single-call writes)

जब आपको dev/test/prod की तुलना करनी हो या किसी चुने हुए instance पर deploy करना हो, तो `SERVICENOW_INSTANCE_CONFIG` के साथ named instances में opt in करें। `SERVICENOW_ACTIVE_INSTANCE` अभी भी आवश्यक है।

दो चीज़ें global हैं, एक प्रति-instance है:

- **Tool surface global है** — `MCP_TOOL_PACKAGE` के साथ एक बार सेट करें। प्रति सर्वर प्रक्रिया केवल एक instance ही कभी सक्रिय होता है, इसलिए कोई प्रति-instance tool पैकेज नहीं है।
- **Write अनुमति प्रति-instance है** — प्रत्येक alias `allow_writes` रखता है। इसे call time पर सक्रिय instance के विरुद्ध लागू किया जाता है: एक write टूल load किया जा सकता है लेकिन फिर भी अस्वीकार किया जा सकता है यदि सक्रिय instance में `allow_writes: false` हो। Writes opt-in हैं: `allow_writes` छोड़ें और instance read-only हो जाता है।
- **क्रेडेंशियल प्रति-instance हैं और global fallback के साथ** — override करने के लिए किसी alias पर `username` / `password` / `api_key` (और `auth_type`) रखें; उन्हें छोड़ें और alias global `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` / आदि को inherit करता है। इसलिए यदि हर instance एक लॉगिन साझा करता है, तो इसे एक बार globally सेट करें और alias entries को credential-free छोड़ दें।

अन्य नियम:

- **Read टूल एक `instance` argument स्वीकार करते हैं** ताकि किसी non-active instance के विरुद्ध एकल read चलाया जा सके — जैसे `sn_query(instance="test", table="incident", ...)` या `sn_health(instance="test")` जबकि `dev` सक्रिय रहता है। आपके पैकेज में हर read टूल इसे अपने schema में एक्सपोज़ करता है (कॉन्फ़िगर किए गए aliases का enum)। यही तरीका है जिससे आप पुनः आरंभ किए बिना किसी अन्य instance के डेटा में झाँकते हैं।
- **किसी non-active instance पर एक single write भी route की जा सकती है**, लेकिन कभी चुपचाप नहीं। `instance="test" confirm_instance="test" confirm="approve"` पास करें (टार्गेट को दो बार नामित करें — इरादे और स्वीकृति दोनों के रूप में) और टार्गेट के पास `allow_writes=true` होना चाहिए। केवल वही एक write वहाँ जाती है; सक्रिय instance तुरंत बाद बहाल हो जाता है। टार्गेट/confirm बेमेल या read-only टार्गेट को एक स्पष्ट संदेश के साथ अस्वीकार कर दिया जाता है, इसलिए dev/test/prod का घालमेल गलत instance पर नहीं लग सकता। फिर write को टार्गेट पर फिर से पढ़ा जाता है और `landed` (या `WRITE_NOT_LANDED`) के रूप में रिपोर्ट किया जाता है, साथ `target_instance` echo होता है — "success" का अर्थ है कि सामग्री इच्छित instance पर मौजूद होने की पुष्टि हुई, न कि केवल 200 मिला।
- `list_instances` कॉन्फ़िगर किए गए aliases के साथ-साथ सक्रिय वाले और प्रत्येक का write flag रिपोर्ट करता है। `compare_instances` aliases के पार read-only तालिका तुलना करता है।
- *डिफ़ॉल्ट* सक्रिय instance को स्विच करने के लिए MCP क्लाइंट को पुनः आरंभ करने की आवश्यकता होती है — इसे सर्वर स्टार्टअप पर एक बार पढ़ा जाता है, लाइव refresh नहीं किया जाता। (ऊपर दी गई प्रति-कॉल `instance=` routing को पुनः आरंभ की आवश्यकता नहीं।)

उदाहरण — साझा global लॉगिन, प्रति-instance write gating:

```bash
export MCP_TOOL_PACKAGE=standard
export SERVICENOW_USERNAME=svc_account
export SERVICENOW_PASSWORD='...'
export SERVICENOW_ACTIVE_INSTANCE=dev
export SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "allow_writes": false }
}'
```

किसी instance को इसके बजाय इसका अपना लॉगिन देने के लिए, उस alias में fields जोड़ें (एक `${ENV}` संदर्भ resolve हो जाता है, इसलिए आप secrets को JSON से बाहर रख सकते हैं):

```json
"prod": { "url": "https://acme.service-now.com", "username": "prod_user", "password": "${SERVICENOW_PROD_PASSWORD}" }
```

dev/test drift जाँच के लिए `compare_instances` का उपयोग करें। **बहुत सारे** रिकॉर्ड्स को promote करने के लिए (विशेषकर Service Portal / scoped तालिकाएँ), प्रति-रिकॉर्ड cross-instance writes के बजाय एक Update Set को प्राथमिकता दें (source पर commit, target UI में retrieve + commit) — यह उन per-table/SP ACLs को bypass करता है जिनसे single Table-API writes टकराती हैं।

यदि आपके वर्तमान पैकेज में कोई टूल उपलब्ध नहीं है, तो सर्वर आपको बताता है कि कौन सा पैकेज इसे शामिल करता है।

पूर्ण संदर्भ के लिए (सभी पैकेज, inheritance विवरण, कॉन्फ़िग syntax): [Tool Packages Advanced Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md)।

---

## CLI Reference

### Server Options

| Flag | Env Variable | Default | Description |
|------|-------------|---------|-------------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *आवश्यक* | ServiceNow instance URL |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | Auth मोड: `basic`, `oauth`, `api_key`, `browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | Load करने के लिए tool पैकेज |
| `--transport` | `SERVICENOW_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` या `http` |
| `--http-host` | `SERVICENOW_MCP_HTTP_HOST` | `127.0.0.1` | `--transport http` के लिए Host |
| `--http-port` | `SERVICENOW_MCP_HTTP_PORT` | `8000` | `--transport http` के लिए Port |
| `--http-path` | `SERVICENOW_MCP_HTTP_PATH` | `/mcp` | Streamable HTTP endpoint path |
| `--http-allowed-hosts` | `SERVICENOW_MCP_HTTP_ALLOWED_HOSTS` | loopback hosts | DNS rebinding सुरक्षा के लिए comma-separated Host allowlist |
| `--http-disable-dns-rebinding-protection` | `SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | विश्वसनीय नेटवर्क नियंत्रणों के पीछे DNS rebinding सुरक्षा अक्षम करें |
| `--http-json-response` | `SERVICENOW_MCP_HTTP_JSON_RESPONSE` | `false` | SSE streams के बजाय JSON responses लौटाएँ |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP request timeout (सेकंड) |
| `--debug` | `SERVICENOW_DEBUG` | `false` | Debug logging सक्षम करें |

HTTP transport उदाहरण:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP endpoint `http://127.0.0.1:8000/mcp` है; `/health` एक lightweight health प्रतिक्रिया लौटाता है।

### Basic Auth

| Flag | Env Variable |
|------|-------------|
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### OAuth

| Flag | Env Variable |
|------|-------------|
| `--client-id` | `SERVICENOW_CLIENT_ID` |
| `--client-secret` | `SERVICENOW_CLIENT_SECRET` |
| `--token-url` | `SERVICENOW_TOKEN_URL` |
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### API Key

| Flag | Env Variable | Default |
|------|-------------|---------|
| `--api-key` | `SERVICENOW_API_KEY` | — |
| `--api-key-header` | `SERVICENOW_API_KEY_HEADER` | `X-ServiceNow-API-Key` |

### Script Execution

| Flag | Env Variable |
|------|-------------|
| `--script-execution-api-resource-path` | `SCRIPT_EXECUTION_API_RESOURCE_PATH` |

---

## Keeping Up to Date

> **`uvx` अपने द्वारा डाउनलोड किए गए अंतिम version को cache करता है** और उसी का पुनः उपयोग करता रहता है।
> कोई नया release पाने के लिए आपको स्पष्ट रूप से refresh करना होगा — यह स्वयं अपडेट नहीं होगा।

```bash
# Refresh the uvx cache to the latest PyPI release
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

refresh करने के बाद, नए version को load करने के लिए **अपने MCP क्लाइंट को पुनः आरंभ करें** (Claude Code, Cursor, आदि)।

### पहला ब्राउज़र कॉल Chromium डाउनलोड करता है

uvx नवीनतम `mfa-servicenow-mcp` और Playwright को resolve करता है, और एक नया Playwright release एक नया Chromium build भेजता है। तब *पहले* ब्राउज़र टूल कॉल को ~150 MB ब्राउज़र बाइनरी fetch करनी पड़ती है — जो धीमे लिंक पर MCP host के handshake timeout को पार कर सकती है और इस रूप में सामने आती है:

```text
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

पहले कॉल से **पहले** Chromium install करके इससे बचें (ऊपर दिए गए setup कमांड पहले से ही ऐसा करते हैं):

```bash
uvx --with playwright playwright install chromium
```

#### Upgrading

uvx नवीनतम `mfa-servicenow-mcp` और `playwright` को स्वतः-resolve करता है — आपके कॉन्फ़िग में bump करने के लिए कोई versions नहीं हैं। refresh करने के लिए:

```bash
# Re-install Chromium in case a newer Playwright shipped a new build, then
# restart your MCP client
uvx --with playwright playwright install chromium
```

> **हम अब MCP सर्वर के अंदर Chromium स्वतः-install क्यों नहीं करते:** वह डाउनलोड पहले टूल कॉल के दौरान चलता था। धीमे लिंक पर subprocess host की handshake समय-सीमा से अधिक जीवित रहा और क्लाइंट ने "connection closed" की रिपोर्ट दी। v1.13.1 ने इसे बदल दिया — MCP सर्वर अब केवल *चेतावनी* देता है यदि Chromium गायब है। इसे पहले से `uvx --with playwright playwright install chromium` (out-of-band, कोई handshake timer नहीं) के साथ install करें।

---

## Safety Policy

सभी mutating टूल स्पष्ट पुष्टिकरण द्वारा संरक्षित हैं।

नियम:
1. `create_`, `update_`, `delete_`, `remove_`, `add_`, `move_`, `activate_`, `deactivate_`, `commit_`, `publish_`, `submit_`, `approve_`, `reject_`, `resolve_`, `reorder_`, और `execute_` जैसे उपसर्गों वाले mutating टूल को पुष्टिकरण की आवश्यकता होती है।
2. आपको `confirm='approve'` पास करना होगा।
3. उस parameter के बिना, सर्वर execution से पहले अनुरोध को अस्वीकार कर देता है।

यह नीति चयनित tool पैकेज की परवाह किए बिना लागू होती है।

### Write Guards

confirm गेट से परे, हर write deterministic गार्ड के माध्यम से चलता है जो असुरक्षित writes को ServiceNow तक पहुँचने से *पहले* ब्लॉक करते हैं। concurrent-edit और duplicate-create जाँच confirm गेट के **बाद** चलती हैं, इसलिए एक अपुष्ट write कभी नेटवर्क को नहीं छूता। प्रत्येक गार्ड एक अस्वीकृत/विफल pre-read पर **open** fail होता है — यह कभी किसी वैध write को केवल इसलिए ब्लॉक नहीं करता क्योंकि वह पहले देख नहीं सका। उद्देश्य सरल है: **आपको कभी भी किसी साथी के परिवर्तन को चुपचाप मिटाने में सक्षम नहीं होना चाहिए** — यदि किसी और ने रिकॉर्ड को छुआ है, तो write रुक जाता है और आपको बताता है, बजाय इसके कि overwrite करके आगे बढ़ जाए।

| Guard | किससे बचाता है | Override / toggle |
|---|---|---|
| Concurrent edit (G3/G8) | किसी रिकॉर्ड को आँख मूँदकर overwrite करना जिसे एक **भिन्न उपयोगकर्ता** ने पिछले 10 मिनट के भीतर संपादित किया। `sn_write`, `manage_portal_component`, और `manage_*` update टूल को कवर करता है — जिसमें `manage_script_include`, `manage_flow_designer`, `manage_workflow`, `manage_kb_article`, `manage_portal_layout`, और `manage_widget_dependency` शामिल हैं। `sys_updated_by`/`sys_updated_on` के एक **लाइव remote read** द्वारा निर्णय लिया जाता है — कभी लोकल कॉपी द्वारा नहीं। | `SERVICENOW_CONCURRENT_EDIT_GUARD=off`; window `SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN` के माध्यम से (डिफ़ॉल्ट `10`) |
| Source push drift (baseline + update-set HOLD) | `update_remote_from_local` के साथ संपादित source को वापस push करना दो जाँच जोड़ता है जिन्हें time-window नहीं पकड़ सकता: remote के वर्तमान `sys_updated_on` की डाउनलोड के समय दर्ज मूल्य के विरुद्ध एक **time-independent** तुलना (घंटों या **दिनों** बाद के overwrite को पकड़ता है), और रिकॉर्ड के किसी अन्य उपयोगकर्ता के अप्रतिबद्ध update set में **रखे जाने** की एक लाइव जाँच। | किसी पहचाने गए drift को पार करके push करने के लिए `force=true` |
| Duplicate create (G9) | ऐसे नाम के साथ चुपचाप एक दूसरा रिकॉर्ड बनाना जो पहले से मौजूद है, उन तालिकाओं पर जिन्हें ServiceNow unique नहीं बनाता (`sys_update_set`, `wf_workflow`, `sys_user_group`, `sys_user`)। | वैसे भी बनाने के लिए `allow_duplicate='true'` पास करें |
| Flow Designer raw write (G6) | `sys_hub_*` तालिकाओं पर raw `sn_write` जो flow snapshots को भ्रष्ट करता है — `manage_flow_designer` को बाध्य करता है। | — |
| Publish-class (G7) | आकस्मिक publish/commit/push — एक दूसरे `confirm_publish='approve'` की आवश्यकता है। | — |
| Cross-instance push | instance A से डाउनलोड किए गए लोकल source को instance B में push करना (origin `_settings.json` / `_manifest.json` से पढ़ा गया)। | सही instance से फिर से डाउनलोड करें |

पूरी परत को `SERVICENOW_WRITE_GUARDS=off` के साथ अक्षम करें। multi-instance मोड में, हर write प्रतिक्रिया एक `instance_target` field भी रखती है (और कहीं और रूट किए गए reads एक `instance_source`) ताकि कॉल जिस instance को छूता है वह हमेशा दृश्यमान रहे।

### Portal Investigation Safety

Portal investigation टूल डिफ़ॉल्ट रूप से conservative हैं:

- `search_portal_regex_matches` widget-only scanning, linked expansion off, और छोटी डिफ़ॉल्ट सीमाओं के साथ शुरू होता है।
- `trace_portal_route_targets` कॉम्पैक्ट Widget -> Provider -> route target साक्ष्य के लिए पसंदीदा follow-up है।
- `download_portal_sources` स्पष्ट रूप से अनुरोध किए बिना linked Script Includes या Angular Providers नहीं खींचता।
- बड़े portal scans सर्वर-साइड capped हैं और जब अनुरोध सुरक्षित डिफ़ॉल्ट से अधिक होता है तो warnings लौटाते हैं।

Pattern matching मोड:

| Mode | Behavior |
|------|----------|
| `auto` (default) | Plain strings को literally माना जाता है, regex-दिखने वाले patterns regex रहते हैं |
| `literal` | पहले हमेशा pattern को escape करें; route/token strings के लिए सबसे सुरक्षित |
| `regex` | केवल तब उपयोग करें जब आपको जानबूझकर regex operators की आवश्यकता हो |

---

## Performance Optimizations

सर्वर में latency और token उपयोग को कम करने के लिए performance optimization की कई परतें शामिल हैं।

### Serialization

- **orjson backend**: सभी JSON serialization `json_fast` का उपयोग करती है (उपलब्ध होने पर orjson, stdlib fallback)। loads और dumps दोनों के लिए stdlib `json` से 2-4x तेज़।
- **Compact output**: टूल responses को indentation या अतिरिक्त whitespace के बिना serialize किया जाता है, प्रति प्रतिक्रिया 20-30% tokens बचाते हुए।
- **Double-parse avoidance**: `serialize_tool_output` पहले से-compact JSON strings का पता लगाता है और re-serialization को छोड़ देता है।

### Caching

- **OrderedDict LRU cache**: Query परिणाम `OrderedDict.popitem()` का उपयोग करके O(1) eviction के साथ cache किए जाते हैं। 256 अधिकतम entries, 30-सेकंड TTL (स्थिर metadata के लिए 600s: schema/scope/choice तालिकाएँ), thread-safe।
- **Tool schema cache**: Pydantic `model_json_schema()` output को प्रति model प्रकार cache किया जाता है, बार-बार schema generation से बचते हुए।
- **Lazy tool discovery**: स्टार्टअप पर केवल सक्रिय `MCP_TOOL_PACKAGE` द्वारा आवश्यक tool modules import किए जाते हैं। अप्रयुक्त modules को पूरी तरह छोड़ दिया जाता है।

### Network

- **डिफ़ॉल्ट रूप से Browser-grade TLS**: HTTP परत एक Chrome impersonation प्रोफ़ाइल (`chrome120` डिफ़ॉल्ट रूप से) के साथ `curl_cffi` के माध्यम से रूट करती है, इसलिए TLS handshake असली ब्राउज़र की तरह byte-for-byte होता है — Cloudflare/Akamai या JA3 bot-detection के पीछे के instances जो stock Python `requests` को अस्वीकार करते हैं, बिना अतिरिक्त कॉन्फ़िग के काम करते हैं। `SERVICENOW_TLS_IMPERSONATE=off` के साथ opt out करें।
- **HTTP session pooling**: TCP keep-alive और gzip/deflate compression के साथ persistent session (बड़े JSON पर 60-80% payload कमी)। stock-`requests` opt-out path एक 20-connection `HTTPAdapter` mount करता है।
- **Parallel pagination**: `sn_query_all` कुल गणना के लिए पहले पेज को sequentially fetch करता है, फिर शेष पेजों को `ThreadPoolExecutor` (4 workers तक) के माध्यम से concurrently retrieve करता है।
- **Dynamic page sizing**: जब शेष रिकॉर्ड एक ही पेज में fit होते हैं (<=100), तो अतिरिक्त round-trips से बचने के लिए page size को बढ़ा दिया जाता है।
- **Batch API**: `sn_batch` कई REST sub-requests को एक ही `/api/now/batch` POST में जोड़ता है, 150-request सीमा पर स्वचालित chunking के साथ।
- **Parallel chunked M2M queries**: Widget-to-provider M2M lookups जो 100-ID chunks में विभाजित होते हैं, sequentially के बजाय concurrently execute किए जाते हैं।

### Schema & Startup

- **Shallow-copy schema injection**: Confirmation schema (`confirm='approve'`) को `copy.deepcopy` के बजाय lightweight dict copy के माध्यम से inject किया जाता है, `list_tools` overhead को कम करते हुए।
- **No-count optimization**: बाद के pagination पेज server-side कुल गणना computation को छोड़ने के लिए `sysparm_no_count=true` का उपयोग करते हैं।
- **Payload safety**: Heavy तालिकाओं (`sp_widget`, `sys_script`, आदि) में context window overflow को रोकने के लिए स्वचालित field clamping और सीमा प्रतिबंध होते हैं।

## Local Source Audit

अपने पूरे ServiceNow application को locally डाउनलोड और विश्लेषण करें — कोई बार-बार API कॉल नहीं, कोई context बर्बादी नहीं।

```
Step 1: download_app_sources(scope="x_company_app")    → All server-side code + cross-scope deps to disk
Step 2: audit_local_sources(source_root="temp/...")     → Analysis + HTML report
```

Step 1 डिफ़ॉल्ट रूप से `auto_resolve_deps=True` चलाता है: in-scope डाउनलोड के बाद यह हर
`.js/.html/.xml` फ़ाइल को scan करता है और bundle में पहले से नहीं मौजूद किसी भी संदर्भित `sys_script_include`, `sp_widget`,
`sp_angular_provider`, या `sys_ui_macro` रिकॉर्ड को fetch करता है — चाहे वे जिस भी
scope में रहते हों। खींचे गए deps को उसी tree में उनके `_metadata.json` में
`"is_dependency": true` के साथ save किया जाता है, ताकि Step 2 में ऑडिट पूर्ण
call graph देखे। यदि आप केवल in-scope रिकॉर्ड चाहते हैं तो `auto_resolve_deps=False` सेट करें।

> **टिप — `global` सहित पूरा scope खींचें:** हर global-scope रिकॉर्ड को dump करने के लिए `scope="global"`
> पास करें, या अपना ऐप scope रखें और `auto_resolve_deps` को उन रिकॉर्ड के लिए
> `global` में पहुँचने दें जिन्हें आप वास्तव में संदर्भित करते हैं। किसी भी तरह से लोकल bundle
> स्व-निहित है, इसलिए विश्लेषण पूरी तरह से डिस्क के विरुद्ध ऑफ़लाइन चलता है।

### Incremental Sync

हर run पर एक बड़े ऐप को फिर से डाउनलोड करना धीमा है और timeouts का जोखिम रखता है। `incremental=True` पास करें
ताकि **केवल वही fetch हो जो पिछले डाउनलोड के बाद बदला** — एक नए `clone` के बजाय `git pull` की तरह।
`download_app_sources` और `download_portal_sources` दोनों पर काम करता है।

```
download_app_sources(scope="x_company_app")                      # 1st run: full download
download_app_sources(scope="x_company_app", incremental=True)    # later: changed records only
```

- **यह कैसे काम करता है:** पहला डाउनलोड प्रत्येक रिकॉर्ड के `sys_updated_on` को
  `_sync_meta.json` में दर्ज करता है। एक incremental run पर, हर source family
  `sys_updated_on >= <latest seen>` (server-side timestamps, कोई clock skew नहीं) query करता है, केवल उन रिकॉर्ड्स को फिर से-डाउनलोड करता है, और अपरिवर्तित लोकल फ़ाइलों को अछूता छोड़ देता है।
- **Deletions:** timestamp deltas डिलीट किए गए रिकॉर्ड्स को नहीं देख सकते। locally मौजूद लेकिन instance पर चले गए रिकॉर्ड्स को सूचीबद्ध करने के लिए `reconcile_deletions=True` जोड़ें — `deletion_candidates` के अंतर्गत warnings के रूप में रिपोर्ट किए गए, **कभी स्वचालित रूप से डिलीट नहीं किए गए**।
- **पहला run / कोई पूर्व डेटा नहीं:** स्वचालित रूप से एक full डाउनलोड पर वापस आ जाता है।
- पूरी तरह से sync में रहने के लिए समय-समय पर एक full (non-incremental) डाउनलोड चलाएँ।

### Download Safety & Completeness

डाउनलोड ऑफ़लाइन विश्लेषण के लिए सत्य का स्रोत है, इसलिए इसे deterministic होने के लिए और जब यह पूर्ण न हो तब कभी पूर्ण *दिखने* से बचने के लिए बनाया गया है:

- **Scope auto-resolution.** ऐप **namespace** (`x_company_app`), इसका **display name** ("My App"), या एक `sys_scope` sys_id पास करें — सभी canonical namespace में resolve हो जाते हैं, इसलिए लोकल फ़ोल्डर (`temp/<instance>/<namespace>/`) और हर query हर run में समान होती हैं। resolve किया गया मूल्य `scope_resolution` के रूप में echo किया जाता है।
- **कोई silent caps नहीं।** यदि कोई source family `max_records_per_type` से टकराती है, तो इसे ज़ोर से फ़्लैग किया जाता है: `source_types` में एक प्रति-family `capped: true`, `incomplete_types` में family, और एक top-level `complete: false`। एक truncated डाउनलोड कभी एक full के रूप में छद्मवेश नहीं रख सकता।
- **Cross-instance / stale गार्ड।** वापस push करना (`update_remote_from_local`) लोकल tree के दर्ज origin की connected instance के विरुद्ध जाँच करता है; एक resume re-download जो एक stale लोकल कॉपी रखता है, असली sync watermark को संरक्षित करता है और drift को छिपाने के बजाय warn करता है।
- **डाउनलोड समय पर Relationship metadata.** Widget→Angular-Provider edges (`_graph.json`) और widget→CSS/JS-dependency edges (`_dependency_graph.json`) को portal डाउनलोड के दौरान लाइव M2M तालिकाओं से कैप्चर किया जाता है — विश्लेषण code से अनुमान लगाने के बजाय असली graph पढ़ता है।
- **Transitive dependency depth.** Cross-scope deps डिफ़ॉल्ट रूप से `2` passes गहरे resolve होते हैं (conservative)। लंबी A→B→C→D chains का पीछा करने के लिए `SERVICENOW_DEP_MAX_DEPTH` (`1–6` तक clamped) के साथ बढ़ाएँ।
- **One-call graph build.** डाउनलोड के तुरंत बाद ऑफ़लाइन relationship ऑडिट चलाने के लिए `download_app_sources` को `build_graph=True` पास करें — कोई अतिरिक्त API लागत नहीं।
- **Create → local sync nudge.** जब आप instance पर एक widget/page बनाते हैं *और* उस scope के लिए एक लोकल tree मौजूद होता है, तो create प्रतिक्रिया नए रिकॉर्ड को local में खींचने के लिए सटीक `download_portal_sources(...)` कमांड के साथ एक `local_out_of_sync` संदेश जोड़ती है। यह कभी आपके लिए लोकल फ़ाइलें नहीं लिखता।

### क्या जनित होता है

| File | Purpose |
|------|---------|
| `_audit_report.html` | स्व-निहित dark-theme HTML रिपोर्ट — ब्राउज़र में खोलें |
| `_cross_references.json` | कौन किसे कॉल करता है — Script Include chains, GlideRecord table refs |
| `_graph.json` | लाइव M2M से आधिकारिक widget→Angular Provider edges (text-अनुमानित नहीं) |
| `_dependency_graph.json` | `m2m_sp_widget_dependency` से आधिकारिक widget→CSS/JS dependency edges |
| `_page_graph.json` | `sp_instance` से locally प्राप्त Page→widget placements (कोई API कॉल नहीं) |
| `_orphans.json` | Dead code उम्मीदवार — असंदर्भित SIs, अप्रयुक्त widgets |
| `_execution_order.json` | order संख्याओं के साथ प्रति-table BR/CS/ACL execution अनुक्रम |
| `_domain_knowledge.md` | स्वतः-जनित ऐप प्रोफ़ाइल — table maps, hub scripts, warnings |
| `_schema/*.json` | हर संदर्भित table के लिए field परिभाषाएँ |
| `_sync_meta.json` | incremental sync को शक्ति देने वाला प्रति-family `sys_updated_on` watermark |

### Individual Download Tools

एक full dump के लिए orchestrator का उपयोग करें, या एक targeted single-family refresh के लिए `download_server_sources` का:

| Tool | Sources |
|------|---------|
| `download_app_sources` | पूर्ण ऐप dump (सभी families + portal + schema + cross-scope deps) |
| `download_portal_sources` | Widgets, Angular Providers, linked Script Includes |
| `download_server_sources` (`families=`) | Targeted refresh — `script_includes`, `server_scripts` (BR/Client/Catalog Client), `ui` (Actions/Scripts/Pages/Macros), `api` (Scripted REST/Processors), `security` (ACLs, डिफ़ॉल्ट रूप से script-only), `admin` (Fix Scripts/Scheduled Jobs/Script Actions/Notifications/Transforms) |
| `download_table_schema` | sys_dictionary field परिभाषाएँ |

सभी डाउनलोड पूर्ण source को बिना किसी truncation के डिस्क पर लिखते हैं। LLM context में केवल एक सारांश लौटाया जाता है।

---

## Skills

टूल कच्ची API कॉल हैं। Skills वही हैं जो आपके LLM को वास्तव में उपयोगी बनाती हैं — सुरक्षा गेट, rollback, और context-aware sub-agent डेलिगेशन के साथ सत्यापित पाइपलाइनें। **MCP सर्वर + skills LLM-संचालित ServiceNow automation के लिए पूर्ण सेटअप है।**

आज 4 skills, हर release के साथ और आ रही हैं।

| | केवल Tools | Tools + Skills |
|---|---|---|
| Safety | LLM निर्णय करता है | गेट लागू (snapshot → preview → apply) |
| Tokens | context में Source dumps | sub-agent को delegate करें, केवल सारांश |
| Accuracy | LLM tool क्रम का अनुमान लगाता है | सत्यापित पाइपलाइन |
| Rollback | भूल सकता है | Snapshot अनिवार्य |

### Install Skills

```bash
# Claude Code
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude

# OpenAI Codex
uvx --from mfa-servicenow-mcp servicenow-mcp-skills codex

# OpenCode
uvx --from mfa-servicenow-mcp servicenow-mcp-skills opencode

# Antigravity
uvx --from mfa-servicenow-mcp servicenow-mcp-skills antigravity
```

installer इस repository की `skills/` डायरेक्टरी से 24 skill फ़ाइलें डाउनलोड करता है और उन्हें एक project-local LLM डायरेक्टरी में रखता है। कोई प्रमाणीकरण या कॉन्फ़िगरेशन आवश्यक नहीं।

| Client | Install Path | Auto-Discovery |
|--------|-------------|----------------|
| Claude Code | `.claude/commands/servicenow/` | `/servicenow` slash commands अगले स्टार्टअप पर दिखाई देते हैं |
| OpenAI Codex | `.codex/skills/servicenow/` | अगले agent session पर Skills load होती हैं |
| OpenCode | `.opencode/skills/servicenow/` | अगले session पर Skills load होती हैं |
| Antigravity | `.gemini/antigravity/skills/servicenow/` | अगले session पर Skills सक्रिय होती हैं |

**यह कैसे काम करता है:** प्रत्येक skill YAML frontmatter (metadata) और pipeline निर्देशों के साथ एक standalone Markdown फ़ाइल है। LLM क्लाइंट इन फ़ाइलों को install path से पढ़ता है और उन्हें callable commands या skill triggers के रूप में एक्सपोज़ करता है।

**Update:** वही install कमांड फिर से चलाएँ — यह सभी मौजूदा skill फ़ाइलों को बदल देता है (clean install, कोई merge नहीं)।

**केवल skills हटाएँ:** skill install डायरेक्टरी को मैन्युअल रूप से डिलीट करें (उदाहरण के लिए `rm -rf .claude/commands/servicenow/`)।

### Skill Categories

| Category | Skills | Purpose |
|----------|--------|---------|
| `analyze/` | 6 | Widget विश्लेषण, portal diagnosis, provider ऑडिट, dependency मैपिंग, ESC ऑडिट, **local source audit** |
| `fix/` | 3 | Widget patching (staged gates), debugging, code review |
| `manage/` | 8 | Page layout, script includes, source export, **app source download**, changeset workflow, local sync, workflow management, **skill management** |
| `deploy/` | 2 | Change request lifecycle, incident triage |
| `explore/` | 5 | Health check, schema discovery, route tracing, flow trigger tracing, ESC catalog flow |

### Skill Metadata

प्रत्येक skill में metadata शामिल है जो LLMs को execution optimize करने में मदद करता है:

```yaml
context_cost: low|medium|high    # → high = delegate to sub-agent
safety_level: none|confirm|staged # → staged = mandatory snapshot/preview/apply
delegatable: true|false           # → can run in sub-agent to save context
triggers: ["위젯 분석", "analyze widget"]  # → LLM trigger matching
```

पूर्ण skill संदर्भ के लिए, देखें [skills/SKILL.md](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/skills/SKILL.md)।

### MCP Resources (Built-in Skill Guides)

Skills को सर्वर से सीधे **MCP resources** के रूप में भी एक्सपोज़ किया जाता है — किसी client-side installation की आवश्यकता नहीं। कोई भी MCP-अनुपालक क्लाइंट उन्हें मांग पर खोज और पढ़ सकता है।

```
# List available skill guides
list_resources → skill://manage/local-sync, skill://manage/app-source-download, ...

# Read a specific guide
read_resource("skill://manage/local-sync") → full pipeline with safety gates
```

जिन टूल के पास एक मेल खाता skill guide होता है, वे अपने description में एक `→ skill://...` संकेत दिखाते हैं। guide सामग्री **pull-based** है — जब तक क्लाइंट वास्तव में नहीं पढ़ता तब तक शून्य token लागत।

| Feature | Client-side Skills | MCP Resources |
|---------|-------------------|---------------|
| Availability | install कमांड की आवश्यकता | Built-in, कोई भी क्लाइंट |
| Token cost | क्लाइंट द्वारा loaded | मांग पर pull (पढ़े जाने तक 0) |
| Discovery | Slash commands / triggers | `list_resources` |
| Best for | Power users, slash commands | सार्वभौमिक मार्गदर्शन |

## Docker

केवल API Key auth (MFA browser auth को GUI की आवश्यकता होती है, जो containers में उपलब्ध नहीं है)।

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

local build विकल्पों के लिए [Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md#docker-api-key-only) देखें।

## Developer Setup

यदि आप source को locally संशोधित करना चाहते हैं:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uvx --with playwright playwright install chromium
```

### Running Tests

```bash
uv run pytest
```

### Linting & Formatting

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

### Building

```bash
uv build
```

> Windows: देखें [Windows Installation Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)

---

## Documentation

- [LLM Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/llm-setup.md) — AI-निर्देशित one-line installation flow
- [Client Setup Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md) — Installer-first सेटअप के साथ-साथ fallback client configs
- [Tool Inventory](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_INVENTORY.md) — category और package के अनुसार पूर्ण tool सूची
- [Windows Installation Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)
- [Catalog Guide](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/catalog.md) — Service catalog CRUD और optimization
- [Change Management](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/change_management.md) — Change request lifecycle और approval
- [Workflow Management](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/workflow_management.md) — Workflow (wf_workflow engine) और Flow Designer टूल
- [Korean README](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md)

---

## Related Projects and Acknowledgements

- इस repository में पहले के internal / legacy ServiceNow MCP implementations से समेकित और refactored टूल शामिल हैं। वर्तमान surface bundled `manage_*` टूल के इर्द-गिर्द व्यवस्थित है (देखें [tool_utils.py](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/src/servicenow_mcp/utils/tool_utils.py))।
- यह परियोजना सुरक्षित, diff-first MCP सर्वर उपयोग के मामलों पर केंद्रित है: हर write confirm + write-guards (concurrent-edit, duplicate-create, publish, Flow Designer) के माध्यम से जाता है, और source edits को push किए जाने से पहले लाइव remote के विरुद्ध diff किया जाता है।

---

## License

Apache License 2.0
