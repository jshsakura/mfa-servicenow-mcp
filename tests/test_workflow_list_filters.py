"""manage_workflow list: `active` and the run table are read from the published
version, because wf_workflow has no `active` column and its `table` is mostly blank."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools import workflow_tools as wt

WF_A = "aaaa1111bbbb2222cccc3333dddd4444"
WF_B = "bbbb2222cccc3333dddd4444eeee5555"
VER_A = "cccc3333dddd4444eeee5555ffff6666"


def _run(params, versions_for_filter, published, page_rows):
    calls = []

    def query_all(config, auth, *, table, query, fields, **kw):
        calls.append((table, query))
        if "workflowIN" in query:
            return published
        return versions_for_filter

    def query_page(config, auth, *, table, query, fields, **kw):
        calls.append((table, query))
        return page_rows, len(page_rows)

    with (
        patch.object(wt, "sn_query_all", side_effect=query_all),
        patch.object(wt, "sn_query_page", side_effect=query_page),
    ):
        return wt.list_workflows(MagicMock(), MagicMock(), params), calls


def test_table_filter_goes_through_the_published_version():
    result, calls = _run(
        {"table": "sc_req_item, sc_request", "limit": 10},
        versions_for_filter=[{"workflow": WF_A}, {"workflow": WF_B}],
        published=[{"sys_id": VER_A, "workflow": WF_A, "table": "sc_req_item", "active": "true"}],
        page_rows=[{"sys_id": WF_A, "name": "A", "table": ""}, {"sys_id": WF_B, "name": "B"}],
    )
    version_q = calls[0]
    assert version_q == ("wf_workflow_version", "published=true^tableINsc_req_item,sc_request")
    list_q = [q for t, q in calls if t == "wf_workflow"][0]
    assert list_q == f"sys_idIN{WF_A},{WF_B}"
    # wf_workflow.table is never used as the filter
    assert all("tableIN" not in q for t, q in calls if t == "wf_workflow")
    a, b = result["workflows"]
    assert a["run_table"] == "sc_req_item" and a["active"] == "true"
    assert b["published_version"] == "none"


def test_active_filter_is_never_sent_to_wf_workflow():
    _, calls = _run(
        {"active": True},
        versions_for_filter=[{"workflow": WF_A}],
        published=[],
        page_rows=[{"sys_id": WF_A}],
    )
    assert calls[0] == ("wf_workflow_version", "published=true^active=true")
    assert all("active=" not in q for t, q in calls if t == "wf_workflow")


def test_no_matching_published_version_returns_empty_with_reason():
    result, calls = _run({"table": "incident"}, [], [], [{"sys_id": WF_A}])
    assert result["workflows"] == [] and "PUBLISHED" in result["note"]
    assert all(t != "wf_workflow" for t, _ in calls)


def test_unread_published_version_is_not_none():
    def query_all(config, auth, *, table, query, fields, **kw):
        raise RuntimeError("HTTP 502")

    with (
        patch.object(wt, "sn_query_all", side_effect=query_all),
        patch.object(wt, "sn_query_page", return_value=([{"sys_id": WF_A}], 1)),
    ):
        result = wt.list_workflows(MagicMock(), MagicMock(), {})
    assert result["workflows"][0]["published_version"] == "unread"


def test_list_projects_columns_instead_of_whole_records():
    seen = {}

    def query_page(config, auth, *, table, query, fields, **kw):
        seen["fields"] = fields
        return [], 0

    with (
        patch.object(wt, "sn_query_page", side_effect=query_page),
        patch.object(wt, "sn_query_all", return_value=[]),
    ):
        wt.list_workflows(MagicMock(), MagicMock(), {})
    assert seen["fields"] and "sys_id" in seen["fields"] and "active" not in seen["fields"]
