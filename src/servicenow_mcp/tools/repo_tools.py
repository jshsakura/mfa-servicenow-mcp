import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from servicenow_mcp.utils.registry import register_tool


class RepoQueryBaseParams(BaseModel):
    repo_path: str = Field(".", description="Target git repository path")
    path_filter: Optional[str] = Field(
        None,
        description="Optional path prefix filter (example: src/servicenow_mcp/tools)",
    )


class GetRepoWorkingTreeStatusParams(RepoQueryBaseParams):
    include_untracked: bool = Field(True, description="Include untracked files")


class GetRepoRecentCommitsParams(RepoQueryBaseParams):
    limit: int = Field(30, description="Maximum number of commits to return (1..200)")
    include_files: bool = Field(True, description="Include file list for each commit")


class GetRepoFileLastModifierParams(RepoQueryBaseParams):
    files: List[str] | None = Field(
        None,
        description="Optional target files. If omitted, uses files from working tree status and recent commits",
    )
    commits_scan_limit: int = Field(
        100, description="Commit scan depth used for file last-commit cache"
    )
    include_uncommitted_status: bool = Field(True, description="Attach uncommitted status per file")


class GetRepoChangeReportParams(RepoQueryBaseParams):
    limit: int = Field(50, description="Maximum number of recent commits to scan (1..200)")
    include_uncommitted: bool = Field(True, description="Include uncommitted files from git status")
    include_recent_commits: bool = Field(
        True, description="Include recent commit list and file mappings"
    )


def _run_git(repo_path: Path, args: List[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "git command failed").strip())
    return completed.stdout


def _resolve_repo(repo_path_value: str) -> Tuple[Path, str, str]:
    repo_path = Path(repo_path_value).expanduser().resolve()
    if not repo_path.exists():
        raise RuntimeError(f"Path does not exist: {repo_path}")

    inside = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"]).strip()
    if inside != "true":
        raise RuntimeError(f"Not a git repository: {repo_path}")

    branch = _run_git(repo_path, ["branch", "--show-current"]).strip()
    head = _run_git(repo_path, ["rev-parse", "HEAD"]).strip()
    return repo_path, branch, head


def _passes_filter(path: str, path_filter: Optional[str]) -> bool:
    return True if not path_filter else path.startswith(path_filter)


def _parse_porcelain_status(raw: str, include_untracked: bool) -> Dict[str, Dict[str, Any]]:
    status_map: Dict[str, Dict[str, Any]] = {}
    for line in raw.splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            if not include_untracked:
                continue
            path = line[3:].strip()
            status_map[path] = {
                "path": path,
                "index_status": "?",
                "worktree_status": "?",
                "untracked": True,
                "staged": False,
                "unstaged": False,
            }
            continue

        if len(line) < 4:
            continue

        index_status = line[0]
        worktree_status = line[1]
        path = line[3:].strip()
        status_map[path] = {
            "path": path,
            "index_status": index_status,
            "worktree_status": worktree_status,
            "untracked": False,
            "staged": index_status not in {" ", "?"},
            "unstaged": worktree_status not in {" ", "?"},
        }

    return status_map


def _parse_commit_log_with_files(raw: str) -> List[Dict[str, Any]]:
    commits: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    for line in raw.splitlines():
        if line.startswith("__COMMIT__"):
            payload = line[len("__COMMIT__") :]
            parts = payload.split("|", 4)
            if len(parts) != 5:
                continue
            current = {
                "hash": parts[0],
                "author": parts[1],
                "author_email": parts[2],
                "date": parts[3],
                "message": parts[4],
                "files": [],
            }
            commits.append(current)
            continue

        if current is None:
            continue
        file_path = line.strip()
        if file_path:
            current["files"].append(file_path)

    return commits


def _collect_recent_commits(repo_path: Path, limit: int) -> List[Dict[str, Any]]:
    capped = max(1, min(limit, 200))
    log_raw = _run_git(
        repo_path,
        [
            "log",
            f"-n{capped}",
            "--date=iso-strict",
            "--name-only",
            "--pretty=format:__COMMIT__%H|%an|%ae|%ad|%s",
        ],
    )
    return _parse_commit_log_with_files(log_raw)


