"""Red-green tests for query/schema metadata hints that keep the LLM from
floundering: surfacing ServiceNow 400 error detail (#1), guidance on empty
results (#2), and distinguishing a missing table from a fields-inherited
table in sn_schema (#4).
"""

import json

import pytest
import requests

from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture
def mock_auth():
    from unittest.mock import MagicMock

    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


class _Resp:
    """Minimal requests-like response for driving the real code paths."""

    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self.reason = "Bad Request" if status >= 400 else "OK"
        self._body = body if body is not None else {"result": []}
        self.content = json.dumps(self._body).encode()
        self.headers = headers or {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code), response=self)


# ---------------------------------------------------------------------------
# #1 — surface ServiceNow's 400 error body (invalid field / table)
# ---------------------------------------------------------------------------


class TestServiceNowErrorDetail:
    def test_sn_query_page_raises_enriched_httperror(self, mock_config, mock_auth):
        """A 400 must raise an HTTPError whose message carries ServiceNow's
        detail, while still being an HTTPError with .response so the retry
        layer can classify it."""
        from servicenow_mcp.tools.sn_api import sn_query_page

        body = {"error": {"message": "Invalid table", "detail": "no such table foo_xyz"}}
        mock_auth.make_request.return_value = _Resp(400, body)

        with pytest.raises(requests.exceptions.HTTPError) as ei:
            sn_query_page(
                mock_config,
                mock_auth,
                table="foo_xyz",
                query="",
                fields="",
                limit=1,
                offset=0,
                fail_silently=False,
            )

        assert "no such table foo_xyz" in str(ei.value)
        assert ei.value.response is not None  # retry classification still works

    def test_sn_query_surfaces_invalid_field_detail_and_schema_hint(self, mock_config, mock_auth):
        """sn_query must echo the bad-field detail and point at sn_schema."""
        from servicenow_mcp.tools.sn_api import GenericQueryParams, sn_query

        body = {
            "error": {
                "message": "Invalid field",
                "detail": "category_xyz is not a valid field on incident",
            }
        }
        mock_auth.make_request.return_value = _Resp(400, body)

        resp = sn_query(
            mock_config,
            mock_auth,
            GenericQueryParams(table="incident", fields="category_xyz"),
        )

        assert resp["success"] is False
        assert "category_xyz" in resp["message"]
        assert "sn_schema" in resp.get("hint", "")


# ---------------------------------------------------------------------------
# #2 — guidance when a query returns zero rows
# ---------------------------------------------------------------------------


class TestEmptyResultGuidance:
    def test_empty_result_includes_hint(self, mock_config, mock_auth):
        from servicenow_mcp.tools.sn_api import GenericQueryParams, sn_query

        mock_auth.make_request.return_value = _Resp(
            200, {"result": []}, headers={"X-Total-Count": "0"}
        )

        resp = sn_query(mock_config, mock_auth, GenericQueryParams(table="incident"))

        assert resp["success"] is True
        assert resp["count"] == 0
        hint = resp.get("hint", "")
        assert "sn_schema" in hint or "sn_discover" in hint

    def test_nonempty_result_has_no_empty_hint(self, mock_config, mock_auth):
        """Regression: the empty-result hint must not appear when rows return."""
        from servicenow_mcp.tools.sn_api import GenericQueryParams, sn_query

        mock_auth.make_request.return_value = _Resp(
            200, {"result": [{"sys_id": "1"}, {"sys_id": "2"}]}
        )

        resp = sn_query(mock_config, mock_auth, GenericQueryParams(table="incident"))

        assert resp["success"] is True
        assert resp["count"] == 2
        assert "hint" not in resp


# ---------------------------------------------------------------------------
# #4 — sn_schema: missing table vs fields-inherited table
# ---------------------------------------------------------------------------


class TestSchemaTableExistence:
    def test_schema_reports_nonexistent_table(self, mock_config, mock_auth):
        """Both sys_dictionary and sys_db_object empty => table does not exist."""
        from servicenow_mcp.tools.sn_api import SchemaParams, sn_schema

        def _mr(method, url, params=None, **kw):
            return _Resp(200, {"result": []})

        mock_auth.make_request.side_effect = _mr

        resp = sn_schema(mock_config, mock_auth, SchemaParams(table="nope_xyz"))

        assert resp["success"] is False
        msg = resp["message"].lower()
        assert "not found" in msg or "does not exist" in msg

    def test_schema_existing_table_no_own_fields_adds_note(self, mock_config, mock_auth):
        """sys_dictionary empty but the table exists => success with a note
        explaining the fields are inherited, not a typo."""
        from servicenow_mcp.tools.sn_api import SchemaParams, sn_schema

        def _mr(method, url, params=None, **kw):
            if "sys_db_object" in url:
                return _Resp(200, {"result": [{"name": "task"}]})
            return _Resp(200, {"result": []})

        mock_auth.make_request.side_effect = _mr

        resp = sn_schema(mock_config, mock_auth, SchemaParams(table="task"))

        assert resp["success"] is True
        assert resp["count"] == 0
        assert "note" in resp

    def test_schema_with_fields_does_not_call_db_object(self, mock_config, mock_auth):
        """Regression: when fields exist, no extra existence check fires."""
        from servicenow_mcp.tools.sn_api import SchemaParams, sn_schema

        calls = []

        def _mr(method, url, params=None, **kw):
            calls.append(url)
            return _Resp(200, {"result": [{"element": "number", "internal_type": "string"}]})

        mock_auth.make_request.side_effect = _mr

        resp = sn_schema(mock_config, mock_auth, SchemaParams(table="incident"))

        assert resp["success"] is True
        assert resp["count"] == 1
        assert not any("sys_db_object" in u for u in calls)
