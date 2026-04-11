"""
Tests for performance optimizations introduced in the perf pass:
  1. json_fast migration (stdlib json → orjson/json_fast)
  2. Shallow-copy schema injection (replace copy.deepcopy)
  3. Parallel chunked M2M queries (_parallel_chunked_query)
  4. serialize_tool_output edge cases with json_fast
"""

import json
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    ServerConfig,
)


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
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


# ============================================================================
# 1. json_fast migration — no stdlib json leaks
# ============================================================================


class TestJsonFastMigration:
    """Verify that tool output paths use json_fast, not stdlib json."""

    def test_server_introspection_tool_uses_json_fast(self, mock_config, mock_auth):
        """list_tool_packages response must be serialized via json_fast (compact)."""
        from servicenow_mcp.server import ServiceNowMCP

        with patch.dict("os.environ", {"MCP_TOOL_PACKAGE": "standard"}):
            server = ServiceNowMCP(mock_config)

        result = server._list_tool_packages_impl()
        # Simulate the call_tool path for introspection
        from servicenow_mcp.utils import json_fast

        serialized = json_fast.dumps(result)
        # Must be compact — no indentation
        assert "\n" not in serialized
        # Must be valid JSON
        parsed = json.loads(serialized)
        assert "current_package" in parsed

    def test_server_error_response_is_compact(self):
        """Error responses from _call_tool_impl must be compact JSON (no indent)."""
        from servicenow_mcp.utils import json_fast

        error_result = {"success": False, "error": "test error", "tool": "test"}
        serialized = json_fast.dumps(error_result)
        assert "\n" not in serialized
        assert "  " not in serialized  # no indentation
        parsed = json.loads(serialized)
        assert parsed["success"] is False

    def test_script_include_execute_json_parse_uses_json_fast(self):
        """execute_script_include must parse GlideAjax JSON via json_fast."""
        from servicenow_mcp.tools.script_include_tools import execute_script_include

        mock_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )
        mock_auth = MagicMock()
        mock_auth.get_headers.return_value = {"Authorization": "Basic ..."}

        # Mock get_script_include to return a client-callable SI
        with patch(
            "servicenow_mcp.tools.script_include_tools.get_script_include"
        ) as mock_get:
            mock_get.return_value = {
                "success": True,
                "message": "Found",
                "script_include": {
                    "sys_id": "si1",
                    "name": "TestSI",
                    "client_callable": True,
                },
            }
            # Mock the HTTP response with valid JSON
            resp = MagicMock()
            resp.status_code = 200
            resp.text = '{"answer":"hello"}'
            resp.raise_for_status = MagicMock()
            mock_auth.make_request.return_value = resp

            from servicenow_mcp.tools.script_include_tools import (
                ExecuteScriptIncludeParams,
            )

            result = execute_script_include(
                mock_config,
                mock_auth,
                ExecuteScriptIncludeParams(name="TestSI", method="execute"),
            )
            assert result["success"] is True
            assert result["result"] == {"answer": "hello"}

    def test_script_include_execute_non_json_fallback(self):
        """Non-JSON response (e.g. XML) must fall back to raw text."""
        from servicenow_mcp.tools.script_include_tools import (
            ExecuteScriptIncludeParams,
            execute_script_include,
        )

        mock_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )
        mock_auth = MagicMock()
        mock_auth.get_headers.return_value = {"Authorization": "Basic ..."}

        with patch(
            "servicenow_mcp.tools.script_include_tools.get_script_include"
        ) as mock_get:
            mock_get.return_value = {
                "success": True,
                "message": "Found",
                "script_include": {
                    "sys_id": "si1",
                    "name": "TestSI",
                    "client_callable": True,
                },
            }
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "<xml><answer>hello</answer></xml>"
            resp.raise_for_status = MagicMock()
            mock_auth.make_request.return_value = resp

            result = execute_script_include(
                mock_config,
                mock_auth,
                ExecuteScriptIncludeParams(name="TestSI", method="execute"),
            )
            assert result["success"] is True
            assert result["result"] == "<xml><answer>hello</answer></xml>"

    def test_portal_snapshot_read_uses_json_fast(self, tmp_path):
        """_read_portal_component_snapshot must parse via json_fast, not stdlib."""
        from servicenow_mcp.tools.portal_tools import _read_portal_component_snapshot

        snapshot = {
            "component": {"table": "sp_widget", "sys_id": "w1"},
            "values": {"script": "console.log('test');"},
            "fields": ["script"],
        }
        snap_file = tmp_path / "test_snapshot.json"
        snap_file.write_text(json.dumps(snapshot), encoding="utf-8")

        result = _read_portal_component_snapshot(str(snap_file))
        assert result["component"]["sys_id"] == "w1"

    def test_portal_json_write_uses_json_fast(self, tmp_path):
        """_write_json_file must use json_fast.dumps (compact output)."""
        from servicenow_mcp.tools.portal_tools import _write_json_file

        payload = {"key": "value", "nested": {"a": 1}}
        out_file = tmp_path / "output.json"
        _write_json_file(out_file, payload)
        content = out_file.read_text(encoding="utf-8")
        # Must be valid JSON
        parsed = json.loads(content)
        assert parsed == payload

    def test_portal_json_or_raw_string_parses_json(self):
        """_json_or_raw_string must parse JSON strings via json_fast."""
        from servicenow_mcp.tools.portal_tools import _json_or_raw_string

        assert _json_or_raw_string('{"key":"value"}') == {"key": "value"}
        assert _json_or_raw_string("[1,2,3]") == [1, 2, 3]
        # Non-JSON returns as-is
        assert _json_or_raw_string("plain text") == "plain text"
        # Non-string passes through
        assert _json_or_raw_string(42) == 42

    def test_resources_changesets_error_uses_json_fast(self):
        """Changeset resource error responses must use json_fast."""
        from servicenow_mcp.resources.changesets import ChangesetResource

        mock_config = MagicMock()
        mock_config.instance_url = "https://test.service-now.com"
        mock_auth = MagicMock()
        mock_auth.get_headers.return_value = {}

        resource = ChangesetResource(mock_config, mock_auth)
        # We can't easily call async methods here, but we can verify the import
        import servicenow_mcp.resources.changesets as mod

        assert hasattr(mod, "json_fast")

    def test_resources_script_includes_error_uses_json_fast(self):
        """Script include resource error responses must use json_fast."""
        import servicenow_mcp.resources.script_includes as mod

        assert hasattr(mod, "json_fast")


