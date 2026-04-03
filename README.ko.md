# ServiceNow MCP Server

[English](./README.md) | [한국어](./README.ko.md)

MFA(다요소 인증) 및 SSO 환경을 위한 브라우저 인증 기반 ServiceNow MCP 서버입니다. Claude Desktop, Claude Code, OpenCode, Gemini Code Assist 같은 MCP 클라이언트에서 바로 사용할 수 있습니다.

[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)

## 필수 준비 사항 (Prerequisites)

서버를 등록하기 전에 아래 도구들이 설치되어 있는지 확인하세요.

### 1. `uv` 설치 (권장)

이 프로젝트는 [uv](https://astral.sh/uv)에 최적화되어 있습니다.

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### 2. 브라우저 바이너리 설치 (`browser` 인증 필수)

MFA/SSO 환경에서 `auth-type: browser`를 사용하려면 로컬 시스템에 Chromium 브라우저 바이너리가 설치되어 있어야 합니다:

```bash
# uvx를 사용하여 전역 설치 없이 브라우저 바이너리만 설치
uvx playwright install chromium
```

### 3. Windows 전용 팁

Windows 사용자는 PowerShell에서 스크립트 실행 권한이 허용되어 있어야 합니다:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

상세한 Windows 설치 가이드는 [WINDOWS_INSTALL.md](./WINDOWS_INSTALL.md)에서 확인하세요.

## 바로 쓰기

대부분의 사용자는 Git으로 소스를 받을 필요가 없습니다. [uv](https://astral.sh/uv)만 있으면 MCP 클라이언트 설정에 바로 넣어 쓸 수 있습니다.

### 1. MCP 클라이언트에 등록

#### Claude Desktop

`claude_desktop_config.json`에 아래처럼 넣으면 됩니다.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with",
        "playwright",
        "mfa-servicenow-mcp",
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

#### OpenCode / Gemini / Vertex AI

이 계열 호스트는 보통 아래 두 가지 실행 방식 중 하나로 쓰면 관리가 편합니다.

##### `uvx`로 실행

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright", "mfa-servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
    }
  }
}
```

##### 체크아웃한 소스에서 바로 실행

이 저장소를 로컬에 clone 해 두었다면 프로젝트 경로를 지정해서 `uv run`으로 바로 실행하면 됩니다.

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "--project",
        "/absolute/path/to/mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
    }
  }
}
```

> `SERVICENOW_BROWSER_USERNAME`, `SERVICENOW_BROWSER_PASSWORD`는 필수는 아니지만, MFA/SSO 로그인 화면에 계정을 미리 채우고 싶을 때 유용합니다.

#### AntiGravity

AntiGravity Editor는 Claude Desktop 스타일의 `mcpServers` 설정을 사용합니다. 에디터 우측 에이전트 패널 상단의 **점 세 개(...)** -> **Manage MCP Servers** -> **View raw config**를 눌러 설정 파일을 편집할 수 있습니다.

- **macOS/Linux:** `~/.gemini/antigravity/mcp_config.json`
- **Windows:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

##### `uvx`로 실행 (권장)

`auth-type: browser`를 사용할 경우, `uvx` 실행 환경에 브라우저 제어 의존성이 포함되도록 `--with playwright`를 **반드시** 추가해야 합니다.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with",
        "playwright",
        "mfa-servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

##### 체크아웃한 소스에서 바로 실행

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> **주의:** 설정을 저장한 후 AntiGravity의 MCP 관리 화면에서 **Refresh**를 눌러주세요. 브라우저 인증을 사용한다면 로컬에 `playwright install chromium`이 완료된 상태여야 합니다.

#### OpenAI Codex

`codex.json`에 추가하거나 CLI로 전달합니다:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false",
        "--tool-package", "standard"
      ]
    }
  }
}
```

### 2. 터미널에서 바로 실행

```bash
uvx mfa-servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

- 최초 실행 시 브라우저 관련 의존성이 자동으로 준비될 수 있습니다.
- 브라우저 인증에서는 로그인 창이 뜰 수 있습니다.
- `--browser-headless false`를 주면 MFA/SSO 확인이 더 쉽습니다.

### 3. 로컬에 설치해서 계속 쓰기

