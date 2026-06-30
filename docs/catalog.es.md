# Integración con el Catálogo de Servicios de ServiceNow

Este documento proporciona información sobre la integración con el Catálogo de Servicios de ServiceNow en el servidor MCP de ServiceNow.

## Descripción general

La integración con el Catálogo de Servicios de ServiceNow le permite:

- Listar categorías del catálogo de servicios
- Listar elementos del catálogo de servicios
- Obtener información detallada sobre elementos específicos del catálogo, incluidas sus variables
- Filtrar elementos del catálogo por categoría o consulta de búsqueda

## Herramientas

Las siguientes herramientas están disponibles para interactuar con el Catálogo de Servicios de ServiceNow:

### `manage_catalog(action="list_categories")`

Lista las categorías disponibles del catálogo de servicios.

**Parámetros:**
- `limit` (int, default: 10): Número máximo de categorías a devolver
- `offset` (int, default: 0): Desplazamiento para la paginación
- `query` (string, optional): Consulta de búsqueda para categorías
- `active` (boolean, default: true): Si solo se deben devolver categorías activas

**Ejemplo:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogCategoriesParams, list_catalog_categories

params = ListCatalogCategoriesParams(
    limit=5,
    query="hardware"
)
result = list_catalog_categories(config, auth_manager, params)
```

### `manage_catalog(action="list_items")`

Lista los elementos disponibles del catálogo de servicios.

**Parámetros:**
- `limit` (int, default: 10): Número máximo de elementos a devolver
- `offset` (int, default: 0): Desplazamiento para la paginación
- `category` (string, optional): Filtrar por categoría
- `query` (string, optional): Consulta de búsqueda para elementos
- `active` (boolean, default: true): Si solo se deben devolver elementos activos

**Ejemplo:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogItemsParams, list_catalog_items

params = ListCatalogItemsParams(
    limit=5,
    category="hardware",
    query="laptop"
)
result = list_catalog_items(config, auth_manager, params)
```

### `manage_catalog(action="get_item")`

Obtiene información detallada sobre un elemento específico del catálogo.

**Parámetros:**
- `item_id` (string, required): ID o sys_id del elemento del catálogo

**Ejemplo:**
```python
from servicenow_mcp.tools.catalog_tools import GetCatalogItemParams, get_catalog_item

params = GetCatalogItemParams(
    item_id="item123"
)
result = get_catalog_item(config, auth_manager, params)
```

## Recursos

Los siguientes recursos están disponibles para acceder al Catálogo de Servicios de ServiceNow:

### `catalog://items`

Lista los elementos del catálogo de servicios.

**Ejemplo:**
```
catalog://items
```

### `catalog://categories`

Lista las categorías del catálogo de servicios.

**Ejemplo:**
```
catalog://categories
```

### `catalog://{item_id}`

Obtiene un elemento específico del catálogo por ID.

**Ejemplo:**
```
catalog://item123
```

## Integración con Claude Desktop

Para usar el Catálogo de Servicios de ServiceNow con Claude Desktop:

1. Configure el servidor MCP de ServiceNow en Claude Desktop
2. Haga preguntas a Claude sobre el catálogo de servicios

**Ejemplos de indicaciones:**
- "¿Puedes listar las categorías disponibles del catálogo de servicios en ServiceNow?"
- "¿Puedes mostrarme los elementos disponibles en el catálogo de servicios de ServiceNow?"
- "¿Puedes listar los elementos del catálogo en la categoría Hardware?"
- "¿Puedes mostrarme los detalles del elemento del catálogo 'New Laptop'?"
- "¿Puedes encontrar elementos del catálogo relacionados con 'software' en ServiceNow?"
- "¿Puedes crear una nueva categoría llamada 'Cloud Services' en el catálogo de servicios?"
- "¿Puedes actualizar la categoría 'Hardware' para cambiarle el nombre a 'IT Equipment'?"
- "¿Puedes mover el elemento del catálogo 'Virtual Machine' a la categoría 'Cloud Services'?"
- "¿Puedes crear una subcategoría llamada 'Monitors' bajo la categoría 'IT Equipment'?"
- "¿Puedes reorganizar nuestro catálogo moviendo todos los elementos de software a la categoría 'Software'?"

## Scripts de ejemplo

### Prueba de integración

El script `examples/catalog_integration_test.py` demuestra cómo usar las herramientas del catálogo directamente:

```bash
python examples/catalog_integration_test.py
```

### Demostración con Claude Desktop

El script `examples/claude_catalog_demo.py` demuestra cómo usar la funcionalidad del catálogo con Claude Desktop:

```bash
python examples/claude_catalog_demo.py
```

## Modelos de datos

### CatalogItemModel

Representa un elemento del catálogo de ServiceNow.

**Campos:**
- `sys_id` (string): Identificador único del elemento del catálogo
- `name` (string): Nombre del elemento del catálogo
- `short_description` (string, optional): Descripción corta del elemento del catálogo
- `description` (string, optional): Descripción detallada del elemento del catálogo
- `category` (string, optional): Categoría del elemento del catálogo
- `price` (string, optional): Precio del elemento del catálogo
- `picture` (string, optional): URL de la imagen del elemento del catálogo
- `active` (boolean, optional): Si el elemento del catálogo está activo
- `order` (integer, optional): Orden del elemento del catálogo en su categoría

### CatalogCategoryModel

Representa una categoría del catálogo de ServiceNow.

**Campos:**
- `sys_id` (string): Identificador único de la categoría
- `title` (string): Título de la categoría
- `description` (string, optional): Descripción de la categoría
- `parent` (string, optional): ID de la categoría padre
- `icon` (string, optional): Icono de la categoría
- `active` (boolean, optional): Si la categoría está activa
- `order` (integer, optional): Orden de la categoría

### CatalogItemVariableModel

Representa una variable de un elemento del catálogo de ServiceNow.

**Campos:**
- `sys_id` (string): Identificador único de la variable
- `name` (string): Nombre de la variable
- `label` (string): Etiqueta de la variable
- `type` (string): Tipo de la variable
- `mandatory` (boolean, optional): Si la variable es obligatoria
- `default_value` (string, optional): Valor predeterminado de la variable
- `help_text` (string, optional): Texto de ayuda para la variable
- `order` (integer, optional): Orden de la variable
