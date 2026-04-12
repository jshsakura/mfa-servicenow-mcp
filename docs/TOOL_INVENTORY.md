# ServiceNow MCP - Tool Inventory

Active tools: **95** | Registered in code: **133** | Removed from packages: **38**

## Package Summary

| Package | Tools | Default | Description |
|---------|-------|---------|-------------|
| `none` | 0 |  | Disabled |
| `standard` | 51 | Y | Read-only safe mode |
| `portal_developer` | 67 |  | Portal/Widget development |
| `platform_developer` | 75 |  | Backend/Workflow development |
| `service_desk` | 55 |  | Incident operations |
| `full` | 95 |  | All capabilities |

## Tools by Category

### Agile - Epic (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_epic` | W | Create a new epic in ServiceNow... | *(none)* |
| `list_epics` | R | List epics from ServiceNow... | *(none)* |
| `update_epic` | W | Update an existing epic in ServiceNow... | *(none)* |

### Agile - Project (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_project` | W | Create a new project in ServiceNow... | *(none)* |
| `list_projects` | R | List projects from ServiceNow... | *(none)* |
| `update_project` | W | Update an existing project in ServiceNow... | *(none)* |

### Agile - Scrum Task (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_scrum_task` | W | Create a new scrum task in ServiceNow... | *(none)* |
| `list_scrum_tasks` | R | List scrum tasks from ServiceNow... | *(none)* |
| `update_scrum_task` | W | Update an existing scrum task in ServiceNow... | *(none)* |

### Agile - Story (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_story` | W | Create a new story in ServiceNow... | *(none)* |
| `create_story_dependency` | W | Create a dependency between two stories in ServiceNow... | *(none)* |
| `delete_story_dependency` | W | Delete a story dependency in ServiceNow... | *(none)* |
| `list_stories` | R | List stories from ServiceNow... | *(none)* |
| `list_story_dependencies` | R | List story dependencies from ServiceNow... | *(none)* |
| `update_story` | W | Update an existing story in ServiceNow... | *(none)* |

### Audit (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | Audit a developer's pending update set changes in one call. Returns inventory gr... | full, platform_developer, portal_developer, service_desk, standard |

### Catalog (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_catalog_category` | W | Create a catalog category. Requires title. Optionally set parent, icon, order, a... | full |
| `get_catalog_item` | R | Fetch a single catalog item by sys_id. Returns full details including variables.... | full, platform_developer, portal_developer, service_desk, standard |
| `list_catalog_categories` | R | List catalog categories with parent/child relationships. Filter by active status... | full, platform_developer, portal_developer, service_desk, standard |
| `list_catalog_items` | R | Search catalog items with optional category/active filters. Returns name, price,... | full, platform_developer, portal_developer, service_desk, standard |
| `move_catalog_items` | W | Reassign one or more catalog items to a target category. Requires item_ids and t... | full |
| `update_catalog_category` | W | Partial update of a catalog category by sys_id. Supports title, parent, icon, or... | full |

### Catalog Optimization (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_optimization_recommendations` | R | Analyze catalog structure and suggest improvements (inactive items, low usage, a... | full, platform_developer, portal_developer, service_desk, standard |
| `update_catalog_item` | W | Partial update of a catalog item by sys_id. Supports name, description, category... | full |

### Catalog Variables (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_catalog_item_variable` | W | Add a form variable to a catalog item. Requires cat_item sys_id, variable type, ... | full |
| `list_catalog_item_variables` | R | List variable definitions for a catalog item. Returns type, order, mandatory fla... | full, platform_developer, portal_developer, service_desk, standard |
| `update_catalog_item_variable` | W | Partial update of a catalog item variable by sys_id. Supports label, order, mand... | full |

