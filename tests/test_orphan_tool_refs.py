"""CI gate: scripts/check_orphan_tool_refs.py must pass on every change.

The script scans markdown / YAML under docs/, skills/, website/, and the
top-level README files for tool name references that no longer exist in the
live registry. Any orphan reference (typo, deleted-but-not-cleaned-up tool
name, doc lagging behind a refactor) fails the build.

Implemented as an in-process import so we exercise the same registry path
production code uses, and so the failure surfaces inside pytest output rather
than only when a developer remembers to run the script by hand.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_orphan_tool_refs.py"


def _load_check_module():
    spec = importlib.util.spec_from_file_location("check_orphan_tool_refs", SCRIPT_PATH)
    assert spec and spec.loader, f"Cannot load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_orphan_tool_refs(capsys):
    """Docs/skills must not reference tool names absent from the live registry."""
    assert SCRIPT_PATH.is_file(), f"Missing checker script: {SCRIPT_PATH}"

    module = _load_check_module()
    exit_code = module.main()
    captured = capsys.readouterr()

    assert exit_code == 0, (
        "Orphan tool reference(s) detected in docs/skills.\n"
        "Run `python scripts/check_orphan_tool_refs.py` to reproduce.\n\n"
        f"{captured.out}"
    )
