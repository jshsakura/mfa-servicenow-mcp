# Tool Packages — Advanced Reference

> **Most users don't need this page.** The default package is `standard` — read-only, safe for any environment.
> Only read on if you need write tools beyond what `standard` provides.

---

## Choosing a package

Start with the narrowest package that covers your work. Each step up adds write access to more domains:

Read-only — safe for any environment, no write tools:

| Package | Tools | ~Tokens | When to use |
| :--- | :---: | :---: | :--- |
| `core` | 12 | ~3.0K | Minimal read-only: health, schema, discovery, key artifact lookups only |
| `standard` | 30 | ~7.3K | **(Default)** Read-only across incidents, changes, portal, logs, and source analysis |
| `none` | 0 | 0 | Intentionally disable all tools (testing, locked-down environments) |

⚠️ Write-capable — **advanced options** that grant create/update/delete:

| Package | Tools | ~Tokens | When to use |
| :--- | :---: | :---: | :--- |
| `service_desk` | 32 | ~8.2K | ⚠️ Service desk agents who need to update/close incidents and changes |
| `portal_developer` | 42 | ~10.6K | ⚠️ Portal developers who deploy widgets, changesets, and script includes |
| `platform_developer` | 42 | ~10.8K | ⚠️ Platform engineers who manage workflows, Flow Designer, and scripts |
| `full` | 56 | ~13.8K | ⚠️ Most advanced — all write tools across all domains at once (see warning below) |

> **~Tokens** is the approximate footprint each package's tool schemas add to the model's context per request (tiktoken `cl100k_base` over the server's compacted schemas; actual Claude counts vary slightly). Prefer the narrowest package to keep context and cost down.

All packages except `core` and `none` inherit `standard` read-only tools via `_extends`. See `config/tool_packages.yaml` for the full inheritance tree.

---

!!! danger "⚠️  Any package above `standard` is an advanced, write-capable option"
    `service_desk`, `portal_developer`, `platform_developer`, and `full` all activate write tools — an AI
    agent running under them can create, update, and delete ServiceNow records. `full` does so across **every
    domain simultaneously** (incidents, changes, portal, Flow Designer, workflows, scripts, and more), so one
    misunderstood prompt or hallucination can trigger destructive changes across multiple areas at once.

    **Do not opt up from `standard` unless:**
    - You understand every write tool the package activates (see [Tool Inventory](TOOL_INVENTORY.md))
    - You are working in a **non-production** or **sandboxed** instance, or have `allow_writes` gating in place
    - You are an experienced ServiceNow developer who knows how to recover from unintended changes

    If you're unsure, stay on the read-only default `standard` and pick the narrowest write package only when a task truly needs it.

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

For the complete list of all 73 tools by category and package membership, see [Tool Inventory](TOOL_INVENTORY.md).
