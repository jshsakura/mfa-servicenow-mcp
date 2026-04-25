"""Guard against drift between the dev/repo and packaged tool_packages.yaml.

config/tool_packages.yaml          ← used by tests + dev runs
src/servicenow_mcp/config/tool_packages.yaml  ← shipped in the wheel

Both must stay byte-identical. If this test fails, copy whichever you edited
to the other location (or replace one with a symlink — see README).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_PATH = REPO_ROOT / "config" / "tool_packages.yaml"
PKG_PATH = REPO_ROOT / "src" / "servicenow_mcp" / "config" / "tool_packages.yaml"


def test_dev_and_packaged_yaml_match():
    assert DEV_PATH.exists(), f"missing dev config at {DEV_PATH}"
    assert PKG_PATH.exists(), f"missing packaged config at {PKG_PATH}"
    dev = DEV_PATH.read_bytes()
    pkg = PKG_PATH.read_bytes()
    assert dev == pkg, (
        f"\n{DEV_PATH.relative_to(REPO_ROOT)} and "
        f"{PKG_PATH.relative_to(REPO_ROOT)} have drifted.\n"
        "Copy whichever you edited to the other path so the wheel matches dev."
    )
