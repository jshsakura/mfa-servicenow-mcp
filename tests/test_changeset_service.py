"""Tests for the changeset service layer (services/changeset.py)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.services import changeset as cs_svc
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _auth(response_body=None):
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic test"}
    if response_body is not None:
        resp = MagicMock()
        resp.json.return_value = response_body
        resp.raise_for_status = MagicMock()
        auth.make_request.return_value = resp
    return auth


class TestCreate(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth({"result": {"sys_id": "abc", "name": "My CS", "application": "App1"}})
        result = cs_svc.create(_config(), auth, name="My CS", application="App1")
        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "abc")
        mock_inv.assert_called_once_with(table="sys_update_set")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success_with_optional_fields(self, mock_inv):
        auth = _auth({"result": {"sys_id": "abc", "name": "CS"}})
        result = cs_svc.create(_config(), auth, name="CS", application="App", description="d")
        self.assertTrue(result["success"])
        args, kwargs = auth.make_request.call_args
        self.assertEqual(kwargs["json"]["description"], "d")
        # sys_update_set has no `developer` column — probed live: a filter on it
        # returns every row, so the write was being discarded. The server
        # records the author in sys_created_by.
        self.assertNotIn("developer", kwargs["json"])

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Create failed")
        result = cs_svc.create(_config(), auth, name="CS", application="App")
        self.assertFalse(result["success"])
        self.assertIn("Create failed", result["message"])
        mock_inv.assert_not_called()


class TestUpdate(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth({"result": {"sys_id": "123", "name": "Updated", "state": "in_progress"}})
        result = cs_svc.update(_config(), auth, changeset_id="123", name="Updated")
        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "123")
        mock_inv.assert_called_once_with(table="sys_update_set")

    def test_no_fields_returns_error(self):
        auth = MagicMock()
        result = cs_svc.update(_config(), auth, changeset_id="123")
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No fields to update")
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.changeset.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"success": True, "preview": True}
        auth = MagicMock()
        result = cs_svc.update(
            _config(), auth, changeset_id="123", state="in_progress", dry_run=True
        )
        mock_preview.assert_called_once()
        self.assertTrue(result["preview"])
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Update failed")
        result = cs_svc.update(_config(), auth, changeset_id="123", name="X")
        self.assertFalse(result["success"])
        self.assertIn("Update failed", result["message"])


class TestPublishRetired(unittest.TestCase):
    def test_no_service_writes_a_state_that_does_not_exist(self):
        # sys_update_set.state is in progress, complete or ignore; never published.
        self.assertFalse(hasattr(cs_svc, "publish"))


class TestAddFileRetired(unittest.TestCase):
    def test_no_service_writes_a_caller_typed_entry(self):
        # A caller-typed payload in an update set is a hand-written deploy XML.
        self.assertFalse(hasattr(cs_svc, "add_file"))


if __name__ == "__main__":
    unittest.main()


def _http_error(status, body):
    import requests

    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    err = requests.exceptions.HTTPError(f"{status} Client Error", response=resp)
    return err


def test_a_refused_update_is_the_same_answer():
    auth = MagicMock()
    auth.get_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.side_effect = _http_error(403, {"error": {"message": "Forbidden"}})
    auth.make_request.return_value = resp
    out = cs_svc.update(
        _config(), auth, changeset_id="aaaa1111bbbb2222cccc3333dddd4444", state="ignore"
    )
    assert out["error"] == "WRITE_REFUSED" and out["server_message"] == "Forbidden"


def test_update_will_not_complete_a_set_and_points_at_commit():
    auth = MagicMock()
    out = cs_svc.update(_config(), auth, changeset_id=SET_ID_U, state="Complete")
    assert out["error"] == "USE_COMMIT" and "action='commit'" in out["next"][0]
    auth.make_request.assert_not_called()


SET_ID_U = "aaaa1111bbbb2222cccc3333dddd4444"


def test_a_404_on_write_is_not_called_gone():
    auth = MagicMock()
    auth.get_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.side_effect = _http_error(
        404,
        {
            "error": {
                "message": "No Record found",
                "detail": "Record doesn't exist or ACL restricts the record retrieval",
            }
        },
    )
    auth.make_request.return_value = resp
    out = cs_svc.update(_config(), auth, changeset_id=SET_ID_U, name="x")
    assert out["error"] == "NOT_FOUND_OR_HIDDEN" and "read ACL" in out["refused_by"]
    assert "ACL restricts" in out["server_message"]


# --- commit: what is shown and checked before a set is closed -----------------

SET_ID = "aaaa1111bbbb2222cccc3333dddd4444"


class _CommitServer:
    """The reads commit makes, and the PATCH it sends."""

    def __init__(self, **kw):
        self.set_row = {
            "sys_id": SET_ID,
            "name": "my_set",
            "state": "in progress",
            "application": "global",
            "is_default": "false",
            "description": "first line",
        }
        self.set_row.update(kw.get("set_row", {}))
        self.by_type = kw.get("by_type", {"Widget": 2})
        self.created = kw.get("created", {"alice": 2})
        self.updated = kw.get("updated", {"alice": 2})
        self.me = kw.get("me", "alice")
        self.current = kw.get("current", {"sys_id": "eeee5555ffff6666aaaa7777bbbb8888"})
        self.current_after = kw.get("current_after", {"sys_id": "default0000", "name": "Default"})
        self.patch_error = kw.get("patch_error")
        self.patches = []
        self.reads_current = 0

    def install(self, stack):
        stack.enter_context(
            patch.object(cs_svc, "sn_query_page", lambda *a, **k: ([self.set_row], 1))
        )
        stack.enter_context(patch.object(cs_svc, "invalidate_query_cache"))
        stack.enter_context(patch("servicenow_mcp.tools.sn_api.sn_count_by_group", self._count))
        stack.enter_context(
            patch("servicenow_mcp.tools.sn_api._authenticated_user", lambda *a, **k: self.me)
        )
        stack.enter_context(
            patch(
                "servicenow_mcp.tools.session_context_tools.get_current_update_set", self._current
            )
        )
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = self._request
        return auth

    def _count(self, config, auth, table, query, group_by):
        return {
            "type": self.by_type,
            "sys_created_by": self.created,
            "sys_updated_by": self.updated,
        }[group_by]

    def _current(self, *a, **k):
        self.reads_current += 1
        return self.current if self.reads_current == 1 else self.current_after

    def _request(self, method, url, json=None, headers=None):
        self.patches.append(json)
        resp = MagicMock()
        if self.patch_error:
            resp.raise_for_status.side_effect = self.patch_error
        else:
            resp.json.return_value = {"result": {"sys_id": SET_ID, "state": json["state"]}}
        return resp


def _commit(server, **kw):
    from contextlib import ExitStack

    with ExitStack() as stack:
        auth = server.install(stack)
        return cs_svc.commit(_config(), auth, changeset_id=SET_ID, **kw)


def test_commit_marks_complete_and_appends_to_the_description():
    srv = _CommitServer()
    out = _commit(srv, commit_message="ship it")
    assert out["success"] and out["written"] and out["changeset"]["state"] == "complete"
    assert srv.patches == [{"state": "complete", "description": "first line\n\nship it"}]
    assert out["preflight"]["entries"] == 2 and "other_authors" not in out["preflight"]


def test_dry_run_shows_the_contents_and_writes_nothing():
    srv = _CommitServer()
    out = _commit(srv, dry_run=True)
    assert out["dry_run"] and not out["written"] and srv.patches == []
    assert out["preflight"]["entries_by_type"] == {"Widget": 2}


def test_someone_elses_work_needs_their_name():
    srv = _CommitServer(updated={"alice": 1, "bob": 1})
    out = _commit(srv)
    assert out["error"] == "OTHER_AUTHORS_NOT_APPROVED" and srv.patches == []
    assert out["approvals_needed"]["confirm_other_author"] == "bob"
    ok = _commit(_CommitServer(updated={"alice": 1, "bob": 1}), confirm_other_author="bob")
    assert ok["success"] and ok["written"]


def test_an_unconfirmed_session_user_names_everyone():
    srv = _CommitServer(me=None)
    out = _commit(srv)
    assert out["error"] == "OTHER_AUTHORS_NOT_APPROVED" and srv.patches == []
    assert "alice" in out["approvals_needed"]["confirm_other_author"]


def test_uncountable_entries_stop_the_commit():
    srv = _CommitServer()
    srv.by_type = None
    out = _commit(srv)
    assert out["success"] is False and srv.patches == []


def test_a_default_set_is_never_completed():
    srv = _CommitServer(set_row={"is_default": "true", "name": "Default"})
    out = _commit(srv)
    assert out["success"] is False and srv.patches == [] and "Default" in out["message"]


def test_an_already_complete_set_is_left_alone():
    srv = _CommitServer(set_row={"state": "complete"})
    out = _commit(srv)
    assert out["success"] and not out["written"] and srv.patches == []


def test_completing_the_current_set_says_where_the_session_went():
    srv = _CommitServer(current={"sys_id": SET_ID})
    out = _commit(srv)
    assert out["current_update_set_now"]["name"] == "Default"
    assert any("CURRENT" in n for n in out["preflight"].get("notes", [])) or "next" in out


def test_an_empty_set_is_called_empty():
    out = _commit(_CommitServer(by_type={}, created={}, updated={}), dry_run=True)
    assert any("EMPTY" in n for n in out["notes"])


def _http_error(status, body):
    import requests

    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    return requests.exceptions.HTTPError(f"{status} Client Error", response=resp)


def test_a_refused_commit_carries_the_server_reason_and_where_to_look():
    srv = _CommitServer(
        patch_error=_http_error(
            403,
            {
                "error": {
                    "message": "Operation Failed",
                    "detail": "ACL Exception Update Failed due to security constraints",
                }
            },
        )
    )
    out = _commit(srv)
    assert out["success"] is False and out["error"] == "WRITE_REFUSED" and out["http_status"] == 403
    assert "ACL Exception" in out["server_message"]
    assert (
        "not a missing MCP capability" in out["refused_by"] and "business rule" in out["refused_by"]
    )
    assert any("get_table_automation" in step for step in out["next"])
    assert any("sys_security_acl_role" in step for step in out["next"])


def test_a_server_error_is_not_called_a_permission_refusal():
    out = _commit(_CommitServer(patch_error=_http_error(500, {"error": {"message": "boom"}})))
    assert "error" not in out and out["server_message"] == "boom"
