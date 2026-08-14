# MCP 토큰 회계 & 조임 계획 (Accounting + Tightening)

*측정 기준일: 2026-07-24 · 수치는 이 시점 코퍼스 기준이며 사용 패턴이 바뀌면 재측정 필요*

## 재계측 라운드 2 (2026-08-14, 7/25 이후 세션 18개 · 181콜 · ~56K tok)

코퍼스가 작아(56K) %는 참고치. 이전 라운드 완료분은 실현 확인됨 — sn_query 평균
196tok(컬럼형 동작), update_remote 성공 ack 85~91tok(트림 동작). 새로 잡힌 것 2건,
둘 다 **무손실**(정보 손실 0)이라 §T7 기준 충족:

| 발견 | 실측 | 조치 (v1.24.20) |
|---|---|---|
| `sn_schema`가 코퍼스 1위(22%, 단건 최대 4.2K) — `sysparm_display_value=true`가 `internal_type`/`reference`를 `{display_value, link}` 객체로 만들어 필드당 ~110자 `sys_glide_object` URL이 실림 | 6콜 12.5K tok | raw 값으로 전환(라이브 검증: `boolean`/`sys_user_group` 평문) — 응답 ~55%↓ **+ 정보 개선**(테이블 라벨 대신 실제 테이블명). 빈 `reference:""`도 키 생략(의미 동일). dict 응답 방어 `_plain()` 유지 |
| 푸시 게이트 거절 응답(`CROSS_INSTANCE_UNREVIEWED`/`CONFLICT*`)이 `risk['message']`를 톱레벨 `message`에 임베드하고 `risk` 딕셔너리에 같은 산문을 통째로 반복 (~350tok/건). CROSS_INSTANCE 경로는 `_compute_field_diffs`도 2회 계산 | 단건 1.6~1.7K tok | `_risk_without_duplicate_message()` — **포함 검증된 dedup**(임베드 안 된 경로는 산문 유지, unanchored 분기·FORCE_CONFIRM_STALE은 그대로). diff 1회 계산 재사용 |
| 목 fixture는 처음부터 평문 문자열이라 dict 실서버 형상을 못 잡았음 — §대전제 "구현≠실현"에 이어 **규칙 7의 실사례 추가** | — | 실서버 형상(dict) fixture 테스트로 핀 |

