# MCP 클라이언트 설정

각 MCP 클라이언트별 상세 설정 가이드입니다. 모든 클라이언트는 동일한 MCP 서버를 사용하며, 설정 형식만 다릅니다.

> **여기서 시작하세요:** 모든 플랫폼에서 기본 설치는 `uvx`입니다. `uvx`가 아예 실행되지 않는다면 — 대개 Windows Smart App Control이 원인입니다 — `pip`으로 넘어가세요. 설치 경로는 이 두 가지입니다.

---

## 시작하기 전에

기본 설치는 `uvx`입니다. macOS, Linux, Windows에서 같은 흐름으로 설치와 MCP 설정을 맞춥니다.

### 1. uv 설치

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 서버 fetch + Chromium 설치

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # 서버 fetch + 검증
uvx --with playwright playwright install chromium                                   # MFA/SSO 로그인용 Chromium
```

첫 명령은 클라이언트가 쓰는 것과 같은 `--with playwright` env에 서버를 미리 받아 검증하므로 첫 시작이 즉시 뜹니다. 둘째 명령은 Chromium을 받습니다(같은 revision이 표준 캐시에 있으면 재다운로드 안 함).

#### uvx가 막힐 때 — `pip`

Windows [Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0)은 `uvx` 실행 자체를 막습니다: uvx는 실행할 때마다 서명 없는 임시 실행 파일을 풀어놓는데, SAC가 이걸 차단하기 때문입니다. Windows 업데이트 직후 uvx가 안 되기 시작했다면 십중팔구 이 문제입니다. 대신 pip으로 설치하세요:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

[python.org 인스톨러](https://www.python.org/downloads/)로 설치한 Python(서명됨, 3.10+)은 그대로 SAC를 통과합니다. 서버는 `python -m servicenow_mcp`로 실행하세요 — `servicenow-mcp` 콘솔 스크립트는 **쓰지 마세요**. pip이 만들어 주는 서명 없는 `.exe` shim이라 이것도 SAC가 막습니다.

> macOS/Linux에서 pip을 쓸 때 걸리는 건 하나뿐입니다. Homebrew나 배포판 기본 Python은 [PEP 668](https://peps.python.org/pep-0668/) 때문에 전역 설치를 거부합니다(`externally-managed-environment`). python.org 인스톨러를 쓰거나, 그냥 uvx를 유지하세요.

**PyPI 자체가 막혀 있다면** — 사내망이 패키지 인덱스를 차단하는 경우 — uvx든 pip이든 패키지를 받아올 방법이 없습니다. IT 부서에 `pypi.org`와 `files.pythonhosted.org` 허용을 요청하거나, 사내 인덱스에 미러링해 두고 `pip install --index-url`로 받아 쓰세요.

> Windows 사용자: 단계별 안내 + 프록시/백신 관련 주의사항은 [Windows 설치 가이드](WINDOWS_INSTALL.ko.md) 참조.

### 3. MCP 클라이언트 설정에 서버 추가

클라이언트 설정파일에 엔트리를 추가하세요 (별도 installer 명령 불필요). **어떤 방식으로 설치했든 `env` 블록은 동일합니다** — 위에서 고른 경로에 따라 `command`/`args`만 달라집니다:

| 설치 방식 | `command` | `args` |
|---|---|---|
| uvx (기본) | `uvx` | `["--with","playwright","--from","mfa-servicenow-mcp","servicenow-mcp"]` |
| pip (uvx 차단 시) | `python` | `["-m","servicenow_mcp"]` |

아래 클라이언트별 예시는 전부 uvx 형태입니다. pip으로 설치했다면 이 두 키만 바꾸고 나머지는 그대로 두세요.

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

클라이언트별 경로·형식(Codex TOML 등)은 아래에 있습니다. 추가 후 클라이언트를 재시작하세요.

### 동작 확인

클라이언트 설정 전에 서버가 정상 작동하는지 먼저 확인하세요:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"

# pip 설치: 첫 줄을 아래로 교체
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

서버가 시작되고 로그인용 브라우저 창이 열리면, 아래 클라이언트 설정으로 넘어갈 준비가 된 것입니다.

---

## 설정 가이드

> **`args`는 패키지 실행에만 사용합니다**. 인스턴스 URL, 인증 방식, 자격 증명은 모두 `env`(또는 `environment`)에 넣으세요. 이렇게 하면 args가 깔끔하게 유지되고, 프로젝트별로 다른 인스턴스에 쉽게 연결할 수 있습니다.

> **프로젝트 로컬 설정을 권장합니다**: 프로젝트 단위로 설정하면 각 프로젝트가 서로 다른 ServiceNow 인스턴스에 연결할 수 있습니다.

아래 내용은 `env` 안에서만 달라집니다. `command`/`args`는 [3단계](#3-mcp-클라이언트-설정에-서버-추가)에서 넣은 그대로 두면 됩니다 — 어떤 설치 경로를 택했든 마찬가지입니다.

### 프로파일 — 여기서 시작하세요

ServiceNow 인스턴스를 두 개 이상 다룬다면, **인스턴스마다 서버를 따로 띄우지 말고 프로파일을 설정하세요.** 환경마다 alias를 붙이고 active로 쓸 하나를 고르면 됩니다:

```json
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"prod\": { \"url\": \"https://acme-prod.service-now.com\", \"auth_type\": \"browser\" } }"
      }
