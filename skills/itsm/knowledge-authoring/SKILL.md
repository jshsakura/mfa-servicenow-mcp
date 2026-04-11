---
name: knowledge-authoring
version: 1.0.0
description: Create, organize, and publish knowledge base articles from incident resolutions or new documentation needs
author: jshsakura
tags: [itsm, knowledge, kb, article, documentation]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - list_knowledge_bases
    - create_knowledge_base
    - list_categories
    - create_category
    - list_articles
    - get_article
    - create_article
    - update_article
    - publish_article
complexity: beginner
estimated_time: 5-10 minutes
---

# Knowledge Authoring

## Overview

Create and manage knowledge base articles — organize into categories, draft content, review, and publish.

**When to use:**
- "Create a KB article from this incident resolution"
- "Document the portal widget deployment process"
- "List all draft articles"
- "Publish this article"

## Prerequisites

- **Roles:** `knowledge` or `knowledge_manager`
- **MCP Package:** `full` (knowledge tools are in full package)

## Procedure

### Step 1: Find or Create Knowledge Base

```
Tool: list_knowledge_bases
Parameters:
  limit: 10
```

If needed, create a new one:
```
Tool: create_knowledge_base
Parameters:
  title: "Portal Development Guide"
  description: "Knowledge base for Service Portal development procedures"
  confirm: "approve"
```

### Step 2: Organize Categories

```
Tool: list_categories
Parameters:
  knowledge_base_id: "<kb sys_id>"
```

Create a category if needed:
```
Tool: create_category
Parameters:
  knowledge_base_id: "<kb sys_id>"
  label: "Widget Development"
  description: "Guides for Service Portal widget development"
  confirm: "approve"
```

### Step 3: Create Article

```
Tool: create_article
Parameters:
  knowledge_base_id: "<kb sys_id>"
  category_id: "<category sys_id>"
  short_description: "How to add company code branches to portal widgets"
  text: "<article body in HTML>"
  confirm: "approve"
```

**Article body template:**
```html
<h2>Symptoms</h2>
<p>Widget does not display correct content for company code 2J00.</p>

<h2>Cause</h2>
<p>The client_script conditional logic handles 2400 and 5K00 but not 2J00.</p>

<h2>Resolution</h2>
<ol>
  <li>Use the <code>code-detection</code> skill to find missing branches</li>
  <li>Use the <code>widget-patching</code> skill to apply the fix</li>
  <li>Create a changeset and deploy</li>
</ol>

<h2>Related</h2>
<p>See also: Portal Diagnosis skill for comprehensive widget audits.</p>
```

### Step 4: Review and Publish

```
Tool: get_article
Parameters:
  article_id: "<article sys_id>"
```

Review content, then publish:
```
Tool: publish_article
Parameters:
  article_id: "<article sys_id>"
  confirm: "approve"
```

## Tips

- Structure articles with Symptoms → Cause → Resolution for consistency
- Reference other skills in articles — they serve as runbooks
- Create articles from resolved incidents — capture institutional knowledge before it's forgotten
- Use `list_articles` with query to check for duplicates before creating
