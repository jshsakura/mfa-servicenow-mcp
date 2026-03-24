# Windows 설치 및 실행 가이드 (MFA/Browser 최적화)

도커(Docker) 없이 브라우저 인증을 가장 편하게 사용하는 방법입니다. 
`uv`를 사용하면 파이썬 버전을 직접 관리할 필요 없이 항상 최신 환경에서 실행 가능합니다.

---

### 0. 사전 준비 (Prerequisites)

이 프로젝트는 **[uv](https://astral.sh/uv)**라는 현대적인 파이썬 관리 도구를 사용합니다. 
`uv`가 설치되어 있으면 **파이썬이 직접 깔려 있지 않아도** 필요한 버전을 자동으로 내려받아 실행해 줍니다.

1.  **uv 설치 (PowerShell에서 한 줄 입력):**
    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
    *설치 후 PowerShell 창을 닫았다가 다시 열어주세요.*

2.  **브라우저 엔진 설치 (Playwright):**
    ```powershell
    uvx playwright install chromium
    ```

---

### 1. 초간편 실행 (추천)

Claude Desktop 설정(`claude_desktop_config.json`)을 열고 아래 내용을 붙여넣으세요. 
소스 코드를 다운로드하거나 환경변수를 직접 설정할 필요 없이 이 설정 하나로 끝납니다.

**설정 파일 예시:**
(통상 `%APPDATA%\Claude\claude_desktop_config.json`에 위치합니다.)

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
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

### 2. 소스 코드에서 실행하고 싶다면? (개발자용)

로컬에서 소스를 직접 실행하거나 수정하고 싶을 때 사용하세요.

1.  **소스 다운로드 및 자동 설정:**
    ```powershell
    git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
    cd mfa-servicenow-mcp
    .\setup_windows.ps1  # uv 설치, 가상환경 구축, 브라우저 세팅을 모두 수행합니다.
    ```

2.  **서버 실행:**
    ```powershell
    uv run servicenow-mcp
    ```

---

### 💡 왜 이 방식이 좋은가요?

*   **파이썬 관리 자동화:** `uv`가 프로젝트에 필요한 파이썬(3.11+)을 알아서 내려받아 환경을 구축합니다.
*   **MFA 완벽 지원:** 실제 윈도우 브라우저(크롬/엣지)가 직접 떠서 Okta, Microsoft Authenticator 등 모든 인증을 처리합니다.
*   **환경변수 대신 설정 파일:** `args`를 활용하여 모든 인증 정보를 JSON 하나로 명확하게 관리합니다.

---

### 🛠️ 문제 해결 (Troubleshooting)

*   **uvx 명령어를 찾을 수 없음:** 설치 후 PowerShell을 재시작했는지 확인해 주세요.
*   **브라우저가 안 떠요:** `uvx playwright install chromium` 명령어를 다시 실행해 보세요.
