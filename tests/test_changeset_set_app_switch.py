"""A write to an update set happens inside the set's own app, then the session goes back.

Measured live: PATCH state=ignore on a scoped set from a Global session came back
403 (cross-scope ACL); after set_app to the set's app the same PATCH succeeded.
The fake below refuses a PATCH whose session app is not the set's, as the server
did — so a write that forgets to switch fails here, not only on an instance.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from servicenow_mcp.services import changeset as cs_svc
from servicenow_mcp.tools import session_context_tools as sct
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SET_ID = "aaaa1111bbbb2222cccc3333dddd4444"
SET_APP = "bbbb2222cccc3333dddd4444eeee5555"
GLOBAL_DEFAULT = "cccc3333dddd4444eeee5555ffff6666"
APP_DEFAULT = "dddd4444eeee5555ffff6666aaaa7777"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


class _Session:
    def __init__(self, *, start_app="global", switch_ok=True, restore_ok=True, remembered=None):
        self.app = start_app
        # The set each app comes back to when you switch into it.
        self.remembered = {"global": GLOBAL_DEFAULT, SET_APP: APP_DEFAULT}
        self.remembered.update(remembered or {})
        self.update_set = self.remembered[start_app]
        self.switch_ok = switch_ok
        self.restore_ok = restore_ok
        self.app_calls = []
        self.set_calls = []
        self.patches = []
        self.patch_status = None
        self.set_reads = 0

    def get_current(self, config, auth, endpoint):
        if endpoint == sct._APP_ENDPOINT:
            return {"sys_id": self.app, "name": "Global" if self.app == "global" else "My App"}
        return {"sys_id": self.update_set, "name": "Default"}

    def ensure_app(self, config, auth, app_id):
        self.app_calls.append(app_id)
        ok = self.switch_ok if app_id == SET_APP else self.restore_ok
        if not ok:
            return {"switched": False, "error": "not_applied"}
        if app_id == self.app:
            return {"switched": False, "already_current": True}
        self.app = app_id
        self.update_set = self.remembered[app_id]
        return {"switched": True, "success": True}

    def ensure_set(self, config, auth, set_id):
        self.set_calls.append(set_id)
        self.update_set = set_id
        return {"switched": True, "success": True}

    def query_page(self, *a, **k):
        self.set_reads += 1
        return (
            [
                {
                    "sys_id": SET_ID,
                    "name": "my_set",
                    "state": "in progress",
                    "application": {"value": SET_APP},
                    "is_default": "false",
                    "description": "",
                }
            ],
            1,
        )

    def request(self, method, url, json=None, headers=None):
        self.patches.append({"json": json, "app": self.app})
        resp = MagicMock()
        status = self.patch_status or (200 if self.app == SET_APP else 403)
        if status >= 400:
            err = Exception(f"HTTP Error {status}")
            err.response = MagicMock(status_code=status, text='{"error":{"message":"ACL"}}')
            resp.raise_for_status.side_effect = err
        else:
            resp.json.return_value = {"result": {"sys_id": SET_ID, **json}}
        return resp


def _run(session, fn, *, browser=True, **kw):
    with ExitStack() as stack:
        stack.enter_context(patch.object(sct, "_is_browser_auth", return_value=browser))
        stack.enter_context(patch.object(sct, "_get_current", session.get_current))
        stack.enter_context(patch.object(sct, "ensure_current_app", session.ensure_app))
        stack.enter_context(patch.object(sct, "ensure_current_update_set", session.ensure_set))
        stack.enter_context(patch.object(cs_svc, "sn_query_page", session.query_page))
        stack.enter_context(patch.object(cs_svc, "invalidate_query_cache"))
        stack.enter_context(
            patch("servicenow_mcp.tools.sn_api.sn_count_by_group", lambda *a, **k: {"alice": 1})
        )
        stack.enter_context(
            patch("servicenow_mcp.tools.sn_api._authenticated_user", lambda *a, **k: "alice")
        )
        stack.enter_context(
            patch.object(
                sct, "get_current_update_set", lambda *a, **k: {"sys_id": session.update_set}
            )
        )
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = session.request
        return fn(_config(), auth, changeset_id=SET_ID, **kw)


def test_update_from_another_app_writes_in_the_sets_app_and_goes_back():
    s = _Session()
    out = _run(s, cs_svc.update, state="ignore")
    assert out["success"], out
    assert s.patches == [{"json": {"state": "ignore"}, "app": SET_APP}]
    assert s.app_calls == [SET_APP, "global"]
    assert (s.app, s.update_set) == ("global", GLOBAL_DEFAULT)
    assert out["session_application"]["restored"] is True


def test_a_failed_switch_writes_nothing():
    s = _Session(switch_ok=False)
    out = _run(s, cs_svc.update, state="ignore")
    assert out["error"] == "APP_SWITCH_FAILED" and out["written"] is False
    assert s.patches == []


def test_a_failed_restore_is_said_out_loud_not_hidden_behind_the_success():
    s = _Session(restore_ok=False)
    out = _run(s, cs_svc.update, state="ignore")
    assert out["success"]  # the write itself landed
    back = out["session_application"]
    assert back["restored"] is False and "set_app" in back["next"][0]


def test_the_previous_update_set_is_put_back_when_the_app_switch_did_not():
    other = "eeee5555ffff6666aaaa7777bbbb8888"
    s = _Session(remembered={"global": other})
    s.update_set = GLOBAL_DEFAULT  # what the session really had before
    out = _run(s, cs_svc.update, state="ignore")
    assert out["session_application"]["restored"] is True
    assert s.set_calls == [GLOBAL_DEFAULT] and s.update_set == GLOBAL_DEFAULT


def test_a_refused_write_still_restores_the_session():
    s = _Session()
    s.patch_status = 403
    out = _run(s, cs_svc.update, state="ignore")
    assert not out["success"]
    assert s.app == "global" and out["session_application"]["restored"] is True


def test_already_in_the_sets_app_switches_nothing():
    s = _Session(start_app=SET_APP)
    out = _run(s, cs_svc.update, state="ignore")
    assert out["success"] and s.app_calls == [] and "session_application" not in out


def test_without_browser_auth_the_set_is_not_read_and_the_server_decides():
    s = _Session(start_app=SET_APP)
    out = _run(s, cs_svc.update, browser=False, state="ignore")
    assert out["success"] and s.set_reads == 0 and s.app_calls == []


def test_commit_from_another_app_completes_in_the_sets_app_and_goes_back():
    s = _Session()
    out = _run(s, cs_svc.commit)
    assert out["success"] and out["changeset"]["state"] == "complete", out
    assert s.patches[0]["app"] == SET_APP
    assert s.app == "global" and out["session_application"]["restored"] is True


def test_dry_run_names_the_switch_and_moves_nothing():
    s = _Session()
    with patch.object(cs_svc, "build_update_preview", return_value={"success": True}):
        out = _run(s, cs_svc.update, state="ignore", dry_run=True)
    assert "switches to the set's app" in out["session_switch"]
    assert s.app_calls == [] and s.patches == []
