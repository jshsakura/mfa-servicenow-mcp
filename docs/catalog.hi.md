# ServiceNow सर्विस कैटलॉग एकीकरण

यह दस्तावेज़ ServiceNow MCP सर्वर में ServiceNow सर्विस कैटलॉग एकीकरण के बारे में जानकारी प्रदान करता है।

## अवलोकन

ServiceNow सर्विस कैटलॉग एकीकरण आपको निम्नलिखित की अनुमति देता है:

- सर्विस कैटलॉग श्रेणियों को सूचीबद्ध करना
- सर्विस कैटलॉग आइटम को सूचीबद्ध करना
- विशिष्ट कैटलॉग आइटम के बारे में विस्तृत जानकारी प्राप्त करना, उनके वेरिएबल सहित
- श्रेणी या खोज क्वेरी के आधार पर कैटलॉग आइटम को फ़िल्टर करना

## टूल

ServiceNow सर्विस कैटलॉग के साथ इंटरैक्ट करने के लिए निम्नलिखित टूल उपलब्ध हैं:

### `manage_catalog(action="list_categories")`

उपलब्ध सर्विस कैटलॉग श्रेणियों को सूचीबद्ध करता है।

**पैरामीटर:**
- `limit` (int, default: 10): लौटाई जाने वाली श्रेणियों की अधिकतम संख्या
- `offset` (int, default: 0): पेजिनेशन के लिए ऑफ़सेट
- `query` (string, optional): श्रेणियों के लिए खोज क्वेरी
- `active` (boolean, default: true): क्या केवल सक्रिय श्रेणियाँ ही लौटानी हैं

**उदाहरण:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogCategoriesParams, list_catalog_categories

params = ListCatalogCategoriesParams(
    limit=5,
    query="hardware"
)
result = list_catalog_categories(config, auth_manager, params)
```

### `manage_catalog(action="list_items")`

उपलब्ध सर्विस कैटलॉग आइटम को सूचीबद्ध करता है।

**पैरामीटर:**
- `limit` (int, default: 10): लौटाए जाने वाले आइटम की अधिकतम संख्या
- `offset` (int, default: 0): पेजिनेशन के लिए ऑफ़सेट
- `category` (string, optional): श्रेणी के आधार पर फ़िल्टर करें
- `query` (string, optional): आइटम के लिए खोज क्वेरी
- `active` (boolean, default: true): क्या केवल सक्रिय आइटम ही लौटाने हैं

**उदाहरण:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogItemsParams, list_catalog_items

params = ListCatalogItemsParams(
    limit=5,
    category="hardware",
    query="laptop"
)
result = list_catalog_items(config, auth_manager, params)
```

### `manage_catalog(action="get_item")`

किसी विशिष्ट कैटलॉग आइटम के बारे में विस्तृत जानकारी प्राप्त करता है।

**पैरामीटर:**
- `item_id` (string, required): कैटलॉग आइटम ID या sys_id

**उदाहरण:**
```python
from servicenow_mcp.tools.catalog_tools import GetCatalogItemParams, get_catalog_item

params = GetCatalogItemParams(
    item_id="item123"
)
result = get_catalog_item(config, auth_manager, params)
```

## संसाधन

ServiceNow सर्विस कैटलॉग तक पहुँचने के लिए निम्नलिखित संसाधन उपलब्ध हैं:

### `catalog://items`

सर्विस कैटलॉग आइटम को सूचीबद्ध करता है।

**उदाहरण:**
```
catalog://items
```

### `catalog://categories`

सर्विस कैटलॉग श्रेणियों को सूचीबद्ध करता है।

**उदाहरण:**
```
catalog://categories
```

### `catalog://{item_id}`

ID के आधार पर एक विशिष्ट कैटलॉग आइटम प्राप्त करता है।

**उदाहरण:**
```
catalog://item123
```

## Claude Desktop के साथ एकीकरण

Claude Desktop के साथ ServiceNow सर्विस कैटलॉग का उपयोग करने के लिए:

1. Claude Desktop में ServiceNow MCP सर्वर को कॉन्फ़िगर करें
2. Claude से सर्विस कैटलॉग के बारे में प्रश्न पूछें

