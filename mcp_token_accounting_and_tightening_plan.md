# MCP 토큰 회계 & 조임 계획 (Accounting + Tightening)

*측정 기준일: 2026-07-24 · 수치는 이 시점 코퍼스 기준이며 사용 패턴이 바뀌면 재측정 필요*

> 근거: 실측 코퍼스 **12,936콜 / 출력 8.38M 토큰**(tiktoken cl100k, 620 트랜스크립트
> 549MB). 상세 조사·적대검수는 `mcp_deep_research_token_optimization.md` 참조.
> 이 문서는 **회계(얼마)** + **다음 조임(더)** 만 압축.

## ⚠️ 대전제 (착각 방지)
- **%는 전부 출력토큰(8.38M) 기준.** 입력/스키마 축(요청당 ~5K·캐시)은 **이미 종료** — 더 없음.
- 코퍼스는 **유지보수자 sync-편향**(update+diff+download+flow=48% 토큰). 코덱스 read-mostly면
  랭킹 뒤집힘 → **#2·#3 둘 다** 해야 양쪽 커버.
- **구현 ≠ 실현.** 기본OFF/스펙만은 실현 0.
- **선택/추론 비용은 미측정**(정적으로 못 잼) — eval 하네스 필요.
- **under-fetch 금지**: 필드 누락→재쿼리(왕복)는 절감이 아니라 손해. 안전한 절감은
  fetch한 걸 안 버리는 것뿐(캐시=동일본문 / 컬럼형=쿼리필드 재인코딩 / 트림=에코 제거).

---

## 1. 회계 — 얼마 절감되나

| 항목 | 잠재 | %(출력) | 상태 | 지금 실현 |
|---|--:|--:|---|--:|
| #1 flow get_detail 캐시 | ~193K | 2.3% | ✅ 활성 | ~193K† |
| #2 update_remote 성공 트림 | 549K | 6.6% | 📋 스펙만 | 0 |
| #3 sn_query 컬럼형 | 519K | 6.2% | ✅ **기본ON**(플래그 제거·무손실 왕복 검증) | 다행쿼리서 자동 |
| ~~#1b download 캐시~~ | ~330K | — | ⛔ **드롭**(드리프트 정확성 손상) | 0 |
| #4 error→retry 감소 | 120K | 1.4% | ⛔ 미착수 | 0 |
| #5 diff→update→diff 루프 단락 | ~189K | 2.3% | ⛔ 미착수 | 0 |
| #6 diff full 컨텍스트 캡 | ~120K | 1.4% | ⛔ 위험·보류 | 0 |

† TTL 60s 내 동일 재fetch만 → 실제론 상한. **지금 도는 실현 ≈ 2%대.**

**단계별 누적 실현:**
- 지금: **~2%** (#1 flow 캐시만; #3는 이제 기본ON이라 다행쿼리에서 자동 실현되기 시작).
- **#2 반영: ~15%** ← 저노력 실질 목표(#2 549K + #3 519K가 여기 대부분).
- +#4 error 감소: ~16%.
- ~~#1b download 캐시~~: **드롭**(드리프트 정확성 손상, T3 참조).
- +#5/#6(redundancy·diff): 상한 **~18%**, 단 sync 정확성 검증 필요.

> 정직한 상한: **안전하게 ~15~16%**(출력토큰). 그 이상(download/diff-loop)은 정확성
> 비용이 붙어 "성능 유지" 조건과 충돌 — 무리하게 안 함.

---

## 2. 이번 세션 착수분 (구현 완료)
- **#3 컬럼형**: `sn_api.py` `to_columnar`/`columnar_enabled`, `sn_query` 배선.
  `SERVICENOW_SN_QUERY_COLUMNAR` 기본OFF·≥3행. under-fetch-safe. 테스트 9.
- **#1 flow 캐시**: `sn_api.py` 범용 `read_cache_get/put/invalidate_read_cache`(네임스페이스,
  독립 TTL). `flow_tools.py` `_do_get_detail` 캐시(성공만·TTL60s)·write시 무효화. 테스트 9.
- 전체 스위트 3969 passed / cov 92.95% / 회귀 0.

---

## 3. 다음 조임 — 우선순위 (더 짜기)

### T1. #2 update_remote 성공 payload 트림 `[저노력·최대 즉시실현 549K]`
> 📄 **구현 스펙 별도 문서: `mcp_next_win_update_remote_trim_spec.md`**
> (자체 완결형 — 현재 구조/목표 shape/절차/테스트 영향/검증법. 원격에서 이것만 보고 작업 가능)
- `sync_tools.py`(유지보수자 mid-edit — **본인 반영**). 성공경로만.
- 버림: `risk` 산문중복(message==factors)·`validation` 에코·`local_sync.pushed_from` 절대경로·
  `instance_target`·`update_set_context`. 유지: success/landed/target_instance/sys_id/
  fields_pushed/risk_level/change_ratio/update_set_warning?/origin_unverified?. 에러경로 상세 유지.

### T2. #3 컬럼형 활성화 `[519K, eval 게이트]`
- A/B eval(코덱스가 `{columns,data}` 정확 파싱하나) → 통과시 `=on`. 실패시 OFF 유지.

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

### T7. #4 error→retry 감소 `[120K]`
- 604건 실패후성공 재시도 = 파라미터 검증/스키마 명료화로 선제 차단.

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
- **#2 update_remote 성공 트림 (549K, 최대 잔여)** — `sync_tools.py`가 미커밋 편집 중이라
  미착수. 스펙은 §3 T1. **이것만 반영하면 누적 ~15%.**

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
