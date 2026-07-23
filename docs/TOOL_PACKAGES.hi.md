# Tool Packages — उन्नत संदर्भ

> **अधिकांश उपयोगकर्ताओं को इस पृष्ठ की आवश्यकता नहीं है।** डिफ़ॉल्ट पैकेज `standard` है — केवल-पठन (read-only), किसी भी वातावरण के लिए सुरक्षित।
> केवल तभी आगे पढ़ें जब आपको `standard` द्वारा प्रदान किए गए से अधिक लेखन (write) टूल्स की आवश्यकता हो।

---

## पैकेज चुनना

सबसे संकीर्ण पैकेज से शुरू करें जो आपके कार्य को कवर करता हो। प्रत्येक अगला स्तर अधिक डोमेन में लेखन पहुँच जोड़ता है:

केवल-पठन — किसी भी वातावरण के लिए सुरक्षित, कोई लेखन टूल नहीं:

| Package | Tools | ~टोकन | कब उपयोग करें |
| :--- | :---: | :---: | :--- |
| `core` | 12 | ~3.0K | न्यूनतम केवल-पठन: केवल health, schema, discovery, और मुख्य artifact लुकअप |
| `standard` | 29 | ~7.3K | **(डिफ़ॉल्ट)** incidents, changes, portal, logs, और source विश्लेषण में केवल-पठन |
| `none` | 0 | 0 | जानबूझकर सभी टूल्स अक्षम करें (परीक्षण, प्रतिबंधित वातावरण) |

⚠️ लेखन-सक्षम — **उन्नत विकल्प** जो create/update/delete की अनुमति देते हैं:

| Package | Tools | ~टोकन | कब उपयोग करें |
| :--- | :---: | :---: | :--- |
| `service_desk` | 31 | ~8.2K | ⚠️ सर्विस डेस्क एजेंट जिन्हें incidents और changes को अपडेट/बंद करने की आवश्यकता हो |
| `portal_developer` | 41 | ~10.6K | ⚠️ पोर्टल डेवलपर जो widgets, changesets, और script includes परिनियोजित करते हैं |
| `platform_developer` | 41 | ~10.8K | ⚠️ प्लेटफ़ॉर्म इंजीनियर जो workflows, Flow Designer, और scripts प्रबंधित करते हैं |
| `full` | 55 | ~13.8K | ⚠️ सबसे उन्नत — सभी डोमेन में सभी लेखन टूल्स एक साथ (नीचे चेतावनी देखें) |

> **~टोकन** = हर request पर उस package की tool schemas model के context में जोड़ने वाले अनुमानित tokens (tiktoken cl100k_base आधार; वास्तविक Claude token संख्या थोड़ी भिन्न)। संकरे package से context और लागत बचती है।

`core` और `none` को छोड़कर सभी पैकेज `_extends` के माध्यम से `standard` केवल-पठन टूल्स को इनहेरिट करते हैं। पूर्ण इनहेरिटेंस ट्री के लिए `config/tool_packages.yaml` देखें।

---

!!! danger "⚠️  `standard` से ऊपर का कोई भी पैकेज एक उन्नत, लेखन-सक्षम विकल्प है"
    `service_desk`, `portal_developer`, `platform_developer`, और `full` सभी लेखन टूल्स सक्रिय करते हैं — इनके अंतर्गत
    चलने वाला कोई AI एजेंट ServiceNow रिकॉर्ड्स को create, update, और delete कर सकता है। `full` ऐसा **हर
    डोमेन में एक साथ** करता है (incidents, changes, portal, Flow Designer, workflows, scripts, और अधिक), इसलिए एक
    गलत-समझा गया प्रॉम्प्ट या hallucination एक साथ कई क्षेत्रों में विनाशकारी परिवर्तन ट्रिगर कर सकता है।

    **`standard` से ऊपर तब तक न जाएँ जब तक:**
    - आप पैकेज द्वारा सक्रिय किए जाने वाले हर लेखन टूल को समझते न हों ([Tool Inventory](TOOL_INVENTORY.md) देखें)
    - आप किसी **गैर-उत्पादन (non-production)** या **sandboxed** इंस्टेंस में काम कर रहे हों, या आपके पास `allow_writes` गेटिंग मौजूद हो
    - आप एक अनुभवी ServiceNow डेवलपर हों जो अनपेक्षित परिवर्तनों से पुनर्प्राप्त करना जानते हों

    यदि आप अनिश्चित हैं, तो केवल-पठन डिफ़ॉल्ट `standard` पर बने रहें और सबसे संकीर्ण लेखन पैकेज केवल तभी चुनें जब किसी कार्य को वास्तव में इसकी आवश्यकता हो।

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

सभी 73 टूल्स की श्रेणी और पैकेज सदस्यता के अनुसार पूर्ण सूची के लिए, [Tool Inventory](TOOL_INVENTORY.md) देखें।
