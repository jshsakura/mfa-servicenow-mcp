"""Contract: downloaders and the uploader speak ONE on-disk language.

The download path used to fork — providers were written flat by one downloader
and as a folder by the other, with client_script/processing_script getting
different extensions on each side — so a downloaded tree could not be pushed
back without per-case fixups. These tests pin every filename to the single
source of truth in source_layout so a future edit cannot silently re-drift.
"""

from servicenow_mcp.tools.source_tools import _FIELD_EXTENSIONS
from servicenow_mcp.tools.sync_tools import SINGLE_FILE_FOLDER_FIELD_MAP, WIDGET_FILE_FIELD_MAP
from servicenow_mcp.utils.source_layout import FIELD_FILENAME, field_extension, field_filename

# Filenames the uploader still accepts only for trees downloaded by older
# versions (before canonicalization). Not part of the forward contract.
_LEGACY_FILENAMES = {"client_script.client.js"}


def test_generic_downloader_filenames_match_canonical():
    """source_tools builds files as f"{field}{ext}" — that must equal the
    canonical filename for every field, or the uploader can't find them."""
    for field, ext in _FIELD_EXTENSIONS.items():
        assert f"{field}{ext}" == field_filename(field), field


def test_field_extension_is_suffix_of_filename():
    for field, filename in FIELD_FILENAME.items():
        assert filename == f"{field}{field_extension(field)}"


def test_uploader_widget_filenames_are_canonical():
    """Every widget file the uploader reads is a canonical filename."""
    canonical = set(FIELD_FILENAME.values())
    for filename in WIDGET_FILE_FIELD_MAP:
        assert filename in canonical, filename


def test_uploader_folder_filenames_are_canonical_or_legacy():
    canonical = set(FIELD_FILENAME.values())
    for table, file_map in SINGLE_FILE_FOLDER_FIELD_MAP.items():
        for filename, field in file_map.items():
            assert filename in canonical or filename in _LEGACY_FILENAMES, (table, filename)
            # When canonical, the filename must map to the field it claims.
            if filename in canonical:
                assert field_filename(field) == filename, (table, field)


def test_historical_drift_is_eliminated():
    """The two specific extensions that used to disagree are now canonical."""
    assert field_filename("client_script") == "client_script.js"
    assert field_filename("processing_script") == "processing_script.js"
    assert field_filename("script") == "script.js"
