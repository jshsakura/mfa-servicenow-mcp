# Windows 설치 가이드

파이썬을 직접 설치할 필요 없습니다. `uv`가 알아서 처리합니다.

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

## 2단계: 브라우저 엔진 설치

MFA/SSO 인증을 위해 Chromium 브라우저 엔진이 필요합니다:

```powershell
uvx playwright install chromium
```

> 이 명령어는 시스템 크롬과 무관한 별도 바이너리를 설치합니다.
> "uvx를 찾을 수 없음" 오류 → 1단계에서 PowerShell을 재시작했는지 확인.

---

## 3단계: MCP 클라이언트 설정

사용하는 MCP 클라이언트에 맞는 설정을 복사해서 넣으세요.

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
        "mfa-servicenow-mcp",
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
claude mcp add servicenow -- uvx --with playwright mfa-servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
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
        "mfa-servicenow-mcp"
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

### OpenAI Codex

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "mfa-servicenow-mcp",
        "--instance-url", "https://your-instance.service-now.com",
        "--auth-type", "browser",
        "--browser-headless", "false"
      ]
    }
  }
}
```

---

## 4단계: 동작 확인

MCP 클라이언트를 재시작하면 최초 접속 시 브라우저 창이 뜹니다.
Okta/Microsoft Authenticator 등으로 MFA 인증을 완료하면 세션이 유지됩니다.

> 브라우저가 안 뜨면 2단계(Chromium 설치)를 다시 확인하세요.

---

## 도구 패키지 선택

`MCP_TOOL_PACKAGE` 값으로 사용할 도구 세트를 선택합니다. 기본값은 `standard`(읽기 전용)입니다.

| 패키지 | 도구 수 | 설명 |
|--------|---------|------|
| `standard` | 48 | **(기본값)** 읽기 전용 safe mode. 모든 조회 도구 포함 |
| `portal_developer` | 58 | standard + 포탈/위젯/체인지셋 수정 |
| `platform_developer` | 71 | standard + 워크플로우/인시던트/변경관리 수정 |
| `service_desk` | 52 | standard + 인시던트 생성/처리 |
| `full` | 86 | 전체 기능 (수정/삭제 포함) |

수정 권한이 필요하면 `MCP_TOOL_PACKAGE` 값만 바꾸면 됩니다:

```json
"env": {
  "MCP_TOOL_PACKAGE": "portal_developer"
}
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
→ `uvx playwright install chromium`을 다시 실행하세요.
→ 회사 프록시/방화벽이 다운로드를 차단할 수 있습니다. IT팀에 확인하세요.

### "MCP 서버가 연결되지 않습니다"
→ 설정 파일의 JSON 문법 오류를 확인하세요 (쉼표, 따옴표).
→ `instance-url`이 `https://`로 시작하는지 확인하세요.
→ Claude Desktop은 설정 변경 후 **완전히 종료 후 재시작**해야 합니다 (트레이 아이콘도 닫기).

### "PowerShell 스크립트 실행이 차단됩니다"
→ 아래 명령어로 현재 사용자의 실행 권한을 허용하세요:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 버전 업데이트
`uvx`는 실행할 때마다 최신 버전을 자동으로 받습니다. 별도 업데이트 명령이 필요 없습니다.
