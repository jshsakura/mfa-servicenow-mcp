"""Fixes for failures measured in real session logs. Each test names the failure."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.browser import actions, window
from servicenow_mcp.policies.write_guards import _CONCURRENT_EDIT_REGISTRY
from servicenow_mcp.server import ServiceNowMCP, _normalize_arguments, _package_rules
from servicenow_mcp.services.script_include import list_si, si_lookup_query, si_name_filter
from servicenow_mcp.tools import sn_api
from servicenow_mcp.tools.sn_api import AggregateParams, sn_aggregate
from servicenow_mcp.utils.config import ApiKeyConfig, AuthConfig, AuthType, ServerConfig

SYS_ID = "aaaa1111bbbb2222cccc3333dddd4444"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.API_KEY, api_key=ApiKeyConfig(api_key="k", header_name="X-Key")
        ),
    )


def _server(package):
    with patch.dict("os.environ", {"MCP_TOOL_PACKAGE": package}):
        return ServiceNowMCP(_config())


class TestScriptIncludeIdentifiers:
    def test_the_sys_id_create_returned_is_looked_up_as_a_sys_id(self):
        assert si_lookup_query(SYS_ID) == f"sys_id={SYS_ID}"

    def test_prefixed_sys_id_still_works(self):
        assert si_lookup_query(f"sys_id:{SYS_ID}") == f"sys_id={SYS_ID}"

    def test_api_name_is_looked_up_by_api_name(self):
        assert si_lookup_query("x_myapp.MyInclude") == "api_name=x_myapp.MyInclude"

    def test_plain_name(self):
        assert si_lookup_query("MyInclude") == "name=MyInclude"

    @pytest.mark.parametrize("query", ["nameLIKEfoo", "name=Foo", "active=true^nameLIKEfoo"])
    def test_encoded_query_is_not_searched_for_as_a_name(self, query):
        assert si_name_filter(query) == query

    @pytest.mark.parametrize("query", ["Foo", "INvoice", "x_myapp.Foo"])
    def test_plain_search_stays_a_name_search(self, query):
        assert si_name_filter(query) == f"nameLIKE{query}"


def _groups(n):
    return [
        {
            "stats": {"count": str(i + 1)},
            "groupby_fields": [{"field": "category", "value": f"v{i}"}],
        }
        for i in range(n)
    ]


def _stats_response(result):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"result": result}
    response.content = json.dumps({"result": result}).encode()
    return response


class TestAggregateGuards:
    def test_unknown_query_field_is_refused_before_the_request(self):
        auth = MagicMock()
        with (
            patch.object(sn_api, "unknown_query_fields", return_value=["no_such"]),
            patch.object(sn_api, "table_columns", return_value={"state"}),
        ):
            result = sn_aggregate(_config(), auth, AggregateParams(table="t", query="no_such=1"))
        assert result["error"] == "unknown_query_fields"
        auth.make_request.assert_not_called()

    def test_group_by_and_field_are_checked_too(self):
        auth = MagicMock()
        auth.make_request.return_value = _stats_response({"stats": {"count": "1"}})
        with patch.object(sn_api, "unknown_query_fields", return_value=[]) as check:
            sn_aggregate(
                _config(),
                auth,
                AggregateParams(table="t", aggregate="SUM", field="cost", group_by="model"),
            )
        checked = check.call_args.args[3]
        assert "modelISNOTEMPTY" in checked and "costISNOTEMPTY" in checked

    def test_an_unreadable_dictionary_does_not_block(self):
        auth = MagicMock()
        auth.make_request.return_value = _stats_response({"stats": {"count": "1"}})
        with patch.object(sn_api, "unknown_query_fields", return_value=None):
            result = sn_aggregate(_config(), auth, AggregateParams(table="t", query="a=1"))
        assert result["success"] is True

    @pytest.mark.parametrize(
        "error,expected",
        [("HTTP Error 414: Request-URI Too Large", "414"), ("HTTP Error 403: Forbidden", "403")],
    )
    def test_failed_aggregate_carries_the_same_hint_sn_query_has(self, error, expected):
        auth = MagicMock()
        auth.make_request.side_effect = RuntimeError(error)
        with (
            patch.object(sn_api, "unknown_query_fields", return_value=[]),
            patch.object(sn_api, "_unknown_table_response", return_value=None),
        ):
            result = sn_aggregate(_config(), auth, AggregateParams(table="t", query="a=1"))
        assert expected in result["hint"]


class TestAggregateGroups:
    def _run(self, groups, **kwargs):
        auth = MagicMock()
        auth.make_request.return_value = _stats_response(groups)
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            return sn_aggregate(
                _config(), auth, AggregateParams(table="t", group_by="category", **kwargs)
            )

    def test_few_groups_are_untouched(self):
        groups = _groups(5)
        result = self._run(groups)
        assert result["result"] == groups and "groups" not in result

    def test_excess_groups_are_withheld_and_accounted_for(self):
        result = self._run(_groups(1000))
        assert len(result["result"]) == 200
        assert result["groups"]["total"] == 1000
        assert result["groups"]["withheld"] == 800
        # The total covers every group, not just the ones listed.
        assert result["groups"]["all_groups_total"] == sum(range(1, 1001))
        assert isinstance(result["groups"]["all_groups_total"], int)
        assert result["result"][0]["stats"]["count"] == "1000"

    def test_no_total_is_claimed_when_a_row_is_unreadable(self):
        groups = _groups(5) + [{"stats": {"count": "n/a"}, "groupby_fields": []}]
        result = self._run(groups, group_limit=2)
        assert "all_groups_total" not in result["groups"]

    def test_group_limit_can_be_raised(self):
        assert len(self._run(_groups(300), group_limit=300)["result"]) == 300


class TestReadsDoNotNeedConfirm:
    def test_mixed_tool_does_not_require_confirm_in_its_schema(self):
        schema = ServiceNowMCP._inject_confirmation_schema(
            {"properties": {}, "required": []}, "manage_session_context"
        )
        assert "confirm" in schema["properties"] and "confirm" not in schema["required"]

    def test_write_only_tool_still_requires_it(self):
        schema = ServiceNowMCP._inject_confirmation_schema(
            {"properties": {}, "required": []}, "update_remote_from_local"
        )
        assert "confirm" in schema["required"]

    def test_session_context_get_is_a_read_and_set_is_not(self):
        server = _server("portal_developer")
        assert server._is_read_only_call("manage_session_context", {"action": "get"})
        assert not server._is_read_only_call("manage_session_context", {"action": "set_app"})


class TestHamItomPackage:
    def test_is_the_query_surface_plus_the_checked_asset_writers(self):
        names = set(_server("asset_manager").enabled_tool_names)
        assert names >= {"sn_query", "sn_aggregate", "sn_schema", "sn_discover"}
        writers = {n for n in names if n.startswith(("manage_", "download_", "get_"))}
        assert writers == {"manage_asset", "manage_procurement", "manage_hardware_disposal"}
        assert "sn_write" not in names

    def test_flow_designer_add_on_stays_read_only(self):
        allowed = _server("asset_manager,scripting")._active_action_allowlists[
            "manage_flow_designer"
        ]
        assert set(allowed) == {"list", "get_detail", "get_executions", "get_action_source"}

    def test_add_ons_combine(self):
        names = set(
            _server(
                "asset_manager,scripting,office_files,debug_window,source_sync"
            ).enabled_tool_names
        )
        assert {
            "sn_query",
            "manage_script_include",
            "manage_workbook",
            "act_in_debug_window",
            "update_remote_from_local",
        } <= names

    def test_a_step_allowed_by_vocabulary_is_normalized(self):
        steps = actions.normalize([{"action": "goto", "value": "/x"}, {"action": "reload"}])
        assert [s["action"] for s in steps] == ["goto", "reload"]


class _Element:
    def __init__(self, visible=True, raises=False):
        self.visible, self.raises, self.clicked = visible, raises, False

    def click(self, timeout=None):
        self.clicked = True


class _Matches:
    def __init__(self, elements):
        self.elements = elements
        self.first = elements[0] if elements else None

    def count(self):
        return len(self.elements)


class _Page:
    url = "https://test.service-now.com/x"

    def __init__(self, elements):
        self.elements = elements
        self.frames = [self]
        self.main_frame = self
        self.navigated = []

    def locator(self, selector):
        if selector.endswith(">> visible=true"):
            for element in self.elements:
                if element.raises:
                    raise RuntimeError("frame detached")
            return _Matches([e for e in self.elements if e.visible])
        return _Matches(self.elements)

    def goto(self, url, wait_until=None, timeout=None):
        self.navigated.append((url, timeout))


def _step(**changes):
    step = dict(
        action="click", selector=".x", value=None, key=None, ms=0, timeout_ms=100, state="visible"
    )
    step.update(changes)
    return step


class TestStepsActOnWhatIsVisible:
    def test_click_skips_a_hidden_first_match(self):
        hidden, shown = _Element(visible=False), _Element()
        actions._run_step(_Page([hidden, shown]), _step(), 1)
        assert shown.clicked and not hidden.clicked

    def test_only_hidden_matches_says_so(self):
        with pytest.raises(actions.ActionError, match="none became visible"):
            actions._run_step(_Page([_Element(visible=False)]), _step(), 1)

    def test_unreadable_visibility_falls_back_to_the_first_match(self):
        element = _Element(raises=True)
        actions._run_step(_Page([element]), _step(), 1)
        assert element.clicked

    def test_wait_for_visible_does_not_accept_a_hidden_node(self):
        with pytest.raises(actions.ActionError, match="to be visible"):
            actions._run_step(_Page([_Element(visible=False)]), _step(action="wait_for"), 1)

    def test_wait_for_hidden_accepts_a_hidden_node(self):
        result = actions._run_step(
            _Page([_Element(visible=False)]), _step(action="wait_for", state="hidden"), 1
        )
        assert result == {"state": "hidden"}

    def test_wait_for_attached_accepts_a_hidden_node(self):
        result = actions._run_step(
            _Page([_Element(visible=False)]), _step(action="wait_for", state="attached"), 1
        )
        assert result == {"state": "attached"}


class TestGoto:
    def test_relative_path_resolves_on_this_instance_with_a_load_budget(self):
        page = _Page([])
        actions._run_step(
            page, _step(action="goto", selector=None, value="/sys_user_list.do?x=1"), 1
        )
        url, timeout = page.navigated[0]
        assert url == "https://test.service-now.com/sys_user_list.do?x=1"
        assert timeout >= actions.MIN_NAVIGATION_TIMEOUT_MS

    def test_another_host_is_refused(self):
        page = _Page([])
        with pytest.raises(actions.ActionError, match="stays on"):
            actions._run_step(
                page, _step(action="goto", selector=None, value="https://example.com/"), 1
            )
        assert page.navigated == []

    def test_navigation_is_in_the_batch_budget(self):
        steps = actions.normalize([{"action": "goto", "value": "/a"}])
        assert actions.budget_seconds(steps) >= actions.MIN_NAVIGATION_TIMEOUT_MS / 1000.0


class TestOrphanWindow:
    def _adopt(self, *, port=9333, answers=True, started=1000.0, impersonating=False):
        with (
            patch.object(window, "window_profile_dir", return_value="/p"),
            patch.object(window, "_orphan_window_pid", return_value=4242),
            patch.object(window, "_debugging_port_of", return_value=port),
            patch.object(window, "_cdp_responds", return_value=answers),
            patch.object(window, "_process_started_at", return_value=started),
            patch.object(window, "_impersonation_on_record", return_value=impersonating),
            patch.object(window, "_caller_url", return_value="https://test.service-now.com"),
            patch.object(window, "_chromium_executable", return_value="/c"),
            patch.object(window, "read_window_state", return_value=None),
            patch.object(window, "write_window_state") as written,
        ):
            return window._adopt_orphan_window(MagicMock()), written

    def test_adopts_a_live_window_keyed_on_when_the_process_started(self):
        state, written = self._adopt()
        assert (state.pid, state.port, state.started_at) == (4242, 9333, 1000.0)
        written.assert_called_once()

    @pytest.mark.parametrize(
        "kwargs",
        [{"port": None}, {"answers": False}, {"started": None}, {"impersonating": True}],
    )
    def test_no_adoption_without_proof(self, kwargs):
        state, written = self._adopt(**kwargs)
        assert state is None
        written.assert_not_called()

    def test_port_is_read_from_the_command_line(self):
        ran = MagicMock(stdout="Chromium --remote-debugging-port=9333 --user-data-dir=/p")
        with patch.object(window.subprocess, "run", return_value=ran):
            assert window._debugging_port_of(4242) == 9333

    def test_start_time_is_stable_across_reads(self):
        ran = MagicMock(stdout="Tue Nov  3 10:20:02 2026\n")
        with patch.object(window.subprocess, "run", return_value=ran):
            assert window._process_started_at(4242) == window._process_started_at(4242)

    @pytest.mark.parametrize(
        "content, expected",
        [
            ({"as": "alice", "started_at": 2000.0}, True),  # another host, this lifetime
            ({"as": "alice", "started_at": 500.0}, False),  # a closed window's marker
            ({"as": None, "started_at": 2000.0}, False),  # impersonation ended
            ("{not json", True),  # unread is not "nobody"
        ],
    )
    def test_impersonation_markers(self, tmp_path, content, expected):
        root = tmp_path / ".mfa_servicenow_mcp"
        root.mkdir()
        marker = root / "debug_window_acct.test_host.impersonation.json"
        marker.write_text(content if isinstance(content, str) else json.dumps(content))
        with (
            patch.object(window, "_cache_root", return_value=str(root)),
            patch.object(window, "_window_key", return_value="acct"),
        ):
            assert window._impersonation_on_record(MagicMock(), 1000.0) is expected


class TestSnQueryEnvelope:
    def _query(self, rows, fields):
        with (
            patch.object(sn_api, "unknown_query_fields", return_value=[]),
            patch.object(sn_api, "sn_query_page", return_value=(rows, None)),
        ):
            return sn_api.sn_query(
                _config(), MagicMock(), sn_api.GenericQueryParams(table="t", fields=fields)
            )

    def test_the_request_is_not_echoed_back(self):
        assert "queried_fields" not in self._query([{"a": "1", "b": "2"}], "a,b")

    def test_a_field_absent_from_every_row_is_named(self):
        result = self._query([{"a": "1"}, {"a": "2"}, {"a": "3"}], "a,no_such")
        assert result["empty_or_unknown_fields"] == ["no_such"]

    def test_a_field_present_on_some_rows_is_not_named(self):
        result = self._query([{"a": "1", "b": "2"}, {"a": "3"}], "a,b")
        assert "empty_or_unknown_fields" not in result

    def test_no_rows_says_nothing_about_fields(self):
        assert "empty_or_unknown_fields" not in self._query([], "a,b")


class TestGuardsTheNewPathsMustHonour:
    def test_goto_refuses_to_discard_unsaved_input(self):
        page = _Page([])
        with patch.object(actions, "_dirty_fields", return_value=(["short_description"], "seen")):
            with pytest.raises(actions.ActionError, match="discard_unsaved_input"):
                actions._run_step(page, _step(action="goto", selector=None, value="/a.do"), 1)
        assert page.navigated == []

    def test_goto_proceeds_with_the_approval(self):
        page = _Page([])
        with patch.object(actions, "_dirty_fields", return_value=(["short_description"], "seen")):
            actions._run_step(
                page,
                _step(action="goto", selector=None, value="/a.do"),
                1,
                session={"allow_discard": True},
            )
        assert len(page.navigated) == 1

    def test_encoded_list_query_with_a_dead_column_is_refused(self):
        auth = MagicMock()
        with (
            patch("servicenow_mcp.tools.sn_api.unknown_query_fields", return_value=["nmae"]),
            patch("servicenow_mcp.tools.sn_api.table_columns", return_value={"name"}),
        ):
            result = list_si(_config(), auth, query="nmaeLIKEfoo")
        assert result["error"] == "unknown_query_fields"
        auth.make_request.assert_not_called()

    def test_a_name_with_capitals_after_lowercase_is_still_a_name(self):
        assert si_name_filter("mainINFO") == "nameLIKEmainINFO"
        assert si_name_filter("nameINa,b") == "nameINa,b"

    def test_write_guard_can_find_a_record_by_every_accepted_identifier(self):
        target = _CONCURRENT_EDIT_REGISTRY["manage_script_include"]
        assert set(target.id_columns) >= {"sys_id", "name", "api_name"}

    def test_field_on_a_row_the_size_cut_removed_is_not_called_absent(self):
        rows = [{"a": "1"}, {"a": "2", "b": "3"}]
        with (
            patch.object(sn_api, "unknown_query_fields", return_value=[]),
            patch.object(sn_api, "sn_query_page", return_value=(rows, None)),
            patch.object(sn_api, "truncate_results", return_value=(rows[:1], "cut")),
        ):
            result = sn_api.sn_query(
                _config(), MagicMock(), sn_api.GenericQueryParams(table="t", fields="a,b")
            )
        assert "empty_or_unknown_fields" not in result

    def test_several_sum_fields_claim_no_total_and_are_all_checked(self):
        auth = MagicMock()
        rows = [
            {"stats": {"sum": {"a": "1", "b": "2"}}, "groupby_fields": []},
            {"stats": {"sum": {"a": "3", "b": "4"}}, "groupby_fields": []},
        ]
        auth.make_request.return_value = _stats_response(rows)
        with patch.object(sn_api, "unknown_query_fields", return_value=[]) as check:
            result = sn_aggregate(
                _config(),
                auth,
                AggregateParams(
                    table="t", aggregate="SUM", field="a,b", group_by="c", group_limit=1
                ),
            )
        assert "aISNOTEMPTY" in check.call_args.args[3] and "bISNOTEMPTY" in check.call_args.args[3]
        assert "all_groups_total" not in result["groups"]


def test_goto_says_when_it_landed_somewhere_else():
    class _Redirecting(_Page):
        def goto(self, url, wait_until=None, timeout=None):
            self.url = "https://test.service-now.com/session_timeout.do"

    with patch.object(actions, "_dirty_fields", return_value=([], "none")):
        result = actions._run_step(
            _Redirecting([]), _step(action="goto", selector=None, value="/a.do"), 1
        )
    assert result["redirected_from"] == "https://test.service-now.com/a.do"


class TestScriptAndHostGates:
    def _goto(self, value, **kwargs):
        with patch.object(actions, "_dirty_fields", return_value=([], "none")):
            return actions._run_step(
                _Page([]), _step(action="goto", selector=None, value=value), 1, **kwargs
            )

    def test_goto_to_a_script_runner_needs_the_second_approval(self):
        with pytest.raises(actions.ActionError):
            self._goto("/sys.scripts.do")

    def test_goto_to_a_script_runner_proceeds_with_it(self):
        assert self._goto("/sys.scripts.do", allow_server_script=True)["url"]

    def test_type_is_gated_like_a_key_press(self):
        assert "type" in actions.ACTIVATING_ACTIONS

    @pytest.mark.parametrize(
        "value",
        [
            "https://evil.example\\@test.service-now.com/",
            "https://test.service-now.com\\@evil.example/",
            "/a\nb",
            "//evil.example/x",
            "javascript:alert(1)",
        ],
    )
    def test_goto_cannot_be_talked_off_this_instance(self, value):
        with pytest.raises(actions.ActionError):
            self._goto(value)


class TestListFilterAndOrdering:
    @pytest.mark.parametrize(
        "query",
        [
            "sys_updated_on>2026-01-01",
            "nameISNOTEMPTY",
            "ORDERBYname",
            "ORDERBYDESCname",
            "nameNOT LIKEfoo",
            "a^b",
        ],
    )
    def test_more_encoded_forms_stay_encoded(self, query):
        assert si_name_filter(query) == query

    def test_min_of_a_date_does_not_claim_an_order(self):
        rows = [{"stats": {"min": {"d": "2026-01-01"}}, "groupby_fields": []}] * 3
        auth = MagicMock()
        auth.make_request.return_value = _stats_response(rows)
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            result = sn_aggregate(
                _config(),
                auth,
                AggregateParams(table="t", aggregate="MIN", field="d", group_by="c", group_limit=1),
            )
        assert result["groups"]["order"] == "as returned"


class TestCheapModelMistakes:
    SCHEMA = {"properties": {"table": {}, "query": {}, "fields": {}, "limit": {}, "offset": {}}}

    def _norm(self, arguments):
        return _normalize_arguments("sn_query", arguments, self.SCHEMA)

    def test_unknown_parameter_is_refused_not_ignored(self):
        with pytest.raises(ValueError, match="nothing was run"):
            self._norm({"table": "t", "filter": "a=1"})

    def test_a_near_miss_gets_a_suggestion(self):
        with pytest.raises(ValueError, match="Did you mean 'fields'"):
            self._norm({"table": "t", "field": "a"})

    def test_table_api_names_are_mapped(self):
        assert self._norm({"table": "t", "sysparm_query": "a=1", "sysparm_limit": 5}) == {
            "table": "t",
            "query": "a=1",
            "limit": 5,
        }

    def test_an_alias_never_overrides_the_real_argument(self):
        with pytest.raises(ValueError, match="sysparm_query"):
            self._norm({"table": "t", "query": "a=1", "sysparm_query": "b=2"})

    @pytest.mark.parametrize("key", ["confirm", "confirm_publish", "confirm_instance", "instance"])
    def test_approval_and_routing_fields_are_left_to_their_guards(self, key):
        assert self._norm({"table": "t", key: "x"}) == {"table": "t", key: "x"}

    def test_query_and_fields_keep_their_descriptions_in_the_schema(self):
        tools = {t.name: t for t in asyncio.run(_server("asset_manager")._list_tools_impl())}
        properties = tools["sn_query"].input_schema["properties"]
        assert "not SQL" in properties["query"]["description"]
        assert "description" in properties["fields"]

    def test_sql_shaped_query_is_named_when_it_finds_nothing(self):
        assert "looks like SQL" in sn_api._zero_rows_hint("state=1 AND active=true")
        assert "looks like SQL" not in sn_api._zero_rows_hint("state=1^active=true")

    def test_zero_is_not_called_proof_of_none(self):
        assert "not proof of none" in sn_api._zero_rows_hint("a=1")

    def test_empty_aggregate_carries_the_hint(self):
        auth = MagicMock()
        auth.make_request.return_value = _stats_response([])
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            result = sn_aggregate(
                _config(), auth, AggregateParams(table="t", group_by="a", query="company=Acme")
            )
        assert "field.name=X" in result["hint"]

    @pytest.mark.parametrize(
        "package", ["asset_manager", "asset_manager,scripting", "scripting,asset_manager"]
    )
    def test_instructions_carry_the_map_with_this_package(self, package):
        server = _server(package)
        server.start()
        assert "alm_stockroom" in server.mcp_server.instructions

    @pytest.mark.parametrize("package", ["standard", "scripting", "portal_developer"])
    def test_instructions_stay_out_of_other_packages(self, package):
        server = _server(package)
        server.start()
        assert "alm_stockroom" not in (server.mcp_server.instructions or "")


class TestSecondReview:
    def _dotted_cache(self, tmp_path):
        root = tmp_path / ".mfa_servicenow_mcp"
        root.mkdir()
        return root

    def _patched(self, root):
        return patch.object(window, "_cache_root", return_value=str(root)), patch.object(
            window, "_window_key", return_value="acct"
        )

    def test_markers_are_found_under_a_dot_directory(self, tmp_path):
        root = self._dotted_cache(tmp_path)
        (root / "debug_window_acct.test_host.impersonation.json").write_text(
            json.dumps({"as": "alice", "started_at": 2000.0})
        )
        cache, key = self._patched(root)
        with cache, key:
            assert window._impersonation_on_record(MagicMock(), 1000.0) is True

    def test_another_windows_marker_is_not_read(self, tmp_path):
        root = self._dotted_cache(tmp_path)
        (root / "debug_window_other.test_host.impersonation.json").write_text(
            json.dumps({"as": "alice", "started_at": 2000.0})
        )
        cache, key = self._patched(root)
        with cache, key:
            assert window._impersonation_on_record(MagicMock(), 1000.0) is False

    def test_adoption_keeps_the_launch_stamp_the_login_claim_is_keyed_on(self, tmp_path):
        root = self._dotted_cache(tmp_path)
        (root / "debug_window_acct.dev_host.login.json").write_text(
            json.dumps({"started_at": 1003.25})
        )
        cache, key = self._patched(root)
        with cache, key:
            assert window._original_started_at(MagicMock(), 1000.0) == 1003.25

    def test_with_no_marker_the_process_start_is_used(self, tmp_path):
        root = self._dotted_cache(tmp_path)
        cache, key = self._patched(root)
        with cache, key:
            assert window._original_started_at(MagicMock(), 1000.0) == 1000.0

    def test_an_unreadable_login_marker_blocks_adoption(self, tmp_path):
        root = self._dotted_cache(tmp_path)
        (root / "debug_window_acct.dev_host.login.json").write_text("{bad")
        cache, key = self._patched(root)
        with cache, key:
            assert window._original_started_at(MagicMock(), 1000.0) is None

    def test_allow_duplicate_reaches_its_guard(self):
        schema = {"properties": {"action": {}, "name": {}}}
        arguments = {"action": "create", "name": "n", "allow_duplicate": "true"}
        assert _normalize_arguments("manage_changeset", arguments, schema) == arguments

    @pytest.mark.parametrize(
        "query",
        [
            "sys_idINaaaa1111bbbb2222cccc3333dddd4444",
            "sys_updated_onONToday@javascript:gs.beginningOfToday()@javascript:gs.endOfToday()",
            "sys_created_onBETWEENjavascript:gs.dateGenerate('2026-01-01')@javascript:x",
            "123TEXTQUERY321foo",
            "descriptionANYTHING",
            "sys_created_onRELATIVEGT@dayofweek@ago@3",
        ],
    )
    def test_single_condition_queries_stay_encoded(self, query):
        assert si_name_filter(query) == query

    @pytest.mark.parametrize("name", ["mainINFO", "getUserON", "AbstractAjaxProcessor", "x"])
    def test_names_stay_names(self, name):
        assert si_name_filter(name) == f"nameLIKE{name}"

    @pytest.mark.parametrize("value", ["http:///evil.example/x", "https:evil.example", "/x"])
    def test_goto_with_nothing_to_compare_against_is_refused(self, value):
        page = _Page([])
        page.url = "about:blank"
        with pytest.raises(ValueError):
            actions._same_instance_url(page, value, "")

    @pytest.mark.parametrize(
        "value", ["//evil.example/x", "https://evil.example/", "http://test.service-now.com.evil/"]
    )
    def test_goto_with_the_configured_host_stays_on_it(self, value):
        page = _Page([])
        page.url = "about:blank"
        with pytest.raises(ValueError):
            actions._same_instance_url(page, value, "test.service-now.com")
        assert actions._same_instance_url(page, "/incident_list.do", "test.service-now.com") == (
            "https://test.service-now.com/incident_list.do"
        )

    def test_wait_for_visible_does_not_pass_on_unreadable_visibility(self):
        page = _Page([_Element(visible=True, raises=True)])
        with patch.object(actions, "_has", return_value=True):
            assert actions._any_visible(page, "#x", unreadable=False) is False
            assert actions._any_visible(page, "#x", unreadable=True) is True


@pytest.mark.parametrize(
    "package, widget_files", [("asset_manager,source_sync", False), ("portal_developer", True)]
)
def test_sync_instructions_match_what_the_package_can_download(package, widget_files):
    server = _server(package)
    server.start()
    assert "update_remote_from_local to push" in server.mcp_server.instructions
    assert ("client_script.js" in server.mcp_server.instructions) is widget_files


class TestDomainRulesAreDocuments:
    def test_the_attached_text_is_the_document(self):
        (rules,) = _package_rules("asset_manager")
        server = _server("asset_manager")
        server.start()
        assert rules in server.mcp_server.instructions
        assert "alm_stockroom" in rules

    def test_a_package_without_a_document_adds_nothing(self):
        assert _package_rules("standard") == []
        assert _package_rules("scripting+office_files") == []

    def test_combined_packages_keep_their_rules(self):
        assert len(_package_rules("scripting+asset_manager")) == 1

    def test_general_add_ons_combine_with_any_package(self):
        server = _server("standard,scripting,office_files")
        assert {"manage_business_rule", "manage_workbook", "get_page"} <= set(
            server.enabled_tool_names
        )


def test_sn_query_says_table_is_required_in_the_published_schema():
    tools = {t.name: t for t in asyncio.run(_server("asset_manager")._list_tools_impl())}
    table = tools["sn_query"].input_schema["properties"]["table"]
    assert "(REQUIRED)" in table["description"]
    # sn_aggregate marks it required in the schema, so the name alone is enough there.
    assert "table" in tools["sn_aggregate"].input_schema["required"]


def test_the_rules_carry_what_a_weak_model_gets_wrong_on_these_tables():
    (rules,) = _package_rules("asset_manager")
    for fact in ("aggregate=SUM", "display_value=true", "bound them by date"):
        assert fact in rules


# ---------------------------------------------------------------------------
# Lean reads: leave out the bulk, keep a way to read it in full
# ---------------------------------------------------------------------------


class TestLeanReads:
    def test_workflow_versions_skip_the_compiled_graph_and_order_by_a_real_column(self):
        from servicenow_mcp.tools import workflow_tools as wt

        fields = wt.VERSION_LISTING_FIELDS.split(",")
        for heavy in ("full_sequences", "expected_sequences", "activity_stages"):
            assert heavy not in fields
        assert "published" in fields and "sys_id" in fields
        with patch.object(wt, "sn_query_page", return_value=([], 0)) as qp:
            wt.list_workflow_versions(MagicMock(), MagicMock(), {"workflow_id": "w1"})
            wt._fetch_workflow_versions(MagicMock(), MagicMock(), "w1")
        for call in qp.call_args_list:
            # wf_workflow_version has no `version` column; ordering by it is ignored.
            assert call.kwargs["orderby"] == "-sys_created_on"
            assert call.kwargs["fields"] == wt.VERSION_LISTING_FIELDS

    def test_published_version_lookup_reads_only_the_id(self):
        from servicenow_mcp.tools import workflow_tools as wt

        with (
            patch.object(wt, "sn_query_page", return_value=([{"sys_id": "v1"}], 1)) as qp,
            patch.object(wt, "sn_query_all", return_value=[]),
        ):
            result = wt._fetch_workflow_activities(MagicMock(), MagicMock(), "w1")
        lookup = qp.call_args_list[0].kwargs
        assert lookup["fields"] == "sys_id" and lookup["orderby"] == "-sys_created_on"
        assert result["version_id"] == "v1"

    @pytest.mark.parametrize("summary", [True, False])
    def test_flow_label_cache_is_a_size_in_summary_mode_only(self, summary):
        from servicenow_mcp.tools import flow_designer_tools as fd

        flow = {
            "sys_id": "aaaa1111bbbb2222cccc3333dddd4444",
            "name": "F",
            "label_cache": "x" * 5000,
        }
        params = fd.GetFlowDetailsParams(
            flow_id=flow["sys_id"],
            summary_format=summary,
            include_triggers=False,
            include_structure=False,
            include_executions_summary=False,
        )
        with (
            patch.object(fd, "_is_browser_auth", return_value=False),
            patch.object(fd, "sn_query_page", return_value=([dict(flow)], 1)),
            patch.object(fd, "_flow_runtime_status", return_value={}),
        ):
            result = fd.get_flow_details(MagicMock(), MagicMock(), params)
        if summary:
            assert "5,000 characters left out" in result["flow"]["label_cache"]
        else:
            assert result["flow"]["label_cache"] == "x" * 5000

    def test_user_listing_is_projected_and_points_at_the_full_read(self):
        from servicenow_mcp.tools import user_tools as ut

        params = ut.ListUsersParams(limit=5)
        with patch.object(ut, "sn_query_page", return_value=([{"sys_id": "u1"}], 1)) as qp:
            result = ut.list_users(MagicMock(), MagicMock(), params)
        assert qp.call_args.kwargs["fields"] == ut.USER_LISTING_FIELDS
        assert "manage_user(action='get'" in result["full_record"]

    def test_change_tasks_are_projected_and_a_failed_read_is_not_none(self):
        from servicenow_mcp.services import change as ch

        with patch.object(
            ch, "sn_query_page", side_effect=[([{"sys_id": "c1"}], 1), ([{"sys_id": "t1"}], 1)]
        ) as qp:
            result = ch.get(MagicMock(), MagicMock(), change_id="c1")
        task_call = qp.call_args_list[1].kwargs
        assert task_call["fields"] == ch.TASK_LISTING_FIELDS
        assert task_call["fail_silently"] is False
        assert "tasks_complete" not in result
        with patch.object(
            ch, "sn_query_page", side_effect=[([{"sys_id": "c1"}], 1), RuntimeError("HTTP 500")]
        ):
            failed = ch.get(MagicMock(), MagicMock(), change_id="c1")
        assert failed["success"] is False and "tasks" not in failed

    def test_change_listing_is_projected_and_loud(self):
        from servicenow_mcp.services import change as ch

        with patch.object(ch, "sn_query_page", return_value=([{"sys_id": "c1"}], 1)) as qp:
            result = ch.get(MagicMock(), MagicMock())
        assert qp.call_args.kwargs["fields"] == ch.CHANGE_LISTING_FIELDS
        assert qp.call_args.kwargs["fail_silently"] is False
        assert "manage_change(action='get'" in result["full_record"]