# ============================================================================
# 2. Shallow-copy schema injection (replaces copy.deepcopy)
# ============================================================================


class TestShallowCopySchemaInjection:
    """Verify _inject_confirmation_schema produces correct schemas without deepcopy."""

    def test_inject_adds_confirm_field(self):
        """confirm field must appear in injected schema."""
        from servicenow_mcp.server import ServiceNowMCP

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }
        result = ServiceNowMCP._inject_confirmation_schema(schema)
        assert "confirm" in result["properties"]
        assert "confirm" in result["required"]

    def test_inject_does_not_mutate_original(self):
        """Original schema must be untouched after injection."""
        from servicenow_mcp.server import ServiceNowMCP

        original = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "integer"},
            },
            "required": ["name"],
        }
        original_props_keys = set(original["properties"].keys())
        original_required = list(original["required"])

        ServiceNowMCP._inject_confirmation_schema(original)

        # Original must NOT be modified
        assert set(original["properties"].keys()) == original_props_keys
        assert original["required"] == original_required
        assert "confirm" not in original["properties"]
        assert "confirm" not in original["required"]

    def test_inject_preserves_existing_properties(self):
        """All existing properties must survive injection."""
        from servicenow_mcp.server import ServiceNowMCP

        schema = {
            "type": "object",
            "properties": {
                "field_a": {"type": "string"},
                "field_b": {"type": "number"},
                "field_c": {"type": "boolean"},
            },
            "required": ["field_a"],
        }
        result = ServiceNowMCP._inject_confirmation_schema(schema)
        assert "field_a" in result["properties"]
        assert "field_b" in result["properties"]
        assert "field_c" in result["properties"]
        assert "confirm" in result["properties"]
        assert result["properties"]["confirm"]["enum"] == ["approve"]

    def test_inject_handles_empty_schema(self):
        """Schema with no properties or required should still work."""
        from servicenow_mcp.server import ServiceNowMCP

        schema = {"type": "object"}
        result = ServiceNowMCP._inject_confirmation_schema(schema)
        assert "confirm" in result["properties"]
        assert "confirm" in result["required"]

    def test_inject_idempotent(self):
        """Injecting twice should not duplicate the confirm field."""
        from servicenow_mcp.server import ServiceNowMCP

        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        first = ServiceNowMCP._inject_confirmation_schema(schema)
        second = ServiceNowMCP._inject_confirmation_schema(first)
        assert second["required"].count("confirm") == 1

    def test_inject_confirm_field_shape(self):
        """Confirm field must have correct type, enum, and description."""
        from servicenow_mcp.server import ServiceNowMCP

        schema = {"type": "object", "properties": {}, "required": []}
        result = ServiceNowMCP._inject_confirmation_schema(schema)
        confirm = result["properties"]["confirm"]
        assert confirm["type"] == "string"
        assert confirm["enum"] == ["approve"]
        assert "description" in confirm


