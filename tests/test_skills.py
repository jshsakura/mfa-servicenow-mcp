"""
Skill validation tests — ensures all skills are well-formed,
reference real MCP tools, and have required structure.

Runs as part of CI to prevent broken skills from being merged.
"""

from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

REQUIRED_META_FIELDS = [
    "name",
    "description",
    "context_cost",
    "safety_level",
    "delegatable",
    "required_input",
    "output",
    "tools",
    "triggers",
]

VALID_CONTEXT_COSTS = {"low", "medium", "high"}
VALID_SAFETY_LEVELS = {"none", "confirm", "staged"}
VALID_OUTPUTS = {"summary", "report", "diff", "data", "status", "files", "action", "diagnosis"}
VALID_CATEGORIES = {"analyze", "fix", "manage", "deploy", "explore"}

REQUIRED_SECTIONS = ["## Pipeline", "## ON ERROR", "## DELEGATE hint"]


def _get_skill_files():
    """Collect all skill markdown files (excluding index)."""
    return sorted(
        p
        for p in SKILLS_DIR.rglob("*.md")
        if p.name != "SKILL.md" and p.name != "_mcp_info.md" and ".ipynb_checkpoints" not in str(p)
    )


def _parse_frontmatter(path: Path):
    """Parse YAML frontmatter from a skill file."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None, content
    end = content.index("---", 3)
    front = yaml.safe_load(content[3:end])
    body = content[end + 3 :]
    return front, body


def _get_all_registered_tools():
    """Get set of all tool names registered in code."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from servicenow_mcp.utils.registry import discover_tools

    return set(discover_tools().keys())


# Cache tools once
_ALL_TOOLS = None


def _tools():
    global _ALL_TOOLS
    if _ALL_TOOLS is None:
        _ALL_TOOLS = _get_all_registered_tools()
    return _ALL_TOOLS


# ============================================================================
# Tests
# ============================================================================


class TestSkillStructure:
    """Verify skill directory structure is correct."""

    def test_skills_directory_exists(self):
        assert SKILLS_DIR.is_dir(), f"skills/ directory not found at {SKILLS_DIR}"

    def test_index_exists(self):
        assert (SKILLS_DIR / "SKILL.md").is_file(), "skills/SKILL.md index missing"

    def test_categories_are_valid(self):
        """Only allowed category directories should exist."""
        for item in SKILLS_DIR.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                assert item.name in VALID_CATEGORIES, (
                    f"Unknown category directory: {item.name}. " f"Allowed: {VALID_CATEGORIES}"
                )

    def test_no_empty_categories(self):
        """Each category must have at least one skill."""
        for cat in VALID_CATEGORIES:
            cat_dir = SKILLS_DIR / cat
            if cat_dir.is_dir():
                skills = list(cat_dir.glob("*.md"))
                assert len(skills) > 0, f"Category {cat}/ is empty"


class TestSkillMetadata:
    """Verify each skill has valid YAML frontmatter."""

    @pytest.fixture(params=_get_skill_files(), ids=lambda p: str(p.relative_to(SKILLS_DIR)))
    def skill(self, request):
        path = request.param
        front, body = _parse_frontmatter(path)
        return path, front, body

    def test_has_frontmatter(self, skill):
        path, front, _ = skill
        assert front is not None, f"{path.name}: missing YAML frontmatter"

    def test_required_fields_present(self, skill):
        path, front, _ = skill
        if front is None:
            pytest.skip("no frontmatter")
        for field in REQUIRED_META_FIELDS:
            assert field in front, f"{path.name}: missing required field '{field}'"

    def test_context_cost_valid(self, skill):
        _, front, _ = skill
        if front and "context_cost" in front:
            assert (
                front["context_cost"] in VALID_CONTEXT_COSTS
            ), f"context_cost must be one of {VALID_CONTEXT_COSTS}"

    def test_safety_level_valid(self, skill):
        _, front, _ = skill
        if front and "safety_level" in front:
            assert (
                front["safety_level"] in VALID_SAFETY_LEVELS
            ), f"safety_level must be one of {VALID_SAFETY_LEVELS}"

    def test_output_valid(self, skill):
        _, front, _ = skill
        if front and "output" in front:
            assert front["output"] in VALID_OUTPUTS, f"output must be one of {VALID_OUTPUTS}"

    def test_delegatable_is_bool(self, skill):
        _, front, _ = skill
        if front and "delegatable" in front:
            assert isinstance(front["delegatable"], bool), "delegatable must be true or false"

    def test_tools_is_list(self, skill):
        _, front, _ = skill
        if front and "tools" in front:
            assert isinstance(front["tools"], list), "tools must be a list"

    def test_triggers_is_list(self, skill):
        _, front, _ = skill
        if front and "triggers" in front:
            assert isinstance(front["triggers"], list), "triggers must be a list"
            assert len(front["triggers"]) >= 2, "triggers must have at least 2 entries (KO + EN)"


