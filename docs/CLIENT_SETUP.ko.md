# MCP 클라이언트 설정

각 MCP 클라이언트별 상세 설정 가이드입니다. 모든 클라이언트는 동일한 MCP 서버를 사용하며, 설정 형식만 다릅니다.

> **먼저 권장하는 방법:** `servicenow-mcp setup <client> --instance-url ...`를 실행하거나 [`llm-setup.ko.md`](llm-setup.ko.md)의 AI 자동 설치 흐름을 사용하세요. 아래 설정 예시는 MCP 설정을 직접 점검하거나 수동 복구해야 할 때 참고하는 용도입니다.

---

## 시작하기 전에

**두 가지를 미리 설치**해야 합니다. 둘 중 하나라도 빠지면 첫 브라우저 인증 호출이 도중에 다운로드 시도하다가 멈춥니다.

### 1. `uv` 설치

`uv`가 Python · 패키지 · 실행을 한 번에 처리합니다. MCP 서버는 `uvx`로 실행되며 `uv`가 필요합니다.

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

설치 후 터미널을 재시작하세요. Python 설치, pip, venv 전부 필요 없습니다.

### 2. Chromium 미리 설치 (필수)

MFA/SSO 로그인 창은 Playwright가 띄우는 Chromium입니다 — 필수 종속성입니다. Playwright와 MCP 서버 실행 경로가 엇갈리지 않도록 Chromium 설치도 `uvx`로 실행하세요:

```bash
uvx --with playwright playwright install chromium
```

브라우저 바이너리는 `~/.cache/ms-playwright/` (macOS/Linux) 또는 `%USERPROFILE%\AppData\Local\ms-playwright\` (Windows)에 캐시되며 MCP 버전과 무관하게 공유됩니다. Playwright 자체가 업그레이드될 때만 같은 `uvx --with playwright playwright install chromium` 명령을 다시 실행하세요.

#### 회사 프록시 / Zscaler 우회

TLS 검사나 엄격한 outbound allowlist 때문에 `uvx` 또는 Chromium 아카이브 다운로드가 막히면, 설치 명령은 그대로 두고 사내 네트워크 변수만 먼저 지정하세요:

```bash
# macOS/Linux
export HTTPS_PROXY="http://proxy.company.example:8080"
export HTTP_PROXY="$HTTPS_PROXY"
export UV_NATIVE_TLS=true
export UV_DEFAULT_INDEX="https://pypi.company.example/simple"          # PyPI를 사내 미러로 받는 경우
export PLAYWRIGHT_DOWNLOAD_HOST="https://artifacts.company.example/playwright"  # 브라우저 아카이브를 사내 미러로 받는 경우
uvx --with playwright playwright install chromium
```

```powershell
# Windows PowerShell
$env:HTTPS_PROXY="http://proxy.company.example:8080"
$env:HTTP_PROXY=$env:HTTPS_PROXY
$env:UV_NATIVE_TLS="true"
$env:UV_DEFAULT_INDEX="https://pypi.company.example/simple"          # PyPI를 사내 미러로 받는 경우
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://artifacts.company.example/playwright"  # 브라우저 아카이브를 사내 미러로 받는 경우
uvx --with playwright playwright install chromium
```

프록시, 사내 PyPI 인덱스, 브라우저 아카이브 미러 값은 반드시 사내 IT/보안팀이 제공한 값만 사용하세요. `UV_DEFAULT_INDEX`는 Python 패키지 다운로드 정책용이고, `PLAYWRIGHT_DOWNLOAD_HOST`는 Playwright 브라우저 아카이브 위치용입니다.

> Windows 사용자: 단계별 안내 + 프록시/백신 관련 주의사항은 [Windows 설치 가이드](WINDOWS_INSTALL.ko.md) 참조.

### 동작 확인

클라이언트 설정 전에 서버가 정상 작동하는지 먼저 확인하세요:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

서버가 시작되고 로그인용 브라우저 창이 열리면, 아래 클라이언트 설정으로 넘어갈 준비가 된 것입니다.

---

## 설정 가이드

> **`args`는 패키지 실행에만 사용합니다**. 인스턴스 URL, 인증 방식, 자격 증명은 모두 `env`(또는 `environment`)에 넣으세요. 이렇게 하면 args가 깔끔하게 유지되고, 프로젝트별로 다른 인스턴스에 쉽게 연결할 수 있습니다.

> **프로젝트 로컬 설정을 권장합니다**: 프로젝트 단위로 설정하면 각 프로젝트가 서로 다른 ServiceNow 인스턴스에 연결할 수 있습니다.

> **단일 active 인스턴스 설계**: 일반 도구는 하나의 active ServiceNow 인스턴스에만 라우팅됩니다. dev/test/prod 사이를 오갈 때 운영에 잘못 쓰는 사고를 막기 위해 요청 시점의 쓰기 대상 전환은 의도적으로 피합니다.

---

## Streamable HTTP

기본 transport는 `stdio`입니다. 원격 MCP 클라이언트나 로컬 HTTP 브리지가 필요하면 Streamable HTTP로 실행할 수 있습니다.

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP 엔드포인트는 `http://127.0.0.1:8000/mcp`이고, `/health`는 가벼운 상태 응답을 반환합니다. 신뢰된 네트워크 제어 뒤에 둔 경우가 아니라면 기본 loopback 호스트를 유지하세요.