```

이 블록 하나가 `SERVICENOW_INSTANCE_URL`을 대체하며, 이 가이드의 나머지 내용이 성립하는 전제가 됩니다:

- **운영은 키를 빼는 것으로 보호됩니다.** `allow_writes`가 없는 alias는 읽기 전용입니다. 위의 `prod`에는 애초에 쓸 수 없습니다 — 플래그를 깜빡했다고 운영 쓰기가 열리는 일은 생기지 않습니다.
- **재시작 없이 다른 인스턴스에 접근합니다.** 읽기 도구는 `instance` 인자를 받습니다: `dev`를 active로 둔 채 `sn_query(instance="prod", …)`.
- **환경 간 비교를 바로 합니다.** `compare_instances`는 같은 레코드를 두 alias에서 비교하고, `list_instances`는 모든 alias와 쓰기 플래그를 보여줍니다.
- **브라우저 로그인은 한 번.** 서버 프로세스마다 로그인하는 대신 세션을 alias들이 공유합니다.
- **active가 아닌 인스턴스로의 쓰기는 가드됩니다** — 조용히 넘어가는 법은 없습니다. 라우팅 규칙, `confirm_instance` 게이트, `${ENV}` 시크릿 참조는 [멀티 인스턴스 모드](#멀티-인스턴스-모드-비교--가드된-단일-호출-쓰기)를 참고하세요.

### 단일 인스턴스

인스턴스가 하나뿐이라면 프로파일은 건너뛰세요 — 변수 두 개가 설정의 전부입니다:

```json
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
```

이 형태도 그대로 동작하며 폐기 예정이 아닙니다. 위 프로파일 설정의 가장 단순한 경우일 뿐입니다.

### 연결 하나로 갈지, 여러 개로 갈지

프로파일은 모든 인스턴스를 **하나의** 클라이언트 연결 뒤에 둡니다. 대부분은 이걸 원합니다. 반대로 클라이언트 UI에서 눈에 띄게 구분되는 연결이 필요하다면 — `snow-dev`와 `snow-prd`를 별도 항목으로 두는 식 — [서버 엔트리 여러 개에 이름 붙이기](#서버-엔트리-여러-개에-이름-붙이기---server-name)를 보세요. 대신 `compare_instances`, 로그인 공유, `allow_writes` 게이트를 포기하게 되므로 UI 분리가 정말 필요할 때만 선택하세요.

---

## Streamable HTTP

기본 transport는 `stdio`입니다. 원격 MCP 클라이언트나 로컬 HTTP 브리지가 필요하면 Streamable HTTP로 실행할 수 있습니다.

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
# pip 설치: python -m servicenow_mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP 엔드포인트는 `http://127.0.0.1:8000/mcp`이고, `/health`는 가벼운 상태 응답을 반환합니다. 신뢰된 네트워크 제어 뒤에 둔 경우가 아니라면 기본 loopback 호스트를 유지하세요.

---

