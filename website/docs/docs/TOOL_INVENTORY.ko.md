# ServiceNow MCP - 도구 목록

이 페이지는 현재 도구 표면을 빠르게 확인하기 위한 웹 요약본입니다.

- 전체 등록 도구: **151**
- 기본 패키지 `standard`: **36**개 읽기 전용 도구
- 가장 넓은 개발 패키지 `full`: **101**개 도구
- 전체 행 단위 기준 인벤토리: 저장소의 `docs/TOOL_INVENTORY.md`

## 패키지 요약

| 패키지 | 도구 수 | 설명 |
|---------|-------:|------|
| `none` | 0 | 비활성화 |
| `standard` | 36 | 읽기 전용 safe mode **(기본값)** |
| `service_desk` | 46 | standard + 인시던트/변경관리 쓰기 |
| `portal_developer` | 84 | standard + 포털/소스/체인지셋 개발 |
| `platform_developer` | 77 | standard + 워크플로우/플로우/스크립트/ITSM 쓰기 |
| `agile` | 51 | standard + Epic/Story/Scrum/Project PPM |
| `admin` | 61 | standard + 사용자/지식베이스/카탈로그 관리 |
| `full` | 101 | 통합 개발자 패키지 (Agile PPM/Admin 제외) |

## Flow Designer 표면

Flow Designer는 현재 다음 5개 도구로 정리되어 있습니다.

| 도구 | 읽기/쓰기 | 용도 |
|------|-----------|------|
| `list_flow_designers` | R | 플로우/서브플로우 목록 조회 |
| `get_flow_designer_detail` | R | 구조, 트리거, 실행 요약, data pill 추적, subflow tree 조회 |
| `get_flow_designer_executions` | R | 실행 이력/단건 실행 상세 조회 |
| `compare_flows` | R | 두 플로우 구조 비교 |
| `update_flow_designer` | W | 이름/설명/active 상태 수정 |

공개 표면에서 제거된 Flow Designer 전용 조회 도구는 필요한 경우 `sn_query` 기반 조회로 대체합니다.

## 유지보수 원칙

웹 문서는 드리프트를 줄이기 위해 요약본으로 유지합니다. 카테고리별 전체 도구 행렬과 상세 패키지 소속은 저장소 기준 문서 `docs/TOOL_INVENTORY.md`를 확인하세요.
