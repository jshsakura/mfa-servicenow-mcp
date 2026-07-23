#!/usr/bin/env python3
"""Regenerate the per-package tool counts in docs/TOOL_PACKAGES*.md from live config.

The count column of TOOL_PACKAGES had no generator and no accuracy test — it was
hand-edited, so every tool/package change silently drifted it (and the website
mirrors with it). This script is the single source of truth: it loads each
package through the real server and rewrites the count cell in every language
file, then resyncs the website mirrors.

Usage:
    python scripts/regenerate_doc_counts.py          # rewrite in place
    python scripts/regenerate_doc_counts.py --check   # exit 1 if any file is stale

The `~Tokens` column is an approximate footprint and is left untouched (it needs
tiktoken over compacted schemas; a one-tool delta is within its stated slop).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DOCS_DIR = ROOT / "docs"
MIRROR_DIR = ROOT / "website" / "docs" / "docs"

DOC_FILES = [
    "TOOL_PACKAGES.md",
    "TOOL_PACKAGES.es.md",
    "TOOL_PACKAGES.hi.md",
    "TOOL_PACKAGES.ja.md",
    "TOOL_PACKAGES.ko.md",
    "TOOL_PACKAGES.zh.md",
]

# Packages that appear in the doc tables with a live-computed count. `none` is a
# static 0 and is intentionally not recomputed.
PACKAGES = [
    "core",
    "standard",
    "service_desk",
    "portal_developer",
    "platform_developer",
    "full",
]


def live_package_counts() -> dict[str, int]:
    """Return {package: exposed tool count} from the real server, per package."""
    from servicenow_mcp.server import ServiceNowMCP
    from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )
    counts: dict[str, int] = {}
    prev_pkg = os.environ.get("MCP_TOOL_PACKAGE")
    prev_path = os.environ.get("TOOL_PACKAGE_CONFIG_PATH")
    os.environ.pop("TOOL_PACKAGE_CONFIG_PATH", None)
    try:
        for pkg in PACKAGES:
            os.environ["MCP_TOOL_PACKAGE"] = pkg
            counts[pkg] = len(ServiceNowMCP(config).enabled_tool_names)
    finally:
        for key, prev in (("MCP_TOOL_PACKAGE", prev_pkg), ("TOOL_PACKAGE_CONFIG_PATH", prev_path)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
    return counts


def _rewrite(text: str, counts: dict[str, int]) -> str:
    """Rewrite the count cell of each package row, keyed by package name."""
    for pkg, count in counts.items():
        # | `pkg` | <count> | ...   — anchor on the unique package-name cell so
        # portal_developer/platform_developer (same count) never collide.
        pattern = re.compile(rf"(^\| `{re.escape(pkg)}` \| )\d+( \|)", re.MULTILINE)
        new, n = pattern.subn(rf"\g<1>{count}\g<2>", text)
        if n != 1:
            raise SystemExit(f"expected exactly 1 row for `{pkg}`, found {n}")
        text = new
    # Headline "Packaged tool count in `full`: **N**" if present.
    text = re.sub(
        r"(Packaged tool count in `full`: \*\*)\d+(\*\*)",
        rf"\g<1>{counts['full']}\g<2>",
        text,
    )
    return text


def apply(check: bool) -> int:
    counts = live_package_counts()
    stale: list[str] = []
    for name in DOC_FILES:
        canonical = DOCS_DIR / name
        if not canonical.is_file():
            continue
        original = canonical.read_text(encoding="utf-8")
        updated = _rewrite(original, counts)
        mirror = MIRROR_DIR / name
        mirror_original = mirror.read_text(encoding="utf-8") if mirror.is_file() else None
        if updated != original or mirror_original != updated:
            stale.append(name)
            if not check:
                canonical.write_text(updated, encoding="utf-8")
                if mirror.parent.is_dir():
                    mirror.write_text(updated, encoding="utf-8")
    counts_str = ", ".join(f"{k}={v}" for k, v in counts.items())
    if check:
        if stale:
            print(f"STALE doc counts ({counts_str}): {', '.join(stale)}", file=sys.stderr)
            print("Fix: python scripts/regenerate_doc_counts.py", file=sys.stderr)
            return 1
        print(f"doc counts up to date ({counts_str})")
        return 0
    print(f"Live counts: {counts_str}")
    print(f"Updated {len(stale)} file(s): {', '.join(stale) or '(none — already current)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if any file is stale")
    args = parser.parse_args()
    return apply(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
