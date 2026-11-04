---
title: "चेंज मैनेजमेंट"
description: "Change management tools available in the ServiceNow MCP server."
slug: hi/change_management
---

एक ही टूल, `manage_change`, चेंज रिक्वेस्ट (`change_request`), उनके टास्क और अप्रूवल के चरण संभालता है।

| पैकेज | एक्शन |
|---|---|
| `platform_developer`, `full` | हर एक्शन |

इस सर्वर के हर write की तरह write एक्शन के लिए `confirm='approve'` चाहिए। लंबी या फ़िल्टर की गई सूचियों के लिए `table=change_request` के साथ `sn_query` भी काम करता है।

## एक्शन

| एक्शन | ज़रूरी | वैकल्पिक |
|---|---|---|
| `action="get"` | एक रिकॉर्ड के लिए `change_id`; सूची के लिए कुछ नहीं | `limit`, `offset`, `timeframe`, `query`, `state`, `type`, `category`, `assignment_group`, `count_only` |
| `action="create"` | `short_description`, `type` | `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date` |
| `action="update"` | `change_id` और कम से कम एक फ़ील्ड | `short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes` |
| `action="add_task"` | `change_id`, `task_short_description` | `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date` |
| `action="submit"` | `change_id` | `state` (डिफ़ॉल्ट Assess), `work_notes` (अप्रूवल अनुरोध की टिप्पणी) |
| `action="approve"` | `change_id` | `approver_id`, `state` (डिफ़ॉल्ट Implement), `work_notes` (टिप्पणी) |
| `action="reject"` | `change_id`, `work_notes` (कारण) | `approver_id`, `state` (डिफ़ॉल्ट Canceled) |

## अप्रूवल

- `action="submit"` चेंज को लक्ष्य state में ले जाता है और requested state में एक अप्रूवल रिकॉर्ड बनाता है।
- `action="approve"` और `action="reject"` `approver_id` (sys_id या नाम) के अप्रूवल रिकॉर्ड पर लागू होते हैं। यह न दिया हो तो वे पहले लंबित रिकॉर्ड पर लागू होते हैं। फिर चेंज को लक्ष्य state में ले जाते हैं।
- submit और approve के लिए `confirm_publish='approve'` भी चाहिए, क्योंकि वे ऐसे चेंज को आगे बढ़ाते हैं जिस पर दूसरे लोग काम करते हैं।

## चॉइस मान

`state`, `type`, `risk` और `impact` में शब्द नहीं, कोड सहेजे जाते हैं: `state` में -4 का अर्थ Assess और -1 का अर्थ Implement है। कोड या उसका लेबल भेजें। लिखने से पहले टूल मान को इंस्टेंस की अपनी चॉइस सूची (`sys_choice`) से मिलाता है। जो मान सूची में नहीं है उसे अस्वीकार किया जाता है, और अस्वीकृति में हर मान्य मान दिया जाता है।

approve और reject में अप्रूवल रिकॉर्ड को छूने से पहले लक्ष्य state जाँची जाती है। इसलिए गलत state की वजह से ऐसा नहीं हो सकता कि अप्रूवल तय हो जाए और चेंज जहाँ था वहीं रह जाए।

## प्रीव्यू

किसी भी write एक्शन पर `dry_run=true` भेजें:

- `action="update"` फ़ील्ड-दर-फ़ील्ड अंतर लौटाता है।
- `action="approve"` और `action="reject"` वह अप्रूवल रिकॉर्ड और चेंज state लौटाते हैं जो वे सेट करते।
- बाकी हर write एक्शन `would_send` लौटाता है: वही अनुरोध जो कॉल भेजती।

दोनों ही स्थितियों में कुछ भी नहीं लिखा जाता।

## उदाहरण प्रॉम्प्ट

- "कल रात सिक्योरिटी पैच लगाने के लिए सर्वर मेंटेनेंस का चेंज रिक्वेस्ट बनाओ।"
- "सर्वर मेंटेनेंस चेंज में प्री-इम्प्लीमेंटेशन जाँच का टास्क जोड़ो।"
- "सर्वर मेंटेनेंस चेंज को अप्रूवल के लिए भेजो।"
- "डेटाबेस अपग्रेड चेंज को अप्रूव करो, टिप्पणी: इम्प्लीमेंटेशन प्लान पूरा है।"
- "नेटवर्क चेंज को रिजेक्ट करो: टेस्टिंग पर्याप्त नहीं है।"
- "इस हफ़्ते के सभी इमरजेंसी चेंज दिखाओ।"
