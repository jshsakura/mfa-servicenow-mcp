"""Tests for setup_skills.py — download, extract, and main."""

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.setup_skills import CATEGORIES, TARGETS, _download_skills, _print, main

# ---------------------------------------------------------------------------
# _print
# ---------------------------------------------------------------------------


class TestPrint:
    @patch("builtins.print")
    def test_print_calls_print(self, mock_print):
        _print("hello")
        mock_print.assert_called_once_with("hello", flush=True)


# ---------------------------------------------------------------------------
# _download_skills
# ---------------------------------------------------------------------------


def _make_zip_bytes():
    """Create a valid zip archive mimicking the GitHub download structure."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        prefix = "mfa-servicenow-mcp-main/skills/"
        # directory entry
        zf.writestr(prefix, "")
        # category dir
        zf.writestr(prefix + "analyze/", "")
        # skill files
        zf.writestr(prefix + "analyze/check-health.md", "# Check Health\nSteps here.")
        zf.writestr(prefix + "analyze/review-logs.md", "# Review Logs\nSteps here.")
        zf.writestr(prefix + "SKILL.md", "# Skill index")
        # Unrelated file outside skills/
        zf.writestr("mfa-servicenow-mcp-main/README.md", "# README")
    return buf.getvalue()


class TestDownloadSkills:
    @patch("servicenow_mcp.setup_skills.urlopen")
    def test_success(self, mock_urlopen, tmp_path):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        dest = tmp_path / "skills_output"
        count = _download_skills(dest)
        assert count == 2  # two .md files in analyze/
        assert (dest / "analyze" / "check-health.md").exists()
        assert (dest / "SKILL.md").exists()

    @patch("servicenow_mcp.setup_skills.urlopen", side_effect=Exception("network error"))
    def test_download_failure_exits(self, mock_urlopen, tmp_path):
        dest = tmp_path / "skills_output"
        with pytest.raises(SystemExit):
            _download_skills(dest)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @patch("sys.argv", ["setup_skills"])
    def test_no_args_shows_usage(self):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    @patch("sys.argv", ["setup_skills", "invalid_target"])
    def test_invalid_target_shows_usage(self):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    @patch("servicenow_mcp.setup_skills.urlopen")
    @patch("servicenow_mcp.setup_skills.Path.cwd")
    def test_claude_target(self, mock_cwd, mock_urlopen, tmp_path):
        mock_cwd.return_value = tmp_path
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        with patch("sys.argv", ["setup_skills", "claude"]):
            main()

        dest = tmp_path / ".claude" / "commands" / "servicenow"
        assert dest.exists()
        assert (dest / "_mcp_info.md").exists()

    @patch("servicenow_mcp.setup_skills.urlopen")
    @patch("servicenow_mcp.setup_skills.Path.cwd")
    def test_existing_dir_removed(self, mock_cwd, mock_urlopen, tmp_path):
        mock_cwd.return_value = tmp_path
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        dest = tmp_path / ".claude" / "commands" / "servicenow"
        dest.mkdir(parents=True)
        (dest / "old_file.txt").write_text("old")

        with patch("sys.argv", ["setup_skills", "claude"]):
            main()

        assert not (dest / "old_file.txt").exists()  # old file removed
        assert (dest / "_mcp_info.md").exists()  # new content

    @patch("servicenow_mcp.setup_skills.urlopen")
    @patch("servicenow_mcp.setup_skills.Path.cwd")
    def test_codex_target(self, mock_cwd, mock_urlopen, tmp_path):
        mock_cwd.return_value = tmp_path
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        with patch("sys.argv", ["setup_skills", "codex"]):
            main()

        dest = tmp_path / ".codex" / "skills" / "servicenow"
        assert dest.exists()

    @patch("servicenow_mcp.setup_skills.urlopen")
    @patch("servicenow_mcp.setup_skills.Path.cwd")
    def test_opencode_target(self, mock_cwd, mock_urlopen, tmp_path):
        mock_cwd.return_value = tmp_path
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        with patch("sys.argv", ["setup_skills", "opencode"]):
            main()

        dest = tmp_path / ".opencode" / "skills" / "servicenow"
        assert dest.exists()

    @patch("servicenow_mcp.setup_skills.urlopen")
    @patch("servicenow_mcp.setup_skills.Path.cwd")
    def test_gemini_target(self, mock_cwd, mock_urlopen, tmp_path):
        mock_cwd.return_value = tmp_path
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        with patch("sys.argv", ["setup_skills", "gemini"]):
            main()

        dest = tmp_path / ".gemini" / "skills" / "servicenow"
        assert dest.exists()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_targets_has_expected_keys(self):
        assert "claude" in TARGETS
        assert "codex" in TARGETS
        assert "opencode" in TARGETS
        assert "gemini" in TARGETS

    def test_categories_list(self):
        assert "analyze" in CATEGORIES
        assert len(CATEGORIES) >= 4