안 한 것(근거): `sn_health` 세션당 중복 4~5콜(183tok/콜)은 라이브 안전신호라 캐시 부적합;
`inspect_debug_window` 헤더 반복(~25tok/콜)은 prod-창 사고를 잡은 그 신호라 유지;
동일입력 재푸시(#5)는 여전히 호출자 행동 문제.

> 근거: 실측 코퍼스 **12,936콜 / 출력 8.38M 토큰**(tiktoken cl100k, 620 트랜스크립트
> 549MB). 상세 조사·적대검수는 `mcp_deep_research_token_optimization.md` 참조.
> 이 문서는 **회계(얼마)** + **다음 조임(더)** 만 압축.

## ⚠️ 대전제 (착각 방지)
- **%는 전부 출력토큰(8.38M) 기준.** 입력/스키마 축(요청당 ~5K·캐시)은 **이미 종료** — 더 없음.
- 코퍼스는 **유지보수자 sync-편향**(update+diff+download+flow=48% 토큰). 코덱스 read-mostly면
  랭킹 뒤집힘 → **#2·#3 둘 다** 해야 양쪽 커버.
- **구현 ≠ 실현.** 스펙만 있으면 실현 0.
- **배포 ≠ 실현 (재시작 지연).** MCP 서버는 장수 프로세스라 핫리로드가 없다. 배포일
  로그 6세션 중 5세션이 **커밋 이후에도 구 모듈로 계속** 돌았다(09:10에 뜬 프로세스가
  17:12 커밋을 못 봄 → 그날 컬럼형 채택률 0%). 어떤 최적화든 클라이언트 재시작
  전까지 그 세션의 실현은 0이다. 릴리스 직후 측정은 이 지연을 빼고 읽을 것.
- **선택/추론 비용은 미측정**(정적으로 못 잼) — eval 하네스 필요.
- **under-fetch 금지**: 필드 누락→재쿼리(왕복)는 절감이 아니라 손해. 안전한 절감은
  fetch한 걸 안 버리는 것뿐(캐시=동일본문 / 컬럼형=쿼리필드 재인코딩 / 트림=에코 제거).

---

## 1. 회계 — 얼마 절감되나

| 항목 | 잠재 | %(출력) | 상태 | 지금 실현 |
|---|--:|--:|---|--:|
| #1 flow get_detail 캐시 | ~193K | 2.3% | ✅ 활성 | ~193K† |
| #2 update_remote 성공 트림 | 549K | 6.6% | ✅ **반영**(v1.21.12 `80c0a25`) | ≥140K 실측‡ |
| #3 sn_query 컬럼형 | 519K | 6.2% | ✅ **기본ON**(플래그 없음·무손실 왕복 검증) | 다행쿼리서 자동 |
| ~~#1b download 캐시~~ | ~330K | — | ⛔ **드롭**(드리프트 정확성 손상) | 0 |
| #4 error→retry 감소 | 120K | 1.4% | 🔸 **착수**(v1.21.15·16) | ~14K 실측§ |
| #5 diff→update→diff 루프 단락 | ~189K | 2.3% | ⛔ 미착수 | 0 |
| #6 diff full 컨텍스트 캡 | ~120K | 1.4% | ⛔ 위험·보류 | 0 |

† TTL 60s 내 동일 재fetch만 → 실제론 상한.
§ v1.21.15: 잘못된 인스턴스 에러가 alias를 직접 지목(51회×123tok 발생 + `list_instances`
왕복 제거). v1.21.16: `sn_query` 빈결과 힌트에서 **2xx 이후엔 참일 수 없는** "테이블명
확인" 조언 제거(194회×27tok). 둘 다 **문장을 줄인 게 아니라 틀린 안내를 지운** 것 —
그래서 토큰·왕복·성공률이 함께 개선된다. 이 성질(정보 손실 0)을 만족하는 건이 #4의
남은 후보 기준이다.
‡ 실서버 응답 346건 파싱(2026-07-27). 로그가 500자에서 잘려 **보이는 4키만** 계측한
하한: `validation` 31 + `pre_flight_warnings` 26 + `message` 8 + 중복 `fields` 7 ≈
**성공 1건당 72토큰** × 2,198성공. 549K 추정에 포함된 `risk` 산문·`local_sync` 블록은
500자 창 밖이라 미계측 — 실제값은 140K~549K 사이.

**단계별 누적 실현:**
- **지금(v1.21.16): #1·#2·#3 완료 + #4 착수** — 잠재 합 ~1.26M(15.1%), 실측 하한
  기준으로는 더 낮다(‡와 재시작 지연 참조).
- #4 잔여: 120K 중 ~14K 회수, 나머지는 §3 T7 기준으로 선별.
- ~~#1b download 캐시~~: **드롭**(드리프트 정확성 손상, T3 참조).
- +#5/#6(redundancy·diff): 상한 **~18%**, 단 sync 정확성 검증 필요.

> 정직한 상한: **안전하게 ~15~16%**(출력토큰). 그 이상(download/diff-loop)은 정확성
> 비용이 붙어 "성능 유지" 조건과 충돌 — 무리하게 안 함.

---

## 2. 이번 세션 착수분 (구현 완료)
- **#3 컬럼형**: `sn_api.py` `to_columnar()`, `sn_query` 배선. **무조건 ON·≥3행**
  (`_COLUMNAR_MIN_ROWS`, `sn_api.py:1485`). under-fetch-safe. 테스트 9.
  ⚠️ 이 문서 초판이 적었던 `SERVICENOW_SN_QUERY_COLUMNAR` 환경변수와 `columnar_enabled`
  함수는 **소스에 존재한 적이 없다**(도입 커밋 `af87b23`부터 무플래그). 켤 것도 없다.
- **#1 flow 캐시**: `sn_api.py` 범용 `read_cache_get/put/invalidate_read_cache`(네임스페이스,
  독립 TTL). `flow_tools.py` `_do_get_detail` 캐시(성공만·TTL60s)·write시 무효화. 테스트 9.
