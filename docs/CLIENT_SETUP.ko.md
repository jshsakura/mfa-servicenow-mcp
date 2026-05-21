# MCP 클라이언트 설정

각 MCP 클라이언트별 상세 설정 가이드입니다. 모든 클라이언트는 동일한 MCP 서버를 사용하며, 설정 형식만 다릅니다.

> **먼저 권장하는 방법:** 아래 `uvx` setup 명령을 사용하세요. 회사 보안툴이 `uvx`를 막는 환경이면 릴리즈 zip/exe 섹션을 사용하세요.

---

## 시작하기 전에

기본 설치는 `uvx`입니다. macOS, Linux, Windows에서 같은 흐름으로 설치와 MCP 설정을 맞춥니다.

### 1. uv 설치

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Playwright Chromium 설치

```bash
uvx --with playwright playwright install chromium
```

Playwright는 표준 브라우저 캐시를 사용합니다. `uvx`가 로컬 Playwright Python 패키지를 자동으로 우선 사용하지는 않지만, 같은 Chromium revision이 표준 캐시에 있으면 다시 다운로드하지 않습니다.

### 3. setup 실행

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

```powershell
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser"
```

### 로컬 설치 (릴리즈 zip/exe)

`uvx`나 PyPI 접속이 막히는 사내망에서 사용하는 경로입니다. 릴리즈 zip은 **PyInstaller로 빌드된 단일 실행 파일** — 설치 스크립트 없음, Python 불필요, 시스템 캐시 오염 없음. 실행 파일이 자기 옆 `ms-playwright/` 폴더를 자동으로 인식합니다.

**1. [GitHub Releases](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest)에서 다운로드:**

실행 파일은 [최신 릴리즈](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest), 선택적 Chromium 번들(네트워크가 Playwright 자동 다운로드까지 막을 때만)은 고정 [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) 릴리즈에서 받으세요 — 매 버전 재첨부 안 함.

| 플랫폼 | 필수 (최신 릴리즈) | Chromium 막히면 추가로 (chromium-bundle 릴리즈) |
|--------|---------------------|--------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. 아래 구조로 배치** — 본인이 관리하는 안정적인 경로면 어디든 OK. **zip은 미리 다 풀어두세요** — `.zip` 파일을 실행 파일 옆에 남기지 말고. Chromium zip을 푼 폴더 이름은 `ms-play`로 시작하고 안에 `chromium-*` 서브디렉토리만 있으면 됩니다:

```
~/apps/servicenow-mcp/                                  (본인이 정하는 경로)
├── servicenow-mcp                                      ← 플랫폼 zip에서 (Windows는 .exe)
└── ms-playwright-chromium-linux-x64-<ver>/             ← 기본 추출 이름 그대로 OK
    └── chromium-1185/
        └── …
```

(정리해 두고 싶으면 `ms-playwright/`로 이름 변경해도 됩니다 — 둘 다 동작.) 시작 시 실행 파일이 자기 옆 `ms-play*` 디렉토리를 글롭으로 찾고, 안에 `chromium-*` 서브디렉토리가 있으면 그 경로로 `PLAYWRIGHT_BROWSERS_PATH`를 **현재 프로세스에만** 설정합니다. 시스템 Playwright 캐시는 **건드리지 않고**, MCP 클라이언트 설정 파일도 **건드리지 않고**, 디스크에 아무것도 **쓰지 않습니다**.

**3. 동작 확인 후 MCP 클라이언트 연결:**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

아래 [설정 가이드](#설정-가이드)의 MCP 스니펫을 본인 클라이언트 설정 파일에 붙여넣고, `command`를 실행 파일 절대 경로로 지정하세요. `env` 블록은 uvx 설정과 동일 — `command`만 다릅니다. Chromium을 실행 파일 옆이 *아닌* 다른 위치에 두었다면 env에 `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"`를 추가하세요.

Chromium zip을 받지 못했고 사내 망에서 Playwright 자동 다운로드도 막힌다면 Python이 가능한 PC에서 같은 구조로 디렉토리를 만들어 두세요:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

자동 인식이 그대로 동작합니다.

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
        "SERVICENOW_USERNAME": "your-username",
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
MCP_TOOL_PACKAGE = "standard"
# 로그인은 호스트 간 자동 공유됩니다 (~/.mfa_servicenow_mcp 아래 인스턴스+유저 단위로 분리).
# SERVICENOW_BROWSER_USER_DATA_DIR는 샌드박스 호스트가 HOME을 리매핑한 경우에만 설정 —
# README "로그인 공유" 항목 참고. 인스턴스를 여러 개 돌릴 땐 설정하지 마세요;
# 모든 인스턴스가 Chromium 프로필 하나에 묶입니다.
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
        "SERVICENOW_USERNAME": "your-username",
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
        "SERVICENOW_USERNAME": "your-username",
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
