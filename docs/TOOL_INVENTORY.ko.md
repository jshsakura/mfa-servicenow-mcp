# ServiceNow MCP - 도구 목록

이 문서는 유지 비용이 큰 행 단위 번역 인벤토리 대신, 현재 공개 도구 표면을 빠르게 확인할 수 있는 한국어 요약본입니다.

- 전체 등록 도구: **77**
- 기본 패키지 `standard`: **45**개 읽기 전용 도구
- 가장 넓은 개발 패키지 `full`: **66**개 패키지 정의 도구
- 현재 어떤 패키지에도 묶이지 않은 등록 도구: **11**개
- 정확한 행 단위 전체 인벤토리: [영문 기준 문서](./TOOL_INVENTORY.md)

## 패키지 요약

| 패키지 | 도구 수 | 설명 |
|---------|-------:|------|
| `none` | 0 | 비활성화 |
| `core` | 15 | 최소 읽기 전용 핵심 도구 |
| `standard` | 45 | 읽기 전용 safe mode **(기본값)** |
| `service_desk` | 46 | standard + 인시던트/변경 운영 쓰기 |
| `portal_developer` | 55 | standard + 포털/체인지셋/Script Include/로컬 동기화 개발 |
| `platform_developer` | 55 | standard + 워크플로우/플로우/스크립트/ITSM 쓰기 |
| `full` | 66 | 가장 넓은 패키지 표면 (번들 `manage_*` + 고급 운영 도구) |

## Flow Designer 표면

Flow Designer는 요청하신 축소 표면 기준으로 다음 5개 도구만 유지됩니다.

| 도구 | 읽기/쓰기 | 용도 |
|------|-----------|------|
| `list_flow_designers` | R | 플로우/서브플로우 목록 조회 |
| `get_flow_designer_detail` | R | 구조, 트리거, 실행 요약, data pill 추적, subflow tree 조회 |
| `get_flow_designer_executions` | R | 실행 이력/단건 실행 상세 조회 |
| `compare_flows` | R | 두 플로우 구조 비교 |
| `update_flow_designer` | W | 이름/설명/active 상태 수정 |

제거된 전용 도구들(예: trigger-by-table, full-detail, action/playbook/decision-table 전용 조회)은 `sn_query` 기반 조회로 대체되었습니다.

## 문서 운영 원칙

- 전체 행 단위 인벤토리는 영어 문서 `docs/TOOL_INVENTORY.md`를 기준으로 유지합니다.
- 한국어 문서는 패키지 선택, 현재 표면, 핵심 변경사항을 빠르게 확인하는 요약본으로 유지합니다.
- 패키지 수치나 Flow Designer 표면이 바뀌면 이 문서와 README/설치 문서를 함께 갱신합니다.
- `list_tool_packages`는 런타임에 동적으로 주입되므로 위 표의 YAML 패키지 카운트에는 포함하지 않습니다.
