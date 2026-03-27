# ServiceNow MCP Server

[English](./README.md) | [한국어](./README.ko.md)

MFA(다요소 인증) 및 SSO 환경을 위한 브라우저 인증 기반 ServiceNow MCP 서버입니다. Claude Desktop, Claude Code, OpenCode, Gemini Code Assist 같은 MCP 클라이언트에서 바로 사용할 수 있습니다.

[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)

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
        "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ]
    }
  }
}
```

#### OpenCode / Gemini / Vertex AI

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "enabled": true
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

### 4. 브라우저 인증 설정

브라우저 인증은 [Playwright](https://playwright.dev/)로 로컬 브라우저를 제어하여 MFA/SSO 로그인을 수행합니다. Playwright는 **선택적 의존성**이므로 별도 설치가 필요합니다:

```bash
# 1. Playwright 설치
pip install playwright
# 또는
uv pip install playwright

# 2. 브라우저 바이너리 설치 (로컬 Chromium 사용)
playwright install chromium
```

`uvx`로 사용하려면:

```bash
uvx --with playwright mfa-servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

한 번에 설치:

```bash
pip install "mfa-servicenow-mcp[browser]"
playwright install chromium
```

Playwright는 브라우저 인증에서만 필요합니다. Basic, OAuth, API Key 인증은 추가 설치 없이 바로 사용 가능합니다.

> Windows 사용자라면 [Windows 설치 및 실행 가이드](./WINDOWS_INSTALL.md)를 확인하세요.

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

환경변수:

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
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

| 패키지명 | 추천 역할 | 주요 포함 도구 |
| :--- | :--- | :--- |
| `standard` | 표준 사용자 | 인시던트, 카탈로그, 지식베이스, 코어 조회 |
| `portal_developer` | 포탈 개발자 | 포탈 코드, Script Include, 안전한 로그 조회, 서버 소스 조회, 워크플로우 조회, 체인지셋 커밋/퍼블리시 |
| `platform_developer` | 플랫폼 개발자 | Script Include, 안전한 로그 조회, 서버 소스 조회, 워크플로우, UI Policy, 체인지셋 관리 |
| `service_desk` | 운영/헬프데스크 | 인시던트 처리, 코멘트, 사용자 조회, 문서 조회 |
| `full` | 관리자 | 구현된 전 영역 도구 |

## 보안 정책

모든 수정형 도구는 명시적 승인 없이는 실행되지 않습니다.

규칙:
1. `create_`, `update_`, `delete_`, `execute_`, `add_`, `commit_`, `publish_` 계열은 승인 필요
2. 반드시 `confirm='approve'` 전달
3. 없으면 서버가 실행 전에 거부

이 정책은 어떤 도구 패키지를 쓰든 동일합니다.

## 개발용 설치

로컬에서 직접 수정하려면:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uv run playwright install chromium
```

> Windows 전용 절차: [WINDOWS_INSTALL.md](./WINDOWS_INSTALL.md)

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
