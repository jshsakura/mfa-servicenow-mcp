"""One-command installer/remover for client MCP configuration and optional skills."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from servicenow_mcp.setup_skills import TARGETS, install_skills, remove_skills


@dataclass(frozen=True)
class ClientSpec:
    """Install metadata for a supported client."""

    name: str
    format: str
    default_scope: str
    supports_project: bool
    supports_global: bool


CLIENT_SPECS: dict[str, ClientSpec] = {
    "claude-code": ClientSpec("claude-code", "json", "project", True, True),
    "claude-desktop": ClientSpec("claude-desktop", "json", "global", False, True),
    "cursor": ClientSpec("cursor", "json", "project", True, False),
    "vscode-copilot": ClientSpec("vscode-copilot", "json", "project", True, False),
    "opencode": ClientSpec("opencode", "json", "project", True, False),
    "codex": ClientSpec("codex", "toml", "project", True, True),
    "windsurf": ClientSpec("windsurf", "json", "global", False, True),
    "gemini": ClientSpec("gemini", "json", "project", True, True),
    "zed": ClientSpec("zed", "json", "global", False, True),
    "antigravity": ClientSpec("antigravity", "json", "global", False, True),
}

SKILL_TARGETS = {
    "claude-code": "claude",
    "codex": "codex",
    "opencode": "opencode",
    "gemini": "gemini",
}


def build_setup_parser(action: str = "setup") -> argparse.ArgumentParser:
    """Build parser for setup/remove commands."""
    is_setup = action == "setup"
    description = (
        "Install MCP config and optional skills"
        if is_setup
        else "Remove MCP config and optional skills"
    )
    parser = argparse.ArgumentParser(
        description=description,
        epilog=(
            "Examples:\n"
            "  servicenow-mcp setup opencode --instance-url https://demo.service-now.com\n"
            "  servicenow-mcp setup codex --instance-url https://demo.service-now.com --auth-type basic --username demo.user --password secret\n"
            "  servicenow-mcp setup claude-code --instance-url https://demo.service-now.com --scope global --skip-skills\n"
            "  servicenow-mcp remove opencode\n"
            "  servicenow-mcp remove claude-code --scope global --keep-skills"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "clients",
        nargs="*",
        choices=sorted(CLIENT_SPECS.keys()),
        help="Client(s) to configure",
    )
    if is_setup:
        parser.add_argument("--instance-url", help="ServiceNow instance URL")
        parser.add_argument(
            "--auth-type",
            choices=["browser", "basic", "oauth", "api_key"],
            default="browser",
            help="Authentication type",
        )
        parser.add_argument("--username", help="ServiceNow username")
        parser.add_argument("--password", help="ServiceNow password")
        parser.add_argument("--client-id", help="OAuth client ID")
        parser.add_argument("--client-secret", help="OAuth client secret")
        parser.add_argument("--token-url", help="OAuth token URL")
        parser.add_argument("--api-key", help="API key")
        parser.add_argument(
            "--api-key-header",
            default="X-ServiceNow-API-Key",
            help="API key header",
        )
        parser.add_argument(
            "--tool-package",
            default="standard",
            help="Tool package to configure",
        )
        parser.add_argument(
            "--browser-headless",
            choices=["true", "false"],
            default="false",
            help="Browser headless mode",
        )
    parser.add_argument(
        "--scope",
        choices=["project", "global"],
        help="Install scope override",
    )
    if is_setup:
        parser.add_argument(
            "--skip-skills",
            action="store_true",
            help="Skip optional skills install",
        )
    else:
        parser.add_argument(
            "--keep-skills",
            action="store_true",
            help="Keep installed skills instead of removing them",
        )
    return parser


def prompt_if_missing(args: argparse.Namespace, action: str = "setup") -> argparse.Namespace:
    """Prompt for missing required values when running interactively."""
    if args.clients:
        clients = args.clients
    else:
        raw_clients = input(
            "Client(s) [claude-code, claude-desktop, cursor, opencode, codex, windsurf, vscode-copilot, gemini, zed, antigravity]: "
        ).strip()
        clients = [item.strip() for item in raw_clients.split() if item.strip()]
    if not clients:
        raise ValueError("At least one client is required")
    args.clients = clients

    if action != "setup":
        return args

    if not args.instance_url:
        args.instance_url = input("ServiceNow instance URL: ").strip()
    if not args.instance_url:
        raise ValueError("--instance-url is required")

    if args.auth_type == "basic":
        if not args.username:
            args.username = input("Username: ").strip()
        if not args.password:
            args.password = input("Password: ").strip()
    elif args.auth_type == "oauth":
        if not args.client_id:
            args.client_id = input("OAuth client ID: ").strip()
        if not args.client_secret:
            args.client_secret = input("OAuth client secret: ").strip()
        if not args.username:
            args.username = input("Username: ").strip()
        if not args.password:
            args.password = input("Password: ").strip()
    elif args.auth_type == "api_key":
        if not args.api_key:
            args.api_key = input("API key: ").strip()

    return args


def resolve_clients(args: argparse.Namespace, action: str = "setup") -> list[str]:
    """Resolve configured clients, prompting interactively if needed."""
    if args.clients:
        return args.clients
    if sys.stdin.isatty():
        return prompt_if_missing(args, action).clients
    raise ValueError(f"Client target is required. Example: servicenow-mcp {action} codex")


def validate_setup_args(args: argparse.Namespace) -> None:
    """Validate installer arguments."""
    if not args.instance_url:
        raise ValueError("--instance-url is required")

    if args.auth_type == "basic" and (not args.username or not args.password):
        raise ValueError("Basic auth requires --username and --password")
    if args.auth_type == "oauth" and (
        not args.client_id or not args.client_secret or not args.username or not args.password
    ):
        raise ValueError("OAuth requires --client-id, --client-secret, --username, and --password")
    if args.auth_type == "api_key" and not args.api_key:
        raise ValueError("API key auth requires --api-key")


def _current_os() -> str:
    system = platform.system().lower()
    if system.startswith("darwin"):
        return "macos"
    if system.startswith("windows"):
        return "windows"
    return "linux"


def resolve_config_path(client: str, scope: str, cwd: Path) -> Path:
    """Resolve the config path for a client and scope."""
    home = Path.home()
    os_name = _current_os()

    if client == "claude-code":
        return cwd / ".mcp.json" if scope == "project" else home / ".claude.json"
    if client == "claude-desktop":
        if os_name == "macos":
            return home / "Library/Application Support/Claude/claude_desktop_config.json"
        if os_name == "windows":
            appdata = Path.home() / "AppData/Roaming"
            return appdata / "Claude/claude_desktop_config.json"
        return home / ".config/Claude/claude_desktop_config.json"
    if client == "cursor":
        return cwd / ".cursor/mcp.json"
    if client == "vscode-copilot":
        return cwd / ".vscode/mcp.json"
    if client == "opencode":
        return cwd / "opencode.json"
    if client == "codex":
        return cwd / ".codex/config.toml" if scope == "project" else home / ".codex/config.toml"
    if client == "windsurf":
        return home / ".codeium/windsurf/mcp_config.json"
    if client == "gemini":
        return (
            cwd / ".gemini/settings.json" if scope == "project" else home / ".gemini/settings.json"
        )
    if client == "zed":
        return home / ".config/zed/settings.json"
    if client == "antigravity":
        if os_name == "windows":
            return home / ".gemini/antigravity/mcp_config.json"
        return home / ".gemini/antigravity/mcp_config.json"
    raise ValueError(f"Unsupported client: {client}")


def resolve_scope(client: str, requested_scope: str | None) -> str:
    """Resolve effective scope with capability validation."""
    spec = CLIENT_SPECS[client]
    scope = requested_scope or spec.default_scope
    if scope == "project" and not spec.supports_project:
        raise ValueError(f"{client} does not support project scope")
    if scope == "global" and not spec.supports_global:
        raise ValueError(f"{client} does not support global scope")
    return scope


def build_env(args: argparse.Namespace) -> dict[str, str]:
    """Build env vars for the MCP config."""
    env = {
        "SERVICENOW_INSTANCE_URL": args.instance_url,
        "SERVICENOW_AUTH_TYPE": args.auth_type,
        "SERVICENOW_BROWSER_HEADLESS": args.browser_headless,
        "MCP_TOOL_PACKAGE": args.tool_package,
    }

    if args.username:
        env["SERVICENOW_USERNAME"] = args.username
    if args.password:
        env["SERVICENOW_PASSWORD"] = args.password
    if args.client_id:
        env["SERVICENOW_CLIENT_ID"] = args.client_id
    if args.client_secret:
        env["SERVICENOW_CLIENT_SECRET"] = args.client_secret
    if args.token_url:
        env["SERVICENOW_TOKEN_URL"] = args.token_url
    if args.api_key:
        env["SERVICENOW_API_KEY"] = args.api_key
        env["SERVICENOW_API_KEY_HEADER"] = args.api_key_header

    return env


def build_client_config(
    client: str, args: argparse.Namespace
) -> tuple[str, list[str], dict[str, str], bool]:
    """Return format-specific server config pieces."""
    env = build_env(args)
    base_args = ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]

    if client == "opencode":
        return "array_command", ["uvx", *base_args], env, True

    return "split_command", base_args, env, True


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Existing config at {path} is not valid JSON. Fix it before running setup."
        ) from exc


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_json_config(client: str, path: Path, args: argparse.Namespace) -> None:
    """Merge the ServiceNow server into a JSON config file."""
    mode, command_args, env, enabled = build_client_config(client, args)
    data = _read_json(path)

    if client in {"claude-code", "claude-desktop", "cursor", "windsurf", "gemini", "antigravity"}:
        servers = data.setdefault("mcpServers", {})
        entry: dict[str, Any] = {"command": "uvx", "args": command_args, "env": env}
        servers["servicenow"] = entry
    elif client == "vscode-copilot":
        servers = data.setdefault("servers", {})
        servers["servicenow"] = {"command": "uvx", "args": command_args, "env": env}
    elif client == "opencode":
        mcp = data.setdefault("mcp", {})
        mcp["servicenow"] = {
            "type": "local",
            "command": command_args,
            "enabled": enabled,
            "environment": env,
        }
        data.setdefault("$schema", "https://opencode.ai/config.json")
    elif client == "zed":
        data["servicenow"] = {"command": "uvx", "args": command_args, "env": env}
    else:
        raise ValueError(f"Unsupported JSON client: {client}")

    _write_json(path, data)


def remove_json_config(client: str, path: Path) -> bool:
    """Remove the ServiceNow server from a JSON config file."""
    if not path.exists():
        return False

    data = _read_json(path)
    removed = False

    if client in {"claude-code", "claude-desktop", "cursor", "windsurf", "gemini", "antigravity"}:
        servers = data.get("mcpServers")
        if isinstance(servers, dict) and "servicenow" in servers:
            del servers["servicenow"]
            removed = True
            if not servers:
                data.pop("mcpServers", None)
    elif client == "vscode-copilot":
        servers = data.get("servers")
        if isinstance(servers, dict) and "servicenow" in servers:
            del servers["servicenow"]
            removed = True
            if not servers:
                data.pop("servers", None)
    elif client == "opencode":
        mcp = data.get("mcp")
        if isinstance(mcp, dict) and "servicenow" in mcp:
            del mcp["servicenow"]
            removed = True
            if not mcp:
                data.pop("mcp", None)
    elif client == "zed":
        if "servicenow" in data:
            del data["servicenow"]
            removed = True
    else:
        raise ValueError(f"Unsupported JSON client: {client}")

    if removed:
        _write_json(path, data)
    return removed


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    import tomllib

    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Existing config at {path} is not valid TOML. Fix it before running setup."
        ) from exc


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value: {type(value)!r}")


def _toml_lines(data: dict[str, Any], prefix: list[str] | None = None) -> list[str]:
    prefix = prefix or []
    lines: list[str] = []
    scalar_items = {k: v for k, v in data.items() if not isinstance(v, dict)}
    dict_items = {k: v for k, v in data.items() if isinstance(v, dict)}

    if prefix:
        lines.append(f"[{'/'.join(prefix)}]".replace("/", "."))
    for key, value in scalar_items.items():
        lines.append(f"{key} = {_format_toml_value(value)}")
    if prefix and (scalar_items or dict_items):
        lines.append("")
    for key, value in dict_items.items():
        lines.extend(_toml_lines(value, [*prefix, key]))
    return lines


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(line for line in _toml_lines(data) if line is not None).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _render_codex_sections(args: argparse.Namespace) -> str:
    _, command_args, env, enabled = build_client_config("codex", args)
    server_lines = [
        "[mcp_servers.servicenow]",
        'command = "uvx"',
        f"args = {_format_toml_value(command_args)}",
        f"enabled = {_format_toml_value(enabled)}",
        "",
        "[mcp_servers.servicenow.env]",
    ]
    for key, value in env.items():
        server_lines.append(f"{key} = {_format_toml_value(value)}")
    return "\n".join(server_lines) + "\n"


def _upsert_codex_section(content: str, section_name: str, replacement: str) -> str:
    pattern = re.compile(rf"(?ms)^\[{re.escape(section_name)}\]\n.*?(?=^\[[^\n]+\]\n|\Z)")
    match = pattern.search(content)
    if match:
        return content[: match.start()] + replacement + content[match.end() :]
    if content and not content.endswith("\n"):
        content += "\n"
    if content.strip():
        content += "\n"
    return content + replacement


def _write_codex_toml(path: Path, args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        _read_toml(path)
    else:
        raw = ""

    updated = _upsert_codex_section(raw, "mcp_servers.servicenow.env", "")
    updated = _upsert_codex_section(updated, "mcp_servers.servicenow", _render_codex_sections(args))
    updated = re.sub(r"\n{3,}", "\n\n", updated).rstrip() + "\n"
    path.write_text(updated, encoding="utf-8")


def update_codex_config(path: Path, args: argparse.Namespace) -> None:
    """Merge the ServiceNow server into Codex TOML config."""
    _write_codex_toml(path, args)


def _remove_codex_section(content: str, section_name: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(?ms)^\[{re.escape(section_name)}\]\n.*?(?=^\[[^\n]+\]\n|\Z)")
    updated, count = pattern.subn("", content, count=1)
    return updated, count > 0


def remove_codex_config(path: Path) -> bool:
    """Remove the ServiceNow server from Codex TOML config."""
    if not path.exists():
        return False

    raw = path.read_text(encoding="utf-8")
    _read_toml(path)

    updated, removed_env = _remove_codex_section(raw, "mcp_servers.servicenow.env")
    updated, removed_server = _remove_codex_section(updated, "mcp_servers.servicenow")
    removed = removed_env or removed_server
    if removed:
        updated = re.sub(r"\n{3,}", "\n\n", updated).strip()
        path.write_text((updated + "\n") if updated else "", encoding="utf-8")
    return removed


def remove_client(client: str, args: argparse.Namespace, cwd: Path) -> dict[str, str]:
    """Remove config and optional skills for one client."""
    scope = resolve_scope(client, args.scope)
    config_path = resolve_config_path(client, scope, cwd)

    if CLIENT_SPECS[client].format == "json":
        config_result = "removed" if remove_json_config(client, config_path) else "not found"
    else:
        config_result = "removed" if remove_codex_config(config_path) else "not found"

    skill_result = "not supported"
    if getattr(args, "keep_skills", False):
        skill_result = "kept"
    elif client in SKILL_TARGETS:
        skills_path = cwd / TARGETS[SKILL_TARGETS[client]]
        skill_result = (
            "removed" if remove_skills(SKILL_TARGETS[client], skills_path) else "not found"
        )

    return {
        "client": client,
        "scope": scope,
        "config": str(config_path),
        "config_status": config_result,
        "skills": skill_result,
    }


def install_client(client: str, args: argparse.Namespace, cwd: Path) -> dict[str, str]:
    """Install config and optional skills for one client."""
    scope = resolve_scope(client, args.scope)
    config_path = resolve_config_path(client, scope, cwd)

    if CLIENT_SPECS[client].format == "json":
        update_json_config(client, config_path, args)
    else:
        update_codex_config(config_path, args)

    skill_result = "not supported"
    if not args.skip_skills and client in SKILL_TARGETS:
        skills_path = cwd / TARGETS[SKILL_TARGETS[client]]
        count = install_skills(SKILL_TARGETS[client], skills_path)
        skill_result = f"{count} installed"
    elif args.skip_skills:
        skill_result = "skipped"

    return {
        "client": client,
        "scope": scope,
        "config": str(config_path),
        "skills": skill_result,
    }


def format_summary(results: list[dict[str, str]], action: str = "setup") -> str:
    """Format setup/remove summary."""
    is_setup = action == "setup"
    lines = ["Setup complete!" if is_setup else "Removal complete!", ""]
    for result in results:
        lines.append(f"- Client: {result['client']}")
        lines.append(f"  Scope: {result['scope']}")
        lines.append(f"  Config: {result['config']}")
        if is_setup:
            lines.append(f"  Skills: {result['skills']}")
        else:
            lines.append(f"  Config entry: {result['config_status']}")
            lines.append(f"  Skills: {result['skills']}")
    if is_setup:
        lines.extend(
            [
                "",
                "Next steps:",
                "- Restart your AI client or reload MCP servers so it picks up the new config.",
                "- On the first browser-authenticated tool call, a browser window may open for MFA/SSO login.",
                "- After restart, try a simple health check against your ServiceNow instance.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Next steps:",
                "- Restart your AI client or reload MCP servers so it drops the removed config.",
                "- Re-run `servicenow-mcp setup <client> ...` if you want to install it again later.",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None, action: str = "setup") -> int:
    """Run the setup/remove command."""
    parser = build_setup_parser(action)
    args = parser.parse_args(argv)

    if action == "setup" and sys.stdin.isatty() and (not args.clients or not args.instance_url):
        args = prompt_if_missing(args, action)
    elif action != "setup" and sys.stdin.isatty() and not args.clients:
        args = prompt_if_missing(args, action)

    args.clients = resolve_clients(args, action)
    if action == "setup":
        validate_setup_args(args)

    cwd = Path.cwd()
    if action == "setup":
        results = [install_client(client, args, cwd) for client in args.clients]
    else:
        results = [remove_client(client, args, cwd) for client in args.clients]
    print(format_summary(results, action))
    return 0
