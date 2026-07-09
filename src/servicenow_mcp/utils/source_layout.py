"""Single source of truth for on-disk source-file naming.

Both downloaders (``source_tools`` generic table dump, ``portal_tools`` portal
enrichment) and the uploader (``sync_tools``) must speak the SAME on-disk
language: a folder per record, one file per source field —

    <table>/<name>/<field><ext>     e.g. sp_angular_provider/mySvc/script.js

Types whose name is unique only within a parent (``folder_qualifier_field`` in
SOURCE_CONFIG — business rules, notifications, scripted REST operations) nest one
level deeper, ``<table>/<qualifier>/<name>/<field><ext>``. Depth is therefore NOT
part of the contract: a reader resolves a record's table from its _metadata.json,
never by counting directories up from the file.

Historically each module hardcoded its own filenames, so the two download paths
drifted: providers were written flat by one and as a folder by the other, and
``client_script``/``processing_script`` got different extensions on each side.
Defining the field→filename map ONCE here makes every reader/writer agree by
construction; a contract test pins it so a future edit cannot silently re-drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

# Written by the dependency resolver at the scope root; lists the sibling scope
# namespaces that hold this scope's routed dependencies.
DEP_SCOPES_FILE = "_dep_scopes.json"

# Canonical on-disk filename for each source field, in the folder layout
# ``<table>/<name>/<filename>``. The filename always begins with the field
# name so the extension can be derived mechanically (see ``field_extension``).
FIELD_FILENAME: Dict[str, str] = {
    "script": "script.js",
    "client_script": "client_script.js",
    "condition": "condition.js",
    "operation_script": "operation_script.js",
    "processing_script": "processing_script.js",
    "link": "link.js",
    "template": "template.html",
    "html": "html.html",
    "message_html": "message_html.html",
    "css": "css.scss",
    "xml": "xml.xml",
    "payload": "payload.xml",
    "message_text": "message_text.txt",
    "subject": "subject.txt",
}

# Fallback for any field not in the canonical map.
DEFAULT_FILENAME_EXT = ".txt"


def normalize_source_eol(text: str) -> str:
    """Canonicalize line endings to LF for downloaded source bodies.

    ServiceNow stores the same logical script with different EOLs across instances
    (CRLF on one, LF on another, depending on the UI / update-set / API edit path).
    Written verbatim, an identical script then shows as a whole-file change under
    any byte/line diff (git, raw ``diff``, editors) — pure EOL noise that buries the
    real differences in cross-instance comparison. Normalizing to LF on write makes
    the local copy canonical so every comparison method is clean. Safe for the push
    round-trip: ServiceNow normalizes EOLs on store and the uploader already treats
    a pure CRLF<->LF delta as no change, so a normalized body is never a phantom push.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def field_filename(field: str) -> str:
    """Canonical on-disk filename for *field* (folder layout)."""
    return FIELD_FILENAME.get(field, f"{field}{DEFAULT_FILENAME_EXT}")


def dep_scope_roots(scope_root: Path) -> List[Path]:
    """Sibling scope trees that hold this scope's routed dependencies.

    The dependency resolver routes a dep to its OWN scope tree (a global SI lands
    in the sibling ``global/`` tree, not under the app that pulled it) and records
    the sibling namespaces in ``<scope_root>/_dep_scopes.json``. Audit and schema
    scans read this so they cover exactly those dep trees — not every unrelated app
    under ``temp/<instance>``. Returns existing sibling roots only (never the scope
    itself), so callers can scan ``[scope_root, *dep_scope_roots(scope_root)]``.
    """
    manifest = scope_root / DEP_SCOPES_FILE
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    base = scope_root.parent
    roots: List[Path] = []
    for ns in data.get("dep_scopes", []) if isinstance(data, dict) else []:
        cand = base / str(ns)
        if cand.is_dir() and cand != scope_root:
            roots.append(cand)
    return roots


def field_extension(field: str) -> str:
    """Extension portion of the canonical filename (the part after the field name).

    ``script`` → ``.js``; ``css`` → ``.scss``; unknown field → ``.txt``.
    Lets callers that build ``f"{field}{ext}"`` stay byte-identical to
    ``field_filename`` without duplicating the table.
    """
    filename = FIELD_FILENAME.get(field)
    if not filename:
        return DEFAULT_FILENAME_EXT
    return filename[len(field) :]
