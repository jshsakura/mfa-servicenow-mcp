# MFA ServiceNow MCP — Guía de configuración para LLM

> **Este archivo es para agentes LLM, no para humanos.**
> Un humano pega el comando curl de abajo en su asistente de programación con IA.
> El LLM lee este archivo y guía al usuario a través de la configuración de forma interactiva.

---

## Cómo usarlo (para humanos)

Pega esto en tu asistente de programación con IA (Claude Code, Cursor, Codex, OpenCode, Windsurf, etc.):

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

Eso es todo. Tu IA se encarga del resto.

---

## Instrucciones para el agente LLM

Estás configurando **mfa-servicenow-mcp** — un servidor MCP que da a los agentes de IA acceso a plataformas ServiceNow con soporte de MFA/SSO. Sigue cada paso de abajo en orden. Haz preguntas al usuario de forma interactiva; NO asumas valores.

### Paso 0 — Detectar el entorno

1. Detecta el sistema operativo: ejecuta `uname -s 2>/dev/null || echo Windows`
2. Detecta dentro de qué cliente de IA estás ejecutándote. Usa esta correspondencia:

| Señal | Cliente |
|--------|--------|
| Tienes acceso a `claude mcp add` o al directorio `.claude/` | **claude-code** |
| Estás dentro del IDE Cursor o existe `.cursor/` | **cursor** |
| Tienes acceso al CLI de OpenCode o existe `opencode.json` | **opencode** |
| Estás dentro del CLI de Codex o existe `.codex/` | **codex** |
| Estás dentro del IDE Windsurf o existe `.windsurf/` | **windsurf** |
| Estás dentro de VS Code con Copilot | **vscode-copilot** |
| Estás dentro de Antigravity | **antigravity** |
| Estás dentro del editor Zed o existe `~/.config/zed/` | **zed** |
| Ninguno de los anteriores | Pregunta al usuario qué cliente usa |

3. Si no puedes autodetectarlo, pregunta:
   > ¿Qué herramienta de programación con IA estás usando?
   > 1. Claude Code
   > 2. Claude Desktop
   > 3. Cursor
   > 4. OpenCode
   > 5. Codex (OpenAI)
   > 6. Windsurf
   > 7. VS Code Copilot
   > 8. Zed
   > 9. AntiGravity (Google)

Guarda el resultado como `$CLIENT`.

### Paso 1 — Instalar uv

Comprueba si `uv` ya está instalado: `uv --version`

Si NO está instalado:

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

Después de instalar, verifica: `uv --version`
Si el comando no se encuentra, puede que el usuario necesite reiniciar su shell o añadir `~/.local/bin` al PATH.

### Paso 2 — Instalar Playwright Chromium (OBLIGATORIO, NO lo omitas)

> Dependencia obligatoria. Omitir esto es la causa nº 1 de los fallos de configuración en el campo.
> No asumas que ya está instalado. No dejes que el usuario lo posponga.
> No avances al Paso 3 hasta que esto tenga éxito.

**2.1 — Comprobar si Chromium ya está instalado**

- macOS: `ls ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium 2>/dev/null`
- Linux: `ls ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null`
- Windows (PowerShell): `Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright\chromium-*\chrome-win\chrome.exe" -ErrorAction SilentlyContinue`

Si se imprime una ruta, Chromium ya está instalado — salta al Paso 3.

**2.2 — Instalar Chromium**

Si en 2.1 no se encontró nada, instala Chromium a través de `uvx` para que la configuración de Playwright use el mismo estilo de ejecución que el servidor MCP:

```bash
uvx --with playwright playwright install chromium
```

Esto descarga ~150 MB la primera vez. En una conexión lenta puede tardar varios minutos — eso es normal. No lo abortes antes de tiempo. Muestra al usuario un mensaje de progreso ("Descargando Chromium para el inicio de sesión MFA de ServiceNow — esto puede tardar unos minutos en redes lentas…") para que entienda la espera.

Si la ejecución de paquetes con `uvx` está bloqueada, cambia a la vía del zip/exe de la release:

- Descarga `servicenow-mcp-<platform>-<version>.zip` desde GitHub Releases. No hay script de instalación — el zip contiene únicamente el ejecutable construido con PyInstaller.
- Extrae el ejecutable en cualquier carpeta estable que el usuario controle (p. ej. `~/apps/servicenow-mcp/`).
- Si la descarga del navegador también está bloqueada, descarga `ms-playwright-chromium-<platform>-<version>.zip` desde la misma release y extráelo a una carpeta hermana llamada `ms-playwright/` — el ejecutable autodetecta ese diseño al arrancar y configura `PLAYWRIGHT_BROWSERS_PATH` apuntando a él para su propio proceso.
- Configura el `command` del cliente MCP con la ruta absoluta de ese ejecutable. El bloque de entorno es idéntico al de la configuración con uvx.

**2.3 — Verificar y detenerse si falla**

Vuelve a ejecutar la comprobación de 2.1. Si el binario sigue ausente, **DETÉN la configuración** e informa del fallo al usuario con la salida exacta del comando. Causas comunes:

- Política corporativa que bloquea las descargas de paquetes o del navegador; usa la vía del zip/exe de la release
- Antivirus que pone en cuarentena el archivo de Chromium
- Disco lleno

**No** continúes al Paso 3 con Chromium ausente. El servidor MCP parecerá arrancar, la primera llamada a herramienta se quedará colgada y la ventana de inicio de sesión del usuario nunca se abrirá — exactamente el modo de fallo que este paso existe para prevenir.