## 멀티 인스턴스 모드 (비교 + 가드된 단일 호출 쓰기)

`SERVICENOW_INSTANCE_CONFIG`로 named instance(예: `dev` / `test` / `prod` alias)를 설정하면, 한 세션에서 환경 간 비교도 하고 **원하는 인스턴스로 배포**도 할 수 있습니다 — active 인스턴스를 바꾸거나 서버를 재시작할 필요 없이. 단일 호출에 `instance=<alias>` 인자를 넘겨 라우팅합니다.

- **읽기 전용** 호출은 자유롭게 라우팅됩니다: `instance=test`면 active가 `dev`여도 `test`를 읽습니다.
- **비활성 인스턴스로의 쓰기**는 허용되지만 절대 조용히 안 됩니다. 그 한 호출에서 *타깃을 명시하고 승인*해야 합니다 — `instance=test confirm_instance=test confirm=approve` — 그리고 타깃이 `allow_writes=true`여야 합니다. 딱 그 한 번의 쓰기만 라우팅되고, 직후 active가 복원됩니다. 타깃/confirm 불일치나 read-only 타깃은 명시적 메시지로 거부되므로, dev/test/prod가 섞여도 엉뚱한 인스턴스에 안 씁니다.
- **쓰기는 타깃에서 검증됩니다.** 결과에 `target_instance`와 `landed` 판정이 실립니다: 툴이 푸시한 필드를 타깃에서 재조회해, 내용이 안 남았으면(예: `sp_*` Service Portal 필드 silent drop) `WRITE_NOT_LANDED`를 반환합니다. "성공"은 요청이 200을 받은 게 아니라 **의도한 인스턴스에 내용이 실제로 있음이 확인**됐다는 뜻입니다.
- `compare_instances`는 alias 간 레코드를 read-only로 비교하고, `list_instances`는 설정된 alias와 각자의 쓰기 플래그를 보여줍니다.
- `prod`는 의도적으로 운영 쓰기를 하려는 게 아니면 `allow_writes=false`로 두세요 — 그러면 플래그를 깜빡해도 운영 쓰기가 절대 열리지 않습니다.

