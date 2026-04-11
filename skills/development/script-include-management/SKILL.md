---
name: script-include-management
version: 1.0.0
description: Manage script includes — list, read, create, update, execute client-callable methods via GlideAjax
author: jshsakura
tags: [development, script-include, glideajax, server-side]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - list_script_includes
    - get_script_include
    - create_script_include
    - update_script_include
    - execute_script_include
    - delete_script_include
complexity: beginner
estimated_time: 5-10 minutes
---

# Script Include Management

## Overview

Full lifecycle management of ServiceNow Script Includes — search, read source code, create new ones, update existing, and execute client-callable methods.

**When to use:**
- "Show me all active script includes in this scope"
- "Read the source of MyUtil script include"
- "Create a new client-callable script include"
- "Execute a GlideAjax method and get the result"

## Prerequisites

- **Roles:** `admin` or scoped app developer for write operations; read access for queries
- **MCP Package:** `standard` (read), `portal_developer` or higher (write)

## Procedure

### List Script Includes

```
Tool: list_script_includes
Parameters:
  query: "MyApp"
  active: true
  client_callable: true
  limit: 20
```

For count only (faster):
```
Tool: list_script_includes
Parameters:
  query: "MyApp"
  count_only: true
```

### Read Source Code

```
Tool: get_script_include
Parameters:
  script_include_id: "MyAjaxUtil"
```

Also accepts `sys_id:` prefix for sys_id lookup:
```
  script_include_id: "sys_id:abc123def456"
```

### Create New Script Include

```
Tool: create_script_include
Parameters:
  name: "MyNewUtil"
  script: "var MyNewUtil = Class.create();\nMyNewUtil.prototype = {\n  initialize: function() {},\n  doSomething: function() {\n    return 'result';\n  },\n  type: 'MyNewUtil'\n};"
  description: "Utility for processing data"
  client_callable: true
  active: true
  confirm: "approve"
```

### Update Existing

```
Tool: update_script_include
Parameters:
  script_include_id: "MyNewUtil"
  script: "<updated script content>"
  description: "Updated description"
  confirm: "approve"
```

### Execute Client-Callable Method

```
Tool: execute_script_include
Parameters:
  name: "MyAjaxUtil"
  method: "getResult"
  params:
    input_value: "test123"
  confirm: "approve"
```

This calls the script include via GlideAjax REST endpoint. The script include must have `client_callable: true`.

## Tips

- Use `list_script_includes` with `count_only: true` for quick inventory checks
- `get_script_include` returns the full script body — pipe it into code review
- `execute_script_include` is the only way to test GlideAjax methods without a browser
- Write operations require `confirm: "approve"` — this is a safety feature, not a bug
