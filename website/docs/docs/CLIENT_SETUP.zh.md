# MCP 客户端配置

各 MCP 客户端的详细安装说明。所有客户端使用同一个 MCP 服务器 —— 只是配置格式不同。

> **建议优先：** 使用下面的 `uvx` 安装命令。如果 `uvx` 被企业安全工具阻止，请使用发布版 zip/exe 一节。

---

## 开始之前

默认使用 `uvx`。它能让 macOS、Linux 和 Windows 上的安装与客户端配置保持一致。

### 1. 安装 uv

**macOS / Linux：**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell：**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 获取服务器 + 安装 Chromium

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # 获取并验证服务器
uvx --with playwright playwright install chromium                                   # 用于 MFA/SSO 登录的 Chromium
```

第一条命令会在客户端所使用的完全相同的 `--with playwright` 环境中预取并验证服务器，使首次启动瞬间完成。第二条命令下载 Chromium；如果标准缓存中已有匹配的 Chromium，`uvx` 会复用它。

### 3. 将服务器添加到你的 MCP 客户端配置

向客户端的配置文件中添加一个条目（无需安装命令）：

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

各客户端的文件路径和格式（Codex TOML 等）见下文；之后请重启客户端。

### 本地安装（发布版 zip/exe）

当 `uvx` 或 PyPI 被阻止时使用此方式。发布版 zip 是单个由 PyInstaller 构建的可执行文件 —— **无安装脚本，无需 Python，不污染系统缓存**。可执行文件会自动检测位于自身旁边的 `ms-playwright/` 目录。

**1. 下载。** 从[最新发布版](https://github.com/jshsakura/mfa-servicenow-mcp/releases/latest)下载可执行文件；可选的 Chromium 捆绑包（仅当网络同时阻止了 Playwright 的 Chromium 下载时才需要）从长期维护的 [`chromium-bundle`](https://github.com/jshsakura/mfa-servicenow-mcp/releases/tag/chromium-bundle) 发布版下载。

| 平台 | 必需（最新发布版） | 若 Chromium 下载被阻止则补充（chromium-bundle 发布版） |
|----------|---------------------------|----------------------------------------------------------------|
| Windows x64 | `servicenow-mcp-windows-x64-<version>.zip` | `ms-playwright-chromium-windows-x64.zip` |
| macOS (Intel / Apple Silicon) | `servicenow-mcp-macos-<arch>-<version>.zip` | `ms-playwright-chromium-macos-<arch>.zip` |
| Linux x64 | `servicenow-mcp-linux-x64-<version>.zip` | `ms-playwright-chromium-linux-x64.zip` |

**2. 布置文件**，放入你掌控的任意稳定目录。**预先解压两个 zip** —— 不要把 `.zip` 文件留在可执行文件旁边。Chromium zip 解压出的文件夹只需以 `ms-play` 开头并包含一个 `chromium-*` 子目录即可：

```
~/apps/servicenow-mcp/                                  (你选择的任意目录)
├── servicenow-mcp                                      ← 来自平台 zip（Windows 上为 .exe）
└── ms-playwright-chromium-linux-x64-<ver>/             ← 默认解压名即可
    └── chromium-1185/
        └── …
```

（如果想要更整洁的名字，可重命名为 `ms-playwright/` —— 两者都可用。）启动时，可执行文件会通配查找任意同级的 `ms-play*` 目录，找到其中的 `chromium-*` 子目录后，仅为当前进程通过 `PLAYWRIGHT_BROWSERS_PATH` 将 Playwright 指向它。它**不会**触碰系统 Playwright 缓存，**不会**修改任何 MCP 客户端配置，**不会**在磁盘上任何位置写入。

**3. 验证，然后连接你的 MCP 客户端：**

```bash
# macOS / Linux
~/apps/servicenow-mcp/servicenow-mcp --version

# Windows PowerShell
& "$HOME\apps\servicenow-mcp\servicenow-mcp.exe" --version
```

将下面[配置指南](#configuration-guide)中的 MCP 配置片段粘贴到客户端的配置文件中，并将 `command` 设为可执行文件的绝对路径。`env` 块与 uvx 安装方式相同 —— 只有 `command` 不同。如果你把 Chromium 放在了可执行文件旁边以外的位置，请在 `env` 块中添加 `"PLAYWRIGHT_BROWSERS_PATH": "/abs/path/to/ms-playwright"`。

如果你跳过了 Chromium zip，而 Playwright 的自动下载又被阻止，请在一台装有 Python 的机器上预先准备好该目录：

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$HOME/apps/servicenow-mcp/ms-playwright" python -m playwright install chromium
```

自动检测会在无需额外配置的情况下识别它。

> Windows 用户：分步细节及代理/杀毒软件注意事项请参阅 [Windows 安装指南](WINDOWS_INSTALL.md)。

### 快速测试

在配置客户端之前先验证服务器能否启动：

```bash
uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "browser" \
  --browser-headless "false"
```

如果服务器启动并打开一个用于登录的浏览器窗口，就可以按下文配置你的客户端了。

---

## 配置指南

