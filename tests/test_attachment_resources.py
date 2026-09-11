"""Tests for pull-based resources backed by downloaded attachments."""

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from servicenow_mcp.resources.attachment_resources import (
    ATTACHMENT_RESOURCE_MAX_MB_ENV,
    DEFAULT_ATTACHMENT_RESOURCE_MAX_BYTES,
    HARD_MAX_ATTACHMENT_RESOURCE_MAX_MB,
    AttachmentResourceError,
    AttachmentResourceStore,
    AttachmentResourceTooLarge,
    get_attachment_resource_max_bytes,
)
from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class MutableClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def _config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


def _server(tool_defs):
    with (
        patch("servicenow_mcp.server.AuthManager"),
        patch("servicenow_mcp.server.get_tool_definitions", return_value=tool_defs),
        patch("servicenow_mcp.server.load_skills", return_value=[]),
        patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={}),
    ):
        server = ServiceNowMCP(_config())
    server.tool_definitions = tool_defs
    server.enabled_tool_names = list(tool_defs)
    server.current_package_name = "standard"
    return server


def test_store_round_trip_uses_opaque_uri(tmp_path):
    path = _write(tmp_path / "report.pdf", b"pdf bytes")
    store = AttachmentResourceStore(max_bytes=100)

    entry = store.register(path, file_name="report.pdf", mime_type="application/pdf")
    returned, content = store.read(entry.uri)

    assert content == b"pdf bytes"
    assert returned == entry
    assert str(path) not in entry.uri
    assert "report.pdf" not in entry.uri


def test_resource_limit_defaults_to_ten_mib():
    with patch.dict("os.environ", {}, clear=True):
        assert get_attachment_resource_max_bytes() == DEFAULT_ATTACHMENT_RESOURCE_MAX_BYTES
        assert AttachmentResourceStore().max_bytes == 10 * 1024 * 1024


def test_resource_limit_uses_operator_environment_setting():
    with patch.dict("os.environ", {ATTACHMENT_RESOURCE_MAX_MB_ENV: "3"}, clear=True):
        assert AttachmentResourceStore().max_bytes == 3 * 1024 * 1024


@pytest.mark.parametrize("configured", ["not-a-number", "0", "-1"])
def test_invalid_resource_limit_falls_back_to_default(configured):
    with patch.dict("os.environ", {ATTACHMENT_RESOURCE_MAX_MB_ENV: configured}, clear=True):
        assert get_attachment_resource_max_bytes() == DEFAULT_ATTACHMENT_RESOURCE_MAX_BYTES


def test_resource_limit_is_clamped_to_hard_maximum():
    with patch.dict("os.environ", {ATTACHMENT_RESOURCE_MAX_MB_ENV: "999"}, clear=True):
        assert get_attachment_resource_max_bytes() == (
            HARD_MAX_ATTACHMENT_RESOURCE_MAX_MB * 1024 * 1024
        )


def test_store_rejects_file_over_limit(tmp_path):
    path = _write(tmp_path / "large.bin", b"12345")
    store = AttachmentResourceStore(max_bytes=4)

    with pytest.raises(AttachmentResourceTooLarge, match="resource limit"):
        store.register(path, file_name="large.bin", mime_type=None)


def test_store_expires_link(tmp_path):
    clock = MutableClock()
    store = AttachmentResourceStore(max_bytes=100, ttl_seconds=10, clock=clock)
    entry = store.register(
        _write(tmp_path / "data.txt", b"data"), file_name="data.txt", mime_type="text/plain"
    )

    clock.now += 10
    with pytest.raises(AttachmentResourceError, match="expired"):
        store.read(entry.uri)
    assert len(store) == 0


def test_store_evicts_oldest_entry(tmp_path):
    store = AttachmentResourceStore(max_bytes=100, max_entries=2)
    first = store.register(
        _write(tmp_path / "one.txt", b"1"), file_name="one.txt", mime_type="text/plain"
    )
    second = store.register(
        _write(tmp_path / "two.txt", b"2"), file_name="two.txt", mime_type="text/plain"
    )
    third = store.register(
        _write(tmp_path / "three.txt", b"3"), file_name="three.txt", mime_type="text/plain"
    )

    with pytest.raises(AttachmentResourceError, match="not found or expired"):
        store.read(first.uri)
    assert store.read(second.uri)[1] == b"2"
    assert store.read(third.uri)[1] == b"3"


def test_store_rejects_modified_or_deleted_file(tmp_path):
    store = AttachmentResourceStore(max_bytes=100)
    changed_path = _write(tmp_path / "changed.txt", b"before")
    changed = store.register(changed_path, file_name="changed.txt", mime_type="text/plain")
    changed_path.write_bytes(b"after!")

    with pytest.raises(AttachmentResourceError, match="changed"):
        store.read(changed.uri)
    with pytest.raises(AttachmentResourceError, match="not found or expired"):
        store.read(changed.uri)

    deleted_path = _write(tmp_path / "deleted.txt", b"data")
    deleted = store.register(deleted_path, file_name="deleted.txt", mime_type="text/plain")
    deleted_path.unlink()
    with pytest.raises(AttachmentResourceError, match="no longer available"):
        store.read(deleted.uri)


