# ServiceNow MCP Server

> 원본: [echelon-ai-labs/servicenow-mcp](https://github.com/echelon-ai-labs/servicenow-mcp)  
> 보안 인증: [MseeP.ai](https://mseep.ai/app/osomai/servicenow-mcp)

Claude가 ServiceNow 인스턴스와 상호작용할 수 있도록 하는 Model Completion Protocol (MCP) 서버 구현체입니다.

## 개요

이 프로젝트는 Claude가 ServiceNow 인스턴스에 연결하고, 데이터를 조회하며, ServiceNow API를 통해 작업을 수행할 수 있도록 하는 MCP 서버를 구현합니다. Claude와 ServiceNow 간의 원활한 통합을 위한 브리지 역할을 합니다.

## 주요 기능

- 다양한 인증 방식 지원 (Basic, OAuth, API Key, Browser)
- ServiceNow 레코드 및 테이블 조회
- ServiceNow 레코드 생성, 수정, 삭제
- ServiceNow 스크립트 및 워크플로우 실행
- ServiceNow 서비스 카탈로그 접근 및 조회
- 서비스 카탈로그 분석 및 최적화
- 디버그 모드 지원
- stdio 및 Server-Sent Events (SSE) 통신 지원

## 통합 병합 (3 MCP → 1)

이 프로젝트는 세 가지 레거시 구현체를 통합한 결과입니다:

- `servicenow-mcp-1`: 범용 코어 도구 (`sn_query`, `sn_aggregate`, `sn_schema`, `sn_discover`, `sn_health`) 및 자연어 헬퍼 (`sn_nl`)
- `servicenow-mcp-2`: 광범위한 엔터프라이즈 도구, 패키지 기반 노출 (`MCP_TOOL_PACKAGE`), stdio/SSE 전송
- `servicenow-mcp-3`: 실용적인 NLP 파싱 스타일 및 토큰/세션 수명 주기 인식

### 보안 중심 MFA 지원

- MFA 우회 로직 미구현
- 브라우저 인증은 대화형 및 MFA 호환
- 브라우저 세션 쿠키는 인스턴스 범위의 보안 쿠키로만 필터링

## 설치

### 사전 요구사항

- Python 3.11 이상
- 적절한 액세스 자격 증명이 있는 ServiceNow 인스턴스

### 설정

1. 저장소 클론:
   ```bash
   git clone https://github.com/echelon-ai-labs/servicenow-mcp.git
   cd servicenow-mcp
   ```

2. 가상환경 생성 및 패키지 설치:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -e .
   ```

3. `.env` 파일에 ServiceNow 자격 증명 설정:
   ```
   SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
   SERVICENOW_USERNAME=your-username
   SERVICENOW_PASSWORD=your-password
   SERVICENOW_AUTH_TYPE=basic  # 또는 oauth, api_key
   ```

## 사용법

### 표준 (stdio) 모드

```bash
python -m servicenow_mcp.cli
```

또는 환경 변수와 함께:

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
SERVICENOW_USERNAME=your-username \
SERVICENOW_PASSWORD=your-password \
SERVICENOW_AUTH_TYPE=basic \
python -m servicenow_mcp.cli
```

### Server-Sent Events (SSE) 모드

```bash
servicenow-mcp-sse --instance-url=https://your-instance.service-now.com --username=your-username --password=your-password
```

기본적으로 `0.0.0.0:8080`에서 수신합니다. 호스트와 포트 변경 가능:

```bash
servicenow-mcp-sse --host=127.0.0.1 --port=8000
```

#### SSE 서버 엔드포인트

- `/sse` - SSE 연결 엔드포인트
- `/messages/` - 서버로 메시지 전송 엔드포인트

## 도구 패키징 (선택사항)

`MCP_TOOL_PACKAGE` 환경 변수를 통해 도구 하위 집합을 로드할 수 있습니다.

### 설정

```bash
export MCP_TOOL_PACKAGE=catalog_builder
```

패키지 정의는 `config/tool_packages.yaml`에 있습니다.

### 동작

- `MCP_TOOL_PACKAGE`가 유효한 패키지 이름으로 설정되면 해당 패키지의 도구만 로드
- 설정되지 않거나 비어 있으면 `full` 패키지가 기본 로드
- 잘못된 이름이면 `none` 패키지 로드 (경고 로그)
- `MCP_TOOL_PACKAGE=none`으로 명시적 설정 가능

### 기본 패키지

| 패키지 | 설명 |
|--------|------|
| `service_desk` | 인시던트 처리 및 기본 사용자/지식 베이스 조회 |
| `catalog_builder` | 서비스 카탈로그 항목, 카테고리, 변수 관리 |
| `change_coordinator` | 변경 요청 수명 주기 관리 |
| `knowledge_author` | 지식 베이스, 카테고리, 문서 관리 |
| `platform_developer` | 서버 사이드 스크립팅, 워크플로우 개발, 배포 |
| `system_administrator` | 사용자/그룹 관리 및 시스템 로그 조회 |
| `agile_management` | 사용자 스토리, 에픽, 스크럼 태스크, 프로젝트 관리 |
| `full` | 모든 도구 포함 (기본값) |
| `none` | 도구 없음 (`list_tool_packages` 제외) |

## 사용 가능한 도구

> 도구 가용성은 로드된 패키지에 따라 다릅니다.

### 인시던트 관리

| 도구 | 설명 |
|------|------|
| `create_incident` | 새 인시던트 생성 |
| `update_incident` | 인시던트 업데이트 |
| `add_comment` | 인시던트에 코멘트 추가 |
| `resolve_incident` | 인시던트 해결 |
| `list_incidents` | 인시던트 목록 조회 |

### 서비스 카탈로그

| 도구 | 설명 |
|------|------|
| `list_catalog_items` | 카탈로그 항목 목록 |
| `get_catalog_item` | 특정 카탈로그 항목 조회 |
| `list_catalog_categories` | 카탈로그 카테고리 목록 |
| `create_catalog_category` | 새 카테고리 생성 |
| `update_catalog_category` | 카테고리 업데이트 |
| `move_catalog_items` | 항목 이동 |
| `create_catalog_item_variable` | 변수(폼 필드) 생성 |
| `list_catalog_item_variables` | 변수 목록 |
| `update_catalog_item_variable` | 변수 업데이트 |
| `list_catalogs` | 서비스 카탈로그 목록 |

### 변경 관리

| 도구 | 설명 |
|------|------|
| `create_change_request` | 변경 요청 생성 |
| `update_change_request` | 변경 요청 업데이트 |
| `list_change_requests` | 변경 요청 목록 |
| `get_change_request_details` | 변경 요청 상세 조회 |
| `add_change_task` | 변경 요청에 태스크 추가 |
| `submit_change_for_approval` | 승인 요청 제출 |
| `approve_change` | 변경 요청 승인 |
| `reject_change` | 변경 요청 거부 |

### 애자일 관리

**스토리 관리:** `create_story`, `update_story`, `list_stories`, `create_story_dependency`, `delete_story_dependency`

**에픽 관리:** `create_epic`, `update_epic`, `list_epics`

**스크럼 태스크:** `create_scrum_task`, `update_scrum_task`, `list_scrum_tasks`

**프로젝트 관리:** `create_project`, `update_project`, `list_projects`

### 워크플로우 관리

`list_workflows`, `get_workflow`, `create_workflow`, `update_workflow`, `delete_workflow`

### 스크립트 인클루드 관리

`list_script_includes`, `get_script_include`, `create_script_include`, `update_script_include`, `delete_script_include`

### 체인지셋 관리

`list_changesets`, `get_changeset_details`, `create_changeset`, `update_changeset`, `commit_changeset`, `publish_changeset`, `add_file_to_changeset`

### 지식 베이스 관리

`create_knowledge_base`, `list_knowledge_bases`, `create_category`, `create_article`, `update_article`, `publish_article`, `list_articles`, `get_article`

### 사용자 관리

`create_user`, `update_user`, `get_user`, `list_users`, `create_group`, `update_group`, `add_group_members`, `remove_group_members`, `list_groups`

### UI 정책

`create_ui_policy`, `create_ui_policy_action`

## Claude Desktop 통합

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) 또는 OS에 맞는 경로에 설정:

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/Users/yourusername/dev/servicenow-mcp/.venv/bin/python",
      "args": ["-m", "servicenow_mcp.cli"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "SERVICENOW_AUTH_TYPE": "basic"
      }
    }
  }
}
```

## 인증 방법

### Basic 인증

```
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=your-username
SERVICENOW_PASSWORD=your-password
```

### OAuth 인증

```
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_CLIENT_ID=your-client-id
SERVICENOW_CLIENT_SECRET=your-client-secret
SERVICENOW_TOKEN_URL=https://your-instance.service-now.com/oauth_token.do
```

### API Key 인증

```
SERVICENOW_AUTH_TYPE=api_key
SERVICENOW_API_KEY=your-api-key
```

### 브라우저 인증 (MFA/SSO 지원)

보안 정책으로 토큰 발급이 불가하고 수동 MFA 완료가 필요한 경우 사용합니다.

```
SERVICENOW_AUTH_TYPE=browser
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_BROWSER_USERNAME=your-username
SERVICENOW_BROWSER_PASSWORD=your-password
SERVICENOW_BROWSER_HEADLESS=false
SERVICENOW_BROWSER_TIMEOUT=120
SERVICENOW_BROWSER_SESSION_TTL=30
```

Playwright 설치 필요:

```bash
pip install playwright
playwright install chromium
```

## 문제 해결

### 변경 관리 도구 일반 오류

1. **`argument after ** must be a mapping`**: Pydantic 모델 대신 딕셔너리로 전달
2. **`Missing required parameter 'type'`**: 필수 매개변수 포함 확인
3. **`Invalid value for parameter 'type'`**: "normal", "standard", "emergency" 중 하나 사용
4. **`Cannot find get_headers method`**: 매개변수 순서 확인

## 개발

### 문서

`docs` 디렉토리 참조:
- `catalog.md` - 서비스 카탈로그 통합
- `catalog_optimization_plan.md` - 카탈로그 최적화 계획
- `change_management.md` - 변경 관리 도구
- `workflow_management.md` - 워크플로우 관리 도구
- `changeset_management.md` - 체인지셋 관리 도구

## 라이선스

MIT License - LICENSE 파일 참조
