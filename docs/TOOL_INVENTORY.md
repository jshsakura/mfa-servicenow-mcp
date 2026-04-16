# ServiceNow MCP - Tool Inventory

Registered tools: **154**

## Package Summary

| Package | Tools | Description |
|---------|-------|-------------|
| `none` | 0 | Disabled |
| `standard` | 36 | Read-only safe mode **(default)** |
| `service_desk` | 46 | standard + Incident/Change writes |
| `portal_developer` | 85 | standard + Portal/Source/Changeset domain |
| `platform_developer` | 79 | standard + Workflow/Flow/Script/ITSM writes |
| `agile` | 51 | standard + Epic/Story/Scrum/Project PPM |
| `admin` | 61 | standard + User/Knowledge/Catalog management |
| `full` | 114 | All development tools (excludes Agile PPM and Admin) |

## Tools by Category

### Agile - Epic (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_epic` | W | Create an epic (rm_epic). Requires short_description. Optional: priority, state,... | `agile` |
| `list_epics` | R | List epics with optional state/assignment_group/query filters. | `agile` |
| `update_epic` | W | Update an epic by sys_id. Supports description, priority, state, and assignment ... | `agile` |

### Agile - Project (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_project` | W | Create a project (pm_project). Requires short_description. Optional: start/end d... | `agile` |
| `list_projects` | R | List projects with optional state/assignment_group/query filters. | `agile` |
| `update_project` | W | Update a project by sys_id. Supports description, dates, state, and assignment f... | `agile` |

### Agile - Scrum Task (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_scrum_task` | W | Create a scrum task (rm_scrum_task). Requires short_description and story. Optio... | `agile` |
| `list_scrum_tasks` | R | List scrum tasks with optional story/sprint/state filters. | `agile` |
| `update_scrum_task` | W | Update a scrum task by sys_id. Supports state, hours, assigned_to, and work_note... | `agile` |

### Agile - Story (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_story` | W | Create a story (rm_story). Requires short_description. Optional: points, sprint,... | `agile` |
| `create_story_dependency` | W | Create a blocking dependency between two stories. Requires parent and child stor... | `agile` |
| `delete_story_dependency` | W | Delete a story dependency by sys_id. Irreversible. | `agile` |
| `list_stories` | R | List stories with optional sprint/epic/state/assignment filters. | `agile` |
| `list_story_dependencies` | R | List story dependencies. Returns blocking/blocked-by relationships with story de... | `agile` |
| `update_story` | W | Update a story by sys_id. Supports points, sprint, state, and assignment fields. | `agile` |

### Catalog Optimization (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_optimization_recommendations` | R | Analyze catalog structure — find inactive items and items with poor descriptions... | `admin` |
| `update_catalog_item` | W | Update a catalog item by sys_id. Partial field update. | `admin` |

### Catalog Variables (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_catalog_item_variable` | W | Add a form variable to a catalog item. Requires cat_item sys_id, variable type, ... | `admin` |
| `list_catalog_item_variables` | R | List variable definitions for a catalog item. Returns type, order, mandatory fla... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `update_catalog_item_variable` | W | Update a catalog variable by sys_id. Partial field update. | `admin` |

### Change Audit (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | Audit pending update set changes — inventory by type, risk patterns, clones, and... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |

