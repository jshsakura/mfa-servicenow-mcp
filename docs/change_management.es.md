# Herramientas de gestión de cambios de ServiceNow MCP

Este documento proporciona información sobre las herramientas de gestión de cambios disponibles en el servidor ServiceNow MCP.

## Descripción general

Las herramientas de gestión de cambios permiten que Claude interactúe con la funcionalidad de gestión de cambios de ServiceNow, lo que permite a los usuarios crear, actualizar y gestionar solicitudes de cambio mediante conversaciones en lenguaje natural.

## Herramientas disponibles

El servidor ServiceNow MCP proporciona las siguientes herramientas de gestión de cambios:

### Gestión principal de solicitudes de cambio

1. **`manage_change`** - CRUD combinado para solicitudes de cambio (tabla: `change_request`)
   - `action` (obligatorio): uno de `create` / `update` / `add_task`
   - Para `action="create"`: `short_description`, `type` (`normal`/`standard`/`emergency`), además de los opcionales `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date`
   - Para `action="update"`: `change_id` más al menos un campo actualizable (`short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes`); admite `dry_run=True` para una vista previa
   - Para `action="add_task"`: `change_id`, `task_short_description`, además de los opcionales `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date`

2. **`sn_query`** (con `table=change_request`) - Listar solicitudes de cambio con filtros arbitrarios
   - Utilice la primitiva genérica de consulta de tablas para listar solicitudes de cambio. Consulte [Inventario de herramientas](TOOL_INVENTORY.md) para conocer los parámetros de `sn_query`.

3. **`manage_change(action="get")`** - Obtener información detallada sobre una solicitud de cambio específica
   - Parámetros:
     - `change_id` (obligatorio): ID o sys_id de la solicitud de cambio

### Flujo de trabajo de aprobación de cambios

1. **submit_change_for_approval** - Enviar una solicitud de cambio para aprobación
   - Parámetros:
     - `change_id` (obligatorio): ID o sys_id de la solicitud de cambio
     - `approval_comments`: Comentarios para la solicitud de aprobación

2. **approve_change** - Aprobar una solicitud de cambio
   - Parámetros:
     - `change_id` (obligatorio): ID o sys_id de la solicitud de cambio
     - `approver_id`: ID del aprobador
     - `approval_comments`: Comentarios para la aprobación

3. **reject_change** - Rechazar una solicitud de cambio
   - Parámetros:
     - `change_id` (obligatorio): ID o sys_id de la solicitud de cambio
     - `approver_id`: ID del aprobador
     - `rejection_reason` (obligatorio): Motivo del rechazo

## Ejemplo de uso con Claude

Una vez que el servidor ServiceNow MCP esté configurado con Claude Desktop, puede pedirle a Claude que realice acciones como:

### Creación y gestión de solicitudes de cambio

- "Crea una solicitud de cambio para el mantenimiento del servidor para aplicar parches de seguridad mañana por la noche"
- "Programa una actualización de la base de datos para el próximo martes de 2 AM a 4 AM"
- "Crea un cambio de emergencia para corregir la vulnerabilidad de seguridad crítica en nuestra aplicación web"

### Añadir tareas y detalles de implementación

- "Añade una tarea al cambio de mantenimiento del servidor para las comprobaciones previas a la implementación"
- "Añade una tarea para verificar las copias de seguridad del sistema antes de iniciar la actualización de la base de datos"
- "Actualiza el plan de implementación del cambio de red para incluir procedimientos de reversión"

### Flujo de trabajo de aprobación

- "Envía el cambio de mantenimiento del servidor para aprobación"
- "Muéstrame todos los cambios que esperan mi aprobación"
- "Aprueba el cambio de actualización de la base de datos con el comentario: el plan de implementación parece minucioso"
- "Rechaza el cambio de red por pruebas insuficientes"

### Consulta de información de cambios

- "Muéstrame todos los cambios de emergencia programados para esta semana"
- "¿Cuál es el estado del cambio de actualización de la base de datos?"
- "Lista todos los cambios asignados al equipo de Red"
- "Muéstrame los detalles del cambio CHG0010001"

## Código de ejemplo

A continuación se muestra un ejemplo de cómo usar las herramientas de gestión de cambios de forma programática:

```python
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.utils.config import ServerConfig

# Create server configuration
server_config = ServerConfig(
    instance_url="https://your-instance.service-now.com",
)

# Create authentication manager
auth_manager = AuthManager(
    auth_type="basic",
    username="your-username",
    password="your-password",
    instance_url="https://your-instance.service-now.com",
)

# Create a change request via the bundled manage_change tool
params = ManageChangeParams(
    action="create",
    short_description="Server maintenance - Apply security patches",
    description="Apply the latest security patches to the application servers.",
    type="normal",
    risk="moderate",
    impact="medium",
    category="Hardware",
    start_date="2023-12-15 01:00:00",
    end_date="2023-12-15 03:00:00",
)

result = manage_change(server_config, auth_manager, params)
print(result)
```

El ejemplo anterior muestra la forma de la solicitud programática y las importaciones clave necesarias para integrar la gestión de cambios en su propia automatización.

## Integración con Claude Desktop

Para configurar el servidor ServiceNow MCP con herramientas de gestión de cambios en Claude Desktop:

1. Edite el archivo de configuración de Claude Desktop en `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) o la ruta adecuada para su sistema operativo:

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/Users/yourusername/dev/servicenow-mcp/.venv/bin/python",
      "args": [
        "-m",
        "servicenow_mcp.cli"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "SERVICENOW_AUTH_TYPE": "basic"
      }
    }
  }
}
```

2. Reinicie Claude Desktop para aplicar los cambios

## Personalización

Las herramientas de gestión de cambios se pueden personalizar para que coincidan con la configuración específica de ServiceNow de su organización:

- Es posible que los valores de estado deban ajustarse según la configuración de su instancia de ServiceNow
- Se pueden añadir campos adicionales a los modelos de parámetros si es necesario
- Es posible que los flujos de trabajo de aprobación deban modificarse para que coincidan con el proceso de aprobación de su organización

Para personalizar las herramientas, modifique el archivo `change_tools.py` en el directorio `src/servicenow_mcp/tools`. 
