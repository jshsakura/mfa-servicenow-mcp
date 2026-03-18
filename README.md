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
- [사용 가능한 도구](#사용-가능한-도구)
- [Docker 사용법](#docker-사용법)
- [개발](#개발)
- [라이선스](#라이선스)

---

## 개요

이 프로젝트는 AI 어시스턴트가 ServiceNow 인스턴스에 연결하고, 데이터를 조회하며, ServiceNow API를 통해 작업을 수행할 수 있도록 하는 MCP 서버를 구현합니다.

## 주요 기능

- **다양한 인증 방식 지원**: Basic, OAuth, API Key, Browser (MFA/SSO)
- **레코드 관리**: ServiceNow 레코드 및 테이블 CRUD (`sn_query`, `sn_schema`, `sn_aggregate`)
- **자연어 쿼리**: `sn_nl`을 통한 자연어 기반 쿼리 생성 및 실행
- **테이블 탐색**: `sn_discover`로 테이블 이름/라벨 검색
- **스크립트 관리**: Script Include 생성, 수정, 삭제
- **워크플로우 관리**: 워크플로우 및 액티비티 전체 라이프사이클 관리
- **서비스 카탈로그**: 카탈로그 아이템, 카테고리, 변수 관리 및 최적화
- **변경 관리**: 변경 요청 생성부터 승인/거부까지 전체 프로세스
- **지식베이스**: 지식베이스, 카테고리, 문서 생성 및 관리
- **애자일 관리**: 스토리, 에픽, 스크럼 태스크, 프로젝트 관리
- **사용자/그룹 관리**: 사용자 및 그룹 CRUD, 멤버십 관리
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

# Browser Auth (MFA/SSO) 사용 시 추가 설치
pip install -e ".[browser]"
playwright install chromium

# 3. 클라이언트 설정 (opencode.json 또는 claude_desktop_config.json)
# 아래 클라이언트 설정 섹션 참조
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

### 환경변수 상세 설명

#### 공통 환경변수

| 변수명 | 필수 | 기본값 | 설명 |
|--------|------|--------|------|
| **SERVICENOW_INSTANCE_URL** | ✅ | - | ServiceNow 인스턴스 URL (예: `https://your-instance.service-now.com`) |
| **SERVICENOW_AUTH_TYPE** | ✅ | - | 인증 방식: `basic`, `oauth`, `api_key`, `browser` |
| **MCP_TOOL_PACKAGE** | ❌ | `full` | 로드할 도구 패키지 (`full`, `service_desk`, `catalog_builder` 등) |
| **SERVICENOW_TIMEOUT** | ❌ | `30` | API 요청 타임아웃 (초) |
| **SERVICENOW_DEBUG** | ❌ | `false` | 디버그 모드 활성화 |

#### Basic 인증

| 변수명 | 필수 | 설명 |
|--------|------|------|
| **SERVICENOW_USERNAME** | ✅ | ServiceNow 사용자명 |
| **SERVICENOW_PASSWORD** | ✅ | ServiceNow 비밀번호 |

> **사용 시기**: MFA/SSO가 없는 환경에서 가장 간단한 인증 방식

#### Browser 인증 (MFA/SSO)

| 변수명 | 필수 | 기본값 | 설명 |
|--------|------|--------|------|
| **SERVICENOW_BROWSER_HEADLESS** | ❌ | `true` | 브라우저 백그라운드 실행 여부. MFA 있으면 `false` 권장 |
| **SERVICENOW_BROWSER_TIMEOUT** | ❌ | `120` | 브라우저 작업 타임아웃 (초). MFA 입력 시간 고려 |
| **SERVICENOW_BROWSER_SESSION_TTL** | ❌ | `30` | 브라우저 세션 유지 시간 (분) |
| **SERVICENOW_BROWSER_USER_DATA_DIR** | ❌ | - | 브라우저 프로필 저장 디렉토리 (절대경로 권장) |
| **SERVICENOW_BROWSER_PROBE_PATH** | ❌ | `/api/now/table/sys_user?sysparm_limit=1` | 인증 상태 확인용 API 경로 |
| **SERVICENOW_BROWSER_USERNAME** | ❌ | - | 자동 로그인용 사용자명 (MFA 없는 SSO만) |
| **SERVICENOW_BROWSER_PASSWORD** | ❌ | - | 자동 로그인용 비밀번호 (MFA 없는 SSO만) |

> **SERVICENOW_BROWSER_PROBE_PATH 사용 시기**: 기본 `sys_user` API가 ACL로 막혀 있을 때, 계정이 읽기 권한이 있는 다른 API 경로로 변경 (예: `/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id`)

> **SERVICENOW_BROWSER_USER_DATA_DIR 중요성**: 로그인 상태(쿠키, 세션)가 저장됨. 같은 프로필 재사용 시 재로그인 횟수 감소. `.gitignore`에 추가 필수

#### OAuth 인증

| 변수명 | 필수 | 설명 |
|--------|------|------|
| **SERVICENOW_CLIENT_ID** | ✅ | OAuth 클라이언트 ID |
| **SERVICENOW_CLIENT_SECRET** | ✅ | OAuth 클라이언트 시크릿 |
| **SERVICENOW_TOKEN_URL** | ❌ | 토큰 엔드포인트 (기본: `{instance}/oauth_token.do`) |

#### API Key 인증

| 변수명 | 필수 | 설명 |
|--------|------|------|
| **SERVICENOW_API_KEY** | ✅ | API Key 값 |
| **SERVICENOW_API_KEY_HEADER** | ❌ | API Key 헤더명 (기본: `X-ServiceNow-API-Key`) |

#### Python 환경 설정

| 변수명 | 필수 | 설명 |
|--------|------|------|
| **PYTHONPATH** | ❌ | Python 모듈 검색 경로. `src` 디렉토리 추가 시 사용. `pip install -e .` 했으면 불필요 |

#### 도구 패키지 옵션

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

### 인증 설정 예제

#### 예제 1: Basic 인증 (가장 간단)

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=admin
SERVICENOW_PASSWORD=your-password
MCP_TOOL_PACKAGE=full
```

#### 예제 2: Browser 인증 (MFA/SSO 필요 시)

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_TIMEOUT=120
SERVICENOW_BROWSER_SESSION_TTL=30
SERVICENOW_BROWSER_USER_DATA_DIR=/path/to/.browser-profile
SERVICENOW_BROWSER_PROBE_PATH=/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id
MCP_TOOL_PACKAGE=full
```

#### 예제 3: OAuth 인증

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_CLIENT_ID=your-client-id
SERVICENOW_CLIENT_SECRET=your-client-secret
SERVICENOW_TOKEN_URL=https://your-instance.service-now.com/oauth_token.do
MCP_TOOL_PACKAGE=full
```

#### 예제 4: API Key 인증

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=api_key
SERVICENOW_API_KEY=your-api-key
SERVICENOW_API_KEY_HEADER=X-ServiceNow-API-Key
MCP_TOOL_PACKAGE=full
```

### Browser 인증 사용 절차

브라우저 인증은 Basic/OAuth/API Key처럼 "인증 정보만 넣으면 끝"이 아닙니다. 아래 순서로 사용해야 합니다.

1. MCP 서버를 반드시 로컬 프로세스로 실행합니다.
2. `SERVICENOW_AUTH_TYPE=browser`로 설정합니다.
3. `SERVICENOW_BROWSER_USER_DATA_DIR`를 지정해 브라우저 세션을 재사용할 수 있게 합니다.
4. `SERVICENOW_BROWSER_PROBE_PATH`를 계정이 실제로 읽을 수 있는 API 경로로 설정합니다.
5. 첫 `sn_health` 또는 첫 실제 tool 호출 시 브라우저 창이 열리면 MFA/SSO 로그인을 완료합니다.
6. 로그인 후에는 같은 MCP 서버 프로세스를 계속 사용해야 합니다. 서버를 다시 띄우면 브라우저 세션 bootstrap이 다시 필요할 수 있습니다.

**트러블슈팅**:

- `sn_health`가 401이고 `login.do` 리다이렉트라면: 브라우저 세션 bootstrap이 아직 안 된 상태입니다.
- `sn_health`가 `warning`과 함께 401/403이라면: 브라우저 세션은 유효합니다. 이 경우 `additional_api_credentials_required=false`로 반환되며, 문제는 `SERVICENOW_BROWSER_PROBE_PATH` ACL 또는 해당 엔드포인트 권한입니다.
- 계속 "Basic/OAuth/API Key 필요"처럼 보인다면: 현재 실행 중인 MCP가 browser 설정이 아닌 다른 설정/다른 프로세스를 보고 있는지 확인해야 합니다.

---

## 클라이언트 설정

### Python 경로 안내

MCP 클라이언트(OpenCode/Claude)는 서버를 "별도 프로세스"로 실행합니다. 이때 어떤 Python 실행파일로 띄울지 애매하면(시스템 Python, pyenv, venv 충돌) 실행 실패가 자주 납니다.

- **안정성 최우선**: 절대경로 Python (권장)
- **간편성 우선**: `python3` (PATH 보장될 때만)

### 케이스별 권장 사용법

#### 케이스 1: OpenCode + Browser 인증(MFA/SSO)

`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [".venv/bin/python", "-m", "servicenow_mcp.cli"],
      "enabled": true,
      "environment": {
        "PYTHONPATH": "/path/to/mfa-servicenow-mcp/src",
        "SERVICENOW_BROWSER_USER_DATA_DIR": "/path/to/.browser-profile",
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_TIMEOUT": "120",
        "SERVICENOW_BROWSER_SESSION_TTL": "30",
        "SERVICENOW_BROWSER_PROBE_PATH": "/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id",
        "MCP_TOOL_PACKAGE": "full",
        "SERVICENOW_TIMEOUT": "30",
        "SERVICENOW_DEBUG": "true"
      }
    }
  }
}
```

#### 케이스 2: OpenCode + Basic 인증

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
        "MCP_TOOL_PACKAGE": "full"
      }
    }
  }
}
```

#### 케이스 3: Claude Desktop + Basic 인증

`~/Library/Application Support/Claude/claude_desktop_config.json`:

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

#### 케이스 4: Claude Desktop + Browser 인증(MFA/SSO)

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
        "SERVICENOW_BROWSER_SESSION_TTL": "30",
        "SERVICENOW_BROWSER_USER_DATA_DIR": "/absolute/path/to/.browser-profile",
        "SERVICENOW_BROWSER_PROBE_PATH": "/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id",
        "MCP_TOOL_PACKAGE": "full"
      }
    }
  }
}
```

