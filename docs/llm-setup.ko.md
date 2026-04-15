# MFA ServiceNow MCP — LLM 설정 가이드

> **이 파일은 LLM 에이전트용입니다. 사람이 직접 읽는 용도가 아닙니다.**
> 사용자가 아래의 curl 명령어를 AI 코딩 어시스턴트에 붙여넣으면,
> LLM이 이 파일을 읽고 대화형으로 설정을 진행합니다.

---

## 사용법 (사람용)

AI 코딩 어시스턴트(Claude Code, Cursor, Codex, OpenCode, Windsurf 등)에 다음을 붙여넣으세요:

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

이게 전부입니다. 나머지는 AI가 알아서 처리합니다.

---

## LLM 에이전트를 위한 지침

여러분은 **mfa-servicenow-mcp**를 설정해야 합니다. 이것은 MFA/SSO를 지원하는 ServiceNow 플랫폼에 AI 에이전트가 접근할 수 있게 해주는 MCP 서버입니다. 아래의 모든 단계를 순서대로 따르세요. 사용자에게 질문하며 대화형으로 진행하고, 값을 임의로 추측하지 마세요.

### 0단계 — 환경 감지

1. 운영 체제 확인: `uname -s 2>/dev/null || echo Windows` 실행
2. 현재 실행 중인 AI 클라이언트를 감지합니다. 다음 매핑을 사용하세요:

| 신호 | 클라이언트 |
|--------|--------|
| `claude mcp add` 명령어 또는 `.claude/` 디렉토리에 접근 가능 | **claude-code** |
| Cursor IDE 내부이거나 `.cursor/` 디렉토리가 존재 | **cursor** |
| OpenCode CLI에 접근 가능하거나 `opencode.json`이 존재 | **opencode** |
| Codex CLI 내부이거나 `.codex/` 디렉토리가 존재 | **codex** |
| Windsurf IDE 내부이거나 `.windsurf/` 디렉토리가 존재 | **windsurf** |
| VS Code에서 Copilot 사용 중 | **vscode-copilot** |
| Gemini CLI 내부 | **gemini** |
| Zed 에디터 내부이거나 `~/.config/zed/` 디렉토리가 존재 | **zed** |
| 해당 사항 없음 | 사용자에게 어떤 클라이언트를 사용하는지 질문 |

3. 자동 감지가 안 되면, 다음과 같이 질문하세요:
   > 어떤 AI 코딩 도구를 사용 중이신가요?
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

`uv`가 이미 설치되어 있는지 확인: `uv --version`

설치되지 않은 경우:

- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

설치 후 확인: `uv --version`
명령어를 찾을 수 없다면, 셸을 재시작하거나 `~/.local/bin`을 PATH에 추가해야 할 수 있습니다.

### 2단계 — Playwright 브라우저 설치

다음을 실행합니다:
```bash
uvx --with playwright playwright install chromium
```

이 명령은 MFA/SSO 로그인 흐름을 처리하는 Chromium 브라우저를 설치합니다. 브라우저 인증 모드를 사용하려면 필수입니다.

### 3단계 — 사용자 설정 수집

사용자에게 다음 질문을 하나씩 합니다. 대괄호 안에 기본값을 표시하세요.

1. **ServiceNow 인스턴스 URL**
   > ServiceNow 인스턴스 URL을 입력해 주세요.
   > 예시: `https://your-company.service-now.com`

   `$INSTANCE_URL`에 저장합니다. URL 형식인지 확인합니다.

2. **인증 방식**
   > ServiceNow에 어떻게 인증하시나요?
   > 1. browser — 실제 브라우저를 통한 MFA/SSO (권장)
   > 2. basic — 사용자 이름 + 비밀번호
   > 3. oauth — OAuth 2.0 클라이언트 자격 증명
   > 4. api_key — REST API 키

   `$AUTH_TYPE`에 저장합니다. 기본값: `browser`

3. **자격 증명** (선택 사항, 브라우저 인증 시 폼 자동 완성용)
   > (선택 사항) ServiceNow 사용자 이름을 입력하면 로그인 폼에 자동으로 채워집니다.
   > 입력하지 않으면 매번 직접 입력하게 됩니다.

   `$USERNAME`에 저장합니다 (비어 있을 수 있음).
   값이 제공되면 `$PASSWORD`도 추가로 질문합니다.

4. **도구 패키지**
   > 어떤 도구 패키지가 필요하신가요?
   > 1. standard — 핵심 도구 (인시던트, 변경, 카탈로그) [기본값]
   > 2. service_desk — standard + 할당, SLA, 에스컬레이션
   > 3. portal_developer — standard + 포털 위젯, 페이지, 테마
   > 4. platform_developer — standard + 스크립트, 플로우, 업데이트 세트
   > 5. full — 전체 (97개 이상의 도구)

   `$TOOL_PACKAGE`에 저장합니다. 기본값: `standard`

