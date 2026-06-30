# Configuración del cliente MCP

Configuración detallada para cada cliente MCP. Todos los clientes usan el mismo servidor MCP — solo difiere el formato de configuración.

> **Recomendado primero:** usa el comando de configuración `uvx` que aparece abajo. Si las herramientas de seguridad corporativa bloquean `uvx`, usa la sección del zip/exe de la versión.

---

## Antes de empezar

Usa `uvx` de forma predeterminada. Mantiene la instalación y la configuración del cliente consistentes en macOS, Linux y Windows.

### 1. Instalar uv

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Obtener el servidor + instalar Chromium

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # fetch + verify the server
uvx --with playwright playwright install chromium                                   # Chromium for MFA/SSO login
```

El primer comando obtiene y verifica el servidor por adelantado en el mismo entorno `--with playwright` que usa el cliente, de modo que el primer arranque sea instantáneo. El segundo descarga Chromium; `uvx` reutiliza un Chromium compatible que ya esté en la caché estándar.

### 3. Añade el servidor a la configuración de tu cliente MCP

Añade una entrada al archivo de configuración de tu cliente (no se necesita ningún comando de instalación):

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

Las rutas de archivo y formatos por cliente (Codex TOML, etc.) están más abajo; reinicia el cliente después.

### Instalación local (zip/exe de la versión)

Usa esto cuando `uvx` o PyPI estén bloqueados. El zip de la versión es un único ejecutable compilado con PyInstaller — **sin script de instalación, sin necesidad de Python, sin contaminación de la caché del sistema**. El ejecutable detecta automáticamente un directorio `ms-playwright/` ubicado junto a él.

**1. Descargar.** El ejecutable desde la [última versión](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest); el paquete opcional de Chromium (solo si la red también bloquea la descarga de Chromium de Playwright) desde la versión perdurable [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle).

| Plataforma | Requerido (última versión) | Añadir si la descarga de Chromium está bloqueada (versión chromium-bundle) |
|----------|---------------------------|----------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. Distribúyelo** en cualquier directorio estable que controles. **Extrae ambos zips por adelantado** — no dejes los archivos `.zip` junto al ejecutable. La carpeta extraída del zip de Chromium solo tiene que empezar por `ms-play` y contener un subdirectorio `chromium-*`:

```
~/apps/servicenow-mcp/                                  (any directory you choose)
├── servicenow-mcp                                      ← from the platform zip (.exe on Windows)
└── ms-playwright-chromium-linux-x64-<ver>/             ← default extracted name works
    └── chromium-1185/
        └── …
```

(Renómbralo a `ms-playwright/` si quieres un nombre más ordenado — ambos funcionan.) Al arrancar, el ejecutable busca cualquier directorio hermano `ms-play*` y, al encontrar un subdirectorio `chromium-*` dentro, dirige Playwright hacia él mediante `PLAYWRIGHT_BROWSERS_PATH` solo para el proceso actual. **No** toca la caché de Playwright del sistema, **no** modifica ninguna configuración del cliente MCP, **no** escribe en ningún lugar del disco.

**3. Verifica y luego conecta tu cliente MCP:**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

Pega el fragmento de configuración MCP de la [Guía de configuración](#configuration-guide) de abajo en el archivo de configuración de tu cliente, estableciendo `command` en la ruta absoluta de tu ejecutable. El bloque `env` es el mismo que en la configuración de uvx — solo cambia `command`. Si pones Chromium en un lugar distinto a junto al ejecutable, añade `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` al bloque `env`.

Si te saltaste el zip de Chromium y la descarga automática de Playwright está bloqueada, prepara el directorio por adelantado en una máquina con Python:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

La detección automática lo recoge sin configuración adicional.

> Usuarios de Windows: consulta la [Guía de instalación en Windows](WINDOWS_INSTALL.md) para ver detalles paso a paso y notas sobre proxy/antivirus.

### Prueba rápida

Verifica que el servidor arranca antes de configurar tu cliente:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

Si el servidor arranca y se abre una ventana del navegador para iniciar sesión, ya estás listo para configurar tu cliente más abajo.

---

## Guía de configuración

> **`args` es solo para el paquete** — la URL de la instancia, la autenticación y las credenciales van todas en `env` (o `environment`). Esto mantiene `args` limpio y facilita el cambio de instancias por proyecto.

> **Recomendado a nivel de proyecto**: Usa configuración con alcance de proyecto para que cada proyecto pueda conectarse a una instancia de ServiceNow diferente.

> **Una sola instancia activa por diseño**: las herramientas ordinarias se enrutan a una única instancia activa de ServiceNow. Esto evita intencionadamente el cambio de escritura en tiempo de solicitud, que puede provocar escrituras accidentales en producción al moverse entre dev/test/prod.

---

## Streamable HTTP

El transporte predeterminado es `stdio`. Para clientes MCP remotos o un puente HTTP local, arranca el servidor con Streamable HTTP:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

El endpoint MCP es `http://127.0.0.1:8000/mcp`; `/health` devuelve una respuesta de estado ligera. Mantén el host de loopback predeterminado a menos que el servidor esté detrás de controles de red de confianza.

