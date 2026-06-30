# ServiceNow MCP - टूल इन्वेंटरी

`scripts/regenerate_tool_inventory.py` द्वारा स्वतः-जनित (AUTO-GENERATED)। हाथ से संपादित न करें।

लाइव रजिस्ट्री में पंजीकृत टूल: **65**
`full` में पैकेज किए गए टूल की संख्या: **54**
पंजीकृत परंतु वर्तमान में अनपैकेज्ड टूल: **11**

`list_tool_packages` को `none` को छोड़कर हर सक्षम पैकेज में रनटाइम पर इंजेक्ट किया जाता है।
इसे नीचे प्रलेखित किया गया है, परंतु इस फ़ाइल में पैकेज गणनाएँ YAML-परिभाषित टूल सतह को दर्शाती हैं।

## पैकेज सारांश

| Package | Tools | Description |
|---------|------:|-------------|
| `none` | 0 | जानबूझकर टूल बंद करने के लिए अक्षम प्रोफ़ाइल। |
| `core` | 12 | त्वरित health/schema/table कार्य के लिए न्यूनतम read-only आवश्यक टूल। |
| `standard` | 28 | incidents, changes, portal, logs, और source analysis में डिफ़ॉल्ट read-only पैकेज। |
| `service_desk` | 30 | परिचालन समर्थन के लिए standard के साथ incident और change write workflows। |
| `portal_developer` | 40 | standard के साथ portal, changeset, script include, और local-sync delivery workflows। |
| `platform_developer` | 40 | standard के साथ workflow, Flow Designer, UI policy, incident/change, और script writes। |
| `full` | 54 | सबसे व्यापक पैकेज सतह: सभी manage_* workflows के साथ उन्नत संचालन। |

## रनटाइम-इंजेक्टेड सहायक (Helpers)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `list_tool_packages` | R | उपलब्ध tool packages और वर्तमान में सक्रिय पैकेज को सूचीबद्ध करता है। | `core`, `standard`, `service_desk`, `portal_developer`, `platform_developer`, `full` |
| `list_instances` | R | read-only data comparison mode के लिए कॉन्फ़िगर किए गए aliases को सूचीबद्ध करता है। | runtime comparison helper |
| `compare_instances` | R | कॉन्फ़िगर किए गए aliases में read-only record तुलना; यह write-routing तंत्र नहीं है। | runtime comparison helper |

## पंजीकृत परंतु अनपैकेज्ड टूल

ये टूल कोड में पंजीकृत हैं परंतु जानबूझकर पैकेज की गई YAML सतहों से बाहर रखे गए हैं। ये कस्टम बिल्ड, परीक्षण, या भविष्य के पैकेजिंग निर्णयों के लिए पहुँच योग्य बने रहते हैं।

`create_category`, `create_knowledge_base`, `get_developer_daily_summary`, `get_repo_file_last_modifier`, `get_repo_recent_commits`, `get_repo_working_tree_status`, `get_uncommitted_changes`, `manage_epic`, `manage_project`, `manage_scrum_task`, `manage_story`

## मॉड्यूल के अनुसार टूल

**R/W** कॉलम अप्रतिबंधित होने पर टूल की पूर्ण क्षमता है। `pkg (actions…)` के रूप में दिखाया गया पैकेज उस टूल की केवल उन्हीं actions को उजागर करता है — उदाहरण के लिए, `manage_script_include` `R/W` के रूप में पंजीकृत है परंतु read-only पैकेज (`core`, `standard`) इसे `standard (get, list)` के रूप में उजागर करते हैं। बिना कोष्ठक के सूचीबद्ध पैकेज टूल को उसकी पूर्ण R/W क्षमता पर उजागर करते हैं।

### Attachment Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `download_attachment` | R | attachment_sys_id, या table+record द्वारा ServiceNow attachment फ़ाइल(ओं) को डिस्क पर डाउनलोड करें। saved_path से पढ़ें। | standard, portal_developer, platform_developer, service_desk, full |

### Audit Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | लंबित update set परिवर्तनों का ऑडिट करें — प्रकार, जोखिम पैटर्न, clones, और cross-refs के अनुसार इन्वेंटरी। | full |

