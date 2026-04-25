"""Extra tests for skill_resources.py — cover missed branches (88% → ~100%)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from servicenow_mcp.resources.skill_resources import (
    _find_skills_dir,
    _parse_frontmatter,
    load_skills,
)


class TestParseFrontmatterNoMatch:
    def test_no_frontmatter_returns_empty(self):
        result = _parse_frontmatter("Just regular text\nNo frontmatter here")
        assert result == {}

    def test_empty_string(self):
        result = _parse_frontmatter("")
        assert result == {}


class TestFindSkillsDir:
    def test_returns_none_when_no_skills(self):
        with (
            patch("pathlib.Path.is_dir", return_value=False),
            patch("pathlib.Path.rglob", return_value=[]),
        ):
            result = _find_skills_dir()
            assert result is None


class TestLoadSkillsNoDir:
    def test_returns_empty_when_no_skills_dir(self):
        load_skills.cache_clear()
        with patch("servicenow_mcp.resources.skill_resources._find_skills_dir", return_value=None):
            result = load_skills()
            assert result == []
        load_skills.cache_clear()


class TestLoadSkillsWithFiles:
    def test_loads_skill_from_directory(self):
        load_skills.cache_clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            category_dir = Path(tmpdir) / "fix"
            category_dir.mkdir()
            skill_file = category_dir / "widget-patching.md"
            skill_file.write_text(
                "---\n"
                "description: Fix widgets\n"
                "tools:\n"
                "  - sn_query\n"
                "---\n"
                "# Fix Widget\n"
                "Content here\n",
                encoding="utf-8",
            )
            with patch(
                "servicenow_mcp.resources.skill_resources._find_skills_dir",
                return_value=Path(tmpdir),
            ):
                result = load_skills()
                assert len(result) == 1
                uri, name, desc, cat, tools, content = result[0]
                assert uri == "skill://fix/widget-patching"
                assert name == "widget-patching"
                assert desc == "Fix widgets"
                assert cat == "fix"
                assert "sn_query" in tools
        load_skills.cache_clear()


class TestLoadSkillsSkipsInvalid:
    def test_skips_skill_md_file(self):
        load_skills.cache_clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            category_dir = Path(tmpdir) / "fix"
            category_dir.mkdir()
            (category_dir / "SKILL.md").write_text("---\n---\nContent", encoding="utf-8")
            with patch(
                "servicenow_mcp.resources.skill_resources._find_skills_dir",
                return_value=Path(tmpdir),
            ):
                result = load_skills()
                assert len(result) == 0
        load_skills.cache_clear()

    def test_skips_underscore_prefix(self):
        load_skills.cache_clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            category_dir = Path(tmpdir) / "fix"
            category_dir.mkdir()
            (category_dir / "_internal.md").write_text("---\n---\nContent", encoding="utf-8")
            with patch(
                "servicenow_mcp.resources.skill_resources._find_skills_dir",
                return_value=Path(tmpdir),
            ):
                result = load_skills()
                assert len(result) == 0
        load_skills.cache_clear()

    def test_skips_nested_directories(self):
        load_skills.cache_clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_dir = Path(tmpdir) / "fix" / "sub"
            deep_dir.mkdir(parents=True)
            (deep_dir / "deep.md").write_text("---\n---\nContent", encoding="utf-8")
            with patch(
                "servicenow_mcp.resources.skill_resources._find_skills_dir",
                return_value=Path(tmpdir),
            ):
                result = load_skills()
                assert len(result) == 0
        load_skills.cache_clear()

    def test_skips_unreadable_file(self):
        load_skills.cache_clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            category_dir = Path(tmpdir) / "fix"
            category_dir.mkdir()
            skill_file = category_dir / "broken.md"
            skill_file.write_text("---\n---\nContent", encoding="utf-8")
            with patch(
                "servicenow_mcp.resources.skill_resources._find_skills_dir",
                return_value=Path(tmpdir),
            ):
                with patch("pathlib.Path.read_text", side_effect=PermissionError("no access")):
                    result = load_skills()
                    assert len(result) == 0
        load_skills.cache_clear()

    def test_tool_names_string_converted_to_list(self):
        load_skills.cache_clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            category_dir = Path(tmpdir) / "fix"
            category_dir.mkdir()
            skill_file = category_dir / "single-tool.md"
            skill_file.write_text(
                "---\n" "description: Single\n" "tools: sn_query\n" "---\n" "# Single\n",
                encoding="utf-8",
            )
            with patch(
                "servicenow_mcp.resources.skill_resources._find_skills_dir",
                return_value=Path(tmpdir),
            ):
                result = load_skills()
                assert len(result) == 1
                assert isinstance(result[0][4], list)
                assert result[0][4] == ["sn_query"]
        load_skills.cache_clear()
