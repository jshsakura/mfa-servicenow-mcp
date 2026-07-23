"""Atomic local file write guarantees."""

from pathlib import Path
from unittest.mock import patch

import pytest

from servicenow_mcp.utils.atomic_io import atomic_write_text


def test_writes_content(tmp_path):
    target = tmp_path / "sub" / "file.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_creates_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "c.txt"
    atomic_write_text(target, "x")
    assert target.exists()


def test_overwrites_completely(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_text(target, "original-long-content")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_lf_is_not_re_expanded_to_crlf(tmp_path):
    # newline="" must stop text mode from rewriting \n -> os.linesep on write, so
    # an LF-normalized body stays LF on disk on every OS (regression: on Windows,
    # newline=None re-expanded to CRLF and defeated normalize_source_eol).
    target = tmp_path / "body.js"
    atomic_write_text(target, "a\nb\nc\n")
    assert target.read_bytes() == b"a\nb\nc\n"
    assert b"\r" not in target.read_bytes()


def test_content_written_byte_for_byte(tmp_path):
    # No newline translation in either direction: mixed EOLs land verbatim.
    target = tmp_path / "mixed.txt"
    atomic_write_text(target, "a\nb\r\nc")
    assert target.read_bytes() == b"a\nb\r\nc"


def test_no_temp_file_left_after_success(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_text(target, "data")
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_failed_write_leaves_original_intact_and_no_temp(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_text(target, "good")

    # Simulate a crash during the replace step (after the temp file is written).
    with patch("servicenow_mcp.utils.atomic_io.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            atomic_write_text(target, "would-be-corrupt")

    # Original is untouched (never truncated) and the temp file was cleaned up.
    assert target.read_text(encoding="utf-8") == "good"
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_replace_is_used_not_inplace_write(tmp_path):
    """The whole point: writes go through os.replace, never an in-place truncate."""
    target = tmp_path / "f.txt"
    with patch("servicenow_mcp.utils.atomic_io.os.replace") as mock_replace:
        atomic_write_text(target, "data")
        assert mock_replace.call_count == 1
        # Second arg of os.replace is the final destination.
        dest = mock_replace.call_args[0][1]
        assert Path(dest) == target
