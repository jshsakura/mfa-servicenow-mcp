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
- **강력한 보안:** 수정/삭제 작업 시 명시적 승인(`_approved=true`) 요구 정책 적용
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

## 🤖 MCP 클라이언트 설정

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

---

## 🛡️ 승인 기반 실행 정책

본 서버는 데이터 파괴 방지를 위해 Mutation(수정/삭제 등) 도구 실행 시 다음 파라미터를 필수로 요구합니다.

- `_approved=true` : 실행 승인 여부
- `_approval_by` : 승인자 이름
- `_approval_reason` : 실행 사유

이 정보가 없으면 수정 도구는 실행되지 않고 안내 메시지를 반환합니다.

---

## 📚 상세 문서

더 자세한 도구 사용법과 설정은 `docs/` 폴더를 참고하세요.

- [서비스 카탈로그 가이드](docs/catalog.md)
- [변경 관리 가이드](docs/change_management.md)
- [워크플로우 및 개발 도구](docs/workflow_management.md)

## 라이선스

MIT License
