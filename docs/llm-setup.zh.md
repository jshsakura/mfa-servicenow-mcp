# MFA ServiceNow MCP — LLM 安装指南

> **本文件面向 LLM 代理，而非人类用户。**
> 用户将下面的 curl 命令粘贴到其 AI 编码助手中。
> LLM 读取本文件并以交互方式引导用户完成安装。

---

## 使用方法（面向人类用户）

将以下内容粘贴到你的 AI 编码助手中（Claude Code、Cursor、Codex、OpenCode、Windsurf 等）：

```
Install and configure mfa-servicenow-mcp by following:
curl -s https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md
```

就这样。剩下的交给你的 AI。

---

## 面向 LLM 代理的说明

你正在安装 **mfa-servicenow-mcp** —— 一个让 AI 代理能够访问支持 MFA/SSO 的 ServiceNow 平台的 MCP 服务器。请按顺序执行下面的每一步。以交互方式向用户提问；不要擅自假设取值。

### 第 0 步 — 检测环境

1. 检测操作系统：运行 `uname -s 2>/dev/null || echo Windows`
2. 检测你正在其中运行的 AI 客户端。使用以下对照表：

| 信号 | 客户端 |
|--------|--------|
| 你可以访问 `claude mcp add` 或 `.claude/` 目录 | **claude-code** |
| 你在 Cursor IDE 内，或存在 `.cursor/` | **cursor** |
| 你可以访问 OpenCode CLI，或存在 `opencode.json` | **opencode** |
| 你在 Codex CLI 内，或存在 `.codex/` | **codex** |
| 你在 Windsurf IDE 内，或存在 `.windsurf/` | **windsurf** |
| 你在带有 Copilot 的 VS Code 内 | **vscode-copilot** |
| 你在 Antigravity 内 | **antigravity** |
| 你在 Zed 编辑器内，或存在 `~/.config/zed/` | **zed** |
| 以上均不符合 | 询问用户使用的是哪个客户端 |

3. 如果无法自动检测，请询问：
   > 你使用的是哪款 AI 编码工具？
   > 1. Claude Code
   > 2. Claude Desktop
   > 3. Cursor
   > 4. OpenCode
   > 5. Codex (OpenAI)
   > 6. Windsurf
   > 7. VS Code Copilot
   > 8. Zed
   > 9. AntiGravity (Google)

将结果存为 `$CLIENT`。

### 第 1 步 — 安装 uv

检查是否已安装 `uv`：`uv --version`

如果尚未安装：

- **macOS / Linux：**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell)：**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

安装后，验证：`uv --version`
如果提示找不到命令，用户可能需要重启 shell，或将 `~/.local/bin` 加入 PATH。

### 第 2 步 — 安装 Playwright Chromium（必做，切勿跳过）

> 这是硬性依赖。跳过此步是现场安装失败的头号原因。
> 不要假设它已经安装。不要让用户推迟此步。
> 在此步成功之前不要进入第 3 步。

**2.1 — 检查 Chromium 是否已安装**

- macOS：`ls ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium 2>/dev/null`
- Linux：`ls ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null`
- Windows (PowerShell)：`Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright\chromium-*\chrome-win\chrome.exe" -ErrorAction SilentlyContinue`

如果打印出了路径，说明 Chromium 已安装 —— 跳到第 3 步。

**2.2 — 安装 Chromium**

如果 2.1 没有任何发现，通过 `uvx` 安装 Chromium，使 Playwright 的安装方式与 MCP 服务器的执行方式保持一致：

```bash
uvx --with playwright playwright install chromium
```

首次会下载约 150 MB。在慢速链路上可能需要几分钟 —— 这是正常的。不要提前中止。向用户显示进度提示（"正在下载用于 ServiceNow MFA 登录的 Chromium —— 在慢速网络上可能需要几分钟……"），让他们理解这段等待。

如果 `uvx` 的包执行被阻止，改用发布版 zip/exe 路径：

- 从 GitHub Releases 下载 `servicenow-mcp-<platform>-<version>.zip`。没有安装脚本 —— zip 中只包含由 PyInstaller 构建的可执行文件。
- 将该可执行文件解压到用户掌控的任意稳定目录（例如 `~/apps/servicenow-mcp/`）。
- 如果浏览器下载也被阻止，从同一发布版下载 `ms-playwright-chromium-<platform>-<version>.zip`，并解压到名为 `ms-playwright/` 的同级文件夹中 —— 可执行文件在启动时会自动检测该布局，并为其自身进程将 `PLAYWRIGHT_BROWSERS_PATH` 设置为该目录。
- 将 MCP 客户端的 `command` 设为该可执行文件的绝对路径。env 块与 uvx 安装方式相同。

**2.3 — 验证并在失败时停止**

重新运行 2.1 中的检查。如果二进制文件仍然缺失，**停止安装**，并把确切的命令输出报告给用户。常见原因：

- 公司策略阻止包或浏览器下载；改用发布版 zip/exe 路径
- 杀毒软件隔离了 Chromium 压缩包
- 磁盘已满

