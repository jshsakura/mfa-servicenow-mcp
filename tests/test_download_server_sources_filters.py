"""download_server_sources narrowing: sys_ids / tables / customer_only, the UI policy
type, child-class exclusion, and folder names that match a full download."""

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_tools import (
    SOURCE_CONFIG,
    DownloadSourcesParams,
    _class_exclusion_filters,
    _table_filter_clause,
    download_server_sources,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

ID_A = "aaaa1111bbbb2222cccc3333dddd4444"
ID_B = "bbbb2222cccc3333dddd4444eeee5555"
ID_MISSING = "cccc3333dddd4444eeee5555ffff6666"


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth() -> MagicMock:
    return MagicMock()


class FakeInstance:
    """Answers sn_query_all per table and records every query it was sent."""

    def __init__(self, rows: Dict[str, List[Dict[str, Any]]], clash_rows=None, fail_clash=False):
        self.rows = rows
        self.clash_rows = clash_rows or {}
        self.fail_clash = fail_clash
        self.calls: List[Dict[str, str]] = []

    def __call__(self, config, auth_manager, *, table, query, fields, **_kw):
        self.calls.append({"table": table, "query": query, "fields": fields})
        if self._is_clash_read(table, query):
            if self.fail_clash:
                raise RuntimeError("HTTP 502")
            return list(self.clash_rows.get(table, []))
        return list(self.rows.get(table, []))

    @staticmethod
    def _is_clash_read(table, query):
        idents = [c["identifier_field"] for c in SOURCE_CONFIG.values() if c["table"] == table]
        return bool(idents) and f"^{idents[0]}=" in query and "sys_idIN" not in query

    def queries(self, table):
        return [c["query"] for c in self.calls if c["table"] == table]


def _run(config, auth, tmp_path, fake, **kw):
    params = DownloadSourcesParams(output_dir=str(tmp_path), **kw)
    with (
        patch("servicenow_mcp.tools.source_tools.sn_query_all", side_effect=fake),
        patch("servicenow_mcp.tools.source_tools.sn_query_page", return_value=([], 0)),
        patch(
            "servicenow_mcp.tools.source_tools.apply_scope_namespace",
            side_effect=lambda c, a, p: (p, None),
        ),
    ):
        return download_server_sources(config, auth, params)


def _ui_action(sys_id, name="Save", table="incident"):
    return {
        "sys_id": sys_id,
        "name": name,
        "table": table,
        "sys_scope.scope": "global",
        "sys_updated_on": "2026-01-01 00:00:00",
        "sys_mod_count": "1",
        "script": "current.update();",
        "condition": "true",
        "client_script_v2": "function x(){}",
    }


# --- tables ------------------------------------------------------------------


def test_tables_filter_maps_each_type_to_its_own_column(config, auth, tmp_path):
    fake = FakeInstance({})
    result = _run(
        config,
        auth,
        tmp_path,
        fake,
        scope="global",
        families=["server_scripts"],
        tables=["incident", "sc_req_item"],
    )
    assert result["success"] is True
    (br,) = fake.queries("sys_script")
    assert br.endswith("collectionINincident,sc_req_item")
    (cs,) = fake.queries("sys_script_client")
    assert cs.endswith("tableINincident,sc_req_item")
    # A catalog client script has no table column: skipped and named, never queried
    # with a condition the table would silently drop.
    assert fake.queries("catalog_script_client") == []
    assert result["skipped_no_table_column"] == ["catalog_client_script"]


def test_tables_filter_on_families_without_a_table_column_is_refused(config, auth, tmp_path):
    fake = FakeInstance({})
    result = _run(
        config, auth, tmp_path, fake, scope="global", families=["script_includes"], tables=["x"]
    )
    assert result["success"] is False
    assert "script_include" in result["message"]
    assert fake.calls == []


def test_acl_table_filter_matches_row_and_field_acls(config, auth, tmp_path):
    fake = FakeInstance({})
    _run(config, auth, tmp_path, fake, scope="global", families=["security"], tables=["incident"])
    (q,) = fake.queries("sys_security_acl")
    assert q == ("sys_scope.scope=global^scriptISNOTEMPTY^name=incident^ORnameSTARTSWITHincident.")


def test_table_filter_clause_none_for_types_without_table():
    assert _table_filter_clause(SOURCE_CONFIG["script_include"], ["incident"]) is None
    assert _table_filter_clause(SOURCE_CONFIG["ui_policy"], ["a", "b"]) == "tableINa,b"


def test_bad_table_name_is_refused(config, auth, tmp_path):
    fake = FakeInstance({})
    result = _run(
        config, auth, tmp_path, fake, scope="global", families=["ui"], tables=["incident^ORx"]
    )
    assert result["success"] is False
    assert fake.calls == []


# --- customer_only -----------------------------------------------------------


def test_customer_only_filters_on_global_package_and_says_what_it_leaves_out(
    config, auth, tmp_path
):
    fake = FakeInstance({})
    result = _run(config, auth, tmp_path, fake, scope="global", families=["ui"], customer_only=True)
    assert result["success"] is True
    for table in ("sys_ui_action", "sys_ui_policy", "sys_ui_page"):
        (q,) = fake.queries(table)
        assert "^sys_package=global" in q
    assert "NOT in this download" in result["customer_only_note"]


def test_customer_only_outside_global_is_refused(config, auth, tmp_path):
    fake = FakeInstance({})
    result = _run(config, auth, tmp_path, fake, scope="x_app", families=["ui"], customer_only=True)
    assert result["success"] is False
    assert "scope='global'" in result["message"]
    assert fake.calls == []


# --- sys_ids -----------------------------------------------------------------


def test_sys_ids_fetch_named_records_and_name_the_ones_not_returned(config, auth, tmp_path):
    fake = FakeInstance({"sys_ui_action": [_ui_action(ID_A)]})
    result = _run(
        config,
        auth,
        tmp_path,
        fake,
        scope="global",
        families=["ui"],
        sys_ids=[ID_A.upper(), ID_MISSING],
    )
    assert result["success"] is True
    (q,) = [q for q in fake.queries("sys_ui_action") if "sys_idIN" in q]
    assert f"sys_idIN{ID_A},{ID_MISSING}" in q
    assert result["sys_ids_not_returned"] == [ID_MISSING]
    assert "FAILED" not in result["sys_ids_note"]
    meta = json.loads((tmp_path / "sys_ui_action" / "_sync_meta.json").read_text())
    assert meta, "a sys_id download must anchor the record so it can be pushed"


def test_sys_ids_not_returned_hedges_when_a_type_failed(config, auth, tmp_path):
    fake = FakeInstance({})

    def failing(config, auth_manager, *, table, query, fields, **kw):
        if table == "sys_ui_page":
            raise RuntimeError("HTTP 500")
        return fake(config, auth_manager, table=table, query=query, fields=fields, **kw)

    result = _run(config, auth, tmp_path, failing, scope="global", families=["ui"], sys_ids=[ID_A])
    assert result["sys_ids_not_returned"] == [ID_A]
    assert "FAILED" in result["sys_ids_note"]


def test_malformed_sys_id_is_refused(config, auth, tmp_path):
    fake = FakeInstance({})
    result = _run(
        config, auth, tmp_path, fake, scope="global", families=["ui"], sys_ids=["abc^ORactive=true"]
    )
    assert result["success"] is False
    assert fake.calls == []


# --- folder names under a subset ---------------------------------------------


def test_subset_suffixes_a_folder_a_full_download_would_suffix(config, auth, tmp_path):
    # Two 'Save' actions on incident exist in the scope; only one is requested.
    fake = FakeInstance(
        {"sys_ui_action": [_ui_action(ID_A)]},
        clash_rows={"sys_ui_action": [_ui_action(ID_A), _ui_action(ID_B)]},
    )
    _run(config, auth, tmp_path, fake, scope="global", families=["ui"], sys_ids=[ID_A])
    assert (tmp_path / "sys_ui_action" / "incident" / f"Save.{ID_A[:8]}").is_dir()
    clash = [q for q in fake.queries("sys_ui_action") if "^name=" in q]
    assert clash == ["sys_scope.scope=global^name=Save"]


def test_subset_without_namesakes_keeps_the_plain_folder(config, auth, tmp_path):
    fake = FakeInstance(
        {"sys_ui_action": [_ui_action(ID_A)]},
        clash_rows={"sys_ui_action": [_ui_action(ID_A)]},
    )
    _run(config, auth, tmp_path, fake, scope="global", families=["ui"], sys_ids=[ID_A])
    assert (tmp_path / "sys_ui_action" / "incident" / "Save").is_dir()


def test_failed_name_check_writes_nothing(config, auth, tmp_path):
    fake = FakeInstance({"sys_ui_action": [_ui_action(ID_A)]}, fail_clash=True)
    result = _run(config, auth, tmp_path, fake, scope="global", families=["ui"], sys_ids=[ID_A])
    assert result["source_types"]["ui_action"]["count"] == 0
    assert "name check failed" in result["source_types"]["ui_action"]["error"]
    assert not (tmp_path / "sys_ui_action" / "incident").exists()


def test_unfiltered_download_does_not_run_the_name_check(config, auth, tmp_path):
    fake = FakeInstance({"sys_ui_action": [_ui_action(ID_A)]})
    _run(config, auth, tmp_path, fake, scope="global", families=["ui"])
    assert all("^name=" not in q for q in fake.queries("sys_ui_action"))


# --- child classes -----------------------------------------------------------


def test_client_script_excludes_catalog_client_scripts(config, auth, tmp_path):
    fake = FakeInstance({})
    _run(config, auth, tmp_path, fake, scope="global", families=["server_scripts"])
    (q,) = fake.queries("sys_script_client")
    assert "sys_class_name!=catalog_script_client" in q
    (cat,) = fake.queries("catalog_script_client")
    assert "sys_class_name" not in cat


def test_widget_excludes_header_footer():
    assert _class_exclusion_filters(SOURCE_CONFIG["widget"]) == ["sys_class_name!=sp_header_footer"]


# --- UI policy ---------------------------------------------------------------


def test_ui_policy_writes_conditions_scripts_and_action_fields(config, auth, tmp_path):
    policy = {
        "sys_id": ID_A,
        "short_description": "Require reason",
        "table": "incident",
        "run_scripts": "true",
        "sys_scope.scope": "global",
        "sys_updated_on": "2026-01-01 00:00:00",
        "sys_mod_count": "2",
        "conditions": "state=6^EQ",
        "script_true": "function onCondition() {}",
        "script_false": "function onCondition() { return; }",
    }
    actions = [
        {"ui_policy": ID_A, "field": "close_notes"},
        {"ui_policy": ID_A, "field": "close_code"},
    ]
    fake = FakeInstance({"sys_ui_policy": [policy], "sys_ui_policy_action": actions})
    result = _run(config, auth, tmp_path, fake, scope="global", families=["ui"])
    assert result["source_types"]["ui_policy"]["count"] == 1
    folder = tmp_path / "sys_ui_policy" / "incident" / "Require_reason"
    assert (folder / "conditions.txt").read_text() == "state=6^EQ"
    assert (folder / "script_true.js").exists()
    assert (folder / "script_false.js").exists()
    meta = json.loads((folder / "_metadata.json").read_text())
    assert meta["source_table"] == "sys_ui_policy"
    assert {f.strip() for f in meta["action_fields"].split(",")} == {"close_notes", "close_code"}
    assert meta["action_fields_known"] == "true"


# --- other scopes ------------------------------------------------------------


def _run_with_counts(config, auth, tmp_path, fake, totals, groups, **kw):
    params = DownloadSourcesParams(output_dir=str(tmp_path), **kw)
    seen = []

    def count(config, auth_manager, table, query=""):
        seen.append((table, query))
        value = totals.get(table, 0)
        if isinstance(value, Exception):
            raise value
        return value

    with (
        patch("servicenow_mcp.tools.source_tools.sn_query_all", side_effect=fake),
        patch("servicenow_mcp.tools.source_tools.sn_query_page", return_value=([], 0)),
        patch(
            "servicenow_mcp.tools.source_tools.apply_scope_namespace",
            side_effect=lambda c, a, p: (p, None),
        ),
        patch("servicenow_mcp.tools.source_tools.sn_count", side_effect=count),
        patch(
            "servicenow_mcp.tools.source_tools.sn_count_by_group",
            side_effect=lambda c, a, table, q, g: groups.get(table),
        ),
    ):
        return download_server_sources(config, auth, params), seen


def test_tables_download_names_records_in_other_scopes(config, auth, tmp_path):
    result, seen = _run_with_counts(
        config,
        auth,
        tmp_path,
        FakeInstance({}),
        totals={"sys_script": 11},
        groups={"sys_script": {"x_app_one": 3, "x_app_two": 8}},
        scope="global",
        families=["server_scripts"],
        tables=["sc_request"],
    )
    assert result["other_scopes"] == {
        "x_app_one": {"business_rule": 3},
        "x_app_two": {"business_rule": 8},
    }
    assert "scope='<scope>'" in result["other_scopes_note"]
    br_q = [q for t, q in seen if t == "sys_script"][0]
    assert br_q == "sys_scope.scope!=global^collectionINsc_request"
    cs_q = [q for t, q in seen if t == "sys_script_client"][0]
    assert "sys_class_name!=catalog_script_client" in cs_q


def test_other_scopes_absent_when_none_exist(config, auth, tmp_path):
    result, _ = _run_with_counts(
        config,
        auth,
        tmp_path,
        FakeInstance({}),
        totals={},
        groups={},
        scope="global",
        families=["server_scripts"],
        tables=["sc_request"],
    )
    assert "other_scopes" not in result and "other_scopes_unread" not in result


def test_failed_count_is_reported_unread_never_as_none(config, auth, tmp_path):
    result, _ = _run_with_counts(
        config,
        auth,
        tmp_path,
        FakeInstance({}),
        totals={"sys_script": RuntimeError("HTTP 502")},
        groups={},
        scope="global",
        families=["server_scripts"],
        tables=["sc_request"],
    )
    assert "business_rule" in result["other_scopes_unread"]


def test_grouped_read_that_does_not_add_up_is_unread(config, auth, tmp_path):
    # A failed stats call can come back as {} — it must not read as "no other scopes".
    result, _ = _run_with_counts(
        config,
        auth,
        tmp_path,
        FakeInstance({}),
        totals={"sys_script": 11},
        groups={"sys_script": {}},
        scope="global",
        families=["server_scripts"],
        tables=["sc_request"],
    )
    assert "other_scopes" not in result
    assert result["other_scopes_unread"] == ["business_rule (11 records, scopes unread)"]


def test_sys_ids_download_does_not_count_other_scopes(config, auth, tmp_path):
    _, seen = _run_with_counts(
        config,
        auth,
        tmp_path,
        FakeInstance({}),
        totals={"sys_script": 5},
        groups={"sys_script": {"x_app_one": 5}},
        scope="global",
        families=["server_scripts"],
        tables=["sc_request"],
        sys_ids=[ID_A],
    )
    assert seen == []
