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
from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change

PRIORITY = [{"value": "1", "label": "1 - Critical"}, {"value": "3", "label": "3 - Moderate"}]


def _reads(rows, ancestry=("t",)):
    """One hierarchy walk, then ONE sys_choice read over every table in it.

    ``rows`` are (declaring table, row) pairs: the read returns choices from
    the whole chain, and the nearest table that declares any must win.
    """
    calls = []

    def fake(config, auth_manager, **kw):
        calls.append(kw)
        return [{**row, "name": table} for table, row in rows], None

    walk = patch(
        "servicenow_mcp.services.choices.table_ancestry",
        return_value=list(ancestry) if ancestry is not None else None,
    )
    read = patch("servicenow_mcp.services.choices.sn_query_page", side_effect=fake)
    return walk, read, calls


def _resolve(rows, ancestry=("t",), **kw):
    walk, read, calls = _reads(rows, ancestry)
    with walk, read:
        result = resolve_choice(_cfg(), MagicMock(), **kw)
    return result, calls


def _cfg():
    cfg = MagicMock()
    cfg.instance_url = "https://test.service-now.com"
    return cfg


class TestResolveChoice:
    def test_inherits_choices_from_the_parent_table(self):
        # incident declares no priority choices of its own; task does.
        (value, refusal), calls = _resolve(
            [("task", r) for r in PRIORITY],
            ancestry=("incident", "task"),
            table="incident",
            element="priority",
            requested="3",
        )
        assert (value, refusal) == ("3", None)
        assert len(calls) == 1
        assert calls[0]["query"].startswith("nameINincident,task^element=priority^")
        assert calls[0]["fail_silently"] is False

    def test_the_nearest_table_wins_over_its_parent(self):
        # A child that redeclares the column's choices replaces the parent's list.
        rows = [("task", {"value": "1", "label": "Parent"}), ("incident", PRIORITY[1])]
        (value, refusal), _ = _resolve(
            rows,
            ancestry=("incident", "task"),
            table="incident",
            element="priority",
            requested="1",
        )
        assert value is None and refusal["error"] == "UNKNOWN_CHOICE"
        assert "3=3 - Moderate" in refusal["message"] and "Parent" not in refusal["message"]

    def test_numbered_label_is_asked_for_by_its_word(self):
        (value, _), _ = _resolve(
            [("t", r) for r in PRIORITY], table="t", element="priority", requested="moderate"
        )
        assert value == "3"

    def test_an_unknown_value_lists_the_real_ones_in_order(self):
        rows = [
            ("t", {"value": "4", "label": "Canceled"}),
            ("t", {"value": "-4", "label": "Assess"}),
        ]
        (value, refusal), _ = _resolve(rows, table="t", element="state", requested="2")
        assert value is None
        assert refusal["error"] == "UNKNOWN_CHOICE"
        assert "-4=Assess, 4=Canceled" in refusal["message"]

    def test_no_choices_anywhere_up_the_chain_is_not_a_pass(self):
        (value, refusal), _ = _resolve([], table="x", element="state", requested="1")
        assert value is None and refusal["error"] == "CHOICE_UNVERIFIED"

    def test_an_unreadable_hierarchy_is_not_a_pass(self):
        (value, refusal), calls = _resolve(
            PRIORITY, ancestry=None, table="x", element="state", requested="1"
        )
        assert value is None and refusal["error"] == "CHOICE_UNVERIFIED"
        assert calls == []

    def test_an_unreadable_list_is_not_a_pass(self):
        walk, read, _ = _reads([])
        with walk, read as q:
            q.side_effect = RuntimeError("403")
            value, refusal = resolve_choice(
                _cfg(), MagicMock(), table="x", element="state", requested="1"
            )
        assert value is None and refusal["error"] == "CHOICE_UNVERIFIED"
        assert "403" in refusal["message"]


class TestDependentChoices:
    """alm_asset.substatus: each option belongs to one install_status."""

    ROWS = [
        ("alm_asset", {"value": "available", "label": "Available", "dependent_value": "6"}),
        ("alm_asset", {"value": "reserved", "label": "Reserved", "dependent_value": "6"}),
        (
            "alm_asset",
            {"value": "pending_repair", "label": "Pending repair", "dependent_value": "9"},
        ),
    ]

    def _sub(self, requested, parent):
        return _resolve(
            self.ROWS,
            ancestry=("alm_hardware", "alm_asset"),
            table="alm_hardware",
            element="substatus",
            requested=requested,
            depends_on=parent,
        )[0]

    def test_an_option_of_the_parent_status_resolves(self):
        assert self._sub("Reserved", "6") == ("reserved", None)

    def test_an_option_of_another_status_is_refused_and_lists_only_this_ones(self):
        value, refusal = self._sub("pending_repair", "6")
        assert value is None and refusal["error"] == "UNKNOWN_CHOICE"
        assert "(for 6)" in refusal["message"]
        assert "available=Available" in refusal["message"]
        assert "Pending repair" not in refusal["message"]

    def test_a_status_with_no_options_is_not_a_pass(self):
        value, refusal = self._sub("anything", "1")
        assert value is None and refusal["error"] == "CHOICE_UNVERIFIED"


