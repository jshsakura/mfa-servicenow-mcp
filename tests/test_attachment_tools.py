"""Tests for the download_attachment tool.

Covers both resolution modes (explicit attachment sys_id, parent table+record),
the multi-attachment list-vs-download-all branch, the size cap, the scope/owner
consistency guard, the JSON-instead-of-file defensive guard, and filename
sanitization.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.attachment_tools import (
    DownloadAttachmentParams,
    _safe_attachment_name,
    download_attachment,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth() -> MagicMock:
    return MagicMock()


class FakeResp:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = content.decode("latin-1") if isinstance(content, bytes) else str(content)

    def json(self):
        return {}


def _meta(
    sys_id="att-1",
    name="report.pdf",
    ctype="application/pdf",
    size=10,
    table="incident",
    table_sys_id="rec-1",
):
    return {
        "sys_id": sys_id,
        "file_name": name,
        "content_type": ctype,
        "size_bytes": str(size),
        "table_name": table,
        "table_sys_id": table_sys_id,
    }


def _params(tmp_path, **over):
    base = dict(output_dir=str(tmp_path))
    base.update(over)
    return DownloadAttachmentParams(**base)


def _patch_query(side_effect):
    return patch("servicenow_mcp.tools.attachment_tools.sn_query_page", side_effect=side_effect)


# ---------------------------------------------------------------------------
# Mode A: explicit attachment sys_id
# ---------------------------------------------------------------------------


def test_download_by_sys_id_writes_file_and_returns_summary(config, auth, tmp_path):
    def fake_query(*args, **kwargs):
        assert kwargs["table"] == "sys_attachment"
        return [_meta()], 1

    auth.make_request.return_value = FakeResp(
        200, b"%PDF-1.7 data", {"Content-Type": "application/pdf"}
    )
    with _patch_query(fake_query):
        result = download_attachment(config, auth, _params(tmp_path, attachment_sys_id="att-1"))

    assert result["success"] is True
    saved = Path(result["saved_path"])
    assert saved.exists()
    assert saved.read_bytes() == b"%PDF-1.7 data"
    assert result["file_name"] == "report.pdf"
    assert result["size_bytes"] == len(b"%PDF-1.7 data")
    assert result["table_name"] == "incident"
    # The /file endpoint was hit, not the table API for the bytes.
    assert auth.make_request.call_args[0][1].endswith("/api/now/attachment/att-1/file")


def test_download_by_sys_id_not_found(config, auth, tmp_path):
    with _patch_query(lambda *a, **k: ([], 0)):
        result = download_attachment(config, auth, _params(tmp_path, attachment_sys_id="missing"))
    assert result["success"] is False
    assert "missing" in result["message"]


def test_scope_guard_refuses_wrong_table(config, auth, tmp_path):
    """If the caller names a parent table that doesn't own the attachment, refuse."""
    with _patch_query(lambda *a, **k: ([_meta(table="incident")], 1)):
        result = download_attachment(
            config, auth, _params(tmp_path, attachment_sys_id="att-1", table="change_request")
        )
    assert result["success"] is False
    assert "incident" in result["message"]
    auth.make_request.assert_not_called()


def test_size_cap_refuses_large_file(config, auth, tmp_path):
    with _patch_query(lambda *a, **k: ([_meta(size=5 * 1024 * 1024)], 1)):
        result = download_attachment(
            config, auth, _params(tmp_path, attachment_sys_id="att-1", max_size_mb=1)
        )
    assert result["success"] is False
    assert "over the cap" in result["message"]
    auth.make_request.assert_not_called()


def test_json_response_treated_as_error_not_file(config, auth, tmp_path):
    auth.make_request.return_value = FakeResp(
        200, b'{"error":{"message":"boom"}}', {"Content-Type": "application/json"}
    )
    with _patch_query(lambda *a, **k: ([_meta(ctype="application/pdf")], 1)):
        result = download_attachment(config, auth, _params(tmp_path, attachment_sys_id="att-1"))
    assert result["success"] is False
    assert "JSON" in result["message"]


