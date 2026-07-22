# MFA ServiceNow MCP

🌐 [English](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md) | 🇰🇷 [한국어](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md) | 🇯🇵 [日本語](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ja.md) | 🇮🇳 [हिन्दी](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.hi.md) | 🇨🇳 [简体中文](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.zh.md) | 🇪🇸 [Español](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.es.md) | 🚀 [**GitHub Pages**](https://jshsakura.github.io/mfa-servicenow-mcp/)

Servidor MCP de ServiceNow centrado en MFA. Se autentica mediante un navegador real (Playwright), de modo que el inicio de sesión con Okta, Entra ID, SAML y cualquier MFA/SSO simplemente funciona. También admite API Key para entornos headless/Docker.

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-live-blue?logo=github)](https://jshsakura.github.io/mfa-servicenow-mcp/)

> [!WARNING]
> **Creado para uso personal — úsalo bajo tu propia responsabilidad.** Este proyecto se creó principalmente para los flujos de trabajo del propio autor. El riesgo se minimiza activamente (valores por defecto de solo lectura, guardas de escritura, vistas previas en dry-run y compuertas `confirm='approve'` en cada escritura), pero opera contra **instancias de ServiceNow en producción**. Eres el único responsable de lo que haga en tus instancias. Se proporciona **"tal cual", sin garantía de ningún tipo** (Apache-2.0, ver [LICENSE](LICENSE)). Revisa lo que hará una herramienta antes de aprobarla.

---

## Tabla de Contenidos

- [Características](https://github.com/jshsakura/mfa-servicenow-mcp#features)
- [Configuración](https://github.com/jshsakura/mfa-servicenow-mcp#setup)
- [Configuración del cliente MCP](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration)
- [Autenticación](https://github.com/jshsakura/mfa-servicenow-mcp#authentication)
- [Paquetes de herramientas](https://github.com/jshsakura/mfa-servicenow-mcp#tool-packages)
- [Referencia de la CLI](https://github.com/jshsakura/mfa-servicenow-mcp#cli-reference)
- [Mantenerse actualizado](https://github.com/jshsakura/mfa-servicenow-mcp#keeping-up-to-date)
- [Política de seguridad](https://github.com/jshsakura/mfa-servicenow-mcp#safety-policy)
- [Optimizaciones de rendimiento](https://github.com/jshsakura/mfa-servicenow-mcp#performance-optimizations)
- [Auditoría de fuentes locales](https://github.com/jshsakura/mfa-servicenow-mcp#local-source-audit)
- [Skills](https://github.com/jshsakura/mfa-servicenow-mcp#skills)
- [Docker](https://github.com/jshsakura/mfa-servicenow-mcp#docker)
- [Configuración para desarrolladores](https://github.com/jshsakura/mfa-servicenow-mcp#developer-setup)
- [Documentación](https://github.com/jshsakura/mfa-servicenow-mcp#documentation)
- [Proyectos relacionados](https://github.com/jshsakura/mfa-servicenow-mcp#related-projects-and-acknowledgements)
- [Licencia](https://github.com/jshsakura/mfa-servicenow-mcp#license)

---

## Configuración

Dos pasos: **instalar** y luego **añadir el servidor a la configuración de tu cliente MCP**. Sin comando de instalación, sin flags por cliente.

### 1. Instalar

Lo predeterminado es **`uvx`** — no hay paso de instalación aparte, simplemente se ejecuta. Para la mayoría de la gente esto es todo.

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

**Para actualizar** — uvx guarda en caché la última versión que descargó y la sigue reutilizando, así que una release nueva hay que traerla explícitamente con `--refresh`:

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium     # un Playwright más nuevo pide un build de Chromium más nuevo
```

#### Si uvx está bloqueado — `pip`

El Smart App Control de Windows impide directamente que uvx se ejecute: uvx descomprime un ejecutable temporal sin firmar en cada ejecución, y SAC lo bloquea. Si uvx dejó de funcionar de golpe justo después de una actualización de Windows, casi con seguridad es por esto. Usa pip en su lugar:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**Para actualizar:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Un Python del [instalador de python.org](https://www.python.org/downloads/) (firmado, 3.10+) pasa SAC tal cual. Arráncalo con `python -m servicenow_mcp` en lugar del script de consola `servicenow-mcp`: ese script es un `.exe` sin firmar que genera pip, y SAC también lo bloquea.

> En mac/Linux la única pega de pip es que los Python de Homebrew y de la distribución rechazan las instalaciones globales por el [PEP 668](https://peps.python.org/pep-0668/) (`externally-managed-environment`). Usa el instalador de python.org, o simplemente quédate en uvx.

Instalar Chromium **por adelantado** importa en ambos casos. Dejarlo para la primera llamada a una herramienta significa una descarga de ~150 MB compitiendo con el plazo del handshake del host MCP, lo que se manifiesta como `connection closed`.

> **Configuración guiada.** Ejecutar `servicenow-mcp setup` sin flags (con pip: `python -m servicenow_mcp setup`) te guía a través de menús numerados (elige clientes y tipo de autenticación por número o nombre — sin adivinar texto libre), en inglés o coreano (autodetectado a partir de tu configuración regional; fuérzalo con `SERVICENOW_MCP_LANG=ko|en`).

### 2. Configura tu cliente MCP

Añade el servidor al archivo de configuración de tu cliente. **El bloque `env` es idéntico sin importar cómo hayas instalado** — solo `command`/`args` siguen la ruta que elegiste arriba:

| Instalación | `command` | `args` |
|---|---|---|
| uvx (predeterminado) | `uvx` | `["--with","playwright","--from","mfa-servicenow-mcp","servicenow-mcp"]` |
| pip | `python` | `["-m","servicenow_mcp"]` |

Solo se requieren dos variables de entorno; `MCP_TOOL_PACKAGE` tiene el valor por defecto `standard`, así que omítelo a menos que necesites un paquete diferente.

#### Una sola instancia

Si solo usas una instancia, con esto ya está todo.

**Claude Code** — `.mcp.json` (raíz del proyecto) / `~/.claude.json` (global):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Si instalaste con pip, cambia `command`/`args` por esto — todo lo demás se queda igual:

```json
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
```

**Codex** — `.codex/config.toml` (proyecto) / `~/.codex/config.toml` (global):

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
# pip: command = "python"  /  args = ["-m", "servicenow_mcp"]

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
```

**OpenCode** — `opencode.json` (raíz del proyecto):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Otros clientes (Cursor, VS Code, Antigravity, Zed, …) y las opciones completas de entorno (tipos de autenticación, paquetes de herramientas) están en [Configuración del cliente MCP](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration).

Luego reinicia el cliente. La primera llamada a una herramienta de navegador abre una ventana para el inicio de sesión con Okta/Entra ID/SAML/MFA. Las sesiones persisten — sin tener que volver a iniciar sesión cada vez.

#### Múltiples instancias (dev / test / prod)

Si trabajas con dev / test / prod, **no levantes varios servidores.** Cambiando solo `env`, una única conexión puede con todas:

```json
      "env": {
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"prod\": { \"url\": \"https://acme.service-now.com\", \"auth_type\": \"browser\" } }"
      }
```

Lo único que cambia es que una lista de alias ocupa el lugar de `SERVICENOW_INSTANCE_URL`; `command`/`args` siguen igual. Con esto:

- **Producción queda protegida por defecto** — un alias sin `allow_writes` es de solo lectura. En el ejemplo de arriba, en `prod` no se puede escribir en absoluto.
- **Consulta otra instancia sin reiniciar** — pasa `instance` a una herramienta de lectura, como en `sn_query(instance="prod", ...)`.
- **Compara entre instancias** — `compare_instances` enfrenta el mismo componente de dev y de prod.
- **Un solo inicio de sesión** — la sesión del navegador se comparte entre alias.

Las reglas completas (enrutado de escrituras, guardas, referencias `${ENV}`) están en [Múltiples instancias — dos enfoques](#perfiles-vs-multiproceso). Solo recurre allí a **B. Multiproceso** si necesitas que las conexiones se vean separadas en la interfaz de tu cliente.

> ¿Prefieres que lo haga una IA? Pega esto en Claude Code / Cursor / Codex / etc.:
> `Install and configure mfa-servicenow-mcp following https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md`

### Si tu red corporativa bloquea la instalación

Los proxies con inspección TLS (Zscaler y compañía) y el acceso bloqueado a PyPI tienen su propia ruta — consulta [Instalación (sin conexión / corporativa)](#instalación-sin-conexión--corporativa).

---

## Características

- **Autenticación por navegador** para entornos MFA/SSO (Okta, Entra ID, SAML, MFA)
- **4 modos de autenticación**: Browser, Basic, OAuth, API Key
- **65 herramientas registradas** con **6 perfiles de paquete activos** más el `none` deshabilitado — desde el mínimo de solo lectura hasta CRUD agrupado de amplio alcance
- **16 skills de flujo de trabajo** con compuertas de seguridad, delegación a sub-agentes y pipelines verificados
- **Transporte Streamable HTTP** — mantén stdio como predeterminado, o expón `/mcp` para clientes y puentes con capacidad HTTP
- **Auditoría de fuentes locales** con informe HTML, grafo de referencias cruzadas, detección de código muerto y conocimiento de dominio autogenerado
- **Grafos de relaciones autoritativos en disco** — `_graph.json` (widget→Angular Provider, desde el M2M en vivo) y `_page_graph.json` (página→widget, desde `sp_instance`) permiten al LLM responder preguntas de dependencia sin conexión en lugar de volver a consultar la instancia
- **Sincronización incremental** (`incremental=True`) — vuelve a descargar solo los registros cambiados desde la última sincronización (marca de agua `sys_updated_on`), como `git pull`; `reconcile_deletions=True` señala los registros eliminados en la instancia
- **Resolución automática de dependencias entre ámbitos (cross-scope)** en `download_app_sources` — extrae Script Includes, Widgets, Angular Providers y UI Macros del ámbito global que la aplicación referencia, de modo que el paquete local sea autocontenido para el análisis
- **Descarga de adjuntos** (`download_attachment`) — obtén los archivos adjuntos de un registro (xlsx, PDF, Word, …) en disco local por el sys_id del adjunto o por el `table`+`record` padre; resuelve automáticamente los adjuntos de un registro y escribe los bytes en disco para que el LLM los lea desde `saved_path`
- **Vista previa en dry-run** en cada herramienta de escritura (`dry_run=True`) — devuelve el diff a nivel de campo, recuentos de dependencias y notas de precisión antes de cualquier efecto secundario. Usa APIs de solo lectura, funciona en todos los modos de autenticación.
- Confirmación segura de escritura con `confirm='approve'`
- Límites de seguridad de payload, truncado por campo y presupuesto total de respuesta (200K caracteres)
- Reintento con backoff ante errores de red transitorios
- Paquetes de herramientas para core, standard, service desk, desarrolladores de portal y desarrolladores de plataforma — `full` disponible para usuarios avanzados (ver [advertencia](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md))
- Herramientas de productividad para desarrolladores: seguimiento de actividad, cambios no confirmados, mapeo de dependencias, resumen diario
- Cobertura completa de las tablas de artefactos centrales de ServiceNow (ver [Tablas compatibles](https://github.com/jshsakura/mfa-servicenow-mcp#supported-servicenow-tables))
- CI/CD con etiquetado automático, publicación en PyPI y builds multiplataforma de Docker

### Tablas de ServiceNow compatibles

| Tipo de artefacto | Nombre de tabla | Búsqueda de fuente | Seguimiento de desarrollador | Seguridad (tabla pesada) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_script_client` | ✅ | ✅ | 🛡️ |
| Catalog Client Script | `catalog_script_client` | ✅ | ⬜ | ⬜ |
| UI Action | `sys_ui_action` | ✅ | ✅ | 🛡️ |
| UI Script | `sys_ui_script` | ✅ | ✅ | 🛡️ |
| UI Page | `sys_ui_page` | ✅ | ✅ | 🛡️ |
| UI Macro | `sys_ui_macro` | ✅ | ⬜ | 🛡️ |
| Scripted REST API | `sys_ws_operation` | ✅ | ✅ | 🛡️ |
| Fix Script | `sys_script_fix` | ✅ | ✅ | 🛡️ |
| Scheduled Job | `sysauto_script` | ✅ | ⬜ | ⬜ |
| Script Action | `sysevent_script_action` | ✅ | ⬜ | ⬜ |
| Email Notification | `sysevent_email_action` | ✅ | ⬜ | ⬜ |
| ACL | `sys_security_acl` | ✅ | ⬜ | ⬜ |
| Transform Script | `sys_transform_script` | ✅ | ⬜ | ⬜ |
| Processor | `sys_processor` | ✅ | ⬜ | ⬜ |
| Service Portal Widget | `sp_widget` | ✅ | ✅ | 🛡️ |
| Angular Provider | `sp_angular_provider` | ✅ | ✅ | ⬜ |
| Portal Header/Footer | `sp_header_footer` | ✅ | ⬜ | ⬜ |
| Portal CSS | `sp_css` | ✅ | ⬜ | ⬜ |
| Angular Template | `sp_ng_template` | ✅ | ⬜ | ⬜ |
| Metadata / XML Definitions | `sys_metadata` | ✅ | ⬜ | 🛡️ |
| Update XML | `sys_update_xml` | ✅ | ⬜ | ⬜ |

---

## Instalación (sin conexión / corporativa)

Para la mayoría de los usuarios, la [Configuración](https://github.com/jshsakura/mfa-servicenow-mcp#setup) de arriba (uvx) es todo lo que necesitas. Hay dos casos de red corporativa que conviene aclarar.

El caso habitual es **PyPI accesible, pero con HTTPS bajo inspección TLS** (Zscaler / Netskope / MITM corporativo), que es justo lo que cubre la sección de abajo.

Si PyPI está bloqueado por completo, ni uvx ni pip pueden llegar al paquete. Pide a tu equipo de IT que añada `pypi.org` y `files.pythonhosted.org` a la lista de permitidos, o que replique el paquete en un índice interno al que puedas apuntar con `pip install --index-url`.

### Instalar detrás de un proxy con inspección TLS (Zscaler, etc.)

Usa esto cuando PyPI **sí** sea accesible pero un proxy con inspección TLS vuelve a firmar HTTPS, de modo que las instalaciones y las llamadas en runtime fallan con `SSL: CERTIFICATE_VERIFY_FAILED`. Registrar la CA raíz del proxy en el **almacén de confianza del SO no es suficiente** — Python (`pip`, `requests`, `httpx`), `curl_cffi` y Playwright incluyen cada uno su propio bundle de CA (certifi / libcurl / node) e ignoran el almacén del SO a menos que los apuntes al certificado mediante variables de entorno.

**1. Obtén la CA raíz del proxy** como archivo PEM (pídela a TI, o expórtala desde el llavero del SO). Supongamos que queda en `/etc/ssl/zscaler-root.pem` (Windows: `C:\certs\zscaler-root.pem`).

**2. Instala** — apunta el instalador al certificado:

```bash
pip install --cert /etc/ssl/zscaler-root.pem mfa-servicenow-mcp
python -m playwright install chromium     # NODE_EXTRA_CA_CERTS (step 3) covers its download
```

¿Prefieres uvx? `uv` puede usar directamente el almacén de confianza del SO (donde la CA del proxy ya está registrada):

```bash
UV_NATIVE_TLS=1 uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
```

**3. Runtime — establece la ruta de la CA en el `env` de tu cliente MCP.** La parte no obvia: las llamadas en vivo a ServiceNow pasan por **curl_cffi (libcurl)**, que lee `CURL_CA_BUNDLE` — *no* `REQUESTS_CA_BUNDLE`. Establécelas todas para que cada capa confíe en el proxy:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "CURL_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "REQUESTS_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "SSL_CERT_FILE": "/etc/ssl/zscaler-root.pem",
        "NODE_EXTRA_CA_CERTS": "/etc/ssl/zscaler-root.pem"
      }
    }
  }
}
```

| Variable de entorno | Capa que corrige |
|---------|----------------|
| `CURL_CA_BUNDLE` | **curl_cffi / libcurl — las llamadas reales a la API de ServiceNow + la sonda de inicio de sesión por navegador** |
| `REQUESTS_CA_BUNDLE` | `requests` (llamadas de token OAuth / API-key, ruta HTTP de respaldo) |
| `SSL_CERT_FILE` | `ssl` de la stdlib de Python / `httpx` / `uv` |
| `NODE_EXTRA_CA_CERTS` | descarga de Chromium de Playwright |
| `PIP_CERT` (solo instalación) | `pip` descargando desde PyPI (igual que `--cert`) |

En una red totalmente inspeccionada, el proxy vuelve a firmar cada host, por lo que el único PEM de la raíz del proxy cubre todo HTTPS. Si algunos hosts **omiten** el proxy, concatena la raíz del proxy con el bundle de certifi (`python -m certifi` imprime su ruta) en un solo PEM y apunta las variables de entorno a ese.

> Último recurso si realmente no puedes obtener el PEM: `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org mfa-servicenow-mcp` omite la verificación **solo para la instalación** — no hace nada para las llamadas en runtime a ServiceNow, que siguen necesitando `CURL_CA_BUNDLE`. Prefiere la ruta del certificado; `--trusted-host` deshabilita un control de seguridad.

## Configuración del cliente MCP

> Recomendado: usa la [Configuración](https://github.com/jshsakura/mfa-servicenow-mcp#setup) de arriba. Usa las configuraciones de copiar y pegar de abajo cuando necesites inspeccionar, reparar o gestionar manualmente un archivo de configuración de cliente.

Cada proyecto puede conectarse a una instancia de ServiceNow diferente. Establece la configuración en tu **directorio de proyecto** para que cada proyecto tenga su propia URL de instancia y credenciales.

| Cliente | Configuración de proyecto | Configuración global | Formato |
|--------|---------------|--------------|--------|
| Claude Code | `.mcp.json` | `~/.claude.json` | JSON |
| Cursor | `.cursor/mcp.json` | *Solo proyecto* | JSON |
| VS Code (Copilot) | `.vscode/mcp.json` | *Solo proyecto* | JSON |
| Zed | *Solo global* | `~/.config/zed/settings.json` | JSON |
| OpenAI Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML |
| OpenCode | `opencode.json` | *Solo proyecto* | JSON |
| Windsurf | *Solo global* | `~/.codeium/windsurf/mcp_config.json` | JSON |
| Claude Desktop | *Solo global* | `claude_desktop_config.json` | JSON |
| AntiGravity | *Solo global* | `~/.gemini/antigravity/mcp_config.json` | JSON |
| Docker | *Solo variables de entorno* | *Solo variables de entorno* | Variables de entorno |

Configuraciones de copiar y pegar para cada cliente: **[Guía de configuración de clientes](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` son opcionales — pre-rellenan el formulario de inicio de sesión MFA. En Windows, establécelas como variables de entorno del sistema.

#### Perfiles vs. multiproceso

Los ejemplos de arriba son de instancia única — eso sigue siendo el valor por defecto. Con más de una instancia hay dos caminos posibles, y conviene **elegir uno antes de configurar nada:**

| | **A. Perfiles** (recomendado) | **B. Multiproceso** |
|---|---|---|
| Procesos del servidor | 1 | uno por instancia |
| Conexiones que ve el cliente | 1 | 3 |
| Elegir instancia | `instance="test"` en cada llamada | fijada al proceso |
| Comparación entre instancias | **funciona** (`compare_instances`) | imposible — los procesos no se conocen entre sí |
| Inicio de sesión del navegador | una sesión compartida | un inicio de sesión por proceso |
| Control de escritura | `allow_writes` por alias | configuración por proceso |

**La mayoría quiere A.** Ahí la seguridad de escritura ya está resuelta: deja `allow_writes` fuera del alias de producción y queda en solo lectura, y las escrituras a una instancia no activa tienen que pasar la compuerta `confirm_instance`. Además, solo A te da comparación entre instancias y un único inicio de sesión.

**Elige B únicamente cuando las conexiones tengan que verse separadas en la interfaz del cliente.** Los nombres de las herramientas llegan como `mcp_snow-prd_*`, así que una persona las distingue de un vistazo. El precio son tres inicios de sesión, ninguna comparación y tres copias de la configuración. Detalles: [Distinguir varias conexiones](#distinguir-varias-conexiones---server-name).

##### A. Perfiles

Para alternar entre varias instancias desde un solo cliente, lístalas en `SERVICENOW_INSTANCE_CONFIG` (alias → configuración) y elige la activa con `SERVICENOW_ACTIVE_INSTANCE`. Cada alias puede llevar sus **propias credenciales** (`username` / `password` / `auth_type` / `api_key`); las referencias `${ENV}` mantienen los secretos fuera del JSON. La forma de instancia única `SERVICENOW_INSTANCE_URL` sigue funcionando como respaldo.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

`SERVICENOW_ACTIVE_INSTANCE` es el destino por defecto de las escrituras; las herramientas de lectura echan un vistazo a las demás con `instance="test"`, y una sola escritura puede enrutarse a una instancia no activa con `instance="test" confirm_instance="test" confirm="approve"` (con guarda, y verificada tras aplicarse). Reglas completas (enrutamiento de escritura, control, comparación, `${ENV}`): [Modo Multi-Instancia](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.es.md#modo-multi-instancia-comparación--escrituras-guardadas-de-una-sola-llamada).

##### B. Multiproceso

Solo merece la pena cuando quieres las conexiones separadas en la interfaz del cliente. Cada entrada **fija una instancia** y recibe su propio nombre con `--server-name`:

```json
{
  "mcpServers": {
    "snow-dev": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-dev"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme-dev.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    },
    "snow-prd": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-prd"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

Los nombres de las herramientas quedan entonces fijados a `mcp_snow-dev_*` / `mcp_snow-prd_*`. Sin `--server-name`, ambos se anuncian como `ServiceNow`, así que el cliente los numera por orden de carga (`mcp_servicenow`, `mcp_servicenow2`) — y esa numeración puede cambiar entre reinicios, con lo que nunca puedes fiarte de cuál es producción.

Para mantener la conexión de producción en solo lectura, dale un `MCP_TOOL_PACKAGE` de solo lectura. A diferencia de A, aquí no hay compuerta `allow_writes` por alias — **el paquete de herramientas es lo único que bloquea las escrituras.**

> Los avisos de inicio de sesión salen por proceso, y las herramientas entre instancias como `compare_instances` no están disponibles: cada proceso solo conoce su propia instancia. Si eso te estorba, usa A.

---

## Autenticación

Elige el modo de autenticación según tu entorno de ServiceNow.

### Autenticación por navegador (MFA/SSO) — Predeterminado

El comando de [Configuración](https://github.com/jshsakura/mfa-servicenow-mcp#setup) usa la autenticación por navegador por defecto. Flags opcionales:

| Flag | Variable de entorno | Predeterminado | Descripción |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | Pre-rellena el nombre de usuario del formulario de inicio de sesión |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | Pre-rellena la contraseña del formulario de inicio de sesión |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | Ejecuta el navegador sin GUI |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | Tiempo de espera de inicio de sesión en segundos |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | TTL de sesión en minutos |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Sobrescribe la ruta del perfil de Chromium. Rara vez es necesario — consulta la nota sobre el sandbox de abajo antes de establecerlo. |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | búsqueda de `sys_user` específica del usuario cuando se conoce un nombre de usuario, de lo contrario `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | Endpoint de validación de sesión (evita 401 en sesiones de no administrador) |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | URL de página de inicio de sesión personalizada |

#### Compartir el inicio de sesión entre hosts e instancias — cómo funciona realmente

El servidor almacena en caché dos cosas en `~/.mfa_servicenow_mcp/`: el perfil de Playwright (cookies SSO de Chromium) y un JSON de sesión (cookies analizadas reutilizadas en el siguiente arranque). Ambos están **delimitados por instancia + nombre de usuario** — los archivos se nombran `profile_<host>_<user>` y `session_<host>_<user>.json`.

Esa delimitación hace dos cosas por ti automáticamente, **sin configuración**:

- **Múltiples hosts comparten un inicio de sesión.** Claude Code y Codex en la misma máquina resuelven ambos a `~/.mfa_servicenow_mcp/`, así que el primero que inicie sesión escribe la sesión y el otro la reutiliza — sin un segundo aviso de MFA.
- **Diferentes instancias / diferentes credenciales permanecen aisladas.** Cada instancia+usuario obtiene su propio archivo de perfil y de sesión, de modo que dev y test (o dos cuentas) nunca colisionan. Para múltiples instancias, configúralas en `SERVICENOW_INSTANCE_CONFIG` (JSON) — cada alias obtiene su propia caché delimitada; **no** gestionas esto con una ruta de perfil.

**No establezcas `SERVICENOW_BROWSER_USER_DATA_DIR` para "compartir" inicios de sesión.** Sobrescribe la ruta del perfil tal cual — la delimitación por instancia se omite, por lo que cada instancia que ejecutes se ve forzada a un único perfil de Chromium y sus cookies colisionan. El único uso legítimo es uno muy concreto: un host **en sandbox** (p. ej. Claude Desktop en macOS) que reasigna `HOME` a una ruta de contenedor, de modo que su `~/.mfa_servicenow_mcp/` ya no coincide con el del terminal. En ese caso de instancia única, apunta el host en sandbox a la ruta real del home:

```bash
# Only when a sandbox remapped HOME, and only for a single-instance host
export SERVICENOW_BROWSER_USER_DATA_DIR="/Users/you/.mfa_servicenow_mcp/profile_acme"
```

Si ejecutas más de una instancia, deja esto sin establecer y deja que la delimitación por instancia haga su trabajo.

### Autenticación Basic

Usa esto para PDIs o instancias sin MFA.

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth

El soporte actual de la CLI espera entradas de OAuth password grant.

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

Si se omite `--token-url`, el servidor usa por defecto `https://<instance>/oauth_token.do`.

### API Key

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

Encabezado predeterminado: `X-ServiceNow-API-Key` (personalizable con `--api-key-header`).

---

## Paquetes de herramientas

`MCP_TOOL_PACKAGE` controla qué herramientas expone el servidor. **Predeterminado: `standard`** — sin configuración necesaria para la mayoría de los usuarios.

> [!WARNING]
> **Cualquier paquete superior a `standard` otorga acceso de escritura y es una opción avanzada.** `service_desk`, `portal_developer`, `platform_developer` y `full` permiten todos que un agente de IA cree, actualice y elimine registros — `full` lo hace en todos los dominios a la vez. La mayoría de los usuarios deberían quedarse en el predeterminado de solo lectura `standard` y solo subir al paquete de escritura más reducido que su tarea realmente requiera.

Solo lectura (valores predeterminados seguros):

| Paquete | Herramientas | Descripción |
| :--- | :---: | :--- |
| `none` | 0 | Perfil deshabilitado para desactivar herramientas intencionadamente |
| `core` | 12 | Mínimo de solo lectura para salud, esquema, descubrimiento y búsquedas clave de artefactos |
| `standard` | 27 | **(Predeterminado)** Solo lectura en incidentes, cambios, portal, registros y análisis de fuentes |

⚠️ Con capacidad de escritura (avanzado — otorga create/update/delete):

| Paquete | Herramientas | Descripción |
| :--- | :---: | :--- |
| `service_desk` | 29 | ⚠️ standard + escrituras operativas de incidentes y cambios |
| `portal_developer` | 38 | ⚠️ standard + escrituras de portal, changeset, script include y entrega de sincronización local |
| `platform_developer` | 43 | ⚠️ standard + escrituras de workflow, Flow Designer, UI policy, incidentes/cambios y scripts |
| `full` | 57 | ⚠️ **El más avanzado** — todas las herramientas de escritura en todos los dominios a la vez |

Cada proceso de servidor se vincula a una instancia de ServiceNow activa para las herramientas ordinarias. Una escritura hacia una instancia configurada *distinta* es posible por llamada, pero solo mediante un reconocimiento explícito y guardado (abajo) — nunca un cambio silencioso.

### Modo Multi-Instancia (comparación + escrituras guardadas de una sola llamada)

Cuando necesites comparar dev/test/prod o desplegar en una de ellas, opta por instancias con nombre con `SERVICENOW_INSTANCE_CONFIG`. `SERVICENOW_ACTIVE_INSTANCE` sigue siendo obligatorio.

Dos cosas son globales, una es por instancia:

- **La superficie de herramientas es global** — se establece una vez con `MCP_TOOL_PACKAGE`. Solo una instancia está activa por proceso de servidor, por lo que no hay paquete de herramientas por instancia.
- **El permiso de escritura es por instancia** — cada alias lleva `allow_writes`. Se aplica en el momento de la llamada contra la instancia activa: una herramienta de escritura puede cargarse pero aun así rechazarse si la instancia activa tiene `allow_writes: false`. Las escrituras son opt-in: omite `allow_writes` y la instancia será de solo lectura.
- **Las credenciales son por instancia con respaldo global** — pon `username` / `password` / `api_key` (y `auth_type`) en un alias para sobrescribir; omítelas y el alias hereda los `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` / etc. globales. Así que si todas las instancias comparten un inicio de sesión, establécelo una vez globalmente y deja las entradas de alias sin credenciales.

Otras reglas:

- **Las herramientas de lectura aceptan un argumento `instance`** para ejecutar una sola lectura contra una instancia no activa — p. ej. `sn_query(instance="test", table="incident", ...)` o `sn_health(instance="test")` mientras `dev` permanece activa. Cada herramienta de lectura de tu paquete lo expone en su esquema (enum de los alias configurados). Así es como echas un vistazo a los datos de otra instancia sin reiniciar.
- **Una sola escritura puede enrutarse a una instancia no activa**, pero nunca de forma silenciosa. Pasa `instance="test" confirm_instance="test" confirm="approve"` (el destino nombrado dos veces — como intención y como reconocimiento) y el destino debe tener `allow_writes=true`. Solo esa escritura se enruta allí; la instancia activa se restaura inmediatamente después. Un desajuste entre destino/confirm o un destino de solo lectura se rechaza con un mensaje explícito, de modo que una confusión entre dev/test/prod no puede acabar en la instancia equivocada. Luego la escritura se vuelve a leer en el destino y se informa como `landed` (o `WRITE_NOT_LANDED`), con `target_instance` incluido — «éxito» significa que se ha confirmado que el contenido está presente en la instancia prevista, no solo un 200.
- `list_instances` informa de los alias configurados más el activo y el indicador de escritura de cada uno. `compare_instances` realiza comparaciones de tablas de solo lectura entre alias.
- Cambiar la instancia activa *por defecto* requiere reiniciar el cliente MCP — se lee una vez al arrancar el servidor, no se refresca en vivo. (El enrutamiento por llamada con `instance=` de arriba no necesita reinicio.)

Ejemplo — inicio de sesión global compartido, control de escritura por instancia:

```bash
export MCP_TOOL_PACKAGE=standard
export SERVICENOW_USERNAME=svc_account
export SERVICENOW_PASSWORD='...'
export SERVICENOW_ACTIVE_INSTANCE=dev
export SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "allow_writes": false }
}'
```

Para darle a una instancia su propio inicio de sesión en su lugar, añade los campos a ese alias (una referencia `${ENV}` se resuelve, por lo que puedes mantener los secretos fuera del JSON):

```json
"prod": { "url": "https://acme.service-now.com", "username": "prod_user", "password": "${SERVICENOW_PROD_PASSWORD}" }
```

Usa `compare_instances` para comprobaciones de drift entre dev/test. Para promover MUCHOS registros (especialmente tablas de Service Portal / scoped), prefiere un Update Set (commit en el origen, retrieve + commit en el destino desde la UI) antes que escrituras cross-instance registro por registro — así evita los ACL por tabla/SP que sí bloquean una sola escritura de la Table API.

Si una herramienta no está disponible en tu paquete actual, el servidor te indica qué paquete la incluye.

Para la referencia completa (todos los paquetes, detalles de herencia, sintaxis de configuración): [Guía avanzada de paquetes de herramientas](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md).

---

## Referencia de la CLI

### Opciones del servidor

| Flag | Variable de entorno | Predeterminado | Descripción |
|------|-------------|---------|-------------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *requerido* | URL de la instancia de ServiceNow |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | Modo de autenticación: `basic`, `oauth`, `api_key`, `browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | Paquete de herramientas a cargar |
| `--server-name` | `SERVICENOW_MCP_SERVER_NAME` | `ServiceNow` | Nombre del servidor MCP anunciado al cliente |
| `--transport` | `SERVICENOW_MCP_TRANSPORT` | `stdio` | Transporte MCP: `stdio` o `http` |
| `--http-host` | `SERVICENOW_MCP_HTTP_HOST` | `127.0.0.1` | Host para `--transport http` |
| `--http-port` | `SERVICENOW_MCP_HTTP_PORT` | `8000` | Puerto para `--transport http` |
| `--http-path` | `SERVICENOW_MCP_HTTP_PATH` | `/mcp` | Ruta del endpoint Streamable HTTP |
| `--http-allowed-hosts` | `SERVICENOW_MCP_HTTP_ALLOWED_HOSTS` | hosts de loopback | Lista de permitidos de Host separada por comas para protección contra DNS rebinding |
| `--http-disable-dns-rebinding-protection` | `SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | Deshabilita la protección contra DNS rebinding detrás de controles de red de confianza |
| `--http-json-response` | `SERVICENOW_MCP_HTTP_JSON_RESPONSE` | `false` | Devuelve respuestas JSON en lugar de streams SSE |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | Tiempo de espera de solicitud HTTP (segundos) |
| `--debug` | `SERVICENOW_DEBUG` | `false` | Habilita el registro de depuración |

Ejemplo de transporte HTTP:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

El endpoint MCP es `http://127.0.0.1:8000/mcp`; `/health` devuelve una respuesta de salud ligera.

#### Distinguir varias conexiones (`--server-name`)

Si registras **varias entradas de servidor** en un mismo cliente (dev / stg / prd como procesos separados), todas usan por defecto el nombre `ServiceNow`, así que el cliente las desambigua por orden de carga — `mcp_servicenow`, `mcp_servicenow2`, `mcp_servicenow3`. Esa numeración puede cambiar entre reinicios, lo que la vuelve **poco fiable para saber cuál es producción.** Mejor dale nombre a cada conexión:

```bash
servicenow-mcp --server-name snow-prd          # uvx / script de consola
python -m servicenow_mcp --server-name snow-prd # pip
```

El espacio de nombres de las herramientas queda entonces fijado a `mcp_snow-prd_*`. `SERVICENOW_MCP_SERVER_NAME` hace lo mismo como variable de entorno, y el flag gana si se establecen ambos. Sin establecer, se queda en `ServiceNow`, así que las configuraciones existentes siguen funcionando.

> ¿Lo que buscas es cambiar de instancia dentro de **un solo** servidor? Eso es el [Modo Multi-Instancia](#modo-multi-instancia-comparación--escrituras-guardadas-de-una-sola-llamada), no esto. Son cosas distintas — `--server-name` es el nombre que ve el cliente, mientras que un alias multi-instancia nombra una instancia dentro de un mismo proceso.

### Autenticación Basic

| Flag | Variable de entorno |
|------|-------------|
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### OAuth

| Flag | Variable de entorno |
|------|-------------|
| `--client-id` | `SERVICENOW_CLIENT_ID` |
| `--client-secret` | `SERVICENOW_CLIENT_SECRET` |
| `--token-url` | `SERVICENOW_TOKEN_URL` |
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### API Key

| Flag | Variable de entorno | Predeterminado |
|------|-------------|---------|
| `--api-key` | `SERVICENOW_API_KEY` | — |
| `--api-key-header` | `SERVICENOW_API_KEY_HEADER` | `X-ServiceNow-API-Key` |

### Ejecución de scripts

| Flag | Variable de entorno |
|------|-------------|
| `--script-execution-api-resource-path` | `SCRIPT_EXECUTION_API_RESOURCE_PATH` |

---

## Mantenerse actualizado

Elige el que corresponda a cómo instalaste (los mismos comandos están en la [sección de instalación](#1-instalar)):

```bash
# uvx — guarda en caché la última versión que descargó, así que --refresh es la forma de traer una nueva
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

```powershell
# pip
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

En ambos casos Chromium se refresca junto con lo demás, porque un Playwright más nuevo quiere un build de Chromium distinto (ver más abajo).

Después de refrescar, **reinicia tu cliente MCP** (Claude Code, Cursor, etc.) para cargar la nueva versión.

Consulta la versión actual:

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp --version   # uvx
python -m servicenow_mcp --version                       # pip
```

### Por qué hay que instalar Chromium por adelantado

Una nueva release de Playwright quiere un build de Chromium distinto. Si lo dejas estar, la *primera* llamada a una herramienta de navegador tiene que descargar ~150 MB de binarios del navegador — lo que en una conexión lenta supera el tiempo de espera del handshake del host MCP y se manifiesta como:

```text
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

Por eso los comandos de actualización de arriba ejecutan `playwright install chromium` cada vez.

> **Por qué ya no auto-instalamos Chromium dentro del servidor MCP:** esa descarga solía ejecutarse durante la primera llamada a una herramienta. En una conexión lenta, el subproceso sobrevivía al plazo del handshake del host y el cliente reportaba "connection closed". v1.13.1 cambió esto — el servidor MCP ahora solo *avisa* si falta Chromium. Instálalo por adelantado (fuera de banda, sin temporizador de handshake).

---

## Política de seguridad

Todas las herramientas que mutan están protegidas por confirmación explícita.

Reglas:
1. Las herramientas que mutan con prefijos como `create_`, `update_`, `delete_`, `remove_`, `add_`, `move_`, `activate_`, `deactivate_`, `commit_`, `publish_`, `submit_`, `approve_`, `reject_`, `resolve_`, `reorder_` y `execute_` requieren confirmación.
2. Debes pasar `confirm='approve'`.
3. Sin ese parámetro, el servidor rechaza la solicitud antes de su ejecución.

Esta política se aplica independientemente del paquete de herramientas seleccionado.

### Guardas de escritura

Más allá de la compuerta de confirmación, cada escritura pasa por guardas deterministas que bloquean escrituras inseguras *antes* de que lleguen a ServiceNow. Las comprobaciones de edición concurrente y de creación duplicada se ejecutan **después** de la compuerta de confirmación, por lo que una escritura no confirmada nunca toca la red. Cada guarda falla **en abierto** ante una pre-lectura denegada/fallida — nunca bloquea una escritura legítima solo porque no pudo mirar primero. La intención es simple: **nunca deberías poder pisar silenciosamente el cambio de un compañero** — si otra persona tocó el registro, la escritura se detiene y te lo dice, en lugar de sobrescribir y seguir adelante.

| Guarda | Protege contra | Anulación / interruptor |
|---|---|---|
| Edición concurrente (G3/G8) | Sobrescribir a ciegas un registro que un **usuario diferente** editó en los últimos 10 min. Cubre `sn_write`, `manage_portal_component` y las herramientas de actualización `manage_*` — incluyendo `manage_script_include`, `manage_flow_designer`, `manage_workflow`, `manage_kb_article`, `manage_portal_layout` y `manage_widget_dependency`. Se decide mediante una **lectura remota en vivo** de `sys_updated_by`/`sys_updated_on` — nunca la copia local. | `SERVICENOW_CONCURRENT_EDIT_GUARD=off`; ventana mediante `SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN` (predeterminado `10`) |
| Drift de push de fuente (baseline + HOLD de update-set) | Volver a empujar la fuente editada con `update_remote_from_local` añade dos comprobaciones que la ventana de tiempo no puede captar: una comparación **independiente del tiempo** del `sys_updated_on` actual del remoto contra el valor registrado en la descarga (capta una sobrescritura horas o **días** después), y una comprobación en vivo de que el registro esté **retenido en el update set sin confirmar de otro usuario**. | `force=true` para empujar más allá de un drift detectado |
| Creación duplicada (G9) | Crear silenciosamente un segundo registro con un nombre que ya existe, en tablas que ServiceNow no hace únicas (`sys_update_set`, `wf_workflow`, `sys_user_group`, `sys_user`). | pasa `allow_duplicate='true'` para crear de todos modos |
| Escritura cruda de Flow Designer (G6) | `sn_write` cruda a tablas `sys_hub_*` que corrompen los snapshots de flujo — fuerza `manage_flow_designer`. | — |
| Clase de publicación (G7) | Publicación/commit/push accidental — necesita un segundo `confirm_publish='approve'`. | — |
| Push entre instancias | Empujar fuente local descargada de la instancia A hacia la instancia B (origen leído de `_settings.json` / `_manifest.json`). | vuelve a descargar desde la instancia correcta |

Deshabilita toda la capa con `SERVICENOW_WRITE_GUARDS=off`. En modo multi-instancia, cada respuesta de escritura también lleva un campo `instance_target` (y las lecturas enrutadas a otro lugar un `instance_source`) para que la instancia que recibió una llamada sea siempre visible.

### Seguridad de la investigación de portal

Las herramientas de investigación de portal son conservadoras por defecto:

- `search_portal_regex_matches` comienza con escaneo solo de widgets, expansión de enlaces desactivada y límites por defecto pequeños.
- `trace_portal_route_targets` es el seguimiento preferido para evidencia compacta de Widget -> Provider -> destino de ruta.
- `download_portal_sources` no extrae Script Includes ni Angular Providers enlazados a menos que se solicite explícitamente.
- Los escaneos de portal grandes están limitados del lado del servidor y devuelven advertencias cuando la solicitud excede los valores por defecto seguros.

Modos de coincidencia de patrones:

| Modo | Comportamiento |
|------|----------|
| `auto` (predeterminado) | Las cadenas simples se tratan literalmente, los patrones con aspecto de regex siguen siendo regex |
| `literal` | Siempre escapa el patrón primero; el más seguro para cadenas de ruta/token |
| `regex` | Úsalo solo cuando necesites intencionadamente operadores de regex |

---

## Optimizaciones de rendimiento

El servidor incluye varias capas de optimización de rendimiento para minimizar la latencia y el uso de tokens.

### Serialización

- **Backend orjson**: Toda la serialización JSON usa `json_fast` (orjson cuando está disponible, respaldo de la stdlib). 2-4x más rápido que el `json` de la stdlib tanto para loads como para dumps.
- **Salida compacta**: Las respuestas de las herramientas se serializan sin sangría ni espacios en blanco extra, ahorrando 20-30% de tokens por respuesta.
- **Evitar doble análisis**: `serialize_tool_output` detecta cadenas JSON ya compactas y omite la re-serialización.

### Caché

- **Caché LRU con OrderedDict**: Los resultados de consultas se almacenan en caché con desalojo O(1) usando `OrderedDict.popitem()`. 256 entradas máximas, TTL de 30 segundos (600s para metadatos estables: tablas de esquema/scope/choice), thread-safe.
- **Caché de esquema de herramientas**: La salida de `model_json_schema()` de Pydantic se almacena en caché por tipo de modelo, evitando la generación repetida de esquemas.
- **Descubrimiento de herramientas perezoso (lazy)**: Solo los módulos de herramientas requeridos por el `MCP_TOOL_PACKAGE` activo se importan al arrancar. Los módulos no usados se omiten por completo.

### Red

- **TLS de nivel navegador por defecto**: La capa HTTP se enruta a través de `curl_cffi` con un perfil de impersonación de Chrome (`chrome120` por defecto), por lo que el handshake TLS es byte a byte como el de un navegador real — las instancias detrás de Cloudflare/Akamai o detección de bots JA3 que rechazan el `requests` estándar de Python funcionan sin configuración adicional. Desactívalo con `SERVICENOW_TLS_IMPERSONATE=off`.
- **Pooling de sesión HTTP**: Sesión persistente con keep-alive de TCP y compresión gzip/deflate (60-80% de reducción de payload en JSON grandes). La ruta de opt-out con `requests` estándar monta un `HTTPAdapter` de 20 conexiones.
- **Paginación paralela**: `sn_query_all` obtiene la primera página secuencialmente para el recuento total, luego recupera las páginas restantes de forma concurrente vía `ThreadPoolExecutor` (hasta 4 workers).
- **Tamaño de página dinámico**: Cuando los registros restantes caben en una sola página (<=100), el tamaño de página se amplía para evitar viajes de ida y vuelta extra.
- **API Batch**: `sn_batch` combina múltiples sub-solicitudes REST en un único POST a `/api/now/batch`, con fragmentación automática en el límite de 150 solicitudes.
- **Consultas M2M fragmentadas en paralelo**: Las búsquedas M2M de widget-a-provider divididas en fragmentos de 100 IDs se ejecutan de forma concurrente en lugar de secuencial.

### Esquema y arranque

- **Inyección de esquema por copia superficial**: El esquema de confirmación (`confirm='approve'`) se inyecta mediante una copia ligera de dict en lugar de `copy.deepcopy`, reduciendo la sobrecarga de `list_tools`.
- **Optimización sin recuento**: Las páginas de paginación posteriores usan `sysparm_no_count=true` para omitir el cálculo del recuento total del lado del servidor.
- **Seguridad de payload**: Las tablas pesadas (`sp_widget`, `sys_script`, etc.) tienen recorte automático de campos y restricciones de límite para evitar el desbordamiento de la ventana de contexto.

## Auditoría de fuentes locales

Descarga y analiza toda tu aplicación de ServiceNow localmente — sin llamadas repetidas a la API, sin desperdicio de contexto.

```
Step 1: download_app_sources(scope="x_company_app")    → All server-side code + cross-scope deps to disk
Step 2: audit_local_sources(source_root="temp/...")     → Analysis + HTML report
```

El paso 1 ejecuta `auto_resolve_deps=True` por defecto: tras la descarga dentro del ámbito, escanea cada
archivo `.js/.html/.xml` y obtiene cualquier registro `sys_script_include`, `sp_widget`,
`sp_angular_provider` o `sys_ui_macro` referenciado que no esté ya en el paquete — sin importar
en qué ámbito se encuentre. Las dependencias extraídas se guardan en el mismo árbol con
`"is_dependency": true` en su `_metadata.json`, de modo que la auditoría del paso 2 vea el
grafo de llamadas completo. Establece `auto_resolve_deps=False` si solo quieres registros dentro del ámbito.

> **Consejo — extrae un ámbito completo, incluido `global`:** pasa `scope="global"` para volcar cada
> registro del ámbito global, o mantén el ámbito de tu app y deja que `auto_resolve_deps` alcance
> `global` para los registros que realmente referencias. De cualquier forma, el paquete local es
> autocontenido, por lo que el análisis se ejecuta completamente sin conexión contra el disco.

### Sincronización incremental

Volver a descargar una app grande en cada ejecución es lento y arriesga timeouts. Pasa `incremental=True`
para obtener **solo lo que cambió desde la última descarga** — como `git pull` en lugar de un `clone`
nuevo. Funciona tanto en `download_app_sources` como en `download_portal_sources`.

```
download_app_sources(scope="x_company_app")                      # 1st run: full download
download_app_sources(scope="x_company_app", incremental=True)    # later: changed records only
```

- **Cómo funciona:** la primera descarga registra el `sys_updated_on` de cada registro en
  `_sync_meta.json`. En una ejecución incremental, cada familia de fuentes consulta
  `sys_updated_on >= <latest seen>` (marcas de tiempo del lado del servidor, sin desfase de reloj), vuelve a descargar
  solo esos registros y deja intactos los archivos locales sin cambios.
- **Eliminaciones:** los deltas de marca de tiempo no pueden ver registros eliminados. Añade `reconcile_deletions=True`
  para listar los registros presentes localmente pero ausentes en la instancia — reportados como advertencias bajo
  `deletion_candidates`, **nunca eliminados automáticamente**.
- **Primera ejecución / sin datos previos:** recurre automáticamente a una descarga completa.
- Ejecuta una descarga completa (no incremental) periódicamente para mantenerte plenamente sincronizado.

### Seguridad y completitud de la descarga

La descarga es la fuente de verdad para el análisis sin conexión, así que está construida para ser determinista y para nunca *parecer* completa cuando no lo está:

- **Resolución automática del ámbito.** Pasa el **namespace** de la app (`x_company_app`), su **nombre para mostrar** ("My App"), o un sys_id de `sys_scope` — todos resuelven al namespace canónico, de modo que la carpeta local (`temp/<instance>/<namespace>/`) y cada consulta son idénticas en cada ejecución. El valor resuelto se devuelve como `scope_resolution`.
- **Sin límites silenciosos.** Si una familia de fuentes alcanza `max_records_per_type`, se señala claramente: un `capped: true` por familia en `source_types`, la familia en `incomplete_types`, y un `complete: false` de nivel superior. Una descarga truncada nunca puede hacerse pasar por una completa.
- **Guardas de cross-instance / obsolescencia.** Al volver a empujar (`update_remote_from_local`) se comprueba el origen registrado del árbol local contra la instancia conectada; una re-descarga reanudada que mantiene una copia local obsoleta preserva la verdadera marca de agua de sincronización y advierte en lugar de ocultar el drift.
- **Metadatos de relaciones en el momento de la descarga.** Las aristas widget→Angular-Provider (`_graph.json`) y widget→dependencia CSS/JS (`_dependency_graph.json`) se capturan de las tablas M2M en vivo durante la descarga del portal — el análisis lee el grafo real en lugar de adivinar a partir del código.
- **Profundidad de dependencias transitivas.** Las dependencias cross-scope se resuelven `2` pasadas de profundidad por defecto (conservador). Auméntalo con `SERVICENOW_DEP_MAX_DEPTH` (acotado a `1–6`) para perseguir cadenas más largas A→B→C→D.
- **Construcción del grafo en una sola llamada.** Pasa `build_graph=True` a `download_app_sources` para ejecutar la auditoría de relaciones sin conexión justo después de la descarga — sin coste extra de API.
- **Aviso de sincronización local tras crear.** Cuando creas un widget/página en la instancia *y* existe un árbol local para ese ámbito, la respuesta de creación añade un mensaje `local_out_of_sync` con el comando exacto `download_portal_sources(...)` para incorporar el nuevo registro a local. Nunca escribe archivos locales por ti.

### Qué se genera

| Archivo | Propósito |
|------|---------|
| `_audit_report.html` | Informe HTML autocontenido con tema oscuro — ábrelo en el navegador |
| `_cross_references.json` | Quién llama a quién — cadenas de Script Include, referencias a tablas de GlideRecord |
| `_graph.json` | Aristas autoritativas widget→Angular Provider desde el M2M en vivo (no adivinadas por texto) |
| `_dependency_graph.json` | Aristas autoritativas de dependencia widget→CSS/JS desde `m2m_sp_widget_dependency` |
| `_page_graph.json` | Colocaciones página→widget derivadas localmente de `sp_instance` (sin llamada a la API) |
| `_orphans.json` | Candidatos de código muerto — SIs sin referencias, widgets sin uso |
| `_execution_order.json` | Secuencia de ejecución de BR/CS/ACL por tabla con números de orden |
| `_domain_knowledge.md` | Perfil de app autogenerado — mapas de tablas, scripts hub, advertencias |
| `_schema/*.json` | Definiciones de campos para cada tabla referenciada |
| `_sync_meta.json` | Marca de agua de `sys_updated_on` por familia que impulsa la sincronización incremental |

### Herramientas individuales de descarga

Usa el orquestador para un volcado completo, o `download_server_sources` para un refresco dirigido de una sola familia:

| Herramienta | Fuentes |
|------|---------|
| `download_app_sources` | Volcado completo de la app (todas las familias + portal + esquema + deps cross-scope) |
| `download_portal_sources` | Widgets, Angular Providers, Script Includes enlazados |
| `download_server_sources` (`families=`) | Refresco dirigido — `script_includes`, `server_scripts` (BR/Client/Catalog Client), `ui` (Actions/Scripts/Pages/Macros), `api` (Scripted REST/Processors), `security` (ACLs, solo script por defecto), `admin` (Fix Scripts/Scheduled Jobs/Script Actions/Notifications/Transforms) |
| `download_table_schema` | Definiciones de campos de sys_dictionary |

Todas las descargas escriben la fuente completa en disco sin ningún truncado. Solo se devuelve un resumen al contexto del LLM.

---

## Skills

Las herramientas son llamadas API en crudo. Las skills son lo que hace que tu LLM sea realmente útil — pipelines verificados con compuertas de seguridad, rollback y delegación a sub-agentes consciente del contexto. **El servidor MCP + skills es la configuración completa** para la automatización de ServiceNow impulsada por LLM.

4 skills hoy, más en camino con cada release.

| | Solo herramientas | Herramientas + Skills |
|---|---|---|
| Seguridad | El LLM decide | Compuertas aplicadas (snapshot → vista previa → aplicar) |
| Tokens | Volcados de fuente en el contexto | Delegar a sub-agente, solo resumen |
| Precisión | El LLM adivina el orden de las herramientas | Pipeline verificado |
| Rollback | Podría olvidarse | Snapshot obligatorio |

### Instalar Skills

```bash
# Claude Code
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude

# OpenAI Codex
uvx --from mfa-servicenow-mcp servicenow-mcp-skills codex

# OpenCode
uvx --from mfa-servicenow-mcp servicenow-mcp-skills opencode

# Antigravity
uvx --from mfa-servicenow-mcp servicenow-mcp-skills antigravity
```

El instalador descarga 24 archivos de skill del directorio `skills/` de este repositorio y los coloca en un directorio LLM local del proyecto. Sin necesidad de autenticación ni configuración.

> Si la política de seguridad de Windows bloquea `servicenow-mcp-skills`, invócalo como módulo — mismo comportamiento:
>
> ```bash
> python -m servicenow_mcp.setup_skills claude
> ```

| Cliente | Ruta de instalación | Autodescubrimiento |
|--------|-------------|----------------|
| Claude Code | `.claude/commands/servicenow/` | Los comandos slash `/servicenow` aparecen en el siguiente arranque |
| OpenAI Codex | `.codex/skills/servicenow/` | Skills cargadas en la siguiente sesión del agente |
| OpenCode | `.opencode/skills/servicenow/` | Skills cargadas en la siguiente sesión |
| Antigravity | `.gemini/antigravity/skills/servicenow/` | Skills activadas en la siguiente sesión |

**Cómo funciona:** Cada skill es un archivo Markdown autónomo con frontmatter YAML (metadatos) e instrucciones de pipeline. El cliente LLM lee estos archivos desde la ruta de instalación y los expone como comandos invocables o disparadores de skill.

**Actualizar:** Vuelve a ejecutar el mismo comando de instalación — reemplaza todos los archivos de skill existentes (instalación limpia, sin merge).

**Eliminar solo skills:** elimina manualmente el directorio de instalación de skills (por ejemplo `rm -rf .claude/commands/servicenow/`).

### Categorías de skills

| Categoría | Skills | Propósito |
|----------|--------|---------|
| `analyze/` | 6 | Análisis de widgets, diagnóstico de portal, auditoría de providers, mapeo de dependencias, auditoría ESC, **auditoría de fuentes locales** |
| `fix/` | 3 | Parcheado de widgets (compuertas escalonadas), depuración, revisión de código |
| `manage/` | 8 | Diseño de páginas, script includes, exportación de fuentes, **descarga de fuentes de app**, flujo de changeset, sincronización local, gestión de workflow, **gestión de skills** |
| `deploy/` | 2 | Ciclo de vida de change request, triaje de incidentes |
| `explore/` | 5 | Comprobación de salud, descubrimiento de esquema, trazado de rutas, trazado de disparadores de flujo, flujo de catálogo ESC |

### Metadatos de skill

Cada skill incluye metadatos que ayudan a los LLM a optimizar la ejecución:

```yaml
context_cost: low|medium|high    # → high = delegate to sub-agent
safety_level: none|confirm|staged # → staged = mandatory snapshot/preview/apply
delegatable: true|false           # → can run in sub-agent to save context
triggers: ["위젯 분석", "analyze widget"]  # → LLM trigger matching
```

Para la referencia completa de skills, consulta [skills/SKILL.md](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/skills/SKILL.md).

### Recursos MCP (guías de skill integradas)

Las skills también se exponen como **recursos MCP** directamente desde el servidor — sin necesidad de instalación del lado del cliente. Cualquier cliente compatible con MCP puede descubrirlas y leerlas bajo demanda.

```
# List available skill guides
list_resources → skill://manage/local-sync, skill://manage/app-source-download, ...

# Read a specific guide
read_resource("skill://manage/local-sync") → full pipeline with safety gates
```

Las herramientas que tienen una guía de skill correspondiente muestran una pista `→ skill://...` en su descripción. El contenido de la guía es **basado en pull** — coste de token cero hasta que el cliente la lea realmente.

| Característica | Skills del lado del cliente | Recursos MCP |
|---------|-------------------|---------------|
| Disponibilidad | Requiere comando de instalación | Integrado, cualquier cliente |
| Coste de token | Cargado por el cliente | Pull bajo demanda (0 hasta leer) |
| Descubrimiento | Comandos slash / disparadores | `list_resources` |
| Ideal para | Usuarios avanzados, comandos slash | Orientación universal |

## Docker

Solo autenticación con API Key (la autenticación MFA por navegador requiere GUI, no disponible en contenedores).

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

Consulta la [Guía de configuración de clientes](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md#docker-api-key-only) para opciones de build local.

## Configuración para desarrolladores

Si quieres modificar la fuente localmente:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uvx --with playwright playwright install chromium
```

### Ejecutar tests

```bash
uv run pytest
```

### Linting y formateo

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

### Build

```bash
uv build
```

> Windows: consulta la [Guía de instalación en Windows](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)

---

## Documentación

- [Guía de configuración para LLM](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/llm-setup.md) — Flujo de instalación de una línea guiado por IA
- [Guía de configuración de clientes](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md) — Configuración con instalador primero más configuraciones de cliente de respaldo
- [Inventario de herramientas](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_INVENTORY.md) — Lista completa de herramientas por categoría y paquete
- [Guía de instalación en Windows](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)
- [Guía del catálogo](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/catalog.md) — CRUD y optimización del catálogo de servicios
- [Gestión de cambios](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/change_management.md) — Ciclo de vida y aprobación de change requests
- [Gestión de workflow](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/workflow_management.md) — Herramientas de Workflow (motor wf_workflow) y Flow Designer
- [README en coreano](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md)

---

## Proyectos relacionados y agradecimientos

- Este repositorio incluye herramientas consolidadas y refactorizadas de implementaciones anteriores internas / heredadas de ServiceNow MCP. La superficie actual está organizada en torno a herramientas `manage_*` agrupadas (ver [tool_utils.py](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/src/servicenow_mcp/utils/tool_utils.py)).
- Este proyecto se centra en casos de uso de servidor MCP seguros y diff-first: cada escritura pasa por confirmación + guardas de escritura (edición concurrente, creación duplicada, publicación, Flow Designer), y las ediciones de fuente se comparan con el remoto en vivo antes de empujarse.

---

## Licencia

Apache License 2.0
