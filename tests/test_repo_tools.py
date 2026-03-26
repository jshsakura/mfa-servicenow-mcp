from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from servicenow_mcp.tools.repo_tools import (
    GetRepoChangeReportParams,
    GetRepoFileLastModifierParams,
    GetRepoRecentCommitsParams,
    GetRepoWorkingTreeStatusParams,
    get_repo_change_report,
    get_repo_file_last_modifier,
    get_repo_recent_commits,
    get_repo_working_tree_status,
)


def _completed(args, stdout: str, returncode: int = 0, stderr: str = ""):
    return CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


@patch("servicenow_mcp.tools.repo_tools.subprocess.run")
def test_get_repo_working_tree_status_returns_staged_unstaged_untracked(mock_run, tmp_path: Path):
    mock_run.side_effect = [
        _completed([], "true\n"),
        _completed([], "main\n"),
        _completed([], "abc123\n"),
        _completed([], " M src/app.py\nA  src/new.py\n?? docs/readme.md\n"),
    ]

    result = get_repo_working_tree_status(
        GetRepoWorkingTreeStatusParams(repo_path=str(tmp_path), include_untracked=True)
    )

    assert result["success"] is True
    assert result["summary"]["files"] == 3
    by_path = {entry["path"]: entry for entry in result["files"]}
    assert by_path["src/app.py"]["unstaged"] is True
    assert by_path["src/new.py"]["staged"] is True
    assert by_path["docs/readme.md"]["untracked"] is True


@patch("servicenow_mcp.tools.repo_tools.subprocess.run")
def test_get_repo_recent_commits_returns_commit_list(mock_run, tmp_path: Path):
    mock_run.side_effect = [
        _completed([], "true\n"),
        _completed([], "main\n"),
        _completed([], "abc123\n"),
        _completed(
            [],
            "\n".join(
                [
                    "__COMMIT__deadbeef|Alice|alice@example.com|2026-03-26T08:00:00+09:00|update app",
                    "src/app.py",
                    "",
                    "__COMMIT__feedface|Bob|bob@example.com|2026-03-25T08:00:00+09:00|initial",
                    "docs/readme.md",
                ]
            ),
        ),
    ]

    result = get_repo_recent_commits(GetRepoRecentCommitsParams(repo_path=str(tmp_path), limit=10))

    assert result["success"] is True
    assert result["count"] == 2
    assert result["commits"][0]["author"] == "Alice"
    assert "src/app.py" in result["commits"][0]["files"]


@patch("servicenow_mcp.tools.repo_tools.subprocess.run")
def test_get_repo_file_last_modifier_returns_modifier_and_commit_state(mock_run, tmp_path: Path):
    mock_run.side_effect = [
        _completed([], "true\n"),
        _completed([], "main\n"),
        _completed([], "abc123\n"),
        _completed(
            [],
            "__COMMIT__deadbeef|Alice|alice@example.com|2026-03-26T08:00:00+09:00|update app\nsrc/app.py\n",
        ),
        _completed([], " M src/app.py\n"),
    ]

    result = get_repo_file_last_modifier(
        GetRepoFileLastModifierParams(
            repo_path=str(tmp_path), files=["src/app.py"], commits_scan_limit=10
        )
    )

    assert result["success"] is True
    assert result["files"][0]["last_modifier"] == "Alice"
    assert result["files"][0]["commit_state"] == "uncommitted"


@patch("servicenow_mcp.tools.repo_tools.subprocess.run")
def test_get_repo_change_report_aggregates_modular_queries(mock_run, tmp_path: Path):
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
            "__COMMIT__deadbeef|Alice|alice@example.com|2026-03-26T08:00:00+09:00|update app\nsrc/app.py\n",
        ),
        _completed([], "true\n"),
        _completed([], "main\n"),
        _completed([], "abc123\n"),
        _completed(
            [],
            "__COMMIT__deadbeef|Alice|alice@example.com|2026-03-26T08:00:00+09:00|update app\nsrc/app.py\n",
        ),
        _completed([], " M src/app.py\n"),
    ]

    result = get_repo_change_report(GetRepoChangeReportParams(repo_path=str(tmp_path), limit=20))

    assert result["success"] is True
    assert result["summary"]["files_reported"] == 1
    assert result["summary"]["uncommitted_files"] == 1
    assert result["files"][0]["path"] == "src/app.py"
