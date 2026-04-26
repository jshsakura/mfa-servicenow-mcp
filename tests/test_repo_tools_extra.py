"""Tests for repo_tools uncovered paths — error handling, edge cases, path filtering."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from servicenow_mcp.tools.repo_tools import (
    GetRepoChangeReportParams,
    GetRepoFileLastModifierParams,
    GetRepoRecentCommitsParams,
    GetRepoWorkingTreeStatusParams,
    _parse_commit_log_with_files,
    _parse_porcelain_status,
    get_repo_change_report,
    get_repo_file_last_modifier,
    get_repo_recent_commits,
    get_repo_working_tree_status,
)


def _completed(args, stdout: str, returncode: int = 0, stderr: str = ""):
    return CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


class TestParsePorcelainStatus:
    def test_empty_input(self):
        result = _parse_porcelain_status("", include_untracked=True)
        assert result == {}

    def test_excludes_untracked_when_flag_false(self):
        result = _parse_porcelain_status("?? newfile.txt\n", include_untracked=False)
        assert result == {}

    def test_short_line_skipped(self):
        result = _parse_porcelain_status("XY\n", include_untracked=True)
        assert result == {}

    def test_staged_unstaged_combined(self):
        raw = "M  modified.py\nA  added.py\n D deleted.py\n"
        result = _parse_porcelain_status(raw, include_untracked=True)
        assert result["modified.py"]["index_status"] == "M"
        assert result["modified.py"]["staged"] is True
        assert result["modified.py"]["unstaged"] is False
        assert result["added.py"]["staged"] is True
        assert result["deleted.py"]["unstaged"] is True


class TestParseCommitLogWithFiles:
    def test_empty_input(self):
        assert _parse_commit_log_with_files("") == []

    def test_malformed_commit_skipped(self):
        raw = "__COMMIT__abc|only_three_fields\n"
        result = _parse_commit_log_with_files(raw)
        assert result == []

    def test_file_lines_without_commit_header_ignored(self):
        raw = "orphan_file.py\n"
        result = _parse_commit_log_with_files(raw)
        assert result == []


class TestRepoWorkingTreeStatus:
    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_git_command_failure(self, mock_run, tmp_path: Path):
        mock_run.return_value = _completed(
            [], stdout="", returncode=128, stderr="fatal: not a git repo"
        )
        result = get_repo_working_tree_status(
            GetRepoWorkingTreeStatusParams(repo_path=str(tmp_path))
        )
        assert result["success"] is False

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_path_filter(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], " M src/app.py\n M docs/readme.md\n"),
        ]
        result = get_repo_working_tree_status(
            GetRepoWorkingTreeStatusParams(repo_path=str(tmp_path), path_filter="src/")
        )
        assert result["success"] is True
        assert result["summary"]["files"] == 1
        assert result["files"][0]["path"] == "src/app.py"

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_exclude_untracked(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], " M src/app.py\n?? new_file.py\n"),
        ]
        result = get_repo_working_tree_status(
            GetRepoWorkingTreeStatusParams(repo_path=str(tmp_path), include_untracked=False)
        )
        assert result["success"] is True
        assert result["summary"]["files"] == 1

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_empty_status(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], ""),
        ]
        result = get_repo_working_tree_status(
            GetRepoWorkingTreeStatusParams(repo_path=str(tmp_path))
        )
        assert result["success"] is True
        assert result["summary"]["files"] == 0


class TestRepoRecentCommits:
    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_path_filter_skips_commits_without_matching_files(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed(
                [],
                "__COMMIT__deadbeef|Alice|alice@example.com|2026-03-26T08:00:00+09:00|update docs\ndocs/readme.md\n",
            ),
        ]
        result = get_repo_recent_commits(
            GetRepoRecentCommitsParams(
                repo_path=str(tmp_path), path_filter="src/", include_files=True
            )
        )
        assert result["success"] is True
        assert result["count"] == 0

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_without_files(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed(
                [],
                "__COMMIT__deadbeef|Alice|alice@example.com|2026-03-26T08:00:00+09:00|update app\nsrc/app.py\n",
            ),
        ]
        result = get_repo_recent_commits(
            GetRepoRecentCommitsParams(repo_path=str(tmp_path), include_files=False)
        )
        assert result["success"] is True
        assert "files" not in result["commits"][0]

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_git_failure(self, mock_run, tmp_path: Path):
        mock_run.return_value = _completed([], stdout="", returncode=1, stderr="error")
        result = get_repo_recent_commits(GetRepoRecentCommitsParams(repo_path=str(tmp_path)))
        assert result["success"] is False


class TestRepoFileLastModifier:
    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_file_not_in_commits_uses_single_log(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], ""),
            _completed([], " M orphan.py\n"),
            _completed(
                [],
                "__COMMIT__single|Bob|bob@example.com|2026-03-25T08:00:00+09:00|add orphan\norphan.py\n",
            ),
        ]
        result = get_repo_file_last_modifier(
            GetRepoFileLastModifierParams(repo_path=str(tmp_path), files=["orphan.py"])
        )
        assert result["success"] is True
        assert result["files"][0]["last_modifier"] == "Bob"

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_file_not_in_commits_single_log_fails(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], ""),
            _completed([], " M orphan.py\n"),
            _completed([], stdout="", returncode=1, stderr="git error"),
        ]
        result = get_repo_file_last_modifier(
            GetRepoFileLastModifierParams(repo_path=str(tmp_path), files=["orphan.py"])
        )
        assert result["success"] is True
        assert result["files"][0]["last_modifier"] == ""

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_without_uncommitted_status(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed(
                [],
                "__COMMIT__abc|Alice|alice@x.com|2026-01-01T00:00:00+00:00|init\nsrc/app.py\n",
            ),
        ]
        result = get_repo_file_last_modifier(
            GetRepoFileLastModifierParams(
                repo_path=str(tmp_path),
                files=["src/app.py"],
                include_uncommitted_status=False,
            )
        )
        assert result["success"] is True
        assert result["files"][0]["commit_state"] == "committed"

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_auto_targets_with_path_filter(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], ""),
            _completed([], " M src/app.py\n M docs/readme.md\n"),
            _completed(
                [],
                "__COMMIT__abc|Alice|a@x.com|2026-01-01T00:00:00+00:00|init\nsrc/app.py\ndocs/readme.md\n",
            ),
        ]
        result = get_repo_file_last_modifier(
            GetRepoFileLastModifierParams(
                repo_path=str(tmp_path),
                path_filter="src/",
            )
        )
        assert result["success"] is True
        paths = [f["path"] for f in result["files"]]
        assert "src/app.py" in paths
        assert "docs/readme.md" not in paths


class TestRepoChangeReport:
    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_status_failure_propagates(self, mock_run, tmp_path: Path):
        mock_run.return_value = _completed([], stdout="", returncode=128, stderr="not a git repo")
        result = get_repo_change_report(GetRepoChangeReportParams(repo_path=str(tmp_path)))
        assert result.get("success") is False

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_without_recent_commits(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], " M src/app.py\n"),
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed(
                [],
                "__COMMIT__abc|Alice|a@x.com|2026-01-01T00:00:00+00:00|init\nsrc/app.py\n",
            ),
            _completed([], " M src/app.py\n"),
        ]
        result = get_repo_change_report(
            GetRepoChangeReportParams(repo_path=str(tmp_path), include_recent_commits=False)
        )
        assert result["success"] is True
        assert result["recent_commits"] == []

    @patch("servicenow_mcp.tools.repo_tools.subprocess.run")
    def test_without_uncommitted(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed([], " M src/app.py\n"),
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed(
                [],
                "__COMMIT__abc|Alice|a@x.com|2026-01-01T00:00:00+00:00|init\nsrc/app.py\n",
            ),
            _completed([], "true\n"),
            _completed([], "main\n"),
            _completed([], "abc123\n"),
            _completed(
                [],
                "__COMMIT__abc|Alice|a@x.com|2026-01-01T00:00:00+00:00|init\nsrc/app.py\n",
            ),
        ]
        result = get_repo_change_report(
            GetRepoChangeReportParams(repo_path=str(tmp_path), include_uncommitted=False)
        )
        assert result["success"] is True