def test_store_rejects_symlink(tmp_path):
    target = _write(tmp_path / "target.txt", b"secret")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    store = AttachmentResourceStore(max_bytes=100)
    with pytest.raises(AttachmentResourceError, match="symlink"):
        store.register(link, file_name="link.txt", mime_type="text/plain")


@pytest.mark.parametrize(
    "uri",
    [
        "servicenow-attachment://other/abcdefghijklmnopqrstuvwxyz123456",
        "servicenow-attachment://resource/short",
        "servicenow-attachment://resource/abcdefghijklmnopqrstuvwxyz123456?x=1",
    ],
)
def test_store_rejects_invalid_uri(tmp_path, uri):
    store = AttachmentResourceStore(max_bytes=100)
    with pytest.raises(AttachmentResourceError, match="Invalid"):
        store.read(uri)


def test_download_result_returns_link_then_reads_blob(tmp_path):
    class Params(BaseModel):
        pass

    path = _write(tmp_path / "report.pdf", b"%PDF exact downloaded bytes")

    def impl(config, auth, params):
        return {
            "success": True,
            "sys_id": "a" * 32,
            "saved_path": str(path),
            "file_name": "report.pdf",
            "content_type": "application/pdf",
            "size_bytes": path.stat().st_size,
        }

    server = _server(
        {"download_attachment": (impl, Params, dict, "Download attachment", "raw_dict")}
    )

    async def check():
        result = await server._call_tool_impl("download_attachment", {})
        assert len(result) == 2
        payload = json.loads(result[0].text)
        assert "content_base64" not in payload
        assert payload["resource_available"] is True
        assert payload["resource_uri"] == str(result[1].uri)
        assert payload["resource_next_action"].endswith("resources/read.")
        assert result[1].type == "resource_link"
        assert result[1].size == path.stat().st_size

        resource = await server._read_resource_impl(result[1].uri)
        assert len(resource) == 1
        assert resource[0].mimeType == "application/pdf"
        assert base64.b64decode(resource[0].blob) == path.read_bytes()
        server.auth_manager.make_request.assert_not_called()

    asyncio.run(check())


def test_download_all_returns_one_link_per_successful_file(tmp_path):
    class Params(BaseModel):
        pass

    one = _write(tmp_path / "one.txt", b"one")
    two = _write(tmp_path / "two.txt", b"two")

    def impl(config, auth, params):
        return {
            "success": True,
            "downloaded": 2,
            "files": [
                {
                    "success": True,
                    "saved_path": str(one),
                    "file_name": "one.txt",
                    "content_type": "text/plain",
                    "size_bytes": 3,
                },
                {"success": False, "file_name": "failed.txt"},
                {
                    "success": True,
                    "saved_path": str(two),
                    "file_name": "two.txt",
                    "content_type": "text/plain",
                    "size_bytes": 3,
                },
            ],
        }

    server = _server(
        {"download_attachment": (impl, Params, dict, "Download attachment", "raw_dict")}
    )

    async def check():
        result = await server._call_tool_impl("download_attachment", {})
        assert len(result) == 3
        payload = json.loads(result[0].text)
        assert payload["files"][0]["resource_available"] is True
        assert "resource_available" not in payload["files"][1]
        assert payload["files"][2]["resource_available"] is True

    asyncio.run(check())


def test_over_limit_download_still_returns_saved_path_without_link(tmp_path):
    class Params(BaseModel):
        pass

    path = _write(tmp_path / "large.bin", b"12345")

    def impl(config, auth, params):
        return {
            "success": True,
            "saved_path": str(path),
            "file_name": "large.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 5,
        }

    server = _server(
        {"download_attachment": (impl, Params, dict, "Download attachment", "raw_dict")}
    )
    server._attachment_resources = AttachmentResourceStore(max_bytes=4)

    async def check():
        result = await server._call_tool_impl("download_attachment", {})
        assert len(result) == 1
        payload = json.loads(result[0].text)
        assert payload["success"] is True
        assert payload["saved_path"] == str(path)
        assert payload["resource_available"] is False
        assert "resource limit" in payload["resource_unavailable_reason"]
        assert str(path) in payload["resource_unavailable_reason"]
        assert payload["resource_next_action"].startswith("Use saved_path")

    asyncio.run(check())


def test_resource_read_cannot_bypass_disabled_tool_package(tmp_path):
    server = _server({})
    entry = server._attachment_resources.register(
        _write(tmp_path / "data.txt", b"data"), file_name="data.txt", mime_type="text/plain"
    )
    server.enabled_tool_names = []

    async def check():
        with pytest.raises(ValueError, match="disabled"):
            await server._read_resource_impl(entry.uri)

    asyncio.run(check())
