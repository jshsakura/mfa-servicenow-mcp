"""Tests for the export_record_xml tool.

Covers the payload -> <unload> transform, the correctness-critical no-double-
unescape rule, missing-record reporting, name/sys_id validation, the
HTML-login guard, and output_path vs default-dir placement. The live network
path is mocked: make_request returns a hand-built sys_update_version XML dump.
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock
from xml.sax.saxutils import escape

import pytest

from servicenow_mcp.tools.xml_export_tools import (
    ExportRecordXmlParams,
    _payload_to_inner,
    export_record_xml,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


class FakeResp:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


def _payload(table: str, action_body: str) -> str:
    """A realistic sys_update_version payload (an XML doc as a string)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<record_update table="{table}">'
        f'<{table} action="INSERT_OR_UPDATE">{action_body}</{table}>'
        "</record_update>"
    )


def _version_dump(rows: list[tuple[str, str]]) -> bytes:
    """Build the <xml> response the .do?XML endpoint returns: each row's payload
    is XML-escaped once, exactly as ServiceNow serializes it."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<xml>"]
    for name, payload in rows:
        parts.append(
            "<sys_update_version>"
            f"<name>{name}</name>"
            "<state>current</state>"
            f"<payload>{escape(payload)}</payload>"
            "</sys_update_version>"
        )
    parts.append("</xml>")
    return "".join(parts).encode("utf-8")


def _auth(dump: bytes, status=200, headers=None) -> MagicMock:
    auth = MagicMock()
    auth.make_request.return_value = FakeResp(status, dump, headers)
    return auth


SID = "0d90cdb53b6f321046a3934a85e45a1d"


# --- happy path -----------------------------------------------------------


def test_single_record_writes_importable_unload(config, tmp_path):
    dump = _version_dump([(f"sp_widget_{SID}", _payload("sp_widget", "<id>w1</id>"))])
    out = tmp_path / "w.xml"
    res = export_record_xml(
        config,
        _auth(dump),
        ExportRecordXmlParams(table="sp_widget", sys_ids=[SID], output_path=str(out)),
    )
    assert res["success"] and res["record_count"] == 1
    assert res["saved_path"] == str(out)
    root = ET.parse(out).getroot()
    assert root.tag == "unload"
    assert [c.tag for c in root] == ["sp_widget"]
    assert root[0].get("action") == "INSERT_OR_UPDATE"


def test_multi_table_single_file_preserves_order(config, tmp_path):
    n1, n2 = f"sp_widget_{SID}", "sys_script_" + "a" * 32
    dump = _version_dump(
        [
            (n2, _payload("sys_script", "<name>BR</name>")),  # returned out of order
            (n1, _payload("sp_widget", "<id>w1</id>")),
        ]
    )
    res = export_record_xml(
        config,
        _auth(dump),
        ExportRecordXmlParams(names=[n1, n2], output_dir=str(tmp_path)),
    )
    assert res["success"] and res["record_count"] == 2
    root = ET.parse(res["saved_path"]).getroot()
    # Output follows requested order (n1 then n2), not response order.
    assert [c.tag for c in root] == ["sp_widget", "sys_script"]


def test_default_path_uses_temp_dir(config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dump = _version_dump([(f"sp_widget_{SID}", _payload("sp_widget", "<id>w1</id>"))])
    res = export_record_xml(
        config, _auth(dump), ExportRecordXmlParams(table="sp_widget", sys_ids=[SID])
    )
    assert res["success"]
    assert "/temp/test/xml/" in res["saved_path"].replace("\\", "/")


# --- correctness: no double unescape --------------------------------------


def test_payload_with_literal_entity_is_not_double_unescaped(config, tmp_path):
    # A field value that legitimately contains the text "&lt;b&gt;" — after the
    # response is decoded once, payload.text holds "&lt;b&gt;". A second unescape
    # would corrupt it into "<b>". The written file must preserve "&lt;b&gt;".
    body = "<title>&lt;b&gt;</title>"
    dump = _version_dump([(f"sp_widget_{SID}", _payload("sp_widget", body))])
    out = tmp_path / "e.xml"
    res = export_record_xml(
        config,
        _auth(dump),
        ExportRecordXmlParams(table="sp_widget", sys_ids=[SID], output_path=str(out)),
    )
    assert res["success"]
    title = ET.parse(out).getroot()[0].find("title").text
    assert title == "<b>"  # the ORIGINAL field text, intact (not "b")


# --- missing / empty ------------------------------------------------------


def test_missing_record_reported_not_silently_dropped(config, tmp_path):
    dump = _version_dump([(f"sp_widget_{SID}", _payload("sp_widget", "<id>w1</id>"))])
    other = "sp_widget_" + "b" * 32
    res = export_record_xml(
        config,
        _auth(dump),
        ExportRecordXmlParams(
            table="sp_widget", sys_ids=[SID, "b" * 32], output_path=str(tmp_path / "m.xml")
        ),
    )
    assert res["success"] and res["record_count"] == 1
    assert other in res["missing"]
    assert "warning" in res


def test_no_current_version_fails_clearly(config, tmp_path):
    res = export_record_xml(
        config,
        _auth(_version_dump([])),
        ExportRecordXmlParams(table="sp_widget", sys_ids=[SID]),
    )
    assert res["success"] is False
    assert res["missing"] == [f"sp_widget_{SID}"]


# --- validation -----------------------------------------------------------


def test_requires_something_to_export(config):
    res = export_record_xml(config, MagicMock(), ExportRecordXmlParams())
    assert res["success"] is False


def test_bad_sys_id_rejected(config):
    res = export_record_xml(
        config,
        MagicMock(),
        ExportRecordXmlParams(table="sp_widget", sys_ids=["../etc"]),
    )
    assert res["success"] is False


def test_bad_table_rejected(config):
    res = export_record_xml(
        config,
        MagicMock(),
        ExportRecordXmlParams(table="Bad Table!", sys_ids=[SID]),
    )
    assert res["success"] is False


# --- transport guards -----------------------------------------------------


def test_html_login_response_is_flagged(config):
    dump = b"<!DOCTYPE html><html><body>login</body></html>"
    res = export_record_xml(
        config,
        _auth(dump, headers={"Content-Type": "text/html"}),
        ExportRecordXmlParams(table="sp_widget", sys_ids=[SID]),
    )
    assert res["success"] is False
    assert "login" in res["message"].lower() or "html" in res["message"].lower()


def test_http_error_status_surfaced(config):
    res = export_record_xml(
        config,
        _auth(b"", status=500),
        ExportRecordXmlParams(table="sp_widget", sys_ids=[SID]),
    )
    assert res["success"] is False
    assert res["status_code"] == 500


# --- unit: transform ------------------------------------------------------


def test_payload_to_inner_strips_wrapper():
    inner = _payload_to_inner(_payload("sp_widget", "<id>x</id>"))
    assert inner == '<sp_widget action="INSERT_OR_UPDATE"><id>x</id></sp_widget>'