### Catalog Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_catalog` | R/W | Catalog category/item/variable CRUD (tables: sc_category, sc_cat_item, item_option_new)। | portal_developer, service_desk (get_item, list_categories, list_item_variables, list_items), full |

### Change Tools (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `approve_change` | W | किसी change के approval record को स्वीकृत करें (approver_id द्वारा); change_request को आगे बढ़ाएँ (default: implement)। | full |
| `manage_change` | R/W | किसी change request को Get/create/update करें या change task जोड़ें (table: change_request)। | platform_developer, full |
| `reject_change` | W | किसी change के approval record को कारण के साथ अस्वीकार करें (approver_id द्वारा); change_request को आगे बढ़ाएँ (default: canceled)। | full |
| `submit_change_for_approval` | W | किसी change request को assess state में बदलें और approval record बनाएँ। change_id आवश्यक है। | platform_developer, full |

### Changeset Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_changeset` | R/W | किसी update set पर Get/create/update/commit/publish/add_file (table: sys_update_set)। | portal_developer, platform_developer, full |

### Epic Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_epic` | R/W | Epic CRUD (table: rm_epic)। list confirm को छोड़ देता है। | — |

### Flow Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_flow_designer` | R/W | Flow Designer read/inspect। संपादन action inputs + trigger/branch conditions तक सीमित; कोई संरचनात्मक परिवर्तन नहीं (UI का उपयोग करें)। | core (list), standard (get_action_source, get_detail, get_executions, list), portal_developer, platform_developer, service_desk (get_action_source, get_detail, get_executions, list), full |

### Incident Management (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_incident` | R/W | किसी incident को Get/create/update/comment/resolve करें (table: incident)। एक कॉल, किसी schema lookup की आवश्यकता नहीं। | platform_developer, service_desk, full |

### Knowledge Base (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_category` | W | किसी knowledge base के अंतर्गत KB category बनाएँ। kb_id और label आवश्यक हैं। | — |
| `create_knowledge_base` | W | एक knowledge base (kb_knowledge_base) बनाएँ। title आवश्यक है। sys_id लौटाता है। | — |
| `manage_kb_article` | R/W | एक knowledge article बनाएँ/अपडेट करें/प्रकाशित करें (table: kb_knowledge)। | full |

### Local Graph Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `query_local_graph` | R | audit graph फ़ाइलों से ऑफ़लाइन dependency/impact उत्तर (0 API)। uses|used_by|page|impact। | standard, portal_developer, platform_developer, service_desk, full |

### Logs (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_logs` | R | ServiceNow logs को क्वेरी करें। log_type: system/journal/transaction/background। अधिकतम 20 rows। | core, standard, portal_developer, platform_developer, service_desk, full |

### Performance Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | widget performance का विश्लेषण करें — code patterns, transaction logs, provider usage। severity के साथ findings लौटाता है। | standard, portal_developer, platform_developer, service_desk, full |

### Portal CRUD (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_portal_component` | W | portal components बनाएँ; या sys_id द्वारा किसी भी code record को संपादित करें — BR, notification, SI, ACL, UI, आदि। action=update_code। | portal_developer, platform_developer, full |
| `manage_portal_layout` | W | Portal layout: page CRUD + container/row/column + widget instance placement। | portal_developer, platform_developer, full |
| `scaffold_page` | W | एक ही कॉल में layout (container/rows/columns) और widget placements के साथ एक पूर्ण portal page बनाएँ। Scope आवश्यक है। | portal_developer, platform_developer, full |

### Portal Dev Tools (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_developer_changes` | R | portal tables में developer के हाल के परिवर्तन सूचीबद्ध करें। केवल Metadata, पहले count_only का उपयोग करें। | standard, portal_developer, platform_developer, service_desk, full |
| `get_developer_daily_summary` | R | developer का दैनिक कार्य सारांश जनित करें। jira/plain/structured आउटपुट प्रारूपों का समर्थन करता है। | — |
| `get_uncommitted_changes` | R | किसी developer के लिए uncommitted update set entries सूचीबद्ध करें। entry प्रकार और लक्ष्य लौटाता है। पहले count_only=true का उपयोग करें। | — |

