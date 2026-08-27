"""The sys_id shape rule in scripts/check_real_identities.py.

A sys_id is 32 characters of meaningless hex: a real one read off a live
instance is indistinguishable BY INSPECTION from an invented one. There is no
pattern that identifies a real one, so the check runs the other way round — a
sys_id in this repo must LOOK constructed. These pin that direction, because a
rule that fails open here fails silently and permanently (a push cannot be
taken back).
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_real_identities",
    Path(__file__).resolve().parent.parent / "scripts" / "check_real_identities.py",
)
assert _SPEC is not None and _SPEC.loader is not None
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

# Halves, doubled at run time. The refused cases are by definition 32-hex
# strings the rule rejects, so writing them as literals would make this file
# fail its own check — and the fix for that must not be an exemption, or the
# exemption becomes the way past the rule.


def _scan_text(tmp_path, text):
    """scan() reports paths relative to REPO, so point REPO at the tmp tree."""
    f = tmp_path / "fixture.py"
    f.write_text(text, encoding="utf-8")
    original = checker.REPO
    checker.REPO = tmp_path
    try:
        return checker.scan(f)
    finally:
        checker.REPO = original


@pytest.mark.parametrize(
    "sys_id",
    [
        "0123456789abcdef" * 2,
        "fedcba9876543210" * 2,
        "13579bdf02468ace" * 2,
        "0f1e2d3c4b5a6978" * 2,
    ],
)
def test_a_sys_id_that_does_not_look_constructed_is_blocked(tmp_path, sys_id):
    hits = _scan_text(tmp_path, f'SID = "{sys_id}"\n')
    assert hits, f"{sys_id} should be refused"
    assert sys_id in hits[0]


@pytest.mark.parametrize(
    "sys_id",
    [
        "aaaa1111bbbb2222cccc3333dddd4444",
        "eeee5555ffff6666aaaa7777bbbb8888",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "8888aaaa9999bbbb0000cccc1111dddd",
    ],
)
def test_a_visibly_constructed_sys_id_passes(tmp_path, sys_id):
    assert _scan_text(tmp_path, f'SID = "{sys_id}"\n') == []


def test_a_platform_global_id_passes_only_via_the_allowlist(tmp_path):
    """Flow Designer's script-step variable type ships with the platform."""
    sid = "71aa7f6647032200b4fad7527c9a719b"
    assert sid in checker.ALLOWED_SYS_IDS
    assert _scan_text(tmp_path, f'SCRIPT_STEP_VAR_SYSID = "{sid}"\n') == []


def test_a_git_sha_is_not_mistaken_for_a_sys_id(tmp_path):
    """40 hex chars is a commit, not a record — flagging it teaches people to
    ignore the output, which is how a real hit gets scrolled past."""
    assert _scan_text(tmp_path, "# see 386bcc078ef5d0b7c019933c7fbeb3877daabebf\n") == []


def test_the_whole_tracked_tree_is_clean():
    """The rule is only worth anything if the repo currently satisfies it."""
    hits = []
    for path in checker._all_files():
        hits.extend(checker.scan(path))
    assert hits == [], "\n".join(hits[:10])