### Change Management (7)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_change_task` | W | Create a change_task under a change request. Requires change_id and short_descri... | `service_desk`, `platform_developer`, `full` |
| `approve_change` | W | Approve a change request and transition its state to implement. Requires change_... | `service_desk`, `platform_developer`, `full` |
| `create_change_request` | W | Create a change request. Requires short_description and type (normal/standard/em... | `service_desk`, `platform_developer`, `full` |
| `get_change_request_details` | R | Get a single change request by sys_id/number, or list change requests with filte... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `reject_change` | W | Reject a change request and transition its state to canceled. Requires change_id... | `service_desk`, `platform_developer`, `full` |
| `submit_change_for_approval` | W | Transition a change request to assess state and create an approval record. Requi... | `service_desk`, `platform_developer`, `full` |
| `update_change_request` | W | Update a change request by sys_id. Supports state, description, risk, impact, da... | `service_desk`, `platform_developer`, `full` |

### Changeset (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_file_to_changeset` | W | Attach a record (file path + content) to an update set. | `portal_developer`, `platform_developer`, `full` |
| `commit_changeset` | W | Finalize an update set by marking it complete. Prevents further edits. | `portal_developer`, `platform_developer`, `full` |
| `create_changeset` | W | Create a new update set. Returns the new sys_id on success. | `portal_developer`, `platform_developer`, `full` |
| `get_changeset_details` | R | Get a single update set by sys_id with entries, or list update sets with filters... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `publish_changeset` | W | Deploy a committed update set to the target instance. | `portal_developer`, `platform_developer`, `full` |
| `update_changeset` | W | Update an existing update set's name, description, state, or developer. | `portal_developer`, `platform_developer`, `full` |

### Core API (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `sn_aggregate` | R | Run COUNT/SUM/AVG/MIN/MAX on any table with optional group_by. Returns stats wit... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `sn_discover` | R | Find tables by name or label keyword. Returns table name, label, scope, and pare... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `sn_health` | R | Check ServiceNow API connectivity and auth status. Triggers browser login on fir... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `sn_nl` | R | Convert natural language to sn_query/sn_schema/sn_aggregate calls. Parses intent... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `sn_query` | R | Query any ServiceNow table with encoded query filters. Use as fallback when no s... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `sn_schema` | R | Fetch field names, types, labels, and constraints from sys_dictionary for a give... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |

### Detection (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `detect_missing_profit_company_codes` | R | Detect missing profit_company_code branch values in widget/provider conditional ... | `portal_developer`, `full` |

### Flow Designer (7)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `activate_flow_designer` | W | Set a Flow Designer flow to active state by sys_id. | `platform_developer`, `full` |
| `deactivate_flow_designer` | W | Set a Flow Designer flow to inactive state by sys_id. | `platform_developer`, `full` |
| `get_flow_designer_detail` | R | Get a single Flow Designer flow by sys_id. Optionally include structure tree and... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_flow_designer_executions` | R | Get flow execution history or single execution detail. Filter by name, state, or... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_flow_designers` | R | List Flow Designer flows with optional filters. Returns name, status, scope, and... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_flow_triggers_by_table` | R | Find flow triggers for a given table. Returns triggers with linked flow info. An... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `update_flow_designer` | W | Update a Flow Designer flow name, description, or active status by sys_id. | `platform_developer`, `full` |

### Incident Management (5)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_comment` | W | Add a work note (internal) or customer-visible comment to an incident by sys_id ... | `service_desk`, `platform_developer`, `full` |
| `create_incident` | W | Create a new incident (short_description required). Returns sys_id and INC numbe... | `service_desk`, `platform_developer`, `full` |
| `get_incident_by_number` | R | Get a single incident by number, or list incidents with filters. Provide inciden... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `resolve_incident` | W | Set incident to Resolved state. Requires resolution_code and close_notes. Use up... | `service_desk`, `platform_developer`, `full` |
| `update_incident` | W | Update an incident by sys_id or INC number with partial field changes. Accepts a... | `service_desk`, `platform_developer`, `full` |

### Knowledge Base (9)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_article` | W | Create a KB article. Requires kb_id, short_description, and text. | `admin` |
| `create_category` | W | Create a KB category under a knowledge base. Requires kb_id and label. | `admin` |
| `create_knowledge_base` | W | Create a knowledge base (kb_knowledge_base). Requires title. Returns sys_id. | `admin` |
| `get_article` | R | Get a KB article by sys_id. Returns full text and metadata. | `admin` |
| `list_articles` | R | List KB articles with optional kb/category/query filters. | `admin` |
| `list_categories` | R | List categories in a KB with optional active/query filters. | `admin` |
| `list_knowledge_bases` | R | List knowledge bases with optional active/query filters. | `admin` |
| `publish_article` | W | Publish a KB article by sys_id. Sets workflow_state to published. | `admin` |
| `update_article` | W | Update a KB article by sys_id. Supports title, text, category, and workflow_stat... | `admin` |

### Local Sync (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `diff_local_component` | R | Compare local source files against remote ServiceNow. Returns diffs and status s... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `update_remote_from_local` | W | Push local file changes to ServiceNow. Auto-snapshots remote state before push f... | `portal_developer`, `platform_developer`, `full` |

### Logs (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_logs` | R | Query ServiceNow logs. log_type: system (script errors, gs.log), journal (work n... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |

### Performance (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | Analyze widget performance — code patterns, transaction logs, provider usage. Re... | `portal_developer`, `full` |

### Portal Analysis (14)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | W | Analyze a proposed portal component edit and return bounded risk and field-chang... | `portal_developer`, `full` |
| `create_portal_component_snapshot` | W | Save the current editable state of a portal component to a local snapshot file f... | `portal_developer`, `full` |
| `detect_angular_implicit_globals` | R | Detect undeclared variable assignments in Angular provider scripts that cause ru... | `portal_developer`, `full` |
| `download_portal_sources` | R | Export widget, provider, and SI sources to local files. Filter by scope or widge... | `portal_developer`, `full` |
| `get_portal_component_code` | R | Fetch one or more code fields from a widget/provider/SI. Lighter than get_widget... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_widget_bundle` | R | Fetch full widget bundle (HTML, scripts, providers) in one call. Use as analysis... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `preview_portal_component_update` | W | Preview bounded before/after snippets and diff for a proposed portal component e... | `portal_developer`, `full` |
| `resolve_page_dependencies` | W | Resolve ALL widgets on a page with full dependency chains in one call. Deduplica... | `portal_developer`, `full` |
| `resolve_widget_chain` | W | Deep-resolve a widget's full dependency chain with source code. Returns widget s... | `portal_developer`, `full` |
| `route_portal_component_edit` | W | Route a portal edit instruction to the right analyze/preview/apply tool. | `portal_developer`, `full` |
| `search_portal_regex_matches` | R | Regex search across widget sources (HTML/scripts/providers). Supports minimal, c... | `portal_developer`, `full` |
| `trace_portal_route_targets` | R | Map widget→provider→route relationships. Metadata only, no script bodies. | `portal_developer`, `full` |
| `update_portal_component` | W | Update specific code fields (HTML, CSS, or script) of a widget, provider, or scr... | `portal_developer`, `full` |
| `update_portal_component_from_snapshot` | W | Restore a portal component's editable fields from a previously saved local snaps... | `portal_developer`, `full` |

### Portal CRUD (12)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_angular_provider` | W | Create an AngularJS 1.x angular provider (factory/service/directive). Scope is r... | `portal_developer`, `full` |
| `create_column` | W | Add a column to a row. Columns use Bootstrap grid (size 1-12). Widgets are place... | `portal_developer`, `full` |
| `create_container` | W | Add a layout container to a portal page. Containers hold rows. | `portal_developer`, `full` |
| `create_css_theme` | W | Create a Service Portal CSS theme (sp_css). Scope is required. | `portal_developer`, `full` |
| `create_header_footer` | W | Create a Service Portal header or footer component. Scope is required. | `portal_developer`, `full` |
| `create_ng_template` | W | Create an AngularJS ng-template (sp_ng_template) for use in ng-include. Scope is... | `portal_developer`, `full` |
| `create_page` | W | Create a new Service Portal page. Scope is required. Returns sys_id for subseque... | `portal_developer`, `full` |
| `create_row` | W | Add a row to a layout container. Rows hold columns. | `portal_developer`, `full` |
| `create_ui_page` | W | Create a UI Page (sys_ui_page) with HTML, client script, and processing script. ... | `portal_developer`, `full` |
| `create_widget` | W | Create a new Service Portal widget with template, scripts, and CSS. Scope is req... | `portal_developer`, `full` |
| `scaffold_page` | W | Create a complete portal page with layout (container/rows/columns) and widget pl... | `portal_developer`, `full` |
| `update_page` | W | Update a Service Portal page's title, description, CSS, or visibility flags. | `portal_developer`, `full` |

### Portal Developer (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_developer_changes` | R | List a developer's recent changes across portal tables (widgets, providers, SI).... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_developer_daily_summary` | R | Generate a developer's daily work summary for Jira/Confluence. Returns line coun... | `portal_developer`, `full` |
| `get_provider_dependency_map` | R | Build widget-to-provider-to-script-include dependency graph. Returns metadata on... | `portal_developer`, `full` |
| `get_uncommitted_changes` | R | List uncommitted update set entries for a developer. Returns entry type and targ... | `portal_developer`, `full` |

### Portal Management (5)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_widget_instance` | W | Place a widget on a portal page column with order and config. | `portal_developer`, `full` |
| `get_page` | R | Get or list portal pages by URL path, title, or sys_id. Returns layout tree with... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_portal` | R | Get or list Service Portals by name, URL suffix, or sys_id. Returns config, home... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_widget_instance` | R | Get widget instance placement on a page. Returns column, order, and config. Filt... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `update_widget_instance` | W | Move, reorder, or update options/CSS of an existing widget instance on a page. | `portal_developer`, `full` |

### Repository (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | Combined git report: working tree status + recent commits + per-file last modifi... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_repo_file_last_modifier` | R | Lookup per-file last modifier and commit metadata with optional uncommitted stat... | `full` |
| `get_repo_recent_commits` | R | List recent commits with author and optional changed file lists | `full` |
| `get_repo_working_tree_status` | R | Inspect working tree status including staged, unstaged, and untracked files | `full` |

### Script Include (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_script_include` | W | Create a script include with name, script, api_name, and client_callable fields.... | `portal_developer`, `platform_developer`, `full` |
| `delete_script_include` | W | Permanently delete a script include by sys_id or name. Irreversible. | `platform_developer`, `full` |
| `execute_script_include` | W | Execute a client-callable SI method via GlideAjax REST. | `platform_developer`, `full` |
| `get_script_include` | R | Retrieve a single script include with full script body by sys_id or name. | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_script_includes` | R | List script includes filtered by name/scope/active. Returns metadata without scr... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `update_script_include` | W | Update a script include's script, api_name, client_callable, or other fields by ... | `portal_developer`, `platform_developer`, `full` |

### Service Catalog (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_catalog_category` | W | Create a catalog category. Requires title. Optionally set parent, icon, order, a... | `admin` |
| `get_catalog_item` | R | Fetch a single catalog item by sys_id. Returns full details including variables. | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_catalog_categories` | R | List catalog categories with parent/child relationships. Filter by active status... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_catalog_items` | R | Search catalog items with optional category/active filters. Returns name, price,... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `move_catalog_items` | W | Reassign one or more catalog items to a target category. Requires item_ids and t... | `admin` |
| `update_catalog_category` | W | Partial update of a catalog category by sys_id. Supports title, parent, icon, or... | `admin` |

### Source & Download (12)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `download_admin_scripts` | R | Download Fix Scripts, Scheduled Jobs, Script Actions, and Email Notifications fo... | `portal_developer`, `platform_developer`, `full` |
| `download_api_sources` | R | Download Scripted REST API operations and Processors for a scope. | `portal_developer`, `platform_developer`, `full` |
| `download_app_sources` | R | Orchestrator: download ALL source code for an application scope. Calls download_... | `portal_developer`, `platform_developer`, `full` |
| `download_script_includes` | R | Download all Script Includes for a scope to local files. | `portal_developer`, `platform_developer`, `full` |
| `download_security_sources` | R | Download ACL rules for a scope. By default only ACLs with scripts. | `portal_developer`, `platform_developer`, `full` |
| `download_server_scripts` | R | Download Business Rules, Client Scripts, and Catalog Client Scripts for a scope. | `portal_developer`, `platform_developer`, `full` |
| `download_table_schema` | R | Download sys_dictionary field definitions for ServiceNow tables. Specify table n... | `portal_developer`, `platform_developer`, `full` |
| `download_ui_components` | R | Download UI Actions, UI Scripts, UI Pages, and UI Macros for a scope. | `portal_developer`, `platform_developer`, `full` |
| `extract_table_dependencies` | R | Build a GlideRecord table dependency graph from server scripts. Scans SI, BR, an... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `extract_widget_table_dependencies` | R | Build a table dependency graph for a single widget, optionally expanding linked ... | `portal_developer`, `full` |
| `get_metadata_source` | R | Get a single source record (SI, BR, widget, etc.) by name or sys_id. Returns met... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `search_server_code` | R | Search across 22 server-side source types (SI, BR, widget, ACL, etc.) by keyword... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |

### Source Audit (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_local_sources` | R | Analyze downloaded app sources locally (NO API calls). Generates cross-reference... | `portal_developer`, `platform_developer`, `full` |

### UI Policy (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_ui_policy` | W | Create a form field behavior rule (show/hide/mandatory) triggered by encoded que... | `platform_developer`, `full` |
| `create_ui_policy_action` | W | Add a field-level action to a UI policy: set visibility, mandatory, or read-only... | `platform_developer`, `full` |

### User & Group Management (9)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_group_members` | W | Add one or more users to a group. Requires group sys_id and user sys_ids. | `admin` |
| `create_group` | W | Create a group (sys_user_group). Requires name. Optional: manager, description, ... | `admin` |
| `create_user` | W | Create a user (sys_user). Requires user_name. Optional: email, first/last name, ... | `admin` |
| `get_user` | R | Get a user by sys_id or user_name. Returns profile, roles, and group memberships... | `admin` |
| `list_groups` | R | List groups with optional name/type/active filters. Returns group details and me... | `admin` |
| `list_users` | R | List users with optional name/email/department/active filters. | `admin` |
| `remove_group_members` | W | Remove one or more users from a group. Requires group sys_id and user sys_ids. | `admin` |
| `update_group` | W | Update a group by sys_id. Supports name, manager, description, and active fields... | `admin` |
| `update_user` | W | Update a user by sys_id. Supports name, email, active, department, and role fiel... | `admin` |

### Workflow Engine (13)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `activate_workflow` | W | Set a workflow to active state by sys_id. Returns updated workflow record. | `platform_developer`, `full` |
| `add_workflow_activity` | W | Add an activity (approval, task, notification, etc.) to a workflow version. | `platform_developer`, `full` |
| `create_workflow` | W | Create a workflow with name, table, description, and active flag. Returns create... | `platform_developer`, `full` |
| `deactivate_workflow` | W | Set a workflow to inactive state by sys_id. Returns updated workflow record. | `platform_developer`, `full` |
| `delete_workflow` | W | Delete a workflow by sys_id. Irreversible. | `platform_developer`, `full` |
| `delete_workflow_activity` | W | Remove an activity from a workflow by activity sys_id. Irreversible. | `platform_developer`, `full` |
| `get_workflow_activities` | R | Get ordered activity list for a workflow. Uses latest published version unless v... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `get_workflow_details` | R | Get a workflow (wf_workflow engine) by sys_id. Optionally include version histor... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_workflow_versions` | R | List version history for a workflow (wf_workflow_version). Shows version number,... | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `list_workflows` | R | List workflows (wf_workflow engine) with optional name/table/active filters. | `standard`, `service_desk`, `portal_developer`, `platform_developer`, `agile`, `admin`, `full` |
| `reorder_workflow_activities` | W | Reorder workflow activities by providing activity sys_ids in desired sequence. | `platform_developer`, `full` |
| `update_workflow` | W | Update workflow name, description, table, or active status by sys_id. | `platform_developer`, `full` |
| `update_workflow_activity` | W | Update activity name, description, or attributes by activity sys_id. | `platform_developer`, `full` |