> **`args` 仅用于包本身** —— 实例 URL、认证、凭据全部放在 `env`（或 `environment`）中。这能让 args 保持简洁，并便于为每个项目切换实例。

> **推荐使用项目本地配置**：使用项目范围的配置，让每个项目都能连接到不同的 ServiceNow 实例。

> **按设计仅有单个活动实例**：普通工具仅路由到一个活动的 ServiceNow 实例。这是有意为之，以避免请求时的写入切换 —— 在 dev/test/prod 之间移动时，这种切换可能导致意外写入生产环境。

---

## Streamable HTTP

默认传输方式是 `stdio`。对于远程 MCP 客户端或本地 HTTP 桥接，使用 Streamable HTTP 启动服务器：

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP 端点为 `http://127.0.0.1:8000/mcp`；`/health` 返回一个轻量级状态响应。除非服务器处于受信任的网络管控之后，否则请保持默认的回环主机。

---

## 只读数据比对模式

对于 dev/test 的漂移分析，你可以用 `SERVICENOW_INSTANCE_CONFIG` 配置命名实例。此模式有意被限制为仅做数据比对：

- 普通工具仍仅路由到 `SERVICENOW_ACTIVE_INSTANCE`。
- 具备写入能力的工具不暴露实例选择器。
- `compare_instances` 为只读，跨别名比对记录。
- `list_instances` 仅报告已配置的别名。
- 使用只读包并设 `allow_writes=false` 来配置比对别名。
- 不要用此模式跨环境进行写入工作。

```bash
SERVICENOW_ACTIVE_INSTANCE=dev
SERVICENOW_INSTANCE_CONFIG='{
  "dev": {
    "url": "https://acme-dev.service-now.com",
    "tool_package": "standard",
    "allow_writes": false
  },
  "test": {
    "url": "https://acme-test.service-now.com",
    "tool_package": "standard",
    "allow_writes": false
  }
}'
```

各实例的凭据放在 MCP 客户端的 `env` 块中（每个别名都可携带自己的 `username` / `password` / `auth_type` / `api_key`；`${ENV}` 让密钥不出现在 JSON 中；单实例的 `SERVICENOW_INSTANCE_URL` 形式仍可作为回退）：

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mfa-servicenow-mcp@latest"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

比对示例：

```json
{
  "source": "dev",
  "target": "test",
  "table": "sys_script_include",
  "key_field": "api_name",
  "fields": "api_name,name,active,script",
  "query": "sys_scope.scope=x_company_app"
}
```

针对另一个实例的实际写入工作，请使用独立的项目/客户端配置。

---

## Claude Desktop

| 范围 | 路径 |
|-------|------|
| 全局 | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| 全局 | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

> Claude Desktop 不支持项目本地配置。如需按项目设置，请使用 Claude Code。

---

## Claude Code

| 范围 | 路径 |
|-------|------|
| 全局 | `~/.claude.json` |
| 项目 | 项目根目录下的 `.mcp.json` |

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

---

## Zed

| 范围 | 路径 |
|-------|------|
| 全局 | `~/.config/zed/settings.json` |

在 Zed 中通过 **Settings** > **MCP Servers** 添加：

```json
{
  "servicenow": {
    "command": "uvx",
    "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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
```

---

## OpenAI Codex（CLI 与 App）

**Codex CLI**（`codex` 命令）和 **Codex App**（chatgpt.com/codex）都从同一个 `config.toml` 读取配置。

| 范围 | 路径 | 备注 |
|-------|------|------|
| 全局 | `~/.codex/config.toml` | 所有项目共享 |
| 项目 | `.codex/config.toml` | 覆盖全局（仅限受信任的项目） |

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
SERVICENOW_BROWSER_HEADLESS = "false"
SERVICENOW_USERNAME = "your-username"
SERVICENOW_PASSWORD = "your-password"
MCP_TOOL_PACKAGE = "standard"
# 登录会在各主机间自动共享（在 ~/.mfa_servicenow_mcp 下按实例 + 用户
# 进行范围隔离）。仅当某个沙箱化主机重映射了 HOME 时才设置
# SERVICENOW_BROWSER_USER_DATA_DIR —— 见 README 的 "Login sharing" 说明。运行
# 多个实例时不要设置它；它会把多个实例合并到同一个 Chromium 配置文件中。
```

---

## OpenCode

| 范围 | 路径 |
|-------|------|
| 项目 | 项目根目录下的 `opencode.json` |

> OpenCode 使用 `environment`（而非 `env`）。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "enabled": true,
      "environment": {
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

---

## AntiGravity

| 范围 | 路径 |
|-------|------|
| 全局 | `~/.gemini/antigravity/mcp_config.json` (macOS/Linux) |
| 全局 | `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) |

> 通过代理面板编辑：**...** > **Manage MCP Servers** > **View raw config**。保存后点击 **Refresh**。

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
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

---

## Docker（仅 API 密钥）

> 浏览器认证（MFA/SSO）需要图形界面浏览器，无法在容器内工作。

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  -e MCP_TOOL_PACKAGE=standard \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```