### 경로 확인 방법

```bash
# venv 생성 후
which python
# 또는
realpath .venv/bin/python
```

---

## 사용 가능한 도구

### 인시던트 관리
- `list_incidents` - 인시던트 목록 조회
- `get_incident_by_number` - 인시던트 번호로 상세 조회
- `create_incident` - 인시던트 생성
- `update_incident` - 인시던트 수정
- `add_comment` - 인시던트에 코멘트/워크노트 추가
- `resolve_incident` - 인시던트 해결

### 서비스 카탈로그
- `list_catalog_items` - 카탈로그 아이템 목록
- `get_catalog_item` - 카탈로그 아이템 상세
- `update_catalog_item` - 카탈로그 아이템 수정
- `list_catalog_categories` - 카탈로그 카테고리 목록
- `create_catalog_category` - 카탈로그 카테고리 생성
- `update_catalog_category` - 카탈로그 카테고리 수정
- `move_catalog_items` - 카탈로그 아이템 이동
- `get_optimization_recommendations` - 최적화 추천 조회
- `create_catalog_item_variable` - 카탈로그 아이템 변수 생성
- `list_catalog_item_variables` - 카탈로그 아이템 변수 목록
- `update_catalog_item_variable` - 카탈로그 아이템 변수 수정

### 변경 관리
- `list_change_requests` - 변경 요청 목록
- `get_change_request_details` - 변경 요청 상세
- `create_change_request` - 변경 요청 생성
- `update_change_request` - 변경 요청 수정
- `add_change_task` - 변경 요청에 태스크 추가
- `submit_change_for_approval` - 변경 요청 승인 요청
- `approve_change` - 변경 요청 승인
- `reject_change` - 변경 요청 거부

