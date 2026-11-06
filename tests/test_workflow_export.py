"""manage_workflow export: the whole legacy graph to disk, and what each read proved."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools import workflow_export as we
from servicenow_mcp.tools.workflow_tools import ManageWorkflowParams, manage_workflow
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

WF = "aaaa1111bbbb2222cccc3333dddd4444"
WF_OTHER = "abcd1111bbbb2222cccc3333dddd4444"
VER = "bbbb2222cccc3333dddd4444eeee5555"
A_BEGIN = "cccc3333dddd4444eeee5555ffff6666"
A_SCRIPT = "dddd4444eeee5555ffff6666aaaa7777"
A_END = "eeee5555ffff6666aaaa7777bbbb8888"
A_ORPHAN = "ffff6666aaaa7777bbbb8888cccc9999"
C_ALWAYS = "aaaa7777bbbb8888cccc9999dddd0000"
C_SCRIPT = "bbbb8888cccc9999dddd0000eeee1111"


@pytest.fixture()
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _tables(wf_id=WF):
    return {
        "wf_activity": [
            {"sys_id": A_BEGIN, "name": "", "activity_definition.name": "Begin"},
            {"sys_id": A_SCRIPT, "name": "Set fields", "activity_definition.name": "Run Script"},
            {"sys_id": A_END, "name": "", "activity_definition.name": "End"},
            {"sys_id": A_ORPHAN, "name": "Old step", "activity_definition.name": "Run Script"},
        ],
        "sys_variable_value": [
            {
                "document_key": A_SCRIPT,
                "variable.element": "script",
                "variable.internal_type": "script",
                "value": "current.state = 2;\n",
            },
            {
                "document_key": A_SCRIPT,
                "variable.element": "condition",
                "variable.internal_type": "conditions",
                "value": "active=true",
            },
        ],
        "wf_condition": [
            {"sys_id": C_ALWAYS, "activity": A_BEGIN, "name": "Always", "order": "1"},
            {"sys_id": C_SCRIPT, "activity": A_SCRIPT, "name": "Always", "order": "1"},
        ],
        "wf_transition": [
            {"from": A_BEGIN, "to": A_SCRIPT, "condition": C_ALWAYS},
            {"from": A_SCRIPT, "to": A_END, "condition": C_SCRIPT},
        ],
        "wf_stage": [{"sys_id": "s1", "name": "Fulfil", "value": "fulfil", "order": "200"}],
    }


class Fake:
    def __init__(self, tables, wf_id=WF, fail_table=None, cap_table=None, running=0):
        self.tables, self.wf_id = tables, wf_id
        self.fail_table, self.cap_table, self.running = fail_table, cap_table, running
        self.queries = []

    def page(self, config, auth, *, table, query, fields, **kw):
        if table == "wf_workflow":
            return [{"sys_id": self.wf_id, "name": "Order flow", "sys_scope.scope": "global"}], 1
        if table == "wf_workflow_version":
            return [
                {
                    "sys_id": VER,
                    "name": "Order flow",
                    "table": "sc_req_item",
                    "condition": "active=true",
                    "published": "true",
                }
            ], 1
        return [], 0

    def all(self, config, auth, *, table, query, fields, **kw):
        self.queries.append((table, query))
        if table == self.fail_table:
            raise RuntimeError("HTTP 502")
        if table == self.cap_table:
            return [{"sys_id": f"x{i}"} for i in range(we._READ_CAP)]
        return list(self.tables.get(table, []))

    def count(self, config, auth, table, query=""):
        return self.running


def _export(config, tmp_path, fake, **kw):
    with (
        patch.object(we, "sn_query_page", side_effect=fake.page),
        patch.object(we, "sn_query_all", side_effect=fake.all),
        patch.object(we, "sn_count", side_effect=fake.count),
    ):
        return manage_workflow(
            config,
            MagicMock(),
            ManageWorkflowParams(
                action="export", workflow_id=kw.pop("wf", WF), output_dir=str(tmp_path), **kw
            ),
        )


def test_export_writes_graph_scripts_and_outline(config, tmp_path):
    fake = Fake(_tables(), running=3)
    r = _export(config, tmp_path, fake)
    assert r["success"] is True and r["complete"] is True
    assert r["counts"] == {
        "activities": 4,
        "variables": 2,
        "script_files": 1,
        "exits": 2,
        "transitions": 2,
        "stages": 1,
    }
    assert r["trigger"]["table"] == "sc_req_item"
    assert r["running_contexts"] == 3
    root = tmp_path / "wf_workflow" / "Order_flow"
    data = json.loads((root / "workflow.json").read_text())
    act = next(a for a in data["activities"] if a["sys_id"] == A_SCRIPT)
    script_ref = act["variables"]["script"]
    assert (root / script_ref["file"]).read_text() == "current.state = 2;\n"
    # Non-script values stay inline (an encoded query is not a program file).
    assert act["variables"]["condition"] == {"type": "conditions", "value": "active=true"}
    assert data["transitions"][0]["condition_name"] == "Always"
    outline = (root / "outline.md").read_text()
    assert outline.index("[Begin]") < outline.index("Set fields") < outline.index("[End]")
    # An activity nothing leads to is listed, never dropped.
    assert "Not reachable from Begin" in outline and "Old step" in outline
    # One file to analyse from: trigger, settings inline, scripts by path + size.
    assert "trigger: table `sc_req_item`; condition `active=true`" in outline
    assert "`condition` = active=true" in outline
    assert f"`script` (script) → `{script_ref['file']}` (1 lines)" in outline
    assert "on 'Always' → #2 Set fields [Run Script]" in outline


def test_outline_points_long_values_at_the_json(config, tmp_path):
    tables = _tables()
    tables["sys_variable_value"][1]["value"] = "x" * 500
    _export(config, tmp_path, Fake(tables))
    outline = (tmp_path / "wf_workflow" / "Order_flow" / "outline.md").read_text()
    assert "(full value: workflow.json)" in outline
    assert "x" * 500 not in outline


def test_variables_are_read_for_wf_activity_documents_only(config, tmp_path):
    fake = Fake(_tables())
    _export(config, tmp_path, fake)
    (vq,) = [q for t, q in fake.queries if t == "sys_variable_value"]
    assert vq.startswith("document=wf_activity^document_keyIN")


def test_failed_read_writes_nothing(config, tmp_path):
    fake = Fake(_tables(), fail_table="wf_transition")
    r = _export(config, tmp_path, fake)
    assert r["success"] is False
    assert "nothing written" in r["error"]
    assert not (tmp_path / "wf_workflow").exists()


def test_capped_read_is_reported_incomplete(config, tmp_path):
    fake = Fake(_tables(), cap_table="wf_condition")
    r = _export(config, tmp_path, fake)
    assert r["complete"] is False
    assert "INCOMPLETE" in r["warning"] and "conditions" in r["warning"]


def test_unread_running_contexts_is_not_zero(config, tmp_path):
    fake = Fake(_tables())
    fake.count = MagicMock(side_effect=RuntimeError("HTTP 403"))
    r = _export(config, tmp_path, fake)
    assert str(r["running_contexts"]).startswith("unread")


def test_same_named_workflow_never_overwrites_another(config, tmp_path):
    _export(config, tmp_path, Fake(_tables()))
    r = _export(config, tmp_path, Fake(_tables(), wf_id=WF_OTHER), wf=WF_OTHER)
    assert r["output_dir"].endswith(f"Order_flow.{WF_OTHER[:8]}")
    first = json.loads((tmp_path / "wf_workflow" / "Order_flow" / "workflow.json").read_text())
    assert first["workflow"]["sys_id"] == WF


def test_reexport_of_same_workflow_reuses_its_folder(config, tmp_path):
    _export(config, tmp_path, Fake(_tables()))
    r = _export(config, tmp_path, Fake(_tables()))
    assert r["output_dir"].endswith("Order_flow")


def test_export_requires_workflow_id():
    with pytest.raises(ValueError):
        ManageWorkflowParams(action="export")


def test_export_is_classified_as_a_read():
    from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS

    assert "export" in MANAGE_READ_ACTIONS["manage_workflow"]


def test_snapshot_says_edits_go_nowhere(config, tmp_path):
    _export(config, tmp_path, Fake(_tables()))
    root = tmp_path / "wf_workflow" / "Order_flow"
    assert "changes nothing on the server" in (root / "outline.md").read_text()
    data = json.loads((root / "workflow.json").read_text())
    assert "changes nothing on the server" in data["snapshot"] and data["exported_at"]


def test_reexport_reports_whether_the_server_changed(config, tmp_path):
    first = _export(config, tmp_path, Fake(_tables()))
    assert "previous_export" not in first
    same = _export(config, tmp_path, Fake(_tables()))
    assert same["previous_export"]["changed_on_server"] is False
    tables = _tables()
    tables["sys_variable_value"][0]["value"] = "current.state = 3;\n"
    moved = _export(config, tmp_path, Fake(tables))
    assert moved["previous_export"]["changed_on_server"] is True
    assert "re-checked" in moved["previous_export"]["note"]


def test_reexport_drops_script_files_of_removed_activities(config, tmp_path):
    _export(config, tmp_path, Fake(_tables()))
    root = tmp_path / "wf_workflow" / "Order_flow"
    old_files = list((root / "activities").rglob("*.js"))
    assert old_files
    tables = _tables()
    tables["sys_variable_value"] = []  # the scripted activity's variables are gone
    _export(config, tmp_path, Fake(tables))
    assert not any(f.exists() for f in old_files)
