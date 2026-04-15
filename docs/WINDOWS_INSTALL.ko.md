# Windows 설치 가이드

파이썬이나 Playwright를 직접 설치할 필요 없습니다. `uv`가 파이썬, 패키지, Chromium 브라우저 엔진까지 전부 자동으로 설치합니다.

---

## 1단계: uv 설치

`uv`는 파이썬 버전 관리 + 패키지 설치를 한 번에 해주는 도구입니다.

PowerShell을 **관리자 권한 없이** 열고 아래 명령어를 실행하세요:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

설치 후 **PowerShell을 닫고 다시 열어주세요** (PATH 반영을 위해).

확인:
```powershell
uv --version
```

> `uv`를 찾을 수 없다는 오류가 나면 PowerShell을 다시 열었는지 확인하세요.
> 그래도 안 되면 `$env:USERPROFILE\.local\bin`이 PATH에 있는지 확인하세요.

---

## 2단계: MCP 서버 실행

명령어 한 줄이면 됩니다 — Chromium은 처음 실행 시 자동 설치됩니다:

```powershell
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp `
  --instance-url "https://your-instance.service-now.com" `
  --auth-type "browser" `
  --browser-headless "false"
```

첫 번째 도구 호출 시 브라우저 창이 열리고 MFA/SSO 로그인(Okta, Entra ID, SAML)을 진행합니다. 인증 완료 후 브라우저가 자동으로 닫히고 세션이 유지됩니다.

---

## 3단계: MCP 클라이언트 설정

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

## 4단계: 스킬 설치 (선택사항)

스킬은 AI 실행 블루프린트입니다 — 안전 게이트가 포함된 검증된 파이프라인으로, MCP 도구를 신뢰할 수 있는 워크플로우로 전환합니다. 5개 카테고리에 20개 이상의 스킬을 제공합니다.

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
| `manage/` | 5 | 페이지 레이아웃, 스크립트 인클루드, 소스 내보내기, 체인지셋 워크플로우 |
| `deploy/` | 2 | 변경 요청 라이프사이클, 인시던트 트리아지 |
| `explore/` | 4 | 헬스체크, 스키마 탐색, 라우트 추적, ESC 카탈로그 흐름 |

**업데이트:** 같은 설치 명령어를 다시 실행하면 모든 스킬 파일이 업데이트됩니다.
**삭제:** 설치 디렉터리를 삭제하세요 (예: `Remove-Item -Recurse .claude\commands\servicenow\`).

---

## 5단계: 동작 확인

1. MCP 클라이언트를 **완전히 종료 후 재시작**합니다 (트레이 아이콘도 닫기).
2. 첫 번째 도구 호출 시 브라우저 창이 뜹니다 (서버 시작 시점이 아님).
3. Okta/Microsoft Authenticator 등으로 MFA 인증을 완료하세요.
4. 인증 완료 후 브라우저가 자동으로 닫히고 세션이 유지됩니다.

확인 방법: 클라이언트에서 `sn_health` 도구를 호출해 보세요.

> 브라우저가 안 뜨면 Chromium이 자동 설치되었는지 확인하세요. 수동 설치: `uvx playwright install chromium`

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
|--------|---------|------|
| `standard` | 55 | **(기본값)** 읽기 전용 safe mode. 모든 조회 도구 포함 |
| `portal_developer` | 70 | standard + 포탈/위젯/체인지셋 수정 |
| `platform_developer` | 78 | standard + 워크플로우/인시던트/변경관리 수정 |
| `service_desk` | 59 | standard + 인시던트 생성/처리 |
| `full` | 98 | 전체 기능 (수정/삭제 포함) |

수정 권한이 필요하면 `MCP_TOOL_PACKAGE` 값만 바꾸면 됩니다:

JSON 클라이언트 (Claude Desktop, AntiGravity):
```json
"env": {
  "MCP_TOOL_PACKAGE": "portal_developer"
}
```

TOML 클라이언트 (Codex) — `args` 배열 안에 추가:
```toml
"--tool-package", "portal_developer",
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
→ Chromium은 처음 실행 시 자동 설치됩니다. 실패하면 수동 설치:
```powershell
uvx playwright install chromium
```
→ 회사 프록시/방화벽이 다운로드를 차단할 수 있습니다. IT팀에 확인하세요.

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

### "회사 프록시/SSL 인증서 오류"
→ 회사 내부 CA 인증서를 사용하는 환경에서는 아래 환경 변수를 설정하세요:
```powershell
$env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
```
또는 회사 루트 인증서를 시스템에 등록한 후:
```powershell
$env:REQUESTS_CA_BUNDLE = "C:\path\to\company-ca-bundle.crt"
```

### 세션 초기화
로그인 문제가 반복되면 세션 캐시를 삭제하고 다시 시도하세요:
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### 버전 업데이트
`uvx`는 실행할 때마다 최신 버전을 자동으로 받습니다. 캐시를 강제로 갱신하려면:
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```