---

## 읽기 전용 데이터 비교 모드

dev/test drift 분석이 필요할 때 `SERVICENOW_INSTANCE_CONFIG`로 named instance를 설정할 수 있습니다. 이 모드는 의도적으로 데이터 비교 용도로만 제한됩니다.

- 일반 도구는 여전히 `SERVICENOW_ACTIVE_INSTANCE`로만 라우팅됩니다.
- 쓰기 가능한 도구에는 인스턴스 선택 파라미터가 없습니다.
- `compare_instances`는 alias 간 레코드를 read-only로 비교합니다.
- `list_instances`는 설정된 alias만 보여줍니다.
- 비교 alias는 read-only 패키지와 `allow_writes=false`로 설정하세요.
- 이 모드를 환경 간 쓰기 작업에 사용하지 마세요.

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev": {
    "url": "https://dev.service-now.com",
    "role": "development",
    "tool_package": "standard",
    "allow_writes": false
  },
  "test": {
    "url": "https://test.service-now.com",
    "role": "test",
    "tool_package": "standard",
    "allow_writes": false
  }
}'
```

비교 예시:

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

다른 인스턴스에 실제 작업을 해야 한다면 프로젝트/클라이언트 설정을 분리하세요.

---

## Claude Desktop

| 범위 | 경로 |
|------|------|
| 전역 | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| 전역 | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Claude Desktop은 프로젝트 로컬 설정을 지원하지 않습니다. 프로젝트별 설정이 필요하면 Claude Code를 사용하세요.

---

## Claude Code

| 범위 | 경로 |
|------|------|
| 전역 | `~/.claude.json` |
| 프로젝트 | 프로젝트 루트의 `.mcp.json` |

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Zed

| 범위 | 경로 |
|------|------|
| 전역 | `~/.config/zed/settings.json` |

Zed에서 **Settings** > **MCP Servers**로 추가하세요:

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

## OpenAI Codex (CLI & App)

**Codex CLI**(`codex` 명령어)와 **Codex App**(chatgpt.com/codex) 모두 동일한 `config.toml`을 사용합니다.

| 범위 | 경로 | 비고 |
|------|------|------|
| 전역 | `~/.codex/config.toml` | 모든 프로젝트에 공통 적용 |
| 프로젝트 | `.codex/config.toml` | 전역 설정을 덮어씀 (신뢰하는 프로젝트만) |

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
# 다른 MCP 호스트(Claude, Cursor 등)와 로그인 상태를 공유하려면
# 모든 호스트의 설정에 **같은 절대 경로**를 지정하세요. macOS Codex.app은
# 샌드박스라 `~`이 리매핑되므로, 이 값을 안 맞추면 호스트마다 별도 세션
# 캐시를 쓰게 되고 매번 MFA 로그인 창이 새로 뜹니다. `/Users/me`는 본인 $HOME으로 바꾸세요.
SERVICENOW_BROWSER_USER_DATA_DIR = "/Users/me/.servicenow_mcp/shared/profile_acme"
MCP_TOOL_PACKAGE = "standard"
```

---

## OpenCode

| 범위 | 경로 |
|------|------|
| 프로젝트 | 프로젝트 루트의 `opencode.json` |

> OpenCode는 `env` 대신 `environment`를 사용합니다.

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Gemini CLI

| 범위 | 경로 |
|------|------|
| 전역 | `~/.gemini/settings.json` |
| 프로젝트 | 프로젝트 루트의 `.gemini/settings.json` |

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## AntiGravity

| 범위 | 경로 |
|------|------|
| 전역 | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| 전역 | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> 에이전트 패널에서도 수정할 수 있습니다: **...** > **Manage MCP Servers** > **View raw config**. 저장 후 **Refresh**를 클릭하세요.

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
        "SERVICENOW_USERNAME": "your.username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Docker (API Key만 지원)

> 브라우저 인증(MFA/SSO)은 GUI 브라우저가 필요하여 컨테이너 환경에서는 동작하지 않습니다.

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
