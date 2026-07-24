# MCP 토큰 최적화 — Deep Research & 개선 계획

> 📕 **이 문서는 조사·적대검수 로그(why)입니다.** 가설→실측→기각의 전 과정을 남겨
> 둔 기록이라 **중간에 뒤집힌 결론이 그대로 보존**돼 있습니다(P1 강등, R 재조준,
> narrowing 포화, 통합 기각 등). 되풀이 방지용 근거로 보세요.
>
> ▶ **실행할 것(what/얼마)은 `mcp_token_accounting_and_tightening_plan.md`** 를
> 보세요. 회계·우선순위·현재 상태는 그쪽이 최신이며, 충돌 시 그쪽이 우선입니다.

> 목적: 회사 정책상 향후 Codex만 허용 → **실토큰을 정확히 아껴야** 함.
> 원칙: *단순·기계적 작업을 LLM 컨텍스트에 밀어넣지 말고 Python 서버단에서
> 처리해 결과만 반환*. 성능(정확도)은 유지, 왕복·payload만 줄인다.
> 범위: 계획만. 소스는 건드리지 않음(현재 `session_context_tools.py`,
> `sync_tools.py` 편집 중).

---

## 0.5 실측 (REAL DATA — 아래 추정들을 상회/정정함) ⭐

> tiktoken cl100k 실측 + 실사용 로그 11,431콜 분석. **정적 추정을 뒤집음.**
> 스크립트: scratchpad/`parse_usage.py`,`t2_served.py`.

**A. 실사용 top 툴(11,431콜, 빈도×평균결과 = 집계 출력소비):**
`sn_query`(4364×1519B) ≫ `update_remote_from_local`(2651×1226B) >
`diff_local_component`(1397×1591B) > `sn_aggregate`(1023×640B) >
`download_app_sources`(349×3728B) > `manage_flow_designer`(253×**7126B**) >
`get_metadata_source`/`sn_schema`/`get_widget_bundle`(97/74/61 × ~7-9KB).
→ **정정:** §1 R에서 1순위로 짚은 `manage_change`/`manage_user` list는 **실사용
top에 없음.** "wide=크다" 이론 오조준. **출력 최적화는 위 실측 고빈도 툴에 재조준.**

**B. 스키마 비용 = 정적 감사가 뻥튀기:**
- standard(기본) 전체 served = **5,099T**(full 57툴=10,780T, core 13툴=1,538T).
  스키마는 시스템프롬프트라 **요청당 1회·캐시.**
- `manage_flow_designer` standard 실측 = **429T (882 아님, 2.05× 과다계상)** —
  narrowing이 write 4액션 숨김. (§2c 결론 실측으로 재확인.)

**C. 통합(끌어올리기)은 토큰상 막다른 길(§3b 정정):**
- 포털 getter 4→1 실절감 = **139T = standard의 2.7%** = 오차 수준.
- 오선택 1회 = 500~9000T(실 payload) → 통합이 mis-route 살짝만 늘려도 순손실.
- **통합을 토큰 근거로 정당화 금지.** 하려면 ergonomics + eval 하네스 입증.

**D. 못 잰 것(T3):** 정적 측정은 **선택/추론 비용**(어떤 툴·액션·파라미터냐 +
오라우트 복구)을 못 담음. proliferation도 over-consolidation도 이걸 키움. 실측하려면
A/B eval 하네스(wrong-tool률·round-trips·task당 토큰) 필요. **이게 유일한 미해결 축.**

**⇒ 재조준: 입력/통합 축 종료. 실질 절감 = 출력측 §1을 실측 고빈도 툴(sn_query/
sync/diff/flow_designer/source readers)로 재타깃.**

## 0. 이미 갖춰진 것 (재발명 금지 — 적대적 기준선)

