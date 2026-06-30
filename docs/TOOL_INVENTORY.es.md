# ServiceNow MCP - Inventario de Herramientas

GENERADO AUTOMÁTICAMENTE por `scripts/regenerate_tool_inventory.py`. No editar a mano.

Herramientas registradas en el registro activo: **65**
Recuento de herramientas empaquetadas en `full`: **54**
Herramientas registradas pero actualmente sin empaquetar: **11**

`list_tool_packages` se inyecta en tiempo de ejecución en cada paquete habilitado excepto `none`.
Está documentado más abajo, pero los recuentos de paquetes en este archivo reflejan la superficie de herramientas definida en YAML.

## Resumen de Paquetes

| Paquete | Herramientas | Descripción |
|---------|------:|-------------|
| `none` | 0 | Perfil deshabilitado para apagar herramientas intencionadamente. |
| `core` | 12 | Elementos esenciales mínimos de solo lectura para trabajo rápido de health/schema/table. |
| `standard` | 28 | Paquete predeterminado de solo lectura para incidentes, cambios, portal, registros y análisis de fuentes. |
| `service_desk` | 30 | standard más flujos de escritura de incidentes y cambios para soporte operativo. |
| `portal_developer` | 40 | standard más flujos de portal, changeset, script include y entrega de sincronización local. |
| `platform_developer` | 40 | standard más flujos de workflow, Flow Designer, UI policy, incidentes/cambios y escrituras de scripts. |
| `full` | 54 | La superficie empaquetada más amplia: todos los flujos manage_* más operaciones avanzadas. |

## Auxiliares Inyectados en Tiempo de Ejecución

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `list_tool_packages` | R | Lista los paquetes de herramientas disponibles y el actualmente activo. | `core`, `standard`, `service_desk`, `portal_developer`, `platform_developer`, `full` |
| `list_instances` | R | Lista los alias configurados para el modo de comparación de datos de solo lectura. | runtime comparison helper |
| `compare_instances` | R | Comparación de registros de solo lectura entre alias configurados; no es un mecanismo de enrutamiento de escritura. | runtime comparison helper |

## Herramientas Registradas pero Sin Empaquetar

Estas herramientas están registradas en el código pero excluidas intencionadamente de las superficies YAML empaquetadas. Permanecen accesibles para compilaciones personalizadas, pruebas o futuras decisiones de empaquetado.

`create_category`, `create_knowledge_base`, `get_developer_daily_summary`, `get_repo_file_last_modifier`, `get_repo_recent_commits`, `get_repo_working_tree_status`, `get_uncommitted_changes`, `manage_epic`, `manage_project`, `manage_scrum_task`, `manage_story`

## Herramientas por Módulo

La columna **R/W** indica la capacidad completa de la herramienta cuando no está restringida. Un paquete mostrado como `pkg (actions…)` expone ÚNICAMENTE esas acciones de esa herramienta — por ejemplo, `manage_script_include` está registrado como `R/W` pero los paquetes de solo lectura (`core`, `standard`) lo exponen como `standard (get, list)`. Los paquetes listados sin paréntesis exponen la herramienta con su capacidad R/W completa.

### Attachment Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `download_attachment` | R | Descarga archivo(s) adjunto(s) de ServiceNow a disco por attachment_sys_id, o table+record. Lee desde saved_path. | standard, portal_developer, platform_developer, service_desk, full |

### Audit Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | Audita los cambios pendientes del update set — inventario por tipo, patrones de riesgo, clones y referencias cruzadas. | full |

### Catalog Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_catalog` | R/W | CRUD de categoría/ítem/variable del catálogo (tablas: sc_category, sc_cat_item, item_option_new). | portal_developer, service_desk (get_item, list_categories, list_item_variables, list_items), full |

### Change Tools (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `approve_change` | W | Aprueba el registro de aprobación de un cambio (por approver_id); avanza el change_request (predeterminado: implement). | full |
| `manage_change` | R/W | Obtiene/crea/actualiza una solicitud de cambio o añade una tarea de cambio (tabla: change_request). | platform_developer, full |
| `reject_change` | W | Rechaza el registro de aprobación de un cambio (por approver_id) con motivo; avanza el change_request (predeterminado: canceled). | full |
| `submit_change_for_approval` | W | Transiciona una solicitud de cambio al estado assess y crea un registro de aprobación. Requiere change_id. | platform_developer, full |

### Changeset Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_changeset` | R/W | Get/create/update/commit/publish/add_file en un update set (tabla: sys_update_set). | portal_developer, platform_developer, full |

### Epic Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_epic` | R/W | CRUD de Epic (tabla: rm_epic). list omite confirmación. | — |

### Flow Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_flow_designer` | R/W | Lectura/inspección de Flow Designer. Ediciones LIMITADAS a inputs de acción + condiciones de trigger/branch; sin cambios estructurales (usa la UI). | core (list), standard (get_action_source, get_detail, get_executions, list), portal_developer, platform_developer, service_desk (get_action_source, get_detail, get_executions, list), full |

