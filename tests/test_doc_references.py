"""Every code reference in the docs resolves.

The catalog guide (six languages) documented functions, Params classes, three
`catalog://` resources and two example scripts that had all been deleted. Each
was a promise a reader could act on and fail at. These tests make a deleted
symbol fail the build until the doc that names it is fixed.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = sorted(
    p
    for p in [*REPO.glob("docs/**/*.md"), *REPO.glob("README*.md")]
    if "node_modules" not in p.parts
)

_IMPORT = re.compile(r"from (servicenow_mcp[\w.]*) import \(?([\w, \n]+?)\)?\n")
_EXAMPLE = re.compile(r"\bexamples/[\w./-]+\.py\b")
_RESOURCE_URI = re.compile(r"`(catalog|changeset|script_include)://[^`]*`")


def _ids(paths):
    return [str(p.relative_to(REPO)) for p in paths]


@pytest.mark.parametrize("doc", DOCS, ids=_ids(DOCS))
def test_documented_imports_exist(doc):
    missing = []
    for match in _IMPORT.finditer(doc.read_text(encoding="utf-8")):
        module_name = match.group(1)
        names = [n.strip() for n in match.group(2).replace("\n", " ").split(",") if n.strip()]
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            missing.append(module_name)
            continue
        missing += [f"{module_name}.{n}" for n in names if not hasattr(module, n)]
    assert missing == [], f"{doc.name} documents symbols that do not exist: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=_ids(DOCS))
def test_documented_example_scripts_exist(doc):
    text = doc.read_text(encoding="utf-8")
    missing = sorted({m for m in _EXAMPLE.findall(text) if not (REPO / m).exists()})
    assert missing == [], f"{doc.name} points at scripts that do not exist: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=_ids(DOCS))
def test_no_retired_resource_uris(doc):
    # The catalog/changeset/script_include MCP resources were removed; only
    # attachments and skills are served as resources now.
    found = _RESOURCE_URI.findall(doc.read_text(encoding="utf-8"))
    assert found == [], f"{doc.name} documents removed MCP resources: {found}"