def test_filename_override_is_sanitized(config, auth, tmp_path):
    auth.make_request.return_value = FakeResp(200, b"data", {"Content-Type": "application/pdf"})
    with _patch_query(lambda *a, **k: ([_meta()], 1)):
        result = download_attachment(
            config,
            auth,
            _params(tmp_path, attachment_sys_id="att-1", filename="../../etc/evil"),
        )
    assert result["success"] is True
    saved = Path(result["saved_path"])
    # No traversal — the file lands inside the output dir.
    assert saved.parent == tmp_path
    assert saved.name == "evil"


# ---------------------------------------------------------------------------
# Mode B: parent table + record
# ---------------------------------------------------------------------------


def test_resolve_by_record_number_single_attachment(config, auth, tmp_path):
    def fake_query(*args, **kwargs):
        if kwargs["table"] == "incident":  # number → sys_id resolution
            assert "number=INC0010023" in kwargs["query"]
            return [{"sys_id": "rec-1", "number": "INC0010023"}], 1
        # sys_attachment listing for the record
        assert "table_sys_id=rec-1" in kwargs["query"]
        return [_meta()], 1

    auth.make_request.return_value = FakeResp(200, b"data", {"Content-Type": "application/pdf"})
    with _patch_query(fake_query):
        result = download_attachment(
            config, auth, _params(tmp_path, table="incident", record="INC0010023")
        )
    assert result["success"] is True
    assert result["downloaded"] == 1
    assert result["record_sys_id"] == "rec-1"


def test_multiple_attachments_lists_without_downloading(config, auth, tmp_path):
    def fake_query(*args, **kwargs):
        if kwargs["table"] == "sys_attachment":
            return [_meta(sys_id="a1", name="one.pdf"), _meta(sys_id="a2", name="two.xlsx")], 2
        return [], 0

    with _patch_query(fake_query):
        result = download_attachment(
            config, auth, _params(tmp_path, table="incident", record="a" * 32)
        )
    assert result["success"] is True
    assert result["downloaded"] == 0
    assert result["multiple"] is True
    assert {a["file_name"] for a in result["attachments"]} == {"one.pdf", "two.xlsx"}
    auth.make_request.assert_not_called()


def test_multiple_attachments_download_all(config, auth, tmp_path):
    def fake_query(*args, **kwargs):
        if kwargs["table"] == "sys_attachment":
            return [_meta(sys_id="a1", name="one.pdf"), _meta(sys_id="a2", name="two.xlsx")], 2
        return [], 0

    auth.make_request.return_value = FakeResp(200, b"data", {"Content-Type": "application/pdf"})
    with _patch_query(fake_query):
        result = download_attachment(
            config,
            auth,
            _params(tmp_path, table="incident", record="a" * 32, download_all=True),
        )
    assert result["success"] is True
    assert result["downloaded"] == 2
    assert auth.make_request.call_count == 2


def test_record_number_unresolved(config, auth, tmp_path):
    with _patch_query(lambda *a, **k: ([], 0)):
        result = download_attachment(
            config, auth, _params(tmp_path, table="incident", record="INC9999999")
        )
    assert result["success"] is False
    assert "INC9999999" in result["message"]


def test_no_attachments_on_record(config, auth, tmp_path):
    def fake_query(*args, **kwargs):
        if kwargs["table"] == "sys_attachment":
            return [], 0
        return [{"sys_id": "rec-1", "number": "INC0010023"}], 1

    with _patch_query(fake_query):
        result = download_attachment(
            config, auth, _params(tmp_path, table="incident", record="rec-1")
        )
    assert result["success"] is True
    assert result["downloaded"] == 0
    assert "No attachments" in result["message"]


def test_no_args_returns_error(config, auth, tmp_path):
    result = download_attachment(config, auth, _params(tmp_path))
    assert result["success"] is False
    assert "attachment_sys_id" in result["message"]


# ---------------------------------------------------------------------------
# Unit: filename sanitizer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("a/b/c.txt", "c.txt"),
        ("weird:name?.xlsx", "weird_name_.xlsx"),
        ("", "fallback"),
        ("   ", "fallback"),
    ],
)
def test_safe_attachment_name(raw, expected):
    assert _safe_attachment_name(raw, "fallback") == expected
