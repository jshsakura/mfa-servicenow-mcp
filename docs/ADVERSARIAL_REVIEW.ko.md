# 적대적 리뷰 (Adversarial Review) — MFA ServiceNow MCP

> **리뷰 관점**: 회의적·적대적 (Red-team / Challenger)
> **대상**: `mfa-servicenow-mcp` v1.18.23
> **전제**: "안전하다"는 자기 서술(self-narrative)을 의심하고, **주장과 코드 현실의 괴리**를 잡는다.
> **라벨**: `AR` = Adversarial Finding. 강도 ■■■(치명)/■■(심각)/■(주의). 모든 주장에 `file:line` 증거 부착.

---

## 0. 한 줄 요약 (TL;DR)

이 프로젝트는 스스로를 "엔터프라이즈급 안전 설계"라고 선전하지만, **위협 모델을 잘못 세웠다**. 모든 "안전 장치"는 **LLM 자신이 우회할 수 있는 형태**로 되어 있어, 정작 이 시스템이 막아야 할 **프롬프트 주입(prompt injection)** 앞에서는 무력하다. 동시에 **실사용자 크리덴셜(재생 가능한 SSO 세션)이 평문으로 디스크에 영구 잔존**한다. "안전"은 마케팅이지 설계가 아니다.

---

## 1. 핵심 적발: "안전 장치"는 누구를 위한 것인가?

### AR-1 ■■■ `confirm='approve'` 게이트는 시큐어어 연극(security theater)이다

**주장**: README는 "Safe write confirmation with `confirm='approve'`" 라며 이것이 핵심 보안 계층이라고 한다.

**현실**: 게이트 구현은 문자열 동등 검사 하나다.

```python
# server.py:1340-1341
confirmation = str(arguments.get(CONFIRM_FIELD, "")).lower().strip()
if confirmation != CONFIRM_VALUE:  # CONFIRM_VALUE = "approve"
```

**문제**: `confirm` 인자를 채우는 주체는 **LLM 자신**이다. 이 시스템의 전체 위협 모델(LLM 구동 자동화)에서 공격자는 프롬프트를 통해 LLM에게 `confirm='approve'`를 넘기라고 지시하면 된다. 게이트가 보호하는 것은 **우발적 호출**뿐이며, **적대적 호출**에는 무방비다. README의 "Safe write" 표현은 사용자에게 거짓된 안심을 준다 — 오해상 소비자 기만에 가깝다.

**증거**: `server.py:1340-1347`, README "Safety Policy" 절 전체.

**권고**: "LLM 우발 호출 방지용 intent gate"로 정확히 명명. 보안 통제로 표현하지 말 것. 진짜 적대적 보호가 필요하다면 **out-of-band 인가**(별도 채널的人类 승인·TOTP)를 추가해야 한다.

### AR-2 ■■■ 모든 가드는 fail-open 이거나 우회 스위치를 가진다

**주장**: "다층 가드(G3/G6/G7/G8/G9)가 안전하지 않은 쓰기를 차단한다."

**현실**: 가드는 셀프서비스 우회투성이다:

| 가드 | 우회 방법 | 증거 |
|---|---|---|
| G3/G8 동시편집 | `SERVICENOW_CONCURRENT_EDIT_GUARD=off` | `write_guards.py:163` |
| 전체 가드 | `SERVICENOW_WRITE_GUARDS=off` | `write_guards.py:161` |
| G9 중복생성 | `allow_duplicate='true'` 인자 | `write_guards.py:153-154` |
| 드리프트 푸시 | `force=true` | README 표 |
| G6/G7 | LLM이 `confirm_publish='approve'` 추가 | `write_guards.py:191-192` |

**더 심각한 문제 — fail-open**: 사전 읽기가 실패하면 가드가 **조용히 통과**시킨다.

```
write_guards.py:36   "failed/denied existence read fails open (never blocks a create)"
write_guards.py:524  return  # fail-open if audit fetch fails
write_guards.py:674  return  # none found, or check couldn't run — fail-open
```

즉, **네트워크 장애나 ServiceNow 읽기 거부(권한 부족·일시적 5xx) 상황에서 안전 가드는 작동하지 않는다** — 정확히 가드가 필요한 순간에 사라진다. fail-open은 "정당한 쓰기를 막지 않는다"는 사용성 목표에는 부합하지만, 보안 목표와는 정면 충돌한다.

**권고**: 보안-민감 가드는 최소한 **fail-closed 옵션**을 제공하고(`SERVICENOW_WRITE_GUARDS_FAIL=closed`), fail-open 시 응답에 **가드가 작동하지 않았음을 명시**해 호출자가 알게 할 것.

---

## 2. 크리덴셜/세션 위생: 평문·영구·재생 가능

### AR-3 ■■■ SSO 세션(쿠키 DB)이 평문으로 디스크에 영구 잔존

**현실**: 인증 매니저는 두 가지를 디스크에 쓴다 — `session_<host>_<user>.json`(파싱된 쿠키)과 Playwright 프로파일 디렉터리(Chromium 쿠키 DB).

