"""Tests for setup_skills.py — download, extract, and main."""

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.setup_skills import (
    BRANCH,
    CATEGORIES,
    TARGETS,
    _copy_bundled_skills,
    _download_refs,
    _download_skills,
    _print,
    _ref_url_and_prefix,
    main,
)

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
    def test_antigravity_target(self, mock_cwd, mock_urlopen, tmp_path):
        mock_cwd.return_value = tmp_path
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_zip_bytes()
        mock_urlopen.return_value = mock_resp

        with patch("sys.argv", ["setup_skills", "antigravity"]):
            main()

        dest = tmp_path / ".gemini" / "antigravity" / "skills" / "servicenow"
        assert dest.exists()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestBundledSkills:
    def test_copy_bundled_skills_copies_real_skills(self, tmp_path):
        # The repo checkout always has a skills/ dir, so the bundled path is
        # the one exercised on a normal install — no network involved.
        dest = tmp_path / "out"
        count = _copy_bundled_skills(dest)
        assert count is not None and count > 0
        assert (dest / "SKILL.md").exists()
        # At least one category .md landed.
        assert any(dest.rglob("*/*.md"))

    def test_copy_returns_none_when_no_bundled_dir(self, tmp_path):
        with patch("servicenow_mcp.setup_skills._find_bundled_skills_dir", return_value=None):
            assert _copy_bundled_skills(tmp_path / "out") is None

    def test_install_prefers_bundled_over_download(self, tmp_path):
        # urlopen must never be called when bundled skills are available.
        from servicenow_mcp.setup_skills import install_skills

        with patch("servicenow_mcp.setup_skills.urlopen") as mock_urlopen:
            count = install_skills("claude", tmp_path / "skills")
        mock_urlopen.assert_not_called()
        assert count > 0
        assert (tmp_path / "skills" / "_mcp_info.md").exists()


class TestDownloadRefs:
    def test_version_tag_first_then_main(self):
        refs = _download_refs()
        assert refs[-1] == BRANCH
        # When a version is resolvable, a v-prefixed tag precedes main.
        assert any(r.startswith("v") for r in refs[:-1]) or refs == [BRANCH]

    def test_branch_url_uses_heads(self):
        url, prefix = _ref_url_and_prefix(BRANCH)
        assert "/refs/heads/main.zip" in url
        assert prefix == f"mfa-servicenow-mcp-{BRANCH}/skills/"

    def test_tag_url_uses_tags_and_strips_v_in_dir(self):
        url, prefix = _ref_url_and_prefix("v1.2.3")
        assert "/refs/tags/v1.2.3.zip" in url
        assert prefix == "mfa-servicenow-mcp-1.2.3/skills/"


class TestConstants:
    def test_targets_has_expected_keys(self):
        assert "claude" in TARGETS
        assert "codex" in TARGETS
        assert "opencode" in TARGETS
        assert "antigravity" in TARGETS
        assert "gemini" not in TARGETS

    def test_categories_list(self):
        assert "analyze" in CATEGORIES
        assert len(CATEGORIES) >= 4
