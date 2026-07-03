# 개선 계획서 — MFA ServiceNow MCP

> **문서 성격**: 네 건의 외부 검토(AGY 자동분석 · 정기 종합감사 · adversarial devil's-advocate · 적대적 red-team 리뷰)를
> 실제 소스와 대조 검증한 뒤, 실행 항목만 남겨 통합한 단일 계획서.
> **대상 버전**: `v1.18.23` · **작성일**: 2026-07-03 · **저장소**: `jshsakura/mfa-servicenow-mcp` (공개 OSS, Apache-2.0)
>
> 원본 검토 4건(`AGY_SECURITY_AND_IMPROVEMENT_PLAN.md`, `docs/AUDIT_REPORT.ko.md`, `adversarial_review.md`,
> `docs/ADVERSARIAL_REVIEW.ko.md`)의 내용은 본 문서로 통합됨. 개별 지적의 코드 라인 근거는 검증 완료.

---

## 0-A. 선행 이슈 대조 (#63 — 이미 처리된 범위)

이 적대적 리뷰들의 주제(fail-open·평문 크리덴셜·write-classification)는 **이슈 #63**
("Security hardening", CLOSED v1.18.13-17)이 6-angle 리뷰로 이미 상당 부분 처리했다.
중복을 피하려면 아래를 "완료된 선행 작업"으로 간주한다:

- **write-classification**: `scaffold_page` confirm/allow_writes 우회 차단, 분류 테이블을 `write_guards.py` 단일 소스화 + 스냅샷 테스트로 신규 쓰기툴 누락 CI 차단.
- **per-instance 크리덴셜**: `${ENV}` 간접참조로 평문 시크릿 제거, 부분참조 거부, 미해결 참조가 타 인스턴스 시크릿으로 폴백 금지.
- **fail-safe 방향**: 깨진 인스턴스는 startup 비치명화(config_error), 깨진 ACTIVE alias는 `allow_writes=false`로 **fail-CLOSED**.
- **파일 위생**: 캐시/프로파일 디렉토리 `0700` 강제(Chromium 쿠키 DB = replayable SSO).

**→ 새 리뷰의 진짜 잔여 갭** (이번에 반영): (1) **per-write 동시편집 가드의 fail-open**은 #63의 startup fail-closed와 별개로 남아 있음 → AR-2, (2) SECURITY.md는 #63 범위 밖 → GM-1, (3) confirm 게이트의 정직한 문서화 → AR-1.

---

## 0. 요약

- **코드 자체의 치명적 취약점은 발견되지 않음** — 명령 주입 0건, 하드코딩 시크릿 0건, 위험 역직렬화 미사용.
- 총 23개 지적(AGY 4 + 감사 11 + adversarial 8) 중 **실제 조치 가치가 있는 항목은 소수이며 대부분 문서/가시성 영역**.
- 세 검토의 코드 관련 지적은 **전부 이미 통제되었거나 전제 오류** — 특히 반복 제안된 "auth 모듈 분할"·"키링 연동"은 각각 FROZEN 정책 위반·헤드리스 크래시로 **명시 기각**.
- adversarial 리뷰의 유일한 코드 사실 주장("쓰기 가드가 클라이언트 레벨")은 **거짓** — `write_guards.py`가 `server.py`에서 호출돼 서버측 `PolicyViolation` raise로 강제됨.
- **즉시 조치 1건(GM-1: SECURITY.md 템플릿 방치)**만 명확한 실행 대상. adversarial 리뷰의 유효 잔여물(프롬프트 인젝션·RBAC 모델·curl_cffi 근거·air-gap)은 **GM-6 위협모델 문서로 흡수**.

| 지표 | 수치 | 비고 |
|---|---|---|
| 소스 LOC | 47,109 | — |
| 테스트 LOC | 61,271 | TV ratio > 1.3 |
| 테스트 파일 | 166 | — |
| 커버리지 게이트 | **80%** (`fail_under`, pyproject.toml:122) | ※ AGY 문서의 "93.5%"는 미검증 전파값 — 실제 게이트는 80% |
| 등록 툴 | 65 | — |
| 인증 모드 | 4 (browser/basic/oauth/api_key) | — |

---

## 1. 실행 대상 (Actionable)

### P0 — 즉시

#### [GM-1] `SECURITY.md`가 GitHub 기본 템플릿 그대로 — ✅ 반영 완료
- **팩트**: 지원 버전 테이블이 `5.1.x / 5.0.x / 4.0.x` — 실제 버전 `1.18.23`과 무관. 보고 채널·SLA 전무.
- **반영**: 버전 행을 `1.18.x`로 교체, GitHub Security Advisory 보고 경로 + SLA(ack 72h / 평가 7d) 명시, 신뢰모델 스코프 노트(confirm=intent gate, 세션 미암호화) 추가.

#### [AR-2] fail-open 동시편집 가드 — 옵트인 fail-closed — ✅ 반영 완료
- **팩트**: 동시편집 가드(G3/G8)는 사전 감사 읽기 실패 시 **조용히 통과**한다(`write_guards.py`, 설계상 명시). 네트워크 장애·권한부족·5xx 등 "가드가 정작 필요한 순간"에 사라진다.
- **반영**: `SERVICENOW_WRITE_GUARDS_FAIL=closed` 옵트인 도입. **읽기 자체가 실패한 경우만**(`server_now is None`으로 record-absent와 정밀 구분) 차단하도록 `_check_concurrent_edit`에 fail-closed 분기 추가. 기본(fail-open)은 불변. 테스트 4개 추가(fail-closed 차단 / record-absent 통과 / 기본 fail-open 유지).
- **주의 준수**: 기본 동작·사용성 계약 불변, 순수 additive. G9(중복생성)는 `_fetch_existing_by_name`이 read-fail과 not-found를 구분 못 해(신호 부재) 이번 범위에서 제외 — 후속 시 시그니처 변경 필요.

### P1 — 단기 (문서/가시성 중심)

#### [GM-6] 위협 모델 1장 문서화 (GM-1 연장 + adversarial 유효 잔여물 흡수)
- 크리덴셜 저장 위치(`~/.servicenow_mcp/session_*.json`, 0o600), 인증 흐름, 신뢰 경계를 다이어그램 1장으로. 공개 OSS 사용자의 "내 크리덴셜이 어디로 가나" 질문에 대한 답.
- **추가로 명시할 것** (adversarial 리뷰에서 유효하게 제기된 항목):
  - **[AR-1] confirm 게이트의 정직한 네이밍**: `confirm='approve'`는 서버측 강제이나 **인자를 채우는 주체가 LLM 자신**이라, 적대적 프롬프트 앞에선 보안통제가 아니라 "LLM 우발 호출 방지용 intent gate"다. README의 "Safe write" 표현을 이 수준으로 정확히 재명명. 진짜 적대적 보호가 필요하면 out-of-band 인가(별도 채널 인간 승인/TOTP)가 별도 과제.
  - **간접 프롬프트 인젝션**: LLM이 악성 소스 설명에 유도돼 파괴적 쓰기를 "정상 업데이트"로 포장할 수 있음 → G6/G7/읽기전용 기본값이 최대 폭발반경을 완화하나, 사용자는 confirm 프롬프트를 맹신하지 말 것.
  - **권한 모델**: 서버는 인증된 사용자 권한 그대로 동작하며 별도 서버측 RBAC를 두지 않음(모든 MCP 공통). 최소권한 계정 운용 권장.
  - **[AR-3] 세션 재생 위험 + 저비용 완화**: 프로파일 Chromium 쿠키 DB는 코드가 직접 "replayable SSO session"이라 인정(`auth_manager.py:1552`), 0700 퍼미션만 있고 암호화·TTL 파기 없음. **키링/암호화-at-rest는 헤드리스 리눅스 비호환으로 기각**하되, 저비용 완화는 채택 검토: ①`~/.servicenow_mcp/`가 클라우드 동기화(Dropbox/iCloud) 경로면 설치 시 경고, ②세션 JSON뿐 아니라 프로파일 쿠키 DB도 TTL 기반 자동 파기.
  - **curl_cffi TLS 가장**: 제3자 봇회피가 아니라 본인 인스턴스에 대한 브라우저-동등 트래픽임을 명시. `SERVICENOW_TLS_IMPERSONATE=off` 탈출구 안내(issue #37 근거). 멀티테넌트/타조직 인스턴스에선 SOC 가시성 영향([AR-8]) 고지.
  - **air-gap/프록시**: 오프라인/차단 환경 설치 절차 — `SERVICENOW_AUTO_INSTALL_CHROMIUM=off` + 사전 번들/수동 `playwright install` 경로.

#### [GM-4] 비루프백 바인딩 문서 강화
- **팩트**: `_default_http_allowed_hosts`가 `--http-host`에서 파생(cli.py:185). 코드 자체는 안전(`0.0.0.0`/`::` 비루프백 분류 정확).
- **조치**: 퍼블릭 바인딩 시 `--http-allowed-hosts`를 명시적 FQDN 목록으로 지정하라는 안내만 추가. **코드 변경 없음.**

#### [GM-10] 커버리지 게이트 단계 상향
- `fail_under = 80` → 85% 검토. **단 `auth_manager.py`(동결)는 제외 대상 명시** — 감사 보고서가 정확히 지적한 caveat 준수.

### P2 — 정기 감사 항목으로 편입 (저긴급)

| 항목 | 내용 | 처리 방침 |
|---|---|---|
| [GM-2] `except Exception` 345건 | 다수는 외부 경계 + 의도적 fail-open. | 신규 코드에서만 좁은 예외 + `logger.exception` 권장. 일괄 리팩터 X. |
| [GM-3] `auth_manager.py` 4,965 LOC 동결 | 동결은 유지. | **신규 인증 플로우는 별도 모듈**로 분리하는 예외 조항만 CLAUDE.md에 추가. 불변식 테스트는 area별 분산 유지(통합 X — 의도된 구조). |
| [GM-8] 의존성 상한 캡 | `mcp<2` 등 상한이 보안 패치 지연 소지. | 분기별 상한 재평가. |
| [GM-9] `# type: ignore` 12건 / mypy 관대 | `disallow_untyped_defs=false` 확인. | 신규 코드부터 점진 강화. |

---

## 2. 반영하지 않음 (검증 결과 — 오판·완화·중복)

각 항목은 코드 대조로 "조치 불필요" 확정. **코드 변경 시 회귀 리스크가 이득을 상회.**

| 원 지적 | 판정 | 근거 |
|---|---|---|
| **AGY-SEC-01** PID 재사용 락 교착 | ❌ 오판 | PID 생사 무관 **300초 하드 타임아웃**(auth_manager.py:1595) + **fail-open**(:1618) + `_wait_for_other_login` 180초 상한. 영구 교착 불가능. startup sweep의 age-무시(:1799)는 느린 MFA peer 락 보호용 **의도 설계**. |
| **AGY-SEC-02** 세션 평문 저장 | ❌ 완화됨 | 세션 `0o600`(:1701) + 디렉토리 `0o700`(:420). `~/.aws/credentials`·kubeconfig 동급 표준. **헤드리스 리눅스엔 키링 데몬 부재 → 연동 시 인증 모듈 크래시 리스크.** |
| **AGY-IMPR-02** Chromium 설치 지연 알림 | ❌ 이미 처리 | 데몬 스레드라 핸드셰이크 **비블로킹**(:1385). `_browser_setup_error`가 initialize-response에 "downloading…" 고지(:1416) + `logger.info` stderr(:1423). |
| **AGY-IMPR-01** 서킷 브레이커 프로세스 간 desync | ⚠️ 보류 | 카운터는 프로세스별 in-memory(맞음). 단 **로그인 락이 인증 복구를 1개씩 직렬화**해 lockout storm을 실질 완충. 공유 상태를 동결 파일에 추가하는 복잡도 대비 이득 미미 → 저우선 보류. |
| **GM-5** 크리덴셜 zeroize 부재 | ❌ 저ROI | teardown/zeroize 없음은 사실이나 **CPython은 불변 str/bytes를 신뢰성 있게 제로화 불가**(`del`은 메모리 스크럽 아님). 코드 조치는 theater. |
| **GM-7** `doctor` 서브커맨드 | ⚠️ 상당부분 존재 | `sn_health` 툴이 instance/profile/probe_path/세션인증 상태 이미 리포트(sn_api.py:1073). CLI 신설은 능력 중복. |
| **GM-11** isort만 정확 핀 | ❌ 전제 오류 | isort뿐 아니라 **ruff `v0.1.9`·mypy `v1.8.0` 등 모든 pre-commit 훅이 `rev:` 정확 핀**(pre-commit 표준 동작). "일관성 검토" 전제 성립 안 함. |
| **ADV** auth를 전략별로 모듈 분할 | ❌ 정책 위반 | CLAUDE.md가 명시 금지한 **FROZEN 정책 정면 위반**. 리팩터가 운영 장애를 낸 이력(프로브 8판)에 대한 방어를 무력화. |
| **ADV** 쓰기 가드가 "클라이언트 레벨" | ❌ 사실 오류 | `write_guards.py`가 `server.py`에서 호출돼 **서버측 `PolicyViolation` raise**. LLM이 문구 조작해도 서버가 거부. |
| **ADV** curl_cffi = 봇회피/SOC 위반 | ❌ 미스프레이밍 | 제3자 회피 아닌 **본인 인증 트래픽**. `TLS_IMPERSONATE=off` 탈출구 존재. arms-race 우려만 GM-6 문서로 흡수. |
| **ADV** 자동 드리프트 sync-check 신설 | ⚠️ 도구 존재·자동화는 의도적 미탑재 | `diff_local_component`(sync_tools.py:1193) 존재, CLAUDE.md가 "diff 먼저" 강제. startup 자동체크는 offline-first/near-0-token 설계상 의도적 배제. |
| **ADV** CI 번역 파이프라인(6 README) | ⚪ 과함 | drift 일반론은 사실이나 1인 OSS엔 과투자. 저우선. |
| **AR-4** "최근 커밋 16%가 fix → 미성숙" | ❌ 수치 오류 | 실제는 **18/50 = 36%**(리뷰가 과소집계). 게다가 v1.18.x는 의도된 보안 하드닝 스프린트(#63)라 높은 fix가 "베타"의 증거 아님 — 맥락 무시. |
| **AR-5** "테스트 201개 skip/xfail" | ❌ grep 아티팩트(20배 과장) | 실제 pytest skip/xfail 마커는 **10개**. "skip" 문자열 203회 중 ~192개는 `resume-skip` 워터마크 등 **기능 코드**. 논지는 맞으나 증거가 허위. |
| **AR-6** 동결 = 부채 상환 거부 | ⚠️ 의견 | "좋은 설계는 8번 안 짠다"는 glib — 8판은 설계결함이 아니라 인스턴스별 ACL 상이라는 실서버 발견. 순수함수 추출 제안은 GM-3에서 이미 부분 수용. FROZEN 정책은 유지. |
| **AR-7** 65툴 = 공격표면 / undoability 게이트 | ⚪ 저우선 유효 | delete/publish 계열 추가 인가는 아이디어로 기록. 현재 read-only 기본 + G7 이중확인이 최고 폭발반경은 이미 커버. |

---

## 3. 검증된 우수 설계 (유지·확산 대상)

외부 검토가 공통으로 지목한, 타 MCP 프로젝트가 참고할 만한 패턴. **변경 금지, 문서화 가치.**

### 지능형 응답 토큰 예산 — `utils/response_budget.py`
- 클라이언트(기본 25,000 토큰) 초과 시 로컬 파일 수납으로 LLM 맥락 상실 → 이를 서버가 사전 방지.
- `DEFAULT_BUDGET_BYTES = 75_000` 초과 시 대형 필드 동적 stubbing, `PREVIEW_CHARS = 240` 요약 + `_fetch` 재요청 힌트 제공.
- **레코드-백드(`sys_id` 보유) 값만 생략**, 계산값(diff 등)은 재요청 불가라 **통째 보존**(response_budget.py:12-14, 92-94).

### 다차원 쓰기 보호 — `policies/write_guards.py`
- **G3/G8** 동시편집 blind-write 차단(table+sys_id 명시 시에만, 보수적).
- **G6** `sys_hub_*` raw-write 차단 → `manage_flow_designer`(checkout/save) 강제(write_guards.py:166-186).
- **G7** publish-class는 `confirm_publish='approve'` 별도 명시 요구(:191).

### 인증 코드 동결(FROZEN) + 불변식 테스트 전략 — `auth/auth_manager.py`
- "CI 통과·운영 장애" 이력(프로브 경로 8판, 헤드리스-퍼스트 사가)에 대한 현실적 방어. 리팩터 대신 area별 불변식 테스트로 동작 고정. **동결 유지가 최선.**

### 보안 fail-closed 기본값
- 비루프백 HTTP + 토큰 누락 → 시작 거부 · 교차 인스턴스 푸시 원본 불일치 차단 · TLS 가장(JA3) 기본 ON(issue #37).

---

## 4. 결론 및 우선순위

| 우선순위 | 항목 | 조치 | 리스크 |
|---|---|---|---|
| **즉시** | GM-1 | SECURITY.md 버전·보고채널 현실화 | 0 |
| **즉시(코드)** | **AR-2** | fail-open 시 `guard_skipped` 가시화 + 옵트인 `WRITE_GUARDS_FAIL=closed` | 낮음(순수 추가) |
| 단기 | GM-6, GM-4, GM-10 | 위협모델 문서(AR-1 네이밍·AR-3 완화·RBAC·curl_cffi·air-gap 흡수) + 바인딩 안내 + 커버리지 상향 | 낮음 |
| 검토 | AR-3 완화 | 클라우드동기화 경고 + 프로파일 쿠키 DB TTL 파기 | 낮음 |
| 정기감사 | GM-2, GM-3, GM-8, GM-9, AR-7 | 신규코드 기준 점진 개선 | — |
| **반영 안 함** | AGY-SEC-01/02, IMPR-01/02, GM-5/7/11, ADV 전건, AR-4/5/6 | 오판·완화·중복·정책위반·수치오류 — 현 코드 유지 | 변경 시 회귀 |

> **종합**: 네 건의 외부 검토를 코드와 전수 대조했다. 앞선 세 건이 대부분 문서/가시성 갭이었던 반면,
> 네 번째 적대적 리뷰는 코드 사실로 **한 가지 실질 코드 개선(AR-2)**을 드러냈다 — fail-open 가드가
> 침묵으로 통과하면 광고된 "safe write"가 시스템 자신의 위협(LLM 자동화) 앞에 성립하지 않는다.
> 이는 기본 동작을 바꾸지 않고 **가시성 + 옵트인 fail-closed**로 정직하게 보완할 수 있다.
> 반복 제안된 "auth 모듈 분할"·"키링"은 각각 FROZEN 정책·헤드리스 호환성으로 기각.
> 적대적 리뷰의 성숙도 반박(AR-4/5)은 수치가 각각 과소·20배 과장이라 기각.
> 실질 실행 대상: **GM-1 + AR-2(즉시) → GM-6 위협모델 + AR-3 완화(단기)**로 수렴한다.

---

*통합 완료 — 원본 검토 4건은 본 문서로 대체됨.*