- 전체 스위트 3969 passed / cov 92.95% / 회귀 0.

---

## 3. 다음 조임 — 우선순위 (더 짜기)

### ~~T1. #2 update_remote 성공 payload 트림~~ `[완료 — v1.21.12 80c0a25]`
성공경로가 delegate 결과를 장식하는 대신 **compact ack를 새로 조립**한다:
`{success, landed, target_instance, sys_id, fields_pushed, risk_level, change_ratio}`.
버림: `message`·중복 `fields`·`validation` 에코·`risk` 산문블록·`local_sync` 래퍼(절대경로).
안전신호는 **조건부로 전부 생존** — `risk`는 level≠none일 때 원본 유지, `validation`은
자체 재읽기가 실패한 경우에만 `fields_mismatched`로 전달, `size_warnings`/
`pre_flight_warnings`/`update_set_warning`은 그대로 통과. 스펙 문서는 구현과 함께 삭제됨.

### ~~T2. #3 컬럼형 활성화~~ `[해당없음 — 애초에 게이트가 없었음]`
플래그가 존재한 적 없으므로 "켜는" 작업 자체가 성립하지 않는다(위 §2 경고 참조).
다만 **≥3행에서만** 발동하므로 상한 519K는 다행 트래픽 비중에 비례해 축소된다 —
실측 세션(2026-07-27)에서 sn_query 15건 중 3건(20%)만 임계치 통과.

### ~~T3. #1b download_app_sources 캐시~~ `[드롭 — 코드 검증 후 기각]`
- **재평가 결과 안전 레버 아님.** download은 `sys_mod_count`로 **라이브 드리프트
  검증**을 하는 sync 작업 — 330K "반복"의 상당수가 **드리프트 재검증(=정확성)**이지
  트림 가능한 낭비가 아님. 결과 캐시 = **드리프트 감지 스킵 → 옛 소스로 작업**(source판
  under-fetch/stale). ⚠️ 정확성 손상.
- **요약 트림도 무의미:** 반환 요약은 이미 lean(bodies는 디스크, 요약엔 per-family
  카운트+next_step만, `entries`는 매니페스트에만). 큰 트림 여지 없음.
- **결론: 착수 안 함.** 계획서 초안의 T3 랭킹이 낙관적이었음(정직한 교정).

### T4. #1 캐시 확장 (기타 순수 read) `[소액]`
- sn_schema/get_metadata_source는 코퍼스상 **동일-반복이 적어** 캐시 실익 작음(측정 기반).
  무리하게 확장 말 것. export/health 등도 미미.

---

## 4. 더 어려운/구조적 레버 (redundancy 축, 13.1%)

### T5. diff→update→diff 루프 단락 `[~189K]`
- push 후 `update_remote_from_local`이 이미 post-write 검증 수행 → 직후 동일 path의 diff는
  그 결과로 응답 가능(재계산 회피). 워크플로 최적화라 정확성 검증 필요.

### T6. flow get_detail 서브플로 이중커버 dedup `[포함]`
- `include_subflow_tree`가 인라인한 서브플로 본문을, 이후 그 서브플로 standalone get_detail이
  또 가져옴. 인라인분을 서브플로 own 캐시키로도 채우면 후속 조회가 히트. (현 캐시는 트리 전체키만.)

### T7. #4 error→retry 감소 `[120K · 착수됨]`
- 604건 실패후성공 재시도 = 파라미터 검증/스키마 명료화로 선제 차단.
- **완료분(v1.21.15·16)**: 위 §1 § 각주 참조. 공통 패턴 — 에러 메시지가 **답을 주는
  대신 조회를 시키거나**(→왕복), **그 시점에 참일 수 없는 원인을 지목**(→오도)하고 있었다.
