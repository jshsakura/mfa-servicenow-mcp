# ServiceNow MCP Server

[English](./README.md) | [한국어](./README.ko.md)

**MFA 우선** ServiceNow MCP 서버. MFA/SSO가 필수인 기업 환경을 위해 만들었습니다 — 실제 브라우저(Playwright)로 인증하므로 Okta, Entra ID, SAML 등 어떤 대화형 로그인이든 그대로 동작합니다. headless/Docker 환경에서는 API Key 인증도 지원합니다. Claude Desktop, Claude Code, OpenCode, Gemini Code Assist, AntiGravity, OpenAI Codex에서 바로 사용 가능합니다.

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

```bash
# 설치 없이 바로 실행 (한 줄)
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser"
```

---

## 목차

- [주요 특징](#주요-특징)
- [필수 준비 사항](#필수-준비-사항)
- [바로 쓰기](#바로-쓰기)
- [MCP 클라이언트 설정](#mcp-클라이언트-설정)
- [인증 방법](#인증-방법)
- [도구 패키지](#도구-패키지)
- [CLI 레퍼런스](#cli-레퍼런스)
- [최신 버전 유지 (PyPI)](#최신-버전-유지-pypi)
- [보안 정책](#보안-정책)
- [Docker](#docker)
- [개발용 설치](#개발용-설치)
- [상세 문서](#상세-문서)
- [관련 프로젝트 및 참고](#관련-프로젝트-및-참고)
- [라이선스](#라이선스)

---

## 주요 특징

- **브라우저 인증** — MFA/SSO 환경 지원 (Okta, Entra ID, SAML, MFA)
- **4가지 인증 모드**: Browser, Basic, OAuth, API Key
- **98개 도구**, 5개 역할 기반 패키지 — 읽기 전용부터 전체 CRUD까지
- `confirm='approve'` 기반 안전한 수정 승인 정책
- 페이로드 안전 제한, 필드별 절단, 총 응답 한도 (200K 문자)
- 일시적 네트워크 오류 자동 재시도 (백오프)
- 표준 사용자, 운영자, 포탈 개발자, 플랫폼 개발자용 도구 패키지
- 개발자 도구: 활동 추적, 미커밋 변경사항, 의존성 매핑, 일일 요약
- 핵심 ServiceNow 아티팩트 테이블 전체 커버리지 ([지원 테이블](#지원하는-servicenow-테이블) 참조)
- CI/CD: 자동 태깅, PyPI 퍼블리싱, Docker 멀티플랫폼 빌드

### 지원하는 ServiceNow 테이블

| 아티팩트 유형 | 테이블명 | 소스 검색 | 개발자 추적 | 안전 제한 (대형 테이블) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | O | O | O |
| Business Rule | `sys_script` | O | O | O |
| Client Script | `sys_client_script` | O | O | O |
| UI Action | `sys_ui_action` | O | O | O |
| UI Script | `sys_ui_script` | O | O | O |
| UI Page | `sys_ui_page` | O | O | O |
| Scripted REST API | `sys_ws_operation` | O | O | O |
| Fix Script | `sys_script_fix` | O | O | O |
| Service Portal Widget | `sp_widget` | O | O | O |
| Angular Provider | `sp_angular_provider` | - | O | - |
| Update XML | `sys_update_xml` | O | - | - |

---

## 필수 준비 사항

서버를 등록하기 전에 아래 도구들이 설치되어 있는지 확인하세요.

### 1. `uv` 설치 (필수)

이 프로젝트는 [uv](https://astral.sh/uv)에 최적화되어 있습니다.

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

설치 후 터미널을 재시작하고 확인합니다:

```bash
uv --version
```

### 2. 브라우저 바이너리 설치 (`browser` 인증 필수)

MFA/SSO 환경에서 `auth-type: browser`를 사용하려면 로컬 시스템에 Chromium 브라우저 바이너리가 설치되어 있어야 합니다:

```bash
uvx playwright install chromium
```

> 최초 1회만 실행하면 됩니다. 바이너리는 모든 uvx 실행에서 공유됩니다.

### 3. Windows 전용 팁

Windows 사용자는 PowerShell에서 스크립트 실행 권한이 허용되어 있어야 합니다:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

상세한 Windows 설치 가이드는 [docs/WINDOWS_INSTALL.ko.md](./docs/WINDOWS_INSTALL.ko.md)에서 확인하세요.

---

## 바로 쓰기

대부분의 사용자는 Git으로 소스를 받을 필요가 **없습니다**. [uv](https://astral.sh/uv)만 있으면 MCP 클라이언트 설정에 바로 넣어 쓸 수 있습니다.

### 터미널에서 바로 실행 (한 줄)

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

### 로컬에 설치해서 계속 쓰기

```bash
uv tool install mfa-servicenow-mcp
servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
```

---

## MCP 클라이언트 설정

### Claude Desktop

`claude_desktop_config.json`에 아래처럼 넣으면 됩니다.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add servicenow -- \
  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

또는 프로젝트 루트의 `.mcp.json`에 추가:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ],
      "env": {
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### OpenCode / Gemini / Vertex AI

#### `uvx`로 실행

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
    }
  }
}
```

#### 체크아웃한 소스에서 바로 실행

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uv", "run", "--project", "/absolute/path/to/mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      },
      "enabled": true
    }
  }
}
```

> `SERVICENOW_BROWSER_USERNAME`, `SERVICENOW_BROWSER_PASSWORD`는 필수는 아니지만, MFA/SSO 로그인 화면에 계정을 미리 채우고 싶을 때 유용합니다.

### AntiGravity

AntiGravity Editor는 Claude Desktop 스타일의 `mcpServers` 설정을 사용합니다. 에디터 우측 에이전트 패널 상단의 **점 세 개(...)** -> **Manage MCP Servers** -> **View raw config**를 눌러 설정 파일을 편집할 수 있습니다.

- **macOS / Linux:** `~/.gemini/antigravity/mcp_config.json`
- **Windows:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_USERNAME": "your.username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> 설정을 저장한 후 AntiGravity의 MCP 관리 화면에서 **Refresh**를 눌러주세요.

### OpenAI Codex

`agents.toml` 파일에 추가합니다 (보통 `~/.codex/agents.toml` 또는 프로젝트 루트의 `.codex/agents.toml`):

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "https://your-instance.service-now.com",
  "--auth-type", "browser",
  "--browser-headless", "false",
  "--tool-package", "standard",
]
```

---

## 인증 방법

ServiceNow 환경에 맞는 인증 방식을 선택하세요.

### 브라우저 인증 (MFA/SSO)

Okta, Entra ID, SAML, MFA 같은 대화형 로그인 환경에 적합합니다.

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

브라우저 관련 옵션:

| 플래그 | 환경변수 | 기본값 | 설명 |
|------|---------|--------|------|
| `--browser-username` | `SERVICENOW_BROWSER_USERNAME` | — | 로그인 폼 사용자명 미리 채우기 |
| `--browser-password` | `SERVICENOW_BROWSER_PASSWORD` | — | 로그인 폼 비밀번호 미리 채우기 |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | GUI 없이 브라우저 실행 |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | 로그인 타임아웃 (초) |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | 세션 TTL (분) |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | 영구 브라우저 프로파일 경로 |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | `/api/now/table/sys_user?sysparm_limit=1&sysparm_fields=sys_id` | 세션 검증 엔드포인트 |
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

모든 패키지는 읽기 전용 도구 55개를 기본 포함하며, 상위 패키지는 도메인별 수정 권한을 추가합니다.

| 패키지명 | 도구 수 | 설명 |
| :--- | :---: | :--- |
| `standard` | 48 | **(기본값)** 읽기 전용 safe mode. 전 도메인 조회/분석 도구 포함 |
| `service_desk` | 52 | standard + 인시던트 생성/처리/해결/코멘트 |
| `portal_developer` | 58 | standard + 포탈/위젯 수정, Script Include 수정, 체인지셋 커밋/퍼블리시 |
| `platform_developer` | 71 | standard + 워크플로우 CRUD, UI Policy, 인시던트/변경관리 수정 |
| `full` | 86 | 전 도메인 수정/삭제 가능 |

현재 패키지에 없는 도구를 호출하면, 어느 패키지에서 사용 가능한지 안내합니다.

카테고리별 전체 도구 목록은 [Tool Inventory](docs/TOOL_INVENTORY.md)에서 확인할 수 있습니다.

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

## 최신 버전 유지 (PyPI)

이 프로젝트는 [PyPI](https://pypi.org/project/mfa-servicenow-mcp/)에 배포되며 시맨틱 버전을 따릅니다. 버전 태그(`v*`)가 push되면 GitHub Actions를 통해 자동 배포됩니다.

### `uvx`의 버전 동작 방식

`uvx`는 패키지를 **캐시**합니다. 실행할 때마다 자동으로 최신 버전을 가져오는 것은 **아닙니다**. 최신 버전을 확실히 받으려면:

```bash
# 현재 버전 확인
uvx --from mfa-servicenow-mcp servicenow-mcp --version

# 최신 PyPI 릴리스로 강제 갱신
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

### `uv tool` 업그레이드

`uv tool install`로 설치한 경우:

```bash
uv tool upgrade mfa-servicenow-mcp
```

### pip 업그레이드

```bash
pip install --upgrade mfa-servicenow-mcp
```

### 특정 버전 고정

안정성을 위해 특정 버전이 필요한 경우:

```bash
# uvx에서 버전 고정
uvx --from "mfa-servicenow-mcp==1.5.0" servicenow-mcp --version

# uv tool에서 버전 고정
uv tool install "mfa-servicenow-mcp==1.5.0"

# pip에서 버전 고정
pip install "mfa-servicenow-mcp==1.5.0"
```

### 버전 릴리스 프로세스

1. 버전은 `pyproject.toml`의 `version = "x.y.z"`에서 관리
2. `main` 브랜치에 push하면 CI가 해당 버전의 git 태그 `v{version}`을 자동 생성
3. 태그 push가 PyPI 배포와 GitHub Release 생성을 트리거
4. Docker 이미지 (standard + playwright 변형)가 `amd64`, `arm64`용으로 빌드

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

## Docker

Docker 이미지는 main 브랜치 푸시마다 `ghcr.io/jshsakura/mfa-servicenow-mcp`에 자동 배포됩니다.

> **참고:** 브라우저 인증(MFA/SSO)은 GUI 브라우저가 필요하므로 컨테이너 안에서 사용할 수 없습니다. MFA가 활성화된 ServiceNow 인스턴스는 Docker 환경에서 `api_key` 인증을 사용하세요.

### 바로 실행 (API Key)

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

### SSE 모드 (HTTP 서버)

```bash
docker run -p 8080:8080 \
  -e MCP_MODE=sse \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

### 로컬 빌드

```bash
docker build --target runtime -t servicenow-mcp .
```

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

- [도구 목록](docs/TOOL_INVENTORY.md) — 98개 도구 카테고리/패키지별 전체 목록
- [Windows 설치 가이드](docs/WINDOWS_INSTALL.ko.md)
- [서비스 카탈로그 가이드](docs/catalog.md) — 카탈로그 CRUD 및 최적화
- [변경 관리 가이드](docs/change_management.md) — 변경 요청 생명주기 및 승인
- [워크플로우 관리](docs/workflow_management.md) — 레거시 워크플로우 및 Flow Designer 도구
- [English README](./README.md)

---

## 관련 프로젝트 및 참고

- 이 저장소의 일부 도구는 기존 내부/레거시 ServiceNow MCP 구현들을 정리하고 재구성한 결과물입니다. 그 흔적은 [core_plus.py](./src/servicenow_mcp/tools/core_plus.py), [tool_utils.py](./src/servicenow_mcp/utils/tool_utils.py) 같은 모듈에서 볼 수 있습니다.
- 개발자 생산성 기능, 특히 서버 소스 조회 흐름은 [SN Utils](https://github.com/arnoudkooi/SN-Utils)의 아이디어를 참고해 설계했습니다. 다만 이 프로젝트는 SN Utils 코드를 포함하거나 재배포하지 않습니다.
- 이 프로젝트는 브라우저 확장 UX 자체보다 MCP 서버 사용 시나리오에 초점을 둡니다. ServiceNow 화면 안에서 바로 쓰는 생산성 기능이 필요하면 SN Utils를 함께 사용하는 것도 좋은 선택입니다.

---

## 라이선스

MIT License
