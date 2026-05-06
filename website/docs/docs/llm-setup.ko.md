# MFA ServiceNow MCP — LLM 설정 가이드

> **이 파일은 사람이 아니라 LLM 에이전트를 위한 문서입니다.**
> 사용자는 아래 curl 명령을 AI 코딩 도우미에 붙여넣고,
> LLM은 이 파일을 읽고 대화형으로 설치를 진행합니다.

---

## 사람용 사용 방법

Claude Code, Cursor, Codex, OpenCode, Windsurf 같은 AI 코딩 도우미에 아래를 붙여넣으세요:

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

이후 과정은 AI가 안내합니다.

---

## LLM 에이전트용 지침

당신은 **mfa-servicenow-mcp**를 설치하고 있습니다. 이 MCP 서버는 MFA/SSO를 지원하는 ServiceNow용 AI 도구 접근을 제공합니다. 아래 순서를 그대로 따르세요. 필요한 값은 반드시 사용자에게 물어보고, 임의로 가정하지 마세요.

### 0단계 — 환경 감지

1. 운영체제를 감지합니다: `uname -s 2>/dev/null || echo Windows`
2. 현재 어떤 AI 클라이언트 안에서 실행 중인지 감지합니다.

| 신호 | 클라이언트 |
|------|-----------|
| `claude mcp add` 사용 가능 또는 `.claude/` 디렉터리 존재 | **claude-code** |
| Cursor IDE 내부 또는 `.cursor/` 존재 | **cursor** |
| OpenCode CLI 내부 또는 `opencode.json` 존재 | **opencode** |
| Codex CLI 내부 또는 `.codex/` 존재 | **codex** |
| Windsurf IDE 내부 또는 `.windsurf/` 존재 | **windsurf** |
| VS Code Copilot 내부 | **vscode-copilot** |
| Gemini CLI 내부 | **gemini** |
| Zed 내부 또는 `~/.config/zed/` 존재 | **zed** |
| 위에 해당 없음 | 사용자에게 직접 질문 |

3. 자동 감지가 안 되면 이렇게 물어봅니다:
   > 어떤 AI 코딩 도구를 사용하고 있나요?
   > 1. Claude Code
   > 2. Claude Desktop
   > 3. Cursor
   > 4. OpenCode
   > 5. Codex (OpenAI)
   > 6. Windsurf
   > 7. VS Code Copilot
   > 8. Gemini CLI
   > 9. Zed
   > 10. AntiGravity (Google)

결과를 `$CLIENT`에 저장합니다.

### 1단계 — uv 설치

먼저 `uv`가 있는지 확인합니다: `uv --version`

없다면 설치합니다.

- **macOS / Linux**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell)**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

설치 후 다시 `uv --version`으로 확인합니다.
명령이 안 잡히면 셸을 재시작하거나 `~/.local/bin`이 PATH에 들어있는지 안내합니다.

### 2단계 — Playwright Chromium 설치 (필수, 절대 건너뛰지 말 것)

> 필수 종속성입니다. 현장에서 설치 실패하는 1순위 원인이 이거 빼먹는 케이스입니다.
> "이미 깔려있을 거야"라고 가정하지 말고, 사용자가 "나중에 해도 돼?"라고 해도 미루지 마세요.
> 이 단계가 성공하기 전엔 3단계로 넘어가지 마세요.

**2.1 — Chromium이 이미 깔려있는지 확인**

- macOS: `ls ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium 2>/dev/null`
- Linux: `ls ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null`
- Windows (PowerShell): `Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright\chromium-*\chrome-win\chrome.exe" -ErrorAction SilentlyContinue`

경로가 출력되면 이미 깔려있는 것 — 3단계로 점프.

**2.2 — Chromium 설치**

2.1에서 아무것도 없으면 Playwright를 uv tool로 깔고(이러면 `playwright` 바이너리가 PATH에 박혀서 로컬에서 재사용 가능) Chromium 빌드를 받습니다:

```bash
uv tool install playwright
playwright install chromium
```

> PATH에 새 명령 추가가 부담스러우면 한 줄 대안: `uvx --with playwright playwright install chromium` — 결과는 같지만 uvx가 매번 임시 venv를 만드므로 약간 더 느립니다. 사용자의 첫 설치라면 `uv tool install` 방식을 우선 사용하세요.

처음엔 ~150 MB 다운로드입니다. 느린 회선에선 몇 분 걸릴 수 있는데 정상입니다. 중간에 중단하지 마세요. 사용자에게 진행 메시지("ServiceNow MFA 로그인용 Chromium을 다운로드 중입니다 — 느린 네트워크에선 몇 분 걸릴 수 있습니다…")를 보여서 기다리는 이유를 알게 해주세요.

**2.3 — 검증 및 실패 시 중단**

2.1의 확인 명령을 다시 실행하세요. 그래도 바이너리가 없으면 **설치를 중단**하고 사용자에게 명령 출력 그대로 보고하세요. 흔한 원인:

- 회사 프록시가 `playwright.azureedge.net` 또는 `*.googleapis.com` 차단
- 백신이 Chromium 아카이브를 격리
- 디스크 공간 부족

Chromium이 없는 상태로 **절대 3단계로 진행하지 마세요**. MCP 서버는 시작된 것처럼 보이지만 첫 툴 호출이 행 걸리고 사용자 화면엔 로그인 창이 영영 안 뜹니다 — 이게 바로 이 단계가 존재하는 이유의 실제 실패 패턴입니다.

