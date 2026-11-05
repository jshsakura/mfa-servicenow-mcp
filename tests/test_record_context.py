"""get_record_context: prefix resolution, sections, and the guard vocabulary."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from servicenow_mcp.tools import record_context_tools as rc
from servicenow_mcp.tools.record_context_tools import RecordContextParams, get_record_context
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

RITM = "aaaa1111bbbb2222cccc3333dddd4444"
INC = "aaaa1111bbbb2222cccc3333dddd5555"
CHG = "aaaa1111bbbb2222cccc3333dddd6666"
USER_A = "aaaa1111bbbb2222cccc3333dddd7777"
USER_B = "aaaa1111bbbb2222cccc3333dddd8888"
GROUP = "aaaa1111bbbb2222cccc3333dddd9999"


def cell(value, display=None):
    return {"value": value, "display_value": value if display is None else display}


def row(**kw):
    return {k: (v if isinstance(v, dict) else cell(v)) for k, v in kw.items()}


def http_error(status):
    resp = MagicMock()
    resp.status_code = status
    err = requests.exceptions.HTTPError(f"HTTP {status}")
    err.response = resp
    return err


class Fake:
    """sn_query_page stand-in: handlers keyed by table, called with (query, fields)."""

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def __call__(self, config, auth, *, table, query, fields, limit, offset, **kw):
        self.calls.append((table, query))
        handler = self.handlers.get(table)
        if handler is None:
            return [], 0
        out = handler(query) if callable(handler) else handler
        if isinstance(out, Exception):
            raise out
        return out


SYS_NUMBER = (
    [
        row(prefix="INC", category="incident"),
        row(prefix="RITM", category="sc_req_item"),
        row(prefix="CHG", category="change_request"),
    ],
    3,
)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    rc._sys_number_cache.clear()
    monkeypatch.setattr(rc, "_read_failure_verdict", lambda *a, **k: None)
    monkeypatch.setattr(rc, "sn_count_by_group", lambda *a, **k: {})
    yield
    rc._sys_number_cache.clear()


@pytest.fixture
def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def run(cfg, fake, number, sections=None):
    with patch.object(rc, "sn_query_page", fake):
        return get_record_context(
            cfg, MagicMock(), RecordContextParams(number=number, sections=sections)
        )


def test_prefix_resolves_and_is_memoised(cfg):
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "incident": ([row(sys_id=INC, number="INC0000001", state=cell("2", "In Progress"))], 1),
        }
    )
    out = run(cfg, fake, "INC0000001", sections=["sla"])
    assert out["table"] == "incident" and out["record"]["state"] == {
        "value": "2",
        "label": "In Progress",
    }
    run(cfg, fake, "INC0000001", sections=["sla"])
    assert [t for t, _ in fake.calls].count("sys_number") == 1


def test_failed_prefix_read_is_not_memoised(cfg):
    fake = Fake({"sys_number": http_error(500)})
    out = run(cfg, fake, "INC0000001")
    assert out["error"] == "prefix_map_unreadable" and not rc._sys_number_cache


def test_unknown_prefix_lists_known(cfg):
    out = run(cfg, Fake({"sys_number": SYS_NUMBER}), "ZZZ0000001")
    assert out["error"] == "unknown_number_prefix"
    assert out["known_prefixes"] == ["CHG", "INC", "RITM"]


def test_bad_number_refused(cfg):
    assert run(cfg, Fake({"sys_number": SYS_NUMBER}), "nonsense")["error"] == "bad_number"


def test_unknown_section_refused(cfg):
    out = run(cfg, Fake({"sys_number": SYS_NUMBER}), "INC0000001", sections=["bogus"])
    assert out["error"] == "unknown_section"


def test_record_404_is_undetermined_not_not_found(cfg):
    fake = Fake({"sys_number": SYS_NUMBER, "incident": http_error(404)})
    out = run(cfg, fake, "INC0000001")
    assert out["success"] is False and out["availability"] == "undetermined"
    assert "not found" not in out["because"].lower()


def test_record_no_row_is_undetermined(cfg):
    fake = Fake({"sys_number": SYS_NUMBER, "incident": ([], 0)})
    out = run(cfg, fake, "INC0000001")
    assert out["error"] == "record_not_determined" and out["availability"] == "undetermined"
    assert "ACL" in out["because"]


def test_ritm_variables_choice_and_reference(cfg):
    q_choice, q_ref = "aaaa1111bbbb2222cccc3333dddd0001", "aaaa1111bbbb2222cccc3333dddd0002"
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "sc_req_item": (
                [
                    row(
                        sys_id=RITM,
                        number="RITM0010002",
                        request=cell("aaaa1111bbbb2222cccc3333dddd0003", "REQ0010001"),
                    )
                ],
                1,
            ),
            "sc_item_option_mtom": (
                [
                    row(sc_item_option="aaaa1111bbbb2222cccc3333dddd00a1"),
                    row(sc_item_option="aaaa1111bbbb2222cccc3333dddd00a2"),
                ],
                2,
            ),
            "sc_item_option": (
                [
                    row(
                        sys_id="aaaa1111bbbb2222cccc3333dddd00a1",
                        item_option_new=q_choice,
                        value="2",
                        order="100",
                    ),
                    row(
                        sys_id="aaaa1111bbbb2222cccc3333dddd00a2",
                        item_option_new=q_ref,
                        value=USER_A,
                        order="200",
                    ),
                ],
                2,
            ),
            "item_option_new": (
                [
                    row(
                        sys_id=q_choice,
                        name="size",
                        question_text="Size",
                        type=cell("5", "Select Box"),
                        reference="",
                    ),
                    row(
                        sys_id=q_ref,
                        name="requested_for",
                        question_text="For",
                        type=cell("8", "Reference"),
                        reference="sys_user",
                    ),
                ],
                2,
            ),
            "question_choice": ([row(question=q_choice, value="2", text="Large")], 1),
            "sys_user": ([row(sys_id=USER_A, name="Alice Example")], 1),
        }
    )
    out = run(cfg, fake, "RITM0010002", sections=["variables"])
    by_name = {v["name"]: v for v in out["variables"]["variables"]}
    assert by_name["size"]["display"] == "Large"
    assert by_name["requested_for"]["display"] == "Alice Example"
    # exactly one batched read for the referenced table
    assert [t for t, _ in fake.calls].count("sys_user") == 1


def test_unresolved_variable_is_marked(cfg):
    q = "aaaa1111bbbb2222cccc3333dddd0001"
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "sc_req_item": ([row(sys_id=RITM, number="RITM0010002")], 1),
            "sc_item_option_mtom": ([row(sc_item_option="aaaa1111bbbb2222cccc3333dddd00a1")], 1),
            "sc_item_option": (
                [row(sys_id="aaaa1111bbbb2222cccc3333dddd00a1", item_option_new=q, value="9")],
                1,
            ),
            "item_option_new": (
                [row(sys_id=q, name="size", question_text="Size", type=cell("5", "Select Box"))],
                1,
            ),
            "question_choice": http_error(403),
        }
    )
    out = run(cfg, fake, "RITM0010002", sections=["variables"])
    assert "unresolved" in out["variables"]["variables"][0]


def test_reference_targets_follow_the_measured_columns(cfg):
    # Measured live: 21 keeps its table in list_table, 31 names sys_user in
    # reference, and a lookup may store a column other than sys_id.
    q_list, q_for, q_look = (
        "aaaa1111bbbb2222cccc3333dddd0011",
        "aaaa1111bbbb2222cccc3333dddd0012",
        "aaaa1111bbbb2222cccc3333dddd0013",
    )
    asset_a, asset_b = "aaaa1111bbbb2222cccc3333dddd0a01", "aaaa1111bbbb2222cccc3333dddd0a02"
    opts = [
        row(
            sys_id="aaaa1111bbbb2222cccc3333dddd00b1",
            item_option_new=q_list,
            value=f"{asset_a},{asset_b}",
            order="1",
        ),
        row(
            sys_id="aaaa1111bbbb2222cccc3333dddd00b2",
            item_option_new=q_for,
            value=USER_A,
            order="2",
        ),
        row(
            sys_id="aaaa1111bbbb2222cccc3333dddd00b3",
            item_option_new=q_look,
            value="laptop",
            order="3",
        ),
    ]
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "sc_req_item": ([row(sys_id=RITM, number="RITM0010002")], 1),
            "sc_item_option_mtom": ([row(sc_item_option=o["sys_id"]["value"]) for o in opts], 3),
            "sc_item_option": (opts, 3),
            "item_option_new": (
                [
                    row(
                        sys_id=q_list,
                        name="assets",
                        question_text="Assets",
                        type=cell("21", "List Collector"),
                        reference="",
                        list_table="alm_asset",
                    ),
                    row(
                        sys_id=q_for,
                        name="who",
                        question_text="Requested for",
                        type=cell("31", "Requested For"),
                        reference="sys_user",
                    ),
                    row(
                        sys_id=q_look,
                        name="kind",
                        question_text="Kind",
                        type=cell("18", "Lookup Select Box"),
                        lookup_table="x_kind",
                        lookup_value="code",
                    ),
                ],
                3,
            ),
            "alm_asset": (
                [row(sys_id=asset_a, name="Asset A"), row(sys_id=asset_b, name="Asset B")],
                2,
            ),
            "sys_user": ([row(sys_id=USER_A, name="Alice Example")], 1),
        }
    )
    out = run(cfg, fake, "RITM0010002", sections=["variables"])
    by_name = {v["name"]: v for v in out["variables"]["variables"]}
    assert by_name["assets"]["display"] == "Asset A, Asset B"
    assert by_name["who"]["display"] == "Alice Example"
    assert "not a sys_id" in by_name["kind"]["unresolved"]
    assert "x_kind" not in [t for t, _ in fake.calls]


def test_capped_variable_read_says_incomplete(cfg):
    q = "aaaa1111bbbb2222cccc3333dddd0021"
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "sc_req_item": ([row(sys_id=RITM, number="RITM0010002")], 1),
            "sc_item_option_mtom": ([row(sc_item_option="aaaa1111bbbb2222cccc3333dddd00c1")], 250),
            "sc_item_option": (
                [row(sys_id="aaaa1111bbbb2222cccc3333dddd00c1", item_option_new=q, value="x")],
                1,
            ),
            "item_option_new": (
                [
                    row(
                        sys_id=q,
                        name="note",
                        question_text="Note",
                        type=cell("6", "Single Line Text"),
                    )
                ],
                1,
            ),
        }
    )
    out = run(cfg, fake, "RITM0010002", sections=["variables"])
    assert out["variables"]["complete"] is False and out["variables"]["total"] == 250
    assert "unresolved" not in out["variables"]["variables"][0]


def test_incident_links_outgoing_incoming_cap_and_complete(cfg):
    many = [
        row(
            sys_id=f"aaaa1111bbbb2222cccc3333dd{i:06d}",
            number=f"INC{i:07d}",
            state="1",
            short_description="child",
        )
        for i in range(20)
    ]
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "incident": lambda q: (
                (
                    [
                        row(
                            sys_id=INC,
                            number="INC0000001",
                            rfc=cell(CHG, "CHG0000009"),
                            parent_incident="",
                        )
                    ],
                    1,
                )
                if q.startswith("number=")
                else (many, 35)
            ),
            "change_request": lambda q: (
                (
                    [
                        row(
                            sys_id=CHG,
                            number="CHG0000009",
                            state=cell("-5", "New"),
                            short_description="Upgrade",
                        )
                    ],
                    1,
                )
                if q.startswith("sys_idIN")
                else ([], 0)
            ),
            "task": ([], 0),
            "task_rel_task": ([], 0),
        }
    )
    out = run(cfg, fake, "INC0000001", sections=["links"])
    links = out["links"]
    assert links["outgoing"][0]["number"] == "CHG0000009" and links["outgoing"][0]["state"] == "New"
    child = links["incoming"]["incident_parent_incident"]
    assert child["total"] == 35 and child["complete"] is False and len(child["rows"]) == 20


def test_incoming_list_that_fails_is_unchecked(cfg):
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "incident": lambda q: (
                ([row(sys_id=INC, number="INC0000001")], 1)
                if q.startswith("number=")
                else http_error(500)
            ),
            "task": ([], 0),
            "task_rel_task": ([], 0),
            "change_request": ([], 0),
        }
    )
    out = run(cfg, fake, "INC0000001", sections=["links"])
    bad = out["links"]["incoming"]["incident_parent_incident"]
    assert bad["checked"] is False and "because" in bad
    assert "links" not in out.get("empty_sections", [])


def test_approvals_with_valid_delegate(cfg):
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "sc_req_item": ([row(sys_id=RITM, number="RITM0010002")], 1),
            "sysapproval_approver": (
                [
                    row(
                        approver=cell(USER_A, "Alice Example"),
                        state=cell("requested", "Requested"),
                        group=cell(GROUP, "Approvers"),
                        order="1",
                    )
                ],
                1,
            ),
            "sysapproval_group": ([], 0),
            "sys_user_delegate": (
                [
                    row(
                        user=cell(USER_A, "Alice Example"),
                        delegate=cell(USER_B, "Bob Example"),
                        ends="",
                    )
                ],
                1,
            ),
        }
    )
    out = run(cfg, fake, "RITM0010002", sections=["approvals"])
    ap = out["approvals"]
    assert ap["approvers"]["rows"][0]["state"] == "Requested"
    assert ap["valid_delegates"]["rows"][0]["delegate"] == "Bob Example"
    delegate_query = [q for t, q in fake.calls if t == "sys_user_delegate"][0]
    assert USER_A in delegate_query and "approvals=true" in delegate_query


def test_unreadable_section_is_checked_false_not_empty(cfg):
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "incident": ([row(sys_id=INC, number="INC0000001")], 1),
            "task_sla": http_error(403),
        }
    )
    out = run(cfg, fake, "INC0000001", sections=["sla"])
    assert out["sla"]["checked"] is False and out["sla"]["because"]
    assert "sla" not in out.get("empty_sections", [])


def test_empty_sections_are_named(cfg):
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "incident": ([row(sys_id=INC, number="INC0000001")], 1),
            "task_sla": ([], 0),
            "sys_flow_context": ([], 0),
        }
    )
    out = run(cfg, fake, "INC0000001", sections=["sla", "flows", "journal"])
    assert out["empty_sections"] == ["sla", "flows", "journal"]
    assert "sla" not in out


def test_flows_on_latest_snapshot_and_counts(cfg):
    flow_id, snap_new, snap_old = (
        "aaaa1111bbbb2222cccc3333dddd0f01",
        "aaaa1111bbbb2222cccc3333dddd0e01",
        "aaaa1111bbbb2222cccc3333dddd0e02",
    )
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "incident": ([row(sys_id=INC, number="INC0000001")], 1),
            "sys_flow_context": (
                [
                    row(
                        name="Sample Flow",
                        state=cell("COMPLETE", "Complete"),
                        flow=flow_id,
                        snapshot=snap_old,
                        sys_created_on="2026-01-01 10:00:00",
                    ),
                    row(
                        name="Sample Flow",
                        state=cell("COMPLETE", "Complete"),
                        flow=flow_id,
                        snapshot=snap_new,
                        sys_created_on="2026-01-02 10:00:00",
                    ),
                ],
                2,
            ),
            "sys_hub_flow": ([row(sys_id=flow_id, latest_snapshot=snap_new)], 1),
        }
    )
    out = run(cfg, fake, "INC0000001", sections=["flows"])
    flows = out["flows"]
    assert [c["on_latest_snapshot"] for c in flows["contexts"]] == [False, True]
    assert flows["by_state"] == {"Complete": 2}


def test_tasks_for_ritm_and_not_applicable_for_incident(cfg):
    fake = Fake(
        {
            "sys_number": SYS_NUMBER,
            "sc_req_item": ([row(sys_id=RITM, number="RITM0010002")], 1),
            "incident": ([row(sys_id=INC, number="INC0000001")], 1),
            "sc_task": (
                [
                    row(
                        number="SCTASK0000001",
                        state=cell("1", "Open"),
                        assignment_group=cell(GROUP, "Fulfillers"),
                        assigned_to="",
                    )
                ],
                1,
            ),
        }
    )
    out = run(cfg, fake, "RITM0010002", sections=["tasks"])
    assert out["tasks"]["rows"][0]["number"] == "SCTASK0000001"
    out = run(cfg, fake, "INC0000001", sections=["tasks"])
    assert "tasks" in out["not_applicable"]


def test_journal_counts_and_failed_aggregate(cfg, monkeypatch):
    fake = Fake({"sys_number": SYS_NUMBER, "incident": ([row(sys_id=INC, number="INC0000001")], 1)})
    monkeypatch.setattr(rc, "sn_count_by_group", lambda *a, **k: {"work_notes": 3, "comments": 1})
    assert run(cfg, fake, "INC0000001", sections=["journal"])["journal"]["counts"] == {
        "comments": 1,
        "work_notes": 3,
    }
    monkeypatch.setattr(rc, "sn_count_by_group", lambda *a, **k: None)
    assert run(cfg, fake, "INC0000001", sections=["journal"])["journal"]["checked"] is False


def _approval_fake(record_table, record_row, approver):
    return Fake(
        {
            "sys_number": SYS_NUMBER,
            record_table: ([record_row], 1),
            "sysapproval_approver": (
                [
                    row(
                        approver=cell(approver, "Alice Example"),
                        state=cell("requested", "Requested"),
                        order="1",
                    )
                ],
                1,
            ),
            "sysapproval_group": ([], 0),
            "sys_user_delegate": ([], 0),
        }
    )


def test_self_approval_warned_for_assignee(cfg):
    fake = _approval_fake(
        "change_request",
        row(sys_id=CHG, number="CHG0000001", assigned_to=cell(USER_A, "Alice Example")),
        USER_A,
    )
    out = run(cfg, fake, "CHG0000001", sections=["approvals"])
    chk = out["approvals"]["self_approval_check"]
    assert out["approvals"]["warnings"][0]["code"] == "SELF_APPROVAL"
    assert out["approvals"]["warnings"][0]["is"] == "assigned_to"
    assert chk["checked"] is False  # requested_by was not in the row
    assert "requested_by" in chk["unchecked_fields"]


def test_self_approval_warned_for_requester_by_sys_id_not_label(cfg):
    fake = _approval_fake(
        "change_request",
        row(
            sys_id=CHG,
            number="CHG0000001",
            assigned_to=cell(USER_B, "Alice Example"),
            requested_by=cell(USER_A, "Someone Else"),
        ),
        USER_A,
    )
    out = run(cfg, fake, "CHG0000001", sections=["approvals"])
    warns = out["approvals"]["warnings"]
    assert [w["is"] for w in warns] == ["requested_by"]
    assert out["approvals"]["self_approval_check"]["checked"] is True


def test_no_self_approval_when_fields_read_and_different(cfg):
    fake = _approval_fake(
        "incident",
        row(sys_id=INC, number="INC0000001", assigned_to=cell(USER_B, "Bob Example")),
        USER_A,
    )
    out = run(cfg, fake, "INC0000001", sections=["approvals"])
    assert "warnings" not in out["approvals"]
    assert out["approvals"]["self_approval_check"] == {"checked": True, "warnings": []}


def test_self_approval_unchecked_when_assignee_not_read(cfg):
    fake = _approval_fake("incident", row(sys_id=INC, number="INC0000001"), USER_A)
    out = run(cfg, fake, "INC0000001", sections=["approvals"])
    chk = out["approvals"]["self_approval_check"]
    assert chk["checked"] is False and "assigned_to" in chk["unchecked_fields"]
