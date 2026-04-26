# MFA ServiceNow MCP

[English](./README.md) | [한국어](./README.ko.md)

MFA 우선 ServiceNow MCP 서버. 실제 브라우저(Playwright)로 인증하므로 Okta, Entra ID, SAML 등 어떤 MFA/SSO 로그인이든 그대로 동작합니다. headless/Docker 환경에서는 API Key 인증도 지원합니다.

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

```bash
# 아무 AI 코딩 도구에 붙여넣으면 설치를 끝까지 안내합니다
Install and configure mfa-servicenow-mcp by following the instructions here:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

---

## 목차

- [주요 특징](#주요-특징)
- [AI 자동 설치](#ai-자동-설치)
- [필수 준비 사항](#필수-준비-사항)
- [바로 쓰기](#바로-쓰기)
- [MCP 클라이언트 설정](#mcp-클라이언트-설정)
- [인증 방법](#인증-방법)
- [도구 패키지](#도구-패키지)
- [CLI 레퍼런스](#cli-레퍼런스)
- [최신 버전 유지](#최신-버전-유지)
- [보안 정책](#보안-정책)
- [로컬 소스 검수](#로컬-소스-검수)
- [스킬](#스킬)
- [Docker](#docker)
- [개발용 설치](#개발용-설치)
- [상세 문서](#상세-문서)
- [관련 프로젝트 및 참고](#관련-프로젝트-및-참고)
- [라이선스](#라이선스)

---

## AI 자동 설치

> **한 줄이면 끝. AI가 알아서 전부 설정합니다.**

Claude Code, Cursor, Codex, OpenCode, Windsurf, VS Code Copilot, Gemini CLI 등 아무 AI 코딩 도구에 아래 내용을 붙여넣으세요:

```
Install and configure mfa-servicenow-mcp by following the instructions here:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

AI가 자동으로:
1. **uv**와 **Playwright** 설치 (없으면)
2. ServiceNow 인스턴스 URL, 인증 방식, 도구 패키지 질문
3. 사용 중인 클라이언트에 맞는 MCP 설정 파일 생성
4. **24개 워크플로우 스킬** 설치 (지원 클라이언트)

설정 파일 직접 편집할 필요 없습니다. 포맷 차이 신경 쓸 필요 없습니다. macOS, Linux, Windows 전부 지원.

설치 후 **AI 클라이언트를 재시작**하면 MCP 서버가 로드됩니다. 첫 도구 호출 시 브라우저가 열려 MFA 로그인을 진행합니다.

