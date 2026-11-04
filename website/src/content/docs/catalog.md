---
title: "Service Catalog"
description: "ServiceNow Service Catalog integration tools and workflows."
slug: catalog
---

One tool, `manage_catalog`, covers service catalog categories (`sc_category`),
items (`sc_cat_item`) and item variables (`item_option_new`).

| Package | Actions |
|---|---|
| `service_desk` | the four read actions |
| `portal_developer`, `full` | every action |

Write actions need `confirm='approve'`, like every write in this server.

## Read actions

| Action | Arguments | Returns |
|---|---|---|
| `action="list_categories"` | `limit`, `offset`, `query`, `active`, `count_only` | categories |
| `action="list_items"` | `limit`, `offset`, `query`, `category`, `active`, `count_only` | items |
| `action="get_item"` | `item_id` | the item and its variables |
| `action="list_item_variables"` | `catalog_item_id` | variables: name, label, type code, mandatory, default, order |

The two list actions return:

- `count`: the rows on this page.
- `total`: how many rows match on the server.
- `more`: present when there is another page. It also gives the offset to ask
  for next.

If the server sends no match count, the response says `total_unknown` instead
of guessing one. `count_only=true` returns just the count.

## Write actions

| Action | Required | Optional |
|---|---|---|
| `action="create_category"` | `title` | `description`, `parent`, `icon`, `active`, `order` |
| `action="update_category"` | `category_id` and one field or more | the same fields as create |
| `action="update_item"` | `item_id` and one field or more | `name`, `short_description`, `description`, `category`, `price`, `active`, `order` |
| `action="move_items"` | `item_ids`, `target_category_id` | |
| `action="create_variable"` | `catalog_item_id`, `variable_name`, `variable_type`, `label` | `mandatory`, `help_text`, `default_value`, `description`, `order`, `reference_table`, `reference_qualifier`, `max_length`, `min`, `max` |
| `action="update_variable"` | `variable_id` and one field or more | `variable_name`, `variable_type`, `reference_table`, and the optional fields of create |

### Variable types

`item_option_new.type` stores a number, not a word. Pass the number or its label:

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

Before writing, the tool checks the value against the instance's own choice list
(`sys_choice`), so options added on your instance are accepted too. A value
that is not on the list is refused, and the refusal lists every valid code.
If the choice list cannot be read, nothing is written.

### Length and range

- `item_option_new` has no `max_length` column. `max_length` is saved in the
  variable's `attributes` as `max_length=N`, the same way the platform saves it.
- `min` and `max` set `scale_min` and `scale_max`, the range of a rating scale.

## Previews

Pass `dry_run=true` on any write action:

- `action="update_category"` and `action="update_item"` return a field-by-field diff.
- Every other write action returns `would_send`: the exact request the call
  would make.

Either way, nothing is written. The server enforces this for every tool. A
preview cannot turn into a write.

## Example prompts

- "List the catalog categories and how many items each one holds."
- "Show the variables on the 'New Laptop' item."
- "Add a mandatory Single Line Text variable 'asset_tag' to that item. Preview it first."
- "Move these three items into the Hardware category."
