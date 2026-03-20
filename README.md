# ServiceNow MCP Server

ServiceNow용 Model Context Protocol (MCP) 서버 구현체입니다.

- 저장소: `mfa-servicenow-mcp`
- Python 패키지: `mfa-servicenow-mcp`
- 실행 모듈: `servicenow_mcp`
- 엔트리포인트:
  - `servicenow-mcp`
  - `servicenow-mcp-sse`

Claude Desktop, OpenCode 같은 MCP 클라이언트에서 ServiceNow 인스턴스와 상호작용할 수 있습니다.

## 개요

이 프로젝트는 ServiceNow API와 MCP 클라이언트 사이를 연결하는 서버입니다.

지원 범위:
- Basic / OAuth / API Key / Browser 인증
- 레코드 및 테이블 조회/수정
- 서비스 카탈로그 관리
- 변경 관리
- 워크플로우 / Script Include / ChangeSet 관리
- 지식베이스 / 사용자 / 그룹 / 애자일 관련 도구
- stdio 및 SSE 전송

## 빠른 시작

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 기본 설치
pip install -e .

# Browser auth(MFA/SSO) 사용 시 추가 설치
pip install -e ".[browser]"
playwright install chromium
```

## 실행 방법

### stdio 모드

가장 일반적인 MCP 실행 방식입니다.

```bash
servicenow-mcp
```

또는:

```bash
python -m servicenow_mcp.cli
```

예시:

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
SERVICENOW_AUTH_TYPE=basic \
SERVICENOW_USERNAME=your-username \
SERVICENOW_PASSWORD=your-password \
servicenow-mcp
```

### SSE 모드

SSE 서버 엔트리포인트는 현재 `--host`, `--port`만 직접 받고, 인증 정보는 환경변수에서 읽습니다.

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
SERVICENOW_AUTH_TYPE=basic \
SERVICENOW_USERNAME=your-username \
SERVICENOW_PASSWORD=your-password \
servicenow-mcp-sse --host 127.0.0.1 --port 8000
```

엔드포인트:
- `/sse`
- `/messages/`

주의:
- 현재 `src/servicenow_mcp/server_sse.py` 기준으로 SSE 실행 경로는 Basic 인증 환경변수 사용 방식에 맞춰져 있습니다.
- Browser/OAuth/API Key 중심 운용은 stdio 모드 문서를 기준으로 보는 것이 안전합니다.

## 인증 설정

### 공통 환경변수

```env
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=basic
MCP_TOOL_PACKAGE=full
SERVICENOW_TIMEOUT=30
SERVICENOW_DEBUG=false
```

### Basic 인증

```env
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=your-username
SERVICENOW_PASSWORD=your-password
```

### OAuth 인증

```env
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_CLIENT_ID=your-client-id
SERVICENOW_CLIENT_SECRET=your-client-secret
SERVICENOW_TOKEN_URL=https://your-instance.service-now.com/oauth_token.do
SERVICENOW_USERNAME=your-username
SERVICENOW_PASSWORD=your-password
```

### API Key 인증

```env
SERVICENOW_AUTH_TYPE=api_key
SERVICENOW_API_KEY=your-api-key
SERVICENOW_API_KEY_HEADER=X-ServiceNow-API-Key
```

### Browser 인증 (MFA/SSO)

브라우저 인증은 MFA/SSO 환경에서 가장 중요한 모드입니다.

```env
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_BROWSER_USERNAME=your-username
SERVICENOW_BROWSER_PASSWORD=your-password
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_TIMEOUT=120
SERVICENOW_BROWSER_SESSION_TTL=30
SERVICENOW_BROWSER_USER_DATA_DIR=/absolute/path/to/browser-profile
SERVICENOW_BROWSER_PROBE_PATH=/api/now/table/sys_user?sysparm_limit=1&sysparm_fields=sys_id
```

브라우저 인증 팁:
- `SERVICENOW_BROWSER_USER_DATA_DIR`를 지정하면 세션 재사용에 유리합니다.
- 기본 probe path가 권한 문제를 일으키면, 읽을 수 있는 다른 API 경로로 `SERVICENOW_BROWSER_PROBE_PATH`를 바꿔야 합니다.
- MFA가 있으면 `SERVICENOW_BROWSER_HEADLESS=false`가 일반적으로 더 안전합니다.

## MCP 클라이언트 설정

### OpenCode / 범용 MCP 등록 형식

```json
{
  "servicenow": {
    "command": "/absolute/path/to/mfa-servicenow-mcp/.venv/bin/python",
    "args": ["-m", "servicenow_mcp.cli"],
    "env": {
      "PYTHONPATH": "/absolute/path/to/mfa-servicenow-mcp/src",
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "SERVICENOW_BROWSER_TIMEOUT": "120",
      "SERVICENOW_BROWSER_SESSION_TTL": "30",
      "SERVICENOW_BROWSER_USER_DATA_DIR": "/absolute/path/to/browser-profile",
      "SERVICENOW_BROWSER_USERNAME": "your-username",
      "SERVICENOW_BROWSER_PASSWORD": "your-password",
      "MCP_TOOL_PACKAGE": "full",
      "SERVICENOW_TIMEOUT": "30",
      "SERVICENOW_DEBUG": "false"
    }
  }
}
```

### Claude Desktop 예시

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/absolute/path/to/mfa-servicenow-mcp/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.cli"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/mfa-servicenow-mcp/src",
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_TIMEOUT": "120",
        "SERVICENOW_BROWSER_SESSION_TTL": "30",
        "SERVICENOW_BROWSER_USER_DATA_DIR": "/absolute/path/to/browser-profile",
        "SERVICENOW_BROWSER_USERNAME": "your-username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "full"
      }
    }
  }
}
```

