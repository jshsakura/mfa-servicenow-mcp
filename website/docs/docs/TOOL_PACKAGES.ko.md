# 도구 패키지 — 고급 레퍼런스

> **대부분의 사용자는 이 페이지가 필요 없습니다.** 기본 패키지는 `standard`로, 읽기 전용이며 어떤 환경에서도 안전합니다.
> `standard`로 충분하지 않은 쓰기 도구가 필요할 때만 이 문서를 참고하세요.

---

## 패키지 선택 가이드

자신의 작업에 필요한 가장 좁은 패키지부터 시작하세요. 단계가 올라갈수록 더 많은 도메인의 쓰기 권한이 추가됩니다:

| 패키지명 | 도구 수 | 사용 시기 |
| :--- | :---: | :--- |
| `core` | 15 | 최소 읽기 전용: 헬스체크, 스키마, 탐색, 핵심 조회만 |
| `standard` | 45 | **(기본값)** 인시던트/변경/포털/로그/소스 분석 읽기 전용 |
| `service_desk` | 46 | 인시던트/변경 업데이트·종료가 필요한 서비스 데스크 담당자 |
| `portal_developer` | 55 | 위젯, 체인지셋, Script Include를 배포하는 포털 개발자 |
| `platform_developer` | 55 | 워크플로우, Flow Designer, 스크립트를 관리하는 플랫폼 엔지니어 |
| `full` | 66 | ⚠️ 아래 경고 참고 |
| `none` | 0 | 모든 도구를 의도적으로 비활성화 (테스트, 잠금 환경) |

`core`와 `none`을 제외한 모든 패키지는 `_extends`를 통해 `standard` 읽기 전용 도구를 상속합니다. 전체 상속 구조는 `config/tool_packages.yaml`을 참고하세요.

---

!!! danger "⚠️  `full` 패키지는 숙련된 사용자 전용입니다"
    `full` 패키지는 **모든 도메인의 쓰기 도구를 동시에 노출합니다** — 인시던트, 변경, 포털, Flow Designer, 워크플로우, 스크립트 등 전 영역.

    `full`로 실행된 AI 에이전트는 도메인 제약 없이 레코드를 생성·수정·삭제할 수 있습니다.
    프롬프트 오해나 환각 한 번으로 여러 영역에서 동시에 파괴적인 변경이 발생할 수 있습니다.

    **`full`은 다음 경우에만 사용하세요:**
    - 활성화되는 모든 쓰기 도구를 정확히 파악한 경우 ([도구 목록](TOOL_INVENTORY.ko.md) 참고)
    - **비프로덕션** 또는 **샌드박스** 인스턴스에서 작업하는 경우
    - 의도치 않은 변경을 복구할 방법을 아는 숙련된 ServiceNow 개발자인 경우

    확실하지 않다면, 도메인별 패키지(`portal_developer`, `platform_developer` 등)를 선택하세요.

---

## 패키지 설정 방법

환경변수로 설정 (권장):

```bash
MCP_TOOL_PACKAGE=portal_developer
```

CLI 플래그로 설정:

```bash
servicenow-mcp --tool-package portal_developer --instance-url ...
```

MCP 클라이언트 설정 파일:

```json
{
  "env": {
    "MCP_TOOL_PACKAGE": "portal_developer"
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

카테고리와 패키지별 전체 77개 도구 목록은 [도구 목록](TOOL_INVENTORY.ko.md)에서 확인하세요.