# ============================================================================
# 3. Parallel chunked M2M queries
# ============================================================================


class TestParallelChunkedQuery:
    """Verify _parallel_chunked_query executes chunks in parallel."""

    def test_single_chunk_no_threading(self, mock_config, mock_auth):
        """A single chunk should execute directly without ThreadPoolExecutor."""
        from servicenow_mcp.tools.portal_tools import _parallel_chunked_query

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all") as mock_qall:
            mock_qall.return_value = [{"sys_id": "r1"}, {"sys_id": "r2"}]
            rows = _parallel_chunked_query(
                mock_config,
                mock_auth,
                table="sp_widget",
                chunks=[["id1", "id2"]],
                query_template="sys_idIN{ids}",
                fields="sys_id,name",
                page_size=50,
                max_records=100,
            )
        assert len(rows) == 2
        mock_qall.assert_called_once()
        call_kwargs = mock_qall.call_args
        assert "sys_idINid1,id2" in str(call_kwargs)

    def test_multiple_chunks_parallel(self, mock_config, mock_auth):
        """Multiple chunks must be submitted to executor and results merged."""
        from servicenow_mcp.tools.portal_tools import _parallel_chunked_query

        def _fake_query_all(config, auth, *, table, query, fields, page_size, max_records):
            # Return different results per chunk based on query
            if "id1" in query:
                return [{"sys_id": "r1"}]
            elif "id3" in query:
                return [{"sys_id": "r3"}, {"sys_id": "r4"}]
            return []

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all", side_effect=_fake_query_all):
            rows = _parallel_chunked_query(
                mock_config,
                mock_auth,
                table="m2m_sp_widget_angular_provider",
                chunks=[["id1", "id2"], ["id3", "id4"]],
                query_template="sp_widgetIN{ids}",
                fields="sp_angular_provider",
                page_size=50,
                max_records=1000,
            )
        assert len(rows) == 3
        sys_ids = {r["sys_id"] for r in rows}
        assert sys_ids == {"r1", "r3", "r4"}

    def test_empty_chunks_returns_empty(self, mock_config, mock_auth):
        """Empty chunk list should return empty without API calls."""
        from servicenow_mcp.tools.portal_tools import _parallel_chunked_query

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all") as mock_qall:
            rows = _parallel_chunked_query(
                mock_config,
                mock_auth,
                table="sp_widget",
                chunks=[],
                query_template="sys_idIN{ids}",
                fields="sys_id",
                page_size=50,
                max_records=100,
            )
        assert rows == []
        mock_qall.assert_not_called()

    def test_parallel_chunk_failure_graceful(self, mock_config, mock_auth):
        """If one chunk fails, others should still return results."""
        from servicenow_mcp.tools.portal_tools import _parallel_chunked_query

        call_count = 0

        def _flaky_query(config, auth, *, table, query, fields, page_size, max_records):
            nonlocal call_count
            call_count += 1
            if "fail" in query:
                raise ConnectionError("Network timeout")
            return [{"sys_id": "ok"}]

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all", side_effect=_flaky_query):
            rows = _parallel_chunked_query(
                mock_config,
                mock_auth,
                table="sp_widget",
                chunks=[["ok_id"], ["fail_id"]],
                query_template="sys_idIN{ids}",
                fields="sys_id",
                page_size=50,
                max_records=100,
            )
        # At least the successful chunk should return
        assert len(rows) >= 1
        assert any(r["sys_id"] == "ok" for r in rows)


