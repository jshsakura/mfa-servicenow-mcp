# Windows 설치 및 실행 가이드 (MFA/Browser 최적화)

도커(Docker)는 브라우저를 직접 띄우는 기능에 제약이 있어, 윈도우에서는 **네이티브 실행**을 강력히 권장합니다. 
`uv`를 사용하면 소스 코드 다운로드 없이 바로 실행하거나, 소스를 받아 직접 개발 환경을 구축할 수 있습니다.

---

### [방법 1] 초간편 실행 (소스 코드 불필요)

PyPI에 배포된 패키지를 바로 사용하는 방식입니다. 가장 빠르고 간편합니다.

1.  **Claude Desktop 설정에 바로 추가:**
    `claude_desktop_config.json` 파일을 열고 아래 내용을 붙여넣으세요.
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

2.  **터미널에서 테스트 실행:**
    ```powershell
    uvx mfa-servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type "browser"
    ```

---

### [방법 2] 소스 코드 실행 (Git Clone 방식)

소스 코드를 다운로드하여 로컬에서 수정하거나 직접 실행하고 싶을 때 사용합니다.

1.  **소스 다운로드 및 설정:**
    ```powershell
    git clone https://github.com/your-repo/mfa-servicenow-mcp.git
    cd mfa-servicenow-mcp
    .\setup_windows.ps1  # 모든 환경 구성을 자동으로 수행합니다.
    ```

2.  **서버 실행:**
    ```powershell
    uv run servicenow-mcp
    ```

---

### 💡 왜 이 방식이 좋은가요?

*   **MFA 완벽 지원:** 실제 윈도우 브라우저(크롬/엣지)가 직접 떠서 모든 MFA 인증을 수행할 수 있습니다.
*   **환경 변수 대신 설정 파일:** `args`를 활용하여 모든 인증 설정을 JSON 하나로 관리할 수 있습니다.
*   **세션 유지:** 한 번 로그인하면 세션이 안전하게 저장되어, 이후에는 로그인 과정 없이 즉시 실행됩니다.

### 🛠️ 문제 해결 (Troubleshooting)

*   **브라우저가 안 떠요:** 터미널에서 `uvx playwright install chromium` 명령어를 실행하여 브라우저 엔진을 설치해 주세요.
*   **uv 명령어를 찾을 수 없음:** [uv 설치 가이드](https://github.com/astral-sh/uv)를 참고하여 `uv`를 먼저 설치해 주세요.
