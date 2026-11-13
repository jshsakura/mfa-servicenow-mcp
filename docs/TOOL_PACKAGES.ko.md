# 도구 패키지 — 고급 레퍼런스

> **대부분의 사용자는 이 페이지가 필요 없습니다.** 기본 패키지는 `standard`로, 읽기 전용이며 어떤 환경에서도 안전합니다.
> `standard`로 충분하지 않은 쓰기 도구가 필요할 때만 이 문서를 참고하세요.

---

## 패키지 선택 가이드

자신의 작업에 필요한 가장 좁은 패키지부터 시작하세요. 단계가 올라갈수록 더 많은 도메인의 쓰기 권한이 추가됩니다:

읽기 전용 — 어떤 환경에서도 안전, 쓰기 도구 없음:

| 패키지명 | 도구 수 | 최대 토큰 | 최대 (인스턴스 3개) | 사용 시기 |
| :--- | :---: | :---: | :---: | :--- |
| `core` | 12 | ~2.2K | ~2.7K | 최소 읽기 전용: 헬스체크, 스키마, 탐색, 핵심 조회만 |
| `standard` | 31 | ~7.4K | ~8.3K | **(기본값)** 인시던트/변경/포털/로그/소스 분석 읽기 전용 |
| `none` | 0 | 0 | 0 | 모든 도구를 의도적으로 비활성화 (테스트, 잠금 환경) |

애드온 — 범용이며 단독 패키지가 아닙니다. 어떤 패키지에든 쉼표로 붙여 씁니다 (`MCP_TOOL_PACKAGE=asset_manager,scripting`). ⚠️는 쓰기 가능:

| 애드온 | 도구 | 추가 토큰 | 용도 |
| :--- | :---: | :---: | :--- |
| `scripting` | 13 | +~4.6K | ⚠️ 서버 로직(Script Include, Business Rule, Scheduled Job, REST Message, Flow 조회), 업데이트 세트, XML 배포 |
| `office_files` | 2 | +~0.7K | Excel 통합문서(읽기·쓰기·양식 채우기), 레코드 첨부파일 |
| `debug_window` | 3 | +~1.2K | ⚠️ 공유 브라우저. `act_in_debug_window`는 저장 버튼도 누를 수 있음 |
| `source_sync` | 3 | +~0.9K | ⚠️ 서버 소스 다운로드, 비교, 반영 |
| `portal_design` | 10 | +~2.8K | ⚠️ 테마 다음 단계의 포털 디자인: 페이지 레이아웃과 인스턴스 CSS·옵션, 위젯·헤더/푸터 복사본, Workspace 리스트 — `itsm_developer,portal_design`용 |

⚠️ 쓰기 가능 — **고급 옵션**, 생성/수정/삭제 권한 부여:

| 패키지명 | 도구 수 | 최대 토큰 | 최대 (인스턴스 3개) | 사용 시기 |
| :--- | :---: | :---: | :---: | :--- |
| `service_desk` | 34 | ~8.3K | ~9.3K | ⚠️ 인시던트/변경 업데이트·종료가 필요한 서비스 데스크 담당자 |
| `portal_developer` | 53 | ~16.8K | ~18.6K | ⚠️ 위젯, 체인지셋, Script Include를 배포하는 포털 개발자 |
| `platform_developer` | 48 | ~13.7K | ~15.3K | ⚠️ 워크플로우, Flow Designer, 스크립트를 관리하는 플랫폼 엔지니어 |
| `full` | 74 | ~21.8K | ~24.2K | ⚠️ 가장 고급 — 모든 도메인의 쓰기 도구 전체를 동시에 (아래 경고 참고) |
| `itsm_developer` | 37 | ~11.3K | ~12.7K | ⚠️ 단독 ITSM 구성: 레코드 진단, 테이블 자동화 파악, 카탈로그·정책·알림 설정, 승인과 테스트 주문, 배정·승인 규칙과 선택지 목록, 포털 테마, 업데이트 세트나 XML로 배포. |
| `asset_manager` | 9 | ~1.2K | ~1.6K | ⚠️ 자재·자산·ITOM 업무용 최소 구성: 조회와, 인스턴스에서 먼저 검증하는 자산 쓰기(`manage_asset`). 필요하면 `scripting`, `office_files`, `debug_window`, `source_sync`를 쉼표로 추가 (`MCP_TOOL_PACKAGE=asset_manager,office_files`) |

