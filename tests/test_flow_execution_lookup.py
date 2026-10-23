"""manage_flow_designer: get_executions filters and read_action's action_ref.

get_executions used to demand flow_id, so a lookup by context_id or by the
triggering record — both supported by the reader underneath — was rejected
before it ran. source_record was LIKE-matched as a display value against a
column that holds a sys_id, so a lookup by number always answered "none".
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    GetFlowExecutionsParams,
    get_flow_executions,
)
from servicenow_mcp.tools.flow_tools import ManageFlowDesignerParams, manage_flow_designer
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig

_REC = "aaaa1111bbbb2222cccc3333dddd4444"
_ACT = "bbbb2222cccc3333dddd4444eeee5555"
_QP = "servicenow_mcp.tools.flow_designer_tools.sn_query_page"


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"flow_id": "f1"},
        {"context_id": _REC},
        {"flow_name": "My Flow"},
        {"source_record": "TASK0001"},
        {"exec_state": "Error"},
        {"errors_only": True},
    ],
)
def test_get_executions_accepts_any_one_filter(kwargs):
    ManageFlowDesignerParams(action="get_executions", **kwargs)


def test_get_executions_with_no_filter_is_refused():
    with pytest.raises(ValidationError, match="get_executions needs a filter"):
        ManageFlowDesignerParams(action="get_executions")


def test_read_action_accepts_action_ref_instead_of_flow_id():
    ManageFlowDesignerParams(action="read_action", action_ref="My Action")


def test_read_action_with_neither_is_refused():
    with pytest.raises(ValidationError, match="read_action requires"):
        ManageFlowDesignerParams(action="read_action")


# --- source_record ---------------------------------------------------------


def test_a_sys_id_source_record_is_matched_exactly_with_no_lookup():
    with patch(_QP, return_value=([], 0)) as qp:
        result = get_flow_executions(
            _cfg(), MagicMock(), GetFlowExecutionsParams(source_record=_REC)
        )
    assert result["success"] is True
    assert qp.call_count == 1
    assert qp.call_args[1]["query"] == f"source_recordIN{_REC}"


def test_a_number_resolves_in_the_named_source_table():
    rows = [{"sys_id": _REC, "number": "REQ0001"}]
    with patch(_QP, side_effect=[(rows, 1), ([{"sys_id": "ctx"}], 1)]) as qp:
        result = get_flow_executions(
            _cfg(),
            MagicMock(),
            GetFlowExecutionsParams(source_record="REQ0001", source_table="x_myapp_request"),
        )
    assert result["success"] is True
    assert qp.call_args_list[0][1]["table"] == "x_myapp_request"
    assert f"source_recordIN{_REC}" in qp.call_args[1]["query"]


def test_an_unknown_number_is_an_error_not_an_empty_history():
    with patch(_QP, return_value=([], 0)) as qp:
        result = get_flow_executions(
            _cfg(), MagicMock(), GetFlowExecutionsParams(source_record="TASK9999")
        )
    assert result["success"] is False
    assert "source_table" in result["error"]
    assert qp.call_count == 1  # the executions table was never read


def test_rows_that_do_not_carry_the_number_are_not_taken_as_a_match():
    # A table with no number column drops the condition and returns arbitrary
    # rows; the first of them must not become "the" triggering record.
    rows = [{"sys_id": _REC, "number": ""}]
    with patch(_QP, return_value=(rows, 1)):
        result = get_flow_executions(
            _cfg(),
            MagicMock(),
            GetFlowExecutionsParams(source_record="REQ0001", source_table="x_myapp_thing"),
        )
    assert result["success"] is False
    assert "sys_id" in result["error"]


def test_manage_tool_passes_source_table_through():
    rows = [{"sys_id": _REC, "number": "REQ0001"}]
    with patch(_QP, side_effect=[(rows, 1), ([], 0)]) as qp:
        manage_flow_designer(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowDesignerParams(
                action="get_executions", source_record="REQ0001", source_table="x_myapp_request"
            ),
        )
    assert qp.call_args_list[0][1]["table"] == "x_myapp_request"


# --- read_action by action_ref ---------------------------------------------

_FT_QP = "servicenow_mcp.tools.flow_tools.sn_query_page"
_PF = "servicenow_mcp.tools.flow_tools._try_processflow_action"
_PF_OK = {"action": {"name": "My Action"}, "steps": []}


def test_action_ref_sys_id_is_read_directly():
    with patch(_FT_QP) as qp, patch(_PF, return_value=_PF_OK) as pf:
        result = manage_flow_designer(
            _cfg(), MagicMock(), ManageFlowDesignerParams(action="read_action", action_ref=_ACT)
        )
    assert result["success"] is True
    qp.assert_not_called()
    assert pf.call_args[0][2] == _ACT


def test_action_ref_exact_name_resolves_to_its_sys_id():
    rows = [{"sys_id": _ACT, "name": "My Action", "internal_name": "my_action"}]
    with patch(_FT_QP, return_value=(rows, 1)), patch(_PF, return_value=_PF_OK) as pf:
        result = manage_flow_designer(
            _cfg(),
            MagicMock(),
            ManageFlowDesignerParams(action="read_action", action_ref="my_action"),
        )
    assert result["success"] is True
    assert pf.call_args[0][2] == _ACT


def test_action_ref_naming_two_actions_asks_which():
    rows = [
        {"sys_id": _ACT, "name": "My Action", "internal_name": "a1"},
        {"sys_id": _REC, "name": "My Action", "internal_name": "a2"},
    ]
    with patch(_FT_QP, return_value=(rows, 2)), patch(_PF) as pf:
        result = manage_flow_designer(
            _cfg(),
            MagicMock(),
            ManageFlowDesignerParams(action="read_action", action_ref="My Action"),
        )
    assert result["success"] is False
    assert "2 actions" in result["error"]
    pf.assert_not_called()


def test_action_ref_with_no_exact_match_is_not_fuzzy_matched():
    rows = [{"sys_id": _ACT, "name": "My Action Extended", "internal_name": "x"}]
    with patch(_FT_QP, return_value=(rows, 1)), patch(_PF) as pf:
        result = manage_flow_designer(
            _cfg(),
            MagicMock(),
            ManageFlowDesignerParams(action="read_action", action_ref="My Action"),
        )
    assert result["success"] is False
    assert "No action is named" in result["error"]
    pf.assert_not_called()


# --- get_detail with a flow_id that is not a sys_id -------------------------


def test_a_truncated_flow_id_beside_a_flow_name_resolves_by_name():
    with (
        patch(
            "servicenow_mcp.tools.flow_tools._resolve_flow_id_by_name",
            return_value={"sys_id": _REC},
        ) as by_name,
        patch(
            "servicenow_mcp.tools.flow_tools.get_flow_details",
            return_value={"success": True, "flow": {"sys_id": _REC}},
        ) as details,
    ):
        manage_flow_designer(
            _cfg(),
            MagicMock(),
            ManageFlowDesignerParams(action="get_detail", flow_id="aaaa1111", flow_name="My Flow"),
        )
    by_name.assert_called_once()
    assert details.call_args[0][2].flow_id == _REC


def test_a_full_sys_id_is_used_as_given_even_with_a_name():
    # _ACT, not _REC: a successful get_detail is cached per sys_id, and the test
    # above already cached _REC.
    with (
        patch("servicenow_mcp.tools.flow_tools._resolve_flow_id_by_name") as by_name,
        patch(
            "servicenow_mcp.tools.flow_tools.get_flow_details",
            return_value={"success": True, "flow": {"sys_id": _ACT}},
        ) as details,
    ):
        manage_flow_designer(
            _cfg(),
            MagicMock(),
            ManageFlowDesignerParams(action="get_detail", flow_id=_ACT, flow_name="My Flow"),
        )
    by_name.assert_not_called()
    assert details.call_args[0][2].flow_id == _ACT
