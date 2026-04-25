"""Tests for sn_resolve_url — URL parser, no network calls."""

from servicenow_mcp.tools.sn_api import SnResolveUrlParams, _resolve_servicenow_url, sn_resolve_url
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

INSTANCE = "https://acme.service-now.com"
SID = "a" * 32


def _config():
    return ServerConfig(
        instance_url=INSTANCE,
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


class TestNavToUrl:
    def test_incident_record_form_via_nav_to(self):
        url = f"{INSTANCE}/nav_to.do?uri=incident.do%3Fsys_id%3D{SID}"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "incident"
        assert out["sys_id"] == SID
        assert out["context"] == "record_form"
        assert out["suggested_tool"] == "manage_incident"
        assert out["suggested_action"] == "get"

    def test_change_request_via_nav_to(self):
        url = f"{INSTANCE}/nav_to.do?uri=change_request.do%3Fsys_id%3D{SID}"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "change_request"
        assert out["sys_id"] == SID
        assert out["suggested_tool"] == "manage_change"


class TestDirectFormUrl:
    def test_incident_form_direct(self):
        url = f"{INSTANCE}/incident.do?sys_id={SID}"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "incident"
        assert out["sys_id"] == SID
        assert out["context"] == "record_form"

    def test_custom_table_falls_through(self):
        url = f"{INSTANCE}/x_acme_request.do?sys_id={SID}"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "x_acme_request"
        assert out["sys_id"] == SID
        # Custom table → suggested_tool defaults to sn_query
        assert out["suggested_tool"] == "sn_query"


class TestListUrl:
    def test_incident_list(self):
        url = f"{INSTANCE}/incident_list.do"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "incident"
        assert out["context"] == "record_list"
        assert out["suggested_action"] == "list"


class TestPortalUrls:
    def test_service_portal_widget_editor(self):
        url = f"{INSTANCE}/sp?id=widget_editor&sys_id={SID}"
        out = _resolve_servicenow_url(url)
        assert out["context"] == "portal_page"
        assert out["page"] == "widget_editor"
        assert out["sys_id"] == SID

    def test_employee_center(self):
        url = f"{INSTANCE}/esc?id=catalog"
        out = _resolve_servicenow_url(url)
        assert out["context"] == "esc_page"
        assert out["page"] == "catalog"


class TestKbUrl:
    def test_kb_view(self):
        url = f"{INSTANCE}/kb_view.do?sysparm_article=KB0010001"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "kb_knowledge"
        assert out["article_number"] == "KB0010001"
        assert out["context"] == "kb_article"


class TestStudioUrl:
    def test_studio_with_scope_in_fragment(self):
        url = f"{INSTANCE}/sys_app_studio.do#/x_acme_app/scripts/foo"
        out = _resolve_servicenow_url(url)
        assert out["table"] == "sys_app"
        assert out["context"] == "studio"
        # Studio fragment scope detection is best-effort; just verify it runs
        assert "scope" in out


class TestUnknown:
    def test_garbage_url_does_not_crash(self):
        out = _resolve_servicenow_url("https://example.com/random/path")
        assert out["table"] is None
        assert out["context"] == "unknown"

    def test_empty_string(self):
        out = _resolve_servicenow_url("")
        assert out["table"] is None
        assert out["context"] == "unknown"


class TestRegisteredTool:
    def test_invokes_via_pydantic_params(self):
        cfg = _config()
        out = sn_resolve_url(
            cfg, None, SnResolveUrlParams(url=f"{INSTANCE}/incident.do?sys_id={SID}")
        )
        assert out["table"] == "incident"
        assert out["sys_id"] == SID
