# Gestión de Workflows en ServiceNow MCP

Este documento cubre dos motores de workflow expuestos por el servidor MCP:

1. **Workflow heredado** (`wf_workflow`) — controlado por el enrutador de acciones `manage_workflow` que se describe a continuación.
2. **Flow Designer** (`sys_hub_flow`) — herramienta unificada `manage_flow_designer` con despacho de acciones. El paquete estándar expone acciones de lectura (`list` / `get_detail` / `get_executions` / `compare`); los paquetes superiores desbloquean escrituras (`update` / `checkout` / `set_*` / `save` / `discard`). Las tablas de Action/SubFlow/Playbook están documentadas en el [mapa de tablas de Flow Designer](#mapa-de-tablas-de-flow-designer).

Si no estás seguro de qué motor usa un proceso, comienza con `manage_flow_designer(action="list")` (instancias modernas) y recurre a `manage_workflow(action="list")` para los registros heredados `wf_workflow`.

## Resumen

Los workflows de ServiceNow son una potente función de automatización que te permite definir y automatizar procesos de negocio. Las herramientas de gestión de workflows del servidor ServiceNow MCP te permiten ver, crear y modificar workflows en tu instancia de ServiceNow.

## Herramientas Disponibles

### Visualización de Workflows

1. **manage_workflow(action="list")** - Lista los workflows de ServiceNow
   - Parámetros:
     - `limit` (opcional): Número máximo de registros a devolver (predeterminado: 10)
     - `offset` (opcional): Desplazamiento desde el que comenzar (predeterminado: 0)
     - `active` (opcional): Filtrar por estado activo (true/false)
     - `name` (opcional): Filtrar por nombre (contiene)
     - `query` (opcional): Cadena de consulta adicional

2. **manage_workflow(action="get")** - Obtiene información detallada sobre un workflow específico
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id

3. **manage_workflow(action="list_versions")** - Lista todas las versiones de un workflow específico
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id
     - `limit` (opcional): Número máximo de registros a devolver (predeterminado: 10)
     - `offset` (opcional): Desplazamiento desde el que comenzar (predeterminado: 0)

4. **manage_workflow(action="get_activities")** - Obtiene todas las actividades de un workflow
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id
     - `version` (opcional): Versión específica de la que obtener actividades (si no se proporciona, se usará la última versión publicada)

### Modificación de Workflows

5. **manage_workflow** (action="create") - Crea un nuevo workflow en ServiceNow
   - Parámetros:
     - `name` (requerido): Nombre del workflow
     - `description` (opcional): Descripción del workflow
     - `table` (opcional): Tabla a la que se aplica el workflow
     - `active` (opcional): Indica si el workflow está activo (predeterminado: true)
     - `attributes` (opcional): Atributos adicionales para el workflow

6. **manage_workflow** (action="update") - Actualiza un workflow existente
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id
     - `name` (opcional): Nombre del workflow
     - `description` (opcional): Descripción del workflow
     - `table` (opcional): Tabla a la que se aplica el workflow
     - `active` (opcional): Indica si el workflow está activo
     - `attributes` (opcional): Atributos adicionales para el workflow

7. **manage_workflow** (action="activate") - Activa un workflow
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id

8. **manage_workflow** (action="deactivate") - Desactiva un workflow
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id

### Gestión de Actividades de Workflow

9. **manage_workflow** (action="add_activity") - Añade una nueva actividad a un workflow
   - Parámetros:
     - `workflow_id` (requerido): ID del workflow o sys_id
     - `name` (requerido): Nombre de la actividad
     - `description` (opcional): Descripción de la actividad
     - `activity_type` (requerido): Tipo de actividad (p. ej., 'approval', 'task', 'notification')
     - `attributes` (opcional): Atributos adicionales para la actividad
     - `position` (opcional): Posición en el workflow (si no se proporciona, la actividad se añadirá al final)

10. **manage_workflow** (action="update_activity") - Actualiza una actividad existente en un workflow
    - Parámetros:
      - `activity_id` (requerido): ID de la actividad o sys_id
      - `name` (opcional): Nombre de la actividad
      - `description` (opcional): Descripción de la actividad
      - `attributes` (opcional): Atributos adicionales para la actividad

11. **manage_workflow** (action="delete_activity") - Elimina una actividad de un workflow
    - Parámetros:
      - `activity_id` (requerido): ID de la actividad o sys_id

12. **manage_workflow** (action="reorder_activities") - Cambia el orden de las actividades en un workflow
    - Parámetros:
      - `workflow_id` (requerido): ID del workflow o sys_id
      - `activity_ids` (requerido): Lista de IDs de actividades en el orden deseado

## Ejemplos de Uso

### Visualización de Workflows

#### Listar todos los workflows activos

```python
result = list_workflows({
    "active": True,
    "limit": 20
})
```

#### Obtener detalles de un workflow específico

```python
result = get_workflow_details({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### Listar todas las versiones de un workflow

```python
result = list_workflow_versions({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### Obtener todas las actividades de un workflow

```python
result = get_workflow_activities({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### Modificación de Workflows

#### Crear un nuevo workflow

```python
result = manage_workflow({"action": "create",
    "name": "Software License Request",
    "description": "Workflow for handling software license requests",
    "table": "sc_request"
})
```

#### Actualizar un workflow existente

```python
result = manage_workflow({"action": "update",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "description": "Updated workflow description",
    "active": True
})
```

#### Activar un workflow

```python
result = manage_workflow({"action": "activate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### Desactivar un workflow

```python
result = manage_workflow({"action": "deactivate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### Gestión de Actividades de Workflow

#### Añadir una nueva actividad a un workflow

```python
result = manage_workflow({"action": "add_activity",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "name": "Manager Approval",
    "description": "Approval step for the manager",
    "activity_type": "approval"
})
```

#### Actualizar una actividad existente

```python
result = manage_workflow({"action": "update_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591",
    "name": "Updated Activity Name",
    "description": "Updated activity description"
})
```

#### Eliminar una actividad

```python
result = manage_workflow({"action": "delete_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591"
})
```

#### Reordenar las actividades de un workflow

```python
result = manage_workflow({"action": "reorder_activities",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "activity_ids": [
        "3cda7cda87a9c150e0b0df23cebb3591",
        "4cda7cda87a9c150e0b0df23cebb3592",
        "5cda7cda87a9c150e0b0df23cebb3593"
    ]
})
```

## Herramientas de Flow Designer

Flow Designer (`sys_hub_flow`) es el sucesor moderno de los workflows heredados. El servidor MCP expone una lectura con fidelidad de pantalla más una superficie de edición verificada (condiciones, entradas de acciones, propiedades, copia, activación) a través de la API processflow, restringida por paquete de herramientas. Lo único que **no** simulará es la publicación: la recompilación de snapshots está restringida al editor, por lo que la herramienta devuelve una instrucción de publicación manual en lugar de un falso éxito. Las escrituras directas mediante la Table API a `sys_hub_*` están bloqueadas (guard G6) porque corrompen los snapshots del flujo.

### `manage_flow_designer` (unificada)
Herramienta compuesta única con despacho de acciones. Reemplaza las 6 herramientas de flujo independientes anteriores (`list_flow_designers`, `get_flow_designer_detail`, `get_flow_designer_executions`, `compare_flows`, `update_flow_designer`, `manage_flow_edit`). El enum de acciones se reduce a solo lectura en `standard` y se desbloquea en `portal_developer` / `platform_developer` / `full`.

Acciones de lectura (disponibles en `standard`):
- `action="read"` (v1.18.6) — la lectura con **fidelidad de pantalla**: un único árbol de pasos ordenado y anidado con If/Else (acciones + lógica + subflows fusionados por orden de ejecución), condiciones **decodificadas a texto legible por humanos**, data pills resueltas a las etiquetas de los pasos que las producen, y tipos de Action personalizados con sus cuerpos de Script. Protegido contra ciclos/uid faltantes. ~18K tokens para un flujo de 142 nodos (frente a ~130K antes) — empieza aquí para entender un flujo.
- `action="read_action"` — lee el cuerpo de Script de una única definición de Action personalizada.
- `action="list"` — busca flujos/subflows. Parámetros clave: `limit`, `offset`, `include_inactive`, `flow_status`, `scope`, `name_filter`.
- `action="get_detail"` — metadatos del flujo + secciones pesadas opcionales. Parámetros clave: `flow_id` (requerido), `include_structure`, `include_triggers`, `include_executions_summary`, `trace_pill`, `include_subflow_tree`, `summary_format`.
- `action="get_executions"` — historial de ejecución (filtros) o detalle de una única ejecución. Parámetros clave: `context_id` (modo único), `flow_id`, `flow_name`, `exec_state`, `source_record`, `errors_only`, `limit`/`offset`.
- `action="compare"` — compara dos flujos por `flow_id_a`/`flow_id_b` o `name_a`/`name_b`. Informa de la diferencia estructural, los enlaces de subflows y las diferencias de triggers. Preferible a llamar a `get_detail` dos veces.

Acciones de escritura (solo en `portal_developer` / `platform_developer` / `full`). Todas las ediciones se **verifican en vivo** (relectura tras guardar) y admiten `dry_run`:
- `action="update"` — solo metadatos (`new_name` / `description` / `active`).
- `action="checkout"` — inicia una sesión de edición local (requiere autenticación de navegador, usa la API processflow). `action="status"` la inspecciona; `action="discard"` la descarta.
- `action="set_action_input"` — modifica el valor de entrada de una acción. Requiere `node_id`, `input_name`, `value`.
- `action="set_branch_condition"` / `action="set_trigger_condition"` — modifica la condición de una rama lógica o de un trigger. Pasa filas estructuradas `[{field, operator, value}]` **o** una consulta codificada en bruto; la respuesta devuelve `condition_readable` para que puedas confirmar que el codificador produjo lo que pretendías (los operadores incluyen la familia CHANGES, AND/OR/NQ).
- `action="set_property"` / `action="save_properties"` — propiedades del flujo: Run As, Protection, Priority, `active`.
- `action="copy"` — clonación nativa de flujo/subflow (la misma llamada que hace "Copy flow" de Workflow Studio).
- `action="activate"` / `action="deactivate"` — alterna el estado activo del flujo.
- `action="save"` — persiste las ediciones a través de la API processflow (un PUT con el scope correcto que también escribe una nueva versión del flujo — la corrección para la reversión silenciosa de triggers).
- `action="publish"` — **restringido al editor.** La recompilación de snapshots solo es alcanzable desde el editor interactivo de Workflow Studio; cada ruta de API falla rápidamente. La herramienta no finge éxito — devuelve `manual_publish_required` más la URL exacta de la interfaz para finalizar la publicación a mano.

### Mapa de Tablas de Flow Designer

| Pestaña de Workflow Studio | Tabla |
| --- | --- |
| Flows / SubFlows | `sys_hub_flow` |
| Actions | `sys_hub_action_type_definition` |
| Playbooks | `sys_pd_process_definition` |
| Decision Tables | `sys_decision` |

### Sesgo hacia Solo Lectura

Las modificaciones de flujos conllevan el mayor riesgo en este código base — corromper un flujo publicado puede romper la automatización en toda la instancia. Usa por defecto las acciones de lectura, restringe las escrituras tras una confirmación explícita del usuario, y prefiere `manage_flow_designer(action="compare")` + `manage_flow_designer(action="get_executions")` para verificar el comportamiento antes de cualquier cambio.

## Tipos Comunes de Actividad

ServiceNow proporciona varios tipos de actividad que se pueden usar al añadir actividades a un workflow:

1. **approval** - Una actividad de aprobación que requiere acción del usuario
2. **task** - Una tarea que debe completarse
3. **notification** - Envía una notificación a los usuarios
4. **timer** - Espera durante un periodo de tiempo especificado
5. **condition** - Evalúa una condición y bifurca el workflow
6. **script** - Ejecuta un script
7. **wait_for_condition** - Espera hasta que se cumpla una condición
8. **end** - Finaliza el workflow

## Buenas Prácticas

1. **Control de Versiones**: Crea siempre una nueva versión de un workflow antes de hacer cambios importantes.
2. **Pruebas**: Prueba los workflows en un entorno que no sea de producción antes de desplegarlos en producción.
3. **Documentación**: Documenta el propósito y el comportamiento de cada workflow y actividad.
4. **Manejo de Errores**: Incluye manejo de errores en tus workflows para gestionar situaciones inesperadas.
5. **Notificaciones**: Usa actividades de notificación para mantener informadas a las partes interesadas sobre el progreso del workflow.

## Resolución de Problemas

### Problemas Comunes

1. **Error: "No published versions found for this workflow"**
   - Este error ocurre al intentar obtener actividades de un workflow que no tiene versiones publicadas.
   - Solución: Publica una versión del workflow antes de intentar obtener sus actividades.

2. **Error: "Activity type is required"**
   - Este error ocurre al intentar añadir una actividad sin especificar su tipo.
   - Solución: Proporciona un tipo de actividad válido al añadir una actividad.

3. **Error: "Cannot modify a published workflow version"**
   - Este error ocurre al intentar modificar una versión publicada de un workflow.
   - Solución: Crea una nueva versión en borrador del workflow antes de hacer cambios.

4. **Error: "Workflow ID is required"**
   - Este error ocurre cuando no se proporciona un ID de workflow para operaciones que lo requieren.
   - Solución: Asegúrate de incluir el ID del workflow en tu solicitud.

## Recursos Adicionales

- [Documentación de Workflows de ServiceNow](https://docs.servicenow.com/bundle/tokyo-platform-administration/page/administer/workflow-administration/concept/c_WorkflowAdministration.html)
- [Referencia de la API de Workflows de ServiceNow](https://developer.servicenow.com/dev.do#!/reference/api/tokyo/rest/c_WorkflowAPI)
