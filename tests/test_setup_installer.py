"""Tests for the one-command setup installer."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from servicenow_mcp.setup_installer import (
    format_summary,
    install_client,
    main,
    remove_client,
    remove_codex_config,
    remove_json_config,
    resolve_config_path,
    resolve_scope,
    update_codex_config,
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


class TestValidateSetupArgs:
    def test_browser_args_valid(self):
        validate_setup_args(_args())

    def test_basic_requires_credentials(self):
        with pytest.raises(ValueError, match="Basic auth"):
            validate_setup_args(_args(auth_type="basic", username=None, password=None))

    def test_api_key_requires_key(self):
        with pytest.raises(ValueError, match="API key"):
            validate_setup_args(_args(auth_type="api_key", api_key=None))


class TestConfigReadErrors:
    def test_invalid_json_raises_clear_error(self, tmp_path):
        path = tmp_path / ".mcp.json"
        path.write_text('{"mcpServers": }', encoding="utf-8")

        with pytest.raises(ValueError, match="not valid JSON"):
            update_json_config("claude-code", path, _args(clients=["claude-code"]))

    def test_invalid_toml_raises_clear_error(self, tmp_path):
        path = tmp_path / ".codex/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text('[mcp_servers.other\ncommand = "node"\n', encoding="utf-8")

        with pytest.raises(ValueError, match="not valid TOML"):
            update_codex_config(path, _args(clients=["codex"]))


class TestConfigPaths:
    def test_project_opencode_path(self, tmp_path):
        path = resolve_config_path("opencode", "project", tmp_path)
        assert path == tmp_path / "opencode.json"

    def test_claude_desktop_linux_path(self, tmp_path):
        with patch("servicenow_mcp.setup_installer._current_os", return_value="linux"):
            path = resolve_config_path("claude-desktop", "global", tmp_path)
        assert path == Path.home() / ".config/Claude/claude_desktop_config.json"

    def test_invalid_scope_rejected(self):
        with pytest.raises(ValueError, match="does not support project"):
            resolve_scope("zed", "project")


class TestJsonConfigUpdates:
    def test_claude_code_preserves_existing_servers(self, tmp_path):
        path = tmp_path / ".mcp.json"
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "other": {"command": "node", "args": ["server.js"]},
                        "servicenow": {"command": "old", "args": ["stale"]},
                    },
                    "metadata": {"keep": True},
                }
            ),
            encoding="utf-8",
        )

        update_json_config("claude-code", path, _args(clients=["claude-code"]))

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["metadata"] == {"keep": True}
        assert data["mcpServers"]["other"] == {"command": "node", "args": ["server.js"]}
        assert data["mcpServers"]["servicenow"]["command"] == "uvx"
        assert data["mcpServers"]["servicenow"]["env"]["SERVICENOW_INSTANCE_URL"]

    def test_opencode_config_merged(self, tmp_path):
        path = tmp_path / "opencode.json"
        path.write_text(json.dumps({"mcp": {"other": {"type": "local"}}}), encoding="utf-8")

        update_json_config("opencode", path, _args())

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["$schema"] == "https://opencode.ai/config.json"
        assert "other" in data["mcp"]
        assert data["mcp"]["servicenow"]["environment"]["SERVICENOW_INSTANCE_URL"]

    def test_vscode_config_uses_servers_key(self, tmp_path):
        path = tmp_path / ".vscode/mcp.json"
        update_json_config("vscode-copilot", path, _args())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "servicenow" in data["servers"]

    def test_gemini_config_matches_documented_shape(self, tmp_path):
        path = tmp_path / ".gemini/settings.json"
        update_json_config("gemini", path, _args(clients=["gemini"]))

        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data["mcpServers"]["servicenow"]
        assert entry["command"] == "uvx"
        assert "enabled" not in entry
        assert entry["env"]["SERVICENOW_INSTANCE_URL"] == "https://demo.service-now.com"

    def test_zed_preserves_unrelated_settings(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "theme": "Andromeda",
                    "features": {"assistant": True},
                    "servicenow": {"command": "old"},
                }
            ),
            encoding="utf-8",
        )

        update_json_config("zed", path, _args(clients=["zed"]))

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["theme"] == "Andromeda"
        assert data["features"] == {"assistant": True}
        assert data["servicenow"]["command"] == "uvx"

    def test_remove_claude_code_preserves_other_servers(self, tmp_path):
        path = tmp_path / ".mcp.json"
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "other": {"command": "node", "args": ["server.js"]},
                        "servicenow": {"command": "uvx"},
                    },
                    "metadata": {"keep": True},
                }
            ),
            encoding="utf-8",
        )

        removed = remove_json_config("claude-code", path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert removed is True
        assert data["metadata"] == {"keep": True}
        assert "servicenow" not in data["mcpServers"]
        assert "other" in data["mcpServers"]

    def test_remove_opencode_preserves_other_entries(self, tmp_path):
        path = tmp_path / "opencode.json"
        path.write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "mcp": {
                        "other": {"type": "local"},
                        "servicenow": {"type": "local"},
                    },
                }
            ),
            encoding="utf-8",
        )

        removed = remove_json_config("opencode", path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert removed is True
        assert data["$schema"] == "https://opencode.ai/config.json"
        assert "servicenow" not in data["mcp"]
        assert "other" in data["mcp"]

    def test_remove_zed_preserves_unrelated_settings(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "theme": "Andromeda",
                    "features": {"assistant": True},
                    "servicenow": {"command": "uvx"},
                }
            ),
            encoding="utf-8",
        )

        removed = remove_json_config("zed", path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert removed is True
        assert data["theme"] == "Andromeda"
        assert data["features"] == {"assistant": True}
        assert "servicenow" not in data


class TestTomlConfigUpdates:
    def test_codex_config_written(self, tmp_path):
        path = tmp_path / ".codex/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '[mcp_servers.other]\ncommand = "node"\nargs = ["server.js"]\nenabled = true\n',
            encoding="utf-8",
        )

        update_codex_config(path, _args(clients=["codex"]))

        content = path.read_text(encoding="utf-8")
        assert "[mcp_servers.other]" in content
        assert "[mcp_servers.servicenow]" in content
        assert 'SERVICENOW_INSTANCE_URL = "https://demo.service-now.com"' in content

    def test_codex_config_preserves_numeric_values(self, tmp_path):
        path = tmp_path / ".codex/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '[mcp_servers.other]\ncommand = "node"\nargs = ["server.js"]\nenabled = true\ntimeout = 30\n',
            encoding="utf-8",
        )

        update_codex_config(path, _args(clients=["codex"]))

        content = path.read_text(encoding="utf-8")
        assert "[mcp_servers.other]" in content
        assert "timeout = 30" in content
        assert "[mcp_servers.servicenow]" in content

    def test_codex_config_replaces_only_servicenow_section(self, tmp_path):
        path = tmp_path / ".codex/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            """[mcp_servers.other]
