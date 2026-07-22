# Configuración del cliente MCP

Configuración detallada para cada cliente MCP. Todos los clientes usan el mismo servidor MCP — solo difiere el formato de configuración.

> **Empieza por aquí:** `uvx` es la instalación predeterminada en todas las plataformas. Si `uvx` no llega a ejecutarse — el motivo habitual es Smart App Control de Windows —, recurre a `pip`. Esas son las dos vías de instalación.

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

#### Si `uvx` está bloqueado — `pip`

Smart App Control de Windows impide directamente que `uvx` se ejecute: uvx descomprime un ejecutable temporal sin firmar en cada ejecución y SAC lo bloquea. Si uvx dejó de funcionar justo después de una actualización de Windows, casi con total seguridad la causa es esa. Instálalo con pip en su lugar:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Un Python del [instalador de python.org](https://www.python.org/downloads/) (firmado, 3.10+) pasa el filtro de SAC sin más. Arranca el servidor con `python -m servicenow_mcp` — **no** con el script de consola `servicenow-mcp`, que es un `.exe` puente sin firmar generado por pip y que SAC también bloquea.

> En macOS/Linux la única pega de pip es que los Python de Homebrew y de la distribución rechazan las instalaciones globales según la [PEP 668](https://peps.python.org/pep-0668/) (`externally-managed-environment`). Usa el instalador de python.org, o simplemente quédate con uvx.

Si **el bloqueo alcanza al propio PyPI** —una red corporativa que corta el índice de paquetes—, ninguna de las dos vías puede descargar nada. Pide a IT que incluya `pypi.org` y `files.pythonhosted.org` en la lista de permitidos, o que replique el paquete en un índice interno al que puedas apuntar con `pip install --index-url`.

> Usuarios de Windows: consulta la [Guía de instalación en Windows](WINDOWS_INSTALL.md) para ver detalles paso a paso y notas sobre proxy/antivirus.

### 3. Añade el servidor a la configuración de tu cliente MCP

Añade una entrada al archivo de configuración de tu cliente (no se necesita ningún comando de instalación). **El bloque `env` es idéntico sea cual sea la forma de instalación** — solo `command`/`args` dependen de la vía que hayas elegido arriba:

| Instalación | `command` | `args` |
|---|---|---|
| uvx (predeterminada) | `uvx` | `["--with","playwright","--from","mfa-servicenow-mcp","servicenow-mcp"]` |
| pip (uvx bloqueado) | `python` | `["-m","servicenow_mcp"]` |

Todos los ejemplos por cliente de más abajo muestran la forma con uvx. Con pip, cambia esas dos claves y deja todo lo demás intacto.

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

### Prueba rápida

Verifica que el servidor arranca antes de configurar tu cliente:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"

# pip install: replace the first line with
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

Si el servidor arranca y se abre una ventana del navegador para iniciar sesión, ya estás listo para configurar tu cliente más abajo.

---

## Guía de configuración

> **`args` es solo para el paquete** — la URL de la instancia, la autenticación y las credenciales van todas en `env` (o `environment`). Esto mantiene `args` limpio y facilita el cambio de instancias por proyecto.

> **Recomendado a nivel de proyecto**: Usa configuración con alcance de proyecto para que cada proyecto pueda conectarse a una instancia de ServiceNow diferente.

Todo lo que sigue varía únicamente dentro de `env`. `command`/`args` se quedan tal como los dejaste en el [paso 3](#3-añade-el-servidor-a-la-configuración-de-tu-cliente-mcp), sea cual sea la ruta de instalación que hayas seguido.

### Perfiles — empieza aquí

Si tocas más de una instancia de ServiceNow, **configura perfiles en lugar de levantar un servidor por instancia.** Dale un alias a cada entorno y elige cuál está activo:

```json
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"prod\": { \"url\": \"https://acme-prod.service-now.com\", \"auth_type\": \"browser\" } }"
      }
```

Ese único bloque sustituye a `SERVICENOW_INSTANCE_URL`, y es lo que hace funcionar el resto de esta guía:

- **Producción queda protegida por omisión.** Un alias sin `allow_writes` es de solo lectura. En el `prod` de arriba no se puede escribir en absoluto: olvidar un flag nunca podrá habilitar una escritura en producción.
- **Llega a otra instancia sin reiniciar.** Las herramientas de lectura aceptan un argumento `instance`: `sn_query(instance="prod", …)` mientras `dev` sigue activa.
- **Compara entornos directamente.** `compare_instances` compara el mismo registro entre dos alias; `list_instances` muestra cada alias y su flag de escritura.
- **Un solo inicio de sesión en el navegador.** La sesión se comparte entre alias en vez de un login por cada proceso de servidor.
- **Las escrituras a una instancia no activa están protegidas**, nunca son silenciosas: consulta [Modo Multi-Instancia](#modo-multi-instancia-comparación--escrituras-guardadas-de-una-sola-llamada) para las reglas de enrutado, el control `confirm_instance` y las referencias a secretos `${ENV}`.

### Una sola instancia

¿Solo una instancia? Sáltate los perfiles por completo: dos variables son toda la configuración.

```json
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
```

Esta forma sigue funcionando y no está obsoleta; es simplemente el caso más simple de la configuración por perfiles de arriba.

### ¿Una conexión o varias?

Los perfiles ponen todas las instancias detrás de **una sola** conexión de cliente, que es lo que quiere casi todo el mundo. Si en cambio necesitas conexiones visualmente distintas en la interfaz del cliente —una entrada `snow-dev` y otra `snow-prd`—, mira [Nombrar varias entradas de servidor](#nombrar-varias-entradas-de-servidor---server-name). Eso renuncia a `compare_instances`, al inicio de sesión compartido y al control `allow_writes`, así que elígelo solo por esa separación visual.

---

## Streamable HTTP

El transporte predeterminado es `stdio`. Para clientes MCP remotos o un puente HTTP local, arranca el servidor con Streamable HTTP:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
# pip install: python -m servicenow_mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

El endpoint MCP es `http://127.0.0.1:8000/mcp`; `/health` devuelve una respuesta de estado ligera. Mantén el host de loopback predeterminado a menos que el servidor esté detrás de controles de red de confianza.

---

## Modo Multi-Instancia (comparación + escrituras guardadas de una sola llamada)

Configura instancias con nombre (p. ej. alias `dev` / `test` / `prod`) mediante `SERVICENOW_INSTANCE_CONFIG` para que una misma sesión pueda tanto comparar entre entornos COMO desplegar en uno elegido — sin cambiar la instancia activa ni reiniciar el servidor. Enruta una sola llamada con el argumento `instance=<alias>`:

- Las llamadas **de solo lectura** se enrutan libremente: `instance=test` lee `test` mientras `dev` permanece activa.
- Las **escrituras** hacia una instancia no activa están permitidas pero nunca son silenciosas. Esa única llamada debe *nombrar el destino y aprobarlo* — `instance=test confirm_instance=test confirm=approve` — y el destino debe tener `allow_writes=true`. Solo esa escritura se enruta allí; la instancia activa se restaura inmediatamente después. Un desajuste entre destino/confirm o un destino de solo lectura se rechaza con un mensaje explícito, de modo que una confusión entre dev/test/prod no puede acabar en la instancia equivocada.
- **La escritura se verifica en el destino.** El resultado incluye `target_instance` y un veredicto `landed`: la herramienta vuelve a leer los campos empujados en el destino y devuelve `WRITE_NOT_LANDED` si el contenido no persistió (p. ej. un campo `sp_*` de Service Portal descartado en silencio). «Éxito» significa que se ha confirmado que el contenido está presente en la instancia prevista — no solo que la petición devolvió un 200.
- `compare_instances` compara registros entre alias (de solo lectura); `list_instances` informa de los alias configurados y el indicador de escritura de cada uno.
- Mantén `prod` en `allow_writes=false` a menos que pretendas deliberadamente escribir en producción — así un indicador olvidado nunca podrá habilitar una.

> Para promover MUCHOS registros (especialmente tablas de Service Portal / scoped), prefiere un Update Set — commit en el origen, retrieve + commit en el destino desde la UI — antes que escrituras cross-instance registro por registro; así evita los ACL por tabla/SP que sí bloquean una sola escritura de la Table API.

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "auth_type": "browser", "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "auth_type": "browser", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "auth_type": "browser", "allow_writes": false }
}'
```

Credenciales por instancia, en un bloque `env` del cliente MCP (cada alias puede llevar su propio `username` / `password` / `auth_type` / `api_key`; `${ENV}` mantiene los secretos fuera del JSON; la forma de instancia única `SERVICENOW_INSTANCE_URL` sigue funcionando como alternativa):

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

Para una sola escritura contra una instancia no activa, usa el enrutamiento protegido `instance=<alias> confirm_instance=<alias> confirm=approve` de arriba. Para promover MUCHOS registros, prefiere un Update Set en lugar de escrituras entre instancias registro por registro.

---

## Nombrar varias entradas de servidor (`--server-name`)

Esta es una topología distinta del modo multi-instancia de arriba. Multi-instancia = **una sola** conexión capaz de alcanzar varias instancias. Esta sección = **varias conexiones separadas**, un proceso por instancia, cada uno fijado a la suya — solo merece la pena cuando quieres ver dev/stg/prd claramente separadas en la interfaz del cliente.

El inconveniente: cada entrada se anuncia como `ServiceNow` de forma predeterminada, así que el cliente las distingue por orden de carga — `mcp_servicenow`, `mcp_servicenow2`, `mcp_servicenow3`. Esa numeración puede cambiar entre reinicios, lo que la vuelve **poco fiable para saber qué conexión es la de producción.** Dale un nombre a cada una con `--server-name`:

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

Los nombres de las herramientas quedan entonces fijados como `mcp_snow-dev_*` / `mcp_snow-prd_*`. `SERVICENOW_MCP_SERVER_NAME` hace lo mismo como variable de entorno, y si se definen ambos gana el flag. Sin definir, el nombre sigue siendo `ServiceNow`, de modo que las configuraciones existentes siguen funcionando.

**Prefiere los perfiles siempre que puedas.** Para moverte entre instancias dentro de una misma conexión, el enfoque recomendado es el [Modo Multi-Instancia](#modo-multi-instancia-comparación--escrituras-guardadas-de-una-sola-llamada): solo él te da `compare_instances`, un único inicio de sesión compartido en el navegador y el control `allow_writes` por alias. Los procesos separados no tienen nada de eso — cada uno conoce únicamente su propia instancia, inicia sesión por su cuenta y el paquete de herramientas es lo único que se interpone entre tú y una escritura en producción.

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
