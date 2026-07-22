# Guía de instalación en Windows

`uvx` es la opción predeterminada en Windows, igual que en el resto de plataformas. Hay una situación propia de Windows que puede obligarte a abandonarlo:

- **Smart App Control bloquea `uvx`** → cambia a **pip** (Paso 1b). Es con diferencia el fallo más habitual en Windows, y suele aparecer de golpe justo después de una actualización de Windows.

Si **PyPI es inaccesible** —una red corporativa que bloquea el índice de paquetes por completo—, ninguna de las dos vías podrá descargar nada. Pide a tu departamento de IT que ponga `pypi.org` y `files.pythonhosted.org` en la lista de permitidos, o que replique el paquete en un índice interno al que puedas apuntar con `pip install --index-url`.

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

**Actualizar:** `uvx` guarda en caché la versión que descargó y la sigue reutilizando, así que hay que traer explícitamente cada nueva versión:

```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

---

## Paso 1b: Smart App Control bloquea uvx — instala con pip

### Qué vas a ver

`uvx` deja de funcionar sin ningún error útil. El cliente MCP informa de que el servidor no arrancó, o PowerShell indica que el programa fue bloqueado por tu administrador / por una directiva del sistema. Nada ha cambiado en tu configuración. Muy a menudo esto empieza **justo después de una actualización de Windows**, lo que hace parecer que se ha roto el servidor y no el lanzador.

### Por qué ocurre

Smart App Control (SAC) es una característica de Windows 11 que solo permite ejecutar programas **firmados o reconocidos como fiables**. `uvx` no ejecuta un programa instalado de forma permanente: en cada ejecución descomprime un **ejecutable temporal nuevo y sin firmar** y lo lanza. Eso es exactamente lo que SAC existe para impedir, así que lo bloquea siempre. Por más que reintentes o reinstales `uv`, no cambia nada: por diseño, el archivo es nuevo y no está firmado en cada ejecución.

SAC viene en modo de evaluación en los equipos nuevos con Windows 11 y puede activarse solo más adelante, por su cuenta. Por eso aparece de la nada en una máquina donde `uvx` llevaba meses funcionando.

Para comprobarlo: **Seguridad de Windows → Control de aplicaciones y navegador → Configuración de Smart App Control**.

> **No desactives Smart App Control para resolver esto.** Desactivarlo es un **cambio sin retorno**: una vez desactivado, Windows no te dejará volver a activarlo. Recuperarlo exige **reinstalar Windows**. No compensa degradar permanentemente la seguridad del sistema operativo por un lanzador de paquetes. Usa pip: resuelve el problema por completo y deja SAC activado.

### La vía de pip

pip instala el servidor como archivos Python normales que ejecuta un intérprete de Python **firmado**, así que SAC no tiene nada que objetar.

Instala Python **3.10 o superior** desde el [instalador de python.org](https://www.python.org/downloads/): esa compilación está firmada y pasa SAC tal cual. (El Python de Microsoft Store también sirve.) Marca **«Add python.exe to PATH»** durante la instalación. Después:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**Actualizar:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Instala Chromium de antemano, como se muestra. Dejarlo para la primera llamada a una herramienta supone una descarga de ~150 MB compitiendo con el plazo de handshake de tu cliente MCP, lo que se manifiesta como `connection closed`.

### Lánzalo siempre como módulo, nunca con el script de consola

pip también deja un shim `servicenow-mcp.exe` en tu carpeta Scripts. **Ese shim es un `.exe` sin firmar que pip genera en tu máquina, así que SAC lo bloquea igual que bloqueaba uvx.** Evítalo por completo llamando al módulo:

| En lugar de | Usa |
|---|---|
| `servicenow-mcp` | `python -m servicenow_mcp` |
| `servicenow-mcp setup` | `python -m servicenow_mcp setup` |
| `servicenow-mcp --version` | `python -m servicenow_mcp --version` |
| `servicenow-mcp-skills claude` | `python -m servicenow_mcp.setup_skills claude` |

Verifica la instalación:

```powershell
python -m servicenow_mcp --version
```

### Configuración del cliente en la vía de pip

Solo cambian `command` y `args`. **El bloque `env` es idéntico al de la forma con uvx**: copia cualquier configuración del Paso 2 y sustituye las dos primeras líneas:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Para el TOML de Codex, el equivalente es `command = "python"` / `args = ["-m", "servicenow_mcp"]`.

> Si tu cliente MCP no encuentra `python`, indica la ruta absoluta (por ejemplo `C:/Users/you/AppData/Local/Programs/Python/Python312/python.exe`). Los clientes MCP no siempre heredan el PATH que tiene tu shell.

---

## Paso 2: Configura tu cliente MCP

Copia la configuración para tu cliente MCP que aparece a continuación.
Reemplaza `your-instance` por la dirección real de tu instancia de ServiceNow.

> Estos ejemplos usan la instalación predeterminada con `uvx`. **En la vía de pip (Paso 1b), reemplaza `command` por `python` y `args` por `["-m", "servicenow_mcp"]`**, conservando los flags `--instance-url` / `--auth-type` que vengan a continuación y dejando el bloque `env` exactamente como está.

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

## Paso 3: Instalar Skills (opcional)

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

> **En la vía de pip (Paso 1b), llama al módulo en su lugar**: `servicenow-mcp-skills` es el mismo tipo de shim `.exe` sin firmar generado por pip que Smart App Control bloquea:
>
> ```powershell
> python -m servicenow_mcp.setup_skills claude
> python -m servicenow_mcp.setup_skills codex
> python -m servicenow_mcp.setup_skills opencode
> ```

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

## Paso 4: Verificar

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

### uvx se encuentra, pero no se ejecuta nada / «bloqueado por tu administrador» / dejó de funcionar tras una actualización de Windows
→ Esto es **Smart App Control**, no una instalación rota. uvx descomprime un ejecutable temporal sin firmar en cada ejecución y SAC se niega a ejecutarlo. Cambia a la vía de pip del [Paso 1b](#paso-1b-smart-app-control-bloquea-uvx--instala-con-pip). No desactives SAC: es un cambio sin retorno que solo puedes deshacer reinstalando Windows.

### La instalación con pip funcionó, pero `servicenow-mcp` sigue sin arrancar
→ Estás topándote con el shim `servicenow-mcp.exe` generado por pip, que no está firmado y SAC bloquea igual que hacía con uvx. Llama al módulo en su lugar: `python -m servicenow_mcp`. Actualiza también la configuración de tu cliente MCP a `"command": "python"`, `"args": ["-m", "servicenow_mcp"]`.

### "Python is not installed"
→ En la vía de **uvx**, `uv` descarga automáticamente Python 3.11+: no se necesita ninguna instalación manual. Si hay un conflicto con el Python del sistema, desinstala y reinstala `uv`.
→ En la vía de **pip** eres tú quien aporta Python: instala 3.10+ desde el [instalador de python.org](https://www.python.org/downloads/) (está firmado, así que pasa Smart App Control) y marca **«Add python.exe to PATH»**. El Python de Microsoft Store también sirve.

### "Browser won't open"
→ Chromium debe estar instalado antes de iniciar MCP:
```powershell
uvx --with playwright playwright install chromium   # uvx
python -m playwright install chromium               # pip
```

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
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

En la vía de pip:
```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

En ambos casos Chromium se actualiza a la vez, porque una versión más reciente de Playwright espera una compilación más reciente de Chromium.

Después de actualizar, reinicia por completo tu cliente MCP para que lance la nueva versión.
