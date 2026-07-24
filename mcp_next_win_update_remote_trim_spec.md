# 다음 한 방 — `update_remote_from_local` 성공 payload 트림 (구현 스펙)

*작성 2026-07-24 · 근거 코퍼스: 12,936콜 / 출력 8.38M 토큰 (tiktoken cl100k)*
*상위 계획: `mcp_token_accounting_and_tightening_plan.md` §3 T1 / 조사 로그: `mcp_deep_research_token_optimization.md`*

## 0. 한 줄 요약
`update_remote_from_local`의 **성공 응답**이 매번 의례적인 봉투(risk 산문·에코·절대경로)를
반복해 실어 보낸다. 이를 compact ack로 줄이면 **549K 토큰(출력 총량의 6.6%)** 절감.
**남은 단일 최대 건이며, 난이도 低·리스크 低.**

## 1. 왜 이게 제일 큰가 (실측)
| 지표 | 값 |
|---|--:|
| `update_remote_from_local` 총 출력 | **864,373 토큰** (전체의 10.3%, 툴 중 3위) |
| 콜 수 | 2,651 |
| 그중 **성공** 응답 | 2,198콜 / **659,557 토큰** (평균 278) |
| 실패·충돌 응답 | 222콜 / 188K (**건드리지 않음** — 디버깅에 필요) |
| 트림 후 추정 | **110,665 토큰** → **-548,892 (-83.2%)** |

핵심: 이 툴은 **본문을 반환하지 않는다**(파일은 디스크에). 그런데도 성공 1건당 278토큰이
나가는 건 전부 **메타/의례 봉투**다. 즉 정보가 아니라 포장을 줄이는 것이라
**under-fetch 위험이 0**이다(호출자가 방금 보낸 것을 되돌려주는 에코 제거).

## 2. 현재 응답 구조

### 2-A. 코드에서 직접 확인한 것 ✅
`update_remote_from_local` 말미의 finalize 블록(성공 경로에서만 도달):
```
result["success"]        = True
result["landed"]         = True | "unverified"     # 쓰기후 재읽기 확인 여부
result["target_instance"]= active                   # 어느 인스턴스에 착지했나
result["risk"]           = risk                     # ← 트림 대상(아래)
result["local_sync"]     = {"pushed_from": str(path),        # ← 절대경로
                            "fields_pushed": [...],
                            "sync_meta_updated": True}
result["update_set_warning"] = ...  # 조건부 (Default/전환 감지)
result["origin_unverified"]  = ...  # 조건부
```
`result`는 함수 앞부분에서 이미 채워진 상태로 여기 도달한다(= 위 목록이 전부가 아님).

### 2-B. 로그에서 관측된 비대 요인 ⚠️ *구현 시 코드에서 재확인 필요*
실제 반환 JSON을 분석한 결과 아래가 성공 payload를 부풀리고 있었다. 다만 **나는
`sync_tools.py`에서 이 키들의 리터럴을 grep으로 확인하지 못했다**(중첩이거나 다른
경로에서 합쳐질 수 있음). **추정으로 지우지 말고, 아래 §4 절차로 실제 payload를 떠서
확인한 뒤 지울 것.**
- `risk` 블록: **같은 문장이 `risk.message`(산문)와 `risk.factors`(패러프레이즈)에 중복**
- `validation` 에코 — 호출자가 방금 보낸 입력의 되돌림
- `local_sync.pushed_from` — 로컬 **절대경로** 전체
- `instance_target` — 상세 블록 (스칼라 `target_instance`와 중복)
- `update_set_context` — 상세 블록

## 3. 목표 형태

**남길 것 (계약·안전 신호 — 절대 제거 금지)**
| 키 | 이유 |
|---|---|
| `success` | 결과 판정 |
| `landed` (`True`/`"unverified"`) | 낙관적 성공과 **검증된 착지**를 구분하는 핵심 신호 |
| `target_instance` | "어디에 썼나"는 멀티인스턴스 안전 서사의 근간 — 암묵적이면 안 됨 |
| `sys_id`, `fields_pushed` | 후속 작업의 핸들 |
| `update_set_warning` (조건부) | 배송 실패(Default 캡처)를 알리는 유일한 신호 |
| `origin_unverified` (조건부) | 출처 미검증 경고 |

**추가할 스칼라 (블록 대체)**
- `risk_level` — `risk` 블록의 등급만
- `change_ratio` — 변경 비율 수치만

**버릴 것**
- `risk` 산문 전체(`message`/`factors` 중복) → 위 스칼라 2개로 대체
- `validation` 에코
- `local_sync.pushed_from` 절대경로 → 제거하거나 basename만
- `instance_target` / `update_set_context` 상세 블록 (스칼라·warning으로 충분)

**결과 shape (목표)**
```json
{"success": true, "landed": true, "target_instance": "<alias>",
 "sys_id": "...", "fields_pushed": ["..."],
 "risk_level": "low", "change_ratio": 0.12,
 "update_set_warning": {...},      // 있을 때만
 "origin_unverified": "..."}       // 있을 때만
```

## 4. 구현 절차
1. **실제 payload를 먼저 뜬다.** 성공 push 1건의 반환 JSON을 그대로 덤프해
   §2-B의 키가 현재 코드에 실제로 있는지 확인(있는 것만 지운다).
2. finalize 블록에서 위 §3대로 조립을 바꾼다. **성공 경로에서만.**
3. **에러/충돌 경로는 그대로 둔다** — `risk` 상세, 충돌 사유, 3-way 정보는 디버깅에
   필요하고 빈도도 낮다(222콜/188K).
4. 테스트 동반 수정: `tests/test_sync_tools.py`에서 트림 대상 키를 단언하는 곳을 찾아
   조정한다.
   ```
   grep -nE '"(risk|validation|local_sync|pushed_from|instance_target|update_set_context)"' tests/test_sync_tools.py
   ```
   `success`/`landed`/`target_instance`/`update_set_warning` 단언은 **유지**돼야 한다.
5. `pytest tests/ -x` 통과 후 커밋. (릴리즈로 낼 거면 patch bump + 태그 동시 푸시.)

## 5. 검증
트림 전후로 동일한 성공 push의 반환 JSON을 tiktoken으로 재어 **평균 278 → 약 47토큰**
(-83%) 수준인지 확인. 크게 못 미치면 §2-B에서 실제로 안 지워진 블록이 남아 있다는 뜻.

## 6. 주의 (이 작업의 경계)
- 이 트림은 **정보가 아니라 포장**을 줄이는 것. 안전 신호(`landed`,
  `target_instance`, `update_set_warning`)를 같이 지우면 **멀티인스턴스/업데이트셋
  안전 서사가 깨진다** — 토큰보다 비싼 손실이다.
- 워크로드 편향 주의: 근거 코퍼스는 sync 중심이라 이 항목의 비중이 크게 잡힌다.
  read 위주 사용에서는 상대 비중이 낮아진다(그래도 절감 자체는 유효).
