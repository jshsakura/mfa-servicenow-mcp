"""Setup skills for MFA ServiceNow MCP.

Skills install from the copy bundled inside the installed package
(``servicenow_mcp/skills/``) so the server and its skills always match the
installed version and work offline. GitHub download is only a fallback for
environments where the bundled copy is missing, and even then it is pinned to
the installed version's git tag (``v{__version__}``) before falling back to the
``main`` branch.
"""

import io
import shutil
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import urlopen

REPO = "jshsakura/mfa-servicenow-mcp"
BRANCH = "main"
SKILLS_DIR = "skills"

TARGETS = {
    "claude": ".claude/commands/servicenow",
    "codex": ".codex/skills/servicenow",
    "opencode": ".opencode/skills/servicenow",
    # Antigravity (Google) replaces the discontinued Gemini CLI. Its files live
    # under the .gemini/antigravity/ namespace (same as its MCP config).
    "antigravity": ".gemini/antigravity/skills/servicenow",
}

CATEGORIES = ["analyze", "fix", "manage", "deploy", "explore"]


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def _installed_version() -> str | None:
    try:
        from servicenow_mcp.version import __version__

        return __version__
    except Exception:
        return None


def _count_skill(rel: str) -> bool:
    """A countable skill is a category .md (e.g. ``manage/local-sync.md``)."""
    return rel.endswith(".md") and rel != "SKILL.md" and "/" in rel


# ---------------------------------------------------------------------------
# Bundled source (preferred) — copy from the installed package, no network
# ---------------------------------------------------------------------------


def _find_bundled_skills_dir() -> Path | None:
    """Locate the skills/ dir shipped inside the package (or repo checkout)."""
    try:
        from servicenow_mcp.resources.skill_resources import _find_skills_dir

        return _find_skills_dir()
    except Exception:
        return None


def _copy_bundled_skills(dest: Path) -> int | None:
    """Copy bundled skills into *dest*. Returns count, or None if unavailable."""
    src = _find_bundled_skills_dir()
    if src is None:
        return None

    _print("  Using skills bundled with the installed package...")
    count = 0
    categories_found: dict[str, int] = {}
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if _count_skill(rel):
            cat = rel.split("/")[0]
            categories_found[cat] = categories_found.get(cat, 0) + 1
            count += 1

    for cat in sorted(categories_found):
        _print(f"    {cat}/ — {categories_found[cat]} skills")
    return count


# ---------------------------------------------------------------------------
# GitHub fallback — pinned to the installed version tag, then main
# ---------------------------------------------------------------------------


def _download_refs() -> list[str]:
    """Refs to try, in order: installed version tag first, then main."""
    refs: list[str] = []
    version = _installed_version()
    if version:
        refs.append(f"v{version}")
    refs.append(BRANCH)
    return refs


def _ref_url_and_prefix(ref: str) -> tuple[str, str]:
    """GitHub archive URL and in-zip path prefix for a branch or tag ref."""
    if ref == BRANCH:
        url = f"https://github.com/{REPO}/archive/refs/heads/{ref}.zip"
        dir_name = f"mfa-servicenow-mcp-{ref}"
    else:
        # Tag archives extract to a dir with the leading 'v' stripped.
        url = f"https://github.com/{REPO}/archive/refs/tags/{ref}.zip"
        dir_name = f"mfa-servicenow-mcp-{ref.lstrip('v')}"
    return url, f"{dir_name}/{SKILLS_DIR}/"


def _download_skills_from_ref(dest: Path, ref: str) -> int:
    url, prefix = _ref_url_and_prefix(ref)
    _print(f"  Downloading skills@{ref} from github.com/{REPO}...")
    t0 = time.monotonic()
    resp = urlopen(url, timeout=30)
    zip_bytes = resp.read()
    _print(f"  Downloaded ({len(zip_bytes) // 1024}KB, {time.monotonic() - t0:.1f}s)")

    count = 0
    categories_found: dict[str, int] = {}
    _print("  Extracting skills...")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix) :]
            if not rel:
                continue
            target = dest / rel
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                if _count_skill(rel):
                    cat = rel.split("/")[0]
                    categories_found[cat] = categories_found.get(cat, 0) + 1
                    count += 1

    if count == 0:
        raise RuntimeError("no skills found in archive")
    for cat in sorted(categories_found):
        _print(f"    {cat}/ — {categories_found[cat]} skills")
    return count


def _download_skills(dest: Path) -> int:
    """Download skills/ from GitHub, trying the version tag then main."""
    last_error: Exception | None = None
    for ref in _download_refs():
        try:
            return _download_skills_from_ref(dest, ref)
        except Exception as exc:  # noqa: BLE001 — try the next ref
            last_error = exc
            _print(f"  {ref} unavailable: {exc}")
    _print(f"  FAILED: could not download skills from GitHub ({last_error})")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Public install / remove
# ---------------------------------------------------------------------------


def install_skills(target: str, dest: Path | None = None) -> int:
    """Install skills for one supported target and return installed count."""
    if target not in TARGETS:
        raise ValueError(f"Unsupported skill target: {target}")

    resolved_dest = dest or (Path.cwd() / TARGETS[target])

    if resolved_dest.exists():
        _print("  Removing previous installation...")
        shutil.rmtree(resolved_dest)

    count = _copy_bundled_skills(resolved_dest)
    source = "bundled with installed package"
    if count is None:
        count = _download_skills(resolved_dest)
        source = "downloaded from GitHub"

    version = _installed_version() or "unknown"
    (resolved_dest / "_mcp_info.md").write_text(
        "# MFA ServiceNow MCP Skills\n\n"
        "Workflow recipes for the `mfa-servicenow-mcp` MCP server.\n"
        "Each skill has triggers, decision trees, and exact tool calls.\n\n"
        f"- Package: `mfa-servicenow-mcp` (PyPI)\n"
        f"- Server version: `{version}`\n"
        f"- Skill source: {source}\n"
        f"- Repository: https://github.com/{REPO}\n",
        encoding="utf-8",
    )
    return count


def remove_skills(target: str, dest: Path | None = None) -> bool:
    """Remove skills for one supported target and report whether anything changed."""
    if target not in TARGETS:
        raise ValueError(f"Unsupported skill target: {target}")

    resolved_dest = dest or (Path.cwd() / TARGETS[target])
    if not resolved_dest.exists():
        return False

    shutil.rmtree(resolved_dest)
    return True


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        _print()
        _print("MFA ServiceNow MCP — Skill Installer")
        _print("=" * 40)
        _print()
        _print("Usage: servicenow-mcp-skills <target>")
        _print()
        _print("Targets:")
        _print("  claude       .claude/commands/servicenow/")
        _print("  codex        .codex/skills/servicenow/")
        _print("  opencode     .opencode/skills/servicenow/")
        _print("  antigravity  .gemini/antigravity/skills/servicenow/")
        _print()
        _print("Example:")
        _print("  servicenow-mcp-skills claude")
        _print()
        _print("Or with uvx (no install needed):")
        _print("  uvx --from mfa-servicenow-mcp servicenow-mcp-skills claude")
        sys.exit(0)

    target = sys.argv[1]
    dest = Path.cwd() / TARGETS[target]

    _print()
    _print("MFA ServiceNow MCP — Skill Installer")
    _print("=" * 40)
    _print(f"  Target:  {target}")
    _print(f"  Path:    {dest}")
    _print()

    t0 = time.monotonic()
    count = install_skills(target, dest)
    elapsed = time.monotonic() - t0

    _print()
    _print(f"Done. {count} skills installed in {elapsed:.1f}s")
    _print()


if __name__ == "__main__":
    main()
