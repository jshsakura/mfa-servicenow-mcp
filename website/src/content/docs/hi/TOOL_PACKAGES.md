---
title: "Tool Packages — उन्नत संदर्भ"
description: "Advanced reference for the read/write tool package system."
slug: hi/TOOL_PACKAGES
---

> **अधिकांश उपयोगकर्ताओं को इस पृष्ठ की आवश्यकता नहीं है।** डिफ़ॉल्ट पैकेज `standard` है — केवल-पठन (read-only), किसी भी वातावरण के लिए सुरक्षित।
> केवल तभी आगे पढ़ें जब आपको `standard` द्वारा प्रदान किए गए से अधिक लेखन (write) टूल्स की आवश्यकता हो।

---

## पैकेज चुनना

सबसे संकीर्ण पैकेज से शुरू करें जो आपके कार्य को कवर करता हो। प्रत्येक अगला स्तर अधिक डोमेन में लेखन पहुँच जोड़ता है:

केवल-पठन — किसी भी वातावरण के लिए सुरक्षित, कोई लेखन टूल नहीं:

| Package | Tools | अधिकतम टोकन | अधिकतम (3 instances) | कब उपयोग करें |
| :--- | :---: | :---: | :---: | :--- |
| `core` | 12 | ~2.2K | ~2.7K | न्यूनतम केवल-पठन: केवल health, schema, discovery, और मुख्य artifact लुकअप |
| `standard` | 31 | ~7.4K | ~8.3K | **(डिफ़ॉल्ट)** incidents, changes, portal, logs, और source विश्लेषण में केवल-पठन |
| `none` | 0 | 0 | 0 | जानबूझकर सभी टूल्स अक्षम करें (परीक्षण, प्रतिबंधित वातावरण) |

Add-on — सामान्य-उद्देश्य, अपने आप में पैकेज नहीं। किसी भी पैकेज के साथ comma से जोड़ें (`MCP_TOOL_PACKAGE=asset_manager,scripting`); ⚠️ लेखन-सक्षम दर्शाता है:

| Add-on | टूल | अतिरिक्त | उपयोग |
| :--- | :---: | :---: | :--- |
| `scripting` | 13 | +~4.6K | ⚠️ server-side तर्क (script includes, business rules, scheduled jobs, REST messages, flow पठन), update sets, XML deployment |
| `office_files` | 2 | +~0.7K | Excel workbooks (पढ़ना, लिखना, फ़ॉर्म भरना) और record attachments |
| `debug_window` | 3 | +~1.2K | ⚠️ साझा browser; `act_in_debug_window` Save दबा सकता है |
| `source_sync` | 3 | +~0.9K | ⚠️ server-side sources डाउनलोड, diff, और वापस push |
| `portal_design` | 10 | +~2.8K | ⚠️ theme से आगे portal design: page layout और instance CSS/options, widget और header/footer की copy, Workspace list — `itsm_developer,portal_design` के लिए |

⚠️ लेखन-सक्षम — **उन्नत विकल्प** जो create/update/delete की अनुमति देते हैं:

| Package | Tools | अधिकतम टोकन | अधिकतम (3 instances) | कब उपयोग करें |
| :--- | :---: | :---: | :---: | :--- |
| `service_desk` | 34 | ~8.3K | ~9.3K | ⚠️ सर्विस डेस्क एजेंट जिन्हें incidents और changes को अपडेट/बंद करने की आवश्यकता हो |
| `portal_developer` | 53 | ~16.8K | ~18.6K | ⚠️ पोर्टल डेवलपर जो widgets, changesets, और script includes परिनियोजित करते हैं |
| `platform_developer` | 48 | ~13.7K | ~15.3K | ⚠️ प्लेटफ़ॉर्म इंजीनियर जो workflows, Flow Designer, और scripts प्रबंधित करते हैं |
| `full` | 71 | ~21.8K | ~24.2K | ⚠️ सबसे उन्नत — सभी डोमेन में सभी लेखन टूल्स एक साथ (नीचे चेतावनी देखें) |
| `itsm_developer` | 37 | ~11.3K | ~12.7K | ⚠️ स्वतंत्र ITSM: record का निदान, table automation का नक्शा, catalog/policy/notification config, approval और test order, assignment/approval rule और choice list, portal theme, update set या XML से ship. |
| `asset_manager` | 7 | ~1.2K | ~1.6K | ⚠️ सामग्री, asset और ITOM कार्य के लिए न्यूनतम सतह: query, और इंस्टेंस पर पहले जाँचे गए asset write (`manage_asset`)। Add-on comma से जोड़ें: `scripting`, `office_files`, `debug_window`, `source_sync` (`MCP_TOOL_PACKAGE=asset_manager,office_files`) |