```bash
uv tool install mfa-servicenow-mcp
servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

### 4. 최신 버전으로 업데이트

#### macOS / Linux

```bash
# uvx (--refresh로 PyPI 최신 버전을 강제로 가져오기)
uvx --refresh mfa-servicenow-mcp --version

# uv tool
uv tool upgrade mfa-servicenow-mcp

# pip
pip install --upgrade mfa-servicenow-mcp
```

#### Windows

```powershell
# uv tool
uv tool upgrade mfa-servicenow-mcp

# pip
pip install --upgrade mfa-servicenow-mcp
```

### 5. 브라우저 인증 설정 (Browser Auth)

브라우저 인증은 [Playwright](https://playwright.dev/)를 통해 로컬 브라우저를 제어합니다.

`uvx` 실행 시 `--with playwright` 플래그를 사용하면 라이브러리는 자동으로 준비되지만, [필수 준비 사항](#2-브라우저-바이너리-설치-browser-인증-필수)에서 언급한 **브라우저 바이너리**는 미리 설치되어 있어야 합니다.

```bash
# 1단계: 브라우저 바이너리 설치 확인
uvx playwright install chromium

# 2단계: playwright 의존성을 주입하여 실행
uvx --with playwright mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

Playwright는 브라우저 인증에서만 필요합니다. Basic, OAuth, API Key 인증은 추가 설치 없이 바로 사용 가능합니다.

> Windows 사용자라면 [Windows 설치 가이드](./WINDOWS_INSTALL.md)를 확인하세요.

## 주요 특징

- MFA/SSO 환경용 브라우저 인증
- `confirm='approve'` 기반 수정 승인 정책
- 대형 레코드에 대한 자동 제한 및 절단
- 표준 사용자, 운영자, 포탈 개발자, 플랫폼 개발자용 도구 패키지
- 로그 조회, 서버 소스 조회, 워크플로우 조회, 체인지셋 관리 같은 개발자 기능

## 인증 방법

ServiceNow 환경에 맞는 인증 방식을 선택하세요.

### 브라우저 인증

Okta, Entra ID, SAML, MFA 같은 대화형 로그인 환경에 적합합니다.

```bash
uvx mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

추가 옵션:
- `--browser-username`
- `--browser-password`
- `--browser-user-data-dir`
- `--browser-timeout`
- `--browser-probe-path`

기타 옵션:
- `--tool-package` — 도구 패키지 선택 (환경변수: `MCP_TOOL_PACKAGE`, 기본값: `standard`)
- `--timeout` — HTTP 요청 타임아웃 초 (환경변수: `SERVICENOW_TIMEOUT`, 기본값: `30`)

환경변수:

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_USERNAME=your.username
SERVICENOW_BROWSER_PASSWORD=your-password
MCP_TOOL_PACKAGE=standard
```

### Basic 인증

MFA가 없는 PDI나 테스트 인스턴스용입니다.

```bash
uvx mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

환경변수 예시:

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=your.username
SERVICENOW_PASSWORD=your-password
```

### OAuth 인증

현재 CLI는 OAuth password grant 입력 기준입니다.

```bash
uvx mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

`--token-url`을 지정하지 않으면 기본적으로 `https://<instance>/oauth_token.do`를 사용합니다.

### API Key 인증