在 Chromium 缺失的情况下**不要**继续进入第 3 步。MCP 服务器看似会启动，但第一次工具调用会挂起，用户的登录窗口永远不会打开 —— 这正是本步骤所要防止的失败模式。

**为什么这很重要（供代理参考的背景 —— 除非用户询问，否则不要透露给用户）：** 当 Chromium 缺失时，运行时会尝试回退到"按需安装"，但在慢速连接上该下载会超过 MCP 主机的工具调用超时。用户看不到登录窗口、看不到错误界面，便以为服务器坏了。在此处预先安装可使第一次工具调用在亚秒级完成。

### 第 3 步 — 收集用户配置

逐个向用户提出以下问题。在方括号中提供默认值。

1. **ServiceNow 实例 URL**
   > 你的 ServiceNow 实例 URL 是什么？
   > 示例：`https://your-company.service-now.com`

   存为 `$INSTANCE_URL`。验证它看起来像一个 URL。

2. **认证类型**
   > 你如何向 ServiceNow 认证？
   > 1. browser —— 通过真实浏览器进行 MFA/SSO（推荐）
   > 2. basic —— 用户名 + 密码
   > 3. oauth —— OAuth 2.0 客户端凭据
   > 4. api_key —— REST API 密钥

   存为 `$AUTH_TYPE`。默认值：`browser`

3. **凭据**（可选，用于在浏览器认证时预填表单）
   > （可选）输入你的 ServiceNow 用户名以预填登录表单。
   > 留空则每次手动输入。

   存为 `$USERNAME`（可为空）。
   如果提供了用户名，再询问 `$PASSWORD`。

4. **工具包**
   > 你需要哪个工具包？
   > 1. standard —— 核心工具（incident、change、catalog）[默认]
   > 2. service_desk —— standard + 指派、SLA、升级
   > 3. portal_developer —— standard + 门户 widget、page、theme
   > 4. platform_developer —— standard + 脚本、flow、update set
   > 5. full —— 最广泛的打包功能面，附带捆绑的工作流（53 个工具）

   存为 `$TOOL_PACKAGE`。默认值：`standard`

5. **无头浏览器**
   > 以无头模式运行浏览器吗？（无可见窗口）
   > 推荐：否（这样你才能看到并完成 MFA 提示）

   存为 `$HEADLESS`。默认值：`false`

### 第 4 步 — 运行安装命令

**重要：当客户端支持时，始终默认采用项目本地安装。** 只有在用户明确要求全局安装时才使用 `--scope global`。

构建单条安装命令，并从当前项目根目录运行。安装程序现在负责：
- 各客户端专属的配置文件路径
- 对现有配置文件的合并/更新行为
- 为受支持的客户端可选地安装技能

基础命令：

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup "$CLIENT" \
  --instance-url "$INSTANCE_URL" \
  --auth-type "$AUTH_TYPE" \
  --tool-package "$TOOL_PACKAGE" \
  --browser-headless "$HEADLESS"
```

仅在需要时添加标志：

- 如果用户提供了用户名：`--username "$USERNAME"`
- 如果用户提供了密码：`--password "$PASSWORD"`
- 对于 OAuth：添加 `--client-id`、`--client-secret`，以及可选的 `--token-url`
- 对于 API 密钥：添加 `--api-key`，以及可选的 `--api-key-header`
- 如果用户想要全局安装：添加 `--scope global`
- 如果用户**不**想要技能：添加 `--skip-skills`

示例：

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup opencode \
  --instance-url "https://your-instance.service-now.com"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup codex \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type basic \
  --username "your-username" \
  --password "your-password"
```

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp setup claude-code \
  --instance-url "https://your-instance.service-now.com" \
  --scope global \
  --skip-skills
```

### 第 5 步 — 验证安装

1. 确认安装程序成功退出
2. 读取安装程序摘要中报告的配置文件路径
3. 如果安装了技能，确认已安装的技能目录存在
4. 除非安装程序失败且你正在明确修复，否则**不要**手动重写配置

### 第 6 步 — 告知用户接下来会发生什么

安装完成后，告知用户：

> **安装完成！**
> 重启你的 AI 客户端（或重新加载 MCP 服务器），以便它读取新配置。
>
> 在第一次基于浏览器认证的工具调用时，会打开一个浏览器窗口用于 MFA/SSO 登录。
> 登录后，尝试：`Run a health check on my ServiceNow instance`
> 完整文档：https://jshsakura.github.io/mfa-servicenow-mcp/

安装后，不要在当前会话中尝试调用 ServiceNow MCP 工具。客户端必须先重启。

### 面向 LLM 的重要提示

- **绝不在未询问的情况下将凭据硬编码**进配置文件。如果用户跳过凭据，请将其完全从配置中省略。
- 安装程序会合并到现有配置文件中。除非需要修复，否则不要手工拼凑配置合并。
- **Windows 路径**使用反斜杠。请为相应操作系统使用正确的路径分隔符。
- 如果任何一步失败，先诊断错误并帮助用户修复，再继续下一步。
- 保持对话友好简洁。不要堆砌大段文字。
- 安装后，不要尝试测试 MCP 工具。只需告诉用户重启即可。
