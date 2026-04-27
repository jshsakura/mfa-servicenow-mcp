# Tool Packages — Advanced Reference

> **Most users don't need this page.** The default package is `standard` — read-only, safe for any environment.
> Only read on if you need write tools beyond what `standard` provides.

---

## Choosing a package

Start with the narrowest package that covers your work. Each step up adds write access to more domains:

| Package | Tools | When to use |
| :--- | :---: | :--- |
| `core` | 15 | Minimal read-only: health, schema, discovery, key artifact lookups only |
| `standard` | 45 | **(Default)** Read-only across incidents, changes, portal, logs, and source analysis |
| `service_desk` | 46 | Service desk agents who need to update/close incidents and changes |
| `portal_developer` | 55 | Portal developers who deploy widgets, changesets, and script includes |
| `platform_developer` | 55 | Platform engineers who manage workflows, Flow Designer, and scripts |
| `full` | 66 | ⚠️ See warning below |
| `none` | 0 | Intentionally disable all tools (testing, locked-down environments) |

All packages except `core` and `none` inherit `standard` read-only tools via `_extends`. See `config/tool_packages.yaml` for the full inheritance tree.

---

!!! danger "⚠️  `full` is for experienced users only"
    The `full` package exposes **all write tools across every domain simultaneously** — incidents, changes,
    portal, Flow Designer, workflows, scripts, and more.

    An AI agent running under `full` can create, update, and delete records without any domain-level guard rails.
    One misunderstood prompt or hallucination can trigger destructive changes across multiple areas at once.

    **Do not use `full` unless:**
    - You fully understand every write tool it activates (see [Tool Inventory](TOOL_INVENTORY.md))
    - You are working in a **non-production** or **sandboxed** instance
    - You are an experienced ServiceNow developer who knows how to recover from unintended changes

    If you're unsure, pick the domain-specific package instead (`portal_developer`, `platform_developer`, etc.).

---

## Setting the package

Via environment variable (recommended):

```bash
MCP_TOOL_PACKAGE=portal_developer
```

Via CLI flag:

```bash
servicenow-mcp --tool-package portal_developer --instance-url ...
```

In your MCP client config:

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "portal_developer"
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

For the complete list of all 77 tools by category and package membership, see [Tool Inventory](TOOL_INVENTORY.md).
