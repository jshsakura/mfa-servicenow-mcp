"""manage_catalog create_record_producer + create_variable map_to_field."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import catalog as svc
from servicenow_mcp.tools.catalog_tools import ManageCatalogParams, manage_catalog
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

ITEM = "aaaa1111bbbb2222cccc3333dddd4444"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


class Fake:
    def __init__(self, tables):
        self.tables = tables
        self.writes = []
        self.auth = MagicMock(spec=AuthManager)
        self.auth.get_headers.return_value = {}
        self.auth.make_request.side_effect = self._request

    def _request(self, method, url, **kw):
        self.writes.append((method, url.split("/table/")[1], kw.get("json")))
        r = MagicMock()
        r.json.return_value = {"result": {"sys_id": ITEM}}
        return r

    def read(self, config, auth, *, table, query, **kw):
        out = self.tables.get(table, [])
        if isinstance(out, Exception):
            raise out
        return out, None


@pytest.fixture
def run():
    patches = []

    def _go(tables, fn):
        f = Fake(tables)
        p = patch.object(svc, "sn_query_page", side_effect=f.read)
        p.start()
        patches.append(p)
        return f, fn(f)

    with patch.object(svc, "invalidate_query_cache"):
        yield _go
    for p in patches:
        p.stop()
    patch.stopall()


def _create(f, **kw):
    return svc.create_record_producer(
        _config(), f.auth, name="Report Issue", table_name="my_table", **kw
    )


def test_creates_inactive_with_proof(run):
    tables = {
        "sys_db_object": [{"name": "my_table"}],
        "sc_cat_item_producer": [{"sys_id": ITEM, "active": "false"}],
    }
    f, out = run(tables, lambda f: _create(f, script="x=1;"))
    assert out["success"] and out["verified"] and out["sys_id"] == ITEM
    method, table, body = f.writes[0]
    assert (method, table) == ("POST", "sc_cat_item_producer")
    assert body["active"] == "false" and body["table_name"] == "my_table"
    assert body["script"] == "x=1;"


def test_missing_table_writes_nothing(run):
    f, out = run({"sys_db_object": []}, _create)
    assert out["error"] == "TABLE_NOT_FOUND" and f.writes == []


def test_unreadable_table_check_writes_nothing(run):
    f, out = run({"sys_db_object": RuntimeError("403")}, _create)
    assert out["error"] == "TABLE_UNVERIFIED" and f.writes == []


def test_dry_run_previews_without_write(run):
    f, out = run({"sys_db_object": [{"name": "my_table"}]}, lambda f: _create(f, dry_run=True))
    assert out["dry_run"] is True and f.writes == []


def test_variable_map_to_field_in_body(run):
    patch.object(svc, "resolve_variable_type", return_value=("6", None)).start()
    f, out = run(
        {},
        lambda f: svc.create_variable(
            _config(),
            f.auth,
            catalog_item_id=ITEM,
            name="short_description",
            variable_type="6",
            label="Summary",
            map_to_field=True,
            target_field="short_description",
            dry_run=True,
        ),
    )
    proposed = out.get("proposed") or out
    assert "map_to_field" in str(proposed) and "short_description" in str(proposed)


def test_params_and_narrowing():
    with pytest.raises(ValidationError):
        ManageCatalogParams(action="create_record_producer", name="N")
    p = ManageCatalogParams(action="create_record_producer", name="N", table_name="my_table")
    assert p.table_name == "my_table"
    fields = ManageCatalogParams._FIELDS_BY_ACTION["create_record_producer"]
    assert "table_name" in fields and "flow_designer_flow" not in fields


def test_tool_dispatch(run):
    tables = {"sys_db_object": [{"name": "my_table"}]}
    f = Fake(tables)
    with (
        patch.object(svc, "sn_query_page", side_effect=f.read),
        patch.object(svc, "invalidate_query_cache"),
    ):
        out = manage_catalog(
            _config(),
            f.auth,
            ManageCatalogParams(
                action="create_record_producer", name="N", table_name="my_table", dry_run=True
            ),
        )
    assert out["dry_run"] is True
