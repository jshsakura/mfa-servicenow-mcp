## Windows에서 가장 쉬운 설치 방법 (브라우저 로그인 기준)

### 1) 권장 설치: `pipx` (가장 간단)
PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
# PowerShell 재시작
pipx install mfa-servicenow-mcp
pipx inject mfa-servicenow-mcp playwright
playwright install chromium
```

설치 확인:

```powershell
servicenow-mcp --help
```

---

### 2) 실행용 환경변수 (브라우저 로그인)
PowerShell:

```powershell
$env:SERVICENOW_INSTANCE_URL="https://your-instance.service-now.com"
$env:SERVICENOW_AUTH_TYPE="browser"
$env:SERVICENOW_BROWSER_HEADLESS="false"
$env:SERVICENOW_BROWSER_TIMEOUT="120"
$env:SERVICENOW_BROWSER_SESSION_TTL="30"
$env:SERVICENOW_BROWSER_USER_DATA_DIR="$env:USERPROFILE\.mfa-servicenow-browser"
$env:SERVICENOW_BROWSER_USERNAME="your-username"
$env:SERVICENOW_BROWSER_PASSWORD="your-password"
$env:MCP_TOOL_PACKAGE="approval_query_only"
servicenow-mcp
```

> `MCP_TOOL_PACKAGE="approval_query_only"`는 조회 중심으로 안전하게 시작할 때 권장입니다.

---

### 3) Codex MCP 설정 예시 (stdio)
```json
{
  "mcpServers": {
    "servicenow": {
      "command": "servicenow-mcp",
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "SERVICENOW_BROWSER_HEADLESS": "false",
        "SERVICENOW_BROWSER_TIMEOUT": "120",
        "SERVICENOW_BROWSER_SESSION_TTL": "30",
        "SERVICENOW_BROWSER_USER_DATA_DIR": "C:\\Users\\<you>\\.mfa-servicenow-browser",
        "SERVICENOW_BROWSER_USERNAME": "your-username",
        "SERVICENOW_BROWSER_PASSWORD": "your-password",
        "MCP_TOOL_PACKAGE": "approval_query_only"
      }
    }
  }
}
```

---

### 4) PATH 문제 있을 때
`servicenow-mcp`가 안 잡히면 `command`를 절대경로로 지정:

```text
C:\Users\<you>\AppData\Roaming\Python\Python3x\Scripts\servicenow-mcp.exe
```

또는 pipx 경로(환경마다 다름)를 직접 지정하면 됩니다.
