"""Guard every hand-maintained tool count against the live package config.

Before this, the count column was hand-edited with no generator and no test, so
every tool/package change silently drifted it (a manual edit even missed that
`platform_developer` inherits `standard`'s additions). This locks the counts to
`scripts/regenerate_doc_counts.py`.

v1.24.24 widened the generator past TOOL_PACKAGES to the READMEs, the Windows
install guides, the translated inventories, llm-setup and the website landing
pages — 32 files across six languages, several of which were four releases
behind. ``apply(check=True)`` covers all of them, so this one assertion grew
with it.

Marked ``docs`` — a stale count is one command to fix and must not block the
deploy; CI runs it in a separate non-blocking job. Regenerate with:

    python scripts/regenerate_doc_counts.py
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "regenerate_doc_counts.py"


def _load_generator():
    spec = spec_from_file_location("regenerate_doc_counts", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load generator from {SCRIPT_PATH}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_packages_counts_match_live():
    gen = _load_generator()
    assert gen.apply(check=True) == 0, (
        "Documented tool counts are stale vs live package config. "
        "Regenerate with `python scripts/regenerate_doc_counts.py`."
    )


def test_a_rewrite_rule_that_matches_twice_refuses_to_guess():
    """The bug this caught, kept caught.

    The website hero block holds four stats — tools, MFA, skill categories,
    credentials shared. A rule anchored on the stat VALUE alone matched all
    four and rewrote every one of them to the tool count. It was spotted by
    reading the diff, which is not a control. A rule that matches more than
    once does not know what it is editing, so it must stop rather than pick.
    """
    gen = _load_generator()
    hero = (
        '<span class="hero-stat-value">66</span>\n'
        '    <span class="hero-stat-label">Registered Tools</span>\n'
        '<span class="hero-stat-value">3</span>\n'
        '    <span class="hero-stat-label">Skill Categories</span>\n'
    )
    updated = gen._rewrite(hero, {"registry": 75})
    assert '<span class="hero-stat-value">75</span>' in updated
    assert '<span class="hero-stat-value">3</span>' in updated, "an unrelated stat was rewritten"

    with pytest.raises(SystemExit):
        # Two lines that both state the registry total the same way: the file
        # is ambiguous, and guessing is what produced the bug above.
        gen._rewrite("**66 registered tools**\n**66 registered tools**\n", {"registry": 75})


def test_a_rule_that_carries_its_anchor_keeps_the_sentence():
    """The second bug this caught, also kept caught.

    ``re.sub`` replaces the whole MATCH, not the group — so the rule
    ``\\*\\*(?P<n>\\d+) registered tools\\*\\*`` turned

        - **66 registered tools** with **6 active package profiles** …
    into
        - 75 with **6 active package profiles** …

    eating the words it was anchored on, in six languages at once. Only the
    number may move.
    """
    gen = _load_generator()
    line = "- **66 registered tools** with **6 active package profiles** plus `none`\n"
    assert gen._rewrite(line, {"registry": 75}) == (
        "- **75 registered tools** with **6 active package profiles** plus `none`\n"
    )
    ko = "- **등록 도구 66개**, **실사용 패키지 6개**와 비활성 `none` 프로필\n"
    assert gen._rewrite(ko, {"registry": 75}) == (
        "- **등록 도구 75개**, **실사용 패키지 6개**와 비활성 `none` 프로필\n"
    )


def test_every_prose_rule_captures_exactly_one_number():
    """A rule must isolate the number, or `sub` would eat its own anchor."""
    import re

    gen = _load_generator()
    for pattern_text, key in gen.PROSE_RULES:
        compiled = re.compile(pattern_text)
        assert compiled.groups == 1, f"{pattern_text!r} must have exactly one group"
        assert "n" in compiled.groupindex, f"{pattern_text!r} must name its group 'n'"
        assert key in {"registry", "full", "standard", "unpackaged"}, f"unknown key {key}"
