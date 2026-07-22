# Windows 安装指南

和其他平台一样，Windows 上也默认使用 `uvx`。只有一种 Windows 特有的情况会迫使你放弃它：

- **Smart App Control 阻止 `uvx`** → 改用 **pip**（第 1b 步）。这是 Windows 上最常见的故障，而且往往在一次 Windows 更新之后毫无征兆地出现。

如果**连 PyPI 本身都访问不了**——企业网络直接封掉了包索引——那么两条路都取不到包。请让 IT 把 `pypi.org` 和 `files.pythonhosted.org` 加入白名单，或者在内部索引上做一份镜像，再用 `pip install --index-url` 指向它安装。

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

**更新：** `uvx` 会缓存它下载过的版本并一直复用，因此必须显式拉取新的发布版：

```powershell
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

---

## 第 1b 步：Smart App Control 阻止 uvx 时改用 pip 安装

### 你会看到的现象

`uvx` 突然不工作了，而且没有任何有价值的报错。MCP 客户端提示服务器启动失败，或者 PowerShell 提示该程序已被管理员/系统策略阻止。你的配置什么都没改。这种情况经常在**一次 Windows 更新之后**开始出现，看上去像是服务器坏了，其实是启动器被拦了。

### 为什么会这样

Smart App Control（SAC）是 Windows 11 的一项功能，只允许**已签名或以其他方式确认可信**的可执行文件运行。而 `uvx` 并不运行一个长期安装好的程序 —— 它每次运行都会解包出一个**全新的、未签名的临时可执行文件**再启动它。这正是 SAC 要拦截的形态，所以 SAC 每次都会阻止它。反复重试或重装 `uv` 都没有用：按照设计，那个文件每次运行都是新的、未签名的。

新的 Windows 11 机器上 SAC 处于评估模式，之后可能自行切换到**开启**状态。这就是为什么在一台用了几个月 `uvx` 都正常的机器上，问题会凭空冒出来。

查看方式：**Windows 安全中心 → 应用和浏览器控制 → 智能应用控制设置**。

> **不要为了解决这个问题而关闭 Smart App Control。** 关闭它是一个**单向开关** —— 一旦禁用，Windows 就不允许你再把它打开。想恢复只能**重装 Windows**。为了一个包启动器而永久降低操作系统的安全等级并不划算。改用 pip 即可，它能彻底解决问题，同时保持 SAC 开启。

### pip 方式

pip 把服务器安装为普通的 Python 文件，由**已签名的** Python 解释器来运行，因此 SAC 无从拦起。

请从 [python.org 安装程序](https://www.python.org/downloads/)安装 **3.10 或更高版本**的 Python —— 该构建已签名，可以直接通过 SAC。（Microsoft Store 版 Python 同样可用。）安装时勾选 **"Add python.exe to PATH"**。然后：

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**更新：**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

请按上面所示预先装好 Chromium。把它拖到第一次工具调用时再下载，意味着约 150 MB 的下载要和 MCP 客户端的握手超时赛跑，表现出来就是 `connection closed`。

### 始终以模块方式启动，不要用控制台脚本

pip 还会在 Scripts 目录里放一个 `servicenow-mcp.exe` 垫片。**那个垫片是 pip 在你机器上生成的未签名 `.exe`，所以 SAC 会像拦截 uvx 一样拦截它。** 直接调用模块即可完全绕开它：

| 不要用 | 改用 |
|---|---|
| `servicenow-mcp` | `python -m servicenow_mcp` |
| `servicenow-mcp setup` | `python -m servicenow_mcp setup` |
| `servicenow-mcp --version` | `python -m servicenow_mcp --version` |
| `servicenow-mcp-skills claude` | `python -m servicenow_mcp.setup_skills claude` |

验证安装：

```powershell
python -m servicenow_mcp --version
```

### pip 方式下的客户端配置

只有 `command` 和 `args` 需要改。**`env` 块与 uvx 形式完全一致** —— 从第 2 步复制任意一份配置，替换开头两行即可：

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

对于 Codex 的 TOML，对应写法是 `command = "python"` / `args = ["-m", "servicenow_mcp"]`。

> 如果你的 MCP 客户端找不到 `python`，请改填绝对路径（例如 `C:/Users/you/AppData/Local/Programs/Python/Python312/python.exe`）。MCP 客户端并不总是继承你 shell 里的 PATH。

---

## 第 2 步：配置你的 MCP 客户端

复制下面适用于你的 MCP 客户端的配置。
将 `your-instance` 替换为你实际的 ServiceNow 实例地址。

> 以下示例基于默认的 `uvx` 安装方式。**如果走的是 pip 方式（第 1b 步），请把 `command` 换成 `python`，把 `args` 换成 `["-m", "servicenow_mcp"]`** —— 后面跟着的 `--instance-url` / `--auth-type` 等参数保留不动，`env` 块也原样保持。

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

## 第 3 步：安装技能（可选）

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

> **如果走的是 pip 方式（第 1b 步），请改为调用模块** —— `servicenow-mcp-skills` 同样是 pip 生成的未签名 `.exe` 垫片，会被 Smart App Control 阻止：
>
> ```powershell
> python -m servicenow_mcp.setup_skills claude
> python -m servicenow_mcp.setup_skills codex
> python -m servicenow_mcp.setup_skills opencode
> ```

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

## 第 4 步：验证

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

### 能找到 uvx，但什么都跑不起来 / 提示"已被管理员阻止" / Windows 更新后突然失效
→ 这是 **Smart App Control**，不是安装坏了。uvx 每次运行都会解包一个未签名的临时可执行文件，SAC 拒绝运行它。请改用[第 1b 步](#第-1b-步smart-app-control-阻止-uvx-时改用-pip-安装)的 pip 方式。不要关闭 SAC —— 那是个只能靠重装 Windows 才能撤销的单向开关。

### pip 装好了，但 `servicenow-mcp` 还是启动不了
→ 你调用的是 pip 生成的 `servicenow-mcp.exe` 垫片，它未签名，会像之前的 uvx 一样被 SAC 阻止。请改为调用模块：`python -m servicenow_mcp`。同时把 MCP 客户端配置改成 `"command": "python"`、`"args": ["-m", "servicenow_mcp"]`。

### "Python is not installed"
→ 走 **uvx** 方式时，`uv` 会自动下载 Python 3.11+，无需手动安装。如果与系统 Python 冲突，请卸载并重新安装 `uv`。
→ 走 **pip** 方式时，Python 由你自己提供：从 [python.org 安装程序](https://www.python.org/downloads/)安装 3.10+（已签名，可通过 Smart App Control），并勾选 **"Add python.exe to PATH"**。Microsoft Store 版 Python 同样可用。

### "Browser won't open"
→ 必须在 MCP 启动前安装 Chromium：
```powershell
uvx --with playwright playwright install chromium   # uvx
python -m playwright install chromium               # pip
```

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
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

pip 方式下：
```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

两种方式都会一并刷新 Chromium，因为更新的 Playwright 需要配套更新的 Chromium 构建。

刷新后，完全重启你的 MCP 客户端，使其启动新版本。
