# Windows 설치 가이드

Windows에서도 다른 OS와 동일하게 `uvx`가 기본입니다. 다만 Windows에서만 생기는 한 가지 이유로 `uvx`를 못 쓰게 될 수 있습니다:

- **Smart App Control이 `uvx`를 차단** → **pip 설치**로 전환하세요 (1b단계). Windows에서 가장 흔한 고장 원인이고, 보통 Windows 업데이트 직후에 갑자기 나타납니다.

PyPI 자체에 접근이 막혀 있다면(사내망이 패키지 인덱스를 통째로 차단하는 경우) 두 방법 모두 패키지를 받아올 수 없습니다. 사내 IT에 `pypi.org`와 `files.pythonhosted.org` 허용을 요청하거나, 내부 인덱스에 미러링해 두고 `pip install --index-url`로 그 주소를 가리켜 설치하세요.

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

**업데이트:** `uvx`는 한 번 받은 버전을 캐시에 두고 계속 재사용하므로, 새 릴리스는 명시적으로 당겨와야 합니다:

```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

---

## 1b단계: Smart App Control이 uvx를 막을 때 pip으로 설치

### 증상

`uvx`가 쓸 만한 에러 메시지 하나 없이 동작을 멈춥니다. MCP 클라이언트는 서버 시작 실패라고만 하고, PowerShell은 관리자 정책 또는 시스템 정책에 의해 프로그램이 차단되었다고 표시합니다. 설정은 아무것도 바뀌지 않았는데 말이죠. 특히 **Windows 업데이트 직후**에 시작되는 경우가 많아서, 실행기가 아니라 서버가 망가진 것처럼 보입니다.

### 원인

[Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4495-afc7-c4d1abd9c0e0)(SAC)은 **서명되었거나 안전하다고 확인된** 실행 파일만 실행을 허용하는 Windows 11 기능입니다. `uvx`는 영구 설치된 프로그램을 실행하는 방식이 아니라, 실행할 때마다 **서명되지 않은 임시 실행 파일을 새로 풀어서** 띄웁니다. 이는 SAC가 막으려고 존재하는 형태 그 자체라서 매번 차단됩니다. 재시도하거나 `uv`를 재설치해도 소용없습니다 — 설계상 매 실행마다 새롭고 서명 없는 파일이 생기기 때문입니다.

SAC는 새 Windows 11 기기에서 평가 모드로 시작하며, 이후 스스로 **켜짐** 상태로 전환될 수 있습니다. 몇 달간 잘 쓰던 `uvx`가 어느 날 갑자기 안 되는 이유가 이것입니다.

확인 경로: **Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 설정**.

> **이 문제를 해결하려고 Smart App Control을 끄지 마세요.** 끄는 것은 **되돌릴 수 없는 일방향 스위치**입니다 — 한 번 끄면 Windows가 다시 켜는 것을 허용하지 않습니다. 복구하려면 **Windows를 재설치**해야 합니다. 패키지 실행기 하나 때문에 OS 보안을 영구히 낮출 이유는 없습니다. 대신 pip을 쓰세요. SAC를 켜 둔 채로 문제가 완전히 해결됩니다.

### pip 설치 방법

pip은 서버를 평범한 Python 파일로 설치하고 **서명된** Python 인터프리터가 이를 실행하므로, SAC가 트집 잡을 대상 자체가 없습니다.

[python.org 인스톨러](https://www.python.org/downloads/)에서 Python **3.10 이상**을 설치하세요 — 이 빌드는 서명되어 있어 그대로 SAC를 통과합니다. (Microsoft Store 버전 Python도 됩니다.) 설치 중 **"Add python.exe to PATH"**를 체크하세요. 그다음:

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**업데이트:**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

Chromium은 위처럼 미리 설치해 두세요. 첫 도구 호출 시점으로 미루면 약 150 MB 다운로드가 MCP 클라이언트의 핸드셰이크 제한 시간과 경쟁하게 되고, `connection closed`로 나타납니다.

### 콘솔 스크립트 말고 항상 모듈로 실행하세요

pip은 Scripts 폴더에 `servicenow-mcp.exe` shim도 같이 만듭니다. **이 shim은 pip이 사용자 PC에서 생성한 서명 없는 `.exe`이기 때문에, uvx와 똑같은 이유로 SAC가 차단합니다.** 모듈을 직접 호출해서 아예 우회하세요:

| 이 대신 | 이렇게 |
|---|---|
| `servicenow-mcp` | `python -m servicenow_mcp` |
| `servicenow-mcp setup` | `python -m servicenow_mcp setup` |
| `servicenow-mcp --version` | `python -m servicenow_mcp --version` |
| `servicenow-mcp-skills claude` | `python -m servicenow_mcp.setup_skills claude` |

설치 확인:

```powershell
python -m servicenow_mcp --version
```

### pip 설치 시 클라이언트 설정

바뀌는 건 `command`와 `args` 뿐입니다. **`env` 블록은 uvx 방식과 완전히 동일합니다** — 2단계의 설정을 그대로 복사한 뒤 위 두 줄만 바꾸면 됩니다:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

Codex의 TOML에서는 `command = "python"` / `args = ["-m", "servicenow_mcp"]`가 같은 의미입니다.

> MCP 클라이언트가 `python`을 못 찾으면 절대 경로를 지정하세요 (예: `C:/Users/you/AppData/Local/Programs/Python/Python312/python.exe`). MCP 클라이언트가 셸의 PATH를 항상 물려받는 것은 아닙니다.

---

## 2단계: MCP 클라이언트 설정

사용하는 MCP 클라이언트에 맞는 설정을 복사해서 넣으세요.
`your-instance`를 실제 ServiceNow 인스턴스 주소로 바꿔야 합니다.

> 아래 예시는 기본 `uvx` 설치 기준입니다. **pip으로 설치했다면(1b단계) `command`를 `python`으로, `args`를 `["-m", "servicenow_mcp"]`로 바꾸세요** — 뒤에 붙는 `--instance-url` / `--auth-type` 플래그는 그대로 두고, `env` 블록도 적힌 그대로 유지합니다.

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

## 3단계: 스킬 설치 (선택사항)

스킬은 AI 실행 블루프린트입니다 — 안전 게이트가 포함된 검증된 파이프라인으로, MCP 도구를 신뢰할 수 있는 워크플로우로 전환합니다. 현재 3개 카테고리에 4개 스킬을 제공합니다.

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

> **pip으로 설치했다면(1b단계) 모듈을 호출하세요** — `servicenow-mcp-skills` 역시 Smart App Control이 차단하는, pip이 만든 서명 없는 `.exe` shim입니다:
>
> ```powershell
> python -m servicenow_mcp.setup_skills claude
> python -m servicenow_mcp.setup_skills codex
> python -m servicenow_mcp.setup_skills opencode
> ```

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

## 4단계: 동작 확인

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

### uvx는 찾는데 아무것도 실행되지 않음 / "관리자에 의해 차단됨" / Windows 업데이트 후 고장
→ 설치가 깨진 게 아니라 **Smart App Control** 문제입니다. uvx는 실행할 때마다 서명 없는 임시 실행 파일을 풀어내고, SAC가 그 실행을 거부합니다. [1b단계](#1b단계-smart-app-control이-uvx를-막을-때-pip으로-설치)의 pip 방식으로 전환하세요. SAC를 끄지는 마세요 — Windows 재설치로만 되돌릴 수 있는 일방향 스위치입니다.

### pip 설치는 됐는데 `servicenow-mcp`가 여전히 실행되지 않음
→ pip이 생성한 `servicenow-mcp.exe` shim을 실행하고 있어서입니다. 이 파일은 서명이 없어 uvx와 똑같이 SAC에 막힙니다. 모듈을 호출하세요: `python -m servicenow_mcp`. MCP 클라이언트 설정도 `"command": "python"`, `"args": ["-m", "servicenow_mcp"]`로 바꾸세요.

### "파이썬이 설치되어 있지 않습니다"
→ **uvx** 방식에서는 `uv`가 자동으로 Python 3.11+을 내려받으므로 직접 설치할 필요가 없습니다. 혹시 시스템 Python과 충돌하면 `uv`를 삭제 후 재설치해 보세요.
→ **pip** 방식에서는 Python을 직접 준비해야 합니다. [python.org 인스톨러](https://www.python.org/downloads/)로 3.10 이상을 설치하고(서명되어 있어 Smart App Control을 통과합니다) **"Add python.exe to PATH"**를 체크하세요. Microsoft Store 버전 Python도 됩니다.

### "브라우저가 열리지 않습니다"
→ Chromium은 MCP 시작 전에 설치되어 있어야 합니다:
```powershell
uvx --with playwright playwright install chromium   # uvx
python -m playwright install chromium               # pip
```

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
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

pip 방식이라면:
```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

두 경우 모두 Chromium을 함께 갱신합니다. 새 Playwright는 그에 맞는 새 Chromium 빌드를 요구하기 때문입니다.

갱신 후에는 MCP 클라이언트를 완전히 재시작해야 새 버전으로 실행됩니다.