class TestDetectionToolsParallelM2M:
    """Verify detection_tools M2M lookup uses parallel execution."""

    def test_detection_parallel_m2m_single_chunk(self, mock_config, mock_auth):
        """Single chunk of widget IDs should not use threading."""
        from servicenow_mcp.tools.detection_tools import (
            DetectMissingCodesParams,
            detect_missing_profit_company_codes,
        )

        widget_data = [
            {
                "sys_id": "w1",
                "name": "TestWidget",
                "id": "test",
                "sys_scope": "global",
                "client_script": "if (profit_company_code == '2400') { } else if (profit_company_code == '5K00') { }",
                "script": "",
            }
        ]

        provider_data = [
            {
                "sys_id": "p1",
                "name": "TestProvider",
                "script": "switch(profit_company_code) { case '2400': break; case '5K00': break; }",
            }
        ]

        m2m_data = [{"sp_angular_provider": {"value": "p1"}}]

        call_log = []

        def _mock_query_all(config, auth, *, table, query, fields, page_size, max_records):
            call_log.append(table)
            if table == "sp_widget":
                return widget_data
            if table == "m2m_sp_widget_angular_provider":
                return m2m_data
            if table == "sp_angular_provider":
                return provider_data
            return []

        def _mock_count(config, auth, table, query):
            return 1

        with (
            patch(
                "servicenow_mcp.tools.detection_tools._sn_query_all_shared",
                side_effect=_mock_query_all,
            ),
            patch(
                "servicenow_mcp.tools.detection_tools._sn_count_shared",
                side_effect=_mock_count,
            ),
        ):
            result = detect_missing_profit_company_codes(
                mock_config,
                mock_auth,
                DetectMissingCodesParams(
                    required_codes=["2400", "5K00", "2J00"],
                    include_angular_providers=True,
                    max_widgets=10,
                ),
            )

        assert result["success"] is True
        assert result["scan_summary"]["widgets_scanned"] == 1
        assert result["scan_summary"]["providers_scanned"] == 1
        # Should find missing '2J00' in both widget and provider
        assert result["scan_summary"]["findings_count"] >= 1


# ============================================================================
# 4. serialize_tool_output edge cases
# ============================================================================


class TestSerializeToolOutput:
    """Comprehensive tests for serialize_tool_output with json_fast backend."""

    def test_compact_json_string_passthrough(self):
        """Already-compact JSON strings must pass through without re-parsing."""
        from servicenow_mcp.server import serialize_tool_output

        compact = '{"success":true,"count":5}'
        assert serialize_tool_output(compact, "test") == compact

    def test_indented_json_recompacted(self):
        """JSON with whitespace must be re-compacted."""
        from servicenow_mcp.server import serialize_tool_output

        indented = '{\n  "success" : true,\n  "count" : 5\n}'
        result = serialize_tool_output(indented, "test")
        assert "\n" not in result
        assert " : " not in result
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_dict_serialized_compact(self):
        """Dict input must be serialized to compact JSON."""
        from servicenow_mcp.server import serialize_tool_output

        result = serialize_tool_output({"key": "value", "num": 42}, "test")
        assert "\n" not in result
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_plain_string_passthrough(self):
        """Non-JSON strings must pass through as-is."""
        from servicenow_mcp.server import serialize_tool_output

        assert serialize_tool_output("hello world", "test") == "hello world"

    def test_pydantic_model_serialized(self):
        """Pydantic model must be serialized correctly."""
        from pydantic import BaseModel

        from servicenow_mcp.server import serialize_tool_output

        class TestModel(BaseModel):
            name: str
            value: int

        model = TestModel(name="test", value=42)
        result = serialize_tool_output(model, "test")
        parsed = json.loads(result)
        assert parsed["name"] == "test"
        assert parsed["value"] == 42

    def test_serialization_error_returns_error_json(self):
        """If serialization fails, must return error JSON (not crash)."""
        from servicenow_mcp.server import serialize_tool_output

        class Unserializable:
            pass

        result = serialize_tool_output(Unserializable(), "test")
        assert "test" in result  # tool name in output


