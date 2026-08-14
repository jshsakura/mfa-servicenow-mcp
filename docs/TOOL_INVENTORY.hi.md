# ServiceNow MCP - टूल इन्वेंटरी

पंक्ति-दर-पंक्ति अनुवादित इन्वेंटरी बनाए रखने की लागत से बचने के लिए यह फ़ाइल वर्तमान सार्वजनिक टूल सतह का **सारांश** है। इसके आँकड़े `scripts/regenerate_doc_counts.py` स्वतः अपडेट करता है।

लाइव रजिस्ट्री में पंजीकृत टूल: **75**
`full` में पैकेज किए गए टूल की संख्या: **61**
पंजीकृत परंतु वर्तमान में अनपैकेज्ड टूल: **11**

- टूल-दर-टूल पूरी सूची: [अंग्रेज़ी TOOL_INVENTORY.md](./TOOL_INVENTORY.md)

`list_tool_packages` को `none` को छोड़कर हर सक्षम पैकेज में रनटाइम पर इंजेक्ट किया जाता है।
इसे नीचे प्रलेखित किया गया है, परंतु इस फ़ाइल में पैकेज गणनाएँ YAML-परिभाषित टूल सतह को दर्शाती हैं।

## पैकेज सारांश

| Package | Tools | Description |
|---------|------:|-------------|
| `none` | 0 | जानबूझकर टूल बंद करने के लिए अक्षम प्रोफ़ाइल। |
| `core` | 12 | त्वरित health/schema/table कार्य के लिए न्यूनतम read-only आवश्यक टूल। |
| `standard` | 31 | incidents, changes, portal, logs, और source analysis में डिफ़ॉल्ट read-only पैकेज। |
| `service_desk` | 33 | परिचालन समर्थन के लिए standard के साथ incident और change write workflows। |
| `portal_developer` | 50 | standard के साथ portal, changeset, script include, और local-sync delivery workflows। |
| `platform_developer` | 44 | standard के साथ workflow, Flow Designer, UI policy, incident/change, और script writes। |
| `full` | 61 | सबसे व्यापक पैकेज सतह: सभी manage_* workflows के साथ उन्नत संचालन। |

## रनटाइम-इंजेक्टेड सहायक (Helpers)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `list_tool_packages` | R | उपलब्ध tool packages और वर्तमान में सक्रिय पैकेज को सूचीबद्ध करता है। | `core`, `standard`, `service_desk`, `portal_developer`, `platform_developer`, `full` |
| `list_instances` | R | read-only data comparison mode के लिए कॉन्फ़िगर किए गए aliases को सूचीबद्ध करता है। | runtime comparison helper |
| `compare_instances` | R | कॉन्फ़िगर किए गए aliases में read-only record तुलना; यह write-routing तंत्र नहीं है। | runtime comparison helper |

## इस दस्तावेज़ की रखरखाव नीति

- **टूल-दर-टूल पूरी सूची अंग्रेज़ी `docs/TOOL_INVENTORY.md` में रखी जाती है** — वह लाइव
  रजिस्ट्री से जनरेट होती है, इसलिए कभी पुरानी नहीं पड़ती।
- यह फ़ाइल पैकेज चुनने और वर्तमान सतह देखने के लिए सारांश तक सीमित है। समानांतर में
  पंक्ति-दर-पंक्ति अनुवाद बनाए रखने से यह चार रिलीज़ पीछे रह गई थी (10 टूल गायब), इसलिए
  इसे उसी नीति पर लाया गया जो कोरियाई फ़ाइल ने पहले अपनाई।
- ऊपर के आँकड़े और पैकेज तालिका स्वतः पुनर्जनित होते हैं — इन्हें हाथ से न बदलें।