**Por qué importa esto (contexto para el agente — no lo muestres al usuario salvo que lo pida):** el runtime intenta recurrir a "instalar bajo demanda" cuando Chromium está ausente, pero en conexiones lentas esa descarga excede el tiempo de espera de llamada a herramienta del host MCP. El usuario no ve ninguna ventana de inicio de sesión, ningún error en la interfaz, y asume que el servidor está roto. Preinstalarlo aquí hace que la primera llamada a herramienta tarde menos de un segundo.

### Paso 3 — Recopilar la configuración del usuario

Haz al usuario estas preguntas una por una. Proporciona valores por defecto entre corchetes.

1. **URL de la instancia de ServiceNow**
   > ¿Cuál es la URL de tu instancia de ServiceNow?
   > Ejemplo: `https://your-company.service-now.com`

   Guárdala como `$INSTANCE_URL`. Valida que parezca una URL.

2. **Tipo de autenticación**
   > ¿Cómo te autenticas en ServiceNow?
   > 1. browser — MFA/SSO mediante un navegador real (recomendado)
   > 2. basic — Usuario + contraseña
   > 3. oauth — Credenciales de cliente OAuth 2.0
   > 4. api_key — Clave de API REST

   Guárdalo como `$AUTH_TYPE`. Por defecto: `browser`

3. **Credenciales** (opcional, para rellenar previamente el formulario con autenticación de navegador)
   > (Opcional) Introduce tu nombre de usuario de ServiceNow para rellenar previamente el formulario de inicio de sesión.
   > Déjalo en blanco para escribirlo manualmente cada vez.

   Guárdalo como `$USERNAME` (puede estar vacío).
   Si se proporciona, pide también `$PASSWORD`.

4. **Paquete de herramientas**
   > ¿Qué paquete de herramientas necesitas?
   > 1. standard — Herramientas básicas (incidentes, cambios, catálogo) [por defecto]
   > 2. service_desk — Standard + asignación, SLA, escalado
   > 3. portal_developer — Standard + widgets de portal, páginas, temas
   > 4. platform_developer — Standard + scripts, flujos, update sets
   > 5. full — La superficie empaquetada más amplia con flujos de trabajo incluidos (53 herramientas)

   Guárdalo como `$TOOL_PACKAGE`. Por defecto: `standard`

5. **Navegador headless**
   > ¿Ejecutar el navegador en modo headless? (sin ventana visible)
   > Recomendado: No (para que puedas ver y completar las solicitudes de MFA)

   Guárdalo como `$HEADLESS`. Por defecto: `false`

### Paso 4 — Ejecutar el comando del instalador

**IMPORTANTE: Usa siempre por defecto la instalación local del proyecto cuando el cliente lo soporte.** Usa `--scope global` solo si el usuario pide explícitamente una instalación global.

Construye un único comando de instalador y ejecútalo desde la raíz del proyecto actual. El instalador ahora se encarga de:
- las rutas de los archivos de configuración específicas de cada cliente
- el comportamiento de fusión/actualización para archivos de configuración existentes
- la instalación opcional de skills para los clientes soportados

Comando base:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS"
```

Añade flags solo cuando sea necesario:

- Si el usuario proporcionó un nombre de usuario: `--username "$USERNAME"`
- Si el usuario proporcionó una contraseña: `--password "$PASSWORD"`
- Para OAuth: añade `--client-id`, `--client-secret` y, opcionalmente, `--token-url`
- Para clave de API: añade `--api-key` y, opcionalmente, `--api-key-header`
- Si el usuario quiere una instalación global: añade `--scope global`
- Si el usuario **no** quiere skills: añade `--skip-skills`

Ejemplos:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup codex \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type basic \
  --username "your-username" \
  --password "your-password"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup claude-code \
  --instance-url "https://your-instance.service-now.com" \
  --scope global \
  --skip-skills
```

### Paso 5 — Verificar la instalación

1. Confirma que el instalador terminó correctamente
2. Lee la ruta del archivo de configuración indicada en el resumen del instalador
3. Si se instalaron skills, confirma que existe el directorio de skills instaladas
4. **No** reescribas manualmente la configuración salvo que el instalador haya fallado y estés reparándolo explícitamente

### Paso 6 — Decir al usuario qué pasa a continuación

Tras la instalación, dile al usuario:

> **¡La instalación está completa!**
> Reinicia tu cliente de IA (o recarga los servidores MCP) para que tome la nueva configuración.
>
> En la primera llamada a herramienta con autenticación de navegador, se abrirá una ventana del navegador para el inicio de sesión MFA/SSO.
> Después de iniciar sesión, prueba: `Run a health check on my ServiceNow instance`
> Documentación completa: https://jshsakura.github.io/mfa-servicenow-mcp/

**No** intentes llamar a herramientas MCP de ServiceNow en la sesión actual después de la configuración. El cliente debe reiniciarse primero.

### Notas importantes para el LLM

- **Nunca incrustes credenciales** en archivos de configuración sin preguntar. Si el usuario omite las credenciales, omítelas por completo de la configuración.
- El instalador fusiona en los archivos de configuración existentes. No hagas fusiones de configuración a mano salvo que sea necesario para una recuperación.
- Las **rutas de Windows** usan barras invertidas. Usa el separador de ruta correcto para el sistema operativo.
- Si algún paso falla, diagnostica el error y ayuda al usuario a corregirlo antes de continuar.
- Mantén la conversación amistosa y concisa. No vuelques muros de texto.
- Tras la instalación, NO intentes probar las herramientas MCP. Simplemente dile al usuario que reinicie y listo.
