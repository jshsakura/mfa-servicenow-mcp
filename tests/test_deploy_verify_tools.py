"""Tests for the deploy-XML origin ledger and verify_deployment_xml.

The failure these pin: an ``<unload>`` assembled by hand from day-old local
copies was shipped as if it were a live export. Nothing could tell it apart from
a real one, importing it would have reverted two developers' same-day work, and
the import never happened yet was recorded as deployed.

So the invariants under test are: an export issues an origin certificate; a file
without one is refused before any network call; a live record that moved AFTER
the export reads as ``live_newer`` and blocks the import; and a postflight that
does not match says so instead of confirming.
"""

import json
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock
from xml.sax.saxutils import escape

import pytest

from servicenow_mcp.tools.deploy_verify_tools import (
    DIFFERS,
    LIVE_NEWER,
    MATCH,
    MISSING,
    VerifyDeploymentXmlParams,
    verify_deployment_xml,
)
from servicenow_mcp.tools.xml_export_tools import ExportRecordXmlParams, export_record_xml
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig
from servicenow_mcp.utils.deploy_ledger import (
    is_confirmed_applied,
    pending_exports,
    read_origin,
    record_xml_dir,
    sidecar_path_for,
    write_origin,
)

SID = "dddd1111eeee2222ffff3333aaaa4444"
SID2 = "a" * 32
XML_VERSION = "2026-07-28 12:35:13"
LIVE_VERSION = "2026-07-29 09:05:23"


