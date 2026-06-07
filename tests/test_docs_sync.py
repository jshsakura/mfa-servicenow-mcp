"""Guard against docs/ ↔ website/docs/docs/ drift.

The website mirrors the canonical docs/ tree. They used to drift silently —
conflicting tool counts and stale setup steps depending on which copy a user (or
LLM) happened to read. docs/ is the single source of truth; this test fails if a
mirrored file diverges so the website copy is updated in the same change.

To resync after an intentional docs/ edit:
    cp docs/<file>.md website/docs/docs/<file>.md
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
WEBSITE_DIR = ROOT / "website" / "docs" / "docs"

# Every markdown file the website mirrors from docs/. Discovered from the
# website tree so a new mirrored page is covered automatically.
_MIRRORED = sorted(p.name for p in WEBSITE_DIR.glob("*.md")) if WEBSITE_DIR.is_dir() else []


@pytest.mark.parametrize("name", _MIRRORED)
def test_website_doc_matches_canonical(name):
    canonical = DOCS_DIR / name
    mirror = WEBSITE_DIR / name
    assert canonical.is_file(), (
        f"website/docs/docs/{name} has no docs/ source. Either add docs/{name} "
        f"(canonical) or remove the website mirror."
    )
    assert canonical.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8"), (
        f"website/docs/docs/{name} drifted from docs/{name}. docs/ is canonical — "
        f"resync with: cp docs/{name} website/docs/docs/{name}"
    )


def test_mirror_set_is_non_empty():
    # Guards against the glob silently finding nothing (e.g. path moved).
    assert _MIRRORED, "No mirrored docs found under website/docs/docs/"
