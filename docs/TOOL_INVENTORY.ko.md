# ServiceNow MCP - 도구 인벤토리

활성 도구: **89** | 코드에 등록된 도구: **127** | 패키지에서 제거된 도구: **38**

## 패키지 요약

| 패키지 | 도구 | 기본값 | 설명 |
|---------|-------|---------|-------------|
| `none` | 0 |  | 비활성화 |
| `standard` | 45 | Y | 읽기 전용 안전 모드 |
| `portal_developer` | 61 |  | 포털/위젯 개발 |
| `platform_developer` | 69 |  | 백엔드/워크플로 개발 |
| `service_desk` | 49 |  | 인시던트 운영 |
| `full` | 89 |  | 모든 기능 |

## 카테고리별 도구

### 애자일 - 에픽 (3)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_epic` | W | ServiceNow에 새 에픽을 생성합니다... | *(none)* |
| `list_epics` | R | ServiceNow에서 에픽 목록을 조회합니다... | *(none)* |
| `update_epic` | W | 기존 에픽을 업데이트합니다... | *(none)* |

### 애자일 - 프로젝트 (3)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_project` | W | ServiceNow에 새 프로젝트를 생성합니다... | *(none)* |
| `list_projects` | R | ServiceNow에서 프로젝트 목록을 조회합니다... | *(none)* |
| `update_project` | W | 기존 프로젝트를 업데이트합니다... | *(none)* |

### 애자일 - 스크럼 태스크 (3)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_scrum_task` | W | ServiceNow에 새 스크럼 태스크를 생성합니다... | *(none)* |
| `list_scrum_tasks` | R | ServiceNow에서 스크럼 태스크 목록을 조회합니다... | *(none)* |
| `update_scrum_task` | W | 기존 스크럼 태스크를 업데이트합니다... | *(none)* |

### 애자일 - 스토리 (6)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_story` | W | ServiceNow에 새 스토리를 생성합니다... | *(none)* |
| `create_story_dependency` | W | 두 스토리 간의 의존성을 생성합니다... | *(none)* |
| `delete_story_dependency` | W | 스토리 의존성을 삭제합니다... | *(none)* |
| `list_stories` | R | ServiceNow에서 스토리 목록을 조회합니다... | *(none)* |
| `list_story_dependencies` | R | ServiceNow에서 스토리 의존성 목록을 조회합니다... | *(none)* |
| `update_story` | W | 기존 스토리를 업데이트합니다... | *(none)* |

### 감사 (1)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `audit_pending_changes` | R | 한 번의 호출로 개발자의 대기 중인 업데이트 세트 변경 사항을 감사합니다. 인벤토리 그... | full, platform_developer, portal_developer, service_desk, standard |

### 카탈로그 (6)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_catalog_category` | W | 카탈로그 카테고리를 생성합니다. 제목이 필요합니다. 선택적으로 상위 카테고리, 아이콘, 정렬 순서... | full |
| `get_catalog_item` | R | sys_id로 단일 카탈로그 아이템을 가져옵니다. 변수를 포함한 전체 세부 정보를 반환합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `list_catalog_categories` | R | 상위/하위 관계가 포함된 카탈로그 카테고리 목록을 조회합니다. 활성 상태로 필터링... | full, platform_developer, portal_developer, service_desk, standard |
| `list_catalog_items` | R | 카테고리/활성 상태 필터로 카탈로그 아이템을 검색합니다. 이름, 가격,... | full, platform_developer, portal_developer, service_desk, standard |
| `move_catalog_items` | W | 하나 이상의 카탈로그 아이템을 대상 카테고리로 이동합니다. item_ids와 t... | full |
| `update_catalog_category` | W | sys_id로 카탈로그 카테고리를 부분 업데이트합니다. 제목, 상위 카테고리, 아이콘, 정렬 순서... | full |

### 카탈로그 최적화 (2)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_optimization_recommendations` | R | 카탈로그 구조를 분석하여 개선 사항을 제안합니다 (비활성 아이템, 낮은 사용량, a... | full, platform_developer, portal_developer, service_desk, standard |
| `update_catalog_item` | W | sys_id로 카탈로그 아이템을 부분 업데이트합니다. 이름, 설명, 카테고리... | full |