class TestPayload:
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
        with (
            patch("servicenow_mcp.services.change.invalidate_query_cache"),
            patch("servicenow_mcp.services.change.sn_query_page", return_value=([], None)),
        ):
            change_svc.update(mock_config, auth, change_id="c1", state="Implement")
        put = next(c for c in auth.make_request.call_args_list if c.args[0] == "PUT")
        assert put.kwargs["json"]["state"] == "-1"

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
        from servicenow_mcp.tools.incident_tools import ManageIncidentParams, manage_incident

        result = manage_incident(
            mock_config,
            auth,
            ManageIncidentParams(action="create", short_description="s", urgency="asap"),
        )
        assert result["success"] is False
        assert "incident.urgency" in result["message"]
        auth.make_request.assert_not_called()


@pytest.mark.usefixtures("live_choices")
class TestApprovalActionsRefuseBeforeTheFirstWrite:
    """A bad target state must not leave the approval changed and the change not."""

    @pytest.fixture(autouse=True)
    def _pending(self):
        row = {"sys_id": "aaaa1111bbbb2222cccc3333dddd4444", "state": "requested"}
        with patch(
            "servicenow_mcp.tools.change_tools._find_change_approval", return_value=(row, None)
        ):
            yield

    @pytest.mark.parametrize(
        "action,extra",
        [("approve", {}), ("reject", {"work_notes": "r"}), ("submit", {})],
    )
    def test_bad_state(self, mock_config, action, extra):
        auth = MagicMock()
        params = ManageChangeParams(action=action, change_id="c1", state="nope", **extra)
        result = manage_change(mock_config, auth, params)
        assert result["error"] == "UNKNOWN_CHANGE_STATE"
        auth.make_request.assert_not_called()

    def test_state_label_resolves_to_its_code(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value.json.return_value = {"result": {}}
        # The approval write and its caller check live in decide_approval (own tests);
        # here it is allowed, so only the change PATCH and its state code remain.
        with (
            patch("servicenow_mcp.tools.change_tools.invalidate_query_cache"),
            patch(
                "servicenow_mcp.tools.change_tools.decide_approval",
                return_value={"success": True, "applied": True},
            ),
        ):
            manage_change(mock_config, auth, ManageChangeParams(action="approve", change_id="c1"))
        change_patch = auth.make_request.call_args_list[-1]
        assert change_patch.kwargs["json"] == {"state": "-1"}


class TestApprovalActionParams:
    def test_reject_needs_a_reason(self):
        with pytest.raises(ValueError, match="rejection reason"):
            ManageChangeParams(action="reject", change_id="c1")

    @pytest.mark.parametrize("action", ["submit", "approve", "reject"])
    def test_change_id_is_required(self, action):
        with pytest.raises(ValueError, match="change_id"):
            ManageChangeParams(action=action, work_notes="r")

    def test_reject_reason_reaches_the_approval_and_the_change(self, mock_config, live_choices):
        auth = MagicMock()
        auth.make_request.return_value.json.return_value = {"result": {}}
        row = {"sys_id": "aaaa1111bbbb2222cccc3333dddd4444", "state": "requested"}
        with (
            patch(
                "servicenow_mcp.tools.change_tools._find_change_approval", return_value=(row, None)
            ),
            patch("servicenow_mcp.tools.change_tools.invalidate_query_cache"),
            patch(
                "servicenow_mcp.tools.change_tools.decide_approval",
                return_value={"success": True, "applied": True},
            ) as decide,
        ):
            result = manage_change(
                mock_config,
                auth,
                ManageChangeParams(action="reject", change_id="c1", work_notes="no window"),
            )
        assert result["success"] is True
        assert decide.call_args.kwargs["decision"] == "rejected"
        assert decide.call_args.kwargs["comments"] == "no window"
        (change,) = [c.kwargs["json"] for c in auth.make_request.call_args_list]
        assert change["state"] == "4" and "no window" in change["work_notes"]