@pytest.fixture(autouse=True)
def _hermetic_cwd(tmp_path, monkeypatch):
    """pending_exports() falls back to ./temp/*/xml for pre-registry exports, so
    without this the repo's own temp/ leaks into every scan assertion."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://dev12345.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def live(monkeypatch):
    """Rows the mocked live read returns, keyed by table. Mutate in the test."""
    rows_by_table: dict = {}

    def fake_query_page(config, auth_manager, *, table, **kwargs):
        return list(rows_by_table.get(table, [])), None

    monkeypatch.setattr("servicenow_mcp.tools.sn_api.sn_query_page", fake_query_page)
    return rows_by_table


def _block(table, sys_id, *, updated_on=XML_VERSION, mod_count="5", **fields) -> str:
    body = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in fields.items())
    return (
        f'<{table} action="INSERT_OR_UPDATE">'
        f"<sys_id>{sys_id}</sys_id>"
        f"<sys_updated_on>{updated_on}</sys_updated_on>"
        f"<sys_updated_by>exporter</sys_updated_by>"
        f"<sys_mod_count>{mod_count}</sys_mod_count>"
        f"{body}"
        f"</{table}>"
    )


def _write_unload(path, *blocks):
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<unload unload_date="2026-07-29 08:49:00">\n'
        + "\n".join(blocks)
        + "\n</unload>\n",
        encoding="utf-8",
    )
    return path


def _certify(path, records=None):
    write_origin(
        path,
        source_instance="dev12345",
        source_instance_url="https://dev12345.service-now.com",
        records=records if records is not None else [{"name": f"sys_script_{SID}"}],
    )
    return path


def _verify(config, path, **kw):
    return verify_deployment_xml(
        config, MagicMock(), VerifyDeploymentXmlParams(xml_path=str(path), **kw)
    )


# --- the export issues a certificate --------------------------------------


class FakeResp:
    def __init__(self, content: bytes):
        self.status_code = 200
        self.content = content
        self.headers: dict[str, str] = {}


def _version_dump(name: str, inner: str) -> bytes:
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<record_update table="sys_script">{inner}</record_update>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><xml><sys_update_version>'
        f"<name>{name}</name><state>current</state>"
        f"<payload>{escape(payload)}</payload>"
        "</sys_update_version></xml>"
    ).encode("utf-8")


def test_export_issues_origin_certificate_with_live_stamps(config, tmp_path):
    inner = _block("sys_script", SID, updated_on=XML_VERSION, mod_count="97", script="gs.log(1)")
    auth = MagicMock()
    auth.make_request.return_value = FakeResp(_version_dump(f"sys_script_{SID}", inner))
    out = tmp_path / "01_br.xml"

    res = export_record_xml(
        config,
        auth,
        ExportRecordXmlParams(table="sys_script", sys_ids=[SID], output_path=str(out)),
    )

    assert res["success"]
    assert res["origin_certificate"] == str(sidecar_path_for(out))
    doc = read_origin(out)
    assert doc is not None
    assert doc["source_instance"] == "dev12345"
    stamp = doc["records"][0]
    # Table and sys_id come from the parsed block, not from splitting the name.
    assert stamp["table"] == "sys_script"
    assert stamp["sys_id"] == SID
    assert stamp["sys_updated_on"] == XML_VERSION
    assert stamp["sys_mod_count"] == "97"
    assert stamp["payload_sha"]


def test_export_records_its_dir_so_health_can_find_it(config, tmp_path):
    inner = _block("sys_script", SID, script="gs.log(1)")
    auth = MagicMock()
    auth.make_request.return_value = FakeResp(_version_dump(f"sys_script_{SID}", inner))

    export_record_xml(
        config,
        auth,
        ExportRecordXmlParams(table="sys_script", sys_ids=[SID], output_dir=str(tmp_path)),
    )

    pending = pending_exports()
    assert pending["unconfirmed_exports"] == 1
    assert "verify_deployment_xml" in pending["next"]


# --- origin is checked before the network ---------------------------------


def test_unanchored_xml_is_refused(config, tmp_path, live):
    path = _write_unload(tmp_path / "hand_built.xml", _block("sys_script", SID, script="x"))

    res = _verify(config, path)

    assert res["success"] is False
    assert res["verdict"] == "unanchored"
    assert "export_record_xml" in res["message"]
    # Refused BEFORE any live read — nothing was fetched.
    assert not live


def test_allow_unanchored_is_a_second_approval_not_a_wall(config, tmp_path, live):
    path = _write_unload(tmp_path / "hand_built.xml", _block("sys_script", SID, script="x"))
    live["sys_script"] = [
        {"sys_id": SID, "script": "x", "sys_updated_on": XML_VERSION, "sys_updated_by": "me"}
    ]

    res = _verify(config, path, allow_unanchored=True)

    assert res["success"] is True
    assert res["origin_unverified"] is True
    assert "not provably a live export" in res["origin_warning"]
    assert res["counts"] == {MATCH: 1}


def test_malformed_certificate_reads_as_unanchored(config, tmp_path, live):
    path = _write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x"))
    sidecar_path_for(path).write_text("{not json", encoding="utf-8")

    res = _verify(config, path)

    assert res["verdict"] == "unanchored"


def test_foreign_certificate_reads_as_unanchored(config, tmp_path, live):
    """A sidecar this tool did not issue proves nothing."""
    path = _write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x"))
    sidecar_path_for(path).write_text(json.dumps({"origin": "hand", "records": []}), "utf-8")

    res = _verify(config, path)

    assert res["verdict"] == "unanchored"


# --- preflight: the check that was missing --------------------------------


def test_preflight_blocks_when_live_moved_after_the_export(config, tmp_path, live):
    """The incident: XML captured 07-28, someone edited the record 07-29."""
    path = _certify(
        _write_unload(tmp_path / "01_oir.xml", _block("sys_script", SID, script="OLD BODY"))
    )
    live["sys_script"] = [
        {
            "sys_id": SID,
            "script": "NEW BODY from bob",
            "sys_updated_on": LIVE_VERSION,
            "sys_updated_by": "bob",
            "sys_mod_count": "97",
        }
    ]

    res = _verify(config, path)

    assert res["success"] is True
    assert res["deployable"] is False
    record = res["records"][0]
    assert record["verdict"] == LIVE_NEWER
    assert record["live_updated_by"] == "bob"
    assert record["xml_version"] == XML_VERSION
    assert record["live_version"] == LIVE_VERSION
    assert record["differing_fields"] == ["script"]
    assert "DO NOT IMPORT" in res["message"]


def test_preflight_match_is_deployable(config, tmp_path, live):
    path = _certify(
        _write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="SAME BODY"))
    )
    live["sys_script"] = [{"sys_id": SID, "script": "SAME BODY", "sys_updated_on": XML_VERSION}]

    res = _verify(config, path)

    assert res["deployable"] is True
    assert res["counts"] == {MATCH: 1}


def test_older_live_record_differs_but_does_not_block(config, tmp_path, live):
    """A target that lags is normal — only a live record NEWER than the export
    means the import would revert work."""
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="NEW")))
    live["sys_script"] = [{"sys_id": SID, "script": "OLD", "sys_updated_on": "2026-07-01 00:00:00"}]

    res = _verify(config, path)

    assert res["records"][0]["verdict"] == DIFFERS
    assert res["deployable"] is True


def test_volatile_fields_alone_are_not_a_difference(config, tmp_path, live):
    """Audit stamps and update bookkeeping always differ; content is what counts."""
    path = _certify(
        _write_unload(
            tmp_path / "d.xml",
            _block("sys_script", SID, mod_count="5", script="BODY", sys_package="pkg_a"),
        )
    )
    live["sys_script"] = [
        {
            "sys_id": SID,
            "script": "BODY",
            "sys_package": "pkg_b",  # per-instance packaging, excluded
            "sys_updated_on": LIVE_VERSION,  # newer, but content matches
            "sys_mod_count": "412",
        }
    ]

    res = _verify(config, path)

    assert res["records"][0]["verdict"] == MATCH
    assert res["deployable"] is True


def test_line_endings_and_boolean_spellings_are_not_differences(config, tmp_path, live):
    path = _certify(
        _write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="a\r\nb", active="true"))
    )
    live["sys_script"] = [
        {"sys_id": SID, "script": "a\nb", "active": "1", "sys_updated_on": XML_VERSION}
    ]

    res = _verify(config, path)

    assert res["records"][0]["verdict"] == MATCH


def test_record_absent_on_this_instance(config, tmp_path, live):
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x")))
    live["sys_script"] = []

    res = _verify(config, path)

    assert res["records"][0]["verdict"] == MISSING
    assert res["counts"] == {MISSING: 1}


# --- postflight: did it actually land? ------------------------------------


def test_postflight_refuses_to_confirm_an_import_that_did_not_happen(config, tmp_path, live):
    """The other half of the incident: recorded as deployed, never imported."""
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="FIXED")))
    live["sys_script"] = [
        {"sys_id": SID, "script": "UNFIXED", "sys_updated_on": "2026-07-01 00:00:00"}
    ]

    res = _verify(config, path, mode="postflight")

    assert res["applied"] == 0
    assert res["not_applied"] == 1
    assert "NOT fully applied" in res["message"]
    assert "do not record this deployment as done" in res["message"].lower()
    # A failed landing must NOT clear the pending flag.
    assert not is_confirmed_applied(read_origin(path))


def test_postflight_applied_records_the_landing_and_clears_health(config, tmp_path, live):
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="FIXED")))
    record_xml_dir(tmp_path)
    live["sys_script"] = [{"sys_id": SID, "script": "FIXED", "sys_updated_on": LIVE_VERSION}]
    assert pending_exports()["unconfirmed_exports"] == 1

    res = _verify(config, path, mode="postflight")

    assert res["applied"] == 1 and res["not_applied"] == 0
    assert "Confirmed" in res["message"]
    doc = read_origin(path)
    assert is_confirmed_applied(doc)
    assert doc["applied"][-1]["instance"] == "dev12345"
    # Confirmed landing -> sn_health goes quiet about this file.
    assert pending_exports() == {}


def test_partial_landing_keeps_nagging(config, tmp_path, live):
    path = _certify(
        _write_unload(
            tmp_path / "d.xml",
            _block("sys_script", SID, script="FIXED"),
            _block("sys_script", SID2, script="ALSO FIXED"),
        )
    )
    record_xml_dir(tmp_path)
    live["sys_script"] = [
        {"sys_id": SID, "script": "FIXED", "sys_updated_on": LIVE_VERSION},
        {"sys_id": SID2, "script": "STILL OLD", "sys_updated_on": LIVE_VERSION},
    ]

    res = _verify(config, path, mode="postflight")

    assert (res["applied"], res["not_applied"]) == (1, 1)
    assert not is_confirmed_applied(read_origin(path))
    assert pending_exports()["unconfirmed_exports"] == 1


# --- input handling -------------------------------------------------------


def test_missing_file(config, tmp_path):
    res = _verify(config, tmp_path / "nope.xml")
    assert res["success"] is False and "No such file" in res["message"]


def test_non_unload_root_is_rejected(config, tmp_path):
    path = tmp_path / "d.xml"
    path.write_text("<html><body>login</body></html>", encoding="utf-8")
    _certify(path)

    res = _verify(config, path)

    assert res["success"] is False and "expected <unload>" in res["message"]


def test_bare_record_update_root_is_accepted(config, tmp_path, live):
    """A single-record file is a legitimate shape and must still be checkable."""
    path = tmp_path / "d.xml"
    path.write_text(
        f'<record_update table="sys_script">{_block("sys_script", SID, script="x")}</record_update>',
        encoding="utf-8",
    )
    _certify(path)
    live["sys_script"] = [{"sys_id": SID, "script": "x", "sys_updated_on": XML_VERSION}]

    res = _verify(config, path)

    assert res["records"][0]["verdict"] == MATCH


def test_cross_instance_export_is_noted_not_blocked(config, tmp_path, live):
    path = _write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x"))
    write_origin(
        path,
        source_instance="prod999",
        source_instance_url="https://prod999.service-now.com",
        records=[],
    )
    live["sys_script"] = [{"sys_id": SID, "script": "x", "sys_updated_on": XML_VERSION}]

    res = _verify(config, path, mode="postflight")

    assert res["origin"]["source_instance"] == "prod999"
    assert "prod999" in res["origin"]["note"] and "dev12345" in res["origin"]["note"]


def test_live_read_failure_is_surfaced(config, tmp_path, monkeypatch):
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x")))

    def boom(*a, **kw):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr("servicenow_mcp.tools.sn_api.sn_query_page", boom)

    res = _verify(config, path)

    assert res["success"] is False and "403 forbidden" in res["message"]


def test_verification_never_answers_from_cache(config, tmp_path, monkeypatch):
    """A cached read is the exact failure this tool exists to prevent: a
    'confirmed deployed' verdict from a query taken before the import."""
    invalidated: list = []
    monkeypatch.setattr(
        "servicenow_mcp.tools.sn_api.invalidate_query_cache",
        lambda *, table=None: invalidated.append(table) or 0,
    )
    monkeypatch.setattr(
        "servicenow_mcp.tools.sn_api.sn_query_page",
        lambda *a, **kw: ([{"sys_id": SID, "script": "x", "sys_updated_on": XML_VERSION}], None),
    )
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x")))

    _verify(config, path, mode="postflight")

    assert invalidated == ["sys_script"]


def test_show_fields_false_reports_counts_without_names(config, tmp_path, live):
    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="NEW")))
    live["sys_script"] = [{"sys_id": SID, "script": "OLD", "sys_updated_on": "2026-07-01 00:00:00"}]

    res = _verify(config, path, show_fields=False)

    record = res["records"][0]
    assert record["differing_field_count"] == 1
    assert "differing_fields" not in record


def test_sn_health_surfaces_unconfirmed_exports(tmp_path):
    from servicenow_mcp.tools.sn_api import _deployments_snapshot

    path = _certify(_write_unload(tmp_path / "d.xml", _block("sys_script", SID, script="x")))
    record_xml_dir(tmp_path)

    snapshot = _deployments_snapshot()

    assert snapshot["unconfirmed_exports"] == 1
    assert path.name in snapshot["oldest"]


def test_sn_health_is_silent_with_nothing_pending():
    from servicenow_mcp.tools.sn_api import _deployments_snapshot

    assert _deployments_snapshot() == {}


def test_exported_xml_bytes_carry_no_provenance_comment(config, tmp_path):
    """The certificate is a sidecar on purpose: the importable format is
    live-verified and must not gain an embedded comment."""
    inner = _block("sys_script", SID, script="gs.log(1)")
    auth = MagicMock()
    auth.make_request.return_value = FakeResp(_version_dump(f"sys_script_{SID}", inner))
    out = tmp_path / "d.xml"

    export_record_xml(
        config,
        auth,
        ExportRecordXmlParams(table="sys_script", sys_ids=[SID], output_path=str(out)),
    )

    text = out.read_text(encoding="utf-8")
    assert "<!--" not in text
    root = ET.parse(out).getroot()
    assert root.tag == "unload" and [c.tag for c in root] == ["sys_script"]
