# ServiceNow MCP चेंज मैनेजमेंट टूल्स

यह दस्तावेज़ ServiceNow MCP सर्वर में उपलब्ध चेंज मैनेजमेंट टूल्स के बारे में जानकारी प्रदान करता है।

## अवलोकन

चेंज मैनेजमेंट टूल्स Claude को ServiceNow की चेंज मैनेजमेंट कार्यक्षमता के साथ इंटरैक्ट करने की अनुमति देते हैं, जिससे उपयोगकर्ता प्राकृतिक भाषा वार्तालापों के माध्यम से चेंज रिक्वेस्ट बना सकते हैं, अपडेट कर सकते हैं और प्रबंधित कर सकते हैं।

## उपलब्ध टूल्स

ServiceNow MCP सर्वर निम्नलिखित चेंज मैनेजमेंट टूल्स प्रदान करता है:

### कोर चेंज रिक्वेस्ट प्रबंधन

1. **`manage_change`** - चेंज रिक्वेस्ट के लिए बंडल किया गया CRUD (table: `change_request`)
   - `action` (required): `create` / `update` / `add_task` में से एक
   - `action="create"` के लिए: `short_description`, `type` (`normal`/`standard`/`emergency`), साथ ही वैकल्पिक `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date`
   - `action="update"` के लिए: `change_id` के साथ कम से कम एक अपडेट करने योग्य फ़ील्ड (`short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes`); पूर्वावलोकन के लिए `dry_run=True` का समर्थन करता है
   - `action="add_task"` के लिए: `change_id`, `task_short_description`, साथ ही वैकल्पिक `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date`

2. **`sn_query`** (`table=change_request` के साथ) - मनमाने फ़िल्टर के साथ चेंज रिक्वेस्ट सूचीबद्ध करें
   - चेंज रिक्वेस्ट सूचीबद्ध करने के लिए जेनेरिक टेबल-क्वेरी प्रिमिटिव का उपयोग करें। `sn_query` पैरामीटर के लिए [टूल इन्वेंट्री](TOOL_INVENTORY.md) देखें।

3. **`manage_change(action="get")`** - किसी विशिष्ट चेंज रिक्वेस्ट के बारे में विस्तृत जानकारी प्राप्त करें
   - पैरामीटर:
     - `change_id` (required): चेंज रिक्वेस्ट ID या sys_id

### चेंज अप्रूवल वर्कफ़्लो

1. **submit_change_for_approval** - किसी चेंज रिक्वेस्ट को अप्रूवल के लिए सबमिट करें
   - पैरामीटर:
     - `change_id` (required): चेंज रिक्वेस्ट ID या sys_id
     - `approval_comments`: अप्रूवल रिक्वेस्ट के लिए टिप्पणियाँ

2. **approve_change** - किसी चेंज रिक्वेस्ट को अप्रूव करें
   - पैरामीटर:
     - `change_id` (required): चेंज रिक्वेस्ट ID या sys_id
     - `approver_id`: अप्रूवर की ID
     - `approval_comments`: अप्रूवल के लिए टिप्पणियाँ

3. **reject_change** - किसी चेंज रिक्वेस्ट को अस्वीकार करें
   - पैरामीटर:
     - `change_id` (required): चेंज रिक्वेस्ट ID या sys_id
     - `approver_id`: अप्रूवर की ID
     - `rejection_reason` (required): अस्वीकृति का कारण

## Claude के साथ उदाहरण उपयोग

एक बार ServiceNow MCP सर्वर Claude Desktop के साथ कॉन्फ़िगर हो जाने पर, आप Claude से इस प्रकार की क्रियाएँ करने के लिए कह सकते हैं:

### चेंज रिक्वेस्ट बनाना और प्रबंधित करना

- "सर्वर मेंटेनेंस के लिए एक चेंज रिक्वेस्ट बनाएं ताकि कल रात सिक्योरिटी पैच लागू किए जा सकें"
- "अगले मंगलवार सुबह 2 बजे से 4 बजे तक के लिए एक डेटाबेस अपग्रेड शेड्यूल करें"
- "हमारे वेब एप्लिकेशन में क्रिटिकल सिक्योरिटी कमजोरी को ठीक करने के लिए एक एमरजेंसी चेंज बनाएं"

### कार्य और कार्यान्वयन विवरण जोड़ना

