---
name: asset-itom-map
description: Table map and first queries for HAM, materials management, CMDB and ITOM work
context_cost: low
safety_level: confirm
delegatable: false
required_input: the question (stock, asset lifecycle, CI, discovery run, alert)
output: report
tools:
  - sn_discover
  - sn_schema
  - sn_query
  - sn_aggregate
  - manage_asset
  - manage_procurement
triggers:
  - "자재 재고 확인"
  - "자산 현황"
  - "입고 출고 이관"
  - "PO 입고"
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

Checked on a HAM lab instance (HAM Pro, procurement and contracts on; Discovery, Service
Mapping and Event Management off): `proc_po`, `ast_contract` and `sn_hamp_*` hold data;
`em_*` does not exist; `discovery_*`, `ecc_agent` and `sa_*` tables **exist even with
their plugin off**. So a table being there proves nothing about Discovery or Service
Mapping.

The read tools decide this for you. They check the plugin or app state on the instance
and put the answer in `availability`. Do not infer it from a table list:

| `availability` | Meaning | Say |
|---|---|---|
| `not_installed` | The feature is off; `feature.evidence` names the plugin read back | "X is not on this instance". Do not try a similar table |
| `forbidden` | The table exists and the session's ACLs refuse it | Which role is missing. A role granted after login needs a fresh login |
| `absent` | No such table; the feature, if any, is on | A wrong name. Use `did_you_mean` |
| `undetermined` | `because` names what could not be read | "Not determined", with the reason |
| `rows_hidden_by_acl: N` | N rows on this page exist but are withheld | Never "fewer rows" |

`sn_schema(table=...)` before you filter on a column. `install_status` and `state`
values differ by instance, so read `sys_choice` rather than assuming numbers.

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

1. IDENTIFY the table from the maps above and read it. The answer's `availability` says
   whether the feature is there; a separate `sn_discover` first is not needed.
2. Count before reading: `sn_aggregate(table, group_by=...)` for stock by stockroom,
   assets by status, CIs by class. It lists the largest groups and accounts for the rest.
3. Dot-walk rather than making a second query:
   `fields="asset_tag,model.display_name,stockroom.name"`.
4. Reconcile a count sheet: `manage_workbook` (general add-on `office_files`) reads the sheet,
   `sn_query` with an `IN` list reads the system. Report the differences.
5. Name what could not be checked. A table that is absent or unreadable is "not
   determined", never "no stock" or "no failures".

## Writes

Asset records are written with `manage_asset`, in `asset_manager` and `full`. Before
any write it reads the instance: the class must extend `alm_asset`, every column must
exist on it, `install_status` and `substatus` must be on its choice list (a substatus
only under its own status), and every reference must point at a real record. Values
can be codes or labels.

| Lifecycle step | Call |
|---|---|
| Look one asset up | `manage_asset(action="get", asset_id=<sys_id, tag or serial>)` |
| Register an asset | `action="create"` with `model`, plus `install_status`, `stockroom`, `asset_tag`, `serial_number`. `model_category` comes from the model when it has one; `asset_class` defaults to `alm_hardware` |
| Hand it to a user | `action="update"` with `assigned_to` and `install_status` (In use) |
| Back to stock, repair, retire | `action="update"` with `install_status` and `substatus` |
| Move between stockrooms | `action="transfer"` with `stockroom` (from), `to_stockroom`, and `asset_ids` or `model` + `quantity`. It creates the transfer order and its lines; the stages after that are the platform's workflow |

1. Run the write with `dry_run=true` first and show the result.
2. Read `server_changed` in the answer. Business rules on `alm_asset` rewrite fields
   (status, stockroom, the CI link). A changed field did not take the value you sent:
   report it, never call it done.
3. `PARTIAL_TRANSFER` means the order exists with some lines. Name the order number
   and leave the decision to the user.

### Receiving against a purchase order

`manage_procurement(action="receive", po_line=<POL number or sys_id>, quantity=N)`.
It calls the Receive page's own server path, so the platform creates the assets (and
their CIs) and moves the line's quantities. It needs browser auth. Do NOT insert
`proc_rec_slip` / `proc_rec_slip_item` yourself: field ACLs drop `purchase_line` and
`quantity` from a Table API insert, which still answers 200 with an empty line.

1. CALL it with `dry_run=true`. `plan.required_by_page` is the instance's own rule:
   `serial_number` there means pass `serial_numbers`, one per unit, in order.
2. Show the plan (cost is in the line's own currency, the stockroom defaults to the
   order's ship-to), then run it without `dry_run`.
3. Report from the answer, not the request: `receiving_lines`, `assets` (tag, serial,
   status, stockroom) and `po_line_after`. `success: false` with `warnings` means
   something did not land; say which.

Hardware lines only. Software, consumable and bundle lines, MAC-required models and
tagged units on lines with pre-created assets are refused: say they go through the
Receive page.

Not covered: inventory audits and disposal. They are Hardware Asset Management plugin
flows. CI records are not written either. Say the
gap plainly. Do not reach for `sn_write` or hand over a background script.
Configuration writes (script includes, business rules, jobs) are in the `scripting`
add-on.

## ON ERROR

- `feature_not_installed`: report the feature as not on this instance. Stop; no retry.
- `unknown_table`: a wrong name. Use `did_you_mean`; when `feature` is `undetermined`, the feature may be missing too, so say so.
- `unknown_query_fields`: use the suggested name, or CALL `sn_schema`.
- `forbidden`: report the permission gap. Do not read it as empty or as not installed.

## DELEGATE hint

Reads are safe to delegate, and the result is a short report. Keep writes in the main session, where the user approves them. Have the agent return counts and differences, not rows.
