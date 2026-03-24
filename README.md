# ServiceNow MCP Server

ServiceNow용 Model Context Protocol (MCP) 서버 구현체입니다. MFA(다요소 인증) 및 SSO가 설정된 환경에서도 브라우저 인증을 통해 완벽하게 동작합니다.

[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)

---

## ⚡ 초간편 실행 (추천)

소스 코드를 다운로드하거나 개발 환경을 구축할 필요가 없습니다. [uv](https://astral.sh/uv)가 설치되어 있다면 명령어 한 줄로 즉시 실행 가능합니다.

```bash
# 1. 서버 실행 (최초 실행 시 브라우저 엔진 자동 설치)
uvx mfa-servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

> **Windows 사용자라면?** 도커 없이 브라우저 인증을 가장 편하게 사용하는 방법인 [Windows 설치 및 실행 가이드](./WINDOWS_INSTALL.md)를 확인하세요.

---

## ✨ 주요 특징

- **MFA/SSO 완벽 지원:** Playwright 기반 브라우저 인증 모드로 Okta, Microsoft Authenticator 등 모든 인증 환경 대응
- **Zero Configuration:** `uvx`를 통한 소스 코드 없는 즉시 실행 지원
- **강력한 보안:** 수정/삭제 작업 시 명시적 확인(`confirm='approve'`) 요구 정책 적용
- **데이터 안전장치:** 페이로드 폭발 방지를 위한 자동 Limit 및 필드 절단(Truncation) 기능
- **방대한 도구 모음:** 인시던트, 서비스 카탈로그, 변경 관리, 워크플로우, 지식베이스 등 ServiceNow 전 영역 커버

---

## 🚀 시작하기

### 1. 설치 방법 (개발자용)

소스 코드를 직접 수정하거나 로컬에서 실행하고 싶다면 다음 과정을 따르세요.

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

# Windows 통합 설치 스크립트 실행 (추천)
.\setup_windows.ps1

# 또는 수동 설치
uv venv
uv pip install -e .
uv run playwright install chromium
```

### 2. 인증 설정

#### 브라우저 인증 (MFA/SSO 필수 환경)
브라우저가 직접 떠서 로그인을 진행합니다. 세션은 로컬에 저장되어 재사용됩니다.

```env
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_BROWSER_HEADLESS=false
```

#### 기타 인증 방식
- **Basic:** `SERVICENOW_AUTH_TYPE=basic` (ID/PW)
- **OAuth:** `SERVICENOW_AUTH_TYPE=oauth` (Client ID/Secret)
- **API Key:** `SERVICENOW_AUTH_TYPE=api_key`

---

## 🛠️ 도구 프로필 (Profiles)

상황에 맞게 필요한 도구 모음을 선택하여 사용할 수 있습니다. 환경변수 `MCP_TOOL_PACKAGE`로 설정하세요. (기본값: **`standard`**)

| 프로필명 | 추천 역할 | 주요 포함 도구 |
| :--- | :--- | :--- |
| `standard` | **표준 모드** | **기본값.** 인시던트, 서비스 카탈로그, 지식베이스 등 공통 데이터 조회 및 처리 |
| `portal_developer` | **풀스택 포탈 개발자** | **위젯 + 서버 스크립트(SI) 통합 개발**, Angular Provider, Update Set 관리 |
| `platform_developer` | **플랫폼 개발자** | 비즈니스 로직(Script Include), 워크플로우 자동화, UI Policy, 체인지셋 관리 |
| `service_desk` | **운영 및 헬프데스크** | 인시던트 생성/수정, 업무 코멘트 추가, 사용자 정보 조회 |
| `full` | **슈퍼 관리자** | 모든 도구 로드 (데이터, 프로젝트, 스크럼, 워크플로우 등 전 영역) |

---

## 🛡️ 전역 보안 정책 (Universal Safety Policy)

**중요: 본 서버의 보안 정책은 모든 프로필에 예외 없이 강제 적용되는 '절대 원칙'입니다.** 

어떤 프로필을 사용하든, **서버의 데이터를 수정/삭제하거나 소스 코드를 변경하는 행위**가 발생하면 무조건 사용자의 **명시적 승인**을 받아야만 실행됩니다.

1. **승인 조건:** `create_`, `update_`, `delete_`, `execute_`, `add_` 등으로 시작하는 모든 '수정형' 도구 호출 시.
2. **승인 방법:** 요청 시 반드시 파라미터로 **`confirm='approve'`**를 명시적으로 전달해야 합니다.
3. **작동 방식:** 승인 파라미터 없이 실행을 시도하면 서버가 **물리적으로 실행을 거부**하고 사용자에게 확인을 요청합니다.

### Claude Desktop (추천 설정)
`claude_desktop_config.json`에 아래 설정을 복사하여 사용하세요. 환경변수 설정 없이 `args`만으로 간편하게 관리할 수 있습니다.

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

### Gemini / Vertex AI (OpenCode 설정)
Gemini Code Assist 또는 OpenCode와 같은 MCP 클라이언트에서 아래와 같이 로컬 서버를 추가할 수 있습니다. 사용하시는 인증 방식에 맞춰 설정을 선택하세요.

#### 1. 브라우저 인증 (MFA/SSO 대응 - 추천)
브라우저 창이 직접 떠서 로그인을 진행합니다. 아이디/비밀번호 자동 입력도 지원합니다.
```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--username", "your_id",
        "--password", "your_password",
        "--browser-headless", "false"
      ],
      "enabled": true
    }
  }
}
```

#### 2. 기본 인증 (Basic Auth)
MFA가 없는 PDI(개인 개발 인스턴스) 등에서 적합합니다.
```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "basic",
        "--username", "your_id",
        "--password", "your_password"
      ],
      "enabled": true
    }
  }
}
```

#### 3. 기타 인증 (OAuth / API Key)
- **OAuth:** `--auth-type oauth --oauth-client-id <id> --oauth-client-secret <secret>`
- **API Key:** `--auth-type api_key --api-key <key>`

---

## 🛡️ 데이터 보호 정책 (Confirmation Required)

본 서버는 데이터 파괴 방지를 위해 Mutation(수정/삭제 등) 도구 실행 시 명시적인 확인 파라미터를 요구합니다.

- `confirm='approve'` : 실행을 확정하기 위해 반드시 전달해야 하는 파라미터

이 정보가 없으면 수정 도구는 실행되지 않고 안내 메시지를 반환합니다.

---

## 📚 상세 문서

더 자세한 도구 사용법과 설정은 `docs/` 폴더를 참고하세요.

- [서비스 카탈로그 가이드](docs/catalog.md)
- [변경 관리 가이드](docs/change_management.md)
- [워크플로우 및 개발 도구](docs/workflow_management.md)

## 라이선스

MIT License