---

## Modo de comparación de datos de solo lectura

Para el análisis de desviaciones (drift) entre dev/test, puedes configurar instancias con nombre mediante `SERVICENOW_INSTANCE_CONFIG`. Este modo está intencionadamente limitado a la comparación de datos:

- Las herramientas ordinarias siguen enrutándose solo a `SERVICENOW_ACTIVE_INSTANCE`.
- Las herramientas con capacidad de escritura no exponen un selector de instancia.
- `compare_instances` es de solo lectura y compara registros entre alias.
- `list_instances` solo informa de los alias configurados.
- Configura los alias de comparación con paquetes de solo lectura y `allow_writes=false`.
- No uses este modo para trabajos de escritura entre entornos.

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev": {
    "url": "https://acme-dev.service-now.com",
    "tool_package": "standard",
    "allow_writes": false
  },
  "test": {
    "url": "https://acme-test.service-now.com",
    "tool_package": "standard",
    "allow_writes": false
  }
}'
```

Credenciales por instancia, en un bloque `env` del cliente MCP (cada alias puede llevar su propio `username` / `password` / `auth_type` / `api_key`; `${ENV}` mantiene los secretos fuera del JSON; la forma de instancia única `SERVICENOW_INSTANCE_URL` sigue funcionando como alternativa):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mfa-servicenow-mcp@latest"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

Ejemplo de comparación:

```json
{
  "source": "dev",
  "target": "test",
  "table": "sys_script_include",
  "key_field": "api_name",
  "fields": "api_name,name,active,script",
  "query": "sys_scope.scope=x_company_app"
}
```

Usa configuraciones de proyecto/cliente separadas para el trabajo real contra otra instancia.

---

## Claude Desktop

| Alcance | Ruta |
|-------|------|
| Global | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Global | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Claude Desktop no admite configuración a nivel de proyecto. Usa Claude Code para la configuración por proyecto.

---

## Claude Code

| Alcance | Ruta |
|-------|------|
| Global | `~/.claude.json` |
| Proyecto | `.mcp.json` en la raíz del proyecto |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Zed

| Alcance | Ruta |
|-------|------|
| Global | `~/.config/zed/settings.json` |

Añádelo mediante **Settings** > **MCP Servers** en Zed:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
    "env": {
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "SERVICENOW_USERNAME": "your-username",
      "SERVICENOW_PASSWORD": "your-password",
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

---

## OpenAI Codex (CLI y App)

Tanto **Codex CLI** (comando `codex`) como **Codex App** (chatgpt.com/codex) leen del mismo `config.toml`.

| Alcance | Ruta | Nota |
|-------|------|------|
| Global | `~/.codex/config.toml` | Compartido entre todos los proyectos |
| Proyecto | `.codex/config.toml` | Anula el global (solo proyectos de confianza) |

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
# Login is shared across hosts automatically (scoped per instance + user under
# ~/.mfa_servicenow_mcp). Only set SERVICENOW_BROWSER_USER_DATA_DIR if a sandboxed
# host remapped HOME — see the README "Login sharing" note. Do NOT set it when you
# run multiple instances; it collapses them into one Chromium profile.
```

---

## OpenCode

| Alcance | Ruta |
|-------|------|
| Proyecto | `opencode.json` en la raíz del proyecto |

> OpenCode usa `environment` (no `env`).

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
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## AntiGravity

| Alcance | Ruta |
|-------|------|
| Global | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| Global | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> Edita mediante el panel del agente: **...** > **Manage MCP Servers** > **View raw config**. Haz clic en **Refresh** después de guardar.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Docker (solo API Key)

> La autenticación por navegador (MFA/SSO) requiere un navegador con GUI y no funciona dentro de contenedores.

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