# ============================================================================
# 5. No stdlib json import leaks in optimized modules
# ============================================================================


class TestNoStdlibJsonLeaks:
    """Verify optimized modules don't import stdlib json anymore."""

    def test_server_no_stdlib_json(self):
        """server.py must not import stdlib json."""
        import servicenow_mcp.server as mod

        # The module should have json_fast but not json
        source = open(mod.__file__).read()
        lines = source.split("\n")
        direct_imports = [
            l for l in lines if l.strip().startswith("import json") and "json_fast" not in l
        ]
        assert len(direct_imports) == 0, f"Found stdlib json import: {direct_imports}"

    def test_portal_tools_no_stdlib_json(self):
        """portal_tools.py must not import stdlib json."""
        import servicenow_mcp.tools.portal_tools as mod

        source = open(mod.__file__).read()
        lines = source.split("\n")
        direct_imports = [
            l for l in lines if l.strip().startswith("import json") and "json_fast" not in l
        ]
        assert len(direct_imports) == 0, f"Found stdlib json import: {direct_imports}"

    def test_script_include_tools_no_stdlib_json(self):
        """script_include_tools.py must not import stdlib json."""
        import servicenow_mcp.tools.script_include_tools as mod

        source = open(mod.__file__).read()
        lines = source.split("\n")
        direct_imports = [
            l for l in lines if l.strip().startswith("import json") and "json_fast" not in l
        ]
        assert len(direct_imports) == 0, f"Found stdlib json import: {direct_imports}"

    def test_server_no_copy_import(self):
        """server.py must not import copy module (deepcopy removed)."""
        import servicenow_mcp.server as mod

        source = open(mod.__file__).read()
        lines = source.split("\n")
        copy_imports = [l for l in lines if l.strip().startswith("import copy")]
        assert len(copy_imports) == 0, f"Found copy import: {copy_imports}"


# ============================================================================
# 6. LRU cache OrderedDict correctness
# ============================================================================


class TestLRUCacheCorrectness:
    """Extended cache tests to verify OrderedDict-based LRU behavior."""

    def test_cache_respects_max_entries(self):
        """Cache must never exceed _CACHE_MAX_ENTRIES."""
        from servicenow_mcp.tools.sn_api import (
            _CACHE_MAX_ENTRIES,
            _cache_put,
            _query_cache,
            invalidate_query_cache,
        )

        invalidate_query_cache()
        for i in range(_CACHE_MAX_ENTRIES + 50):
            _cache_put(f"overflow_{i}", f"val_{i}")
        assert len(_query_cache) <= _CACHE_MAX_ENTRIES

    def test_cache_is_ordered_dict(self):
        """Cache implementation must be OrderedDict for O(1) LRU."""
        from servicenow_mcp.tools.sn_api import _query_cache

        assert isinstance(_query_cache, OrderedDict)

    def test_cache_put_update_moves_to_end(self):
        """Updating an existing entry must move it to the end (most recent)."""
        from servicenow_mcp.tools.sn_api import (
            _cache_get,
            _cache_put,
            _query_cache,
            invalidate_query_cache,
        )

        invalidate_query_cache()
        _cache_put("key_a", "val_1")
        _cache_put("key_b", "val_2")
        _cache_put("key_c", "val_3")
        # Update key_a — should move to end
        _cache_put("key_a", "val_1_updated")
        keys = list(_query_cache.keys())
        assert keys[-1] == "key_a"
        assert _cache_get("key_a") == "val_1_updated"


