"""manage_workflow verify: did a script edit applied in the Workflow Editor reach the server?"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools import workflow_export as we
from servicenow_mcp.tools import workflow_verify as wv
from servicenow_mcp.tools.workflow_tools import ManageWorkflowParams, manage_workflow
from tests.test_workflow_export import A_SCRIPT, WF, Fake, _tables

# A checkout copies every activity under a new sys_id.
A_COPY = "aaaa9999bbbb0000cccc1111dddd2222"
EXPORTED = "current.state = 2;\n"
EDITED = "current.state = 3;\n"


@pytest.fixture()
def config():
    from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _checked_out(value):
    """The live graph after checkout → edit → publish: new ids, same names."""
    t = _tables()
    for a in t["wf_activity"]:
        if a["sys_id"] == A_SCRIPT:
            a["sys_id"] = A_COPY
    for row in t["wf_condition"]:
        if row["activity"] == A_SCRIPT:
            row["activity"] = A_COPY
    for tr in t["wf_transition"]:
        for end in ("from", "to"):
            if tr[end] == A_SCRIPT:
                tr[end] = A_COPY
    for v in t["sys_variable_value"]:
        if v["document_key"] == A_SCRIPT:
            v["document_key"] = A_COPY
            if v["variable.element"] == "script":
                v["value"] = value
    return t


def _capture(rows=None, error=None):
    def page(config, auth, **kw):
        assert kw["table"] == "sys_update_xml" and kw["query"] == f"name=wf_workflow_{WF}"
        if error:
            raise RuntimeError(error)
        return (rows if rows is not None else []), None

    return page


CAPTURED_LATER = [
    {
        "update_set.name": "Sprint 12 fixes",
        "update_set.state": "in progress",
        "sys_updated_on": "2999-01-01 00:00:00",
        "sys_updated_by": "alice",
    }
]


def _call(config, tmp_path, tables, action, capture=None):
    fake = Fake(tables)
    with (
        patch.object(we, "sn_query_page", side_effect=fake.page),
        patch.object(we, "sn_query_all", side_effect=fake.all),
        patch.object(we, "sn_count", side_effect=fake.count),
        patch.object(wv, "sn_query_page", side_effect=capture or _capture()),
    ):
        return manage_workflow(
            config,
            MagicMock(),
            ManageWorkflowParams(action=action, workflow_id=WF, output_dir=str(tmp_path)),
        )


def _script_file(tmp_path):
    root = tmp_path / "wf_workflow" / "Order_flow"
    data = json.loads((root / "workflow.json").read_text())
    act = next(a for a in data["activities"] if a["sys_id"] == A_SCRIPT)
    return root / act["variables"]["script"]["file"]


def test_edit_not_yet_in_the_editor_is_not_applied(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _tables(), "verify")
    assert [e["verdict"] for e in r["edited"]] == ["not_applied"]
    assert r["verdict"].startswith("NOT ALL APPLIED: 0/1")


def test_edit_published_from_a_checkout_is_applied_and_captured(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _checked_out(EDITED), "verify", _capture(CAPTURED_LATER))
    assert [e["verdict"] for e in r["edited"]] == ["applied"]
    assert r["update_set_capture"]["after_export"] is True
    assert r["verdict"] == (
        "APPLIED and captured in update set 'Sprint 12 fixes' (state: in progress)."
    )


def test_applied_without_a_capture_says_it_will_not_travel(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _checked_out(EDITED), "verify")
    assert "will not travel" in r["verdict"]


def test_capture_older_than_the_export_does_not_count(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    old = [dict(CAPTURED_LATER[0], sys_updated_on="2000-01-01 00:00:00")]
    r = _call(config, tmp_path, _checked_out(EDITED), "verify", _capture(old))
    assert r["update_set_capture"]["after_export"] is False
    assert "will not travel" in r["verdict"]


def test_unread_capture_is_never_reported_as_captured(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _checked_out(EDITED), "verify", _capture(error="HTTP 403"))
    assert r["update_set_capture"]["checked"] is False
    assert "could not be read" in r["verdict"]


def test_a_third_body_on_the_server_is_differs(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _checked_out("current.state = 9;\n"), "verify")
    assert [e["verdict"] for e in r["edited"]] == ["differs"]


def test_same_named_activities_are_told_apart_by_position_or_called_ambiguous():
    index = {
        ("Set", "Run Script"): [
            {"sys_id": "a", "position": ("10", "20"), "values": {}},
            {"sys_id": "b", "position": ("30", "40"), "values": {}},
        ]
    }
    assert wv._match(index, "Set", "Run Script", ("30", "40"))[0]["sys_id"] == "b"
    assert wv._match(index, "Set", "Run Script", ("99", "99")) == (None, "ambiguous")
    assert wv._match(index, "Gone", "Run Script", ("1", "1")) == (None, "activity_not_found")


def test_untouched_file_whose_server_body_moved_is_named(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    r = _call(config, tmp_path, _checked_out("current.state = 9;\n"), "verify")
    assert r["edited"] == [] and r["verdict"].startswith("NO_LOCAL_EDITS")
    assert r["server_changed_unedited"] == [
        str(_script_file(tmp_path).relative_to(tmp_path / "wf_workflow" / "Order_flow"))
    ]


def test_export_without_hashes_is_undetermined_not_clean(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    root = tmp_path / "wf_workflow" / "Order_flow"
    data = json.loads((root / "workflow.json").read_text())
    for a in data["activities"]:
        for v in a["variables"].values():
            v.pop("sha256", None)
    (root / "workflow.json").write_text(json.dumps(data))
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _tables(), "verify")
    assert r["edited"] == [] and "predates hashes" in r["undetermined"][0]


def test_verify_without_an_export_says_so(config, tmp_path):
    r = _call(config, tmp_path, _tables(), "verify")
    assert r["success"] is False and r["error"] == "NO_EXPORT"


def test_verify_never_judges_a_capped_read(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    fake = Fake(_tables(), cap_table="sys_variable_value")
    with (
        patch.object(we, "sn_query_page", side_effect=fake.page),
        patch.object(we, "sn_query_all", side_effect=fake.all),
        patch.object(wv, "sn_query_page", side_effect=_capture()),
    ):
        r = manage_workflow(
            config,
            MagicMock(),
            ManageWorkflowParams(action="verify", workflow_id=WF, output_dir=str(tmp_path)),
        )
    assert r["error"] == "LIVE_READ_INCOMPLETE"


def test_reexport_refuses_to_destroy_an_unapplied_edit(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    f = _script_file(tmp_path)
    f.write_text(EDITED)
    r = _call(config, tmp_path, _tables(), "export")
    assert r["success"] is False and r["error"] == "LOCAL_EDITS_PENDING"
    assert f.read_text() == EDITED


def test_reexport_after_the_edit_is_live_replaces_the_snapshot(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    r = _call(config, tmp_path, _checked_out(EDITED), "export")
    assert r["success"] is True


def test_verify_is_classified_as_a_read():
    from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS

    assert "verify" in MANAGE_READ_ACTIONS["manage_workflow"]


def test_verify_requires_workflow_id():
    with pytest.raises(ValueError):
        ManageWorkflowParams(action="verify")


def test_crlf_on_the_server_is_not_a_local_edit_and_not_a_difference(config, tmp_path):
    crlf = _tables()
    crlf["sys_variable_value"][0]["value"] = "a = 1;\r\nb = 2;\r\n"
    _call(config, tmp_path, crlf, "export")
    assert _script_file(tmp_path).read_bytes() == b"a = 1;\nb = 2;\n"
    r = _call(config, tmp_path, crlf, "verify")
    assert r["edited"] == [] and "server_changed_unedited" not in r
    # The editor stores the pasted edit with CRLF: still applied.
    _script_file(tmp_path).write_text("a = 1;\nb = 3;\n")
    r = _call(config, tmp_path, _checked_out("a = 1;\r\nb = 3;\r\n"), "verify")
    assert [e["verdict"] for e in r["edited"]] == ["applied"]


def test_capture_without_a_readable_update_set_is_not_shipped(config, tmp_path):
    _call(config, tmp_path, _tables(), "export")
    _script_file(tmp_path).write_text(EDITED)
    orphan = [dict(CAPTURED_LATER[0], **{"update_set.name": ""})]
    r = _call(config, tmp_path, _checked_out(EDITED), "verify", _capture(orphan))
    assert "do not count it as shipped" in r["verdict"]
