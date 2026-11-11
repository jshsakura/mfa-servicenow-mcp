"""download_portal_sources(portal=/page_ids=) end to end, mocked at the query layer."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import DownloadPortalSourcesParams, download_portal_sources
from servicenow_mcp.utils.config import ServerConfig

OOTB = "aaaa1111bbbb2222cccc3333dddd4444"
OURS = "eeee5555ffff6666aaaa7777bbbb8888"


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


def _widget(sys_id, wid, package, package_class, vendor="", klass="sp_widget"):
    return {
        "sys_id": sys_id,
        "id": wid,
        "name": wid,
        "template": "<div></div>",
        "script": "",
        "client_script": "",
        "link": "",
        "css": "",
        "sys_class_name": klass,
        "sys_package": package,
        "sys_package.sys_class_name": package_class,
        "sys_scope.vendor": vendor,
        "sys_updated_on": "2026-01-01 00:00:00",
        "sys_mod_count": "1",
    }


def _rows(*_args, table, query, fields, **_kw):
    if table == "sp_widget":
        assert "sys_package.sys_class_name" in fields, "origin is read in the same query"
        return [
            _widget(
                OOTB,
                "employee-center-header",
                "pkg1",
                "sys_store_app",
                "ServiceNow",
                klass="sp_header_footer",
            ),
            _widget(OURS, "my-card", "global", "sys_scope"),
        ]
    return []


@patch("servicenow_mcp.tools.portal_tools._sn_query_all", side_effect=_rows)
@patch(
    "servicenow_mcp.services.portal_slice.resolve_slice",
    return_value={
        "widget_sys_ids": [OOTB, OURS],
        "widget_source": {OOTB: "theme header", OURS: "page index"},
        "pages": [{"sys_id": "p1", "id": "index"}],
        "portal": {"sys_id": "portal1", "url_suffix": "esc", "title": "Employee Center"},
        "themes": [{"sys_id": "theme1", "name": "Coral", "scope": "sn_ex_sp"}],
        "unresolved": [],
        "complete": True,
        "warnings": [],
    },
)
def test_a_portal_downloads_its_widgets_and_marks_servicenow_owned(_slice, _q, config, tmp_path):
    result = download_portal_sources(
        config,
        MagicMock(),
        DownloadPortalSourcesParams(
            portal="esc",
            output_dir=str(tmp_path / "esc"),
            include_linked_script_includes=False,
            include_linked_angular_providers=False,
        ),
        emit_phases=False,
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 2
    assert result["summary"]["origin"] == {"servicenow": 1, "customer": 1}
    owned = result["servicenow_owned"]
    assert [o["id"] for o in owned] == ["employee-center-header"]
    assert "clone_header_footer" in owned[0]["clone"]
    assert result["slice"]["complete"] is True
    assert result["slice"]["theme_download"] == [
        "download_server_sources(scope='sn_ex_sp', families=['theme'], sys_ids=['theme1'])"
    ]
    meta = json.loads(
        (tmp_path / "esc" / "sp_widget" / "employee-center-header" / "_widget.json").read_text()
    )
    assert meta["origin"]["verdict"] == "servicenow"


@patch("servicenow_mcp.tools.portal_tools._sn_query_all", side_effect=_rows)
@patch(
    "servicenow_mcp.services.portal_slice.resolve_slice",
    return_value={
        "widget_sys_ids": [],
        "widget_source": {},
        "pages": [],
        "portal": None,
        "themes": [],
        "unresolved": ["page:nope"],
        "complete": False,
        "warnings": ["Not found: page:nope"],
    },
)
def test_a_slice_that_resolves_to_nothing_says_so(_slice, _q, config, tmp_path):
    result = download_portal_sources(
        config,
        MagicMock(),
        DownloadPortalSourcesParams(page_ids=["nope"], output_dir=str(tmp_path / "x")),
        emit_phases=False,
    )

    assert result["success"] is False
    assert result["slice"]["unresolved"] == ["page:nope"]
