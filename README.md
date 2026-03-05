# ServiceNow MCP Server

ServiceNow용 Model Context Protocol (MCP) 서버 구현체입니다.  
Claude, OpenCode 등 MCP 클라이언트에서 ServiceNow 인스턴스와 상호작용할 수 있습니다.

## 목차

- [개요](#개요)
- [주요 기능](#주요-기능)
- [빠른 시작](#빠른-시작)
- [설치](#설치)
- [인증 설정](#인증-설정)
- [클라이언트 설정](#클라이언트-설정)
- [도구 패키징](#도구-패키징)
- [사용 가능한 도구](#사용-가능한-도구)
- [Docker 사용법](#docker-사용법)
- [개발](#개발)
- [라이선스](#라이선스)

---

## 개요

이 프로젝트는 AI 어시스턴트가 ServiceNow 인스턴스에 연결하고, 데이터를 조회하며, ServiceNow API를 통해 작업을 수행할 수 있도록 하는 MCP 서버를 구현합니다.

## 주요 기능

- **다양한 인증 방식 지원**: Basic, OAuth, API Key, Browser (MFA/SSO)
- **레코드 관리**: ServiceNow 레코드 및 테이블 CRUD
- **스크립트 실행**: ServiceNow 스크립트 및 워크플로우 실행
- **서비스 카탈로그**: 카탈로그 아이템 조회 및 관리
- **지식베이스**: 문서 생성 및 관리
- **애자일 관리**: 스토리, 에픽, 스크럼 태스크 관리
- **Docker 지원**: 컨테이너화된 배포
- **SSE 지원**: HTTP 기반 MCP 통신

---

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

# 2. 가상환경 생성 및 패키지 설치
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .

# 3. 환경변수 파일 생성
cp .env.example .env
# .env 파일을 열어서 본인의 ServiceNow 자격증명 입력

# 4. MCP 서버 실행 (테스트)
python -m servicenow_mcp.cli
```

---

## 설치

### 사전 요구사항

- Python 3.11 이상
- ServiceNow 인스턴스 및 접속 자격증명
- (Browser Auth 사용 시) Playwright

### 설치 방법

```bash
# 기본 설치
pip install -e .

# Browser Auth (MFA/SSO) 사용 시
pip install -e ".[browser]"
playwright install chromium
```

---

## 인증 설정

### 환경변수 파일 (.env)

`.env.example`을 복사하여 `.env` 파일을 생성하고 아래 예제를 참고하여 설정하세요.

#### 예제 1: Basic 인증 (가장 간단)

```bash
# ServiceNow 인스턴스 정보
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com

# 인증 방식
SERVICENOW_AUTH_TYPE=basic

# Basic 인증 자격증명
SERVICENOW_USERNAME=admin
SERVICENOW_PASSWORD=your-password

# 서버 설정
SERVICENOW_DEBUG=false
SERVICENOW_TIMEOUT=30
MCP_TOOL_PACKAGE=full
```

#### 예제 2: Browser 인증 (MFA/SSO 필요 시)

```bash
# ServiceNow 인스턴스 정보
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com

# 인증 방식
SERVICENOW_AUTH_TYPE=browser

# Browser 인증 설정
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_TIMEOUT=120
SERVICENOW_BROWSER_SESSION_TTL=30

# 선택사항: 자동 로그인용 자격증명 (없으면 수동 로그인)
# SERVICENOW_BROWSER_USERNAME=your-username
# SERVICENOW_BROWSER_PASSWORD=your-password

# 서버 설정
SERVICENOW_DEBUG=false
SERVICENOW_TIMEOUT=30
MCP_TOOL_PACKAGE=full
```

> **참고**: Browser 인증은 최초 1회 브라우저가 열리며 MFA/SSO 인증을 완료하면 세션이 유지됩니다.

#### 예제 3: OAuth 인증

```bash
# ServiceNow 인스턴스 정보
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com

# 인증 방식
SERVICENOW_AUTH_TYPE=oauth

# OAuth 설정
SERVICENOW_CLIENT_ID=your-client-id
SERVICENOW_CLIENT_SECRET=your-client-secret
SERVICENOW_TOKEN_URL=https://your-instance.service-now.com/oauth_token.do

# 서버 설정
SERVICENOW_DEBUG=false
SERVICENOW_TIMEOUT=30
MCP_TOOL_PACKAGE=full
```

#### 예제 4: API Key 인증

```bash
# ServiceNow 인스턴스 정보
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com

# 인증 방식
SERVICENOW_AUTH_TYPE=api_key

# API Key 설정
SERVICENOW_API_KEY=your-api-key
SERVICENOW_API_KEY_HEADER=X-ServiceNow-API-Key

# 서버 설정
SERVICENOW_DEBUG=false
SERVICENOW_TIMEOUT=30
MCP_TOOL_PACKAGE=full
```

---

## 클라이언트 설정

### OpenCode 설정

`opencode.json` 파일을 프로젝트 루트에 생성하세요.

#### 예제 1: Basic 인증

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [".venv/bin/python", "-m", "servicenow_mcp.cli"],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "basic",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "full",
        "SERVICENOW_DEBUG": "false",
        "SERVICENOW_TIMEOUT": "30"
      }
    }
  }
}
```

#### 예제 2: Browser 인증 (MFA/SSO)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [".venv/bin/python", "-m", "servicenow_mcp.cli"],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_TIMEOUT": "120",
        "SERVICENOW_BROWSER_SESSION_TTL": "30",
        "MCP_TOOL_PACKAGE": "full",
        "SERVICENOW_DEBUG": "false"
      }
    }
  }
}
```

#### 예제 3: .env 파일 사용 (권장)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [".venv/bin/python", "-m", "servicenow_mcp.cli"],
      "enabled": true,
      "envFile": ".env"
    }
  }
}
```

### Claude Desktop 설정

`~/Library/Application Support/Claude/claude_desktop_config.json` 파일을 수정하세요.

#### 예제 1: Basic 인증

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/absolute/path/to/mfa-servicenow-mcp/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.cli"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "basic",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "full"
      }
    }
  }
}
```

#### 예제 2: Browser 인증 (MFA/SSO)

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/absolute/path/to/mfa-servicenow-mcp/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.cli"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_TIMEOUT": "120",
        "MCP_TOOL_PACKAGE": "full"
      }
    }
  }
}
```

---

## 도구 패키징

`MCP_TOOL_PACKAGE` 환경변수로 필요한 도구만 선택하여 로드할 수 있습니다.

### 사용 가능한 패키지

| 패키지 | 설명 | 포함 도구 |
|--------|------|-----------|
| `full` | 모든 도구 포함 (기본값) | 전체 |
| `service_desk` | 인시던트 처리 및 사용자/지식 조회 | incident, user, knowledge |
| `catalog_builder` | 카탈로그 아이템, 카테고리, 변수 관리 | catalog, catalog_variables |
| `change_coordinator` | 변경 요청 라이프사이클 관리 | change, changeset, workflow |
| `knowledge_author` | 지식베이스 및 문서 관리 | knowledge_base |
| `platform_developer` | 스크립트, 워크플로우, 배포 관리 | script_include, workflow, changeset |
| `system_administrator` | 사용자/그룹 관리 및 로그 조회 | user |
| `agile_management` | 스토리, 에픽, 스크럼 태스크 관리 | story, epic, scrum_task, project |
| `none` | 도구 없음 | - |

```bash
export MCP_TOOL_PACKAGE=service_desk
```

---

## 사용 가능한 도구

### 인시던트 관리
- `list_incidents` - 인시던트 목록 조회
- `create_incident` - 인시던트 생성
- `update_incident` - 인시던트 수정
- `add_comment` - 인시던트에 코멘트 추가
- `resolve_incident` - 인시던트 해결

### 서비스 카탈로그
- `list_catalog_items` - 카탈로그 아이템 목록
- `get_catalog_item` - 카탈로그 아이템 상세
- `create_catalog_item` - 카탈로그 아이템 생성
- `list_catalog_categories` - 카탈로그 카테고리 목록

### 변경 관리
- `list_change_requests` - 변경 요청 목록
- `create_change_request` - 변경 요청 생성
- `update_change_request` - 변경 요청 수정
- `approve_change` - 변경 요청 승인

### 워크플로우
- `list_workflows` - 워크플로우 목록
- `get_workflow` - 워크플로우 상세
- `create_workflow` - 워크플로우 생성
- `update_workflow` - 워크플로우 수정

### 스크립트 인클루드
- `list_script_includes` - 스크립트 인클루드 목록
- `get_script_include` - 스크립트 인클루드 상세
- `create_script_include` - 스크립트 인클루드 생성
- `execute_script_include` - 스크립트 인클루드 실행

### 변경세트
- `list_changesets` - 변경세트 목록
- `create_changeset` - 변경세트 생성
- `commit_changeset` - 변경세트 커밋
- `publish_changeset` - 변경세트 퍼블리시

### 지식베이스
- `list_knowledge_bases` - 지식베이스 목록
- `create_knowledge_base` - 지식베이스 생성
- `create_article` - 문서 생성
- `publish_article` - 문서 퍼블리시

### 사용자 관리
- `list_users` - 사용자 목록
- `get_user` - 사용자 상세
- `create_user` - 사용자 생성
- `update_user` - 사용자 수정
- `create_group` - 그룹 생성

### 애자일 관리
- `create_story` - 스토리 생성
- `update_story` - 스토리 수정
- `create_epic` - 에픽 생성
- `create_scrum_task` - 스크럼 태스크 생성
- `create_project` - 프로젝트 생성

---

## Docker 사용법

### Docker 이미지 빌드

```bash
# 기본 이미지 (Playwright 미포함)
docker build --target runtime -t servicenow-mcp:latest .

# Playwright 포함 (Browser Auth용)
docker build --target runtime-playwright -t servicenow-mcp:playwright .
```

### Docker Compose 실행

```bash
# SSE 모드
docker compose --profile sse up -d

# Browser Auth 모드 (MFA/SSO)
docker compose --profile browser up -d

# 개발 모드 (hot reload)
docker compose --profile dev up -d
```

### Docker 실행 예시

```bash
docker run -p 8080:8080 \
  -e SERVICENOW_INSTANCE_URL=https://instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=basic \
  -e SERVICENOW_USERNAME=admin \
  -e SERVICENOW_PASSWORD=password \
  servicenow-mcp:latest
```

---

## 개발

### 문서

- [Catalog Integration](docs/catalog.md)
- [Change Management](docs/change_management.md)
- [Workflow Management](docs/workflow_management.md)
- [Changeset Management](docs/changeset_management.md)

### 테스트 실행

```bash
pytest tests/ -v --cov=src/servicenow_mcp
```

### 코드 품질

```bash
black src/ tests/
isort src/ tests/
ruff check src/ tests/
mypy src/
```

---

## 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.