5. **헤드리스 브라우저**
   > 브라우저를 헤드리스 모드로 실행할까요? (창이 보이지 않음)
   > 권장: 아니요 (MFA 프롬프트를 직접 확인하려면)

   `$HEADLESS`에 저장합니다. 기본값: `false`

### 4단계 — 클라이언트에 MCP 구성

**중요: 항상 프로젝트 로컬 설치를 기본으로 합니다.** 구성 파일은 사용자의 현재 작업 디렉토리(프로젝트 루트)에 작성합니다. 사용자가 명시적으로 요청한 경우에만 전역/사용자 수준 구성을 사용합니다. 각 프로젝트는 자체 ServiceNow 인스턴스 설정을 가져야 합니다.

`$CLIENT`에 따라 현재 디렉토리에 구성 파일을 작성합니다. 모든 `$VARIABLES`를 수집된 값으로 교체합니다.

---

#### claude-code

**기본값: 프로젝트 로컬 설치.** 현재 프로젝트 루트에 `.mcp.json`을 작성합니다. 권장 방식입니다. 각 프로젝트가 자체 ServiceNow 인스턴스 설정을 갖게 됩니다.

사용자에게 질문: "이 프로젝트에 설치할까요, 아니면 모든 프로젝트에 전역으로 설치할까요?"
- **프로젝트 (기본값):** 현재 프로젝트 루트에 `.mcp.json` 작성
- **전역:** `claude mcp add --global` 사용 또는 `~/.claude.json`에 작성

전역 설치 시 다음을 실행:
```bash
claude mcp add --global servicenow -- \
  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --browser-headless "$HEADLESS"
```

프로젝트 로컬 (기본값)인 경우, `.mcp.json` 작성:
```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

사용자가 사용자 이름/비밀번호를 입력하지 않은 경우, `env`에서 `SERVICENOW_USERNAME`과 `SERVICENOW_PASSWORD`를 제거합니다.

---

#### claude-desktop

구성 파일 위치:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

파일이 이미 존재하면, 기존 `mcpServers` 객체에 **병합**합니다. 다른 서버 설정을 덮어쓰지 마세요.

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### cursor

구성 파일: 프로젝트 루트의 `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### vscode-copilot

구성 파일: 프로젝트 루트의 `.vscode/mcp.json`