- **다음 후보를 고르는 기준**: 메시지를 짧게 쓰는 게 아니라, (a) 서버가 이미 아는 답을
  호출자에게 찾아오게 시키는 곳, (b) 코드 경로상 반증 가능한 원인을 안내하는 곳.
  실측 진입점: 로그에서 80자 이상 상수 문자열의 반복 횟수를 세면 후보가 바로 뜬다.

---

## 5. 미해결 (측정 불가 축)
- **선택/추론 비용**: 통합·description 조정의 순효과는 정적으로 못 잼.
  eval 하네스(wrong-tool률·round-trips·task당 토큰) 필요. 통합은 이거 없이 정당화 금지
  (실측상 스키마 절감 3%·선택비용 폭발 위험).

---

## 5b. 최종 상태 (한 눈에)

**✅ 착수·완료 (코드 반영됨, 전체 스위트 3967 passed / cov 92.9% / 회귀 0)**
| 항목 | 파일 | 내용 |
|---|---|---|
| #3 컬럼형 | `tools/sn_api.py` | `to_columnar()` + `sn_query` 배선. **기본ON**, ≥3행, `format:"columnar"` 자기기술. 무손실(왕복 테스트로 증명) |
| #1 flow 캐시 | `tools/sn_api.py`, `tools/flow_tools.py` | 범용 네임스페이스 read-cache(`read_cache_get/put/invalidate_read_cache`) + `_do_get_detail` 캐시(성공만·TTL60s) + **write시 무효화** |
| 테스트 | `tests/test_sn_query_columnar.py`(8), `tests/test_flow_detail_cache.py`(9) | 순수헬퍼·통합·무효화·TTL·무손실 왕복 |

**📋 남은 것 (실행 주체 = 유지보수자)**
- **#5 diff→update→diff 루프 단락 (~189K, 최대 잔여)** — 유일한 미착수 大건. 다만
  이건 payload 설계가 아니라 **호출자 판단**의 문제다(실측: 같은 파일을 한 세션에서
  3회 푸시한 구간이 있다). 응답을 깎아서 되는 일이 아니므로 별도 조사가 선행되어야 한다.
- #4는 착수됨(§1 § 각주) — 남은 후보 선별 기준은 §3 T7.

**⛔ 의도적으로 안 한 것 (근거 있는 기각)**
| 항목 | 기각 사유 |
|---|---|
| projection 좁히기 / DEFAULT_TABLE_PROJECTIONS | **under-fetch → 재쿼리**(왕복이 절감보다 큼) |
| description 삭감 | 바닥 있음 — 깎으면 툴 선택이 **멍청해짐** |
| 툴 통합(끌어올리기) | 실측 절감 **2.7%**뿐 + 오선택 비용 폭발 위험 |
| 입력 스키마/narrowing | **이미 포화**(6툴 `_FIELDS_BY_ACTION` 완비, 표면 5K·캐시) |
| sn_exec 메타라우터 | 스키마 가이드 파괴 → 파라미터 장님 추측 |
| download 캐시 | **드리프트 검증(정확성) 손상** |
| prune_empty / display_value 정리 | 실측 **0**(코퍼스에 null셀·참조객체 0) |

**🔬 미해결(측정 불가)** — 선택/추론 비용. eval 하네스 없이는 통합·description 판단 불가.

## 6. 권장 실행 순서
1. **T1**(#2, 본인) + **T2**(#3 eval→on) → **~15% 즉시 실현.**
2. **T3**(download 캐시, 안전설계) → **~19%.**
3. T5/T7(redundancy) → 상한 ~24%.
4. T2/통합 판단용 eval 하네스는 병행 인프라.

각 단계 `pytest tests/ -x` 통과 후. under-fetch/dumbing 유발 항목은 **하지 않음.**