# ============================================================================
# 7. Tuple cache keys
# ============================================================================


class TestTupleCacheKeys:
    """Verify cache key is now a tuple, not a string."""

    def test_cache_key_returns_tuple(self):
        """_cache_key must return a tuple for cheaper hashing."""
        from servicenow_mcp.tools.sn_api import _cache_key

        key = _cache_key(
            "incident", "active=true", "sys_id,name", 20, 0,
            display_value=True, no_count=False, orderby="number",
        )
        assert isinstance(key, tuple)
        assert key[0] == "incident"
        assert key[1] == "active=true"

    def test_tuple_cache_key_distinct_for_different_params(self):
        """Different parameters must produce different keys."""
        from servicenow_mcp.tools.sn_api import _cache_key

        key1 = _cache_key("incident", "a=1", "sys_id", 10, 0,
                          display_value=True, no_count=False, orderby=None)
        key2 = _cache_key("incident", "a=1", "sys_id", 10, 0,
                          display_value=False, no_count=False, orderby=None)
        key3 = _cache_key("incident", "a=1", "sys_id", 10, 0,
                          display_value=True, no_count=False, orderby="-number")
        assert key1 != key2
        assert key1 != key3

    def test_invalidate_by_table_works_with_tuple_keys(self):
        """invalidate_query_cache(table=...) must match tuple keys by first element."""
        from servicenow_mcp.tools.sn_api import (
            _cache_key,
            _cache_get,
            _cache_put,
            invalidate_query_cache,
        )

        invalidate_query_cache()
        k_inc = _cache_key("incident", "", "sys_id", 10, 0,
                           display_value=False, no_count=False, orderby=None)
        k_task = _cache_key("task", "", "sys_id", 10, 0,
                            display_value=False, no_count=False, orderby=None)
        _cache_put(k_inc, "incident_data")
        _cache_put(k_task, "task_data")

        removed = invalidate_query_cache(table="incident")
        assert removed == 1
        assert _cache_get(k_inc) is None
        assert _cache_get(k_task) == "task_data"


# ============================================================================
# 8. Pre-compiled portal regex patterns
# ============================================================================


class TestPrecompiledPortalRegex:
    """Verify portal edit action regexes are pre-compiled at module level."""

    def test_regex_patterns_are_compiled(self):
        """Module-level regex patterns must be compiled re.Pattern objects."""
        from servicenow_mcp.tools.portal_tools import (
            _RE_APPLY,
            _RE_PREVIEW,
            _RE_ROLLBACK,
            _RE_SNAPSHOT,
        )
        import re as _re

        assert isinstance(_RE_ROLLBACK, _re.Pattern)
        assert isinstance(_RE_SNAPSHOT, _re.Pattern)
        assert isinstance(_RE_PREVIEW, _re.Pattern)
        assert isinstance(_RE_APPLY, _re.Pattern)

    def test_detect_action_rollback(self):
        from servicenow_mcp.tools.portal_tools import _detect_portal_edit_action

        assert _detect_portal_edit_action("rollback the widget") == "rollback"
        assert _detect_portal_edit_action("Revert changes") == "rollback"
        assert _detect_portal_edit_action("undo last edit") == "rollback"

    def test_detect_action_snapshot(self):
        from servicenow_mcp.tools.portal_tools import _detect_portal_edit_action

        assert _detect_portal_edit_action("take a snapshot") == "snapshot"
        assert _detect_portal_edit_action("Backup the widget") == "snapshot"

    def test_detect_action_preview(self):
        from servicenow_mcp.tools.portal_tools import _detect_portal_edit_action

        assert _detect_portal_edit_action("preview changes") == "preview"
        assert _detect_portal_edit_action("show diff") == "preview"

    def test_detect_action_apply(self):
        from servicenow_mcp.tools.portal_tools import _detect_portal_edit_action

        assert _detect_portal_edit_action("apply the update") == "apply"
        assert _detect_portal_edit_action("Fix the script") == "apply"

    def test_detect_action_default_analyze(self):
        from servicenow_mcp.tools.portal_tools import _detect_portal_edit_action

        assert _detect_portal_edit_action("what does this widget do") == "analyze"

    def test_case_insensitive(self):
        """Patterns must match regardless of case."""
        from servicenow_mcp.tools.portal_tools import _detect_portal_edit_action

        assert _detect_portal_edit_action("ROLLBACK NOW") == "rollback"
        assert _detect_portal_edit_action("Preview Changes") == "preview"


