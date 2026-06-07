# Windows 설치 가이드

기본 설치는 `uvx`입니다. Zscaler/보안툴이 `uvx`나 패키지 다운로드를 막는 Windows 환경에서는 아래 릴리즈 zip/exe 섹션을 사용하세요.

---

## 1단계: 기본 uvx 설치

관리자 권한 없는 PowerShell에서 실행:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

`uv` 설치 + 서버 fetch·검증 + Chromium 다운로드를 합니다. 그다음 MCP 클라이언트 설정파일에 서버를 추가하세요 (별도 installer 명령 불필요):

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

`uvx`는 같은 Chromium revision이 표준 Playwright 캐시에 있으면 재다운로드하지 않습니다. 없으면 위 설치 명령을 먼저 실행하세요.

---

## 2단계: 릴리즈 zip/exe 설치

`uvx`가 막히면 GitHub Releases에서 `servicenow-mcp-windows-x64-<version>.zip`을 받으세요. 안에는 PyInstaller로 빌드된 `servicenow-mcp.exe` 와 `LICENSE` 만 들어 있고, 설치 스크립트는 없습니다 — Chromium 탐색은 실행 파일이 직접 처리합니다. 본인이 관리하는 안정적인 폴더를 정해서 (`C:\Users\you\apps\servicenow-mcp\` 등) `servicenow-mcp.exe`를 그 안에 풀고, Chromium zip이 있으면 **같은 폴더에 미리 풀어두세요** — `.zip` 파일은 옆에 남기지 말고. 추출된 폴더 이름은 Windows 기본 출력(`ms-playwright-chromium-windows-x64-<ver>\`) 그대로 둬도 되고 `ms-playwright\`로 바꿔도 됩니다. 실행 파일은 시작 시 `ms-play*` 디렉토리를 글롭으로 찾습니다:

```
C:\Users\you\apps\servicenow-mcp\
├── servicenow-mcp.exe
└── ms-playwright-chromium-windows-x64-<ver>\   (기본 추출 이름 OK)
    └── chromium-1185\
        └── …
```

시작 시 실행 파일이 자기 옆 `ms-play*\chromium-*` 디렉토리를 찾고, 있으면 `PLAYWRIGHT_BROWSERS_PATH`를 그 경로로 지정합니다 — 현재 프로세스에만 적용. 시스템 표준 Playwright 캐시(`%LOCALAPPDATA%\ms-playwright`)는 건드리지 않고, MCP 클라이언트 설정 파일도 건드리지 않고, 디스크에 아무것도 쓰지 않습니다.

이후 본인 클라이언트 설정 파일에 아래 스니펫을 붙여넣으세요 (Claude Code / Claude Desktop 예):

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "C:/Users/you/apps/servicenow-mcp/servicenow-mcp.exe",
      "args": [],
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

`SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD`는 선택(MFA 폼 미리 채우기). Chromium을 실행 파일 옆 `ms-playwright\` 이 *아닌* 다른 위치에 두었다면 env에 `"PLAYWRIGHT_BROWSERS_PATH": "C:/abs/path/to/ms-playwright"`를 추가하세요. Codex(`config.toml`) / OpenCode(`opencode.json`) / Cursor / Antigravity / Zed 등 다른 클라이언트 설정 스니펫은 [클라이언트 설정 가이드](CLIENT_SETUP.ko.md) 참조.

이 방식은 runtime에서 `uvx`를 일절 쓰지 않습니다.

Chromium 번들을 안 받았고 다운로드가 허용되는 환경이면 <https://www.python.org/downloads/> 에서 Python을 설치한 뒤, 같은 구조로 캐시를 만드세요:

```powershell
py -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = "$HOME\apps\servicenow-mcp\ms-playwright"
py -m playwright install chromium
```

브라우저 다운로드까지 막히면 chromium-bundle 릴리즈(https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle)의 `ms-playwright-chromium-windows-x64.zip`을 받아 아래 위치에 풀면 됩니다.

```text
%LOCALAPPDATA%\ms-playwright
```

Playwright 브라우저 문서: <https://playwright.dev/python/docs/browsers>

---

## 3단계: 릴리즈 빌드

관리자는 Windows 빌드 머신에서 릴리즈 zip을 만듭니다:

```powershell
py scripts\build_desktop_release.py --browser-zip
```

이 명령은 실행 파일 zip과, 차단망용 Playwright Chromium 캐시 zip을 생성합니다.

---

## 4단계: MCP 클라이언트 설정

사용하는 MCP 클라이언트에 맞는 설정을 복사해서 넣으세요.
`your-instance`를 실제 ServiceNow 인스턴스 주소로 바꿔야 합니다.

### Claude Desktop

설정 파일 위치: `%APPDATA%\Claude\claude_desktop_config.json`

> 파일이 없으면 새로 만드세요. 폴더가 없다면 Claude Desktop을 한 번 실행하면 생깁니다.

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

별도 설정 파일 없이 `claude mcp add` 명령어로 등록합니다:

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

등록 확인:
```powershell
claude mcp list
```

### OpenAI Codex

설정 파일 위치: `%USERPROFILE%\.codex\agents.toml` 또는 프로젝트 루트의 `.codex\agents.toml`

> 파일이나 폴더가 없으면 새로 만드세요.

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

### OpenCode

설정 파일 위치: 프로젝트 루트의 `opencode.json`

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "enabled": true,
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

### Zed

설정 파일 위치: `~/.config/zed/settings.json`

> Zed에서 **Settings** > **MCP Servers**로 추가하세요:

```json
{
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
      "MCP_TOOL_PACKAGE": "standard"
    }
  }
}
```

### AntiGravity

설정 파일 위치: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> 에이전트 패널 상단 **...** → **Manage MCP Servers** → **View raw config**로도 열 수 있습니다.

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
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

> 설정 저장 후 AntiGravity에서 **Refresh**를 눌러야 적용됩니다.

---

## 5단계: 스킬 설치 (선택사항)

스킬은 AI 실행 블루프린트입니다 — 안전 게이트가 포함된 검증된 파이프라인으로, MCP 도구를 신뢰할 수 있는 워크플로우로 전환합니다. 현재 5개 카테고리에 16개 스킬을 제공합니다.

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# 또는 uvx로 바로 실행 (설치 불필요)
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

| 클라이언트 | 설치 경로 | 자동 인식 |
|-----------|----------|----------|
| Claude Code | `.claude\commands\servicenow\` | 재시작 시 `/servicenow` 슬래시 명령으로 표시 |
| OpenAI Codex | `.codex\skills\servicenow\` | 다음 에이전트 세션에서 자동 로드 |
| OpenCode | `.opencode\skills\servicenow\` | 다음 세션에서 자동 로드 |

| 카테고리 | 스킬 수 | 용도 |
|---------|---------|------|
| `analyze/` | 6 | 위젯 분석, 포탈 진단, 의존성 매핑, 코드 탐지 |
| `fix/` | 3 | 위젯 패칭 (단계별 안전 게이트), 디버깅, 코드 리뷰 |
| `manage/` | 8 | 페이지 레이아웃, 스크립트 인클루드, 소스 내보내기, 앱 소스 다운로드, 체인지셋 워크플로우, 로컬 동기화, 워크플로우 관리, 스킬 관리 |
| `deploy/` | 2 | 변경 요청 라이프사이클, 인시던트 트리아지 |
| `explore/` | 5 | 헬스체크, 스키마 탐색, 라우트 추적, 플로우 트리거 추적, ESC 카탈로그 흐름 |

**업데이트:** 같은 설치 명령어를 다시 실행하면 기존 스킬 파일을 통째로 교체합니다.
**스킬만 제거:** 스킬 디렉터리를 직접 삭제하세요 (예: `Remove-Item -Recurse .claude\commands\servicenow\`).

---

## 6단계: 동작 확인

1. MCP 클라이언트를 **완전히 종료 후 재시작**합니다 (트레이 아이콘도 닫기).
2. 첫 번째 도구 호출 시 브라우저 창이 뜹니다 (서버 시작 시점이 아님).
3. Okta/Microsoft Authenticator 등으로 MFA 인증을 완료하세요.
4. 인증 완료 후 브라우저가 자동으로 닫히고 세션이 유지됩니다.

확인 방법: 클라이언트에서 `sn_health` 도구를 호출해 보세요.

> 브라우저가 안 뜨면 Chromium이 설치되어 있는지 확인하세요. 수동 설치: `uvx --with playwright playwright install chromium`

---

## 세션 관리

인증 세션은 디스크에 자동 저장되어 매번 로그인할 필요가 없습니다.

- **세션 파일 위치**: `%USERPROFILE%\.servicenow_mcp\session_*.json`
- **기본 세션 TTL**: 30분 (keepalive 쓰레드가 15분마다 연장)
- **세션 만료 시**: 자동으로 브라우저 창이 열려 재인증을 요청합니다

TTL을 변경하려면 `--browser-session-ttl` 옵션을 사용하세요 (단위: 분):
```
--browser-session-ttl 60
```

브라우저 프로필을 영속적으로 유지하려면 `--browser-user-data-dir` 옵션을 추가하세요:
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
이 옵션을 사용하면 쿠키와 로그인 상태가 디렉터리에 저장되어 세션이 더 오래 유지됩니다.

---

## 도구 패키지 선택

`MCP_TOOL_PACKAGE` 값으로 사용할 도구 세트를 선택합니다. 기본값은 `standard`(읽기 전용)입니다.

| 패키지 | 도구 수 | 설명 |
|--------|:------:|------|
| `core` | 12 | 헬스체크, 스키마, 탐색, 핵심 조회만 담은 최소 읽기 전용 패키지 |
| `standard` | 27 | **(기본값)** 인시던트/변경/포털/로그/소스 분석 전반의 읽기 전용 패키지 |
| `service_desk` | 29 | standard + 인시던트/변경 운영 쓰기 |
| `portal_developer` | 38 | standard + 포털, 체인지셋, Script Include, 로컬 동기화 워크플로우 |
| `platform_developer` | 43 | standard + 워크플로우, Flow Designer, UI Policy, 인시던트/변경/스크립트 쓰기 |
| `full` | 57 | 가장 넓은 패키지 표면: 번들 `manage_*` 워크플로우 + 고급 운영 도구 |

수정 권한이 필요하면 `MCP_TOOL_PACKAGE` 값만 바꾸면 됩니다:

JSON 클라이언트 (Claude Desktop, AntiGravity):
```json
"env": {
  "MCP_TOOL_PACKAGE": "standard"
}
```

TOML 클라이언트 (Codex) — `args` 배열 안에 추가:
```toml
"--tool-package", "standard",
```

---

## 자주 묻는 문제

### "uvx를 찾을 수 없습니다"
→ 1단계 후 PowerShell을 **닫고 다시 열었는지** 확인. 안 되면:
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### "파이썬이 설치되어 있지 않습니다"
→ `uv`가 자동으로 Python 3.11+을 내려받습니다. 직접 설치할 필요 없습니다.
혹시 시스템 Python과 충돌하면 `uv`를 삭제 후 재설치해 보세요.

### "브라우저가 열리지 않습니다"
→ Chromium은 MCP 시작 전에 설치되어 있어야 합니다:
```powershell
uvx --with playwright playwright install chromium
```
→ 브라우저 다운로드가 차단되면 chromium-bundle 릴리즈(https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle)의 `ms-playwright-chromium-windows-x64.zip`을 받아 `%LOCALAPPDATA%\ms-playwright`에 풀어 주세요.

### "MCP 서버가 연결되지 않습니다"
→ 설정 파일의 문법 오류를 확인하세요:
  - JSON: 쉼표, 따옴표, 중괄호 짝이 맞는지
  - TOML: 대괄호, 따옴표, 쉼표 확인
→ `instance-url`이 `https://`로 시작하는지 확인하세요.
→ Claude Desktop은 설정 변경 후 **완전히 종료 후 재시작**해야 합니다 (트레이 아이콘도 닫기).

### "PowerShell 스크립트 실행이 차단됩니다"
→ 아래 명령어로 현재 사용자의 실행 권한을 허용하세요:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 세션 초기화
로그인 문제가 반복되면 세션 캐시를 삭제하고 다시 시도하세요:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### 버전 업데이트
`uvx`는 마지막으로 받은 버전을 캐시에 저장해 재사용합니다. 실행할 때마다 최신 릴리스를 자동으로 받지는 않습니다. 최신 배포본을 다시 받으려면:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

갱신 후에는 MCP 클라이언트를 완전히 재시작해야 새 캐시 버전으로 실행됩니다.
