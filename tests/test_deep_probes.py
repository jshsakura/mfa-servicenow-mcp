"""Tests for sn_health(deep=True) — upgrade-breakage early warning.

Pinned invariants:
- Probes exercise the undocumented APIs exactly the way the tools call them
  (concoursepicker current-shape parse, processflow flow payload shape).
- basic/oauth auth skips with a clear note (those sessions never call these
  endpoints, so there is nothing to break) — zero network.
- A probe failure/exception can never fail the health check.
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.sn_api import _deep_api_probes
from servicenow_mcp.utils.config import ServerConfig


@pytest.fixture
def basic_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "pw"}},
    )


@pytest.fixture
def browser_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "browser", "browser": {}},
    )


class TestDeepProbes:
    def test_basic_auth_skips_without_network(self, basic_config):
        auth = MagicMock()
        result = _deep_api_probes(basic_config, auth)
        assert "skipped" in result
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.tools.sn_api.sn_query_page")
    @patch("servicenow_mcp.tools.session_context_tools._get_current_raw")
    def test_healthy_instance_probes_ok(self, mock_current, mock_page, browser_config):
        mock_current.return_value = ({"sys_id": "scope-1", "name": "x_app"}, {"status": 200})
        mock_page.return_value = ([{"sys_id": "flow-1"}], None)
        auth = MagicMock()
        auth.make_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": {"data": {"name": "My Flow", "actions": []}}},
        )

        probes = _deep_api_probes(browser_config, auth)
        assert probes["concoursepicker"]["ok"] is True
        assert probes["processflow"]["ok"] is True

    @patch("servicenow_mcp.tools.session_context_tools._get_current_raw")
    def test_concoursepicker_shape_drift_is_flagged(self, mock_current, browser_config):
        # Endpoint answers 200 but the 'current' shape no longer parses — the
        # exact failure mode a ServiceNow upgrade produced before (set_app saga).
        mock_current.return_value = ({}, {"status": 200})
        with patch("servicenow_mcp.tools.sn_api.sn_query_page", return_value=([], None)):
            probes = _deep_api_probes(browser_config, MagicMock())
        assert probes["concoursepicker"]["ok"] is False
        assert "upgrade" in probes["concoursepicker"]["note"]

    @patch("servicenow_mcp.tools.sn_api.sn_query_page")
    @patch("servicenow_mcp.tools.session_context_tools._get_current_raw")
    def test_processflow_error_wrapper_is_flagged(self, mock_current, mock_page, browser_config):
        # Yokohama-style: 200 with an errorMessage wrapper instead of flow data.
        mock_current.return_value = ({"sys_id": "scope-1"}, {"status": 200})
        mock_page.return_value = ([{"sys_id": "flow-1"}], None)
        auth = MagicMock()
        auth.make_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": {"errorMessage": "plugin inactive", "errorCode": 7}},
        )

        probes = _deep_api_probes(browser_config, auth)
        assert probes["processflow"]["ok"] is False
        assert "upgrade" in probes["processflow"]["note"]

    @patch("servicenow_mcp.tools.sn_api.sn_query_page")
    @patch("servicenow_mcp.tools.session_context_tools._get_current_raw")
    def test_no_flows_is_ok_not_failure(self, mock_current, mock_page, browser_config):
        mock_current.return_value = ({"sys_id": "scope-1"}, {"status": 200})
        mock_page.return_value = ([], None)
        probes = _deep_api_probes(browser_config, MagicMock())
        assert probes["processflow"]["ok"] is True
        assert "no flows" in probes["processflow"]["note"]

    @patch("servicenow_mcp.tools.session_context_tools._get_current_raw")
    def test_probe_exception_never_raises(self, mock_current, browser_config):
        mock_current.side_effect = RuntimeError("boom")
        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=RuntimeError("boom2")):
            probes = _deep_api_probes(browser_config, MagicMock())
        assert probes["concoursepicker"]["ok"] is False
        assert probes["processflow"]["ok"] is False
