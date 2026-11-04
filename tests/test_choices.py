"""Choice-column writes resolve against the live sys_choice list before any write.

ServiceNow stores a value that is not one of a choice column's options and
answers 200. Measured on a live instance: change_request.state takes -4/-1/4,
and the approval tools were writing the words "assess"/"implement"/"canceled";
kb_knowledge.workflow_state and item_option_new.type had the same shape.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import change as change_svc
from servicenow_mcp.services import incident as incident_svc
from servicenow_mcp.services.choices import resolve_choice, resolve_payload_choices
from servicenow_mcp.tools.change_tools import (
    ApproveChangeParams,
    RejectChangeParams,
    SubmitChangeForApprovalParams,
    approve_change,
    reject_change,
    submit_change_for_approval,
)

PRIORITY = [{"value": "1", "label": "1 - Critical"}, {"value": "3", "label": "3 - Moderate"}]


def _reads(answers):
    """Script sn_query_page by table: sys_choice per name, sys_db_object parents."""
    calls = []

    def fake(config, auth_manager, **kw):
        calls.append((kw["table"], kw["query"]))
        return answers(kw["table"], kw["query"]), None

    return patch("servicenow_mcp.services.choices.sn_query_page", side_effect=fake), calls


class TestResolveChoice:
    def test_inherits_choices_from_the_parent_table(self, mock_config):
        # incident declares no priority choices of its own; task does.
        def answers(table, query):
            if table == "sys_choice":
                return PRIORITY if query.startswith("name=task^") else []
            return [{"super_class.name": "task"}] if "name=incident" in query else []

        patcher, calls = _reads(answers)
        with patcher:
            value, refusal = resolve_choice(
                mock_config, MagicMock(), table="incident", element="priority", requested="3"
            )
        assert (value, refusal) == ("3", None)
        assert [c[0] for c in calls] == ["sys_choice", "sys_db_object", "sys_choice"]

    def test_numbered_label_is_asked_for_by_its_word(self, mock_config):
        patcher, _ = _reads(lambda t, q: PRIORITY if t == "sys_choice" else [])
        with patcher:
            value, _ = resolve_choice(
                mock_config, MagicMock(), table="t", element="priority", requested="moderate"
            )
        assert value == "3"

    def test_an_unknown_value_lists_the_real_ones_in_order(self, mock_config):
        rows = [{"value": "4", "label": "Canceled"}, {"value": "-4", "label": "Assess"}]
        patcher, _ = _reads(lambda t, q: rows if t == "sys_choice" else [])
        with patcher:
            value, refusal = resolve_choice(
                mock_config, MagicMock(), table="change_request", element="state", requested="2"
            )
        assert value is None
        assert refusal["error"] == "UNKNOWN_CHOICE"
        assert "-4=Assess, 4=Canceled" in refusal["message"]

    def test_no_choices_anywhere_up_the_chain_is_not_a_pass(self, mock_config):
        patcher, _ = _reads(lambda t, q: [])
        with patcher:
            value, refusal = resolve_choice(
                mock_config, MagicMock(), table="x", element="state", requested="1"
            )
        assert value is None and refusal["error"] == "CHOICE_UNVERIFIED"

    def test_an_unreadable_list_is_not_a_pass(self, mock_config):
        with patch(
            "servicenow_mcp.services.choices.sn_query_page", side_effect=RuntimeError("403")
        ):
            value, refusal = resolve_choice(
                mock_config, MagicMock(), table="x", element="state", requested="1"
            )
        assert value is None and refusal["error"] == "CHOICE_UNVERIFIED"
        assert "403" in refusal["message"]

    def test_payload_fields_resolve_in_place_and_absent_ones_are_skipped(
        self, mock_config, live_choices
    ):
        data = {"state": "Assess", "risk": "moderate", "short_description": "x"}
        assert (
            resolve_payload_choices(
                mock_config,
                MagicMock(),
                table="change_request",
                data=data,
                elements=("state", "risk", "impact"),
            )
            is None
        )
        assert data == {"state": "-4", "risk": "3", "short_description": "x"}


@pytest.mark.usefixtures("live_choices")
class TestServicesRefuseBeforeWriting:
    def test_change_create_with_a_bad_type_sends_nothing(self, mock_config):
        auth = MagicMock()
        result = change_svc.create(mock_config, auth, short_description="s", type="major")
        assert result["error"] == "UNKNOWN_CHOICE"
        auth.make_request.assert_not_called()

    def test_change_update_resolves_a_state_word(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value.json.return_value = {"result": {}}
        with patch("servicenow_mcp.services.change.invalidate_query_cache"):
            change_svc.update(mock_config, auth, change_id="c1", state="Implement")
        assert auth.make_request.call_args.kwargs["json"]["state"] == "-1"

    def test_incident_resolve_with_an_unknown_close_code_sends_nothing(self, mock_config):
        auth = MagicMock()
        with patch(
            "servicenow_mcp.services.incident.resolve_incident_sys_id", return_value=("i1", None)
        ):
            result = incident_svc.resolve(
                mock_config,
                auth,
                incident_id="i1",
                resolution_code="Fixed it",
                resolution_notes="n",
            )
        assert result["error"] == "UNKNOWN_CHOICE"
        auth.make_request.assert_not_called()

    def test_incident_create_with_a_bad_urgency_sends_nothing(self, mock_config):
        auth = MagicMock()
        result = incident_svc.create(mock_config, auth, short_description="s", urgency="asap")
        assert result.success is False
        assert "incident.urgency" in result.message
        auth.make_request.assert_not_called()


@pytest.mark.usefixtures("live_choices")
class TestApprovalToolsRefuseBeforeTheFirstWrite:
    """A bad target state must not leave the approval changed and the change not."""

    @staticmethod
    def _auth_with_pending_approval():
        return MagicMock()

    @pytest.fixture(autouse=True)
    def _pending(self):
        row = {"sys_id": "aaaa1111bbbb2222cccc3333dddd4444", "state": "requested"}
        with patch(
            "servicenow_mcp.tools.change_tools._find_change_approval", return_value=(row, None)
        ):
            yield

    def _writes(self, auth):
        return list(auth.make_request.call_args_list)

    def test_approve(self, mock_config):
        auth = self._auth_with_pending_approval()
        result = approve_change(
            mock_config, auth, ApproveChangeParams(change_id="c1", change_state="done")
        )
        assert result["error"] == "UNKNOWN_CHANGE_STATE"
        assert self._writes(auth) == []

    def test_reject(self, mock_config):
        auth = self._auth_with_pending_approval()
        result = reject_change(
            mock_config,
            auth,
            RejectChangeParams(change_id="c1", rejection_reason="r", change_state="nope"),
        )
        assert result["error"] == "UNKNOWN_CHANGE_STATE"
        assert self._writes(auth) == []

    def test_submit(self, mock_config):
        auth = MagicMock()
        result = submit_change_for_approval(
            mock_config, auth, SubmitChangeForApprovalParams(change_id="c1", change_state="go")
        )
        assert result["error"] == "UNKNOWN_CHANGE_STATE"
        auth.make_request.assert_not_called()