```python
# auth_manager.py:1554-1556  (주석)
#  its Chromium cookie DB is a replayable SSO session
```

코드 자신이 인정한다: 이 쿠키 DB는 **"재생 가능한 SSO 세션"**이다. 그런데:

1. **암호화 없음** — 평문 SQLite. 보호는 파일 퍼미션(0700)뿐.
2. **영구 잔존** — 코드가 직접 고백한다:

```
auth_manager.py:1751-1753
   the previous instance's `.lock` and `session_*.json` files persist forever
   because each manager only owns its own paths.
```

3. **정리 로직은 다른 인스턴스의 만료 파일만 지운다**(`auth_manager.py:1785`). 현재 인스턴스 세션은 "leave alone". 프로파일 디렉터리(쿠키 DB 포함)는 **아예 정리 대상이 아니다**.

**영향**: 노트북 분실·공유 호스트·백업 스냅숏·클라우드 동기화(Dropbox/iCloud) 중 하나라도 털리면, **공격자는 Okta/Entra ID SSO 세션을 그대로 재생**할 수 있다. MFA가 무력화된다 — MFA는 로그인 시점에만 작동하니까.

**권고**: 
- 세션/프로파일 **암호화 at rest** (OS 키체인 또는 사용자 비밀번호 유도 키).
- **TTL 기반 자동 파기**(세션 JSON뿐 아니라 프로파일 쿠키 DB도).
- 설치 시 `~/.mfa_servicenow_mcp/`가 클라우드 동기화 대상이면 경고.

---

## 3. "성숙한 코드"라는 서술에 대한 반박

### AR-4 ■■ 최근 커밋 16%가 `fix:` — 성숙도 과장

**증거**: 최근 50개 커밋 중 **8개(16%)**가 `fix:` 접두사.

```
8 / 50 = 16% fix ratio
```

버전 `1.18.23` = 마이너 18 + 패치 23. 커밋 메시지들을 보면 `v1.18.17`~`v1.18.23` 사이에 **"dirty-checkout protection", "lost-update guard", "clone remap self-check", "no ghost version rows"** 같은 정정 연속 — 이들은 **이미 출시된 기능의 결함 회수**다. "성숙한 코드베이스"라는 자기 서술과 맞지 않는다. 실상은 **활발히 수정되고 있는 베타**다.

**권고**: README 경고문("Built for personal use — use at your own risk")은 솔직하나, pyproject 분류자 `Development Status :: 4 - Beta`와 모순되게 "엔터프라이즈급" 암시를 품는 마케팅 어조를 조정할 것.

### AR-5 ■■ 테스트 201개 skip/xfail — "61K LOC 테스트"의 허상

**주장**: 보고서와 README가 "테스트 61K LOC, 166개 파일, TV > 1.3"으로 포괄성을 자랑.

**현실**: `tests/` 내 `skip`/`xfail`/`skipif` 참조가 **201건**. assertion 총 5,037개 중 일부는 단순 smoke(`assert resp`) 수준이다(85개 파일이 smoke성 검증). "LOC가 많다" ≠ "커버리지가 좋다". **건너뛴 테스트는 테스트가 아니다** — 오히려 "이 영역은 검증 못 함"이라는 부채 표지판이다.

**권고**: skip/xfail을 별도 인벤토리로 추적. 각 skip에 이유와 재활성화 조건 명시. CI에 "skip 감소 추세" 메트릭 노출.

### AR-6 ■■ `auth_manager.py` "동결" 정책은 기술 부채의 합법화

**주장 (CLAUDE.md)**: "이 파일은 동결 — 리팩터 금지, 버그 수정만. 불변성은 테스트로 고정."

**현실**: 이것은 **4,965 LOC 단일 파일의 복잡성을 해소하지 않겠다는 선언**이다. 근거("실서버·실브라우저 결합이라 CI가 못 잡는다")는 부분적으로 타당하나, **결론은 도끼다**:

- 신규 인증 플로우 추가 시 단일 파일이 병목 → 모든 변경이 거대 diff.
- "불변성 테스트로 고정"은 **테스트가 존재하는 불변성에만 유효** — 테스트되지 않은 모서리 동작은 동결하에 방치.
- "8판 패치 사가"를 근거로 드는데, 이는 오히려 **이 파일이 제대로 설계되지 않았음**을 입증한다(좋은 설계는 8번 다시 짜지 않는다).

**이것은 "안전"이 아니라 "무서워서 못 건드림"이다.** 동결 정책은 부채 상환을 거부하는 정치적 결정이다.

**권고**: 동결 해제 없이도 — (a) 순수 함수(파싱·시간계산·경로생성)는 부작용 없으므로 별도 모듈로 추출 허용, (b) 동결 범위를 "브라우저 드라이버 상호작용 함수"로 좁히고 나머지는 개방.

---

## 4. 공격 표면: 65개 툴 = 65개 벡터

