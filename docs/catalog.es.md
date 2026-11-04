# Catálogo de servicios

Una sola herramienta, `manage_catalog`, cubre las categorías del catálogo de servicios (`sc_category`), los artículos (`sc_cat_item`) y las variables de artículo (`item_option_new`).

| Paquete | Acciones |
|---|---|
| `service_desk` | las cuatro acciones de lectura |
| `portal_developer`, `full` | todas las acciones |

Las acciones de escritura necesitan `confirm='approve'`, como cualquier escritura en este servidor.

## Acciones de lectura

| Acción | Argumentos | Devuelve |
|---|---|---|
| `action="list_categories"` | `limit`, `offset`, `query`, `active`, `count_only` | las categorías |
| `action="list_items"` | `limit`, `offset`, `query`, `category`, `active`, `count_only` | los artículos |
| `action="get_item"` | `item_id` | el artículo y sus variables |
| `action="list_item_variables"` | `catalog_item_id` | las variables: nombre, etiqueta, código de tipo, obligatoria, valor por defecto, orden |

Las dos acciones de listado devuelven:

- `count`: las filas de esta página.
- `total`: cuántas filas coinciden en el servidor.
- `more`: solo aparece cuando hay otra página, e indica el offset que hay que pedir a continuación.

Si el servidor no envía el total, la respuesta indica `total_unknown` en lugar de adivinarlo. Con `count_only=true` solo se devuelve el número.

## Acciones de escritura

| Acción | Obligatorio | Opcional |
|---|---|---|
| `action="create_category"` | `title` | `description`, `parent`, `icon`, `active`, `order` |
| `action="update_category"` | `category_id` y al menos un campo | los mismos campos que create |
| `action="update_item"` | `item_id` y al menos un campo | `name`, `short_description`, `description`, `category`, `price`, `active`, `order` |
| `action="move_items"` | `item_ids`, `target_category_id` | |
| `action="create_variable"` | `catalog_item_id`, `variable_name`, `variable_type`, `label` | `mandatory`, `help_text`, `default_value`, `description`, `order`, `reference_table`, `reference_qualifier`, `max_length`, `min`, `max` |
| `action="update_variable"` | `variable_id` y al menos un campo | `variable_name`, `variable_type`, `reference_table` y los campos opcionales de create |

### Tipos de variable

`item_option_new.type` guarda un número, no una palabra. Pasa el número o su etiqueta:

| Código | Etiqueta |
|---|---|
| `6` | Single Line Text |
| `2` | Multi Line Text |
| `5` | Select Box |
| `3` | Multiple Choice |
| `7` | CheckBox |
| `8` | Reference |
| `9` | Date |
| `10` | Date/Time |

Antes de escribir, la herramienta compara el valor con la lista de opciones de la propia instancia (`sys_choice`), así que también acepta las opciones añadidas en tu instancia. Un valor que no está en la lista se rechaza, y el rechazo enumera todos los códigos válidos. Si la lista de opciones no se puede leer, no se escribe nada.

### Longitud y rango

- `item_option_new` no tiene columna `max_length`. `max_length` se guarda en los `attributes` de la variable como `max_length=N`, igual que lo guarda la plataforma.
- `min` y `max` fijan `scale_min` y `scale_max`, el rango de una escala de valoración.

## Vistas previas

Puedes pasar `dry_run=true` en cualquier acción de escritura:

- `action="update_category"` y `action="update_item"` devuelven las diferencias campo a campo.
- Las demás acciones de escritura devuelven `would_send`: la petición exacta que se enviaría.

En ambos casos no se escribe nada. El servidor lo impone en todas las herramientas, así que una vista previa no puede convertirse en una escritura.

## Ejemplos de instrucciones

- "Lista las categorías del catálogo y cuántos artículos tiene cada una."
- "Muestra las variables del artículo 'New Laptop'."
- "Añade a ese artículo una variable Single Line Text obligatoria llamada 'asset_tag'. Primero una vista previa."
- "Mueve estos tres artículos a la categoría Hardware."
