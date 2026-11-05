"""Theme sources: portal SCSS variables and Next Experience theme/style JSON travel
the same download → diff → push path as code, and a JSON body that does not
parse is refused before any network call."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_tools import (
    _SOURCE_FAMILIES,
    SOURCE_CONFIG,
    DownloadSourcesParams,
    download_server_sources,
)
from servicenow_mcp.tools.sync_tools import (
    PushLocalComponentParams,
    _resolve_local_path,
    update_remote_from_local,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

_BODY_FIELDS = {"css_variables", "theme", "style", "css"}


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


def _rec(sys_id, ident_field, ident, **body):
    return {
        "sys_id": sys_id,
        ident_field: ident,
        "sys_scope": "x_myapp",
        "sys_scope.scope": "x_myapp",
        "sys_updated_on": "2026-04-01 12:00:00",
        "sys_updated_by": "alice",
        "sys_mod_count": "3",
        **body,
    }


_RECORDS = {
    "sp_theme": [
        _rec("aaaa1111bbbb2222cccc3333dddd4444", "name", "My Theme", css_variables="$a: 1;")
    ],
    "sp_portal": [
        _rec("bbbb2222cccc3333dddd4444eeee5555", "url_suffix", "myportal", css_variables="$b: 2;")
    ],
    "sys_ux_theme": [
        _rec("cccc3333dddd4444eeee5555ffff6666", "name", "My NX Theme", theme='{"base": {}}')
    ],
    "sys_ux_style": [
        _rec(
            "dddd4444eeee5555ffff6666aaaa7777",
            "name",
            "Colors",
            style='{"properties": {"--now-color--primary-1": "31,132,118"}}',
        )
    ],
}


def _query_all(*args, **kwargs):
    rows = _RECORDS.get(kwargs.get("table", ""), [])
    return [{k: v for k, v in r.items() if k not in _BODY_FIELDS} for r in rows]


def _query_page(*args, **kwargs):
    query = kwargs.get("query", "")
    for rows in _RECORDS.values():
        for r in rows:
            if r["sys_id"] in query:
                return ([{k: v for k, v in r.items() if k in _BODY_FIELDS}], None)
    return ([], None)


def test_theme_family_covers_portal_and_next_experience_design():
    assert set(_SOURCE_FAMILIES["theme"]) == {
        "sp_theme",
        "sp_portal",
        "sp_css",
        "sp_header_footer",
        "ux_theme",
        "ux_style",
    }
    # Field names measured on a live dictionary — a wrong one is dropped silently.
    assert SOURCE_CONFIG["sp_theme"]["source_fields"] == ["css_variables"]
    assert SOURCE_CONFIG["sp_portal"]["source_fields"] == ["css_variables"]
    assert SOURCE_CONFIG["ux_theme"] == {**SOURCE_CONFIG["ux_theme"], "table": "sys_ux_theme"}
    assert SOURCE_CONFIG["ux_theme"]["source_fields"] == ["theme"]
    assert SOURCE_CONFIG["ux_style"]["source_fields"] == ["style"]


@patch("servicenow_mcp.tools.source_tools.sn_query_all")
@patch("servicenow_mcp.tools.source_tools.sn_query_page")
def test_theme_download_writes_editable_files(mock_page, mock_all, config, tmp_path):
    mock_all.side_effect = _query_all
    mock_page.side_effect = _query_page

    result = download_server_sources(
        config,
        MagicMock(),
        DownloadSourcesParams(scope="x_myapp", output_dir=str(tmp_path), families=["theme"]),
    )

    assert result["success"] is True
    assert (tmp_path / "sp_theme" / "My_Theme" / "css_variables.scss").read_text() == "$a: 1;"
    assert (tmp_path / "sp_portal" / "myportal" / "css_variables.scss").read_text() == "$b: 2;"
    assert json.loads((tmp_path / "sys_ux_theme" / "My_NX_Theme" / "theme.json").read_text())
    style = tmp_path / "sys_ux_style" / "Colors" / "style.json"
    assert "--now-color--primary-1" in json.loads(style.read_text())["properties"]

    # The downloaded folder resolves for diff/push like any code record.
    resolved = _resolve_local_path(style.parent)
    assert (resolved.table, resolved.sys_id) == (
        "sys_ux_style",
        _RECORDS["sys_ux_style"][0]["sys_id"],
    )
    assert set(resolved.fields) == {"style"}


@patch("servicenow_mcp.tools.source_tools.sn_query_all")
@patch("servicenow_mcp.tools.source_tools.sn_query_page")
def test_invalid_json_is_refused_before_any_network_call(mock_page, mock_all, config, tmp_path):
    mock_all.side_effect = _query_all
    mock_page.side_effect = _query_page
    download_server_sources(
        config,
        MagicMock(),
        DownloadSourcesParams(scope="x_myapp", output_dir=str(tmp_path), families=["theme"]),
    )
    style = tmp_path / "sys_ux_style" / "Colors" / "style.json"
    style.write_text('{"properties": {"--now-color--primary-1": "31,132,118",}', encoding="utf-8")

    auth = MagicMock()
    with patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record") as fetch:
        result = update_remote_from_local(
            config, auth, PushLocalComponentParams(path=str(style.parent))
        )

    assert result["error"] == "INVALID_JSON"
    assert "style: line 1" in result["message"]
    fetch.assert_not_called()
    auth.make_request.assert_not_called()


def test_empty_json_body_is_a_cleared_value_not_a_syntax_error(tmp_path):
    from servicenow_mcp.tools.sync_tools import _invalid_json_fields

    rec = tmp_path / "x_myapp" / "sys_ux_theme" / "Blank"
    rec.mkdir(parents=True)
    (rec / "theme.json").write_text("  \n", encoding="utf-8")
    (rec / "_metadata.json").write_text(
        json.dumps(
            {"table": "sys_ux_theme", "sys_id": "eeee5555ffff6666aaaa7777bbbb8888", "name": "Blank"}
        ),
        encoding="utf-8",
    )

    assert _invalid_json_fields(_resolve_local_path(rec)) == {}