**왜 이렇게까지 강조하는지 (에이전트용 컨텍스트 — 사용자가 묻지 않으면 굳이 설명하지 마세요):** 런타임이 Chromium 부재 시 "필요할 때 설치" 폴백을 시도하지만, 느린 연결에선 그 다운로드가 MCP 호스트의 툴 호출 timeout을 넘깁니다. 사용자는 로그인 창도 못 보고, 에러 UI도 없고, "서버가 깨졌나?" 추측하게 됩니다. 이 단계에서 미리 깔면 첫 호출이 1초 이내로 끝납니다.

### 3단계 — 사용자 설정 수집

다음 질문을 하나씩 합니다. 기본값이 있으면 함께 보여주세요.

1. **ServiceNow 인스턴스 URL**
   > ServiceNow 인스턴스 URL이 무엇인가요?
   > 예: `https://your-company.service-now.com`

   값을 `$INSTANCE_URL`에 저장하고, URL처럼 보이는지 확인합니다.

2. **인증 방식**
   > ServiceNow에는 어떤 방식으로 로그인하나요?
   > 1. browser — 실제 브라우저로 MFA/SSO 로그인 (권장)
   > 2. basic — 사용자 이름 + 비밀번호
   > 3. oauth — OAuth 2.0 클라이언트 인증
   > 4. api_key — REST API 키

   값을 `$AUTH_TYPE`에 저장합니다. 기본값은 `browser`입니다.

3. **자격 증명** (선택 사항, browser 로그인 폼 자동 채움용)
   > (선택 사항) ServiceNow 사용자 이름을 입력하면 로그인 폼에 미리 채울 수 있습니다.
   > 비워 두면 매번 직접 입력합니다.

   값을 `$USERNAME`에 저장합니다. 값이 있으면 `$PASSWORD`도 추가로 받습니다.

4. **도구 패키지**
   > 어떤 도구 패키지가 필요하신가요?
   > 1. standard — 핵심 도구 (incident, change, catalog) [기본값]
   > 2. service_desk — standard + assignment, SLA, escalation
   > 3. portal_developer — standard + portal widgets, pages, themes
   > 4. platform_developer — standard + scripts, flows, update sets
   > 5. full — 가장 넓은 패키지 표면, 번들 워크플로우 포함 (124개 도구)

   값을 `$TOOL_PACKAGE`에 저장합니다. 기본값은 `standard`입니다.

5. **헤드리스 브라우저 여부**
   > 브라우저를 헤드리스로 실행할까요? (창이 보이지 않음)
   > 권장: 아니요 (MFA 과정을 직접 확인할 수 있도록)

   값을 `$HEADLESS`에 저장합니다. 기본값은 `false`입니다.

### 4단계 — 설치 명령 실행

**중요: 클라이언트가 지원하면 항상 프로젝트 로컬 설치를 기본으로 사용하세요.** 사용자가 명시적으로 원할 때만 `--scope global`을 붙입니다.

이제 하나의 설치 명령을 현재 프로젝트 루트에서 실행합니다. 설치기는 아래를 책임집니다.

- 클라이언트별 설정 파일 경로 결정
- 기존 설정 파일 병합/업데이트
- 지원 클라이언트의 스킬 설치

기본 명령:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS"
```

필요할 때만 추가 플래그를 붙입니다.

- 사용자 이름을 받았다면 `--username "$USERNAME"`
- 비밀번호를 받았다면 `--password "$PASSWORD"`
- OAuth면 `--client-id`, `--client-secret`, 필요 시 `--token-url`
- API 키면 `--api-key`, 필요 시 `--api-key-header`
- 전역 설치를 원하면 `--scope global`
- 스킬 설치를 원치 않으면 `--skip-skills`

예시:

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup codex \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type basic \
  --username "your.username" \
  --password "your-password"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup claude-code \
  --instance-url "https://your-instance.service-now.com" \
  --scope global \
  --skip-skills
```

### 5단계 — 설치 확인

1. 설치 명령이 성공적으로 종료되었는지 확인합니다.
2. 설치 요약에 표시된 설정 파일 경로를 읽어 확인합니다.
3. 스킬을 설치했다면 해당 디렉터리가 실제로 생성되었는지 확인합니다.
4. 설치기가 실패하지 않았다면 설정 파일을 수동으로 다시 쓰지 마세요.

### 6단계 — 사용자에게 다음 행동 안내

설치 후 사용자에게 이렇게 안내합니다:

> **설치가 완료되었습니다!**
> AI 클라이언트를 재시작하거나 MCP 서버를 다시 불러와서 새 설정을 읽게 하세요.
>
> browser 인증 방식이면 첫 도구 호출 때 MFA/SSO 로그인을 위한 브라우저 창이 열립니다.
> 로그인 후에는 `Run a health check on my ServiceNow instance` 같은 요청으로 시작하면 됩니다.
> 전체 문서: https://jshsakura.github.io/mfa-servicenow-mcp/

설치 직후 현재 세션에서 ServiceNow MCP 도구를 바로 호출하려고 하지 마세요. 클라이언트 재시작이 먼저 필요합니다.

### LLM을 위한 중요 메모

- 사용자 동의 없이 자격 증명을 설정 파일에 하드코딩하지 마세요.
- 설치기는 기존 설정 파일에 병합합니다. 복구가 필요한 경우가 아니면 수동 병합을 새로 작성하지 마세요.
- Windows 경로는 백슬래시를 사용합니다. OS에 맞는 경로 구분자를 사용하세요.
- 어떤 단계에서든 실패하면 원인을 설명하고 해결한 뒤 다음 단계로 진행하세요.
- 설명은 친절하고 짧게 유지하세요.
- 설치 후 MCP 도구를 바로 테스트하지 말고, 재시작이 필요하다고 안내만 하세요.