```json
{
  "servers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### opencode

구성 파일: 프로젝트 루트의 `opencode.json`. 주요 차이점: `env` 대신 `environment`를 사용하며, 환경 변수로 설정을 전달하고, 명령어를 배열로 감쌉니다.

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
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### codex

구성 파일: 프로젝트 루트의 `.codex/config.toml` (또는 전역 설정의 경우 `~/.codex/config.toml`)

```toml
[mcp_servers.servicenow]
command = "uvx"
args = [
  "--with", "playwright",
  "--from", "mfa-servicenow-mcp",
  "servicenow-mcp",
  "--instance-url", "$INSTANCE_URL",
  "--auth-type", "$AUTH_TYPE",
  "--browser-headless", "$HEADLESS",
  "--tool-package", "$TOOL_PACKAGE",
]
```

---

#### windsurf

구성 파일: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp",
        "--instance-url", "$INSTANCE_URL",
        "--auth-type", "$AUTH_TYPE",
        "--browser-headless", "$HEADLESS"
      ],
      "env": {
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### gemini

Gemini CLI에서 작동합니다. 구성 파일: `~/.gemini/settings.json` (기존 파일에 병합).

```json
{
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": [
        "uvx", "--with", "playwright",
        "--from", "mfa-servicenow-mcp", "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      },
      "enabled": true
    }
  }
}
```

---

#### zed

구성 파일: `~/.config/zed/settings.json` (macOS/Linux)

기존 `settings.json` 파일에 `context_servers` 블록을 **병합**합니다. 파일 전체를 덮어쓰지 마세요.

```json
{
  "context_servers": {
    "servicenow": {
      "command": "uvx",
      "args": [
        "--with", "playwright",
        "--from", "mfa-servicenow-mcp",
        "servicenow-mcp"
      ],
      "env": {
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

#### antigravity

구성 파일:
- **macOS / Linux:** `~/.gemini/antigravity/mcp_config.json`
- **Windows:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

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
        "SERVICENOW_INSTANCE_URL": "$INSTANCE_URL",
        "SERVICENOW_AUTH_TYPE": "$AUTH_TYPE",
        "SERVICENOW_BROWSER_HEADLESS": "$HEADLESS",
        "SERVICENOW_USERNAME": "$USERNAME",
        "SERVICENOW_PASSWORD": "$PASSWORD",
        "MCP_TOOL_PACKAGE": "$TOOL_PACKAGE"
      }
    }
  }
}
```

---

### 5단계 — 스킬 설치 (지원되는 경우)

스킬은 LLM 실행 청사진입니다. 안전 게이트와 정확한 도구 호출이 포함된 검증된 파이프라인입니다. 커스텀 명령어/스킬을 지원하는 클라이언트에서 사용할 수 있습니다.

사용자에게 질문:
> ServiceNow 스킬(분석, 디버깅, 배포를 위한 20개 워크플로 레시피)을 설치할까요? [Y/n]

'예'인 경우, `$CLIENT`에서 스킬 대상을 결정합니다:

| 클라이언트 | 스킬 대상 | 설치 경로 |
|--------|-------------|--------------|
| claude-code | `claude` | `.claude/commands/servicenow/` |
| codex | `codex` | `.codex/skills/servicenow/` |
| opencode | `opencode` | `.opencode/skills/servicenow/` |
| gemini | `gemini` | `.gemini/skills/servicenow/` |
| cursor | — | 아직 지원되지 않음 (대신 CLAUDE.md 규칙 사용) |
| windsurf | — | 아직 지원되지 않음 |
| zed | — | 아직 지원되지 않음 |
| vscode-copilot | — | 아직 지원되지 않음 |
| claude-desktop | — | 해당 사항 없음 (프로젝트 워크스페이스 없음) |

지원되는 클라이언트의 경우, 다음을 실행:
```bash
uvx --from mfa-servicenow-mcp servicenow-mcp-skills $SKILL_TARGET
```

지원되지 않는 클라이언트의 경우, 사용자에게 알립니다:
> $CLIENT에서는 스킬이 아직 지원되지 않습니다. MCP 도구(97개 이상)는 모두 사용 가능합니다. 스킬 지원은 향후 릴리스에서 추가될 예정입니다.

### 6단계 — 설치 확인

1. **uv 확인:** `uv --version`
2. **playwright 확인:** `uvx --with playwright playwright --version`
3. **구성 파일 존재 확인:** 4단계에서 생성한 구성 파일 읽기
4. **스킬 확인 (설치한 경우):** 스킬 파일이 제자리에 있는지 확인

사용자에게 요약을 보고합니다:

```
Setup complete!

  Client:       $CLIENT
  Instance:     $INSTANCE_URL
  Auth:         $AUTH_TYPE
  Tool package: $TOOL_PACKAGE
  Skills:       $SKILL_COUNT installed (or "not applicable")
  Config:       $CONFIG_FILE_PATH
```

**다음: 재시작 필요**

위의 모든 설치 단계를 완료한 후, 사용자에게 다음과 같이 안내합니다:

> **설치가 완료되었습니다!**
> ServiceNow MCP 도구를 사용하려면 **AI 클라이언트를 재시작**하세요 (또는 MCP 서버를 다시 로드하세요).
> >
> > MCP 서버는 클라이언트가 시작될 때 로드됩니다. 재시작 후:
> >
> > 1. 첫 번째 도구 호출 시 MFA/SSO 로그인을 위해 브라우저 창이 열립니다
> > 2. 로그인을 완료하면 이후에는 세션이 유지됩니다
> > 3. 시도해 보기: "Run a health check on my ServiceNow instance"
> > 4. 전체 문서: https://jshsakura.github.io/mfa-servicenow-mcp/

이것으로 설정이 끝입니다. 이 세션에서 ServiceNow MCP 도구(`sn_health`, `sn_query` 등)를 호출하지 마세요. 클라이언트가 재시작되어 서버 프로세스를 로드하기 전까지는 사용할 수 없습니다. 셸 명령어로 서버를 실행하는 등의 우회 방법을 시도하지 마세요.

### LLM을 위한 중요 참고 사항

- 구성 파일에 자격 증명을 **절대 하드코딩하지 마세요**. 사용자가 자격 증명 입력을 건너뛰면 구성에서 완전히 제외합니다.
- 기존 구성 파일에는 항상 **병합**하세요. 사용자가 설정한 다른 MCP 서버를 덮어쓰지 마세요.
- **Windows 경로**는 백슬래시를 사용합니다. 운영 체제에 맞는 올바른 경로 구분자를 사용하세요.
- 어떤 단계라도 실패하면, 오류를 진단하고 다음 단계로 넘어가기 전에 사용자가 해결할 수 있도록 도와주세요.
- 대화는 친절하고 간결하게 유지하세요. 긴 텍스트를 한 번에 쏟아내지 마세요.
- 설치 후 MCP 도구를 테스트하지 마세요. 사용자에게 재시작하라고 안내하고 끝내세요.
