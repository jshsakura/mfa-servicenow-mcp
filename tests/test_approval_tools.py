"""manage_approval: caller verification, write, proof."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools import approval_tools as at
from servicenow_mcp.tools.approval_tools import ManageApprovalParams, manage_approval
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

AP = "aaaa1111bbbb2222cccc3333dddd4444"
BOB = "bbbb1111cccc2222dddd3333eeee4444"
ALICE = "cccc1111dddd2222eeee3333ffff4444"
DOC = "dddd1111eeee2222ffff3333aaaa4444"
_NOW = datetime.now(timezone.utc)


def _ts(delta_days: int) -> str:
    return (_NOW + timedelta(days=delta_days)).strftime("%Y-%m-%d %H:%M:%S")


class Env:
    """Fake instance: sn_query_page answers by table; tracks the approval row state."""

    def __init__(self, caller="alice", state="requested", delegates=None, applies=True):
        self.caller = caller
        self.state = state
        self.delegates = delegates if delegates is not None else []
        self.applies = applies
        self.patches = []

    def query(self, config, auth_manager, *, table, query, fields, **kw):
        if table == "sysapproval_approver":
            return (
                [
                    {
                        "sys_id": AP,
                        "approver": {"value": BOB, "display_value": "Bob"},
                        "state": self.state,
                        "document_id": {"value": DOC},
                        "source_table": "change_request",
                    }
                ],
                1,
            )
        if table == "sys_user":
            if f"sys_id={BOB}" in query or "user_name=bob" in query:
                return ([{"sys_id": BOB, "user_name": "bob", "name": "Bob"}], 1)
            if "user_name=alice" in query:
                return ([{"sys_id": ALICE, "user_name": "alice", "name": "Alice"}], 1)
            return ([], 0)
        if table == "sys_user_delegate":
            assert f"user={BOB}" in query and f"delegate={ALICE}" in query
            assert "approvals=true" in query
            return (self.delegates, len(self.delegates))
        if table == "change_request":
            return ([{"sys_id": DOC, "approval": "approved" if self.applies else "requested"}], 1)
        raise AssertionError(table)

    def request(self, method, url, json=None, headers=None):
        self.patches.append((url, json))
        if self.applies:
            self.state = json["state"]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp


@pytest.fixture
def make():
    cfg = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="alice", password="x")),
    )
    am = MagicMock(spec=AuthManager)

    def build(**kw):
        env = Env(**kw)
        am.make_request.side_effect = env.request
        patches = [
            patch.object(at, "sn_query_page", env.query),
            patch.object(at, "_authenticated_user", lambda *a, **k: env.caller),
        ]
        for p in patches:
            p.start()
        return env

    yield cfg, am, build
    patch.stopall()


def run(cfg, am, **kw):
    kw.setdefault("approval_id", AP)
    return manage_approval(cfg, am, ManageApprovalParams(**kw))


def test_approver_match(make):
    cfg, am, build = make
    env = build(caller="BOB")  # case-insensitive match
    r = run(cfg, am, action="approve", comments="ok")
    assert r["success"] and r["applied"] and r["basis"] == "approver"
    assert r["state_after"] == "approved" and r["parent_approval"] == "approved"
    assert "sys_flow_context" in r["note"]
    assert env.patches[0][1] == {"state": "approved", "comments": "ok"}


def test_valid_delegate(make):
    cfg, am, build = make
    build(
        delegates=[
            {"user": BOB, "delegate": ALICE, "approvals": "true", "starts": _ts(-1), "ends": ""}
        ]
    )
    r = run(cfg, am, action="approve")
    assert r["success"] and r["basis"] == "delegate"


def test_expired_delegate_refused(make):
    cfg, am, build = make
    env = build(delegates=[{"starts": _ts(-10), "ends": _ts(-1)}])
    r = run(cfg, am, action="approve")
    assert not r["success"] and r["error"] == "caller_not_approver"
    assert "window" in r["because"]
    assert env.patches == []


def test_future_delegate_refused(make):
    cfg, am, build = make
    env = build(delegates=[{"starts": _ts(2), "ends": ""}])
    assert run(cfg, am, action="approve")["error"] == "caller_not_approver"
    assert env.patches == []


def test_unknown_identity_refused(make):
    cfg, am, build = make
    env = build(caller=None)
    r = run(cfg, am, action="approve")
    assert r["error"] == "caller_not_approver" and "could not be determined" in r["because"]
    assert env.patches == []


def test_confirm_on_behalf_mismatch_refused(make):
    cfg, am, build = make
    env = build()
    r = run(cfg, am, action="approve", confirm_on_behalf="carol")
    assert r["error"] == "caller_not_approver"
    assert "confirm_on_behalf='bob'" in r["message"]
    assert env.patches == []


def test_confirm_on_behalf_match_proceeds_with_comment(make):
    cfg, am, build = make
    env = build()
    r = run(cfg, am, action="approve", comments="fine", confirm_on_behalf="bob")
    assert r["success"] and r["basis"] == "on_behalf"
    body = env.patches[0][1]
    assert "fine" in body["comments"]
    assert "Approved via MCP by alice on behalf of bob" in body["comments"]


def test_on_behalf_with_unknown_identity_names_unidentified(make):
    cfg, am, build = make
    env = build(caller=None)
    r = run(cfg, am, action="reject", comments="no", confirm_on_behalf="bob")
    assert r["basis"] == "on_behalf"
    assert (
        "Rejected via MCP by unidentified session on behalf of bob" in env.patches[0][1]["comments"]
    )


def test_non_requested_state_refused(make):
    cfg, am, build = make
    env = build(caller="bob", state="approved")
    r = run(cfg, am, action="approve")
    assert r["error"] == "not_actionable" and r["current_state"] == "approved"
    assert env.patches == []


def test_applied_false_when_row_unchanged(make):
    cfg, am, build = make
    build(caller="bob", applies=False)
    r = run(cfg, am, action="approve")
    assert r["applied"] is False and r["success"] is False
    assert r["state_after"] == "requested" and "business rule" in r["message"]


def test_reject_needs_comments(make):
    with pytest.raises(ValueError, match="comments"):
        ManageApprovalParams(action="reject", approval_id=AP)
    cfg, am, build = make
    build(caller="bob")
    r = at.decide_approval(cfg, am, approval_id=AP, decision="rejected", comments="  ")
    assert r["error"] == "comments_required"


def test_dry_run_makes_no_write(make):
    cfg, am, build = make
    env = build(caller="bob")
    r = run(cfg, am, action="approve", dry_run=True)
    assert r["dry_run"] and r["basis"] == "approver"
    assert env.patches == []


def test_dry_run_still_refuses_unverified_caller(make):
    cfg, am, build = make
    build()
    r = run(cfg, am, action="approve", dry_run=True)
    assert r["error"] == "caller_not_approver"


def test_list_for_caller_filters_approver_and_state(make):
    cfg, am, build = make
    seen = {}
    env = build(caller="alice")
    orig = env.query

    def spy(config, auth_manager, *, table, query, **kw):
        if table == "sysapproval_approver":
            seen["q"] = query
        return orig(config, auth_manager, table=table, query=query, **kw)

    with patch.object(at, "sn_query_page", spy):
        r = manage_approval(cfg, am, ManageApprovalParams(action="list"))
    assert seen["q"] == f"approver={ALICE}^state=requested"
    assert r["success"] and r["count"] == 1
