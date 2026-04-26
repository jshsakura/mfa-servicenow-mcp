"""Tests for services/portal_component.py — all 6 create functions."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services.portal_component import (
    create_angular_provider,
    create_css_theme,
    create_header_footer,
    create_ng_template,
    create_ui_page,
    create_widget,
)
from servicenow_mcp.utils.config import ServerConfig

SCOPE = "scope-svc-test"


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# create_widget
# ---------------------------------------------------------------------------
class TestCreateWidget:
    @patch("servicenow_mcp.services.portal_component.sn_query_page")
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_minimal(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_query.return_value = ([], 0)
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "w1", "name": "My Widget", "id": "my_widget"}}
        )
        result = create_widget(mock_config, mock_auth, name="My Widget", scope=SCOPE)
        assert result["success"] is True
        assert result["sys_id"] == "w1"
        assert result["name"] == "My Widget"

    @patch("servicenow_mcp.services.portal_component.sn_query_page")
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_all_optional_fields(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_query.return_value = ([], 0)
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "w2", "name": "Full", "id": "full"}}
        )
        result = create_widget(
            mock_config,
            mock_auth,
            name="Full",
            scope=SCOPE,
            widget_id="full",
            template="<div/>",
            css=".a{}",
            script="s()",
            client_script="c()",
            link="l()",
            internal=True,
            data_table="incident",
            description="desc",
        )
        assert result["success"] is True
        body = mock_auth.make_request.call_args[1]["json"]
        assert body["internal"] == "true"
        assert body["data_table"] == "incident"

    @patch(
        "servicenow_mcp.services.portal_component.sn_query_page",
        return_value=([{"sys_id": "dup", "sys_scope": "s"}], 1),
    )
    def test_duplicate_name_blocked(self, mock_query, mock_config, mock_auth):
        result = create_widget(mock_config, mock_auth, name="Existing", scope=SCOPE)
        assert result["success"] is False
        assert "already exists" in result["message"]

    @patch("servicenow_mcp.services.portal_component.sn_query_page")
    def test_duplicate_widget_id_blocked(self, mock_query, mock_config, mock_auth):
        mock_query.side_effect = [
            ([], 0),
            ([{"sys_id": "dup-id", "sys_scope": "s"}], 1),
        ]
        result = create_widget(mock_config, mock_auth, name="W", scope=SCOPE, widget_id="taken_id")
        assert result["success"] is False
        assert "already exists" in result["message"]

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    def test_api_error(self, mock_query, mock_config, mock_auth):
        mock_auth.make_request.side_effect = Exception("Fail")
        result = create_widget(mock_config, mock_auth, name="Bad", scope=SCOPE)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_angular_provider
# ---------------------------------------------------------------------------
class TestCreateAngularProvider:
    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_success(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "ap1", "name": "mySvc", "type": "factory"}}
        )
        result = create_angular_provider(
            mock_config, mock_auth, name="mySvc", script="x", scope=SCOPE
        )
        assert result["success"] is True
        assert result["sys_id"] == "ap1"

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_provider_type_and_description(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "ap2", "name": "svc", "type": "service"}}
        )
        result = create_angular_provider(
            mock_config,
            mock_auth,
            name="svc",
            script="x",
            scope=SCOPE,
            provider_type="service",
            description="desc",
        )
        assert result["success"] is True
        body = mock_auth.make_request.call_args[1]["json"]
        assert body["type"] == "service"
        assert body["description"] == "desc"

    @patch(
        "servicenow_mcp.services.portal_component.sn_query_page",
        return_value=([{"sys_id": "dup"}], 1),
    )
    def test_duplicate_blocked(self, mock_query, mock_config, mock_auth):
        result = create_angular_provider(
            mock_config, mock_auth, name="dup", script="x", scope=SCOPE
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_header_footer
# ---------------------------------------------------------------------------
class TestCreateHeaderFooter:
    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_minimal(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "hf1", "name": "My Header"}}
        )
        result = create_header_footer(mock_config, mock_auth, name="My Header", scope=SCOPE)
        assert result["success"] is True
        assert result["name"] == "My Header"

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_with_template_css(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "hf2", "name": "Footer"}}
        )
        result = create_header_footer(
            mock_config, mock_auth, name="Footer", scope=SCOPE, template="<footer/>", css=".f{}"
        )
        assert result["success"] is True
        body = mock_auth.make_request.call_args[1]["json"]
        assert "template" in body
        assert "css" in body

    @patch(
        "servicenow_mcp.services.portal_component.sn_query_page",
        return_value=([{"sys_id": "dup"}], 1),
    )
    def test_duplicate_blocked(self, mock_query, mock_config, mock_auth):
        result = create_header_footer(mock_config, mock_auth, name="Existing", scope=SCOPE)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_css_theme
# ---------------------------------------------------------------------------
class TestCreateCssTheme:
    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_minimal(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "cs1", "name": "Dark"}}
        )
        result = create_css_theme(mock_config, mock_auth, name="Dark", scope=SCOPE)
        assert result["success"] is True

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_with_css(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "cs2", "name": "Light"}}
        )
        result = create_css_theme(
            mock_config, mock_auth, name="Light", scope=SCOPE, css="body{color:red}"
        )
        assert result["success"] is True
        body = mock_auth.make_request.call_args[1]["json"]
        assert body["css"] == "body{color:red}"

    @patch(
        "servicenow_mcp.services.portal_component.sn_query_page",
        return_value=([{"sys_id": "dup"}], 1),
    )
    def test_duplicate_blocked(self, mock_query, mock_config, mock_auth):
        result = create_css_theme(mock_config, mock_auth, name="Dark", scope=SCOPE)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_ng_template
# ---------------------------------------------------------------------------
class TestCreateNgTemplate:
    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_success(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "ng1", "id": "my-tpl.html"}}
        )
        result = create_ng_template(
            mock_config, mock_auth, template_id="my-tpl.html", template="<span/>", scope=SCOPE
        )
        assert result["success"] is True
        assert result["id"] == "my-tpl.html"

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_scope_in_body(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "ng2", "id": "tpl2.html"}}
        )
        result = create_ng_template(
            mock_config, mock_auth, template_id="tpl2.html", template="<p/>", scope=SCOPE
        )
        assert result["success"] is True
        body = mock_auth.make_request.call_args[1]["json"]
        assert body["sys_scope"] == SCOPE

    @patch(
        "servicenow_mcp.services.portal_component.sn_query_page",
        return_value=([{"sys_id": "dup"}], 1),
    )
    def test_duplicate_blocked(self, mock_query, mock_config, mock_auth):
        result = create_ng_template(
            mock_config, mock_auth, template_id="dup.html", template="<p/>", scope=SCOPE
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# create_ui_page
# ---------------------------------------------------------------------------
class TestCreateUiPage:
    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_minimal(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "up1", "name": "test_page"}}
        )
        result = create_ui_page(mock_config, mock_auth, name="test_page", scope=SCOPE)
        assert result["success"] is True

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    @patch("servicenow_mcp.services.portal_component.invalidate_query_cache")
    def test_all_fields(self, mock_cache, mock_query, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "up2", "name": "full_page"}}
        )
        result = create_ui_page(
            mock_config,
            mock_auth,
            name="full_page",
            scope=SCOPE,
            html="<jelly/>",
            client_script="cs()",
            processing_script="ps()",
            description="desc",
            category="general",
        )
        assert result["success"] is True
        body = mock_auth.make_request.call_args[1]["json"]
        assert body["html"] == "<jelly/>"
        assert body["client_script"] == "cs()"
        assert body["processing_script"] == "ps()"
        assert body["category"] == "general"

    @patch(
        "servicenow_mcp.services.portal_component.sn_query_page",
        return_value=([{"sys_id": "dup"}], 1),
    )
    def test_duplicate_blocked(self, mock_query, mock_config, mock_auth):
        result = create_ui_page(mock_config, mock_auth, name="existing_page", scope=SCOPE)
        assert result["success"] is False

    @patch("servicenow_mcp.services.portal_component.sn_query_page", return_value=([], 0))
    def test_api_error(self, mock_query, mock_config, mock_auth):
        mock_auth.make_request.side_effect = Exception("API error")
        result = create_ui_page(mock_config, mock_auth, name="new_page", scope=SCOPE)
        assert result["success"] is False
