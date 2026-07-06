# 멀티세션 개선목록 — 2026-07-05 로그 분석

근거 로그: `~/.mfa_servicenow_mcp/servicenow-mcp_<dev-instance>.log{,.1,.2}` (7/5 전체, 약 18MB).
당일 상황: Claude 세션 다수(서버 프로세스 재시작 17회+), 인스턴스 3개(dev/test/prod)를
한 프로세스에서 프로필 라우팅으로 오가며 작업.

당일 집계:
- `auth_event=login.start` **53회** (dev 23 / test 18 / prod 12)
- `login.poll.confirmed` (수동 브라우저 로그인 완료) **25회**
- `login.headless.mfa_detected` (헤드리스 실패 → 비저블 창) **22회**
- `profile.restore.rejected` (캐시 세션 401 거부) **29회**
- 인스턴스 미스매치 에러 **12회** (17:48~18:46, 같은 에러 반복)
- `download_app_sources` 호출 32회 (실패 0 — 대부분 백그라운드 폴링 재호출)

이미 커밋으로 커버된 것: fe3bede(widget_ids 다운로드가 엉뚱한 위젯 반환 — "소스를
못 받았다"의 실체 중 하나), 220d866(global→profile 자격증명 상속 — 설정 헤멤 일부),
1b043b2(G10 세션 아이덴티티 가드).

---

## ✅ P1-1. 세션 복원이 사실상 매번 죽어 있음 → 재로그인 폭풍 (v1.18.45 완료)

**적용**: `auth/_keepalive.py` — 실제 툴 활동이 있는 동안(기본 6h 한도) 5분 주기
경량 프로브로 서버 세션 유지. 절대 브라우저를 띄우지 않음(거부 시 로그만 남기고
다음 실제 호출의 self-heal에 위임). 기본 ON, `SERVICENOW_SESSION_KEEPALIVE=off`
옵트아웃. `mfa_detected` 이벤트에 `mfa_remembered_cookie_valid` 필드 추가 —
다음에 재발하면 쿠키 만료 vs 인스턴스 정책 구분 가능.
`tests/test_session_keepalive.py`에 invariant 14건 고정.

**증상**: 새 MCP 프로세스가 뜰 때마다 restore probe가 401 (29회). MFA 기억 쿠키
(`glide_mfa_remembered_browser`)가 있는데도 헤드리스 로그인에서 MFA가 22회나
재검출되어 비저블 창으로 전환 → 사용자가 하루 25번 수동 로그인.

**분석 포인트**:
- Claude 세션 사이 간격(30분+)마다 서버측 idle timeout으로 세션이 죽는 것으로 보임.
  클라이언트 sliding TTL은 있으나 **서버 세션을 살려두는 keep-alive가 없음**.
- MFA 기억 쿠키가 왜 MFA 스킵으로 이어지지 않는지 별도 확인 필요
  (쿠키 만료? 인스턴스 정책? 헤드리스 UA 차이?).

**개선안**: (a) 활성 프로세스가 있는 동안 저비용 keep-alive 핑(예: 5분 주기
`sys_user_preference` GET)으로 서버 세션 유지 — 옵트인 env로, AuthManager FROZEN
정책에 맞춰 최소 diff. (b) MFA 재검출 원인 로그 보강(`mfa_detected` 시 remembered
쿠키 존재/만료 여부를 함께 기록).

## ✅ P1-2. MFA 코드 입력 중 90초 타임아웃으로 창이 닫힘 (v1.18.45 완료)

**적용**: `_login_poll_should_keep_waiting()` (`_url_predicates.py`) — 비저블
창이 로그인/MFA 페이지에 있는 동안엔 budget 만료 후에도 대기 연장, 하드캡
`VISIBLE_AUTH_PAGE_HARD_CAP_MS`(5분)로 walk-away 방지. 헤드리스는 절대 연장 안 함.
연장 시 `login.poll.extended_on_auth_page` 이벤트 기록. invariant 테스트 3건 추가.

**증상**: 17:08 — URL이 `validate_multifactor_auth_code.do`(사용자가 TOTP 입력 중)인
상태에서 `login.poll.timeout` → "Browser was closed by user"로 오분류 → 15초 쿨다운 →
직후 툴 호출 실패("Browser session expired").

**개선안**: 폴링 URL이 MFA/로그인 검증 페이지면 타임아웃 대폭 연장(또는 진행 중으로
간주해 리셋). 타임아웃을 user-close로 분류하지 않기(쿨다운 정책이 달라져야 함).
invariant 테스트 추가 방식으로 진행(FROZEN 정책의 공인 루트).

## P2-1. 인스턴스 미스매치 에러를 LLM이 학습 못 하고 12연타

**증상**: dev에서 받은 로컬 트리를 active=test/prod 상태에서 diff → 차단 에러가
1시간 동안 12회 반복. 에러 문구에 해결법(`instance=<alias>`)이 있지만 문장 뒤쪽에
있어 LLM이 계속 놓침.

**개선안**: (a) read/diff는 로컬 파일에 기록된 origin 인스턴스로 **자동 라우팅**
(읽기라 안전; 차단은 write에만 유지) — 근본 해결. (b) 최소한 에러 첫 문장을
"Retry with instance='<alias>'"로 시작하게 재배치.

## P3-1. 종료 시 BrokenPipeError를 ERROR로 기록

클라이언트(Claude 세션)가 먼저 끊기면 stdio flush에서 BrokenPipe → "Unexpected
error starting or running server" ERROR + 풀 트레이스백. 멀티세션에선 세션 닫을
때마다 발생하는 정상 종료 노이즈. → BrokenPipe/ClosedResource는 INFO "client
disconnected"로 다운그레이드.

## P3-2. 플레이스홀더 자격증명으로 실제 프로필 생성됨

`profile_<prod-instance>_REPLACE_WITH_PROD_USERNAME/` 디렉토리가 실제로 생성됨(7/2).
설정 템플릿의 placeholder가 치환 안 된 채로 로그인 시도까지 감. → username/password가
`REPLACE_WITH*`, 미확장 `${VAR}` 패턴이면 fail-fast + 명확한 에러.

## P3-3. 백그라운드 다운로드 폴링 폭풍 (토큰 낭비)

17:25~17:29에 같은 args로 9회 재호출(폴링). 매 호출이 풀 인자 echo + 진행 로그.
→ 응답에 `next_poll_after_s`(예: ETA 기반) 힌트 추가, 폴링 응답은 stages/파일 수만
담은 경량 포맷으로. (실패는 아니고 비용 문제.)

## P3-4. 멀티프로세스 로그 관측성: PID 없음 + 로테이션 레이스

- 모든 프로세스(호스트 3개 트래픽 포함)가 기본 인스턴스명 파일 하나에 기록,
  라인에 PID가 없어 프로세스 구분 불가.
- 증거: `.log.1`이 12:11~12:59 커버인데 메인 `.log`가 12:53 시작 — 구간 중첩 =
  RotatingFileHandler를 여러 프로세스가 독립 로테이션(유실 위험).
→ 로그 포맷에 `pid` 추가(1줄 diff), 로테이션은 프로세스별 파일명(`.<pid>`) 또는
  로테이션 없는 date-suffix 방식 검토.

## P3-5. (작업 중 발견) 테스트 flaky 2건

- ✅ `test_workflow_tools_coverage.py::test_partial_failure` — 병렬 reorder의
  공유 `side_effect` 리스트가 스레드 순서로 소비되어 순서 의존 실패. URL 키잉으로
  결정적으로 수정(v1.18.45).
- ⬜ `tests/test_source_download_tools.py` — 파일 전체 실행 시 실행마다 다른
  테스트가 실패(`test_ui_page_multi_field_export`,
  `test_unqualified_name_collision_warns_and_keeps_first` 등). 클린 트리에서도
  재현되는 기존 순서 의존 flaky. 원인 미조사.

## P3-6. batch_get 서브요청 body 파싱 실패 2건

18시경 `batch_get: sub-request 2/3 body unparsable: unexpected character` —
Batch API 응답에 JSON 아닌 body(HTML 에러 추정)가 섞임. 현재는 WARNING 후 진행.
→ unparsable일 때 body 앞 200자를 DEBUG로 남겨 원인 식별 가능하게.

---

### 우선순위 요약
| 순위 | 항목 | 효과 |
|---|---|---|
| P1-1 | 서버 세션 keep-alive + MFA 재검출 원인 로깅 | 하루 25회 수동 로그인 → 수 회로 |
| P1-2 | MFA 입력 중 타임아웃 방지 | 로그인 실패/쿨다운 연쇄 제거 |
| P2-1 | read/diff origin 자동 라우팅 | 미스매치 12연타 같은 LLM 루프 제거 |
| P3-* | 종료 노이즈, placeholder 검증, 폴링 힌트, PID 로그, batch 디버그 | 관측성/비용 |
