# ServiceNow MCP Server

ServiceNow용 Model Context Protocol (MCP) 서버 구현체로, Claude가 ServiceNow 인스턴스와 상호작용할 수 있게 합니다.

## 개요

이 프로젝트는 Claude가 ServiceNow 인스턴스에 연결하고, 데이터를 조회하며, ServiceNow API를 통해 작업을 수행할 수 있도록 하는 MCP 서버를 구현합니다. Claude와 ServiceNow 간의 원활한 통합을 위한 브리지 역할을 합니다.

## 주요 기능

- 다양한 인증 방식 지원 (Basic, OAuth, API Key, Browser)
- ServiceNow 레코드 및 테이블 조회
- ServiceNow 레코드 생성, 수정, 삭제
- ServiceNow 스크립트 및 워크플로우 실행
- Service Catalog 접근 및 조회
- Service Catalog 분석 및 최적화
- 디버그 모드 지원
- stdio 및 Server-Sent Events (SSE) 통신 지원
- Docker 컨테이너 지원
- GitHub Actions CI/CD 파이프라인

## 참조 프로젝트

이 프로젝트는 다음 3개의 레거시 구현체를 통합한 결과입니다:

| 프로젝트 | 통합된 기능 |
|---------|------------|
| **servicenow-mcp-1** | 범용 코어 도구 (`sn_query`, `sn_aggregate`, `sn_schema`, `sn_discover`, `sn_health`) 및 자연어 헬퍼 (`sn_nl`) |
| **servicenow-mcp-2** | 광범위한 엔터프라이즈 도구, 패키지 기반 노출 (`MCP_TOOL_PACKAGE`), stdio/SSE 전송 |
| **servicenow-mcp-3** | 실용적인 NLP 파싱 스타일 및 토큰/세션 라이프사이클 관리 |

### 보안 우선 MFA 접근

- MFA 우회 로직 미구현
- 브라우저 인증은 대화형 및 MFA 호환
- 브라우저 세션 쿠키는 인스턴스 범위 보안 쿠키만 필터링

## 설치

### 사전 요구사항

- Python 3.11 이상
- ServiceNow 인스턴스 및 접속 자격증명

### 설치 방법

```bash
# 1. 저장소 클론
git clone https://github.com/echelon-ai-labs/servicenow-mcp.git
cd servicenow-mcp

# 2. 가상환경 생성 및 패키지 설치
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .

# 3. 환경변수 파일 생성
cp .env.example .env
# .env 파일 편집 후 자격증명 입력
```

## 사용법

### stdio 모드 (기본)

```bash
python -m servicenow_mcp.cli
```

### SSE 모드 (HTTP 접근)

```bash
servicenow-mcp-sse --host=0.0.0.0 --port=8080
```

SSE 서버 엔드포인트:
- `/sse` - SSE 연결 엔드포인트
- `/messages/` - 메시지 전송 엔드포인트

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
  -e SERVICENOW_USERNAME=admin \
  -e SERVICENOW_PASSWORD=password \
  servicenow-mcp:latest
```

## 인증 방법

### Basic 인증

```bash
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=your-username
SERVICENOW_PASSWORD=your-password
```

### OAuth 인증

```bash
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_CLIENT_ID=your-client-id
SERVICENOW_CLIENT_SECRET=your-client-secret
SERVICENOW_TOKEN_URL=https://your-instance.service-now.com/oauth_token.do
```

### API Key 인증

```bash
SERVICENOW_AUTH_TYPE=api_key
SERVICENOW_API_KEY=your-api-key
```

### Browser 인증 (MFA/SSO)

```bash
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_TIMEOUT=120
```

Playwright 설치 필요:
```bash
pip install playwright
playwright install chromium
```

## 도구 패키징

`MCP_TOOL_PACKAGE` 환경변수로 도구 세트를 선택할 수 있습니다.

### 사용 가능한 패키지

| 패키지 | 설명 |
|--------|------|
| `full` | 모든 도구 포함 (기본값) |
| `service_desk` | 인시던트 처리 및 사용자/지식 조회 |
| `catalog_builder` | 카탈로그 아이템, 카테고리, 변수 관리 |
| `change_coordinator` | 변경 요청 라이프사이클 관리 |
| `knowledge_author` | 지식베이스 및 문서 관리 |
| `platform_developer` | 스크립트, 워크플로우, 배포 관리 |
| `system_administrator` | 사용자/그룹 관리 및 로그 조회 |
| `agile_management` | 스토리, 에픽, 스크럼 태스크 관리 |
| `none` | 도구 없음 |

```bash
export MCP_TOOL_PACKAGE=catalog_builder
```

## 사용 가능한 도구

### 인시던트 관리
- `create_incident`, `update_incident`, `add_comment`, `resolve_incident`, `list_incidents`

### 서비스 카탈로그
- `list_catalog_items`, `get_catalog_item`, `create_catalog_item`, `list_catalog_categories`

### 변경 관리
- `create_change_request`, `update_change_request`, `list_change_requests`, `approve_change`

### 워크플로우
- `list_workflows`, `get_workflow`, `create_workflow`, `update_workflow`

### 스크립트 인클루드
- `list_script_includes`, `get_script_include`, `create_script_include`, `execute_script_include`

### 변경세트
- `list_changesets`, `create_changeset`, `commit_changeset`, `publish_changeset`

### 지식베이스
- `create_knowledge_base`, `list_knowledge_bases`, `create_article`, `publish_article`

### 사용자 관리
- `create_user`, `update_user`, `get_user`, `list_users`, `create_group`

### 애자일 관리
- `create_story`, `update_story`, `create_epic`, `create_scrum_task`, `create_project`

## Claude Desktop 연동

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/path/to/servicenow-mcp/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.cli"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://instance.service-now.com",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "password",
        "SERVICENOW_AUTH_TYPE": "basic"
      }
    }
  }
}
```

## CI/CD

이 프로젝트는 GitHub Actions를 통한 자동화 파이프라인을 제공합니다:

- **Lint & Type Check**: Black, isort, Ruff, MyPy
- **Test**: Python 3.11, 3.12 매트릭스 테스트
- **Build**: Docker 이미지 빌드 및 GHCR 푸시
- **Security**: Trivy 취약점 스캔
- **Release**: 태그 생성 시 자동 릴리스 및 PyPI 퍼블리시

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

## 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.
