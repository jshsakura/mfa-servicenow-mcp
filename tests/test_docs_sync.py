"""Guard against docs/ <-> website Starlight-mirror drift.

The website mirrors the canonical docs/ tree, transformed into Starlight pages
(frontmatter added, leading H1 stripped, the one mkdocs admonition converted —
see ``regenerate_doc_counts.wrap_for_starlight``). Mirrors used to drift
silently — conflicting tool counts and stale setup steps depending on which
copy a user (or LLM) happened to read. docs/ is the single source of truth;
this test fails if a mirrored file diverges from ``wrap_for_starlight(docs/...)``
so the website copy is updated in the same change.

To resync after an intentional docs/ edit:
    python scripts/regenerate_doc_counts.py
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

# Cosmetic mirror-sync — never gate the PyPI deploy on it (see the `docs` marker
# note in pyproject.toml). CI runs these in a separate non-blocking job.
pytestmark = pytest.mark.docs

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
SITE_CONTENT_DIR = ROOT / "website" / "src" / "content" / "docs"
SCRIPT_PATH = ROOT / "scripts" / "regenerate_doc_counts.py"


def _load_generator():
    spec = spec_from_file_location("regenerate_doc_counts", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load generator from {SCRIPT_PATH}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_gen = _load_generator()

# (base, lang_suffix) for every mirror actually present on disk — discovered,
# not assumed, so a new mirrored page or locale is covered automatically.
_MIRRORED = [
    (base, lang)
    for base in _gen.MIRRORED_PAGES
    for lang in _gen.LANGS
    if (SITE_CONTENT_DIR / _gen.LOCALE_DIR[lang] / f"{base}.md").is_file()
]


@pytest.mark.parametrize(
    "base,lang", _MIRRORED, ids=[f"{base}{lang or ''}" for base, lang in _MIRRORED]
)
def test_website_doc_matches_canonical(base, lang):
    gen = _load_generator()
    canonical = DOCS_DIR / f"{base}{lang}.md"
    mirror = SITE_CONTENT_DIR / gen.LOCALE_DIR[lang] / f"{base}.md"
    assert canonical.is_file(), (
        f"{mirror.relative_to(ROOT)} has no docs/{base}{lang}.md source. Either "
        f"add docs/{base}{lang}.md (canonical) or remove the website mirror."
    )
    expected = gen.wrap_for_starlight(
        base, canonical.read_text(encoding="utf-8"), gen.LOCALE_DIR[lang]
    )
    assert mirror.read_text(encoding="utf-8") == expected, (
        f"{mirror.relative_to(ROOT)} drifted from docs/{base}{lang}.md. docs/ is "
        f"canonical — resync with: python scripts/regenerate_doc_counts.py"
    )


def test_mirror_set_is_non_empty():
    # Guards against discovery silently finding nothing (e.g. path moved).
    assert _MIRRORED, "No mirrored docs found under website/src/content/docs/"
