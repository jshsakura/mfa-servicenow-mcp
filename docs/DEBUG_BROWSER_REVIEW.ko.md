# ServiceNow MCP 디버그 브라우저(Debug Browser) 적대적 리뷰 및 개선 사항

본 문서는 현재 ServiceNow MCP에 구현된 디버그 브라우저(`debug_browser`) 기능(`open_debug_window`, `inspect_debug_window`, `act_in_debug_window`)의 아키텍처와 설계 측면에서 발견되는 취약점(Adversarial Review) 및 이를 해결하기 위한 개선 사항(Improvement Plan)을 정리한 내용입니다.

## 🚨 적대적 리뷰 (Adversarial Review)

### 1. 전역 공유 상태로 인한 "충돌(Chaos)" 및 동시성 문제
* **문제점:** 디버그 브라우저는 기본적으로 단일 창을 여러 세션(MCP 내부 세션 및 화면을 보는 사용자)이 공유하는 구조입니다.
* **취약성:** 다중 에이전트가 동시에 디버깅을 시도하거나, 사용자가 브라우저를 조작하는 도중에 `act_in_debug_window`가 실행되면 컨텍스트 오염이 발생합니다. A 세션이 Impersonation(사용자 가장)을 켜고 B 세션이 그것을 모른 채 작업을 수행하면 심각한 데이터 오류나 권한 탈취로 이어질 수 있습니다.

### 2. 과도하고 파편화된 승인(Approval) 게이트
* **문제점:** 서버 사이드 스크립트를 실행하기 위해 `confirm='approve'`, `confirm_eval='approve'`, `confirm_script_exec='approve'` 등 다중 승인 플래그를 요구합니다.
* **취약성:** 보안을 위한 설계라지만 개발자 경험(DX)을 크게 저해합니다. 모델이 코드를 실행하려 할 때마다 수많은 권한 플래그를 정확히 일치시켜야 하며, 하나라도 누락되면 전체 배치가 취소됩니다. 이는 자동화를 방해하는 불필요한 마찰(Friction)로 작용합니다.

### 3. 불안정한 상태 동기화 및 부수 효과(Side-effects)
* **문제점:** 입력 폼에 저장되지 않은 데이터가 있을 때(`blocked_by_unsaved_input`), 기존 탭을 덮어쓰지 못하고 강제로 새 탭을 열어버리는 로직(`new_tab=True` 우회)이 있습니다.
* **취약성:** 디버깅 세션이 길어지면 수십 개의 새 탭이 열리며 메모리 누수가 발생하거나 타겟팅할 탭을 잃어버리는 '탭 지옥'에 빠질 수 있습니다. 또한 `since_last=True` 방식의 이벤트 폴링은 다중 탭 환경에서 이벤트를 유실하거나 다른 탭의 결과와 섞일 위험이 높습니다.

### 4. 느슨한 생명주기(Lifecycle) 관리
* **문제점:** `reap_idle_windows`를 통해 유휴 창을 정리하지만, 명시적인 "초기화(Teardown / Reset)" 도구가 부족합니다.
* **취약성:** 테스트를 완전히 백지 상태에서 시작하고 싶어도 캐시, 세션 쿠키, Impersonation 마커 등이 그대로 남아있어 테스트의 멱등성(Idempotency)을 보장하기 어렵습니다.

---

## 💡 개선 사항 (Improvement Plan)

### 1. 브라우저 컨텍스트 격리 (Context Isolation) 지원
* **개선안:** 단일 글로벌 윈도우 대신 Playwright의 **Browser Context**를 활용하여 요청 세션마다 격리된 샌드박스 환경을 제공해야 합니다.
* **효과:** 각 MCP 세션이 고유한 쿠키와 세션을 가지므로 Impersonation이나 로그인 상태가 서로 간섭하지 않으며, 동시 다발적인 디버깅이 가능해집니다. 시각적 공유가 필요한 경우에만 명시적으로 `shared=True` 옵션을 받도록 변경합니다.

### 2. 선언적 어설션(Declarative Assertions) 도입
* **개선안:** 현재는 `act`로 동작을 수행한 뒤 다시 `inspect`로 DOM의 변화를 읽어오는 명령형(Imperative) 방식입니다. 이를 개선하여 `act_in_debug_window` 파라미터에 `expect` 개념을 추가합니다.
  * *예시:* `{"action": "click", "selector": "#save", "expect_visible": ".success-msg"}`
* **효과:** 에이전트가 두 번 호출(Tool Call)할 필요 없이 동작과 검증을 원자적(Atomic)으로 수행할 수 있어 디버깅 속도와 안정성이 크게 향상됩니다.

### 3. 권한 증명(Auth/Confirm) 파이프라인 단일화
* **개선안:** 여러 개로 쪼개져 있는 `confirm_*` 파라미터를 하나의 명시적인 `SecurityContext` 객체 또는 단일 `intent_level`로 통합합니다.
* **효과:** "read", "write", "execute_script" 등의 직관적인 열거형(Enum)으로 관리하여, 모델이 불필요하게 문자열('approve')을 여러 변수에 복사&붙여넣기 하는 구조적 에러를 줄일 수 있습니다.

### 4. 명시적인 Session Reset 도구 추가
* **개선안:** 캐시 비우기, 모든 탭 닫기, Impersonation 즉시 해제, 쿠키 삭제 등을 한 번에 수행하는 `reset_debug_window` 도구 또는 `act_in_debug_window(action="reset")` 기능을 추가합니다.
* **효과:** 테스트 스크립트 실행 전후에 환경을 일괄 정리하여 테스트의 신뢰성과 멱등성을 보장할 수 있습니다. 탭 누수 문제도 함께 해결됩니다.
