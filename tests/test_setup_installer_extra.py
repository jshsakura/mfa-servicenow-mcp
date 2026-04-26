"""Tests for setup_installer uncovered paths — prompt_if_missing, resolve_clients, build_env, format_summary, main edge cases."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from servicenow_mcp.setup_installer import (
    _format_toml_value,
    _toml_lines,
    _upsert_codex_section,
    build_env,
    build_setup_parser,
    format_summary,
    install_client,
    main,
    prompt_if_missing,
    remove_client,
    remove_codex_config,
    remove_json_config,
    resolve_clients,
    resolve_config_path,
    resolve_scope,
    update_json_config,
    validate_setup_args,
)


def _args(**overrides):
    data = {
        "clients": ["opencode"],
        "instance_url": "https://demo.service-now.com",
        "auth_type": "browser",
        "username": "demo.user",
        "password": "secret",
        "client_id": None,
        "client_secret": None,
        "token_url": None,
        "api_key": None,
        "api_key_header": "X-ServiceNow-API-Key",
        "tool_package": "standard",
        "browser_headless": "false",
        "scope": None,
        "skip_skills": False,
        "keep_skills": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


class TestPromptIfMissing:
    def test_prompt_clients_from_input(self):
        with patch("builtins.input", return_value="opencode cursor"):
            args = _args(clients=[])
            result = prompt_if_missing(args, "setup")
        assert result.clients == ["opencode", "cursor"]

    def test_prompt_empty_clients_raises(self):
        with patch("builtins.input", return_value="  "):
            args = _args(clients=[])
            with pytest.raises(ValueError, match="At least one client"):
                prompt_if_missing(args, "setup")

    def test_prompt_instance_url_from_input(self):
        with patch("builtins.input", return_value="https://my.instance.com"):
            args = _args(instance_url=None)
            result = prompt_if_missing(args, "setup")
        assert result.instance_url == "https://my.instance.com"

    def test_prompt_empty_instance_url_raises(self):
        with patch("builtins.input", return_value="  "):
            args = _args(instance_url=None)
            with pytest.raises(ValueError, match="--instance-url is required"):
                prompt_if_missing(args, "setup")

    def test_prompt_basic_auth_credentials(self):
        inputs = iter(["myuser", "mypassword"])
        with patch("builtins.input", side_effect=inputs):
            args = _args(auth_type="basic", username=None, password=None)
            result = prompt_if_missing(args, "setup")
        assert result.username == "myuser"
        assert result.password == "mypassword"

    def test_prompt_oauth_credentials(self):
        inputs = iter(["cid", "csec", "oauthuser", "oauthpass"])
        with patch("builtins.input", side_effect=inputs):
            args = _args(
                auth_type="oauth", client_id=None, client_secret=None, username=None, password=None
            )
            result = prompt_if_missing(args, "setup")
        assert result.client_id == "cid"
        assert result.client_secret == "csec"

    def test_prompt_api_key(self):
        with patch("builtins.input", return_value="my-api-key"):
            args = _args(auth_type="api_key", api_key=None)
            result = prompt_if_missing(args, "setup")
        assert result.api_key == "my-api-key"

    def test_prompt_remove_action_skips_setup_prompts(self):
        args = _args(clients=[], auth_type="browser")
        with patch("builtins.input", return_value="opencode"):
            result = prompt_if_missing(args, "remove")
        assert result.clients == ["opencode"]


class TestResolveClients:
    def test_with_existing_clients(self):
        args = _args(clients=["opencode"])
        result = resolve_clients(args, "setup")
        assert result == ["opencode"]

    def test_no_clients_tty_prompts(self):
        args = _args(clients=[])
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("servicenow_mcp.setup_installer.prompt_if_missing") as mock_prompt,
        ):
            mock_prompt.return_value = _args(clients=["cursor"])
            result = resolve_clients(args, "setup")
        assert result == ["cursor"]

    def test_no_clients_non_tty_raises(self):
        args = _args(clients=[])
        with patch("sys.stdin.isatty", return_value=False):
            with pytest.raises(ValueError, match="Client target is required"):
                resolve_clients(args, "setup")


class TestValidateSetupArgs:
    def test_oauth_missing_fields_raises(self):
        with pytest.raises(ValueError, match="OAuth requires"):
            validate_setup_args(
                _args(
                    auth_type="oauth",
                    client_id=None,
                    client_secret=None,
                    username=None,
                    password=None,
                )
            )

    def test_missing_instance_url_raises(self):
        with pytest.raises(ValueError, match="--instance-url is required"):
            validate_setup_args(
                _args(instance_url=None, auth_type="basic", username=None, password=None)
            )


class TestBuildEnv:
    def test_browser_env(self):
        args = _args()
        env = build_env(args)
        assert env["SERVICENOW_INSTANCE_URL"] == "https://demo.service-now.com"
        assert env["SERVICENOW_AUTH_TYPE"] == "browser"
        assert "SERVICENOW_USERNAME" in env

    def test_api_key_env(self):
        args = _args(auth_type="api_key", api_key="key123", api_key_header="X-Custom-Header")
        env = build_env(args)
        assert env["SERVICENOW_API_KEY"] == "key123"
        assert env["SERVICENOW_API_KEY_HEADER"] == "X-Custom-Header"

    def test_oauth_env(self):
        args = _args(
            auth_type="oauth", client_id="cid", client_secret="csec", token_url="https://token.url"
        )
        env = build_env(args)
        assert env["SERVICENOW_CLIENT_ID"] == "cid"
        assert env["SERVICENOW_CLIENT_SECRET"] == "csec"
        assert env["SERVICENOW_TOKEN_URL"] == "https://token.url"


class TestResolveConfigPath:
    def test_claude_desktop_macos(self, tmp_path):
        with patch("servicenow_mcp.setup_installer._current_os", return_value="macos"):
            path = resolve_config_path("claude-desktop", "global", tmp_path)
        assert "Claude" in str(path)

    def test_claude_desktop_windows(self, tmp_path):
        with patch("servicenow_mcp.setup_installer._current_os", return_value="windows"):
            path = resolve_config_path("claude-desktop", "global", tmp_path)
        assert "AppData" in str(path)

    def test_codex_project_scope(self, tmp_path):
        path = resolve_config_path("codex", "project", tmp_path)
        assert path == tmp_path / ".codex/config.toml"

    def test_codex_global_scope(self, tmp_path):
        path = resolve_config_path("codex", "global", tmp_path)
        assert path == Path.home() / ".codex/config.toml"

    def test_cursor_project(self, tmp_path):
        path = resolve_config_path("cursor", "project", tmp_path)
        assert path == tmp_path / ".cursor/mcp.json"

    def test_vscode_copilot_project(self, tmp_path):
        path = resolve_config_path("vscode-copilot", "project", tmp_path)
        assert path == tmp_path / ".vscode/mcp.json"

    def test_windsurf_global(self, tmp_path):
        path = resolve_config_path("windsurf", "global", tmp_path)
        assert ".codeium/windsurf" in str(path)

    def test_gemini_project(self, tmp_path):
        path = resolve_config_path("gemini", "project", tmp_path)
        assert path == tmp_path / ".gemini/settings.json"

    def test_gemini_global(self, tmp_path):
        path = resolve_config_path("gemini", "global", tmp_path)
        assert path == Path.home() / ".gemini/settings.json"

    def test_zed_global(self, tmp_path):
        path = resolve_config_path("zed", "global", tmp_path)
        assert ".config/zed/settings.json" in str(path)

    def test_antigravity_windows(self, tmp_path):
        with patch("servicenow_mcp.setup_installer._current_os", return_value="windows"):
            path = resolve_config_path("antigravity", "global", tmp_path)
        assert "antigravity" in str(path)

    def test_antigravity_linux(self, tmp_path):
        with patch("servicenow_mcp.setup_installer._current_os", return_value="linux"):
            path = resolve_config_path("antigravity", "global", tmp_path)
        assert "antigravity" in str(path)

    def test_unsupported_client_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unsupported client"):
            resolve_config_path("nonexistent_client", "project", tmp_path)


class TestResolveScope:
    def test_project_not_supported(self):
        with pytest.raises(ValueError, match="does not support project scope"):
            resolve_scope("claude-desktop", "project")

    def test_global_not_supported(self):
        with pytest.raises(ValueError, match="does not support global scope"):
            resolve_scope("cursor", "global")

    def test_default_scope_used(self):
        scope = resolve_scope("opencode", None)
        assert scope == "project"


class TestFormatTomlValue:
    def test_bool_true(self):
        assert _format_toml_value(True) == "true"

    def test_bool_false(self):
        assert _format_toml_value(False) == "false"

    def test_int(self):
        assert _format_toml_value(42) == "42"

    def test_float(self):
        assert _format_toml_value(3.14) == "3.14"

    def test_string_escapes(self):
        assert _format_toml_value('he said "hi"') == '"he said \\"hi\\""'

    def test_string_backslash(self):
        assert _format_toml_value("back\\slash") == '"back\\\\slash"'

    def test_list(self):
        assert _format_toml_value(["a", "b"]) == '["a", "b"]'

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError, match="Unsupported TOML value"):
            _format_toml_value({"nested": "dict"})


class TestTomlLines:
    def test_nested_dict(self):
        data = {"section": {"key": "value"}, "top": "level"}
        lines = _toml_lines(data)
        result = "\n".join(lines)
        assert "top = " in result
        assert "[section]" in result
        assert "key = " in result

    def test_empty_dict(self):
        assert _toml_lines({}) == []

    def test_with_prefix(self):
        data = {"key": "val"}
        lines = _toml_lines(data, prefix=["parent", "child"])
        result = "\n".join(lines)
        assert "[parent.child]" in result


class TestUpsertCodexSection:
    def test_replaces_existing_section(self):
        content = (
            '[mcp_servers.servicenow]\ncommand = "old"\n\n[mcp_servers.other]\ncommand = "keep"\n'
        )
        result = _upsert_codex_section(
            content, "mcp_servers.servicenow", '[mcp_servers.servicenow]\ncommand = "new"\n'
        )
        assert 'command = "new"' in result
        assert 'command = "keep"' in result
        assert 'command = "old"' not in result

    def test_appends_to_empty(self):
        result = _upsert_codex_section(
            "", "mcp_servers.servicenow", '[mcp_servers.servicenow]\ncommand = "uvx"\n'
        )
        assert 'command = "uvx"' in result

    def test_appends_to_nonempty_without_trailing_newline(self):
        result = _upsert_codex_section(
            '[other]\nkey = "val"',
            "mcp_servers.servicenow",
            '[mcp_servers.servicenow]\ncommand = "uvx"\n',
        )
        assert 'command = "uvx"' in result
        assert 'key = "val"' in result


class TestRemoveJsonConfig:
    def test_remove_nonexistent_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert remove_json_config("claude-code", path) is False

    def test_remove_vscode_copilot(self, tmp_path):
        path = tmp_path / ".vscode/mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"servers": {"servicenow": {"command": "uvx"}}}), encoding="utf-8"
        )
        removed = remove_json_config("vscode-copilot", path)
        assert removed is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "servicenow" not in data.get("servers", {})

    def test_remove_antigravity(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"mcpServers": {"servicenow": {"command": "uvx"}}}), encoding="utf-8"
        )
        removed = remove_json_config("antigravity", path)
        assert removed is True

    def test_remove_windsurf(self, tmp_path):
        path = tmp_path / "mcp_config.json"
        path.write_text(
            json.dumps({"mcpServers": {"servicenow": {"command": "uvx"}}}), encoding="utf-8"
        )
        removed = remove_json_config("windsurf", path)
        assert removed is True

    def test_remove_gemini(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"mcpServers": {"servicenow": {"command": "uvx"}}}), encoding="utf-8"
        )
        removed = remove_json_config("gemini", path)
        assert removed is True

    def test_remove_empty_servers_removes_key(self, tmp_path):
        path = tmp_path / ".mcp.json"
        path.write_text(
            json.dumps({"mcpServers": {"servicenow": {"command": "uvx"}}}), encoding="utf-8"
        )
        removed = remove_json_config("claude-code", path)
        assert removed is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "mcpServers" not in data

    def test_remove_vscode_empty_servers_removes_key(self, tmp_path):
        path = tmp_path / ".vscode/mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"servers": {"servicenow": {"command": "uvx"}}}), encoding="utf-8"
        )
        removed = remove_json_config("vscode-copilot", path)
        assert removed is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "servers" not in data

    def test_remove_opencode_empty_mcp_removes_key(self, tmp_path):
        path = tmp_path / "opencode.json"
        path.write_text(json.dumps({"mcp": {"servicenow": {"type": "local"}}}), encoding="utf-8")
        removed = remove_json_config("opencode", path)
        assert removed is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "mcp" not in data


class TestRemoveCodexConfig:
    def test_remove_nonexistent_file(self, tmp_path):
        path = tmp_path / ".codex/config.toml"
        assert remove_codex_config(path) is False


class TestUpdateJsonConfig:
    def test_unsupported_json_client_raises(self, tmp_path):
        path = tmp_path / "config.json"
        with pytest.raises(ValueError, match="Unsupported JSON client"):
            update_json_config("codex", path, _args(clients=["codex"]))

    def test_cursor_config(self, tmp_path):
        path = tmp_path / ".cursor/mcp.json"
        update_json_config("cursor", path, _args(clients=["cursor"]))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "servicenow" in data["mcpServers"]

    def test_claude_code_global(self, tmp_path):
        path = tmp_path / ".claude.json"
        update_json_config("claude-code", path, _args(clients=["claude-code"]))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "servicenow" in data["mcpServers"]


class TestBuildSetupParser:
    def test_setup_parser_has_instance_url(self):
        parser = build_setup_parser("setup")
        args = parser.parse_args(["opencode", "--instance-url", "https://x.com"])
        assert args.instance_url == "https://x.com"

    def test_remove_parser_has_keep_skills(self):
        parser = build_setup_parser("remove")
        args = parser.parse_args(["opencode", "--keep-skills"])
        assert args.keep_skills is True

    def test_setup_parser_has_skip_skills(self):
        parser = build_setup_parser("setup")
        args = parser.parse_args(["opencode", "--instance-url", "https://x.com", "--skip-skills"])
        assert args.skip_skills is True


class TestMainEdgeCases:
    @patch("servicenow_mcp.setup_installer.install_skills", return_value=0)
    @patch("builtins.print")
    def test_main_with_all_optional_args(self, mock_print, mock_install_skills, tmp_path):
        with patch("servicenow_mcp.setup_installer.Path.cwd", return_value=tmp_path):
            exit_code = main(
                [
                    "opencode",
                    "--instance-url",
                    "https://demo.service-now.com",
                    "--auth-type",
                    "basic",
                    "--username",
                    "u",
                    "--password",
                    "p",
                    "--tool-package",
                    "full",
                    "--browser-headless",
                    "true",
                    "--scope",
                    "project",
                    "--skip-skills",
                ]
            )
        assert exit_code == 0

    @patch("servicenow_mcp.setup_installer.remove_skills", return_value=True)
    @patch("builtins.print")
    def test_main_remove_with_keep_skills(self, mock_print, mock_remove_skills, tmp_path):
        path = tmp_path / "opencode.json"
        path.write_text(json.dumps({"mcp": {"servicenow": {"type": "local"}}}), encoding="utf-8")
        with patch("servicenow_mcp.setup_installer.Path.cwd", return_value=tmp_path):
            exit_code = main(["opencode", "--keep-skills"], action="remove")
        assert exit_code == 0
        mock_remove_skills.assert_not_called()


class TestFormatSummaryEdgeCases:
    def test_setup_summary_next_steps(self):
        summary = format_summary(
            [
                {
                    "client": "opencode",
                    "scope": "project",
                    "config": "opencode.json",
                    "skills": "skipped",
                }
            ],
            "setup",
        )
        assert "Next steps" in summary
        assert "health check" in summary

    def test_remove_summary_next_steps(self):
        summary = format_summary(
            [
                {
                    "client": "opencode",
                    "scope": "project",
                    "config": "opencode.json",
                    "config_status": "removed",
                    "skills": "not found",
                }
            ],
            "remove",
        )
        assert "Next steps" in summary
        assert "install it again" in summary


class TestInstallClientEdgeCases:
    @patch("servicenow_mcp.setup_installer.install_skills")
    def test_skip_skills_for_supported_client(self, mock_install_skills, tmp_path):
        result = install_client(
            "claude-code", _args(clients=["claude-code"], skip_skills=True), tmp_path
        )
        assert result["skills"] == "skipped"
        mock_install_skills.assert_not_called()


class TestRemoveClientEdgeCases:
    @patch("servicenow_mcp.setup_installer.remove_skills")
    def test_unsupported_client_no_skills(self, mock_remove_skills, tmp_path):
        result = remove_client("cursor", _args(clients=["cursor"], keep_skills=False), tmp_path)
        assert result["skills"] == "not supported"
        mock_remove_skills.assert_not_called()

    def test_config_not_found(self, tmp_path):
        result = remove_client("opencode", _args(clients=["opencode"]), tmp_path)
        assert result["config_status"] == "not found"
