"""What a step is CONFIGURED to do, when the configuration is a script.

Three reads used to come back looking finished while carrying nothing:

  * a field whose value is computed by a script reported ``state=fd-scripted``
    — the sentinel that says "a script decides this" — as though that WERE the
    value, with ``note: None`` on top of it. Measured on a live 36-action flow:
    33 rows carried a body and every one of them was invisible.
  * every logic row decoded to None and was counted "unreadable" (83 of 83 on
    that same flow — i.e. every branch condition in it), because an action's
    blob is a bare input LIST and a logic row's is an object CONTAINING one,
    and only the list shape was accepted.
  * ``node_id`` — the handle the whole-flow answer tells callers to narrow with
    — was not on the params model, so it was dropped and the call fell through
    to the whole-flow read, which answered with the flow record and a ~30KB
    label_cache and not one word about the node asked for.

Fixtures go through the same gzip+base64+JSON encoder production reads, so a
fixture cannot drift into a shape the platform never writes.
"""

import base64
import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.flow_designer_tools import (
    GetFlowDetailsParams,
    _decode_values_blob,
    _humanize_input,
    _input_script_bodies,
    _project_step_inputs,
    _script_input_key,
    _summarize_node_inputs,
    get_flow_details,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig

# Long enough to be stubbed (over _SCRIPT_STUB_MIN_CHARS) — a one-liner stays
# inline on purpose, so a fixture under that floor would test the wrong branch.
SCRIPT = (
    "var priority = fd_data.trigger.current.priority;\n"
    "var assignment = fd_data.trigger.current.assignment_group;\n\n"
    "if (priority == '1' && assignment) {\n    return 'high';\n}\n\n"
    "return 'normal';"
)
SCRIPT_LINES = SCRIPT.count("\n") + 1


def encode(payload) -> str:
    """The producer side, used exactly as ServiceNow stores it."""
    return base64.b64encode(gzip.compress(json.dumps(payload).encode("utf-8"))).decode("ascii")


def scripted_entry(active=True, saved="32"):
    """An Update Record 'Fields' input whose `state` is script-driven."""
    return {
        "id": "b" * 32,
        "name": "values",
        "value": "state=fd-scripted",
        "displayValue": "state=fd-scripted",
        "children": [],
        "parameter": {"label": "Fields", "name": "values", "type": "template_value"},
        "scriptActive": active,
        "script": {"state": {"scriptActive": active, "script": SCRIPT, "savedValue": saved}},
    }


def plain_entry(name="table_name", value="incident"):
    return {
        "name": name,
        "value": value,
        "displayValue": value,
        "children": [],
        "parameter": {"label": name.replace("_", " ").title(), "type": "string"},
    }


def logic_blob(condition="{{Updated_1.current.priority}}=1", label="Priority = 1"):
    """A LOGIC row's blob: the input list wrapped in an object."""
    return encode(
        {
            "outputsToAssign": [],
            "inputs": [plain_entry("condition", condition), plain_entry("condition_name", label)],
        }
    )


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


class TestScriptExtraction:
    def test_an_unscripted_input_reports_no_scripts(self):
        """Empty means "not scripted" — it must not also mean "could not tell"."""
        assert _input_script_bodies(plain_entry()) == []

    def test_the_body_saved_value_and_liveness_all_survive(self):
        (body,) = _input_script_bodies(scripted_entry())
        assert body == {"field": "state", "script": SCRIPT, "active": True, "saved_value": "32"}

    def test_a_dormant_script_is_not_reported_as_the_value(self):
        """scriptActive=false means savedValue runs. Calling the script "the
        value" would swap one false answer for another."""
        (body,) = _input_script_bodies(scripted_entry(active=False))
        assert body["active"] is False
        key = _script_input_key("values", body)
        assert "INACTIVE" in key and "32" in key

    @pytest.mark.parametrize(
        "entry",
        [
            {"name": "v", "script": "not-a-block"},
            {"name": "v", "script": {"state": "not-a-dict"}},
            {"name": "v", "script": {"state": {"scriptActive": True, "script": "   "}}},
            {"name": "v", "script": {}},
            "not-an-entry-at-all",
        ],
    )
    def test_an_unrecognised_script_block_yields_nothing_and_never_raises(self, entry):
        assert _input_script_bodies(entry) == []


class TestScriptedFieldIsReadable:
    def test_the_sentinel_alone_is_no_longer_the_whole_answer(self):
        inputs, note = _project_step_inputs(encode([scripted_entry()]), [300])
        (field,) = inputs
        assert field["value"] == "state=fd-scripted", "the stored value still shows"
        assert field["scripts"][0]["field"] == "state"
        assert field["scripts"][0]["saved_value"] == "32"
        assert note is None

    def test_a_flow_wide_read_stubs_the_body_but_proves_one_exists(self):
        inputs, _ = _project_step_inputs(encode([scripted_entry()]), [300])
        stub = inputs[0]["scripts"][0]["script"]
        assert SCRIPT not in stub
        assert f"{SCRIPT_LINES} lines" in stub and str(len(SCRIPT)) in stub
        assert "node_id" in stub, "the stub must name the read that returns the body"

    def test_the_single_step_read_returns_it_verbatim(self):
        inputs, _ = _project_step_inputs(encode([scripted_entry()]), [300], None, full_scripts=True)
        assert inputs[0]["scripts"][0]["script"] == SCRIPT

    def test_an_unscripted_input_gains_no_scripts_key(self):
        inputs, _ = _project_step_inputs(encode([plain_entry()]), [300])
        assert "scripts" not in inputs[0]


class TestLogicBlobShape:
    def test_a_logic_row_decodes_to_its_inputs(self):
        decoded = _decode_values_blob(logic_blob())
        assert isinstance(decoded, list)
        assert [d["name"] for d in decoded] == ["condition", "condition_name"]

    def test_the_branch_condition_projects_instead_of_reading_unreadable(self):
        inputs, note = _project_step_inputs(logic_blob(), [300])
        assert note is None, "a decodable logic row must not be counted unreadable"
        assert {i["name"]: i["value"] for i in inputs}["condition"] == (
            "{{Updated_1.current.priority}}=1"
        )

    @pytest.mark.parametrize(
        "payload",
        [{"a": 1}, {"inputs": "not-a-list"}, {"outputsToAssign": []}],
    )
    def test_an_object_without_an_input_list_stays_unreadable(self, payload):
        """Widening the shape must not turn "unknown" into "binds nothing"."""
        assert _decode_values_blob(encode(payload)) is None
        _, note = _project_step_inputs(encode(payload), [300])
        assert note == "unreadable"


class TestProcessflowPath:
    """Browser auth reads a different payload; it must not answer differently."""

    def test_the_tree_row_carries_the_body_under_its_own_key(self):
        flat = _summarize_node_inputs({"inputs": [scripted_entry(), plain_entry()]}, {})
        assert flat["values"] == "state=fd-scripted"
        assert flat["values.state (script)"] == SCRIPT
        assert flat["table_name"] == "incident"

    def test_a_long_body_is_stubbed_when_the_tree_asks_for_no_scripts(self):
        flat = _summarize_node_inputs({"inputs": [scripted_entry()]}, {})
        key = "values.state (script)"
        rendered = _humanize_input(key, flat[key], {}, False)
        assert rendered.startswith("«script:")
        assert _humanize_input(key, flat[key], {}, True) == SCRIPT


class TestSingleNodeRead:
    UI = "11111111-2222-3333-4444-555555555555"

    def _rows(self, config, auth_manager, *, table, query, **_):
        if table == "sys_hub_action_instance_v2" and f"ui_id={self.UI}" in query:
            return (
                [
                    {
                        "sys_id": "a" * 32,
                        "ui_id": self.UI,
                        "order": "7",
                        "display_text": "",
                        "name": "",
                        "action_type": "Update Record",
                        "parent_ui_id": "99999999-8888-7777-6666-555555555555",
                        "values": encode([scripted_entry(), plain_entry()]),
                    }
                ],
                None,
            )
        return ([], None)

    def _read(self, node_id):
        with (
            patch("servicenow_mcp.tools.flow_designer_tools._is_browser_auth", return_value=False),
            patch(
                "servicenow_mcp.tools.flow_designer_tools._get_snapshot_id",
                return_value="s" * 32,
            ),
            patch(
                "servicenow_mcp.tools.flow_designer_tools.sn_query_page",
                side_effect=self._rows,
            ),
        ):
            return get_flow_details(
                _cfg(), MagicMock(), GetFlowDetailsParams(flow_id="f" * 32, node_id=node_id)
            )

    def test_it_returns_that_node_with_the_body_in_full(self):
        result = self._read(self.UI)
        assert result["success"] is True
        node = result["node"]
        assert node["order"] == "7" and node["kind"] == "action"
        assert node["type"] == "Update Record"
        assert node["inputs"][0]["scripts"][0]["script"] == SCRIPT

    def test_it_answers_with_the_node_and_not_the_flow(self):
        """The bug was a 30KB flow record + label_cache in place of the node."""
        result = self._read(self.UI)
        assert "flow" not in result and "label_cache" not in json.dumps(result)
        assert len(json.dumps(result)) < 2000

    def test_a_handle_that_does_not_resolve_says_so(self):
        result = self._read("no-such-node")
        assert result["success"] is False
        assert "no-such-node" in result["error"]
        assert "not evidence" in result["error"], "absence must not read as 'binds nothing'"
        assert "include_structure" in result["how_to_find_it"]
