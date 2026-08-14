# ServiceNow MCP - Inventario de Herramientas

Para evitar el coste de mantener un inventario traducido fila por fila, este archivo es un **resumen** de la superficie de herramientas actual. Las cifras las actualiza `scripts/regenerate_doc_counts.py`.

Herramientas registradas en el registro activo: **75**
Recuento de herramientas empaquetadas en `full`: **61**
Herramientas registradas pero actualmente sin empaquetar: **11**

- Listado completo herramienta por herramienta: [TOOL_INVENTORY.md en inglés](./TOOL_INVENTORY.md)

`list_tool_packages` se inyecta en tiempo de ejecución en cada paquete habilitado excepto `none`.
Está documentado más abajo, pero los recuentos de paquetes en este archivo reflejan la superficie de herramientas definida en YAML.

## Resumen de Paquetes

| Paquete | Herramientas | Descripción |
|---------|------:|-------------|
| `none` | 0 | Perfil deshabilitado para apagar herramientas intencionadamente. |
| `core` | 12 | Elementos esenciales mínimos de solo lectura para trabajo rápido de health/schema/table. |
| `standard` | 31 | Paquete predeterminado de solo lectura para incidentes, cambios, portal, registros y análisis de fuentes. |
| `service_desk` | 33 | standard más flujos de escritura de incidentes y cambios para soporte operativo. |
| `portal_developer` | 50 | standard más flujos de portal, changeset, script include y entrega de sincronización local. |
| `platform_developer` | 44 | standard más flujos de workflow, Flow Designer, UI policy, incidentes/cambios y escrituras de scripts. |
| `full` | 61 | La superficie empaquetada más amplia: todos los flujos manage_* más operaciones avanzadas. |

## Auxiliares Inyectados en Tiempo de Ejecución

| Tool | R/W | Description | Packages |
|------|-----|-------------|----------|
| `list_tool_packages` | R | Lista los paquetes de herramientas disponibles y el actualmente activo. | `core`, `standard`, `service_desk`, `portal_developer`, `platform_developer`, `full` |
| `list_instances` | R | Lista los alias configurados para el modo de comparación de datos de solo lectura. | runtime comparison helper |
| `compare_instances` | R | Comparación de registros de solo lectura entre alias configurados; no es un mecanismo de enrutamiento de escritura. | runtime comparison helper |

## Criterio de mantenimiento de este documento

- **El listado completo por herramienta se mantiene en el archivo en inglés
  `docs/TOOL_INVENTORY.md`**, que se genera desde el registro activo y por tanto
  nunca se queda atrás.
- Este archivo se limita a un resumen para elegir paquete y ver la superficie
  actual. Mantener en paralelo la traducción fila por fila lo dejó cuatro
  versiones atrasado (faltaban 10 herramientas), así que se unifica con el
  criterio que el archivo en coreano adoptó primero.
- Las cifras y la tabla de paquetes se regeneran automáticamente: no las edites a mano.
