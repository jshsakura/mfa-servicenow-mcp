"""Publish vs activate, captured from the UI (2026-06-30) and live-verified
over curl_cffi (2026-07-06):
- publish (snapshot recompile) = safeEdit GraphQL lock (read → upsert) THEN
  POST /flow/{id}/snapshot with the FULL flow model as the body. The UI gzips
  that body, so captures showed it "empty" — a truly bodyless snapshot 500s
  ({} → "Flow id cannot be null or empty"), which is why every earlier attempt
  failed.
- activate/deactivate of an ALREADY-published flow = GET /flow/{id}/activate|
  deactivate (a plain toggle, no recompile).
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    ManageFlowEditParams,
    _toggle_active,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _ok(body=None):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body if body is not None else {"result": {}}
    return r


def _safe_edit_status(**status):
    return {"data": {"global": {"snFlowDesigner": {"safeEdit": {"status": status}}}}}


_FLOW_ROW = [
    {
        "sys_id": "f1",
        "sys_scope": "scope1",
        "sys_updated_on": "2026-06-30 10:18:44",
        "sys_mod_count": "5",
        "sys_updated_by": "someone",
    }
]


def _publish_auth(read_status, upsert_status, snapshot_resp=None):
    """make_request mock wired to the captured publish sequence."""
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/now/graphql"):
            q = kwargs.get("json", {}).get("query", "")
            return _ok(upsert_status if q.lstrip().startswith("mutation") else read_status)
        if method == "GET" and url.endswith("/api/now/processflow/flow/f1"):
            # editor re-read: the snapshot body source
            return _ok({"result": {"data": {"id": "f1", "name": "Test Flow"}}})
        if url.endswith("/api/now/ui/concoursepicker/current"):
            return _ok(
                {
                    "result": {
                        "currentUpdateSet": {"name": "My Update Set", "sysId": "us1"},
                        "currentApplication": {"name": "My App", "sysId": "scope1"},
                    }
                }
            )
        if "/snapshot" in url:
            if isinstance(snapshot_resp, Exception):
                raise snapshot_resp
            return snapshot_resp or _ok({"result": {"data": {"id": "f1"}}})
        return _ok()

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    return auth, calls


def _writes(calls):
    """Every non-GET request the mock saw (GraphQL queries excluded, mutations
    included) — the 'did it touch the server' assertion for the confirm gate."""
    out = []
    for method, url, kwargs in calls:
        if url.endswith("/api/now/graphql"):
            q = kwargs.get("json", {}).get("query", "")
            if q.lstrip().startswith("mutation"):
                out.append((method, url))
        elif method != "GET":
            out.append((method, url))
    return out


def test_publish_without_confirm_returns_plan_and_writes_nothing():
    # The confirm gate: no confirm=true → a read-only preview (plan + where the
    # change would be recorded) and ZERO writes — no lock upsert, no snapshot.
    auth, calls = _publish_auth(
        _safe_edit_status(canUserEdit=False, currentEditor=None),
        _safe_edit_status(canUserEdit=True, currentEditor=None),
    )
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=_FLOW_ROW):
        r = manage_flow_edit(_cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1"))
    assert r["success"] is False
    assert r["confirmation_required"] is True and r["experimental"] is True
    assert r["plan"]["flow_id"] == "f1"
    ctx = r["session_context"]
    assert ctx["current_update_set"] == "My Update Set"
    assert ctx["current_editor"] is None
    assert "scope_mismatch_warning" not in ctx  # app scope matches the flow's
    assert _writes(calls) == []


def test_publish_preview_flags_update_set_scope_mismatch():
    # The 'recorded in the wrong update set' fear: preview must warn when the
    # session's current application is NOT the flow's scope.
    auth, calls = _publish_auth(
        _safe_edit_status(canUserEdit=False, currentEditor=None),
        _safe_edit_status(canUserEdit=True, currentEditor=None),
    )
    other_scope_row = [dict(_FLOW_ROW[0], sys_scope="other_scope")]
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=other_scope_row):
        r = manage_flow_edit(_cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1"))
    assert r["confirmation_required"] is True
    assert "scope_mismatch_warning" in r["session_context"]
    assert _writes(calls) == []


def test_publish_confirmed_acquires_safe_edit_lock_then_snapshots():
    # Verified order (confirm=true): safeEdit read → safeEdit upsert(canUserEdit)
    # → flow re-read → POST /snapshot with the flow model as body →
    # create_version 'Activate/Publish'. Pin the sequence, scope param, and body.
    auth, calls = _publish_auth(
        _safe_edit_status(canUserEdit=False, currentEditor=None),
        _safe_edit_status(canUserEdit=True, currentEditor=None, clientFlowStale=None),
    )
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=_FLOW_ROW):
        r = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1", confirm=True)
        )
    assert r["success"] is True and r["published"] is True
    urls = [u for _, u, _ in calls]
    snap = next(i for i, u in enumerate(urls) if "/snapshot" in u)
    gql = [i for i, u in enumerate(urls) if u.endswith("/api/now/graphql")]
    assert len(gql) == 2 and max(gql) < snap  # lock fully acquired BEFORE snapshot
    assert calls[snap][2]["params"] == {"sysparm_transaction_scope": "scope1"}
    # the snapshot body IS the flow model — a bodyless snapshot 500s
    assert calls[snap][2]["json"]["id"] == "f1"
    upsert_q = calls[gql[1]][2]["json"]["query"]
    assert '"f1"' in upsert_q and '"2026-06-30 10:18:44"' in upsert_q
    assert any("create_version" in u for u in urls[snap + 1 :])


def test_publish_blocked_when_someone_else_is_editing_no_takeover():
    # currentEditor set → publish blocked even WITH confirm, and force must not
    # open a takeover path — there deliberately is none.
    for extra in ({}, {"force": True}):
        auth, calls = _publish_auth(
            _safe_edit_status(canUserEdit=False, currentEditor="other.user"),
            _safe_edit_status(canUserEdit=True, currentEditor=None),
        )
        with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=_FLOW_ROW):
            r = manage_flow_edit(
                _cfg(),
                auth,
                ManageFlowEditParams(action="publish", flow_id="f1", confirm=True, **extra),
            )
        assert r["success"] is False and r["current_editor"] == "other.user"
        assert _writes(calls) == []


def test_publish_aborts_when_lock_reports_stale_flow():
    # clientFlowStale from the upsert = the server's flow moved under us —
    # never compile over that; hand it to the human.
    auth, calls = _publish_auth(
        _safe_edit_status(canUserEdit=False, currentEditor=None),
        _safe_edit_status(canUserEdit=True, currentEditor=None, clientFlowStale=True),
    )
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=_FLOW_ROW):
        r = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1", confirm=True)
        )
    assert r["success"] is False and r["manual_publish_required"] is True
    assert not any("/snapshot" in u for _, u, _ in calls)


def test_publish_falls_back_to_ui_guidance_on_snapshot_failure():
    # Snapshot failure → manual_publish_required + the observed attempt attached,
    # never a silent bare 500.
    auth, _ = _publish_auth(
        _safe_edit_status(canUserEdit=False, currentEditor=None),
        _safe_edit_status(canUserEdit=True, currentEditor=None),
        snapshot_resp=RuntimeError("HTTP Error 500: Server Error"),
    )
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=_FLOW_ROW):
        r = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1", confirm=True)
        )
    assert r["success"] is False
    assert r["manual_publish_required"] is True
    assert r["ui_url"].endswith("/now/wsd/flow-designer/f1")
    assert "500" in r["publish_attempt"]["snapshot_error"]


def test_publish_falls_back_when_lock_not_granted():
    # upsert answered but canUserEdit stayed false → no snapshot attempt, UI guidance.
    auth, calls = _publish_auth(
        _safe_edit_status(canUserEdit=False, currentEditor=None),
        _safe_edit_status(canUserEdit=False, currentEditor=None),
    )
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", return_value=_FLOW_ROW):
        r = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1", confirm=True)
        )
    assert r["success"] is False and r["manual_publish_required"] is True
    assert not any("/snapshot" in u for _, u, _ in calls)


def test_toggle_active_uses_get_activate():
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url))
        return _ok()

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    r = _toggle_active(_cfg(), auth, "f1", "sc", activate=True)
    assert r == {"success": True, "action": "activate", "active": True}
    assert any(m == "GET" and u.endswith("/f1/activate") for m, u in calls)


def test_toggle_deactivate_uses_get_deactivate():
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_ok())
    r = _toggle_active(_cfg(), auth, "f1", "sc", activate=False)
    assert r["action"] == "deactivate" and r["active"] is False
    assert auth.make_request.call_args_list[0].args == (
        "GET",
        "https://test.service-now.com/api/now/processflow/flow/f1/deactivate",
    )


def test_activate_action_resolves_scope_and_toggles():
    auth = MagicMock(spec=AuthManager)
    with (
        patch(
            "servicenow_mcp.tools.flow_edit_tools._table_lookup",
            return_value=[{"sys_id": "f1", "sys_scope": "scope1"}],
        ),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._toggle_active",
            return_value={"success": True, "action": "activate", "active": True},
        ) as mock_toggle,
    ):
        r = manage_flow_edit(_cfg(), auth, ManageFlowEditParams(action="activate", flow_id="f1"))
    assert r["action"] == "activate"
    assert mock_toggle.call_args.kwargs["activate"] is True