| 계층 | 장치 | 위치 |
|---|---|---|
| 입력 스키마 | 3단계 컴팩션(minimal/compact/full), title·docstring·anyOf 제거 | `server.py::_compact_schema`, `_get_tool_schema` |
| 출력 예산 | 75KB 초과분만 abridge — sys_id 있는 레코드 문자열 필드 stub / 후행 행 절단 | `utils/response_budget.py::enforce_response_budget` |
| 출력 직렬화 | 공백 제거 compact JSON(orjson) | `server.py::serialize_tool_output` |
| **소스비교(신규, working)** | `diff_local_component(refresh=True)` per-field 무클로버 fast-forward; `_rebase_guidance`는 **diverged 케이스만** 안내(나머지 침묵); `check_update_set_for_push`는 Default/전환만 경고 | `sync_tools.py::_refresh_local_from_remote`, `_rebase_guidance`, `session_context_tools.py::check_update_set_for_push` |

> **정합성:** 위 소스비교 개선은 이 계획의 철학과 동일 혈통(verdict-mode).
> 세 신규 advisory 필드 전부 **조건부 emit**(좋은 케이스엔 키 부재).
> ⚠️ 단 개별 gate ≠ 안전: `refresh_report`+`rebase_guidance`는 refresh 후 여전히
> diverged면 **동시발생**(정상 조합) → 최악 ~200토큰. "동시발생 상한"으로 관리.
> `update_remote_from_local`은 이미 projected dict 반환 → **P1 대상 아님(깨끗)**.

**핵심 함의:** JSON 공백압축·스키마 다이어트는 **이미 소진**. 출력 예산은
**75KB 안전망**일 뿐 — 그 미만 payload와 sys_id 없는 계산값은 **매 호출 통째로
과금**된다. 따라서 남은 절감은 전부 **구조적**이다: (a) LLM이 안 쓰는 데이터
반환, (b) Python 한 번이면 될 걸 여러 번 왕복, (c) LLM이 하는 기계적 변환.

---

## 1. 개선 포인트 (적대적 검수 통과분만)

각 항목: 근거(file:line) → 고칠 것 → **판정**(절감/난이도/리스크).

### ★★ R — read/list의 `fields=""` 전컬럼 덤프 → projection  `[HIGHEST, 최우선]`
> **남은 최대 실질 win.** wide 테이블 list가 전 컬럼을 컨텍스트로 쏟음.
> narrowing(입력측)도 75KB 예산망(레코드당 미달)도 안 잡는 **순수 출력 낭비.**
> 고빈도 triage 콜 × wide 테이블 = 곱셈으로 큼. 전부 코드 직접 검증함.
> 아키텍처상 `display_value=True`가 참조필드는 이미 flatten → ref 3배문제는 clean.