### 워크플로우
- `list_workflows` - 워크플로우 목록
- `get_workflow_details` - 워크플로우 상세
- `list_workflow_versions` - 워크플로우 버전 목록
- `get_workflow_activities` - 워크플로우 액티비티 조회
- `create_workflow` - 워크플로우 생성
- `update_workflow` - 워크플로우 수정
- `activate_workflow` - 워크플로우 활성화
- `deactivate_workflow` - 워크플로우 비활성화
- `add_workflow_activity` - 워크플로우 액티비티 추가
- `update_workflow_activity` - 워크플로우 액티비티 수정
- `delete_workflow_activity` - 워크플로우 액티비티 삭제
- `reorder_workflow_activities` - 워크플로우 액티비티 순서 변경

### 스크립트 인클루드
- `list_script_includes` - 스크립트 인클루드 목록
- `get_script_include` - 스크립트 인클루드 상세
- `create_script_include` - 스크립트 인클루드 생성
- `update_script_include` - 스크립트 인클루드 수정
- `delete_script_include` - 스크립트 인클루드 삭제

### 변경세트
- `list_changesets` - 변경세트 목록
- `get_changeset_details` - 변경세트 상세
- `create_changeset` - 변경세트 생성
- `update_changeset` - 변경세트 수정
- `commit_changeset` - 변경세트 커밋
- `publish_changeset` - 변경세트 퍼블리시
- `add_file_to_changeset` - 변경세트에 파일 추가