### AR-7 ■ 툴 팽창과 쓰기 확장

**현실**: 65개 등록 툴, `full` 패키지는 "모든 도메인의 쓰기를 한 번에". 40개 툴 파일.

LLM 구동 시스템에서 **노출된 툴 수 = 공격 표면 크기**다. 프롬프트 주입 공격자에게 `full` 패키지는 "레코드 생성·삭제·플로우 게시·업데이트셋 커밋·사용자 관리·위키 게시"를 한 서버에서 전부 허용하는 것이다. 각 툴이 confirm 게이트(AR-1)와 우회 가능한 가드(AR-2)만으로 보호된다면, **공격자는 가장 파괴적인 툴을 골라 `confirm='approve'`와 함께 호출**하면 끝이다.

**권고**: 
- `full` 패키지를 **경고와 함께 비권장**하는 것(현재 방식)을 넘어, **호출당 파괴도(destructiveness) 를 기반으로 한 추가 게이트**(예: delete/publish 계열은 rate-limit 또는 out-of-band 승인) 추가.
- 각 쓰기 툴의 **취소 가능성(undoability)** 분류 — undo 불가능한 작업(delete workflow, publish)은 더 강한 인가.

---

## 5. 프라이버시·가시성: SOC 블라인드 스팟

### AR-8 ■ TLS 가장(impersonation) 기본 ON은 ServiceNow 관리자의 가시성을 뺏는다

**주장**: `curl_cffi` chrome 가장이 기본 ON이며 "JA3 봇 탐지를 우회"한다고 자랑.

**현실의 다른 면**: 이는 ServiceNow 인스턴스 관리자의 **봇/자동화 탐지와 보안 모니터링(SIEM/SOC)**을 무력화한다. 실제 브라우저와 바이트 단위로 동일한 TLS 핸드셰이크를 만들면, 관리자는 **LLM 구동 대량 쓰기 트래픽과 인간 사용자 트래픽을 구분할 수 없다**.

이것은 사용자(편의)에게는 이득이지만, **ServiceNow 인스턴스 소유자(종종 다른 조직)의 가시성을 일방적으로 훼손**한다. 공개 도구가 "탐지 우회"를 기본값으로 내장하는 것은 윤리적 경계가 모호하다.

**권고**: 기본 ON은 유지하되, README와 툴 응답에 **"이 트래픽은 봇 탐지를 통과하므로 인스턴스 관리자에게 보이지 않을 수 있음"** 명시. 기업 환경에서는 SOC와 합의 후 사용하라고 권고.

---

## 6. 기타 적발 (Minor)

### AR-9 ■ 광범위 예외 345건 — 오류 삼킴
`except Exception` 345건. 일부는 외부 경계로 정당하나, "로그만 하고 통과" 패턴이 **실패를 성공으로 위장**할 수 있다. 특히 fail-open 가드(AR-2)와 결합하면, 읽기 실패 → 예외 삼킴 → 가드 통과 → 쓰기 실행, 이라는 연쇄가 가능하다.

### AR-10 ■ `SECURITY.md` 버전 불일치 (GM-1 재확인)
`5.1.x/5.0.x/4.0.x` vs 실제 `1.18.x`. 공개 보안 정책 문서가 **거짓말**이다. 이것만으로도 보안 성숙도 의심에 충분하다.

### AR-11 ■ 다국어 README 6개국어 — 문서화 부피 vs 코드 감시 불균형
README/문서가 6개국어로 번역되는 동안, `SECURITY.md`는 기본 템플릿 그대로다. **우선순위가 뒤집혀 있다** — 마케팅(도달)에 자원을 쏟고 보안 기본기는 방치.

---

## 7. 결론: "안전"은 형용사가 아니라 동사여야 한다

이 프로젝트는 **기능적으로는 훌륭**하다. 그러나 "안전"을 **정적인 속성(우리는 안전한 설계를 했다)으로 취급**하지, **지속적 과정(위협 모델을 검증하고 가드를 시험한다)으로 취급**하지 않는다.

세 가지 근본적 갭:

1. **위협 모델 부재** — LLM 구동 시스템의 핵심 위협(프롬프트 주입)에 대해 `confirm` 게이트는 무의미하다(AR-1).
2. **fail-open 안전 장치** — 정작 필요한 순간(읽기 실패)에 가드가 사라진다(AR-2).
3. **크리덴셜 평문 영구 잔존** — MFA를 우회하는 재생 가능 세션이 보호 없이 디스크에 있다(AR-3).

이 세 가지가 해결되기 전까지, "엔터프라이즈급"이라는 수식어는 과장이다.

> **적대적 평가**: **기능 B+, 보안 C−, 위생(크리덴셜/테스트/부채) C.**
> 우발적 사용자에는 양호하지만, **적대적 환경(프롬프트 주입·멀티테넌트 호스트·분실 단말)에서는 신뢰할 수 없다.**

---

*— 적대적 리뷰 종료. 모든 주장은 인용된 `file:line`에서 검증 가능해야 한다. —*