> 수동 설치는 아래 [필수 준비 사항](#필수-준비-사항)과 [바로 쓰기](#바로-쓰기) 참조.

---

## 주요 특징

- **브라우저 인증** — MFA/SSO 환경 지원 (Okta, Entra ID, SAML, MFA)
- **4가지 인증 모드**: Browser, Basic, OAuth, API Key
- **등록 도구 165개**, **실사용 패키지 6개**와 비활성 `none` 프로필 — 최소 읽기 전용부터 넓은 번들 CRUD까지
- **24개 워크플로우 스킬** — 안전 게이트, 서브에이전트 위임, 검증된 파이프라인
- **로컬 소스 검수** — HTML 리포트, 상호참조 그래프, 데드코드 탐지, 도메인 지식 자동 생성
- **크로스-스코프 의존성 자동 해석** — `download_app_sources`가 앱 코드에서 참조하는 글로벌 스코프의 Script Include, Widget, Angular Provider, UI Macro까지 함께 받아 로컬 번들을 분석에 자족적으로 만듭니다
- **Dry-run 프리뷰** — 모든 쓰기 도구에서 `dry_run=True` 지원. 실행 전 필드 단위 diff, 의존성 카운트, 정확도 노트를 반환합니다. 읽기 전용 API만 사용하므로 모든 인증 모드에서 동작.
- `confirm='approve'` 기반 안전한 수정 승인 정책
- 페이로드 안전 제한, 필드별 절단, 총 응답 한도 (200K 문자)
- 일시적 네트워크 오류 자동 재시도 (백오프)
- core, standard, service desk, 포탈 개발자, 플랫폼 개발자, 그리고 가장 넓은 `full` 개발 패키지 제공
- 개발자 도구: 활동 추적, 미커밋 변경사항, 의존성 매핑, 일일 요약
- 핵심 ServiceNow 아티팩트 테이블 전체 커버리지 ([지원 테이블](#지원하는-servicenow-테이블) 참조)
- CI/CD: 자동 태깅, PyPI 퍼블리싱, Docker 멀티플랫폼 빌드

### 지원하는 ServiceNow 테이블

| 아티팩트 유형 | 테이블명 | 소스 검색 | 개발자 추적 | 안전 제한 (대형 테이블) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_client_script` | ✅ | ✅ | 🛡️ |
| Catalog Client Script | `catalog_script_client` | ✅ | ⬜ | ⬜ |
| UI Action | `sys_ui_action` | ✅ | ✅ | 🛡️ |
| UI Script | `sys_ui_script` | ✅ | ✅ | 🛡️ |
| UI Page | `sys_ui_page` | ✅ | ✅ | 🛡️ |
| UI Macro | `sys_ui_macro` | ✅ | ⬜ | 🛡️ |
| Scripted REST API | `sys_ws_operation` | ✅ | ✅ | 🛡️ |
| Fix Script | `sys_script_fix` | ✅ | ✅ | 🛡️ |
| Scheduled Job | `sysauto_script` | ✅ | ⬜ | ⬜ |
| Script Action | `sysevent_script_action` | ✅ | ⬜ | ⬜ |
| Email Notification | `sysevent_email_action` | ✅ | ⬜ | ⬜ |
| ACL | `sys_security_acl` | ✅ | ⬜ | ⬜ |
| Transform Script | `sys_transform_script` | ✅ | ⬜ | ⬜ |
| Processor | `sys_processor` | ✅ | ⬜ | ⬜ |
| Service Portal Widget | `sp_widget` | ✅ | ✅ | 🛡️ |
| Angular Provider | `sp_angular_provider` | ✅ | ✅ | ⬜ |
| Portal Header/Footer | `sp_header_footer` | ✅ | ⬜ | ⬜ |
| Portal CSS | `sp_css` | ✅ | ⬜ | ⬜ |
| Angular Template | `sp_ng_template` | ✅ | ⬜ | ⬜ |
| Update XML | `sys_update_xml` | ✅ | ⬜ | ⬜ |

---

## 필수 준비 사항

[uv](https://astral.sh/uv)를 설치하세요 — Python, 패키지, 실행을 한번에 처리합니다.

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

설치 후 터미널을 재시작하면 끝입니다. Python 설치, pip, venv 전부 필요 없습니다.

> MFA/SSO 브라우저 로그인용 Chromium은 첫 사용 시 자동 설치됩니다.
> Windows 사용자: [Windows 설치 가이드](./docs/WINDOWS_INSTALL.ko.md)를 참조하세요.

---

## 바로 쓰기

수동 설치를 한다면, 먼저 installer가 클라이언트 설정까지 써 주는 경로를 쓰는 것이 가장 쉽습니다.

클론 필요 없습니다. 한 줄 — macOS, Linux, Windows 전부 동작:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

`opencode` 대신 사용 중인 클라이언트 이름(`claude-code`, `codex`, `cursor`, `gemini` 등)을 넣으세요. installer가 기존 설정 파일에 ServiceNow 엔트리를 병합하고, 지원 클라이언트면 스킬도 설치합니다.

전역 설치가 필요할 때만 `--scope global`을 추가하세요. 기본값은 프로젝트 단위 설치입니다.

나중에 제거하려면 해당 클라이언트용 제거 명령을 실행하세요:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp remove opencode
```

전역 설치를 제거할 때는 `--scope global`을 함께 사용하세요. MCP 설정만 지우고 스킬은 유지하려면 `--keep-skills`를 추가하면 됩니다.

첫 브라우저 인증 도구 호출 시 Okta/Entra ID/SAML/MFA 로그인 창이 뜹니다. Chromium은 자동 설치됩니다. 세션은 유지되어 매번 재로그인할 필요 없습니다.

> AI가 끝까지 안내하게 하려면 위의 [AI 자동 설치](#ai-자동-설치)를 사용하세요. 클라이언트 설정 없이 서버만 직접 실행하려면 [CLI 레퍼런스](#cli-레퍼런스)를 참고하세요.

---

## MCP 클라이언트 설정

> 권장: 위의 AI 자동 설치 또는 `servicenow-mcp setup <client> ...`를 먼저 사용하세요. 아래 복사-붙여넣기 설정은 직접 점검하거나 수동 복구가 필요할 때 쓰는 용도입니다.

프로젝트마다 다른 ServiceNow 인스턴스에 접속할 수 있습니다. **프로젝트 디렉토리**에 설정 파일을 두세요.

| 클라이언트 | 프로젝트 설정 | 글로벌 설정 | 포맷 |
|-----------|-------------|-----------|------|
| Claude Code | `.mcp.json` | `~/.claude.json` | JSON |
| Zed | ⬜ | `~/.config/zed/settings.json` | JSON |
| OpenAI Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML |
| Gemini CLI | `.gemini/settings.json` | `~/.gemini/settings.json` | JSON |
| OpenCode | `opencode.json` | ⬜ | JSON |
| Claude Desktop | ⬜ | `claude_desktop_config.json` | JSON |
| AntiGravity | ⬜ | `~/.gemini/antigravity/mcp_config.json` | JSON |
| Docker | ⬜ | ⬜ | 환경변수 |

클라이언트별 복사 붙여넣기 설정: **[클라이언트 설정 가이드](docs/CLIENT_SETUP.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD`는 선택 — MFA 로그인 폼을 미리 채웁니다. Windows에서는 시스템 환경변수로 설정하세요.

---

## 인증 방법

ServiceNow 환경에 맞는 인증 방식을 선택하세요.

### 브라우저 인증 (MFA/SSO) — 기본

[바로 쓰기](#바로-쓰기)의 명령어가 브라우저 인증입니다. 추가 옵션:

| 플래그 | 환경변수 | 기본값 | 설명 |
|------|---------|--------|------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | 로그인 폼 사용자명 미리 채우기 |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | 로그인 폼 비밀번호 미리 채우기 |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | GUI 없이 브라우저 실행 |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | 로그인 타임아웃 (초) |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | 세션 TTL (분) |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | 영구 브라우저 프로파일 경로 |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | 사용자명을 알 수 있는 경우 사용자별 `sys_user` 조회, 그 외에는 `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | 세션 검증 엔드포인트 (비관리자 세션 401 회피) |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | 커스텀 로그인 페이지 URL |

### Basic 인증

MFA가 없는 PDI나 테스트 인스턴스용입니다.

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth 인증

현재 CLI는 OAuth password grant 입력 기준입니다.

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

`--token-url`을 지정하지 않으면 기본적으로 `https://<instance>/oauth_token.do`를 사용합니다.

### API Key 인증

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

기본 헤더는 `X-ServiceNow-API-Key` (`--api-key-header`로 변경 가능).

---

## 도구 패키지

`MCP_TOOL_PACKAGE`를 설정하여 도구 세트를 선택할 수 있습니다. 기본값: `standard`

모든 패키지는 `_extends`로 `standard` 읽기 전용 도구를 상속하고, 도메인별 쓰기 권한을 추가합니다. YAML 설정에서 상속을 사용하여 중복을 제거했습니다.

| 패키지명 | 도구 수 | 설명 |
| :--- | :---: | :--- |
| `none` | 0 | 도구를 의도적으로 비활성화하는 프로필 |
| `core` | 15 | 헬스체크, 스키마, 탐색, 핵심 조회만 담은 최소 읽기 전용 패키지 |
| `standard` | 45 | **(기본값)** 인시던트/변경/포털/로그/소스 분석 전반의 읽기 전용 패키지 |
| `service_desk` | 46 | standard + 인시던트/변경 운영 쓰기 |
| `portal_developer` | 55 | standard + 포털, 체인지셋, Script Include, 로컬 동기화 워크플로우 |
| `platform_developer` | 55 | standard + 워크플로우, Flow Designer, UI Policy, 인시던트/변경/스크립트 쓰기 |
| `full` | 66 | 가장 넓은 패키지 표면: 번들 `manage_*` 워크플로우 + 고급 운영 도구 |

현재 패키지에 없는 도구를 호출하면, 어느 패키지에서 사용 가능한지 안내합니다.

카테고리별 전체 도구 목록은 [도구 목록](docs/TOOL_INVENTORY.ko.md)에서 확인할 수 있습니다.

---

## CLI 레퍼런스

### 서버 옵션

| 플래그 | 환경변수 | 기본값 | 설명 |
|------|---------|--------|------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *필수* | ServiceNow 인스턴스 URL |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | 인증 모드: `basic`, `oauth`, `api_key`, `browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | 도구 패키지 |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP 요청 타임아웃 (초) |
| `--debug` | `SERVICENOW_DEBUG` | `false` | 디버그 로깅 |

### Basic 인증

| 플래그 | 환경변수 |
|------|---------|
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### OAuth

| 플래그 | 환경변수 |
|------|---------|
| `--client-id` | `SERVICENOW_CLIENT_ID` |
| `--client-secret` | `SERVICENOW_CLIENT_SECRET` |
| `--token-url` | `SERVICENOW_TOKEN_URL` |
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### API Key

| 플래그 | 환경변수 | 기본값 |
|------|---------|--------|
| `--api-key` | `SERVICENOW_API_KEY` | — |
| `--api-key-header` | `SERVICENOW_API_KEY_HEADER` | `X-ServiceNow-API-Key` |

### 스크립트 실행

| 플래그 | 환경변수 |
|------|---------|
| `--script-execution-api-resource-path` | `SCRIPT_EXECUTION_API_RESOURCE_PATH` |

---

## 최신 버전 유지

> **`uvx`는 마지막으로 다운로드한 버전을 캐시하여 계속 재사용합니다.**
> 새 릴리스가 나와도 자동으로 반영되지 않으므로, 직접 갱신해야 합니다.

```bash
# uvx 캐시를 최신 PyPI 릴리스로 갱신
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

갱신 후 **MCP 클라이언트를 재시작**해야 새 버전이 적용됩니다 (Claude Code, Cursor 등).

### 특정 버전 고정

```bash
# 예시: 1.8.17 버전으로 고정
uvx --from "mfa-servicenow-mcp==1.8.17" servicenow-mcp --version
```

MCP 클라이언트 설정에서 버전을 고정하려면 명령어에 `--from` 제약 조건을 추가하세요:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--from",
        "mfa-servicenow-mcp==1.8.17",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser"
      ]
    }
  }
}
```

---

## 보안 정책

모든 수정형 도구는 명시적 승인 없이는 실행되지 않습니다.

규칙:
1. `create_`, `update_`, `delete_`, `remove_`, `add_`, `move_`, `activate_`, `deactivate_`, `commit_`, `publish_`, `submit_`, `approve_`, `reject_`, `resolve_`, `reorder_`, `execute_` 계열은 승인 필요
2. 반드시 `confirm='approve'` 전달
3. 없으면 서버가 실행 전에 거부

이 정책은 어떤 도구 패키지를 쓰든 동일합니다.

### 포탈 조사 안전 정책

포탈 조사 도구는 기본적으로 보수적으로 동작합니다:

- `search_portal_regex_matches`는 기본적으로 widget만 조회하고 linked 확장은 꺼져 있으며 기본 제한도 작게 잡혀 있습니다.
- `trace_portal_route_targets`는 Widget -> Provider -> route target 근거를 최소 결과 형태로 넘길 때 권장됩니다.
- `download_portal_sources`도 명시적으로 요청하지 않으면 Script Include, Angular Provider를 따라가지 않습니다.
- 큰 포탈 스캔 요청은 서버에서 상한이 적용되며, 안전 기본값보다 넓은 요청에는 경고를 반환합니다.

패턴 매칭 모드:

| 모드 | 동작 |
|------|------|
| `auto` (기본값) | 일반 문자열은 literal로, regex처럼 보이는 패턴만 regex로 처리 |
| `literal` | 패턴을 항상 escape해서 안전하게 검색. 경로/토큰용으로 가장 무난 |
| `regex` | 정규식 연산자가 정말 필요할 때만 사용 |

---

## 성능 최적화

서버는 지연 시간과 토큰 사용량을 최소화하기 위해 여러 단계의 성능 최적화를 포함합니다.

### 직렬화

- **orjson 백엔드**: 모든 JSON 직렬화에 `json_fast` (orjson 우선, stdlib 폴백) 사용. stdlib `json` 대비 2-4배 빠른 loads/dumps.
- **컴팩트 출력**: 도구 응답을 들여쓰기 없이 직렬화하여 응답당 토큰 20-30% 절약.
- **이중 파싱 방지**: `serialize_tool_output`이 이미 컴팩트한 JSON 문자열을 감지하고 재직렬화를 생략.

### 캐싱

- **OrderedDict LRU 캐시**: `OrderedDict.popitem()`을 사용한 O(1) 제거 방식의 쿼리 결과 캐싱. 최대 256 엔트리, 30초 TTL, 스레드 안전.
- **도구 스키마 캐시**: Pydantic `model_json_schema()` 출력을 모델 타입별로 캐싱하여 반복 스키마 생성 방지.
- **레이지 도구 디스커버리**: 활성 `MCP_TOOL_PACKAGE`에 필요한 도구 모듈만 시작 시 임포트. 미사용 모듈은 완전히 건너뜀.

### 네트워크

- **HTTP 세션 풀링**: 20개 커넥션 풀의 영속 `requests.Session`, TCP keep-alive, TLS 세션 재개, gzip/deflate 압축.
- **병렬 페이지네이션**: `sn_query_all`이 첫 페이지를 순차적으로 가져와 전체 개수를 확인한 후, 나머지 페이지를 `ThreadPoolExecutor` (최대 4 워커)로 동시 조회.
- **동적 페이지 크기**: 남은 레코드가 단일 페이지(<=100)에 들어맞으면 페이지 크기를 확대하여 추가 라운드트립 방지.
- **배치 API**: `sn_batch`가 여러 REST 하위 요청을 단일 `/api/now/batch` POST로 결합. 150건 제한 시 자동 청크 분할.
- **병렬 청크 M2M 쿼리**: 위젯-프로바이더 M2M 조회를 100개 ID 단위로 분할하여 순차가 아닌 동시 실행.

### 스키마 및 시작

- **얕은 복사 스키마 주입**: 확인 스키마(`confirm='approve'`)를 `copy.deepcopy` 대신 경량 dict 복사로 주입하여 `list_tools` 오버헤드 감소.
- **카운트 생략 최적화**: 후속 페이지네이션 페이지에서 `sysparm_no_count=true`를 사용하여 서버 측 전체 개수 계산 생략.
- **페이로드 안전 장치**: 무거운 테이블(`sp_widget`, `sys_script` 등)에 자동 필드 클램핑과 제한 적용으로 컨텍스트 윈도우 오버플로 방지.

## 로컬 소스 검수

ServiceNow 앱의 전체 소스를 로컬에 다운로드하고 분석합니다 — 반복적인 API 호출 없이, 컨텍스트 낭비 없이.

```
Step 1: download_app_sources(scope="x_company_app")    → 서버사이드 코드 + 크로스-스코프 의존성까지 디스크에
Step 2: audit_local_sources(source_root="temp/...")     → 분석 + HTML 리포트
```

Step 1은 기본값 `auto_resolve_deps=True`로 동작합니다: 인-스코프 다운로드 후 모든
`.js/.html/.xml` 파일을 스캔해 번들에 없는 `sys_script_include`, `sp_widget`,
`sp_angular_provider`, `sys_ui_macro`를 스코프 상관없이 추가로 받아옵니다. 끌어온 의존성은
같은 트리에 저장되며 `_metadata.json`에 `"is_dependency": true`로 표시되어 Step 2 감사가
완전한 호출 그래프를 보게 됩니다. 인-스코프만 받고 싶으면 `auto_resolve_deps=False`로 설정.

### 생성되는 파일

| 파일 | 용도 |
|------|------|
| `_audit_report.html` | 셀프 컨테인드 다크 테마 HTML 리포트 — 브라우저에서 바로 열기 |
| `_cross_references.json` | 상호참조 — SI 호출 체인, GlideRecord 테이블 참조 |
| `_orphans.json` | 데드코드 후보 — 참조되지 않는 SI, 미사용 위젯 |
| `_execution_order.json` | 테이블별 BR/CS/ACL 실행 순서 |
| `_domain_knowledge.md` | 자동 생성 앱 프로파일 — 테이블 맵, 허브 스크립트, 경고 |
| `_schema/*.json` | 참조된 모든 테이블의 필드 정의 |

### 개별 다운로드 도구

각 소스 타입별 전용 다운로드 도구가 있습니다. 오케스트레이터로 전체를 받거나, 필요한 것만 선택:

| 도구 | 소스 |
|------|------|
| `download_portal_sources` | 위젯, Angular Provider, 연결된 Script Include |
| `download_script_includes` | Script Include (scope 전체) |
| `download_server_scripts` | Business Rule, Client Script, Catalog Client Script |
| `download_ui_components` | UI Action, UI Script, UI Page, UI Macro |
| `download_api_sources` | Scripted REST API, Processor |
| `download_security_sources` | ACL (스크립트 있는 것만) |
| `download_admin_scripts` | Fix Script, Scheduled Job, Script Action, Email Notification |
| `download_table_schema` | sys_dictionary 필드 정의 |

모든 다운로드는 잘림 없이 전체 소스를 디스크에 저장합니다. LLM 컨텍스트에는 요약만 반환됩니다.

---

## 스킬

스킬은 MCP 도구를 검증된 파이프라인으로 조합하는 LLM 실행 명세서입니다. 안전 게이트, 서브에이전트 위임, 컨텍스트 최적화를 포함합니다.

| | 도구만 | 스킬 + 도구 |
|---|---|---|
| 안전성 | LLM 판단 (운빨) | 게이트 강제 (스냅샷 → 프리뷰 → 적용) |
| 토큰 | 소스 전문 컨텍스트 | 서브에이전트 위임, 요약만 반환 |
| 정확도 | 도구 순서 추측 | 검증된 파이프라인 |
| 롤백 | 까먹으면 끝 | 스냅샷 필수 |

### 스킬 설치

```bash
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# Gemini CLI
servicenow-mcp-skills gemini

# uvx로 설치 없이 바로 실행
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

이 저장소의 `skills/` 디렉토리에서 20개 이상의 스킬 파일을 다운로드해 프로젝트 로컬 LLM 디렉토리에 설치합니다. 인증이나 별도 설정은 필요 없습니다.

| 클라이언트 | 설치 경로 | 자동 인식 |
|-----------|----------|----------|
| Claude Code | `.claude/commands/servicenow/` | 다음 시작 시 `/servicenow` 슬래시 명령으로 노출 |
| OpenAI Codex | `.codex/skills/servicenow/` | 다음 에이전트 세션에서 로드 |
| OpenCode | `.opencode/skills/servicenow/` | 다음 세션에서 로드 |
| Gemini CLI | `.gemini/skills/servicenow/` | 다음 세션에서 활성화 |

**동작 원리:** 각 스킬은 YAML 프론트매터(메타데이터) + 파이프라인 지시문으로 구성된 독립 Markdown 파일입니다. LLM 클라이언트가 설치 경로에서 이 파일을 읽어 호출 가능한 명령이나 스킬 트리거로 노출합니다.

**업데이트:** 동일한 설치 명령을 다시 실행하면 기존 파일을 모두 교체합니다 (클린 설치).

**삭제:** 설치 디렉토리를 삭제하면 됩니다 (예: `rm -rf .claude/commands/servicenow/`).

### 스킬 카테고리

| 카테고리 | 스킬 수 | 용도 |
|----------|---------|------|
| `analyze/` | 6 | 위젯 분석, 포탈 진단, 프로바이더 감사, 의존성 매핑, ESC 감사, **로컬 소스 검수** |
| `fix/` | 3 | 위젯 패치 (단계별 게이트), 디버깅, 코드 리뷰 |
| `manage/` | 8 | 페이지 레이아웃, SI 관리, 소스 내보내기, **앱 소스 다운로드**, 체인지셋, 로컬 동기화, 워크플로우 관리, **스킬 관리** |
| `deploy/` | 2 | 변경 요청 생명주기, 인시던트 분류 |
| `explore/` | 5 | 헬스 체크, 스키마 탐색, 라우트 추적, 플로우 트리거 추적, ESC 카탈로그 흐름 |

### 스킬 메타데이터

각 스킬에는 LLM이 실행을 최적화하는 데 쓰는 메타데이터가 포함됩니다:

```yaml
context_cost: low|medium|high    # → high = 서브에이전트 위임
safety_level: none|confirm|staged # → staged = 스냅샷/프리뷰/적용 필수
delegatable: true|false           # → 서브에이전트 실행 가능 여부
triggers: ["위젯 분석", "analyze widget"]  # → LLM 트리거 매칭
```

전체 스킬 레퍼런스는 [skills/SKILL.md](skills/SKILL.md)를 참조하세요.

### MCP 리소스 (내장 스킬 가이드)

스킬은 MCP 서버에서 **MCP 리소스**로도 직접 제공됩니다 — 클라이언트 측 설치 없이 사용 가능합니다. MCP 호환 클라이언트라면 누구나 on-demand로 조회하고 읽을 수 있습니다.

```
# 스킬 가이드 목록 조회
list_resources → skill://fix/widget-patching, skill://deploy/change-lifecycle, ...

# 특정 가이드 읽기
read_resource("skill://fix/widget-patching") → 안전 게이트 포함 전체 파이프라인
```

매칭되는 스킬 가이드가 있는 도구는 description에 `→ skill://...` 힌트가 표시됩니다. 가이드 본문은 **Pull 기반** — 클라이언트가 실제로 읽을 때까지 토큰 비용 0입니다.

| 기능 | 클라이언트 측 스킬 | MCP 리소스 |
|------|------------------|-----------|
| 사용 가능 조건 | 설치 명령 필요 | 내장, 모든 클라이언트 |
| 토큰 비용 | 클라이언트가 로딩 | 요청 시만 (0 until read) |
| 탐색 방법 | 슬래시 명령 / 트리거 | `list_resources` |
| 적합한 사용자 | 파워 유저, 슬래시 명령 | 범용 가이드 |

## Docker

API Key 인증만 가능 (MFA 브라우저 인증은 GUI가 필요하므로 컨테이너 불가).

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

로컬 빌드 방법: [클라이언트 설정 가이드](docs/CLIENT_SETUP.md#docker-api-key-only)

## 개발용 설치

로컬에서 직접 수정하려면:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uv run playwright install chromium
```

### 테스트 실행

```bash
uv run pytest
```

### 린팅 & 포맷팅

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

### 빌드

```bash
uv build
```

> Windows: [Windows 설치 가이드](./docs/WINDOWS_INSTALL.ko.md) 참조

---

## 상세 문서

- [LLM 설정 가이드](docs/llm-setup.ko.md) — AI가 진행하는 한 줄 설치 흐름
- [클라이언트 설정 가이드](docs/CLIENT_SETUP.ko.md) — installer 우선 설치 + 수동 복구용 설정 예시
- [도구 목록](docs/TOOL_INVENTORY.md) — 전체 도구 카테고리/패키지별 목록
- [Windows 설치 가이드](docs/WINDOWS_INSTALL.ko.md)
- [서비스 카탈로그 가이드](docs/catalog.md) — 카탈로그 CRUD 및 최적화
- [변경 관리 가이드](docs/change_management.md) — 변경 요청 생명주기 및 승인
- [워크플로우 관리](docs/workflow_management.md) — 레거시 워크플로우 및 Flow Designer 도구
- [English README](./README.md)

---

## 관련 프로젝트 및 참고

- 이 저장소의 일부 도구는 기존 내부/레거시 ServiceNow MCP 구현들을 정리하고 재구성한 결과물입니다. 현재 표면은 번들된 `manage_*` 도구를 중심으로 정리되어 있습니다 ([tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py) 참조).
- 개발자 생산성 기능, 특히 서버 소스 조회 흐름은 [SN Utils](https://github.com/arnoudkooi/SN-Utils)의 아이디어를 참고해 설계했습니다. 다만 이 프로젝트는 SN Utils 코드를 포함하거나 재배포하지 않습니다.
- 이 프로젝트는 브라우저 확장 UX 자체보다 MCP 서버 사용 시나리오에 초점을 둡니다. ServiceNow 화면 안에서 바로 쓰는 생산성 기능이 필요하면 SN Utils를 함께 사용하는 것도 좋은 선택입니다.

---

## 라이선스

Apache License 2.0