### 카탈로그 변수 (3)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_catalog_item_variable` | W | 카탈로그 아이템에 폼 변수를 추가합니다. cat_item sys_id, 변수 타입,... | full |
| `list_catalog_item_variables` | R | 카탈로그 아이템의 변수 정의 목록을 조회합니다. 타입, 순서, 필수 여부... | full, platform_developer, portal_developer, service_desk, standard |
| `update_catalog_item_variable` | W | sys_id로 카탈로그 아이템 변수를 부분 업데이트합니다. 라벨, 순서, 필수 여부... | full |

### 변경 관리 (7)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_change_request_details` | R | sys_id/번호로 단일 변경 요청을 가져오거나, 필터로 목록을 조회합니다. change... | full, platform_developer, portal_developer, service_desk, standard |
| `add_change_task` | W | 변경 요청 하위에 change_task를 생성합니다. change_id와 short_descri... | full |
| `approve_change` | W | 변경 요청을 승인하고 상태를 구현으로 전환합니다. change_... | full |
| `create_change_request` | W | 변경 요청을 생성합니다. short_description과 type(normal/standard/em... | full |
| `reject_change` | W | 변경 요청을 거부하고 상태를 취소로 전환합니다. change_id... | full |
| `submit_change_for_approval` | W | 변경 요청을 평가 상태로 전환하고 승인 레코드를 생성합니다. 필수... | full, platform_developer |
| `update_change_request` | W | sys_id로 변경 요청을 업데이트합니다. 상태, 설명, 위험, 영향도, 날짜... | full, platform_developer |

### 체인지셋 (6)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_changeset_details` | R | sys_id로 항목이 포함된 단일 업데이트 세트를 가져오거나, 필터로 목록을 조회합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `add_file_to_changeset` | W | 업데이트 세트에 레코드(파일 경로 + 콘텐츠)를 첨부합니다... | full, platform_developer, portal_developer |
| `commit_changeset` | W | 업데이트 세트를 완료로 표시하여 마무리합니다. 이후 편집이 불가합니다... | full, platform_developer, portal_developer |
| `create_changeset` | W | 새 업데이트 세트를 생성합니다. 성공 시 새 sys_id를 반환합니다... | full, platform_developer, portal_developer |
| `publish_changeset` | W | 커밋된 업데이트 세트를 대상 인스턴스에 배포합니다... | full, platform_developer, portal_developer |
| `update_changeset` | W | 기존 업데이트 세트의 이름, 설명, 상태 또는 개발자를 업데이트합니다... | full, platform_developer, portal_developer |

### 코드 감지 (1)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `detect_missing_profit_company_codes` | R | 포털 위젯과 프로바이더 스크립트에서 누락된 profit_company_code 브랜치 값을 감지합니다... | full, platform_developer, portal_developer, service_desk, standard |

### 코어 (6)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `sn_aggregate` | R | 임의의 테이블에서 COUNT/SUM/AVG/MIN/MAX를 실행합니다. 선택적 group_by 지원. 통계와 함께... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_discover` | R | 이름 또는 라벨 키워드로 테이블을 검색합니다. 테이블 이름, 라벨, 범위, 상위 테이블... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_health` | R | ServiceNow API 연결 및 인증 상태를 확인합니다. 최초 실행 시 브라우저 로그인을 트리거합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_nl` | R | 자연어를 쿼리, 스키마 또는 집계 호출로 변환합니다. 의도를 파싱하고... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_query` | R | 인코딩된 쿼리 필터로 임의의 ServiceNow 테이블을 조회합니다. 대체용이며, 전용 도구를 우선... | full, platform_developer, portal_developer, service_desk, standard |
| `sn_schema` | R | 지정된 테이블의 sys_dictionary에서 필드 이름, 타입, 라벨, 제약 조건을 가져옵니다... | full, platform_developer, portal_developer, service_desk, standard |

### 개발자 - 리포지토리 (4)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_repo_change_report` | R | 통합 git 보고서: 작업 트리 상태 + 최근 커밋 + 파일별 마지막 수정... | full, platform_developer, portal_developer, service_desk, standard |
| `get_repo_file_last_modifier` | R | 파일별 마지막 수정자와 커밋 메타데이터를 조회합니다. 커밋되지 않은 상태... | *(none)* |
| `get_repo_recent_commits` | R | 작성자 및 선택적 변경 파일 목록이 포함된 최근 커밋을 조회합니다... | *(none)* |
| `get_repo_working_tree_status` | R | 스테이징, 비스테이징, 추적되지 않은 파일을 포함한 작업 트리 상태를 확인합니다... | *(none)* |

### 플로우 디자이너 (3)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `list_flow_designers` | R | 선택적 필터로 Flow Designer 플로우 목록을 조회합니다. 플로우 이름, 상태, 활성... | full, platform_developer, portal_developer, service_desk, standard |
| `get_flow_designer_detail` | R | 플로우 메타데이터를 가져옵니다. include_structure=true로 액션/로직/서브플로우 트리를, inc... | full, platform_developer, portal_developer, service_desk, standard |
| `get_flow_designer_executions` | R | 실행 이력 또는 단일 실행 상세 정보를 가져옵니다(context_id 제공). 필터: 상태별... | full, platform_developer, portal_developer, service_desk, standard |

### 인시던트 (5)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_incident_by_number` | R | 번호로 단일 인시던트를 가져오거나, 필터로 목록을 조회합니다. inciden... | full, platform_developer, portal_developer, service_desk, standard |
| `add_comment` | W | sys_id로 인시던트에 작업 노트(내부용) 또는 고객에게 보이는 댓글을 추가합니다... | full, service_desk |
| `create_incident` | W | 새 인시던트를 생성합니다(short_description 필수). sys_id와 INC 번호를 반환합니다... | full, service_desk |
| `resolve_incident` | W | 인시던트 상태를 해결됨으로 변경하고 resolution_code와 close_notes를 설정합니다. update_... | full, platform_developer, service_desk |
| `update_incident` | W | sys_id 또는 INC 번호로 인시던트를 부분 필드 변경하여 업데이트합니다. 모든... | full, platform_developer, service_desk |

### 지식 베이스 (9)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_article` | W | 새 지식 아티클을 생성합니다... | *(none)* |
| `create_category` | W | 지식 베이스에 새 카테고리를 생성합니다... | *(none)* |
| `create_knowledge_base` | W | ServiceNow에 새 지식 베이스를 생성합니다... | *(none)* |
| `get_article` | R | ID로 특정 지식 아티클을 가져옵니다... | *(none)* |
| `list_articles` | R | 지식 아티클 목록을 조회합니다... | *(none)* |
| `list_categories` | R | 지식 베이스의 카테고리 목록을 조회합니다... | *(none)* |
| `list_knowledge_bases` | R | ServiceNow에서 지식 베이스 목록을 조회합니다... | *(none)* |
| `publish_article` | W | 지식 아티클을 게시합니다... | *(none)* |
| `update_article` | W | 기존 지식 아티클을 업데이트합니다... | *(none)* |

### 워크플로 (wf_workflow 엔진) (10)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `list_workflows` | R | 이름, 테이블 또는 활성 상태로 필터링하여 워크플로 목록을 조회합니다. 간단한... | full, platform_developer, portal_developer, service_desk, standard |
| `get_workflow_details` | R | 워크플로 메타데이터를 가져옵니다. include_versions=true로 버전 이력, include_act... | full, platform_developer, portal_developer, service_desk, standard |
| `activate_workflow` | W | sys_id로 워크플로를 활성 상태로 설정합니다. 업데이트된 워크플로 레코드를 반환합니다... | full, platform_developer |
| `add_workflow_activity` | W | 워크플로 버전에 액티비티(승인, 태스크, 알림 등)를 추가합니다... | full, platform_developer |
| `create_workflow` | W | 이름, 테이블, 설명 및 활성 플래그로 워크플로를 생성합니다. 생성된... | full, platform_developer |
| `deactivate_workflow` | W | sys_id로 워크플로를 비활성 상태로 설정합니다. 업데이트된 워크플로 레코드를 반환합니다... | full, platform_developer |
| `delete_workflow_activity` | W | 액티비티 sys_id로 워크플로에서 액티비티를 제거합니다. 복원할 수 없습니다... | full, platform_developer |
| `reorder_workflow_activities` | W | 액티비티 sys_id를 원하는 순서로 제공하여 워크플로 액티비티를 재정렬합니다... | full, platform_developer |
| `update_workflow` | W | sys_id로 워크플로의 이름, 설명, 테이블 또는 활성 상태를 업데이트합니다... | full, platform_developer |
| `update_workflow_activity` | W | 액티비티 sys_id로 액티비티의 이름, 설명 또는 속성을 업데이트합니다... | full, platform_developer |

### 로그 (4)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_background_script_logs` | R | sys_execution_tracker에서 상태가 포함된 예약/백그라운드 스크립트 실행 로그를 조회합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `get_journal_entries` | R | 임의의 레코드에서 작업 노트와 댓글을 가져옵니다. 테이블, 레코드 sys_id 또는... | full, platform_developer, portal_developer, service_desk, standard |
| `get_system_logs` | R | 레벨/소스/메시지로 syslog 항목을 조회합니다. 안전을 위해 20행으로 하드 캡됩니다... | full, platform_developer, portal_developer, service_desk, standard |
| `get_transaction_logs` | R | URL, 상태 및 소요 시간이 포함된 HTTP 트랜잭션 로그를 조회합니다. 요청 성능... | full, platform_developer, portal_developer, service_desk, standard |

### 성능 분석 (1)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `analyze_widget_performance` | R | 위젯의 코드 패턴, 트랜잭션 로그 및 데이터 프로바이더 사용량을 분석합니다. 반환... | full, platform_developer, portal_developer, service_desk, standard |

### 로컬 동기화 (2)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `diff_local_component` | R | 로컬 포털 소스 파일과 원격 ServiceNow를 비교합니다. 루트 디렉토리에서 다운로드... | full, platform_developer, portal_developer, service_desk, standard |
| `update_remote_from_local` | W | 로컬 파일 변경 사항을 ServiceNow에 푸시합니다. 푸시 전 자동으로 스냅샷을 생성합니다. 거부... | full, platform_developer, portal_developer |

### 포털 개발 유틸리티 (4)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_developer_changes` | R | 포털 테이블(위젯, 프로바이더, SI, ...)에서 개발자의 최근 변경 사항을 조회합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `get_developer_daily_summary` | R | 개발자의 일일 작업 요약을 Jira/Confluence용으로 생성합니다. 라인 수... | *(none)* |
| `get_provider_dependency_map` | R | 위젯-프로바이더-스크립트 인클루드 의존성 그래프를 생성합니다. 메타데이터... | full, platform_developer, portal_developer, service_desk, standard |
| `get_uncommitted_changes` | R | 개발자의 커밋되지 않은 업데이트 세트 항목을 조회합니다. 먼저 count_only=true로... | *(none)* |

### 포털 개발 (12)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `analyze_portal_component_update` | R | 제안된 포털 컴포넌트 편집을 분석하여 범위가 제한된 위험도와 필드 변경... | full, portal_developer |
| `create_portal_component_snapshot` | W | 포털 컴포넌트의 현재 편집 가능한 상태를 로컬 스냅샷 파일로 저장합니다... | full, portal_developer |
| `detect_angular_implicit_globals` | R | Angular 프로바이더 스크립트에서 런타임 오류를 유발하는 선언되지 않은 변수 할당을 찾습니다... | full, platform_developer, portal_developer, service_desk, standard |
| `download_portal_sources` | R | 위젯, 프로바이더 및 스크립트 인클루드 소스를 로컬 파일 구조로 내보냅니다. 지원... | full, platform_developer, portal_developer, service_desk, standard |
| `get_portal_component_code` | R | 위젯, 프로바이더 또는 스크립트 인클루드에서 특정 코드 필드를 가져옵니다. 토큰 효율적... | full, platform_developer, portal_developer, service_desk, standard |
| `get_widget_bundle` | R | 단일 API 호출로 위젯 HTML, 스크립트 및 프로바이더 목록을 가져옵니다. 완전한... | full, platform_developer, portal_developer, service_desk, standard |
| `preview_portal_component_update` | R | 제안된 포털 컴포넌트 편집에 대한 변경 전/후 스니펫과 diff를 미리 확인합니다... | full, portal_developer |
| `route_portal_component_edit` | R | 짧은 포털 편집 지침을 범위가 제한된... | full, portal_developer |
| `search_portal_regex_matches` | R | 위젯 소스(HTML/스크립트/프로바이더)에서 정규식 검색을 수행합니다. 최소, c... | full, platform_developer, portal_developer, service_desk, standard |
| `trace_portal_route_targets` | R | 원본 스크립트 본문 없이 위젯-프로바이더-라우트 관계를 매핑합니다. 반환... | full, platform_developer, portal_developer, service_desk, standard |
| `update_portal_component` | W | 위젯, 프로바이더 또는 스크립트 인클루드의 특정 코드 필드(HTML, CSS 또는 스크립트)를 업데이트합니다... | full, portal_developer |
| `update_portal_component_from_snapshot` | W | 이전에 저장된 로컬 스냅샷에서 포털 컴포넌트의 편집 가능한 필드를 복원합니다... | full, portal_developer |

### 포털 관리 (5)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `get_portal` | R | sys_id/URL 접미사로 단일 포털을 가져오거나, 모든 포털 목록을 조회합니다. portal_id... | full, platform_developer, portal_developer, service_desk, standard |
| `get_page` | R | sys_id/URL 경로로 레이아웃이 포함된 단일 페이지를 가져오거나, 모든 페이지 목록을 조회합니다. pag... | full, platform_developer, portal_developer, service_desk, standard |
| `get_widget_instance` | R | sys_id로 단일 위젯 인스턴스를 가져오거나, 페이지/위젯 필터로 목록을 조회합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `create_widget_instance` | W | 페이지 컬럼에 위젯을 배치합니다. 위젯 sys_id, 대상 컬럼, 순서 및... | full, portal_developer |
| `update_widget_instance` | W | 페이지에서 기존 위젯 인스턴스를 이동, 재정렬 또는 옵션/CSS 업데이트합니다... | full, portal_developer |

### 스크립트 인클루드 (6)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_script_include` | W | 이름, 스크립트, api_name 및 client_callable 필드로 스크립트 인클루드를 생성합니다... | full, platform_developer, portal_developer |
| `delete_script_include` | W | sys_id 또는 이름으로 스크립트 인클루드를 영구 삭제합니다. 복원할 수 없습니다... | full, platform_developer |
| `execute_script_include` | W | GlideAjax REST를 통해 클라이언트 호출 가능한 스크립트 인클루드 메서드를 실행합니다. client_... | full, platform_developer |
| `get_script_include` | R | sys_id 또는 이름으로 전체 스크립트 본문이 포함된 단일 스크립트 인클루드를 가져옵니다... | full, platform_developer, portal_developer, service_desk, standard |
| `list_script_includes` | R | 이름/범위/활성 상태로 필터링하여 스크립트 인클루드 목록을 조회합니다. 스크립트 없이 메타데이터만... | full, platform_developer, portal_developer, service_desk, standard |
| `update_script_include` | W | sys_id로 스크립트 인클루드의 스크립트, api_name, client_callable 또는 기타 필드를 업데이트합니다... | full, platform_developer, portal_developer |

### 소스 검색 (4)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `extract_table_dependencies` | R | 서버 스크립트에서 GlideRecord 테이블 의존성 그래프를 생성합니다. SI, BR 및... | full, platform_developer, portal_developer, service_desk, standard |
| `extract_widget_table_dependencies` | R | 단일 위젯에 대한 테이블 의존성 그래프를 생성합니다. 선택적으로 연결된... | full, platform_developer, portal_developer, service_desk, standard |
| `get_metadata_source` | R | 이름 또는 sys_id로 소스 레코드(SI, BR, 위젯 등)를 가져옵니다. 메타데이터를 반환합니다... | full, platform_developer, portal_developer, service_desk, standard |
| `search_server_code` | R | 서버 측 스크립트(SI, BR, 클라이언트 스크립트 등)에서 키워드/정규식 검색을 수행합니다. ... | full, platform_developer, portal_developer, service_desk, standard |

### UI 정책 (2)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `create_ui_policy` | W | 인코딩된 쿼리에 의해 트리거되는 폼 필드 동작 규칙(표시/숨김/필수)을 생성합니다... | full, platform_developer |
| `create_ui_policy_action` | W | UI 정책에 필드 수준 액션을 추가합니다: 표시 여부, 필수 여부 또는 읽기 전용... | full, platform_developer |

### 사용자 및 그룹 (9)

| 도구 | 읽기/쓰기 | 설명 | 패키지 |
|------|-----|-------------|----------|
| `add_group_members` | W | ServiceNow의 기존 그룹에 멤버를 추가합니다... | *(none)* |
| `create_group` | W | ServiceNow에 새 그룹을 생성합니다... | *(none)* |
| `create_user` | W | ServiceNow에 새 사용자를 생성합니다... | *(none)* |
| `get_user` | R | ServiceNow에서 특정 사용자를 가져옵니다... | *(none)* |
| `list_groups` | R | 선택적 필터링으로 ServiceNow에서 그룹 목록을 조회합니다... | *(none)* |
| `list_users` | R | ServiceNow에서 사용자 목록을 조회합니다... | *(none)* |
| `remove_group_members` | W | ServiceNow의 기존 그룹에서 멤버를 제거합니다... | *(none)* |
| `update_group` | W | ServiceNow의 기존 그룹을 업데이트합니다... | *(none)* |
| `update_user` | W | ServiceNow의 기존 사용자를 업데이트합니다... | *(none)* |