### Change Management (8)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_change_task` | W | Create a change_task under a change request. Requires change_id and short_descri... | full |
| `approve_change` | W | Approve a change request and transition its state to implement. Requires change_... | full |
| `create_change_request` | W | Create a change request. Requires short_description and type (normal/standard/em... | full |
| `get_change_request_details` | R | Fetch a single change request by sys_id or number. Returns full details includin... | full, platform_developer, portal_developer, service_desk, standard |
| `list_change_requests` | R | Search change requests with filters for state, type, assignment group, and timef... | full, platform_developer, portal_developer, service_desk, standard |
| `reject_change` | W | Reject a change request and transition its state to canceled. Requires change_id... | full |
| `submit_change_for_approval` | W | Transition a change request to assess state and create an approval record. Requi... | full, platform_developer |
| `update_change_request` | W | Update a change request by sys_id. Supports state, description, risk, impact, da... | full, platform_developer |

### Changeset (7)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_file_to_changeset` | W | Attach a record (file path + content) to an update set.... | full, platform_developer, portal_developer |
| `commit_changeset` | W | Finalize an update set by marking it complete. Prevents further edits.... | full, platform_developer, portal_developer |
| `create_changeset` | W | Create a new update set. Returns the new sys_id on success.... | full, platform_developer, portal_developer |
| `get_changeset_details` | R | Retrieve a single update set with its entries and metadata by sys_id.... | full, platform_developer, portal_developer, service_desk, standard |
| `list_changesets` | R | List update sets filtered by state/developer/app. Returns name, state, and scope... | full, platform_developer, portal_developer, service_desk, standard |
| `publish_changeset` | W | Deploy a committed update set to the target instance.... | full, platform_developer, portal_developer |
| `update_changeset` | W | Update an existing update set's name, description, state, or developer.... | full, platform_developer, portal_developer |

### Code Detection (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `detect_missing_profit_company_codes` | R | Detect missing profit_company_code branch values in portal widget and provider s... | full, platform_developer, portal_developer, service_desk, standard |

### Core (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `sn_aggregate` | R | Run COUNT/SUM/AVG/MIN/MAX on any table with optional group_by. Returns stats wit... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_discover` | R | Find tables by name or label keyword. Returns table name, label, scope, and pare... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_health` | R | Check ServiceNow API connectivity and auth status. Triggers browser login on fir... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_nl` | R | Convert natural language to query, schema, or aggregate calls. Parses intent and... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_query` | R | Query any ServiceNow table with encoded query filters. Fallback only — prefer sp... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_schema` | R | Fetch field names, types, labels, and constraints from sys_dictionary for a give... | full, platform_developer, portal_developer, service_desk, standard |

### Developer - Repo (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | Combined git report: working tree status + recent commits + per-file last modifi... | full, platform_developer, portal_developer, service_desk, standard |
| `get_repo_file_last_modifier` | R | Lookup per-file last modifier and commit metadata with optional uncommitted stat... | *(none)* |
| `get_repo_recent_commits` | R | List recent commits with author and optional changed file lists... | *(none)* |
| `get_repo_working_tree_status` | R | Inspect working tree status including staged, unstaged, and untracked files... | *(none)* |

### Flow Designer (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `list_flow_designers` | R | List Flow Designer flows with optional filters. Returns flow name, status, activ... | full, platform_developer, portal_developer, service_desk, standard |
| `get_flow_designer_detail` | R | Get flow metadata. Use include_structure=true for action/logic/subflow tree, inc... | full, platform_developer, portal_developer, service_desk, standard |
| `get_flow_designer_executions` | R | Get execution history or single execution detail (provide context_id). Filter by... | full, platform_developer, portal_developer, service_desk, standard |

### Incident (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_comment` | W | Add a work note (internal) or customer-visible comment to an incident by sys_id ... | full, service_desk |
| `create_incident` | W | Create a new incident (short_description required). Returns sys_id and INC numbe... | full, service_desk |
| `get_incident_by_number` | R | Fetch a single incident by INC number with full field details including timestam... | full, platform_developer, portal_developer, service_desk, standard |
| `list_incidents` | R | List incidents with state/category/assignee filters. Returns summary fields only... | full, platform_developer, portal_developer, service_desk, standard |
| `resolve_incident` | W | Set incident state to Resolved with resolution_code and close_notes. Use update_... | full, platform_developer, service_desk |
| `update_incident` | W | Update an incident by sys_id or INC number with partial field changes. Accepts a... | full, platform_developer, service_desk |

### Knowledge Base (9)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_article` | W | Create a new knowledge article... | *(none)* |
| `create_category` | W | Create a new category in a knowledge base... | *(none)* |
| `create_knowledge_base` | W | Create a new knowledge base in ServiceNow... | *(none)* |
| `get_article` | R | Get a specific knowledge article by ID... | *(none)* |
| `list_articles` | R | List knowledge articles... | *(none)* |
| `list_categories` | R | List categories in a knowledge base... | *(none)* |
| `list_knowledge_bases` | R | List knowledge bases from ServiceNow... | *(none)* |
| `publish_article` | W | Publish a knowledge article... | *(none)* |
| `update_article` | W | Update an existing knowledge article... | *(none)* |

### Legacy Workflow (10)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `list_legacy_workflows` | R | List workflows with optional filters by name, table, or active status. Returns s... | full, platform_developer, portal_developer, service_desk, standard |
| `get_legacy_workflow_details` | R | Get workflow metadata. Use include_versions=true for version history, include_act... | full, platform_developer, portal_developer, service_desk, standard |
| `activate_legacy_workflow` | W | Set a workflow to active state by sys_id. Returns updated workflow record.... | full, platform_developer |
| `add_legacy_workflow_activity` | W | Add an activity (approval, task, notification, etc.) to a workflow version.... | full, platform_developer |
| `create_legacy_workflow` | W | Create a workflow with name, table, description, and active flag. Returns create... | full, platform_developer |
| `deactivate_legacy_workflow` | W | Set a workflow to inactive state by sys_id. Returns updated workflow record.... | full, platform_developer |
| `delete_legacy_workflow_activity` | W | Remove an activity from a workflow by activity sys_id. Irreversible.... | full, platform_developer |
| `reorder_legacy_workflow_activities` | W | Reorder workflow activities by providing activity sys_ids in desired sequence.... | full, platform_developer |
| `update_legacy_workflow` | W | Update workflow name, description, table, or active status by sys_id.... | full, platform_developer |
| `update_legacy_workflow_activity` | W | Update activity name, description, or attributes by activity sys_id.... | full, platform_developer |

### Logs (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_background_script_logs` | R | Query sys_execution_tracker for scheduled/background script run logs with state ... | full, platform_developer, portal_developer, service_desk, standard |
| `get_journal_entries` | R | Fetch work notes and comments on any record. Filter by table, record sys_id, or ... | full, platform_developer, portal_developer, service_desk, standard |
| `get_system_logs` | R | Query syslog entries by level/source/message. Hard-capped at 20 rows for safety.... | full, platform_developer, portal_developer, service_desk, standard |
| `get_transaction_logs` | R | Query HTTP transaction logs with URL, status, and duration. Use for request perf... | full, platform_developer, portal_developer, service_desk, standard |

### Performance Analysis (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | Analyze a widget's code patterns, transaction logs, and data provider usage. Ret... | full, platform_developer, portal_developer, service_desk, standard |

### Local Sync (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `diff_local_component` | R | Compare local portal source files against remote ServiceNow. Download root dir f... | full, platform_developer, portal_developer, service_desk, standard |
| `update_remote_from_local` | W | Push local file changes to ServiceNow. Auto-creates snapshot before push. Refuse... | full, platform_developer, portal_developer |

### Portal Dev Utilities (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_developer_changes` | R | List a developer's recent changes across portal tables (widgets, providers, SI, ... | full, platform_developer, portal_developer, service_desk, standard |
| `get_developer_daily_summary` | R | Generate a developer's daily work summary for Jira/Confluence. Returns line coun... | *(none)* |
| `get_provider_dependency_map` | R | Build widget-to-provider-to-script-include dependency graph. Returns metadata on... | full, platform_developer, portal_developer, service_desk, standard |
| `get_uncommitted_changes` | R | List uncommitted update set entries for a developer. Use count_only=true first t... | *(none)* |

### Portal Development (12)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | R | Analyze a proposed portal component edit and return bounded risk and field-chang... | full, portal_developer |
| `create_portal_component_snapshot` | W | Save the current editable state of a portal component to a local snapshot file f... | full, portal_developer |
| `detect_angular_implicit_globals` | R | Find undeclared variable assignments in Angular provider scripts that cause runt... | full, platform_developer, portal_developer, service_desk, standard |
| `download_portal_sources` | R | Export widget, provider, and script include sources to local file structure. Sup... | full, platform_developer, portal_developer, service_desk, standard |
| `get_portal_component_code` | R | Fetch specific code field from a widget, provider, or script include. Token-effi... | full, platform_developer, portal_developer, service_desk, standard |
| `get_widget_bundle` | R | Fetch widget HTML, scripts, and provider list in a single API call. Returns comp... | full, platform_developer, portal_developer, service_desk, standard |
| `preview_portal_component_update` | R | Preview bounded before/after snippets and diff for a proposed portal component e... | full, portal_developer |
| `route_portal_component_edit` | R | Shallow natural-language router that maps short portal edit instructions to boun... | full, portal_developer |
| `search_portal_regex_matches` | R | Regex search across widget sources (HTML/scripts/providers). Supports minimal, c... | full, platform_developer, portal_developer, service_desk, standard |
| `trace_portal_route_targets` | R | Map widget-to-provider-to-route relationships without raw script bodies. Returns... | full, platform_developer, portal_developer, service_desk, standard |
| `update_portal_component` | W | Update specific code fields (HTML, CSS, or script) of a widget, provider, or scr... | full, portal_developer |
| `update_portal_component_from_snapshot` | W | Restore a portal component's editable fields from a previously saved local snaps... | full, portal_developer |

### Portal Management (8)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_widget_instance` | W | Place a widget on a page column. Specify widget sys_id, target column, order, an... | full, portal_developer |
| `get_page` | R | Get a page by sys_id or URL path. Optionally includes full container/row/column/... | full, platform_developer, portal_developer, service_desk, standard |
| `get_portal` | R | Get a single portal by sys_id or URL suffix. Returns full config including theme... | full, platform_developer, portal_developer, service_desk, standard |
| `get_widget_instance` | R | Get a single widget instance with its placement, parameters, and CSS overrides.... | full, platform_developer, portal_developer, service_desk, standard |
| `list_pages` | R | List portal pages with title, URL path, and visibility flags. Filterable by titl... | full, platform_developer, portal_developer, service_desk, standard |
| `list_portals` | R | List portals with title, URL suffix, theme, and homepage references. Filterable ... | full, platform_developer, portal_developer, service_desk, standard |
| `list_widget_instances` | R | List widget placements on pages with column and order info. Filter by page or wi... | full, platform_developer, portal_developer, service_desk, standard |
| `update_widget_instance` | W | Move, reorder, or update options/CSS of an existing widget instance on a page.... | full, portal_developer |

### Script Include (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_script_include` | W | Create a script include with name, script, api_name, and client_callable fields.... | full, platform_developer, portal_developer |
| `delete_script_include` | W | Permanently delete a script include by sys_id or name. Irreversible.... | full, platform_developer |
| `execute_script_include` | W | Run a client-callable script include method via GlideAjax REST. Requires client_... | full, platform_developer |
| `get_script_include` | R | Retrieve a single script include with full script body by sys_id or name.... | full, platform_developer, portal_developer, service_desk, standard |
| `list_script_includes` | R | List script includes filtered by name/scope/active. Returns metadata without scr... | full, platform_developer, portal_developer, service_desk, standard |
| `update_script_include` | W | Update a script include's script, api_name, client_callable, or other fields by ... | full, platform_developer, portal_developer |

### Source Search (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `extract_table_dependencies` | R | Build a GlideRecord table dependency graph from server scripts. Scans SI, BR, an... | full, platform_developer, portal_developer, service_desk, standard |
| `extract_widget_table_dependencies` | R | Build a table dependency graph for a single widget, optionally expanding linked ... | full, platform_developer, portal_developer, service_desk, standard |
| `get_metadata_source` | R | Fetch a source record (SI, BR, widget, etc.) by name or sys_id. Returns metadata... | full, platform_developer, portal_developer, service_desk, standard |
| `search_server_code` | R | Keyword/regex search across server-side scripts (SI, BR, client scripts, etc.). ... | full, platform_developer, portal_developer, service_desk, standard |

### UI Policy (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_ui_policy` | W | Create a form field behavior rule (show/hide/mandatory) triggered by encoded que... | full, platform_developer |
| `create_ui_policy_action` | W | Add a field-level action to a UI policy: set visibility, mandatory, or read-only... | full, platform_developer |

### User & Group (9)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `add_group_members` | W | Add members to an existing group in ServiceNow... | *(none)* |
| `create_group` | W | Create a new group in ServiceNow... | *(none)* |
| `create_user` | W | Create a new user in ServiceNow... | *(none)* |
| `get_user` | R | Get a specific user in ServiceNow... | *(none)* |
| `list_groups` | R | List groups from ServiceNow with optional filtering... | *(none)* |
| `list_users` | R | List users in ServiceNow... | *(none)* |
| `remove_group_members` | W | Remove members from an existing group in ServiceNow... | *(none)* |
| `update_group` | W | Update an existing group in ServiceNow... | *(none)* |
| `update_user` | W | Update an existing user in ServiceNow... | *(none)* |