### 지식베이스
- `list_knowledge_bases` - 지식베이스 목록
- `create_knowledge_base` - 지식베이스 생성
- `list_categories` - 카테고리 목록
- `create_category` - 카테고리 생성
- `list_articles` - 문서 목록
- `get_article` - 문서 상세
- `create_article` - 문서 생성
- `update_article` - 문서 수정
- `publish_article` - 문서 퍼블리시

### 사용자 관리
- `list_users` - 사용자 목록
- `get_user` - 사용자 상세
- `create_user` - 사용자 생성
- `update_user` - 사용자 수정
- `list_groups` - 그룹 목록
- `create_group` - 그룹 생성
- `update_group` - 그룹 수정
- `add_group_members` - 그룹 멤버 추가
- `remove_group_members` - 그룹 멤버 제거

### 애자일 관리
- `list_stories` - 스토리 목록
- `create_story` - 스토리 생성
- `update_story` - 스토리 수정
- `list_story_dependencies` - 스토리 의존성 목록
- `create_story_dependency` - 스토리 의존성 생성
- `delete_story_dependency` - 스토리 의존성 삭제
- `list_epics` - 에픽 목록
- `create_epic` - 에픽 생성
- `update_epic` - 에픽 수정
- `list_scrum_tasks` - 스크럼 태스크 목록
- `create_scrum_task` - 스크럼 태스크 생성
- `update_scrum_task` - 스크럼 태스크 수정
- `list_projects` - 프로젝트 목록
- `create_project` - 프로젝트 생성
- `update_project` - 프로젝트 수정

### 유틸리티
- `sn_health` - API 연결 및 인증 상태 확인
- `sn_query` - 임의 테이블 쿼리
- `sn_aggregate` - 집계 통계 (count/sum/avg/min/max)
- `sn_schema` - 테이블 스키마 조회
- `sn_discover` - 테이블 이름/라벨 검색
- `sn_nl` - 자연어 쿼리 도우미
- `list_tool_packages` - 사용 가능한 도구 패키지 목록

---

## Docker 사용법

### 인증 방식별 권장 실행 방식

| 인증 방식 | Docker 권장 여부 | 권장 실행 방식 | 이유 |
|--------|------|-----------|------|
| `basic` | 권장 | Docker (`latest`) | 브라우저 인터랙션이 필요 없음 |
| `oauth` | 권장 | Docker (`latest`) | 토큰 기반 인증으로 컨테이너 환경 적합 |
| `api_key` | 권장 | Docker (`latest`) | 헤더 인증만 필요 |
| `browser` (MFA/SSO) | 비권장 | 로컬 Python | MFA용 물리 브라우저 창/사용자 상호작용 필요 |

> Browser(MFA/SSO) 모드는 Docker보다 로컬 실행이 안정적입니다.

### GHCR 배포 태그 규칙

- `latest` - 기본 runtime 이미지 (multi-arch: `linux/amd64`, `linux/arm64`)
- `latest-playwright` - Playwright 포함 이미지 (`linux/amd64`)
- `v0.0.<run_number>` - 배포 실행번호 기반 릴리즈 태그
- `sha-<commit>` - 커밋 기반 고유 태그

```bash
docker pull ghcr.io/jshsakura/mfa-servicenow-mcp:latest
docker pull ghcr.io/jshsakura/mfa-servicenow-mcp:latest-playwright
```

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
