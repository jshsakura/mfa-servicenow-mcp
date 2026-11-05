---
title: "Tool Packages — Advanced Reference"
description: "Advanced reference for the read/write tool package system."
slug: TOOL_PACKAGES
---

> **Most users don't need this page.** The default package is `standard` — read-only, safe for any environment.
> Only read on if you need write tools beyond what `standard` provides.

---

## Choosing a package

Start with the narrowest package that covers your work. Each step up adds write access to more domains:

Read-only — safe for any environment, no write tools:

| Package | Tools | Max tokens | Max (3 instances) | When to use |
| :--- | :---: | :---: | :---: | :--- |
| `core` | 12 | ~2.2K | ~2.7K | Minimal read-only: health, schema, discovery, key artifact lookups only |
| `standard` | 31 | ~7.4K | ~8.3K | **(Default)** Read-only across incidents, changes, portal, logs, and source analysis |
| `none` | 0 | 0 | 0 | Intentionally disable all tools (testing, locked-down environments) |

Add-ons — general-purpose, not packages on their own. Combine with any package by comma (`MCP_TOOL_PACKAGE=asset_manager,scripting`); ⚠️ marks a write-capable one:

| Add-on | Tools | Adds | What it is for |
| :--- | :---: | :---: | :--- |
| `scripting` | 13 | +~4.6K | ⚠️ Server-side logic (script includes, business rules, scheduled jobs, REST messages, flow reads), update sets, XML deployment |
| `office_files` | 2 | +~0.7K | Excel workbooks (read, write, fill forms) and record attachments |
| `debug_window` | 3 | +~1.2K | ⚠️ The shared browser; `act_in_debug_window` can press Save |
| `source_sync` | 3 | +~0.9K | ⚠️ Download server-side sources, diff them, push them back |
| `portal_design` | 10 | +~2.8K | ⚠️ Portal design past the theme: page layout and instance CSS/options, widget and header/footer copies, Workspace lists — for `itsm_developer,portal_design` |

⚠️ Write-capable — **advanced options** that grant create/update/delete:

| Package | Tools | Max tokens | Max (3 instances) | When to use |
| :--- | :---: | :---: | :---: | :--- |
| `service_desk` | 34 | ~8.3K | ~9.3K | ⚠️ Service desk agents who need to update/close incidents and changes |
| `portal_developer` | 53 | ~16.8K | ~18.6K | ⚠️ Portal developers who deploy widgets, changesets, and script includes |
| `platform_developer` | 45 | ~13.7K | ~15.3K | ⚠️ Platform engineers who manage workflows, Flow Designer, and scripts |
| `full` | 68 | ~21.8K | ~24.2K | ⚠️ Most advanced — all write tools across all domains at once (see warning below) |
| `itsm_developer` | 34 | ~11.3K | ~12.7K | ⚠️ Standalone ITSM: diagnose a record, map table automation, configure catalog/policies/notifications, approvals and test orders, assignment/approval rules and choice lists, portal themes, ship by update set or XML. |
| `asset_manager` | 7 | ~1.2K | ~1.6K | ⚠️ Materials, asset and ITOM work: queries plus asset writes checked against the instance (`manage_asset`). Add-ons by comma: `scripting`, `office_files`, `debug_window`, `source_sync` (`MCP_TOOL_PACKAGE=asset_manager,office_files`) |

> **Max tokens** is the approximate footprint each package's tool schemas add to the model's context per request (tiktoken `cl100k_base` over the server's compacted schemas; actual Claude counts vary slightly). Prefer the narrowest package to keep context and cost down. **This is the maximum**, not a typical cost: it is paid in full only by clients that load every tool schema up front. Clients with deferred tool loading (e.g. Claude Code's tool search) load a schema only when that tool is used, so their real per-request cost is far lower. Tool counts are package members; every package also carries `list_tool_packages`, and a multi-instance setup adds `list_instances`, `compare_instances` and an `instance` parameter on every tool — the second token column measures that with three instances. Figures are measured with tiktoken, not estimated (`uv run --no-sync --with tiktoken python scripts/measure_tool_tokens.py <package>` lists every tool's share).

All packages except `core` and `none` inherit `standard` read-only tools via `_extends`. See `config/tool_packages.yaml` for the full inheritance tree. `asset_manager`, `itsm_developer` and the add-ons do not extend anything: a session pays only for the tools it asked for.

---

:::danger[⚠️  Any package above `standard` is an advanced, write-capable option]
`service_desk`, `portal_developer`, `platform_developer`, and `full` all activate write tools — an AI
agent running under them can create, update, and delete ServiceNow records. `full` does so across **every
domain simultaneously** (incidents, changes, portal, Flow Designer, workflows, scripts, and more), so one
misunderstood prompt or hallucination can trigger destructive changes across multiple areas at once.

**Do not opt up from `standard` unless:**
- You understand every write tool the package activates (see [Tool Inventory](../TOOL_INVENTORY/))
- You are working in a **non-production** or **sandboxed** instance, or have `allow_writes` gating in place
- You are an experienced ServiceNow developer who knows how to recover from unintended changes

If you're unsure, stay on the read-only default `standard` and pick the narrowest write package only when a task truly needs it.
:::
---

## Setting the package

Via environment variable (recommended):

```bash
MCP_TOOL_PACKAGE=standard
```

Via CLI flag:

```bash
servicenow-mcp --tool-package standard --instance-url ...
```

In your MCP client config:

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "standard"
  }
}
```

---

## What happens when a tool isn't in your package

If you call a tool that isn't active in your current package, the server returns a clear error:

```
Tool 'manage_widget' is not available in package 'standard'.
Enable package 'portal_developer' or higher to use this tool.
```

No silent failures — the LLM knows exactly which package to request.

---

## Full tool list

For the complete list of all 82 tools by category and package membership, see [Tool Inventory](../TOOL_INVENTORY/).
