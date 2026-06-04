# MFA ServiceNow MCP

[English](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md) | [한국어](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md)

MFA를 우선으로 지원하는 ServiceNow MCP 서버입니다. 실제 브라우저(Playwright)로 로그인하기 때문에 Okta, Entra ID, SAML 등 어떤 MFA/SSO 환경에서도 그대로 동작합니다. MFA를 강제하는 보안 정책 때문에 API Key 발급이 어려운 환경에서도 업무를 이어갈 수 있도록 만든 도구입니다. (headless·Docker 환경에서는 API Key 인증도 함께 지원합니다.)

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

> [!WARNING]
> **개인용으로 만든 도구라, 사용에 따른 책임은 전적으로 사용자에게 있습니다.** 제작자 본인의 작업 방식에 맞춰 만들었습니다. 위험을 줄이는 장치(읽기 전용 기본값, 쓰기 가드, dry-run 미리보기, 모든 쓰기에 `confirm='approve'` 확인 단계)는 갖췄지만, **실제 운영 중인 ServiceNow 인스턴스에 그대로 반영**됩니다. 잘못 쓰면 되돌리기 어려운 변경이 생길 수 있으니, 쓰기를 승인하기 전에 도구가 무슨 일을 하는지 꼭 직접 확인하세요. 보증 없이 "있는 그대로" 제공됩니다(Apache-2.0, [LICENSE](LICENSE)).

---

## 목차

