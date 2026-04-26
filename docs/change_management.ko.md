# ServiceNow MCP 변경 관리 도구

이 문서는 ServiceNow MCP 서버에서 제공하는 변경 관리 도구에 대한 정보를 다룹니다.

## 개요

변경 관리 도구를 사용하면 Claude가 ServiceNow의 변경 관리 기능과 연동되어, 자연어 대화를 통해 사용자가 변경 요청을 생성, 수정, 관리할 수 있습니다.

## 사용 가능한 도구

ServiceNow MCP 서버는 다음과 같은 변경 관리 도구를 제공합니다.

### 기본 변경 요청 관리

1. **`manage_change`** - 변경 요청 CRUD 번들 (테이블: `change_request`)
   - `action` (필수): `create` / `update` / `add_task` 중 하나
   - `action="create"`: `short_description`, `type` (`normal`/`standard`/`emergency`) 필수, 그 외 `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date` 선택
   - `action="update"`: `change_id` 필수 + 갱신 필드 1개 이상 (`short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes`); `dry_run=True`로 미리보기 가능
   - `action="add_task"`: `change_id`, `task_short_description` 필수, 그 외 `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date` 선택

2. **`sn_query`** (`table=change_request`) - 임의의 필터로 변경 요청 목록을 조회합니다.
   - 범용 테이블 쿼리 프리미티브로 변경 요청 목록을 조회합니다. `sn_query` 매개변수는 [Tool Inventory](TOOL_INVENTORY.md)를 참고하세요.

3. **`manage_change(action="get")`** - 특정 변경 요청의 상세 정보를 조회합니다.
   - 매개변수:
     - `change_id` (필수): 변경 요청 ID 또는 sys_id

### 변경 승인 워크플로우

1. **submit_change_for_approval** - 변경 요청을 승인 요청 상태로 전환합니다.
   - 매개변수:
     - `change_id` (필수): 변경 요청 ID 또는 sys_id
     - `approval_comments`: 승인 요청에 대한 코멘트

2. **approve_change** - 변경 요청을 승인합니다.
   - 매개변수:
     - `change_id` (필수): 변경 요청 ID 또는 sys_id
     - `approver_id`: 승인자 ID
     - `approval_comments`: 승인 코멘트

3. **reject_change** - 변경 요청을 반려합니다.
   - 매개변수:
     - `change_id` (필수): 변경 요청 ID 또는 sys_id
     - `approver_id`: 승인자 ID
     - `rejection_reason` (필수): 반려 사유

## Claude와 함께 사용하는 예시

ServiceNow MCP 서버를 Claude Desktop에 구성하면, Claude에게 다음과 같은 작업을 요청할 수 있습니다.

### 변경 요청 생성 및 관리

- "내일 밤 보안 패치 적용을 위한 서버 유지보수 변경 요청을 만들어줘"
- "다음 주 화요일 새벽 2시부터 4시까지 데이터베이스 업그레이드를 예약해줘"
- "웹 애플리케이션의 중요 보안 취약점을 긴급 수정하기 위한 긴급 변경 요청을 만들어줘"

### 작업 추가 및 구현 상세

- "서버 유지보수 변경 요청에 사전 점검 작업을 추가해줘"
- "데이터베이스 업그레이드 시작 전 시스템 백업 확인 작업을 추가해줘"
- "네트워크 변경 요청의 구현 계획에 롤백 절차를 포함하도록 수정해줘"

### 승인 워크플로우

- "서버 유지보수 변경 요청을 승인 요청 상태로 올려줘"
- "내 승인을 기다리는 모든 변경 요청을 보여줘"
- "데이터베이스 업그레이드 변경 요청을 승인해줘. 코멘트: 구현 계획이 꼼꼼하네요"
- "테스트가 부족해서 네트워크 변경 요청을 반려해줘"

### 변경 정보 조회

- "이번 주 예정된 모든 긴급 변경 요청을 보여줘"
- "데이터베이스 업그레이드 변경 요청의 상태가 어때?"
- "네트워크 팀에 할당된 모든 변경 요청을 조회해줘"
- "CHG0010001 변경 요청의 상세 정보를 보여줘"

## 코드 예시

변경 관리 도구를 프로그래밍 방식으로 사용하는 예시입니다.

```python
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.utils.config import ServerConfig

# Create server configuration
server_config = ServerConfig(
    instance_url="https://your-instance.service-now.com",
)

# Create authentication manager
auth_manager = AuthManager(
    auth_type="basic",
    username="your-username",
    password="your-password",
    instance_url="https://your-instance.service-now.com",
)

# Create a change request via the bundled manage_change tool
params = ManageChangeParams(
    action="create",
    short_description="Server maintenance - Apply security patches",
    description="Apply the latest security patches to the application servers.",
    type="normal",
    risk="moderate",
    impact="medium",
    category="Hardware",
    start_date="2023-12-15 01:00:00",
    end_date="2023-12-15 03:00:00",
)

result = manage_change(server_config, auth_manager, params)
print(result)
```

위 예시는 프로그래밍 방식의 요청 구조와 변경 관리를 자동화에 통합할 때 필요한 핵심 임포트를 보여줍니다.

## Claude Desktop 연동

Claude Desktop에서 변경 관리 도구가 포함된 ServiceNow MCP 서버를 구성하려면 다음 단계를 따르세요.

1. Claude Desktop 설정 파일을 엽니다. 경로는 macOS의 경우 `~/Library/Application Support/Claude/claude_desktop_config.json` 이며, 사용 중인 OS에 맞는 경로를 사용하세요.

```json
{
  "mcpServers": {
    "ServiceNow": {
      "command": "/Users/yourusername/dev/servicenow-mcp/.venv/bin/python",
      "args": [
        "-m",
        "servicenow_mcp.cli"
      ],
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

2. 변경 사항을 적용하려면 Claude Desktop을 재시작하세요.

## 커스터마이징

변경 관리 도구는 조직의 ServiceNow 구성에 맞게 커스터마이징할 수 있습니다.

- 상태 값은 ServiceNow 인스턴스 구성에 따라 조정이 필요할 수 있습니다.
- 필요한 경우 매개변수 모델에 추가 필드를 포함할 수 있습니다.
- 승인 워크플로우는 조직의 승인 프로세스에 맞게 수정이 필요할 수 있습니다.

도구를 커스터마이징하려면 `src/servicenow_mcp/tools` 디렉토리의 `change_tools.py` 파일을 수정하세요.