### Portal Management (9)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | R | प्रस्तावित portal component संपादन का विश्लेषण करें और सीमित जोखिम व field-change सारांश लौटाएँ | portal_developer, full |
| `detect_angular_implicit_globals` | R | Angular provider scripts में अघोषित variable असाइनमेंट का पता लगाएँ जो runtime 'not defined' त्रुटियाँ उत्पन्न करते हैं। | portal_developer, full |
| `download_portal_sources` | R | लक्षित portal widgets/providers। पूरा ऐप: download_app_sources। widget_ids=एक widget। | standard, portal_developer, platform_developer, service_desk, full |
| `get_portal_component_code` | R | widget/provider/SI fields प्राप्त करें। डिफ़ॉल्ट रूप से पूर्ण body लौटाता है। विश्लेषण के लिए कभी chunk न करें। | standard, portal_developer, platform_developer, service_desk, full |
| `get_widget_bundle` | R | एक ही कॉल में पूर्ण widget bundle (HTML, scripts, providers, CSS/JS dependencies) प्राप्त करें। विश्लेषण का प्रारंभ बिंदु। | standard, portal_developer, platform_developer, service_desk, full |
| `preview_portal_component_update` | R | प्रस्तावित portal component संपादन के लिए सीमित before/after स्निपेट और diff का पूर्वावलोकन करें | portal_developer, full |
| `route_portal_component_edit` | R | किसी portal संपादन निर्देश को सही analyze/preview/apply टूल पर रूट करें। | portal_developer, full |
| `search_portal_regex_matches` | R | portal code (widget/provider/SI) पर वास्तविक regex, offsets+context। Server-table keyword search: search_server_code। | standard, portal_developer, platform_developer, service_desk, full |
| `trace_portal_route_targets` | R | widget→provider→route संबंधों को मैप करें। केवल Metadata, कोई script bodies नहीं। | standard, portal_developer, platform_developer, service_desk, full |

### Portal Management Tools (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_page` | R | URL path, title, या sys_id द्वारा portal pages प्राप्त करें या सूचीबद्ध करें। widget placements के साथ layout tree लौटाता है। | core, standard, portal_developer, platform_developer, service_desk, full |
| `get_portal` | R | name, URL suffix, या sys_id द्वारा Service Portals प्राप्त करें या सूचीबद्ध करें। config, homepage, theme, और pages लौटाता है। | full |
| `get_widget_instance` | R | किसी page पर widget instance placement प्राप्त करें। column, order, और config लौटाता है। page या widget द्वारा फ़िल्टर करें। | standard, portal_developer, platform_developer, service_desk, full |

### Project Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_project` | R/W | Project CRUD (table: pm_project)। list confirm को छोड़ देता है। | — |

### Repository (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | संयुक्त git रिपोर्ट: working tree status + recent commits + प्रति-फ़ाइल last modifier एक ही कॉल में। | full |
| `get_repo_file_last_modifier` | R | वैकल्पिक uncommitted status के साथ प्रति-फ़ाइल last modifier और commit metadata देखें | — |
| `get_repo_recent_commits` | R | author और वैकल्पिक बदली गई फ़ाइल सूचियों के साथ recent commits सूचीबद्ध करें | — |
| `get_repo_working_tree_status` | R | staged, unstaged, और untracked फ़ाइलों सहित working tree status का निरीक्षण करें | — |

### Script Include (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_script_include` | R/W | किसी script include को List/get/create/update/delete/execute करें (table: sys_script_include)। | core (get, list), standard (get, list), portal_developer, platform_developer, service_desk (get, list), full |

### Scrum Task Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_scrum_task` | R/W | Scrum task CRUD (table: rm_scrum_task)। list confirm को छोड़ देता है। | — |

### Session Context Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_session_context` | W | वर्तमान application + update set को Get/switch करें (browser auth)। set_* read-back के माध्यम से सत्यापित करता है। | portal_developer, platform_developer, full |