> **अधिकतम टोकन** = हर request पर उस package की tool schemas model के context में जोड़ने वाले अनुमानित tokens (tiktoken cl100k_base आधार; वास्तविक Claude token संख्या थोड़ी भिन्न)। संकरे package से context और लागत बचती है। **यह अधिकतम है**, सामान्य लागत नहीं: पूरा खर्च केवल वे clients उठाते हैं जो सारी tool schemas शुरुआत में load करते हैं। Deferred tool loading वाले clients (जैसे Claude Code का tool search) किसी tool का schema तभी load करते हैं जब वह उपयोग हो, इसलिए उनकी वास्तविक per-request लागत काफी कम होती है। Tools की संख्या package के सदस्य गिनती है; हर package में `list_tool_packages` भी होता है, और multi-instance setup में `list_instances`, `compare_instances` और हर tool पर एक `instance` parameter जुड़ता है — दूसरा token column इसे तीन instances के साथ मापता है। आंकड़े tiktoken से मापे गए हैं, अनुमानित नहीं (`uv run --no-sync --with tiktoken python scripts/measure_tool_tokens.py <package>` हर tool का हिस्सा दिखाता है)।

`core` और `none` को छोड़कर सभी पैकेज `_extends` के माध्यम से `standard` केवल-पठन टूल्स को इनहेरिट करते हैं। पूर्ण इनहेरिटेंस ट्री के लिए `config/tool_packages.yaml` देखें। `asset_manager`, `itsm_developer` और add-on कुछ भी extend नहीं करते: session केवल माँगे गए टूल का भुगतान करता है।

---

:::danger[⚠️  `standard` से ऊपर का कोई भी पैकेज एक उन्नत, लेखन-सक्षम विकल्प है]
`service_desk`, `portal_developer`, `platform_developer`, और `full` सभी लेखन टूल्स सक्रिय करते हैं — इनके अंतर्गत
चलने वाला कोई AI एजेंट ServiceNow रिकॉर्ड्स को create, update, और delete कर सकता है। `full` ऐसा **हर
डोमेन में एक साथ** करता है (incidents, changes, portal, Flow Designer, workflows, scripts, और अधिक), इसलिए एक
गलत-समझा गया प्रॉम्प्ट या hallucination एक साथ कई क्षेत्रों में विनाशकारी परिवर्तन ट्रिगर कर सकता है।

**`standard` से ऊपर तब तक न जाएँ जब तक:**
- आप पैकेज द्वारा सक्रिय किए जाने वाले हर लेखन टूल को समझते न हों ([Tool Inventory](../TOOL_INVENTORY/) देखें)
- आप किसी **गैर-उत्पादन (non-production)** या **sandboxed** इंस्टेंस में काम कर रहे हों, या आपके पास `allow_writes` गेटिंग मौजूद हो
- आप एक अनुभवी ServiceNow डेवलपर हों जो अनपेक्षित परिवर्तनों से पुनर्प्राप्त करना जानते हों

यदि आप अनिश्चित हैं, तो केवल-पठन डिफ़ॉल्ट `standard` पर बने रहें और सबसे संकीर्ण लेखन पैकेज केवल तभी चुनें जब किसी कार्य को वास्तव में इसकी आवश्यकता हो।
:::
---

## पैकेज सेट करना

पर्यावरण चर (environment variable) के माध्यम से (अनुशंसित):

```bash
MCP_TOOL_PACKAGE=standard
```

CLI फ़्लैग के माध्यम से:

```bash
servicenow-mcp --tool-package standard --instance-url ...
```

आपके MCP क्लाइंट कॉन्फ़िग में:

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "standard"
  }
}
```

---

## जब कोई टूल आपके पैकेज में नहीं होता तो क्या होता है

यदि आप कोई ऐसा टूल कॉल करते हैं जो आपके वर्तमान पैकेज में सक्रिय नहीं है, तो सर्वर एक स्पष्ट त्रुटि लौटाता है:

```
Tool 'manage_widget' is not available in package 'standard'.
Enable package 'portal_developer' or higher to use this tool.
```

कोई मौन विफलता (silent failure) नहीं — LLM को ठीक-ठीक पता होता है कि कौन सा पैकेज अनुरोध करना है।

---

## पूर्ण टूल सूची

सभी 73 टूल्स की श्रेणी और पैकेज सदस्यता के अनुसार पूर्ण सूची के लिए, [Tool Inventory](../TOOL_INVENTORY/) देखें।
