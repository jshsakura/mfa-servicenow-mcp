# Windows 安装指南

默认使用 `uvx`。如果端点安全软件/Zscaler 阻止了 `uvx` 或包下载，请使用下面的发布版 zip/exe 一节。

---

## 第 1 步：默认的 uvx 安装

在不具备管理员权限的情况下打开 PowerShell：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

这会安装 `uv`、获取并验证服务器，并下载 Chromium。然后将服务器添加到你的 MCP 客户端配置文件（无需安装命令）：

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

如果标准 Playwright 缓存中已有匹配的 Chromium，`uvx` 会复用它；如果 Chromium 缺失，请先运行上面的安装命令。

---

## 第 2 步：发布版 zip/exe 安装

当 `uvx` 被阻止时使用此方式。从 GitHub Releases 下载 `servicenow-mcp-windows-x64-<version>.zip`。它包含单个由 PyInstaller 构建的 `servicenow-mcp.exe` 以及 `LICENSE`。无需安装脚本 —— 可执行文件自行处理 Chromium 的发现。挑选一个你掌控的稳定文件夹（例如 `C:\Users\you\apps\servicenow-mcp\`），将 `servicenow-mcp.exe` 解压进去，并且 —— 如果你有 Chromium zip —— **预先把它解压**到同一文件夹中。不要把 `.zip` 留在那里。解压出的文件夹名可以保持 Windows 生成的样子，也可以重命名为 `ms-playwright\`；可执行文件在启动时会通配查找任意同级的 `ms-play*` 目录：

```
C:\Users\you\apps\servicenow-mcp\
├── servicenow-mcp.exe
└── ms-playwright-chromium-windows-x64-<ver>\   (默认解压名即可)
    └── chromium-1185\
        └── …
```

启动时，可执行文件会查找任意同级的 `ms-play*\chromium-*` 目录，并仅为当前进程通过 `PLAYWRIGHT_BROWSERS_PATH` 将 Playwright 指向它。它不会触碰系统标准 Playwright 缓存（`%LOCALAPPDATA%\ms-playwright`），不会修改任何 MCP 客户端配置，也不会在磁盘上任何位置写入。

然后将以下内容粘贴到你的客户端配置文件中（以 Claude Code / Claude Desktop 为例）：

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

`SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` 是可选的 MFA 登录预填。如果你把 Chromium 放在了同级 `ms-playwright\` 目录以外的位置，请在 `env` 块中添加 `"PLAYWRIGHT_BROWSERS_PATH": "C:/abs/path/to/ms-playwright"`。Codex（`config.toml`）/ OpenCode（`opencode.json`）/ Cursor / Antigravity / Zed 的片段见[客户端安装指南](CLIENT_SETUP.md)。

这样可以让 `uvx` 完全不参与运行时。

如果 Chromium 未被捆绑且允许下载，请从 <https://www.python.org/downloads/> 安装 Python，然后运行：

```powershell
py -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = "$HOME\apps\servicenow-mcp\ms-playwright"
py -m playwright install chromium
```

如果 Playwright 浏览器下载也被阻止，请从 chromium-bundle 发布版（https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle）下载 `ms-playwright-chromium-windows-x64.zip`，并将其内容解压到：

```text
%LOCALAPPDATA%\ms-playwright
```

Playwright 浏览器文档：<https://playwright.dev/python/docs/browsers>

---

## 第 3 步：构建发布资产

维护者在 Windows 上构建发布版 zip：

```powershell
py scripts\build_desktop_release.py --browser-zip
```

这会创建可执行文件 zip，以及供受阻网络使用的可选 Playwright Chromium 缓存 zip。

---

## 第 4 步：配置你的 MCP 客户端

复制下面适用于你的 MCP 客户端的配置。
将 `your-instance` 替换为你实际的 ServiceNow 实例地址。

### Claude Desktop

配置文件位置：`%APPDATA%\Claude\claude_desktop_config.json`

> 如果文件不存在，请创建它。如果文件夹缺失，先启动一次 Claude Desktop 以创建它。

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

通过 CLI 注册 —— 无需配置文件：

```powershell
claude mcp add servicenow -- uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --instance-url "https://your-instance.service-now.com" --auth-type browser --browser-headless false
```

验证：
```powershell
claude mcp list
```

### OpenAI Codex

配置文件位置：`%USERPROFILE%\.codex\agents.toml` 或项目根目录下的 `.codex\agents.toml`。

> 如果文件和文件夹不存在，请创建它们。

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

配置文件位置：项目根目录下的 `opencode.json`。

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

配置文件位置：`~/.config/zed/settings.json`

> 在 Zed 中通过 **Settings** > **MCP Servers** 添加：

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

配置文件位置：`%USERPROFILE%\.gemini\antigravity\mcp_config.json`

> 也可通过代理面板 **...** → **Manage MCP Servers** → **View raw config** 访问。

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

> 保存配置，然后在 AntiGravity 中点击 **Refresh**。

---

## 第 5 步：安装技能（可选）

技能是 AI 执行蓝图 —— 带安全门控的经验证流水线，把原始 MCP 工具变成可靠的工作流。3 个类别共 4 个技能。

```powershell
# Claude Code
servicenow-mcp-skills claude

# OpenAI Codex
servicenow-mcp-skills codex

# OpenCode
servicenow-mcp-skills opencode

