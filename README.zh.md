# MFA ServiceNow MCP

🌐 [English](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.md) | 🇰🇷 [한국어](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md) | 🇯🇵 [日本語](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ja.md) | 🇮🇳 [हिन्दी](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.hi.md) | 🇨🇳 [简体中文](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.zh.md) | 🇪🇸 [Español](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.es.md) | 🚀 [**GitHub Pages**](https://jshsakura.github.io/mfa-servicenow-mcp/)

MFA 优先的 ServiceNow MCP 服务器。通过真实浏览器（Playwright）进行认证，因此 Okta、Entra ID、SAML 以及任何 MFA/SSO 登录都能直接使用。同时也支持用于无界面/Docker 环境的 API Key。

[![PyPI version](https://img.shields.io/pypi/v/mfa-servicenow-mcp.svg)](https://pypi.org/project/mfa-servicenow-mcp/)
[![Python Version](https://img.shields.io/pypi/pyversions/mfa-servicenow-mcp)](https://pypi.org/project/mfa-servicenow-mcp/)
[![CI](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jshsakura/mfa-servicenow-mcp/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-mfa--servicenow--mcp-blue?logo=docker)](https://ghcr.io/jshsakura/mfa-servicenow-mcp)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-live-blue?logo=github)](https://jshsakura.github.io/mfa-servicenow-mcp/)

> [!WARNING]
> **为个人使用而构建——使用风险自负。** 本项目主要为作者自己的工作流而创建。风险已被积极降至最低（只读默认值、写入防护、试运行预览，以及每次写入都有 `confirm='approve'` 门槛），但它针对的是**正在运行的 ServiceNow 实例**。你需要对它在你的实例上的所有行为负全部责任。本项目按**"原样"提供，不附带任何形式的担保**（Apache-2.0，见 [LICENSE](LICENSE)）。在批准某个工具之前，请先审查它将要执行的操作。

---

## 目录

- [功能特性](https://github.com/jshsakura/mfa-servicenow-mcp#features)
- [安装设置](https://github.com/jshsakura/mfa-servicenow-mcp#setup)
- [MCP 客户端配置](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration)
- [认证](https://github.com/jshsakura/mfa-servicenow-mcp#authentication)
- [工具包](https://github.com/jshsakura/mfa-servicenow-mcp#tool-packages)
- [CLI 参考](https://github.com/jshsakura/mfa-servicenow-mcp#cli-reference)
- [保持更新](https://github.com/jshsakura/mfa-servicenow-mcp#keeping-up-to-date)
- [安全策略](https://github.com/jshsakura/mfa-servicenow-mcp#safety-policy)
- [性能优化](https://github.com/jshsakura/mfa-servicenow-mcp#performance-optimizations)
- [本地源代码审计](https://github.com/jshsakura/mfa-servicenow-mcp#local-source-audit)
- [技能](https://github.com/jshsakura/mfa-servicenow-mcp#skills)
- [Docker](https://github.com/jshsakura/mfa-servicenow-mcp#docker)
- [开发者设置](https://github.com/jshsakura/mfa-servicenow-mcp#developer-setup)
- [文档](https://github.com/jshsakura/mfa-servicenow-mcp#documentation)
- [相关项目](https://github.com/jshsakura/mfa-servicenow-mcp#related-projects-and-acknowledgements)
- [许可证](https://github.com/jshsakura/mfa-servicenow-mcp#license)

---

## 安装设置

两个步骤：**安装**，然后**将服务器添加到你的 MCP 客户端配置中**。无需安装命令，无需逐客户端标志。

### 1. 安装

默认方式是 **`uvx`**——无需单独的安装步骤，直接运行即可。对大多数人来说，这就是全部。

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version  # 获取并验证服务器
uvx --with playwright playwright install chromium                                   # 用于 MFA/SSO 登录的 Chromium
```

**更新时**——uvx 会缓存它下载的最后一个版本并持续复用，因此新发布版本必须用 `--refresh` 显式拉取：

```bash
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium     # Playwright 升级后需要配套的新 Chromium 构建
```

#### 如果 uvx 被阻止——改用 `pip`

Windows 的 Smart App Control 会让 uvx 完全无法运行：uvx 每次执行都会解包一个未签名的临时可执行文件，而 SAC 会拦截它。如果 uvx 在某次 Windows 更新之后突然不能用了，基本就是这个原因。此时改用 pip：

```powershell
pip install mfa-servicenow-mcp playwright
python -m playwright install chromium
```

**更新时：**

```powershell
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

用 [python.org 安装程序](https://www.python.org/downloads/)装的 Python（已签名，3.10+）可以原样通过 SAC。启动时请使用 `python -m servicenow_mcp`，而不是 `servicenow-mcp` 控制台脚本——那个脚本是 pip 生成的未签名 `.exe` 包装器，同样会被 SAC 拦截。

> 在 mac/Linux 上，用 pip 唯一需要注意的是：Homebrew 和发行版自带的 Python 会依据 [PEP 668](https://peps.python.org/pep-0668/) 拒绝全局安装（`externally-managed-environment`）。改用 python.org 安装程序，或者干脆继续用 uvx。

无论走哪条路，**预先**安装 Chromium 都很重要。把它推迟到首次工具调用意味着一个约 150 MB 的下载要跟 MCP 主机的握手截止时间赛跑，表现出来就是 `connection closed`。

> **引导式设置。** 不带任何标志运行 `servicenow-mcp setup`（pip 用户为 `python -m servicenow_mcp setup`）会引导你完成编号菜单（按编号或名称选择客户端和认证类型——无需自由文本猜测），支持英语或韩语（根据你的区域设置自动检测；可用 `SERVICENOW_MCP_LANG=ko|en` 强制指定）。

### 2. 配置你的 MCP 客户端

将服务器添加到你客户端的配置文件中。**无论你用哪种方式安装，`env` 块都完全相同**——只有 `command`/`args` 跟随你上面选择的路径：

| 安装方式 | `command` | `args` |
|---|---|---|
| uvx（默认） | `uvx` | `["--with","playwright","--from","mfa-servicenow-mcp","servicenow-mcp"]` |
| pip | `python` | `["-m","servicenow_mcp"]` |

仅需两个环境变量；`MCP_TOOL_PACKAGE` 默认为 `standard`，因此除非你需要不同的工具包，否则可省略。

#### 单个实例

如果你只用一个实例，到这里就够了。

**Claude Code** — `.mcp.json`（项目根目录）/ `~/.claude.json`（全局）：

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

如果你是通过 pip 安装的，只需把 `command`/`args` 换成下面这样——其余保持不变：

```json
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
```

**Codex** — `.codex/config.toml`（项目）/ `~/.codex/config.toml`（全局）：

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]
# pip: command = "python"  /  args = ["-m", "servicenow_mcp"]

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com"
SERVICENOW_AUTH_TYPE = "browser"
```

**OpenCode** — `opencode.json`（项目根目录）：

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
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    }
  }
}
```

其他客户端（Cursor、VS Code、Antigravity、Zed 等）以及完整的环境变量选项（认证类型、工具包）见 [MCP 客户端配置](https://github.com/jshsakura/mfa-servicenow-mcp#mcp-client-configuration)。

然后重启客户端。首次浏览器工具调用会打开一个窗口用于 Okta/Entra ID/SAML/MFA 登录。会话会持久保存——无需每次都重新登录。

#### 多个实例（dev / test / prod）

如果你同时要用 dev / test / prod，**不要起多个服务器。** 只改 `env`，一个连接就能全部管起来：

```json
      "env": {
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"allow_writes\": true }, \"prod\": { \"url\": \"https://acme.service-now.com\", \"auth_type\": \"browser\" } }"
      }
```

这只是把 alias 列表放到了 `SERVICENOW_INSTANCE_URL` 的位置，`command`/`args` 保持不变。这样一来：

- **生产环境默认受保护** —— 没有给 `allow_writes` 的 alias 是只读的。上面例子里的 `prod` 根本写不进去。
- **无需重启即可查询另一个实例** —— 给读取类工具传 `instance` 即可，例如 `sn_query(instance="prod", ...)`。
- **跨实例比较** —— 用 `compare_instances` 直接对照 dev 和 prod 上的同一个组件。
- **只登录一次** —— 浏览器会话在各 alias 之间共享。

完整规则（写入路由、防护门、`${ENV}` 引用）见[多个实例——两种方式](#配置档-vs-多进程)。只有当你必须在客户端界面上把连接从视觉上分开时，才去看那里的 **B. 多进程**。

> 希望让 AI 来完成？将以下内容粘贴到 Claude Code / Cursor / Codex 等：
> `Install and configure mfa-servicenow-mcp following https://raw.githubusercontent.com/jshsakura/mfa-servicenow-mcp/main/docs/llm-setup.md`

### 如果你的企业网络阻止安装

TLS 检查代理（Zscaler 之类）和被封锁的 PyPI 访问各有对应的路径——见[安装（离线 / 企业环境）](#安装离线--企业环境)。

---

## 功能特性

- 面向 MFA/SSO 环境（Okta、Entra ID、SAML、MFA）的**浏览器认证**
- **4 种认证模式**：Browser、Basic、OAuth、API Key
- **65 个已注册工具**，含 **6 个活动工具包配置**外加禁用的 `none`——从最简只读到广泛的捆绑式 CRUD
- **16 个工作流技能**，带安全门、子代理委派和经过验证的流水线
- **可流式 HTTP 传输**——保留 stdio 作为默认值，或为支持 HTTP 的客户端和桥接器暴露 `/mcp`
- **本地源代码审计**，带 HTML 报告、交叉引用图、死代码检测和自动生成的领域知识
- **磁盘上的权威关系图**——`_graph.json`（widget→Angular Provider，来自实时 M2M）和 `_page_graph.json`（page→widget，来自 `sp_instance`）让 LLM 可以离线回答依赖问题，而无需重新查询实例
- **增量同步**（`incremental=True`）——仅重新下载自上次同步以来更改的记录（`sys_updated_on` 水位线），类似 `git pull`；`reconcile_deletions=True` 会标记在实例上已删除的记录
- `download_app_sources` 中的**跨作用域依赖自动解析**——拉取应用引用的全局作用域 Script Includes、Widgets、Angular Providers 和 UI Macros，使本地包自成一体，便于分析
- **附件下载**（`download_attachment`）——通过附件 sys_id 或父级 `table`+`record` 将某条记录的附件文件（xlsx、PDF、Word 等）获取到本地磁盘；自动解析记录的附件并将字节写入磁盘，使 LLM 从 `saved_path` 读取它们
- 每个写入工具上的**试运行预览**（`dry_run=True`）——在产生任何副作用之前返回字段级差异、依赖计数和精度提示。使用只读 API，在所有认证模式下均可工作。
- 通过 `confirm='approve'` 进行安全的写入确认
- 负载安全限制、逐字段截断和总响应预算（200K 字符）
- 带退避的瞬态网络错误重试
- 面向 core、standard、service desk、portal developers 和 platform developers 的工具包——`full` 供高级用户使用（见[警告](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md)）
- 开发者生产力工具：活动跟踪、未提交更改、依赖映射、每日摘要
- 全面覆盖核心 ServiceNow 工件表（见[支持的表](https://github.com/jshsakura/mfa-servicenow-mcp#supported-servicenow-tables)）
- 带自动打标签、PyPI 发布和 Docker 多平台构建的 CI/CD

### 支持的 ServiceNow 表

| 工件类型 | 表名 | 源码搜索 | 开发者跟踪 | 安全（重型表） |
|--------------|------------|:---:|:---:|:---:|
| Script Include | `sys_script_include` | ✅ | ✅ | 🛡️ |
| Business Rule | `sys_script` | ✅ | ✅ | 🛡️ |
| Client Script | `sys_script_client` | ✅ | ✅ | 🛡️ |
| Catalog Client Script | `catalog_script_client` | ✅ | ⬜ | ⬜ |
| UI Action | `sys_ui_action` | ✅ | ✅ | 🛡️ |
| UI Script | `sys_ui_script` | ✅ | ✅ | 🛡️ |
| UI Page | `sys_ui_page` | ✅ | ✅ | 🛡️ |
| UI Macro | `sys_ui_macro` | ✅ | ⬜ | 🛡️ |
| Scripted REST API | `sys_ws_operation` | ✅ | ✅ | 🛡️ |
| Fix Script | `sys_script_fix` | ✅ | ✅ | 🛡️ |
| Scheduled Job | `sysauto_script` | ✅ | ⬜ | ⬜ |
| Script Action | `sysevent_script_action` | ✅ | ⬜ | ⬜ |
| Email Notification | `sysevent_email_action` | ✅ | ⬜ | ⬜ |
| ACL | `sys_security_acl` | ✅ | ⬜ | ⬜ |
| Transform Script | `sys_transform_script` | ✅ | ⬜ | ⬜ |
| Processor | `sys_processor` | ✅ | ⬜ | ⬜ |
| Service Portal Widget | `sp_widget` | ✅ | ✅ | 🛡️ |
| Angular Provider | `sp_angular_provider` | ✅ | ✅ | ⬜ |
| Portal Header/Footer | `sp_header_footer` | ✅ | ⬜ | ⬜ |
| Portal CSS | `sp_css` | ✅ | ⬜ | ⬜ |
| Angular Template | `sp_ng_template` | ✅ | ⬜ | ⬜ |
| Metadata / XML Definitions | `sys_metadata` | ✅ | ⬜ | 🛡️ |
| Update XML | `sys_update_xml` | ✅ | ⬜ | ⬜ |

---

## 安装（离线 / 企业环境）

对于大多数用户，上面的[安装设置](https://github.com/jshsakura/mfa-servicenow-mcp#setup)（uvx）即可满足所有需求。企业网络下有两种情况值得说明。

常见的情况是 **PyPI 可访问，但 HTTPS 被 TLS 检查**（Zscaler / Netskope / 企业 MITM）——下面紧接着的这一节讲的就是它。

如果 PyPI 本身被彻底封锁，uvx 和 pip 都取不到这个包。请让 IT 团队把 `pypi.org` 和 `files.pythonhosted.org` 加入白名单，或者把该包镜像到一个内部索引上，再用 `pip install --index-url` 指向它。

### 在 TLS 检查代理后面安装（Zscaler 等）

当 PyPI **可**访问，但 TLS 检查代理会重新签名 HTTPS，导致安装和运行时调用以 `SSL: CERTIFICATE_VERIFY_FAILED` 失败时，使用此方法。在 **操作系统信任库中注册代理的根 CA 并不够**——Python（`pip`、`requests`、`httpx`）、`curl_cffi` 和 Playwright 各自携带自己的 CA 包（certifi / libcurl / node），除非你通过环境变量将它们指向该证书，否则会忽略操作系统信任库。

**1. 获取代理根 CA**，作为 PEM 文件（询问 IT，或从操作系统钥匙串导出）。假设它位于 `/etc/ssl/zscaler-root.pem`（Windows：`C:\certs\zscaler-root.pem`）。

**2. 安装**——将安装程序指向该证书：

```bash
pip install --cert /etc/ssl/zscaler-root.pem mfa-servicenow-mcp
python -m playwright install chromium     # NODE_EXTRA_CA_CERTS (step 3) covers its download
```

更喜欢 uvx？`uv` 可以直接使用操作系统信任库（代理 CA 已在其中注册）：

```bash
UV_NATIVE_TLS=1 uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
```

**3. 运行时——在你的 MCP 客户端 `env` 中设置 CA 路径。** 不明显的一点是：实时 ServiceNow 调用经过 **curl_cffi (libcurl)**，它读取的是 `CURL_CA_BUNDLE`——而*不是* `REQUESTS_CA_BUNDLE`。把它们全部设置上，让每一层都信任该代理：

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "CURL_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "REQUESTS_CA_BUNDLE": "/etc/ssl/zscaler-root.pem",
        "SSL_CERT_FILE": "/etc/ssl/zscaler-root.pem",
        "NODE_EXTRA_CA_CERTS": "/etc/ssl/zscaler-root.pem"
      }
    }
  }
}
```

| 环境变量 | 它修复的层 |
|---------|----------------|
| `CURL_CA_BUNDLE` | **curl_cffi / libcurl——实际的 ServiceNow API + 浏览器登录探测调用** |
| `REQUESTS_CA_BUNDLE` | `requests`（OAuth / API-key 令牌调用、回退 HTTP 路径） |
| `SSL_CERT_FILE` | Python 标准库 `ssl` / `httpx` / `uv` |
| `NODE_EXTRA_CA_CERTS` | Playwright 的 Chromium 下载 |
| `PIP_CERT`（仅安装时） | `pip` 从 PyPI 获取（与 `--cert` 相同） |

在完全检查的网络中，代理会重新签名每个主机，因此单个代理根 PEM 覆盖所有 HTTPS。如果某些主机**绕过**了代理，则将代理根证书与 certifi 的包（`python -m certifi` 会打印其路径）拼接成一个 PEM，并将环境变量指向该文件。

> 如果你确实无法获取 PEM 文件，最后的手段：`pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org mfa-servicenow-mcp` 会**仅在安装时**跳过验证——它对运行时 ServiceNow 调用毫无作用，后者仍然需要 `CURL_CA_BUNDLE`。优先使用证书路径；`--trusted-host` 会禁用一项安全控制。

## MCP 客户端配置

> 推荐：使用上面的[安装设置](https://github.com/jshsakura/mfa-servicenow-mcp#setup)。当你需要检查、修复或手动管理客户端配置文件时，使用下面的复制粘贴配置。

每个项目都可以连接到不同的 ServiceNow 实例。将配置设在你的**项目目录**中，使每个项目都有自己的实例 URL 和凭据。

| 客户端 | 项目配置 | 全局配置 | 格式 |
|--------|---------------|--------------|--------|
| Claude Code | `.mcp.json` | `~/.claude.json` | JSON |
| Cursor | `.cursor/mcp.json` | *仅项目* | JSON |
| VS Code (Copilot) | `.vscode/mcp.json` | *仅项目* | JSON |
| Zed | *仅全局* | `~/.config/zed/settings.json` | JSON |
| OpenAI Codex | `.codex/config.toml` | `~/.codex/config.toml` | TOML |
| OpenCode | `opencode.json` | *仅项目* | JSON |
| Windsurf | *仅全局* | `~/.codeium/windsurf/mcp_config.json` | JSON |
| Claude Desktop | *仅全局* | `claude_desktop_config.json` | JSON |
| AntiGravity | *仅全局* | `~/.gemini/antigravity/mcp_config.json` | JSON |
| Docker | *仅环境变量* | *仅环境变量* | 环境变量 |

每个客户端的复制粘贴配置：**[客户端设置指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md)**

> `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` 是可选的——它们会预填充 MFA 登录表单。在 Windows 上，将它们设置为系统环境变量。

#### 配置档 vs 多进程

上面的示例是单实例的——这仍是默认设置。当实例不止一个时有两条路可走，而且值得**在动手配置之前先选定一条**：

| | **A. 配置档**（推荐） | **B. 多进程** |
|---|---|---|
| 服务器进程 | 1 个 | 每个实例一个 |
| 客户端看到的连接 | 1 个 | 3 个 |
| 如何选择实例 | 每次调用传 `instance="test"` | 固定绑定到该进程 |
| 跨实例比较 | **可用**（`compare_instances`） | 做不到——进程之间互不知情 |
| 浏览器登录 | 共享一次会话 | 每个进程各登录一次 |
| 写入控制 | 逐别名的 `allow_writes` | 逐进程的配置 |

**大多数人想要的是 A。** 写入安全在那边已经解决了——不给 prod 别名设 `allow_writes`，它就是只读的；而写入非活动实例还必须过 `confirm_instance` 这道门。除此之外，只有 A 才能做跨实例比较，并且只需登录一次。

**只有当这些连接需要在客户端界面里明显分开时，才选 B。** 那样工具名会显示为 `mcp_snow-prd_*`，人一眼就能分辨。代价是三次登录、无法比较，以及三份配置。详见[区分多个连接](#区分多个连接--server-name)。

##### A. 配置档

要在一个客户端中切换多个实例，请在 `SERVICENOW_INSTANCE_CONFIG`（别名 → 设置）中列出它们，并用 `SERVICENOW_ACTIVE_INSTANCE` 选择活动实例。每个别名都可以携带**自己的凭据**（`username` / `password` / `auth_type` / `api_key`）；`${ENV}` 引用可以把密钥排除在 JSON 之外。单实例的 `SERVICENOW_INSTANCE_URL` 形式仍可作为回退使用。

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"],
      "env": {
        "MCP_TOOL_PACKAGE": "standard",
        "SERVICENOW_ACTIVE_INSTANCE": "dev",
        "SERVICENOW_INSTANCE_CONFIG": "{ \"dev\": { \"url\": \"https://acme-dev.service-now.com\", \"auth_type\": \"browser\", \"username\": \"dev_user\", \"password\": \"${SERVICENOW_DEV_PASSWORD}\", \"allow_writes\": true }, \"test\": { \"url\": \"https://acme-test.service-now.com\", \"auth_type\": \"browser\", \"username\": \"test_user\", \"password\": \"${SERVICENOW_TEST_PASSWORD}\" } }"
      }
    }
  }
}
```

`SERVICENOW_ACTIVE_INSTANCE` 是写入操作的默认目标；读取工具可通过 `instance="test"` 窥视其他实例，而单次写入也可通过 `instance="test" confirm_instance="test" confirm="approve"` 路由到非活动实例（受保护，且在写入落地后进行验证）。完整规则（写入路由、门控、比较、`${ENV}`）：[多实例模式](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.zh.md#多实例模式比较--受保护的单次调用写入)。

##### B. 多进程

只有当你希望这些连接在客户端界面里各自分开时才值得这么做。每个条目**固定绑定一个实例**，并通过 `--server-name` 获得自己的名字：

```json
{
  "mcpServers": {
    "snow-dev": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-dev"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme-dev.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser"
      }
    },
    "snow-prd": {
      "command": "uvx",
      "args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp", "--server-name", "snow-prd"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://acme.service-now.com",
        "SERVICENOW_AUTH_TYPE": "browser",
        "MCP_TOOL_PACKAGE": "standard"
      }
    }
  }
}
```

这样工具名就固定为 `mcp_snow-dev_*` / `mcp_snow-prd_*`。若省略 `--server-name`，两者都会以 `ServiceNow` 的名义出现，客户端只能按加载顺序编号（`mcp_servicenow`、`mcp_servicenow2`）——而这个编号可能在重启之间发生变化，意味着你永远无法确信哪一个是生产环境。

要让生产连接保持只读，请给它一个只读的 `MCP_TOOL_PACKAGE`。与 A 不同，这里没有 `allow_writes` 别名门——**工具包是唯一阻挡写入的东西。**

> 登录提示会逐进程弹出，而 `compare_instances` 这类跨实例工具无法使用——每个进程只知道自己的实例。如果这一点让你难受，就选 A。

---

## 认证

根据你的 ServiceNow 环境选择认证模式。

### 浏览器认证（MFA/SSO）——默认

[安装设置](https://github.com/jshsakura/mfa-servicenow-mcp#setup)命令默认使用浏览器认证。可选标志：

| 标志 | 环境变量 | 默认 | 说明 |
|------|-------------|---------|-------------|
| `--browser-username` | `SERVICENOW_USERNAME` | — | 预填充登录表单用户名 |
| `--browser-password` | `SERVICENOW_PASSWORD` | — | 预填充登录表单密码 |
| `--browser-headless` | `SERVICENOW_BROWSER_HEADLESS` | `false` | 无 GUI 运行浏览器 |
| `--browser-timeout` | `SERVICENOW_BROWSER_TIMEOUT` | `120` | 登录超时（秒） |
| `--browser-session-ttl` | `SERVICENOW_BROWSER_SESSION_TTL` | `30` | 会话 TTL（分钟） |
| `--browser-user-data-dir` | `SERVICENOW_BROWSER_USER_DATA_DIR` | — | 覆盖 Chromium 配置文件路径。很少需要——设置前请参阅下面的沙箱说明。 |
| `--browser-probe-path` | `SERVICENOW_BROWSER_PROBE_PATH` | 当用户名已知时进行用户特定的 `sys_user` 查找，否则为 `/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id` | 会话验证端点（避免在非管理员会话上出现 401） |
| `--browser-login-url` | `SERVICENOW_BROWSER_LOGIN_URL` | — | 自定义登录页面 URL |

#### 跨主机和跨实例的登录共享——它实际如何工作

服务器在 `~/.mfa_servicenow_mcp/` 下缓存两样东西：Playwright 配置文件（Chromium SSO cookies）和一个会话 JSON（在下次启动时复用的解析后 cookies）。两者都**按实例 + 用户名作用域划分**——文件命名为 `profile_<host>_<user>` 和 `session_<host>_<user>.json`。

这种作用域划分会自动为你做两件事，**无需任何配置**：

- **多个主机共享一次登录。** 同一台机器上的 Claude Code 和 Codex 都解析到 `~/.mfa_servicenow_mcp/`，因此谁先登录谁就写入会话，另一个则复用它——不会有第二次 MFA 提示。
- **不同实例 / 不同凭据保持隔离。** 每个实例+用户都获得自己的配置文件和会话文件，因此 dev 和 test（或两个账户）永不冲突。对于多个实例，在 `SERVICENOW_INSTANCE_CONFIG`（JSON）中配置它们——每个别名都获得自己的作用域缓存；你**不**用配置文件路径来管理这一点。

**不要为了"共享"登录而设置 `SERVICENOW_BROWSER_USER_DATA_DIR`。** 它会原样覆盖配置文件路径——按实例的作用域划分被绕过，因此你运行的每个实例都被强制进入一个 Chromium 配置文件，它们的 cookies 会冲突。唯一合理的用途是一个狭窄的场景：一个**沙箱化的**主机（例如 macOS 上的 Claude Desktop）将 `HOME` 重映射到容器路径，因此它的 `~/.mfa_servicenow_mcp/` 不再与终端的相匹配。在这种单实例情形下，将沙箱化的主机指向真实的 home 路径：

```bash
# Only when a sandbox remapped HOME, and only for a single-instance host
export SERVICENOW_BROWSER_USER_DATA_DIR="/Users/you/.mfa_servicenow_mcp/profile_acme"
```

如果你运行多个实例，请将其保持未设置，让按实例的作用域划分发挥作用。

### 基本认证（Basic Auth）

用于 PDI 或没有 MFA 的实例。

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "basic" \
  --username "your_id" \
  --password "your_password"
```

### OAuth

当前的 CLI 支持期望 OAuth 密码授权（password grant）输入。

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "oauth" \
  --client-id "your_client_id" \
  --client-secret "your_client_secret" \
  --username "your_id" \
  --password "your_password"
```

如果省略 `--token-url`，服务器默认为 `https://<instance>/oauth_token.do`。

### API Key

```bash
python -m servicenow_mcp \
  --instance-url "https://your-instance.service-now.com" \
  --auth-type "api_key" \
  --api-key "your_api_key"
```

默认请求头：`X-ServiceNow-API-Key`（可用 `--api-key-header` 自定义）。

---

## 工具包

`MCP_TOOL_PACKAGE` 控制服务器暴露哪些工具。**默认：`standard`**——大多数用户无需配置。

> [!WARNING]
> **任何高于 `standard` 的工具包都授予写入访问权限，属于高级选项。** `service_desk`、`portal_developer`、`platform_developer` 和 `full` 都允许 AI 代理创建、更新和删除记录——`full` 会在所有领域中一次性做到这一点。大多数用户应保持只读默认值 `standard`，仅在任务确实需要时才升级到其所需的最窄写入工具包。

只读（安全默认值）：

| 工具包 | 工具数 | 说明 |
| :--- | :---: | :--- |
| `none` | 0 | 用于有意关闭工具的禁用配置 |
| `core` | 12 | 用于健康检查、schema、发现和关键工件查找的最简只读必需项 |
| `standard` | 27 | **（默认）** 跨 incidents、changes、portal、logs 和源码分析的只读 |

⚠️ 具备写入能力（高级——授予创建/更新/删除）：

| 工具包 | 工具数 | 说明 |
| :--- | :---: | :--- |
| `service_desk` | 29 | ⚠️ standard + incident 和 change 运营写入 |
| `portal_developer` | 38 | ⚠️ standard + portal、changeset、script include 和本地同步交付写入 |
| `platform_developer` | 43 | ⚠️ standard + workflow、Flow Designer、UI policy、incident/change 和脚本写入 |
| `full` | 57 | ⚠️ **最高级**——一次性提供所有领域的全部写入工具 |

对于普通工具，每个服务器进程都绑定到一个活动的 ServiceNow 实例。向*另一个*已配置实例的写入可以逐调用完成，但只能通过显式、受保护的确认（见下文）——绝不会静默切换。

### 多实例模式（比较 + 受保护的单次调用写入）

当你需要比较 dev/test/prod 或部署到选定的实例时，可以通过 `SERVICENOW_INSTANCE_CONFIG` 选择启用命名实例。仍需要 `SERVICENOW_ACTIVE_INSTANCE`。

两样东西是全局的，一样是逐实例的：

- **工具面是全局的**——用 `MCP_TOOL_PACKAGE` 设置一次。每个服务器进程任何时候只有一个实例处于活动状态，因此不存在逐实例的工具包。
- **写入权限是逐实例的**——每个别名携带 `allow_writes`。它在调用时针对活动实例强制执行：写入工具可以被加载，但如果活动实例的 `allow_writes: false`，它仍会被拒绝。写入是选择性启用的：省略 `allow_writes`，该实例即为只读。
- **凭据是逐实例的，带全局回退**——在某个别名上放置 `username` / `password` / `api_key`（以及 `auth_type`）以覆盖；省略它们则该别名继承全局的 `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` 等。因此如果每个实例共享一次登录，只需全局设置一次，并让别名条目保持无凭据。

其他规则：

- **读取工具接受 `instance` 参数**，以针对非活动实例运行单次读取——例如在 `dev` 保持活动时执行 `sn_query(instance="test", table="incident", ...)` 或 `sn_health(instance="test")`。你工具包中的每个读取工具都在其 schema 中暴露它（已配置别名的枚举）。这就是你在不重启的情况下窥视另一个实例数据的方式。
- **单次写入也可以路由到非活动实例**，但绝不会静默进行。传入 `instance="test" confirm_instance="test" confirm="approve"`（目标被命名两次——作为意图和确认），且目标必须设有 `allow_writes=true`。只有那一次写入会被路由到那里；紧接着活动实例即被恢复。目标/confirm 不匹配或只读目标会以明确消息被拒绝，因此 dev/test/prod 混淆不会落到错误的实例上。随后会在目标实例上重新读取该写入并报告为 `landed`（或 `WRITE_NOT_LANDED`），并回显 `target_instance`——"成功"意味着内容已确认存在于目标实例上，而不仅仅是返回了 200。
- `list_instances` 报告已配置的别名、活动的别名以及各自的写入标志。`compare_instances` 跨别名执行只读表比较。
- 切换*默认*活动实例需要重启 MCP 客户端——它在服务器启动时被读取一次，不会实时刷新。（上述逐调用的 `instance=` 路由无需重启。）

示例——共享的全局登录、逐实例的写入门控：

```bash
export MCP_TOOL_PACKAGE=standard
export SERVICENOW_USERNAME=svc_account
export SERVICENOW_PASSWORD='...'
export SERVICENOW_ACTIVE_INSTANCE=dev
export SERVICENOW_INSTANCE_CONFIG='{
  "dev":  { "url": "https://acme-dev.service-now.com",  "allow_writes": true },
  "test": { "url": "https://acme-test.service-now.com", "allow_writes": true },
  "prod": { "url": "https://acme-prod.service-now.com", "allow_writes": false }
}'
```

要让某个实例改用自己的登录，请将相应字段添加到该别名（`${ENV}` 引用会被解析，因此你可以把密钥排除在 JSON 之外）：

```json
"prod": { "url": "https://acme.service-now.com", "username": "prod_user", "password": "${SERVICENOW_PROD_PASSWORD}" }
```

使用 `compare_instances` 进行 dev/test 漂移检查。对于**批量**记录的推广（尤其是 Service Portal / scoped 表），相比逐记录的跨实例写入，更推荐使用 Update Set（在源实例 commit，在目标 UI 中 retrieve + commit）——它可以绕过单次 Table-API 写入会碰到的 per-table/SP ACL。

如果某个工具在你当前的工具包中不可用，服务器会告诉你哪个工具包包含它。

完整参考（所有工具包、继承细节、配置语法）：[工具包高级指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_PACKAGES.md)。

---

## CLI 参考

### 服务器选项

| 标志 | 环境变量 | 默认 | 说明 |
|------|-------------|---------|-------------|
| `--instance-url` | `SERVICENOW_INSTANCE_URL` | *必需* | ServiceNow 实例 URL |
| `--auth-type` | `SERVICENOW_AUTH_TYPE` | `basic` | 认证模式：`basic`、`oauth`、`api_key`、`browser` |
| `--tool-package` | `MCP_TOOL_PACKAGE` | `standard` | 要加载的工具包 |
| `--server-name` | `SERVICENOW_MCP_SERVER_NAME` | `ServiceNow` | 向客户端声明的 MCP 服务器名称 |
| `--transport` | `SERVICENOW_MCP_TRANSPORT` | `stdio` | MCP 传输：`stdio` 或 `http` |
| `--http-host` | `SERVICENOW_MCP_HTTP_HOST` | `127.0.0.1` | `--transport http` 的主机 |
| `--http-port` | `SERVICENOW_MCP_HTTP_PORT` | `8000` | `--transport http` 的端口 |
| `--http-path` | `SERVICENOW_MCP_HTTP_PATH` | `/mcp` | 可流式 HTTP 端点路径 |
| `--http-allowed-hosts` | `SERVICENOW_MCP_HTTP_ALLOWED_HOSTS` | 环回主机 | 用于 DNS 重绑定保护的逗号分隔 Host 允许列表 |
| `--http-disable-dns-rebinding-protection` | `SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION` | `false` | 在受信任的网络控制后面禁用 DNS 重绑定保护 |
| `--http-json-response` | `SERVICENOW_MCP_HTTP_JSON_RESPONSE` | `false` | 返回 JSON 响应而非 SSE 流 |
| `--timeout` | `SERVICENOW_TIMEOUT` | `30` | HTTP 请求超时（秒） |
| `--debug` | `SERVICENOW_DEBUG` | `false` | 启用调试日志 |

HTTP 传输示例：

```bash
servicenow-mcp --transport http --http-host 127.0.0.1 --http-port 8000
```

MCP 端点是 `http://127.0.0.1:8000/mcp`；`/health` 返回一个轻量级的健康响应。

#### 区分多个连接（`--server-name`）

如果你在一个客户端里注册了**多个服务器条目**（dev / stg / prd 各自独立的进程），它们会全部默认叫 `ServiceNow`，于是客户端只能按加载顺序来区分——`mcp_servicenow`、`mcp_servicenow2`、`mcp_servicenow3`。这个编号可能在重启之间变化，因此**用它来判断哪个是生产环境并不可靠。** 请给每个连接起个名字：

```bash
servicenow-mcp --server-name snow-prd          # uvx / 控制台脚本
python -m servicenow_mcp --server-name snow-prd # pip
```

这样工具命名空间就固定为 `mcp_snow-prd_*`。`SERVICENOW_MCP_SERVER_NAME` 环境变量效果相同，两者同时设置时以标志为准。不设置则保持 `ServiceNow`，因此现有配置不受影响。

> 想在**一个**服务器内部切换实例？那是[多实例模式](#多实例模式比较--受保护的单次调用写入)，不是这里。两者互不相干——`--server-name` 是客户端看到的名字，而多实例别名是单个进程内部用来指代实例的名字。

### 基本认证（Basic Auth）

| 标志 | 环境变量 |
|------|-------------|
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### OAuth

| 标志 | 环境变量 |
|------|-------------|
| `--client-id` | `SERVICENOW_CLIENT_ID` |
| `--client-secret` | `SERVICENOW_CLIENT_SECRET` |
| `--token-url` | `SERVICENOW_TOKEN_URL` |
| `--username` | `SERVICENOW_USERNAME` |
| `--password` | `SERVICENOW_PASSWORD` |

### API Key

| 标志 | 环境变量 | 默认 |
|------|-------------|---------|
| `--api-key` | `SERVICENOW_API_KEY` | — |
| `--api-key-header` | `SERVICENOW_API_KEY_HEADER` | `X-ServiceNow-API-Key` |

### 脚本执行

| 标志 | 环境变量 |
|------|-------------|
| `--script-execution-api-resource-path` | `SCRIPT_EXECUTION_API_RESOURCE_PATH` |

---

## 保持更新

按你的安装方式选择对应的命令（[安装章节](#1-安装)里也有同样的命令）：

```bash
# uvx——它会缓存下载过的最后一个版本，因此要靠 --refresh 拉取新版本
uvx --refresh --with playwright --from mfa-servicenow-mcp servicenow-mcp --version
uvx --with playwright playwright install chromium
```

```powershell
# pip
pip install --upgrade mfa-servicenow-mcp playwright
python -m playwright install chromium
```

两种方式都会顺带刷新 Chromium，因为更新后的 Playwright 需要不同的 Chromium 构建（见下文）。

刷新后，**重启你的 MCP 客户端**（Claude Code、Cursor 等）以加载新版本。

查看当前版本：

```bash
uvx --from mfa-servicenow-mcp servicenow-mcp --version   # uvx
python -m servicenow_mcp --version                       # pip
```

### 为什么必须提前安装 Chromium

新的 Playwright 发布版本需要不同的 Chromium 构建。放着不管的话，*首次*浏览器工具调用就必须获取约 150 MB 的浏览器二进制文件——在慢速连接上这会超过 MCP 主机的握手超时，并表现为：

```text
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

这正是上面的升级命令每次都要跑 `playwright install chromium` 的原因。

> **我们为何不再在 MCP 服务器内部自动安装 Chromium：** 那个下载过去会在首次工具调用期间运行。在慢速连接上，子进程的存活时间超过了主机的握手截止时间，客户端便报告"connection closed"。v1.13.1 改变了这一点——MCP 服务器现在仅在缺少 Chromium 时*警告*。请提前（带外执行，无握手计时器）安装它。

---

## 安全策略

所有变更类工具都受显式确认保护。

规则：
1. 带有诸如 `create_`、`update_`、`delete_`、`remove_`、`add_`、`move_`、`activate_`、`deactivate_`、`commit_`、`publish_`、`submit_`、`approve_`、`reject_`、`resolve_`、`reorder_` 和 `execute_` 等前缀的变更类工具需要确认。
2. 你必须传入 `confirm='approve'`。
3. 若没有该参数，服务器会在执行前拒绝请求。

无论所选的工具包如何，此策略都适用。

### 写入防护

在确认门之外，每次写入都会经过确定性的防护，这些防护会在写入到达 ServiceNow *之前*阻止不安全的写入。并发编辑和重复创建检查在确认门**之后**运行，因此未确认的写入永远不会接触网络。每个防护在被拒绝/失败的预读上都会**保守失败（fail open）**——它绝不会仅仅因为无法先查看就阻止一次合法的写入。意图很简单：**你应该永远无法悄无声息地覆盖队友的更改**——如果其他人触碰过该记录，写入会停止并告知你，而不是覆盖后继续往前。

| 防护 | 防范的对象 | 覆盖 / 开关 |
|---|---|---|
| 并发编辑 (G3/G8) | 盲目覆盖**另一个用户**在过去 10 分钟内编辑过的记录。覆盖 `sn_write`、`manage_portal_component` 以及 `manage_*` 更新工具——包括 `manage_script_include`、`manage_flow_designer`、`manage_workflow`、`manage_kb_article`、`manage_portal_layout` 和 `manage_widget_dependency`。由对 `sys_updated_by`/`sys_updated_on` 的**实时远程读取**决定——绝非本地副本。 | `SERVICENOW_CONCURRENT_EDIT_GUARD=off`；时间窗口通过 `SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN`（默认 `10`） |
| 源码推送漂移（基线 + update-set HOLD） | 用 `update_remote_from_local` 将编辑后的源码推回会增加两项时间窗口无法捕捉的检查：一项是将远程当前的 `sys_updated_on` 与下载时记录的值进行**与时间无关**的比较（捕捉数小时甚至**数天**之后的覆盖），以及一项对该记录是否被**保留在另一个用户未提交的 update set 中**的实时检查。 | 用 `force=true` 推送越过已检测到的漂移 |
| 重复创建 (G9) | 在 ServiceNow 不强制唯一的表（`sys_update_set`、`wf_workflow`、`sys_user_group`、`sys_user`）上，悄无声息地创建第二条同名记录。 | 传入 `allow_duplicate='true'` 以仍然创建 |
| Flow Designer 原始写入 (G6) | 对会破坏 flow 快照的 `sys_hub_*` 表进行原始 `sn_write`——强制使用 `manage_flow_designer`。 | — |
| 发布类 (G7) | 意外的发布/提交/推送——需要第二次 `confirm_publish='approve'`。 | — |
| 跨实例推送 | 将从实例 A 下载的本地源码推送到实例 B（来源从 `_settings.json` / `_manifest.json` 读取）。 | 从正确的实例重新下载 |

用 `SERVICENOW_WRITE_GUARDS=off` 禁用整个层。在多实例模式下，每个写入响应还携带一个 `instance_target` 字段（路由到别处的读取则携带 `instance_source`），因此调用命中的实例始终可见。

### 门户调查安全

门户调查工具默认保守：

- `search_portal_regex_matches` 起步时仅扫描 widget，关闭链接展开，并采用较小的默认限制。
- `trace_portal_route_targets` 是首选的后续操作，用于获取紧凑的 Widget -> Provider -> route target 证据。
- `download_portal_sources` 除非明确请求，否则不会拉取链接的 Script Includes 或 Angular Providers。
- 大型门户扫描在服务器端被设上限，当请求超过安全默认值时返回警告。

模式匹配模式：

| 模式 | 行为 |
|------|----------|
| `auto`（默认） | 纯字符串按字面处理，看起来像正则的模式保持为正则 |
| `literal` | 始终先转义模式；对路由/令牌字符串最安全 |
| `regex` | 仅在你有意需要正则运算符时使用 |

---

## 性能优化

服务器包含多层性能优化，以尽量降低延迟和令牌使用量。

### 序列化

- **orjson 后端**：所有 JSON 序列化都使用 `json_fast`（可用时用 orjson，否则回退到标准库）。对加载和转储而言，都比标准库 `json` 快 2-4 倍。
- **紧凑输出**：工具响应序列化时不带缩进或额外空白，每个响应可节省 20-30% 令牌。
- **避免双重解析**：`serialize_tool_output` 会检测已经紧凑的 JSON 字符串并跳过重新序列化。

### 缓存

- **OrderedDict LRU 缓存**：查询结果使用 `OrderedDict.popitem()` 以 O(1) 淘汰进行缓存。最多 256 个条目，30 秒 TTL（稳定元数据为 600 秒：schema/scope/choice 表），线程安全。
- **工具 schema 缓存**：Pydantic `model_json_schema()` 的输出按模型类型缓存，避免重复生成 schema。
- **延迟工具发现**：仅在启动时导入活动 `MCP_TOOL_PACKAGE` 所需的工具模块。未使用的模块被完全跳过。

### 网络

- **默认浏览器级 TLS**：HTTP 层通过带 Chrome 伪装配置（默认 `chrome120`）的 `curl_cffi` 路由，因此 TLS 握手与真实浏览器逐字节一致——位于 Cloudflare/Akamai 后面或拒绝原生 Python `requests` 的 JA3 机器人检测的实例，无需额外配置即可工作。用 `SERVICENOW_TLS_IMPERSONATE=off` 退出。
- **HTTP 会话池化**：带 TCP keep-alive 和 gzip/deflate 压缩的持久会话（大型 JSON 负载减少 60-80%）。原生 `requests` 退出路径会挂载一个 20 连接的 `HTTPAdapter`。
- **并行分页**：`sn_query_all` 顺序获取第一页以得到总数，然后通过 `ThreadPoolExecutor`（最多 4 个工作线程）并发检索剩余页。
- **动态页大小**：当剩余记录能容纳在单页内（<=100）时，页大小会被扩大以避免额外的往返。
- **批量 API**：`sn_batch` 将多个 REST 子请求合并到单次 `/api/now/batch` POST 中，并在 150 请求上限处自动分块。
- **并行分块 M2M 查询**：拆分为 100-ID 块的 widget-to-provider M2M 查找会并发执行，而非顺序执行。

### Schema 与启动

- **浅拷贝 schema 注入**：确认 schema（`confirm='approve'`）通过轻量级字典拷贝注入，而非 `copy.deepcopy`，减少 `list_tools` 开销。
- **无计数优化**：后续的分页页使用 `sysparm_no_count=true` 跳过服务器端总数计算。
- **负载安全**：重型表（`sp_widget`、`sys_script` 等）有自动字段钳制和限制约束，以防止上下文窗口溢出。

## 本地源代码审计

在本地下载并分析你的整个 ServiceNow 应用——无需重复的 API 调用，无上下文浪费。

```
Step 1: download_app_sources(scope="x_company_app")    → All server-side code + cross-scope deps to disk
Step 2: audit_local_sources(source_root="temp/...")     → Analysis + HTML report
```

Step 1 默认运行 `auto_resolve_deps=True`：在作用域内下载之后，它会扫描每一个
`.js/.html/.xml` 文件，并获取任何被引用但尚未在包中的 `sys_script_include`、`sp_widget`、
`sp_angular_provider` 或 `sys_ui_macro` 记录——无论它们位于什么作用域。拉取的依赖会保存到同一棵树中，
其 `_metadata.json` 里带有 `"is_dependency": true`，因此 Step 2 中的审计能看到
完整的调用图。如果你只想要作用域内的记录，请设置 `auto_resolve_deps=False`。

> **提示——拉取整个作用域，包括 `global`：** 传入 `scope="global"` 以转储每一条
> 全局作用域记录，或保留你的应用作用域并让 `auto_resolve_deps` 伸入
> `global` 去取你实际引用的记录。无论哪种方式，本地包都是
> 自成一体的，因此分析完全离线地针对磁盘运行。

### 增量同步

每次运行都重新下载一个大型应用既慢又有超时风险。传入 `incremental=True`
以**仅获取自上次下载以来更改的内容**——就像 `git pull` 而非重新
`clone`。在 `download_app_sources` 和 `download_portal_sources` 上均可工作。

```
download_app_sources(scope="x_company_app")                      # 1st run: full download
download_app_sources(scope="x_company_app", incremental=True)    # later: changed records only
```

- **工作原理：** 首次下载会将每条记录的 `sys_updated_on` 记入
  `_sync_meta.json`。在增量运行时，每个源码族都查询
  `sys_updated_on >= <latest seen>`（服务器端时间戳，无时钟偏差），仅重新下载
  那些记录，并保持未更改的本地文件不动。
- **删除：** 时间戳增量看不到已删除的记录。添加 `reconcile_deletions=True`
  以列出本地存在但在实例上已消失的记录——它们作为警告报告在
  `deletion_candidates` 下，**绝不自动删除**。
- **首次运行 / 无先前数据：** 自动回退到完整下载。
- 定期运行一次完整（非增量）下载以保持完全同步。

### 下载安全与完整性

下载是离线分析的真相来源，因此它被构建为确定性的，并且在不完整时绝不*看起来*完整：

- **作用域自动解析。** 传入应用**命名空间**（`x_company_app`）、其**显示名称**（"My App"）或一个 `sys_scope` sys_id——它们全都解析为规范命名空间，因此本地文件夹（`temp/<instance>/<namespace>/`）和每次查询每次运行都相同。解析出的值作为 `scope_resolution` 回显。
- **无静默上限。** 如果某个源码族命中 `max_records_per_type`，它会被高调标记：`source_types` 中逐族的 `capped: true`、`incomplete_types` 中的该族，以及顶层的 `complete: false`。被截断的下载永远无法伪装成完整的下载。
- **跨实例 / 陈旧防护。** 推回（`update_remote_from_local`）会将本地树记录的来源与已连接的实例进行核对；保留陈旧本地副本的续传重新下载会保全真正的同步水位线，并发出警告而非隐藏漂移。
- **下载时的关系元数据。** Widget→Angular-Provider 的边（`_graph.json`）和 widget→CSS/JS 依赖的边（`_dependency_graph.json`）会在门户下载期间从实时 M2M 表捕获——分析读取真实的图，而非从代码猜测。
- **传递依赖深度。** 跨作用域依赖默认解析 `2` 层深（保守）。用 `SERVICENOW_DEP_MAX_DEPTH`（钳制在 `1–6`）提高，以追踪更长的 A→B→C→D 链。
- **一次调用构建图。** 向 `download_app_sources` 传入 `build_graph=True`，以在下载后立即运行离线关系审计——无额外 API 成本。
- **创建 → 本地同步提示。** 当你在实例上创建一个 widget/page *且*该作用域存在本地树时，创建响应会添加一条 `local_out_of_sync` 消息，附带把新记录拉入本地的精确 `download_portal_sources(...)` 命令。它绝不会替你写入本地文件。

### 会生成什么

| 文件 | 用途 |
|------|---------|
| `_audit_report.html` | 自包含的暗色主题 HTML 报告——在浏览器中打开 |
| `_cross_references.json` | 谁调用谁——Script Include 链、GlideRecord 表引用 |
| `_graph.json` | 来自实时 M2M 的权威 widget→Angular Provider 边（非文本猜测） |
| `_dependency_graph.json` | 来自 `m2m_sp_widget_dependency` 的权威 widget→CSS/JS 依赖边 |
| `_page_graph.json` | 从 `sp_instance` 本地推导的 Page→widget 放置（无 API 调用） |
| `_orphans.json` | 死代码候选——未被引用的 SI、未使用的 widget |
| `_execution_order.json` | 带顺序号的逐表 BR/CS/ACL 执行序列 |
| `_domain_knowledge.md` | 自动生成的应用画像——表映射、hub 脚本、警告 |
| `_schema/*.json` | 每个被引用表的字段定义 |
| `_sync_meta.json` | 驱动增量同步的逐族 `sys_updated_on` 水位线 |

### 单独的下载工具

用编排器进行完整转储，或用 `download_server_sources` 进行有针对性的单族刷新：

| 工具 | 来源 |
|------|---------|
| `download_app_sources` | 完整应用转储（所有族 + 门户 + schema + 跨作用域依赖） |
| `download_portal_sources` | Widgets、Angular Providers、链接的 Script Includes |
| `download_server_sources`（`families=`） | 有针对性刷新——`script_includes`、`server_scripts`（BR/Client/Catalog Client）、`ui`（Actions/Scripts/Pages/Macros）、`api`（Scripted REST/Processors）、`security`（ACL，默认仅脚本）、`admin`（Fix Scripts/Scheduled Jobs/Script Actions/Notifications/Transforms） |
| `download_table_schema` | sys_dictionary 字段定义 |

所有下载都将完整源码零截断地写入磁盘。只有摘要会返回到 LLM 上下文。

---

## 技能

工具是原始 API 调用。技能才是让你的 LLM 真正有用的东西——带安全门、回滚和上下文感知子代理委派的经过验证的流水线。**MCP 服务器 + 技能是 LLM 驱动的 ServiceNow 自动化的完整配置**。

今天有 4 个技能，每次发布都会增加更多。

| | 仅工具 | 工具 + 技能 |
|---|---|---|
| 安全 | LLM 决定 | 强制门控（快照 → 预览 → 应用） |
| 令牌 | 源码转储在上下文中 | 委派给子代理，仅摘要 |
| 准确性 | LLM 猜测工具顺序 | 经过验证的流水线 |
| 回滚 | 可能忘记 | 强制快照 |

### 安装技能

```bash
# Claude Code
uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude

# OpenAI Codex
uvx --from mfa-servicenow-mcp servicenow-mcp-skills codex

# OpenCode
uvx --from mfa-servicenow-mcp servicenow-mcp-skills opencode

# Antigravity
uvx --from mfa-servicenow-mcp servicenow-mcp-skills antigravity
```

安装程序会从本仓库的 `skills/` 目录下载 24 个技能文件，并将它们放在一个项目本地的 LLM 目录中。无需认证或配置。

> 如果 `servicenow-mcp-skills` 在 Windows 上被安全策略拦截，可以改为以模块方式调用——行为完全相同：
>
> ```bash
> python -m servicenow_mcp.setup_skills claude
> ```

| 客户端 | 安装路径 | 自动发现 |
|--------|-------------|----------------|
| Claude Code | `.claude/commands/servicenow/` | `/servicenow` 斜杠命令在下次启动时出现 |
| OpenAI Codex | `.codex/skills/servicenow/` | 技能在下次代理会话时加载 |
| OpenCode | `.opencode/skills/servicenow/` | 技能在下次会话时加载 |
| Antigravity | `.gemini/antigravity/skills/servicenow/` | 技能在下次会话时激活 |

**工作原理：** 每个技能都是一个独立的 Markdown 文件，带 YAML frontmatter（元数据）和流水线指令。LLM 客户端从安装路径读取这些文件，并将它们暴露为可调用命令或技能触发器。

**更新：** 重新运行相同的安装命令——它会替换所有现有技能文件（全新安装，无合并）。

**仅移除技能：** 手动删除技能安装目录（例如 `rm -rf .claude/commands/servicenow/`）。

### 技能分类

| 分类 | 技能数 | 用途 |
|----------|--------|---------|
| `analyze/` | 6 | Widget 分析、门户诊断、provider 审计、依赖映射、ESC 审计、**本地源代码审计** |
| `fix/` | 3 | Widget 打补丁（分阶段门控）、调试、代码评审 |
| `manage/` | 8 | 页面布局、script includes、源码导出、**应用源码下载**、changeset 工作流、本地同步、工作流管理、**技能管理** |
| `deploy/` | 2 | 变更请求生命周期、incident 分诊 |
| `explore/` | 5 | 健康检查、schema 发现、路由追踪、flow 触发器追踪、ESC catalog flow |

### 技能元数据

每个技能都包含有助于 LLM 优化执行的元数据：

```yaml
context_cost: low|medium|high    # → high = delegate to sub-agent
safety_level: none|confirm|staged # → staged = mandatory snapshot/preview/apply
delegatable: true|false           # → can run in sub-agent to save context
triggers: ["위젯 분석", "analyze widget"]  # → LLM trigger matching
```

完整的技能参考见 [skills/SKILL.md](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/skills/SKILL.md)。

### MCP 资源（内置技能指南）

技能也直接从服务器作为 **MCP 资源**暴露——无需客户端安装。任何符合 MCP 标准的客户端都能按需发现并读取它们。

```
# List available skill guides
list_resources → skill://manage/local-sync, skill://manage/app-source-download, ...

# Read a specific guide
read_resource("skill://manage/local-sync") → full pipeline with safety gates
```

具有匹配技能指南的工具会在其描述中显示一个 `→ skill://...` 提示。指南内容是**按需拉取的**——在客户端实际读取之前零令牌成本。

| 特性 | 客户端技能 | MCP 资源 |
|---------|-------------------|---------------|
| 可用性 | 需要安装命令 | 内置，任何客户端 |
| 令牌成本 | 由客户端加载 | 按需拉取（读取前为 0） |
| 发现 | 斜杠命令 / 触发器 | `list_resources` |
| 最适合 | 高级用户、斜杠命令 | 通用指导 |

## Docker

仅支持 API Key 认证（MFA 浏览器认证需要 GUI，在容器中不可用）。

```bash
docker run -it --rm \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=api_key \
  -e SERVICENOW_API_KEY=your-api-key \
  ghcr.io/jshsakura/mfa-servicenow-mcp:latest
```

本地构建选项见[客户端设置指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md#docker-api-key-only)。

## 开发者设置

如果你想在本地修改源码：

```bash
git clone https://github.com/jshsakura/mfa-servicenow-mcp.git
cd mfa-servicenow-mcp

uv venv
uv pip install -e ".[browser,dev]"
uvx --with playwright playwright install chromium
```

### 运行测试

```bash
uv run pytest
```

### 代码检查与格式化

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

### 构建

```bash
uv build
```

> Windows：见 [Windows 安装指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)

---

## 文档

- [LLM 设置指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/llm-setup.md) — AI 引导的一行式安装流程
- [客户端设置指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/CLIENT_SETUP.md) — 安装程序优先的设置以及回退客户端配置
- [工具清单](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/TOOL_INVENTORY.md) — 按分类和工具包列出的完整工具列表
- [Windows 安装指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/WINDOWS_INSTALL.md)
- [Catalog 指南](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/catalog.md) — 服务目录 CRUD 与优化
- [变更管理](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/change_management.md) — 变更请求生命周期与审批
- [工作流管理](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/docs/workflow_management.md) — Workflow（wf_workflow 引擎）和 Flow Designer 工具
- [韩语 README](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/README.ko.md)

---

## 相关项目与致谢

- 本仓库包含从早期内部 / 遗留 ServiceNow MCP 实现整合并重构而来的工具。当前的工具面围绕捆绑式 `manage_*` 工具组织（见 [tool_utils.py](https://github.com/jshsakura/mfa-servicenow-mcp/blob/main/src/servicenow_mcp/utils/tool_utils.py)）。
- 本项目专注于安全、diff 优先的 MCP 服务器使用场景：每次写入都经过 confirm + 写入防护（并发编辑、重复创建、发布、Flow Designer），并且源码编辑在推送前会与实时远程进行 diff 比对。

---

## 许可证

Apache License 2.0
