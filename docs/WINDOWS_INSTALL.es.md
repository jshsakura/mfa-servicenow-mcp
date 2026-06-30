# Guía de instalación en Windows

Usa `uvx` de forma predeterminada. Si la seguridad de endpoints/Zscaler bloquea `uvx` o las descargas de paquetes, usa la sección del zip/exe de la versión más abajo.

---

## Paso 1: Instalación predeterminada con uvx

Abre PowerShell sin privilegios de administrador:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

Eso instala `uv`, descarga y verifica el servidor, y descarga Chromium. Luego añade el servidor al archivo de configuración de tu cliente MCP (sin comando de instalación):

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

`uvx` reutiliza un Chromium compatible que ya esté en la caché estándar de Playwright; si falta Chromium, ejecuta primero el comando de instalación anterior.

---

## Paso 2: Instalación con el zip/exe de la versión

Usa esto cuando `uvx` esté bloqueado. Descarga `servicenow-mcp-windows-x64-<version>.zip` desde GitHub Releases. Contiene un único `servicenow-mcp.exe` compilado con PyInstaller más `LICENSE`. No se necesita ningún script de instalación: el ejecutable gestiona por sí mismo el descubrimiento de Chromium. Elige una carpeta estable que controles (por ejemplo `C:\Users\you\apps\servicenow-mcp\`), extrae `servicenow-mcp.exe` en ella y, si tienes el zip de Chromium, **extráelo de antemano** en la misma carpeta. No dejes el `.zip` por ahí. El nombre de la carpeta extraída puede mantenerse tal como lo produjo Windows o renombrarse a `ms-playwright\`; el ejecutable busca con glob cualquier directorio hermano `ms-play*` al iniciarse:

```
C:\Users\you\apps\servicenow-mcp\
├── servicenow-mcp.exe
└── ms-playwright-chromium-windows-x64-<ver>\   (el nombre extraído predeterminado funciona)
    └── chromium-1185\
        └── …
```

Al iniciarse, el ejecutable busca cualquier directorio hermano `ms-play*\chromium-*` y apunta Playwright hacia él mediante `PLAYWRIGHT_BROWSERS_PATH` solo para el proceso actual. No toca la caché estándar de Playwright del sistema (`%LOCALAPPDATA%\ms-playwright`), no modifica ninguna configuración de cliente MCP y no escribe en ningún lugar del disco.

Luego pega esto en el archivo de configuración de tu cliente (ejemplo de Claude Code / Claude Desktop):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe",
      "args": [],
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

`SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` son un pre-rellenado opcional del inicio de sesión MFA. Si colocas Chromium en algún lugar distinto del directorio hermano `ms-playwright\`, añade `"PLAYWRIGHT_BROWSERS_PATH": "C:/abs/path/to/ms-playwright"` al bloque `env`. Los fragmentos para Codex (`config.toml`) / OpenCode (`opencode.json`) / Cursor / Antigravity / Zed están en la [Guía de configuración de clientes](CLIENT_SETUP.md).

Esto mantiene `uvx` completamente fuera del tiempo de ejecución.

Si Chromium no viene incluido y las descargas están permitidas, instala Python desde <https://www.python.org/downloads/> y luego ejecuta:

```powershell
py -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = "$HOME\apps\servicenow-mcp\ms-playwright"
py -m playwright install chromium
```

Si la descarga del navegador de Playwright también está bloqueada, descarga `ms-playwright-chromium-windows-x64.zip` desde la versión chromium-bundle (https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) y extrae su contenido en:

```text
%LOCALAPPDATA%\ms-playwright
```

Documentación de los navegadores de Playwright: <https://playwright.dev/python/docs/browsers>

---

## Paso 3: Compilar los artefactos de la versión

Los mantenedores compilan el zip de la versión en Windows:

```powershell
py scripts\build_desktop_release.py --browser-zip
```

Esto crea el zip del ejecutable y el zip opcional de la caché de Chromium de Playwright para redes bloqueadas.

---

## Paso 4: Configura tu cliente MCP

Copia la configuración para tu cliente MCP que aparece a continuación.
Reemplaza `your-instance` por la dirección real de tu instancia de ServiceNow.

### Claude Desktop

Ubicación del archivo de configuración: `%APPDATA%\Claude\claude_desktop_config.json`

> Crea el archivo si no existe. Si falta la carpeta, inicia Claude Desktop una vez para crearla.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Claude Code

Regístralo mediante la CLI: no se necesita archivo de configuración:

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

Verifica:
```powershell
claude mcp list
```

### OpenAI Codex

Ubicación del archivo de configuración: `%USERPROFILE%\.codex\agents.toml` o `.codex\agents.toml` en la raíz de tu proyecto.

> Crea el archivo y la carpeta si no existen.

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://your-instance.service-now.com",
  "--auth-type", "browser",
  "--browser-headless", "false",
  "--tool-package", "standard",
]
```

### OpenCode

Ubicación del archivo de configuración: `opencode.json` en la raíz de tu proyecto.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Zed

Ubicación del archivo de configuración: `~/.config/zed/settings.json`

> Añádelo mediante **Settings** > **MCP Servers** en Zed:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": [
      "--with", "playwright",
      "--from", "mfa-servicenow-mcp",
      "servicenow-mcp"
    ],
    "env": {
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

### AntiGravity

Ubicación del archivo de configuración: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> También accesible mediante el panel del agente **...** → **Manage MCP Servers** → **View raw config**.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Guarda la configuración y luego haz clic en **Refresh** en AntiGravity.

---

## Paso 5: Instalar Skills (opcional)

Las Skills son planos de ejecución de IA: canalizaciones verificadas con controles de seguridad que convierten las herramientas MCP en bruto en flujos de trabajo fiables. 4 skills en 3 categorías.

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# O con uvx (sin necesidad de instalar)
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

| Cliente | Ruta de instalación | Descubrimiento automático |
|--------|-------------|----------------|
| Claude Code | `.claude\commands\servicenow\` | Los comandos slash `/servicenow` aparecen en el siguiente arranque |
| OpenAI Codex | `.codex\skills\servicenow\` | Las skills se cargan en la siguiente sesión del agente |
| OpenCode | `.opencode\skills\servicenow\` | Las skills se cargan en la siguiente sesión |

| Categoría | Skills | Propósito |
|----------|--------|---------|
| `analyze/` | 6 | Análisis de widgets, diagnóstico de portal, mapeo de dependencias, detección de código |
| `fix/` | 3 | Parcheo de widgets (controles de seguridad por etapas), depuración, revisión de código |
| `manage/` | 8 | Diseño de página, script includes, exportación de fuentes, descarga de fuentes de la aplicación, flujo de trabajo de changeset, sincronización local, gestión de flujos de trabajo, gestión de skills |
| `deploy/` | 2 | Ciclo de vida de change request, triaje de incidentes |
| `explore/` | 5 | Comprobación de estado, descubrimiento de esquema, rastreo de rutas, rastreo de disparadores de flujo, flujo del catálogo ESC |

**Actualizar:** Vuelve a ejecutar el mismo comando de instalación para reemplazar todos los archivos de skills existentes.
**Eliminar solo las skills:** elimina manualmente el directorio de skills (por ejemplo `Remove-Item -Recurse .claude\commands\servicenow\`).

---

## Paso 6: Verificar

1. **Cierra por completo y reinicia** tu cliente MCP (cierra también el icono de la bandeja).
2. La ventana del navegador se abre en la primera llamada a una herramienta (no al iniciar el servidor).
3. Completa la autenticación MFA mediante Okta/Microsoft Authenticator/etc.
4. Tras la autenticación, el navegador se cierra automáticamente y la sesión persiste.

Prueba: llama a la herramienta `sn_health` desde tu cliente.

> Si el navegador no se abre, comprueba que Chromium se instaló. Puedes forzar su instalación con: `uvx --with playwright playwright install chromium`

---

## Gestión de sesiones

Las sesiones autenticadas se guardan en disco automáticamente: no es necesario iniciar sesión cada vez.

- **Ubicación del archivo de sesión**: `%USERPROFILE%\.servicenow_mcp\session_*.json`
- **TTL de sesión predeterminado**: 30 minutos (el hilo de keepalive lo extiende cada 15 minutos)
- **Al expirar la sesión**: la ventana del navegador se abre automáticamente para reautenticarse

Para cambiar el TTL, usa la opción `--browser-session-ttl` (en minutos):
```
--browser-session-ttl 60
```

Para mantener el perfil del navegador, añade la opción `--browser-user-data-dir`:
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
Esto almacena las cookies y el estado de inicio de sesión en el directorio para una persistencia de sesión más prolongada.

---

## Paquetes de herramientas

Establece `MCP_TOOL_PACKAGE` para elegir un conjunto de herramientas. Predeterminado: `standard` (solo lectura).

| Paquete | Herramientas | Descripción |
|---------|:-----:|-------------|
| `core` | 12 | Elementos esenciales mínimos de solo lectura para estado, esquema, descubrimiento y búsquedas clave |
| `standard` | 27 | **(Predeterminado)** Paquete de solo lectura para incidentes, cambios, portal, registros y análisis de fuentes |
| `service_desk` | 29 | standard + escrituras operativas de incidentes y cambios |
| `portal_developer` | 38 | standard + flujos de trabajo de portal, changeset, script include y entrega de sincronización local |
| `platform_developer` | 43 | standard + escrituras de flujos de trabajo, Flow Designer, UI policy, incidentes/cambios y scripts |
| `full` | 57 | La superficie empaquetada más amplia: todos los flujos de trabajo `manage_*` más operaciones avanzadas |

Para cambiarlo, actualiza el valor de `MCP_TOOL_PACKAGE`:

Clientes JSON (Claude Desktop, AntiGravity):
```json
"env": {
  "MCP_TOOL_PACKAGE": "standard"
}
```

Clientes TOML (Codex) — añádelo dentro del array `args`:
```toml
"--tool-package", "standard",
```

---

## Solución de problemas

### "uvx not found"
→ Asegúrate de haber **cerrado y reabierto** PowerShell después del Paso 1. Si sigue fallando:
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### "Python is not installed"
→ `uv` descarga automáticamente Python 3.11+. No se necesita ninguna instalación manual.
Si hay un conflicto con el Python del sistema, desinstala y reinstala `uv`.

### "Browser won't open"
→ Chromium debe estar instalado antes de iniciar MCP:
```powershell
uvx --with playwright playwright install chromium
```
→ Si la descarga del navegador está bloqueada, usa `ms-playwright-chromium-windows-x64.zip` de la versión chromium-bundle y extráelo en `%LOCALAPPDATA%\ms-playwright`.

### "MCP server won't connect"
→ Comprueba la sintaxis del archivo de configuración:
  - JSON: comas, comillas, llaves coincidentes
  - TOML: corchetes, comillas, comas
→ Verifica que `instance-url` comience con `https://`.
→ Claude Desktop requiere un **cierre completo y reinicio** tras los cambios de configuración (cierra también el icono de la bandeja).

### "PowerShell script execution is blocked"
→ Permite la ejecución para el usuario actual:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Restablecer la sesión
Si los problemas de inicio de sesión persisten, elimina la caché de sesión y vuelve a intentarlo:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### Actualización de versión
`uvx` reutiliza la última versión que descargó en caché. **No** se actualiza automáticamente a una versión más reciente en cada ejecución. Para traer la última versión publicada a la caché:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

Después de actualizar, reinicia por completo tu cliente MCP para que lance la nueva versión en caché.