**उदाहरण प्रॉम्प्ट:**
- "क्या आप ServiceNow में उपलब्ध सर्विस कैटलॉग श्रेणियों को सूचीबद्ध कर सकते हैं?"
- "क्या आप मुझे ServiceNow सर्विस कैटलॉग में उपलब्ध आइटम दिखा सकते हैं?"
- "क्या आप Hardware श्रेणी में कैटलॉग आइटम को सूचीबद्ध कर सकते हैं?"
- "क्या आप मुझे 'New Laptop' कैटलॉग आइटम का विवरण दिखा सकते हैं?"
- "क्या आप ServiceNow में 'software' से संबंधित कैटलॉग आइटम खोज सकते हैं?"
- "क्या आप सर्विस कैटलॉग में 'Cloud Services' नामक एक नई श्रेणी बना सकते हैं?"
- "क्या आप 'Hardware' श्रेणी का नाम बदलकर 'IT Equipment' कर सकते हैं?"
- "क्या आप 'Virtual Machine' कैटलॉग आइटम को 'Cloud Services' श्रेणी में स्थानांतरित कर सकते हैं?"
- "क्या आप 'IT Equipment' श्रेणी के अंतर्गत 'Monitors' नामक एक उपश्रेणी बना सकते हैं?"
- "क्या आप सभी software आइटम को 'Software' श्रेणी में स्थानांतरित करके हमारे कैटलॉग को पुनर्व्यवस्थित कर सकते हैं?"

## उदाहरण स्क्रिप्ट

### एकीकरण परीक्षण

`examples/catalog_integration_test.py` स्क्रिप्ट यह प्रदर्शित करती है कि कैटलॉग टूल का सीधे उपयोग कैसे करें:

```bash
python examples/catalog_integration_test.py
```

### Claude Desktop डेमो

`examples/claude_catalog_demo.py` स्क्रिप्ट यह प्रदर्शित करती है कि Claude Desktop के साथ कैटलॉग कार्यक्षमता का उपयोग कैसे करें:

```bash
python examples/claude_catalog_demo.py
```

## डेटा मॉडल

### CatalogItemModel

एक ServiceNow कैटलॉग आइटम का प्रतिनिधित्व करता है।

**फ़ील्ड:**
- `sys_id` (string): कैटलॉग आइटम के लिए विशिष्ट पहचानकर्ता
- `name` (string): कैटलॉग आइटम का नाम
- `short_description` (string, optional): कैटलॉग आइटम का संक्षिप्त विवरण
- `description` (string, optional): कैटलॉग आइटम का विस्तृत विवरण
- `category` (string, optional): कैटलॉग आइटम की श्रेणी
- `price` (string, optional): कैटलॉग आइटम की कीमत
- `picture` (string, optional): कैटलॉग आइटम का चित्र URL
- `active` (boolean, optional): क्या कैटलॉग आइटम सक्रिय है
- `order` (integer, optional): अपनी श्रेणी में कैटलॉग आइटम का क्रम

### CatalogCategoryModel

एक ServiceNow कैटलॉग श्रेणी का प्रतिनिधित्व करता है।

**फ़ील्ड:**
- `sys_id` (string): श्रेणी के लिए विशिष्ट पहचानकर्ता
- `title` (string): श्रेणी का शीर्षक
- `description` (string, optional): श्रेणी का विवरण
- `parent` (string, optional): मूल श्रेणी ID
- `icon` (string, optional): श्रेणी का आइकन
- `active` (boolean, optional): क्या श्रेणी सक्रिय है
- `order` (integer, optional): श्रेणी का क्रम

### CatalogItemVariableModel

एक ServiceNow कैटलॉग आइटम वेरिएबल का प्रतिनिधित्व करता है।

**फ़ील्ड:**
- `sys_id` (string): वेरिएबल के लिए विशिष्ट पहचानकर्ता
- `name` (string): वेरिएबल का नाम
- `label` (string): वेरिएबल का लेबल
- `type` (string): वेरिएबल का प्रकार
- `mandatory` (boolean, optional): क्या वेरिएबल अनिवार्य है
- `default_value` (string, optional): वेरिएबल का डिफ़ॉल्ट मान
- `help_text` (string, optional): वेरिएबल के लिए सहायता पाठ
- `order` (integer, optional): वेरिएबल का क्रम