command = \"node\"
args = [\"server.js\"]
enabled = true

[mcp_servers.servicenow]
command = \"old\"
args = [\"stale\"]
enabled = false

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = \"https://old.example.com\"
""",
            encoding="utf-8",
        )

        update_codex_config(path, _args(clients=["codex"]))

        content = path.read_text(encoding="utf-8")
        assert content.count("[mcp_servers.servicenow]") == 1
        assert content.count("[mcp_servers.servicenow.env]") == 1
        assert "[mcp_servers.other]" in content
        assert 'command = "uvx"' in content
        assert 'SERVICENOW_INSTANCE_URL = "https://demo.service-now.com"' in content

    def test_remove_codex_config_preserves_other_sections(self, tmp_path):
        path = tmp_path / ".codex/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            """[mcp_servers.other]
command = \"node\"
args = [\"server.js\"]
enabled = true
timeout = 30

[mcp_servers.servicenow]
command = \"uvx\"
args = [\"--from\", \"mfa-servicenow-mcp\", \"servicenow-mcp\"]
enabled = true

[mcp_servers.servicenow.env]
SERVICENOW_INSTANCE_URL = \"https://demo.service-now.com\"
""",
            encoding="utf-8",
        )

        removed = remove_codex_config(path)

        content = path.read_text(encoding="utf-8")
        assert removed is True
        assert "[mcp_servers.other]" in content
        assert "timeout = 30" in content
        assert "[mcp_servers.servicenow]" not in content
        assert "[mcp_servers.servicenow.env]" not in content


class TestInstallClient:
    @patch("servicenow_mcp.setup_installer.install_skills", return_value=22)
    def test_supported_client_installs_skills(self, mock_install_skills, tmp_path):
        result = install_client("codex", _args(clients=["codex"]), tmp_path)
        assert result["skills"] == "22 installed"
        mock_install_skills.assert_called_once()

    @patch("servicenow_mcp.setup_installer.install_skills")
    def test_unsupported_client_skips_skills(self, mock_install_skills, tmp_path):
        result = install_client("zed", _args(clients=["zed"]), tmp_path)
        assert result["skills"] == "not supported"
        mock_install_skills.assert_not_called()

    @patch("servicenow_mcp.setup_installer.install_skills")
    def test_skip_skills_respected(self, mock_install_skills, tmp_path):
        result = install_client("opencode", _args(skip_skills=True), tmp_path)
        assert result["skills"] == "skipped"
        mock_install_skills.assert_not_called()


class TestRemoveClient:
    @patch("servicenow_mcp.setup_installer.remove_skills", return_value=True)
    def test_supported_client_removes_skills(self, mock_remove_skills, tmp_path):
        path = tmp_path / "opencode.json"
        path.write_text(
            json.dumps({"mcp": {"servicenow": {"type": "local"}}}),
            encoding="utf-8",
        )

        result = remove_client("opencode", _args(), tmp_path)

        assert result["config_status"] == "removed"
        assert result["skills"] == "removed"
        mock_remove_skills.assert_called_once()

    @patch("servicenow_mcp.setup_installer.remove_skills")
    def test_keep_skills_respected(self, mock_remove_skills, tmp_path):
        path = tmp_path / ".mcp.json"
        path.write_text(
            json.dumps({"mcpServers": {"servicenow": {"command": "uvx"}}}),
            encoding="utf-8",
        )

        result = remove_client(
            "claude-code", _args(clients=["claude-code"], keep_skills=True), tmp_path
        )

        assert result["config_status"] == "removed"
        assert result["skills"] == "kept"
        mock_remove_skills.assert_not_called()


class TestMain:
    @patch("servicenow_mcp.setup_installer.install_skills", return_value=20)
    @patch("builtins.print")
    def test_main_runs_multiple_clients(self, mock_print, mock_install_skills, tmp_path):
        with patch("servicenow_mcp.setup_installer.Path.cwd", return_value=tmp_path):
            exit_code = main(
                [
                    "opencode",
                    "codex",
                    "--instance-url",
                    "https://demo.service-now.com",
                ]
            )

        assert exit_code == 0
        rendered = mock_print.call_args[0][0]
        assert "Client: opencode" in rendered
        assert "Client: codex" in rendered

    @patch("servicenow_mcp.setup_installer.remove_skills", return_value=True)
    @patch("builtins.print")
    def test_main_runs_remove_flow(self, mock_print, mock_remove_skills, tmp_path):
        path = tmp_path / "opencode.json"
        path.write_text(
            json.dumps({"mcp": {"servicenow": {"type": "local"}}}),
            encoding="utf-8",
        )

        with patch("servicenow_mcp.setup_installer.Path.cwd", return_value=tmp_path):
            exit_code = main(["opencode"], action="remove")

        assert exit_code == 0
        rendered = mock_print.call_args[0][0]
        assert "Removal complete!" in rendered
        assert "Config entry: removed" in rendered


class TestSummary:
    def test_format_summary(self):
        summary = format_summary(
            [
                {
                    "client": "opencode",
                    "scope": "project",
                    "config": "opencode.json",
                    "skills": "20 installed",
                }
            ]
        )
        assert "Setup complete!" in summary
        assert "Client: opencode" in summary

    def test_format_remove_summary(self):
        summary = format_summary(
            [
                {
                    "client": "opencode",
                    "scope": "project",
                    "config": "opencode.json",
                    "config_status": "removed",
                    "skills": "removed",
                }
            ],
            action="remove",
        )
        assert "Removal complete!" in summary
        assert "Config entry: removed" in summary
