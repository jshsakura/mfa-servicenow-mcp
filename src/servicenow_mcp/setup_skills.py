"""
Setup skills for MFA ServiceNow MCP.

Downloads portal-specialized skills from the mfa-servicenow-mcp repository
and installs them into the current project.

Usage:
    servicenow-mcp-skills claude
    servicenow-mcp-skills codex
    servicenow-mcp-skills opencode
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
GITHUB_ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"

TARGETS = {
    "claude": ".claude/commands/servicenow",
    "codex": ".codex/skills/servicenow",
    "opencode": ".opencode/skills/servicenow",
    "gemini": ".gemini/skills/servicenow",
}

CATEGORIES = ["analyze", "fix", "manage", "deploy", "explore"]


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def _download_skills(dest: Path) -> int:
    """Download skills/ from GitHub and extract to dest. Returns skill count."""
    _print(f"  Downloading from github.com/{REPO}...")
    t0 = time.monotonic()

    try:
        resp = urlopen(GITHUB_ZIP_URL, timeout=30)
        zip_bytes = resp.read()
    except Exception as exc:
        _print(f"  FAILED: {exc}")
        sys.exit(1)

    elapsed_dl = time.monotonic() - t0
    _print(f"  Downloaded ({len(zip_bytes) // 1024}KB, {elapsed_dl:.1f}s)")

    prefix = f"mfa-servicenow-mcp-{BRANCH}/{SKILLS_DIR}/"
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
                if rel.endswith(".md") and rel != "SKILL.md" and "/" in rel:
                    cat = rel.split("/")[0]
                    categories_found[cat] = categories_found.get(cat, 0) + 1
                    count += 1

    # Progress: show what was installed
    for cat in sorted(categories_found):
        _print(f"    {cat}/ — {categories_found[cat]} skills")

    return count


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        _print()
        _print("MFA ServiceNow MCP — Skill Installer")
        _print("=" * 40)
        _print()
        _print("Usage: servicenow-mcp-skills <target>")
        _print()
        _print("Targets:")
        _print("  claude     .claude/commands/servicenow/")
        _print("  codex      .codex/skills/servicenow/")
        _print("  opencode   .opencode/skills/servicenow/")
        _print("  gemini     .gemini/skills/servicenow/")
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

    if dest.exists():
        _print("  Removing previous installation...")
        shutil.rmtree(dest)

    t0 = time.monotonic()
    count = _download_skills(dest)
    elapsed = time.monotonic() - t0

    # Marker file
    (dest / "_mcp_info.md").write_text(
        "# MFA ServiceNow MCP Skills\n\n"
        "Workflow recipes for the `mfa-servicenow-mcp` MCP server.\n"
        "Each skill has triggers, decision trees, and exact tool calls.\n\n"
        f"- Package: `mfa-servicenow-mcp` (PyPI)\n"
        f"- Repository: https://github.com/{REPO}\n",
        encoding="utf-8",
    )

    _print()
    _print(f"Done. {count} skills installed in {elapsed:.1f}s")
    _print()


if __name__ == "__main__":
    main()
