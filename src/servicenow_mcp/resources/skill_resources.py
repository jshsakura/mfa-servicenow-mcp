"""Expose skills/ markdown files as MCP resources.

Skills are loaded once at startup from the package's ``skills/`` directory
(via ``importlib.resources``) or from the repo checkout.  Each ``.md`` file
becomes an MCP resource with URI ``skill://{category}/{name}``.

Clients can:
  * ``list_resources`` → discover available skill guides
  * ``read_resource("skill://fix/widget-patching")`` → pull the full SOP

This is **pull-based** — zero token cost until a client actually reads a skill.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Frontmatter fields we parse from each skill .md
_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_PATTERN = re.compile(r"^(\w[\w_]*):\s*(.*)$", re.MULTILINE)
_LIST_ITEM = re.compile(r"^\s*-\s*(.+)$", re.MULTILINE)

# Skill entry: (uri, name, description, category, tool_names, content)
SkillEntry = Tuple[str, str, str, str, List[str], str]


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """Extract YAML-ish frontmatter without importing PyYAML."""
    m = _FM_PATTERN.match(text)
    if not m:
        return {}
    block = m.group(1)
    result: Dict[str, Any] = {}
    current_key: str | None = None
    current_list: List[str] = []

    def _flush_list() -> None:
        nonlocal current_key, current_list
        if current_key is not None and current_list:
            result[current_key] = current_list
        current_key = None
        current_list = []

    for line in block.split("\n"):
        li = _LIST_ITEM.match(line)
        if li and current_key is not None:
            current_list.append(li.group(1).strip().strip('"').strip("'"))
            continue

        kv = _KV_PATTERN.match(line)
        if kv:
            _flush_list()
            key = kv.group(1)
            val = kv.group(2).strip()
            if val == "" or val == "[]":
                # Next lines may be list items
                current_key = key
                current_list = []
            else:
                result[key] = val

    _flush_list()
    return result


def _find_skills_dir() -> Path | None:
    """Locate the skills/ directory — package or repo checkout."""
    # 1. importlib.resources (pip installed)
    try:
        from importlib.resources import files

        pkg = files("servicenow_mcp")
        # skills/ lives at repo root, two levels up from the package
        candidates = [
            Path(str(pkg)).parent.parent / "skills",
            Path(str(pkg)) / "skills",
        ]
    except Exception:
        candidates = []

    # 2. Repo-relative fallback
    repo_skills = Path(os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "skills")
    ))
    candidates.append(repo_skills)

    for p in candidates:
        if p.is_dir() and any(p.rglob("*.md")):
            return p
    return None


@lru_cache(maxsize=1)
def load_skills() -> List[SkillEntry]:
    """Discover and parse all skill .md files. Cached for server lifetime."""
    skills_dir = _find_skills_dir()
    if skills_dir is None:
        logger.info("No skills/ directory found — skill resources disabled")
        return []

    entries: List[SkillEntry] = []

    for md_path in sorted(skills_dir.rglob("*.md")):
        if md_path.name == "SKILL.md" or md_path.name.startswith("_"):
            continue

        rel = md_path.relative_to(skills_dir)
        parts = rel.with_suffix("").parts  # e.g. ("fix", "widget-patching")
        if len(parts) != 2:
            continue

        category, name = parts
        uri = f"skill://{category}/{name}"

        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Failed to read skill %s", md_path, exc_info=True)
            continue

        fm = _parse_frontmatter(content)
        description = fm.get("description", name.replace("-", " ").title())
        tool_names = fm.get("tools", [])
        if isinstance(tool_names, str):
            tool_names = [tool_names]

        entries.append((uri, name, description, category, tool_names, content))

    logger.info("Loaded %d skill resources from %s", len(entries), skills_dir)
    return entries


def build_tool_to_skills_map() -> Dict[str, List[str]]:
    """Build reverse map: tool_name → [skill URIs that reference it]."""
    mapping: Dict[str, List[str]] = {}
    for uri, _name, _desc, _cat, tool_names, _content in load_skills():
        for tool in tool_names:
            mapping.setdefault(tool, []).append(uri)
    return mapping