| 대상(tool/action) | 근거 | 낭비 | 고칠 것 |
|---|---|---|---|
| `manage_change` list+detail | `services/change.py:229,241 fields=""` | change_request ~150컬럼, +change_task 100건×전필드 | list=`sys_id,number,short_description,state,type,risk,assignment_group,sys_updated_on`; task=`sys_id,number,short_description,state` |
| `manage_user` list | `user_tools.py:80,121,160 fields=""` | sys_user ~100컬럼(photo/calendar 등) | `sys_id,user_name,name,email,active,department,title` |
| `manage_changeset` detail | `services/changeset.py:241 fields=""` | `sys_update_xml.payload`=레코드별 **XML 전문** ×100 = 토큰폭탄 | payload 드롭, 인벤토리(`name,type,target_name,action,sys_created_on)`만; payload는 sha/linecount 모드 |
| `manage_group` list | `user_tools.py:160` (+count_only 없음) | 전필드 | `sys_id,name,description,manager,type,active` + `count_only` 추가 |
| `manage_workflow` list | `workflow_tools.py:262 fields=""`, limit 미클램프 | 전필드 | projection + `min(limit,100)` |
| Agile list ×4 | `story_tools.py:272`/`epic_tools.py:207`/`scrum_task_tools.py:260`/`project_tools.py:237` | list에 `description/acceptance_criteria/work_notes` 저널본문 포함, count_only 전무 | list projection에서 저널/free-text 제거(detail에만), `count_only` 추가 |
| `manage_changeset` list | `services/changeset.py:289`, limit 미클램프 | 전필드 | projection + clamp |

- **고칠 것(공통 shape):** `sn_query_page(fields="…")` 명시 + `count_only` 분기는
  `sn_count`/`sn_count_by_group`(`sn_api.py:729/752`) 위임 + `limit=min(limit,100)`.
  코드베이스 다수가 이미 쓰는 패턴 — 발명 아님.
- **판정:** 절감 **최고**(고빈도×wide) / 난이도 **低**(projection 문자열 추가) /
  리스크 **低~中**. ⚠️ list projection 축소 시 그 필드 단언 테스트 grep 후 동반수정.
- **검증 clean(손대지 말 것):** catalog/script_include/scripted_rest/incident/
  knowledge_base/flow_designer list/get_logs/ui_policy/`sn_query`(apply_payload_safety)
  /session_context reads — **이미 projection+count_only 완비.** 재작업 0.
  `get_incident_by_number`는 `fields=""`지만 출력을 11필드로 수동 projection →
  **네트워크 over-fetch일 뿐 LLM토큰 낭비 아님, 제외.**

### P1 — 쓰기 후 전체 레코드 echo 제거  `[LOW — 강등됨, 콜드패스]`
> ⚠️ **재평가: 초기 HIGH → LOW로 강등.** 아래 3가지 이유로 ROI 최악. 급하지 않음.
- **근거:** `workflow_tools.py:451,525,582,639,705,773`, `epic_tools.py:117,167`,
  `project_tools.py:141,197`, `story_tools.py:176,232`, `flow_designer_tools.py:2353`.
  전부 `"<obj>": result.get("result", {})` — write 응답 레코드 전체(~30~70필드) 반환.
- **왜 강등:**
  1. **콜드패스.** write는 read/download 대비 저빈도. 레코드1개 echo(~500~1k토큰)는
     세션 전체 토큰에서 미미. "절감 高"는 mutation 내부 상대비율일 뿐이었음.
  2. **net-negative 위험.** 필드를 쳐냈는데 LLM이 다음 스텝에 필요 → **re-GET 왕복**
     = 오히려 토큰 증가. 쓰기 직후 레코드 읽어 이어가는 패턴 흔함.
  3. **품·리스크 최대.** 5개 중 유일하게 **테스트 28곳 결합**
     (`test_workflow_tools.py:423 active`, `:158 name`, `test_story_tools.py:205 state`,
     `test_flow_designer_tools.py:218 result["flow"]=={}` 빈케이스).
- **굳이 한다면(안전 최소범위):** 전면 projection ✗. **호출자가 방금 보낸 무거운
  본문 필드(`script`/`description`/`work_notes`)만 드롭**, sys_id/number/name/state/
  active는 유지 → 테스트 안 깨짐, re-fetch 위험 없음. 그래도 콜드패스라 후순위.

### P2 — `batch_get` 서브응답 다이어트  `[HIGH]`
- **근거:** `sn_batch.py:126-130` — `{status_code, body(전필드 파싱), headers}`를
  요청 수만큼. `headers` dict는 성공경로에서 거의 불필요.
- **고칠 것:** ① 성공(2xx) 경로에서 `headers` 제거(비2xx만 유지) ② 선택적
  `fields=` projection 파라미터 추가. `apply_payload_safety`(`sn_api.py:117`) 재사용.
- **판정:** 절감 **中~高**(배치 크기 비례) / 난이도 **低** / 리스크 **低**
  (headers 드롭은 하위호환, projection은 opt-in). **P1 다음 우선.**

### P3 — 파싱 실패/에러 경로의 무제한 본문 반환  `[MED, 저비용]`
- **근거:** `sn_api.py:901 {"raw": response.text}` **← 유일한 완전 무제한**.
  그 외 `portal_tools.py:3097 Update failed: {response.text}`,
  `flow_edit_tools.py:406,1289,1407 resp.text[:2000]`.
- **고칠 것:** 에러엔 status+짧은 사유면 충분. `str(exc)[:200]`
  (`sn_api.py:1129,1169`) / `text[:200]`(`sync_tools.py:1756`) 관례로 캡.
  최소 **`:901`만이라도** 캡(HTML 오류페이지 수 KB 통째 유입 방지).
- **판정:** 절감 **中**(에러시 폭발적) / 난이도 **低** / 리스크 **低**. **가성비 최고.**

### P4 — `sn_aggregate` 통계 봉투 평탄화  `[MED]`
- **근거:** `sn_api.py:1451 "result": _safe_json(...).get("result")` — 중첩
  `stats` + groupby 링크객체까지 통째.
- **고칠 것:** **단일 stat·단일 groupby** 케이스만 `{group_value: number}` 로
  평탄화(`sn_count_by_group` `sn_api.py:752` 재사용). 다중 stat/groupby는 원형 유지.
- **판정:** 절감 **中** / 난이도 **低** / 리스크 **低**.
  - ⚠️ 적대적: 무조건 평탄화하면 다중 stat 손실 → **조건부**로만.

### P5 — 위젯 의존체인 본문 덤프 → 매니페스트 기본화  `[MED]`
- **근거:** `portal_tools.py:3955-4060` — widget + provider N + script_include N의
  `script`/`client_script` **본문**을 결과에 축적(각 `_truncate_source` 캡이나
  다수 × 통째).
- **고칠 것:** 기본은 매니페스트(names/sys_ids/ref엣지/본문 line-count·sha),
  전체 본문은 `include_bodies=True` gate. `:4056`의 `summary` 문자열 확장.
- **판정:** 절감 **中** / 난이도 **中** / 리스크 **中**
  (기본동작 변경 → 호출부·테스트 계약 먼저 확인 후).

---

### 추가 조임 (성능 중립 — "더 조일 포인트")
> 속도·네트워크·연산 불변(Python 변환/문자열 제거)인 것만. 실측 기반.

- **C — 대형 list 컬럼형 인코딩  `[상한 최고, 실험]`:** compact JSON도 행마다 키
  반복(`"short_description":`×N). 키 1회 + 값 배열(`{cols:[...],rows:[[...]]}`)로.
  **절감 100행당 ~2,376토큰 / 25행당 ~576토큰**(projection 8필드 기준). 속도 중립.
  ⚠️ **정확도 리스크:** LLM은 위치배열을 keyed 객체보다 덜 정확히 읽음 → header
  포함 + 대형(>N행)만 + **opt-in/실험**으로. "성능 유지" 조건상 즉시적용 ✗, A/B 후.
- **A — 성공 message 보일러플레이트 드롭  `[LOW, 제로리스크]`:** `"…successfully"`
  정적 리터럴 35개(`"message"` 반환 220곳 중). 성공은 projected 결과(sys_id 존재·
  error 부재)로 자명. 호출당 ~5~8토큰×빈도. 테스트 message 단언만 grep 후 제거.
- **strip_empty 편승  `[LOW]`:** service-list(change/user)는 `fields=""`라 empty 셀도
  직렬화. R projection 후 `strip_empty_fields`(`sn_api.py:62`; generic 경로엔 이미
  `:1370` 적용) 태우면 sparse 레코드 추가 절감. R와 함께.

## 2. 기각·보류 (적대적으로 걸러낸 것)

| 후보 | 판정 | 사유 |
|---|---|---|
| JSON 공백/스키마 압축 강화 | **기각** | 이미 구현됨(§0). 재작업 = 0 절감. |
| `get_logs`/journal 캡 | **기각** | 이미 20행+preview 캡(`log_tools.py:215`). |
| flow 구조 all-field fetch(`flow_designer_tools.py:2160,2307`) | **기각** | 와이어는 크나 **반환은 distilled**(`flat_summary`+counts). LLM 토큰비용 0(네트워크만). |
| `sn_health`/probe/session_context 진단 blob | **보류** | 저빈도 단발 진단. ROI 낮음. |

---

## 2b. Description 레이어 스윕 (기계적, AST 계측 — 확정)

> 매 요청 나가는 최고빈도 비용이라 먼저 쟀음. 결과: **여기는 리크 아님.**
- **tool description >120자: 딱 1건** (`flow_tools.py:519`, 159자) → 이것만 다듬으면 끝.
- **param description >80자: 28건** (top: `flow_edit_tools.py:1032` 122자) → 사소.
  게다가 minimal 스키마 모드(`_SCHEMA_DETAIL_MINIMAL`)에선 **전부 스트립**되어 0비용.
- ⚠️ **함정(하지 말 것):** "description 없는 Field 228개"는 토큰 *절감*이지 추가 대상
  아님. CLAUDE.md는 문서화를 권하나 그건 추론비용 트레이드오프 — **토큰만 보면
  무설명이 더 쌈.** 여기에 설명 채우면 토큰 늘어남 → **본 목표(절감)와 상충, 제외.**
- **판정:** description 레이어 정리는 `flow_tools.py:519` 1줄 외 **ROI 없음.**

## 2c. 입력 스키마 / action-narrowing 축 (Tool Token Cost 감사 적대검수 — 확정)

> 별도 Tool Token Cost 감사(57툴, manage_flow_designer 882T/40param 등)를 코드로
> 대조 검증한 결과. **매 요청 나가는 상시비용**이라 축 자체는 최우선이 맞으나 —

- **`manage_flow_designer` narrowing 권고 = 이미 실현됨(기각).**
  - `ManageFlowDesignerParams._FIELDS_BY_ACTION` 완비(`flow_tools.py:1174`),
    standard가 `[list,get_detail,get_executions,get_action_source]`로 pin(`yaml:56`),
    read-only 프로파일은 `[list]`(`yaml:30`), `server.py:1197`이 서빙 시 미사용
    프로퍼티 실제 drop.
  - **standard 실전송 24/40필드(~40% drop), `[list]` 프로파일 10필드(~75% drop).**
    882T/40param은 `model_json_schema()` **raw값** — 서버 전송값 아님.
- **narrowing 패턴 포화 = 남은 win 0.** `actions:` read리스트로 pin된 툴 6개
  (workflow/flow_designer/script_include/widget_dependency/scripted_rest/catalog)
  **전부 이미 `_FIELDS_BY_ACTION` 보유.** `_FIELDS_BY_ACTION` 없는 16개
  action-multiplex 툴(portal_component/incident/change/…)은 **read리스트 노출
  패키지가 없어** narrowing 미발동 → 추가해도 **현 구성 0절감.**
- **측정 결함(핵심):** 감사가 **선언 모델**을 쟀으나 서버는 **패키지별 narrow+
  compact 스키마**를 보냄 → `_FIELDS_BY_ACTION` 6툴 전부 과다계상. 실토큰은
  `MCP_TOOL_PACKAGE=<pkg>`로 띄워 **`list_tools()` 실 출력 스키마**를 재야 함.
- **잠재적 신규 win(설계 결정, 버그 아님):** 지금 full-surface로만 노출되는 read
  겸용 툴을 어떤 read 프로파일에 `actions:[get,list]`+`_FIELDS_BY_ACTION`으로
  추가 노출한다면 그 프로파일에서 절감 발생. 단 incident/change는 의도적으로
  standard 밖(대신 `sn_query`) — 그럼 손댈 것 없음.
- **param desc 압축(#2) = LOW:** minimal 모드 스트립 + narrowing 대비 미미.
  비-multiplex 툴(search_portal_regex_matches/scaffold_page)은 압축만 가능, 저가치.

**→ 입력 스키마 축의 실행 항목은 사실상 없음. 남은 실질 절감은 전부 출력측(§1).**

## 3. 감사가 과소평가한 2차 축 — 왕복 (2차 감사 완료)

> 별도 round-trip 감사 결과: 이 저장소는 왕복 붕괴도 대부분 완료 상태
> (대부분 get 툴이 name-or-sys_id 수용, `sn_batch`/verdict 배치 존재).
> **유일하게 남은 유효 후보 1건:**
- **RANK1 — `manage_flow_designer` get_detail에 `name=` 추가.** 현재 get_detail은
  `flow_id`(sys_id)만 받고 list만 name 필터 보유(`flow_designer_tools.py:82`) →
  `list(name=)`→LLM이 dump에서 sys_id 골라냄→`get_detail(sys_id)` **3왕복.**
  server-side name→sys_id 해소(리졸버 `flow_edit_tools.py:1088` `_resolve_target`
  이미 존재, 재사용)하면 **list dump+pick+2차콜 전부 제거.** 플로우 구조 조회는
  고빈도라 실효 큼. 난이도 低(기존 리졸버 재사용)/리스크 低(모호시 candidates 반환).
- RANK2/3(flow_edit write name 수용, widget_dependency record_id name 수용) = 저빈도.

### (아래는 기존 §3 내용 — payload 크기 축과 구분)

§1은 **payload 크기** 축이다. 사용자 원칙("Python으로 대체해 결과만")의 더 큰
지렛대는 **왕복 횟수**다: LLM이 여러 tool을 순차 오케스트레이션해서 하는 일 중
Python 한 번이면 끝나는 것.

- 후보 패턴: `list → (LLM이 sys_id 고름) → get` 왕복. 필터/projection 파라미터로
  1콜에 원하는 1건만 반환하면 list 덤프+추론+2차콜을 제거.
- 후보: audit/diff 결과를 LLM이 순회하며 후속콜 → 서버단 집계로 대체.
- **액션:** "다중 왕복 워크플로" 전용 2차 감사를 별도 실행(이번 감사는 반환-shape
  한정). 근거 없이 리팩터 금지.

---

## 3b. 기능 축 — 쳐내기 / 끌어올리기 (description 삭감 대신)

> **원칙(사용자 지시):** description을 아끼려 무작정 빼면 **툴 선택·사용이 멍청해짐**
> (바닥이 있음 = 토큰 vs 정확도 트레이드오프). 순수 절감은 **기능적으로** 낸다.
> 무설정 기본 패키지 = `standard`(`server.py:941`), 나머지 전부 `_extends: standard`.

### ★★★ F1 — 비대한 `standard` 베이스 분해 (요청당 최대 절감)  `[HIGHEST]`
- **근거:** `standard`(30툴)에 **포털 read 9개**(get_page/get_widget_bundle/
  get_widget_instance/get_portal_component_code/download_portal_sources/
  search_portal_regex_matches/trace_portal_route_targets/analyze_widget_performance/
  manage_widget_dependency) + **소스분석 ~6개**(extract_table_dependencies/
  download_app_sources/audit_local_sources/query_local_graph/export_record_xml/
  get_metadata_source)가 박혀 있음. `standard`가 만능 베이스라 **모두가 상속** →
  포털 안 만지는 `platform_developer`(incident/change)도 포털툴 9개를 **매 요청 세금.**
- **낭비 규모:** 포털툴 다수가 무거움(portal_component 474T, search_portal_regex
  465T, widget_dependency 402T…) → 비-포털 세션에서 **요청당 대략 2~3천 토큰.**
  스키마는 **매 요청** 나가므로 이 축이 출력측(호출당)보다 상시비용이 큼.
- **고칠 것:** read-layer 분리. `standard` = 린 제네릭 코어(sn_* + get_logs +
  diff_local_component 등), `portal_read`/`source_read` layer를 신설해
  portal_developer만 `_extends: standard, portal_read`. 비-포털 프로파일은 안 짊어짐.
- **판정:** 절감 **최고**(요청당·상시) / 난이도 **中**(패키지 재편) / 리스크 **中**.
  - ⚠️ **적대적 전제:** 이 축의 실효는 **기본 사용자가 누구냐**에 달림. 다수가
    `standard`로 포털+소스 인스펙션을 기대하고 쓴다면 슬림화는 기능 상실로 느껴짐.
    → **하위호환 경로:** 오늘의 standard를 `standard_full` 별칭으로 남기고 기본
    `standard`만 린 코어로. 기능 총량 보존 + 기본 세션만 절감. 사용 패턴 확인 후.

### F2 — 포털 read getter 4개 통합 (끌어올리기)  `[MED]`
- **근거:** get_page / get_widget_bundle / get_widget_instance /
  get_portal_component_code = 별개 4툴. 선례 있음 — widget_dependency가
  "get_provider_dependency_map + resolve_widget_chain + resolve_page_dependencies
  흡수"(내부 resolver화).
- **고칠 것:** action-multiplex `get_portal_source(kind=...)` + `_FIELDS_BY_ACTION`
  → 4 스키마 → 1, 패키지별 narrow 가능.
- **판정:** 절감 **中**(툴 수 감소) / 리스크 **中**.
  - ⚠️ **사용자 원칙 직결:** **사용자용 getter 병합은 선택 정확도 저하 위험**
    (LLM이 `kind` 오선택). widget_dependency는 *내부 resolver* 병합이라 안전했음.
    getter 병합은 액션별 설명 명료성 유지 + 선택품질 테스트 전제. 슬램덩크 아님.
- **description 삭감(예: `flow_tools.py:519` >120자)은 선택관련 정보 손실 없을 때만.**
  바닥 아래로 깎으면 동작 저하 → 실질 지렛대 아님(§본 원칙).

## 4. 재사용 패턴 카탈로그 (구현 시 복사 대상)

- **Projection:** `apply_payload_safety`(`sn_api.py:117`, UNIVERSAL_SAFE_FIELDS +
  HEAVY_FIELDS시 limit≤5), `strip_empty_fields`(:62), `truncate_results`(:76),
  명시적 `fields="sys_id,name,..."`(`change_tools.py:361` 등).
- **Count/Verdict/Summary:** `count_only`(`workflow_tools.py:41`, `change_tools.py:47`),
  **`verdict`(gold standard)** `sync_tools.py:225→_verdict_scan(1762)/`
  `_component_field_verdicts(1851)` — 본문을 **Python에서 비교**, verdict+변경라인수만.
  stats-only `sn_count(729)/sn_count_by_group(752)/sn_aggregate(1418)`.
- **매니페스트/안전망:** `_manifest.json`(`sync_tools.py:319`),
  `enforce_response_budget`(sha+preview+refetch 힌트) — "해시/verdict 반환+재요청
  제공" shape의 표준.

---

## 4b. 실측 kill-list (12,936콜 / 8.38M 출력토큰 딥마이닝 — 최종 확정) ⭐⭐

> tiktoken cl100k, 620개 트랜스크립트 549MB 파싱. 스크립트 scratchpad/`m1..m4,m3.py`.
> **상위 5툴이 출력토큰의 82.3%, sn_query+flow_designer가 58.9%.**

| # | 인터벤션 | 실절감 | %코퍼스 | 난이도 | 리스크 | 상태 |
|---|---|--:|--:|---|---|---|
| **1** | read 툴 **세션 응답캐시**. 착수: **flow get_detail**(순수 read, TTL 60s, write시 네임스페이스 무효화). 범용 `read_cache_get/put/invalidate_read_cache`(sn_api.py, 미래 read툴 확장용) | **~566K**(1차 착수분 ~193K) | 6.8% | 中 | 低中 | ✅ **flow get_detail 구현+테스트9**. download은 부작용으로 보류 |
| **2** | `update_remote_from_local` **성공 payload 트림** → `{success,sys_id,fields,risk_level,change_ratio,cross_instance}`. risk 산문중복·절대경로·update_set/validation echo 제거 | **549K** | 6.6% | **低** | 低 | 📋 **스펙 전달**(네 파일 mid-edit, 네가 반영) |
| **3** | multi-row `sn_query` **컬럼형**(`columns[]`+`data[][]`). 다행결과 바이트 28.7%=반복 키 | **519K** | 6.2% | 中 | 中 | ✅ **구현+테스트9**. `SERVICENOW_SN_QUERY_COLUMNAR` 기본OFF·≥3행·eval후 on |

> **구현 원칙(확정):** 채택한 3개 전부 **under-fetch-safe** — 필드를 안 버림(캐시=동일본문,
> 컬럼형=쿼리필드 그대로 재인코딩, 트림=콜러가 보낸 에코 제거). projection 좁히기·
> DEFAULT_TABLE_PROJECTIONS·description 삭감은 under-fetch/dumbing 위험으로 **폐기**.
> 전체 스위트 3969 passed / 92.95% cov, 회귀 0.
| 4 | error→retry 감소(파라미터 검증 강화) | 120K | 1.4% | 中 | 低 |
| 5 | full-`diff` 컨텍스트 라인 캡 | ~100-150K | ~1.5% | 中 | 中(콜러가 원한 본문) |

**상위 3 비중복 합 ≈ 1.63M ≈ 19.5%.** (+4,5 하면 ~24% 상한.)

**데이터로 죽인 것(적대적 컷):**
- ❌ sn_query **display_value/null 드롭 = 0토큰**(코퍼스에 null셀 0·참조객체 0, 이미 규율). ← §5 이전 "sn_query projection" 방식 실측 0. 진짜 win은 컬럼형.
- ❌ list→get `name=` 붕괴 = 0.6% → 컷. ❌ risk.message 중복 = <0.1%(#2흡수).
- ❌ diff verdict 기본화 — verdict 이미 lean, full-diff는 콜러 요청 본문.

**핵심:** ①왕복/중복이 최대 지렛대(**13.1%, 1.099M** — 어떤 포맷변경보다 큼), clean 부분집합이 #1. ②워크로드 편향(sync-도그푸딩): read-mostly면 랭킹 뒤집혀 #3+쿼리캐시 지배 → **#2·#3 둘 다 + #1(무조건 이김)** 이 정답.

**미해결(§0.5-D):** 선택/추론 비용은 여전히 정적으로 못 잼 → eval 하네스 필요.

## 5. 권장 실행 순서 (실측 재조준 — 최종)

> 입력 스키마/narrowing/통합 축은 **종료**(§0.5 B/C: 표면 5K·캐시, 통합 3%·선택비용
> 리스크). **실질 절감 = 출력측을 §0.5-A 실측 고빈도 툴에 재타깃.** 우선순위는
> "정적 wide 테이블"이 아니라 **실 집계 출력소비(빈도×크기)** 순.

1. **sn_query 출력** — 실사용 1위(4364콜×1519B, max 48KB). 이미 `apply_payload_safety`
   경유하나 집계소비 압도적 → **기본 projection/limit·truncate 상수 재점검**이 최대 ROI.
   sn_query 10% > manage_change 100%.
2. **sync/diff 출력** — `update_remote_from_local`(2651콜, 이미 projected dict) +
   `diff_local_component`(1397콜, max 47KB). 네가 지금 편집 중인 파일 — verdict/refresh
   응답의 동시발생 상한(§0 정합성) 관리가 여기 직결.
3. **`manage_flow_designer` 출력**(253콜×**7126B**) + `download_app_sources`(349×3728B)
   + source readers(`get_metadata_source`/`get_widget_bundle`/`sn_schema` ~7-9KB) —
   본문 요약/manifest 모드 재점검. **P5(의존체인 매니페스트)가 여기 해당.**
4. **P3** (에러본문 캡, `sn_api.py:901`) — 저비용·저위험 즉시.
5. **RANK1** (`manage_flow_designer` get_detail `name=` 추가) — 왕복 제거, flow_designer
   실사용 빈도 있어 실효.
6. **A / strip_empty / P2** — 공짜~저위험 잡절감.
7. **미해결 축 — eval 하네스(§0.5-D):** 선택/추론 비용은 정적으로 못 잼.
   통합·description 조정의 순효과는 **A/B eval(wrong-tool률·round-trips·task당 토큰)**
   없이는 결정 불가. 통합 하려면 여기부터.

**보류/기각(실측 후):** R의 change/user/changeset/group projection(안 쓰는 툴),
통합 6툴(3% + 선택리스크), description 삭감(바닥·dumbing), C 컬럼형(정확도 대가),
P1 write-echo(콜드패스). — 전부 "가능하나 실측상 ROI 낮음 or 리스크>이득".

각 단계: `python -m pytest tests/ -x` 통과 후 커밋. 버전 bump + 태그(CLAUDE.md 규칙).
