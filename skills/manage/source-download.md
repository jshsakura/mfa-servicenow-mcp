---
name: source-download
description: Export portal sources to local files for offline review or version control
context_cost: high
safety_level: none
delegatable: true
required_input: widget_ids or scope
output: files
tools:
  - download_portal_sources
triggers:
  - "소스 내보내기"
  - "다운로드"
  - "소스 백업"
  - "download sources"
  - "export widget code"
  - "back up portal"
---

# Instructions

You are exporting Service Portal source code to local files.

## Pipeline

IF specific widgets:
  CALL download_portal_sources
    - widget_ids = INPUT_LIST
    - include_linked_angular_providers = true
    - include_linked_script_includes = true

IF entire scope:
  CALL download_portal_sources
    - scope = INPUT_SCOPE
    - max_widgets = 100
    - include_widget_template = true
    - include_widget_server_script = true
    - include_widget_client_script = true
    - include_widget_link_script = true
    - include_widget_css = true
    - include_linked_angular_providers = true
    - include_linked_script_includes = true

→ RETURN: file count and output path

## Output Structure

```
<scope>/sp_widget/<id>/
  _widget.json, template.html, script.js, client_script.js, css.scss
<scope>/sp_angular_provider/<name>.script.js
<scope>/sys_script_include/<name>.script.js
```

## ON ERROR

- 0 widgets → wrong scope or no widgets in scope
- Permission denied → check output_dir

## DELEGATE hint

Delegatable. Large I/O operation, minimal context needed.
