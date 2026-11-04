---
title: "सर्विस कैटलॉग"
description: "ServiceNow Service Catalog integration tools and workflows."
slug: hi/catalog
---

एक ही टूल, `manage_catalog`, सर्विस कैटलॉग की categories (`sc_category`), items (`sc_cat_item`) और item variables (`item_option_new`) संभालता है।

| Package | Actions |
|---|---|
| `service_desk` | चारों read actions |
| `portal_developer`, `full` | सभी actions |

इस server की हर write की तरह, write actions के लिए `confirm='approve'` ज़रूरी है।

## Read actions

| Action | Arguments | क्या लौटाता है |
|---|---|---|
| `action="list_categories"` | `limit`, `offset`, `query`, `active`, `count_only` | categories |
| `action="list_items"` | `limit`, `offset`, `query`, `category`, `active`, `count_only` | items |
| `action="get_item"` | `item_id` | item और उसके variables |
| `action="list_item_variables"` | `catalog_item_id` | variables: name, label, type code, mandatory, default, order |

दोनों list actions ये लौटाते हैं:

- `count`: इस page की rows।
- `total`: server पर कितनी rows match करती हैं।
- `more`: सिर्फ़ तब आता है जब अगला page हो; अगली बार माँगने वाला offset भी बताता है।

अगर server match count नहीं भेजता, तो response अंदाज़ा लगाने के बजाय `total_unknown` बताता है। `count_only=true` सिर्फ़ count लौटाता है।

## Write actions

| Action | ज़रूरी | वैकल्पिक |
|---|---|---|
| `action="create_category"` | `title` | `description`, `parent`, `icon`, `active`, `order` |
| `action="update_category"` | `category_id` और कम से कम एक field | create वाले ही fields |
| `action="update_item"` | `item_id` और कम से कम एक field | `name`, `short_description`, `description`, `category`, `price`, `active`, `order` |
| `action="move_items"` | `item_ids`, `target_category_id` | |
| `action="create_variable"` | `catalog_item_id`, `variable_name`, `variable_type`, `label` | `mandatory`, `help_text`, `default_value`, `description`, `order`, `reference_table`, `reference_qualifier`, `max_length`, `min`, `max` |
| `action="update_variable"` | `variable_id` और कम से कम एक field | `variable_name`, `variable_type`, `reference_table`, और create के वैकल्पिक fields |

### Variable types

`item_option_new.type` में शब्द नहीं, एक number code रखा जाता है। Code या उसका label, कोई भी भेजें:

| Code | Label |
|---|---|
| `6` | Single Line Text |
| `2` | Multi Line Text |
| `5` | Select Box |
| `3` | Multiple Choice |
| `7` | CheckBox |
| `8` | Reference |
| `9` | Date |
| `10` | Date/Time |

लिखने से पहले टूल value को उसी instance की choice list (`sys_choice`) से मिलाता है, इसलिए आपके instance में जोड़े गए options भी स्वीकार होते हैं। जो value list में नहीं है वह refuse होती है, और refusal में सभी valid codes दिए जाते हैं। अगर choice list पढ़ी न जा सके, तो कुछ नहीं लिखा जाता।

### Length और range

- `item_option_new` में `max_length` column नहीं है। `max_length` को platform के अपने तरीके से variable के `attributes` में `max_length=N` के रूप में रखा जाता है।
- `min` और `max` से `scale_min` और `scale_max` set होते हैं, जो rating scale की range है।

## Previews

किसी भी write action पर `dry_run=true` दिया जा सकता है:

- `action="update_category"` और `action="update_item"` field-by-field diff लौटाते हैं।
- बाकी सभी write actions `would_send` लौटाते हैं: वही request जो call भेजती।

दोनों में से किसी भी हालत में कुछ नहीं लिखा जाता। Server यह नियम हर टूल पर लागू करता है, इसलिए preview कभी असली write नहीं बन सकता।

## Example prompts

- "कैटलॉग categories और हर एक में कितने items हैं, दिखाओ।"
- "'New Laptop' item के variables दिखाओ।"
- "उस item में mandatory Single Line Text variable 'asset_tag' जोड़ो। पहले preview करो।"
- "इन तीन items को Hardware category में ले जाओ।"
