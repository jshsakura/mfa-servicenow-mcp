# ServiceNow MCP में Workflow प्रबंधन

यह दस्तावेज़ MCP सर्वर द्वारा उजागर किए गए दो workflow इंजनों को कवर करता है:

1. **Legacy Workflow** (`wf_workflow`) — नीचे दिए गए `manage_workflow` action राउटर द्वारा संचालित।
2. **Flow Designer** (`sys_hub_flow`) — action डिस्पैच के साथ एकीकृत `manage_flow_designer` टूल। Standard पैकेज read actions (`list` / `get_detail` / `get_executions` / `compare`) उजागर करता है; उच्चतर पैकेज writes (`update` / `checkout` / `set_*` / `save` / `discard`) अनलॉक करते हैं। Action/SubFlow/Playbook तालिकाएँ [Flow Designer table map](#flow-designer-table-map) में प्रलेखित हैं।

यदि आप निश्चित नहीं हैं कि कोई प्रक्रिया किस इंजन का उपयोग करती है, तो `manage_flow_designer(action="list")` (आधुनिक इंस्टेंस) से शुरू करें और legacy `wf_workflow` रिकॉर्ड के लिए `manage_workflow(action="list")` पर वापस जाएँ।

## अवलोकन

ServiceNow workflows एक शक्तिशाली स्वचालन सुविधा है जो आपको व्यावसायिक प्रक्रियाओं को परिभाषित और स्वचालित करने की अनुमति देती है। ServiceNow MCP सर्वर में workflow प्रबंधन टूल आपको अपने ServiceNow इंस्टेंस में workflows देखने, बनाने और संशोधित करने में सक्षम बनाते हैं।

## उपलब्ध टूल

### Workflows देखना

1. **manage_workflow(action="list")** - ServiceNow से workflows सूचीबद्ध करें
   - पैरामीटर:
     - `limit` (optional): वापस करने के लिए रिकॉर्ड की अधिकतम संख्या (default: 10)
     - `offset` (optional): किस स्थान से शुरू करना है उसका Offset (default: 0)
     - `active` (optional): सक्रिय स्थिति के अनुसार फ़िल्टर करें (true/false)
     - `name` (optional): नाम के अनुसार फ़िल्टर करें (contains)
     - `query` (optional): अतिरिक्त query स्ट्रिंग

2. **manage_workflow(action="get")** - किसी विशिष्ट workflow के बारे में विस्तृत जानकारी प्राप्त करें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id

3. **manage_workflow(action="list_versions")** - किसी विशिष्ट workflow के सभी संस्करण सूचीबद्ध करें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id
     - `limit` (optional): वापस करने के लिए रिकॉर्ड की अधिकतम संख्या (default: 10)
     - `offset` (optional): किस स्थान से शुरू करना है उसका Offset (default: 0)

4. **manage_workflow(action="get_activities")** - किसी workflow में सभी activities प्राप्त करें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id
     - `version` (optional): activities प्राप्त करने के लिए विशिष्ट संस्करण (यदि प्रदान नहीं किया गया, तो नवीनतम प्रकाशित संस्करण का उपयोग किया जाएगा)

### Workflows संशोधित करना

5. **manage_workflow** (action="create") - ServiceNow में एक नया workflow बनाएँ
   - पैरामीटर:
     - `name` (required): workflow का नाम
     - `description` (optional): workflow का विवरण
     - `table` (optional): वह तालिका जिस पर workflow लागू होता है
     - `active` (optional): workflow सक्रिय है या नहीं (default: true)
     - `attributes` (optional): workflow के लिए अतिरिक्त विशेषताएँ

6. **manage_workflow** (action="update") - किसी मौजूदा workflow को अपडेट करें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id
     - `name` (optional): workflow का नाम
     - `description` (optional): workflow का विवरण
     - `table` (optional): वह तालिका जिस पर workflow लागू होता है
     - `active` (optional): workflow सक्रिय है या नहीं
     - `attributes` (optional): workflow के लिए अतिरिक्त विशेषताएँ

7. **manage_workflow** (action="activate") - किसी workflow को सक्रिय करें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id

8. **manage_workflow** (action="deactivate") - किसी workflow को निष्क्रिय करें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id

### Workflow Activities का प्रबंधन

9. **manage_workflow** (action="add_activity") - किसी workflow में एक नई activity जोड़ें
   - पैरामीटर:
     - `workflow_id` (required): Workflow ID या sys_id
     - `name` (required): activity का नाम
     - `description` (optional): activity का विवरण
     - `activity_type` (required): activity का प्रकार (उदा., 'approval', 'task', 'notification')
     - `attributes` (optional): activity के लिए अतिरिक्त विशेषताएँ
     - `position` (optional): workflow में स्थिति (यदि प्रदान नहीं किया गया, तो activity अंत में जोड़ी जाएगी)

10. **manage_workflow** (action="update_activity") - किसी workflow में मौजूदा activity को अपडेट करें
    - पैरामीटर:
      - `activity_id` (required): Activity ID या sys_id
      - `name` (optional): activity का नाम
      - `description` (optional): activity का विवरण
      - `attributes` (optional): activity के लिए अतिरिक्त विशेषताएँ

11. **manage_workflow** (action="delete_activity") - किसी workflow से एक activity हटाएँ
    - पैरामीटर:
      - `activity_id` (required): Activity ID या sys_id

12. **manage_workflow** (action="reorder_activities") - किसी workflow में activities का क्रम बदलें
    - पैरामीटर:
      - `workflow_id` (required): Workflow ID या sys_id
      - `activity_ids` (required): वांछित क्रम में activity ID की सूची

## उपयोग के उदाहरण

### Workflows देखना

#### सभी सक्रिय workflows सूचीबद्ध करें

```python
result = list_workflows({
    "active": True,
    "limit": 20
})
```

#### किसी विशिष्ट workflow के बारे में विवरण प्राप्त करें

```python
result = get_workflow_details({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### किसी workflow के सभी संस्करण सूचीबद्ध करें

```python
result = list_workflow_versions({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### किसी workflow में सभी activities प्राप्त करें

```python
result = get_workflow_activities({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### Workflows संशोधित करना

#### एक नया workflow बनाएँ

```python
result = manage_workflow({"action": "create",
    "name": "Software License Request",
    "description": "Workflow for handling software license requests",
    "table": "sc_request"
})
```

#### किसी मौजूदा workflow को अपडेट करें

```python
result = manage_workflow({"action": "update",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "description": "Updated workflow description",
    "active": True
})
```

#### किसी workflow को सक्रिय करें

```python
result = manage_workflow({"action": "activate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### किसी workflow को निष्क्रिय करें

```python
result = manage_workflow({"action": "deactivate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### Workflow Activities का प्रबंधन

#### किसी workflow में एक नई activity जोड़ें

```python
result = manage_workflow({"action": "add_activity",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "name": "Manager Approval",
    "description": "Approval step for the manager",
    "activity_type": "approval"
})
```

#### किसी मौजूदा activity को अपडेट करें

```python
result = manage_workflow({"action": "update_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591",
    "name": "Updated Activity Name",
    "description": "Updated activity description"
})
```

#### किसी activity को हटाएँ

```python
result = manage_workflow({"action": "delete_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591"
})
```

#### किसी workflow में activities का क्रम पुनः व्यवस्थित करें

```python
result = manage_workflow({"action": "reorder_activities",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "activity_ids": [
        "3cda7cda87a9c150e0b0df23cebb3591",
        "4cda7cda87a9c150e0b0df23cebb3592",
        "5cda7cda87a9c150e0b0df23cebb3593"
    ]
})
```

## Flow Designer टूल

Flow Designer (`sys_hub_flow`) legacy workflows का आधुनिक उत्तराधिकारी है। MCP सर्वर processflow API के माध्यम से एक स्क्रीन-फ़िडेलिटी read के साथ-साथ एक सत्यापित edit सतह (conditions, action inputs, properties, copy, activate) उजागर करता है, जो tool पैकेज द्वारा गेट किया गया है। एक चीज़ जिसे यह **नकली नहीं बनाएगा** वह है publish: snapshot recompile editor-गेटेड है, इसलिए टूल झूठी सफलता के बजाय एक manual-publish निर्देश लौटाता है। `sys_hub_*` पर Raw Table-API writes अवरुद्ध (guard G6) हैं क्योंकि वे flow snapshots को भ्रष्ट कर देते हैं।

### `manage_flow_designer` (एकीकृत)
action डिस्पैच के साथ एकल समग्र टूल। पिछले 6 स्टैंडअलोन flow टूल (`list_flow_designers`, `get_flow_designer_detail`, `get_flow_designer_executions`, `compare_flows`, `update_flow_designer`, `manage_flow_edit`) को प्रतिस्थापित करता है। Action enum को `standard` में read-only तक संकुचित किया गया है और `portal_developer` / `platform_developer` / `full` में अनलॉक किया गया है।

Read actions (`standard` में उपलब्ध):
- `action="read"` (v1.18.6) — **स्क्रीन-फ़िडेलिटी** read: एक क्रमबद्ध, If/Else-नेस्टेड step वृक्ष (actions + logic + subflows निष्पादन क्रम के अनुसार मर्ज किए गए), conditions **मानव-पठनीय पाठ में डिकोड की गई**, data pills उन्हें उत्पन्न करने वाले step लेबल्स से हल किए गए, और custom Action प्रकार उनके Script बॉडी के साथ। Cycle/missing-uid गार्डेड। 142-नोड flow के लिए ~18K टोकन (पहले के ~130K की तुलना में) — किसी flow को समझने के लिए यहाँ से शुरू करें।
- `action="read_action"` — किसी एकल custom Action परिभाषा की Script बॉडी पढ़ें।
- `action="list"` — flows/subflows खोजें। मुख्य params: `limit`, `offset`, `include_inactive`, `flow_status`, `scope`, `name_filter`।
- `action="get_detail"` — flow मेटाडेटा + वैकल्पिक भारी अनुभाग। मुख्य params: `flow_id` (required), `include_structure`, `include_triggers`, `include_executions_summary`, `trace_pill`, `include_subflow_tree`, `summary_format`।
- `action="get_executions"` — रनटाइम इतिहास (फ़िल्टर) या एकल execution विवरण। मुख्य params: `context_id` (single mode), `flow_id`, `flow_name`, `exec_state`, `source_record`, `errors_only`, `limit`/`offset`।
- `action="compare"` — दो flows की तुलना `flow_id_a`/`flow_id_b` या `name_a`/`name_b` द्वारा करें। संरचनात्मक diff, subflow bindings, trigger अंतर रिपोर्ट करता है। `get_detail` को दो बार कॉल करने की तुलना में प्राथमिकता दी जाती है।

Write actions (केवल `portal_developer` / `platform_developer` / `full` में)। सभी edits **लाइव सत्यापित** होते हैं (save के बाद पुनः पढ़े जाते हैं) और `dry_run` का समर्थन करते हैं:
- `action="update"` — केवल मेटाडेटा (`new_name` / `description` / `active`)।
- `action="checkout"` — एक स्थानीय edit सत्र शुरू करें (browser auth आवश्यक, processflow API का उपयोग करता है)। `action="status"` इसका निरीक्षण करता है; `action="discard"` इसे छोड़ देता है।
- `action="set_action_input"` — action input मान पैच करें। इसके लिए `node_id`, `input_name`, `value` आवश्यक हैं।
- `action="set_branch_condition"` / `action="set_trigger_condition"` — किसी logic-branch या trigger condition को पैच करें। संरचित पंक्तियाँ `[{field, operator, value}]` **या** एक raw encoded query पास करें; प्रतिक्रिया `condition_readable` को इको करती है ताकि आप पुष्टि कर सकें कि encoder ने वही उत्पन्न किया जो आपका अभिप्राय था (operators में CHANGES परिवार, AND/OR/NQ शामिल हैं)।
- `action="set_property"` / `action="save_properties"` — flow properties: Run As, Protection, Priority, `active`।
- `action="copy"` — नेटिव flow/subflow क्लोन (वही कॉल जो Workflow Studio का "Copy flow" करता है)।
- `action="activate"` / `action="deactivate"` — flow की सक्रिय स्थिति टॉगल करें।
- `action="save"` — processflow API के माध्यम से edits को persist करें (एक scope-correct PUT जो एक नया flow संस्करण भी लिखता है — silent trigger-revert का समाधान)।
- `action="publish"` — **editor-गेटेड।** Snapshot recompile केवल इंटरैक्टिव Workflow Studio editor से पहुँच योग्य है; हर API पथ तेज़ी से विफल हो जाता है। टूल सफलता का दिखावा नहीं करता — यह `manual_publish_required` के साथ-साथ publish को हाथ से पूरा करने के लिए सटीक UI URL लौटाता है।

### Flow Designer Table Map

| Workflow Studio टैब | तालिका |
| --- | --- |
| Flows / SubFlows | `sys_hub_flow` |
| Actions | `sys_hub_action_type_definition` |
| Playbooks | `sys_pd_process_definition` |
| Decision Tables | `sys_decision` |

### Read-only पूर्वाग्रह

इस कोडबेस में flow संशोधन सबसे अधिक जोखिम वहन करते हैं — एक प्रकाशित flow को भ्रष्ट करना पूरे इंस्टेंस में स्वचालन को तोड़ सकता है। डिफ़ॉल्ट रूप से read actions का उपयोग करें, writes को स्पष्ट उपयोगकर्ता पुष्टि के पीछे गेट करें, और किसी भी परिवर्तन से पहले व्यवहार सत्यापित करने के लिए `manage_flow_designer(action="compare")` + `manage_flow_designer(action="get_executions")` को प्राथमिकता दें।

## सामान्य Activity प्रकार

ServiceNow कई activity प्रकार प्रदान करता है जिनका उपयोग किसी workflow में activities जोड़ते समय किया जा सकता है:

1. **approval** - एक approval activity जिसके लिए उपयोगकर्ता क्रिया आवश्यक है
2. **task** - एक कार्य जिसे पूरा करने की आवश्यकता है
3. **notification** - उपयोगकर्ताओं को एक सूचना भेजता है
4. **timer** - एक निर्दिष्ट समय अवधि की प्रतीक्षा करता है
5. **condition** - एक condition का मूल्यांकन करता है और workflow को शाखाओं में विभाजित करता है
6. **script** - एक स्क्रिप्ट निष्पादित करता है
7. **wait_for_condition** - तब तक प्रतीक्षा करता है जब तक कोई condition पूरी न हो जाए
8. **end** - workflow को समाप्त करता है

## सर्वोत्तम प्रथाएँ

1. **Version Control**: महत्वपूर्ण परिवर्तन करने से पहले हमेशा किसी workflow का एक नया संस्करण बनाएँ।
2. **Testing**: उत्पादन में परिनियोजन से पहले गैर-उत्पादन परिवेश में workflows का परीक्षण करें।
3. **Documentation**: प्रत्येक workflow और activity के उद्देश्य और व्यवहार का दस्तावेज़ीकरण करें।
4. **Error Handling**: अप्रत्याशित स्थितियों को संभालने के लिए अपने workflows में error handling शामिल करें।
5. **Notifications**: workflow प्रगति के बारे में हितधारकों को सूचित रखने के लिए notification activities का उपयोग करें।

## समस्या निवारण

### सामान्य समस्याएँ

1. **Error: "No published versions found for this workflow"**
   - यह त्रुटि तब होती है जब किसी ऐसे workflow के लिए activities प्राप्त करने का प्रयास किया जाता है जिसका कोई प्रकाशित संस्करण नहीं है।
   - समाधान: workflow की activities प्राप्त करने का प्रयास करने से पहले उसका एक संस्करण प्रकाशित करें।

2. **Error: "Activity type is required"**
   - यह त्रुटि तब होती है जब किसी activity को उसके प्रकार को निर्दिष्ट किए बिना जोड़ने का प्रयास किया जाता है।
   - समाधान: activity जोड़ते समय एक मान्य activity प्रकार प्रदान करें।

3. **Error: "Cannot modify a published workflow version"**
   - यह त्रुटि तब होती है जब किसी प्रकाशित workflow संस्करण को संशोधित करने का प्रयास किया जाता है।
   - समाधान: परिवर्तन करने से पहले workflow का एक नया draft संस्करण बनाएँ।

4. **Error: "Workflow ID is required"**
   - यह त्रुटि तब होती है जब उन ऑपरेशनों के लिए workflow ID प्रदान नहीं किया जाता जिनके लिए यह आवश्यक है।
   - समाधान: सुनिश्चित करें कि आप अपने अनुरोध में workflow ID शामिल करें।

## अतिरिक्त संसाधन

- [ServiceNow Workflow Documentation](https://docs.servicenow.com/bundle/tokyo-platform-administration/page/administer/workflow-administration/concept/c_WorkflowAdministration.html)
- [ServiceNow Workflow API Reference](https://developer.servicenow.com/dev.do#!/reference/api/tokyo/rest/c_WorkflowAPI)
