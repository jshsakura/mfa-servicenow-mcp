"""Guard TOOL_PACKAGES*.md count accuracy against the live package config.

Before this, the count column was hand-edited with no generator and no test, so
every tool/package change silently drifted it (a manual edit even missed that
`platform_developer` inherits `standard`'s additions). This locks the counts to
`scripts/regenerate_doc_counts.py`.

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
        "TOOL_PACKAGES*.md counts are stale vs live package config. "
        "Regenerate with `python scripts/regenerate_doc_counts.py`."
    )
