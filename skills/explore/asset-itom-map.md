---
name: asset-itom-map
description: Table map and first queries for HAM, materials management, CMDB and ITOM work
context_cost: low
safety_level: none
delegatable: yes
required_input: the question (stock, asset lifecycle, CI, discovery run, alert)
output: report
tools:
  - sn_discover
  - sn_schema
  - sn_query
  - sn_aggregate
triggers:
  - "자재 재고 확인"
  - "자산 현황"
  - "입고 출고 이관"
  - "CMDB 관계"
  - "디스커버리 실패"
  - "stock level"
  - "asset lifecycle"
  - "discovery failed"
---

# Instructions

You are answering a materials, asset, CMDB or ITOM question from live tables.

These are the platform's standard names. HAM, Discovery, Service Mapping and Event
Management are separately licensed plugins, so any of them can be absent.

Checked once, on one instance with no asset data: the `alm_*`, `cmdb_*`,
`discovery_status`, `discovery_log`, `discovery_device_history`, `ecc_*`, `svc_ci_assoc`
and import tables exist, and `alm_asset` declares tag, serial, model, status, stockroom,
quantity and `ci`. `proc_*`, `discovery_schedule` and `em_*` were absent there, so those
names are **unproven**: the plugin may be missing, or the name may be wrong.

**Confirm first, once per instance:** `sn_discover(keyword="alm_")`, then
`sn_schema(table=...)` for the table you will filter on. A missing table does not
mean there is no data: the work may sit in a custom table. `install_status` and
`state` values differ by instance, so read `sys_choice` rather than assuming numbers.

## Materials and assets

| Question | Table | Note |
|---|---|---|
| Any asset | `alm_asset` | Parent of the classes below; holds tag, serial, model, status, stockroom |
| Hardware | `alm_hardware` | `ci` links to the CMDB record |
| Consumables | `alm_consumable` | Counted by `quantity`, not one row per unit |
| Stockrooms | `alm_stockroom` | |
| Reorder rules | `alm_stock_rule` | |
| Moves between stockrooms | `alm_transfer_order`, `alm_transfer_order_line` | |
| What it is | `cmdb_model`, `cmdb_hardware_product_model`, `cmdb_consumable_product_model`, `cmdb_model_category` | |
| Purchasing | `proc_po`, `proc_po_item`, `proc_rec_slip`, `proc_rec_slip_item` | Requires procurement |
| Contracts | `ast_contract` | |

## CMDB and ITOM

| Question | Table | Note |
|---|---|---|
| Configuration items | `cmdb_ci`, `cmdb_ci_hardware` and subclasses | Query the narrowest class |
| Relationships | `cmdb_rel_ci`, `cmdb_rel_type` | `parent`, `child`, `type` |
| Discovery runs | `discovery_status`, `discovery_schedule`, `discovery_device_history`, `discovery_log` | |
| MID Server traffic | `ecc_agent`, `ecc_queue` | `ecc_queue` is large: always bound by date |
| Events and alerts | `em_event`, `em_alert`, `em_alert_rule` | `em_event` is large: always bound by date |
| Application services | `cmdb_ci_service_discovered`, `svc_ci_assoc` | |
| Imports | `sys_import_set`, `sys_import_set_run`, `sys_transform_map` | First stop for "the feed did not update" |

## Pipeline

1. IDENTIFY the table from the maps above, and CALL `sn_discover` to confirm it exists here.
2. Count before reading: `sn_aggregate(table, group_by=...)` for stock by stockroom,
   assets by status, CIs by class. It lists the largest groups and accounts for the rest.
3. Dot-walk rather than making a second query:
   `fields="asset_tag,model.display_name,stockroom.name"`.
4. Reconcile a count sheet: `manage_workbook` (general add-on `office_files`) reads the sheet,
   `sn_query` with an `IN` list reads the system. Report the differences.
5. Name what could not be checked. A table that is absent or unreadable is "not
   determined", never "no stock" or "no failures".

## Writes

`asset_manager` is read-only, and no package has a dedicated tool that updates asset or CI
records. Do not reach for `sn_write` or hand over a background script: say the gap
plainly. Configuration writes (script includes, business rules, jobs) are in the
`scripting` add-on.

## ON ERROR

- `unknown_table`: the plugin is absent or the name differs. CALL `sn_discover`, and report it as not determined if nothing fits.
- `unknown_query_fields`: use the suggested name, or CALL `sn_schema`.
- 403: the account may lack the asset or ITOM read role. Report it; do not read it as empty.

## DELEGATE hint

Safe to delegate: read-only, and the result is a short report. Have the agent return counts and differences, not rows.
