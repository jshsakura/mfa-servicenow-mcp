"""Single source of truth for on-disk source-file naming.

Both downloaders (``source_tools`` generic table dump, ``portal_tools`` portal
enrichment) and the uploader (``sync_tools``) must speak the SAME on-disk
language: a folder per record, one file per source field —

    <table>/<name>/<field><ext>     e.g. sp_angular_provider/mySvc/script.js

Historically each module hardcoded its own filenames, so the two download paths
drifted: providers were written flat by one and as a folder by the other, and
``client_script``/``processing_script`` got different extensions on each side.
Defining the field→filename map ONCE here makes every reader/writer agree by
construction; a contract test pins it so a future edit cannot silently re-drift.
"""

from __future__ import annotations

from typing import Dict

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
}

# Fallback for any field not in the canonical map.
DEFAULT_FILENAME_EXT = ".txt"


def field_filename(field: str) -> str:
    """Canonical on-disk filename for *field* (folder layout)."""
    return FIELD_FILENAME.get(field, f"{field}{DEFAULT_FILENAME_EXT}")


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