- [주요 특징](#주요-특징)
- [설치](#설치)
- [필수 준비 사항](#필수-준비-사항)
- [MCP 클라이언트 설정](#mcp-클라이언트-설정)
- [인증 방법](#인증-방법)
- [도구 패키지](#도구-패키지)
- [CLI 레퍼런스](#cli-레퍼런스)
- [최신 버전 유지](#최신-버전-유지)
- [보안 정책](#보안-정책)
- [성능 최적화](#성능-최적화)
- [로컬 소스 검수](#로컬-소스-검수)
- [스킬](#스킬)
- [Docker](#docker)
- [개발용 설치](#개발용-설치)
- [상세 문서](#상세-문서)
- [관련 프로젝트 및 참고](#관련-프로젝트-및-참고)
- [라이선스](#라이선스)

---

## 설치

두 단계: **설치**, 그다음 **MCP 클라이언트 설정파일에 서버 추가**. 별도 installer 명령도, 클라이언트별 플래그도 없습니다.

### 1. 설치

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # 서버 fetch + 검증
uvx --with playwright playwright install chromium                                   # MFA/SSO 로그인용 Chromium
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # 서버 fetch + 검증
uvx --with playwright playwright install chromium                                   # MFA/SSO 로그인용 Chromium
```

`uv` 설치 + 서버 fetch·검증 + Chromium 다운로드를 한 번에 끝냅니다. fetch에 `--with playwright`를 붙여 아래 런타임 config와 같은 env를 캐시하므로 첫 클라이언트 시작이 즉시 뜹니다(미리 안 받으면 첫 호출 때 받느라 handshake timeout 위험).

> **가이드 설치.** 플래그 없이 `servicenow-mcp setup`을 실행하면 번호 메뉴로 안내합니다(클라이언트·인증 방식을 번호나 이름으로 선택 — 자유 입력으로 헤맬 일 없음). 영어/한국어 지원(로케일 자동 감지, `SERVICENOW_MCP_LANG=ko|en`으로 강제).

### 2. MCP 클라이언트 설정

클라이언트 설정파일에 서버를 추가하세요 — 본인 클라이언트를 골라 복붙하면 됩니다. 필수 env는 2개뿐이고, `MCP_TOOL_PACKAGE`는 생략하면 `standard`가 기본이라 다른 패키지가 필요할 때만 적으면 됩니다.

**Claude Code** — `.mcp.json` (프로젝트 루트) / `~/.claude.json` (전역):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

**Codex** — `.codex/config.toml` (프로젝트) / `~/.codex/config.toml` (전역):

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
```

**OpenCode** — `opencode.json` (프로젝트 루트):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

다른 클라이언트(Cursor, VS Code, Gemini, Zed 등)와 전체 env 옵션(인증 방식, 도구 패키지)은 [MCP 클라이언트 설정](#mcp-클라이언트-설정) 참고.

그다음 클라이언트를 재시작하세요. 첫 브라우저 도구 호출 시 Okta/Entra ID/SAML/MFA 로그인 창이 뜹니다. 세션은 유지되어 매번 재로그인할 필요 없습니다.

> AI에게 맡기고 싶으면? Claude Code / Cursor / Codex 등에 붙여넣으세요:
> `Install and configure mfa-servicenow-mcp following https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md`
> 사내망이 uvx/PyPI를 막으면 [릴리즈 zip/exe](#설치-사내망--오프라인) 사용.

---

## 주요 특징

- **브라우저 인증** — MFA/SSO 환경 지원 (Okta, Entra ID, SAML, MFA)
- **4가지 인증 모드**: Browser, Basic, OAuth, API Key
- **등록 도구 66개**, **실사용 패키지 6개**와 비활성 `none` 프로필 — 최소 읽기 전용부터 넓은 번들 CRUD까지
- **16개 워크플로우 스킬** — 안전 게이트, 서브에이전트 위임, 검증된 파이프라인
- **Streamable HTTP transport** — 기본 stdio는 그대로 두고, HTTP 지원 클라이언트/브리지에는 `/mcp` 엔드포인트 제공
- **로컬 소스 검수** — HTML 리포트, 상호참조 그래프, 데드코드 탐지, 도메인 지식 자동 생성
- **권위 관계 그래프를 디스크에** — `_graph.json`(위젯→Angular Provider, 라이브 M2M 기반)과 `_page_graph.json`(페이지→위젯, `sp_instance` 기반)으로 LLM이 인스턴스에 다시 묻지 않고 의존성 질문을 오프라인으로 답합니다
- **증분 동기화** (`incremental=True`) — 지난 동기화 이후 바뀐 레코드만 다시 받음(`sys_updated_on` 워터마크, `git pull` 방식); `reconcile_deletions=True`로 인스턴스에서 삭제된 레코드 경고
- **크로스-스코프 의존성 자동 해석** — `download_app_sources`가 앱 코드에서 참조하는 글로벌 스코프의 Script Include, Widget, Angular Provider, UI Macro까지 함께 받아 로컬 번들을 분석에 자족적으로 만듭니다
- **첨부파일 다운로드** (`download_attachment`) — 레코드 첨부파일(xlsx, PDF, Word 등)을 attachment sys_id 또는 부모 `table`+`record`로 받아 로컬 디스크에 저장. 레코드의 첨부를 자동 해석하고 바이트를 디스크에 쓰므로 LLM은 `saved_path`에서 파일을 읽습니다
- **Dry-run 프리뷰** — 모든 쓰기 도구에서 `dry_run=True` 지원. 실행 전 필드 단위 diff, 의존성 카운트, 정확도 노트를 반환합니다. 읽기 전용 API만 사용하므로 모든 인증 모드에서 동작.
- `confirm='approve'` 기반 안전한 수정 승인 정책
- 페이로드 안전 제한, 필드별 절단, 총 응답 한도 (200K 문자)
- 일시적 네트워크 오류 자동 재시도 (백오프)
- core, standard, service desk, 포탈 개발자, 플랫폼 개발자용 도구 패키지 — `full`은 고급 사용자 전용 ([경고 참고](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.ko.md))
- 개발자 도구: 활동 추적, 미커밋 변경사항, 의존성 매핑, 일일 요약
- 핵심 ServiceNow 아티팩트 테이블 전체 커버리지 ([지원 테이블](#지원하는-servicenow-테이블) 참조)
- CI/CD: 자동 태깅, PyPI 퍼블리싱, Docker 멀티플랫폼 빌드

### 지원하는 ServiceNow 테이블

| 아티팩트 유형 | 테이블명 | 소스 검색 | 개발자 추적 | 안전 제한 (대형 테이블) |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_script_client` | ✅ | ✅ | 🛡️ |
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

## 설치 (사내망 / 오프라인)

대부분은 위 [설치](#설치) (uvx)면 충분합니다. 릴리즈 zip은 `uvx`나 PyPI가 사내 보안에 막힐 때**만** 쓰세요.

### 릴리즈 zip/exe (로컬 설치)

`uvx`나 PyPI 접속이 막히는 사내망에서 사용하는 경로입니다. 릴리즈 zip에는 **PyInstaller로 빌드된 단일 실행 파일**만 들어 있습니다 — Python 설치 불필요, 설치 스크립트 없음, 시스템 캐시 오염 없음. 실행 파일이 자기 옆 `ms-playwright/` 폴더를 자동으로 인식하므로 설치 절차는 "풀고, MCP 클라이언트의 `command`에 경로 박는 것" 두 가지뿐입니다.

#### 1. 다운로드

실행 파일은 [최신 릴리즈](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest)에 있습니다. Chromium 번들(네트워크가 Playwright의 Chromium 자동 다운로드까지 막을 때만 필요)은 ~150MB라 매 릴리즈에 다시 붙이지 않고 — Playwright 버전 바뀔 때만 갱신되는 고정 [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) 릴리즈에서 받으세요.

| 플랫폼 | 필수 (최신 릴리즈) | Chromium도 막히면 추가로 (chromium-bundle 릴리즈) |
|--------|---------------------|---------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel/Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

#### 2. 아래 폴더 구조로 풀기

본인이 관리하는 안정적인 경로면 어디든 OK (`~/apps/servicenow-mcp/`, `D:\Tools\servicenow-mcp\` 등). **zip은 미리 다 풀어두세요** — `.zip` 파일을 실행 파일 옆에 남겨두지 말고. Chromium zip을 푼 폴더 이름은 `ms-play`로 시작하고 안에 `chromium-*` 서브디렉토리만 있으면 OK — unzip 기본 동작이 만드는 이름 그대로 둬도 됩니다:

```
~/apps/servicenow-mcp/                                  (본인이 정하는 경로)
├── servicenow-mcp                                      ← 플랫폼 zip에서 (Windows는 .exe)
└── ms-playwright-chromium-linux-x64-1.13.7/            ← 기본 추출 이름 그대로 OK
    └── chromium-1185/                                  (하나만 있으면 됩니다)
        └── …
```

정리해 두고 싶으면 폴더 이름을 `ms-playwright/`로 바꿔도 됩니다. 둘 다 동작 — 실행 파일이 시작 시 자기 옆 `ms-play*` 디렉토리를 글롭으로 찾고, 안에 `chromium-*` 서브디렉토리가 있으면 그 경로로 `PLAYWRIGHT_BROWSERS_PATH`를 **현재 프로세스에만** 설정합니다. 디스크에 아무것도 쓰지 않고, MCP 클라이언트 설정 파일도 절대 건드리지 않고, 시스템 표준 Playwright 캐시(`~/.cache/ms-playwright`, `%LOCALAPPDATA%\ms-playwright`) 도 건드리지 않습니다. Chromium 번들을 안 받았으면 Playwright 자체 탐색에 맡기거나 `playwright install chromium`을 별도로 돌리세요.

#### 3. 동작 확인

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

버전이 찍히면 바이너리 쪽은 끝 — 남은 건 설정 파일 한 곳뿐입니다.

#### 4. MCP 클라이언트에 직접 연결 (복붙)

[설치 섹션](#설치)의 uvx 설정을 그대로 쓰고 `command`만 실행 파일 절대 경로로 바꾸면 됩니다. env 블록은 동일. Claude Code 예시:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "/home/you/apps/servicenow-mcp/servicenow-mcp",
      "args": [],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}
```

Windows라면 `"command"`를 `"C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe"`로.

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD`는 선택(MFA 폼 prefill). Chromium을 실행 파일 옆이 아닌 위치에 두었다면 env에 `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"` 추가. Codex(TOML)·OpenCode·Cursor·VS Code Copilot·Gemini·Zed 설정: [클라이언트 설정 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.ko.md).

#### Chromium 대체 (선택)

Chromium zip을 받지 못했고 사내 망에서 Playwright 자동 다운로드도 막힌다면, Python이 가능한 PC에서 같은 구조로 디렉토리를 만들어 두세요:

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

번들 zip을 푼 것과 동일한 `ms-playwright/chromium-*/…` 구조가 만들어지므로 자동 인식이 그대로 동작합니다.

> Windows 사용자: PATH/백신 관련 주의사항은 [Windows 설치 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.ko.md)를 참조하세요.

---

## MCP 클라이언트 설정

> 권장: 위의 [설치](#설치) 섹션 사용. 아래 복사-붙여넣기 설정은 직접 점검하거나 수동 복구가 필요할 때 쓰는 용도.

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

클라이언트별 복사 붙여넣기 설정: **[클라이언트 설정 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.ko.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD`는 선택 — MFA 로그인 폼을 미리 채웁니다. Windows에서는 시스템 환경변수로 설정하세요.

#### 한 클라이언트에서 여러 인스턴스 (dev / test / prod)

위 예시는 단일 인스턴스 — 그게 기본입니다. 한 클라이언트에서 여러 인스턴스를 오가려면 `SERVICENOW_INSTANCE_CONFIG`(alias → 설정)에 나열하고 `SERVICENOW_ACTIVE_INSTANCE`로 활성 인스턴스를 고르세요. alias마다 **자체 자격증명**(`username` / `password` / `auth_type` / `api_key`)을 가질 수 있고, `${ENV}` 참조로 비밀번호를 JSON 밖에 둘 수 있습니다. 기존 단일 인스턴스 `SERVICENOW_INSTANCE_URL` 방식도 폴백으로 그대로 동작합니다.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mfa-servicenow-mcp@latest"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

`SERVICENOW_ACTIVE_INSTANCE`가 쓰기가 닿는 인스턴스이고, 읽기 도구는 `instance="test"`로 다른 인스턴스를 들여다볼 수 있습니다. 전체 규칙(쓰기 게이트·비교·`${ENV}`): [읽기 전용 데이터 비교 모드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md#읽기-전용-데이터-비교-모드).

---

## 인증 방법

ServiceNow 환경에 맞는 인증 방식을 선택하세요.

### 브라우저 인증 (MFA/SSO) — 기본

[설치](#설치)의 명령어가 브라우저 인증입니다. 추가 옵션:

| 플래그 | 환경변수 | 기본값 | 설명 |
|------|---------|--------|------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | 로그인 폼 사용자명 미리 채우기 |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | 로그인 폼 비밀번호 미리 채우기 |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | GUI 없이 브라우저 실행 |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | 로그인 타임아웃 (초) |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | 세션 TTL (분) |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | Chromium 프로필 경로 오버라이드. 거의 쓸 일 없음 — 설정 전 아래 샌드박스 주의사항 참고. |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | 사용자명을 알 수 있는 경우 사용자별 `sys_user` 조회, 그 외에는 `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | 세션 검증 엔드포인트 (비관리자 세션 401 회피) |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | 커스텀 로그인 페이지 URL |

#### 호스트·인스턴스 간 로그인 공유 — 실제 동작

서버는 `~/.mfa_servicenow_mcp/` 아래에 두 가지를 캐시합니다 — Playwright 프로필(Chromium SSO 쿠키)과 세션 JSON(다음 시작 시 재사용하는 파싱된 쿠키). 둘 다 **인스턴스 + 사용자명 단위로 분리**됩니다 — 파일명이 `profile_<host>_<user>`, `session_<host>_<user>.json`.

이 분리 덕분에 **별도 설정 없이** 두 가지가 자동으로 됩니다:

- **여러 호스트가 로그인 하나를 공유.** 같은 머신의 Claude Code와 Codex는 둘 다 `~/.mfa_servicenow_mcp/`를 가리키므로, 먼저 로그인한 쪽이 세션을 쓰면 다른 쪽이 그대로 재사용 — MFA 두 번 안 뜸.
- **인스턴스/자격증명이 다르면 자동 격리.** 인스턴스+유저마다 프로필·세션 파일이 따로라 dev와 test(또는 계정 두 개)가 절대 충돌 안 함. 인스턴스가 여러 개면 `SERVICENOW_INSTANCE_CONFIG`(JSON)로 설정하세요 — alias마다 캐시가 분리됩니다. 프로필 경로로 관리하는 게 **아닙니다**.

**로그인 "공유"하려고 `SERVICENOW_BROWSER_USER_DATA_DIR`를 설정하지 마세요.** 이 값은 프로필 경로를 그대로 덮어써서 인스턴스별 분리를 무력화합니다 — 실행하는 모든 인스턴스가 Chromium 프로필 하나에 강제로 묶여 쿠키가 충돌합니다. 유일하게 정당한 용도는 좁은 케이스 하나뿐 — **샌드박스** 호스트(예: macOS의 Claude Desktop)가 `HOME`을 컨테이너 경로로 리매핑해서 그쪽 `~/.mfa_servicenow_mcp/`가 터미널과 안 맞을 때. 이 단일 인스턴스 케이스에서만 샌드박스 호스트를 실제 home 경로로 지정합니다:

```bash
# 샌드박스가 HOME을 리매핑한 경우 + 호스트당 단일 인스턴스일 때만
export SERVICENOW_BROWSER_USER_DATA_DIR="/Users/you/.mfa_servicenow_mcp/profile_acme"
```

인스턴스를 둘 이상 돌리면 이 값은 비워두고 인스턴스별 자동 분리에 맡기세요.

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

`MCP_TOOL_PACKAGE`로 서버가 노출할 도구 세트를 선택합니다. **기본값: `standard`** — 대부분의 사용자는 별도 설정이 필요 없습니다.

> [!WARNING]
> **`standard` 위의 패키지는 전부 쓰기 권한을 부여하는 고급 옵션입니다.** `service_desk`, `portal_developer`, `platform_developer`, `full` 모두 AI 에이전트가 레코드를 생성·수정·삭제할 수 있게 하며, `full`은 모든 도메인에서 동시에 가능합니다. 대부분의 사용자는 읽기 전용 기본값 `standard`에 머물고, 작업에 꼭 필요한 가장 좁은 쓰기 패키지로만 올리세요.

읽기 전용 (안전한 기본값):

| 패키지명 | 도구 수 | 설명 |
| :--- | :---: | :--- |
| `none` | 0 | 도구를 의도적으로 비활성화하는 프로필 |
| `core` | 12 | 헬스체크, 스키마, 탐색, 핵심 조회만 담은 최소 읽기 전용 패키지 |
| `standard` | 29 | **(기본값)** 인시던트/변경/포털/로그/소스 분석 읽기 전용 |

⚠️ 쓰기 가능 (고급 — 생성/수정/삭제 권한 부여):

| 패키지명 | 도구 수 | 설명 |
| :--- | :---: | :--- |
| `service_desk` | 31 | ⚠️ standard + 인시던트/변경 운영 쓰기 |
| `portal_developer` | 40 | ⚠️ standard + 포털, 체인지셋, Script Include, 로컬 동기화 쓰기 |
| `platform_developer` | 45 | ⚠️ standard + 워크플로우, Flow Designer, UI Policy, 인시던트/변경/스크립트 쓰기 |
| `full` | 59 | ⚠️ **가장 고급** — 모든 도메인의 쓰기 도구 전체를 동시에 |

일반 도구는 서버 프로세스 하나당 하나의 active ServiceNow 인스턴스에만 연결됩니다. 안전을 위해 요청별 쓰기 라우팅으로 인스턴스를 오가는 방식은 지원하지 않습니다.

### 읽기 전용 데이터 비교 모드

개발/테스트 데이터 차이를 비교해야 할 때 `SERVICENOW_INSTANCE_CONFIG`로 named instance를 설정할 수 있습니다. `SERVICENOW_ACTIVE_INSTANCE`는 여전히 필요합니다.

글로벌 두 개, 인스턴스별 하나로 정리됩니다:

- **툴 surface는 글로벌** — `MCP_TOOL_PACKAGE` 하나로 결정. 서버 프로세스당 active 인스턴스는 항상 하나라 인스턴스별 tool package는 없습니다.
- **쓰기 권한은 인스턴스별** — alias마다 `allow_writes`. 호출 시점에 active 인스턴스 기준으로 강제됩니다 — 쓰기 도구가 로드돼 있어도 active 인스턴스가 `allow_writes: false`면 거부. 쓰기는 opt-in이라 `allow_writes`를 생략하면 읽기 전용입니다.
- **자격증명은 인스턴스별 + 글로벌 fallback** — alias에 `username` / `password` / `api_key`(및 `auth_type`)를 넣으면 오버라이드, 없으면 글로벌 `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` 등을 상속합니다. 모든 인스턴스가 같은 로그인을 쓰면 글로벌에 한 번만 넣고 alias는 자격증명 없이 두면 됩니다.

그 외 규칙:

- 쓰기 도구는 항상 active 인스턴스만 사용하고 인스턴스 선택 파라미터가 없습니다.
- **읽기 도구는 `instance` 인자를 받습니다** — 비-active 인스턴스를 한 번만 조회할 때 사용. 예: `dev`가 active인 채로 `sn_query(instance="test", table="incident", ...)`, `sn_health(instance="test")`. 패키지 안의 모든 읽기 도구에 노출됩니다(설정된 alias enum). 쓰기 도구엔 없음. **재시작 없이 다른 인스턴스 데이터를 들여다보는 방법이 이겁니다.**
- `list_instances`는 설정된 alias와 active를 보여줍니다. `compare_instances`는 alias 간 테이블을 read-only로 비교합니다.
- *active*(쓰기) 인스턴스 전환은 MCP 클라이언트 재시작 필요 — 서버 시작 시 한 번 읽고 런타임에 다시 안 읽습니다.

예시 — 글로벌 공용 로그인 + 인스턴스별 쓰기 게이트:

```bash
export MCP_TOOL_PACKAGE=standard
export SERVICENOW_USERNAME=svc_account
export SERVICENOW_PASSWORD='...'
export SERVICENOW_ACTIVE_INSTANCE=dev
export SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "allow_writes": false }
}'
```

특정 인스턴스에 별도 로그인을 주려면 해당 alias에 필드를 추가하세요 (`${ENV}` 참조가 해석되므로 비밀번호를 JSON에 평문으로 안 박아도 됩니다):

```json
"prod": { "url": "https://acme.service-now.com", "username": "prod_user", "password": "${SERVICENOW_PROD_PASSWORD}" }
```

dev/test drift 확인에는 `compare_instances`를 사용하세요. 다른 인스턴스에 실제 작업을 해야 한다면 프로젝트/클라이언트 설정을 분리하는 방식을 권장합니다.

현재 패키지에 없는 도구를 호출하면, 어느 패키지에서 사용 가능한지 안내합니다.

전체 레퍼런스(모든 패키지, 상속 구조, 설정 방법): [도구 패키지 고급 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.ko.md).

---

## CLI 레퍼런스

### 서버 옵션

| 플래그 | 환경변수 | 기본값 | 설명 |
|------|---------|--------|------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *필수* | ServiceNow 인스턴스 URL |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | 인증 모드: `basic`, `oauth`, `api_key`, `browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | 도구 패키지 |
| `--transport` | `SERVICENOW_MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` 또는 `http` |
| `--http-host` | `SERVICENOW_MCP_HTTP_HOST` | `127.0.0.1` | `--transport http` 호스트 |
| `--http-port` | `SERVICENOW_MCP_HTTP_PORT` | `8000` | `--transport http` 포트 |
| `--http-path` | `SERVICENOW_MCP_HTTP_PATH` | `/mcp` | Streamable HTTP 엔드포인트 경로 |
| `--http-allowed-hosts` | `SERVICENOW_MCP_HTTP_ALLOWED_HOSTS` | loopback hosts | DNS rebinding 보호용 Host allowlist (쉼표 구분) |
| `--http-disable-dns-rebinding-protection` | `SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | 신뢰된 네트워크 제어 뒤에서 DNS rebinding 보호 비활성화 |
| `--http-json-response` | `SERVICENOW_MCP_HTTP_JSON_RESPONSE` | `false` | SSE 스트림 대신 JSON 응답 반환 |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP 요청 타임아웃 (초) |
| `--debug` | `SERVICENOW_DEBUG` | `false` | 디버그 로깅 |

HTTP transport 예시:

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP 엔드포인트는 `http://127.0.0.1:8000/mcp`이고, `/health`는 가벼운 상태 응답을 반환합니다.

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

### 첫 브라우저 호출 시 Chromium 다운로드

uvx는 `mfa-servicenow-mcp`와 Playwright를 최신으로 받습니다. Playwright 새 버전이 나오면 다른 Chromium 빌드를 요구하게 되어, **첫 도구 호출**에서 ~150 MB 브라우저 바이너리를 받아오느라 MCP 호스트의 handshake timeout을 넘기는 경우가 있습니다:

```text
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

이를 피하려면 첫 호출 **전에** Chromium을 미리 설치하세요 (위 setup 명령이 이미 해줍니다):

```bash
uvx --with playwright playwright install chromium
```

#### 업그레이드

uvx가 `mfa-servicenow-mcp`와 `playwright`를 자동으로 최신 해석합니다 — 설정에서 올릴 버전이 없습니다. 갱신하려면:

```bash
# 새 Playwright가 새 빌드를 냈을 수 있으니 Chromium 재설치 후 MCP 클라이언트 재시작
uvx --with playwright playwright install chromium
```

> **왜 MCP 서버가 더 이상 Chromium을 자동 설치하지 않는가:** 예전에는 첫 도구 호출 시점에 `playwright install chromium`을 호출했습니다. 느린 회선에서는 그 subprocess가 호스트의 handshake 데드라인을 넘겨 "connection closed"로 실패했습니다. v1.13.1부터 MCP 서버는 Chromium이 없으면 **경고만** 출력합니다. `uvx --with playwright playwright install chromium`으로 미리 설치하세요(handshake timer 영향 없음).

---

## 보안 정책

모든 수정형 도구는 명시적 승인 없이는 실행되지 않습니다.

규칙:
1. `create_`, `update_`, `delete_`, `remove_`, `add_`, `move_`, `activate_`, `deactivate_`, `commit_`, `publish_`, `submit_`, `approve_`, `reject_`, `resolve_`, `reorder_`, `execute_` 계열은 승인 필요
2. 반드시 `confirm='approve'` 전달
3. 없으면 서버가 실행 전에 거부

이 정책은 어떤 도구 패키지를 쓰든 동일합니다.

### 쓰기 가드 (Write Guards)

confirm 게이트 외에도, 모든 쓰기는 **ServiceNow에 도달하기 전에** 위험한 쓰기를 막는 결정론적 가드를 거칩니다. 동시 수정·중복 생성 검사는 confirm 게이트 **이후**에 돌기 때문에, **승인되지 않은 쓰기는 네트워크를 전혀 건드리지 않습니다.** 각 가드는 사전 조회가 거부/실패하면 **fail-open** — 들여다보지 못했다는 이유로 정상 쓰기를 막지 않습니다.

| 가드 | 막는 것 | 우회 / 토글 |
|---|---|---|
| 동시 수정 (G3/G8) | **다른 사용자**가 최근 10분 내 수정한 레코드를 모르고 덮어쓰기. `sn_write`, `manage_portal_component`, `manage_*` 업데이트 계열 커버. 로컬 사본이 아닌 **원격 실시간 조회**(`sys_updated_by`/`sys_updated_on`)로 판정. | `SERVICENOW_CONCURRENT_EDIT_GUARD=off`; 윈도우는 `SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN`(기본 `10`) |
| 중복 생성 (G9) | ServiceNow가 유니크를 강제하지 않는 테이블(`sys_update_set`, `wf_workflow`, `sys_user_group`, `sys_user`)에 같은 이름으로 조용히 또 만들기. | `allow_duplicate='true'`를 넘기면 생성 |
| Flow Designer 직접 쓰기 (G6) | 플로우 스냅샷을 깨는 `sys_hub_*` 직접 `sn_write` — `manage_flow_designer` 강제. | — |
| Publish 계열 (G7) | 실수 publish/commit/push — 별도 `confirm_publish='approve'` 필요. | — |
| 인스턴스 간 푸시 | A에서 받은 로컬 소스를 B로 푸시(출처는 `_settings.json`/`_manifest.json`에서 읽음). | 올바른 인스턴스에서 재다운로드 |

전체 레이어는 `SERVICENOW_WRITE_GUARDS=off`로 끌 수 있습니다. 멀티 인스턴스 모드에서는 모든 쓰기 응답에 `instance_target`(다른 곳으로 라우팅된 읽기는 `instance_source`)이 붙어 어느 인스턴스에 닿았는지 항상 보입니다.

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

- **OrderedDict LRU 캐시**: `OrderedDict.popitem()`을 사용한 O(1) 제거 방식의 쿼리 결과 캐싱. 최대 256 엔트리, 30초 TTL (schema·scope·choice 등 안정적 메타데이터 테이블은 600초), 스레드 안전.
- **도구 스키마 캐시**: Pydantic `model_json_schema()` 출력을 모델 타입별로 캐싱하여 반복 스키마 생성 방지.
- **레이지 도구 디스커버리**: 활성 `MCP_TOOL_PACKAGE`에 필요한 도구 모듈만 시작 시 임포트. 미사용 모듈은 완전히 건너뜀.

### 네트워크

- **기본값 브라우저급 TLS**: HTTP 계층이 `curl_cffi`의 Chrome 임퍼서네이트 프로파일(기본 `chrome120`)로 동작해 TLS 핸드셰이크가 실제 브라우저와 동일 — Cloudflare/Akamai나 JA3 봇 탐지 뒤의 인스턴스가 stock Python `requests`를 거부해도 추가 설정 없이 동작. `SERVICENOW_TLS_IMPERSONATE=off`로 비활성화.
- **HTTP 세션 풀링**: TCP keep-alive와 gzip/deflate 압축의 영속 세션(대용량 JSON 응답 60-80% 절감). stock `requests` 옵트아웃 경로는 20개 커넥션 `HTTPAdapter`를 마운트.
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

> **팁 — `global` 포함 스코프 통째로 받기:** `scope="global"`을 주면 글로벌 스코프의 모든
> 레코드를 통으로 받습니다. 또는 앱 스코프를 유지한 채 `auto_resolve_deps`가 실제로 참조하는
> `global` 레코드만 끌어오게 둘 수도 있습니다. 어느 쪽이든 로컬 번들이 자족적이라 분석은
> 디스크 기준으로 완전히 오프라인 동작합니다.

### 증분 동기화 (Incremental)

매번 큰 앱을 전부 다시 받는 건 느리고 타임아웃 위험이 있습니다. `incremental=True`를 주면
**지난 다운로드 이후 바뀐 것만** 받습니다 — 새로 `clone`하지 않고 `git pull` 하는 것과 같습니다.
`download_app_sources`와 `download_portal_sources` 둘 다 지원합니다.

```
download_app_sources(scope="x_company_app")                      # 1회차: 전체 다운로드
download_app_sources(scope="x_company_app", incremental=True)    # 이후: 바뀐 레코드만
```

- **동작 방식:** 첫 다운로드 때 각 레코드의 `sys_updated_on`을 `_sync_meta.json`에 기록합니다.
  증분 실행 시 각 소스 패밀리는 `sys_updated_on >= <마지막 기록 시각>` 쿼리로 바뀐 레코드만
  받고(서버측 타임스탬프 — 클럭 스큐 없음), 안 바뀐 로컬 파일은 그대로 둡니다.
- **삭제:** 타임스탬프 델타로는 삭제된 레코드를 볼 수 없습니다. `reconcile_deletions=True`를 주면
  로컬엔 있는데 인스턴스엔 없는 레코드를 `deletion_candidates`로 경고합니다 — **자동 삭제는 절대 안 함.**
- **첫 실행 / 이전 데이터 없음:** 자동으로 전체 다운로드로 폴백합니다.
- 가끔 한 번씩은 전체(비증분) 다운로드로 완전 동기화를 맞춰주세요.

### 다운로드 안전성 & 완전성

다운로드는 오프라인 분석의 진실의 원천이라, 결정론적으로 동작하고 **불완전한데 완전한 척하지 않도록** 만들어졌습니다:

- **스코프 자동 해석.** 앱 **네임스페이스**(`x_company_app`), **표시명**("My App"), 또는 `sys_scope` sys_id 무엇을 넣어도 정식 네임스페이스로 해석돼, 로컬 폴더(`temp/<instance>/<namespace>/`)와 모든 쿼리가 매번 동일합니다. 해석값은 `scope_resolution`으로 반환.
- **조용한 캡 금지.** 어떤 소스 패밀리가 `max_records_per_type`에 도달하면 명확히 표시됩니다: `source_types` 안에 패밀리별 `capped: true`, `incomplete_types` 목록, 최상위 `complete: false`. 잘린 다운로드가 완전한 척할 수 없습니다.
- **인스턴스 간 / stale 가드.** 푸시백(`update_remote_from_local`)은 로컬 트리의 기록된 출처를 현재 연결 인스턴스와 대조하고, stale 로컬을 유지하는 resume 재다운로드는 실제 동기화 워터마크를 보존하고 드리프트를 숨기지 않고 경고합니다.
- **다운로드 시점 관계 메타.** 위젯→Angular Provider 엣지(`_graph.json`)와 위젯→CSS/JS 의존성 엣지(`_dependency_graph.json`)를 포털 다운로드 중 라이브 M2M 테이블에서 캡처 — 분석이 코드 추정이 아닌 실제 그래프를 읽습니다.
- **전이 의존성 깊이.** 크로스 스코프 의존성은 기본 `2`패스(보수적). `SERVICENOW_DEP_MAX_DEPTH`로 올림(상한 `1–6`)해 더 긴 A→B→C→D 체인 추적.
- **한 번에 그래프 생성.** `download_app_sources`에 `build_graph=True`를 주면 다운로드 직후 오프라인 관계 audit을 실행 — API 비용 0.
- **생성 → 로컬 동기화 안내.** 인스턴스에 위젯/페이지를 만들면서 **해당 스코프의 로컬 트리가 있을 때**, 생성 응답에 `local_out_of_sync` 메시지와 새 레코드를 로컬로 당기는 정확한 `download_portal_sources(...)` 명령이 붙습니다. 로컬 파일을 대신 쓰지는 않습니다.

### 생성되는 파일

| 파일 | 용도 |
|------|------|
| `_audit_report.html` | 셀프 컨테인드 다크 테마 HTML 리포트 — 브라우저에서 바로 열기 |
| `_cross_references.json` | 상호참조 — SI 호출 체인, GlideRecord 테이블 참조 |
| `_graph.json` | 라이브 M2M 기반 위젯→Angular Provider 엣지 (텍스트 추정이 아닌 권위 데이터) |
| `_dependency_graph.json` | `m2m_sp_widget_dependency` 기반 위젯→CSS/JS 의존성 엣지 |
| `_page_graph.json` | `sp_instance`에서 로컬로 도출한 페이지→위젯 배치 (API 호출 없음) |
| `_orphans.json` | 데드코드 후보 — 참조되지 않는 SI, 미사용 위젯 |
| `_execution_order.json` | 테이블별 BR/CS/ACL 실행 순서 |
| `_domain_knowledge.md` | 자동 생성 앱 프로파일 — 테이블 맵, 허브 스크립트, 경고 |
| `_schema/*.json` | 참조된 모든 테이블의 필드 정의 |
| `_sync_meta.json` | 증분 동기화를 구동하는 패밀리별 `sys_updated_on` 워터마크 |

### 개별 다운로드 도구

오케스트레이터로 전체를 받거나, `download_sources`로 특정 패밀리만 타겟 갱신:

| 도구 | 소스 |
|------|------|
| `download_app_sources` | 앱 전체 덤프 (모든 패밀리 + 포털 + 스키마 + 크로스 스코프 의존성) |
| `download_portal_sources` | 위젯, Angular Provider, 연결된 Script Include |
| `download_sources` (`families=`) | 타겟 갱신 — `script_includes`, `server_scripts`(BR/Client/Catalog Client), `ui`(Action/Script/Page/Macro), `api`(Scripted REST/Processor), `security`(ACL, 기본 스크립트 있는 것만), `admin`(Fix Script/Scheduled Job/Script Action/Notification/Transform) |
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

이 저장소의 `skills/` 디렉토리에서 16개 스킬 파일을 다운로드해 프로젝트 로컬 LLM 디렉토리에 설치합니다. 인증이나 별도 설정은 필요 없습니다.

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

전체 스킬 레퍼런스는 [skills/SKILL.md](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/skills/SKILL.md)를 참조하세요.

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

로컬 빌드 방법: [클라이언트 설정 가이드 — Docker](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.ko.md)

## 개발용 설치

로컬에서 직접 수정하려면:

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uvx --with playwright playwright install chromium
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

> Windows: [Windows 설치 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.ko.md) 참조

---

## 상세 문서

- [LLM 설정 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/llm-setup.ko.md) — AI가 진행하는 한 줄 설치 흐름
- [클라이언트 설정 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.ko.md) — installer 우선 설치 + 수동 복구용 설정 예시
- [도구 목록](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_INVENTORY.md) — 전체 도구 카테고리/패키지별 목록
- [Windows 설치 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.ko.md)
- [서비스 카탈로그 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/catalog.ko.md) — 카탈로그 CRUD 및 최적화
- [변경 관리 가이드](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/change_management.ko.md) — 변경 요청 생명주기 및 승인
- [워크플로우 관리](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/workflow_management.ko.md) — 레거시 워크플로우 및 Flow Designer 도구
- [English README](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md)

---

## 관련 프로젝트 및 참고

- 이 저장소의 일부 도구는 기존 내부/레거시 ServiceNow MCP 구현들을 정리하고 재구성한 결과물입니다. 현재 표면은 번들된 `manage_*` 도구를 중심으로 정리되어 있습니다 ([tool_utils.py](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/src/servicenow_mcp/utils/tool_utils.py) 참조).
- 이 프로젝트는 안전하고 diff 우선의 MCP 서버 사용 시나리오에 초점을 둡니다. 모든 쓰기는 confirm + write-guard(동시 수정·중복 생성·publish·Flow Designer)를 거치며, 소스 편집은 푸시 전에 실시간 원격과 diff합니다.

---

## 라이선스

Apache License 2.0