class TestSkillToolReferences:
    """Verify all tool references in skills point to real MCP tools."""

    @pytest.fixture(params=_get_skill_files(), ids=lambda p: str(p.relative_to(SKILLS_DIR)))
    def skill(self, request):
        path = request.param
        front, body = _parse_frontmatter(path)
        return path, front, body

    def test_all_tools_exist(self, skill):
        path, front, _ = skill
        if front is None or "tools" not in front:
            pytest.skip("no tools field")
        registered = _tools()
        for tool_name in front["tools"]:
            assert tool_name in registered, (
                f"{path.name}: references unknown tool '{tool_name}'. "
                f"Did the tool get renamed or removed?"
            )


class TestSkillContent:
    """Verify each skill has required instruction sections."""

    @pytest.fixture(params=_get_skill_files(), ids=lambda p: str(p.relative_to(SKILLS_DIR)))
    def skill(self, request):
        path = request.param
        front, body = _parse_frontmatter(path)
        return path, front, body

    def test_has_instructions_header(self, skill):
        path, _, body = skill
        assert "# Instructions" in body, f"{path.name}: missing '# Instructions' section"

    def test_has_pipeline(self, skill):
        path, _, body = skill
        assert "## Pipeline" in body, f"{path.name}: missing '## Pipeline' section"

    def test_has_error_handling(self, skill):
        path, _, body = skill
        assert "## ON ERROR" in body, f"{path.name}: missing '## ON ERROR' section"

    def test_has_delegate_hint(self, skill):
        path, _, body = skill
        assert "## DELEGATE hint" in body, f"{path.name}: missing '## DELEGATE hint' section"

    def test_pipeline_has_action_statements(self, skill):
        """Pipeline must contain at least one action instruction (CALL, READ, WRITE, SCAN, ASK, IDENTIFY, VALIDATE, GENERATE, APPLY, SHOW)."""
        path, _, body = skill
        pipeline_start = body.find("## Pipeline")
        if pipeline_start == -1:
            pytest.skip("no pipeline")
        pipeline_section = body[pipeline_start:]
        # Find next ## or end of file
        next_section = pipeline_section.find("\n## ", 1)
        if next_section > 0:
            pipeline_section = pipeline_section[:next_section]
        action_keywords = [
            "CALL ",
            "READ ",
            "WRITE ",
            "SCAN ",
            "ASK",
            "IDENTIFY",
            "VALIDATE",
            "GENERATE",
            "APPLY",
            "SHOW",
            "UPDATE",
        ]
        has_action = any(kw in pipeline_section for kw in action_keywords)
        assert has_action, f"{path.name}: Pipeline section has no action instructions"

    def test_staged_skills_have_gate(self, skill):
        """Skills with safety_level=staged must have GATE rules."""
        path, front, body = skill
        if front and front.get("safety_level") == "staged":
            assert "GATE" in body, f"{path.name}: safety_level is 'staged' but no GATE rules found"


class TestSkillIndex:
    """Verify the SKILL.md index references all skills correctly."""

    def test_all_skills_in_index(self):
        """Every skill file must be listed in SKILL.md index."""
        index_content = (SKILLS_DIR / "SKILL.md").read_text(encoding="utf-8")
        skill_files = _get_skill_files()

        missing = []
        for sf in skill_files:
            rel = str(sf.relative_to(SKILLS_DIR))
            # Index uses relative links like (analyze/widget-analysis.md)
            if rel not in index_content:
                missing.append(rel)

        assert len(missing) == 0, f"Skills missing from SKILL.md index: {missing}"

    def test_index_links_are_valid(self):
        """All links in SKILL.md must point to existing files."""
        import re

        index_content = (SKILLS_DIR / "SKILL.md").read_text(encoding="utf-8")
        links = re.findall(r"\(([a-z/-]+\.md)\)", index_content)

        broken = []
        for link in links:
            target = SKILLS_DIR / link
            if not target.is_file():
                broken.append(link)

        assert len(broken) == 0, f"Broken links in SKILL.md: {broken}"