- "सर्वर मेंटेनेंस चेंज में प्री-इम्प्लीमेंटेशन जाँच के लिए एक कार्य जोड़ें"
- "डेटाबेस अपग्रेड शुरू करने से पहले सिस्टम बैकअप सत्यापित करने के लिए एक कार्य जोड़ें"
- "नेटवर्क चेंज की कार्यान्वयन योजना को अपडेट करें ताकि उसमें रोलबैक प्रक्रियाएँ शामिल की जा सकें"

### अप्रूवल वर्कफ़्लो

- "सर्वर मेंटेनेंस चेंज को अप्रूवल के लिए सबमिट करें"
- "मुझे मेरे अप्रूवल की प्रतीक्षा कर रहे सभी चेंज दिखाएं"
- "डेटाबेस अपग्रेड चेंज को इस टिप्पणी के साथ अप्रूव करें: कार्यान्वयन योजना पूरी तरह से ठोस लगती है"
- "अपर्याप्त परीक्षण के कारण नेटवर्क चेंज को अस्वीकार करें"

### चेंज जानकारी क्वेरी करना

- "मुझे इस सप्ताह के लिए शेड्यूल किए गए सभी एमरजेंसी चेंज दिखाएं"
- "डेटाबेस अपग्रेड चेंज की स्थिति क्या है?"
- "Network टीम को असाइन किए गए सभी चेंज सूचीबद्ध करें"
- "मुझे चेंज CHG0010001 का विवरण दिखाएं"

## उदाहरण कोड

यहाँ एक उदाहरण है कि चेंज मैनेजमेंट टूल्स का प्रोग्रामेटिक रूप से उपयोग कैसे करें:

```python
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.utils.config import ServerConfig

# Create server configuration
server_config = ServerConfig(
    instance_url="https://your-instance.service-now.com",
)

# Create authentication manager
auth_manager = AuthManager(
    auth_type="basic",
    username="your-username",
    password="your-password",
    instance_url="https://your-instance.service-now.com",
)

# Create a change request via the bundled manage_change tool
params = ManageChangeParams(
    action="create",
    short_description="Server maintenance - Apply security patches",
    description="Apply the latest security patches to the application servers.",
    type="normal",
    risk="moderate",
    impact="medium",
    category="Hardware",
    start_date="2023-12-15 01:00:00",
    end_date="2023-12-15 03:00:00",
)

result = manage_change(server_config, auth_manager, params)
print(result)
```

ऊपर दिया गया नमूना प्रोग्रामेटिक रिक्वेस्ट का स्वरूप और चेंज मैनेजमेंट को अपने स्वयं के ऑटोमेशन में एकीकृत करने के लिए आवश्यक प्रमुख इम्पोर्ट्स दिखाता है।

## Claude Desktop के साथ एकीकरण

Claude Desktop में चेंज मैनेजमेंट टूल्स के साथ ServiceNow MCP सर्वर को कॉन्फ़िगर करने के लिए:

1. `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) पर Claude Desktop कॉन्फ़िगरेशन फ़ाइल या अपने OS के लिए उपयुक्त पथ संपादित करें:

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/Users/yourusername/dev/servicenow-mcp/.venv/bin/python",
      "args": [
        "-m",
        "servicenow_mcp.cli"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "SERVICENOW_AUTH_TYPE": "basic"
      }
    }
  }
}
```

2. परिवर्तनों को लागू करने के लिए Claude Desktop को पुनः आरंभ करें

## अनुकूलन

चेंज मैनेजमेंट टूल्स को आपके संगठन के विशिष्ट ServiceNow कॉन्फ़िगरेशन से मेल खाने के लिए अनुकूलित किया जा सकता है:

- State मानों को आपके ServiceNow इंस्टेंस कॉन्फ़िगरेशन के आधार पर समायोजित करने की आवश्यकता हो सकती है
- यदि आवश्यक हो तो पैरामीटर मॉडल में अतिरिक्त फ़ील्ड जोड़े जा सकते हैं
- अप्रूवल वर्कफ़्लो को आपके संगठन की अप्रूवल प्रक्रिया से मेल खाने के लिए संशोधित करने की आवश्यकता हो सकती है

टूल्स को अनुकूलित करने के लिए, `src/servicenow_mcp/tools` डायरेक्टरी में `change_tools.py` फ़ाइल को संशोधित करें।