### Sn Api (7)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `sn_aggregate` | R | वैकल्पिक group_by के साथ किसी भी table पर COUNT/SUM/AVG/MIN/MAX चलाएँ। records प्राप्त किए बिना आँकड़े लौटाता है। | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_discover` | R | name या label keyword द्वारा tables खोजें। table name, label, scope, और parent class लौटाता है। | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_health` | R | ServiceNow API कनेक्टिविटी, auth status, Chromium install state (browser auth), और MCP server संस्करण जाँचें। | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_query` | R | सामान्य table query — अंतिम उपाय। domain tools को प्राथमिकता दें: search_server_code, manage_workflow, manage_flow_designer। | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_resolve_url` | R | किसी ServiceNow URL को पार्स करें → table, sys_id, scope, सुझाया गया अगला टूल। Read-only। | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_schema` | R | किसी दिए गए table के लिए sys_dictionary से field names, types, labels, और constraints प्राप्त करें। | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_write` | W | अंतिम उपाय CRUD (कोई समर्पित टूल नहीं)। manage_*/update_* को प्राथमिकता दें। ACL/user/group/scope अवरुद्ध। confirm='approve'। | full |

### Source Analysis (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `download_app_sources` | R | किसी ऐप scope का पूर्ण/संपूर्ण source डिस्क पर (सभी groups+deps)। scope आवश्यक — उपयोगकर्ता से पूछें। Step 1, portal नहीं। | standard, portal_developer, platform_developer, service_desk, full |
| `download_server_sources` | R | लक्षित server-side source families (SIs/BRs/UI/api/security/admin)। पूरा ऐप: download_app_sources। | platform_developer, full |
| `download_table_schema` | R | sys_dictionary field defs डाउनलोड करें। tables निर्दिष्ट करें या local sources से auto-detect करें। | platform_developer, full |
| `extract_table_dependencies` | R | server scripts (SI/BR/widgets) से GlideRecord table dependency graph। एक widget के लिए widget_id पास करें। | standard, portal_developer, platform_developer, service_desk, full |
| `get_metadata_source` | R | name/sys_id द्वारा एक source record (SI/BR/widget) प्राप्त करें। body लौटाता है; यदि preview truncated है तो 'complete' फ़्लैग करता है। | standard, portal_developer, platform_developer, service_desk, full |
| `search_server_code` | R | 22 server-side code प्रकारों (SI/BR/ACL) में तेज़ keyword search। Portal regex+snippets: search_portal_regex_matches। | core, standard, portal_developer, platform_developer, service_desk, full |

### Source Audit Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_local_sources` | R | डाउनलोड किए गए sources का स्थानीय रूप से विश्लेषण करें (कोई API नहीं)। cross-ref graph, dead code, HTML रिपोर्ट जनित करता है। | standard, portal_developer, platform_developer, service_desk, full |

### Story Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_story` | R/W | Story CRUD + dependency ops (rm_story/m2m_story_dependencies)। list/list_dependencies confirm को छोड़ देते हैं। | — |

### Sync Tools (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `diff_local_component` | R | स्थानीय संपादनों की remote के विरुद्ध (या compare_to के माध्यम से किसी दूसरे download root के विरुद्ध, जैसे dev-vs-test) diff। | standard, portal_developer, platform_developer, service_desk, full |
| `update_remote_from_local` | W | एक स्थानीय संपादन को ServiceNow पर वापस पुश करें (पहले diff_local_component)। लक्षित रिफ़्रेश, बल्क dev→test प्रमोशन नहीं। | portal_developer, platform_developer, full |

### UI Policy (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_ui_policy` | W | UI Policy create + add field action (tables: sys_ui_policy / sys_ui_policy_action)। | portal_developer, platform_developer, full |

### User Tools (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_group` | R/W | Group CRUD + membership ops (table: sys_user_group)। list confirm को छोड़ देता है। | full |
| `manage_user` | R/W | User CRUD + lookup (table: sys_user)। Read actions confirm को छोड़ देती हैं। | full |

### Widget Dependency Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_widget_dependency` | R/W | widget Angular providers व CSS/JS dependencies के लिए CRUD + link/unlink। sys_ids के लिए पहले action=list का उपयोग करें। | standard (get, list), portal_developer, platform_developer (get, list), service_desk (get, list), full |

### Workflow (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_workflow` | R/W | केवल LEGACY Workflow engine (wf_workflow/wf_activity)। अधिकांश flows Flow Designer हैं -> manage_flow_designer का उपयोग करें। | core (get_activities, list), standard (get_activities, list), portal_developer, platform_developer, service_desk (get_activities, list), full |