참고:
- `pip install -e .`가 되어 있으면 `PYTHONPATH` 없이도 동작할 수 있습니다.
- 클라이언트가 `servicenow-mcp` 실행 파일을 찾을 수 있는 환경이면 `command`를 `servicenow-mcp`로 단순화할 수도 있습니다.

## 도구 패키징

`MCP_TOOL_PACKAGE` 환경변수로 도구 묶음을 제한할 수 있습니다.

기본값은 `full`입니다.

대표 패키지:
- `service_desk`
- `catalog_builder`
- `change_coordinator`
- `knowledge_author`
- `platform_developer`
- `system_administrator`
- `agile_management`
- `full`
- `none`

패키지 정의 파일: `config/tool_packages.yaml`

## 페이로드 안전장치 (Payload Safety)

대용량 데이터 조회 시 클라이언트(LLM)와 서버의 안정성을 보장하기 위해 다음과 같은 안전장치가 적용되어 있습니다:

- **대용량 테이블 보호:** `sp_widget`, `sys_script`, `sys_metadata` 등 소스 코드가 포함된 무거운 테이블 조회 시, 필드를 지정하지 않으면 자동으로 `sys_id, name, id, sys_scope` 필드만 조회합니다.
- **자동 Limit 조정:** `script`, `html`, `css` 등 대용량 필드를 명시적으로 요청할 경우, 페이로드 폭발을 막기 위해 `limit`을 최대 5건으로 자동 제한합니다.
- **글로벌 Limit 강제:** 모든 일반 쿼리(`sn_query`)의 최대 조회 건수는 100건으로 제한됩니다. 더 많은 데이터가 필요한 경우 `offset`과 `total_count`를 활용한 Pagination을 사용해야 합니다.
- **필드 데이터 절단 (Truncation):** 개별 필드의 문자열 길이가 10,000자를 초과하면 내용을 자동으로 자르고 안내 메시지를 추가하여 컨텍스트 오버플로우를 방지합니다.
- **Pagination 지원:** 응답에 `total_count`가 포함되어 전체 레코드 규모를 파악할 수 있습니다.

## 사용 가능한 도구

도구 노출은 로드한 패키지에 따라 달라집니다.

대표 범주:
- 인시던트 관리
- 서비스 카탈로그
- 변경 관리
- 애자일 관리
- 워크플로우 관리
- Script Include 관리
- ChangeSet 관리
- 지식베이스 관리
- 사용자 / 그룹 관리
- UI 정책

세부 문서는 `docs/`를 참고하면 됩니다.

## 개발

테스트:

```bash
pytest
```

주요 문서:
- `docs/catalog.md`
- `docs/change_management.md`
- `docs/workflow_management.md`
- `docs/changeset_management.md`

## 라이선스

MIT License
