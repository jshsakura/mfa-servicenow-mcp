---
title: "Gestión de cambios"
description: "Change management tools available in the ServiceNow MCP server."
slug: es/change_management
---

Una sola herramienta, `manage_change`, cubre las solicitudes de cambio (`change_request`), sus tareas y los pasos de aprobación.

| Paquete | Acciones |
|---|---|
| `platform_developer` | todas las acciones menos aprobar (approve) y rechazar (reject) |
| `full` | todas las acciones |

Las acciones de escritura necesitan `confirm='approve'`, como cualquier escritura en este servidor. Para listas largas o filtradas también sirve `sn_query` con `table=change_request`.

## Acciones

| Acción | Obligatorio | Opcional |
|---|---|---|
| `action="get"` | `change_id` para un registro; nada para una lista | `limit`, `offset`, `timeframe`, `query`, `state`, `type`, `category`, `assignment_group`, `count_only` |
| `action="create"` | `short_description`, `type` | `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date` |
| `action="update"` | `change_id` y al menos un campo | `short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes` |
| `action="add_task"` | `change_id`, `task_short_description` | `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date` |
| `action="submit"` | `change_id` | `state` (por defecto Assess), `work_notes` (comentario de la solicitud) |
| `action="approve"` | `change_id` | `approver_id`, `state` (por defecto Implement), `work_notes` (comentario) |
| `action="reject"` | `change_id`, `work_notes` (el motivo) | `approver_id`, `state` (por defecto Canceled) |

## Aprobaciones

- `action="submit"` lleva el cambio al estado objetivo y crea un registro de aprobación en estado requested.
- `action="approve"` y `action="reject"` actúan sobre el registro de aprobación de `approver_id` (un sys_id o un nombre). Sin él, actúan sobre el primer registro que siga pendiente. Después llevan el cambio al estado objetivo.
- Submit y approve también necesitan `confirm_publish='approve'`, porque mueven un cambio con el que trabajan otras personas.

## Valores de elección

`state`, `type`, `risk` e `impact` guardan códigos, no palabras: en `state`, -4 es Assess y -1 es Implement. Pase el código o su etiqueta. Antes de escribir, la herramienta compara el valor con la lista de opciones de la propia instancia (`sys_choice`). Un valor que no está en la lista se rechaza, y el rechazo enumera todos los valores válidos.

En approve y reject, el estado objetivo se comprueba antes de tocar el registro de aprobación. Un estado incorrecto no puede dejar la aprobación decidida y el cambio donde estaba.

## Vistas previas

Pase `dry_run=true` en cualquier acción de escritura:

- `action="update"` devuelve las diferencias campo por campo.
- `action="approve"` y `action="reject"` devuelven el registro de aprobación y el estado del cambio que fijarían.
- Las demás acciones de escritura devuelven `would_send`: la petición exacta que haría la llamada.

En ningún caso se escribe nada.

## Ejemplos de prompts

- "Crea una solicitud de cambio para el mantenimiento del servidor y aplicar parches de seguridad mañana por la noche."
- "Añade al cambio de mantenimiento una tarea de comprobaciones previas."
- "Envía a aprobación el cambio de mantenimiento del servidor."
- "Aprueba el cambio de actualización de la base de datos con el comentario: el plan de implementación es minucioso."
- "Rechaza el cambio de red: faltan pruebas."
- "Muéstrame todos los cambios de emergencia previstos para esta semana."