```bash
uvx mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

기본 헤더는 `X-ServiceNow-API-Key`입니다.

## 도구 패키지

`MCP_TOOL_PACKAGE`를 설정하여 도구 세트를 선택할 수 있습니다. 기본값: `standard`

모든 패키지는 읽기 전용 도구 48개를 기본 포함하며, 상위 패키지는 도메인별 수정 권한을 추가합니다.

| 패키지명 | 도구 수 | 설명 |
| :--- | :--- | :--- |
| `standard` | 48 | **(기본값)** 읽기 전용 safe mode. 전 도메인 조회/분석 도구 포함 |
| `portal_developer` | 58 | standard + 포탈/위젯 수정, Script Include 수정, 체인지셋 커밋/퍼블리시 |
| `platform_developer` | 71 | standard + 워크플로우 CRUD, UI Policy, 인시던트/변경관리 수정 |
| `service_desk` | 52 | standard + 인시던트 생성/처리/해결/코멘트 |
| `full` | 86 | 전 도메인 수정/삭제 가능 |

현재 패키지에 없는 도구를 호출하면, 어느 패키지에서 사용 가능한지 안내합니다.

카테고리별 전체 도구 목록은 [Tool Inventory](docs/TOOL_INVENTORY.md)에서 확인할 수 있습니다.

## 보안 정책

모든 수정형 도구는 명시적 승인 없이는 실행되지 않습니다.

규칙:
1. `create_`, `update_`, `delete_`, `execute_`, `add_`, `commit_`, `publish_` 계열은 승인 필요
2. 반드시 `confirm='approve'` 전달
3. 없으면 서버가 실행 전에 거부

이 정책은 어떤 도구 패키지를 쓰든 동일합니다.

포탈 조사 도구도 기본적으로 보수적으로 동작합니다.

- `search_portal_regex_matches`는 기본적으로 widget만 조회하고 linked 확장은 꺼져 있으며 기본 제한도 작게 잡혀 있습니다.
- `trace_portal_route_targets`는 LLM에게 Widget → Provider → route target 근거를 최소 결과 형태로 넘길 때 권장되는 후속 도구입니다.
- `sn_query`는 일반 레코드 조회용 fallback으로 보고, 포탈 소스/라우팅 분석의 1순위 도구로 쓰지 않는 것이 좋습니다.
- `download_portal_sources`도 명시적으로 요청하지 않으면 Script Include, Angular Provider를 따라가지 않습니다.
- 큰 포탈 스캔 요청은 서버에서 상한이 적용되며, 안전 기본값보다 넓은 요청에는 경고를 반환합니다.
- 권장 흐름은 특정 위젯 1~2개를 먼저 지정하고, 정말 필요할 때만 linked 확장과 범위를 늘리는 것입니다.

예시: 특정 위젯만 대상으로 조회

```json
{
  "regex": "click-event|another-query",
  "widget_ids": ["portal-widget-id"],
  "max_widgets": 1,
  "max_matches": 20
}
```

LLM 친화적인 pattern matching 모드:

- `match_mode: "auto"` (기본값): 일반 문자열은 literal로 처리하고, regex처럼 보이는 패턴만 regex로 처리합니다.
- `match_mode: "literal"`: 패턴을 항상 escape해서 안전하게 찾습니다. 경로나 토큰 문자열만 있을 때 가장 무난합니다.
- `match_mode: "regex"`: 정규식 연산자가 정말 필요할 때만 사용합니다.

예시: LLM 친화적인 route trace

```json
{
  "regex": "my-search-regex",
  "match_mode": "auto",
  "widget_ids": ["portal-widget-id"],
  "include_linked_angular_providers": true,
  "output_mode": "minimal"
}
```

예시: 확장이 필요한 경우에만 명시적으로 요청

```json
{
  "regex": "click-event|another-query",
  "widget_ids": ["portal-widget-id", "legacy-widget-id"],
  "include_linked_script_includes": true,
  "include_linked_angular_providers": true,
  "max_widgets": 2,
  "max_matches": 50
}
```

## 개발용 설치

로컬에서 직접 수정하려면:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uv run playwright install chromium
```

> Windows 설치: [WINDOWS_INSTALL.md](./WINDOWS_INSTALL.md)

## 상세 문서

- [서비스 카탈로그 가이드](docs/catalog.md)
- [변경 관리 가이드](docs/change_management.md)
- [워크플로우 및 개발 도구](docs/workflow_management.md)
- [English README](./README.md)

## 관련 프로젝트 및 참고

- 이 저장소의 일부 도구는 기존 내부/레거시 ServiceNow MCP 구현들을 정리하고 재구성한 결과물입니다. 그 흔적은 [core_plus.py](./src/servicenow_mcp/tools/core_plus.py), [tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py) 같은 모듈에서 볼 수 있습니다.
- 개발자 생산성 기능, 특히 서버 소스 조회 흐름은 [SN Utils](https://github.com/arnoudkooi/SN-Utils)의 아이디어를 참고해 설계했습니다. 다만 이 프로젝트는 SN Utils 코드를 포함하거나 재배포하지 않고, MCP 서버용 기능으로 별도 구현합니다.
- 이 프로젝트는 브라우저 확장 UX 자체보다 MCP 서버 사용 시나리오에 초점을 둡니다. ServiceNow 화면 안에서 바로 쓰는 생산성 기능이 필요하면 SN Utils를 함께 사용하는 것도 좋은 선택입니다.

## 라이선스

MIT License