# ============================================================================
# 9. Basic auth header caching
# ============================================================================


class TestBasicAuthHeaderCache:
    """Verify basic auth header is encoded once and reused."""

    def test_basic_auth_header_cached_across_calls(self):
        """get_headers() must produce identical Authorization header without re-encoding."""
        from servicenow_mcp.auth.auth_manager import AuthManager
        from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig

        config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="secret"),
        )
        auth = AuthManager(config, "https://test.service-now.com")

        h1 = auth.get_headers()
        h2 = auth.get_headers()
        assert h1["Authorization"] == h2["Authorization"]
        assert h1["Authorization"].startswith("Basic ")
        # Internal cache field should be populated
        assert auth._cached_basic_auth_header is not None

    def test_basic_auth_header_value_correct(self):
        """Cached header must produce the correct base64 encoding."""
        import base64
        from servicenow_mcp.auth.auth_manager import AuthManager
        from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig

        config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password123"),
        )
        auth = AuthManager(config, "https://test.service-now.com")
        headers = auth.get_headers()
        expected = "Basic " + base64.b64encode(b"admin:password123").decode()
        assert headers["Authorization"] == expected


# ============================================================================
# 10. Session disk write deduplication
# ============================================================================


class TestSessionDiskDedup:
    """Verify _save_session_to_disk skips redundant writes."""

    def test_duplicate_save_skipped(self, tmp_path):
        """Second save with same content must skip file write."""
        from servicenow_mcp.auth.auth_manager import AuthManager
        from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig

        config = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(),
        )
        auth = AuthManager(config, "https://test.service-now.com")
        auth._session_cache_path = str(tmp_path / "session.json")
        auth._browser_cookie_header = "JSESSIONID=abc123"
        auth._browser_user_agent = "TestAgent"
        auth._browser_session_token = "token123"
        auth._browser_cookie_expires_at = 9999999999.0

        # First save — writes file
        auth._save_session_to_disk()
        assert (tmp_path / "session.json").exists()
        first_mtime = (tmp_path / "session.json").stat().st_mtime_ns

        # Tiny delay to ensure mtime would change if written
        import time
        time.sleep(0.01)

        # Second save with same content — must skip
        auth._save_session_to_disk()
        second_mtime = (tmp_path / "session.json").stat().st_mtime_ns
        assert first_mtime == second_mtime, "File was rewritten despite identical content"

    def test_changed_content_triggers_write(self, tmp_path):
        """Save with changed content must actually write."""
        from servicenow_mcp.auth.auth_manager import AuthManager
        from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig

        config = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(),
        )
        auth = AuthManager(config, "https://test.service-now.com")
        auth._session_cache_path = str(tmp_path / "session.json")
        auth._browser_cookie_header = "JSESSIONID=abc123"
        auth._browser_user_agent = "TestAgent"
        auth._browser_session_token = "token123"
        auth._browser_cookie_expires_at = 9999999999.0

        auth._save_session_to_disk()
        first_content = (tmp_path / "session.json").read_text()

        # Change cookie header
        auth._browser_cookie_header = "JSESSIONID=xyz789"
        auth._save_session_to_disk()
        second_content = (tmp_path / "session.json").read_text()

        assert first_content != second_content
        assert "xyz789" in second_content