def _latest_commit_by_file(commits: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for commit in commits:
        payload = {
            "hash": commit["hash"],
            "author": commit["author"],
            "author_email": commit["author_email"],
            "date": commit["date"],
            "message": commit["message"],
        }
        for file_path in commit.get("files", []):
            if file_path not in latest:
                latest[file_path] = payload
    return latest


@register_tool(
    "get_repo_working_tree_status",
    params=GetRepoWorkingTreeStatusParams,
    description="Inspect working tree status including staged, unstaged, and untracked files",
    serialization="raw_dict",
    return_type=dict,
)
def get_repo_working_tree_status(params: GetRepoWorkingTreeStatusParams) -> Dict[str, Any]:
    try:
        repo_path, branch, head = _resolve_repo(params.repo_path)
        status_raw = _run_git(repo_path, ["status", "--porcelain=v1"])
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    status_map = _parse_porcelain_status(status_raw, params.include_untracked)
    file_entries = [
        {
            "path": path,
            "index_status": status["index_status"],
            "worktree_status": status["worktree_status"],
            "staged": status["staged"],
            "unstaged": status["unstaged"],
            "untracked": status["untracked"],
        }
        for path, status in sorted(status_map.items())
        if _passes_filter(path, params.path_filter)
    ]

    summary = {
        "files": len(file_entries),
        "staged_files": sum(1 for entry in file_entries if entry["staged"]),
        "unstaged_files": sum(1 for entry in file_entries if entry["unstaged"]),
        "untracked_files": sum(1 for entry in file_entries if entry["untracked"]),
    }

    return {
        "success": True,
        "repo_path": str(repo_path),
        "branch": branch,
        "head": head,
        "summary": summary,
        "files": file_entries,
    }


@register_tool(
    "get_repo_recent_commits",
    params=GetRepoRecentCommitsParams,
    description="List recent commits with author and optional changed file lists",
    serialization="raw_dict",
    return_type=dict,
)
def get_repo_recent_commits(params: GetRepoRecentCommitsParams) -> Dict[str, Any]:
    try:
        repo_path, branch, head = _resolve_repo(params.repo_path)
        commits = _collect_recent_commits(repo_path, params.limit)
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    output_commits: List[Dict[str, Any]] = []
    for commit in commits:
        commit_files = [
            path for path in commit.get("files", []) if _passes_filter(path, params.path_filter)
        ]
        if params.path_filter and not commit_files:
            continue
        entry = {
            "hash": commit["hash"],
            "author": commit["author"],
            "author_email": commit["author_email"],
            "date": commit["date"],
            "message": commit["message"],
        }
        if params.include_files:
            entry["files"] = commit_files
        output_commits.append(entry)

    return {
        "success": True,
        "repo_path": str(repo_path),
        "branch": branch,
        "head": head,
        "count": len(output_commits),
        "commits": output_commits,
    }


@register_tool(
    "get_repo_file_last_modifier",
    params=GetRepoFileLastModifierParams,
    description="Lookup per-file last modifier and commit metadata with optional uncommitted status",
    serialization="raw_dict",
    return_type=dict,
)
def get_repo_file_last_modifier(params: GetRepoFileLastModifierParams) -> Dict[str, Any]:
    try:
        repo_path, branch, head = _resolve_repo(params.repo_path)
        commits = _collect_recent_commits(repo_path, params.commits_scan_limit)
        latest_by_file = _latest_commit_by_file(commits)
    except Exception as exc:
        return {"success": False, "message": str(exc)}

    status_map: Dict[str, Dict[str, Any]] = {}
    if params.include_uncommitted_status:
        status_raw = _run_git(repo_path, ["status", "--porcelain=v1"])
        status_map = _parse_porcelain_status(status_raw, include_untracked=True)

    targets = set(params.files or [])
    if not targets:
        targets = set(status_map.keys()) | set(latest_by_file.keys())
    if params.path_filter:
        targets = {path for path in targets if path.startswith(params.path_filter)}

    files: List[Dict[str, Any]] = []
    for file_path in sorted(targets):
        last_commit = latest_by_file.get(file_path)
        if last_commit is None:
            try:
                single_log_raw = _run_git(
                    repo_path,
                    [
                        "log",
                        "-n1",
                        "--date=iso-strict",
                        "--pretty=format:__COMMIT__%H|%an|%ae|%ad|%s",
                        "--",
                        file_path,
                    ],
                )
                parsed = _parse_commit_log_with_files(single_log_raw)
                if parsed:
                    single = parsed[0]
                    last_commit = {
                        "hash": single["hash"],
                        "author": single["author"],
                        "author_email": single["author_email"],
                        "date": single["date"],
                        "message": single["message"],
                    }
            except Exception:
                last_commit = None

        status = status_map.get(file_path, {}) if params.include_uncommitted_status else {}
        has_uncommitted = bool(
            status.get("staged") or status.get("unstaged") or status.get("untracked")
        )
        files.append(
            {
                "path": file_path,
                "last_modifier": (last_commit or {}).get("author", ""),
                "last_commit": last_commit,
                "commit_state": "uncommitted" if has_uncommitted else "committed",
                "status": {
                    "index_status": status.get("index_status", " "),
                    "worktree_status": status.get("worktree_status", " "),
                    "staged": bool(status.get("staged", False)),
                    "unstaged": bool(status.get("unstaged", False)),
                    "untracked": bool(status.get("untracked", False)),
                },
            }
        )

    return {
        "success": True,
        "repo_path": str(repo_path),
        "branch": branch,
        "head": head,
        "files": files,
        "summary": {
            "files_reported": len(files),
            "uncommitted_files": sum(
                1 for entry in files if entry["commit_state"] == "uncommitted"
            ),
            "commits_scanned": len(commits),
        },
    }


@register_tool(
    "get_repo_change_report",
    params=GetRepoChangeReportParams,
    description="Combined git report: working tree status + recent commits + per-file last modifier in one call.",
    serialization="raw_dict",
    return_type=dict,
)
def get_repo_change_report(params: GetRepoChangeReportParams) -> Dict[str, Any]:
    status_result = get_repo_working_tree_status(
        GetRepoWorkingTreeStatusParams(
            repo_path=params.repo_path,
            path_filter=params.path_filter,
            include_untracked=True,
        )
    )
    if not status_result.get("success"):
        return status_result

    recent_commits_result = {
        "success": True,
        "commits": [],
    }
    if params.include_recent_commits:
        recent_commits_result = get_repo_recent_commits(
            GetRepoRecentCommitsParams(
                repo_path=params.repo_path,
                path_filter=params.path_filter,
                limit=params.limit,
                include_files=True,
            )
        )
        if not recent_commits_result.get("success"):
            return recent_commits_result

    last_modifier_result = get_repo_file_last_modifier(
        GetRepoFileLastModifierParams(
            repo_path=params.repo_path,
            path_filter=params.path_filter,
            files=(
                [entry["path"] for entry in status_result.get("files", [])]
                if params.include_uncommitted
                else None
            ),
            commits_scan_limit=params.limit,
            include_uncommitted_status=params.include_uncommitted,
        )
    )
    if not last_modifier_result.get("success"):
        return last_modifier_result

    recent_commits_payload = recent_commits_result.get("commits")
    recent_commits: List[Dict[str, Any]] = (
        recent_commits_payload if isinstance(recent_commits_payload, list) else []
    )
    files_payload = last_modifier_result.get("files")
    files: List[Dict[str, Any]] = files_payload if isinstance(files_payload, list) else []

    return {
        "success": True,
        "repo_path": status_result["repo_path"],
        "branch": status_result["branch"],
        "head": status_result["head"],
        "summary": {
            **status_result.get("summary", {}),
            "commits_scanned": len(recent_commits),
            "files_reported": len(files),
            "uncommitted_files": sum(
                1 for entry in files if entry.get("commit_state") == "uncommitted"
            ),
        },
        "files": files,
        "recent_commits": recent_commits,
        "safety_notice": "Local git metadata only. No repository mutations are performed.",
    }