### Incident Management (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_incident` | R/W | Obtiene/crea/actualiza/comenta/resuelve un incidente (tabla: incident). Una sola llamada, sin necesidad de consultar el schema. | platform_developer, service_desk, full |

### Knowledge Base (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `create_category` | W | Crea una categoría de KB bajo una knowledge base. Requiere kb_id y label. | — |
| `create_knowledge_base` | W | Crea una knowledge base (kb_knowledge_base). Requiere title. Devuelve sys_id. | — |
| `manage_kb_article` | R/W | Crea/actualiza/publica un artículo de conocimiento (tabla: kb_knowledge). | full |

### Local Graph Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `query_local_graph` | R | Respuestas offline de dependencia/impacto desde archivos de grafo de auditoría (0 API). uses|used_by|page|impact. | standard, portal_developer, platform_developer, service_desk, full |

### Logs (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_logs` | R | Consulta los registros de ServiceNow. log_type: system/journal/transaction/background. Máx. 20 filas. | core, standard, portal_developer, platform_developer, service_desk, full |

### Performance Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | Analiza el rendimiento del widget — patrones de código, registros de transacciones, uso de providers. Devuelve hallazgos con severidad. | standard, portal_developer, platform_developer, service_desk, full |

### Portal CRUD (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_portal_component` | W | Crea componentes de portal; o edita CUALQUIER registro de código por sys_id — BR, notification, SI, ACL, UI, etc. action=update_code. | portal_developer, platform_developer, full |
| `manage_portal_layout` | W | Layout de portal: CRUD de página + container/row/column + colocación de instancia de widget. | portal_developer, platform_developer, full |
| `scaffold_page` | W | Crea una página de portal completa con layout (container/rows/columns) y colocaciones de widgets en una sola llamada. Scope es obligatorio. | portal_developer, platform_developer, full |

### Portal Dev Tools (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_developer_changes` | R | Lista los cambios recientes de un desarrollador en las tablas del portal. Solo metadatos, usa count_only primero. | standard, portal_developer, platform_developer, service_desk, full |
| `get_developer_daily_summary` | R | Genera el resumen diario de trabajo de un desarrollador. Admite formatos de salida jira/plain/structured. | — |
| `get_uncommitted_changes` | R | Lista las entradas de update set sin confirmar de un desarrollador. Devuelve el tipo de entrada y el target. Usa count_only=true primero. | — |

### Portal Management (9)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | R | Analiza una edición propuesta de componente de portal y devuelve resúmenes acotados de riesgo y cambios de campo. | portal_developer, full |
| `detect_angular_implicit_globals` | R | Detecta asignaciones de variables no declaradas en scripts de provider Angular que causan errores 'not defined' en tiempo de ejecución. | portal_developer, full |
| `download_portal_sources` | R | Widgets/providers de portal específicos. App completa: download_app_sources. widget_ids=un widget. | standard, portal_developer, platform_developer, service_desk, full |
| `get_portal_component_code` | R | Obtiene campos de widget/provider/SI. Devuelve el cuerpo completo por defecto. Nunca fragmentar para análisis. | standard, portal_developer, platform_developer, service_desk, full |
| `get_widget_bundle` | R | Obtiene el bundle completo del widget (HTML, scripts, providers, dependencias CSS/JS) en una sola llamada. Punto de partida del análisis. | standard, portal_developer, platform_developer, service_desk, full |
| `preview_portal_component_update` | R | Previsualiza fragmentos acotados de antes/después y el diff para una edición propuesta de componente de portal. | portal_developer, full |
| `route_portal_component_edit` | R | Enruta una instrucción de edición de portal a la herramienta correcta de analyze/preview/apply. | portal_developer, full |
| `search_portal_regex_matches` | R | Regex real sobre el código del portal (widget/provider/SI), offsets+contexto. Búsqueda de palabras clave en tablas de servidor: search_server_code. | standard, portal_developer, platform_developer, service_desk, full |
| `trace_portal_route_targets` | R | Mapea relaciones widget→provider→route. Solo metadatos, sin cuerpos de script. | standard, portal_developer, platform_developer, service_desk, full |

### Portal Management Tools (3)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_page` | R | Obtiene o lista páginas de portal por ruta URL, título o sys_id. Devuelve el árbol de layout con las colocaciones de widgets. | core, standard, portal_developer, platform_developer, service_desk, full |
| `get_portal` | R | Obtiene o lista Service Portals por nombre, sufijo de URL o sys_id. Devuelve config, homepage, theme y páginas. | full |
| `get_widget_instance` | R | Obtiene la colocación de una instancia de widget en una página. Devuelve column, order y config. Filtra por página o widget. | standard, portal_developer, platform_developer, service_desk, full |

### Project Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_project` | R/W | CRUD de Project (tabla: pm_project). list omite confirmación. | — |

### Repository (4)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | Informe git combinado: estado del working tree + commits recientes + último modificador por archivo en una sola llamada. | full |
| `get_repo_file_last_modifier` | R | Consulta el último modificador por archivo y los metadatos del commit con estado de cambios sin confirmar opcional. | — |
| `get_repo_recent_commits` | R | Lista los commits recientes con autor y listas opcionales de archivos modificados. | — |
| `get_repo_working_tree_status` | R | Inspecciona el estado del working tree incluyendo archivos staged, unstaged y untracked. | — |