> **최대 토큰** = 요청마다 해당 패키지의 툴 스키마가 모델 컨텍스트에 더하는 대략적 토큰 수(tiktoken cl100k_base 기준, 실제 Claude 토큰 수는 약간 다름). 좁은 패키지를 쓸수록 컨텍스트와 비용이 절약됩니다. **이 값은 최대치**이며 평소 비용이 아닙니다. 모든 툴 스키마를 처음부터 싣는 클라이언트만 이 전부를 냅니다. 툴 지연 로딩을 지원하는 클라이언트(예: Claude Code의 툴 검색)는 실제로 쓰는 툴의 스키마만 불러오므로, 요청당 실제 비용은 훨씬 적습니다. 도구 수는 패키지 구성원 수입니다. 모든 패키지에 `list_tool_packages`가 함께 붙고, 멀티 인스턴스 구성에서는 `list_instances`, `compare_instances`와 모든 툴의 `instance` 파라미터가 더해집니다 — 두 번째 토큰 열은 인스턴스 3개 기준 실측값입니다. 수치는 추정이 아니라 tiktoken 실측입니다(`uv run --no-sync --with tiktoken python scripts/measure_tool_tokens.py <package>`로 툴별 내역 확인).

`core`와 `none`을 제외한 모든 패키지는 `_extends`를 통해 `standard` 읽기 전용 도구를 상속합니다. 전체 상속 구조는 `config/tool_packages.yaml`을 참고하세요. `asset_manager`, `itsm_developer`와 애드온은 아무것도 상속하지 않습니다. 세션은 요청한 도구 값만 냅니다.

---

!!! danger "⚠️  `standard` 위의 패키지는 전부 쓰기 가능한 고급 옵션입니다"
    `service_desk`, `portal_developer`, `platform_developer`, `full` 모두 쓰기 도구를 활성화합니다 — 이 패키지로 실행된 AI 에이전트는 ServiceNow 레코드를 생성·수정·삭제할 수 있습니다. `full`은 **모든 도메인에서 동시에** 가능하므로(인시던트, 변경, 포털, Flow Designer, 워크플로우, 스크립트 등), 프롬프트 오해나 환각 한 번으로 여러 영역에서 동시에 파괴적인 변경이 발생할 수 있습니다.

    **`standard`에서 올라가기 전에 다음을 확인하세요:**
    - 활성화되는 모든 쓰기 도구를 파악한 경우 ([도구 목록](TOOL_INVENTORY.ko.md) 참고)
    - **비프로덕션** 또는 **샌드박스** 인스턴스에서 작업하거나 `allow_writes` 게이트를 걸어둔 경우
    - 의도치 않은 변경을 복구할 방법을 아는 숙련된 ServiceNow 개발자인 경우

    확실하지 않다면, 읽기 전용 기본값 `standard`에 머물고 작업에 꼭 필요할 때만 가장 좁은 쓰기 패키지로 올리세요.

---

## 패키지 설정 방법

환경변수로 설정 (권장):

```bash
MCP_TOOL_PACKAGE=standard
```

CLI 플래그로 설정:

```bash
servicenow-mcp --tool-package standard --instance-url ...
```

MCP 클라이언트 설정 파일:

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "standard"
  }
}
```

---

## 패키지에 없는 도구 호출 시

현재 패키지에 없는 도구를 호출하면 서버가 명확한 오류를 반환합니다:

```
Tool 'manage_widget' is not available in package 'standard'.
Enable package 'portal_developer' or higher to use this tool.
```

자동 실패 없이 LLM이 어느 패키지가 필요한지 정확히 알 수 있습니다.

---

## 전체 도구 목록

카테고리와 패키지별 전체 88개 도구 목록은 [도구 목록](TOOL_INVENTORY.ko.md)에서 확인하세요.
