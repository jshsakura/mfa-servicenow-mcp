# ServiceNow MCP 워크플로우 관리

이 문서는 두 종류의 워크플로우 엔진을 다룹니다.

1. **레거시 워크플로우** (`wf_workflow`) — 아래의 `manage_workflow` 액션 라우터로 조작합니다.
2. **Flow Designer** (`sys_hub_flow`) — 단일 통합 도구 `manage_flow_designer`(action 디스패치). `standard` 패키지는 읽기 액션(`list` / `get_detail` / `get_executions` / `compare`)만 노출하고, 상위 패키지(`portal_developer` / `platform_developer` / `full`)에서 쓰기 액션(`update` / `checkout` / `set_*` / `save` / `discard`)이 풀립니다. Action / SubFlow / Playbook 테이블은 [Flow Designer 테이블 맵](#flow-designer-테이블-맵) 참고.

어느 엔진을 쓰는지 모르겠으면 최신 인스턴스에서는 `manage_flow_designer(action="list")`로 시작하고, 레거시 `wf_workflow` 레코드는 `manage_workflow(action="list")`로 폴백하세요.

## 개요

ServiceNow 워크플로우는 비즈니스 프로세스를 정의하고 자동화할 수 있는 강력한 기능입니다. ServiceNow MCP 서버의 워크플로우 관리 도구를 사용하면 ServiceNow 인스턴스의 워크플로우를 조회, 생성, 수정할 수 있습니다.

## 사용 가능한 도구

### 워크플로우 조회

1. **manage_workflow(action="list")** - ServiceNow에서 워크플로우 목록을 조회합니다.
   - 매개변수:
     - `limit` (선택): 반환할 최대 레코드 수 (기본값: 10)
     - `offset` (선택): 조회 시작 위치 (기본값: 0)
     - `active` (선택): 활성 상태로 필터링 (true/false)
     - `name` (선택): 이름으로 필터링 (포함 검색)
     - `query` (선택): 추가 쿼리 문자열

2. **manage_workflow(action="get")** - 특정 워크플로우의 상세 정보를 조회합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id

3. **manage_workflow(action="list_versions")** - 특정 워크플로우의 모든 버전을 조회합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id
     - `limit` (선택): 반환할 최대 레코드 수 (기본값: 10)
     - `offset` (선택): 조회 시작 위치 (기본값: 0)

4. **manage_workflow(action="get_activities")** - 워크플로우의 모든 액티비티를 조회합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id
     - `version` (선택): 액티비티를 조회할 특정 버전 (지정하지 않으면 최신 게시된 버전이 사용됩니다)

### 워크플로우 수정

5. **manage_workflow** (action="create") - ServiceNow에 새 워크플로우를 생성합니다.
   - 매개변수:
     - `name` (필수): 워크플로우 이름
     - `description` (선택): 워크플로우 설명
     - `table` (선택): 워크플로우가 적용되는 테이블
     - `active` (선택): 워크플로우 활성화 여부 (기본값: true)
     - `attributes` (선택): 워크플로우 추가 속성

6. **manage_workflow** (action="update") - 기존 워크플로우를 업데이트합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id
     - `name` (선택): 워크플로우 이름
     - `description` (선택): 워크플로우 설명
     - `table` (선택): 워크플로우가 적용되는 테이블
     - `active` (선택): 워크플로우 활성화 여부
     - `attributes` (선택): 워크플로우 추가 속성

7. **manage_workflow** (action="activate") - 워크플로우를 활성화합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id

8. **manage_workflow** (action="deactivate") - 워크플로우를 비활성화합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id

### 워크플로우 액티비티 관리

9. **manage_workflow** (action="add_activity") - 워크플로우에 새 액티비티를 추가합니다.
   - 매개변수:
     - `workflow_id` (필수): 워크플로우 ID 또는 sys_id
     - `name` (필수): 액티비티 이름
     - `description` (선택): 액티비티 설명
     - `activity_type` (필수): 액티비티 유형 (예: 'approval', 'task', 'notification')
     - `attributes` (선택): 액티비티 추가 속성
     - `position` (선택): 워크플로우 내 위치 (지정하지 않으면 마지막에 추가됩니다)

10. **manage_workflow** (action="update_activity") - 워크플로우의 기존 액티비티를 업데이트합니다.
    - 매개변수:
      - `activity_id` (필수): 액티비티 ID 또는 sys_id
      - `name` (선택): 액티비티 이름
      - `description` (선택): 액티비티 설명
      - `attributes` (선택): 액티비티 추가 속성

11. **manage_workflow** (action="delete_activity") - 워크플로우에서 액티비티를 삭제합니다.
    - 매개변수:
      - `activity_id` (필수): 액티비티 ID 또는 sys_id

12. **manage_workflow** (action="reorder_activities") - 워크플로우 내 액티비티 순서를 변경합니다.
    - 매개변수:
      - `workflow_id` (필수): 워크플로우 ID 또는 sys_id
      - `activity_ids` (필수): 원하는 순서대로 정렬된 액티비티 ID 목록

## 사용 예시

### 워크플로우 조회

#### 모든 활성 워크플로우 조회

```python
result = list_workflows({
    "active": True,
    "limit": 20
})
```

#### 특정 워크플로우 상세 조회

```python
result = get_workflow_details({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### 워크플로우의 모든 버전 조회

```python
result = list_workflow_versions({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### 워크플로우의 모든 액티비티 조회

```python
result = get_workflow_activities({
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### 워크플로우 수정

#### 새 워크플로우 생성

```python
result = manage_workflow({"action": "create",
    "name": "Software License Request",
    "description": "Workflow for handling software license requests",
    "table": "sc_request"
})
```

#### 기존 워크플로우 업데이트

```python
result = manage_workflow({"action": "update",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "description": "Updated workflow description",
    "active": True
})
```

#### 워크플로우 활성화

```python
result = manage_workflow({"action": "activate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

#### 워크플로우 비활성화

```python
result = manage_workflow({"action": "deactivate",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590"
})
```

### 워크플로우 액티비티 관리

#### 새 액티비티 추가

```python
result = manage_workflow({"action": "add_activity",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "name": "Manager Approval",
    "description": "Approval step for the manager",
    "activity_type": "approval"
})
```

#### 기존 액티비티 업데이트

```python
result = manage_workflow({"action": "update_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591",
    "name": "Updated Activity Name",
    "description": "Updated activity description"
})
```

#### 액티비티 삭제

```python
result = manage_workflow({"action": "delete_activity",
    "activity_id": "3cda7cda87a9c150e0b0df23cebb3591"
})
```

#### 액티비티 순서 변경

```python
result = manage_workflow({"action": "reorder_activities",
    "workflow_id": "2bda7cda87a9c150e0b0df23cebb3590",
    "activity_ids": [
        "3cda7cda87a9c150e0b0df23cebb3591",
        "4cda7cda87a9c150e0b0df23cebb3592",
        "5cda7cda87a9c150e0b0df23cebb3593"
    ]
})
```

## Flow Designer 도구

Flow Designer(`sys_hub_flow`)는 레거시 워크플로우의 후속 엔진입니다. MCP 서버는 Table API로 안전하게 노출 가능한 읽기 위주 표면만 제공합니다. 전체 CRUD는 비공개 processflow API가 필요해 의도적으로 표면화하지 않습니다.

### `manage_flow_designer` (통합 도구)
단일 합성 도구. 기존 6개 개별 도구(`list_flow_designers`, `get_flow_designer_detail`, `get_flow_designer_executions`, `compare_flows`, `update_flow_designer`, `manage_flow_edit`)를 대체합니다. `standard`에서는 action enum이 읽기 전용으로 좁혀지고, `portal_developer` / `platform_developer` / `full`에서 쓰기까지 풀립니다.

읽기 액션 (`standard` 포함):
- `action="list"` — 플로우/서브플로우 검색. 주요 파라미터: `limit`, `offset`, `include_inactive`, `flow_status`, `scope`, `name_filter`.
- `action="get_detail"` — 단일 플로우 메타데이터 + 선택적 heavy 섹션. 주요 파라미터: `flow_id`(필수), `include_structure`, `include_triggers`, `include_executions_summary`, `trace_pill`, `include_subflow_tree`, `summary_format`.
- `action="get_executions"` — 실행 이력(필터) 또는 단일 실행 상세. 주요 파라미터: `context_id`(단일 모드), `flow_id`, `flow_name`, `exec_state`, `source_record`, `errors_only`, `limit`/`offset`.
- `action="compare"` — 두 플로우 diff. `flow_id_a`/`flow_id_b` 또는 `name_a`/`name_b`. 구조/서브플로우/트리거 차이 리포트. `get_detail` 두 번 호출보다 권장.

쓰기 액션 (`portal_developer` / `platform_developer` / `full`):
- `action="update"` — 메타데이터만(`new_name` / `description` / `active`). 스텝/트리거 등 구조 변경은 아래 편집 워크플로우 또는 Workflow Studio UI 필요.
- `action="checkout"` — 로컬 편집 세션 시작 (브라우저 auth, processflow API).
- `action="set_action_input"` — 액션 입력값 패치. `node_id`, `input_name`, `value` 필수.
- `action="set_branch_condition"` — 플로우 로직 분기 조건 패치. `node_id`, `value` 필수, `condition_label` 선택.
- `action="set_trigger_condition"` — 트리거 조건 패치. `value` 필수, `node_id` 생략 시 첫 트리거.
- `action="save"` — processflow API로 저장. `publish=true` 시 저장 후 퍼블리시.
- `action="discard"` — 로컬 편집 세션 폐기.
- `action="edit_status"` — 현재 로컬 체크아웃 상태 확인.

### Flow Designer 테이블 맵

| Workflow Studio 탭 | 테이블 |
| --- | --- |
| Flows / SubFlows | `sys_hub_flow` |
| Actions | `sys_hub_action_type_definition` |
| Playbooks | `sys_pd_process_definition` |
| Decision Tables | `sys_decision` |

### 읽기 위주 정책

플로우 변경은 이 코드베이스에서 가장 위험한 작업입니다 — 퍼블리시된 플로우가 깨지면 인스턴스 전반의 자동화가 멈출 수 있습니다. 기본적으로 읽기 액션만 쓰고, 쓰기는 사용자 명시 확인을 게이트로 두며, 변경 전 `manage_flow_designer(action="compare")` + `manage_flow_designer(action="get_executions")`로 동작을 검증하세요.

## 주요 액티비티 유형

ServiceNow에서는 워크플로우에 액티비티를 추가할 때 여러 가지 액티비티 유형을 사용할 수 있습니다.

1. **approval** - 사용자의 승인이 필요한 승인 액티비티
2. **task** - 완료해야 하는 작업
3. **notification** - 사용자에게 알림을 전송합니다.
4. **timer** - 지정된 시간 동안 대기합니다.
5. **condition** - 조건을 평가하고 워크플로우를 분기합니다.
6. **script** - 스크립트를 실행합니다.
7. **wait_for_condition** - 조건이 충족될 때까지 대기합니다.
8. **end** - 워크플로우를 종료합니다.

## 모범 사례

1. **버전 관리**: 중요한 변경을 하기 전에 항상 워크플로우의 새 버전을 생성하세요.
2. **테스트**: 프로덕션에 배포하기 전에 비프로덕션 환경에서 워크플로우를 테스트하세요.
3. **문서화**: 각 워크플로우와 액티비티의 목적과 동작을 문서화하세요.
4. **오류 처리**: 예상치 못한 상황에 대비해 워크플로우에 오류 처리를 포함하세요.
5. **알림**: 알림 액티비티를 사용하여 관계자들에게 워크플로우 진행 상황을 알려주세요.

## 문제 해결

### 자주 발생하는 문제

1. **오류: "No published versions found for this workflow"**
   - 게시된 버전이 없는 워크플로우의 액티비티를 조회하려 할 때 발생합니다.
   - 해결 방법: 액티비티를 조회하기 전에 워크플로우 버전을 먼저 게시하세요.

2. **오류: "Activity type is required"**
   - 액티비티 유형을 지정하지 않고 액티비티를 추가하려 할 때 발생합니다.
   - 해결 방법: 액티비티를 추가할 때 유효한 액티비티 유형을 지정하세요.

3. **오류: "Cannot modify a published workflow version"**
   - 게시된 워크플로우 버전을 수정하려 할 때 발생합니다.
   - 해결 방법: 변경하기 전에 워크플로우의 새 초안 버전을 생성하세요.

4. **오류: "Workflow ID is required"**
   - 워크플로우 ID가 필요한 작업에서 ID를 제공하지 않았을 때 발생합니다.
   - 해결 방법: 요청에 워크플로우 ID를 반드시 포함하세요.

## 추가 자료

- [ServiceNow 워크플로우 문서](https://docs.servicenow.com/bundle/tokyo-platform-administration/page/administer/workflow-administration/concept/c_WorkflowAdministration.html)
- [ServiceNow 워크플로우 API 참조](https://developer.servicenow.com/dev.do#!/reference/api/tokyo/rest/c_WorkflowAPI)
