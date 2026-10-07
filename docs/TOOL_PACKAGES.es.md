# Paquetes de herramientas — Referencia avanzada

> **La mayoría de los usuarios no necesitan esta página.** El paquete predeterminado es `standard` — de solo lectura, seguro para cualquier entorno.
> Continúa leyendo solo si necesitas herramientas de escritura más allá de lo que ofrece `standard`.

---

## Elegir un paquete

Empieza con el paquete más reducido que cubra tu trabajo. Cada nivel superior añade acceso de escritura a más dominios:

Solo lectura — seguro para cualquier entorno, sin herramientas de escritura:

| Paquete | Herramientas | Tokens máx. | Máx. (3 instancias) | Cuándo usarlo |
| :--- | :---: | :---: | :---: | :--- |
| `core` | 12 | ~2.0K | ~2.6K | Solo lectura mínima: salud, esquema, descubrimiento y consultas de artefactos clave únicamente |
| `standard` | 31 | ~7.0K | ~7.9K | **(Predeterminado)** Solo lectura en incidentes, cambios, portal, registros y análisis de código fuente |
| `none` | 0 | 0 | 0 | Deshabilitar intencionadamente todas las herramientas (pruebas, entornos restringidos) |

⚠️ Con capacidad de escritura — **opciones avanzadas** que conceden crear/actualizar/eliminar:

| Paquete | Herramientas | Tokens máx. | Máx. (3 instancias) | Cuándo usarlo |
| :--- | :---: | :---: | :---: | :--- |
| `service_desk` | 33 | ~7.7K | ~8.7K | ⚠️ Agentes de mesa de servicio que necesitan actualizar/cerrar incidentes y cambios |
| `portal_developer` | 52 | ~15.2K | ~17.0K | ⚠️ Desarrolladores de portal que despliegan widgets, changesets y script includes |
| `platform_developer` | 46 | ~12.8K | ~14.4K | ⚠️ Ingenieros de plataforma que gestionan flujos de trabajo, Flow Designer y scripts |
| `full` | 63 | ~17.6K | ~19.8K | ⚠️ El más avanzado — todas las herramientas de escritura en todos los dominios a la vez (consulta la advertencia más abajo) |

> **Tokens máx.** = la huella aproximada que las tool schemas de cada paquete añaden al contexto del modelo por solicitud (medido con tiktoken cl100k_base; el conteo real de Claude varía ligeramente). Usar el paquete más reducido ahorra contexto y costo. **Es el máximo**, no el costo típico: solo lo pagan completo los clientes que cargan todas las tool schemas al inicio. Los clientes con carga diferida de herramientas (p. ej. la búsqueda de herramientas de Claude Code) cargan un schema solo cuando se usa esa herramienta, así que su costo real por solicitud es mucho menor. El número de herramientas cuenta los miembros del paquete; todos los paquetes llevan además `list_tool_packages`, y una configuración multi-instancia añade `list_instances`, `compare_instances` y un parámetro `instance` en cada herramienta — la segunda columna lo mide con tres instancias. Las cifras se miden con tiktoken, no se estiman (`uv run --no-sync --with tiktoken python scripts/measure_tool_tokens.py <paquete>` lista la parte de cada herramienta).

Todos los paquetes excepto `core` y `none` heredan las herramientas de solo lectura de `standard` mediante `_extends`. Consulta `config/tool_packages.yaml` para ver el árbol de herencia completo.

---

!!! danger "⚠️  Cualquier paquete por encima de `standard` es una opción avanzada con capacidad de escritura"
    `service_desk`, `portal_developer`, `platform_developer` y `full` activan herramientas de escritura — un
    agente de IA que se ejecute con ellos puede crear, actualizar y eliminar registros de ServiceNow. `full` lo hace en **todos
    los dominios simultáneamente** (incidentes, cambios, portal, Flow Designer, flujos de trabajo, scripts y más), de modo que un
    solo prompt mal entendido o una alucinación pueden desencadenar cambios destructivos en varias áreas a la vez.

    **No subas de nivel desde `standard` a menos que:**
    - Comprendas cada herramienta de escritura que activa el paquete (consulta [Inventario de herramientas](TOOL_INVENTORY.md))
    - Estés trabajando en una instancia **no productiva** o **de pruebas (sandbox)**, o tengas activado el control `allow_writes`
    - Seas un desarrollador de ServiceNow con experiencia que sepa cómo recuperarse de cambios no deseados

    Si tienes dudas, quédate en el predeterminado de solo lectura `standard` y elige el paquete de escritura más reducido solo cuando una tarea realmente lo necesite.

---

## Establecer el paquete

Mediante variable de entorno (recomendado):

```bash
MCP_TOOL_PACKAGE=standard
```

Mediante opción de la CLI:

```bash
servicenow-mcp --tool-package standard --instance-url ...
```

En la configuración de tu cliente MCP:

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "standard"
  }
}
```

---

## Qué ocurre cuando una herramienta no está en tu paquete

Si llamas a una herramienta que no está activa en tu paquete actual, el servidor devuelve un error claro:

```
Tool 'manage_widget' is not available in package 'standard'.
Enable package 'portal_developer' or higher to use this tool.
```

Sin fallos silenciosos — el LLM sabe exactamente qué paquete solicitar.

---

## Lista completa de herramientas

Para ver la lista completa de las 73 herramientas por categoría y pertenencia a paquete, consulta [Inventario de herramientas](TOOL_INVENTORY.md).