### Script Include (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_script_include` | R/W | List/get/create/update/delete/execute de un script include (tabla: sys_script_include). | core (get, list), standard (get, list), portal_developer, platform_developer, service_desk (get, list), full |

### Scrum Task Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_scrum_task` | R/W | CRUD de scrum task (tabla: rm_scrum_task). list omite confirmación. | — |

### Session Context Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_session_context` | W | Obtiene/cambia la aplicación actual + update set (browser auth). set_* verifica mediante relectura. | portal_developer, platform_developer, full |

### Sn Api (7)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `sn_aggregate` | R | Ejecuta COUNT/SUM/AVG/MIN/MAX en cualquier tabla con group_by opcional. Devuelve estadísticas sin recuperar registros. | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_discover` | R | Encuentra tablas por palabra clave de name o label. Devuelve table name, label, scope y parent class. | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_health` | R | Verifica la conectividad de la API de ServiceNow, el estado de auth, el estado de instalación de Chromium (browser auth) y la versión del servidor MCP. | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_query` | R | Consulta genérica de tabla — último recurso. Prefiere herramientas de dominio: search_server_code, manage_workflow, manage_flow_designer. | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_resolve_url` | R | Analiza una URL de ServiceNow → table, sys_id, scope, herramienta siguiente sugerida. Solo lectura. | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_schema` | R | Obtiene nombres de campo, tipos, labels y restricciones desde sys_dictionary para una tabla dada. | core, standard, portal_developer, platform_developer, service_desk, full |
| `sn_write` | W | CRUD DE ÚLTIMO RECURSO (sin herramienta dedicada). Prefiere manage_*/update_*. ACL/user/group/scope bloqueados. confirm='approve'. | full |

### Source Analysis (6)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `download_app_sources` | R | Fuente COMPLETA/total de un scope de app a disco (todos los grupos+deps). scope OBLIGATORIO — pregunta al usuario. Paso 1, no portal. | standard, portal_developer, platform_developer, service_desk, full |
| `download_server_sources` | R | Familias de fuentes del lado del servidor específicas (SIs/BRs/UI/api/security/admin). App completa: download_app_sources. | platform_developer, full |
| `download_table_schema` | R | Descarga las definiciones de campo de sys_dictionary. Especifica tables o autodetecta desde fuentes locales. | platform_developer, full |
| `extract_table_dependencies` | R | Grafo de dependencias de tablas GlideRecord desde scripts de servidor (SI/BR/widgets). Pasa widget_id para un solo widget. | standard, portal_developer, platform_developer, service_desk, full |
| `get_metadata_source` | R | Obtiene un registro de fuente (SI/BR/widget) por name/sys_id. Devuelve el cuerpo; 'complete' indica si es una vista previa truncada. | standard, portal_developer, platform_developer, service_desk, full |
| `search_server_code` | R | Búsqueda rápida de palabras clave en 22 tipos de código del lado del servidor (SI/BR/ACL). Regex+fragmentos de portal: search_portal_regex_matches. | core, standard, portal_developer, platform_developer, service_desk, full |

### Source Audit Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `audit_local_sources` | R | Analiza las fuentes descargadas localmente (sin API). Genera grafo de referencias cruzadas, código muerto, informe HTML. | standard, portal_developer, platform_developer, service_desk, full |

### Story Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_story` | R/W | CRUD de Story + operaciones de dependencia (rm_story/m2m_story_dependencies). list/list_dependencies omiten confirmación. | — |

### Sync Tools (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `diff_local_component` | R | Compara ediciones locales con el remoto (o con una 2ª raíz de descarga vía compare_to, p. ej. dev-vs-test). | standard, portal_developer, platform_developer, service_desk, full |
| `update_remote_from_local` | W | Envía una edición local de vuelta a ServiceNow (diff_local_component primero). Actualización dirigida, no promoción masiva dev→test. | portal_developer, platform_developer, full |

### UI Policy (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_ui_policy` | W | Creación de UI Policy + add field action (tablas: sys_ui_policy / sys_ui_policy_action). | portal_developer, platform_developer, full |

### User Tools (2)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_group` | R/W | CRUD de Group + operaciones de membresía (tabla: sys_user_group). list omite confirmación. | full |
| `manage_user` | R/W | CRUD de User + búsqueda (tabla: sys_user). Las acciones de lectura omiten confirmación. | full |

### Widget Dependency Tools (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_widget_dependency` | R/W | CRUD + link/unlink para providers Angular y dependencias CSS/JS de widgets. Usa action=list primero para los sys_ids. | standard (get, list), portal_developer, platform_developer (get, list), service_desk (get, list), full |

### Workflow (1)

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `manage_workflow` | R/W | SOLO motor de Workflow LEGACY (wf_workflow/wf_activity). La mayoría de los flujos son Flow Designer -> usa manage_flow_designer. | core (get_activities, list), standard (get_activities, list), portal_developer, platform_developer, service_desk (get_activities, list), full |