> **다수** 레코드 승격(특히 Service Portal / scoped 테이블)은 레코드별 cross-instance 쓰기보다 Update Set을 쓰세요 — 소스에서 commit, 타깃 UI에서 retrieve + commit. 단일 Table-API 쓰기가 걸리는 per-table/SP ACL을 우회합니다.

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "auth_type": "browser", "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "auth_type": "browser", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "auth_type": "browser", "allow_writes": false }
}'
```

MCP 클라이언트 `env` 블록에서 인스턴스별 자격증명 (alias마다 자체 `username` / `password` / `auth_type` / `api_key`; `${ENV}`로 비밀번호를 JSON 밖에 보관; 단일 인스턴스 `SERVICENOW_INSTANCE_URL` 방식도 폴백으로 동작):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

비교 예시:

```json
{
  "source": "dev",
  "target": "test",
  "table": "sys_script_include",
  "key_field": "api_name",
  "fields": "api_name,name,active,script",
  "query": "sys_scope.scope=x_company_app"
}
```

비-active 인스턴스로의 단일 쓰기는 위의 가드된 `instance=<alias> confirm_instance=<alias> confirm=approve` 라우팅을 쓰세요. **다수** 레코드 승격은 레코드별 cross-instance 쓰기보다 Update Set을 권장합니다.

---

## 서버 엔트리 여러 개에 이름 붙이기 (`--server-name`)

위의 멀티 인스턴스 모드와는 구성 자체가 다릅니다. 멀티 인스턴스는 **하나의** 연결로 여러 인스턴스를 오가는 방식이고, 이 섹션은 **연결을 여러 개** 두는 방식입니다 — 인스턴스마다 프로세스 하나, 각각 자기 인스턴스에 고정됩니다. 클라이언트 UI에서 dev/stg/prd를 눈에 띄게 갈라놓고 싶을 때만 의미가 있습니다.

문제는 이겁니다. 모든 엔트리가 기본적으로 자신을 `ServiceNow`라고 알리기 때문에, 클라이언트는 로드 순서로 구분합니다 — `mcp_servicenow`, `mcp_servicenow2`, `mcp_servicenow3`. 이 번호는 재시작할 때마다 바뀔 수 있어서 **어느 연결이 운영인지 판단하는 근거로 삼을 수 없습니다.** `--server-name`으로 각각에 이름을 주세요:

```json
{
  "mcpServers": {
    "snow-dev": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-dev"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme-dev.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    },
    "snow-prd": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-prd"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

그러면 도구 이름이 `mcp_snow-dev_*` / `mcp_snow-prd_*`로 고정됩니다. 환경변수 `SERVICENOW_MCP_SERVER_NAME`도 같은 역할을 하며, 둘 다 설정되면 플래그가 우선합니다. 아무것도 지정하지 않으면 이름은 `ServiceNow` 그대로라 기존 설정은 계속 동작합니다.

**가능하면 프로파일 방식을 쓰세요.** 하나의 연결 안에서 인스턴스를 오가는 용도라면 [멀티 인스턴스 모드](#멀티-인스턴스-모드-비교--가드된-단일-호출-쓰기)가 권장 경로입니다: `compare_instances`, 브라우저 로그인 공유, alias별 `allow_writes` 가드는 이쪽에서만 얻을 수 있습니다. 프로세스를 나누면 이 중 어느 것도 못 씁니다 — 각 프로세스는 자기 인스턴스만 알고, 로그인도 따로 하며, 운영 쓰기를 막아주는 건 툴 패키지 설정 하나뿐입니다.

---

## Claude Desktop

| 범위 | 경로 |
|------|------|
| 전역 | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| 전역 | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> Claude Desktop은 프로젝트 로컬 설정을 지원하지 않습니다. 프로젝트별 설정이 필요하면 Claude Code를 사용하세요.

---

## Claude Code

| 범위 | 경로 |
|------|------|
| 전역 | `~/.claude.json` |
| 프로젝트 | 프로젝트 루트의 `.mcp.json` |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Zed

| 범위 | 경로 |
|------|------|
| 전역 | `~/.config/zed/settings.json` |

Zed에서 **Settings** > **MCP Servers**로 추가하세요:

```json
{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
    "env": {
      "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
      "SERVICENOW_AUTH_TYPE": "browser",
      "SERVICENOW_BROWSER_HEADLESS": "false",
      "SERVICENOW_USERNAME": "your-username",
      "SERVICENOW_PASSWORD": "your-password",
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

---

## OpenAI Codex (CLI & App)

**Codex CLI**(`codex` 명령어)와 **Codex App**(chatgpt.com/codex) 모두 동일한 `config.toml`을 사용합니다.

| 범위 | 경로 | 비고 |
|------|------|------|
| 전역 | `~/.codex/config.toml` | 모든 프로젝트에 공통 적용 |
| 프로젝트 | `.codex/config.toml` | 전역 설정을 덮어씀 (신뢰하는 프로젝트만) |

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
# 로그인은 호스트 간 자동 공유됩니다 (~/.mfa_servicenow_mcp 아래 인스턴스+유저 단위로 분리).
# SERVICENOW_BROWSER_USER_DATA_DIR는 샌드박스 호스트가 HOME을 리매핑한 경우에만 설정 —
# README "로그인 공유" 항목 참고. 인스턴스를 여러 개 돌릴 땐 설정하지 마세요;
# 모든 인스턴스가 Chromium 프로필 하나에 묶입니다.
```

---

## OpenCode

| 범위 | 경로 |
|------|------|
| 프로젝트 | 프로젝트 루트의 `opencode.json` |

> OpenCode는 `env` 대신 `environment`를 사용합니다.

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
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## AntiGravity

| 범위 | 경로 |
|------|------|
| 전역 | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| 전역 | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> 에이전트 패널에서도 수정할 수 있습니다: **...** > **Manage MCP Servers** > **View raw config**. 저장 후 **Refresh**를 클릭하세요.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_USERNAME": "your-username",
        "SERVICENOW_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

---

## Docker (API Key만 지원)

> 브라우저 인증(MFA/SSO)은 GUI 브라우저가 필요하여 컨테이너 환경에서는 동작하지 않습니다.

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
