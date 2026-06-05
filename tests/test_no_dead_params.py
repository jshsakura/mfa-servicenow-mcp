"""CI gate test: no tool declares a parameter it never uses.

A param a tool accepts but never reads is a confusion trap (the LLM passes it
expecting an effect that never happens — e.g. the long-lived
approve_change.approver_id bug). scripts/check_dead_params.py finds them.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_dead_params  # noqa: E402


def test_no_dead_tool_parameters():
    dead = check_dead_params.find_dead_params()
    assert not dead, (
        "Tool parameters declared but never used (wire them, remove them, or "
        "allowlist with justification in scripts/check_dead_params.py):\n"
        + "\n".join(f"  - {tool}.{field}" for tool, field in dead)
    )
