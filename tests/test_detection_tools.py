import json
from unittest.mock import MagicMock

from servicenow_mcp.tools.detection_tools import (
    DetectMissingCodesParams,
    detect_missing_profit_company_codes,
)


def _make_config():
    config = MagicMock()
    config.instance_url = "https://test.service-now.com"
    config.timeout = 30
    config.request_timeout = 30
    return config


def _make_auth():
    return MagicMock()


def _mock_response(data, status=200, total_count=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.content = json.dumps(data).encode("utf-8")
    resp.raise_for_status.return_value = None
    resp.headers = {}
    if total_count is not None:
        resp.headers["X-Total-Count"] = str(total_count)
    return resp


def _mock_stats_response(count):
    return _mock_response({"result": {"stats": {"count": str(count)}}})


def test_detection_count_zero_short_circuits_without_widget_fetch():
    config = _make_config()
    auth = _make_auth()
    auth.make_request.return_value = _mock_stats_response(0)

    result = detect_missing_profit_company_codes(
        config,
        auth,
        DetectMissingCodesParams(required_codes=["2400", "5K00"], widget_prefix="hopes"),
    )

    assert result["success"] is True
    assert result["scan_summary"]["widgets_matched"] == 0
    assert result["findings"] == []
    assert auth.make_request.call_count == 1


def test_detection_count_failure_falls_back_to_no_widgets_result():
    config = _make_config()
    auth = _make_auth()
    auth.make_request.side_effect = RuntimeError("stats down")

    result = detect_missing_profit_company_codes(
        config,
        auth,
        DetectMissingCodesParams(required_codes=["2400", "5K00"], widget_prefix="hopes"),
    )

    assert result["success"] is True
    assert result["message"] == "No widgets matched the filter criteria."
    assert result["scan_summary"]["widgets_matched"] == 0


def test_detection_fetches_widgets_and_reports_missing_codes():
    config = _make_config()
    auth = _make_auth()
    widget_rows = [
        {
            "sys_id": "w1",
            "name": "BudgetWidget",
            "id": "budget_widget",
            "client_script": "if (profit_company_code == '2400') { doThing(); }",
            "script": "",
        }
    ]
    auth.make_request.side_effect = [
        _mock_stats_response(1),
        _mock_response({"result": widget_rows}, total_count=1),
    ]

    result = detect_missing_profit_company_codes(
        config,
        auth,
        DetectMissingCodesParams(
            required_codes=["2400", "5K00"],
            widget_ids=["w1"],
            include_angular_providers=False,
            output_mode="minimal",
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["widgets_scanned"] == 1
    assert result["scan_summary"]["findings_count"] == 1
    finding = result["findings"][0]
    assert finding["location"] == "widget/BudgetWidget/client_script"
    assert finding["found_codes"] == ["2400"]
    assert finding["missing_codes"] == ["5K00"]


def test_detection_skips_provider_phase_after_widget_budget_exhaustion():
    config = _make_config()
    auth = _make_auth()
    widget_rows = [
        {
            "sys_id": "w1",
            "name": "BudgetWidget",
            "id": "budget_widget",
            "client_script": "if (profit_company_code == '2400') { doThing(); }",
            "script": "",
        }
    ]
    auth.make_request.side_effect = [
        _mock_stats_response(1),
        _mock_response({"result": widget_rows}, total_count=1),
    ]

    result = detect_missing_profit_company_codes(
        config,
        auth,
        DetectMissingCodesParams(
            required_codes=["2400", "5K00"],
            widget_ids=["w1"],
            include_angular_providers=True,
            max_matches=1,
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["findings_count"] == 1
    assert result["scan_summary"]["providers_scanned"] == 0
    assert auth.make_request.call_count == 2


def test_detection_expands_to_providers_when_enabled():
    config = _make_config()
    auth = _make_auth()
    widget_rows = [
        {
            "sys_id": "w1",
            "name": "BudgetWidget",
            "id": "budget_widget",
            "client_script": "",
            "script": "",
        }
    ]
    m2m_rows = [{"sp_angular_provider": "p1"}]
    provider_rows = [
        {
            "sys_id": "p1",
            "name": "budgetProvider",
            "script": "if (profit_company_code == '2400') { doThing(); }",
        }
    ]
    auth.make_request.side_effect = [
        _mock_stats_response(1),
        _mock_response({"result": widget_rows}, total_count=1),
        _mock_response({"result": m2m_rows}, total_count=1),
        _mock_response({"result": provider_rows}, total_count=1),
    ]

    result = detect_missing_profit_company_codes(
        config,
        auth,
        DetectMissingCodesParams(
            required_codes=["2400", "5K00"],
            widget_ids=["w1"],
            include_widget_client_script=False,
            include_widget_server_script=False,
            include_angular_providers=True,
            output_mode="full",
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["providers_scanned"] == 1
    assert result["findings"][0]["source_type"] == "angular_provider"
    assert result["findings"][0]["source_name"] == "budgetProvider"