# 或使用 uvx（无需安装）
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude
```

| 客户端 | 安装路径 | 自动发现 |
|--------|-------------|----------------|
| Claude Code | `.claude\commands\servicenow\` | `/servicenow` 斜杠命令在下次启动时出现 |
| OpenAI Codex | `.codex\skills\servicenow\` | 技能在下次代理会话时加载 |
| OpenCode | `.opencode\skills\servicenow\` | 技能在下次会话时加载 |

| 类别 | 技能数 | 用途 |
|----------|--------|---------|
| `analyze/` | 6 | Widget 分析、门户诊断、依赖映射、代码检测 |
| `fix/` | 3 | Widget 修补（分阶段安全门控）、调试、代码审查 |
| `manage/` | 8 | 页面布局、script include、源码导出、应用源码下载、变更集工作流、本地同步、工作流管理、技能管理 |
| `deploy/` | 2 | 变更请求生命周期、事件分诊 |
| `explore/` | 5 | 健康检查、schema 发现、路由追踪、flow 触发器追踪、ESC 目录流程 |

**更新：** 重新运行同一条安装命令即可替换所有现有的技能文件。
**仅移除技能：** 手动删除技能目录（例如 `Remove-Item -Recurse .claude\commands\servicenow\`）。

---

## 第 6 步：验证

1. **完全退出并重启**你的 MCP 客户端（同时关闭托盘图标）。
2. 浏览器窗口在第一次工具调用时打开（而非服务器启动时）。
3. 通过 Okta/Microsoft Authenticator 等完成 MFA 认证。
4. 认证后，浏览器自动关闭，会话得以保留。

测试：从你的客户端调用 `sn_health` 工具。

> 如果浏览器没有打开，请检查 Chromium 是否已安装。你可以用以下命令强制安装：`uvx --with playwright playwright install chromium`

---

## 会话管理

已认证的会话会自动保存到磁盘 —— 无需每次都登录。

- **会话文件位置**：`%USERPROFILE%\.servicenow_mcp\session_*.json`
- **默认会话 TTL**：30 分钟（keepalive 线程每 15 分钟延长一次）
- **会话过期时**：浏览器窗口自动打开以重新认证

要更改 TTL，使用 `--browser-session-ttl` 选项（单位为分钟）：
```
--browser-session-ttl 60
```

要持久化浏览器配置文件，添加 `--browser-user-data-dir` 选项：
```
--browser-user-data-dir "%USERPROFILE%\.mfa-servicenow-browser"
```
这会将 cookie 和登录状态存储到该目录，以实现更长的会话持久化。

---

## 工具包

设置 `MCP_TOOL_PACKAGE` 来选择一组工具。默认值：`standard`（只读）。

| 包 | 工具数 | 描述 |
|---------|:-----:|-------------|
| `core` | 12 | 用于健康检查、schema、发现和关键查询的极简只读基础工具 |
| `standard` | 27 | **（默认）** 覆盖 incident、change、门户、日志和源码分析的只读包 |
| `service_desk` | 29 | standard + 事件与变更的操作性写入 |
| `portal_developer` | 38 | standard + 门户、变更集、script include 和本地同步交付工作流 |
| `platform_developer` | 43 | standard + 工作流、Flow Designer、UI policy、incident/change 和脚本写入 |
| `full` | 57 | 最广泛的打包功能面：所有 `manage_*` 工作流加上高级操作 |

要更改，更新 `MCP_TOOL_PACKAGE` 的值：

JSON 客户端（Claude Desktop、AntiGravity）：
```json
"env": {
  "MCP_TOOL_PACKAGE": "standard"
}
```

TOML 客户端（Codex）—— 添加进 `args` 数组中：
```toml
"--tool-package", "standard",
```

---

## 故障排查

### "uvx not found"
→ 确保你在第 1 步后**关闭并重新打开**了 PowerShell。如果仍然失败：
```powershell
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### "Python is not installed"
→ `uv` 会自动下载 Python 3.11+。无需手动安装。
如果与系统 Python 冲突，请卸载并重新安装 `uv`。

### "Browser won't open"
→ 必须在 MCP 启动前安装 Chromium：
```powershell
uvx --with playwright playwright install chromium
```
→ 如果浏览器下载被阻止，从 chromium-bundle 发布版下载 `ms-playwright-chromium-windows-x64.zip`，并将其解压到 `%LOCALAPPDATA%\ms-playwright`。

### "MCP server won't connect"
→ 检查配置文件语法：
  - JSON：逗号、引号、配对的花括号
  - TOML：方括号、引号、逗号
→ 验证 `instance-url` 以 `https://` 开头。
→ 配置更改后，Claude Desktop 需要**完全退出并重启**（同时关闭托盘图标）。

### "PowerShell script execution is blocked"
→ 为当前用户允许脚本执行：
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 重置会话
如果登录问题持续存在，删除会话缓存并重试：
```powershell
Remove-Item "$env:USERPROFILE\.servicenow_mcp\session_*.json"
```

### 版本更新
`uvx` 会复用它上次下载的缓存版本。它**不会**在每次运行时自动刷新到更新的发布版。要把最新发布的版本拉取到缓存：
```powershell
uvx --refresh --from mfa-servicenow-mcp servicenow-mcp --version
```

刷新后，完全重启你的 MCP 客户端，使其启动新的缓存版本。
